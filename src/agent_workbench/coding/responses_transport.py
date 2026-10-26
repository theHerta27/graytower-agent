"""Bounded localhost transport for one explicitly authorized DeepSeek batch.

It meters every parent/child/review request together. Only namespace names are
translated; native Codex owns the loop and subagent scheduling. The provider
credential never enters the Runtime process or its tools.
"""
from contextlib import contextmanager
from decimal import Decimal
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import threading
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ENDPOINT = 'https://api.deepseek.com/responses'
MODEL = 'deepseek-flash'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


class CallBudget:
    def __init__(self, root: Path, grant: dict):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.grant = dict(grant)
        if (type(grant['max_calls']) is not int or not 1 <= grant['max_calls'] <= 100
                or type(grant['max_input_bytes']) is not int or not 1 <= grant['max_input_bytes'] <= 150000
                or grant.get('model_profile','fast') not in ('fast','reasoned')
                or type(grant['max_output_tokens']) is not int or not 1 <= grant['max_output_tokens'] <= (16384 if grant.get('model_profile')=='reasoned' else 4096)):
            raise ValueError('invalid bounded Coding grant')
        self.max_cost = ((Decimal(grant['max_input_bytes'] + 2048) * Decimal(grant['input_usd_per_million'])
                         + Decimal(grant['max_output_tokens']) * Decimal(grant['output_usd_per_million'])) / 1_000_000)
        if self.max_cost * grant['max_calls'] > Decimal(grant['cost_cap_usd']):
            raise ValueError('grant cost cap does not cover all call reservations')
        self.database = self.root / 'responses-ledger.sqlite'
        with self._db() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS grant_info (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY AUTOINCREMENT, input_hash TEXT NOT NULL, '
                         'state TEXT NOT NULL, usage TEXT, known_cost TEXT)')
            raw = encoded(grant).decode()
            conn.execute('INSERT OR IGNORE INTO grant_info VALUES (1,?)', (raw,))
            if conn.execute('SELECT body FROM grant_info WHERE id=1').fetchone()[0] != raw:
                raise ValueError('existing grant cannot be changed or reset')

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.database, timeout=20)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def reserve(self, body):
        raw = encoded(body)
        if len(raw) > self.grant['max_input_bytes']:
            raise ValueError('request exceeds the authorized input size')
        with self._db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            count = conn.execute('SELECT COUNT(*) FROM calls').fetchone()[0]
            if count >= self.grant['max_calls']:
                raise ValueError('shared Coding call budget exhausted')
            cursor = conn.execute("INSERT INTO calls(input_hash,state) VALUES (?, 'reserved')", (hashlib.sha256(raw).hexdigest(),))
            return cursor.lastrowid

    def finish(self, call_id, state, usage):
        if state not in ('completed', 'failed'):
            raise ValueError('invalid call state')
        cost = None
        if usage is not None:
            incoming, outgoing = usage.get('input_tokens'), usage.get('output_tokens')
            cached = usage.get('input_tokens_details', {}).get('cached_tokens', 0)
            if (any(type(item) is not int or item < 0 for item in (incoming, outgoing, cached))
                    or cached > incoming):
                raise ValueError('invalid provider usage; retain the reservation')
            cost = ((incoming - cached) * Decimal(self.grant['input_usd_per_million'])
                    + cached * Decimal(self.grant['cached_input_usd_per_million'])
                    + outgoing * Decimal(self.grant['output_usd_per_million'])) / 1_000_000
        with self._db() as conn:
            row = conn.execute('SELECT state FROM calls WHERE id=?', (call_id,)).fetchone()
            if not row or row['state'] != 'reserved':
                raise ValueError('call result is immutable')
            conn.execute('UPDATE calls SET state=?, usage=?, known_cost=? WHERE id=?',
                         (state, encoded(usage).decode() if usage is not None else None,
                          str(cost) if cost is not None else None, call_id))

    def summary(self):
        with self._db() as conn:
            rows = conn.execute('SELECT * FROM calls').fetchall()
        known = sum((Decimal(row['known_cost']) for row in rows if row['known_cost'] is not None), Decimal(0))
        unknown = sum(row['known_cost'] is None for row in rows)
        return {'reserved': len(rows), 'completed': sum(row['state'] == 'completed' for row in rows),
                'failed': sum(row['state'] == 'failed' for row in rows), 'unknown': unknown,
                'known_cost_usd': str(known), 'unknown_cost_reserved_usd': str(unknown * self.max_cost),
                'max_calls': self.grant['max_calls'], 'cost_cap_usd': self.grant['cost_cap_usd']}


def deepseek_sender(api_key: str):
    """Construct only after user authorization. No key is included in artifacts."""
    if not api_key:
        raise ValueError('DeepSeek key is required')
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('provider redirects are not part of this authorization')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    def send(body):
        request = Request(ENDPOINT, data=encoded(body), method='POST',
                          headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'})
        with opener.open(request, timeout=90) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('provider response exceeded the bounded transport limit')
        return raw
    return send


@contextmanager
def responses_endpoint(root: Path, grant: dict, sender):
    """Caller supplies either a scripted fixture or the explicitly granted sender."""
    from .response_namespaces import provider_request, runtime_event
    budget = CallBudget(root, grant)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            call_id = None
            usage = None
            try:
                if self.path != '/responses' or not 0 < int(self.headers.get('Content-Length', 0)) <= 1_000_000:
                    raise ValueError('unsupported local request')
                original = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if original.get('model') != MODEL or original.get('stream') is not True:
                    raise ValueError('only DeepSeek Flash streaming Responses is allowed')
                body, mapping = provider_request(original)
                body['max_output_tokens'] = grant['max_output_tokens']
                call_id = budget.reserve(body)
                prefix = budget.root / f'call-{call_id:04d}'
                prefix.with_suffix('.request.json').write_bytes(encoded(body))
                raw = sender(body)
                prefix.with_suffix('.response.sse').write_bytes(raw)
                events = [json.loads(line[5:].strip()) for line in raw.decode('utf-8').splitlines()
                          if line.startswith('data:')]
                terminal = [event for event in events if event.get('type') in
                            ('response.completed', 'response.incomplete', 'response.failed')]
                if len(terminal) != 1:
                    raise ValueError('provider did not return exactly one terminal response')
                final = terminal[0]
                usage = final.get('response', {}).get('usage')
                mapped = [runtime_event(event, mapping) for event in events]
                budget.finish(call_id, 'completed' if final['type'] == 'response.completed' else 'failed',
                              usage)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close')
                self.end_headers()
                for event in mapped:
                    self.wfile.write(b'event: ' + event['type'].encode() + b'\ndata: ' + encoded(event) + b'\n\n')
                self.wfile.flush()
            except Exception as exc:
                if call_id is not None:
                    try:
                        budget.finish(call_id, 'failed', usage)
                    except ValueError:
                        pass
                # Do not echo arbitrary provider exception text (URLs/headers).
                with (budget.root / 'transport-errors.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps({'call_id': call_id, 'error_type': type(exc).__name__}) + '\n')
                try:
                    self.send_error(400, 'Authorized transport rejected the request; inspect local evidence')
                except OSError:
                    pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    # Closing a batch must wait for already-sent requests to be accounted for.
    server.daemon_threads = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', budget
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
