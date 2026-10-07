"""Read-only adapter to the trusted combat-foundation checkout.

Runs only closed numeric candidates. This is NOT a sandbox for generated code.
No model credential, shell command, or dynamically chosen module is accepted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .contracts import ExperimentPlan, canonical, fingerprint


def source_fingerprint(root: Path) -> str:
    roots = [root / "game-core" / "combat_core", root / "services" / "verification-agent" / "verification_agent"]
    paths = [p for folder in roots for p in folder.rglob("*.py") if p.name != "__init__.py"]
    paths += [root / "configs/combat/v2/baseline.json", root / "configs/combat/v2/scenario.json"]
    if not paths or not all(p.is_file() for p in paths):
        raise ValueError("incomplete game checkout")
    h = hashlib.sha256()
    for path in sorted(paths):
        h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


class CombatAdapter:
    def __init__(self, root: Path, python: Path | None = None):
        self.root = root.resolve(strict=True)
        self.python = python or Path(sys.executable)

    def _call(self, operation: str, plan: ExperimentPlan) -> dict:
        # Construct an allowlisted environment rather than copying developer credentials.
        env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}}
        env.update(PYTHONPATH=str(Path(__file__).resolve().parents[2]), PYTHONUTF8="1",
                   LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
        proc = subprocess.run([str(self.python), "-m", "agent_workbench.verification.combat_worker",
                               operation, "--game-root", str(self.root)], input=canonical(plan),
                              text=True, encoding="utf-8", capture_output=True, env=env, timeout=180)
        if proc.returncode:
            raise ValueError("game worker rejected input: " + proc.stderr[-2000:])
        return json.loads(proc.stdout)

    def validate(self, plan):
        return self._call("validate", plan)

    def execute(self, plan):
        return self._call("execute", plan)


def work(root: Path, operation: str, plan: ExperimentPlan) -> dict:
    if source_fingerprint(root) != plan.game_fingerprint:
        raise ValueError("game source changed since plan freeze")
    sys.path[:0] = [str(root / "game-core"), str(root / "services/verification-agent")]
    from combat_core.v2.config import load_bundle, load_scenario, config_hash
    from combat_core.v2.contracts import CombatBundle, Scenario
    from combat_core.v2.report import summarize
    from combat_core.v2.simulation import simulate
    from verification_agent.v2.models import Authorization, TaskSpec
    from verification_agent.v2.policy import apply_changes, validate_candidate

    base = load_bundle(root / "configs/combat/v2/baseline.json")
    scenario = load_scenario(root / "configs/combat/v2/scenario.json")
    bounds = {key: value.model_dump() for key, value in plan.bounds.items()}
    # Legacy policy consumes a Spec. Its criterion here is a DESCRIPTIVE check only;
    # the new report never promotes it to a population statistical verdict.
    criterion = dict(metric="win_rate_delta", op="gte", target=0, policy=plan.policies[0])
    auth = Authorization(actor="local-operator", note=plan.request, scope=bounds,
                         seeds=plan.seeds, policies=plan.policies, min_samples=1,
                         max_model_calls=0, max_simulations=plan.max_battles, required_criteria=[criterion])
    spec = TaskSpec(goal=plan.request, mutable_scope=list(bounds), parameter_constraints=bounds,
                    acceptance_criteria=[criterion])
    candidate, diff = apply_changes(base.model_dump(), [c.model_dump() for c in plan.changes], auth, spec)
    validation = validate_candidate(base.model_dump(), candidate, auth, spec)
    if not validation["passed"]:
        raise ValueError(canonical(validation))
    if operation == "validate":
        return validation
    candidate = CombatBundle.model_validate(candidate)
    rows = []
    for policy in plan.policies:
        for seed in plan.seeds:
            case = Scenario.model_validate({**scenario.model_dump(), "seed": seed, "strategy": policy})
            pair = dict(seed=seed, policy=policy)
            for label, bundle in (("baseline", base), ("candidate", candidate)):
                trace = simulate(bundle, case)
                pair[label] = summarize(trace).model_dump(mode="json")
                pair[label]["trace_sha256"] = hashlib.sha256(canonical(trace).encode("utf-8")).hexdigest()
            rows.append(pair)
    if source_fingerprint(root) != plan.game_fingerprint:
        raise ValueError("game source changed during experiment; result not accepted")
    return dict(rows=rows, diff=diff, validation=validation, game_fingerprint=plan.game_fingerprint,
                plan_hash=fingerprint(plan), baseline_hash=config_hash(base), candidate_hash=config_hash(candidate),
                scenario_hash=fingerprint(scenario),
                worker_python=sys.version, provenance="real-combat-core; no model; no full traces stored")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["validate", "execute"])
    parser.add_argument("--game-root", type=Path, required=True)
    args = parser.parse_args()
    p = ExperimentPlan.model_validate_json(sys.stdin.read())
    print(canonical(work(args.game_root.resolve(strict=True), args.operation, p)))


if __name__ == "__main__":
    main()
