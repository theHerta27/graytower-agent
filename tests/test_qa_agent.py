"""Business verdicts and receipt recovery, with an explicitly scripted model."""
import tempfile
import unittest
import json
from pathlib import Path

from pydantic import ValidationError

from agent_workbench.jobs import JobStore
from agent_workbench.qa import Decision, VerificationAgent


class ScriptedModel:
    def __init__(self, actions):
        self.actions = iter(actions)
    def complete(self, messages, schema):
        return next(self.actions)


class BoundedScriptedModel(ScriptedModel):
    def __init__(self, actions, calls):
        super().__init__(actions)
        self.remaining = calls
        self.inputs = []
    def remaining_calls(self):
        return self.remaining
    def complete(self, messages, schema):
        self.inputs.append(messages)
        if self.remaining <= 0:
            raise RuntimeError('fixture called after model budget exhaustion')
        self.remaining -= 1
        return super().complete(messages, schema)


class FixtureTools:
    """Only tool/game execution is replaced; graph, SQLite and verdicts are real."""
    def __init__(self, store):
        self.store = store
    async def call(self, name, args):
        if name == 'inspect_candidate':
            return {'manifest_hash': 'a'*64, 'diff': [{'path': 'skills.breaker_skill.multiplier', 'before': 1.4, 'after': 1.7}], 'validation': {'valid': True}}
        if name == 'run_simulation':
            return self.store.run(args['request_id'], {k: args[k] for k in ('seeds','policies')}, 2*len(args['seeds'])*len(args['policies']), lambda: {
                'manifest_hash': 'a'*64, 'structural_verdict': 'PASS', 'overall_verdict': 'INCONCLUSIVE',
                'metrics': {'balanced': {'pairs': 1}}, 'trace_refs': [], 'limitations': ['样本只支持描述']})
        raise ValueError(name)


class DecisionContractTests(unittest.TestCase):
    def test_provider_schema_enumerates_strategy_choices(self):
        from agent_workbench.models import ModelGateway
        preview = ModelGateway().preview([{'role': 'user', 'content': 'schema inspection only'}], Decision)
        policies = preview['schema']['properties']['policies']
        self.assertEqual(policies['items'].get('enum'), ['balanced', 'survival', 'basic_only'])
        for policy in ('balanced', 'survival', 'basic_only'):
            decision = Decision.model_validate({'action': 'simulate', 'reason': 'one paired seed',
                                               'seeds': [7], 'policies': [policy]})
            self.assertEqual(decision.policies, [policy])

    def test_versions_and_unknown_values_are_rejected_as_strategies(self):
        for policies in (['baseline', 'candidate'], ['balanced', 'candidate'], ['aggressive'], [True]):
            with self.subTest(policies=policies), self.assertRaises(ValidationError):
                Decision.model_validate({'action': 'simulate', 'reason': 'invalid strategy fixture',
                                         'seeds': [7], 'policies': policies})


class QaAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = JobStore(self.root)
        self.store.confirm('a'*64)
        self.store.admit('qa-test', 'a'*64, '检查改后战斗更快吗', 4)

    async def test_model_cannot_promote_small_sample_to_pass(self):
        model = ScriptedModel([
            {'action': 'simulate', 'reason': '先看一对', 'seeds': [7], 'policies': ['balanced']},
            {'action': 'finish', 'reason': 'PASS! 保证总体更快'}])
        result = await VerificationAgent(self.root, model, FixtureTools(self.store)).run('qa-test')
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['structural_verdict'], 'PASS')
        self.assertEqual(result['charged_battles'], 2)
        self.assertEqual(len(result['jobs']), 1)
        # A completed result must need neither another model response nor a tool call.
        again = await VerificationAgent(self.root, ScriptedModel([]), FixtureTools(self.store)).run('qa-test')
        self.assertEqual(again, result)

    async def test_no_experiment_never_becomes_pass(self):
        result = await VerificationAgent(self.root, ScriptedModel([{'action':'finish','reason':'缺目标'}]), FixtureTools(self.store)).run('qa-test')
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['charged_battles'], 0)

    async def test_each_decision_uses_current_battle_and_model_budgets(self):
        model = BoundedScriptedModel([
            {'action': 'simulate', 'reason': '执行已批准的4场', 'seeds': [7, 11], 'policies': ['balanced']},
            {'action': 'finish', 'reason': '仅描述已有样本'}], calls=2)
        result = await VerificationAgent(self.root, model, FixtureTools(self.store)).run('qa-test')
        first, second = [json.loads(messages[1]['content']) for messages in model.inputs]
        self.assertEqual(first['request']['charged_battles'], 0)
        self.assertEqual(second['request']['charged_battles'], 4, 'the second decision must see the persisted charge')
        self.assertEqual(first['budget']['remaining_battles'], 4)
        self.assertEqual(second['budget']['remaining_battles'], 0)
        self.assertEqual(first['budget']['remaining_model_calls'], 2)
        self.assertEqual(second['budget']['remaining_model_calls'], 1)
        self.assertTrue(first['budget']['new_simulation_allowed'])
        self.assertFalse(second['budget']['new_simulation_allowed'])
        self.assertEqual(result['charged_battles'], 4)
        self.assertEqual(result['errors'], [])

    async def test_exhausted_model_budget_concludes_without_call_or_fabricated_decision(self):
        from agent_workbench.models import ModelGateway
        audit = self.root / 'calls.jsonl'
        audit.write_text(json.dumps({'call_id': 'unknown-after-exit', 'status': 'reserved'}) + '\n', encoding='utf-8')
        before = audit.read_bytes()
        model = ModelGateway(max_calls=1, audit_path=audit)
        result = await VerificationAgent(self.root, model, FixtureTools(self.store)).run('qa-test')
        self.assertEqual(result.get('stop_reason'), 'model_budget_exhausted')
        self.assertTrue(result['model_budget_exhausted'])
        self.assertEqual(result['agent_decision_note'], '', 'budget stop must not impersonate a model finish decision')
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['charged_battles'], 0)
        self.assertEqual(result['jobs'], [])
        self.assertEqual(model.calls, [])
        self.assertEqual(audit.read_bytes(), before)

    async def test_budget_stop_preserves_last_model_choice_and_completed_evidence(self):
        model = BoundedScriptedModel([
            {'action': 'simulate', 'reason': '先观察4场', 'seeds': [7, 11], 'policies': ['balanced']}], calls=1)
        result = await VerificationAgent(self.root, model, FixtureTools(self.store)).run('qa-test')
        self.assertEqual(len(model.inputs), 1, 'exhaustion must not invoke another model decision')
        self.assertEqual(result.get('stop_reason'), 'model_budget_exhausted')
        self.assertEqual(result['agent_decision_note'], '先观察4场')
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['charged_battles'], 4)
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')

    async def test_ignored_battle_budget_stays_visible_before_model_budget_stop(self):
        model = BoundedScriptedModel([
            {'action': 'simulate', 'reason': '先观察4场', 'seeds': [7, 11], 'policies': ['balanced']},
            {'action': 'simulate', 'reason': '错误追加另一对', 'seeds': [17], 'policies': ['survival']}], calls=2)
        result = await VerificationAgent(self.root, model, FixtureTools(self.store)).run('qa-test')
        self.assertEqual(len(model.inputs), 2, 'the second actual model choice must not be forced to finish')
        self.assertEqual(result['stop_reason'], 'model_budget_exhausted')
        self.assertEqual(result['agent_decision_note'], '错误追加另一对')
        self.assertEqual(result['charged_battles'], 4)
        self.assertEqual(len(result['jobs']), 1, 'the authoritative store must refuse new work after all four battles')
        self.assertEqual(len(result['errors']), 1)
        self.assertIn('battle budget', result['errors'][0])
        self.assertNotIn('model call failed', result['errors'][0])
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')

    async def test_invalid_model_ledger_stops_without_impersonating_provider_failure(self):
        from agent_workbench.models import ModelGateway
        audit = self.root / 'calls.jsonl'
        audit.write_text('{corrupted ledger', encoding='utf-8')
        model = ModelGateway(max_calls=8, audit_path=audit)
        result = await VerificationAgent(self.root, model, FixtureTools(self.store)).run('qa-test')
        self.assertEqual(result['stop_reason'], 'model_budget_unavailable')
        self.assertFalse(result['model_budget_exhausted'])
        self.assertEqual(result['agent_decision_note'], '')
        self.assertEqual(result['charged_battles'], 0)
        self.assertEqual(len(result['errors']), 1)
        self.assertIn('model budget unavailable', result['errors'][0])
        self.assertEqual(model.calls, [])
        self.assertEqual(audit.read_text(encoding='utf-8'), '{corrupted ledger')

    async def test_unavailable_candidate_inspection_delivers_durable_inconclusive_without_model(self):
        class ForbiddenModel:
            calls = 0
            def complete(self, messages, schema):
                self.calls += 1
                raise AssertionError('inspection failure must not spend a model call')

        class UnavailableInspection:
            def __init__(self):
                self.calls = []
            async def call(self, name, args):
                self.calls.append((name, args))
                if name == 'inspect_candidate':
                    raise ConnectionError('candidate inspection unavailable')
                raise AssertionError('inspection failure must not launch another tool')

        model, tools = ForbiddenModel(), UnavailableInspection()
        try:
            result = await VerificationAgent(self.root, model, tools).run('qa-test')
        except ConnectionError as exc:
            self.fail(f'admitted inspection failure must produce an uncertainty report: {exc}')
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['structural_verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['charged_battles'], 0)
        self.assertEqual(result['jobs'], [])
        self.assertEqual(result['observations'], [])
        self.assertEqual(len(result['errors']), 1)
        self.assertIn('ConnectionError', result['errors'][0])
        self.assertIn('inspect_candidate', result['errors'][0])
        self.assertEqual(model.calls, 0)
        self.assertEqual(tools.calls, [('inspect_candidate', {'manifest_hash': 'a'*64})])
        saved = JobStore(self.root).get('qa-test')
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(saved['report'], result)
        again = await VerificationAgent(self.root, model, tools).run('qa-test')
        self.assertEqual(again, result)
        self.assertEqual(model.calls, 0)
        self.assertEqual(len(tools.calls), 1, 'replay must use the durable report')

    async def test_unadmitted_request_is_still_rejected_without_a_report(self):
        with self.assertRaises(KeyError):
            await VerificationAgent(self.root, ScriptedModel([]), FixtureTools(self.store)).run('not-admitted')
        with self.assertRaises(KeyError):
            self.store.get('not-admitted')

    async def test_tool_response_lost_after_commit_recovers_evidence_without_rerun(self):
        class LostResponse(FixtureTools):
            async def call(self, name, args):
                result = await super().call(name, args)
                if name == 'run_simulation':
                    raise ConnectionError('response lost after committed receipt')
                return result
        result = await VerificationAgent(self.root, ScriptedModel([
            {'action': 'simulate', 'reason': 'check', 'seeds': [7], 'policies': ['balanced']},
            {'action': 'finish', 'reason': '已有收据，只作描述'}]), LostResponse(self.store)).run('qa-test')
        self.assertEqual(result['charged_battles'], 2)
        self.assertTrue(result['errors'])
        self.assertEqual(len(result['observations']), 1)
        self.assertTrue(result['observations'][0]['recovered_from_receipt'])
        self.assertEqual(result['observations'][0]['result']['metrics']['balanced']['pairs'], 1)

    async def test_bad_tool_choice_or_excess_budget_keeps_failure_visible(self):
        model = ScriptedModel([
            {'action':'simulate','reason':'many','seeds':[1,2,3], 'policies':['balanced']},
            {'action':'finish','reason':'预算不足，无法完成'}])
        result = await VerificationAgent(self.root, model, FixtureTools(self.store)).run('qa-test')
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['charged_battles'], 0)
        self.assertTrue(result['errors'])

    async def test_invalid_model_output_is_distinct_from_provider_failure(self):
        from agent_workbench.models import ModelResponseError
        class InvalidGatewayOutput:
            def complete(self, messages, schema):
                raise ModelResponseError('provider response failed structured output validation')

        invalid_decision = {'action': 'simulate', 'reason': 'confused strategy fixture',
                            'seeds': [7], 'policies': ['baseline', 'candidate']}
        for request_id, model in (('qa-invalid-decision', ScriptedModel([invalid_decision])),
                                  ('qa-invalid-gateway', InvalidGatewayOutput())):
            with self.subTest(request_id=request_id):
                self.store.admit(request_id, 'a'*64, '结构化输出故障分类', 4)
                result = await VerificationAgent(self.root, model, FixtureTools(self.store)).run(request_id)
                self.assertEqual(result['stop_reason'], 'model_output_invalid')
                self.assertEqual(result['charged_battles'], 0)
                self.assertEqual(result['jobs'], [])
                self.assertEqual(result['agent_decision_note'], '')
                self.assertEqual(len(result['errors']), 1)
                self.assertIn('model output invalid', result['errors'][0])
                self.assertNotIn('model call failed', result['errors'][0])

    async def test_plan_diagnostics_distinguish_seeds_policies_and_budget(self):
        cases = [([-1], ['balanced'], 'invalid seeds'),
                 ([7, 7], ['balanced'], 'invalid seeds'),
                 ([7], [], 'invalid policies'),
                 ([7], ['balanced', 'balanced'], 'invalid policies'),
                 ([7, 11, 17], ['balanced'], 'battle budget exceeded')]
        for index, (seeds, policies, diagnostic) in enumerate(cases):
            with self.subTest(seeds=seeds, policies=policies):
                request_id = f'qa-plan-{index}'
                self.store.admit(request_id, 'a'*64, '计划诊断', 4)
                model = BoundedScriptedModel([{'action': 'simulate', 'reason': 'invalid plan fixture',
                                               'seeds': seeds, 'policies': policies}], calls=1)
                result = await VerificationAgent(self.root, model, FixtureTools(self.store)).run(request_id)
                self.assertEqual(result['charged_battles'], 0)
                self.assertEqual(result['errors'], ['ValueError: ' + diagnostic])
                self.assertEqual(result['agent_decision_note'], 'invalid plan fixture')


if __name__ == '__main__':
    unittest.main()
