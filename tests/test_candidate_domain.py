"""Product boundary tests. No models; only the opt-in test runs four real battles."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def raw(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


class CandidateDomainTests(unittest.TestCase):
    def setUp(self):
        from agent_workbench.domain import CandidateRepository
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = CandidateRepository(Path(self.temp.name))

    def create(self):
        return self.repo.create("击破手战技倍率由1.4调整到1.7，观察表现，不承诺收益。",
                                [{"path": "skills.breaker_skill.multiplier", "value": 1.7}])

    def put_fixture(self, value, schema):
        """Adversarial fixture: correctly rehashed content does not confer authorship."""
        encoded = raw(value)
        digest = hashlib.sha256(encoded).hexdigest()
        (Path(self.temp.name) / "artifacts" / (digest + ".json")).write_bytes(encoded)
        return {"artifact_id": digest, "sha256": digest, "schema": schema}

    def test_author_freezes_full_inputs_and_true_schema_without_parent_game_imports(self):
        description = self.repo.describe()
        field = description["catalog"][0]
        self.assertEqual(field["path"], "skills.breaker_skill.multiplier")
        self.assertEqual(field["value"], 1.4)
        self.assertIn("CombatBundle", description["schema"]["title"])
        frozen = self.create()
        self.assertTrue(frozen["validation"]["passed"])
        self.assertEqual(frozen["diff"], [{"path": field["path"], "before": 1.4, "after": 1.7}])
        manifest = frozen["manifest"]
        self.assertEqual(self.repo.read_artifact(manifest["candidate"]["sha256"])["skills"]["breaker_skill"]["multiplier"], 1.7)
        self.assertEqual(self.repo.get(frozen["manifest_hash"]), frozen)
        self.assertFalse(any(name.startswith("combat_core") for name in sys.modules))

    def test_author_rejects_types_ranges_extra_fields_and_unsupported_authors(self):
        for value in (True, "1.7", float("nan"), 1.71, -1, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.repo.create("change", [{"path": "skills.breaker_skill.multiplier", "value": value}])
        for changes in ([], [{"path": "boss_stats.atk", "value": 190}],
                        [{"path": "skills.breaker_skill.multiplier", "value": 1.7, "extra": 1}]):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.repo.create("change", changes)
        with self.assertRaises(ValueError):
            self.repo.create("change", [{"path": "skills.breaker_skill.multiplier", "value": 1.7}], author="verification")

    def test_content_tamper_and_path_refs_are_rejected_before_execution(self):
        frozen = self.create()
        ref = frozen["manifest"]["candidate"]
        path = Path(self.temp.name) / "artifacts" / (ref["sha256"] + ".json")
        path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash"):
            self.repo.verify(frozen["manifest_hash"], [7], ["balanced"])
        for ref in ("../candidate", "0" * 64, True):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.repo.read_artifact(ref)

    def test_rehashed_extra_edit_wrong_reference_and_source_drift_are_rejected(self):
        frozen = self.create()
        for mutation in ("extra_edit", "reference", "source"):
            manifest = deepcopy(frozen["manifest"])
            if mutation == "source":
                snapshot = self.repo.read_artifact(manifest["sources"]["sha256"])
                snapshot["fingerprint"] = "0" * 64
                manifest["sources"] = self.put_fixture(snapshot, manifest["sources"]["schema"])
            else:
                candidate = self.repo.read_artifact(manifest["candidate"]["sha256"])
                if mutation == "extra_edit":
                    candidate["boss_stats"]["atk"] += 1
                else:
                    candidate["characters"][candidate["party"][0]]["skill_slots"]["skill"] = "missing_skill"
                manifest["candidate"] = self.put_fixture(candidate, manifest["candidate"]["schema"])
            ref = self.put_fixture(manifest, "candidate-manifest-v1")
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.repo.verify(ref["sha256"], [7], ["balanced"])

    def test_execution_identity_rejects_duplicate_foreign_and_boolean_samples(self):
        frozen = self.create()
        for seeds, policies in (([7, 7], ["balanced"]), ([True], ["balanced"]),
                                ([-1], ["balanced"]), ([7], ["unknown"]),
                                ([7], ["balanced", "balanced"]), ([], ["balanced"])):
            with self.subTest(seeds=seeds, policies=policies), self.assertRaises(ValueError):
                self.repo.verify(frozen["manifest_hash"], seeds, policies)

    def test_same_author_input_reuses_hash_and_revision_preserves_parent_identity(self):
        original = self.create()
        self.assertEqual(self.create()["manifest_hash"], original["manifest_hash"])
        revision = self.repo.create("保留同一基线，修订建议到1.6", [{"path": "skills.breaker_skill.multiplier", "value": 1.6}],
                                    parent_manifest=original["manifest_hash"])
        self.assertNotEqual(original["manifest_hash"], revision["manifest_hash"])
        self.assertEqual(revision["manifest"]["parent_manifest"], original["manifest_hash"])
        self.assertEqual(revision["manifest"]["baseline"], original["manifest"]["baseline"])
        self.assertEqual(self.repo.get(original["manifest_hash"]), original)

    def test_fixture_metrics_exclude_non_joint_wins_and_keep_all_transitions(self):
        """Synthetic report fixture, not a game or Agent effectiveness test."""
        from agent_workbench.domain.worker import metrics
        rows = [{"seed": 1, "policy": "balanced", "baseline": {"outcome": "win", "elapsed_av": "100"}, "candidate": {"outcome": "win", "elapsed_av": "90"}},
                {"seed": 2, "policy": "balanced", "baseline": {"outcome": "win", "elapsed_av": "200"}, "candidate": {"outcome": "loss", "elapsed_av": "300"}},
                {"seed": 3, "policy": "balanced", "baseline": {"outcome": "timeout", "elapsed_av": "1000"}, "candidate": {"outcome": "win", "elapsed_av": "400"}},
                {"seed": 4, "policy": "balanced", "baseline": {"outcome": "loss", "elapsed_av": "500"}, "candidate": {"outcome": "timeout", "elapsed_av": "1000"}}]
        group = metrics(rows, ["balanced"])["balanced"]
        self.assertEqual(group["common_wins"], 1)
        self.assertEqual(group["paired_av_ratio_median"], 0.9)
        self.assertEqual(group["paired_av_deltas"], [{"seed": 1, "delta_av": "-10"}])
        self.assertEqual(group["baseline"], {"wins": 2, "losses": 1, "timeouts": 1, "win_rate": 0.5})
        self.assertEqual(group["candidate"], {"wins": 2, "losses": 1, "timeouts": 1, "win_rate": 0.5})
        self.assertEqual(group["transitions"], {"win->win": 1, "win->loss": 1, "timeout->win": 1, "loss->timeout": 1})

    @unittest.skipUnless(os.environ.get("RUN_REAL_CANDIDATE_BATTLES") == "1", "opt-in four real battles")
    def test_real_four_battles_keep_full_traces_and_descriptive_pairing(self):
        frozen = self.create()
        before = {p.name: p.read_bytes() for p in (Path(self.temp.name) / "artifacts").glob("*.json")}
        result = self.repo.verify(frozen["manifest_hash"], [7, 11], ["balanced"])
        self.assertEqual(result["identity"]["manifest_hash"], frozen["manifest_hash"])
        self.assertEqual(result["completed_battles"], 4)
        self.assertEqual(result["overall_verdict"], "INCONCLUSIVE")
        self.assertEqual(result["structural_verdict"], "PASS")
        self.assertEqual(result["behavioral_verdict"], "DESCRIPTIVE")
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(len(result["trace_refs"]), 4)
        metrics = result["metrics"]["balanced"]
        self.assertEqual(sum(metrics["transitions"].values()), 2)
        for ref in result["trace_refs"]:
            trace = self.repo.read_artifact(ref["sha256"])
            self.assertTrue(trace["events"])
            self.assertIn("initial_state", trace)
            self.assertIn("final_state", trace["result"])
        for name, contents in before.items():
            self.assertEqual((Path(self.temp.name) / "artifacts" / name).read_bytes(), contents)


if __name__ == "__main__":
    unittest.main()
