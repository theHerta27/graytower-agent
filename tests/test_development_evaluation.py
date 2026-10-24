import json
from pathlib import Path
import unittest
import test_development_checks as fixtures
try:
    from agent_workbench.development.evaluation import prepare_pilot,verify_pilot,run_pilot,grader_payload
except ImportError:
    prepare_pilot=verify_pilot=run_pilot=grader_payload=None


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(prepare_pilot,'真实任务对照入口尚未实现')
        fixtures.DevelopmentCheckTests.setUp(self)

    def test_prepared_three_single_agent_tasks_exclude_private_grader(self):
        scope=prepare_pilot(self.root/'source',self.root/'pilot')
        self.assertEqual(len(scope['cells']),3)
        self.assertEqual({cell['profile'] for cell in scope['cells']},{'standard'})
        self.assertEqual(len({c['baseline_commit'] for c in scope['cells']}),1)
        preview=(self.root/'pilot/outbound-preview.json').read_text(encoding='utf-8')
        self.assertNotIn('expected ValueError',preview)
        self.assertNotIn('acceptance.py',preview)
        self.assertEqual(scope['max_calls'],48)
        self.assertEqual([cell['grant']['max_calls'] for cell in scope['cells']],[16,24,8])
        self.assertLessEqual(float(scope['conservative_max_usd']),float(scope['cost_cap_usd']))
        verify_pilot(self.root/'pilot',scope['scope_sha256'])

    def test_scope_change_and_wrong_authorization_never_call_sender(self):
        from unittest.mock import Mock
        scope=prepare_pilot(self.root/'source',self.root/'pilot');sender=Mock()
        with self.assertRaises(ValueError):run_pilot(self.root/'pilot','wrong',Path('unused'),sender=sender)
        self.assertFalse((self.root/'pilot/claimed').exists());sender.assert_not_called()
        path=self.root/'pilot/tasks/resource-atomicity-standard/request.json'
        value=json.loads(path.read_text(encoding='utf-8'));value['request']='different'
        path.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaises(ValueError):verify_pilot(self.root/'pilot',scope['scope_sha256'])

    def test_independent_payload_uses_frozen_candidate_outside_model_catalog(self):
        payload=grader_payload(self.workspace,'resource-atomicity')
        self.assertEqual(payload['identity']['tree_hash'],self.workspace.inspect()['tree_hash'])
        self.assertEqual(payload['identity']['check_set'],'diagnostic')
        self.assertIn('independent-check',payload['diagnostic'])

    def test_known_failure_is_not_downgraded_by_missing_regression(self):
        from unittest.mock import patch
        from agent_workbench.development.evaluation import grade_cell
        from agent_workbench.development.service import DevelopmentTask
        (self.workspace.control/'request.json').write_text(json.dumps({'request':'test'}))
        task=DevelopmentTask(self.workspace.control)
        independent={'exit_code':0,'log':json.dumps({'checks':[{'name':'requirement','status':'FAIL'}]})}
        with patch('agent_workbench.development.evaluation.execute_once',side_effect=[independent,{'exit_code':124}]):
            grade=grade_cell(task,{'task_id':'resource-atomicity'},self.root/'grade')
        self.assertEqual(grade['verdict'],'FAIL')

    def test_changed_final_snapshot_cannot_be_credited_to_model(self):
        from unittest.mock import patch
        from agent_workbench.development.evaluation import grade_pilot
        from agent_workbench.development.service import DevelopmentTask
        root=self.root/'pilot';scope=prepare_pilot(self.root/'source',root);cell=scope['cells'][0]
        task=DevelopmentTask(root/'tasks'/cell['cell_id']);original=task.workspace.inspect()['tree_hash']
        name='game-core/combat_core/v2/effects.py'
        task.workspace.write_file('later',name,task.workspace.read_file(name)['sha256'],'VALUE = 99\n')
        (task.root/'final-candidate.json').write_text(json.dumps(task.workspace.snapshot()))
        (root/'model-results.json').write_text(json.dumps([{**cell,'final_tree_hash':original,
            'budget':{'known_cost_usd':'0','unknown':0},
            'result':{'runtime':{'after_tree_hash':original}}}]))
        with patch('agent_workbench.development.evaluation.grade_cell',return_value={'verdict':'PASS'}) as grader:
            with self.assertRaises(ValueError):grade_pilot(root)
            grader.assert_not_called()

    def test_unknown_runtime_receipt_is_preserved_without_retry(self):
        from unittest.mock import patch,Mock
        from agent_workbench.development.evaluation import read
        root=self.root/'pilot';scope=prepare_pilot(self.root/'source',root)
        def unknown(task,run_id,*args,**kwargs):
            (task._batch(run_id)/'run-result.json').write_text(json.dumps({'state':'unknown','error_type':'RuntimeError'}))
            raise RuntimeError('timeout')
        sender=Mock()
        with patch('agent_workbench.development.evaluation.DevelopmentTask.execute',unknown),patch('agent_workbench.development.evaluation.grade_pilot',return_value={}):
            run_pilot(root,scope['scope_sha256'],Path('unused'),sender=sender)
        self.assertEqual([r['runtime_state'] for r in read(root/'model-results.json')],['unknown']*3)
        with self.assertRaises(ValueError):run_pilot(root,scope['scope_sha256'],Path('unused'),sender=sender)
        sender.assert_not_called()
