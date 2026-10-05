"""Behavioral contracts for the local Verification experiment slice."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from agent_workbench.verification.contracts import ExperimentPlan, fingerprint
from agent_workbench.verification.store import Store, driver_lock
from agent_workbench.verification.workflow import Verification
from agent_workbench.verification.report import build_report
from agent_workbench.verification.combat_worker import CombatAdapter, source_fingerprint


def plan(**overrides):
    value = dict(request_id="balance-1", request="第二阶段有点拖，先看看提高战技倍率的效果。",
                 game_fingerprint="a" * 64, changes=[{"path": "skills.breaker_skill.multiplier", "value": 1.7}],
                 bounds={"skills.breaker_skill.multiplier": {"minimum": 1.4, "maximum": 1.7}},
                 seeds=[7, 11], policies=["balanced"], max_battles=4)
    value.update(overrides)
    return ExperimentPlan.model_validate(value)


def rows(p):
    return [dict(seed=seed, policy=policy, baseline=dict(outcome="win", elapsed_av="100"),
                 candidate=dict(outcome="win", elapsed_av="90")) for policy in p.policies for seed in p.seeds]


def receipt(p, data=None):
    return {"rows": rows(p) if data is None else data, "game_fingerprint": p.game_fingerprint,
            "plan_hash": fingerprint(p)}


class CountingGame:
    def __init__(self):
        self.executions = 0

    def validate(self, p):
        return {"passed": True}

    def execute(self, p):
        self.executions += 1
        return receipt(p)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.game = CountingGame()
        self.app = Verification(self.folder, self.game)

    def tearDown(self):
        self.temp.cleanup()

    def test_pause_and_rejection_never_simulate(self):
        p = plan()
        self.assertEqual(self.app.prepare(p)["status"], "awaiting_approval")
        self.assertEqual(self.app.resume(p.request_id)["status"], "awaiting_approval")
        self.assertEqual(self.game.executions, 0)
        self.assertEqual(self.app.decide(p.request_id, fingerprint(p), False)["status"], "rejected")
        self.assertEqual(self.app.resume(p.request_id)["status"], "rejected")
        self.assertEqual(self.game.executions, 0)
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.app.decide(p.request_id, fingerprint(p), True)

    def test_same_id_different_payload_conflicts(self):
        self.app.prepare(plan())
        with self.assertRaisesRegex(ValueError, "payload"):
            self.app.prepare(plan(request="偷偷换了需求"))

    def test_approval_hash_and_durable_decision(self):
        p = plan()
        self.app.prepare(p)
        with self.assertRaisesRegex(ValueError, "hash"):
            self.app.decide(p.request_id, "b" * 64, True)
        self.assertEqual(self.game.executions, 0)
        # Simulate approval committed but no graph wake-up delivered yet.
        Store(self.folder).decide(p.request_id, fingerprint(p), True)
        value = Verification(self.folder, self.game).resume(p.request_id)
        self.assertEqual(value["status"], "completed")
        self.assertEqual(value["report"]["verdict"], "DESCRIPTIVE_ONLY")

    def test_completed_receipt_before_checkpoint_reuses_results(self):
        p = plan()
        self.app.prepare(p)
        store = Store(self.folder)
        store.decide(p.request_id, fingerprint(p), True)
        store.claim(p)
        store.complete(p, self.game.execute(p))
        # Graph is still at its approval checkpoint; receipt is already committed.
        for _ in range(3):
            value = Verification(self.folder, self.game).resume(p.request_id)
            self.assertEqual(value["status"], "completed")
        self.assertEqual(self.game.executions, 1)
        self.assertEqual(store.get(p.request_id)["charged_battles"], 4)

    def test_no_automatic_retry_when_worker_outcome_unknown(self):
        p = plan()
        self.app.prepare(p)
        store = Store(self.folder)
        store.decide(p.request_id, fingerprint(p), True)
        store.claim(p)
        with self.assertRaisesRegex(RuntimeError, "outcome unknown"):
            self.app.resume(p.request_id)
        self.assertEqual(self.game.executions, 0)
        self.assertEqual(store.get(p.request_id)["charged_battles"], 4)

    def test_corrupt_receipt_is_rejected_even_after_graph_completion(self):
        p = plan()
        self.app.prepare(p)
        self.app.decide(p.request_id, fingerprint(p), True)
        with closing(sqlite3.connect(self.folder / "domain.sqlite")) as conn:
            with conn:
                conn.execute("UPDATE runs SET result_json='{}' WHERE request_id=?", (p.request_id,))
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.app.resume(p.request_id)
        self.assertEqual(self.game.executions, 1)

    def test_plan_budget_and_duplicate_seeds_rejected(self):
        for overrides in [{"max_battles": 3}, {"seeds": [7, 7]}, {"seeds": [True]}, {"policies": ["balanced", "balanced"]}]:
            with self.assertRaises(ValueError):
                plan(**overrides)

    def test_invalid_candidate_stops_before_approval(self):
        class InvalidGame(CountingGame):
            def validate(self, p):
                raise ValueError("outside authorized bounds")
        game = InvalidGame()
        with self.assertRaisesRegex(ValueError, "bounds"):
            Verification(self.folder, game).prepare(plan())
        self.assertEqual(game.executions, 0)

    def test_failed_validation_result_cannot_reach_execution(self):
        class InvalidGame(CountingGame):
            def validate(self, p):
                return {"passed": False, "errors": ["bad candidate"]}
        game = InvalidGame()
        with self.assertRaisesRegex(ValueError, "validation"):
            Verification(self.folder, game).prepare(plan())
        self.assertEqual(game.executions, 0)

    def test_receipt_from_another_candidate_cannot_complete_approved_plan(self):
        p = plan()
        other = plan(changes=[{"path": "skills.breaker_skill.multiplier", "value": 1.5}])
        self.app.prepare(p)
        store = Store(self.folder)
        store.decide(p.request_id, fingerprint(p), True)
        store.claim(p)
        with self.assertRaisesRegex(ValueError, "plan hash"):
            store.complete(p, receipt(other))
        self.assertEqual(store.get(p.request_id)["job_status"], "running")

    def test_integer_numeric_changes_survive_real_game_validation(self):
        root = Path("D:/Desktop/combat-foundation")
        p = plan(game_fingerprint=source_fingerprint(root),
                 changes=[{"path": "phases.phase_2.toughness_max", "value": 288}],
                 bounds={"phases.phase_2.toughness_max": {"minimum": 288, "maximum": 360}})
        self.assertIs(type(p.changes[0].value), int)
        self.assertTrue(CombatAdapter(root).validate(p)["passed"])
        with self.assertRaises(ValueError):
            plan(changes=[{"path": "skills.breaker_skill.multiplier", "value": True}])

    def test_executed_package_entry_is_in_source_fingerprint(self):
        (self.folder / "game-core/combat_core").mkdir(parents=True)
        package = self.folder / "services/verification-agent/verification_agent"
        (package / "v2").mkdir(parents=True)
        config = self.folder / "configs/combat/v2"
        config.mkdir(parents=True)
        (config / "baseline.json").write_text("{}")
        (config / "scenario.json").write_text("{}")
        entry = package / "__init__.py"
        entry.write_text("# first")
        first = source_fingerprint(self.folder)
        entry.write_text("# changed")
        self.assertNotEqual(first, source_fingerprint(self.folder))

    def test_second_process_cannot_drive_locked_folder(self):
        code = ("from pathlib import Path; import sys; "
                "from agent_workbench.verification.store import driver_lock\n"
                "try:\n with driver_lock(Path(sys.argv[1])): pass\n"
                "except OSError: sys.exit(42)\n")
        with driver_lock(self.folder):
            proc = subprocess.run([sys.executable, "-c", code, str(self.folder)], capture_output=True, timeout=15)
        self.assertEqual(proc.returncode, 42, proc.stderr)


class ReportTests(unittest.TestCase):
    def test_paired_ratio_not_ratio_of_unpaired_medians(self):
        p = plan()
        data = rows(p)
        data[0]["baseline"]["elapsed_av"] = "10"
        data[0]["candidate"]["elapsed_av"] = "20"
        data[1]["baseline"]["elapsed_av"] = "1000"
        data[1]["candidate"]["elapsed_av"] = "100"
        report = build_report(p, receipt(p, data))
        self.assertEqual(report["policies"]["balanced"]["paired_av_ratio_median"], 1.05)
        self.assertEqual(report["verdict"], "DESCRIPTIVE_ONLY")

    def test_missing_duplicate_wrong_manifest_and_bad_av_rejected(self):
        p = plan()
        for data in [rows(p)[:1], [rows(p)[0]] * 2, [dict(rows(p)[0], seed=99), rows(p)[1]]]:
            with self.assertRaises(ValueError):
                build_report(p, receipt(p, data))
        data = rows(p)
        data[0]["baseline"]["elapsed_av"] = "0"
        with self.assertRaises(ValueError):
            build_report(p, receipt(p, data))

    def test_losses_remain_in_denominator_and_no_common_win_is_null(self):
        p = plan()
        data = rows(p)
        for row in data:
            row["candidate"]["outcome"] = "timeout"
        report = build_report(p, receipt(p, data))
        group = report["policies"]["balanced"]
        self.assertEqual(group["candidate_win_rate"], 0)
        self.assertEqual(group["transitions"], {"win->timeout": 2})
        self.assertIsNone(group["paired_av_ratio_median"])
        self.assertFalse(group["no_observed_win_regressions"])


if __name__ == "__main__":
    unittest.main()
