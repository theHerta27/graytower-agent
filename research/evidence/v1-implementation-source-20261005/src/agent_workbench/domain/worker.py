"""Trusted numeric-only child entrypoint; Verifier never invokes candidate authoring."""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
from statistics import median
import sys
import time

# -I suppresses arbitrary caller/import paths. Only this fixed adapter and the
# explicitly trusted, fingerprinted game checkout are added below.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _shared import (Artifacts, FIELD, POLICIES, PROFILE, SCOPE, check_changes,
                     check_plan, digest, encoded, source_snapshot, trusted_root, valid_hash)

MANIFEST_FIELDS = {"schema_version", "kind", "profile", "author", "request", "parent_manifest", "baseline",
                   "candidate", "scenario", "sources", "schema", "rules", "environment", "diff", "validation"}


def load_game(root):
    root = trusted_root(root)
    snapshot = source_snapshot(root)
    sys.path[:0] = [str(root / "game-core"), str(root / "services/verification-agent")]
    from combat_core.v2.config import load_bundle, load_scenario
    from combat_core.v2.contracts import CombatBundle, Scenario
    base = load_bundle(root / "configs/combat/v2/baseline.json").model_dump(mode="json")
    scenario = load_scenario(root / "configs/combat/v2/scenario.json").model_dump(mode="json")
    if base["skills"]["breaker_skill"]["multiplier"] != 1.4:
        raise ValueError("audited V1 baseline expects breaker_skill multiplier 1.4")
    schema = {"bundle": CombatBundle.model_json_schema(), "scenario": Scenario.model_json_schema()}
    rules = {"game_rules": base["rules"], "numeric_scope": SCOPE,
             "policy_source": "services/verification-agent/verification_agent/v2/policy.py",
             "structural_layers": ["schema", "references", "rules", "safety"],
             "behavioral_acceptance": None}
    environment = {"python": sys.version, "pydantic": version("pydantic"),
                   "python_executable_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                   "base_executable_sha256": hashlib.sha256(Path(sys._base_executable).read_bytes()).hexdigest(),
                   "adapter_sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in sorted(Path(__file__).parent.glob("*.py"))}}
    return {"root": root, "snapshot": snapshot, "base": base, "scenario": scenario,
            "schema": schema, "rules": rules, "environment": environment}


def policy_context(request):
    from verification_agent.v2.models import Authorization, TaskSpec
    # The legacy validator requires a criterion. It is only a schema bridge;
    # no behavioral criterion is adopted or evaluated by this product profile.
    criterion = {"metric": "win_rate_delta", "op": "gte", "target": 0, "policy": "balanced"}
    auth = Authorization(actor="config", note=request, scope=SCOPE, seeds=[7], policies=list(POLICIES),
                         min_samples=1, max_model_calls=0, max_simulations=0)
    spec = TaskSpec(goal=request, mutable_scope=[FIELD], parameter_constraints=SCOPE,
                    acceptance_criteria=[criterion])
    return auth, spec


def validate(game, candidate, request):
    from combat_core.v2.contracts import CombatBundle
    from verification_agent.v2.policy import validate_candidate
    auth, spec = policy_context(request)
    # Preserve raw values through validation so schema coercion cannot conceal a
    # string/bool/type edit or an unauthorized extra field.
    value = candidate.get("skills", {}).get("breaker_skill", {}).get("multiplier")
    check_changes(request, [{"path": FIELD, "value": value}], "config")
    validation = validate_candidate(game["base"], candidate, auth, spec)
    if not validation["passed"]:
        raise ValueError("candidate hard-rule validation failed: " + json.dumps(validation, ensure_ascii=False))
    parsed = CombatBundle.model_validate(candidate)
    if encoded(parsed.model_dump(mode="json")) != encoded(candidate):
        raise ValueError("candidate requires forbidden schema coercion")
    return validation


def describe(game):
    return {"profile": PROFILE, "version": "1", "game_contract_version": game["base"]["contract_version"],
            "source_fingerprint": game["snapshot"]["fingerprint"], "schema": game["schema"]["bundle"],
            "scenario_schema": game["schema"]["scenario"], "rules": game["rules"], "policies": list(POLICIES),
            "catalog": [{"path": FIELD, "label": "击破手战技倍率", "value": 1.4, "min": 1.4, "max": 1.7,
                         "type": "number", "rule": "V1审计范围1.4–1.7；保留战技消耗、目标和削韧规则，收益需另行验证。"}],
            "example": {"path": FIELD, "before": 1.4, "after": 1.7,
                        "explanation": "待验证的数值建议；不能据此承诺通关更快或胜率更高。"},
            "limitations": ["仅可信本地数值配置，非不可信代码沙箱。", "范围来自产品审计约束；Schema和硬规则来自真实游戏核心。"]}


def author(game, artifacts, payload):
    if set(payload) != {"request", "changes", "author", "parent_manifest"}:
        raise ValueError("unexpected author input")
    check_changes(payload["request"], payload["changes"], payload["author"])
    if payload["parent_manifest"] is not None:
        inspect(game, artifacts, valid_hash(payload["parent_manifest"]))
    from verification_agent.v2.policy import apply_changes
    auth, spec = policy_context(payload["request"])
    candidate, diff = apply_changes(game["base"], payload["changes"], auth, spec)
    validation = validate(game, candidate, payload["request"])
    unchanged(game)
    manifest = {"schema_version": "candidate-manifest-v1", "kind": "numeric_config", "profile": PROFILE,
                "author": payload["author"], "request": payload["request"], "parent_manifest": payload["parent_manifest"],
                "baseline": artifacts.put(game["base"], "combat-bundle-v2"),
                "candidate": artifacts.put(candidate, "combat-bundle-v2"),
                "scenario": artifacts.put(game["scenario"], "combat-scenario-v2"),
                "sources": artifacts.put(game["snapshot"], "game-sources-v1"),
                "schema": artifacts.put(game["schema"], "game-schema-v1"),
                "rules": artifacts.put(game["rules"], "game-rules-v1"),
                "environment": artifacts.put(game["environment"], "worker-environment-v1"),
                "diff": diff, "validation": validation}
    ref = artifacts.put(manifest, "candidate-manifest-v1")
    return {"manifest_hash": ref["sha256"], "manifest": manifest, "diff": diff, "validation": validation}


def inspect(game, artifacts, manifest_hash):
    manifest = artifacts.read(manifest_hash)
    if (set(manifest) != MANIFEST_FIELDS or manifest["schema_version"] != "candidate-manifest-v1"
            or manifest["kind"] != "numeric_config" or manifest["profile"] != PROFILE or manifest["author"] != "config"):
        raise ValueError("unsupported or malformed candidate manifest")
    if manifest["parent_manifest"] is not None:
        parent = artifacts.read(valid_hash(manifest["parent_manifest"]))
        if parent.get("schema_version") != "candidate-manifest-v1":
            raise ValueError("wrong parent manifest reference")
    refs = {"baseline": ("combat-bundle-v2", game["base"]), "scenario": ("combat-scenario-v2", game["scenario"]),
            "sources": ("game-sources-v1", game["snapshot"]), "schema": ("game-schema-v1", game["schema"]),
            "rules": ("game-rules-v1", game["rules"]), "environment": ("worker-environment-v1", game["environment"])}
    for name, (schema, expected) in refs.items():
        if encoded(artifacts.read_ref(manifest[name], schema)) != encoded(expected):
            raise ValueError(name + " fingerprint/content drift")
    candidate = artifacts.read_ref(manifest["candidate"], "combat-bundle-v2")
    validation = validate(game, candidate, manifest["request"])
    if encoded(validation) != encoded(manifest["validation"]) or encoded(validation["diff"]) != encoded(manifest["diff"]):
        raise ValueError("manifest diff/validation does not match independent inspection")
    unchanged(game)
    return {"manifest_hash": manifest_hash, "manifest": manifest, "diff": validation["diff"], "validation": validation}


def unchanged(game):
    if source_snapshot(game["root"]) != game["snapshot"]:
        raise ValueError("game source fingerprint changed during operation")


def metrics(rows, policies):
    result = {}
    for policy in policies:
        pairs = [row for row in rows if row["policy"] == policy]
        group = {"pairs": len(pairs), "transitions": dict(Counter(row["baseline"]["outcome"] + "->" + row["candidate"]["outcome"] for row in pairs))}
        for label in ("baseline", "candidate"):
            counts = Counter(row[label]["outcome"] for row in pairs)
            group[label] = {"wins": counts["win"], "losses": counts["loss"], "timeouts": counts["timeout"],
                            "win_rate": counts["win"] / len(pairs)}
        common = [row for row in pairs if row["baseline"]["outcome"] == row["candidate"]["outcome"] == "win"]
        ratios = [Fraction(row["candidate"]["elapsed_av"]) / Fraction(row["baseline"]["elapsed_av"]) for row in common]
        group.update(common_wins=len(common), paired_av_ratio_median=float(median(ratios)) if ratios else None,
                     paired_av_deltas=[{"seed": row["seed"], "delta_av": str(Fraction(row["candidate"]["elapsed_av"]) - Fraction(row["baseline"]["elapsed_av"]))} for row in common])
        result[policy] = group
    return result


def verify(game, artifacts, payload):
    if set(payload) != {"manifest_hash", "seeds", "policies"}:
        raise ValueError("Verifier accepts frozen hash references and execution plan only")
    check_plan(payload["seeds"], payload["policies"])
    frozen = inspect(game, artifacts, payload["manifest_hash"])
    manifest = frozen["manifest"]
    from combat_core.v2.contracts import CombatBundle, Scenario
    from combat_core.v2.simulation import simulate
    from combat_core.v2.report import summarize
    bundles = {label: CombatBundle.model_validate(artifacts.read_ref(manifest[label], "combat-bundle-v2"))
               for label in ("baseline", "candidate")}
    before = {label: encoded(bundle.model_dump(mode="json")) for label, bundle in bundles.items()}
    rows, traces = [], []
    started = time.monotonic()
    for policy in payload["policies"]:
        for seed in payload["seeds"]:
            scenario = Scenario.model_validate({**game["scenario"], "seed": seed, "strategy": policy})
            row = {"seed": seed, "policy": policy}
            for label, bundle in bundles.items():
                trace = simulate(bundle, scenario)
                ref = artifacts.put(trace.model_dump(mode="json"), "combat-trace-v2")
                traces.append({**ref, "seed": seed, "policy": policy, "variant": label})
                row[label] = {**summarize(trace).model_dump(mode="json"), "trace_sha256": ref["sha256"]}
            rows.append(row)
    after = inspect(game, artifacts, payload["manifest_hash"])
    if frozen != after or any(encoded(bundle.model_dump(mode="json")) != before[label] for label, bundle in bundles.items()):
        raise ValueError("frozen or in-memory input changed during verification")
    identity = {"manifest_hash": payload["manifest_hash"], "execution_hash": digest(payload),
                "game_fingerprint": game["snapshot"]["fingerprint"],
                "input_refs": {key: manifest[key] for key in ("baseline", "candidate", "scenario")},
                "seeds": payload["seeds"], "policies": payload["policies"]}
    result = {"profile": PROFILE, "identity": identity, "manifest_hash": payload["manifest_hash"],
              "rows": rows, "metrics": metrics(rows, payload["policies"]), "trace_refs": traces,
              "validation": frozen["validation"], "completed_battles": len(rows) * 2,
              "simulation_seconds": time.monotonic() - started, "structural_verdict": "PASS",
              "behavioral_verdict": "DESCRIPTIVE", "overall_verdict": "INCONCLUSIVE", "model_calls": 0,
              "limitations": ["固定样本只描述观测，不证明总体胜率、非劣性或玩家通关体验改善。",
                              "legacy criterion仅用于旧结构校验兼容，未作为行为验收标准。",
                              "仅可信数值配置；无代码/build沙箱或Unity验收。"]}
    result["report_ref"] = artifacts.put(result, "verification-report-v1")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("describe", "author", "inspect", "verify"))
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("object input required")
    game = load_game(args.game_root)
    artifacts = Artifacts(args.artifacts)
    if args.operation == "describe":
        if payload:
            raise ValueError("describe accepts no payload")
        result = describe(game)
    elif args.operation == "author":
        result = author(game, artifacts, payload)
    elif args.operation == "inspect":
        if set(payload) != {"manifest_hash"}:
            raise ValueError("inspect accepts only manifest hash")
        result = inspect(game, artifacts, valid_hash(payload["manifest_hash"]))
    else:
        result = verify(game, artifacts, payload)
    unchanged(game)
    sys.stdout.buffer.write(encoded(result))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, KeyError, OSError) as exc:
        sys.stderr.write(str(exc))
        raise SystemExit(2)
