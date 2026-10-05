"""UI operation receipts; domain candidates, confirmations and jobs keep ownership."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .jobs import canonical, digest


class OperationConflict(ValueError):
    pass


class WorkbenchStore:
    def __init__(self, root):
        self.path = Path(root) / 'workbench.sqlite'
        with closing(self.connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, input TEXT NOT NULL,
                    input_hash TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT, result_hash TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS candidates (manifest TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS coding_runs (
                    id TEXT PRIMARY KEY, details TEXT NOT NULL, details_hash TEXT NOT NULL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def interrupt_running(self):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE operations SET status='interrupted',error=? WHERE status='running'",
                       ('服务曾中断；未自动重发。请检查已有请求与收据。',))

    def get(self, operation_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM operations WHERE id=?', (operation_id,)).fetchone()
        if row is None:
            raise KeyError(operation_id)
        if digest(json.loads(row['input'])) != row['input_hash']:
            raise ValueError('operation input integrity failure')
        result = json.loads(row['result']) if row['result'] else None
        if result is not None and digest(result) != row['result_hash']:
            raise ValueError('operation result integrity failure')
        return {'operation_id': row['id'], 'kind': row['kind'], 'status': row['status'],
                'result': result, 'error': row['error']}

    def existing(self, operation_id, kind, payload):
        with closing(self.connect()) as db:
            row = db.execute('SELECT kind,input,input_hash FROM operations WHERE id=?', (operation_id,)).fetchone()
        if row is None:
            return None
        if digest(json.loads(row['input'])) != row['input_hash']:
            raise ValueError('operation input integrity failure')
        if row['kind'] != kind or row['input'] != canonical(payload):
            raise OperationConflict('same operation id has different immutable input')
        return self.get(operation_id)

    def start(self, operation_id, kind, payload):
        with closing(self.connect()) as db, db:
            db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?,?)',
                       (operation_id, kind, canonical(payload), digest(payload), 'running', None, None, None))
        return self.get(operation_id)

    def resume(self, operation_id):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE operations SET status='running',error=NULL WHERE id=? AND status IN ('interrupted','failed')",
                       (operation_id,))
        return self.get(operation_id)

    def finish(self, operation_id, *, result=None, error=None):
        status = 'failed' if error else 'completed'
        with closing(self.connect()) as db, db:
            db.execute('UPDATE operations SET status=?,result=?,result_hash=?,error=? WHERE id=? AND status=?',
                       (status, canonical(result) if result is not None else None,
                        digest(result) if result is not None else None, error, operation_id, 'running'))

    def remember_candidate(self, manifest_hash):
        with closing(self.connect()) as db, db:
            db.execute('INSERT OR IGNORE INTO candidates VALUES (?)', (manifest_hash,))

    def candidates(self):
        with closing(self.connect()) as db:
            return [row['manifest'] for row in db.execute('SELECT manifest FROM candidates ORDER BY manifest')]

    def start_coding(self, operation_id, payload, details):
        """Claim operation and its recovery references in one local transaction."""
        with closing(self.connect()) as db, db:
            db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?,?)',
                       (operation_id, 'coding', canonical(payload), digest(payload), 'running', None, None, None))
            db.execute('INSERT INTO coding_runs VALUES (?,?,?)',
                       (operation_id, canonical(details), digest(details)))
        return self.get(operation_id)

    def coding_details(self, operation_id):
        self.get(operation_id)  # Also verify the immutable business input.
        with closing(self.connect()) as db:
            row = db.execute('SELECT details,details_hash FROM coding_runs WHERE id=?', (operation_id,)).fetchone()
        if row is None:
            raise KeyError(operation_id)
        details = json.loads(row['details'])
        if digest(details) != row['details_hash']:
            raise ValueError('coding recovery reference integrity failure')
        return details

    def save_coding_details(self, operation_id, details):
        with closing(self.connect()) as db, db:
            if db.execute('UPDATE coding_runs SET details=?,details_hash=? WHERE id=?',
                          (canonical(details), digest(details), operation_id)).rowcount != 1:
                raise KeyError(operation_id)

    def coding_ids(self):
        with closing(self.connect()) as db:
            return [row['id'] for row in db.execute('SELECT id FROM coding_runs ORDER BY rowid DESC')]
