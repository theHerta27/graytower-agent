"""Trusted single-operator localhost A2A; no OAuth, tenant isolation or SDK patch.

Frozen numeric-config and bounded Python-code requests are supported. Each send creates a new
protocol Task; durable business receipts deduplicate request_id. Continuation
and cancellation are deliberately unsupported in this V1 product interface.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
import math
from pathlib import Path
import socket
from urllib.parse import urlsplit
import uuid

import httpx
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette
import uvicorn

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.server.agent_execution import AgentExecutor, SimpleRequestContextBuilder
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import DatabaseTaskStore, TaskUpdater
from a2a.types import (AgentCapabilities, AgentCard, AgentInterface, AgentSkill,
                      GetTaskRequest, Message, Part, Role, SendMessageRequest,
                      Task, TaskState, TaskStatus)
from a2a.utils.errors import InvalidParamsError, TaskNotCancelableError, UnsupportedOperationError

from .domain._shared import Artifacts, PROFILE, valid_hash
from .jobs import JobStore


class VerificationFailedError(RuntimeError):
    def __init__(self, task_id: str, task_state: str, detail: str):
        self.task_id, self.task_state = task_id, task_state
        super().__init__(f'{task_state} ({task_id}): {detail}')


def _payload(message) -> dict:
    if message.role != Role.ROLE_USER or len(message.parts) != 1 or not message.parts[0].HasField('data'):
        raise InvalidParamsError('One structured user request is required')
    value = MessageToDict(message.parts[0].data)
    fields = {'request_id', 'manifest_hash', 'goal', 'max_battles', 'kind', 'profile'}
    if not isinstance(value, dict) or set(value) != fields:
        raise InvalidParamsError('Invalid verification request fields')
    from .code_candidates import PROFILES
    if (value['kind'], value['profile']) not in [('numeric_config', PROFILE), *[('code', p) for p in PROFILES]]:
        raise UnsupportedOperationError('Unsupported candidate kind/profile')
    if any(not isinstance(value[key], str) for key in ('request_id', 'manifest_hash', 'goal')):
        raise InvalidParamsError('Request id, manifest hash and goal must be strings')
    # Protobuf Value carries all JSON numbers as double. Reject booleans,
    # fractions and non-finite values before converting an exact integer.
    budget = value['max_battles']
    if type(budget) not in (int, float) or not math.isfinite(budget) or budget != int(budget):
        raise InvalidParamsError('max_battles must be an integer')
    value['max_battles'] = int(budget)
    return value


class _AdmissionContext(SimpleRequestContextBuilder):
    """Use the public SDK admission extension before ActiveTask allocation."""
    def __init__(self, root: Path, store: JobStore):
        super().__init__()
        self.artifacts, self.store = Artifacts(root / 'artifacts'), store

    async def build(self, context, params=None, task_id=None, context_id=None, task=None):
        if task_id:
            raise UnsupportedOperationError('V1 accepts a new Task only; read completed tasks with GetTask')
        if params is None:
            raise InvalidParamsError('A verification request is required')
        value = _payload(params.message)
        try:
            manifest = self.artifacts.read(valid_hash(value['manifest_hash']))
            if value['kind'] == 'code':
                from .code_tools import CodeCatalog
                manifest = CodeCatalog(self.store.root).workspace(value['manifest_hash']).inspect(value['manifest_hash'])['manifest']
                if manifest['profile'] != value['profile']:
                    raise UnsupportedOperationError('Code candidate profile mismatch')
            elif (manifest.get('schema_version') != 'candidate-manifest-v1'
                    or manifest.get('kind') != 'numeric_config' or manifest.get('profile') != PROFILE
                    or manifest.get('author') not in ('config', 'coding')):
                raise UnsupportedOperationError('Unsupported candidate manifest kind/profile/author')
            if manifest.get('author') == 'coding':
                source = self.artifacts.read_ref(manifest.get('coding_source'), 'coding-source-v1')
                if source.get('schema_version') != 'coding-source-v1':
                    raise ValueError('Malformed coding source artifact')
                # Full source/bytes/scope checks belong to the same independent
                # worker inspection used by QA. Admission never runs a build.
            self.store.admit(value['request_id'], value['manifest_hash'], value['goal'], value['max_battles'])
        except (ValueError, TypeError) as exc:
            raise InvalidParamsError(str(exc)) from exc
        return await super().build(context, params, task_id, context_id, task)


class _LocalHandler(DefaultRequestHandler):
    async def on_cancel_task(self, params, context):
        # Reject at the handler boundary: SDK ActiveTask.cancel() cancels its
        # producer in finally even when executor.cancel() raises an exception.
        raise TaskNotCancelableError('V1 cannot safely cancel physical verification work')


class _VerificationExecutor(AgentExecutor):
    def __init__(self, store: JobStore, callback: Callable[[str], Awaitable[dict]]):
        self.store, self.callback = store, callback
        self.driver = asyncio.Lock()

    async def cancel(self, context, event_queue):
        raise TaskNotCancelableError('Cancellation is unsupported by the local verification worker')

    async def execute(self, context, event_queue):
        value = _payload(context.message)
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await event_queue.enqueue_event(Task(id=context.task_id, context_id=context.context_id,
                                            status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                                            history=[context.message]))
        await updater.start_work()
        try:
            # One local callback at a time; a simultaneous duplicate rechecks
            # the durable report after acquiring the driver.
            async with self.driver:
                request = self.store.get(value['request_id'])
                report = request['report']
                if report is None:
                    report = await self.callback(value['request_id'])
                if (not isinstance(report, dict) or report.get('request_id') != value['request_id']
                        or report.get('manifest_hash') != value['manifest_hash']):
                    raise ValueError('Verification report identity mismatch')
                # QA normally persists first. complete() is immutable and
                # idempotent; ensure delivery never outruns its durable receipt.
                self.store.complete(value['request_id'], report)
            await updater.add_artifact(parts=[Part(data=ParseDict(report, Value()))],
                                       name='verification-report', last_chunk=True)
            await updater.complete()
        except Exception as exc:
            # Keep execution failure distinct from a delivered FAIL/INCONCLUSIVE
            # report; avoid exposing provider secrets from arbitrary exceptions.
            detail = f'Verification execution failed ({type(exc).__name__}); inspect local evidence before retrying.'
            await updater.failed(message=updater.new_agent_message([Part(text=detail)]))


@asynccontextmanager
async def local_verifier(root: Path, verify_callback: Callable[[str], Awaitable[dict]], port: int = 0):
    """Serve only 127.0.0.1; caller owns callback/job shutdown semantics."""
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('invalid localhost port')
    root = Path(root).resolve()
    store = JobStore(root)
    engine = create_async_engine(URL.create('sqlite+aiosqlite', database=str(root / 'a2a-tasks.sqlite')))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_task = None
    handler = None
    try:
        task_store = DatabaseTaskStore(engine=engine)
        await task_store.initialize()
        sock.bind(('127.0.0.1', port))
        sock.listen(128)
        sock.setblocking(False)
        base = f'http://127.0.0.1:{sock.getsockname()[1]}'
        card = AgentCard(
            name='Local Verification', version='local-v1',
            description='Local Config/Coding verification: numeric simulation and approved Python test profiles.',
            capabilities=AgentCapabilities(streaming=False, push_notifications=False),
            default_input_modes=['application/json'], default_output_modes=['application/json'],
            skills=[AgentSkill(id='verify_candidate', name='Verify candidate',
                               description='Deliver frozen-candidate evidence for numeric_config and bounded code profiles.',
                               tags=['verification', 'numeric_config', 'code'])],
            supported_interfaces=[AgentInterface(protocol_binding='JSONRPC', protocol_version='1.0', url=base + '/a2a/jsonrpc')])
        handler = _LocalHandler(agent_executor=_VerificationExecutor(store, verify_callback),
                                task_store=task_store, agent_card=card,
                                request_context_builder=_AdmissionContext(root, store))

        @asynccontextmanager
        async def lifespan(app):
            yield
            await handler.aclose()

        app = Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, '/a2a/jsonrpc'), lifespan=lifespan)
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', log_config=None,
                                              log_level='warning', access_log=False, timeout_graceful_shutdown=3))
        server_task = asyncio.create_task(server.serve(sockets=[sock]), name='local-verifier-http')
        for _ in range(500):
            if server.started:
                break
            if server_task.done():
                await server_task
                raise RuntimeError('Local verifier server exited before startup')
            await asyncio.sleep(.01)
        else:
            raise RuntimeError('Local verifier server startup timed out')
        yield base
    finally:
        try:
            if server_task is not None:
                server.should_exit = True
                await asyncio.wait_for(server_task, 10)
        finally:
            try:
                if handler is not None:
                    await handler.aclose()
            finally:
                sock.close()
                await engine.dispose()


async def delegate(base_url: str, request_id: str, manifest_hash: str, goal: str, max_battles: int, *, kind='numeric_config', profile=PROFILE) -> dict:
    """New Task send followed by GetTask. Never append or implicitly retry."""
    url = urlsplit(base_url)
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.password or url.query or url.fragment:
        raise ValueError('Only an explicit http://127.0.0.1 localhost verifier is supported')
    payload = dict(request_id=request_id, manifest_hash=manifest_hash, goal=goal,
                   max_battles=max_battles, kind=kind, profile=profile)
    # No implicit HTTP/provider retries. A timeout has an unknown outcome and
    # must be reconciled from the durable request, not a fresh business id.
    async with httpx.AsyncClient(trust_env=False, timeout=300, follow_redirects=False) as http:
        card = await A2ACardResolver(http, base_url).get_agent_card()
        interfaces = [item for item in card.supported_interfaces
                      if item.protocol_binding == 'JSONRPC' and item.protocol_version == '1.0']
        if not interfaces:
            raise ValueError('Local verifier Card must advertise JSONRPC 1.0')
        for interface in interfaces:
            endpoint = urlsplit(interface.url)
            if (endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1'
                    or (endpoint.port or 80) != (url.port or 80) or endpoint.username or endpoint.password
                    or endpoint.query or endpoint.fragment):
                raise ValueError('Verifier Card endpoint must stay on the requested localhost origin')
        # Pass only the checked interfaces to the public factory, so a Card
        # cannot select another binding/version or resolve a second Card.
        checked_card = AgentCard()
        checked_card.CopyFrom(card)
        checked_card.ClearField('supported_interfaces')
        checked_card.supported_interfaces.extend(interfaces)
        client = await create_client(checked_card, client_config=ClientConfig(
            streaming=False, httpx_client=http, supported_protocol_bindings=['JSONRPC']))
        message = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER,
                          parts=[Part(data=ParseDict(payload, Value()))])
        events = [event async for event in client.send_message(SendMessageRequest(message=message))]
        task_event = next((event.task for event in events if event.HasField('task')), None)
        if task_event is None:
            raise RuntimeError('Verification server returned no Task')
        task = await client.get_task(GetTaskRequest(id=task_event.id))
    state = TaskState.Name(task.status.state)
    if task.status.state != TaskState.TASK_STATE_COMPLETED:
        detail = ' '.join(part.text for part in task.status.message.parts if part.HasField('text'))
        raise VerificationFailedError(task.id, state, detail or 'No completed verification report')
    reports = [MessageToDict(part.data) for artifact in task.artifacts if artifact.name == 'verification-report'
               for part in artifact.parts if part.HasField('data')]
    if (len(reports) != 1 or not isinstance(reports[0], dict)
            or reports[0].get('request_id') != request_id or reports[0].get('manifest_hash') != manifest_hash
            or reports[0].get('verdict') not in ('FAIL', 'INCONCLUSIVE', 'PASS')
            or reports[0].get('verdict') == 'PASS' and kind != 'code'):
        raise RuntimeError('Verification report missing or inconsistent with the request')
    return {'task_id': task.id, 'task_state': state, 'report': reports[0],
            'events': [MessageToDict(event) for event in events]}
