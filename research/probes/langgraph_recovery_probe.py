"""Real LangGraph/SQLite + LangChain offline fault probe; no game or model service.

Run from project root with research/.venv-framework/Scripts/python.exe.
Each invocation creates fresh evidence; children die at a committed side effect.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from typing import TypedDict

# Never send probe traces to a configured remote collector.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt


class State(TypedDict, total=False):
    operation_id: str
    payload_hash: str
    receipt: str


def connect(folder: Path):
    conn = sqlite3.connect(folder / "domain.sqlite")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, payload TEXT NOT NULL,
        reserved INTEGER NOT NULL, receipt TEXT);
    CREATE TABLE IF NOT EXISTS world (id INTEGER PRIMARY KEY, revision INTEGER, rewards INTEGER);
    INSERT OR IGNORE INTO world VALUES (1,0,0);
    CREATE TABLE IF NOT EXISTS outbox (event_id TEXT PRIMARY KEY, value TEXT);
    """)
    conn.commit()
    return conn


def build(saver, folder: Path, kind: str, crash: bool):
    def prepare(state):
        with connect(folder) as conn:
            conn.execute("INSERT OR IGNORE INTO operations VALUES (?,?,?,NULL)",
                         (state["operation_id"], state["payload_hash"], 12 if kind == "experiment" else 0))
            found = conn.execute("SELECT payload FROM operations WHERE id=?", (state["operation_id"],)).fetchone()
            if found[0] != state["payload_hash"]:
                raise ValueError("operation payload mismatch")
        return {}

    def effect(state):
        with connect(folder) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload,receipt FROM operations WHERE id=?", (state["operation_id"],)).fetchone()
            if row[0] != state["payload_hash"]:
                raise ValueError("operation payload mismatch")
            # Receipt lookup precedes expected-revision check for the same command.
            if row[1] is not None:
                return {"receipt": row[1]}
            if kind == "npc":
                revision = conn.execute("SELECT revision FROM world WHERE id=1").fetchone()[0]
                if revision != 0:
                    raise ValueError("stale new command")
                conn.execute("UPDATE world SET revision=revision+1,rewards=rewards+1 WHERE id=1")
                conn.execute("INSERT INTO outbox VALUES (?,?)", (state["operation_id"], "support_granted"))
            else:
                # A fixture stands for a completed worker artifact; no battles are simulated.
                payload = b'{"fixture_experiment":"completed","battles":12}'
                artifact = folder / "artifact.json"
                pending = folder / "artifact.tmp"
                pending.write_bytes(payload)
                pending.replace(artifact)
            receipt = json.dumps({"operation_id": state["operation_id"], "kind": kind, "completed": True})
            conn.execute("UPDATE operations SET receipt=? WHERE id=?", (receipt, state["operation_id"]))
        if crash:
            os._exit(73)  # Real process death: domain committed, node has not returned.
        return {"receipt": receipt}

    graph = StateGraph(State)
    graph.add_node("prepare", prepare)
    graph.add_node("effect", effect)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "effect")
    graph.add_edge("effect", END)
    return graph.compile(checkpointer=saver)


def child(folder: Path, kind: str, mode: str):
    with SqliteSaver.from_conn_string(str(folder / "checkpoint.sqlite")) as saver:
        graph = build(saver, folder, kind, mode == "crash")
        config = {"configurable": {"thread_id": kind + "-fixed-run"}}
        state = {"operation_id": kind + "-fixed-op", "payload_hash": "frozen-spec-v1"} if mode == "crash" else None
        result = graph.invoke(state, config, durability="sync")
        print(json.dumps(result))


def effect_case(root: Path, kind: str):
    folder = root / kind
    folder.mkdir()
    args = [sys.executable, str(Path(__file__).resolve()), "--child", str(folder), "--kind", kind]
    env = dict(os.environ)
    # No provider credential is needed or passed to the child.
    for key in list(env):
        if any(x in key.upper() for x in ("API_KEY", "TOKEN", "SECRET")):
            env.pop(key)
    crash = subprocess.run(args + ["--mode", "crash"], capture_output=True, text=True, env=env, timeout=60)
    assert crash.returncode == 73, crash.stderr
    with SqliteSaver.from_conn_string(str(folder / "checkpoint.sqlite")) as saver:
        graph = build(saver, folder, kind, False)
        snapshot = graph.get_state({"configurable": {"thread_id": kind + "-fixed-run"}})
        assert "receipt" not in snapshot.values
        assert snapshot.next == ("effect",), snapshot.next
    results = []
    for _ in range(3):
        resumed = subprocess.run(args + ["--mode", "resume"], capture_output=True, text=True, env=env, timeout=60)
        assert resumed.returncode == 0, resumed.stderr
        results.append(json.loads(resumed.stdout))
    assert all(r == results[0] for r in results)
    with connect(folder) as conn:
        rows = conn.execute("SELECT id,reserved,receipt FROM operations").fetchall()
        world = conn.execute("SELECT revision,rewards FROM world").fetchone()
        outbox_count = conn.execute("SELECT count(*) FROM outbox").fetchone()[0]
    assert len(rows) == 1 and rows[0][2]
    assert rows[0][1] == (12 if kind == "experiment" else 0)
    assert world == ((1, 1) if kind == "npc" else (0, 0))
    assert outbox_count == (1 if kind == "npc" else 0)
    # Replaying an older checkpoint really re-enters effect; domain receipt prevents duplication.
    with SqliteSaver.from_conn_string(str(folder / "checkpoint.sqlite")) as saver:
        graph = build(saver, folder, kind, False)
        replay = graph.invoke(None, snapshot.config, durability="sync")
        assert replay["receipt"] == results[0]["receipt"]
    with connect(folder) as conn:
        assert conn.execute("SELECT revision,rewards FROM world").fetchone() == world
    return {"status": "PASS", "crash_exit": 73, "checkpoint_pending": list(snapshot.next),
            "receipt_absent_from_checkpoint_after_crash": True, "fresh_process_resumes": 3,
            "old_checkpoint_replay_deduped": True, "domain_operations": len(rows),
            "budget_reserved": rows[0][1], "world_revision": world[0], "rewards": world[1],
            "outbox_count": outbox_count}


def interrupt_case(root: Path):
    visits = []
    class Approval(TypedDict, total=False):
        approved: bool
    def approve(state):
        visits.append("entered")  # Explicitly show node-entry repetition; do not put writes here in product.
        answer = interrupt({"spec_hash": "fixed", "approval_id": "fixed-approval"})
        return {"approved": answer["approved"]}
    with SqliteSaver.from_conn_string(str(root / "interrupt.sqlite")) as saver:
        builder = StateGraph(Approval)
        builder.add_node("approve", approve)
        builder.add_edge(START, "approve")
        builder.add_edge("approve", END)
        graph = builder.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": "approval-thread"}}
        first = graph.invoke({}, config, durability="sync")
        interrupt_id = first["__interrupt__"][0].id
        result = graph.invoke(Command(resume={interrupt_id: {"approved": True}}), config, durability="sync")
        assert result["approved"] is True and len(visits) == 2
    return {"status": "PASS", "entries_for_one_approval": len(visits), "resume_by_interrupt_id": True,
            "limitation": "Sequential framework semantic probe; API nonce/CAS concurrency not implemented."}


def component_case():
    import httpx
    from pydantic import BaseModel, ConfigDict
    from typing import Literal
    from langchain_deepseek import ChatDeepSeek
    from langchain_core.tools import tool
    from langchain_core.messages import AIMessage
    from langgraph.prebuilt import ToolNode
    class Intent(BaseModel):
        model_config = ConfigDict(extra="forbid")
        action: Literal["offer_support", "say"]
        support_id: Literal["shield_start", "sp_supply"] | None
    captured = []
    def transport(request):
        body = json.loads(request.content)
        captured.append(body)
        name = body["tools"][0]["function"]["name"]
        return httpx.Response(200, json={"id": "offline-fixture", "object": "chat.completion",
            "created": 0, "model": "offline-fixture", "choices": [{"index": 0,
            "message": {"role": "assistant", "content": "", "tool_calls": [{"id": "intent-1",
                "type": "function", "function": {"name": name, "arguments":
                '{"action":"offer_support","support_id":"shield_start"}'}}]},
            "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 1,"completion_tokens":1,"total_tokens":2}})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ChatDeepSeek(model="offline-fixture", api_key="fixture-not-a-secret",
                             api_base="https://fixture.invalid", http_client=client, max_retries=0)
        structured = model.with_structured_output(Intent, method="function_calling", include_raw=True)
        result = structured.invoke("Offer the permitted shield support")
    assert result["parsing_error"] is None
    assert result["parsed"].support_id == "shield_start" and len(captured) == 1
    @tool
    def read_visible_fact(fact_id: str) -> str:
        """Read one visible fact from the fixed offline NPC projection."""
        if fact_id != "known_guardian":
            raise ValueError("not visible")
        return "The guardian has three phases."
    node = ToolNode([read_visible_fact])
    message = AIMessage(content="", tool_calls=[{"name": "read_visible_fact", "args":
                          {"fact_id": "known_guardian"}, "id": "read-1", "type": "tool_call"}])
    # ToolNode requires Runtime supplied by compiled graph execution in this release.
    from langgraph.graph import MessagesState
    tool_graph = StateGraph(MessagesState)
    tool_graph.add_node("tools", node)
    tool_graph.add_edge(START, "tools")
    tool_graph.add_edge("tools", END)
    output = tool_graph.compile().invoke({"messages": [message]})
    assert output["messages"][-1].tool_call_id == "read-1"
    assert output["messages"][-1].content == "The guardian has three phases."
    return {"status": "PASS", "structured_output": result["parsed"].model_dump(),
            "component": "ChatDeepSeek.with_structured_output(function_calling) + @tool + ToolNode",
            "provider_calls": 0, "http_fixture_calls": len(captured),
            "limitation": "MockTransport validates SDK composition, not provider availability, quality or latency."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", type=Path)
    parser.add_argument("--kind", choices=["experiment", "npc"])
    parser.add_argument("--mode", choices=["crash", "resume"])
    args = parser.parse_args()
    if args.child:
        child(args.child, args.kind, args.mode)
        return
    evidence = Path(__file__).resolve().parents[1] / "evidence"
    root = Path(tempfile.mkdtemp(prefix="langgraph-20261004-", dir=evidence))
    result = {"evidence_dir": str(root), "python": sys.version, "versions": {
        name: importlib.metadata.version(name) for name in ("langgraph", "langgraph-checkpoint",
        "langgraph-checkpoint-sqlite", "langchain", "langchain-core", "langchain-deepseek", "pydantic")},
        "experiment": effect_case(root, "experiment"), "npc": effect_case(root, "npc"),
        "interrupt": interrupt_case(root), "components": component_case()}
    result["status"] = "PASS"
    result["probe_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (root / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
