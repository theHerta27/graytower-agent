"""Run a frozen manifest serially; preserve every assignment and native evidence.

This is experiment administration, not agent scheduling. Each run delegates its
whole task to the official SDK/native Runtime through collaboration_live_runner.
No private oracle is loaded here. Already-created run directories are immutable.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

import collaboration_live_runner as runner


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def native_audit(raw, events, evidence_dir):
    ids = set(raw.get("native_child_ids", []))
    intervals = {}
    tool_names = set()
    for event in events:
        params = event.get("params", {})
        thread_id = params.get("threadId")
        offset = event.get("offset_seconds")
        item = params.get("item", {})
        if item.get("type") == "collabAgentToolCall":
            tool = item.get("tool")
            tool_names.add({"spawnAgent": "spawn_agent", "wait": "wait_agent", "waitAgent": "wait_agent", "closeAgent": "close_agent"}.get(tool, str(tool)))
        if thread_id not in ids or offset is None:
            continue
        state = params.get("status", {}).get("type")
        if event.get("method") == "thread/status/changed":
            if state == "active":
                spans = intervals.setdefault(thread_id, [])
                if not spans or "end" in spans[-1]:
                    spans.append({"start": offset})
            elif state == "idle" and thread_id in intervals and "end" not in intervals[thread_id][-1]:
                intervals[thread_id][-1]["end"] = offset
    # Missing events remain missing; do not invent child timing from parent waits.
    children = []
    for ident in sorted(ids):
        spans = intervals.get(ident, [])
        child = {"agent_id": ident}
        if len(spans) == 1:
            child.update(spans[0])
        elif spans:
            # This experiment disallows send/resume. Preserve unexpected spans,
            # but do not use their first span or convex hull for timing claims.
            child["activity_spans"] = spans
        children.append(child)
    valid = bool(ids) and len(ids) == raw.get("config", {}).get("specialists") and all(
        "start" in child and "end" in child for child in children)
    valid = valid and raw.get("all_requests_have_full_packet") is True and {"spawn_agent", "wait_agent", "close_agent"}.issubset(tool_names)
    return {"verified": valid,
            "child_identity_and_packet_verified": bool(ids) and raw.get("all_requests_have_full_packet") is True,
            "children": children, "expected_children": raw.get("config", {}).get("specialists"),
            "tool_calls": sorted(tool_names), "evidence_refs": [str(evidence_dir / "events.json"), str(evidence_dir / "wire.json")],
            "independent_contexts_verified": None,
            "serial_no_result_leakage_verified": None,
            "overlapping_model_requests": raw.get("overlapping_model_requests", []),
            "note": "Intervals use observed child active-to-idle events; absent boundaries are unknown."}


def normalize(assignment, raw, evidence_dir):
    usage = dict(raw.get("usage", {}))
    usage["cached_input_tokens"] = raw.get("cache_hit_tokens")
    audit_errors = []
    def read_evidence(name, empty):
        path = evidence_dir / name
        if not path.exists():
            if raw.get("pass"):
                audit_errors.append({"file": name, "error": "missing evidence"})
            return empty
        try:
            return read(path)
        except (OSError, ValueError) as error:
            audit_errors.append({"file": name, "error": type(error).__name__})
            return empty
    events = read_evidence("events.json", [])
    requests = read_evidence("wire.json", {}).get("requests", [])
    truncated = any(event.get("type") == "response.incomplete" and
                    event.get("response", {}).get("incomplete_details", {}).get("reason") == "max_output_tokens"
                    for row in requests for event in row.get("provider_events", []))
    complete = bool(requests) and len(requests) == raw.get("request_count") and all(
        all(type(row.get("usage", {}).get(key)) is int for key in ("input_tokens", "output_tokens"))
        for row in requests)
    # These runs are on Sunday (off-peak); retain the conservative peak cap
    # separately. Prices are estimates from provider usage, not an invoice.
    known = all(isinstance(usage.get(k), int) for k in ("input_tokens", "output_tokens", "cached_input_tokens"))
    known_cost = ((usage["input_tokens"] - usage["cached_input_tokens"]) * .15 + usage["cached_input_tokens"] * .003 + usage["output_tokens"] * .6) / 1_000_000 if known else None
    cost = known_cost if complete else None
    status = ("audit_failure" if audit_errors else "completed") if raw.get("pass") else ("resource_truncated" if truncated else "infrastructure_failure")
    return {**assignment, "status": status, "truncated": truncated,
            "protocol_passed": raw.get("pass") is True,
            "output": raw.get("final_json", raw.get("final_text", "")),
            "usage": usage if complete else {}, "usage_complete": complete, "known_partial_usage": usage,
            "known_partial_cost_usd": known_cost, "usage_scope": "all parent and native children requests in this run; all A+ turns included",
            "cost_usd": cost, "cost_is_estimate": True,
            "pricing": "2026-10-04 Sunday DeepSeek Flash offpeak USD/M: miss .15, hit .003, output .6; failures may have unknown billed usage",
            "timing": {"end_to_end_seconds": raw.get("wall_seconds")},
            "model": runner.MODEL, "provider": "https://api.deepseek.com/responses",
            "resource_caps": raw.get("config"), "requests": raw.get("request_count"),
            "native": native_audit(raw, events, evidence_dir),
            "expected_children": raw.get("config", {}).get("specialists") if assignment["mode"].startswith("team_") else 0,
            "evidence_dir": str(evidence_dir), "packet_sha256": raw.get("packet_sha256"),
            "runner_sha256": raw.get("runner_sha256"),
            "normalizer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "audit_errors": audit_errors,
            "errors": {k: raw[k] for k in ("error_class", "guard_error", "mode_error", "errors") if k in raw}}


def execute(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    plan = read(manifest_path)
    destination = Path(plan["outdir"]).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    write(destination / "manifest.json", plan)
    assignments = plan["assignments"]
    results = []
    # All assigned runs are present from the beginning, including an interrupted
    # batch's not-started tail. A rerun must use a NEW explicit manifest/run ID.
    for item in assignments:
        results.append({**item, "status": "not_started", "protocol_passed": False, "output": ""})
    write(destination / "runs.json", {"runs": results})
    for index, item in enumerate(assignments):
        packet_path = Path(item["packet_path"])
        packet = packet_path.read_text(encoding="utf-8-sig")
        actual_hash = hashlib.sha256(packet.encode("utf-8")).hexdigest()
        if actual_hash != item["packet_sha256"]:
            raise ValueError("Frozen packet changed: " + item["task_id"])
        evidence = destination / item["run_id"]
        profile = {**plan["common_config"], **plan["profiles"][item["mode"]]}
        started = time.monotonic()
        results[index] = {**item, "status": "started", "protocol_passed": False, "output": "", "evidence_dir": str(evidence)}
        write(destination / "runs.json", {"runs": results})
        print(json.dumps({"event": "start", "run_id": item["run_id"], "mode": item["mode"]}), flush=True)
        try:
            raw = runner.run_case(packet, item["mode"], evidence, runner.RunConfig(**profile))
        except Exception as error:
            # Never turn a process/setup failure into a silent discarded sample.
            raw = {"pass": False, "error_class": type(error).__name__, "wall_seconds": time.monotonic() - started,
                   "config": profile, "packet_sha256": actual_hash}
            evidence.mkdir(parents=True, exist_ok=True)
            write(evidence / "batch-error.json", raw)
        write(evidence / "batch-raw-result.json", raw)
        try:
            result = normalize(item, raw, evidence)
        except Exception as error:
            result = {**item, "status": "audit_failure", "protocol_passed": raw.get("pass") is True,
                      "output": raw.get("final_json", raw.get("final_text", "")), "usage": raw.get("usage", {}),
                      "cost_usd": None, "timing": {"end_to_end_seconds": raw.get("wall_seconds")},
                      "evidence_dir": str(evidence), "requests": raw.get("request_count"),
                      "errors": {"normalization_error": type(error).__name__}}
        results[index] = result
        write(destination / "runs.json", {"runs": results})
        print(json.dumps({"event": "complete", "run_id": item["run_id"], "status": result["status"],
                          "seconds": result["timing"]["end_to_end_seconds"], "cost_usd": result["cost_usd"],
                          "requests": result["requests"], "errors": result["errors"]}, ensure_ascii=False), flush=True)
        if result["status"] != "completed" and plan.get("stop_on_failure", True):
            print("BATCH_STOPPED: inspect preserved failure before spending further budget", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    sys.exit(execute(args.manifest))
