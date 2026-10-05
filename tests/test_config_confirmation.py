"""Confirmation runner safety checks; HTTP transport fixtures, no real model."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'src')]


class ConfirmationRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import prepare_config_confirmation as prepare
        cls.preparer = prepare
        cls.master = tempfile.TemporaryDirectory()
        cls.prepared = Path(cls.master.name) / 'prepared'
        prepare.prepare(cls.prepared)

    @classmethod
    def tearDownClass(cls):
        cls.master.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'batch'
        shutil.copytree(self.prepared, self.data)

    def test_fixed_public_previews_exclude_oracle_and_fit_full_wire(self):
        scope = json.loads((self.data / 'outbound-scope.json').read_text(encoding='utf-8'))
        self.assertEqual(scope['case_ids'], [f'confirm-c{i:02d}' for i in range(1, 13)])
        self.assertEqual(scope['max_calls_total_including_failed_unknown'], 24)
        self.assertEqual(scope['max_calls_per_case'], 2)
        previews = json.loads((self.data / 'outbound-previews.json').read_text(encoding='utf-8'))
        for item in previews:
            payload = item['preview']['payload']
            self.assertNotIn('tools', payload)
            self.assertEqual(payload['response_format'], {'type': 'json_object'})
            contexts = [json.loads(m['content']) for m in payload['messages']
                        if m['role'] == 'user']
            self.assertEqual(set(contexts[0]), {'request', 'repository', 'parent_candidate'})
            self.assertTrue(contexts[0]['repository']['schema'])
            self.assertTrue(contexts[0]['repository']['rules'])
            self.assertLessEqual(item['preview']['input_chars'], scope['max_input_chars_per_call'])
        capacity = json.loads((self.data / 'repair-capacity.json').read_text(encoding='utf-8'))
        self.assertTrue(all(row['input_chars'] <= scope['max_input_chars_per_call'] for row in capacity['measurements']))
        self.assertFalse((self.data / 'model-calls.jsonl').exists())
        self.assertFalse(any((self.data / 'cases').glob('*/artifacts/*.json')))

    def test_real_graph_fixture_records_repair_and_refuses_second_batch(self):
        from agent_workbench.models import ModelGateway
        from run_config_confirmation import run_batch
        requests = []
        def response(request):
            requests.append(json.loads(request.content))
            decision = ({'status': 'candidate', 'message': 'fixture invalid value',
                         'changes': [{'path': 'skills.breaker_skill.multiplier', 'value': 8}]}
                        if len(requests) == 1 else
                        {'status': 'needs_input', 'message': 'fixture question, not an evaluation answer', 'changes': []})
            return httpx.Response(200, json={'id': 'fixture', 'model': 'deepseek-flash', 'object': 'chat.completion',
                'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(decision)}}],
                'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}})
        with httpx.Client(transport=httpx.MockTransport(response)) as client:
            def factory(**kwargs):
                return ModelGateway(**kwargs, api_key='sk-offline-confirmation-fixture', http_client=client)
            result = run_batch(self.data, self.preparer.sha(self.data / 'outbound-scope.json'),
                               model_factory=factory, source='fixture')
            self.assertEqual(result['reserved_calls'], 13)
            observations = json.loads((self.data / 'observations.json').read_text(encoding='utf-8'))
            self.assertEqual(list(observations), [f'confirm-c{i:02d}' for i in range(1, 13)])
            first = observations['confirm-c01']
            self.assertEqual(first['audit']['model_reserved_calls'], 2)
            self.assertTrue(first['output']['validation_errors'])
            self.assertEqual(first['audit']['source'], 'fixture')
            self.assertEqual(first['audit']['battle_count'], 0)
            with self.assertRaisesRegex(RuntimeError, 'already started'):
                run_batch(self.data, self.preparer.sha(self.data / 'outbound-scope.json'), model_factory=factory, source='fixture')
        self.assertEqual(len(requests), 13)
        self.assertNotIn('sk-offline', (self.data / 'model-calls.jsonl').read_text(encoding='utf-8'))

    def test_tampered_preview_stops_before_batch_marker_or_model(self):
        from run_config_confirmation import run_batch
        preview = self.data / 'outbound-previews.json'
        preview.write_text(preview.read_text(encoding='utf-8') + ' ', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'seal mismatch'):
            run_batch(self.data, self.preparer.sha(self.data / 'outbound-scope.json'), source='fixture',
                      model_factory=lambda **kwargs: self.fail('must stop before constructing model'))
        self.assertFalse((self.data / 'batch-started.json').exists())

    def test_per_case_wrapper_refuses_third_call_and_keeps_first_preview(self):
        from run_config_confirmation import CaseModel
        class Fixture:
            def preview(self, messages, schema):
                return {'payload': {'messages': messages}, 'input_chars': 1}
            def complete(self, messages, schema):
                return {'fixture': True}
        messages = [{'role': 'user', 'content': 'fixture'}]
        wrapper = CaseModel(Fixture(), {'messages': messages}, max_calls=2)
        wrapper.complete(messages, object)
        wrapper.complete(messages, object)
        with self.assertRaisesRegex(RuntimeError, 'per-case'):
            wrapper.complete(messages, object)
        self.assertEqual(wrapper.attempts, 2)

    def test_fixture_without_factory_rejects_before_scope_or_marker(self):
        from run_config_confirmation import run_batch
        # An absent scope would fail first if the source/factory gate did not
        # precede preparation reads and construction of the real gateway.
        absent = self.data / 'not-prepared'
        with self.assertRaisesRegex(ValueError, 'fixture source requires an injected model'):
            run_batch(absent, 'not-a-scope-hash', source='fixture')
        self.assertFalse(absent.exists())
        self.assertFalse((self.data / 'batch-started.json').exists())
        self.assertFalse((self.data / 'model-calls.jsonl').exists())

    def test_live_with_factory_rejects_before_factory_scope_or_marker(self):
        from run_config_confirmation import run_batch
        constructed = []
        def forbidden_factory(**kwargs):
            constructed.append(kwargs)
            self.fail('live must reject an injected gateway before constructing it')
        absent = self.data / 'not-prepared'
        with self.assertRaisesRegex(ValueError, 'live source forbids injection'):
            run_batch(absent, 'not-a-scope-hash', source='live', model_factory=forbidden_factory)
        self.assertEqual(constructed, [])
        self.assertFalse(absent.exists())
        self.assertFalse((self.data / 'batch-started.json').exists())
        self.assertFalse((self.data / 'model-calls.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
