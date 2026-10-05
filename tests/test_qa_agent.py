"""Business verdicts and receipt recovery, with an explicitly scripted model."""
import tempfile
import unittest
from pathlib import Path

from agent_workbench.jobs import JobStore
from agent_workbench.qa import VerificationAgent


class ScriptedModel:
    def __init__(self, actions):
        self.actions = iter(actions)
    def complete(self, messages, schema):
        return next(self.actions)


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


if __name__ == '__main__':
    unittest.main()
