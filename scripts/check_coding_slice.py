"""Offline integration: real SDK/Runtime/MCP and file edit, scripted model only.

This is NOT a real Agent acceptance demonstration or quality comparison.
"""
import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
from contextlib import nullcontext
from urllib.request import Request, urlopen

from agent_workbench.coding.candidates import CodingWorkspace
from agent_workbench.coding.runtime_adapter import run_runtime, validate_runtime_receipt
from agent_workbench.coding.responses_transport import responses_endpoint, encoded
from agent_workbench.domain import CandidateRepository


def find_tool(body, fragment):
    for tool in body.get('tools', []):
        if tool.get('type') == 'namespace':
            for nested in tool['tools']:
                if fragment in nested.get('name', ''):
                    return nested['name'], tool['name']
        elif fragment in tool.get('name', ''):
            return tool['name'], None
    raise AssertionError('required tool not advertised: ' + fragment)


def tool_value(output):
    assert isinstance(output, str)
    value = json.loads(output.split('\nOutput:\n', 1)[-1])
    assert isinstance(value, dict) and not value.get('isError')
    return value


def main(out: Path, runtime_python: Path, mode: str, relay: bool):
    out.mkdir(parents=True, exist_ok=False)
    data = out / 'data'
    repo = CandidateRepository(data)
    workspace = CodingWorkspace.prepare(out / 'workspace', repo)
    file = workspace.root / 'configs/combat/v2/baseline.json'
    original = file.read_bytes()
    old = original.decode('utf-8')
    assert old.count('"multiplier": 1.4,') == 1
    requests, errors = [], []

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            try:
                assert self.path == '/responses'
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(body)
                (out / 'requests.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding='utf-8')
                assert body['model'] == 'deepseek-flash'
                index = len(requests)
                outputs = {entry['call_id']: entry['output'] for entry in body.get('input', [])
                           if entry.get('type') == 'function_call_output'}
                for read_id in ('read', 'child_read'):
                    if read_id in outputs:
                        read = tool_value(outputs[read_id])
                        assert read['sha256'] == hashlib.sha256(original).hexdigest()
                        assert read['text'] == old
                if 'edit' in outputs:
                    assert tool_value(outputs['edit'])['status'] == 'completed'
                if 'check' in outputs:
                    assert tool_value(outputs['check']) == workspace.inspect_changes()
                users = [entry for entry in body.get('input', []) if entry.get('role') == 'user']
                latest = json.dumps(users[-1], ensure_ascii=False) if users else ''
                operation = None
                review_phase = 'Review only this bounded configuration edit' in latest
                child = 'CHILD_BOUNDARY_FIXTURE_1' in latest and not review_phase
                if child:
                    if 'child_read' not in outputs:
                        operation = ('read_file', {'path': 'configs/combat/v2/baseline.json'}, 'child_read')
                    else:
                        assert '1.4' in str(outputs['child_read'])
                elif not review_phase:
                    if mode == 'auto' and 'spawn' not in outputs:
                        operation = ('spawn_agent', {'message': 'CHILD_BOUNDARY_FIXTURE_1: Read the file and report the unchanged SP cost and toughness reduction; do not edit.',
                                                     'fork_context': False}, 'spawn')
                    elif mode == 'auto' and 'wait' not in outputs:
                        agent_id = json.loads(outputs['spawn'])['agent_id']
                        operation = ('wait_agent', {'targets': [agent_id], 'timeout_ms': 10000}, 'wait')
                    elif mode == 'auto' and 'close' not in outputs:
                        agent_id = json.loads(outputs['spawn'])['agent_id']
                        operation = ('close_agent', {'target': agent_id}, 'close')
                    elif 'read' not in outputs:
                        operation = ('read_file', {'path': 'configs/combat/v2/baseline.json'}, 'read')
                    elif 'edit' not in outputs:
                        operation = ('edit_text', {'path': 'configs/combat/v2/baseline.json',
                                                  'expected_sha256': hashlib.sha256(original).hexdigest(),
                                                  'old_text': '"multiplier": 1.4,', 'new_text': '"multiplier": 1.58,'}, 'edit')
                    elif 'check' not in outputs:
                        operation = ('check_workspace', {}, 'check')
                if operation:
                    fragment, args, call_id = operation
                    name, namespace = find_tool(body, fragment)
                    item = {'type': 'function_call', 'name': name, 'arguments': json.dumps(args),
                            'id': 'fc_' + str(index), 'call_id': call_id}
                    if namespace:
                        item['namespace'] = namespace
                else:
                    message = ('{"findings":[],"overall_correctness":"patch is correct","overall_explanation":"Scripted fixture only, not model review.","overall_confidence_score":1.0}' if review_phase else
                               'Fixture child: SP cost 1 and toughness reduction 90 remain unchanged.' if child else
                               'Fixture: edited multiplier and checked the complete workspace.')
                    item = {'type': 'message', 'role': 'assistant', 'id': 'msg_' + str(index),
                            'content': [{'type': 'output_text', 'text': message}]}
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close')
                self.end_headers()
                response = {'id': 'resp_' + str(index)}
                events = [{'type': 'response.created', 'response': response},
                          {'type': 'response.output_item.added', 'output_index': 0, 'item': item},
                          {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                          {'type': 'response.completed', 'response': response | {'output': [item],
                            'usage': {'input_tokens': 10, 'output_tokens': 10, 'total_tokens': 20}}}]
                for event in events:
                    self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode())
                    self.wfile.flush()
            except Exception as exc:
                errors.append(repr(exc))
                self.send_error(500, 'fixture failed')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        fixture_url = f'http://127.0.0.1:{server.server_port}'
        def sender(body):
            with urlopen(Request(fixture_url + '/responses', data=encoded(body),
                                headers={'Content-Type': 'application/json'}), timeout=30) as response:
                return response.read()
        grant = {'max_calls': 16, 'max_input_bytes': 70000, 'max_output_tokens': 2048,
                 'cost_cap_usd': '0.40', 'authorization_sha256': 'fixture-no-external-authorization',
                 'input_usd_per_million': '0.30', 'cached_input_usd_per_million': '0.006',
                 'output_usd_per_million': '1.20'}
        context = responses_endpoint(out / 'fixture-transport', grant, sender) if relay else nullcontext((fixture_url, None))
        with context as (endpoint, budget):
            result = run_runtime(runtime_python=runtime_python, tools_python=Path(sys.executable),
                                 workspace=workspace.root, data=data, control=out / 'control', preparation=workspace.preparation,
                                 endpoint=endpoint, mode=mode,
                                 prompt='将击破手战技倍率从 1.4 改为 1.58，其他内容不变，检查后交付。', timeout_seconds=90)
        budget_summary = budget.summary() if budget else None
        assert result['status'] == 'completed', result
        assert not errors, errors
        assert len(requests) == (5 if mode == 'single' else 10), len(requests)
        inspected = workspace.inspect_changes()
        assert inspected['diff'][0]['after'] == 1.58
        validate_runtime_receipt(result, inspected)
        receipt = repo.artifacts.put(result, 'coding-runtime-receipt-v1')
        candidate = workspace.import_candidate('将击破手战技倍率从 1.4 改为 1.58，其他内容不变。',
                                              {'source': 'scripted_fixture', 'runtime_receipt': receipt})
        result = {'source': 'scripted fixture, NOT real model or model review', 'mode': mode, 'external_calls': 0,
                  'namespace_transport': relay, 'fixture_budget': budget_summary,
                  'battle_count': 0, 'request_count': len(requests), 'runtime_status': result['status'],
                  'candidate': candidate, 'inspection': inspected}
        (out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'passed': True, 'manifest_hash': candidate['manifest_hash'], 'out': str(out)}))
    finally:
        server.shutdown()
        server.server_close()
        (out / 'fixture-errors.json').write_text(json.dumps(errors), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--runtime-python', default=Path('research/.venv-coding/Scripts/python.exe'), type=Path)
    parser.add_argument('--mode', choices=['single', 'auto'], default='single')
    parser.add_argument('--relay', action='store_true')
    args = parser.parse_args()
    main(args.out.resolve(), args.runtime_python.resolve(), args.mode, args.relay)
