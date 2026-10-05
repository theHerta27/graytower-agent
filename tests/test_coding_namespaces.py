"""Namespacing cannot change native arguments or grant a missing tool."""
from copy import deepcopy
import unittest

from agent_workbench.coding.response_namespaces import provider_request, runtime_event


def function(name):
    return {'type': 'function', 'name': name, 'description': 'Native tool', 'strict': False,
            'parameters': {'type': 'object', 'properties': {'fork_context': {'type': 'boolean'},
                           'message': {'type': 'string'}}, 'additionalProperties': False}}


def request():
    return {'model': 'deepseek-flash', 'stream': True, 'max_output_tokens': 2048,
            'tools': [{'type': 'namespace', 'name': 'multi_agent_v1', 'description': 'Native delegation',
                       'tools': [function(n) for n in ('close_agent', 'resume_agent', 'send_input',
                                                      'spawn_agent', 'wait_agent')]},
                      {'type': 'namespace', 'name': 'mcp__coding_readonly',
                       'tools': [function('read_file')]}, function('edit_text')],
            'input': [{'type': 'function_call', 'namespace': 'multi_agent_v1', 'name': 'spawn_agent',
                       'call_id': 'call-original', 'id': 'fc-original',
                       'arguments': '{ "fork_context": true, "message": "Investigate freely" }'},
                      {'type': 'function_call_output', 'call_id': 'call-original',
                       'output': '{"namespace":"leave user content unchanged","name":"spawn_agent"}'}]}


class CodingNamespaceTests(unittest.TestCase):
    def test_native_catalog_and_history_flatten_without_restricting_arguments(self):
        original = request()
        before = deepcopy(original)
        mapped, mapping = provider_request(original)
        self.assertEqual([t['name'] for t in mapped['tools']], [
            'multi_agent_v1__close_agent', 'multi_agent_v1__resume_agent', 'multi_agent_v1__send_input',
            'multi_agent_v1__spawn_agent', 'multi_agent_v1__wait_agent',
            'mcp__coding_readonly__read_file', 'edit_text'])
        self.assertTrue(all(t['type'] == 'function' for t in mapped['tools']))
        self.assertEqual(mapped['tools'][3], function('multi_agent_v1__spawn_agent'))
        self.assertEqual(mapped['input'][0], {
            'type': 'function_call', 'name': 'multi_agent_v1__spawn_agent', 'call_id': 'call-original',
            'id': 'fc-original', 'arguments': '{ "fork_context": true, "message": "Investigate freely" }'})
        self.assertEqual(mapped['input'][1], original['input'][1])
        self.assertEqual(original, before)
        mapped['tools'][0]['parameters']['properties'].clear()
        self.assertEqual(original, before)

    def test_stream_items_and_final_usage_restore_without_touching_arguments_or_ids(self):
        _, mapping = provider_request(request())
        item = {'type': 'function_call', 'name': 'mcp__coding_readonly__read_file',
                'call_id': 'keep-call', 'id': 'keep-item', 'arguments': ' {"path":"x"} ',
                'status': 'completed'}
        expected = item | {'name': 'read_file', 'namespace': 'mcp__coding_readonly'}
        for event_type in ('response.output_item.added', 'response.output_item.done'):
            with self.subTest(event_type=event_type):
                event = {'type': event_type, 'sequence_number': 7, 'output_index': 2, 'item': item}
                self.assertEqual(runtime_event(event, mapping), event | {'item': expected})
                self.assertNotIn('namespace', event['item'])
        usage = {'input_tokens': 9, 'output_tokens': 3, 'total_tokens': 12,
                 'input_tokens_details': {'cached_tokens': 4}}
        for event_type in ('response.completed', 'response.incomplete', 'response.failed'):
            event = {'type': event_type, 'response': {'id': 'resp-keep', 'usage': usage, 'output': [item]}}
            self.assertEqual(runtime_event(event, mapping), {
                'type': event_type, 'response': {'id': 'resp-keep', 'usage': usage, 'output': [expected]}})

    def test_name_on_arguments_done_restores_but_delta_and_text_are_opaque(self):
        _, mapping = provider_request(request())
        event = {'type': 'response.function_call_arguments.done', 'item_id': 'fc-1',
                 'name': 'multi_agent_v1__spawn_agent', 'arguments': '{"fork_context":true}'}
        self.assertEqual(runtime_event(event, mapping), event | {
            'name': 'spawn_agent', 'namespace': 'multi_agent_v1'})
        delta = {'type': 'response.function_call_arguments.delta', 'item_id': 'fc-1',
                 'delta': '{"namespace":"multi_agent_v1","name":"spawn_agent"}'}
        self.assertEqual(runtime_event(delta, mapping), delta)

    def test_fork_history_does_not_reauthorize_parent_tools(self):
        body = request()
        body['tools'] = [function('edit_text')]
        mapped, mapping = provider_request(body)
        self.assertEqual(mapped['input'][0]['name'], 'multi_agent_v1__spawn_agent')
        with self.assertRaisesRegex(ValueError, 'advertised'):
            runtime_event({'type': 'response.output_item.done', 'item': {
                'type': 'function_call', 'name': 'multi_agent_v1__spawn_agent',
                'call_id': 'escape', 'arguments': '{}'}}, mapping)

    def test_unknown_namespaces_and_colliding_declarations_fail_closed(self):
        cases = []
        bad = request();bad['tools'][0]['name'] = 'other_namespace';cases.append(bad)
        bad = request();bad['input'][0]['namespace'] = 'other_namespace';cases.append(bad)
        bad = request();bad['tools'].append(function('multi_agent_v1__spawn_agent'));cases.append(bad)
        bad = request();bad['tools'].append(function('edit_text'));cases.append(bad)
        bad = request();bad['tools'][0]['tools'].append(function('spawn_agent'));cases.append(bad)
        for body in cases:
            with self.subTest(body=body), self.assertRaises(ValueError):
                provider_request(body)

    def test_response_unadvertised_or_injected_namespace_fails_closed(self):
        _, mapping = provider_request(request())
        for changes in ({'name': 'shell_command'}, {'name': 'spawn_agent'},
                        {'name': 'edit_text', 'namespace': 'other_namespace'},
                        {'name': 'edit_text', 'namespace': 'multi_agent_v1'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                runtime_event({'type': 'response.output_item.done', 'item': {
                    'type': 'function_call', 'call_id': 'x', 'arguments': '{}'} | changes}, mapping)

    def test_custom_or_builtin_tool_response_cannot_bypass_function_allowlist(self):
        _, mapping = provider_request(request())
        for tool_type in ('custom_tool_call', 'web_search_call', 'computer_call'):
            with self.subTest(tool_type=tool_type), self.assertRaisesRegex(ValueError, 'advertised'):
                runtime_event({'type': 'response.output_item.done', 'item': {
                    'type': tool_type, 'name': 'apply_patch', 'call_id': 'x', 'input': 'write'}}, mapping)

    def test_provider_128_character_limit_applies_after_flattening(self):
        for namespace, limit in ((None, 128), ('multi_agent_v1', 112), ('mcp__coding_readonly', 106)):
            tool = function('x' * limit)
            body = {'tools': [tool if namespace is None else {
                'type': 'namespace', 'name': namespace, 'tools': [tool]}]}
            mapped, _ = provider_request(body)
            self.assertEqual(len(mapped['tools'][0]['name']), 128)
            tool['name'] += 'x'
            with self.assertRaisesRegex(ValueError, '128'):
                provider_request(body)
        for name in ('', 'a.b', '含中文', 'x\n'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                provider_request({'tools': [function(name)]})

    def test_parameters_are_not_rebuilt_and_tool_choice_uses_same_mapping(self):
        body = request()
        body['tools'][0]['tools'][3]['parameters'] = {'oneOf': [{'type': 'string'}, {'type': 'integer'}]}
        body['tool_choice'] = {'type': 'function', 'namespace': 'multi_agent_v1', 'name': 'spawn_agent'}
        mapped, _ = provider_request(body)
        self.assertEqual(mapped['tools'][3]['parameters'], {'oneOf': [{'type': 'string'}, {'type': 'integer'}]})
        self.assertEqual(mapped['tool_choice'], {'type': 'function', 'name': 'multi_agent_v1__spawn_agent'})
        body['tool_choice']['name'] = 'unadvertised'
        with self.assertRaises(ValueError):
            provider_request(body)


if __name__ == '__main__':
    unittest.main()
