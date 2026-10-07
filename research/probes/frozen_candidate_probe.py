"""Local research: Author freezes config; Verifier only reads frozen artifacts.

Run with combat-foundation/.venv/Scripts/python.exe -B. No model, provider,
environment secrets, arbitrary code candidate or production A2A implementation.
"""
import argparse
from copy import deepcopy
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import sys
import time

TRUSTED_GAME_ROOT = Path("D:/Desktop/combat-foundation")
PROFILE = "frozen-combat-numeric-probe-v1"
REQUEST_FIELDS = {"schema_version", "request_id", "author_ref", "candidate_revision",
                  "game_fingerprint", "baseline", "candidate", "scenario", "seeds",
                  "policy", "max_battles", "authorization", "spec"}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def source_snapshot(root):
    root = Path(root).resolve(strict=True)
    if root != TRUSTED_GAME_ROOT.resolve(strict=True):
        raise ValueError("only the explicitly trusted game checkout is supported")
    paths = [p for folder in (root / "game-core/combat_core", root / "services/verification-agent/verification_agent")
             for p in folder.rglob("*.py")]
    paths += [root / "configs/combat/v2/baseline.json", root / "configs/combat/v2/scenario.json"]
    fingerprints = {}
    h = hashlib.sha256()
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        fingerprints[relative] = sha(raw)
        h.update(relative.encode("utf-8") + b"\0" + raw + b"\0")
    return {"fingerprint": h.hexdigest(), "files": fingerprints}


def bind_trusted_game(root):
    snapshot = source_snapshot(root)
    sys.path[:0] = [str(Path(root) / "game-core"), str(Path(root) / "services/verification-agent")]
    return snapshot


def write_artifact(folder, value, schema):
    raw = encoded(value)
    digest = sha(raw)
    path = folder / (digest + ".json")
    with path.open("xb") as stream:
        stream.write(raw)
    return {"artifact_id": digest, "sha256": digest, "schema": schema}


def author_freeze(game_root, artifact_dir):
    """Author-only construction; this is a deterministic fixture, never an LLM."""
    snapshot = bind_trusted_game(game_root)
    from combat_core.v2.config import load_bundle, load_scenario
    from verification_agent.v2.models import Authorization, TaskSpec
    from verification_agent.v2.policy import apply_changes, validate_candidate

    base = load_bundle(Path(game_root) / "configs/combat/v2/baseline.json").model_dump(mode="json")
    scenario = load_scenario(Path(game_root) / "configs/combat/v2/scenario.json").model_dump(mode="json")
    if base["skills"]["breaker_skill"]["multiplier"] != 1.4:
        raise ValueError("author fixture expects the audited 1.4 baseline")
    auth = Authorization(actor="config-author-fixture", note="explicit local frozen candidate probe",
                         scope={"skills.breaker_skill.multiplier": {"minimum": 1.4, "maximum": 1.7}},
                         seeds=[7, 11], policies=["balanced"], min_samples=2,
                         max_model_calls=0, max_simulations=4)
    spec = TaskSpec(goal="只将 breaker_skill multiplier 从 1.4 改为 1.7，验证结构并观察固定样本。",
                    mutable_scope=["skills.breaker_skill.multiplier"],
                    parameter_constraints={"skills.breaker_skill.multiplier": {"minimum": 1.7, "maximum": 1.7}},
                    # Legacy structural validator requires a criterion. This probe
                    # does not evaluate it or promote it to a behavioral acceptance.
                    acceptance_criteria=[dict(metric="win_rate_delta", op="gte", target=0, policy="balanced")])
    candidate, _ = apply_changes(base, [{"path": "skills.breaker_skill.multiplier", "value": 1.7}], auth, spec)
    if not validate_candidate(base, candidate, auth, spec)["passed"]:
        raise ValueError("author preflight failed")
    if source_snapshot(game_root) != snapshot:
        raise ValueError("game changed during author freeze")
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=False)
    return dict(schema_version=PROFILE, request_id="frozen-candidate-20261005", author_ref="config-author-fixture",
                candidate_revision="candidate-1", game_fingerprint=snapshot["fingerprint"],
                baseline=write_artifact(artifact_dir, base, "combat-bundle-v2"),
                candidate=write_artifact(artifact_dir, candidate, "combat-bundle-v2"),
                scenario=write_artifact(artifact_dir, scenario, "combat-scenario-v2"),
                seeds=[7, 11], policy="balanced", max_battles=4,
                authorization=auth.model_dump(mode="json"), spec=spec.model_dump(mode="json"))


def read_artifact(folder, ref, expected_schema):
    if not isinstance(ref, dict) or set(ref) != {"artifact_id", "sha256", "schema"}:
        raise ValueError("artifact reference fields rejected")
    if not isinstance(ref["artifact_id"], str) or not re.fullmatch(r"[a-f0-9]{64}", ref["artifact_id"]):
        raise ValueError("artifact_id must be a content hash, not a path")
    if ref["schema"] != expected_schema:
        raise ValueError("artifact schema rejected")
    root = Path(folder).resolve(strict=True)
    path = (root / (ref["artifact_id"] + ".json")).resolve(strict=True)
    if path.parent != root:
        raise ValueError("artifact reference escapes frozen root")
    raw = path.read_bytes()
    if sha(raw) != ref["sha256"] or ref["artifact_id"] != ref["sha256"]:
        raise ValueError("artifact hash mismatch")
    return json.loads(raw)


def inspect_frozen(game_root, artifact_dir, request):
    """Verifier preflight: no changes input, candidate authoring or artifact writes."""
    from combat_core.v2.contracts import CombatBundle, Scenario
    from verification_agent.v2.models import Authorization, TaskSpec
    from verification_agent.v2.policy import validate_candidate

    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise ValueError("request fields rejected; frozen artifact refs only")
    if (request["schema_version"] != PROFILE or request["seeds"] != [7, 11] or
            any(type(seed) is not int for seed in request["seeds"]) or request["policy"] != "balanced" or
            type(request["max_battles"]) is not int or request["max_battles"] != 4):
        raise ValueError("unsupported frozen numeric execution profile")
    snapshot = source_snapshot(game_root)
    if snapshot["fingerprint"] != request["game_fingerprint"]:
        raise ValueError("game fingerprint mismatch")
    parsed = {}
    for kind, model, schema in [("baseline", CombatBundle, "combat-bundle-v2"),
                                ("candidate", CombatBundle, "combat-bundle-v2"),
                                ("scenario", Scenario, "combat-scenario-v2")]:
        value = read_artifact(artifact_dir, request[kind], schema)
        try:
            parsed[kind] = model.model_validate(value)
        except ValueError as exc:
            raise ValueError(kind + " schema rejected: " + str(exc)) from None
    auth = Authorization.model_validate(request["authorization"])
    spec = TaskSpec.model_validate(request["spec"])
    if auth.seeds != request["seeds"] or auth.policies != [request["policy"]] or auth.max_simulations != 4:
        raise ValueError("authorization and fixed execution manifest differ")
    validation = validate_candidate(parsed["baseline"].model_dump(), parsed["candidate"].model_dump(), auth, spec)
    if not validation["passed"]:
        raise ValueError("frozen candidate validation failed: " + json.dumps(validation, ensure_ascii=False))
    return {**parsed, "validation": validation, "sources": snapshot}


def verify_frozen(game_root, artifact_dir, request, output):
    """Verifier runs four battles on validated full artifacts; never creates a candidate."""
    bind_trusted_game(game_root)
    request = deepcopy(request)
    checked = inspect_frozen(game_root, artifact_dir, request)
    from combat_core.v2.contracts import Scenario
    from combat_core.v2.simulation import simulate
    from combat_core.v2.report import summarize, report_pairs
    from combat_core.v2.config import config_hash

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    traces = output / "traces"
    traces.mkdir()
    pairs, trace_refs = [], []
    started = time.monotonic()
    for seed in request["seeds"]:
        scenario = Scenario.model_validate({**checked["scenario"].model_dump(), "seed": seed, "strategy": request["policy"]})
        summaries = []
        for label in ("baseline", "candidate"):
            trace = simulate(checked[label], scenario)
            value = trace.model_dump(mode="json")
            raw = encoded(value)
            name = f"{seed}_{label}.json"
            with (traces / name).open("xb") as stream:
                stream.write(raw)
            trace_refs.append(dict(seed=seed, variant=label, path="traces/" + name, sha256=sha(raw)))
            summaries.append(summarize(trace))
        pairs.append(tuple(summaries))
    seconds = time.monotonic() - started
    # Re-read and validate the same bytes and source tree after execution.
    after = inspect_frozen(game_root, artifact_dir, request)
    if checked["sources"] != after["sources"]:
        raise ValueError("game sources changed during verification")
    for kind in ("baseline", "candidate", "scenario"):
        if checked[kind].model_dump(mode="json") != after[kind].model_dump(mode="json"):
            raise ValueError("in-memory or frozen input changed during verification")
    report = report_pairs(config_hash(checked["baseline"]), config_hash(checked["candidate"]), pairs).model_dump(mode="json")
    result = dict(kind="real_frozen_candidate_numeric_boundary_probe", request_id=request["request_id"],
                  author_ref=request["author_ref"], candidate_revision=request["candidate_revision"],
                  request_sha256=sha(encoded(request)), candidate_ref=request["candidate"],
                  model_calls=0, completed_battles=4, simulation_seconds=seconds,
                  structural_verdict="PASS", behavioral_verdict="DESCRIPTIVE", overall_verdict="INCONCLUSIVE",
                  validation=checked["validation"], report=report, trace_refs=trace_refs,
                  frozen_artifact_hashes_unchanged=True, in_memory_inputs_unchanged=True,
                  input_refs={k: request[k] for k in ("baseline", "candidate", "scenario")},
                  source_snapshot=checked["sources"], python=sys.version, pydantic=version("pydantic"),
                  limitations=["Four fixed battles describe observations, not improvement or population noninferiority.",
                               "Legacy Spec criterion exists only for structural-policy compatibility; no acceptance evaluation was inferred.",
                               "Deterministic Author fixture; no LLM requirement interpretation or optimized candidate search.",
                               "Trusted numeric config only; no code/build sandbox, production A2A, durable jobs, authorization service or total budget."])
    with (output / "result.json").open("xb") as stream:
        stream.write(encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    request = author_freeze(TRUSTED_GAME_ROOT, args.output / "artifacts")
    request_raw = encoded(request)
    with (args.output / "request.json").open("xb") as stream:
        stream.write(request_raw)
    result = verify_frozen(TRUSTED_GAME_ROOT, args.output / "artifacts", json.loads(request_raw), args.output / "verification")
    if sha((args.output / "request.json").read_bytes()) != sha(request_raw):
        raise ValueError("frozen request changed")
    files = {p.relative_to(args.output).as_posix(): sha(p.read_bytes()) for p in sorted(args.output.rglob("*")) if p.is_file()}
    sources = {Path(__file__).name: sha(Path(__file__).read_bytes()),
               "test_frozen_candidate_probe.py": sha(Path(__file__).with_name("test_frozen_candidate_probe.py").read_bytes())}
    with (args.output / "manifest.json").open("xb") as stream:
        stream.write(encoded(dict(files=files, probe_sources=sources, new_model_calls=0, new_game_battles=4)))
    print(json.dumps(dict(output=str(args.output.resolve()), completed_battles=result["completed_battles"],
                          structural_verdict=result["structural_verdict"], overall_verdict=result["overall_verdict"],
                          manifest_sha256=sha((args.output / "manifest.json").read_bytes())), ensure_ascii=False))


if __name__ == "__main__":
    main()
