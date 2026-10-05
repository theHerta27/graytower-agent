"""Zero-model A2A 1.2.1 official Hello World lifecycle reproduction.

Run with research/.venv-protocols/Scripts/python.exe. The parent runs each
scenario in a separate process and exits 2 if SDK lifecycle cleanup fails.
The pinned source snapshot is kept byte-for-byte apart from filesystem EOL.
Only SampleAgentExecutor is compiled unchanged from its AST; grpc/FastAPI
imports and unrelated transports in the official sample are deliberately not
loaded. JSONRPC routes + InMemoryTaskStore + DefaultRequestHandler remain SDK.
No LangGraph, MCP, business code, monkeypatch, or SDK modification is used.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import gc
import hashlib
import importlib.metadata
import inspect
import json
import logging
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tempfile
import threading
import uuid

import httpx
import uvicorn
from google.protobuf.json_format import MessageToDict
from starlette.applications import Starlette
from a2a.client import ClientConfig, create_client
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import (
    AgentCapabilities, AgentCard, AgentInterface, AgentSkill, GetTaskRequest,
    Message, Part, Role, SendMessageRequest, Task, TaskState, TaskStatus,
)
from a2a.utils.errors import UnsupportedOperationError

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'research/evidence/a2a-official-minimal-source-v1.2.1.py'
SOURCE_URL = 'https://github.com/a2aproject/a2a-python/blob/v1.2.1/samples/hello_world_agent.py'
SOURCE_BLOB = 'bf38077ddc324f218f3333bd56116665f8eeb1e1'


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def source_executor():
    source_text = SOURCE.read_text(encoding='utf-8')
    source_bytes = source_text.encode('utf-8')
    blob_hash = hashlib.sha1(b'blob ' + str(len(source_bytes)).encode() + b'\0' + source_bytes).hexdigest()
    if blob_hash != SOURCE_BLOB:
        raise RuntimeError(f'Official source snapshot changed: {blob_hash}')
    tree = ast.parse(source_text, filename=str(SOURCE))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SampleAgentExecutor')
    namespace = dict(globals(), logger=logging.getLogger('official.hello_world'))
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['SampleAgentExecutor'](), blob_hash


def snapshot(handler=None):
    current = asyncio.current_task()
    tasks = []
    for task in asyncio.all_tasks():
        if task is current:
            continue
        coroutine = str(task.get_coro())
        tasks.append({'name': task.get_name(), 'coroutine': coroutine,
                      'done': task.done(), 'cancelled': task.cancelled()})
    result = {
        'dispatcher_count': sum('EventQueueSource._dispatch_loop' in t['coroutine'] for t in tasks),
        'all_other_pending_asyncio_count': len(tasks),
        'pending_asyncio': sorted(tasks, key=lambda t: (t['name'], t['coroutine'])),
        'live_threads': [{'name': t.name, 'daemon': t.daemon} for t in threading.enumerate()],
    }
    if handler is not None:
        # Read-only diagnostic inspection, never mutate or close private objects.
        registry = handler._active_task_registry
        result['registry_active_count'] = len(registry._active_tasks)
        result['registry_cleanup_count'] = len(registry._cleanup_tasks)
    return result


async def run_case(mode: str, repeats: int, streaming: bool):
    executor, blob_hash = source_executor()
    result = {
        'case': mode, 'repeats': repeats, 'streaming': streaming,
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(), 'a2a_sdk': importlib.metadata.version('a2a-sdk'),
        'source_url': SOURCE_URL, 'source_git_blob': blob_hash,
        'source_sha256_lf': hashlib.sha256(SOURCE.read_text(encoding='utf-8').encode()).hexdigest(),
        'model_calls': 0, 'sdk_patched': False, 'snapshots': {}, 'rejections': [],
        'cleanup_pass_scope': 'EventQueueSource dispatchers and recorded loop errors only; other live tasks are separately enumerated',
        'sdk_source_hashes': {
            name: hashlib.sha256(Path(inspect.getfile(__import__(name, fromlist=['']))).read_bytes()).hexdigest()
            for name in ('a2a.server.agent_execution.active_task', 'a2a.server.agent_execution.active_task_registry',
                         'a2a.server.events.event_queue_v2', 'a2a.server.request_handlers.default_request_handler_v2')
        },
        'events': [], 'loop_diagnostics': [], 'functional_checks': {},
    }
    loop = asyncio.get_running_loop()

    def loop_exception(_loop, context):
        result['loop_diagnostics'].append({k: str(v) for k, v in context.items()})
        loop.default_exception_handler(context)

    loop.set_exception_handler(loop_exception)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    sock.setblocking(False)
    base = f'http://127.0.0.1:{sock.getsockname()[1]}'
    card = AgentCard(
        name='Sample Agent', description='Official Hello World minimal JSONRPC reproduction',
        version='1.0.0', capabilities=AgentCapabilities(streaming=True),
        default_input_modes=['text'], default_output_modes=['text', 'task-status'],
        skills=[AgentSkill(id='sample_agent', name='Sample Agent', description='Say hi.', tags=['sample'])],
        supported_interfaces=[AgentInterface(protocol_binding='JSONRPC', protocol_version='1.0', url=base + '/a2a/jsonrpc')],
    )
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=card)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await handler.aclose()
        result['handler_aclose_called'] = True

    app = Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, '/a2a/jsonrpc'), lifespan=lifespan)
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False, timeout_graceful_shutdown=3))
    server_task = asyncio.create_task(server.serve(sockets=[sock]), name='probe-uvicorn')
    try:
        for _ in range(200):
            if server.started:
                break
            if server_task.done():
                await server_task
            await asyncio.sleep(.01)
        if not server.started:
            raise RuntimeError('Loopback server did not start')
        result['snapshots']['before_messages'] = snapshot(handler)
        async with httpx.AsyncClient(trust_env=False, timeout=10) as http:
            client = await create_client(base, client_config=ClientConfig(
                streaming=streaming, httpx_client=http, supported_protocol_bindings=['JSONRPC']))

            async def send(task=None):
                message = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER, parts=[Part(text='hello')])
                if task is not None:
                    message.task_id, message.context_id = task.id, task.context_id
                events = [event async for event in client.send_message(SendMessageRequest(message=message))]
                result['events'].append([MessageToDict(e) for e in events])
                first_task = next(e.task for e in events if e.HasField('task'))
                return await client.get_task(GetTaskRequest(id=first_task.id))

            task = await send()
            await asyncio.sleep(.05)
            result['functional_checks']['first_completed'] = task.status.state == TaskState.TASK_STATE_COMPLETED
            result['functional_checks']['official_reply'] = task.artifacts[0].parts[0].text == 'Hello World! Nice to meet you!'
            result['snapshots']['after_normal_completion'] = snapshot(handler)
            for index in range(repeats):
                if mode == 'terminal':
                    try:
                        await send(task)
                    except UnsupportedOperationError as exc:
                        result['rejections'].append({'type': type(exc).__name__, 'message': str(exc)})
                    else:
                        raise AssertionError('Terminal task continuation unexpectedly accepted')
                else:
                    new_task = await send()
                    if new_task.status.state != TaskState.TASK_STATE_COMPLETED or new_task.id == task.id:
                        raise AssertionError('Fresh official task did not independently complete')
                await asyncio.sleep(.05)
                result['snapshots'][f'after_iteration_{index + 1}'] = snapshot(handler)
            final_task = await client.get_task(GetTaskRequest(id=task.id))
            result['functional_checks']['terminal_task_unchanged'] = final_task == task
            result['functional_checks']['expected_rejections'] = len(result['rejections']) == (repeats if mode == 'terminal' else 0)
        result['snapshots']['after_http_client_close'] = snapshot(handler)
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=8)
        sock.close()
    await asyncio.sleep(.05)
    result['snapshots']['after_handler_aclose'] = snapshot(handler)
    # Diagnostic collection occurs after normal lifecycle teardown and is recorded
    # separately. This never cancels/repairs SDK objects and does not suppress logs.
    result['diagnostic_gc_collected'] = gc.collect()
    await asyncio.sleep(.05)
    result['snapshots']['after_diagnostic_gc'] = snapshot(handler)
    result['functional_passed'] = all(result['functional_checks'].values())
    result['cleanup_passed'] = (
        result['snapshots']['after_handler_aclose']['dispatcher_count'] == 0
        and not result['loop_diagnostics']
    )
    result['loaded_forbidden_modules'] = sorted(k for k in sys.modules if k in ('langgraph', 'mcp') or k.startswith(('langgraph.', 'mcp.')))
    result['scope'] = 'This child process/event loop only; no OS process-tree, external worker, long-service or total-system resource guarantee.'
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--child', choices=['normal', 'terminal'])
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--non-streaming', action='store_true')
    args = parser.parse_args()
    if args.child:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
        result = asyncio.run(run_case(args.child, args.repeats, not args.non_streaming))
        result['threads_after_asyncio_run'] = [{'name': t.name, 'daemon': t.daemon} for t in threading.enumerate()]
        write_json(args.output_dir / 'result.json', result)
        print(json.dumps({'functional_passed': result['functional_passed'], 'cleanup_passed': result['cleanup_passed'], 'result': str(args.output_dir / 'result.json')}))
        return 0 if result['functional_passed'] and result['cleanup_passed'] else 2
    output = args.output_dir or Path(tempfile.mkdtemp(prefix='a2a-official-minimal-20261005-', dir=ROOT / 'research/evidence'))
    output.mkdir(parents=True, exist_ok=True)
    cases = [('normal-stream', 'normal', 2, False), ('normal-send', 'normal', 2, True), ('terminal-stream', 'terminal', 1, False),
             ('terminal-send', 'terminal', 1, True), ('terminal-stream-repeated', 'terminal', 5, False)]
    summary = {'output': str(output), 'cases': {}, 'model_calls': 0,
               'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for name, mode, repeats, non_streaming in cases:
        case_dir = output / name
        case_dir.mkdir()
        command = [sys.executable, str(Path(__file__).resolve()), '--child', mode, '--repeats', str(repeats), '--output-dir', str(case_dir)]
        if non_streaming:
            command.append('--non-streaming')
        with (case_dir / 'console.log').open('w', encoding='utf-8') as log:
            process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=45, check=False)
        result_file = case_dir / 'result.json'
        result = json.loads(result_file.read_text(encoding='utf-8')) if result_file.exists() else {}
        console = (case_dir / 'console.log').read_text(encoding='utf-8')
        summary['cases'][name] = {'exit_code': process.returncode, 'functional_passed': result.get('functional_passed'),
                                  'cleanup_passed': result.get('cleanup_passed'),
                                  'pending_destroyed_count': console.count('Task was destroyed but it is pending!'),
                                  'telemetry_detach_error_count': console.count('Failed to detach context'),
                                  'dispatchers': {k: v['dispatcher_count'] for k, v in result.get('snapshots', {}).items()}}
        print(name, json.dumps(summary['cases'][name]))
    summary['cleanup_passed'] = all(c['cleanup_passed'] for c in summary['cases'].values())
    summary['functional_passed'] = all(c['functional_passed'] for c in summary['cases'].values())
    write_json(output / 'summary.json', summary)
    print(str(output))
    return 0 if all(c['exit_code'] == 0 for c in summary['cases'].values()) else 2


if __name__ == '__main__':
    sys.exit(main())
