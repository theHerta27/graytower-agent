"""Real LangChain wire with offline HTTP; no paid calls or model-quality claims."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import httpx
from pydantic import BaseModel, ConfigDict, StrictInt

from agent_workbench.models import ModelGateway, ModelResponseError


class Choice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: StrictInt


class JsonDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.requests = []

    def gateway(self, content, *, finish='stop', tools=None, extra_choices=None, **options):
        def respond(request):
            self.requests.append(json.loads(request.content))
            message = {'role': 'assistant', 'content': content}
            if tools is not None:
                message['tool_calls'] = tools
            return httpx.Response(200, json={
                'id': 'offline-json', 'object': 'chat.completion', 'model': 'deepseek-flash',
                'choices': [{'index': 0, 'finish_reason': finish, 'message': message}] + (extra_choices or []),
                'usage': {'prompt_tokens': 17, 'completion_tokens': 9, 'total_tokens': 26}})
        client = httpx.Client(transport=httpx.MockTransport(respond))
        self.addCleanup(client.close)
        return ModelGateway(api_key='sk-offline-json-fixture', http_client=client,
                            audit_path=self.root / f'calls-{len(self.requests)}.jsonl', **options)

    def test_default_json_wire_matches_preview_and_preserves_context(self):
        gateway = self.gateway('{"value": 2}', max_calls=1)
        messages = [{'role': 'system', 'content': 'Choose one permitted integer.'},
                    {'role': 'user', 'content': '请选择 2。'}]
        original = deepcopy(messages)
        preview = gateway.preview(messages, Choice)
        self.assertEqual(preview['payload'].get('response_format'), {'type': 'json_object'})
        self.assertNotIn('tools', preview['payload'])
        self.assertNotIn('tool_choice', preview['payload'])
        self.assertIn('"value"', preview['payload']['messages'][0]['content'])
        self.assertEqual(preview['payload']['messages'][1:], original)
        self.assertEqual(gateway.complete(messages, Choice), {'value': 2})
        self.assertEqual(self.requests, [preview['payload']])
        self.assertEqual(messages, original)
        self.assertEqual(gateway.remaining_calls(), 0)
        self.assertEqual(gateway.calls[-1]['usage']['total_tokens'], 26)
        self.assertEqual(gateway.calls[-1]['output_method'], 'json_mode')

    def test_invalid_json_is_not_repaired_or_first_selected_by_parser(self):
        invalid = ['', '{"value": 2', '```json\n{"value": 2}\n```',
                   '{"value": 2} {"value": 3}', '[{"value": 2}]',
                   '{"value": 1,"value": 2}', '{"value": NaN}',
                   '{"value": "2"}', '{"value": 2,"extra": true}']
        for content in invalid:
            with self.subTest(content=content):
                gateway = self.gateway(content, max_calls=1)
                before = len(self.requests)
                with self.assertRaises(ModelResponseError):
                    gateway.complete([{'role': 'user', 'content': 'Choose 2.'}], Choice)
                self.assertEqual(len(self.requests), before + 1, 'no hidden fallback/retry')
                self.assertEqual(gateway.calls[-1]['status'], 'failed')

                self.assertEqual(gateway.calls[-1]['raw']['content'], content)
                self.assertEqual(gateway.calls[-1]['usage']['total_tokens'], 26)
                self.assertEqual(gateway.remaining_calls(), 0)

    def test_valid_object_with_truncation_or_tool_call_is_not_a_complete_decision(self):
        call = {'id': 'unexpected', 'type': 'function', 'function': {
            'name': 'Choice', 'arguments': '{"value":2}'}}
        for finish, tools in [('length', None), ('content_filter', None), ('stop', [call])]:
            with self.subTest(finish=finish, tools=tools):
                gateway = self.gateway('{"value":2}', finish=finish, tools=tools)
                with self.assertRaises(ModelResponseError):
                    gateway.complete([{'role': 'user', 'content': 'Choose 2.'}], Choice)
                self.assertEqual(gateway.calls[-1]['status'], 'failed')
                self.assertEqual(gateway.calls[-1]['usage']['total_tokens'], 26)
                self.assertEqual(gateway.calls[-1]['raw']['finish_reason'], finish)

    def test_overflowing_json_number_is_rejected_before_domain_execution(self):
        class Number(BaseModel):
            value: float
        gateway = self.gateway('{"value":1e999}')
        with self.assertRaises(ModelResponseError):
            gateway.complete([{'role': 'user', 'content': 'A finite value.'}], Number)

    def test_multiple_completion_choices_never_silently_select_the_first(self):
        for finish in ('stop', 'length'):
            with self.subTest(second_finish=finish):
                gateway = self.gateway('{"value":1}', extra_choices=[{
                    'index': 1, 'finish_reason': finish,
                    'message': {'role': 'assistant', 'content': '{"value":2}'}}])
                with self.assertRaises(ModelResponseError):
                    gateway.complete([{'role': 'user', 'content': 'Choose one.'}], Choice)
                self.assertEqual(gateway.calls[-1]['status'], 'failed')
                self.assertEqual(len(gateway.calls[-1]['raw_choices']), 2)
                self.assertEqual(gateway.calls[-1]['usage']['total_tokens'], 26)

    def test_schema_instruction_is_included_in_input_limit_before_reservation(self):
        gateway = self.gateway('{"value":2}', max_input_chars=100)
        with self.assertRaisesRegex(ValueError, 'input'):
            gateway.complete([{'role': 'user', 'content': '2'}], Choice)
        self.assertEqual(self.requests, [])
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
