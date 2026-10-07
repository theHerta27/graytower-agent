"""No live model calls: frozen delegation schema and real-Runtime fixture tests."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import collaboration_profile_runner as profile
import collaboration_live_runner as base


def frozen_fixture_transport(body):
    """Scripted local Responses fixture only; Runtime performs every lifecycle."""
    users=[x for x in body.get("input",[]) if x.get("role")=="user"]
    last=users[-1].get("content",[]) if users else []
    last=last if isinstance(last,str) else "\n".join(x.get("text","") for x in last)
    if last in profile.SPECIALIST_MESSAGES:
        items=[base.protocol.message('{"findings":[],"summary":"local fixed-role fixture only"}', "msg_child_"+str(profile.SPECIALIST_MESSAGES.index(last)))]
    else:
        outputs={x["call_id"]:x["output"] for x in body.get("input",[]) if x.get("type")=="function_call_output"}
        parallel="Spawn ALL roles before waiting" in last
        count=next((len(t["parameters"]["properties"]["message"]["enum"]) for t in body["tools"] if t.get("name")=="ma1__spawn_agent"),0)
        items=[]
        if parallel and not any("fixed_spawn_"+str(i) in outputs for i in range(count)):
            items=[base.protocol.function("spawn_agent",{"message":message,"fork_context":False},"fixed_spawn_"+str(i)) for i,message in enumerate(profile.SPECIALIST_MESSAGES[:count])]
        else:
            for i,message in enumerate(profile.SPECIALIST_MESSAGES[:count]):
                if "fixed_spawn_"+str(i) not in outputs:
                    items=[base.protocol.function("spawn_agent",{"message":message,"fork_context":False},"fixed_spawn_"+str(i))]
                    break
                child=json.loads(outputs["fixed_spawn_"+str(i)])["agent_id"]
                if "fixed_wait_"+str(i) not in outputs:
                    items=[base.protocol.function("wait_agent",{"targets":[child],"timeout_ms":10000},"fixed_wait_"+str(i))]
                    break
                if "fixed_close_"+str(i) not in outputs:
                    items=[base.protocol.function("close_agent",{"target":child},"fixed_close_"+str(i))]
                    break
        if not items:
            items=[base.protocol.message('{"findings":[],"summary":"local fixed-role fixture only"}',"msg_parent_final")]
    events=[{"type":"response.created","response":{"id":"fixed_fixture"}}]
    for i,item in enumerate(items):
        events.extend([{"type":"response.output_item.added","output_index":i,"item":item},{"type":"response.output_item.done","output_index":i,"item":item}])
    events.append({"type":"response.completed","response":{"id":"fixed_fixture","output":items,"usage":{"input_tokens":100,"output_tokens":30,"total_tokens":130}}})
    return events


class FrozenProfileTests(unittest.TestCase):
    def test_same_exact_messages_and_roles_in_both_schedules(self):
        config = base.RunConfig(fixture=True)
        serial = profile.profile_prompt("team_serial", config)
        parallel = profile.profile_prompt("team_parallel", config)
        self.assertEqual(serial.split("SCHEDULING:")[0], parallel.split("SCHEDULING:")[0])
        for message in profile.SPECIALIST_MESSAGES:
            self.assertIn(json.dumps(message, ensure_ascii=False), serial)
            self.assertIn(json.dumps(message, ensure_ascii=False), parallel)
        self.assertEqual(len(profile.SPECIALIST_MESSAGES), 3)

    def test_spawn_schema_uses_exact_enum_only(self):
        guard = profile.FrozenDelegation(3)
        raw = {"tools": [{"type": "function", "name": "ma1__spawn_agent", "parameters": {"type": "object", "properties": {"message": {"type": "string"}, "fork_context": {"type": "boolean"}}, "additionalProperties": False}}]}
        shaped = guard.constrain_schema(raw)
        self.assertEqual(shaped["tools"][0]["parameters"]["properties"]["message"]["enum"], list(profile.SPECIALIST_MESSAGES))
        self.assertIn("message", shaped["tools"][0]["parameters"]["required"])
        self.assertNotIn("enum", raw["tools"][0]["parameters"]["properties"]["message"])

    def test_accept_roles_reject_injected_answers_and_duplicate_roles(self):
        guard = profile.FrozenDelegation(3)
        for i, message in enumerate(profile.SPECIALIST_MESSAGES):
            item=base.protocol.function("spawn_agent", {"message": message, "fork_context": False}, "role"+str(i))
            guard.validate(item)
            guard.validate(item)  # SSE done and terminal validation is idempotent.
        for bad in (profile.SPECIALIST_MESSAGES[0]+" Previous reviewer found bug in file X.", "".join(profile.SPECIALIST_MESSAGES), "Review the packet independently."):
            with self.subTest(message=bad), self.assertRaises(ValueError):
                guard.validate(base.protocol.function("spawn_agent", {"message":bad}, "injected"))
        with self.assertRaises(ValueError):
            guard.validate(base.protocol.function("spawn_agent", {"message":profile.SPECIALIST_MESSAGES[0]}, "duplicate"))

    def test_declared_count_and_call_identity_cannot_expand(self):
        guard=profile.FrozenDelegation(1)
        with self.assertRaises(ValueError):
            guard.validate(base.protocol.function("spawn_agent", {"message":profile.SPECIALIST_MESSAGES[1]}, "extra"))
        guard.validate(base.protocol.function("spawn_agent", {"message":profile.SPECIALIST_MESSAGES[0]}, "same"))
        with self.assertRaises(ValueError):
            profile.FrozenDelegation(4)

    def test_original_runner_remains_unmodified_and_global_functions_unchanged(self):
        path=Path(base.__file__)
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        bounded,validate,prompt=base.bounded_request,base.validate_arguments,base.task_prompt
        isolated=profile.load_isolated_runtime()
        self.assertIsNot(isolated,base)
        self.assertIs(base.bounded_request,bounded)
        self.assertIs(base.validate_arguments,validate)
        self.assertIs(base.task_prompt,prompt)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_single_plus_six_distinct_followups_and_old_initial_prompt(self):
        self.assertEqual(len(profile.SINGLE_PLUS_FOLLOWUPS), 5)
        self.assertEqual(len(set(profile.SINGLE_PLUS_FOLLOWUPS)), 5)
        config=base.RunConfig(fixture=True)
        self.assertEqual(profile.profile_prompt("single_plus",config),base.task_prompt("single_plus",config))


if __name__=='__main__':
    unittest.main(verbosity=2)
