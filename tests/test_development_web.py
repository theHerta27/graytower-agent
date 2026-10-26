import unittest
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
from starlette.testclient import TestClient
import test_development_checks as fixtures
try:
    from agent_workbench.development.web import create_app,DEFAULT_GRANT
except ModuleNotFoundError:
    create_app=None


class DevelopmentWebTests(unittest.TestCase):
    def setUp(self):
        fixtures.DevelopmentCheckTests.setUp(self)
        self.assertIsNotNone(create_app)
        self.app=create_app(self.root/'web',api_key='never-expose-fixture-key',runtime_python='unused')
        self.client=TestClient(self.app,base_url='http://127.0.0.1:18790')
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)

    def create(self):
        r=self.client.post('/api/development/tasks',json={'project':str(self.root/'source'),'request':'修复新的规则问题'})
        self.assertEqual(r.status_code,200,r.text);return r.json()

    def test_real_project_new_request_and_initial_empty_diff(self):
        task=self.create()
        self.assertEqual(task['request'],'修复新的规则问题')
        self.assertEqual(task['changed_files'],[])
        self.assertEqual(task['model_state'],'not_started')
        self.assertNotIn('never-expose',self.client.get('/api/development/status').text)
        self.assertEqual(len(self.client.get('/api/development/tasks').json()['tasks']),1)

    def test_cross_origin_bad_paths_and_unknown_fields_are_rejected(self):
        self.assertEqual(self.client.post('/api/development/tasks',headers={'Origin':'https://evil.invalid'},json={}).status_code,403)
        task=self.create();prefix='/api/development/tasks/'+task['task_id']
        self.assertEqual(self.client.get(prefix+'/file',params={'path':'../secret'}).status_code,422)
        self.assertEqual(self.client.post(prefix+'/check',json={'check_set':'effects','command':'dir'}).status_code,422)
        self.assertEqual(self.client.get('/local-data/requests.json').status_code,404)

    def test_model_preview_is_free_and_run_needs_explicit_both_consents(self):
        from unittest.mock import patch
        task=self.create();prefix='/api/development/tasks/'+task['task_id']
        with patch('agent_workbench.development.service.ToolModel') as sender:
            prepared=self.client.post(prefix+'/prepare',json={})
            self.assertEqual(prepared.status_code,200,prepared.text)
            scope=prepared.json()
            denied=self.client.post(prefix+'/run',json={'run_id':scope['run_id'],'scope_sha256':scope['scope_sha256']})
            self.assertEqual(denied.status_code,422)
            sender.assert_not_called()

    def test_standard_preview_uses_reasoning_and_named_real_tasks_are_browsable(self):
        from agent_workbench.development.service import DevelopmentTask
        control=self.app.state.workbench.root/'tasks'/'configurable-cap-standard-off'
        DevelopmentTask.create(self.root/'source',control,'新的真实需求')
        listed=self.client.get('/api/development/tasks')
        self.assertEqual(listed.status_code,200,listed.text)
        prefix='/api/development/tasks/configurable-cap-standard-off'
        self.assertEqual(self.client.get(prefix).status_code,200)
        prepared=self.client.post(prefix+'/prepare',json={}).json()
        self.assertEqual(prepared['model_settings']['profile'],'reasoned')
        self.assertEqual(prepared['grant']['max_output_tokens'],16384)

    def test_human_edit_real_diff_and_discard_does_not_touch_source(self):
        task=self.create();prefix='/api/development/tasks/'+task['task_id']
        file=self.client.get(prefix+'/file',params={'path':'game-core/combat_core/v2/effects.py'}).json()
        result=self.client.post(prefix+'/edit',json={'operation_id':'manual1','path':file['path'],
              'expected_sha256':file['sha256'],'content':'VALUE = 9\n'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertIn('+VALUE = 9',result.json()['patch'])
        abandoned=self.client.post(prefix+'/discard',json={'tree_hash':result.json()['tree_hash']})
        self.assertEqual(abandoned.status_code,200,abandoned.text)
        self.assertEqual(abandoned.json()['workflow_state'],'discarded')
        self.assertEqual((self.root/'source/game-core/combat_core/v2/effects.py').read_text(),'VALUE = 1\n')

    def test_latest_run_uses_creation_order_and_only_its_events(self):
        view=self.create();task=self.app.state.workbench.task(view['task_id'])
        for run_id,stamp,state in [('user-zzzz',100,'completed'),('user-aaaa',200,'failed')]:
            folder=task._batch(run_id);folder.mkdir(parents=True)
            (folder/'outbound-scope.json').write_text('{}')
            os.utime(folder/'outbound-scope.json',ns=(stamp,stamp))
            (folder/'run-result.json').write_text(json.dumps({'state':state}))
            (folder/'runtime').mkdir()
            (folder/'runtime/events.jsonl').write_text(json.dumps({'params':{'item':{'type':'agentMessage','text':run_id}}})+'\n')
        detail=self.app.state.workbench.detail(view['task_id'])
        self.assertEqual([r['run_id'] for r in detail['runs']],['user-zzzz','user-aaaa'])
        self.assertEqual(detail['model_state'],'failed')
        self.assertEqual(detail['model_summary'],'user-aaaa')

    def test_active_run_does_not_mark_other_prepared_batches_running(self):
        view=self.create();bench=self.app.state.workbench;task=bench.task(view['task_id'])
        for run_id in ['older','active']:
            folder=task._batch(run_id);folder.mkdir(parents=True)
            (folder/'outbound-scope.json').write_text('{}')
        bench.active={view['task_id']:'active'}
        states={r['run_id']:r['state'] for r in bench.detail(view['task_id'])['runs']}
        self.assertEqual(states,{'older':'prepared','active':'running'})

    def test_successful_explicit_retry_does_not_show_old_preflight_error(self):
        view=self.create();bench=self.app.state.workbench;task=bench.task(view['task_id'])
        folder=task._batch('same-batch');folder.mkdir(parents=True)
        (folder/'outbound-scope.json').write_text('{}')
        (folder/'worker-error.json').write_text(json.dumps({'error_type':'OSError','message':'old environment error'}))
        (folder/'run-result.json').write_text(json.dumps({'state':'completed'}))
        detail=bench.detail(view['task_id'])
        self.assertEqual(detail['model_state'],'completed')
        self.assertIsNone(detail['model_error'])

    def test_stale_scope_failure_is_visible_without_claim_or_model_call(self):
        view=self.create();bench=self.app.state.workbench;task=bench.task(view['task_id'])
        scope=task.prepare('old-scope',DEFAULT_GRANT)
        name='game-core/combat_core/v2/effects.py'
        task.workspace.write_file('later',name,task.workspace.read_file(name)['sha256'],'VALUE = 8\n')
        bench.runtime_python=Path(sys.executable)
        class InlineThread:
            def __init__(self,target,**kwargs):self.target=target
            def start(self):self.target()
        with patch('agent_workbench.development.web.threading.Thread',InlineThread),patch('agent_workbench.development.service.ToolModel') as sender:
            detail=bench.start(view['task_id'],'old-scope',scope['scope_sha256'])
            sender.return_value.assert_not_called()
        self.assertFalse((task._batch('old-scope')/'claimed').exists())
        self.assertEqual(detail['runs'][-1]['state'],'not_started')
        self.assertIn('重新准备',detail['runs'][-1]['error_message'])
        self.assertNotIn('never-expose',json.dumps(detail))

    def test_new_default_reports_langgraph_without_sdk_and_memory_crud_is_project_bound(self):
        status=self.client.get('/api/development/status').json()
        self.assertEqual(status['engine'],'langgraph')
        self.assertTrue(status['runtime_available'])
        task=self.create();prefix='/api/development/tasks/'+task['task_id']
        saved=self.client.post(prefix+'/memories',json={'action':'add','content':'资源参数非法时必须先拒绝。','kind':'constraint','version':'*'})
        self.assertEqual(saved.status_code,200,saved.text)
        listed=self.client.get(prefix+'/memories').json()
        self.assertEqual(len(listed['memories']),1)
        item=listed['memories'][0];self.assertEqual(item['status'],'confirmed')
        self.assertEqual(self.client.post(prefix+'/memories',json={'action':'update','id':item['id'],'content':'资源参数非法不能改变状态。'}).status_code,200)
        self.assertEqual(self.client.post(prefix+'/memories',json={'action':'delete','id':item['id']}).status_code,200)
        self.assertEqual(self.client.get(prefix+'/memories').json()['memories'],[])
        invalid=self.client.post(prefix+'/memories',json={'action':'add','version':'*'})
        self.assertEqual(invalid.status_code,422,invalid.text)

    def test_web_pause_and_resume_use_saved_run_and_do_not_call_sdk(self):
        from test_development_agent import ScriptModel,call
        from langchain_core.messages import AIMessage
        task=self.create();prefix='/api/development/tasks/'+task['task_id']
        scope=self.client.post(prefix+'/prepare',json={}).json()
        model=ScriptModel([call('ask_user',{'question':'应改为多少？'},'ask'),AIMessage(content='收到，目标7。')])
        class InlineThread:
            def __init__(self,target,**kwargs):self.target=target
            def start(self):self.target()
        with patch.object(self.app.state.workbench,'launch',side_effect=lambda work:work()),patch('agent_workbench.development.service.ToolModel',return_value=model):
            started=self.client.post(prefix+'/run',json={'run_id':scope['run_id'],'scope_sha256':scope['scope_sha256'],'accept_data':True,'accept_cost':True})
            self.assertEqual(started.status_code,200,started.text)
            self.assertEqual(started.json()['model_state'],'waiting_user',started.json()['runs'])
            self.assertEqual(started.json()['resumable_run']['question'],'应改为多少？')
            result=self.client.post(prefix+'/resume',json={'run_id':scope['run_id'],'scope_sha256':scope['scope_sha256'],'answer':'目标7'})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['model_state'],'completed')
            self.assertEqual(result.json()['model_summary'],'收到，目标7。')
            self.assertEqual(len(model.saved),2)

    def test_scope_identity_belongs_to_selected_run_not_directory_enumeration(self):
        view=self.create();bench=self.app.state.workbench;task=bench.task(view['task_id'])
        for name,stamp in [('aaa-new',200),('zzz-old',100)]:
            folder=task._batch(name);folder.mkdir(parents=True)
            (folder/'claimed').mkdir()
            (folder/'outbound-scope.json').write_text(json.dumps({'schema':'development-langgraph-v1','created_at_ns':stamp,'scope_sha256':'scope-'+name}))
            (folder/'run-result.json').write_text(json.dumps({'state':'waiting_user','closed':False,'agent':{'question':name}}))
        value=bench.detail(view['task_id'])
        self.assertEqual(value['resumable_run']['scope_sha256'],'scope-aaa-new')

    def test_later_preview_cannot_hide_or_bypass_unfinished_original_run(self):
        from test_development_agent import ScriptModel,call
        view=self.create();bench=self.app.state.workbench;task=bench.task(view['task_id'])
        a=task.prepare('original',DEFAULT_GRANT);b=task.prepare('later-preview',DEFAULT_GRANT)
        model=ScriptModel([call('ask_user',{'question':'目标是多少？'},'ask')])
        task.execute('original',a['scope_sha256'],model=model)
        self.assertEqual(bench.detail(view['task_id'])['resumable_run']['run_id'],'original')
        with self.assertRaises(ValueError):task.execute('later-preview',b['scope_sha256'],model=model)
        self.assertFalse((task._batch('later-preview')/'claimed').exists())

    def test_question_is_visible_from_checkpoint_when_result_publication_was_lost(self):
        from test_development_agent import ScriptModel,call
        view=self.create();bench=self.app.state.workbench;task=bench.task(view['task_id'])
        a=task.prepare('original',DEFAULT_GRANT)
        task.execute('original',a['scope_sha256'],model=ScriptModel([call('ask_user',{'question':'需要多少？'},'ask')]))
        (task._batch('original')/'run-result.json').unlink()
        detail=bench.detail(view['task_id'])
        self.assertEqual(detail['resumable_run']['question'],'需要多少？')
        self.assertEqual(detail['resumable_run']['status'],'waiting_user')

if __name__=='__main__':unittest.main()
