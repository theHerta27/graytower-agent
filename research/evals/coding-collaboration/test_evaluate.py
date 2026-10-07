"""Behavior tests for independent, non-keyword collaboration adjudication."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).with_name("evaluate.py")


def load_evaluator():
    if not PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("collaboration_evaluate", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load_evaluator()
ORACLE = {"tasks": [{"task_id": "task-1", "split": "confirmation", "exhaustive": True,
                     "issues": [{"issue_id": "defect-1", "severity": "high", "root_cause": "discarded version",
                                 "trigger": "stale receipt", "paths": ["src/store.py"]}]}]}


def run(run_id="r1", mode="single", **changes):
    result = {"run_id": run_id, "task_id": "task-1", "mode": mode, "repeat": 1,
              "status": "completed", "protocol_passed": True,
              "findings": [{"title": "discarded version", "body": "Stale receipt accepts another version",
                            "path": "src/store.py", "line": 10}],
              "usage": {"input_tokens": 100, "output_tokens": 20}, "cost_usd": 0.01,
              "timing": {"end_to_end_seconds": 2.0}}
    result.update(changes)
    return result


def adjudicate(runs):
    packet, mapping, template = E.prepare(runs, ORACLE)
    template["reviewer"] = "independent-reviewer"
    for record in template["runs"]:
        record["output_qualified"] = True
        for finding in record["findings"]:
            finding.update(verdict="tp", issue_id="defect-1", rationale="Compared source, root cause and stale input",
                           checks={"root_cause": True, "trigger": True, "path": True, "evidence": True},
                           evidence_refs=["src/store.py:10"])
    return template


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(E, "Independent evaluator implementation is not present")

    def test_prepare_blinds_mode_and_does_not_auto_award_keyword_tp(self):
        packet, mapping, template = E.prepare([run(mode="teamparallel")], ORACLE)
        self.assertNotIn("teamparallel", json.dumps(packet))
        self.assertNotIn("r1", json.dumps(packet))
        self.assertEqual(template["runs"][0]["findings"][0]["verdict"], "pending")
        self.assertEqual(mapping["runs"][0]["mode"], "teamparallel")

    def test_unreviewed_findings_cannot_be_scored_as_tp(self):
        _, _, template = E.prepare([run()], ORACLE)
        scored = E.score([run()], ORACLE, template)
        self.assertEqual(scored["runs"][0]["tp"], 0)
        self.assertEqual(scored["runs"][0]["adjudication_status"], "pending")
        self.assertIsNone(scored["runs"][0]["quality_fn"])

    def test_tp_requires_every_causal_check_and_source_reference(self):
        for field in ("root_cause", "trigger", "path", "evidence"):
            template = adjudicate([run()])
            template["runs"][0]["findings"][0]["checks"][field] = False
            with self.assertRaisesRegex(ValueError, "causal checks"):
                E.score([run()], ORACLE, template)

    def test_duplicate_findings_do_not_multiply_recall(self):
        data = run()
        data["findings"] *= 2
        scored = E.score([data], ORACLE, adjudicate([data]))["runs"][0]
        self.assertEqual(scored["tp"], 1)
        self.assertEqual(scored["duplicate_findings"], 1)
        self.assertEqual(scored["quality_fn"], 0)

    def test_infrastructure_failure_stays_in_delivery_denominator(self):
        data = [run(), run("r2", status="infrastructure_failure", protocol_passed=False, findings=[])]
        scored = E.score(data, ORACLE, adjudicate(data))
        self.assertEqual(scored["summary"]["attempted_runs"], 2)
        self.assertEqual(scored["summary"]["delivered_runs"], 1)
        self.assertEqual(scored["runs"][1]["delivery_missing_issues"], ["defect-1"])
        self.assertIsNone(scored["runs"][1]["quality_fn"])
        self.assertEqual(scored["summary"]["cost_usd_known_sum"], 0.02)

    def test_score_refuses_stale_adjudication_after_output_changed(self):
        data = [run()]
        template = adjudicate(data)
        data[0]["findings"][0]["body"] = "other finding"
        with self.assertRaisesRegex(ValueError, "digest"):
            E.score(data, ORACLE, template)

    def test_unknown_issue_id_cannot_gain_credit(self):
        template = adjudicate([run()])
        template["runs"][0]["findings"][0]["issue_id"] = "invented"
        with self.assertRaisesRegex(ValueError, "Unknown issue"):
            E.score([run()], ORACLE, template)

    def test_serial_parallel_audit_uses_actual_overlap(self):
        children = [{"agent_id": "c1", "start": 1.0, "end": 5.0},
                    {"agent_id": "c2", "start": 4.0, "end": 8.0}]
        a = E.audit_schedule(run(mode="teamserial", native={"verified": True, "children": children}))
        self.assertEqual(a["schedule_conforms"], False)
        self.assertEqual(a["max_active_children"], 2)
        self.assertEqual(a["overlap_seconds"], 1.0)
        self.assertEqual(E.audit_schedule(run(mode="teamparallel", native={"children": children}))["schedule_conforms"], True)

    def test_missing_timing_or_native_claim_is_not_verification(self):
        a = E.audit_schedule(run(mode="teamparallel", native={"verified": True}))
        self.assertIsNone(a["schedule_conforms"])
        self.assertEqual(a["native_status"], "unverified")

    def test_nonexhaustive_oracle_does_not_claim_full_recall(self):
        oracle = copy.deepcopy(ORACLE)
        oracle["tasks"][0]["exhaustive"] = False
        packet, mapping, template = E.prepare([run()], oracle)
        template["reviewer"] = "reviewer"
        template["runs"][0]["output_qualified"] = True
        template["runs"][0]["findings"][0].update(verdict="fp", rationale="Not actionable", evidence_refs=["src/store.py:10"])
        scored = E.score([run()], oracle, template)["runs"][0]
        self.assertIsNone(scored["recall"])
        self.assertEqual(scored["known_issue_recall"], 0.0)

    def test_missing_usage_is_unknown_not_zero_and_repeats_not_independent(self):
        runs = [run(usage={}, cost_usd=None), run("r2", repeat=2)]
        summary = E.score(runs, ORACLE, adjudicate(runs))["summary"]
        self.assertEqual(summary["independent_tasks"], 1)
        self.assertEqual(summary["attempted_runs"], 2)
        self.assertEqual(summary["cost_missing_runs"], 1)
        self.assertEqual(summary["input_tokens_known_sum"], 100)
        self.assertEqual(summary["usage_incomplete_runs"], 1)

    def test_confirmed_root_cause_can_have_incomplete_submitted_evidence(self):
        judgments = adjudicate([run()])
        judgments["runs"][0]["findings"][0]["submitted_evidence_complete"] = False
        result = E.score([run()], ORACLE, judgments)["runs"][0]
        self.assertEqual(result["tp"], 1)
        self.assertEqual(result["evidence_complete_tp"], 0)
        self.assertEqual(result["evidence_completeness"], 0.0)

    def test_non_boolean_output_qualification_is_rejected(self):
        judgments = adjudicate([run()])
        judgments["runs"][0]["output_qualified"] = 1
        with self.assertRaisesRegex(ValueError, "boolean"):
            E.score([run()], ORACLE, judgments)

    def test_novel_issue_is_separate_credit_without_changing_frozen_recall(self):
        judgments = adjudicate([run()])
        finding = judgments["runs"][0]["findings"][0]
        finding.update(verdict="novel_tp", issue_id=None,
                       novel_issue={"root_cause": "other defective branch", "trigger": "valid input",
                                    "paths": ["src/store.py"], "severity": "P2"})
        result = E.score([run()], ORACLE, judgments)["runs"][0]
        self.assertEqual(result["tp"], 0)
        self.assertEqual(result["novel_tp"], 1)
        self.assertEqual(result["fp"], 0)
        self.assertEqual(result["quality_fn"], 1)
        self.assertEqual(result["known_issue_recall"], 0.0)
        self.assertEqual(result["precision"], 1.0)

    def test_unstarted_assignments_are_retained_but_not_attempts_or_zero_cost(self):
        runs = [run(), run("r2", status="not_started", findings=[], usage={"input_tokens": 0, "output_tokens": 0},
                           cost_usd=0, timing={"end_to_end_seconds": 0})]
        scored = E.score(runs, ORACLE, adjudicate(runs))
        summary = scored["summary"]
        self.assertEqual(summary["assigned_runs"], 2)
        self.assertEqual(summary["actually_started_runs"], 1)
        self.assertEqual(summary["attempted_runs"], 1)
        self.assertEqual(summary["not_started_runs"], 1)
        self.assertEqual(summary["delivery_rate_all_attempts"], 1.0)
        self.assertEqual(summary["delivery_rate_all_assignments"], 0.5)
        self.assertEqual(summary["cost_usd_median"], 0.01)
        self.assertEqual(summary["cost_missing_runs"], 0)
        self.assertFalse(scored["runs"][1]["actually_started"])
        self.assertFalse(scored["runs"][1]["quality_eligible"])
        self.assertIsNone(scored["runs"][1]["resources"]["cost_usd"])

    def test_offpeak_actual_estimate_is_separate_from_peak_budget_reserve(self):
        data = run(cost_usd=None, estimated_offpeak_cost_usd=0.003, estimated_peak_cost_usd=0.009)
        result = E.score([data], ORACLE, adjudicate([data]))["runs"][0]["resources"]
        self.assertEqual(result["cost_usd"], 0.003)
        self.assertEqual(result["offpeak_estimated_cost_usd"], 0.003)
        self.assertEqual(result["peak_budget_estimate_usd"], 0.009)
        self.assertTrue(result["cost_is_estimate"])


if __name__ == "__main__":
    unittest.main()
