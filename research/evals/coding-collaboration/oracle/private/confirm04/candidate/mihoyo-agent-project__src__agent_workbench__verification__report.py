"""Descriptive, paired evidence. This module cannot certify population noninferiority."""
from collections import Counter
from fractions import Fraction
from statistics import median

from .contracts import ExperimentPlan, fingerprint


def build_report(plan: ExperimentPlan, result: dict) -> dict:
    if result.get("plan_hash") != fingerprint(plan):
        raise ValueError("receipt plan hash mismatch")
    if result.get("game_fingerprint") != plan.game_fingerprint:
        raise ValueError("game fingerprint mismatch")
    expected = frozenset((policy, seed) for policy in plan.policies for seed in plan.seeds)
    rows = result.get("rows", [])
    actual = [(r["policy"], r["seed"]) for r in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("missing, duplicate or foreign paired result")
    groups = {}
    for policy in plan.policies:
        data = [r for r in rows if r["policy"] == policy]
        ratios = []
        transitions = Counter()
        for row in data:
            b, c = row["baseline"], row["candidate"]
            if b["outcome"] not in ("win", "loss", "timeout") or c["outcome"] not in ("win", "loss", "timeout"):
                raise ValueError("invalid battle outcome")
            bav, cav = Fraction(b["elapsed_av"]), Fraction(c["elapsed_av"])
            if bav <= 0 or cav <= 0:
                raise ValueError("invalid nonpositive battle AV")
            transitions[f'{b["outcome"]}->{c["outcome"]}'] += 1
            if b["outcome"] == c["outcome"] == "win":
                ratios.append(cav / bav)
        bw = sum(r["baseline"]["outcome"] == "win" for r in data)
        cw = sum(r["candidate"]["outcome"] == "win" for r in data)
        groups[policy] = dict(pairs=len(data), baseline_win_rate=bw / len(data),
                              candidate_win_rate=cw / len(data), transitions=dict(transitions),
                              common_wins=len(ratios), paired_av_ratio_median=float(median(ratios)) if ratios else None,
                              no_observed_win_regressions=not any(r["baseline"]["outcome"] == "win" and
                                                               r["candidate"]["outcome"] != "win" for r in data))
    return dict(profile=plan.profile, verdict="DESCRIPTIVE_ONLY", plan_hash=fingerprint(plan),
                simulated_battles=plan.battles, policies=groups,
                limitation="固定小样本描述；不证明总体胜率、严格非劣或玩家通关时间改善。未经人工采纳不修改游戏。")
