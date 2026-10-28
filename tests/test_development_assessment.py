"""Current LangGraph batch: real Git/graph/ledgers, scripted provider and grader."""
import json
import importlib.util
import io
import os
from pathlib import Path
import threading
import unittest
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from langchain_core.messages import AIMessage
import test_development_checks as fixtures
from agent_workbench.coding.responses_transport import CallBudget
from agent_workbench.development.agent import run_agent
from agent_workbench.development.model import ModelUnknownError
from agent_workbench.development.service import DevelopmentTask
from agent_workbench.development.workspace import digest, encoded

try:
    from agent_workbench.development.assessment import (
        prepare_assessment, verify_assessment, run_assessment, grade_assessment)
except ImportError:
    prepare_assessment = verify_assessment = run_assessment = grade_assessment = None


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def tool(name, args):
    return AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': 'one'}])


class LedgerScript:
    """Only the external response boundary is scripted; paid-attempt ledger is real."""
    def __init__(self, task, cell, steps):
        self.steps = iter(steps)
        self.inputs = []
        self.budget = CallBudget(task._batch(cell['run_id'])/'model', cell['grant'])

    def remaining_calls(self):
        return self.budget.summary()['max_calls'] - self.budget.summary()['reserved']

    def complete(self, messages, decision_id, final_only=False):
        self.inputs.append(messages)
        identity = self.budget.reserve({'decision': decision_id})
        step = next(self.steps)
        self.budget.finish(identity, 'failed' if isinstance(step, Exception) else 'completed',
                           {'input_tokens': 100, 'output_tokens': 20,
                            'input_tokens_details': {'cached_tokens': 10}})
        if isinstance(step, Exception):
            raise step
        return step

    def summary(self):
        return self.budget.summary()


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(prepare_assessment, 'new LangGraph assessment is missing')
        fixtures.DevelopmentCheckTests.setUp(self)
        self.batch = self.root/'assessment'
        self.models = []

    def prepare(self):
        return prepare_assessment(self.root/'source', self.batch)

    def factory(self, task, cell):
        model = LedgerScript(task, cell, [AIMessage(content='已核对；证据与限制见候选。')])
        self.models.append(model)
        return model

    def run_batch(self, scope, factory=None, grader=None):
        with patch('agent_workbench.development.assessment.grade_cell',
                   side_effect=grader or (lambda task, cell, folder, tree=None:
                                        {'verdict': 'PASS', 'tree_hash': digest(tree)})):
            return run_assessment(self.batch, scope['scope_sha256'], '', model_factory=factory or self.factory)

    def test_prepare_seals_current_chat_three_fixed_grants_and_excludes_grader(self):
        scope = self.prepare()
        self.assertEqual(scope['max_calls'], 52)
        self.assertEqual([c['grant']['max_calls'] for c in scope['cells']], [18, 24, 10])
        self.assertEqual(scope['endpoint'], 'https://api.deepseek.com/chat/completions')
        self.assertEqual(scope['conservative_max_usd'], '1.8475392')
        self.assertEqual(scope['cost_cap_usd'], '1.90')
        self.assertEqual({c['knowledge_mode'] for c in scope['cells']}, {'off'})
        preview = read(self.batch/'outbound-preview.json')
        self.assertEqual(preview['authorization']['max_calls'], 52)
        self.assertNotIn('acceptance.py', json.dumps(preview))
        self.assertNotIn('expected ValueError', json.dumps(preview))
        self.assertEqual(verify_assessment(self.batch, scope['scope_sha256']), scope)

    def test_wrong_scope_never_claims_or_builds_a_model(self):
        self.prepare()
        with self.assertRaises(ValueError):
            run_assessment(self.batch, 'wrong', '', model_factory=self.factory)
        self.assertFalse((self.batch/'claimed').exists())
        self.assertEqual(self.models, [])

    def test_empty_explicit_key_does_not_fall_back_to_environment_or_claim_root(self):
        scope = self.prepare()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'ambient-key-must-not-be-used'}):
            with self.assertRaises(ValueError):
                run_assessment(self.batch, scope['scope_sha256'], '')
        self.assertFalse((self.batch/'claimed').exists())

    def test_request_preview_or_scope_edits_are_rejected_before_claim(self):
        scope = self.prepare()
        child = self.batch/'tasks'/scope['cells'][0]['cell_id']
        paths = [self.batch/'outbound-scope.json', self.batch/'outbound-preview.json',
                 child/'request.json', child/'runs'/scope['cells'][0]['run_id']/'outbound-preview.json',
                 child/'runs'/scope['cells'][0]['run_id']/'outbound-scope.json']
        for path in paths:
            original = path.read_bytes()
            value = read(path); value['tampered'] = True
            path.write_bytes(encoded(value))
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                verify_assessment(self.batch, scope['scope_sha256'])
            path.write_bytes(original)
        self.assertFalse((self.batch/'claimed').exists())

    def test_source_or_implementation_edits_invalidate_prepared_scope(self):
        scope = self.prepare()
        with patch('agent_workbench.development.assessment.implementation_identity', return_value='changed'):
            with self.assertRaises(ValueError): verify_assessment(self.batch, scope['scope_sha256'])
        source = self.root/'source/game-core/combat_core/v2/effects.py'
        source.write_text('VALUE = 2\n', encoding='utf-8')
        with self.assertRaises(ValueError): verify_assessment(self.batch, scope['scope_sha256'])

    def test_each_cell_runs_once_with_atomic_results_actual_model_usage_and_closed_unused_calls(self):
        scope = self.prepare(); result = self.run_batch(scope)
        self.assertEqual([r['run_state'] for r in result['results']], ['completed']*3)
        self.assertEqual(result['reserved_calls'], 3)
        self.assertEqual(result['unused_calls_closed'], 49)
        self.assertEqual(result['usage']['input_tokens'], 300)
        self.assertEqual(result['usage']['output_tokens'], 60)
        self.assertEqual(result['usage']['cached_input_tokens'], 30)
        self.assertEqual(len(self.models), 3)
        self.assertNotIn('acceptance.py', str([model.inputs for model in self.models]))
        self.assertNotIn('expected ValueError', str([model.inputs for model in self.models]))
        for cell in scope['cells']:
            self.assertTrue((self.batch/'model-results'/f"{cell['cell_id']}.json").exists())
            close = read(self.batch/'tasks'/cell['cell_id']/'runs'/cell['run_id']/'batch-close.json')
            self.assertTrue(close['closed'])
        with self.assertRaises(ValueError): self.run_batch(scope)
        self.assertEqual(len(self.models), 3)
        self.assertEqual((self.root/'source/game-core/combat_core/v2/effects.py').read_text(), 'VALUE = 1\n')

    def test_model_failure_counts_once_and_candidate_pass_does_not_mean_handoff_success(self):
        scope = self.prepare()
        def factory(task, cell):
            return LedgerScript(task, cell, [ModelUnknownError('offline timeout')])
        result = self.run_batch(scope, factory)
        self.assertEqual(result['reserved_calls'], 3)
        self.assertEqual(result['failed_calls'], 3)
        self.assertEqual([r['run_state'] for r in result['results']], ['partial']*3)
        self.assertTrue(all(r['grade']['verdict']=='PASS' for r in result['results']))
        self.assertTrue(all(not r['task_success'] for r in result['results']))

    def test_executable_candidate_pass_cannot_certify_wrong_final_explanation(self):
        scope=self.prepare()
        def factory(task,cell):
            return LedgerScript(task,cell,[AIMessage(content='护盾会阻止削韧，所以一定是Bug；未调查。')])
        result=self.run_batch(scope,factory)
        for row in result['results']:
            self.assertTrue(row['candidate_pass_and_handoff_completed'])
            self.assertEqual(row['semantic_review'],'pending')
            self.assertIsNone(row['task_success'])

    def test_unknown_model_attempts_keep_reservations_and_are_never_retried(self):
        scope = self.prepare()
        class UnknownModel(LedgerScript):
            def complete(self, messages, decision_id, final_only=False):
                self.budget.reserve({'decision': decision_id})
                raise ConnectionError('physical attempt outcome unknown')
        def factory(task, cell): return UnknownModel(task, cell, [])
        result = self.run_batch(scope, factory)
        self.assertEqual(result['reserved_calls'], 3)
        self.assertEqual(result['unknown_requests'], 3)
        self.assertEqual(result['usage']['missing_usage_records'], 3)
        self.assertEqual(result['unknown_cost_reserved_usd'], '0.1065888')
        self.assertEqual([r['run_state'] for r in result['results']], ['interrupted']*3)
        self.assertTrue(all(r['result']['error_type']=='ConnectionError' for r in result['results']))

    def test_model_construction_failure_closes_all_allowance_and_child_cannot_start_later(self):
        scope = self.prepare()
        def unavailable(task, cell): raise RuntimeError('offline constructor unavailable')
        result = self.run_batch(scope, unavailable)
        self.assertEqual(result['reserved_calls'], 0)
        self.assertEqual(result['unused_calls_closed'], 52)
        self.assertEqual([r['run_state'] for r in result['results']], ['not_started']*3)
        cell = scope['cells'][0]; task = DevelopmentTask(self.batch/'tasks'/cell['cell_id'])
        with self.assertRaises(ValueError):
            task.execute(cell['run_id'], cell['scope_sha256'], model=LedgerScript(task, cell, [AIMessage(content='unexpected later send')]))

    def test_model_close_failure_does_not_erase_completed_cell_receipts(self):
        scope = self.prepare()
        class CloseFailure(LedgerScript):
            def close(self): raise RuntimeError('offline close failure')
        def factory(task, cell): return CloseFailure(task, cell, [AIMessage(content='已交付。')])
        result = self.run_batch(scope, factory)
        self.assertEqual(result['reserved_calls'], 3)
        self.assertEqual([r['run_state'] for r in result['results']], ['completed']*3)
        self.assertTrue(all(r['result']['close_error_type']=='RuntimeError' for r in result['results']))

    def test_unreadable_token_ledger_keeps_saved_run_budget_and_marks_missing_usage(self):
        scope = self.prepare()
        class DamagedLedger(LedgerScript):
            def close(self): self.budget.database.write_bytes(b'unreadable after saved result')
        def factory(task, cell): return DamagedLedger(task, cell, [AIMessage(content='已交付。')])
        result = self.run_batch(scope, factory)
        self.assertEqual(result['reserved_calls'], 3)
        self.assertEqual(result['usage']['missing_usage_records'], 3)
        self.assertEqual(result['usage']['input_tokens'], 0)
        self.assertTrue(all(r['accounting_error_type']=='DatabaseError' for r in result['results']))

    def test_clarification_is_preserved_and_unused_allowance_is_closed(self):
        scope = self.prepare()
        def factory(task, cell):
            return LedgerScript(task, cell, [tool('ask_user', {'question': '应采用哪个上限？'})])
        result = self.run_batch(scope, factory)
        self.assertEqual([r['run_state'] for r in result['results']], ['waiting_user']*3)
        self.assertTrue(all(not r['handoff_completed'] for r in result['results']))
        self.assertIn('上限', result['results'][0]['result']['agent']['question'])
        task = DevelopmentTask(self.batch/'tasks'/scope['cells'][0]['cell_id'])
        with self.assertRaises(ValueError):
            task.execute(scope['cells'][0]['run_id'], scope['cells'][0]['scope_sha256'],
                         model=LedgerScript(task, scope['cells'][0], []), resume=True, answer='7')

    def test_waiting_checks_poll_without_model_calls_and_resume_same_child(self):
        scope = self.prepare(); launched = []; timers = []
        def factory(task, cell):
            def launch(request):
                launched.append(request['job_id'])
                timer = threading.Timer(.04, lambda: task.jobs.complete(request['job_id'],
                    {'exit_code': 0, 'tests': [{'name': 'rule', 'status': 'PASS'}]}))
                timers.append(timer); timer.start()
            task.jobs.launcher = launch
            model = LedgerScript(task, cell, [tool('start_check', {'check_set': 'rules'}),
                                              AIMessage(content='规则检查完成。')])
            self.models.append(model); return model
        def fast_graph(**kwargs):
            return run_agent(**kwargs, wait_seconds=0)
        with patch('agent_workbench.development.service.run_agent', side_effect=fast_graph), \
             patch('agent_workbench.development.assessment.CHECK_WAIT_SECONDS', 1), \
             patch('agent_workbench.development.assessment.CHECK_POLL_SECONDS', .01):
            result = self.run_batch(scope, factory)
        for timer in timers: timer.join()
        self.assertEqual(len(launched), 3)
        self.assertEqual(result['reserved_calls'], 6)
        self.assertEqual([r['run_state'] for r in result['results']], ['completed']*3)

    def test_unknown_or_not_started_checks_are_not_relaunched_or_autoanswered(self):
        for status in ('unknown', 'not_started'):
            with self.subTest(status=status):
                self.batch = self.root/status; scope = self.prepare(); launched = []
                def factory(task, cell):
                    def launch(request):
                        launched.append(request['job_id'])
                        method = task.jobs.mark_unknown if status=='unknown' else task.jobs.mark_not_started
                        method(request['job_id'], 'offline check unavailable')
                    task.jobs.launcher = launch
                    return LedgerScript(task, cell, [tool('start_check', {'check_set': 'rules'})])
                def fast_graph(**kwargs): return run_agent(**kwargs, wait_seconds=0)
                with patch('agent_workbench.development.service.run_agent', side_effect=fast_graph):
                    result = self.run_batch(scope, factory)
                self.assertEqual(len(launched), 3)
                self.assertEqual(result['reserved_calls'], 3)
                self.assertEqual([r['run_state'] for r in result['results']], ['waiting_checks']*3)

    def test_unavailable_grading_is_inconclusive_and_never_retries_unknown_physical_attempt(self):
        scope = self.prepare()
        attempts = []
        def unavailable(task, cell, folder, tree=None):
            attempts.append(cell['cell_id']); raise RuntimeError('offline grader unavailable')
        result = self.run_batch(scope, grader=unavailable)
        self.assertEqual([r['grade']['verdict'] for r in result['results']], ['INCONCLUSIVE']*3)
        with patch('agent_workbench.development.assessment.grade_cell', side_effect=AssertionError('must not rerun')):
            again = grade_assessment(self.batch)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(again['results'], result['results'])

    def test_existing_grade_is_preserved_and_grading_requires_batch_close(self):
        scope = self.prepare(); first = self.run_batch(scope)
        with patch('agent_workbench.development.assessment.grade_cell', side_effect=RuntimeError('unavailable')):
            self.assertEqual(grade_assessment(self.batch)['results'], first['results'])
        (self.batch/'batch-close.json').unlink()
        with patch('agent_workbench.development.assessment.grade_cell', side_effect=AssertionError('cannot grade active batch')):
            with self.assertRaises(ValueError): grade_assessment(self.batch)

    def test_concurrent_grading_cannot_overwrite_a_running_grading_attempt(self):
        scope = self.prepare(); entered = threading.Event(); release = threading.Event(); calls = []
        # Finish model execution first; the synchronization below tests two
        # graders, not how quickly three Git-backed model tasks can finish.
        with patch('agent_workbench.development.assessment.grade_assessment',return_value={}):
            self.run_batch(scope)
        def grader(task, cell, folder, tree=None):
            calls.append(cell['cell_id'])
            if len(calls)==1:
                entered.set(); release.wait(10)
            return {'verdict': 'FAIL'}
        with patch('agent_workbench.development.assessment.grade_cell',side_effect=grader),ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(grade_assessment,self.batch)
            self.assertTrue(entered.wait(10))
            try:
                with self.assertRaises(ValueError): grade_assessment(self.batch)
            finally:
                release.set()
            result = future.result(timeout=10)
        self.assertEqual(len(calls), 3)
        self.assertEqual([r['grade']['verdict'] for r in result['results']], ['FAIL']*3)

    def test_cli_prepare_verify_do_not_read_credentials_and_run_requires_exact_scope(self):
        path = Path(__file__).resolve().parents[1]/'scripts/assess_development.py'
        spec = importlib.util.spec_from_file_location('assessment_cli_test', path)
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        with patch.object(cli, '_execution_key', side_effect=AssertionError('offline action read credential')):
            with redirect_stdout(io.StringIO()):
                scope = cli.main(['prepare', '--data', str(self.batch), '--project', str(self.root/'source')])
                cli.main(['verify', '--data', str(self.batch), '--authorize-scope-sha256', scope['scope_sha256']])
                with self.assertRaises(ValueError):
                    cli.main(['run', '--data', str(self.batch), '--authorize-scope-sha256', 'wrong'])
        output = io.StringIO()
        def scripted_run(root, scope_hash, key):
            self.assertEqual(key, 'execution-secret-sentinel')
            with patch('agent_workbench.development.assessment.grade_cell', return_value={'verdict': 'PASS'}):
                return run_assessment(root, scope_hash, key, model_factory=self.factory)
        with patch.object(cli, '_execution_key', return_value='execution-secret-sentinel'), \
             patch.object(cli, 'run_assessment', side_effect=scripted_run), redirect_stdout(output):
            cli.main(['run', '--data', str(self.batch), '--authorize-scope-sha256', scope['scope_sha256']])
        self.assertNotIn('execution-secret-sentinel', output.getvalue())

    def test_frozen_final_candidate_tampering_is_rejected_before_grader(self):
        scope = self.prepare(); self.run_batch(scope)
        path = self.batch/'tasks'/scope['cells'][0]['cell_id']/'final-candidate.json'
        value = read(path); value['files'] = {}; path.write_bytes(encoded(value))
        with patch('agent_workbench.development.assessment.grade_cell', side_effect=AssertionError('must not grade')):
            with self.assertRaises(ValueError): grade_assessment(self.batch)


if __name__ == '__main__':
    unittest.main()
