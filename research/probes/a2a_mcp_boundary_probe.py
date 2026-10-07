"""Throwaway protocol spike: official A2A 1.0 + MCP 2 + LangGraph fixture.

No LLM, repository upload, production credentials, candidate editing, or product code.
The fixed test bearer values below are deliberately public fixture identities.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import logging
import re
import socket
import sqlite3
import sys
import tempfile
import time
import traceback
import uuid
from contextlib import AsyncExitStack, asynccontextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

import httpx
import uvicorn
from a2a.client import ClientConfig, create_client
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.routes.common import StarletteUser
from a2a.server.tasks import TaskUpdater
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.types import (
    AgentCapabilities, AgentCard, AgentInterface, AgentSkill,
    CancelTaskRequest, GetTaskRequest, ListTasksRequest, Message, Part, Role,
    SendMessageRequest, SubscribeToTaskRequest, Task, TaskState, TaskStatus,
)
from a2a.utils.errors import InvalidParamsError, TaskNotCancelableError, TaskNotFoundError, UnsupportedOperationError
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value
from langgraph.graph import END, START, StateGraph
from mcp import Client as MCPClient
from mcp.client.stdio import StdioServerParameters
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette
from starlette.authentication import SimpleUser
from starlette.responses import JSONResponse


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class PayloadConflict(ValueError):
    pass


class BusinessLedger:
    """Single-host fixture ledger, independent of A2A TaskStore and graph state."""

    def __init__(self, path: Path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (owner TEXT, business_id TEXT, payload_hash TEXT, run_id TEXT, state TEXT, report TEXT, reserved_units INTEGER, PRIMARY KEY(owner,business_id))")

    def claim(self, owner: str, business_id: str, payload_hash: str) -> dict:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload_hash,run_id,state,report FROM requests WHERE owner=? AND business_id=?", (owner, business_id)).fetchone()
            if row:
                if row[0] != payload_hash:
                    raise PayloadConflict("same business id has different immutable input")
                return {"state": row[2], "run_id": row[1], "report": json.loads(row[3]) if row[3] else None}
            run_id = str(uuid.uuid4())
            db.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?)", (owner, business_id, payload_hash, run_id, "running", None, 1))
            return {"state": "new", "run_id": run_id}

    def complete(self, owner: str, business_id: str, report: dict) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            changed = db.execute("UPDATE requests SET state='completed',report=? WHERE owner=? AND business_id=? AND state='running'", (canonical(report), owner, business_id)).rowcount
            if changed != 1:
                raise RuntimeError("receipt commit requires an existing running request")

    def reservations(self) -> int:
        with closing(sqlite3.connect(self.path)) as db, db:
            return db.execute("SELECT COALESCE(SUM(reserved_units),0) FROM requests").fetchone()[0]


def resolve_ref(root: Path, ref: str, scheme: str) -> Path:
    match = re.fullmatch(rf"{scheme}://([a-zA-Z0-9_-]+)", ref)
    if not match:
        raise ValueError("invalid fixture content reference")
    folder = "candidates" if scheme == "candidate" else "artifacts"
    path = (root / folder / (match[1] + ".json")).resolve()
    if not path.is_relative_to((root / folder).resolve()):
        raise ValueError("reference escapes fixture storage")
    return path


def serve_mcp(root: Path) -> None:
    """Official MCPServer in its own stdio process; candidate tools are read-only."""
    server = MCPServer("verification-fixture-tools", version="fixture-1", log_level="WARNING")

    def record(tool: str, ctx: Context, data: dict) -> None:
        with (root / "mcp-tool-calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(canonical({"tool": tool, "mcp_request_id": ctx.request_id, "data": data}) + "\n")

    @server.tool(structured_output=True)
    async def query_schema(ctx: Context) -> dict[str, Any]:
        """Return the fixed fixture candidate schema, without accessing a repository."""
        record("query_schema", ctx, {})
        return {"schema_version": 1, "required": ["attack_multiplier", "sample_count"], "allowed_multiplier": [0, 2], "fixture_only": True}

    @server.tool(structured_output=True)
    async def validate(candidate_ref: str, candidate_sha256: str, ctx: Context) -> dict[str, Any]:
        """Read a frozen JSON candidate, verify its hash and inspect fixture constraints."""
        raw = resolve_ref(root, candidate_ref, "candidate").read_bytes()
        actual = digest(raw)
        record("validate", ctx, {"candidate_ref": candidate_ref, "actual_sha256": actual})
        if actual != candidate_sha256:
            raise ValueError("candidate hash mismatch")
        value = json.loads(raw)
        multiplier = value.get("attack_multiplier")
        valid = isinstance(multiplier, (int, float)) and not isinstance(multiplier, bool) and 0 < multiplier <= 2
        return {"valid": valid, "sample_count": value.get("sample_count", 0), "candidate_sha256": actual}

    @server.tool(structured_output=True)
    async def read_artifact(artifact_ref: str, artifact_sha256: str, ctx: Context) -> dict[str, Any]:
        """Read a hash-checked fixture artifact; no arbitrary filesystem paths."""
        raw = resolve_ref(root, artifact_ref, "evidence").read_bytes()
        if digest(raw) != artifact_sha256:
            raise ValueError("artifact hash mismatch")
        record("read_artifact", ctx, {"artifact_ref": artifact_ref})
        return json.loads(raw)

    server.run(transport="stdio")


class GraphState(TypedDict, total=False):
    payload: dict
    run_id: str
    owner: str
    schema: dict
    observation: dict
    report: dict


def fixture_graph(mcp: MCPClient, root: Path):
    async def investigate(state: GraphState):
        schema = await mcp.call_tool("query_schema")
        observed = await mcp.call_tool("validate", {
            "candidate_ref": state["payload"]["candidate_ref"],
            "candidate_sha256": state["payload"]["candidate_sha256"],
        })
        with (root / "mcp-responses.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(canonical({"schema": schema.model_dump(by_alias=True, mode="json"), "observed": observed.model_dump(by_alias=True, mode="json")}) + "\n")
        if schema.is_error or observed.is_error:
            raise ValueError("MCP fixture validation failed")
        return {"schema": schema.structured_content, "observation": observed.structured_content}

    async def conclude(state: GraphState):
        observed = state["observation"]
        # This deterministic rule is intentionally not an LLM or game-quality claim.
        verdict = "FAIL" if not observed["valid"] else ("INCONCLUSIVE" if observed["sample_count"] < 1 else "PASS")
        evidence = {"fixture_only": True, "schema": state["schema"], "observation": observed, "candidate_ref": state["payload"]["candidate_ref"]}
        raw = canonical(evidence).encode("utf-8")
        evidence_hash = digest(raw)
        evidence_path = root / "artifacts" / (evidence_hash + ".json")
        evidence_path.write_bytes(raw)
        ref = "evidence://" + evidence_hash
        readback = await mcp.call_tool("read_artifact", {"artifact_ref": ref, "artifact_sha256": evidence_hash})
        if readback.is_error or readback.structured_content != evidence:
            raise RuntimeError("evidence readback mismatch")
        return {"report": {
            "schema_version": 1, "verification_run_id": state["run_id"],
            "verification_request_id": state["payload"]["business_id"],
            "authenticated_owner": state["owner"], "verdict": verdict,
            "candidate_ref": state["payload"]["candidate_ref"],
            "candidate_sha256": state["payload"]["candidate_sha256"],
            "evidence_ref": ref, "evidence_sha256": evidence_hash,
            "fixture_only": True, "model_api_calls": 0,
        }}

    graph = StateGraph(GraphState)
    graph.add_node("investigate", investigate)
    graph.add_node("conclude", conclude)
    graph.add_edge(START, "investigate")
    graph.add_edge("investigate", "conclude")
    graph.add_edge("conclude", END)
    return graph.compile()


class VerificationExecutor(AgentExecutor):
    def __init__(self, graph, ledger: BusinessLedger):
        self.graph = graph
        self.ledger = ledger
        self.pending: dict[str, dict] = {}
        self.lifecycle: list[dict] = []

    async def execute(self, context: RequestContext, event_queue):
        task_id, context_id = context.task_id, context.context_id
        owner = context.call_context.user.user_name
        updater = TaskUpdater(event_queue, task_id, context_id)
        try:
            payload = next(MessageToDict(p.data) for p in context.message.parts if p.HasField("data"))
            if not context.current_task:
                await event_queue.enqueue_event(Task(id=task_id, context_id=context_id, status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED), history=[context.message]))
            else:
                # V2 send-stream does not synthesize the initial Task for us.
                # Emit its resumed snapshot before any updates, as A2A specifies.
                resumed = Task()
                resumed.CopyFrom(context.current_task)
                resumed.status.CopyFrom(TaskStatus(state=TaskState.TASK_STATE_WORKING))
                await event_queue.enqueue_event(resumed)
            if task_id in self.pending:
                prior = self.pending[task_id]
                for key in ("business_id", "candidate_ref", "candidate_sha256"):
                    if key in payload and payload[key] != prior[key]:
                        await updater.reject(updater.new_agent_message([Part(text="candidate cannot change during clarification")]))
                        return
                payload = {**prior, **payload}
            if not payload.get("goal"):
                self.pending[task_id] = payload
                await updater.requires_input(updater.new_agent_message([Part(text="Provide the fixture verification goal; candidate remains frozen.")]))
                return
            self.pending.pop(task_id, None)
            await updater.start_work()
            # Hold/delay are explicit probe scenarios, not arbitrary execution tools.
            if payload.get("probe_behavior") == "hold":
                self.lifecycle.append({"task_id": task_id, "event": "hold_started"})
                await asyncio.Event().wait()
            if payload.get("probe_behavior") == "delay":
                await asyncio.sleep(0.6)
            immutable = {key: payload[key] for key in ("business_id", "candidate_ref", "candidate_sha256", "goal")}
            claimed = self.ledger.claim(owner, payload["business_id"], digest(canonical(immutable).encode()))
            if claimed["state"] == "completed":
                report = claimed["report"]
            elif claimed["state"] == "running":
                await updater.reject(updater.new_agent_message([Part(text="business execution already pending; reconcile its receipt")]))
                return
            else:
                output = await self.graph.ainvoke({"payload": immutable, "owner": owner, "run_id": claimed["run_id"]})
                report = output["report"]
                self.ledger.complete(owner, payload["business_id"], report)
            await updater.add_artifact([Part(data=ParseDict(report, Value()), media_type="application/json")], name="verification-report", last_chunk=True)
            await updater.complete()
        except PayloadConflict as exc:
            await updater.reject(updater.new_agent_message([Part(text=str(exc))]))
        except asyncio.CancelledError:
            self.lifecycle.append({"task_id": task_id, "event": "execute_cancelled"})
            raise
        except Exception as exc:
            self.lifecycle.append({"task_id": task_id, "event": "execute_error", "error": repr(exc), "traceback": traceback.format_exc()})
            await updater.failed(updater.new_agent_message([Part(text=f"fixture error: {type(exc).__name__}")]))

    async def cancel(self, context: RequestContext, event_queue):
        self.lifecycle.append({"task_id": context.task_id, "event": "cancel_callback"})
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


class FixtureIdentityAndWire:
    """Local test identity gate; explicitly not an OAuth implementation."""
    def __init__(self, app, records: list):
        self.app, self.records = app, records

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        owner = {b"Bearer fixture-coding": "coding", b"Bearer fixture-config": "config"}.get(headers.get(b"authorization"))
        if scope["path"] == "/a2a/jsonrpc" and owner is None:
            return await JSONResponse({"error": "fixture identity required"}, status_code=401)(scope, receive, send)
        if owner:
            scope["user"] = SimpleUser(owner)
        record = {"owner": owner, "path": scope["path"], "method": scope["method"], "request_chunks": [], "response_chunks": []}
        self.records.append(record)

        async def received():
            value = await receive()
            if value["type"] == "http.request":
                record["request_chunks"].append(value.get("body", b"").decode("utf-8"))
            return value

        async def sent(value):
            if value["type"] == "http.response.start":
                record["status"] = value["status"]
            if value["type"] == "http.response.body":
                record["response_chunks"].append(value.get("body", b"").decode("utf-8"))
            await send(value)

        await self.app(scope, received, sent)


def message(payload: dict, task: Task | None = None, context_id: str | None = None):
    fields = {"role": Role.ROLE_USER, "message_id": str(uuid.uuid4()), "parts": [Part(data=ParseDict(payload, Value()), media_type="application/json")]}
    if task:
        fields.update(task_id=task.id, context_id=context_id or task.context_id)
    return SendMessageRequest(message=Message(**fields))


def report_of(task: Task) -> dict:
    if not task.artifacts:
        raise AssertionError(f"task {task.id} has no report artifact; state={TaskState.Name(task.status.state)}")
    return MessageToDict(task.artifacts[0].parts[0].data)


async def send_and_get(client, payload: dict, previous: Task | None = None):
    events = [event async for event in client.send_message(message(payload, previous))]
    # Continuation can emit only updates with this executor; its Task id is known.
    task_event = next((event.task for event in events if event.HasField("task")), previous)
    if task_event is None:
        raise AssertionError("new task stream supplied no Task identity")
    return await client.get_task(GetTaskRequest(id=task_event.id)), events


def tool_records(root: Path) -> list[dict]:
    path = root / "mcp-tool-calls.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


async def run_probe(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    if (root / "result.json").exists() or (root / "business.sqlite").exists():
        raise ValueError("refusing to overwrite prior probe evidence")
    for folder in ("candidates", "artifacts"):
        (root / folder).mkdir()
    for name, value in {"pass": {"attack_multiplier": 1, "sample_count": 2}, "fail": {"attack_multiplier": -1, "sample_count": 2}, "inconclusive": {"attack_multiplier": 1, "sample_count": 0}}.items():
        write_json(root / "candidates" / (name + ".json"), value)
    before = {p.name: digest(p.read_bytes()) for p in (root / "candidates").glob("*.json")}
    checks, wire, observed = {}, [], {}
    started = time.monotonic()
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "model_api_calls": 0, "fixture_only": True, "pass_scope": "functional boundary assertions only; SDK cleanup diagnostics are reported separately", "production_ready": False, "checks": checks, "observed": observed, "limitations": ["local fixture bearer identities, not production OAuth", "fixed LangGraph decisions, not LLM quality", "no game engine, external job cancellation, or OS sandbox proof", "SQLite reopen checks stored Task only, not interrupted workflow recovery", "no exactly-once guarantee from SDK; fixture business ledger handles duplicate completed requests", "first response completely lost before any Task id and in-flight server crash are not tested"]}

    def check(name, condition):
        checks[name] = bool(condition)
        if not condition:
            raise AssertionError(name)

    def payload(name, business_id, **extra):
        return {"business_id": business_id, "candidate_ref": "candidate://" + name, "candidate_sha256": before[name + ".json"], "goal": "fixture schema and evidence check", **extra}

    try:
        async with AsyncExitStack() as stack:
            stderr = stack.enter_context((root / "mcp-stderr.txt").open("w", encoding="utf-8"))
            # Standard SDK transport launches this file in a distinct process.
            params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve()), "--mcp-server", "--out", str(root)])
            from mcp.client.stdio import stdio_client
            mcp = await stack.enter_async_context(MCPClient(stdio_client(params, errlog=stderr), cache=None))
            observed["mcp_protocol_version"] = mcp.protocol_version
            observed["mcp_discovery"] = mcp.session.discover_result.model_dump(by_alias=True, mode="json")
            listed = await mcp.list_tools()
            check("mcp_exact_readonly_tools", sorted(t.name for t in listed.tools) == ["query_schema", "read_artifact", "validate"])
            invalid = await mcp.call_tool("candidate_write", {})
            check("mcp_unregistered_write_rejected", invalid.is_error)
            wrong = await mcp.call_tool("validate", {"candidate_ref": "candidate://pass", "candidate_sha256": "wrong"})
            check("mcp_hash_mismatch_rejected", wrong.is_error)

            engine = create_async_engine("sqlite+aiosqlite:///" + (root / "tasks.sqlite").as_posix())
            stack.push_async_callback(engine.dispose)
            task_store = DatabaseTaskStore(engine=engine)
            await task_store.initialize()
            ledger = BusinessLedger(root / "business.sqlite")
            executor = VerificationExecutor(fixture_graph(mcp, root), ledger)
            # Bind once and hand the live socket to uvicorn; no free-port race.
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sock.listen(128)
            sock.setblocking(False)
            stack.callback(sock.close)
            base = f"http://127.0.0.1:{sock.getsockname()[1]}"
            card = AgentCard(name="Verification", description="One fixture verification capability, immutable candidate references", version="fixture-1", supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", protocol_version="1.0", url=base + "/a2a/jsonrpc")], capabilities=AgentCapabilities(streaming=True, push_notifications=False), default_input_modes=["application/json"], default_output_modes=["application/json"], skills=[AgentSkill(id="verify_candidate", name="Verify immutable candidate", description="Return evidence and PASS, FAIL, or INCONCLUSIVE", tags=["verification"])])
            ParseDict({"securitySchemes": {"fixtureBearer": {"httpAuthSecurityScheme": {"scheme": "bearer", "bearerFormat": "local-fixture-only"}}}, "securityRequirements": [{"schemes": {"fixtureBearer": {"list": []}}}]}, card)
            handler = DefaultRequestHandler(agent_executor=executor, task_store=task_store, agent_card=card, validate_input_modes=True)

            @asynccontextmanager
            async def lifespan(app):
                yield
                await handler.aclose()

            app = FixtureIdentityAndWire(Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/a2a/jsonrpc"), lifespan=lifespan), wire)
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3))
            server_task = asyncio.create_task(server.serve(sockets=[sock]))

            async def close_server():
                server.should_exit = True
                await asyncio.wait_for(server_task, timeout=8)

            stack.push_async_callback(close_server)
            for _ in range(100):
                if server.started:
                    break
                if server_task.done():
                    await server_task
                await asyncio.sleep(0.02)
            check("http_server_started", server.started)

            clients, http_clients = {}, {}
            for owner in ("coding", "config"):
                http = await stack.enter_async_context(httpx.AsyncClient(headers={"Authorization": "Bearer fixture-" + owner}, timeout=10, trust_env=False))
                http_clients[owner] = http
                config = ClientConfig(streaming=True, httpx_client=http, supported_protocol_bindings=["JSONRPC"])
                clients[owner] = await create_client(base, client_config=config)
            cards = [(await http_clients[o].get(base + "/.well-known/agent-card.json")).json() for o in ("coding", "config")]
            check("one_card_two_clients", cards[0] == cards[1] and [s["id"] for s in cards[0]["skills"]] == ["verify_candidate"])
            write_json(root / "agent-card.json", cards[0])
            async with httpx.AsyncClient(trust_env=False) as anonymous:
                without_auth = await anonymous.post(base + "/a2a/jsonrpc", json={})
            check("anonymous_request_rejected", without_auth.status_code == 401)

            verdicts, tasks, event_records = [], [], []
            for name, owner in (("pass", "coding"), ("fail", "config"), ("inconclusive", "coding")):
                task, events = await send_and_get(clients[owner], payload(name, "request-" + name, author="config"))
                report = report_of(task)
                tasks.append(task)
                verdicts.append(report["verdict"])
                event_records.append([MessageToDict(e) for e in events])
                check("completed_" + name, task.status.state == TaskState.TASK_STATE_COMPLETED)
                check("stream_first_task_" + name, events[0].HasField("task"))
                check("trusted_owner_" + name, report["authenticated_owner"] == owner)
            result["verdicts"] = verdicts
            check("completed_does_not_mean_pass", verdicts == ["PASS", "FAIL", "INCONCLUSIVE"])

            async def rejected_call(label, callback, error_type):
                try:
                    await callback()
                except error_type as exc:
                    observed[label] = {"type": type(exc).__name__, "message": str(exc)}
                    return True
                return False

            result["cross_owner_get_rejected"] = await rejected_call("cross_owner_get", lambda: clients["config"].get_task(GetTaskRequest(id=tasks[0].id)), TaskNotFoundError)
            check("cross_owner_get_rejected", result["cross_owner_get_rejected"])
            check("cross_owner_cancel_rejected", await rejected_call("cross_owner_cancel", lambda: clients["config"].cancel_task(CancelTaskRequest(id=tasks[0].id)), TaskNotFoundError))
            visible = await clients["config"].list_tasks(ListTasksRequest())
            check("cross_owner_list_scoped", tasks[0].id not in [t.id for t in visible.tasks] and tasks[1].id in [t.id for t in visible.tasks])

            validation_count = lambda: sum(row["tool"] == "validate" for row in tool_records(root))
            v0, b0 = validation_count(), ledger.reservations()
            # A new wire/message identity replays the same business request.
            repeated, repeated_events = await send_and_get(clients["coding"], payload("pass", "request-pass", author="someone-else"))
            result["duplicate_validation_delta"] = validation_count() - v0
            result["duplicate_reservation_delta"] = ledger.reservations() - b0
            check("duplicate_reuses_business_receipt", report_of(repeated) == report_of(tasks[0]))
            check("duplicate_no_execution_or_budget", result["duplicate_validation_delta"] == result["duplicate_reservation_delta"] == 0)
            observed["duplicate_task_ids"] = [tasks[0].id, repeated.id]
            conflict, _ = await send_and_get(clients["coding"], payload("fail", "request-pass"))
            check("same_business_id_different_payload_rejected", conflict.status.state == TaskState.TASK_STATE_REJECTED and ledger.reservations() == b0)

            clarifying = payload("pass", "request-clarify")
            del clarifying["goal"]
            waiting, _ = await send_and_get(clients["coding"], clarifying)
            check("input_required", waiting.status.state == TaskState.TASK_STATE_INPUT_REQUIRED)

            async def wrong_context():
                return [e async for e in clients["coding"].send_message(message({"goal": "ok"}, waiting, "unrelated-context"))]

            check("context_mismatch_rejected", await rejected_call("wrong_context", wrong_context, InvalidParamsError))

            async def cross_owner_continue():
                return [e async for e in clients["config"].send_message(message({"goal": "ok", "author": "coding"}, waiting))]

            check("cross_owner_continuation_rejected", await rejected_call("cross_owner_continue", cross_owner_continue, TaskNotFoundError))
            continued, continuation_events = await send_and_get(clients["coding"], {"goal": "fixture schema and evidence check"}, waiting)
            observed["continuation_event_kinds"] = [e.WhichOneof("payload") for e in continuation_events]
            check("continuation_first_task", continuation_events[0].HasField("task"))
            check("input_continues_same_task", continued.id == waiting.id and continued.status.state == TaskState.TASK_STATE_COMPLETED)

            async def terminal_continue():
                return [e async for e in clients["coding"].send_message(message({"goal": "again"}, continued))]

            def queue_dispatchers():
                return sorted(str(t.get_coro()) for t in asyncio.all_tasks() if "EventQueueSource._dispatch_loop" in str(t.get_coro()))

            observed["dispatchers_before_terminal_replay"] = queue_dispatchers()
            check("terminal_task_cannot_restart", await rejected_call("terminal_continue", terminal_continue, UnsupportedOperationError))
            await asyncio.sleep(0.01)
            observed["dispatchers_after_terminal_replay"] = queue_dispatchers()

            # Disconnect the first stream after obtaining a Task, then re-subscribe.
            interrupted_stream = clients["coding"].send_message(message(payload("pass", "request-stream", probe_behavior="delay")))
            first = await anext(interrupted_stream)
            check("disconnect_first_task", first.HasField("task"))
            await interrupted_stream.aclose()
            recovered_events = [e async for e in clients["coding"].subscribe(SubscribeToTaskRequest(id=first.task.id))]
            check("resubscribe_first_snapshot", recovered_events[0].HasField("task"))
            recovered = await clients["coding"].get_task(GetTaskRequest(id=first.task.id))
            check("disconnect_task_completed", recovered.status.state == TaskState.TASK_STATE_COMPLETED and report_of(recovered)["verdict"] == "PASS")

            polling = await create_client(base, client_config=ClientConfig(streaming=False, polling=True, httpx_client=http_clients["coding"]))
            held, _ = await send_and_get(polling, payload("pass", "request-cancel", probe_behavior="hold"))
            for _ in range(100):
                if any(e["task_id"] == held.id and e["event"] == "hold_started" for e in executor.lifecycle):
                    break
                await asyncio.sleep(0.01)
            cancelled = await clients["coding"].cancel_task(CancelTaskRequest(id=held.id))
            check("cancel_protocol_state", cancelled.status.state == TaskState.TASK_STATE_CANCELED)
            check("cancel_executor_observed", any(e["task_id"] == held.id and e["event"] == "execute_cancelled" for e in executor.lifecycle))
            check("completed_cannot_cancel", await rejected_call("completed_cancel", lambda: clients["coding"].cancel_task(CancelTaskRequest(id=tasks[0].id)), TaskNotCancelableError))

            reopened_engine = create_async_engine("sqlite+aiosqlite:///" + (root / "tasks.sqlite").as_posix())
            stack.push_async_callback(reopened_engine.dispose)
            reopened = DatabaseTaskStore(engine=reopened_engine)
            restored = await reopened.get(tasks[0].id, ServerCallContext(user=StarletteUser(SimpleUser("coding"))))
            result["sqlite_reopened_task"] = restored is not None and report_of(restored) == report_of(tasks[0])
            check("sqlite_reopened_task", result["sqlite_reopened_task"])
            result["candidate_mutations"] = [p.name for p in (root / "candidates").glob("*.json") if digest(p.read_bytes()) != before[p.name]]
            check("immutable_candidates", not result["candidate_mutations"])
            observed["fixture_budget_units_reserved"] = ledger.reservations()
            write_json(root / "stream-events.json", {"initial_runs": event_records, "resubscribe": [MessageToDict(e) for e in recovered_events]})
            write_json(root / "executor-events.json", executor.lifecycle)
            check("a2a_wire_standard_methods", {json.loads("".join(r["request_chunks"])).get("method") for r in wire if r["path"] == "/a2a/jsonrpc" and r["request_chunks"]} >= {"SendMessage", "SendStreamingMessage", "GetTask", "SubscribeToTask", "CancelTask"})
            write_json(root / "candidate-hashes.json", before)
        result["passed"] = True
    except BaseException as exc:
        result["passed"] = False
        result["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
    finally:
        if "executor" in locals():
            write_json(root / "executor-events.json", executor.lifecycle)
        result["wall_seconds"] = time.monotonic() - started
        result["versions"] = {name: importlib.metadata.version(name) for name in ("a2a-sdk", "mcp", "langgraph", "langgraph-checkpoint", "langgraph-checkpoint-sqlite", "pydantic", "uvicorn", "starlette")}
        result["python"] = sys.version
        result["probe_sha256"] = digest(Path(__file__).read_bytes())
        write_json(root / "http-wire.json", wire)
        write_json(root / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--mcp-server", action="store_true")
    args = parser.parse_args()
    if args.mcp_server:
        serve_mcp(args.out.resolve())
        return
    root = args.out or Path(tempfile.mkdtemp(prefix="a2a-mcp-20261005-", dir=Path(__file__).resolve().parents[1] / "evidence"))
    root.mkdir(parents=True, exist_ok=True)
    diagnostics = logging.FileHandler(root / "sdk-diagnostics.log", encoding="utf-8")
    logging.getLogger().addHandler(diagnostics)
    try:
        result = asyncio.run(run_probe(root.resolve()))
    finally:
        logging.getLogger().removeHandler(diagnostics)
        diagnostics.close()
    print(canonical({"passed": result["passed"], "out": str(root.resolve()), "checks": result["checks"], "error": result.get("error")}))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
