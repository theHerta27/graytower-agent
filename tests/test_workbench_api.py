"""Local HTTP integration; explicit model fixtures, zero provider/battle calls."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import asyncio

from starlette.testclient import TestClient

from agent_workbench.domain import CandidateRepository
from agent_workbench.domain._shared import Artifacts
from agent_workbench.jobs import JobStore


class FixtureModel:
    """Deliberately fixed decisions; not a real-model acceptance result."""
    def __init__(self, answer, limit=4, entered=None, release=None):
        self.answer, self.limit = answer, limit
        self.entered, self.release = entered, release
        self.calls = 0

    def remaining_calls(self):
        return self.limit - self.calls

    def complete(self, messages, schema):
        self.calls += 1
        if self.entered:
            self.entered.set()
            if not self.release.wait(10):
                raise RuntimeError('fixture release timed out')
        return schema.model_validate(self.answer).model_dump()


class WorkbenchAPITests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('agent_workbench.workbench'),
                             'The local workbench API has not been implemented')
        from agent_workbench.workbench import create_app
        self.create_app = create_app
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = JobStore(self.root)
        self.repo = CandidateRepository(self.root)

    def app(self, model=None, **kwargs):
        if model is not None:
            kwargs.update(call_cap=model.limit, audit_path=self.root / 'fixture-audit.jsonl',
                          model_factory=lambda **unused: model)
        return self.create_app(self.root, **kwargs)

    def client(self, app=None):
        return TestClient(app or self.app(), base_url='http://127.0.0.1:8765')

    def candidate(self, text='将击破手战技倍率改为1.7。', value=1.7):
        return self.repo.create(text, [{'path': 'skills.breaker_skill.multiplier', 'value': value}])

    def wait_operation(self, client, operation_id):
        for _ in range(200):
            item = client.get('/api/operations/' + operation_id).json()
            if item['status'] != 'running':
                return item
            time.sleep(.03)
        self.fail('operation did not finish')

    def test_default_model_gate_rejects_work_without_creating_operations(self):
        def forbidden(**kwargs):
            self.fail('disabled startup must not construct a model')
        candidate = self.candidate()
        self.store.confirm(candidate['manifest_hash'])
        with self.client(self.app(model_factory=forbidden)) as client:
            self.assertEqual(client.get('/api/status').json()['model']['remaining_calls'], 0)
            for path, body in (
                ('/api/drafts', {'operation_id': 'draft1', 'request': '改到1.7'}),
                ('/api/verifications', {'request_id': 'qa1', 'manifest_hash': candidate['manifest_hash'],
                                        'goal': '检查变化', 'max_battles': 4}),
            ):
                response = client.post(path, json=body)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()['error']['code'], 'model_disabled')
            self.assertEqual(client.get('/api/operations/draft1').status_code, 404)
            self.assertEqual(client.get('/api/requests').json(), {'requests': []})
        self.assertFalse((self.root / 'model-calls.jsonl').exists())

    def test_invalid_origins_hosts_and_extra_authority_fields_are_rejected(self):
        with self.client() as client:
            for headers in ({'Host': 'evil.example'}, {'Host': 'localhost:invalid'}, {'Origin': 'https://evil.example'},
                            {'Origin': 'http://localhost:8765'}, {'Origin': 'null'}):
                result = client.post('/api/drafts', headers=headers,
                                     json={'operation_id': 'd', 'request': '改到1.7'})
                self.assertEqual(result.status_code, 403)
                self.assertEqual(result.json()['error']['code'], 'forbidden_origin')
            for extra in ({'call_cap': 100}, {'data': 'D:/other'}, {'api_key': 'fixture-secret'}):
                result = client.post('/api/drafts', json={'operation_id': 'd', 'request': '改到1.7', **extra})
                self.assertEqual(result.status_code, 422)
                self.assertNotIn('fixture-secret', result.text)
            self.assertEqual(client.get('/api/status', headers={'Origin': 'http://127.0.0.1:8765'}).status_code, 200)

    def test_candidate_listing_is_explicit_and_confirmation_binds_exact_hash(self):
        first = self.candidate()
        second = self.candidate('将击破手战技倍率改为1.6。', 1.6)
        with self.client() as client:
            self.assertEqual(client.get('/api/candidates').json(), {'candidates': []})
            shown = client.post('/api/candidates/inspect', json={'manifest_hash': first['manifest_hash']})
            self.assertEqual(shown.status_code, 200)
            self.assertFalse(shown.json()['confirmed'])
            self.assertEqual(shown.json()['diff'], [{'path': 'skills.breaker_skill.multiplier', 'before': 1.4, 'after': 1.7}])
            confirmed = client.post('/api/candidates/' + first['manifest_hash'] + '/confirm')
            self.assertTrue(confirmed.json()['confirmed'])
            listed = client.get('/api/candidates').json()['candidates']
            self.assertEqual([c['manifest_hash'] for c in listed], [first['manifest_hash']])
            self.assertEqual(client.post('/api/candidates/not-a-hash/confirm').status_code, 422)
            self.assertEqual(self.repo.get(second['manifest_hash']), second)
        with self.client() as client:
            self.assertTrue(client.get('/api/candidates').json()['candidates'][0]['confirmed'])

    def test_draft_is_async_immutable_and_replayed_without_another_model_call(self):
        entered, release = threading.Event(), threading.Event()
        model = FixtureModel({'status': 'candidate', 'message': 'fixture proposal',
                              'changes': [{'path': 'skills.breaker_skill.multiplier', 'value': 1.7}]},
                             entered=entered, release=release)
        body = {'operation_id': 'draft1', 'request': '将击破手战技倍率改为1.7。'}
        with self.client(self.app(model)) as client:
            try:
                started = client.post('/api/drafts', json=body)
                self.assertEqual(started.status_code, 202)
                self.assertEqual(started.json()['status'], 'running')
                self.assertTrue(entered.wait(5))
                replay = client.post('/api/drafts', json=body)
                self.assertEqual(replay.json()['operation_id'], 'draft1')
                changed = client.post('/api/drafts', json={**body, 'request': '改成1.6'})
                self.assertEqual(changed.status_code, 409)
                self.assertEqual(changed.json()['error']['code'], 'idempotency_conflict')
                busy = client.post('/api/drafts', json={**body, 'operation_id': 'draft2'})
                self.assertEqual(busy.status_code, 409)
                self.assertEqual(busy.json()['error']['code'], 'busy')
                self.assertEqual(model.calls, 1)
            finally:
                release.set()
            operation = self.wait_operation(client, 'draft1')
            self.assertEqual(operation['status'], 'completed')
            self.assertEqual(operation['result']['status'], 'candidate')
            candidates = client.get('/api/candidates').json()['candidates']
            self.assertEqual(len(candidates), 1)
            self.assertFalse(candidates[0]['confirmed'])
            self.assertEqual(candidates[0]['manifest_hash'], operation['result']['candidate']['manifest_hash'])
        with self.client() as client:
            self.assertEqual(client.post('/api/drafts', json=body).json(), operation)
        self.assertEqual(model.calls, 1)

    def test_saved_report_and_trace_are_read_only_and_request_scoped(self):
        candidate = self.candidate()
        manifest = candidate['manifest_hash']
        self.store.confirm(manifest)
        self.store.admit('saved', manifest, '固定样本检查', 4)
        trace_ref = Artifacts(self.root / 'artifacts').put({'events': [
            {'event_id': 'end', 'kind': 'battle_finished', 'payload': {'outcome': 'win'}}]}, 'combat-trace-v2')
        receipt = self.store.run('saved', {'fixture': True}, 2, lambda: {
            'manifest_hash': manifest, 'completed_battles': 2,
            'rows': [{'seed': 7, 'policy': 'balanced',
                      'baseline': {'outcome': 'win', 'elapsed_av': '100'},
                      'candidate': {'outcome': 'win', 'elapsed_av': '100/7'}}],
            'trace_refs': [{**trace_ref, 'seed': 7, 'policy': 'balanced', 'variant': 'candidate'}]})
        report = {'request_id': 'saved', 'manifest_hash': manifest, 'verdict': 'INCONCLUSIVE',
                  'jobs': [receipt], 'errors': [], 'charged_battles': 2}
        self.store.complete('saved', report)
        self.store.admit('other', manifest, '另一个请求', 2)
        with self.client() as client:
            detail = client.get('/api/requests/saved').json()
            self.assertEqual(detail['request']['report'], report)
            self.assertEqual(detail['facts']['comparisons'][0]['delta_av'], '-600/7')
            self.assertIn('行动值减少', detail['report_text'])
            trace = client.get('/api/requests/saved/traces/' + trace_ref['sha256'])
            self.assertEqual(trace.status_code, 200)
            self.assertEqual(trace.json()['artifact_hash'], trace_ref['sha256'])
            self.assertTrue(trace.json()['selection']['single_variant'])
            self.assertEqual(client.get('/api/requests/other/traces/' + trace_ref['sha256']).status_code, 422)
            self.assertEqual(client.get('/api/requests/missing').status_code, 404)
        self.assertEqual(JobStore(self.root).get('saved')['charged_battles'], 2)
        self.assertEqual(JobStore(self.root).get('saved')['report'], report)

    def test_real_qa_graph_mcp_a2a_with_fixture_model_saves_report_and_deduplicates(self):
        model = FixtureModel({'action': 'finish', 'reason': 'Fixture: no battles requested.'})
        candidate = self.candidate()
        self.store.confirm(candidate['manifest_hash'])
        body = {'request_id': 'qa1', 'manifest_hash': candidate['manifest_hash'],
                'goal': '检查候选，fixture不启动战斗', 'max_battles': 4}
        with self.client(self.app(model)) as client:
            started = client.post('/api/verifications', json=body)
            self.assertEqual(started.status_code, 202)
            self.assertEqual(started.json()['operation_id'], 'verify_qa1')
            operation = self.wait_operation(client, 'verify_qa1')
            self.assertEqual(operation['status'], 'completed', operation)
            self.assertEqual(operation['result']['task_state'], 'TASK_STATE_COMPLETED')
            detail = client.get('/api/requests/qa1').json()
            self.assertEqual(detail['request']['status'], 'completed')
            self.assertEqual(detail['request']['report']['verdict'], 'INCONCLUSIVE')
            self.assertEqual(detail['request']['charged_battles'], 0)
            self.assertEqual(client.post('/api/verifications', json=body).json(), operation)
            self.assertEqual(client.post('/api/verifications', json={**body, 'max_battles': 6}).status_code, 409)
        self.assertEqual(model.calls, 1)
        with self.client() as client:
            self.assertEqual(client.post('/api/verifications', json=body).json(), operation)

    def test_existing_completed_request_delivers_via_a2a_with_model_disabled(self):
        candidate = self.candidate()
        manifest = candidate['manifest_hash']
        self.store.confirm(manifest)
        self.store.admit('saved', manifest, '已保存报告', 2)
        report = {'request_id': 'saved', 'manifest_hash': manifest, 'verdict': 'INCONCLUSIVE',
                  'jobs': [], 'errors': [], 'charged_battles': 0}
        self.store.complete('saved', report)
        with self.client() as client:
            result = client.post('/api/verifications', json={'request_id': 'saved', 'manifest_hash': manifest,
                                                            'goal': '已保存报告', 'max_battles': 2})
            self.assertEqual(result.status_code, 202)
            operation = self.wait_operation(client, 'verify_saved')
            self.assertEqual(operation['status'], 'completed', operation)
            self.assertEqual(operation['result']['report'], report)

    def test_startup_interrupts_unfinished_operation_without_reissuing_it(self):
        from agent_workbench.workbench_store import WorkbenchStore
        WorkbenchStore(self.root).start('old-draft', 'draft', {'request': 'old', 'parent_manifest': None})
        with self.client() as client:
            saved = client.get('/api/operations/old-draft').json()
            self.assertEqual(saved['status'], 'interrupted')
            again = client.post('/api/drafts', json={'operation_id': 'old-draft', 'request': 'old'})
            self.assertEqual(again.json(), saved)

    def test_positive_cap_requires_explicit_audit_path_and_used_calls_remain_charged(self):
        with self.assertRaises(ValueError):
            self.app(call_cap=1)
        audit = self.root / 'explicit-shared-audit.jsonl'
        audit.write_text(json.dumps({'call_id': 'unknown', 'status': 'reserved'}) + '\n', encoding='utf-8')
        with self.client(self.app(call_cap=1, audit_path=audit)) as client:
            status = client.get('/api/status').json()['model']
            self.assertEqual(status['remaining_calls'], 0)
            self.assertFalse(status['enabled'])
            self.assertNotIn(str(audit), json.dumps(status))
            result = client.post('/api/drafts', json={'operation_id': 'blocked', 'request': '改到1.7'})
            self.assertEqual(result.status_code, 403)
        self.assertEqual(len(audit.read_text(encoding='utf-8').splitlines()), 1)

    def test_qa_only_startup_keeps_draft_disabled_even_with_available_calls(self):
        model = FixtureModel({'action': 'finish', 'reason': 'fixture'})
        with self.client(self.app(model, model_actions=('verify',))) as client:
            status = client.get('/api/status').json()['model']
            self.assertTrue(status['enabled'])
            self.assertEqual(status['actions'], ['verify'])
            rejected = client.post('/api/drafts', json={'operation_id': 'd', 'request': '改到1.7'})
            self.assertEqual(rejected.status_code, 403)
            self.assertEqual(rejected.json()['error']['code'], 'action_disabled')
            self.assertEqual(client.get('/api/operations/d').status_code, 404)
        self.assertEqual(model.calls, 0)

    def test_explicit_resume_uses_saved_input_checkpoint_and_receipts(self):
        from agent_workbench.workbench_store import WorkbenchStore
        model = FixtureModel({'action': 'finish', 'reason': 'fixture: existing receipt only'})
        manifest = self.candidate()['manifest_hash']
        self.store.confirm(manifest)
        payload = {'request_id': 'resume1', 'manifest_hash': manifest, 'goal': '检查已保存收据', 'max_battles': 4}
        self.store.admit(**payload)
        self.store.run('resume1', {'fixture': True}, 2, lambda: {'manifest_hash': manifest,
            'completed_battles': 2, 'overall_verdict': 'INCONCLUSIVE', 'structural_verdict': 'PASS',
            'rows': [], 'trace_refs': []})
        WorkbenchStore(self.root).start('verify_resume1', 'verify', payload)
        with self.client(self.app(model)) as client:
            self.assertEqual(client.post('/api/verifications', json=payload).json()['status'], 'interrupted')
            self.assertEqual(client.post('/api/verifications/resume1/resume', json={'max_battles': 8}).status_code, 422)
            started = client.post('/api/verifications/resume1/resume')
            self.assertEqual(started.status_code, 202)
            finished = self.wait_operation(client, 'verify_resume1')
            self.assertEqual(finished['status'], 'completed', finished)
            report = finished['result']['report']
            self.assertEqual(report['charged_battles'], 2)
            self.assertEqual(len(report['jobs']), 1)
        self.assertEqual(model.calls, 1)
        self.assertEqual(self.store.get('resume1')['max_battles'], 4)

    def test_resume_refuses_unknown_physical_job_without_consuming_model(self):
        model = FixtureModel({'action': 'finish', 'reason': 'fixture'})
        manifest = self.candidate()['manifest_hash']
        self.store.confirm(manifest)
        self.store.admit('unknown', manifest, '保留未知作业', 4)
        def interrupted():
            raise RuntimeError('fixture hard-stop after durable claim')
        with self.assertRaises(RuntimeError):
            self.store.run('unknown', {'fixture': True}, 2, interrupted)
        with self.client(self.app(model)) as client:
            result = client.post('/api/verifications/unknown/resume')
            self.assertEqual(result.status_code, 409)
            self.assertEqual(result.json()['error']['code'], 'recovery_required')
            self.assertEqual(client.get('/api/operations/verify_unknown').status_code, 404)
        self.assertEqual(model.calls, 0)
        self.assertEqual(self.store.get('unknown')['charged_battles'], 2)

    def test_zero_budget_resume_finishes_saved_decision_without_new_inference(self):
        from agent_workbench.qa import VerificationAgent
        from agent_workbench.game_tools import GameTools
        from agent_workbench.workbench_store import WorkbenchStore
        model = FixtureModel({'action': 'finish', 'reason': 'fixture: saved decision'}, limit=1)
        manifest = self.candidate()['manifest_hash']
        self.store.confirm(manifest)
        payload = {'request_id': 'last-call', 'manifest_hash': manifest, 'goal': '恢复最后决定', 'max_battles': 4}
        self.store.admit(**payload)
        self.store.run('last-call', {'fixture': True}, 2, lambda: {'manifest_hash': manifest,
            'completed_battles': 2, 'overall_verdict': 'INCONCLUSIVE', 'structural_verdict': 'PASS',
            'rows': [], 'trace_refs': []})
        root = self.root
        class ReadOnlyTools:
            async def call(self, name, args):
                if name != 'inspect_candidate':
                    raise AssertionError('fixture never starts simulation')
                return GameTools(root).inspect_candidate(**args)
        with patch.object(JobStore, 'complete', side_effect=RuntimeError('crash before report save')):
            with self.assertRaisesRegex(RuntimeError, 'crash before report save'):
                asyncio.run(VerificationAgent(self.root, model, ReadOnlyTools()).run('last-call'))
        self.assertEqual(model.remaining_calls(), 0)
        self.assertIsNone(self.store.get('last-call')['report'])
        WorkbenchStore(self.root).start('verify_last-call', 'verify', payload)
        with self.client() as client:
            self.assertFalse(client.get('/api/status').json()['model']['enabled'])
            resumed = client.post('/api/verifications/last-call/resume')
            self.assertEqual(resumed.status_code, 202, resumed.text)
            result = self.wait_operation(client, 'verify_last-call')
            self.assertEqual(result['status'], 'completed', result)
            report = result['result']['report']
            self.assertEqual(report['agent_decision_note'], 'fixture: saved decision')
            self.assertEqual(report['charged_battles'], 2)
            self.assertEqual(len(report['jobs']), 1)
            self.assertEqual(report['errors'], [])
        self.assertEqual(model.calls, 1)

    def test_static_frontend_cannot_serve_data_directory_or_raw_audit(self):
        dist = self.root / 'fixture-dist'
        dist.mkdir()
        (dist / 'index.html').write_text('<html><body>Fixture shell</body></html>', encoding='utf-8')
        (self.root / 'model-calls.jsonl').write_text('private fixture ledger', encoding='utf-8')
        with self.client(self.app(frontend_dist=dist)) as client:
            self.assertIn('Fixture shell', client.get('/').text)
            self.assertEqual(client.get('/model-calls.jsonl').status_code, 404)
            self.assertEqual(client.get('/%2e%2e/model-calls.jsonl').status_code, 404)
            self.assertEqual(client.get('/api/no-such-route').json()['error']['code'], 'not_found')


if __name__ == '__main__':
    unittest.main()
