"""Offline SDK boundary probe: no Codex process, provider, credentials or network."""
import inspect
import json
from pathlib import Path
import sys
import threading

sys.dont_write_bytecode = True
ROOT = Path(r"D:\Desktop\codex-main")
sys.path.insert(0, str(ROOT / "sdk/python/src"))
from openai_codex import AsyncCodex, Codex, CodexConfig
from openai_codex.client import CodexClient, CodexBinResolverOps, resolve_codex_bin
from openai_codex._runtime_requirements import require_runtime_version

result = {"scope": "offline in-memory SDK behavior; no real subprocess/model/tool", "checks": {}}
client = CodexClient(CodexConfig())
result["checks"]["default_command_approval"] = client._default_approval_handler("item/commandExecution/requestApproval", {})
result["checks"]["default_file_approval"] = client._default_approval_handler("item/fileChange/requestApproval", {})
result["checks"]["high_level_signatures"] = {"Codex": str(inspect.signature(Codex)), "AsyncCodex": str(inspect.signature(AsyncCodex))}
path = resolve_codex_bin(CodexConfig(codex_bin="fixture-codex.exe"), CodexBinResolverOps(path_exists=lambda _: True, installed_codex_path=lambda: Path("should-not-be-used.exe")))
result["checks"]["custom_executable_override"] = str(path)
require_runtime_version("0.159.0-alpha.12.1")
result["checks"]["installed_alpha_passes_version_floor"] = True

entered = threading.Event()
release = threading.Event()
routed = threading.Event()
def delayed_approval(method, params):
    entered.set()
    if not release.wait(3):
        raise TimeoutError("probe release timeout")
    return {"decision": "decline"}

blocking_client = CodexClient(approval_handler=delayed_approval)
messages = iter([
    {"id": 9, "method": "item/commandExecution/requestApproval", "params": {}},
    {"method": "item/agentMessage/delta", "params": {"threadId": "t", "turnId": "u", "itemId": "i", "delta": "pending"}},
])
blocking_client._read_message = lambda: next(messages)
blocking_client._write_message = lambda payload: None
blocking_client._router.route_notification = lambda notification: routed.set()
blocking_client._router.fail_all = lambda error: None
worker = threading.Thread(target=blocking_client._reader_loop, daemon=True)
worker.start()
assert entered.wait(2), "approval callback was not reached"
blocked = not routed.wait(0.1)
release.set()
worker.join(2)
assert blocked and routed.is_set() and not worker.is_alive()
result["checks"]["waiting_approval_blocks_notification_reader"] = blocked
result["checks"]["notification_resumes_after_handler_returns"] = routed.is_set()
out = Path(__file__).with_name("codex-sdk-static-probe-result.json")
out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2, ensure_ascii=False))
