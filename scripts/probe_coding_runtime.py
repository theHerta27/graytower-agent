"""Offline G0-C probe: released SDK/default CLI, real native tools, scripted model.

Run with research/.venv-coding/Scripts/python.exe -B. No credentials or external
model endpoint are used. Every run has a new directory; failed evidence remains.
The fixture tests protocol/permissions, never coding or model quality.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'deepseek-flash'
TOKEN = 'OFFLINE_MCP_SENTINEL_73129'


def save(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mcp_fixture(args):
    """Small real stdio MCP endpoint; only a fixed read-only sentinel is exposed."""
    for line in sys.stdin:
        message = json.loads(line)
        with args.audit.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'message': message}) + '\n')
        if 'id' not in message:
            continue
        method = message.get('method')
        if method == 'initialize':
            result = {'protocolVersion': message['params']['protocolVersion'],
                      'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'coding-offline-sentinel', 'version': '1'}}
        elif method == 'tools/list':
            result = {'tools': [{'name': 'read_sentinel', 'description': 'Read fixed offline sentinel',
                      'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
                      'annotations': {'readOnlyHint': True, 'destructiveHint': False}}]}
        elif method == 'tools/call' and message['params'].get('name') == 'read_sentinel':
            result = {'content': [{'type': 'text', 'text': args.sentinel.read_text(encoding='utf-8')}],
                      'isError': False}
        else:
            print(json.dumps({'jsonrpc': '2.0', 'id': message['id'],
                              'error': {'code': -32601, 'message': 'fixture method denied'}}), flush=True)
            continue
        print(json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': result}), flush=True)


def tool_entries(body):
    entries = []
    for tool in body.get('tools', []):
        if tool.get('type') == 'namespace':
            entries.extend((tool['name'], inner) for inner in tool.get('tools', []))
        else:
            entries.append((None, tool))
    return entries


def call(body, name, arguments, call_id, *, undeclared=False):
    matches = [(ns, t) for ns, t in tool_entries(body)
               if t.get('name') == name or t.get('name', '').endswith('__' + name)]
    if not matches and not undeclared:
        raise AssertionError('required tool unavailable: ' + name)
    namespace, tool = matches[0] if matches else (None, {'name': name})
    item = {'type': 'function_call', 'name': tool['name'], 'arguments': json.dumps(arguments),
            'call_id': call_id, 'id': 'fc_' + call_id}
    if namespace:
        item['namespace'] = namespace
    return item


def answer(text):
    return {'type': 'message', 'role': 'assistant', 'id': 'msg_' + str(time.time_ns()),
            'content': [{'type': 'output_text', 'text': text}]}


class Fixture(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, scenario, outside):
        super().__init__(('127.0.0.1', 0), FixtureHandler)
        self.scenario, self.outside = scenario, outside
        self.requests, self.errors = [], []
        self.lock = threading.Lock()

    def decide(self, body):
        assert body.get('model') == MODEL, 'model route not allowlisted'
        assert len(self.requests) <= 32, 'fixture request cap exceeded'
        outputs = {i['call_id']: i['output'] for i in body.get('input', [])
                   if i.get('type') == 'function_call_output'}
        users = [i for i in body.get('input', []) if i.get('role') == 'user']
        latest = json.dumps(users[-1], ensure_ascii=False) if users else ''
        if self.scenario == 'review':
            return answer(json.dumps({'findings': [], 'overall_correctness': 'patch is correct',
                'overall_explanation': 'Scripted offline review, not a quality assessment.',
                'overall_confidence_score': 1.0}))
        child_kind = next((x for x in ('FRESH', 'FORK') if 'CHILD_' + x + '_73129' in latest), None)
        if child_kind:
            prefix = child_kind.lower()
            if prefix + '_edit' in outputs:
                return answer('CHILD_' + child_kind + '_DONE_' + TOKEN)
            if prefix + '_read' in outputs:
                assert TOKEN in json.dumps(outputs[prefix + '_read'])
                return call(body, 'edit_text', {'path': 'editable.txt', 'text': 'CHILD_WRITE_DENIED'},
                            prefix + '_edit', undeclared=True)
            return call(body, 'read_sentinel', {}, prefix + '_read')
        if self.scenario == 'single':
            if 'forbidden_shell' in outputs:
                return answer('SINGLE_OFFLINE_DONE')
            if 'outside_edit' in outputs:
                return call(body, 'shell_command', {'command': 'Set-Content -LiteralPath ' +
                    "'" + str(self.outside).replace("'", "''") + "' -Value FORBIDDEN_SHELL_WRITE"},
                    'forbidden_shell', undeclared=True)
            if 'main_edit' in outputs:
                return call(body, 'edit_text', {'path': '../outside.txt', 'text': 'FORBIDDEN_PATH_WRITE'}, 'outside_edit')
            return call(body, 'edit_text', {'path': 'editable.txt', 'text': 'MAIN_ALLOWED'}, 'main_edit')
        # Native lifecycle only. The fixture supplies decisions, Runtime creates,
        # waits for and closes the real child threads; no child result is forged.
        for kind in ('fresh', 'fork'):
            if kind + '_close' in outputs:
                continue
            if kind + '_wait' in outputs:
                assert 'CHILD_' + kind.upper() + '_DONE_' + TOKEN in json.dumps(outputs[kind + '_wait'])
                agent_id = json.loads(outputs[kind + '_spawn'])['agent_id']
                return call(body, 'close_agent', {'target': agent_id}, kind + '_close')
            if kind + '_spawn' in outputs:
                agent_id = json.loads(outputs[kind + '_spawn'])['agent_id']
                return call(body, 'wait_agent', {'targets': [agent_id], 'timeout_ms': 10000}, kind + '_wait')
            return call(body, 'spawn_agent', {'message': 'CHILD_' + kind.upper() + '_73129: offline read probe.',
                        'fork_context': kind == 'fork'}, kind + '_spawn')
        return answer('AUTO_OFFLINE_DONE')


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        try:
            assert self.path == '/responses'
            length = int(self.headers['Content-Length'])
            assert 0 < length < 2_000_000
            body = json.loads(self.rfile.read(length))
            with self.server.lock:
                self.server.requests.append(body)
            item = self.server.decide(body)
            rid = 'offline_' + str(time.time_ns())
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            for event in [
                {'type': 'response.created', 'response': {'id': rid}},
                {'type': 'response.output_item.added', 'output_index': 0, 'item': item},
                {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                {'type': 'response.completed', 'response': {'id': rid, 'output': [item],
                  'usage': {'input_tokens': 10, 'output_tokens': 3, 'total_tokens': 13}}}]:
                self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode())
                self.wfile.flush()
        except Exception as exc:
            self.server.errors.append(type(exc).__name__ + ': ' + str(exc))
            self.send_error(500, 'offline fixture assertion failed')


def catalog():
    return {'models': [{'slug': MODEL, 'display_name': 'DeepSeek route offline fixture',
        'description': 'Scripted protocol fixture; no model quality evidence',
        'default_reasoning_level': 'low', 'supported_reasoning_levels': [{'effort': 'low', 'description': 'low'}],
        'shell_type': 'shell_command', 'visibility': 'list', 'supported_in_api': True,
        'priority': 1, 'availability_nux': None, 'upgrade': None, 'support_verbosity': False,
        'default_verbosity': None, 'apply_patch_tool_type': None, 'web_search_tool_type': 'text',
        'truncation_policy': {'mode': 'tokens', 'limit': 10000}, 'context_window': 1048576,
        'experimental_supported_tools': [], 'input_modalities': ['text'], 'tool_mode': 'direct',
        'multi_agent_version': 'v1', 'auto_review_model_override': MODEL,
        'model_messages': {'instructions_template': 'You are an offline protocol test assistant.'},
        'supports_reasoning_summary_parameter': False}]}


def run_case(out, scenario):
    from openai_codex.client import CodexClient, CodexConfig
    from openai_codex.generated.v2_all import ReviewStartResponse
    home, work = out / 'home', out / 'workspace'
    home.mkdir(parents=True);work.mkdir()
    (work / 'sentinel.txt').write_text(TOKEN, encoding='utf-8')
    (work / 'editable.txt').write_text('ORIGINAL', encoding='utf-8')
    outside = out / 'outside.txt';outside.write_text('PROTECTED', encoding='utf-8')
    save(home / 'models.json', catalog())
    server = Fixture(scenario, outside)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = [f'model="{MODEL}"', f'review_model="{MODEL}"', 'model_provider="offline_deepseek"',
        'model_catalog_json=' + json.dumps(str(home / 'models.json')), 'approval_policy="never"',
        'approvals_reviewer="user"', 'sandbox_mode="read-only"', 'web_search="disabled"',
        'check_for_update_on_startup=false', '[analytics]', 'enabled=false',
        '[features]', 'shell_tool=false', 'apps=false', 'plugins=false', 'memories=false',
        'goals=false', 'code_mode=false', 'multi_agent_v2=false',
        '[agents]', 'enabled=' + str(scenario == 'auto').lower(),
        'max_concurrent_threads_per_session=2', f'default_subagent_model="{MODEL}"',
        '[model_providers.offline_deepseek]', 'name="Loopback fixture only"',
        f'base_url="http://127.0.0.1:{server.server_address[1]}"', 'wire_api="responses"',
        'requires_openai_auth=false', 'supports_websockets=false', 'request_max_retries=0', 'stream_max_retries=0',
        '[mcp_servers.sentinel]', 'command=' + json.dumps(sys.executable),
        'args=' + json.dumps(['-B', str(Path(__file__).resolve()), '--mcp-server', '--audit',
                             str(out / 'mcp.jsonl'), '--sentinel', str(work / 'sentinel.txt')]),
        'startup_timeout_sec=15', 'tool_timeout_sec=5', 'enabled_tools=["read_sentinel"]']
    (home / 'config.toml').write_text('\n'.join(config), encoding='utf-8')
    seen, inbox, handlers = [], queue.Queue(), []
    main_id = None

    def handler(method, params):
        row = {'method': method, 'params': params};handlers.append(row)
        if method != 'item/tool/call':
            row['denied'] = 'approval_or_unknown_request'
            return {'decision': 'decline'}
        allowed = (params.get('threadId') == main_id and params.get('tool') == 'edit_text'
                   and params.get('namespace') is None and params.get('arguments', {}).get('path') == 'editable.txt'
                   and params.get('arguments', {}).get('text') == 'MAIN_ALLOWED')
        if allowed:
            (work / 'editable.txt').write_text('MAIN_ALLOWED', encoding='utf-8')
        row['allowed'] = allowed
        return {'success': allowed, 'contentItems': [{'type': 'inputText',
                'text': 'EDIT_RECORDED' if allowed else 'EDIT_SCOPE_DENIED'}]}

    client = CodexClient(CodexConfig(cwd=str(work), env={'CODEX_HOME': str(home),
        'NO_PROXY': '127.0.0.1,localhost'}), approval_handler=handler)
    result = {'scenario': scenario, 'source': 'fixture', 'external_model_calls': 0}
    def collect(turn_id=None):
        try:
            while True:
                notification = (client.next_turn_notification(turn_id) if turn_id
                                else client.next_notification())
                row = {'method': notification.method,
                       'params': notification.payload.model_dump(mode='json', by_alias=True)}
                seen.append(row);inbox.put(row)
        except BaseException:
            pass
    try:
        client.start();result['initialize'] = client.initialize().model_dump(mode='json')
        threading.Thread(target=collect, daemon=True).start()
        started = client.thread_start({'cwd': str(work), 'model': MODEL, 'modelProvider': 'offline_deepseek',
            'ephemeral': False,
            'allowProviderModelFallback': False, 'sandbox': 'read-only', 'approvalPolicy': 'never',
            'approvalsReviewer': 'user', 'dynamicTools': [{'type': 'function', 'name': 'edit_text',
                'description': 'Edit only the owned offline sentinel; main thread only',
                'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'},
                    'text': {'type': 'string'}}, 'required': ['path', 'text'], 'additionalProperties': False}}]})
        main_id = started.thread.id;result['thread_id'] = main_id
        if scenario == 'review':
            # Product Review follows a completed author turn. Starting Review
            # on a brand-new empty thread exposes an unrelated materialization
            # edge in 0.160.0 (retained in offline-r3..r6 evidence).
            initial = client.turn_start(main_id, 'REVIEW_MATERIALIZE_73129')
            threading.Thread(target=collect, args=(initial.turn.id,), daemon=True).start()
            initial_deadline = time.monotonic() + 30
            while True:
                row = inbox.get(timeout=max(.1, initial_deadline - time.monotonic()))
                if row['method'] == 'turn/completed' and row['params']['turn']['id'] == initial.turn.id:
                    result['initial_turn_status'] = row['params']['turn']['status']
                    assert result['initial_turn_status'] == 'completed'
                    break
            turn = client.request('review/start', {'threadId': main_id,
                'target': {'type': 'custom', 'instructions': 'Offline routing check; return no findings.'}},
                response_model=ReviewStartResponse)
        else:
            turn = client.turn_start(main_id, 'PARENT_OFFLINE_' + scenario.upper() + '_73129')
        result['started'] = turn.model_dump(mode='json', by_alias=True)
        turn_id = turn.turn.id
        deadline = time.monotonic() + 50
        if scenario == 'review':
            # The release's generic request() does not reserve a turn stream.
            # Unsubscribed turn events are pruned, so subscribing after the
            # response can race a fast completion. Public persisted state is
            # authoritative here; do not patch the SDK's private router.
            while time.monotonic() < deadline:
                try:
                    snapshot = client.thread_read(turn.review_thread_id, include_turns=True)
                except Exception as exc:
                    # A review on a brand-new thread races its first rollout
                    # materialization. Retain the observed transitional error.
                    if 'is not materialized yet' not in str(exc):
                        raise
                    result.setdefault('review_pending_errors', []).append(str(exc))
                    time.sleep(.1)
                    continue
                matched = [t for t in snapshot.thread.turns if t.id == turn_id]
                status = matched[0].model_dump(mode='json')['status'] if matched else None
                if status and status != 'inProgress':
                    result['turn_status'] = status
                    result['review_snapshot'] = snapshot.model_dump(mode='json', by_alias=True)
                    break
                time.sleep(.1)
            else:
                raise TimeoutError('offline review timed out')
        else:
            threading.Thread(target=collect, args=(turn_id,), daemon=True).start()
            while time.monotonic() < deadline:
                row = inbox.get(timeout=max(.1, deadline - time.monotonic()))
                if row['method'] == 'turn/completed' and row['params']['turn']['id'] == turn_id:
                    result['turn_status'] = row['params']['turn']['status'];break
            else:
                raise TimeoutError('offline turn timed out')
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        client.close();server.shutdown();server.server_close()
        result['requests'] = len(server.requests)
        result['fixture_errors'] = server.errors
        result['checks'] = {
            'turn_completed': result.get('turn_status') == 'completed',
            'fixture_no_errors': not server.errors,
            'all_requests_deepseek_route': bool(server.requests) and all(r['model'] == MODEL for r in server.requests),
            'shell_and_apply_patch_not_advertised': all(t.get('name') not in
                {'shell_command', 'shell', 'exec_command', 'apply_patch'} for r in server.requests for _,t in tool_entries(r)),
            'outside_sentinel_unchanged': outside.read_text(encoding='utf-8') == 'PROTECTED',
            'main_edit_only': (work / 'editable.txt').read_text(encoding='utf-8') ==
                ('MAIN_ALLOWED' if scenario == 'single' else 'ORIGINAL')}
        if scenario == 'single':
            result['checks']['native_spawn_not_advertised'] = not any(t.get('name') == 'spawn_agent'
                for r in server.requests for _,t in tool_entries(r))
            result['checks']['main_thread_id_seen'] = any(h.get('allowed') and h['params']['threadId'] == main_id for h in handlers)
            result['checks']['path_escape_denied'] = any(h.get('allowed') is False and h['params'].get('arguments',{}).get('path') == '../outside.txt' for h in handlers)
        if scenario == 'auto':
            result['checks']['fresh_and_fork_completed'] = any('AUTO_OFFLINE_DONE' in json.dumps(e) for e in seen)
            result['checks']['child_dynamic_edit_denied'] = any(h.get('allowed') is False and
                h['params'].get('threadId') != main_id for h in handlers)
            for kind in ('FRESH', 'FORK'):
                child_requests = []
                for request in server.requests:
                    users = [i for i in request.get('input', []) if i.get('role') == 'user']
                    if users and 'CHILD_' + kind + '_73129' in json.dumps(users[-1]):
                        child_requests.append(request)
                names = {t.get('name') for r in child_requests for _, t in tool_entries(r)}
                result['checks'][kind.lower() + '_mcp_advertised'] = 'read_sentinel' in names
                result['checks'][kind.lower() + '_dynamic_visibility'] = ('edit_text' in names) == (kind == 'FORK')
            mcp_calls = [json.loads(line) for line in (out / 'mcp.jsonl').read_text(encoding='utf-8').splitlines()
                         if json.loads(line)['message'].get('method') == 'tools/call']
            result['checks']['two_actual_child_mcp_processes'] = len({r['pid'] for r in mcp_calls}) == 2
        if scenario == 'review':
            result['checks']['review_result_persisted'] = 'Scripted offline review' in json.dumps(result.get('review_snapshot'))
        result['passed'] = all(result['checks'].values())
        save(out / 'requests.json', server.requests);save(out / 'events.json', seen)
        save(out / 'handlers.json', handlers);save(out / 'result.json', result)
    return result


def main(args):
    # This process exists solely for the probe. SDK's env overlay must not inherit
    # host credentials; never perform this scrubbing inside a shared web process.
    safe = {k:v for k,v in os.environ.items() if k.upper() in {
        'PATH','PATHEXT','SYSTEMROOT','WINDIR','SYSTEMDRIVE','TEMP','TMP','USERPROFILE','COMSPEC','PROCESSOR_ARCHITECTURE'}}
    os.environ.clear();os.environ.update(safe)
    os.environ['NO_PROXY'] = '127.0.0.1,localhost'
    from codex_cli_bin import bundled_codex_path
    out = args.out.resolve();out.mkdir(parents=True, exist_ok=False)
    (out / 'bootstrap-home').mkdir()
    os.environ['CODEX_HOME'] = str(out / 'bootstrap-home')
    binary = Path(bundled_codex_path())
    identity = {'source': 'fixture', 'sdk': importlib.metadata.version('openai-codex'),
                'runtime_package': importlib.metadata.version('openai-codex-cli-bin'),
                'binary_sha256': sha(binary), 'script_sha256': sha(Path(__file__)),
                'version': subprocess.check_output([str(binary),'--version'],text=True).strip()}
    assert identity['sdk'] == identity['runtime_package'] == '0.160.0'
    subprocess.run([str(binary),'app-server','generate-json-schema','--experimental','--out',str(out/'schema')],check=True,timeout=30)
    identity['schema_hashes'] = {str(p.relative_to(out/'schema')):sha(p) for p in sorted((out/'schema').rglob('*.json'))}
    save(out/'identity.json',identity)
    results = [run_case(out/scenario,scenario) for scenario in args.scenarios]
    summary = {'source':'fixture','external_model_calls':0,'results':results,
        'passed':all(r['passed'] for r in results),
        'limitations':['Scripted local Responses and MCP fixtures, not DeepSeek or coding quality evidence.',
            'No general shell/build permissions or process-tree sandbox claim.',
            'Review routing only; no model review quality or cancellation/resume proof.']}
    save(out/'summary.json',summary)
    print(json.dumps({'out':str(out),'passed':summary['passed'],
                      'results':[{k:r.get(k) for k in ('scenario','passed','error','checks')} for r in results]},ensure_ascii=False))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'local-data/coding-runtime-v1'/('offline-'+time.strftime('%Y%m%d-%H%M%S')))
    parser.add_argument('--scenarios',nargs='+',choices=['single','auto','review'],default=['single','auto','review'])
    parser.add_argument('--mcp-server',action='store_true')
    parser.add_argument('--audit',type=Path);parser.add_argument('--sentinel',type=Path)
    args=parser.parse_args()
    if args.mcp_server:mcp_fixture(args)
    else:raise SystemExit(main(args))
