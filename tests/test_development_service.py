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
        with patch('agent_workbench.development.service.run_runtime',return_value={'status':'completed'}) as runtime:
            result=self.task.execute('r1',scope['scope_sha256'],Path('unused'),Path('unused'),sender=lambda body:b'')
        self.assertEqual(runtime.call_count,1)
        self.assertEqual(result['state'],'completed')
        self.assertTrue(result['closed'])
        with self.assertRaises(ValueError):
            self.task.execute('r1',scope['scope_sha256'],Path('unused'),Path('unused'),sender=lambda body:b'')

    def test_export_contains_actual_diff_and_leaves_source_alone(self):
        before=self.workspace.read_file('game-core/combat_core/v2/effects.py')
        self.workspace.write_file('rev',before['path'],before['sha256'],'VALUE = 2\n')
        exported=self.task.export()
        self.assertIn('+VALUE = 2',Path(exported['patch']).read_text(encoding='utf-8'))
        self.assertEqual((self.root/'source'/before['path']).read_text(encoding='utf-8'),'VALUE = 1\n')


if __name__=='__main__':unittest.main()
