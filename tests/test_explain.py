"""Read-only recovery appendix tests: fixture tools/model, real SQLite receipts."""
from copy import deepcopy
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_workbench.jobs import JobStore, RecoveryRequired, digest


class FakeModel:
    """Explicit local fixture, never a live inference result."""
    def __init__(self, failure=False, extra=None):
        self.inputs = []
        self.failure, self.extra = failure, extra or {}

    def complete(self, messages, schema):
        self.inputs.append(deepcopy(messages))
        if self.failure:
            raise RuntimeError('Authorization: Bearer sk-sensitive-fixture')
        return {'summary': '现有配对样本中候选战斗更快；原工具返回存在错误，不能据此认定整个流程通过。',
                'limitations': ['仅为已有小样本收据的解释，原判定仍是不确定。'], **self.extra}


class FixtureTools:
    def __init__(self, store, mutate=False):
        self.store, self.mutate = store, mutate
        self.calls = []

    async def call(self, name, args):
        self.calls.append((name, deepcopy(args)))
        if name != 'read_receipts':
            raise AssertionError('explanation must not simulate or invoke any write tool')
        receipts = deepcopy(self.store.receipts(args['request_id']))
        if self.mutate:
            receipts[0]['manifest_hash'] = 'b' * 64
        return {'receipts': receipts, 'authorization': 'Bearer sk-tool-secret-fixture'}


class ExplainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = JobStore(self.root)
        self.store.confirm('a' * 64)
        self.store.admit('qa-fixture', 'a' * 64, '检查现有配对战斗。', 4)
        self.receipt = self.store.run('qa-fixture', {'seeds': [7], 'policies': ['balanced']}, 2, lambda: {
            'manifest_hash': 'a' * 64, 'completed_battles': 2,
            'structural_verdict': 'PASS', 'overall_verdict': 'INCONCLUSIVE',
            'rows': [{'seed': 7, 'policy': 'balanced',
                      'baseline': {'outcome': 'win', 'elapsed_av': '100'},
                      'candidate': {'outcome': 'win', 'elapsed_av': '90'}}],
            'metrics': {'balanced': {'pairs': 1, 'common_wins': 1, 'paired_av_ratio_median': 0.9,
                                    'api_key': 'raw-tool-credential', 'transitions': {'win->win': 1}}},
            'api_key': 'raw-receipt-credential'})
        self.report = {'schema_version': 'qa-report-v1', 'request_id': 'qa-fixture',
                       'manifest_hash': 'a' * 64, 'verdict': 'INCONCLUSIVE',
                       'structural_verdict': 'PASS', 'charged_battles': 2,
                       'errors': ['Authorization: Bearer sk-error-secret-fixture'],
                       'observations': [], 'jobs': [self.receipt], 'api_key': 'raw-report-credential'}
        self.store.complete('qa-fixture', self.report)

    async def explain(self, model=None, tools=None):
        from agent_workbench.explain import explain_report
        return await explain_report(self.root, 'qa-fixture', model or FakeModel(), tools or FixtureTools(self.store))

    async def test_explanation_uses_one_read_and_one_call_and_preserves_original_report(self):
        model, tools = FakeModel(), FixtureTools(self.store)
        result = await self.explain(model, tools)
        artifact = result['artifact']
        self.assertEqual(result['artifact_hash'], digest(artifact))
        self.assertEqual(artifact['report_hash'], digest(self.report))
        self.assertEqual(artifact['receipt_hashes'], [digest(self.receipt)])
        self.assertEqual(artifact['manifest_hash'], 'a' * 64)
        self.assertEqual(artifact['verdict'], 'INCONCLUSIVE')
        self.assertTrue(artifact['original_run_had_errors'])
        self.assertEqual(len(model.inputs), 1)
        self.assertEqual(tools.calls, [('read_receipts', {'request_id': 'qa-fixture'})])
        self.assertEqual(self.store.get('qa-fixture')['report'], self.report)
        self.assertEqual(self.store.get('qa-fixture')['charged_battles'], 2)

    async def test_completed_artifact_reuses_without_model_or_mcp_after_reopen(self):
        first = await self.explain()
        model, tools = FakeModel(failure=True), FixtureTools(JobStore(self.root))
        self.assertEqual(await self.explain(model, tools), first)
        self.assertEqual(model.inputs, [])
        self.assertEqual(tools.calls, [])

    async def test_output_tamper_is_rejected_without_overwriting_or_model_call(self):
        first = await self.explain()
        path = self.root / 'explanations' / 'qa-fixture.json'
        first['artifact']['verdict'] = 'PASS'
        path.write_text(json.dumps(first), encoding='utf-8')
        before = path.read_bytes()
        model = FakeModel()
        with self.assertRaisesRegex(ValueError, 'integrity|hash'):
            await self.explain(model)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(model.inputs, [])

    async def test_started_operation_without_output_never_silently_retries(self):
        model = FakeModel(failure=True)
        with self.assertRaisesRegex(RuntimeError, 'explanation model call failed'):
            await self.explain(model)
        again = FakeModel()
        with self.assertRaises(RecoveryRequired):
            await self.explain(again)
        self.assertEqual(len(model.inputs), 1)
        self.assertEqual(again.inputs, [])
        marker = (self.root / 'explanations' / 'qa-fixture.operation.json').read_text(encoding='utf-8')
        self.assertNotIn('sk-sensitive', marker)
        self.assertEqual(self.store.get('qa-fixture')['report'], self.report)

    async def test_foreign_mcp_receipt_is_rejected_before_model_or_marker(self):
        model = FakeModel()
        with self.assertRaisesRegex(ValueError, 'receipt'):
            await self.explain(model, FixtureTools(self.store, mutate=True))
        self.assertEqual(model.inputs, [])
        self.assertFalse((self.root / 'explanations' / 'qa-fixture.operation.json').exists())

    async def test_only_allowlisted_evidence_is_sent_without_credentials_or_raw_errors(self):
        model = FakeModel()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-env-credential-fixture'}):
            await self.explain(model)
        serialized = json.dumps(model.inputs)
        for excluded in ('raw-tool-credential', 'raw-receipt-credential', 'raw-report-credential',
                         'sk-error-secret', 'sk-tool-secret', 'sk-env-credential', 'api_key', 'Authorization'):
            self.assertNotIn(excluded, serialized)
        payload = json.loads(model.inputs[0][1]['content'])
        self.assertEqual(payload['original_error_count'], 1)
        self.assertEqual(payload['evidence'][0]['rows'][0]['candidate']['elapsed_av'], '90')

    async def test_model_cannot_add_or_override_verdict(self):
        with self.assertRaisesRegex(RuntimeError, 'explanation model call failed'):
            await self.explain(FakeModel(extra={'verdict': 'PASS'}))
        self.assertFalse((self.root / 'explanations' / 'qa-fixture.json').exists())
        self.assertEqual(self.store.get('qa-fixture')['report']['verdict'], 'INCONCLUSIVE')

    async def test_durable_output_before_completion_marker_reconciles_without_new_call(self):
        first = await self.explain()
        path = self.root / 'explanations' / 'qa-fixture.operation.json'
        marker = json.loads(path.read_text(encoding='utf-8'))
        marker['status'] = 'started'
        marker.pop('artifact_hash')
        path.write_text(json.dumps(marker), encoding='utf-8')
        model = FakeModel(failure=True)
        self.assertEqual(await self.explain(model), first)
        self.assertEqual(model.inputs, [])
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['status'], 'completed')

    async def test_rehashed_appendix_still_must_match_completion_marker(self):
        first = await self.explain()
        path = self.root / 'explanations' / 'qa-fixture.json'
        first['artifact']['explanation']['summary'] = '替换后的说明。'
        first['artifact_hash'] = digest(first['artifact'])
        path.write_text(json.dumps(first), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'operation hash'):
            await self.explain()

    async def test_two_concurrent_readers_can_claim_only_one_model_call(self):
        ready = asyncio.Event()
        arrivals = []
        store = self.store

        class SimultaneousTools(FixtureTools):
            async def call(self, name, args):
                arrivals.append(1)
                if len(arrivals) == 2:
                    ready.set()
                await ready.wait()
                return await super().call(name, args)

        left, right = FakeModel(), FakeModel()
        results = await asyncio.gather(self.explain(left, SimultaneousTools(store)),
                                       self.explain(right, SimultaneousTools(store)), return_exceptions=True)
        self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
        self.assertEqual(sum(isinstance(item, RecoveryRequired) for item in results), 1)
        self.assertEqual(len(left.inputs) + len(right.inputs), 1)


if __name__ == '__main__':
    unittest.main()
