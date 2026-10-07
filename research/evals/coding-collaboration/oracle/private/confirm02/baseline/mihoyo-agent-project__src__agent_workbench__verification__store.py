"""Authoritative local ledger. Graph checkpoints never grant approval or reset cost."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from .contracts import ExperimentPlan, canonical, fingerprint


@contextmanager
def driver_lock(folder: Path):
    """OS releases this single-driver lock on process death; no lease-based takeover."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "driver.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        import os
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Store:
    def __init__(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "domain.sqlite"
        with self.connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS runs (
                request_id TEXT PRIMARY KEY, plan_json TEXT NOT NULL, plan_hash TEXT NOT NULL,
                approved INTEGER, charged_battles INTEGER NOT NULL DEFAULT 0,
                job_status TEXT NOT NULL DEFAULT 'new', result_json TEXT, result_hash TEXT)""")

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=FULL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, plan: ExperimentPlan):
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO runs(request_id,plan_json,plan_hash) VALUES(?,?,?)",
                         (plan.request_id, canonical(plan), fingerprint(plan)))
            row = conn.execute("SELECT plan_hash FROM runs WHERE request_id=?", (plan.request_id,)).fetchone()
            if row[0] != fingerprint(plan):
                raise ValueError("request ID payload conflict")

    def get(self, request_id: str) -> dict:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            raise ValueError("unknown request ID")
        result = dict(row)
        plan = ExperimentPlan.model_validate_json(result["plan_json"])
        if fingerprint(plan) != result["plan_hash"]:
            raise ValueError("plan integrity failure")
        if result["result_json"] is not None and fingerprint(json.loads(result["result_json"])) != result["result_hash"]:
            raise ValueError("receipt integrity failure")
        return result

    def plan(self, request_id: str) -> ExperimentPlan:
        return ExperimentPlan.model_validate_json(self.get(request_id)["plan_json"])

    def decide(self, request_id: str, plan_hash: str, approve: bool):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT plan_hash,approved FROM runs WHERE request_id=?", (request_id,)).fetchone()
            if row is None or row[0] != plan_hash:
                raise ValueError("approval plan hash mismatch")
            if row[1] is not None and row[1] != int(approve):
                raise ValueError("approval decision is immutable; create a new reviewed plan")
            conn.execute("UPDATE runs SET approved=? WHERE request_id=?", (int(approve), request_id))

    def claim(self, plan: ExperimentPlan):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM runs WHERE request_id=?", (plan.request_id,)).fetchone()
            if row is None or row["plan_hash"] != fingerprint(plan) or row["approved"] != 1:
                raise ValueError("missing matching approval")
            if row["job_status"] != "new":
                raise RuntimeError("worker outcome unknown; reconcile receipt, no automatic retry")
            conn.execute("UPDATE runs SET job_status='running',charged_battles=? WHERE request_id=?",
                         (plan.battles, plan.request_id))

    def complete(self, plan: ExperimentPlan, result: dict):
        from .report import build_report
        build_report(plan, result)  # Check manifest before acknowledging a completed experiment.
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM runs WHERE request_id=?", (plan.request_id,)).fetchone()
            if row is None or row["plan_hash"] != fingerprint(plan) or row["approved"] != 1:
                raise ValueError("receipt does not match approved plan")
            if row["job_status"] == "completed" and row["result_hash"] == fingerprint(result):
                return
            if row["job_status"] != "running":
                raise ValueError("receipt is immutable or operation was never admitted")
            conn.execute("UPDATE runs SET job_status='completed',result_json=?,result_hash=? WHERE request_id=?",
                         (canonical(result), fingerprint(result), plan.request_id))
