"""G0 protocol audit. Official SDK source + installed CLI + local Responses fixture.

Does not read user Codex authentication. All runtime state is isolated in evidence.
Offline only. This is a diagnostic, not a production adapter or model-quality test.
"""
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(r"D:\Desktop\codex-main")
sys.path.insert(0, str(SOURCE / "sdk/python/src"))
from openai_codex.client import CodexClient, CodexConfig
from pydantic import BaseModel, ConfigDict

class RPCResult(BaseModel):
    model_config = ConfigDict(extra="allow")

class RecordingClient(CodexClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observed = queue.Queue()

    def _coerce_notification(self, method, params):
        value = super()._coerce_notification(method, params)
        self.observed.put(value)
        return value

OUT = ROOT / "research/evidence" / ("runtime-deepseek-" + time.strftime("%Y%m%d-%H%M%S"))
OUT.mkdir(parents=True)
BIN = shutil.which("codex")
SAFE_ENV = {k: v for k, v in os.environ.items() if k.upper() in {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP",
    "USERPROFILE", "COMSPEC", "PROCESSOR_ARCHITECTURE"}}
# The SDK merges env into os.environ, so scrub this dedicated probe process first.
os.environ.clear()
os.environ.update(SAFE_ENV)
REQUESTS = []
CALLS = []
EVENTS = []
SCENARIO = ""

def catalog(multi="disabled"):
    return {"models": [{
        "slug": "deepseek-flash", "display_name": "DeepSeek fixture catalog",
        "description": "Protocol fixture; metadata subset, not a quality claim",
        "default_reasoning_level": "low", "supported_reasoning_levels": [
            {"effort": "low", "description": "low"}, {"effort": "high", "description": "high"}],
        "shell_type": "shell_command", "visibility": "list", "supported_in_api": True,
        "priority": 1, "availability_nux": None, "upgrade": None,
        "support_verbosity": False, "default_verbosity": None,
        "apply_patch_tool_type": "freeform", "web_search_tool_type": "text",
        "truncation_policy": {"mode": "tokens", "limit": 10000},
        "context_window": 1048576, "experimental_supported_tools": [],
        "input_modalities": ["text"], "tool_mode": "direct",
        "multi_agent_version": multi, "auto_review_model_override": "deepseek-flash",
        "model_messages": {"instructions_template": "You are a protocol test assistant."},
        "supports_reasoning_summary_parameter": False,
    }]}

class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        row = {"scenario": SCENARIO, "path": self.path, "body": body}
        REQUESTS.append(row)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        idx = len(REQUESTS)
        rid = f"resp_fixture_{idx}"
        def emit(e):
            self.wfile.write(("event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n").encode())
            self.wfile.flush()
        emit({"type": "response.created", "response": {"id": rid}})
        own = [x for x in REQUESTS if x["scenario"] == SCENARIO]
        if SCENARIO == "dynamic_tool_roundtrip" and len(own) == 1:
            item = {"type": "function_call", "name": "read_fixture", "arguments": "{}",
                    "call_id": "call_fixture", "id": "fc_fixture"}
        elif SCENARIO.startswith("subagent_") and len(own) == 1:
            item = {"type": "function_call", "name": "spawn_agent",
                    "arguments": json.dumps({"message": "CHILD_FIXTURE: answer OK only", "task_name": "fixture_child", "fork_turns": "none"}),
                    "call_id": "call_child", "id": "fc_child"}
            if SCENARIO == "subagent_v2":
                item["namespace"] = "collaboration"
            else:
                item["namespace"] = "multi_agent_v1"
                item["arguments"] = json.dumps({"message": "CHILD_FIXTURE: answer OK only", "fork_context": False})
        else:
            msg = '{"findings":[],"overall_correctness":"patch is correct","overall_explanation":"fixture only","overall_confidence_score":1.0}' if "review" in SCENARIO else "LOCAL_FIXTURE_OK"
            item = {"type": "message", "role": "assistant", "id": f"msg_{idx}",
                    "content": [{"type": "output_text", "text": msg}]}
        emit({"type": "response.output_item.added", "output_index": 0, "item": item})
        emit({"type": "response.output_item.done", "output_index": 0, "item": item})
        emit({"type": "response.completed", "response": {"id": rid, "output": [item],
              "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13,
                        "input_tokens_details": {"cached_tokens": 0}}}})

def handler(method, params):
    CALLS.append({"scenario": SCENARIO, "method": method, "params": params})
    if method == "item/tool/call" and params.get("tool") == "read_fixture" and params.get("arguments") == {}:
        return {"success": True, "contentItems": [{"type": "inputText", "text": "FIXTURE_VALUE_72419"}]}
    return {"decision": "decline"}

def run_scenario(name, use_catalog, multi="disabled", shell=True):
    global SCENARIO
    SCENARIO = name
    data = OUT / name / "runtime"
    work = OUT / name / "workspace"
    data.mkdir(parents=True)
    work.mkdir()
    lines = [
        'model = "deepseek-flash"', 'model_provider = "deepseek_fixture"',
        'review_model = "deepseek-flash"', 'approval_policy = "never"',
        'approvals_reviewer = "user"', 'sandbox_mode = "read-only"', 'web_search = "disabled"',
        'model_reasoning_effort = "low"', 'model_reasoning_summary = "none"',
    ]
    if use_catalog:
        models = data / "models.json"
        models.write_text(json.dumps(catalog(multi)), encoding="utf-8")
        lines.append('model_catalog_json = ' + json.dumps(str(models)))
    lines += ['[analytics]', 'enabled = false', '[features]',
              f'shell_tool = {str(shell).lower()}', 'apps = false', 'plugins = false',
              'memories = false', 'code_mode = false',
              f'multi_agent = {str(multi == "v1").lower()}',
              f'multi_agent_v2 = {str(multi == "v2").lower()}',
              '[model_providers.deepseek_fixture]', 'name = "DeepSeek protocol fixture"',
              f'base_url = "http://127.0.0.1:{PORT}"', 'wire_api = "responses"',
              'requires_openai_auth = false', 'supports_websockets = false',
              'request_max_retries = 0', 'stream_max_retries = 0']
    if name == "mcp_direct":
        lines += ['[mcp_servers.immutable_fixture]', 'command = ' + json.dumps(sys.executable),
                  'args = [' + json.dumps(str(Path(__file__).with_name("runtime_deepseek_mcp_fixture.py"))) + ']',
                  'startup_timeout_sec = 10', 'tool_timeout_sec = 10']
    (data / "config.toml").write_text("\n".join(lines), encoding="utf-8")
    result = {"name": name, "catalog": use_catalog, "multi": multi}
    client = RecordingClient(CodexConfig(codex_bin=BIN, cwd=str(work), env={
        "CODEX_HOME": str(data), "NO_PROXY": "127.0.0.1,localhost"}), approval_handler=handler)
    try:
        client.start()
        result["initialize"] = client.initialize().model_dump(mode="json")
        params = {"cwd": str(work), "model": "deepseek-flash", "modelProvider": "deepseek_fixture",
                  "approvalPolicy": "never", "approvalsReviewer": "user", "sandbox": "read-only"}
        if name == "dynamic_tool_roundtrip":
            params["dynamicTools"] = [{"name": "read_fixture", "description": "Read immutable test fixture",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]
        started = client.thread_start(params)
        tid = started.thread.id
        result["thread_provider"] = started.model_provider
        if "review" in name:
            response = client.request("review/start", {"threadId": tid, "target": {
                "type": "custom", "instructions": "Review fixture only; return no findings; do not execute tools."},
                "delivery": "inline"}, response_model=RPCResult).model_dump()
            turnid = response["turn"]["id"]
        else:
            response = client.turn_start(tid, "Protocol fixture only. No tools except prescribed fixture call.")
            turnid = response.turn.id
        # Diagnostic observer taps notification decoding before SDK routing.
        # review/start has no generated high-level streaming wrapper in this snapshot.
        received = client.observed
        until = time.monotonic() + 30
        while time.monotonic() < until:
            n = received.get(timeout=max(.1, until-time.monotonic()))
            if isinstance(n, BaseException):
                raise n
            payload = n.payload.model_dump(mode="json", by_alias=True)
            EVENTS.append({"scenario": name, "method": n.method, "params": payload})
            if n.method == "turn/completed" and payload["turn"]["id"] == turnid:
                result["turn_status"] = payload["turn"]["status"]
                break
        if name.startswith("subagent_"):
            time.sleep(1)
        own = [x for x in REQUESTS if x["scenario"] == name]
        result["request_count"] = len(own)
        result["pass"] = result.get("turn_status") == "completed" and (not name.startswith("subagent_") or len(own) >= 3)
    except BaseException as e:
        result["pass"] = False
        result["error"] = repr(e)
    finally:
        result["stderr"] = client._stderr_tail(15)
        client.close()
    return result

if __name__ == "__main__":
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    PORT = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    results = []
    try:
        scenarios = [("default_metadata", False), ("explicit_catalog", True),
                     ("dynamic_tool_roundtrip", True, "disabled", False),
                     ("inline_review", True), ("subagent_v1", True, "v1"),
                     ("subagent_v2", True, "v2"), ("mcp_direct", True)]
        if len(sys.argv) == 2:
            scenarios = [x for x in scenarios if x[0] == sys.argv[1]]
        for args in scenarios:
            result = run_scenario(*args)
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        httpd.shutdown()
        (OUT / "requests.json").write_text(json.dumps(REQUESTS, indent=2), encoding="utf-8")
        (OUT / "events.json").write_text(json.dumps(EVENTS, indent=2), encoding="utf-8")
        (OUT / "calls.json").write_text(json.dumps(CALLS, indent=2), encoding="utf-8")
        summary = {"binary": BIN, "binary_sha256": hashlib.sha256(Path(BIN).read_bytes()).hexdigest(),
                   "version": subprocess.check_output([BIN, "--version"], text=True).strip(),
                   "python": sys.version, "sdk_source": str(SOURCE / "sdk/python"),
                   "scope": "real CLI and official SDK source; localhost fixture only; no credential/model use",
                   "scenarios": results,
                   "request_summary": [{"scenario": r["scenario"], "path": r["path"], "model": r["body"].get("model"),
                       "tool_types": [{"type": t.get("type"), "name": t.get("name"), "tools": [x.get("name") for x in t.get("tools", [])]} for t in r["body"].get("tools", [])],
                       "input_types": [x.get("type") for x in r["body"].get("input", [])],
                       "top_level_keys": sorted(r["body"])} for r in REQUESTS]}
        (OUT / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("EVIDENCE=" + str(OUT))
