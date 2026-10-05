"""Coding UI service tests use an explicit Responses fixture, never a model."""
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from starlette.testclient import TestClient

from agent_workbench.coding.service import CodingAuthorization, CodingService
from agent_workbench.coding.candidates import CodingWorkspace
from agent_workbench.domain import CandidateRepository
from agent_workbench.jobs import JobStore
from agent_workbench.workbench import create_app


class CodingServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.tasks = {name: {'request': '将战技倍率改为1.58，其他不变。', 'mode': mode}
                      for name, mode in [('coding1', 'single'), ('coding2', 'auto')]}
        self.scope = self.root / 'authorization.json'
        self.scope.write_text(json.dumps({'schema': 'coding-service-grant-v1', 'tasks': self.tasks,
            'coding_grant': {'max_calls': 4, 'max_input_bytes': 10000, 'max_output_tokens': 100,
                            'cost_cap_usd': '0.10', 'input_usd_per_million': '0.30',
                            'cached_input_usd_per_million': '0.006', 'output_usd_per_million': '1.20'}}), encoding='utf-8')
        self.authorization = CodingAuthorization(self.scope, hashlib.sha256(self.scope.read_bytes()).hexdigest(),
                                                 self.root / 'coding-ledger')
        self.calls = 0
        self.executions = 0
        self.after_receipt = None

        def sender(body):
            self.calls += 1
            return ('data: ' + json.dumps({'type': 'response.completed', 'response': {
                'id': 'fixture', 'output': [], 'usage': {'input_tokens': 10, 'output_tokens': 2}}}) + '\n\n').encode()

        def runner(**args):
            self.executions += 1
            with urlopen(Request(args['endpoint'] + '/responses', data=json.dumps({
                'model': 'deepseek-flash', 'stream': True, 'input': 'fixture', 'tools': []}).encode(),
                headers={'Content-Type': 'application/json'}), timeout=5) as response:
                self.assertEqual(response.status, 200)
            file = args['workspace'] / 'configs/combat/v2/baseline.json'
            file.write_bytes(file.read_bytes().replace(b'"multiplier": 1.4,', b'"multiplier": 1.58,'))
            workspace = CodingWorkspace(args['workspace'], CandidateRepository(args['data']), args['preparation'])
            inspection = workspace.inspect_changes()
            receipt = {'schema': 'coding-runtime-run-v1', 'mode': args['mode'], 'status': 'completed',
                'sdk': '0.160.0', 'runtime': '0.160.0', 'thread_id': 'fixture-main',
                'review_tree_hash': inspection['after_tree_hash'], 'after_tree_hash': inspection['after_tree_hash'],
                'review_file_sha256': inspection['after_hash'], 'after_sha256': inspection['after_hash'],
                'task_turn': {'status': 'completed', 'items': [{'type': 'agentMessage', 'text': 'fixture author summary'}]},
                'review_turn': {'status': 'completed', 'items': [
                    {'type': 'enteredReviewMode', 'review': 'PRIVATE PROMPT NOT A RESULT'},
                    {'type': 'exitedReviewMode', 'review': 'fixture review opinion'}]},
                'native_spawn_events': [{'params': {'item': {'tool': 'spawnAgent', 'status': 'failed', 'receiverThreadIds': []}}}]}
            args['control'].mkdir(parents=True)
            (args['control'] / 'result.json').write_text(json.dumps(receipt), encoding='utf-8')
            if self.after_receipt:
                self.after_receipt(file)
            return receipt

        self.service = CodingService(self.data, authorization=self.authorization, sender=sender, runner=runner,
                                     runtime_python=Path('fixture-python'), tools_python=Path('fixture-tools'),
                                     source_label='explicit offline fixture')

    def payload(self, name='coding1'):
        return {'operation_id': name, **self.tasks[name]}

    def test_default_http_is_readable_but_cannot_launch_and_does_not_leak_authority(self):
        with TestClient(create_app(self.data), base_url='http://127.0.0.1:8765') as client:
            self.assertFalse(client.get('/api/status').json()['coding']['enabled'])
            self.assertEqual(client.get('/api/coding/runs').json(), {'runs': []})
            result = client.post('/api/coding/runs', json=self.payload())
            self.assertEqual(result.status_code, 403)
            self.assertEqual(client.get('/api/operations/coding1').status_code, 404)
            result = client.post('/api/coding/runs', json=self.payload() | {'api_key': 'secret'})
            self.assertEqual(result.status_code, 422)
            self.assertNotIn('secret', result.text)
        self.assertEqual(self.calls, 0)

    def test_shared_responses_grant_and_identical_post_do_not_repeat_or_confirm(self):
        with TestClient(create_app(self.data, coding_service=self.service), base_url='http://127.0.0.1:8765') as client:
            for name in self.tasks:
                response = client.post('/api/coding/runs', json=self.payload(name))
                self.assertEqual(response.status_code, 202, response.text)
                self.wait(client, name)
            completed = client.get('/api/coding/runs/coding1').json()['run']
            self.assertEqual(completed['status'], 'completed')
            self.assertEqual(completed['review_text'], 'fixture review opinion')
            self.assertEqual(completed['spawned_thread_ids'], [])
            self.assertEqual(completed['spawn_attempts'], 1)
            self.assertNotIn(str(self.root), json.dumps(completed))
            self.assertNotIn('PRIVATE PROMPT', json.dumps(completed))
            self.assertEqual(client.post('/api/coding/runs', json=self.payload()).status_code, 202)
            conflict = client.post('/api/coding/runs', json=self.payload() | {'mode': 'auto'})
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(self.calls, 2)
            self.assertEqual(self.authorization.budget.summary()['reserved'], 2)
            self.assertTrue(all(not c['confirmed'] for c in client.get('/api/candidates').json()['candidates']))
            self.assertEqual(client.get('/api/requests').json()['requests'], [])

    def test_closed_scope_and_nonmatching_task_are_rejected_before_side_effect(self):
        with self.assertRaisesRegex(ValueError, 'authorized'):
            self.service.admit(self.payload() | {'request': 'different request'})
        (self.root / 'closed.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'closed'):
            self.service.admit(self.payload())
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.service.list_runs(), [])
        self.assertFalse(self.service.status()['enabled'])

    def test_status_exposes_only_exact_unclaimed_tasks_and_closure_hides_them(self):
        self.assertEqual(self.service.status()['tasks'], [self.payload(), self.payload('coding2')])
        self.service.admit(self.payload())
        self.assertEqual(self.service.status()['tasks'], [self.payload('coding2')])
        (self.root / 'closed.json').write_text('{}', encoding='utf-8')
        self.assertEqual(self.service.status()['tasks'], [])

    def test_import_completed_keeps_real_receipt_and_existing_confirmation_without_model(self):
        self.service.admit(self.payload())
        self.service.execute('coding1')
        details = self.service.store.coding_details('coding1')
        manifest = details['manifest_hash']
        JobStore(self.data).confirm(manifest)
        imported = CodingService(self.data).import_completed(operation_id='imported',
            request=self.tasks['coding1']['request'], mode='single', manifest_hash=manifest,
            runtime_receipt=details['runtime_receipt'], seconds=1.5, budget=details['budget'])
        self.assertTrue(imported['result']['candidate']['confirmed'])
        self.assertEqual(imported['result']['run']['review_text'], 'fixture review opinion')
        self.assertEqual(self.calls, 1)

    def test_interrupted_import_finishes_from_same_frozen_receipt_without_model(self):
        self.service.admit(self.payload())
        self.service.execute('coding1')
        details = self.service.store.coding_details('coding1')
        readonly = CodingService(self.data)
        args = dict(operation_id='imported', request=self.tasks['coding1']['request'], mode='single',
                    manifest_hash=details['manifest_hash'], runtime_receipt=details['runtime_receipt'])
        with patch.object(readonly, '_complete', side_effect=RuntimeError('power loss during import')):
            with self.assertRaises(RuntimeError):
                readonly.import_completed(**args)
        readonly.store.interrupt_running()
        with self.assertRaises(ValueError):
            readonly.import_completed(**(args | {'runtime_receipt': {'sha256': '0' * 64}}))
        saved = readonly.import_completed(**args)
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(readonly.import_completed(**args), saved)
        self.assertEqual((self.calls, self.executions), (1, 1))

    def test_cli_coding_reads_are_zero_model_and_include_existing_receipt(self):
        from agent_workbench.cli import main
        self.service.admit(self.payload())
        self.service.execute('coding1')
        output = io.StringIO()
        with redirect_stdout(output):
            main(['--data', str(self.data), 'coding-show', 'coding1'])
        self.assertEqual(json.loads(output.getvalue())['run']['manifest_hash'],
                         self.service.get_run('coding1')['manifest_hash'])
        self.assertEqual((self.calls, self.executions), (1, 1))

    def test_demo_import_copies_only_closed_evidence_and_refuses_overwrite(self):
        from scripts.prepare_coding_workbench_demo import prepare
        self.service.admit(self.payload())
        self.service.execute('coding1')
        details = self.service.store.coding_details('coding1')
        manifest = details['manifest_hash']
        source = self.root / 'demo-source'
        source.mkdir()
        import shutil
        shutil.copytree(self.data, source / 'data')
        (source / 'coding-summary.json').write_text(json.dumps({'runs': {'single': {
            'manifest_hash': manifest, 'runtime_receipt': details['runtime_receipt'], 'seconds': 1}},
            'budget': self.authorization.budget.summary()}), encoding='utf-8')
        (source / 'candidate-single.json').write_text(json.dumps(self.service.repo.get(manifest)), encoding='utf-8')
        (source / 'model-calls.jsonl').write_text('must not copy', encoding='utf-8')
        dest = self.root / 'demo-copy'
        with self.assertRaises(ValueError):
            prepare(source, dest)
        (source / 'closed.json').write_text('{"unused_calls_closed": true}', encoding='utf-8')
        result = prepare(source, dest)
        self.assertTrue(result['source_files_unchanged'])
        self.assertEqual(CodingService(dest).get_run('coding-demo-single')['manifest_hash'], manifest)
        self.assertFalse((dest / 'model-calls.jsonl').exists())
        self.assertFalse((dest / 'coding-runs').exists())
        with self.assertRaises(FileExistsError):
            prepare(source, dest)
        self.assertEqual((self.calls, self.executions), (1, 1))

    def test_completed_receipt_can_finish_after_restart_with_no_authorization_or_sender(self):
        self.service.admit(self.payload())
        with patch.object(self.service, '_finalize', side_effect=RuntimeError('crash before candidate receipt')):
            self.service.execute('coding1')
        self.assertEqual(self.calls, 1)
        restarted = CodingService(self.data)
        restarted.recover('coding1')
        run = restarted.get_run('coding1')
        self.assertEqual(run['status'], 'completed')
        restarted.recover('coding1')
        self.assertEqual(self.calls, 1)
        self.assertEqual(restarted.get_run('coding1')['manifest_hash'], run['manifest_hash'])
        self.assertFalse(restarted.status()['enabled'])

    def test_missing_receipt_never_reruns_and_changed_review_tree_cannot_freeze(self):
        self.service.admit(self.payload())
        self.service.store.interrupt_running()
        with self.assertRaisesRegex(ValueError, 'receipt'):
            CodingService(self.data).recover('coding1')
        self.assertEqual(self.executions, 0)
        self.service.admit(self.payload('coding2'))
        self.after_receipt = lambda file: file.write_bytes(file.read_bytes().replace(b'1.58,', b'1.60,'))
        self.service.execute('coding2')
        self.assertEqual(self.service.get_run('coding2')['status'], 'failed')
        self.assertIsNone(self.service.get_run('coding2')['manifest_hash'])
        CodingService(self.data).recover('coding2')
        self.assertEqual(self.service.get_run('coding2')['status'], 'failed')
        self.assertEqual(self.executions, 1)

    def wait(self, client, name):
        import time
        for _ in range(200):
            run = client.get('/api/coding/runs/' + name).json()['run']
            if run['status'] != 'running':
                self.assertEqual(run['status'], 'completed', run)
                return
            time.sleep(.03)
        self.fail('fixture operation did not finish')


if __name__ == '__main__':
    unittest.main()
