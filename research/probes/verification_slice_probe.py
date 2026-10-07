"""Product slice + real game + deliberate process death after domain commit.

Run with the framework venv from the project root. No paid model calls.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from agent_workbench.verification.combat_worker import CombatAdapter, source_fingerprint
from agent_workbench.verification.contracts import ExperimentPlan, fingerprint
from agent_workbench.verification.store import Store
from agent_workbench.verification.workflow import Verification


def child(folder, operation):
    game = Path("D:/Desktop/combat-foundation")
    p = ExperimentPlan.model_validate({**json.loads((ROOT / "examples/verification-breaker.json").read_text(encoding="utf-8")),
                                       "request_id": "crash-after-receipt", "seeds": [7], "max_battles": 4,
                                       "game_fingerprint": source_fingerprint(game)})
    app = Verification(folder, CombatAdapter(game))
    if operation in ("crash", "unknown"):
        app.prepare(p)
        if operation == "crash":
            real_complete = app.store.complete
            def die_after_commit(plan, result):
                real_complete(plan, result)
                os._exit(73)
            app.store.complete = die_after_commit
        else:
            app.game.execute = lambda plan: os._exit(74)
        app.decide(p.request_id, fingerprint(p), True)
    else:
        print(json.dumps(app.resume(p.request_id), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", type=Path)
    parser.add_argument("--operation", choices=["crash", "resume", "unknown"])
    args = parser.parse_args()
    if args.child:
        child(args.child, args.operation)
        return
    folder = Path(tempfile.mkdtemp(prefix="verification-recovery-", dir=ROOT / "research/evidence"))
    env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}}
    env["PYTHONUTF8"] = "1"
    command = [sys.executable, str(Path(__file__).resolve()), "--child", str(folder)]
    first = subprocess.run(command + ["--operation", "crash"], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    assert first.returncode == 73, first.stderr
    from langgraph.checkpoint.sqlite import SqliteSaver
    with SqliteSaver.from_conn_string(str(folder / "checkpoint.sqlite")) as saver:
        app = Verification(folder, CombatAdapter(Path("D:/Desktop/combat-foundation")))
        snapshot = app.graph(saver).get_state({"configurable": {"thread_id": "crash-after-receipt"}})
        assert snapshot.next == ("experiment",) and "receipt_hash" not in snapshot.values
    before = Store(folder).get("crash-after-receipt")
    resumed = []
    for _ in range(3):
        proc = subprocess.run(command + ["--operation", "resume"], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        assert proc.returncode == 0, proc.stderr
        resumed.append(json.loads(proc.stdout))
    after = Store(folder).get("crash-after-receipt")
    assert before == after and after["charged_battles"] == 4
    assert all(r == resumed[0] and r["status"] == "completed" for r in resumed)
    unknown_folder = folder / "unknown-outcome"
    unknown_cmd = [sys.executable, str(Path(__file__).resolve()), "--child", str(unknown_folder)]
    unknown = subprocess.run(unknown_cmd + ["--operation", "unknown"], capture_output=True, text=True, env=env, timeout=60)
    assert unknown.returncode == 74, unknown.stderr
    retry = subprocess.run(unknown_cmd + ["--operation", "resume"], capture_output=True, text=True, env=env, timeout=60)
    assert retry.returncode != 0 and "outcome unknown" in retry.stderr, retry.stderr
    unknown_row = Store(unknown_folder).get("crash-after-receipt")
    assert unknown_row["job_status"] == "running" and unknown_row["charged_battles"] == 4 and unknown_row["result_json"] is None
    result = dict(kind="real_game_product_slice_recovery", death_code=first.returncode,
                  checkpoint_before_resume=dict(next=list(snapshot.next), values=snapshot.values),
                  new_process_resumes=3, domain_row_unchanged=True, charged_battles=4,
                  unknown_case=dict(death_code=74, resume_rejected=True, charged_battles=4, simulations_started=0),
                  result=resumed[0], sources={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                            for p in (ROOT / "src").rglob("*.py")})
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(folder / "result.json"), "death_code": 73,
                      "new_process_resumes": 3, "charged_battles": 4}, ensure_ascii=False))


if __name__ == "__main__":
    main()
