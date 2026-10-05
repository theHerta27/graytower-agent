"""One local Coding driver: explicit startup grant, durable run and receipt recovery.

Default construction is read-only with respect to models. HTTP never supplies a
grant, provider, interpreter or directory. Recovery only completes an existing
Runtime receipt; it does not resume a model turn or replay unknown side effects.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from ..domain import CandidateRepository
from ..jobs import JobStore
from ..workbench_store import OperationConflict, WorkbenchStore
from .candidates import CodingWorkspace
from .responses_transport import CallBudget, responses_endpoint
from .runtime_adapter import run_runtime, validate_runtime_receipt


def _payload(value):
    if (set(value) != {'operation_id', 'request', 'mode'}
            or not isinstance(value['operation_id'], str)
            or not re.fullmatch('[a-zA-Z0-9_-]{1,80}', value['operation_id'])
            or not isinstance(value['request'], str) or not value['request'].strip()
            or len(value['request']) > 4000 or value['mode'] not in ('single', 'auto')):
        raise ValueError('invalid Coding task')
    return dict(value)


class CodingAuthorization:
    """A local, pre-reviewed task allowlist, never an HTTP grant constructor."""
    def __init__(self, scope_path, expected_sha256, ledger_root):
        self.scope_path = Path(scope_path).resolve()
        self.expected_sha256 = expected_sha256
        self.closed_path = self.scope_path.parent / 'closed.json'
        self.ledger_root = Path(ledger_root).resolve()
        self.check_open()
        value = json.loads(self.scope_path.read_text(encoding='utf-8'))
        if value.get('schema') != 'coding-service-grant-v1' or not value.get('tasks'):
            raise ValueError('invalid Coding authorization scope')
        self.tasks = {key: _payload({'operation_id': key, **task}) for key, task in value['tasks'].items()}
        self.grant = dict(value['coding_grant'], authorization_sha256=expected_sha256)
        self.budget = CallBudget(self.ledger_root, self.grant)

    def check_open(self):
        if self.closed_path.exists():
            raise ValueError('Coding authorization is closed')
        if hashlib.sha256(self.scope_path.read_bytes()).hexdigest() != self.expected_sha256:
            raise ValueError('Coding authorization scope changed')

    def require(self, payload):
        self.check_open()
        if self.tasks.get(payload['operation_id']) != payload:
            raise ValueError('Coding task does not match the authorized input')
        if self.budget.summary()['reserved'] >= self.grant['max_calls']:
            raise ValueError('Coding authorization budget exhausted')


class CodingService:
    def __init__(self, root, *, store=None, repo=None, authorization=None, sender=None,
                 runner=run_runtime, runtime_python=None, tools_python=None,
                 source_label='official Codex Runtime'):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = store or WorkbenchStore(self.root)
        self.repo = repo or CandidateRepository(self.root)
        self.authorization, self.sender, self.runner = authorization, sender, runner
        self.runtime_python, self.tools_python = runtime_python, tools_python or Path(sys.executable)
        self.source_label = source_label

    def status(self):
        result = {'enabled': False, 'reason': 'Coding 模型执行未开放；可查看已有运行、确认候选和读取证据。',
                  'remaining_calls': 0, 'modes': ['single', 'auto'], 'tasks': []}
        if self.authorization is None or self.sender is None or self.runtime_python is None:
            return result
        try:
            self.authorization.check_open()
            summary = self.authorization.budget.summary()
            remaining = max(0, summary['max_calls'] - summary['reserved'])
            tasks = [task for task in self.authorization.tasks.values()
                     if self.store.existing(task['operation_id'], 'coding', task) is None] if remaining else []
            result.update(enabled=bool(tasks), remaining_calls=remaining, tasks=tasks,
                          reason=('仅可执行启动授权中列出的原始 Coding 任务。' if tasks else
                                  'Coding 共享调用额度已用尽。' if not remaining else '授权 Coding 任务均已领取；可读取原运行记录。'))
        except Exception:
            result['reason'] = 'Coding 授权已关闭或无法核验；不允许新模型调用。'
        return result

    def _paths(self, operation_id):
        base = self.root / 'coding-runs' / operation_id
        return base / 'workspace', base / 'control'

    def admit(self, value):
        payload = _payload(value)
        previous = self.store.existing(payload['operation_id'], 'coding', payload)
        if previous:
            return previous
        if self.authorization is None or self.sender is None or self.runtime_python is None:
            raise ValueError('Coding execution is not authorized')
        self.authorization.require(payload)
        details = {'payload': payload, 'authorization_sha256': self.authorization.expected_sha256,
                   'preparation': None, 'source_label': self.source_label, 'stage': 'preparing',
                   'manifest_hash': None, 'runtime_receipt': None, 'seconds': None, 'budget': None}
        return self.store.start_coding(payload['operation_id'], payload, details)

    def get_run(self, operation_id):
        details = self.store.coding_details(operation_id)
        operation = self.store.get(operation_id)
        return self._view(details, operation['status'], operation['error'])

    def list_runs(self):
        return [self.get_run(operation_id) for operation_id in self.store.coding_ids()]

    @staticmethod
    def _view(details, status, error=None):
        return {**details['payload'], 'status': status, 'manifest_hash': details.get('manifest_hash'),
                'summary': details.get('summary', ''), 'review_text': details.get('review_text', ''),
                'spawned_thread_ids': details.get('spawned_thread_ids', []),
                'spawn_attempts': details.get('spawn_attempts', 0), 'seconds': details.get('seconds'),
                'budget': details.get('budget'), 'budget_scope': 'shared_coding_grant',
                'stage': details['stage'], 'error': error}

    def _fail(self, operation_id, details, exc):
        details['stage'] = 'failed'
        self.store.save_coding_details(operation_id, details)
        self.store.finish(operation_id, error=f'Coding 未完成（{type(exc).__name__}）；已保留运行记录，不会自动重跑。')

    def execute(self, operation_id):
        details = self.store.coding_details(operation_id)
        if self.store.get(operation_id)['status'] != 'running' or details['stage'] != 'preparing':
            raise ValueError('Coding operation is not a fresh execution claim')
        started = time.monotonic()
        try:
            self.authorization.require(details['payload'])
            workspace_path, control = self._paths(operation_id)
            workspace = CodingWorkspace.prepare(workspace_path, self.repo)
            details.update(preparation=workspace.preparation, stage='runtime_running')
            self.store.save_coding_details(operation_id, details)

            def authorized_sender(body):
                self.authorization.check_open()
                return self.sender(body)

            with responses_endpoint(self.authorization.ledger_root, self.authorization.grant, authorized_sender) as (endpoint, budget):
                receipt = self.runner(runtime_python=self.runtime_python, tools_python=self.tools_python,
                    workspace=workspace.root, data=self.root, control=control, preparation=workspace.preparation,
                    endpoint=endpoint, mode=details['payload']['mode'], prompt=details['payload']['request'])
                saved = json.loads((control / 'result.json').read_text(encoding='utf-8'))
                if saved != receipt:
                    raise ValueError('Runtime receipt differs from its durable result')
            details.update(seconds=time.monotonic() - started, budget=budget.summary(), stage='runtime_completed')
            self.store.save_coding_details(operation_id, details)
            return self._finalize(operation_id, details, receipt, workspace)
        except Exception as exc:
            if self.authorization is not None:
                details['budget'] = self.authorization.budget.summary()
            details['seconds'] = time.monotonic() - started
            self._fail(operation_id, details, exc)
            return self.store.get(operation_id)

    @staticmethod
    def _receipt_summary(receipt):
        summary = '\n\n'.join(item['text'] for item in receipt.get('task_turn', {}).get('items', [])
                               if item.get('type') == 'agentMessage' and isinstance(item.get('text'), str))
        review = '\n\n'.join(item['review'] for item in receipt.get('review_turn', {}).get('items', [])
                              if item.get('type') == 'exitedReviewMode' and isinstance(item.get('review'), str))
        if not review:
            review = '\n\n'.join(item['text'] for item in receipt.get('review_turn', {}).get('items', [])
                                  if item.get('type') == 'agentMessage' and isinstance(item.get('text'), str))
        attempts, children = 0, set()
        for event in receipt.get('native_spawn_events', []):
            item = event.get('params', {}).get('item', {})
            if item.get('tool') == 'spawnAgent':
                attempts += 1
                if item.get('status') == 'completed':
                    children.update(x for x in item.get('receiverThreadIds', []) if isinstance(x, str) and x)
        return {'summary': summary, 'review_text': review,
                'spawn_attempts': attempts, 'spawned_thread_ids': sorted(children)}

    def _finalize(self, operation_id, details, receipt, workspace):
        if receipt.get('schema') != 'coding-runtime-run-v1' or receipt.get('mode') != details['payload']['mode']:
            raise ValueError('Runtime receipt does not match the Coding task')
        validate_runtime_receipt(receipt, workspace.inspect_changes())
        ref = self.repo.artifacts.put(receipt, 'coding-runtime-receipt-v1')
        candidate = workspace.import_candidate(details['payload']['request'], {
            'source': details['source_label'], 'mode': details['payload']['mode'], 'runtime_receipt': ref})
        source = self.repo.read_artifact(candidate['manifest']['coding_source']['sha256'])
        if source['after_tree_hash'] != receipt['review_tree_hash']:
            raise ValueError('frozen candidate differs from the reviewed tree')
        return self._complete(operation_id, details, candidate, ref, receipt)

    def _complete(self, operation_id, details, candidate, ref, receipt):
        details.update(self._receipt_summary(receipt))
        details.update(stage='candidate_frozen', manifest_hash=candidate['manifest_hash'], runtime_receipt=ref)
        self.store.save_coding_details(operation_id, details)
        self.store.remember_candidate(candidate['manifest_hash'])
        with closing(JobStore(self.root).connect()) as db:
            confirmed = bool(db.execute('SELECT 1 FROM confirmations WHERE manifest=?',
                                        (candidate['manifest_hash'],)).fetchone())
        result = {'run': self._view(details, 'completed'), 'candidate': {
            'manifest_hash': candidate['manifest_hash'], 'request': candidate['manifest']['request'],
            'diff': candidate['diff'], 'validation': candidate['validation'],
            'confirmed': confirmed}}
        self.store.finish(operation_id, result=result)
        return self.store.get(operation_id)

    def require_receipt(self, operation_id):
        details = self.store.coding_details(operation_id)
        _, control = self._paths(operation_id)
        if details.get('preparation') is None or not (control / 'result.json').is_file():
            raise ValueError('complete Runtime receipt is unavailable; do not replay the task')

    def recover(self, operation_id):
        operation = self.store.get(operation_id)
        if operation['status'] == 'completed':
            return operation
        self.require_receipt(operation_id)
        self.store.resume(operation_id)
        details = self.store.coding_details(operation_id)
        try:
            workspace_path, control = self._paths(operation_id)
            receipt = json.loads((control / 'result.json').read_text(encoding='utf-8'))
            workspace = CodingWorkspace(workspace_path, self.repo, details['preparation'])
            return self._finalize(operation_id, details, receipt, workspace)
        except Exception as exc:
            self._fail(operation_id, details, exc)
            return self.store.get(operation_id)

    def import_completed(self, *, operation_id, request, mode, manifest_hash, runtime_receipt, seconds=None, budget=None):
        """Register an already-frozen local candidate; never execute or confirm it."""
        payload = _payload({'operation_id': operation_id, 'request': request, 'mode': mode})
        previous = self.store.existing(operation_id, 'coding', payload)
        if previous:
            original = self.store.coding_details(operation_id)
            if (original['manifest_hash'] != manifest_hash or original['runtime_receipt'] != runtime_receipt
                    or original.get('preparation') is not None or original.get('source_label') != 'saved evidence'):
                raise OperationConflict('imported run is bound to another candidate or Runtime receipt')
            if previous['status'] == 'completed':
                return previous
        candidate = self.repo.get(manifest_hash)
        if candidate['manifest']['author'] != 'coding' or candidate['manifest']['request'] != request:
            raise ValueError('import requires the original coding-authored candidate')
        source = self.repo.read_artifact(candidate['manifest']['coding_source']['sha256'])
        if source['provenance']['details'].get('runtime_receipt') != runtime_receipt:
            raise ValueError('candidate is not bound to the supplied Runtime receipt')
        receipt = self.repo.artifacts.read_ref(runtime_receipt, 'coding-runtime-receipt-v1')
        if receipt.get('mode') != mode:
            raise ValueError('imported Runtime mode does not match')
        after = self.repo.artifacts.read_ref(source['after_file'], 'coding-file-v1')
        validate_runtime_receipt(receipt, {'after_tree_hash': source['after_tree_hash'], 'after_hash': after['sha256']})
        if previous:
            details = original
            self.store.resume(operation_id)
        else:
            details = {'payload': payload, 'preparation': None, 'stage': 'imported', 'manifest_hash': manifest_hash,
                       'runtime_receipt': runtime_receipt, 'seconds': seconds, 'budget': budget, 'source_label': 'saved evidence'}
            self.store.start_coding(operation_id, payload, details)
        return self._complete(operation_id, details, candidate, runtime_receipt, receipt)
