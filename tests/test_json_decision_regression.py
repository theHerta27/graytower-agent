"""Offline HTTP fixtures for the protocol runner, never live-model evidence.

The production ``live`` entrypoint labels its temporary observations ``live``;
all responses in this suite instead come from an explicit HTTP MockTransport.
The enclosing fixture marker makes that provenance explicit. Temporary outputs
are discarded, and neither the historical nor prepared production data is edited.
"""
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'src')]


class JsonDecisionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import check_json_decisions
        cls.runner = check_json_decisions
        cls.master = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.master.cleanup)
        # Match the historical selector's contract without reading production
        # local-data: these are explicitly synthetic prior protocol records.
        history = Path(cls.master.name) / 'fixture-history.jsonl'
        records = []
        for index in range(1, 6):
            records.append({'status': 'completed', 'call_id': f'fixture-history-{index}',
                'raw': {'tool_calls': [{'name': 'Decision', 'args': {'action': 'finish'}}]
                        * (2 if index in (2, 5) else 1)},
                'preview': {'payload': {'messages': [
                    {'role': 'user', 'content': json.dumps({'fixture_context': index})}]}}})
        history.write_text(''.join(json.dumps(record) + '\n' for record in records), encoding='utf-8')
        history_patch = patch.multiple(cls.runner, HISTORY=history, HISTORY_HASH=cls.runner.sha(history))
        history_patch.start()
        cls.addClassCleanup(history_patch.stop)
        cls.prepared = Path(cls.master.name) / 'prepared'
        http = Mock(side_effect=AssertionError('offline prepare must not send HTTP'))
        with httpx.Client(transport=httpx.MockTransport(http), trust_env=False) as client, \
                patch.object(cls.runner, 'gateway', side_effect=lambda data: cls.offline_gateway(data, client)):
            result = cls.runner.prepare(cls.prepared)
        if http.call_count or result['model_calls'] != 0:
            raise AssertionError('preparation must remain zero-call')

    @classmethod
    def offline_gateway(cls, data, client):
        return cls.runner.ModelGateway(model='deepseek-flash', output_method='json_mode', max_calls=4,
            max_input_chars=cls.runner.INPUT_LIMIT, max_output_tokens=cls.runner.OUTPUT_LIMIT,
            audit_path=data / 'model-calls.jsonl', http_client=client,
            api_key='sk-offline-json-regression-fixture')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'batch'
        shutil.copytree(self.prepared, self.data)
        (Path(self.temp.name) / 'fixture-provenance.json').write_text(json.dumps({
            'source': 'fixture', 'http': 'explicit httpx.MockTransport',
            'gateway': 'real ModelGateway', 'credentials': 'literal offline fixture only',
            'not_live_model_evidence': True}), encoding='utf-8')
        self.requests = []

    def authorize_fixture(self, **overrides):
        value = {'approved': True, 'scope_sha256': self.runner.sha(self.data / 'outbound-scope.json'),
                 'test_only': True, 'source': 'offline_http_fixture_not_user_authorization'}
        value.update(overrides)
        (self.data / 'authorization.json').write_text(json.dumps(value), encoding='utf-8')

    def fixture_http(self, *, fail_first=False):
        def respond(request, **kwargs):
            self.assertEqual(str(request.url), 'https://api.deepseek.com/chat/completions')
            self.requests.append(json.loads(request.content))
            decision = {'action': 'finish', 'reason': 'Offline HTTP fixture: do not execute tools or infer business quality.',
                        'seeds': [], 'policies': [], 'artifact_hash': ''}
            content = json.dumps(decision)
            if fail_first and len(self.requests) == 1:
                content += json.dumps(decision)  # Two JSON objects must fail, without repair.
            return httpx.Response(200, request=request, json={
                'id': 'offline-json-regression-fixture', 'model': 'deepseek-flash', 'object': 'chat.completion',
                'choices': [{'index': 0, 'finish_reason': 'stop',
                             'message': {'role': 'assistant', 'content': content}}],
                'usage': {'prompt_tokens': 24, 'completion_tokens': 10, 'total_tokens': 34}})
        return respond

    def offline_context(self, handler=None):
        stack = ExitStack()
        credential = stack.enter_context(patch('demo_v1.load_local_credential'))
        http = Mock(side_effect=handler or self.fixture_http())
        client = stack.enter_context(httpx.Client(transport=httpx.MockTransport(http), trust_env=False))
        # Replace only the runner's factory connection point: parsing, wire
        # generation, LangChain, reservations and audit all use real Gateway.
        stack.enter_context(patch.object(self.runner, 'gateway',
                            side_effect=lambda data: self.offline_gateway(data, client)))
        return stack, credential, http

    def assert_not_started(self, credential, http):
        self.assertEqual(credential.call_count, 0, 'must reject before any credential loader')
        self.assertEqual(http.call_count, 0, 'must reject before HTTP')
        self.assertFalse((self.data / 'started.json').exists())
        self.assertFalse((self.data / 'model-calls.jsonl').exists())

    def test_missing_authorization_blocks_before_credentials_marker_or_http(self):
        stack, credential, http = self.offline_context()
        with stack:
            with self.assertRaises(FileNotFoundError):
                self.runner.live(self.data)
        self.assert_not_started(credential, http)

    def test_wrong_authorization_and_tampered_scope_block_before_http(self):
        for auth in ({'approved': False}, {'scope_sha256': '0' * 64}):
            with self.subTest(auth=auth):
                self.authorize_fixture(**auth)
                stack, credential, http = self.offline_context()
                with stack:
                    with self.assertRaisesRegex(RuntimeError, 'exact scope authorization'):
                        self.runner.live(self.data)
                self.assert_not_started(credential, http)
        self.authorize_fixture()
        scope = self.data / 'outbound-scope.json'
        scope.write_text(scope.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        stack, credential, http = self.offline_context()
        with stack:
            with self.assertRaisesRegex(RuntimeError, 'exact scope authorization'):
                self.runner.live(self.data)
        self.assert_not_started(credential, http)

    def test_tampered_prepared_input_blocks_before_credentials_or_http(self):
        self.authorize_fixture()
        inputs = self.data / 'inputs.json'
        inputs.write_text(inputs.read_text(encoding='utf-8') + ' ', encoding='utf-8')
        stack, credential, http = self.offline_context()
        with stack:
            with self.assertRaisesRegex(RuntimeError, 'prepared input changed: inputs.json'):
                self.runner.live(self.data)
        self.assert_not_started(credential, http)

    def test_fixed_four_real_gateway_calls_use_exact_previews_and_second_live_refuses(self):
        self.authorize_fixture()
        history_before = self.runner.sha(self.runner.HISTORY)
        stack, credential, http = self.offline_context()
        with stack:
            self.runner.live(self.data)
            first_calls = http.call_count
            saved_hashes = {p.name: self.runner.sha(p) for p in self.data.iterdir() if p.is_file()}
            with self.assertRaisesRegex(RuntimeError, 'already started or closed'):
                self.runner.live(self.data)
            self.assertEqual(http.call_count, first_calls)
        self.assertEqual(first_calls, 4)
        self.assertEqual(credential.call_count, 1)
        cases = self.runner.read(self.data / 'inputs.json')
        self.assertEqual([c['case_id'] for c in cases], [
            'qa-wire-2-repeat-1', 'qa-wire-5-repeat-1', 'qa-wire-2-repeat-2', 'qa-wire-5-repeat-2'])
        for case, payload in zip(cases, self.requests, strict=True):
            expected = self.runner.read(self.data / (case['case_id'] + '-preview.json'))['payload']
            self.assertEqual(payload, expected)
            self.assertEqual(payload['response_format'], {'type': 'json_object'})
            self.assertNotIn('tools', payload)
        summary = self.runner.read(self.data / 'summary.json')
        self.assertTrue(summary['protocol_gate_passed'])
        self.assertEqual(summary['model_calls'], 4)
        self.assertEqual(summary['new_battles'], 0)
        self.assertTrue(all(o['tools_executed'] == 0 for o in summary['observations']))
        self.assertEqual(self.runner.sha(self.runner.HISTORY), history_before)
        self.assertEqual(saved_hashes, {p.name: self.runner.sha(p) for p in self.data.iterdir() if p.is_file()})
        self.assertFalse(list(self.data.rglob('jobs.sqlite')))
        self.assertFalse(list(self.data.rglob('artifacts')))

    def test_failed_first_response_is_retained_gate_false_and_no_selective_retry(self):
        self.authorize_fixture()
        stack, credential, http = self.offline_context(self.fixture_http(fail_first=True))
        with stack:
            self.runner.live(self.data)
            with self.assertRaisesRegex(RuntimeError, 'already started or closed'):
                self.runner.live(self.data)
        self.assertEqual(http.call_count, 4)
        self.assertEqual(credential.call_count, 1)
        summary = self.runner.read(self.data / 'summary.json')
        self.assertFalse(summary['protocol_gate_passed'])
        self.assertEqual([o['status'] for o in summary['observations']], ['failed', 'passed', 'passed', 'passed'])
        self.assertEqual(summary['observations'][0]['error_type'], 'ModelResponseError')
        records = [json.loads(line) for line in (self.data / 'model-calls.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(sum(r['status'] == 'reserved' for r in records), 4)
        failed = [r for r in records if r['status'] == 'failed']
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['usage']['total_tokens'], 34)
        self.assertIn('}{', failed[0]['raw']['content'])
        self.assertNotIn('decision', summary['observations'][0])
        self.assertNotIn('sk-offline', (self.data / 'model-calls.jsonl').read_text(encoding='utf-8'))
        closed = self.runner.read(self.data / 'closed.json')
        self.assertEqual(closed['remaining_calls_closed'], 0)
        self.assertTrue(closed['no_fallback_or_selective_rerun'])


if __name__ == '__main__':
    unittest.main()
