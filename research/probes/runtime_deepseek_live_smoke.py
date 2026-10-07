"""Authorized, bounded real DeepSeek Responses smoke via installed Codex + SDK.

Local audit relay caps each request at 2000 output tokens, at most 3 requests.
Only one immutable dynamic function may be requested/executed. It buffers and
validates the SSE tool calls before passing them to Codex. No protocol conversion.
No user Codex authentication is read, and the DeepSeek key stays in memory only.
"""
import http.client
import json
from pathlib import Path
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import runtime_deepseek_probe as probe

OUT = probe.OUT
DATA = OUT / "live-isolated-runtime"
WORK = OUT / "live-immutable-workspace"
DATA.mkdir()
WORK.mkdir()
LEDGER = OUT / "live-budget.json"
CALL_LIMIT = 3
PER_REQUEST_CAP = 2000
STATE = {"calls_reserved": 0, "max_output_tokens_reserved": 0, "requests": [], "tool_calls": [], "phase": "coding"}
LOCK = threading.Lock()
KEY = None
for line in Path(r"D:\Desktop\combat-foundation\.env").read_text(encoding="utf-8").splitlines():
    if "=" not in line or line.lstrip().startswith("#"):
        continue
    k, v = line.split("=", 1)
    if k.strip() == "COMBAT_API_KEY":
        KEY = v.strip().strip('"').strip("'")
assert KEY and not KEY.startswith("your-"), "DeepSeek key absent or placeholder"

def save():
    LEDGER.write_text(json.dumps(STATE, indent=2), encoding="utf-8")

class Relay(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def fail(self, status, message):
        data = json.dumps({"error": {"message": message, "type": "probe_guard"}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/responses":
            return self.fail(400, "Only Responses endpoint allowed")
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body.get("model") != "deepseek-flash":
            return self.fail(400, "Unexpected model blocked")
        allowed = [t for t in body.get("tools", []) if t.get("type") == "function" and t.get("name") == "read_fixture"]
        phase = STATE["phase"]
        if phase == "coding" and len(allowed) != 1:
            return self.fail(400, "Required immutable tool missing")
        row = {"phase": phase, "endpoint": "https://api.deepseek.com/responses", "model": body["model"],
               "native_tool_surface": [{"type": t.get("type"), "name": t.get("name")} for t in body.get("tools", [])],
               "forwarded_tools": ["read_fixture"] if phase == "coding" else [],
               "input_types": [x.get("type") for x in body.get("input", [])],
               "max_output_tokens": PER_REQUEST_CAP,
               "mutations": ["cap max_output_tokens", "restrict tools to immutable read_fixture (none for review)"]}
        body["tools"] = allowed if phase == "coding" else []
        body["max_output_tokens"] = PER_REQUEST_CAP
        with LOCK:
            if STATE["calls_reserved"] >= CALL_LIMIT:
                return self.fail(429, "Probe budget exhausted; no further model calls")
            STATE["calls_reserved"] += 1
            STATE["max_output_tokens_reserved"] += PER_REQUEST_CAP
            STATE["requests"].append(row)
            save()
        start = time.monotonic()
        conn = None
        try:
            # Fixed host and path; no proxy, redirects, user auth, or tool network access.
            conn = http.client.HTTPSConnection("api.deepseek.com", timeout=80)
            conn.request("POST", "/responses", body=json.dumps(body).encode(), headers={
                "Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
            response = conn.getresponse()
            row["http_status"] = response.status
            payload = response.read()
            row["duration_seconds"] = round(time.monotonic()-start, 3)
            if response.status != 200:
                save()
                return self.fail(502, "Upstream DeepSeek error status " + str(response.status))
            events = []
            for line in payload.decode("utf-8").splitlines():
                if line.startswith("data:"):
                    event = json.loads(line[5:].strip())
                    events.append(event)
            row["event_types"] = sorted({e.get("type", "") for e in events})
            completed_items = [e["item"] for e in events if e.get("type") == "response.output_item.done"]
            for item in completed_items:
                if item.get("type") in {"function_call", "custom_tool_call"}:
                    if phase != "coding" or item.get("type") != "function_call" or item.get("name") != "read_fixture" or json.loads(item.get("arguments", "null")) != {}:
                        row["blocked_unexpected_tool"] = True
                        save()
                        return self.fail(400, "Unexpected generated tool call blocked")
            terminal = [e for e in events if e.get("type") in {"response.completed", "response.incomplete", "response.failed"}]
            if not terminal:
                raise ValueError("No Responses terminal event")
            final = terminal[-1]["response"]
            row["terminal_event"] = terminal[-1]["type"]
            row["usage"] = final.get("usage")
            row["output_types"] = [x.get("type") for x in final.get("output", [])]
            row["final_text"] = "\n".join(c.get("text", "") for x in final.get("output", []) if x.get("type") == "message" for c in x.get("content", []) if c.get("type") == "output_text")
            save()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            # Avoid full exception text: never risk including request headers or credentials.
            row["error_class"] = type(exc).__name__
            row["duration_seconds"] = round(time.monotonic()-start, 3)
            save()
            self.fail(502, "Bounded DeepSeek smoke transport failed: " + type(exc).__name__)
        finally:
            if conn:
                conn.close()

def handle(method, params):
    if method == "item/tool/call" and params.get("tool") == "read_fixture" and params.get("arguments") == {}:
        STATE["tool_calls"].append({"tool": "read_fixture", "call_id": params["callId"], "value": "FIXTURE_VALUE_72419"})
        save()
        return {"success": True, "contentItems": [{"type": "inputText", "text": "FIXTURE_VALUE_72419"}]}
    return {"decision": "decline"}

def wait_turn(client, turnid):
    until = time.monotonic() + 220
    while time.monotonic() < until:
        event = client.observed.get(timeout=max(.1, until-time.monotonic()))
        payload = event.payload.model_dump(mode="json", by_alias=True)
        if event.method == "turn/completed" and payload["turn"]["id"] == turnid:
            return payload["turn"]["status"]
    raise TimeoutError("turn timed out")

server = ThreadingHTTPServer(("127.0.0.1", 0), Relay)
threading.Thread(target=server.serve_forever, daemon=True).start()
model_catalog = probe.catalog()
model_catalog["models"][0]["apply_patch_tool_type"] = None
model_catalog["models"][0]["model_messages"]["instructions_template"] = "You are a test assistant. Complete only the user's bounded protocol check."
(DATA / "models.json").write_text(json.dumps(model_catalog), encoding="utf-8")
(DATA / "config.toml").write_text('\n'.join([
    'model="deepseek-flash"', 'review_model="deepseek-flash"', 'model_provider="deepseek_bounded_probe"',
    'model_catalog_json=' + json.dumps(str(DATA / "models.json")), 'approval_policy="never"',
    'approvals_reviewer="user"', 'sandbox_mode="read-only"', 'web_search="disabled"',
    'model_reasoning_effort="low"', 'model_reasoning_summary="none"',
    '[analytics]', 'enabled=false', '[features]', 'shell_tool=false', 'apps=false', 'plugins=false',
    'memories=false', 'code_mode=false', 'multi_agent=false', 'multi_agent_v2=false', 'goals=false',
    '[model_providers.deepseek_bounded_probe]', 'name="Bounded DeepSeek audit relay"',
    f'base_url="http://127.0.0.1:{server.server_address[1]}"', 'wire_api="responses"',
    'requires_openai_auth=false', 'supports_websockets=false', 'request_max_retries=0', 'stream_max_retries=0',
]), encoding="utf-8")
client = probe.RecordingClient(probe.CodexConfig(codex_bin=probe.BIN, cwd=str(WORK), env={
    "CODEX_HOME": str(DATA), "NO_PROXY": "127.0.0.1,localhost"}), approval_handler=handle)
RESULT = {"scope": "Real DeepSeek Responses; SDK source + installed CLI; read-only synthetic tool; capped audit relay",
          "limitations": ["Relay filters tools and adds output cap; not an unmodified production request", "No arbitrary shell, code writes, MCP or native subagent verification", "SSE validated in relay before forwarding; not a live-stream latency test"],
          "endpoint": "https://api.deepseek.com/responses", "model": "deepseek-flash"}
try:
    client.start()
    RESULT["initialize"] = client.initialize().model_dump(mode="json")
    thread = client.thread_start({"cwd": str(WORK), "model": "deepseek-flash", "modelProvider": "deepseek_bounded_probe",
        "approvalPolicy": "never", "sandbox": "read-only", "dynamicTools": [{"name": "read_fixture",
        "description": "Reads a single immutable test value. No parameters. No writes or external actions.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]})
    turn = client.turn_start(thread.thread.id, "Call read_fixture exactly once with {}. After reading the returned value, reply with only that exact value. No other tools or actions.")
    RESULT["coding_turn"] = wait_turn(client, turn.turn.id)
    RESULT["tool_roundtrip"] = len(STATE["tool_calls"]) == 1 and any("FIXTURE_VALUE_72419" in r.get("final_text", "") for r in STATE["requests"])
    if RESULT["tool_roundtrip"] and STATE["calls_reserved"] == 2:
        STATE["phase"] = "review"
        response = client.request("review/start", {"threadId": thread.thread.id,
            "target": {"type": "custom", "instructions": "Review this self-contained pure function: def add(a, b): return a + b. Its only requirement is to add two integers. Do not inspect any files or call any tools. Return the standard review JSON with no findings if correct."},
            "delivery": "inline"}, response_model=probe.RPCResult).model_dump()
        RESULT["review_turn"] = wait_turn(client, response["turn"]["id"])
    RESULT["pass"] = RESULT.get("coding_turn") == "completed" and RESULT["tool_roundtrip"] and RESULT.get("review_turn") == "completed"
except Exception as exc:
    RESULT["pass"] = False
    RESULT["error_class"] = type(exc).__name__
finally:
    client.close()
    server.shutdown()
    RESULT["budget"] = STATE
    (OUT / "live-result.json").write_text(json.dumps(RESULT, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(OUT), **RESULT}, ensure_ascii=False, indent=2))
