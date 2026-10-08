"""Single-machine SQLite receipts. Unknown attempts are never silently retried."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


class RecoveryRequired(RuntimeError):
    pass


class JobStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'jobs.sqlite'
        with closing(self.connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS confirmations (manifest TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL, charged INTEGER NOT NULL DEFAULT 0,
                    report TEXT, report_hash TEXT);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, request_id TEXT NOT NULL, args TEXT NOT NULL,
                    state TEXT NOT NULL, units INTEGER NOT NULL,
                    receipt TEXT, receipt_hash TEXT);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def confirm(self, manifest_hash: str):
        if not re.fullmatch('[0-9a-f]{64}', manifest_hash):
            raise ValueError('invalid manifest hash')
        with closing(self.connect()) as db, db:
            db.execute('INSERT OR IGNORE INTO confirmations VALUES (?)', (manifest_hash,))

    def admit(self, request_id: str, manifest_hash: str, goal: str, max_battles: int):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', request_id):
            raise ValueError('invalid request id')
        if not goal.strip() or len(goal) > 3000 or type(max_battles) is not int or not 2 <= max_battles <= 12:
            raise ValueError('goal and a battle budget of 2..12 required')
        payload = dict(manifest_hash=manifest_hash, goal=goal, max_battles=max_battles)
        raw = canonical(payload)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM confirmations WHERE manifest=?', (manifest_hash,)).fetchone():
                raise ValueError('candidate manifest is not confirmed')
            previous = db.execute('SELECT payload FROM requests WHERE id=?', (request_id,)).fetchone()
            if previous and previous['payload'] != raw:
                raise ValueError('same request id has different immutable input')
            db.execute('INSERT OR IGNORE INTO requests(id,payload,payload_hash,status) VALUES (?,?,?,?)',
                       (request_id, raw, digest(payload), 'new'))
        return self.get(request_id)

    def get(self, request_id: str):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        if row is None:
            raise KeyError(request_id)
        payload = json.loads(row['payload'])
        if digest(payload) != row['payload_hash']:
            raise ValueError('request integrity failure')
        report = json.loads(row['report']) if row['report'] else None
        if report is not None and digest(report) != row['report_hash']:
            raise ValueError('report integrity failure')
        if report is not None and (report.get('manifest_hash') != payload['manifest_hash']
                                   or report.get('request_id', request_id) != request_id):
            raise ValueError('report identity mismatch')
        return dict(request_id=request_id, **payload, status=row['status'],
                    charged_battles=row['charged'], report=report)

    def run(self, request_id: str, args: dict, units: int, execute: Callable[[], dict]):
        request = self.get(request_id)
        if not isinstance(args, dict) or type(units) is not int or units <= 0:
            raise ValueError('job arguments and positive integer units required')
        args = json.loads(canonical(args))
        job_id = digest({'request': request_id, 'manifest': request['manifest_hash'], 'args': args})
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if job:
                if job['request_id'] != request_id or job['args'] != canonical(args) or job['units'] != units:
                    raise ValueError('existing job arguments or units mismatch')
                if job['state'] != 'completed':
                    raise RecoveryRequired('作业已启动但没有完成收据。请保留现场；本次不会自动重跑。')
                return self._checked_receipt(job, request)
            if db.execute("SELECT 1 FROM jobs WHERE request_id=? AND state='running'", (request_id,)).fetchone():
                raise RecoveryRequired('该请求仍有未对账作业，不能通过新参数绕过恢复并重跑。')
            live = db.execute('SELECT status,charged FROM requests WHERE id=?', (request_id,)).fetchone()
            if live['status'] == 'completed' or type(units) is not int or units <= 0 or live['charged'] + units > request['max_battles']:
                raise ValueError('request completed or battle budget exhausted')
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)', (job_id, request_id, canonical(args), 'running', units, None, None))
            db.execute("UPDATE requests SET charged=charged+?,status='running' WHERE id=?", (units, request_id))
        # The durable claim precedes physical work; any failure keeps its unknown receipt.
        result = execute()
        self._check_result(result, request['manifest_hash'], units)
        receipt = {'job_id': job_id, 'request_id': request_id, 'manifest_hash': request['manifest_hash'],
                   'args': args, 'units': units, 'result': result}
        with closing(self.connect()) as db, db:
            db.execute("UPDATE jobs SET state='completed',receipt=?,receipt_hash=? WHERE id=? AND state='running'",
                       (canonical(receipt), digest(receipt), job_id))
        return receipt

    def complete(self, request_id: str, report: dict):
        request = self.get(request_id)
        if (report.get('manifest_hash') != request['manifest_hash']
                or report.get('request_id', request_id) != request_id
                or report.get('verdict') not in ('FAIL', 'INCONCLUSIVE', 'PASS')
                or report.get('verdict') == 'PASS' and report.get('kind') != 'code'):
            raise ValueError('report identity or verdict mismatch')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT report FROM requests WHERE id=?', (request_id,)).fetchone()
            if row['report'] and row['report'] != canonical(report):
                raise ValueError('completed report is immutable')
            db.execute("UPDATE requests SET status='completed',report=?,report_hash=? WHERE id=?",
                       (canonical(report), digest(report), request_id))

    def reconcile_completed(self, request_id, args, units, result):
        """Internal adapter: attach a hash-checked physical receipt to its claim.

        No new work or budget; callers must independently verify the completed
        execution receipt before using this method. Unknown work stays blocked.
        """
        request = self.get(request_id)
        job_id = digest({'request': request_id, 'manifest': request['manifest_hash'], 'args': args})
        self._check_result(result, request['manifest_hash'], units)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None or row['args'] != canonical(args) or row['units'] != units:
                return False
            if row['state'] == 'completed':
                self._checked_receipt(row, request)
                return True
            receipt = dict(job_id=job_id, request_id=request_id, manifest_hash=request['manifest_hash'],
                           args=args, units=units, result=result)
            db.execute("UPDATE jobs SET state='completed',receipt=?,receipt_hash=? WHERE id=?",
                       (canonical(receipt), digest(receipt), job_id))
        return True

    def receipts(self, request_id: str):
        request = self.get(request_id)
        with closing(self.connect()) as db:
            rows = db.execute("SELECT * FROM jobs WHERE request_id=? AND state='completed' ORDER BY id", (request_id,)).fetchall()
        return [self._checked_receipt(row, request) for row in rows]

    @staticmethod
    def _check_result(result: dict, manifest_hash: str, units: int):
        # Generic local jobs can omit game fields. Game callers additionally
        # enforce their full result schema before returning from execute().
        if not isinstance(result, dict):
            raise ValueError('job result must be an object')
        if 'manifest_hash' in result and result['manifest_hash'] != manifest_hash:
            raise ValueError('game result manifest mismatch')
        if 'identity' in result and (not isinstance(result['identity'], dict)
                                     or result['identity'].get('manifest_hash') != manifest_hash):
            raise ValueError('game result identity mismatch')
        if 'completed_battles' in result and (type(result['completed_battles']) is not int
                                              or result['completed_battles'] != units):
            raise ValueError('game result battle count mismatch')

    def _checked_receipt(self, row, request):
        receipt = json.loads(row['receipt'])
        if not isinstance(receipt, dict) or digest(receipt) != row['receipt_hash']:
            raise ValueError('job receipt integrity failure')
        expected = {'job_id': row['id'], 'request_id': request['request_id'],
                    'manifest_hash': request['manifest_hash'], 'args': json.loads(row['args']), 'units': row['units']}
        if (set(receipt) != {*expected, 'result'}
                or row['request_id'] != request['request_id']
                or type(receipt.get('units')) is not int
                or any(canonical(receipt.get(key)) != canonical(value) for key, value in expected.items())
                or row['id'] != digest({'request': request['request_id'], 'manifest': request['manifest_hash'], 'args': expected['args']})):
            raise ValueError('job receipt identity, arguments or units mismatch')
        self._check_result(receipt['result'], request['manifest_hash'], row['units'])
        return receipt
