import json
from pathlib import Path
import tempfile
import unittest

import collaboration_batch as batch


class BatchEvidenceTests(unittest.TestCase):
    def test_missing_terminal_usage_is_not_free_request(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "wire.json").write_text(json.dumps({"requests": [{"request_id": 1, "status": 200}]}), encoding="utf-8")
            raw = {"pass": False, "usage": {"input_tokens": 0, "output_tokens": 0}, "cache_hit_tokens": 0, "request_count": 1}
            result = batch.normalize({"run_id": "x", "task_id": "x", "mode": "single", "repeat": 1}, raw, directory)
            self.assertIsNone(result["cost_usd"])
            self.assertFalse(result["usage_complete"])

    def test_native_initial_idle_is_not_completion(self):
        events = [{"method": "thread/status/changed", "offset_seconds": t,
                   "params": {"threadId": "c1", "status": {"type": state}}}
                  for t, state in [(0, "idle"), (1, "active"), (4, "idle")]]
        result = batch.native_audit({"native_child_ids": ["c1"]}, events, Path("evidence"))
        self.assertEqual(result["children"], [{"agent_id": "c1", "start": 1, "end": 4}])

    def test_missing_child_boundaries_remain_unknown(self):
        result = batch.native_audit({"native_child_ids": ["c1"]}, [], Path("evidence"))
        self.assertEqual(result["children"], [{"agent_id": "c1"}])
        self.assertFalse(result["verified"])

    def test_corrupted_events_preserve_completed_usage_and_record_audit_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "events.json").write_text("{truncated", encoding="utf-8")
            (directory / "wire.json").write_text(json.dumps({"requests": [{"usage": {"input_tokens": 100, "output_tokens": 20}}]}), encoding="utf-8")
            raw = {"pass": True, "usage": {"input_tokens": 100, "output_tokens": 20}, "cache_hit_tokens": 0,
                   "request_count": 1, "final_json": {"findings": []}}
            result = batch.normalize({"run_id": "x", "task_id": "x", "mode": "single", "repeat": 1}, raw, directory)
            self.assertEqual(result["status"], "audit_failure")
            self.assertEqual(result["usage"]["input_tokens"], 100)
            self.assertGreater(result["cost_usd"], 0)
            self.assertTrue(result["audit_errors"])

    def test_multiple_child_activations_are_not_silently_dropped(self):
        events = [{"method": "thread/status/changed", "offset_seconds": t,
                   "params": {"threadId": "c1", "status": {"type": state}}}
                  for t, state in [(1, "active"), (2, "idle"), (4, "active"), (5, "idle")]]
        result = batch.native_audit({"native_child_ids": ["c1"], "all_requests_have_full_packet": True,
                                    "config": {"specialists": 1}}, events, Path("evidence"))
        child = result["children"][0]
        self.assertEqual(child["activity_spans"], [{"start": 1, "end": 2}, {"start": 4, "end": 5}])
        self.assertNotIn("start", child)
        self.assertFalse(result["verified"])

    def test_incomplete_output_is_resource_truncation_not_protocol_incompatibility(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "wire.json").write_text(json.dumps({"requests": [{"usage": {"input_tokens": 100, "output_tokens": 4000},
                "provider_events": [{"type": "response.incomplete", "response": {"incomplete_details": {"reason": "max_output_tokens"}}}]}]}), encoding="utf-8")
            raw = {"pass": False, "usage": {"input_tokens": 100, "output_tokens": 4000}, "cache_hit_tokens": 0, "request_count": 1}
            result = batch.normalize({"run_id": "x", "task_id": "x", "mode": "single", "repeat": 1}, raw, directory)
            self.assertEqual(result["status"], "resource_truncated")
            self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
