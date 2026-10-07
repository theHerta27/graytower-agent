"""Offline native V1 lifecycle through a narrow Responses namespace mapping.

Real installed Codex CLI + official Python SDK, two localhost HTTP endpoints.
The upstream is scripted fixture, NOT DeepSeek, and produces no quality evidence.
No credential reads, no model-generated shell or file-edit calls are allowed.
"""
import copy
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
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("D:/Desktop/codex-main")
sys.path.insert(0, str(SOURCE / "sdk/python/src"))
from openai_codex.client import CodexClient, CodexConfig

NS = "multi_agent_v1"
PREFIX = "ma1__"
ALLOWED = {"spawn_agent", "wait_agent", "close_agent"}
MODEL = "deepseek-flash"
CHILD_RESULT = "CHILD_IMMUTABLE_RESULT_73129"
WIRE = []
EVENTS = []
ERRORS = []
LOCK = threading.Lock()


def provider_request(body):
    """Only tools declaration and namespaced function-call history are changed."""
    mapped = copy.deepcopy(body)
    flat = []
    names = set()
    for tool in mapped.get("tools", []):
        if tool.get("type") == "namespace":
            if tool.get("name") != NS:
                raise ValueError("Unregistered namespace")
            for inner in tool["tools"]:
                if inner.get("type") != "function":
                    raise ValueError("Only function schemas can be flattened")
                value = copy.deepcopy(inner)
                value["name"] = PREFIX + inner["name"]
                flat.append(value)
        else:
            flat.append(tool)
    for tool in flat:
        if tool["name"] in names:
            raise ValueError("Flattened name collision")
        names.add(tool["name"])
    mapped["tools"] = flat
    for item in mapped.get("input", []):
        if item.get("type") == "function_call" and item.get("namespace") == NS:
            item["name"] = PREFIX + item["name"]
            del item["namespace"]
        elif item.get("namespace"):
            raise ValueError("Unregistered history namespace")
    return mapped


def runtime_item(item):
    mapped = copy.deepcopy(item)
    if item.get("type") == "function_call":
        name = item["name"]
        if not name.startswith(PREFIX) or name[len(PREFIX):] not in ALLOWED:
            raise ValueError("Fixture scope rejects non-lifecycle tool output")
        mapped["name"] = name[len(PREFIX):]
        mapped["namespace"] = NS
    elif item.get("type") != "message":
        raise ValueError("Unregistered output item")
    return mapped


def runtime_event(event):
    result = copy.deepcopy(event)
    if "item" in result:
        result["item"] = runtime_item(result["item"])
    if "response" in result and "output" in result["response"]:
        result["response"]["output"] = [runtime_item(x) for x in result["response"]["output"]]
    return result


def function(name, arguments, call_id):
    return {"type": "function_call", "name": PREFIX + name,
            "arguments": json.dumps(arguments), "id": "fc_" + call_id,
            "call_id": call_id}


def message(text, item_id):
    return {"type": "message", "role": "assistant", "id": item_id,
            "content": [{"type": "output_text", "text": text}]}


def fixture_answer(body):
    assert body["model"] == MODEL
    assert not any(x.get("type") == "namespace" for x in body["tools"])
    assert all(x.get("type") in {"message", "function_call", "function_call_output"}
               for x in body["input"]), "Unexpected V1 input contract"
    assert all(not x.get("namespace") for x in body["input"])
    outputs = {x["call_id"]: x["output"] for x in body["input"]
               if x.get("type") == "function_call_output"}
    if "probe_close" in outputs:
        return message("PARENT_CONFIRMED_" + CHILD_RESULT, "msg_parent_final")
    if "probe_wait" in outputs:
        assert CHILD_RESULT in outputs["probe_wait"], outputs["probe_wait"]
        child_id = json.loads(outputs["probe_spawn"])["agent_id"]
        return function("close_agent", {"target": child_id}, "probe_close")
    if "probe_spawn" in outputs:
        child_id = json.loads(outputs["probe_spawn"])["agent_id"]
        return function("wait_agent", {"targets": [child_id], "timeout_ms": 10000}, "probe_wait")
    users = [x for x in body["input"] if x.get("role") == "user"]
    latest = json.dumps(users[-1]) if users else ""
    if "CHILD_REQUEST_73129" in latest:
        return message(CHILD_RESULT, "msg_child_final")
    return function("spawn_agent", {"message": "CHILD_REQUEST_73129: return immutable result only; no tools.",
                                    "fork_context": False}, "probe_spawn")


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def read_body(self):
        assert self.path == "/responses"
        return json.loads(self.rfile.read(int(self.headers["Content-Length"])))

    def send_events(self, events):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in events:
            self.wfile.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())
            self.wfile.flush()


class FakeProvider(QuietHandler):
    def do_POST(self):
        try:
            body = self.read_body()
            item = fixture_answer(body)
            rid = "fixture_" + item["id"]
            events = [
                {"type": "response.created", "response": {"id": rid}},
                {"type": "response.output_item.added", "output_index": 0, "item": item},
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": {"id": rid, "output": [item],
                 "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}}}]
            self.send_events(events)
        except BaseException as e:
            ERRORS.append("provider: " + repr(e))
            self.send_error(500, "Fixture assertion failed")


class NarrowRelay(QuietHandler):
    upstream = ""

    def do_POST(self):
        try:
            body = self.read_body()
            mapped = provider_request(body)
            req = Request(self.upstream + "/responses", data=json.dumps(mapped).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=20) as response:
                raw = response.read().decode()
            upstream_events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
            downstream_events = [runtime_event(x) for x in upstream_events]
            with LOCK:
                WIRE.append({"runtime_request": body, "provider_request": mapped,
                             "provider_events": upstream_events, "runtime_events": downstream_events})
            self.send_events(downstream_events)
        except BaseException as e:
            ERRORS.append("relay: " + repr(e))
            self.send_error(500, "Relay contract rejected")


class RecordingClient(CodexClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observed = queue.Queue()

    def _coerce_notification(self, method, params):
        value = super()._coerce_notification(method, params)
        self.observed.put(value)
        return value


def main():
    out = ROOT / "research/evidence" / ("cooperation-protocol-" + time.strftime("%Y%m%d-%H%M%S"))
    runtime = out / "runtime"
    work = out / "workspace"
    runtime.mkdir(parents=True)
    work.mkdir()
    binary = shutil.which("codex")
    safe_env = {k: v for k, v in os.environ.items() if k.upper() in {
        "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP",
        "USERPROFILE", "COMSPEC", "PROCESSOR_ARCHITECTURE"}}
    os.environ.clear()
    os.environ.update(safe_env)
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    provider = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
    NarrowRelay.upstream = "http://127.0.0.1:" + str(provider.server_address[1])
    relay = ThreadingHTTPServer(("127.0.0.1", 0), NarrowRelay)
    for server in (provider, relay):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    old_catalog = ROOT / "research/evidence/runtime-deepseek-20261004-152433/subagent_v1/runtime/models.json"
    models = runtime / "models.json"
    models.write_bytes(old_catalog.read_bytes())
    config = [f'model = "{MODEL}"', 'model_provider = "cooperation_fixture"',
              'approval_policy = "never"', 'approvals_reviewer = "user"',
              'sandbox_mode = "read-only"', 'web_search = "disabled"',
              'model_reasoning_effort = "low"', 'model_reasoning_summary = "none"',
              'model_catalog_json = ' + json.dumps(str(models)),
              '[analytics]', 'enabled = false', '[features]', 'shell_tool = false',
              'apps = false', 'plugins = false', 'memories = false', 'code_mode = false',
              'multi_agent = true', 'multi_agent_v2 = false',
              '[model_providers.cooperation_fixture]', 'name = "Offline cooperation fixture"',
              f'base_url = "http://127.0.0.1:{relay.server_address[1]}"',
              'wire_api = "responses"', 'requires_openai_auth = false',
              'supports_websockets = false', 'request_max_retries = 0', 'stream_max_retries = 0']
    (runtime / "config.toml").write_text("\n".join(config), encoding="utf-8")
    result = {"scope": "Offline fake provider; real CLI/SDK/native parent-child lifecycle. No DeepSeek/model quality claim.",
              "binary": binary, "binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
              "cli_version": subprocess.check_output([binary, "--version"], text=True).strip(),
              "python": sys.version, "sdk_source": str(SOURCE / "sdk/python/src"),
              "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    unexpected_requests = []
    def decline(method, params):
        unexpected_requests.append(method)
        return {"decision": "decline"}
    client = RecordingClient(CodexConfig(codex_bin=binary, cwd=str(work),
        env={"CODEX_HOME": str(runtime)}), approval_handler=decline)
    try:
        client.start()
        client.initialize()
        started = client.thread_start({"cwd": str(work), "model": MODEL,
                  "modelProvider": "cooperation_fixture", "approvalPolicy": "never",
                  "approvalsReviewer": "user", "sandbox": "read-only"})
        result["parent_thread_id"] = started.thread.id
        turn = client.turn_start(started.thread.id, "Run prescribed offline native lifecycle fixture.")
        until = time.monotonic() + 40
        while time.monotonic() < until:
            event = client.observed.get(timeout=max(.1, until - time.monotonic()))
            payload = event.payload.model_dump(mode="json", by_alias=True)
            EVENTS.append({"method": event.method, "params": payload})
            if event.method == "turn/completed" and payload["turn"]["id"] == turn.turn.id:
                result["turn_status"] = payload["turn"]["status"]
                break
        histories = [x for row in WIRE for x in row["runtime_request"]["input"]]
        outputs = {x["call_id"]: x["output"] for x in histories if x.get("type") == "function_call_output"}
        result["native_outputs"] = outputs
        result["child_thread_id"] = json.loads(outputs["probe_spawn"])["agent_id"]
        result["request_count"] = len(WIRE)
        result["models"] = sorted({x["provider_request"]["model"] for x in WIRE})
        result["runtime_input_types"] = sorted({x["type"] for x in histories})
        result["fixture_calls"] = [x["provider_events"][2]["item"].get("name") for x in WIRE
                                    if x["provider_events"][2]["item"]["type"] == "function_call"]
        assert result["turn_status"] == "completed"
        assert len(WIRE) == 5
        assert CHILD_RESULT in outputs["probe_wait"]
        assert CHILD_RESULT in outputs["probe_close"]
        assert result["models"] == [MODEL]
        assert not ERRORS and not unexpected_requests
        for row in WIRE:
            native, mapped = row["runtime_request"], row["provider_request"]
            assert {k:v for k,v in native.items() if k not in {"tools", "input"}} == {
                    k:v for k,v in mapped.items() if k not in {"tools", "input"}}
            for a,b in zip(native["input"], mapped["input"]):
                assert a.get("call_id") == b.get("call_id") and a.get("id") == b.get("id")
                assert {k:v for k,v in a.items() if k not in {"name", "namespace"}} == {
                       k:v for k,v in b.items() if k not in {"name", "namespace"}}
            for a,b in zip(row["provider_events"], row["runtime_events"]):
                if "item" in a:
                    assert a["item"].get("call_id") == b["item"].get("call_id")
                    assert a["item"]["id"] == b["item"]["id"]
        rejected = []
        for bad in (function("exec_command", {}, "bad"), {"type": "function_call", "name": "unknown"}):
            try:
                runtime_item(bad)
            except ValueError:
                rejected.append(True)
        assert len(rejected) == 2
        result["checks"] = {"native_spawn_wait_close": True, "child_result_returned": True,
                            "model_inherited": True, "call_and_item_ids_preserved": True,
                            "history_content_preserved": True, "non_lifecycle_output_rejected": True}
        result["pass"] = True
    except BaseException as e:
        result["pass"] = False
        result["error"] = repr(e)
    finally:
        result["stderr"] = client._stderr_tail(10)
        client.close()
        for server in (relay, provider):
            server.shutdown()
            server.server_close()
        result["errors"] = ERRORS
        result["unexpected_sdk_requests"] = unexpected_requests
        for name, value in (("wire.json", WIRE), ("events.json", EVENTS), ("result.json", result)):
            (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("EVIDENCE=" + str(out))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
