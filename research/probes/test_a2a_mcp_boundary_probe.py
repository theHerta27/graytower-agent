"""Research boundary tests: real sqlite, HTTP and stdio; no model API."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("a2a_mcp_boundary_probe.py")


def module():
    spec = importlib.util.spec_from_file_location("boundary_probe", SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


class LedgerTests(unittest.TestCase):
    def test_completed_request_reuses_receipt_after_new_ledger_instance(self):
        p = module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"
            ledger = p.BusinessLedger(path)
            self.assertEqual(ledger.claim("coding", "request-1", "hash-a")["state"], "new")
            ledger.complete("coding", "request-1", {"verdict": "FAIL", "evidence_hash": "abc"})
            replay = p.BusinessLedger(path).claim("coding", "request-1", "hash-a")
            self.assertEqual(replay["state"], "completed")
            self.assertEqual(replay["report"]["verdict"], "FAIL")
            self.assertEqual(ledger.reservations(), 1)

    def test_payload_conflict_does_not_create_second_reservation(self):
        p = module()
        with tempfile.TemporaryDirectory() as directory:
            ledger = p.BusinessLedger(Path(directory) / "ledger.sqlite")
            ledger.claim("coding", "request-1", "hash-a")
            with self.assertRaises(p.PayloadConflict):
                ledger.claim("coding", "request-1", "hash-b")
            self.assertEqual(ledger.reservations(), 1)

    def test_running_request_and_other_owner_do_not_reuse_a_receipt(self):
        p = module()
        with tempfile.TemporaryDirectory() as directory:
            ledger = p.BusinessLedger(Path(directory) / "ledger.sqlite")
            ledger.claim("coding", "request-1", "hash-a")
            self.assertEqual(ledger.claim("coding", "request-1", "hash-a")["state"], "running")
            self.assertEqual(ledger.claim("config", "request-1", "hash-a")["state"], "new")
            self.assertEqual(ledger.reservations(), 2)


class ProtocolBoundaryTests(unittest.TestCase):
    def test_real_protocol_boundaries_keep_domain_result_and_identity(self):
        # Preserve both failing and passing integration evidence; never overwrite.
        directory = Path(tempfile.mkdtemp(prefix="a2a-mcp-test-20261005-", dir=SCRIPT.parents[1] / "evidence"))
        run = subprocess.run(
            [sys.executable, str(SCRIPT), "--out", str(directory)],
            capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        (directory / "stdout.txt").write_text(run.stdout, encoding="utf-8")
        (directory / "stderr.txt").write_text(run.stderr, encoding="utf-8")
        print("protocol evidence: " + str(directory))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        self.assertTrue(result["passed"])
        self.assertFalse(result["production_ready"])
        self.assertEqual(result["model_api_calls"], 0)
        self.assertEqual(result["verdicts"], ["PASS", "FAIL", "INCONCLUSIVE"])
        self.assertEqual(result["duplicate_validation_delta"], 0)
        self.assertEqual(result["duplicate_reservation_delta"], 0)
        self.assertTrue(result["sqlite_reopened_task"])
        self.assertEqual(result["candidate_mutations"], [])
        self.assertTrue(result["cross_owner_get_rejected"])


if __name__ == "__main__":
    unittest.main()
