"""Offline integration tests through the installed LangChain HTTP boundary."""
import json
import os
import sqlite3
from contextlib import closing

import httpx
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_workbench.development.model import ModelLimitError, ModelUnknownError, ToolModel
from agent_workbench.development.tools import tool_specs


KEY = 'offline-secret-never-in-artifacts'


def grant(**changes):
    return dict(max_calls=3, max_input_bytes=15000, max_output_tokens=128,
                input_usd_per_million='1', cached_input_usd_per_million='0.1',
                output_usd_per_million='2', cost_cap_usd='1', **changes)


def response(*, tool=False, content='done'):
    message = {'role': 'assistant', 'content': content}
    if tool:
        message['tool_calls'] = [{'id': 'call-read', 'type': 'function',
                                 'function': {'name': 'read_file', 'arguments': '{"path":"game.py"}'}}]
    return {'id': 'chat-offline', 'object': 'chat.completion', 'created': 1,
            'model': 'deepseek-flash', 'choices': [{'index': 0, 'message': message,
            'finish_reason': 'tool_calls' if tool else 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110,
                      'prompt_cache_hit_tokens': 40, 'prompt_cache_miss_tokens': 60}}


def model(tmp_path, handler, *, caps=None):
    return ToolModel(tmp_path, caps or grant(), tool_specs(), api_key=KEY,
                     http_client=httpx.Client(transport=httpx.MockTransport(handler)))


class ToolModelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_real_langchain_tools_usage_and_durable_replay(self):
        tmp_path = self.root
        requests = []
        old = os.environ.get('LANGSMITH_TRACING')
        self.addCleanup(lambda: os.environ.pop('LANGSMITH_TRACING', None) if old is None else os.environ.__setitem__('LANGSMITH_TRACING', old))
        os.environ['LANGSMITH_TRACING'] = 'true'
        def handler(request):
            assert os.environ['LANGSMITH_TRACING'] == 'false'
            assert str(request.url) == 'https://api.deepseek.com/chat/completions'
            assert request.headers['authorization'] == 'Bearer ' + KEY
            requests.append(json.loads(request.content))
            return httpx.Response(200, json=response(tool=True))
        first = model(tmp_path, handler)
        messages = [HumanMessage(content='inspect the game')]
        answer = first.complete(messages, 'decision-1')
        assert isinstance(answer, AIMessage)
        assert answer.tool_calls == [{'name': 'read_file', 'args': {'path': 'game.py'},
                                      'id': 'call-read', 'type': 'tool_call'}]
        assert requests[0]['model'] == 'deepseek-flash'
        assert requests[0]['max_tokens'] == 128
        assert requests[0]['tools'][1]['function']['parameters'] == tool_specs()[1]['inputSchema']
        assert first.remaining_calls() == 2
        assert first.summary()['known_cost_usd'] == '0.000084'
        assert model(tmp_path, handler).complete(messages, 'decision-1') == answer
        assert len(requests) == 1
        assert os.environ['LANGSMITH_TRACING'] == 'true'
        with closing(sqlite3.connect(first.budget.database)) as conn:
            usage = json.loads(conn.execute('SELECT usage FROM calls').fetchone()[0])
        assert usage == {'input_tokens': 100, 'output_tokens': 10,
                         'input_tokens_details': {'cached_tokens': 40}}


    def test_changed_request_or_mode_rejected_without_new_call(self):
        tmp_path = self.root
        requests = []
        instance = model(tmp_path, lambda req: (requests.append(req) or httpx.Response(200, json=response())))
        instance.complete([HumanMessage(content='one')], 'same')
        for messages, final in (([HumanMessage(content='two')], False), ([HumanMessage(content='one')], True)):
            with self.assertRaisesRegex(ModelUnknownError, 'decision_request_changed'):
                instance.complete(messages, 'same', final_only=final)
        assert len(requests) == 1


    def _failed_call_does_not_retry(self, failure):
        tmp_path = self.root
        requests = []
        def handler(request):
            requests.append(request)
            if failure == 'timeout':
                raise httpx.ReadTimeout(KEY, request=request)
            return httpx.Response(503, json={'error': {'message': KEY}})
        instance = model(tmp_path, handler)
        for active in (instance, model(tmp_path, handler)):
            with self.assertRaisesRegex(ModelUnknownError, '.') as caught:
                active.complete([HumanMessage(content='one')], 'failure')
            assert KEY not in str(caught.exception)
        assert len(requests) == 1
        assert instance.remaining_calls() == 2
        assert instance.summary()['unknown'] == 1
        for path in tmp_path.iterdir():
            assert KEY.encode() not in path.read_bytes()


    def test_timeout_never_retries_and_error_is_safe(self):
        self._failed_call_does_not_retry('timeout')


    def test_http_failure_never_retries_and_error_is_safe(self):
        self._failed_call_does_not_retry('http')


    def test_crash_after_sending_leaves_unknown_not_automatically_resent(self):
        tmp_path = self.root
        requests = []
        def crash(request):
            requests.append(request)
            raise KeyboardInterrupt()
        instance = model(tmp_path, crash)
        with self.assertRaisesRegex(KeyboardInterrupt, ''):
            instance.complete([HumanMessage(content='one')], 'crash')
        with self.assertRaisesRegex(ModelUnknownError, '.'):
            model(tmp_path, crash).complete([HumanMessage(content='one')], 'crash')
        assert len(requests) == 1
        assert instance.summary()['reserved'] == 1


    def test_received_message_survives_crash_during_usage_accounting(self):
        requests = []
        handler = lambda req: (requests.append(req) or httpx.Response(200, json=response()))
        instance = model(self.root, handler)
        with patch.object(instance.budget, 'finish', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                instance.complete([HumanMessage(content='one')], 'received')
        resumed = model(self.root, handler)
        assert resumed.complete([HumanMessage(content='one')], 'received').content == 'done'
        assert len(requests) == 1
        assert resumed.summary()['completed'] == 1
        assert resumed.summary()['unknown'] == 0


    def test_final_call_keeps_schemas_explicitly_disables_tools_and_rejects_provider_requests(self):
        tmp_path = self.root
        requests = []
        instance = model(tmp_path, lambda req: (requests.append(json.loads(req.content))
                         or httpx.Response(200, json=response(tool=True))))
        with self.assertRaisesRegex(ModelUnknownError, 'unexpected_final_tool_call'):
            instance.complete([HumanMessage(content='summarize')], 'final', final_only=True)
        assert requests[0].get('tool_choice') == 'none'
        assert requests[0]['tools']
        assert requests[0]['parallel_tool_calls'] is False
        assert instance.summary()['failed'] == 1

    def test_dsml_text_is_a_known_protocol_failure_not_a_successful_handoff(self):
        text='<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="read_file">\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>'
        requests=[]
        handler=lambda req: (requests.append(req) or httpx.Response(200,json=response(content=text)))
        first=model(self.root,handler)
        for active in (first,model(self.root,handler)):
            with self.assertRaisesRegex(ModelUnknownError,'unstructured_tool_output') as caught:
                active.complete([HumanMessage(content='交付结论')],'dsml-final',final_only=True)
            assert type(caught.exception).__name__=='ModelProtocolError'
        assert len(requests)==1
        assert first.summary()['failed']==1
        assert first.summary()['unknown']==0
        assert first.summary()['known_cost_usd']=='0.000084'
        with closing(sqlite3.connect(first.budget.database)) as db:
            assert text in json.loads(db.execute('SELECT response FROM model_decisions').fetchone()[0])['data']['content']

    def test_explaining_protocol_markup_inside_normal_prose_is_still_text(self):
        text='这段日志中的 <｜｜DSML｜｜ calls> 是协议文本，不能执行。'
        instance=model(self.root,lambda req:httpx.Response(200,json=response(content=text)))
        assert instance.complete([HumanMessage(content='解释日志')],'explanation',final_only=True).content==text


    def test_valid_tool_conversation_survives_http_boundary(self):
        tmp_path = self.root
        requests = []
        instance = model(tmp_path, lambda req: (requests.append(json.loads(req.content))
                         or httpx.Response(200, json=response())))
        messages = [HumanMessage(content='read'), AIMessage(content='', tool_calls=[
            {'name': 'read_file', 'args': {'path': 'game.py'}, 'id': 'call-read', 'type': 'tool_call'}]),
            ToolMessage(content='print(1)', tool_call_id='call-read')]
        assert instance.complete(messages, 'next', final_only=True).content == 'done'
        assert requests[0]['messages'][-1]['tool_call_id'] == 'call-read'


    def test_budget_and_grant_cannot_reset(self):
        tmp_path = self.root
        calls = []
        caps = grant()
        caps['max_calls'] = 1
        instance = model(tmp_path, lambda req: (calls.append(req) or httpx.Response(200, json=response())), caps=caps)
        instance.complete([HumanMessage(content='one')], 'one', final_only=True)
        assert instance.remaining_calls() == 0
        with self.assertRaisesRegex(ModelLimitError, 'call_budget_exhausted'):
            instance.complete([HumanMessage(content='two')], 'two')
        assert len(calls) == 1
        with self.assertRaisesRegex(ValueError, 'cannot be changed'):
            model(tmp_path, lambda req: None)


    def test_oversized_input_rejected_before_reservation_or_network(self):
        tmp_path = self.root
        calls = []
        instance = model(tmp_path, lambda req: calls.append(req))
        with self.assertRaisesRegex(ModelLimitError, 'input_size_exceeded'):
            instance.complete([HumanMessage(content='x' * 15001)], 'oversize')
        assert instance.summary()['reserved'] == 0
        assert calls == []


    def test_key_cannot_leak_from_provider_message_to_saved_response(self):
        tmp_path = self.root
        instance = model(tmp_path, lambda req: httpx.Response(200, json=response(content=KEY)))
        assert KEY not in instance.complete([HumanMessage(content='one')], 'one').content
        for path in tmp_path.iterdir():
            assert KEY.encode() not in path.read_bytes()


if __name__ == "__main__":
    unittest.main()
