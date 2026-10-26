import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_development_checks as fixtures
try:
    from agent_workbench.development.service import DevelopmentTask
except ModuleNotFoundError:
    DevelopmentTask=None


class DevelopmentServiceTests(unittest.TestCase):
    def setUp(self):
        fixtures.DevelopmentCheckTests.setUp(self)
        self.assertIsNotNone(DevelopmentTask)
        (self.workspace.control/'request.json').write_text(json.dumps({'request':'修复规则边界，不改原项目。'}),encoding='utf-8')
        self.task=DevelopmentTask(self.workspace.control)
        self.grant={'max_calls':2,'max_input_bytes':150000,'max_output_tokens':512,'cost_cap_usd':'0',
                    'input_usd_per_million':'0','cached_input_usd_per_million':'0','output_usd_per_million':'0'}

    def test_new_task_has_real_baseline_request_and_unverified_state(self):
        view=self.task.summary()
        self.assertIn('修复',view['request'])
        self.assertEqual(view['changed_files'],[])
        self.assertEqual(view['validation'],'尚未验证')

    def test_prepared_model_settings_drift_stops_before_claim_or_model_call(self):
        from test_development_agent import ScriptModel
        from langchain_core.messages import AIMessage
        scope=self.task.prepare('settings',self.grant);model=ScriptModel([AIMessage(content='must not run')])
        with patch('agent_workbench.development.service.model_settings',return_value={'profile':'changed'}):
            with self.assertRaises(ValueError):self.task.execute('settings',scope['scope_sha256'],model=model)
        self.assertEqual(model.saved,{})

    def test_partial_pass_is_not_full_rules_and_edit_invalidates_old_result(self):
        job=self.jobs.start(self.workspace,'effects')
        self.jobs.complete(job['job_id'],{'exit_code':0,'tests':[{'name':'a','status':'PASS'}]})
        self.task.jobs=self.jobs
        self.assertEqual(self.task.summary()['validation'],'指定检查已通过，尚未完成完整规则回归')
        before=self.workspace.read_file('game-core/combat_core/v2/effects.py')
        self.workspace.write_file('rev',before['path'],before['sha256'],'VALUE = 2\n')
        self.assertEqual(self.task.summary()['validation'],'尚未验证')

    def test_preparation_freezes_scope_and_exact_authorization_is_required(self):
        scope=self.task.prepare('r1',self.grant)
        self.assertEqual(scope['candidate_tree_hash'],self.workspace.inspect()['tree_hash'])
        preview=json.loads((self.workspace.control/'runs/r1/outbound-preview.json').read_text(encoding='utf-8'))
        self.assertIn('VALUE = 1',preview['files'][0]['text'])
        with self.assertRaises(ValueError):
            self.task.execute('r1','wrong',Path('unused'),Path('unused'),sender=lambda body:b'')
        self.assertFalse((self.workspace.control/'runs/r1/claimed').exists())

    def test_changes_after_prepare_prevent_model_execution(self):
        scope=self.task.prepare('r1',self.grant)
        before=self.workspace.read_file('game-core/combat_core/v2/effects.py')
        self.workspace.write_file('rev',before['path'],before['sha256'],'VALUE = 2\n')
        with self.assertRaises(ValueError):
            self.task.execute('r1',scope['scope_sha256'],Path('unused'),Path('unused'),sender=lambda body:b'')

    def test_execution_closes_batch_and_never_automatically_repeats(self):
        scope=self.task.prepare('r1',self.grant)
        from test_development_agent import ScriptModel
        from langchain_core.messages import AIMessage
        model=ScriptModel([AIMessage(content='已调查，未修改。')],limit=2)
        result=self.task.execute('r1',scope['scope_sha256'],model=model)
        self.assertEqual(len(model.saved),1)
        self.assertEqual(result['state'],'completed')
        self.assertTrue(result['closed'])
        with self.assertRaises(ValueError):
            self.task.execute('r1',scope['scope_sha256'],model=model)

    def test_new_scope_uses_framework_and_frozen_project_memory(self):
        self.task.memory.add(self.workspace.metadata['project'],'规则边界：非法参数应先拒绝再改变状态。',
            source='user',version='*',status='confirmed')
        scope=self.task.prepare('graph',self.grant)
        self.assertEqual(scope['schema'],'development-langgraph-v1')
        self.assertEqual(scope['endpoint'],'https://api.deepseek.com/chat/completions')
        preview=json.loads((self.task._batch('graph')/'outbound-preview.json').read_text(encoding='utf-8'))
        self.assertEqual(len(preview['memories']),1)
        self.task.memory.update(self.workspace.metadata['project'],preview['memories'][0]['id'],content='规则已变化')
        with self.assertRaises(ValueError):
            self.task.execute('graph',scope['scope_sha256'],model=object())
        self.assertFalse((self.task._batch('graph')/'claimed').exists())

    def test_clarification_resumes_with_original_scope_and_budget(self):
        from test_development_agent import ScriptModel,call
        from langchain_core.messages import AIMessage
        scope=self.task.prepare('pause',self.grant)
        model=ScriptModel([call('ask_user',{'question':'目标是多少？'},'ask'),AIMessage(content='收到，目标为7。')],limit=3)
        first=self.task.execute('pause',scope['scope_sha256'],model=model)
        self.assertEqual(first['state'],'waiting_user')
        self.assertFalse(first['closed'])
        result=self.task.execute('pause',scope['scope_sha256'],model=model,resume=True,answer='目标7')
        self.assertEqual(result['state'],'completed')
        self.assertTrue(result['closed'])
        self.assertEqual(len(model.saved),2)

    def test_long_valid_request_can_prepare_and_pending_run_cannot_start_another(self):
        from test_development_agent import ScriptModel,call
        self.task.request='资源规则调查。'*700
        scope=self.task.prepare('long',self.grant)
        model=ScriptModel([call('ask_user',{'question':'目标？'},'ask')],limit=3)
        self.task.execute('long',scope['scope_sha256'],model=model)
        with self.assertRaises(ValueError):self.task.prepare('other',self.grant)

    def test_discarded_task_cannot_call_model_from_cli_service(self):
        scope=self.task.prepare('r1',self.grant)
        (self.task.root/'discarded.json').write_text('{}')
        with self.assertRaises(ValueError):self.task.execute('r1',scope['scope_sha256'],model=object())
        self.assertFalse((self.task._batch('r1')/'claimed').exists())

    def test_export_contains_actual_diff_and_leaves_source_alone(self):
        before=self.workspace.read_file('game-core/combat_core/v2/effects.py')
        self.workspace.write_file('rev',before['path'],before['sha256'],'VALUE = 2\n')
        exported=self.task.export()
        self.assertIn('+VALUE = 2',Path(exported['patch']).read_text(encoding='utf-8'))
        self.assertEqual((self.root/'source'/before['path']).read_text(encoding='utf-8'),'VALUE = 1\n')


if __name__=='__main__':unittest.main()
