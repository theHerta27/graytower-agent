"""LangGraph owns routing; the domain ledger owns input, approval and receipts."""
import json
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .contracts import ExperimentPlan, GamePort
from .report import build_report
from .store import Store, driver_lock


class State(TypedDict, total=False):
    request_id: str
    approved: bool
    receipt_hash: str


class Verification:
    def __init__(self, folder: Path, game: GamePort):
        self.folder = Path(folder)
        self.store = Store(self.folder)
        self.game = game

    def graph(self, saver):
        def checked_validate(plan):
            result = self.game.validate(plan)
            if result.get("passed") is not True:
                raise ValueError("game validation failed")

        def validate(state):
            checked_validate(self.store.plan(state["request_id"]))
            return {}

        def authorize(state):
            row = self.store.get(state["request_id"])
            if row["approved"] is None:
                interrupt({"plan_hash": row["plan_hash"], "plan": json.loads(row["plan_json"])})
                row = self.store.get(state["request_id"])
            if row["approved"] is None:
                raise ValueError("resume is not an approval")
            return {"approved": bool(row["approved"])}

        def experiment(state):
            p = self.store.plan(state["request_id"])
            row = self.store.get(p.request_id)
            if row["job_status"] != "completed":
                checked_validate(p)
                self.store.claim(p)
                result = self.game.execute(p)
                self.store.complete(p, result)
            return {"receipt_hash": self.store.get(p.request_id)["result_hash"]}

        graph = StateGraph(State)
        graph.add_node("validate", validate)
        graph.add_node("authorize", authorize)
        graph.add_node("experiment", experiment)
        graph.add_edge(START, "validate")
        graph.add_edge("validate", "authorize")
        graph.add_conditional_edges("authorize", lambda state: "experiment" if state["approved"] else END)
        graph.add_edge("experiment", END)
        return graph.compile(checkpointer=saver)

    def prepare(self, plan: ExperimentPlan):
        with driver_lock(self.folder):
            self.store.create(plan)
            return self._drive(plan.request_id)

    def decide(self, request_id: str, plan_hash: str, approve: bool):
        with driver_lock(self.folder):
            self.store.decide(request_id, plan_hash, approve)
            return self._drive(request_id)

    def resume(self, request_id: str):
        with driver_lock(self.folder):
            return self._drive(request_id)

    def _drive(self, request_id: str):
        row = self.store.get(request_id)
        with SqliteSaver.from_conn_string(str(self.folder / "checkpoint.sqlite")) as saver:
            graph = self.graph(saver)
            config = {"configurable": {"thread_id": request_id}, "recursion_limit": 12}
            snapshot = graph.get_state(config)
            if not snapshot.values:
                graph.invoke({"request_id": request_id}, config, durability="sync")
                snapshot = graph.get_state(config)
            if snapshot.interrupts and row["approved"] is not None:
                graph.invoke(Command(resume={item.id: "reconcile-domain-decision" for item in snapshot.interrupts}),
                             config, durability="sync")
            elif snapshot.next and not snapshot.interrupts:
                graph.invoke(None, config, durability="sync")
        return self.show(request_id)

    def show(self, request_id: str):
        row = self.store.get(request_id)
        status = "awaiting_approval" if row["approved"] is None else "rejected" if not row["approved"] else row["job_status"]
        value = dict(request_id=request_id, status=status, plan_hash=row["plan_hash"],
                     charged_battles=row["charged_battles"], plan=json.loads(row["plan_json"]))
        if row["result_json"] is not None:
            value.update(receipt_hash=row["result_hash"],
                         report=build_report(self.store.plan(request_id), json.loads(row["result_json"])))
        return value
