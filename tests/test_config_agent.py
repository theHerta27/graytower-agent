"""Config fixture-model tests and offline real LangChain provider integration.

No live model call or battle simulation is performed by this suite.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class FakeModel:
    """Explicit decision fixture, never evidence of real model quality."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.inputs = []

    def complete(self, messages, schema):
        self.inputs.append(deepcopy(messages))
        if not self.answers:
            raise AssertionError("unexpected additional model call")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return deepcopy(answer)


def decision(value=1.7, **overrides):
    answer = {"status": "candidate", "message": "提高击破手战技倍率。",
              "changes": [{"path": "skills.breaker_skill.multiplier", "value": value}]}
    answer.update(overrides)
    return answer


class ConfigAgentTests(unittest.TestCase):
    def setUp(self):
        from agent_workbench.domain import CandidateRepository
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = CandidateRepository(Path(self.temp.name))
        # Any accidental simulation during authoring is a contract failure.
        self.repo.verify = lambda *a, **kw: self.fail("Config must not run verification")

    def agent(self, *answers, **kwargs):
        from agent_workbench.config import ConfigAgent
        self.model = FakeModel(*answers)
        return ConfigAgent(self.repo, self.model, **kwargs)

    def test_clear_request_freezes_real_candidate_and_waits_for_confirmation(self):
        result = self.agent(decision()).draft("将击破手战技倍率由1.4改成1.7。")
        self.assertEqual(result["status"], "candidate")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["candidate"]["diff"], [
            {"path": "skills.breaker_skill.multiplier", "before": 1.4, "after": 1.7}])
        self.assertEqual(self.repo.get(result["candidate"]["manifest_hash"]), result["candidate"])
        self.assertEqual(len(self.model.inputs), 1)
        context = json.loads(self.model.inputs[0][1]["content"])
        self.assertEqual(context["repository"]["schema"]["title"], "CombatBundle")
        self.assertTrue(context["repository"]["rules"])

    def test_ambiguous_request_returns_question_without_creating_candidate(self):
        result = self.agent(decision(status="needs_input", changes=[], message="请指定目标倍率。"))\
            .draft("让击破手强一点。")
        self.assertEqual(result["status"], "needs_input")
        self.assertNotIn("candidate", result)
        self.assertFalse(any((Path(self.temp.name) / "artifacts").glob("*.json")))

    def test_out_of_range_is_rejected_by_real_precheck(self):
        result = self.agent(decision(8), max_repairs=0).draft("把倍率改成8。")
        self.assertEqual(result["status"], "rejected")
        self.assertNotIn("candidate", result)
        self.assertTrue(result["validation_errors"])
        self.assertEqual(len(self.model.inputs), 1)

    def test_validation_feedback_allows_only_one_bounded_repair(self):
        result = self.agent(decision(8), decision(1.6)).draft("将倍率调整为1.6。")
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["candidate"]["diff"][0]["after"], 1.6)
        self.assertEqual(result["attempts"], 2)
        feedback = json.loads(self.model.inputs[1][-1]["content"])
        self.assertIn("validation_error", feedback)
        self.assertEqual(feedback["previous_decision"]["changes"][0]["value"], 8)

    def test_repeated_invalid_edits_cannot_loop_or_simulate(self):
        result = self.agent(decision(8), decision(9), decision(1.6)).draft("倍率1.6。")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(len(self.model.answers), 1)

    def test_provider_failure_is_not_retried_or_exposed(self):
        result = self.agent(RuntimeError("Authorization: Bearer sk-secret-fixture"), decision()).draft("倍率1.7。")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(len(self.model.inputs), 1)
        self.assertNotIn("sk-secret", json.dumps(result))

    def test_preview_has_full_context_and_schema_without_model_call(self):
        agent = self.agent()
        preview = agent.preview("倍率1.7。")
        self.assertTrue(preview["schema"]["properties"]["changes"])
        self.assertEqual(json.loads(preview["messages"][1]["content"])["request"], "倍率1.7。")
        self.assertEqual(len(self.model.inputs), 0)

    def test_revision_keeps_parent_link_and_original_candidate_immutable(self):
        original = self.agent(decision(1.6)).draft("倍率1.6。")["candidate"]
        result = self.agent(decision(1.7)).draft("把上次的倍率再改为1.7。", original["manifest_hash"])
        self.assertEqual(result["candidate"]["manifest"]["parent_manifest"], original["manifest_hash"])
        self.assertEqual(self.repo.get(original["manifest_hash"]), original)
        context = json.loads(self.model.inputs[0][1]["content"])
        self.assertEqual(context["parent_candidate"]["diff"][0]["after"], 1.6)

    def test_missing_request_or_unknown_parent_stops_before_model(self):
        agent = self.agent()
        for request, parent in (("", None), ("倍率1.7。", "0" * 64)):
            with self.subTest(request=request):
                result = agent.draft(request, parent)
                self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.model.inputs, [])

    def test_wrong_structured_type_can_be_repaired_without_coercing_a_string(self):
        result = self.agent(decision("1.7"), decision(1.7)).draft("倍率1.7。")
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(len([row for row in result["trace"] if row["node"] == "precheck"]), 1)

    def test_config_graph_does_not_inherit_external_tracing(self):
        from langsmith import tracing_context
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true", "LANGCHAIN_TRACING_V2": "true"}), \
                tracing_context(enabled=True), \
                patch("langchain_core.tracers.langchain.LangChainTracer.__init__",
                      side_effect=RuntimeError("fixture blocks external tracer initialization")) as external:
            result = self.agent(decision()).draft("倍率1.7。")
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(external.call_count, 0, "Config graph must not create external tracing callbacks")


class GatewayAnswer(BaseModel):
    message: str


class ModelGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.audit_path = Path(self.temp.name) / "calls.jsonl"
        self.requests = []

    def gateway(self, handler=None, **kwargs):
        from agent_workbench.models import ModelGateway

        def successful_response(request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, json={
                "id": "offline-fixture-1", "model": "deepseek-flash", "object": "chat.completion",
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": "", "tool_calls": [{"id": "fixture-call", "type": "function",
                        "function": {"name": "GatewayAnswer", "arguments": '{"message":"fixture response"}'}}]}}],
                "usage": {"prompt_tokens": 24, "completion_tokens": 8, "total_tokens": 32}})

        client = httpx.Client(transport=httpx.MockTransport(handler or successful_response))
        self.addCleanup(client.close)
        return ModelGateway(api_key="sk-explicit-offline-fixture", audit_path=self.audit_path,
                            http_client=client, **kwargs)

    def test_real_langchain_path_matches_complete_reviewable_preview_and_saves_usage(self):
        gateway = self.gateway(max_calls=1)
        messages = [{"role": "user", "content": "offline fixture only"}]
        preview = gateway.preview(messages, GatewayAnswer)
        self.assertEqual(gateway.complete(messages, GatewayAnswer), {"message": "fixture response"})
        self.assertEqual(self.requests[0], preview["payload"])
        self.assertEqual(self.requests[0]["thinking"], {"type": "disabled"})
        self.assertEqual(self.requests[0]["model"], "deepseek-flash")
        self.assertEqual(gateway.calls[-1]["usage"]["total_tokens"], 32)
        self.assertGreaterEqual(gateway.calls[-1]["elapsed_seconds"], 0)
        audit = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn("sk-explicit", audit)
        self.assertIn('"status": "reserved"', audit)
        self.assertIn('"status": "completed"', audit)
        # Existing reservations must survive gateway/process reconstruction.
        with self.assertRaisesRegex(RuntimeError, "call limit"):
            self.gateway(max_calls=1).complete(messages, GatewayAnswer)

    def test_provider_failure_is_recorded_once_without_secret_or_silent_retry(self):
        def failure(request):
            self.requests.append(request)
            return httpx.Response(401, json={"error": {"message": "Bearer sk-explicit-offline-fixture"}})
        gateway = self.gateway(handler=failure, max_calls=2)
        with self.assertRaisesRegex(RuntimeError, "provider"):
            gateway.complete([{"role": "user", "content": "fixture"}], GatewayAnswer)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(gateway.calls[-1]["status"], "failed")
        self.assertIsNone(gateway.calls[-1]["usage"])
        self.assertNotIn("sk-explicit", self.audit_path.read_text(encoding="utf-8"))

    def test_total_input_limit_stops_before_reservation_or_network(self):
        gateway = self.gateway(max_input_chars=40)
        with self.assertRaisesRegex(ValueError, "input"):
            gateway.complete([{"role": "user", "content": "x" * 50}], GatewayAnswer)
        self.assertFalse(self.audit_path.exists())
        self.assertEqual(self.requests, [])

    def test_unknown_reserved_call_counts_toward_restart_cap(self):
        self.audit_path.write_text(json.dumps({"call_id": "previous", "status": "reserved"}) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "call limit"):
            self.gateway(max_calls=1).complete([{"role": "user", "content": "fixture"}], GatewayAnswer)
        self.assertEqual(self.requests, [])

    def test_remaining_calls_reads_persistent_reservations_without_writing(self):
        gateway = self.gateway(max_calls=3)
        self.assertTrue(callable(getattr(gateway, 'remaining_calls', None)), 'gateway must expose its durable remaining budget')
        self.assertEqual(gateway.remaining_calls(), 3)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [], 'a budget read must not create ledger or lock files')
        gateway.complete([{'role': 'user', 'content': 'offline fixture'}], GatewayAnswer)
        with self.audit_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'call_id': 'unknown-after-exit', 'status': 'reserved'}) + '\n')
        original = self.audit_path.read_bytes()
        self.assertEqual(self.gateway(max_calls=3).remaining_calls(), 1)
        self.assertEqual(self.gateway(max_calls=2).remaining_calls(), 0)
        self.assertEqual(self.audit_path.read_bytes(), original)
        self.assertEqual(len(self.requests), 1, 'budget reads must not contact the provider')

    def test_invalid_ledger_cannot_authorize_a_new_call(self):
        invalid = [
            '{broken json\n',
            json.dumps({'call_id': 'bad', 'status': 'unknown'}) + '\n',
            json.dumps({'call_id': 'orphan', 'status': 'completed'}) + '\n',
            json.dumps({'status': 'reserved'}) + '\n',
            json.dumps({'call_id': '', 'status': 'reserved'}) + '\n',
            json.dumps({'call_id': 'duplicate', 'status': 'reserved'}) + '\n'
            + json.dumps({'call_id': 'duplicate', 'status': 'reserved'}) + '\n',
        ]
        for raw in invalid:
            with self.subTest(raw=raw):
                self.audit_path.write_text(raw, encoding='utf-8')
                gateway = self.gateway(max_calls=8)
                with self.assertRaisesRegex(RuntimeError, 'ledger'):
                    gateway.remaining_calls()
                with self.assertRaisesRegex(RuntimeError, 'ledger'):
                    gateway.complete([{'role': 'user', 'content': 'offline fixture'}], GatewayAnswer)
                self.assertEqual(self.audit_path.read_text(encoding='utf-8'), raw)
        self.assertEqual(self.requests, [])

    def test_invalid_structured_response_keeps_usage_and_redacts_raw_secret(self):
        def malformed(request):
            self.requests.append(request)
            return httpx.Response(200, json={
                "id": "offline-malformed", "model": "deepseek-flash", "object": "chat.completion",
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": "sk-explicit-offline-fixture", "tool_calls": [
                        {"id": "fixture-call", "type": "function", "function": {
                            "name": "GatewayAnswer", "arguments": '{"bad_field":2}'}}]}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}})
        from agent_workbench.models import ModelResponseError
        gateway = self.gateway(handler=malformed)
        with self.assertRaises(ModelResponseError):
            gateway.complete([{"role": "user", "content": "fixture"}], GatewayAnswer)
        self.assertEqual(gateway.calls[-1]["usage"]["total_tokens"], 17)
        self.assertEqual(gateway.calls[-1]["raw"]["content"], "[REDACTED]")
        self.assertNotIn("sk-explicit", self.audit_path.read_text(encoding="utf-8"))

    def test_gateway_does_not_inherit_external_tracing(self):
        from langsmith import tracing_context
        gateway = self.gateway()
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true", "LANGCHAIN_TRACING_V2": "true"}), \
                tracing_context(enabled=True), \
                patch("langchain_core.tracers.langchain.LangChainTracer.__init__",
                      side_effect=RuntimeError("fixture blocks external tracer initialization")) as external:
            result = gateway.complete([{"role": "user", "content": "private fixture"}], GatewayAnswer)
        self.assertEqual(result["message"], "fixture response")
        self.assertEqual(external.call_count, 0, "Gateway must not create external tracing callbacks")


if __name__ == "__main__":
    unittest.main()
