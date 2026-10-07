"""Offline guard and real-Runtime fixture tests. No credentials or live calls."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
import collaboration_live_runner as runner


class Guards(unittest.TestCase):
    def test_budget_atomic_reservation(self):
        b = runner.Budget(runner.RunConfig(fixture=True, max_model_calls=3, max_output_tokens=5, per_request_output_tokens=2))
        accepted = []
        def reserve():
            try:
                accepted.append(b.reserve())
            except ValueError:
                pass
        workers = [threading.Thread(target=reserve) for _ in range(10)]
        for w in workers: w.start()
        for w in workers: w.join()
        self.assertEqual(sorted(accepted), [(1, 2), (2, 2), (3, 1)])

    def test_budget_settles_known_usage_only(self):
        b = runner.Budget(runner.RunConfig(fixture=True, max_model_calls=5, max_output_tokens=6, per_request_output_tokens=4))
        self.assertEqual(b.reserve(), (1, 4))
        b.settle(1, {"output_tokens": 1})
        self.assertEqual(b.reserve(), (2, 4))
        b.settle(2, {})
        self.assertEqual(b.output_reserved, 5)
        with self.assertRaises(ValueError): b.settle(1, {"output_tokens": 1})

    def test_mapping_preserves_schema_ids_and_no_shell(self):
        schema = {"type": "object", "properties": {"message": {"type": "string"}}}
        body = {"model": runner.MODEL, "instructions": "immutable packet", "input": [{"type": "function_call", "name": "spawn_agent", "namespace": "multi_agent_v1", "arguments": "{}", "call_id": "call1", "id": "fc1"}],
                "tools": [{"type": "namespace", "name": "multi_agent_v1", "tools": [{"type": "function", "name": "spawn_agent", "parameters": schema}]}, {"type": "function", "name": "shell"}]}
        mapped = runner.bounded_request(body, "team_serial", "immutable packet")
        self.assertEqual(mapped["tools"], [{"type": "function", "name": "ma1__spawn_agent", "parameters": schema}])
        self.assertEqual(mapped["input"][0]["call_id"], "call1")
        self.assertNotIn("namespace", mapped["input"][0])
        self.assertIn("namespace", body["input"][0])
        with self.assertRaises(ValueError): runner.bounded_request(body, "team_serial", "absent packet")

    def test_collision_rejected(self):
        body = {"tools": [{"type": "namespace", "name": "multi_agent_v1", "tools": [{"type": "function", "name": "spawn_agent"}]}, {"type": "function", "name": "ma1__spawn_agent"}]}
        with self.assertRaises(ValueError): runner.protocol.provider_request(body)

    def test_sse_split_args_name_and_terminal_validation(self):
        item = runner.protocol.function("spawn_agent", {"message": "scope", "fork_context": False}, "call1")
        events = [{"type": "response.output_item.added", "output_index": 0, "item": {**item, "arguments": ""}},
                  {"type": "response.function_call_arguments.delta", "item_id": item["id"], "output_index": 0, "delta": item["arguments"][:3]},
                  {"type": "response.function_call_arguments.delta", "item_id": item["id"], "output_index": 0, "delta": item["arguments"][3:]},
                  {"type": "response.output_item.done", "output_index": 0, "item": item},
                  {"type": "response.completed", "response": {"output": [item]}}]
        raw = "".join("event: " + e["type"] + "\r\ndata: " + json.dumps(e) + "\r\n\r\n" for e in events).encode()
        mapped, final = runner.checked_events(runner.parse_sse(raw), {"ma1__spawn_agent"})
        self.assertEqual(mapped[0]["item"]["namespace"], "multi_agent_v1")
        self.assertEqual(mapped[1]["delta"], events[1]["delta"])
        self.assertEqual(final["output"][0], item)
        with self.assertRaises(ValueError): runner.checked_events(events, set())
        bad = json.loads(json.dumps(events))
        bad[-1]["response"]["output"][0]["arguments"] = '{"message":"other"}'
        with self.assertRaises(ValueError): runner.checked_events(bad, {"ma1__spawn_agent"})
        with self.assertRaises(ValueError): runner.checked_events(events[:-1], {"ma1__spawn_agent"})
        bad = json.loads(json.dumps(events))
        bad[1]["delta"] = "bad"
        with self.assertRaises(ValueError): runner.checked_events(bad, {"ma1__spawn_agent"})

    def test_unknown_tools_and_overrides_rejected(self):
        for name, args in [("exec_command", {}), ("spawn_agent", {"message": "x", "model": "other"}), ("spawn_agent", {"message": "x", "fork_context": True}), ("wait_agent", {"targets": ["child"], "timeout_ms": 3600001})]:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                runner.validate_arguments(runner.protocol.function(name, args, "bad"))

    def test_wait_timeout_matches_native_schema_independent_of_run_deadline(self):
        for timeout in (10000, 120000, 600000, 3600000):
            with self.subTest(timeout=timeout):
                runner.validate_arguments(runner.protocol.function("wait_agent", {"targets": ["child"], "timeout_ms": timeout}, "native_wait"))
        for timeout in (9999, 3600001, True, 10000.5):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                runner.validate_arguments(runner.protocol.function("wait_agent", {"targets": ["child"], "timeout_ms": timeout}, "bad_wait"))

    def test_schedule_prompts_share_roles_and_packet(self):
        config = runner.RunConfig(fixture=True)
        serial = runner.task_prompt("team_serial", config).split("SCHEDULING:")[0]
        parallel = runner.task_prompt("team_parallel", config).split("SCHEDULING:")[0]
        self.assertEqual(serial, parallel)
        for role in runner.ROLES: self.assertIn(role, serial)

    def test_optional_single_plus_stage_prompts_preserve_default(self):
        default = runner.RunConfig(fixture=True)
        prompts = runner.turn_prompts("single_plus", default)
        self.assertEqual(len(prompts), 3)
        self.assertEqual(prompts[1], prompts[2])
        fixed = runner.RunConfig(fixture=True, single_plus_turns=6,
                                single_plus_followup_prompts=("rules", "contracts", "counterexamples", "evidence", "final"))
        self.assertEqual(runner.turn_prompts("single_plus", fixed)[1:], list(fixed.single_plus_followup_prompts))
        self.assertEqual(runner.turn_prompts("single", fixed), [runner.task_prompt("single", fixed)])
        with self.assertRaises(ValueError):
            runner.RunConfig(fixture=True, single_plus_turns=6, single_plus_followup_prompts=("too short",))

    def test_shared_dollar_budget_rejects_before_upstream(self):
        # A real shared ledger must refuse a reservation that crosses its cap.
        with tempfile.TemporaryDirectory() as tmp:
            ledger = runner.SharedLedger(Path(tmp) / "ledger.json", max_usd=0.001, max_calls=2, max_output_tokens=100)
            with self.assertRaises(ValueError): ledger.reserve(10000, 100)
            token = ledger.reserve(100, 10)
            ledger.settle(token, {"input_tokens": 50, "output_tokens": 5, "input_tokens_details": {"cached_tokens": 20}})
            state = json.loads((Path(tmp) / "ledger.json").read_text())
            self.assertEqual(state["calls_reserved"], 1)
            self.assertLess(state["usd_reserved_or_actual"], 0.001)


if __name__ == "__main__":
    unittest.main(verbosity=2)
