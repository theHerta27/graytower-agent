"""Offline boundary tests; rejected inputs must never reach the game simulator."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import frozen_candidate_probe as probe
except ModuleNotFoundError:
    probe = None


class FrozenCandidateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(probe, "frozen-candidate boundary is not implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.artifacts = self.folder / "artifacts"
        self.request = probe.author_freeze(probe.TRUSTED_GAME_ROOT, self.artifacts)

    def assert_rejected_before_simulation(self, request, expected):
        with patch("combat_core.v2.simulation.simulate", side_effect=AssertionError("must not simulate")) as simulate:
            with self.assertRaisesRegex(ValueError, expected):
                probe.verify_frozen(probe.TRUSTED_GAME_ROOT, self.artifacts, request, self.folder / "result")
            simulate.assert_not_called()
        self.assertFalse((self.folder / "result").exists())

    def test_author_materializes_complete_candidate_and_verifier_never_authors(self):
        with patch("verification_agent.v2.policy.apply_changes", side_effect=AssertionError("Verifier cannot author")):
            checked = probe.inspect_frozen(probe.TRUSTED_GAME_ROOT, self.artifacts, self.request)
        self.assertEqual(checked["baseline"].skills["breaker_skill"].multiplier, 1.4)
        self.assertEqual(checked["candidate"].skills["breaker_skill"].multiplier, 1.7)
        self.assertTrue(checked["validation"]["passed"])
        self.assertEqual(checked["validation"]["diff"], [dict(path="skills.breaker_skill.multiplier", before=1.4, after=1.7)])
        self.assertNotIn("changes", self.request)

    def test_hash_tamper_rejected_before_simulation(self):
        ref = self.request["candidate"]
        path = self.artifacts / (ref["artifact_id"] + ".json")
        path.write_bytes(path.read_bytes() + b" ")
        self.assert_rejected_before_simulation(self.request, "artifact hash mismatch")

    def test_reference_escape_rejected_before_simulation(self):
        request = copy.deepcopy(self.request)
        request["candidate"]["artifact_id"] = "../outside"
        self.assert_rejected_before_simulation(request, "artifact_id")

    def test_wrong_declared_schema_rejected_before_simulation(self):
        request = copy.deepcopy(self.request)
        request["candidate"]["schema"] = "code-snapshot-v1"
        self.assert_rejected_before_simulation(request, "artifact schema")

    def test_wrong_payload_schema_with_valid_hash_rejected_before_simulation(self):
        raw = b'{"not_a_combat_bundle":true}'
        digest = hashlib.sha256(raw).hexdigest()
        (self.artifacts / (digest + ".json")).write_bytes(raw)
        request = copy.deepcopy(self.request)
        request["candidate"].update(artifact_id=digest, sha256=digest)
        self.assert_rejected_before_simulation(request, "candidate schema")

    def test_changes_and_source_drift_are_rejected_before_simulation(self):
        request = copy.deepcopy(self.request)
        request["changes"] = [{"path": "skills.breaker_skill.multiplier", "value": 2.0}]
        self.assert_rejected_before_simulation(request, "request fields")
        request = copy.deepcopy(self.request)
        request["game_fingerprint"] = "0" * 64
        self.assert_rejected_before_simulation(request, "game fingerprint")


if __name__ == "__main__":
    unittest.main()
