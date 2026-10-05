"""Single-driver NPC authority: immutable inputs, source inbox, durable replies."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from .contracts import NPCError, canonical, fingerprint


class NPCStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / 'npc.sqlite'
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS npc_turns (
                  id TEXT PRIMARY KEY, scope TEXT NOT NULL, request_id TEXT NOT NULL,
                  input TEXT NOT NULL, input_hash TEXT NOT NULL, record TEXT NOT NULL,
                  record_hash TEXT NOT NULL, UNIQUE(scope,request_id));
                CREATE TABLE IF NOT EXISTS npc_memories (
                  scope TEXT NOT NULL,event_id TEXT NOT NULL,event TEXT NOT NULL,event_hash TEXT NOT NULL,
                  PRIMARY KEY(scope,event_id));
                CREATE TABLE IF NOT EXISTS npc_cursors (scope TEXT PRIMARY KEY, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS npc_replies (
                  id TEXT PRIMARY KEY,turn_id TEXT NOT NULL UNIQUE,body TEXT NOT NULL,body_hash TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _read(raw, expected):
        value = json.loads(raw)
        if fingerprint(value) != expected:
            raise NPCError('integrity_error', '本机记录损坏；未继续执行。')
        return value

    def get(self, turn_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM npc_turns WHERE id=?', (turn_id,)).fetchone()
            if row is None:
                raise NPCError('not_found', '没有找到对话。')
            return self._read(row['record'], row['record_hash'])

    def admit(self, scope, request):
        tid = 'turn_' + fingerprint({'scope': scope.model_dump(), 'request_id': request.request_id})[:48]
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM npc_turns WHERE id=?', (tid,)).fetchone()
            if row:
                if self._read(row['input'], row['input_hash']) != request.model_dump():
                    raise NPCError('input_conflict', '相同请求 ID 已绑定原话语。')
                return self._read(row['record'], row['record_hash'])
            for row in db.execute('SELECT record,record_hash FROM npc_turns WHERE scope=?', (scope.key,)):
                if self._read(row['record'], row['record_hash'])['status'] not in ('completed', 'rejected', 'model_unknown'):
                    raise NPCError('scope_busy', '请先完成当前角色的待处理对话。')
            record = {'turn_id': tid, 'scope': scope.model_dump(), 'request': request.model_dump(),
                'status': 'new', 'action_id': 'npc_' + tid[5:], 'reply_id': 'reply_' + tid[5:],
                'model_mode': 'offline', 'attempts': [], 'context': None, 'intent': None,
                'offer': None, 'approval_request': None, 'approval': None, 'receipt': None,
                'reply': None, 'error': None, 'nodes': []}
            db.execute('INSERT INTO npc_turns VALUES (?,?,?,?,?,?,?)',
                (tid, scope.key, request.request_id, canonical(request), fingerprint(request), canonical(record), fingerprint(record)))
            return record

    def update(self, turn_id, **changes):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM npc_turns WHERE id=?', (turn_id,)).fetchone()
            record = self._read(row['record'], row['record_hash'])
            record.update(changes)
            db.execute('UPDATE npc_turns SET record=?,record_hash=? WHERE id=?', (canonical(record), fingerprint(record), turn_id))
            return record

    def project(self, scope, context):
        if any(context.get(k) != getattr(scope, k) for k in ('save_id', 'branch_id', 'npc_id')):
            raise NPCError('scope_mismatch', '不能投影其他角色的经历。')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT revision FROM npc_cursors WHERE scope=?', (scope.key,)).fetchone()
            if old and context['revision'] < old[0]:
                raise NPCError('world_regressed', '世界记录落后于已知经历。')
            seen = set()
            for event in context['events']:
                if (scope.npc_id not in event['visible_to'] or event['save_id'] != scope.save_id
                        or event['branch_id'] != scope.branch_id or event['event_id'] in seen
                        or event['sequence'] > context['revision']):
                    raise NPCError('visibility_violation', '经历不属于合法角色来源。')
                seen.add(event['event_id'])
                previous = db.execute('SELECT event_hash FROM npc_memories WHERE scope=? AND event_id=?',
                                      (scope.key, event['event_id'])).fetchone()
                if previous and previous[0] != fingerprint(event):
                    raise NPCError('integrity_error', '既有来源事件发生变化。')
                db.execute('INSERT OR IGNORE INTO npc_memories VALUES (?,?,?,?)',
                           (scope.key, event['event_id'], canonical(event), fingerprint(event)))
            db.execute('INSERT INTO npc_cursors VALUES (?,?) ON CONFLICT(scope) DO UPDATE SET revision=excluded.revision',
                       (scope.key, context['revision']))

    def memories(self, scope, query=None):
        with self.connection() as db:
            events = [self._read(r['event'], r['event_hash']) for r in db.execute(
                'SELECT * FROM npc_memories WHERE scope=? ORDER BY event_id', (scope.key,))]
        # Bounded lexical retrieval over this role's source records, not a global index.
        if query:
            events = [e for e in events if query.casefold() in canonical(e).casefold()]
        return [{'event_id': e['event_id'], 'event_hash': fingerprint(e), 'kind': e['kind'],
                 'source': e['source'], 'payload': e['payload'],
                 'is_world_fact': e['payload'].get('is_world_fact', e['kind'] == 'expedition_prepared')}
                for e in events[-20:]]

    def reply(self, turn_id, text, *, status='completed', citations=None, error=None):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM npc_turns WHERE id=?', (turn_id,)).fetchone()
            record = self._read(row['record'], row['record_hash'])
            reply = {'reply_id': record['reply_id'], 'text': text, 'citations': citations or []}
            previous = db.execute('SELECT * FROM npc_replies WHERE id=?', (record['reply_id'],)).fetchone()
            if previous and self._read(previous['body'], previous['body_hash']) != reply:
                raise NPCError('reply_conflict', '已交付回复不可替换。')
            db.execute('INSERT OR IGNORE INTO npc_replies VALUES (?,?,?,?)',
                       (record['reply_id'], turn_id, canonical(reply), fingerprint(reply)))
            record.update(status=status, reply=reply, error=error)
            db.execute('UPDATE npc_turns SET record=?,record_hash=? WHERE id=?', (canonical(record), fingerprint(record), turn_id))
            return record
