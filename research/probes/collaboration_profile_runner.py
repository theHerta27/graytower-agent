"""Optional frozen delegation profile layered on the unchanged native V1 runner.

Only the parent prompt, spawn.message schema/validation, and role audit differ.
Codex Runtime continues to own spawn/wait/close and all sampling. No scheduler,
tool-argument rewriting, model fallback or automatic retry is introduced.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
import uuid

import collaboration_live_runner as base

RunConfig = base.RunConfig
MODEL = base.MODEL
MODES = base.MODES
PROVIDER = base.PROVIDER
BASE_SHA256 = "360109c34b2a3613c1fe019437c7deb8666a04914b6bcfe377c682c73d2f3b19"
PROFILE_ID = "fixed-specialist-scopes-v1"
SINGLE_PLUS_FOLLOWUPS = (
    "Stage 2 of 6: Re-examine the complete frozen packet for rules and semantic correctness. Check the candidate changes against the stated business rules and invariants, revise unsupported earlier claims, and add any missed concrete defects. Work as the same single reviewer without delegation. Return a revised complete findings JSON using the packet's schema.",
    "Stage 3 of 6: Re-examine the complete frozen packet for contracts, state transitions and recovery. Check interface consistency, persistence, recovery and interactions across the candidate changes. Work as the same single reviewer without delegation. Return a revised complete findings JSON using the packet's schema.",
    "Stage 4 of 6: Re-examine the complete frozen packet for counterexamples and boundary cases. Construct concrete reachable cases, search for missing coverage and test whether each suspected defect survives these checks. Work as the same single reviewer without delegation. Return a revised complete findings JSON using the packet's schema.",
    "Stage 5 of 6: Verify every current finding individually against exact file and line evidence in the full frozen packet. Check its triggering conditions and business impact. Remove unsupported assertions, hypothetical requirements and duplicate root causes; retain any newly verified missed defects. Work as the same single reviewer without delegation. Return a revised complete findings JSON using the packet's schema.",
    "Stage 6 of 6: Consolidate your complete review into the final findings JSON required by the frozen packet. Reconcile the previous rule, contract, counterexample and evidence checks, merge duplicates, and include only supported actionable defects. Work as the same single reviewer without delegation. Return only the final JSON object.",
)
SPECIALIST_MESSAGES = (
    "You are specialist 1: rules and semantic correctness. Independently review the complete frozen task packet in your common instructions. Focus on the stated business rules, invariants and semantic correctness of the candidate changes. Identify only concrete actionable defects supported by the packet, with exact file and line evidence. Follow the packet's findings JSON schema and return concise findings. Do not delegate, use tools, inspect external sources or infer another reviewer's conclusions.",
    "You are specialist 2: contracts, state transitions and recovery. Independently review the complete frozen task packet in your common instructions. Focus on interface contracts, state transitions, persistence, recovery and consistency across the candidate changes. Identify only concrete actionable defects supported by the packet, with exact file and line evidence. Follow the packet's findings JSON schema and return concise findings. Do not delegate, use tools, inspect external sources or infer another reviewer's conclusions.",
    "You are specialist 3: tests, counterexamples and missed boundary cases. Independently review the complete frozen task packet in your common instructions. Focus on concrete counterexamples, boundary cases, missing test coverage and interactions across the candidate changes. Identify only concrete actionable defects supported by the packet, with exact file and line evidence. Follow the packet's findings JSON schema and return concise findings. Do not delegate, use tools, inspect external sources or infer another reviewer's conclusions.",
)


class FrozenDelegation:
    def __init__(self, specialists=3):
        if type(specialists) is not int or not 1 <= specialists <= len(SPECIALIST_MESSAGES):
            raise ValueError("frozen profile supports one to three registered roles")
        self.messages = SPECIALIST_MESSAGES[:specialists]
        self.calls = {}
        self.used_messages = {}
        self.lock = threading.RLock()

    def constrain_schema(self, mapped):
        """Add constraints to a copied function schema; never rewrite call args."""
        constrained = copy.deepcopy(mapped)
        for tool in constrained.get("tools", []):
            if tool.get("type") == "function" and tool.get("name") == "ma1__spawn_agent":
                parameters = tool["parameters"]
                parameters["properties"]["message"]["enum"] = list(self.messages)
                required = parameters.setdefault("required", [])
                if "message" not in required:
                    required.append("message")
        return constrained

    def validate(self, item):
        base.validate_arguments(item)
        if item.get("name") != "ma1__spawn_agent":
            return
        args = json.loads(item["arguments"])
        message = args["message"]
        if message not in self.messages:
            raise ValueError("spawn message must exactly equal a frozen specialist scope")
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise ValueError("frozen role requires a stable native call_id")
        with self.lock:
            if call_id in self.calls and self.calls[call_id] != message:
                raise ValueError("native call identity cannot change role")
            if message in self.used_messages and self.used_messages[message] != call_id:
                raise ValueError("each frozen specialist role may be spawned only once")
            self.calls[call_id] = message
            self.used_messages[message] = call_id


def profile_prompt(mode, config):
    if mode in ("single", "single_plus"):
        return base.task_prompt(mode, config)
    if mode not in ("team_serial", "team_parallel"):
        raise ValueError("unknown mode")
    messages = SPECIALIST_MESSAGES[:config.specialists]
    prompt = (
        "Review the full frozen packet in your common instructions. You are the primary reviewer. "
        f"Create exactly {config.specialists} native read-only specialists. Each registered role must be used exactly once. "
        "For every ma1__spawn_agent call, message must be exactly one of the JSON strings below, without edits, "
        "extra text, task-specific hints, earlier findings or summaries. Set fork_context=false and omit all other overrides. "
        "Every child independently receives the same full packet in common instructions. Do not copy the packet into a task message. "
        "Use only native ma1__spawn_agent, ma1__wait_agent and ma1__close_agent. Wait for every child to complete and close completed children. "
        "Independently verify every returned finding against the packet, remove unsupported claims, merge duplicates and return the required final JSON.\n"
    )
    prompt += "\n".join(f"Role {i+1} exact message: " + json.dumps(message, ensure_ascii=False) for i, message in enumerate(messages))
    if mode == "team_serial":
        return prompt + "\nSCHEDULING: Spawn role 1, wait for it to complete and close it BEFORE spawning role 2; repeat in role order. Never overlap children."
    return prompt + "\nSCHEDULING: Spawn ALL roles before waiting for any child. Let the Runtime execute them concurrently, then wait for all and close them."


def load_isolated_runtime():
    """Separate module globals preserve an active/imported original runner."""
    path = Path(base.__file__).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() != BASE_SHA256:
        raise ValueError("base runner changed; review and refreeze the profile dependency")
    name = "_frozen_profile_runtime_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    module.ENV_LOCK = base.ENV_LOCK
    return module


def run_case(packet: str, mode: str, outdir, config: RunConfig | dict, *, transport=None):
    """Same experiment API; adds exact frozen spawn scopes and auditable coverage."""
    if isinstance(config, dict):
        config = RunConfig(**config)
    if mode == "single_plus":
        config = replace(config, single_plus_turns=6, single_plus_followup_prompts=SINGLE_PLUS_FOLLOWUPS)
    guard = FrozenDelegation(config.specialists)
    isolated = load_isolated_runtime()
    original_request = isolated.bounded_request
    def constrained_request(body, request_mode, frozen_packet):
        return guard.constrain_schema(original_request(body, request_mode, frozen_packet))
    isolated.bounded_request = constrained_request
    isolated.validate_arguments = guard.validate
    isolated.task_prompt = profile_prompt
    try:
        result = isolated.run_case(packet, mode, outdir, config, transport=transport)
    finally:
        sys.modules.pop(isolated.__name__, None)
    actual_spawns = [e["params"]["item"] for e in result.get("native_lifecycle_events", [])
                    if e["method"] == "item/completed" and e["params"]["item"]["tool"] == "spawnAgent"]
    expected = guard.messages if mode.startswith("team_") else ()
    actual_messages = [item.get("prompt") for item in actual_spawns]
    coverage = {f"specialist_{i+1}": actual_messages.count(message) for i, message in enumerate(expected)}
    coverage_ok = len(actual_spawns) == len(expected) and all(count == 1 for count in coverage.values())
    result["base_runner_sha256"] = result["runner_sha256"]
    result["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result["delegation_profile"] = {
        "id": PROFILE_ID,
        "exact_messages": list(expected),
        "messages_sha256": hashlib.sha256(json.dumps(list(expected), ensure_ascii=False).encode()).hexdigest(),
        "role_coverage": coverage,
        "role_coverage_verified": coverage_ok,
        "unknown_actual_messages": [m for m in actual_messages if m not in expected],
        "native_spawn_calls": [{"call_id": item["id"], "child_ids": item["receiverThreadIds"],
                                "message": item.get("prompt")} for item in actual_spawns],
        "boundary": "Only spawn.message schema enum and exact-value validation; no tool argument mutation, no new scheduling loop. Parent-owned history cannot be embedded in the fixed child messages.",
    }
    if mode == "single_plus":
        result["single_plus_stage_prompts"] = [turn["prompt"] for turn in result.get("turns", [])]
    if not coverage_ok:
        result["pass"] = False
        result["profile_error"] = "native fixed-role coverage differs from authorized profile"
    result["limitations"].append("Frozen scopes remove parent-authored result transfer via spawn.message; parent aggregation still sees all completed child results.")
    out = Path(outdir)
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "delegation-profile.json").write_text(json.dumps(result["delegation_profile"], ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--mode", choices=base.MODES, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true")
    group.add_argument("--fixture", action="store_true")
    parser.add_argument("--max-model-calls", type=int, default=8)
    parser.add_argument("--max-output-tokens", type=int, default=16000)
    parser.add_argument("--per-request-output-tokens", type=int, default=2000)
    parser.add_argument("--wall-seconds", type=float, default=240)
    parser.add_argument("--specialists", type=int, default=3)
    parser.add_argument("--single-plus-turns", type=int, default=3)
    parser.add_argument("--ledger-path")
    parser.add_argument("--global-max-usd", type=float, default=3.0)
    parser.add_argument("--global-max-calls", type=int, default=600)
    parser.add_argument("--global-max-output-tokens", type=int, default=1000000)
    args=parser.parse_args()
    config=RunConfig(**{k:v for k,v in vars(args).items() if k not in {"packet","mode","outdir"}})
    result=run_case(args.packet.read_text(encoding="utf-8"),args.mode,args.outdir,config)
    print(json.dumps({k:result.get(k) for k in ("pass","mode","request_count","actual_children","usage","wall_seconds","profile_error")},ensure_ascii=False,indent=2))
    return 0 if result["pass"] else 1


if __name__=="__main__":
    raise SystemExit(main())
