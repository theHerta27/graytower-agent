"""Offline proof: real Codex + SDK dynamicTools -> official MCP client -> same MCP fixture.

Only diagnostic glue; Runtime still owns the model/tool continuation loop.
No credentials, remote provider, Rust changes, or protocol gateway.
"""
import asyncio
import concurrent.futures
import hashlib
import importlib.metadata
import inspect
import json
from pathlib import Path
import queue
import site
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.dont_write_bytecode = True
DEPS = Path(__file__).resolve().parents[1] / "evidence/runtime-deepseek-mcp-client-deps"
site.addsitedir(str(DEPS))
import runtime_deepseek_probe as probe
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

OUT = probe.OUT
WIRE = OUT / "mcp-wire.jsonl"
DATA = OUT / "runtime"
WORK = OUT / "workspace"
DATA.mkdir()
WORK.mkdir()
MAPPING = {"game_read_fixture": "read_fixture"}
ADAPTER_CALLS = []
MODEL_REQUESTS = []
MODEL_INPUTS = []
MCP_TASKS = queue.Queue()
MCP_READY = threading.Event()
MCP_INFO = {}

async def mcp_owner():
    params = StdioServerParameters(command=sys.executable, args=[
        str(Path(__file__).with_name("runtime_deepseek_mcp_fixture.py")),
        "--audit", str(WIRE), "--fail-second-call"], env=probe.SAFE_ENV)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            MCP_INFO.update({"protocol": initialized.protocolVersion,
                             "server": initialized.serverInfo.model_dump(),
                             "tools": [t.model_dump(mode="json", by_alias=True) for t in tools.tools]})
            assert [t.name for t in tools.tools] == ["read_fixture"]
            MCP_READY.set()
            while True:
                item = await asyncio.to_thread(MCP_TASKS.get)
                if item is None:
                    return
                row, future = item
                try:
                    kwargs = {"arguments": {}}
                    if "meta" in inspect.signature(session.call_tool).parameters:
                        kwargs["meta"] = {"runtime_call_id": row["runtime_call_id"]}
                    response = await asyncio.wait_for(session.call_tool(row["mcp_tool"], **kwargs), timeout=3)
                    row["mcp_is_error"] = bool(response.isError)
                    row["mcp_content_types"] = [part.type for part in response.content]
                    assert all(part.type == "text" for part in response.content), "unsupported content must fail closed"
                    future.set_result({"success": not response.isError,
                        "contentItems": [{"type": "inputText", "text": p.text} for p in response.content]})
                except Exception as exc:
                    row["error_class"] = type(exc).__name__
                    future.set_result({"success": False, "contentItems": [{"type": "inputText", "text": "MCP_ADAPTER_FAILURE"}]})

def run_mcp():
    try:
        asyncio.run(mcp_owner())
    except BaseException as exc:
        MCP_INFO["error"] = repr(exc)
        MCP_READY.set()

def handler(method, params):
    row = {"method": method, "runtime_call_id": params.get("callId"),
           "thread_id": params.get("threadId"), "turn_id": params.get("turnId"),
           "dynamic_tool": params.get("tool"), "arguments": params.get("arguments")}
    ADAPTER_CALLS.append(row)
    if method != "item/tool/call" or params.get("tool") not in MAPPING or params.get("namespace") is not None:
        row["denied"] = "tool_not_allowlisted"
        return {"success": False, "contentItems": [{"type": "inputText", "text": "TOOL_NOT_ALLOWLISTED"}]}
    if params.get("arguments") != {}:
        row["denied"] = "invalid_arguments"
        return {"success": False, "contentItems": [{"type": "inputText", "text": "INVALID_ARGUMENTS"}]}
    row["mcp_tool"] = MAPPING[params["tool"]]
    row["mcp_server"] = "immutable-fixture"
    future = concurrent.futures.Future()
    MCP_TASKS.put((row, future))
    return future.result(timeout=5)

class ModelFixture(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        MODEL_REQUESTS.append({"path": self.path, "model": body["model"],
            "tools": [{"type": t.get("type"), "name": t.get("name")} for t in body.get("tools", [])],
            "input_types": [x.get("type") for x in body.get("input", [])]})
        MODEL_INPUTS.append(body["input"])
        n = len(MODEL_REQUESTS)
        calls = {
            1: ("game_read_fixture", {}, "runtime_success"),
            2: ("game_write_fixture", {}, "runtime_forbidden"),
            3: ("game_read_fixture", {"unexpected": True}, "runtime_bad_args"),
            4: ("game_read_fixture", {}, "runtime_mcp_error"),
        }
        if n in calls:
            name, args, callid = calls[n]
            item = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                    "call_id": callid, "id": "fc_" + str(n)}
        else:
            item = {"type": "message", "role": "assistant", "id": "msg_done",
                    "content": [{"type": "output_text", "text": "DYNAMIC_MCP_PROBE_DONE"}]}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in [
            {"type": "response.created", "response": {"id": "resp_" + str(n)}},
            {"type": "response.output_item.added", "output_index": 0, "item": item},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": "resp_" + str(n),
                "output": [item], "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}}},
        ]:
            self.wfile.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())
            self.wfile.flush()

thread = threading.Thread(target=run_mcp, daemon=True)
thread.start()
assert MCP_READY.wait(15), "MCP initialization timeout"
assert "error" not in MCP_INFO, MCP_INFO
server = ThreadingHTTPServer(("127.0.0.1", 0), ModelFixture)
threading.Thread(target=server.serve_forever, daemon=True).start()
models = probe.catalog()
models["models"][0]["apply_patch_tool_type"] = None
(DATA / "models.json").write_text(json.dumps(models), encoding="utf-8")
(DATA / "config.toml").write_text("\n".join([
    'model="deepseek-flash"', 'model_provider="local_probe"', 'approval_policy="never"',
    'approvals_reviewer="user"', 'sandbox_mode="read-only"', 'web_search="disabled"',
    'model_catalog_json=' + json.dumps(str(DATA / "models.json")),
    '[analytics]', 'enabled=false', '[features]', 'shell_tool=false', 'apps=false', 'plugins=false',
    'memories=false', 'goals=false', 'code_mode=false', 'multi_agent=false', 'multi_agent_v2=false',
    '[model_providers.local_probe]', 'name="Local Responses fixture"',
    f'base_url="http://127.0.0.1:{server.server_address[1]}"', 'wire_api="responses"',
    'requires_openai_auth=false', 'supports_websockets=false', 'request_max_retries=0', 'stream_max_retries=0',
]), encoding="utf-8")
client = probe.RecordingClient(probe.CodexConfig(codex_bin=probe.BIN, cwd=str(WORK),
    env={"CODEX_HOME": str(DATA), "NO_PROXY": "127.0.0.1,localhost"}), approval_handler=handler)
result = {"scope": "Real CLI + official Codex SDK source + official MCP Python SDK; local model and MCP fixture only",
          "mcp_version": importlib.metadata.version("mcp"), "mapping": MAPPING,
          "limitations": ["Synchronous SDK reader blocks while handler waits; not a production async adapter",
                          "3-second MCP timeout does not prove external worker stopped or write rolled back",
                          "No cancellation, disconnect, duplicate call, process tree, receipts or persistence proof",
                          "No real DeepSeek call, no generic Responses translation, no native Runtime MCP path"]}
try:
    client.start()
    result["initialize"] = client.initialize().model_dump(mode="json")
    listed = MCP_INFO["tools"][0]
    started = client.thread_start({"cwd": str(WORK), "model": "deepseek-flash", "modelProvider": "local_probe",
        "sandbox": "read-only", "approvalPolicy": "never", "dynamicTools": [{
            "name": "game_read_fixture", "description": listed["description"], "inputSchema": listed["inputSchema"]}]})
    turn = client.turn_start(started.thread.id, "Run the local protocol fixture. Do not perform any external actions.")
    end = time.monotonic() + 30
    while time.monotonic() < end:
        event = client.observed.get(timeout=max(.1, end-time.monotonic()))
        payload = event.payload.model_dump(mode="json", by_alias=True)
        if event.method == "turn/completed" and payload["turn"]["id"] == turn.turn.id:
            result["turn_status"] = payload["turn"]["status"]
            break
finally:
    client.close()
    server.shutdown()
    MCP_TASKS.put(None)
    thread.join(8)
    result["mcp_owner_closed"] = not thread.is_alive()
    result["mcp_info"] = MCP_INFO
    result["adapter_calls"] = ADAPTER_CALLS
    result["model_requests"] = MODEL_REQUESTS
    wire = [json.loads(line) for line in WIRE.read_text().splitlines()]
    calls = [x for x in wire if x.get("method") == "tools/call"]
    dispatched = [x for x in ADAPTER_CALLS if "mcp_tool" in x]
    result["call_id_mapping"] = [{"runtime_call_id": a["runtime_call_id"], "dynamic_tool": a["dynamic_tool"],
        "mcp_jsonrpc_id": b["id"], "mcp_tool": b["params"]["name"], "mcp_meta": b["params"].get("_meta"),
        "is_error": a["mcp_is_error"]} for a, b in zip(dispatched, calls)]
    outputs = {x["call_id"]: x["output"] for x in MODEL_INPUTS[-1] if x.get("type") == "function_call_output"}
    result["runtime_function_outputs"] = outputs
    result["checks"] = {
        "one_flat_dynamic_function": any(x == {"type": "function", "name": "game_read_fixture"} for x in MODEL_REQUESTS[0]["tools"]),
        "no_namespace_on_wire": all(t["type"] != "namespace" for r in MODEL_REQUESTS for t in r["tools"]),
        "success_roundtrip": "IMMUTABLE_MCP_FIXTURE" in json.dumps(outputs.get("runtime_success")),
        "unregistered_tool_never_reached_adapter": not any(a["dynamic_tool"] == "game_write_fixture" for a in ADAPTER_CALLS),
        "invalid_args_denied": "INVALID_ARGUMENTS" in json.dumps(outputs.get("runtime_bad_args")),
        "mcp_error_preserved": "CONTROLLED_MCP_ERROR" in json.dumps(outputs.get("runtime_mcp_error")),
        "only_two_mcp_calls": len(calls) == 2,
        "runtime_owns_five_model_steps": len(MODEL_REQUESTS) == 5,
        "turn_completed": result.get("turn_status") == "completed",
    }
    result["pass"] = all(result["checks"].values())
    result["server_sha256"] = hashlib.sha256(Path(__file__).with_name("runtime_deepseek_mcp_fixture.py").read_bytes()).hexdigest()
    (OUT / "dynamic-mcp-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "dependency-lock.txt").write_text("\n".join(sorted(f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions(path=[str(DEPS)]))), encoding="utf-8")
    print(json.dumps({"evidence": str(OUT), **result}, ensure_ascii=False, indent=2))
