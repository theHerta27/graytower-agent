"""Independent evidence-bound scoring for the frozen collaboration experiment.

No network, model, credential, or candidate-code execution.  `prepare` emits a
mechanically blinded finding packet and an EMPTY adjudication template. `score`
accepts only explicit, source-referenced causal judgments bound to that packet.
There is deliberately no title/keyword matcher and no LLM self-score.

Examples (use the project's explicit Python interpreter):
    evaluate.py prepare --results runs.json --oracle oracle/private --out review
    evaluate.py score --results runs.json --oracle oracle/private \
        --adjudications review/adjudications.json --out review/scored

Results may be a list, {"runs": [...]}, one run, or JSONL. Oracle may be a list,
{"tasks": [...]}, one task, or a directory of task-level oracle.json files.
The output run-map.json contains treatment identities; keep it from the reviewer
until adjudication is locked. Text can still reveal a treatment; disclose that
limitation instead of claiming perfect human blinding.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics

VERSION = "causal-adjudication-v1"
CHECKS = ("root_cause", "trigger", "path", "evidence")
COMPLETE = {"completed", "complete", "success", "succeeded", "ok"}
NOT_STARTED = {"not_started", "not_run", "assigned", "queued", "cancelled_before_start"}
SEVERE = {"P0", "P1", "CRITICAL", "HIGH", "BLOCKER"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_results(path):
    path = Path(path)
    if path.is_dir():
        files = sorted(path.glob("**/run-result.json")) or sorted(path.glob("**/result.json"))
        if not files:
            raise ValueError("No run-result.json or result.json found; pass the run manifest explicitly")
        return [run for file in files for run in load_results(file)]
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    data = read_json(path)
    if isinstance(data, list):
        return data
    if "runs" in data:
        return data["runs"]
    return [data]


def load_oracle(path):
    path = Path(path)
    if path.is_dir():
        return {"tasks": [read_json(file) for file in sorted(path.glob("**/oracle.json"))]}
    return read_json(path)


def oracle_tasks(oracle):
    tasks = oracle if isinstance(oracle, list) else oracle.get("tasks", [oracle])
    if not tasks:
        raise ValueError("Oracle contains no tasks")
    result = {}
    for task in tasks:
        task_id = task["task_id"]
        if task_id in result:
            raise ValueError(f"Duplicate oracle task: {task_id}")
        ids = [issue["issue_id"] for issue in task["issues"]]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Duplicate oracle issue in {task_id}")
        result[task_id] = task
    return result


def extract_findings(run):
    """Parse structure only. Unstructured prose requires manual extraction."""
    if isinstance(run.get("findings"), list):
        return run["findings"], True, None
    output = run.get("output", run.get("final_output", run.get("final", "")))
    if isinstance(output, str):
        value = output.strip()
        if value.startswith("```"):
            lines = value.splitlines()
            if lines[-1].strip() == "```":
                value = "\n".join(lines[1:-1])
        try:
            output = json.loads(value)
        except (ValueError, TypeError):
            return [], False, output
    if isinstance(output, dict) and isinstance(output.get("findings"), list):
        return output["findings"], True, None
    return [], False, output


def normalize_runs(runs):
    normalized = []
    ids = set()
    for index, item in enumerate(runs):
        run = dict(item)
        run_id = str(run.get("run_id", run.get("id", f"run-{index + 1}")))
        if run_id in ids:
            raise ValueError(f"Duplicate run_id: {run_id}")
        ids.add(run_id)
        for key in ("task_id", "mode"):
            if key not in run:
                raise ValueError(f"Run {run_id} missing {key}")
        run.update(run_id=run_id, repeat=run.get("repeat", 1))
        normalized.append(run)
    return normalized


def prepare(runs, oracle):
    runs = normalize_runs(runs)
    tasks = oracle_tasks(oracle)
    source_digest = digest({"runs": runs, "oracle": oracle})
    packet = {"schema_version": 1, "evaluator_version": VERSION, "source_digest": source_digest,
              "blinding": "mode, repeat, runtime status, costs and run IDs removed; output text may reveal treatment",
              "instructions": "Compare each finding against source, trigger and root cause. Never award TP by title or aliases.",
              "runs": []}
    mapping = {"schema_version": 1, "source_digest": source_digest, "runs": []}
    adjudication = {"schema_version": 1, "evaluator_version": VERSION, "source_digest": source_digest,
                    "reviewer": "", "reviewer_kind": "independent_source_review", "runs": []}
    # Hash order removes execution order as a treatment cue, yet remains reproducible.
    ordered = sorted(runs, key=lambda run: digest({"salt": "blind-v1", "id": run["run_id"]}))
    for index, run in enumerate(ordered, 1):
        if run["task_id"] not in tasks:
            raise ValueError(f"Unknown oracle task: {run['task_id']}")
        blind_id = f"review-{index:04d}"
        findings, structured, raw = extract_findings(run)
        review_findings = [{"finding_id": f"f{i:03d}", "finding": finding}
                           for i, finding in enumerate(findings, 1)]
        packet["runs"].append({"blind_id": blind_id, "task_id": run["task_id"],
                               "structured_output": structured, "findings": review_findings,
                               "unparsed_output": raw})
        mapping["runs"].append({"blind_id": blind_id, **{k: run[k] for k in ("run_id", "task_id", "mode", "repeat")}})
        adjudication["runs"].append({"blind_id": blind_id, "task_id": run["task_id"],
                                    "output_qualified": None, "output_notes": "",
                                    "findings": [{"finding_id": f["finding_id"], "verdict": "pending",
                                                  "issue_id": None, "rationale": "",
                                                  "checks": {key: None for key in CHECKS}, "evidence_refs": [],
                                                  "submitted_evidence_complete": None, "submitted_evidence_notes": ""}
                                                 for f in review_findings]})
    return packet, mapping, adjudication


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def timestamp(value):
    if number(value):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def audit_schedule(run):
    native = run.get("native", {}) or {}
    children = native.get("children", run.get("children", []))
    events = []
    valid = []
    invalid = []
    for child in children:
        start = timestamp(child.get("start", child.get("started_at")))
        end = timestamp(child.get("end", child.get("ended_at")))
        if start is None or end is None or end < start or not child.get("agent_id", child.get("thread_id")):
            invalid.append(child)
            continue
        valid.append(child)
        events.extend([(start, 1), (end, -1)])
    active = maximum = 0
    previous = None
    overlap = 0.0
    for time, delta in sorted(events):  # ends before starts at exactly the same timestamp
        if previous is not None and active >= 2:
            overlap += time - previous
        active += delta
        maximum = max(maximum, active)
        previous = time
    mode = str(run["mode"]).lower().replace("-", "").replace("_", "")
    team = mode.startswith("team") or mode.startswith("b")
    conforms = None
    if not invalid and len(valid) >= 2:
        if "serial" in mode:
            conforms = maximum <= 1
        elif "parallel" in mode:
            conforms = maximum >= 2
    tool_names = [str(event.get("name", event.get("tool", ""))) if isinstance(event, dict) else str(event)
                  for event in native.get("tool_calls", [])]
    spawn = any("spawn_agent" in name for name in tool_names)
    wait = any("wait_agent" in name or name.endswith("wait") for name in tool_names)
    refs = native.get("evidence_refs", [])
    native_status = "unverified"
    if not team:
        native_status = "unexpected_children" if children or spawn else "not_requested"
    elif native.get("verified") is True and spawn and wait and refs and valid:
        native_status = "trace_attested"
    elif native.get("verified") is False:
        native_status = "failed"
    expected = run.get("expected_children", native.get("expected_children"))
    return {"native_status": native_status, "native_evidence_refs": refs,
            "reported_native_verification": native.get("verified"),
            "child_count": len(children), "valid_child_intervals": len(valid),
            "invalid_child_intervals": invalid, "max_active_children": maximum if valid else None,
            "overlap_seconds": overlap if valid else None, "schedule_conforms": conforms,
            "child_count_conforms": len(valid) == expected if isinstance(expected, int) else None,
            "parent_interval": native.get("parent"), "child_intervals": children,
            "independent_contexts_verified": native.get("independent_contexts_verified"),
            "serial_no_result_leakage_verified": native.get("serial_no_result_leakage_verified"),
            "note": "Child lifetimes establish runtime overlap, not simultaneous model compute; raw traces still require audit."}


def resources(run):
    usage = dict(run.get("usage") or {})
    timing = dict(run.get("timing") or {})
    cost = run.get("cost_usd")
    offpeak = run.get("estimated_offpeak_cost_usd", run.get("offpeak_estimated_cost_usd"))
    peak = run.get("estimated_peak_cost_usd", run.get("peak_budget_estimate_usd"))
    if cost is None and number(offpeak):
        cost = offpeak
    if isinstance(run.get("cost"), dict):
        cost = run["cost"].get("usd", run["cost"].get("estimated_usd", cost))
    end_to_end = timing.get("end_to_end_seconds", run.get("end_to_end_seconds", run.get("elapsed_seconds")))
    status = str(run.get("status", run.get("pipeline_status", "unknown"))).lower()
    if status in NOT_STARTED or run.get("actually_started") is False:
        # An assigned cell is neither a zero-cost successful run nor a failed inference.
        usage, cost, end_to_end = {}, None, None
        offpeak, peak = None, None
    return {"usage": usage, "usage_complete": all(number(usage.get(k)) for k in ("input_tokens", "output_tokens")),
            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens", usage["input_tokens"] + usage["output_tokens"]
                                      if all(number(usage.get(k)) for k in ("input_tokens", "output_tokens")) else None),
            "cached_input_tokens": usage.get("cached_input_tokens", usage.get("cache_read_input_tokens")),
            "cost_usd": cost, "cost_is_estimate": run.get("cost_is_estimate", True),
            "offpeak_estimated_cost_usd": offpeak, "peak_budget_estimate_usd": peak,
            "cost_note": "Usage-based estimate, not invoice; peak reserve is a separate budget bound.",
            "pricing": run.get("pricing", run.get("price_version")), "end_to_end_seconds": end_to_end,
            "timing": timing, "resource_caps": run.get("resource_caps", run.get("budget")),
            "budget_hit": run.get("budget_hit"), "requests": run.get("requests"),
            "model": run.get("model"), "provider": run.get("provider"),
            "usage_scope": run.get("usage_scope", "unspecified; must audit parent, children, retries and summaries"),
            "retry_count": run.get("retry_count"), "coordination_errors": run.get("coordination_errors", [])}


def summarize(rows):
    started = [r for r in rows if r["actually_started"]]
    result = {"assigned_runs": len(rows), "actually_started_runs": len(started),
              "attempted_runs": len(started), "not_started_runs": len(rows) - len(started),
              "independent_tasks": len({r["task_id"] for r in rows}),
              "actually_started_independent_tasks": len({r["task_id"] for r in started}),
              "delivered_runs": sum(r["delivered"] for r in rows),
              "output_qualified_runs": sum(r["output_qualified"] is True for r in started),
              "all_known_issues_without_fp_runs": sum(r["all_known_issues_without_fp"] for r in rows),
              "quality_scored_runs": sum(r["quality_eligible"] for r in rows),
              "pending_adjudication_runs": sum(r["adjudication_status"] != "complete" for r in started),
              "pipeline_status_counts": dict(Counter(r["pipeline_status"] for r in rows)),
              "native_status_counts": dict(Counter(r["schedule"]["native_status"] for r in rows)),
              "schedule_nonconforming_runs": sum(r["schedule"]["schedule_conforms"] is False for r in rows),
              "cost_missing_runs": sum(not number(r["resources"]["cost_usd"]) for r in started),
              "usage_incomplete_runs": sum(not r["resources"]["usage_complete"] for r in started),
              "end_to_end_missing_runs": sum(not number(r["resources"]["end_to_end_seconds"]) for r in started)}
    for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd", "end_to_end_seconds"):
        values = [r["resources"][key] for r in started if number(r["resources"][key])]
        result[key + "_known_sum"] = sum(values)
        result[key + "_median"] = statistics.median(values) if values else None
        result[key + "_range"] = [min(values), max(values)] if values else None
    result["delivery_rate_all_attempts"] = result["delivered_runs"] / len(started) if started else None
    result["delivery_rate_all_assignments"] = result["delivered_runs"] / len(rows) if rows else None
    eligible = [r for r in rows if r["quality_eligible"]]
    result["quality_tp"] = sum(r["tp"] for r in eligible)
    result["quality_novel_tp_outside_frozen_oracle"] = sum(r["novel_tp"] for r in eligible)
    result["quality_fp"] = sum(r["fp"] for r in eligible)
    result["quality_fn_known_oracle"] = sum(r["quality_fn"] for r in eligible)
    result["quality_severe_fn_known_oracle"] = sum(r["quality_severe_fn"] for r in eligible)
    result["delivery_missing_known_issues_all_attempts"] = sum(len(r["delivery_missing_issues"]) for r in started)
    result["delivery_missing_known_issues_all_assignments"] = sum(len(r["delivery_missing_issues"]) for r in rows)
    result["unit_warning"] = "Runs/repeats are not independent tasks. All sums are descriptive. Unknown costs are not zero."
    return result


def paired_comparisons(rows):
    """All within-task/repeat comparisons, preserving unsuccessful paired rows."""
    cells = defaultdict(list)
    for row in rows:
        cells[(row["task_id"], str(row["repeat"]))].append(row)
    comparisons = []
    for (task_id, repeat), values in sorted(cells.items()):
        for index, left in enumerate(values):
            for right in values[index + 1:]:
                if left["mode"] == right["mode"]:
                    continue
                item = {"task_id": task_id, "repeat": repeat, "left_run_id": left["run_id"],
                        "right_run_id": right["run_id"], "left_mode": left["mode"], "right_mode": right["mode"],
                        "both_quality_eligible": left["quality_eligible"] and right["quality_eligible"],
                        "left_pipeline_status": left["pipeline_status"], "right_pipeline_status": right["pipeline_status"],
                        "delivered_right_minus_left": int(right["delivered"]) - int(left["delivered"]),
                        "all_known_issues_right_minus_left": int(right["all_known_issues_without_fp"]) - int(left["all_known_issues_without_fp"])}
                for key in ("tp", "novel_tp", "fp", "quality_fn", "quality_severe_fn"):
                    item[key + "_right_minus_left"] = right[key] - left[key] if item["both_quality_eligible"] else None
                for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd", "end_to_end_seconds"):
                    a, b = left["resources"][key], right["resources"][key]
                    item[key + "_right_minus_left"] = b - a if number(a) and number(b) else None
                    item[key + "_right_over_left"] = b / a if number(a) and number(b) and a != 0 else None
                serial = next((r for r in (left, right) if "serial" in r["mode"].lower()), None)
                parallel = next((r for r in (left, right) if "parallel" in r["mode"].lower()), None)
                if serial and parallel:
                    a, b = serial["resources"]["end_to_end_seconds"], parallel["resources"]["end_to_end_seconds"]
                    item["serial_minus_parallel_seconds"] = a - b if number(a) and number(b) else None
                    item["serial_over_parallel"] = a / b if number(a) and number(b) and b > 0 else None
                    item["both_schedules_conform"] = all(r["schedule"]["schedule_conforms"] is True for r in (serial, parallel))
                    item["same_division_must_be_audited"] = True
                comparisons.append(item)
    return comparisons


def score(runs, oracle, adjudications):
    runs = normalize_runs(runs)
    tasks = oracle_tasks(oracle)
    packet, mapping, template = prepare(runs, oracle)
    if adjudications.get("source_digest") != template["source_digest"]:
        raise ValueError("Adjudication source digest mismatch; outputs or oracle changed")
    if adjudications.get("evaluator_version") != VERSION:
        raise ValueError("Adjudication evaluator version mismatch")
    judgments = {r["blind_id"]: r for r in adjudications["runs"]}
    if len(judgments) != len(adjudications["runs"]) or set(judgments) != {r["blind_id"] for r in template["runs"]}:
        raise ValueError("Adjudication must retain each prepared run exactly once")
    review_ids = {row["run_id"]: row["blind_id"] for row in mapping["runs"]}
    expected_rows = {row["blind_id"]: row for row in template["runs"]}
    rows = []
    for run in runs:
        task = tasks[run["task_id"]]
        oracle_issues = {i["issue_id"]: i for i in task["issues"]}
        blind_id = review_ids[run["run_id"]]
        judgment = judgments[blind_id]
        expected = expected_rows[blind_id]
        findings = judgment["findings"]
        if judgment["task_id"] != run["task_id"]:
            raise ValueError("Adjudication task mismatch")
        if [f["finding_id"] for f in findings] != [f["finding_id"] for f in expected["findings"]]:
            raise ValueError("Adjudication changed finding identities or removed findings")
        matched = set()
        novel = {}
        fp = duplicates = pending = evidence_complete = evidence_unknown = 0
        for finding in findings:
            verdict = finding["verdict"]
            if verdict in {"pending", "unresolved"}:
                pending += 1
                continue
            if verdict not in {"tp", "fp", "duplicate", "novel_tp"}:
                raise ValueError(f"Unsupported verdict {verdict!r}")
            if not adjudications.get("reviewer") or not finding.get("rationale") or not finding.get("evidence_refs"):
                raise ValueError("Confirmed findings require reviewer, rationale and source evidence_refs")
            if verdict in {"tp", "duplicate", "novel_tp"}:
                if not all(finding.get("checks", {}).get(key) is True for key in CHECKS):
                    raise ValueError("TP requires all root-cause causal checks and evidence")
            if verdict == "novel_tp":
                issue = finding.get("novel_issue", {})
                if not all(issue.get(k) for k in ("root_cause", "trigger", "paths", "severity")):
                    raise ValueError("Novel TP requires an independently described cause, trigger, paths and severity")
                if finding.get("issue_id") is not None:
                    raise ValueError("Novel TP cannot change the frozen oracle or known issue denominator")
                novel_key = finding.get("novel_issue_id", digest(issue))
                if novel_key in novel:
                    duplicates += 1
                else:
                    novel[novel_key] = {**issue, "evidence_refs": finding["evidence_refs"], "rationale": finding["rationale"]}
            elif verdict in {"tp", "duplicate"}:
                issue_id = finding.get("issue_id")
                if issue_id not in oracle_issues:
                    raise ValueError(f"Unknown issue: {issue_id}")
                if verdict == "duplicate" and issue_id not in matched:
                    raise ValueError("A duplicate must refer to an earlier confirmed TP in the same run")
                if issue_id in matched:
                    duplicates += 1
                else:
                    matched.add(issue_id)
                    submitted_evidence = finding.get("submitted_evidence_complete")
                    if submitted_evidence is not None and type(submitted_evidence) is not bool:
                        raise ValueError("submitted_evidence_complete must be boolean or null")
                    evidence_complete += submitted_evidence is True
                    evidence_unknown += submitted_evidence is None
            else:
                fp += 1
        qualified = judgment.get("output_qualified")
        if qualified is not None and type(qualified) is not bool:
            raise ValueError("output_qualified must be boolean or null")
        adjudicated = pending == 0 and qualified is not None and bool(adjudications.get("reviewer"))
        status = str(run.get("status", run.get("pipeline_status", "unknown"))).lower()
        actually_started = status not in NOT_STARTED and run.get("actually_started") is not False
        protocol = run.get("protocol_passed")
        schedule = audit_schedule(run)
        completed = actually_started and status in COMPLETE and not run.get("truncated", False)
        eligible = completed and protocol is not False and adjudicated
        delivered = completed and qualified is True and adjudicated and protocol is not False
        missing = sorted(set(oracle_issues) - matched)
        severe_missing = [issue for issue in missing if str(oracle_issues[issue]["severity"]).upper() in SEVERE]
        exhaustive = task.get("exhaustive", task.get("exhaustive_within_scope", False)) is True
        denominator = len(oracle_issues)
        known_recall = len(matched) / denominator if eligible and denominator else None
        row = {"run_id": run["run_id"], "task_id": run["task_id"], "mode": run["mode"], "repeat": run["repeat"],
               "split": task.get("split", "unknown"), "ground_truth_kind": task.get("ground_truth_kind"),
               "pipeline_status": status, "actually_started": actually_started,
               "protocol_passed": protocol, "truncated": run.get("truncated", False),
               "output_qualified": qualified, "adjudication_status": "not_started" if not actually_started else "complete" if adjudicated else "pending",
               "delivered": delivered, "quality_eligible": eligible, "oracle_exhaustive_within_scope": exhaustive,
               "known_issue_count": denominator, "tp": len(matched), "novel_tp": len(novel),
               "novel_issues_outside_frozen_oracle": novel, "fp": fp, "duplicate_findings": duplicates,
               "pending_findings": pending, "matched_issues": sorted(matched),
               "delivery_missing_issues": missing if delivered else sorted(oracle_issues),
               "quality_fn": len(missing) if eligible else None,
               "quality_severe_fn": len(severe_missing) if eligible else None,
               "quality_missing_issues": missing if eligible else None,
               "quality_severe_missing_issues": severe_missing if eligible else None,
               "known_issue_recall": known_recall, "recall": known_recall if exhaustive else None,
               "precision": (len(matched) + len(novel)) / (len(matched) + len(novel) + fp)
                            if eligible and (matched or novel or fp) else None,
               "evidence_complete_tp": evidence_complete,
               "evidence_unknown_tp": evidence_unknown,
               "evidence_completeness": evidence_complete / len(matched) if matched and not evidence_unknown else None,
               "all_known_issues_without_fp": delivered and not missing and fp == 0,
               "clean_control_correct": delivered and fp == 0 if denominator == 0 else None,
               "resources": resources(run), "schedule": schedule, "adjudication": judgment,
               "raw_audit": {k: v for k, v in run.items() if k not in {"findings", "output", "final", "final_output"}}}
        rows.append(row)
    by_mode = defaultdict(list)
    by_task_mode = defaultdict(list)
    for row in rows:
        by_mode[(row["split"], row["mode"])].append(row)
        by_task_mode[(row["task_id"], row["mode"])].append(row)
    return {"schema_version": 1, "evaluator_version": VERSION, "source_digest": template["source_digest"],
            "reviewer": adjudications.get("reviewer"), "adjudication_digest": digest(adjudications),
            "conclusion": "DESCRIPTIVE_ONLY; no automatic claim of improvement, significance, or adoption",
            "runs": rows, "summary": summarize(rows),
            "by_split_mode": [{"split": key[0], "mode": key[1], **summarize(values)} for key, values in sorted(by_mode.items())],
            "by_task_mode": [{"task_id": key[0], "mode": key[1], **summarize(values)} for key, values in sorted(by_task_mode.items())],
            "paired_comparisons": paired_comparisons(rows),
            "limitations": ["Quality eligibility excludes unfinished infrastructure/protocol attempts; delivery retains every attempt.",
                            "A missing protocol flag is unknown, never proof of compatibility; inspect native audit separately.",
                            "Different resource usage is reported, not used to invalidate A/B quality by itself.",
                            "Partial oracle recall covers only independently enumerated in-scope issues.",
                            "No repair or game delivery success is inferred from review findings."]}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("prepare", "score"))
    parser.add_argument("--results", required=True)
    parser.add_argument("--oracle", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--adjudications")
    args = parser.parse_args(argv)
    runs = load_results(args.results)
    oracle = load_oracle(args.oracle)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.command == "prepare":
        packet, mapping, template = prepare(runs, oracle)
        target = out / "adjudications.json"
        if target.exists():
            raise ValueError("Refusing to overwrite adjudications; choose a new output directory")
        write_json(out / "review-packet.json", packet)
        write_json(out / "run-map.json", mapping)
        write_json(target, template)
        print(json.dumps({"prepared_runs": len(runs), "out": str(out), "source_digest": template["source_digest"]}))
    else:
        if not args.adjudications:
            parser.error("score requires --adjudications")
        result = score(runs, oracle, read_json(args.adjudications))
        write_json(out / "run-scores.json", result)
        write_json(out / "summary.json", {k: v for k, v in result.items() if k != "runs"})
        columns = ("run_id", "task_id", "split", "mode", "repeat", "pipeline_status", "actually_started", "protocol_passed",
                   "truncated", "output_qualified", "adjudication_status", "delivered", "quality_eligible",
                   "tp", "novel_tp", "fp", "duplicate_findings", "quality_fn", "quality_severe_fn", "all_known_issues_without_fp")
        with (out / "run-scores.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=columns + ("input_tokens", "output_tokens", "cost_usd", "end_to_end_seconds"))
            writer.writeheader()
            for row in result["runs"]:
                writer.writerow({**{key: row[key] for key in columns},
                                 **{key: row["resources"][key] for key in ("input_tokens", "output_tokens", "cost_usd", "end_to_end_seconds")}})
        print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
