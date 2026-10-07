"""Disposable architecture probe. Real installed Codex; local fake Responses only.

No real model, login, credentials, shell tools or product code changes.
Every run uses a fresh, child-process-only Codex data directory.
"""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'research' / 'evidence' / ('codex-probe-' + time.strftime('%Y%m%d-%H%M%S'))
OUT.mkdir(parents=True)
DATA = OUT / 'isolated-runtime-data'
DATA.mkdir()
WORK = OUT / 'empty-workspace'
WORK.mkdir()
requests_seen = []
slow_entered = threading.Event()
slow_release = threading.Event()


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests_seen.append({'path': self.path, 'model': body.get('model'),
                              'input_types': [x.get('type') for x in body.get('input', [])]})
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Connection', 'close')
        self.end_headers()

        def emit(event):
            self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode())
            self.wfile.flush()

        try:
            emit({'type': 'response.created', 'response': {'id': 'probe-response'}})
            if 'PROBE_SLOW' in json.dumps(body):
                slow_entered.set()
                slow_release.wait(20)
                return
            item = {'type': 'message', 'role': 'assistant', 'id': 'probe-message',
                    'content': [{'type': 'output_text', 'text': 'LOCAL_FIXTURE_OK'}]}
            emit({'type': 'response.output_item.added', 'output_index': 0, 'item': {**item, 'content': []}})
            emit({'type': 'response.output_text.delta', 'item_id': 'probe-message',
                  'output_index': 0, 'content_index': 0, 'delta': 'LOCAL_FIXTURE_OK'})
            emit({'type': 'response.output_item.done', 'output_index': 0, 'item': item})
            emit({'type': 'response.completed', 'response': {'id': 'probe-response',
                  'usage': {'input_tokens': 10, 'output_tokens': 3, 'total_tokens': 13,
                            'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': None}}})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


httpd = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
port = httpd.server_address[1]
(DATA / 'config.toml').write_text(f'''model = "probe-model"
model_provider = "local_probe"
approval_policy = "never"
sandbox_mode = "read-only"
[analytics]
enabled = false
[model_providers.local_probe]
name = "Local protocol fixture"
base_url = "http://127.0.0.1:{port}/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
request_max_retries = 0
stream_max_retries = 0
''', encoding='utf-8')
binary = shutil.which('codex')
version = subprocess.check_output([binary, '--version'], text=True).strip()
all_events = []


class Client:
    def __init__(self, name):
        # This configures this child only; the user's environment/home is unchanged.
        env = {k: v for k, v in os.environ.items()
               if k.upper() in {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE',
                                 'TEMP', 'TMP', 'USERPROFILE', 'COMSPEC', 'PROCESSOR_ARCHITECTURE'}}
        env['CODEX_HOME'] = str(DATA)
        env['NO_PROXY'] = '127.0.0.1,localhost'
        self.stderr = (OUT / (name + '-stderr.log')).open('w', encoding='utf-8')
        self.proc = subprocess.Popen([binary, 'app-server', '--listen', 'stdio://'], cwd=WORK,
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
            text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
        self.events = queue.Queue()
        self.counter = 0
        threading.Thread(target=self.reader, daemon=True).start()

    def reader(self):
        for line in self.proc.stdout:
            event = json.loads(line)
            all_events.append(event)
            self.events.put(event)

    def send(self, value):
        self.proc.stdin.write(json.dumps(value) + '\n')
        self.proc.stdin.flush()

    def wait(self, predicate, timeout=25):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            event = self.events.get(timeout=max(.01, end-time.monotonic()))
            if predicate(event):
                return event
        raise TimeoutError('expected protocol event not received')

    def rpc(self, method, params):
        self.counter += 1
        rpc_id = self.counter
        self.send({'id': rpc_id, 'method': method, 'params': params})
        result = self.wait(lambda e: e.get('id') == rpc_id)
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result['result']

    def init(self):
        result = self.rpc('initialize', {'clientInfo': {'name': 'mihoyo_architecture_probe',
                          'title': 'Local architecture probe', 'version': '0.1'}})
        self.send({'method': 'initialized'})
        return result

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        self.stderr.close()


clients = []
summary = {'binary': binary, 'version': version, 'scope': 'real app-server / fake local model / no tool execution',
           'checks': {}, 'limitations': ['No real provider compatibility or model-quality claim',
                                         'No approval or Windows sandbox execution verified']}
try:
    c = Client('first'); clients.append(c)
    summary['checks']['initialize'] = c.init()
    started = c.rpc('thread/start', {'cwd': str(WORK), 'model': 'probe-model',
                                    'modelProvider': 'local_probe', 'approvalPolicy': 'never', 'sandbox': 'read-only'})
    tid = started['thread']['id']
    summary['thread_id'] = tid
    t = c.rpc('turn/start', {'threadId': tid, 'input': [{'type': 'text', 'text': 'PROBE_OK'}]})
    done = c.wait(lambda e: e.get('method') == 'turn/completed')
    assert done['params']['turn']['status'] == 'completed', done
    summary['checks']['completed_turn'] = done['params']['turn']['status']
    summary['checks']['text_delta_observed'] = any(e.get('method') == 'item/agentMessage/delta' for e in all_events)
    summary['checks']['usage_observed'] = any(e.get('method') == 'thread/tokenUsage/updated' for e in all_events)
    t = c.rpc('turn/start', {'threadId': tid, 'input': [{'type': 'text', 'text': 'PROBE_SLOW'}]})
    assert slow_entered.wait(10), 'fixture was not reached'
    c.rpc('turn/interrupt', {'threadId': tid, 'turnId': t['turn']['id']})
    interrupted = c.wait(lambda e: e.get('method') == 'turn/completed')
    assert interrupted['params']['turn']['status'] == 'interrupted', interrupted
    summary['checks']['cancel_status'] = 'interrupted'
    slow_release.set()
    c.close(); clients.remove(c)
    c2 = Client('restart'); clients.append(c2)
    c2.init()
    resumed = c2.rpc('thread/resume', {'threadId': tid})
    summary['checks']['resume_same_thread'] = resumed['thread']['id'] == tid
    history = c2.rpc('thread/read', {'threadId': tid, 'includeTurns': True})
    statuses = [x['status'] for x in history['thread']['turns']]
    summary['checks']['persisted_turn_statuses'] = statuses
    assert statuses == ['completed', 'interrupted'], statuses
    summary['result'] = 'PASS'
except Exception as exc:
    summary['result'] = 'FAIL'
    summary['error'] = repr(exc)
finally:
    slow_release.set()
    for client in clients:
        client.close()
    httpd.shutdown()
    summary['local_requests'] = requests_seen
    (OUT / 'events.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False)+'\n' for x in all_events), encoding='utf-8')
    (OUT / 'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(OUT), **summary}, ensure_ascii=False, indent=2))
raise SystemExit(0 if summary['result'] == 'PASS' else 1)
