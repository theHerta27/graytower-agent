"""Single-operator localhost HTTP UI over the real Config/MCP/A2A services.

Model authority is startup-only and disabled by default. Operations persist
before execution; reopening the UI or process never repeats an interrupted call.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .domain import CandidateRepository
from .domain._shared import PROFILE, valid_hash
from .jobs import JobStore
from .report_view import facts_for_report, render_report
from .verification.store import driver_lock
from .workbench_store import OperationConflict, WorkbenchStore


class APIError(Exception):
    def __init__(self, code, message, status=422):
        self.code, self.message, self.status = code, message, status


class NoModelCalls:
    """Resume admitted checkpoints/receipts without granting fresh inference."""
    def remaining_calls(self):
        return 0

    def complete(self, *args, **kwargs):
        raise RuntimeError('new model calls are disabled')


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class DraftInput(Input):
    operation_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    request: str = Field(min_length=1, max_length=4000)
    parent_manifest: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class CodingInput(Input):
    operation_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    request: str = Field(min_length=1, max_length=4000)
    mode: Literal['single', 'auto']


class CandidateInput(Input):
    manifest_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class VerificationInput(CandidateInput):
    request_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    goal: str = Field(min_length=1, max_length=3000)
    max_battles: StrictInt = Field(ge=2, le=12)


def failure(code, message, status):
    return JSONResponse({'error': {'code': code, 'message': message}}, status_code=status)


class LocalOriginMiddleware:
    """Reject DNS rebinding and cross-origin browser requests; no public auth claim."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            headers = scope['headers']
            hosts = [v.decode('latin-1') for k, v in headers if k.lower() == b'host']
            origins = [v.decode('latin-1') for k, v in headers if k.lower() == b'origin']
            try:
                host = urlsplit('http://' + (hosts[0] if len(hosts) == 1 else ''))
                host_port = host.port or 80  # Validate even when Origin is absent.
                allowed = (host.hostname in ('127.0.0.1', 'localhost') and not host.username
                           and not host.password and not host.path and not host.query and not host.fragment)
                if len(origins) > 1:
                    allowed = False
                elif origins:
                    origin = urlsplit(origins[0])
                    allowed = allowed and (origin.scheme == scope['scheme'] == 'http'
                        and origin.hostname == host.hostname and (origin.port or 80) == host_port
                        and not origin.username and not origin.password and not origin.path
                        and not origin.query and not origin.fragment)
                # Browsers can omit Origin on reads; Fetch Metadata remains useful.
                if any(k.lower() == b'sec-fetch-site' and v == b'cross-site' for k, v in headers):
                    allowed = False
            except ValueError:
                allowed = False
            if not allowed:
                await failure('forbidden_origin', '仅允许本机同源工作台访问。', 403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class Workbench:
    def __init__(self, root, *, call_cap, audit_path, model_factory, model_actions, coding_service=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if type(call_cap) is not int or call_cap < 0:
            raise ValueError('call_cap must be a nonnegative integer')
        if call_cap and audit_path is None:
            raise ValueError('positive call_cap requires an explicit shared audit_path')
        if (not isinstance(model_actions, (tuple, list)) or not model_actions
                or any(action not in ('draft', 'verify') for action in model_actions)):
            raise ValueError('model_actions must contain draft and/or verify')
        self.model_actions = tuple(dict.fromkeys(model_actions))
        self.jobs, self.repo = JobStore(self.root), CandidateRepository(self.root)
        self.operations = WorkbenchStore(self.root)
        from .coding.service import CodingService
        self.coding = coding_service or CodingService(self.root, store=self.operations, repo=self.repo)
        if self.coding.root != self.root:
            raise ValueError('Coding service must use the same local data root')
        self.model = None
        if call_cap:
            if model_factory is None:
                from .models import ModelGateway
                model_factory = ModelGateway
            self.model = model_factory(model='deepseek-flash', max_calls=call_cap,
                max_input_chars=32000, max_output_tokens=2048, audit_path=Path(audit_path).resolve())
        self.admission = asyncio.Lock()
        self.task = None

    def model_status(self):
        if self.model is None:
            return {'enabled': False, 'remaining_calls': 0, 'actions': [],
                    'reason': '模型已关闭；可查看、确认已有候选并读取证据。'}
        try:
            remaining = self.model.remaining_calls()
            if type(remaining) is not int or remaining < 0:
                raise ValueError('invalid budget')
        except Exception:
            return {'enabled': False, 'remaining_calls': 0, 'actions': [], 'reason': '共享模型账本不可核验，已禁止新调用。'}
        return {'enabled': remaining > 0, 'remaining_calls': remaining,
                'actions': list(self.model_actions) if remaining else [],
                'reason': '使用启动时明确指定的共享调用额度。' if remaining else '共享模型调用额度已用尽。'}

    def require_model(self, action):
        status = self.model_status()
        if not status['enabled']:
            raise APIError('model_disabled', status['reason'], 403)
        if action not in self.model_actions:
            raise APIError('action_disabled', '本次启动没有启用该模型操作。', 403)

    def require_idle(self):
        if self.task is not None and not self.task.done():
            raise APIError('busy', '当前已有任务执行，请等待完成后再提交。', 409)

    def confirmed(self, manifest_hash):
        with closing(self.jobs.connect()) as db:
            return db.execute('SELECT 1 FROM confirmations WHERE manifest=?', (manifest_hash,)).fetchone() is not None

    def candidate(self, manifest_hash):
        candidate = self.repo.get(valid_hash(manifest_hash))
        return {key: candidate[key] for key in ('manifest_hash', 'diff', 'validation')} | {
            'request': candidate['manifest']['request'], 'confirmed': self.confirmed(manifest_hash)}

    def candidate_list(self):
        hashes = set(self.operations.candidates())
        with closing(self.jobs.connect()) as db:
            hashes.update(row['manifest'] for row in db.execute('SELECT manifest FROM confirmations'))
            ids = [row['id'] for row in db.execute('SELECT id FROM requests')]
        hashes.update(self.jobs.get(request_id)['manifest_hash'] for request_id in ids)
        return [self.candidate(manifest_hash) for manifest_hash in sorted(hashes)]

    def request_list(self):
        with closing(self.jobs.connect()) as db:
            ids = [row['id'] for row in db.execute('SELECT id FROM requests ORDER BY rowid DESC')]
        result = []
        for request_id in ids:
            request = self.jobs.get(request_id)
            result.append({key: request[key] for key in ('request_id', 'manifest_hash', 'goal', 'status',
                                                        'charged_battles', 'max_battles')} | {
                'verdict': request['report']['verdict'] if request['report'] else None})
        return result

    def request_detail(self, request_id):
        request = self.jobs.get(request_id)
        report = request['report']
        return {'request': request, 'facts': facts_for_report(report) if report else None,
                'report_text': render_report(report) if report else None}

    async def run_draft(self, payload):
        from .config import ConfigAgent
        result = await asyncio.to_thread(ConfigAgent(self.repo, self.model).draft, **payload)
        if result.get('status') == 'candidate':
            self.operations.remember_candidate(result['candidate']['manifest_hash'])
        return result

    async def run_verification(self, payload):
        from .protocol import delegate, local_verifier
        saved = self.jobs.get(payload['request_id'])['report']
        if saved is not None:
            async def completed(request_id):
                return self.jobs.get(request_id)['report']
            async with local_verifier(self.root, completed) as endpoint:
                return await delegate(endpoint, **payload)
        from .game_tools import connect_tools
        from .verification.agent import VerificationAgent
        async with connect_tools(self.root) as tools:
            model = self.model if self.model is not None and 'verify' in self.model_actions else NoModelCalls()
            agent = VerificationAgent(self.root, model, tools)
            async with local_verifier(self.root, agent.run) as endpoint:
                return await delegate(endpoint, **payload)

    def launch(self, operation_id, kind, payload, *, recover_coding=False):
        async def work():
            try:
                if kind == 'coding':
                    run = self.coding.recover if recover_coding else self.coding.execute
                    completed = await asyncio.to_thread(run, operation_id)
                    result = completed['result']
                else:
                    result = await (self.run_draft(payload) if kind == 'draft' else self.run_verification(payload))
            except asyncio.CancelledError:
                # A thread or physical worker may still be running. Keep the
                # durable running claim for next startup's interrupted state.
                raise
            except Exception as exc:
                self.operations.finish(operation_id, error=f'执行未完成（{type(exc).__name__}）；请保留已有证据后检查。')
            else:
                self.operations.finish(operation_id, result=result)
        self.task = asyncio.create_task(work(), name='workbench-' + operation_id)

    async def start_coding(self, value):
        payload = value.model_dump()
        async with self.admission:
            previous = self.operations.existing(value.operation_id, 'coding', payload)
            if previous:
                return previous
            self.require_idle()
            if not self.coding.status()['enabled']:
                raise APIError('coding_disabled', self.coding.status()['reason'], 403)
            try:
                operation = self.coding.admit(payload)
            except ValueError:
                raise APIError('coding_not_authorized', '任务内容或模式不符合本次启动授权。', 403) from None
            self.launch(value.operation_id, 'coding', payload)
            return operation

    async def recover_coding(self, operation_id):
        async with self.admission:
            saved = self.coding.get_run(operation_id)
            if saved['status'] in ('completed', 'running'):
                return self.operations.get(operation_id)
            self.require_idle()
            try:
                self.coding.require_receipt(operation_id)
            except ValueError:
                raise APIError('recovery_required', '缺少完整 Runtime 收据；保留现场，不会重新调用模型。', 409) from None
            operation = self.operations.resume(operation_id)
            self.launch(operation_id, 'coding', {}, recover_coding=True)
            return operation

    async def draft(self, value):
        payload = value.model_dump(exclude={'operation_id'})
        if not payload['request'].strip():
            raise APIError('invalid_input', '需求不能为空。')
        async with self.admission:
            previous = self.operations.existing(value.operation_id, 'draft', payload)
            if previous:
                return previous
            self.require_model('draft')
            self.require_idle()
            if value.parent_manifest is not None:
                await asyncio.to_thread(self.repo.get, value.parent_manifest)
            operation = self.operations.start(value.operation_id, 'draft', payload)
            self.launch(value.operation_id, 'draft', payload)
            return operation

    async def verify(self, value, *, resume=False):
        payload = value.model_dump()
        operation_id = 'verify_' + value.request_id
        async with self.admission:
            previous = self.operations.existing(operation_id, 'verify', payload)
            if previous and (not resume or previous['status'] in ('running', 'completed')):
                return previous
            try:
                request = self.jobs.get(value.request_id)
            except KeyError:
                request = None
            if request is not None and any(request[key] != payload[key] for key in payload):
                raise OperationConflict('same request id has different immutable input')
            if request is None or (request['report'] is None and not resume):
                self.require_model('verify')
            self.require_idle()
            if request is not None and request['report'] is None:
                with closing(self.jobs.connect()) as db:
                    unknown = db.execute("SELECT 1 FROM jobs WHERE request_id=? AND state='running'",
                                         (value.request_id,)).fetchone()
                if unknown:
                    raise APIError('recovery_required', '存在已启动但没有完成收据的作业；请先核对现场，不能重新执行。', 409)
            # Completed reports remain readable/deliverable even if today's game
            # environment has changed; new QA must inspect the frozen candidate.
            if request is None:
                await asyncio.to_thread(self.repo.get, value.manifest_hash)
            if not self.confirmed(value.manifest_hash):
                raise APIError('candidate_unconfirmed', '请先按候选 hash 确认，再委托独立验证。', 409)
            self.jobs.admit(**payload)
            operation = self.operations.resume(operation_id) if previous else self.operations.start(operation_id, 'verify', payload)
            self.launch(operation_id, 'verify', payload)
            return operation


async def body(request, schema):
    raw = await request.body()
    if len(raw) > 65536:
        raise APIError('invalid_input', '请求内容过长。', 413)
    try:
        return schema.model_validate_json(raw)
    except (ValidationError, ValueError):
        raise APIError('invalid_input', '请求字段、类型或范围无效。') from None


def create_app(root, *, call_cap=0, audit_path=None, model_factory=None, frontend_dist=None,
               model_actions=('draft', 'verify'), coding_service=None):
    """Startup authority cannot be set by HTTP. model_factory is an offline test seam."""
    workbench = Workbench(root, call_cap=call_cap, audit_path=audit_path,
                          model_factory=model_factory, model_actions=model_actions, coding_service=coding_service)

    @asynccontextmanager
    async def lifespan(app):
        # This service is one local driver. Do not recover another live instance.
        with driver_lock(workbench.root / 'workbench-driver'):
            workbench.operations.interrupt_running()
            yield
            if workbench.task is not None and not workbench.task.done():
                # Graceful shutdown drains accepted work. Hard termination leaves
                # receipts/checkpoints for an explicit operator decision.
                await workbench.task

    async def status(request):
        return JSONResponse({'model': workbench.model_status(), 'coding': workbench.coding.status(), 'profile': PROFILE})

    async def coding_runs(request):
        if request.method == 'POST':
            return JSONResponse(await workbench.start_coding(await body(request, CodingInput)), status_code=202)
        return JSONResponse({'runs': workbench.coding.list_runs()})

    async def coding_detail(request):
        return JSONResponse({'run': workbench.coding.get_run(request.path_params['operation_id'])})

    async def coding_recover(request):
        if (await request.body()).strip() not in (b'', b'{}'):
            raise APIError('invalid_input', '收尾只能使用原任务和收据，不接受新参数。')
        return JSONResponse(await workbench.recover_coding(request.path_params['operation_id']), status_code=202)

    async def candidates(request):
        return JSONResponse({'candidates': await asyncio.to_thread(workbench.candidate_list)})

    async def inspect_candidate(request):
        value = await body(request, CandidateInput)
        candidate = await asyncio.to_thread(workbench.candidate, value.manifest_hash)
        workbench.operations.remember_candidate(value.manifest_hash)
        return JSONResponse(candidate)

    async def confirm_candidate(request):
        # Confirmation contains no mutable fields, directories or authority.
        if (await request.body()).strip() not in (b'', b'{}'):
            raise APIError('invalid_input', '确认操作不接受附加字段。')
        manifest_hash = valid_hash(request.path_params['manifest_hash'])
        candidate = await asyncio.to_thread(workbench.candidate, manifest_hash)
        workbench.jobs.confirm(manifest_hash)
        workbench.operations.remember_candidate(manifest_hash)
        return JSONResponse({**candidate, 'confirmed': True})

    async def requests(request):
        return JSONResponse({'requests': workbench.request_list()})

    async def request_detail(request):
        return JSONResponse(workbench.request_detail(request.path_params['request_id']))

    async def trace(request):
        from .game_tools import GameTools
        value = await asyncio.to_thread(GameTools(workbench.root).read_trace,
            request.path_params['request_id'], valid_hash(request.path_params['artifact_hash']))
        return JSONResponse(value)

    async def drafts(request):
        return JSONResponse(await workbench.draft(await body(request, DraftInput)), status_code=202)

    async def verifications(request):
        return JSONResponse(await workbench.verify(await body(request, VerificationInput)), status_code=202)

    async def resume(request):
        if (await request.body()).strip() not in (b'', b'{}'):
            raise APIError('invalid_input', '恢复只能使用原请求，不接受新参数。')
        saved = workbench.jobs.get(request.path_params['request_id'])
        value = VerificationInput.model_validate({key: saved[key] for key in VerificationInput.model_fields})
        return JSONResponse(await workbench.verify(value, resume=True), status_code=202)

    async def operation(request):
        return JSONResponse(workbench.operations.get(request.path_params['operation_id']))

    async def api_error(request, exc):
        return failure(exc.code, exc.message, exc.status)

    async def conflict(request, exc):
        return failure('idempotency_conflict', '同一业务 ID 已绑定其他参数；原记录未更改。', 409)

    async def missing(request, exc):
        return failure('not_found', '未找到该记录。', 404)

    async def invalid(request, exc):
        return failure('invalid_input', '输入或证据校验未通过；原记录未更改。', 422)

    async def unexpected(request, exc):
        return failure('internal_error', '服务暂时无法完成请求，请检查本机运行状态。', 500)

    async def http_error(request, exc):
        return failure('not_found' if exc.status_code == 404 else 'method_not_allowed', '接口不存在或方法不受支持。', exc.status_code)

    async def missing_frontend(request):
        return PlainTextResponse('前端尚未构建。请在 frontend 目录运行 npm run build，再启动工作台。', status_code=503)

    routes = [Route('/api/status', status), Route('/api/candidates', candidates),
        Route('/api/coding/runs', coding_runs, methods=['GET', 'POST']),
        Route('/api/coding/runs/{operation_id}', coding_detail),
        Route('/api/coding/runs/{operation_id}/resume', coding_recover, methods=['POST']),
        Route('/api/candidates/inspect', inspect_candidate, methods=['POST']),
        Route('/api/candidates/{manifest_hash}/confirm', confirm_candidate, methods=['POST']),
        Route('/api/requests', requests), Route('/api/requests/{request_id}', request_detail),
        Route('/api/requests/{request_id}/traces/{artifact_hash}', trace),
        Route('/api/drafts', drafts, methods=['POST']),
        Route('/api/verifications', verifications, methods=['POST']),
        Route('/api/verifications/{request_id}/resume', resume, methods=['POST']),
        Route('/api/operations/{operation_id}', operation)]
    dist = Path(frontend_dist) if frontend_dist is not None else Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    routes.append(Mount('/', app=StaticFiles(directory=dist, html=True)) if (dist / 'index.html').is_file()
                  else Route('/', missing_frontend))
    app = Starlette(routes=routes, lifespan=lifespan, exception_handlers={
        APIError: api_error, OperationConflict: conflict, KeyError: missing,
        ValueError: invalid, HTTPException: http_error, Exception: unexpected})
    app.add_middleware(LocalOriginMiddleware)
    return app


def serve(root, *, port=8765, call_cap=0, audit_path=None, model_actions=('draft', 'verify')):
    import uvicorn
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('port must be in 1..65535')
    app = create_app(root, call_cap=call_cap, audit_path=audit_path, model_actions=model_actions)
    uvicorn.run(app, host='127.0.0.1', port=port, access_log=False, log_level='warning')
