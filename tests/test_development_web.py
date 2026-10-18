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
        with patch('agent_workbench.development.web.deepseek_sender') as sender:
            prepared=self.client.post(prefix+'/prepare',json={})
            self.assertEqual(prepared.status_code,200,prepared.text)
            scope=prepared.json()
            denied=self.client.post(prefix+'/run',json={'run_id':scope['run_id'],'scope_sha256':scope['scope_sha256']})
            self.assertEqual(denied.status_code,422)
            sender.assert_not_called()

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
        with patch('agent_workbench.development.web.threading.Thread',InlineThread),patch('agent_workbench.development.web.deepseek_sender') as sender:
            detail=bench.start(view['task_id'],'old-scope',scope['scope_sha256'])
            sender.return_value.assert_not_called()
        self.assertFalse((task._batch('old-scope')/'claimed').exists())
        self.assertEqual(detail['runs'][-1]['state'],'not_started')
        self.assertIn('重新准备',detail['runs'][-1]['error_message'])
        self.assertNotIn('never-expose',json.dumps(detail))

if __name__=='__main__':unittest.main()
