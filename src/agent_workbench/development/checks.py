"""Nonblocking check admission, immutable input and local physical receipts."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from ..coding.runtime_adapter import safe_environment
from .workspace import digest, encoded
from .sandbox import CHECK_SETS, IMAGE, runner_hash


class CheckJobs:
    def __init__(self, root, *, launcher=None, python=None):
        self.root = Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / 'checks.sqlite'
        self.python = str(python or sys.executable)
        self.launcher = launcher
        self.active = {}
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,identity TEXT NOT NULL,input_hash TEXT NOT NULL,status TEXT NOT NULL,receipt TEXT,receipt_hash TEXT,error TEXT)')

    def connect(self):
        db = sqlite3.connect(self.database, timeout=20); db.row_factory = sqlite3.Row
        return db

    def start(self, workspace, check_set='rules', *, diagnostic=None):
        if check_set not in (*CHECK_SETS, 'diagnostic'):
            raise ValueError('unsupported check set')
        if check_set == 'diagnostic':
            if not isinstance(diagnostic, str) or not diagnostic.strip() or len(diagnostic) > 8000:
                raise ValueError('require bounded diagnostic Python')
        elif diagnostic is not None:
            raise ValueError('trusted checks cannot accept diagnostic code')
        if self.root.is_relative_to(workspace.path) or workspace.path.is_relative_to(self.root):
            raise ValueError('check controls must be outside candidate')
        tree = workspace.snapshot()
        identity = {'tree_hash': digest(tree), 'check_set': check_set, 'image': IMAGE,
                    'runner_hash': runner_hash(), 'targets':list(CHECK_SETS.get(check_set,[])), 'diagnostic_hash': digest(diagnostic)}
        job_id = digest(identity)
        payload = {'identity': identity, 'tree': tree, 'diagnostic': diagnostic}
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT id,status FROM jobs WHERE id=?', (job_id,)).fetchone()
            if prior and prior['status']!='not_started':
                return self.read(job_id, workspace)
            folder = self.root / job_id
            if prior:
                self.payload(job_id)
                db.execute("UPDATE jobs SET status='running',error=NULL WHERE id=?",(job_id,))
            else:
                folder.mkdir()
                (folder / 'input.json').write_bytes(encoded(payload))
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',
                    (job_id, encoded(identity).decode(), digest(payload), 'running', None, None, None))
        request = {'root': str(self.root), 'job_id': job_id, 'input_path': str(folder / 'input.json')}
        try:
            if self.launcher is not None:
                self.launcher(request); self.active[job_id] = None
            else:
                source = Path(__file__).resolve().parents[2]
                env = safe_environment(os.environ, source)
                with (folder / 'worker.log').open('ab') as log:
                    self.active[job_id] = subprocess.Popen([self.python, '-B', '-m',
                        'agent_workbench.development.check_worker', str(self.root), job_id],
                        cwd=folder, env=env, stdout=log, stderr=log)
        except Exception as exc:
            self.mark_unknown(job_id, type(exc).__name__)
            raise
        return self.read(job_id, workspace)

    def payload(self, job_id):
        row = self._row(job_id)
        value = json.loads((self.root / job_id / 'input.json').read_text(encoding='utf-8'))
        if digest(value) != row['input_hash'] or encoded(value['identity']).decode() != row['identity']:
            raise ValueError('job input damaged')
        return value

    def _row(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch('[a-f0-9]{64}', job_id):
            raise ValueError('invalid job id')
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise ValueError('unknown check job')
        return row

    def read(self, job_id, workspace=None):
        row = self._row(job_id); identity = json.loads(row['identity'])
        status = row['status']
        if status == 'running':
            process = self.active.get(job_id)
            if job_id not in self.active or (process is not None and process.poll() is not None):
                status = 'unknown'
        result = json.loads(row['receipt']) if row['receipt'] is not None else None
        if result is not None and digest(result) != row['receipt_hash']:
            raise ValueError('check receipt damaged')
        return {'job_id': job_id, **identity, 'status': status, 'result': result,
                'matches_current_candidate': None if workspace is None else digest(workspace.snapshot()) == identity['tree_hash'],
                'matches_current_definition':identity.get('image')==IMAGE and identity.get('runner_hash')==runner_hash()
                    and identity.get('targets')==CHECK_SETS.get(identity['check_set'],[]),
                'error':row['error'],'retry_safe':status=='not_started',
                'note': '结果未知，不自动重跑；等待或核对原作业。' if status == 'unknown' else
                    '确认尚未执行候选；修复Docker或镜像后可再次开始同一检查。' if status=='not_started' else ''}

    def complete(self, job_id, outcome):
        identity = json.loads(self._row(job_id)['identity'])
        outcome = dict(outcome)
        tests = outcome.get('tests', [])
        exit_code = outcome.get('exit_code')
        if identity['check_set'] == 'diagnostic':
            verdict = 'OBSERVATION' if type(exit_code) is int and exit_code == 0 else 'DIAGNOSTIC_ERROR'
        elif type(exit_code) is int and exit_code == 1 and any(t.get('status') == 'FAIL' for t in tests):
            verdict = 'FAIL'
        elif (type(exit_code) is int and exit_code == 0 and tests and not outcome.get('xml_error')
              and all(t.get('status') == 'PASS' for t in tests)):
            verdict = 'PASS'
        else:
            verdict = 'INCONCLUSIVE'
        outcome.update(verdict=verdict, tree_hash=identity['tree_hash'], check_set=identity['check_set'])
        raw = encoded(outcome).decode()
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT receipt,status FROM jobs WHERE id=?', (job_id,)).fetchone()
            if previous['receipt'] is not None:
                if previous['receipt'] != raw:
                    raise ValueError('completed receipt is immutable')
                return
            db.execute("UPDATE jobs SET status='completed',receipt=?,receipt_hash=? WHERE id=?", (raw, digest(outcome), job_id))

    def mark_unknown(self, job_id, error):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE jobs SET status='unknown',error=? WHERE id=? AND receipt IS NULL", (str(error)[:300], job_id))

    def mark_not_started(self,job_id,error):
        self._row(job_id)
        with closing(self.connect()) as db,db:
            db.execute("UPDATE jobs SET status='not_started',error=? WHERE id=? AND receipt IS NULL",(str(error)[:300],job_id))

    def list(self, workspace=None):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT id FROM jobs ORDER BY rowid').fetchall()
        if workspace is not None and rows:
            from types import SimpleNamespace
            tree = workspace.snapshot()
            workspace = SimpleNamespace(snapshot=lambda:tree)
        return [self.read(r['id'], workspace) for r in rows]
