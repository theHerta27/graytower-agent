"""Immutable stdio MCP server used only by the local Codex protocol probe."""
import json
import sys
from pathlib import Path

audit_path = Path(sys.argv[sys.argv.index("--audit") + 1]) if "--audit" in sys.argv else None
fail_second = "--fail-second-call" in sys.argv
tool_calls = 0

for line in sys.stdin:
    message = json.loads(line)
    if audit_path:
        with audit_path.open("a", encoding="utf-8") as audit:
            audit.write(json.dumps(message) + "\n")
    if "id" not in message:
        continue
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": message.get("params", {}).get("protocolVersion", "2024-11-05"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "immutable-fixture", "version": "0.1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "read_fixture", "description": "Read immutable fixture",
                  "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                  "annotations": {"readOnlyHint": True, "destructiveHint": False}}]}
    elif method == "tools/call" and message.get("params", {}).get("name") == "read_fixture":
        tool_calls += 1
        result = {"content": [{"type": "text", "text": "IMMUTABLE_MCP_FIXTURE"}]}
        if fail_second and tool_calls == 2:
            result = {"isError": True, "content": [{"type": "text", "text": "CONTROLLED_MCP_ERROR"}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
