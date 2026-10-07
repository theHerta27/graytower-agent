"""Read-only combat calibration; summaries only, no full traces written.

Run with combat-foundation/.venv/Scripts/python.exe and PYTHONDONTWRITEBYTECODE=1.
All conditions are exploratory; this is neither player research nor a release test.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT.parent / "combat-foundation"
sys.path.insert(0, str(GAME / "game-core"))
from combat_core.v2.config import canonical, config_hash, load_bundle, scenario_hash
from combat_core.v2.contracts import CombatBundle, Scenario
from combat_core.v2.simulation import simulate
from combat_core.v2.report import summarize
from combat_core.v2.state import ActionRequest, initial_state
from combat_core.v2.effects import resolve_action, end_statuses
from combat_core.v2.boss import apply_phase_transition, choose_enemy_action, resolve_enemy_action
from combat_core.v2.trace import EventRecorder

MAX_SIMULATIONS = 240
POLICIES = ["balanced", "survival"]
SOURCE_PATHS = ["configs/combat/v2/baseline.json", "configs/combat/v2/scenario.json"] + [
    f"game-core/combat_core/v2/{name}.py" for name in
    ["contracts", "state", "simulation", "scheduler", "effects", "boss", "bots", "report", "config", "trace"]
]


def sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def changed(bundle, *, boss_atk=None, variant="baseline"):
    data = bundle.model_dump(mode="json", by_alias=True)
    if boss_atk is not None:
        data["boss_stats"]["atk"] = boss_atk
    if variant == "breaker_multiplier_1_7":
        data["skills"]["breaker_skill"]["multiplier"] = 1.7
    elif variant == "phase2_toughness_288":
        data["phases"][1]["toughness_max"] = 288
    elif variant != "baseline":
        raise ValueError(variant)
    return CombatBundle.model_validate(data)


def mechanism_checks(bundle):
    """Exercise existing rule boundaries directly, without adding any support rule."""
    state = initial_state(bundle, Scenario())
    defaults = {
        "skill_points": state.skill_points,
        "skill_points_max": bundle.rules.skill_points_max,
        "units": {u: {"hp": state.units[u].hp, "energy": state.units[u].energy,
                       "energy_max": state.units[u].energy_max} for u in bundle.party},
    }
    rec, rng = EventRecorder(), random.Random(7)
    state.current_actor = "support_01"
    state.normal_turn_count = 1
    state.units["support_01"].energy = 120
    resolve_action(bundle, state, ActionRequest(actor_id="support_01", skill_id="support_ultimate",
                  target_ids=bundle.party, reason_code="calibration"), rng, rec)
    shield_value = {u: state.units[u].shields[0].value for u in bundle.party}
    end_statuses(bundle, state, "support_01", rec)
    same_turn = state.units["support_01"].shields[0].remaining
    state.normal_turn_count = 2
    end_statuses(bundle, state, "striker_01", rec)
    teammate_first = state.units["striker_01"].shields[0].remaining
    state.normal_turn_count = 3
    end_statuses(bundle, state, "striker_01", rec)
    teammate_expired = not state.units["striker_01"].shields
    state.normal_turn_count = 4
    end_statuses(bundle, state, "support_01", rec)
    own_next = state.units["support_01"].shields[0].remaining
    state.normal_turn_count = 5
    end_statuses(bundle, state, "support_01", rec)
    own_second_expired = not state.units["support_01"].shields
    assert shield_value == dict.fromkeys(bundle.party, 324)
    assert same_turn == 2 and teammate_first == 1 and own_next == 1
    assert teammate_expired and own_second_expired

    state = initial_state(bundle, Scenario())
    rec, rng = EventRecorder(), random.Random(7)
    state.units[bundle.boss_id].hp = 4000
    apply_phase_transition(bundle, state, rec)
    state.current_actor = bundle.boss_id
    resolve_enemy_action(bundle, state, choose_enemy_action(bundle, state, bundle.boss_id), rng, rec)
    assert state.units[bundle.boss_id].charging == "boss_charge"
    state.units[bundle.boss_id].toughness = 90
    state.current_actor = "breaker_01"
    state.normal_used = False
    resolve_action(bundle, state, ActionRequest(actor_id="breaker_01", skill_id="breaker_skill",
                  target_ids=[bundle.boss_id], reason_code="calibration"), rng, rec)
    assert state.units[bundle.boss_id].charging is None
    assert any(e.kind == "charge_cancelled" for e in rec.events)
    return {
        "default_initial_state": defaults,
        "shield_existing_ultimate": {"value_each": shield_value, "configured_duration": 2,
            "caster_same_turn_remaining": same_turn, "teammate_first_turn_end_remaining": teammate_first,
            "teammate_second_turn_end_expired": teammate_expired,
            "caster_next_turn_end_remaining": own_next,
            "caster_second_following_turn_end_expired": own_second_expired},
        "phase3_control_immune_but_break_cancels_charge": True,
        "charge_cancel_excerpt": [{"kind": e.kind, "av": str(e.av), "payload": e.payload.model_dump(mode="json")}
                                  for e in rec.events if e.kind in ["charge_started", "break_triggered", "charge_cancelled"]],
        "prebattle_support": "NOT_IMPLEMENTED: no Scenario support/shield input; direct boundary setup above is not a playable feature",
    }


def stats(rows):
    wins = [r for r in rows if r["outcome"] == "win"]
    phase_stats = {}
    for phase in ["phase_1", "phase_2", "phase_3"]:
        entered = [r["phases"][phase] for r in rows if r["phases"].get(phase)]
        completed = [p for p in entered if p["completed"]]
        phase_stats[phase] = {"entered": len(entered), "completed": len(completed),
            "completed_median_av": statistics.median([float(Fraction(p["elapsed_av"])) for p in completed]) if completed else None}
    return {"n": len(rows), "outcomes": dict(Counter(r["outcome"] for r in rows)),
            "win_rate": len(wins)/len(rows),
            "winning_median_av": statistics.median([r["elapsed_av_float"] for r in wins]) if wins else None,
            "phases": phase_stats,
            "mechanism_runs": {k: sum(r["mechanism_counts"].get(k, 0) > 0 for r in rows)
                               for k in ["summoned", "charge_started", "charge_released", "charge_cancelled"]}}


def pairs(before, after):
    a, b = {r["seed"]: r for r in before}, {r["seed"]: r for r in after}
    assert a.keys() == b.keys()
    common = [seed for seed in a if a[seed]["outcome"] == b[seed]["outcome"] == "win"]
    change = [(b[s]["elapsed_av_float"] / a[s]["elapsed_av_float"] - 1) * 100 for s in common]
    out = {"outcome_transitions": dict(Counter(a[s]["outcome"] + "->" + b[s]["outcome"] for s in a)),
           "common_wins": len(common), "common_win_median_av_change_percent": statistics.median(change) if change else None,
           "common_win_av_change_percent_range": [min(change), max(change)] if change else None,
           "common_win_faster": sum(v < 0 for v in change), "common_win_equal": sum(v == 0 for v in change),
           "common_win_slower": sum(v > 0 for v in change), "completed_phase_pairs": {}}
    for phase in ["phase_1", "phase_2", "phase_3"]:
        eligible = [s for s in a if a[s]["phases"].get(phase) and b[s]["phases"].get(phase)
                    and a[s]["phases"][phase]["completed"] and b[s]["phases"][phase]["completed"]]
        values = [(float(Fraction(b[s]["phases"][phase]["elapsed_av"])) /
                   float(Fraction(a[s]["phases"][phase]["elapsed_av"])) - 1)*100 for s in eligible]
        out["completed_phase_pairs"][phase] = {"n": len(values), "median_change_percent": statistics.median(values) if values else None}
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "research/evidence/game-semantics-calibration-20261004.json")
    args = parser.parse_args()
    started = time.perf_counter()
    source_before = {p: sha(GAME / p) for p in SOURCE_PATHS}
    baseline = load_bundle(GAME / "configs/combat/v2/baseline.json")
    base_hash = config_hash(baseline)
    runs = []

    def run(bundle, scenario, context, variant, stage):
        if len(runs) >= MAX_SIMULATIONS:
            raise RuntimeError("simulation budget exhausted")
        tick = time.perf_counter()
        trace = simulate(bundle, scenario)
        metrics = summarize(trace)
        counts = Counter(e.kind for e in trace.events)
        row = {"stage": stage, "context": context, "variant": variant, "seed": scenario.seed,
               "strategy": scenario.strategy, "config_hash": config_hash(bundle), "scenario_hash": scenario_hash(scenario),
               "scenario": scenario.model_dump(mode="json"), "outcome": metrics.outcome,
               "elapsed_av": metrics.elapsed_av, "elapsed_av_float": float(Fraction(metrics.elapsed_av)),
               "survivors": metrics.survivors, "phases": metrics.phases,
               "mechanism_counts": {k: counts[k] for k in ["summoned", "summon_fallback", "charge_started", "charge_released", "charge_cancelled", "break_triggered", "enrage_changed"]},
               "boss_breaks": sum(x["target"] == bundle.boss_id for x in metrics.breaks),
               "shield_absorbed": metrics.shield_absorbed, "skill_points": metrics.resources.get("skill_points", {}),
               "event_count": len(trace.events), "wall_seconds": time.perf_counter() - tick}
        if stage == "main" and scenario.seed == 1001 and scenario.strategy == "balanced" and context == "standard":
            row["mechanism_excerpt"] = [{"kind": e.kind, "av": str(e.av), "payload": e.payload.model_dump(mode="json")}
                for e in trace.events if e.kind in ["phase_changed", "summoned", "charge_started", "charge_released", "charge_cancelled"]]
        runs.append(row)
        return row

    scout_seeds = [1, 7, 11, 19]
    scouts = []
    # Predeclared selection rule: nearest baseline win rate to 50%; lower attack wins ties.
    for attack in [245, 315, 400, 490]:
        bundle = changed(baseline, boss_atk=attack)
        rows = [run(bundle, Scenario(seed=s, strategy=p), f"boss_atk_{attack}", "baseline", "scout")
                for p in POLICIES for s in scout_seeds]
        scouts.append({"boss_atk": attack, **stats(rows)})
    selected = min(scouts, key=lambda x: (abs(x["win_rate"]-.5), x["boss_atk"]))["boss_atk"]
    print(f"Scout: {[(s['boss_atk'], s['outcomes']) for s in scouts]}; selected attack={selected}", flush=True)
    main_seeds = list(range(1001, 1011))
    contexts = [dict(id="standard", initial_skill_points=3, boss_atk=175),
                dict(id="low_sp", initial_skill_points=0, boss_atk=175),
                dict(id="attack_stress", initial_skill_points=3, boss_atk=selected)]
    variants = ["baseline", "breaker_multiplier_1_7", "phase2_toughness_288"]
    summaries = []
    for context in contexts:
        for policy in POLICIES:
            group = {}
            for variant in variants:
                bundle = changed(baseline, boss_atk=context["boss_atk"], variant=variant)
                rows = [run(bundle, Scenario(seed=s, strategy=policy, initial_skill_points=context["initial_skill_points"]),
                            context["id"], variant, "main") for s in main_seeds]
                group[variant] = rows
                summary = {"context": context["id"], "strategy": policy, "variant": variant, **stats(rows)}
                if variant != "baseline":
                    summary["paired_comparison"] = pairs(group["baseline"], rows)
                summaries.append(summary)
                print(json.dumps(summary, ensure_ascii=False), flush=True)
    source_after = {p: sha(GAME / p) for p in SOURCE_PATHS}
    assert source_before == source_after and config_hash(baseline) == base_hash
    result = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "kind": "exploratory_small_sample_calibration",
        "limitations": ["Bot outcomes only; not player win rate or real time speed", "No statistical release/NI claim",
            "Stress attack selected from baseline scout only; main seeds do not constitute a sealed release holdout",
            "Same seed pairs runs, not every RNG draw after divergent actions", "No production source/config edits or new support feature"],
        "game_root": str(GAME), "git_head": subprocess.check_output(["git", "-C", str(GAME), "rev-parse", "HEAD"], text=True).strip(),
        "python_executable": sys.executable, "python_version": sys.version,
        "probe_sha256": sha(Path(__file__)), "source_sha256_before": source_before,
        "source_sha256_after": source_after, "sources_unchanged": source_before == source_after,
        "canonical_baseline_hash": base_hash, "simulation_cap": MAX_SIMULATIONS, "simulations_executed": len(runs),
        "full_traces_written": 0, "wall_seconds": time.perf_counter() - started,
        "scout_seeds": scout_seeds, "scouts": scouts, "selected_stress_attack": selected,
        "stress_selection_rule": "Choose scout baseline win rate nearest 0.5 across 2 policies; lower attack breaks ties",
        "main_seeds": main_seeds, "contexts": contexts, "variants": {
            "baseline": {}, "breaker_multiplier_1_7": {"/skills/breaker_skill/multiplier": [1.4, 1.7]},
            "phase2_toughness_288": {"/phases/1/toughness_max": [360, 288]}},
        "mechanism_checks": mechanism_checks(baseline), "summary": summaries, "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Saved {args.output}; {len(runs)} simulations; {result['wall_seconds']:.3f}s; original sources unchanged", flush=True)


if __name__ == "__main__":
    main()
