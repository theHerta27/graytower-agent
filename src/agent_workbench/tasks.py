"""Local business tasks link existing author operations and independent QA receipts."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .jobs import canonical, digest
from .workbench_store import OperationConflict


class TaskInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    task_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,40}$')
    kind: Literal['config', 'coding', 'verification']
    request: str = Field(min_length=1, max_length=3000)
    candidate_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    coding_operation_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,80}$')


class TaskVerificationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    goal: str = Field(min_length=1, max_length=3000)
    max_battles: int = Field(ge=2, le=12)


class TaskHistoryInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    request_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')


class TaskStore:
    def __init__(self, root):
        self.path = Path(root) / 'tasks.sqlite'
        with closing(self.connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                  candidate TEXT, author_op TEXT, verification_op TEXT, request_id TEXT,
                  created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task_events (
                  task_id TEXT NOT NULL, event_key TEXT NOT NULL, payload TEXT NOT NULL,
                  payload_hash TEXT NOT NULL, created_at TEXT NOT NULL,
                  PRIMARY KEY(task_id,event_key));
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def event(self, task_id, key, kind, detail):
        value = {'kind': kind, 'detail': detail}
        with closing(self.connect()) as db, db:
            raw = db.execute('SELECT payload FROM task_events WHERE task_id=? AND event_key=?', (task_id, key)).fetchone()
            if raw and raw['payload'] != canonical(value):
                raise OperationConflict('event identity changed')
            db.execute('INSERT OR IGNORE INTO task_events VALUES (?,?,?,?,?)',
                       (task_id, key, canonical(value), digest(value), datetime.now(timezone.utc).isoformat()))

    def create(self, value):
        raw = value.model_dump()
        with closing(self.connect()) as db, db:
            row = db.execute('SELECT payload FROM tasks WHERE id=?', (value.task_id,)).fetchone()
            if row and row['payload'] != canonical(raw):
                raise OperationConflict('task input changed')
            db.execute('INSERT OR IGNORE INTO tasks VALUES (?,?,?,?,?,?,?,?)',
                       (value.task_id, canonical(raw), digest(raw), value.candidate_id, None, None, None,
                        datetime.now(timezone.utc).isoformat()))
        self.event(value.task_id, 'created', 'task_created', {'kind': value.kind, 'request': value.request})
        if value.candidate_id:
            self.event(value.task_id, 'import', 'existing_candidate_linked', {'candidate_id': value.candidate_id})
        return self.get(value.task_id)

    def observe_operation(self, task_id, kind, detail):
        """Append changed observations, rather than reuse a mutable status key."""
        value = {'kind': kind, 'detail': detail}
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('''SELECT payload FROM task_events
                WHERE task_id=? AND json_extract(payload,'$.kind')=?
                AND json_extract(payload,'$.detail.operation_id')=? ORDER BY rowid DESC LIMIT 1''',
                (task_id, kind, detail['operation_id'])).fetchone()
            if previous and previous['payload'] == canonical(value):
                return
            sequence = db.execute('SELECT COALESCE(MAX(rowid),0)+1 FROM task_events').fetchone()[0]
            db.execute('INSERT INTO task_events VALUES (?,?,?,?,?)',
                (task_id, 'observation:'+str(sequence), canonical(value), digest(value),
                 datetime.now(timezone.utc).isoformat()))

    def link_history(self, task_id, request_id):
        value = {'kind': 'historical_report_linked',
                 'detail': {'request_id': request_id, 'new_model_calls': 0, 'new_battles': 0}}
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT request_id,verification_op FROM tasks WHERE id=?', (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row['verification_op'] or row['request_id'] not in (None, request_id):
                raise OperationConflict('history link conflicts with existing QA')
            db.execute('UPDATE tasks SET request_id=? WHERE id=?', (request_id, task_id))
            db.execute('INSERT OR IGNORE INTO task_events VALUES (?,?,?,?,?)',
                (task_id, 'history', canonical(value), digest(value), datetime.now(timezone.utc).isoformat()))

    def link(self, task_id, **fields):
        if not fields or set(fields) - {'candidate', 'author_op', 'verification_op', 'request_id'}:
            raise ValueError('invalid task link')
        with closing(self.connect()) as db, db:
            row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            if any(row[k] is not None and row[k] != v for k, v in fields.items()):
                raise OperationConflict('task already linked to different immutable artifact')
            db.execute('UPDATE tasks SET '+','.join(k+'=?' for k in fields)+' WHERE id=?', (*fields.values(), task_id))

    def get(self, task_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            value = json.loads(row['payload'])
            if digest(value) != row['payload_hash']:
                raise ValueError('task integrity failure')
            events = []
            for event in db.execute('SELECT * FROM task_events WHERE task_id=? ORDER BY rowid', (task_id,)):
                item = json.loads(event['payload'])
                if digest(item) != event['payload_hash']:
                    raise ValueError('task event integrity failure')
                events.append(item | {'time': event['created_at']})
            return value | {'candidate_id': row['candidate'], 'author_operation_id': row['author_op'],
                            'verification_operation_id': row['verification_op'], 'request_id': row['request_id'],
                            'created_at': row['created_at'], 'events': events,
                            'origin': 'existing_candidate' if value['candidate_id'] else 'new_request'}

    def ids(self):
        with closing(self.connect()) as db:
            return [r['id'] for r in db.execute('SELECT id FROM tasks ORDER BY rowid DESC')]


class TaskService:
    def __init__(self, workbench):
        self.workbench = workbench
        self.store = TaskStore(workbench.root)

    def create(self, value):
        if not value.request.strip():
            raise ValueError('empty request')
        if value.kind == 'verification' and value.candidate_id is None:
            raise ValueError('independent QA needs an existing candidate')
        if value.candidate_id:
            self.workbench.candidate(value.candidate_id)
        self.store.create(value)
        return self.get(value.task_id)

    def get(self, task_id):
        row = self.store.get(task_id)
        status, author_result = 'needs_generation', None
        has_verification_operation = False
        for field in ('author_operation_id', 'verification_operation_id'):
            if row[field]:
                try:
                    op = self.workbench.operations.get(row[field])
                except KeyError:
                    continue  # Grant rejection did not create an operation.
                self.store.observe_operation(task_id, field.removesuffix('_id'),
                                             {'operation_id': row[field], 'status': op['status'], 'error': op['error']})
                status = op['status']
                if field == 'verification_operation_id':
                    has_verification_operation = True
                if field == 'author_operation_id':
                    author_result = op['result']
                    for index, activity in enumerate((op['result'] or {}).get('trace', [])):
                        self.store.event(task_id, row[field]+':node:'+str(index), 'author_node', activity)
                    candidate = (op['result'] or {}).get('candidate')
                    if candidate:
                        self.workbench.candidate(candidate['manifest_hash'])
                        self.store.link(task_id, candidate=candidate['manifest_hash'])
                        self.store.event(task_id, 'candidate', 'candidate_frozen', {'candidate_id': candidate['manifest_hash']})
                    elif op['status'] == 'completed':
                        status = (op['result'] or {}).get('status', 'completed')
        row = self.store.get(task_id)
        candidate = self.workbench.candidate(row['candidate_id']) if row['candidate_id'] else None
        report = None
        if candidate and not has_verification_operation:
            status = 'ready_for_verification' if candidate['confirmed'] else 'awaiting_test_approval'
            if not candidate['execution_compatible']:
                status = 'historical_candidate'
        if row['request_id']:
            try:
                report = self.workbench.request_detail(row['request_id'])
                for receipt in self.workbench.jobs.receipts(row['request_id']):
                    self.store.event(task_id, 'job:'+receipt['job_id'], 'job_receipt',
                                     {'job_id': receipt['job_id'], 'args': receipt['args']})
                if report['request']['report'] is not None:
                    # A historical link has no owned QA operation. This also
                    # recovers old links committed before their history event.
                    status = 'history_view' if not row['verification_operation_id'] else 'verification_completed'
                    self.store.event(task_id, 'report', 'verification_report',
                                     {'request_id': row['request_id'], 'verdict': report['request']['report']['verdict']})
            except KeyError:
                pass
        historical_runs = [r for r in self.workbench.request_list()
                           if r['manifest_hash'] == row['candidate_id'] and r['verdict'] is not None]
        return self.store.get(task_id) | {'status': status, 'candidate': candidate, 'historical_runs': historical_runs,
                                          'author_result': author_result, 'report': report,
                                          'applied': False}

    def link_history(self, task_id, request_id):
        row = self.store.get(task_id)
        report = self.workbench.request_detail(request_id)['request']
        if row['verification_operation_id'] or report['manifest_hash'] != row['candidate_id'] or report['report'] is None:
            raise OperationConflict('historical report must be completed and match this candidate; no active QA replacement')
        self.store.link_history(task_id, request_id)
        return self.get(task_id)

    async def generate(self, task_id):
        from .workbench import DraftInput, CodingInput
        value = self.store.get(task_id)
        if value['origin'] == 'existing_candidate' or value['kind'] == 'verification':
            raise ValueError('existing candidate does not need author generation')
        if value['kind'] == 'config':
            operation_id = task_id + '_author'
            self.store.link(task_id, author_op=operation_id)
            return await self.workbench.draft(DraftInput(operation_id=operation_id, request=value['request']))
        operation_id = value['coding_operation_id']
        if not operation_id:
            from .workbench import APIError
            raise APIError('coding_scope_pending', '当前代码任务仍需受测代码候选与执行范围；不会冒充已支持。', 403)
        self.store.link(task_id, author_op=operation_id)
        return await self.workbench.start_coding(CodingInput(operation_id=operation_id, request=value['request'], mode='single'))

    def approve(self, task_id):
        from .workbench import APIError
        row = self.get(task_id)
        if not row['candidate_id']:
            raise ValueError('candidate not ready')
        if not row['candidate']['execution_compatible']:
            raise APIError('historical_only', row['candidate']['compatibility_note'], 409)
        self.workbench.jobs.confirm(row['candidate_id'])
        self.store.event(task_id, 'approval', 'test_approved', {'candidate_id': row['candidate_id'], 'applied': False})
        return self.get(task_id)

    async def verify(self, task_id, value):
        from .workbench import APIError, VerificationInput
        row = self.get(task_id)
        if row['request_id'] and row['status'] == 'history_view':
            raise APIError('historical_only', '此任务用于历史回看；新验证请创建独立任务。', 409)
        if row['candidate'] and not row['candidate']['execution_compatible']:
            raise APIError('historical_only', row['candidate']['compatibility_note'], 409)
        if not row['candidate'] or not row['candidate']['confirmed']:
            raise APIError('approval_required', '请先批准候选进入测试；这不代表采纳到游戏。', 409)
        request_id = task_id + '_qa'
        self.store.link(task_id, request_id=request_id, verification_op='verify_'+request_id)
        return await self.workbench.verify(VerificationInput(request_id=request_id,
            manifest_hash=row['candidate_id'], **value.model_dump()))

    async def resume(self, task_id):
        from .workbench import APIError, VerificationInput
        row = self.get(task_id)
        if not row['verification_operation_id'] or not row['request_id']:
            raise APIError('recovery_required', '此任务没有已准入的独立验证，不能恢复历史报告。', 409)
        saved = self.workbench.jobs.get(row['request_id'])
        # Resume exactly the original admitted input, with its original budget.
        value = VerificationInput(**{key: saved[key] for key in ('request_id', 'manifest_hash', 'goal', 'max_battles')})
        return await self.workbench.verify(value, resume=True)
