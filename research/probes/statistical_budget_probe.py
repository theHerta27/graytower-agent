"""Fixed-sample paired NI budget audit. No game, network, or model execution.

Requires Python 3.11+ and NumPy. Exact Clopper-Pearson bounds use an in-file
regularized incomplete-beta continued fraction and bisection; numerical checks
use independent finite binomial sums and published SciPy examples.
"""
from __future__ import annotations

import argparse
import csv
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np

ALPHA = 0.05 / 12
MARGIN = 0.02
CELLS = 6


def beta_cf(a: float, b: float, x: float) -> float:
    """Continued fraction, modified Lentz; no statistical approximation."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    tiny = 1e-300
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    value = d
    for m in range(1, 10001):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        value *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        change = d * c
        value *= change
        if abs(change - 1.0) < 3e-14:
            return value
    raise ArithmeticError('incomplete beta continued fraction did not converge')


def regularized_beta(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return front * beta_cf(a, b, x) / a
    return 1.0 - front * beta_cf(b, a, 1 - x) / b


def beta_quantile(probability: float, a: int, b: int) -> float:
    low, high = 0.0, 1.0
    for _ in range(54):
        mid = (low + high) / 2
        if regularized_beta(a, b, mid) < probability:
            low = mid
        else:
            high = mid
    return (low + high) / 2


@lru_cache(maxsize=None)
def cp_lower(n: int, k: int, alpha: float = ALPHA) -> float:
    if not 0 <= k <= n:
        raise ValueError('invalid count')
    if k == 0:
        return 0.0
    if k == n:
        return math.exp(math.log(alpha) / n)
    return beta_quantile(alpha, k, n - k + 1)


@lru_cache(maxsize=None)
def cp_upper(n: int, k: int, alpha: float = ALPHA) -> float:
    if not 0 <= k <= n:
        raise ValueError('invalid count')
    if k == n:
        return 1.0
    if k == 0:
        return -math.expm1(math.log(alpha) / n)
    return 1.0 - cp_lower(n, n - k, alpha)


def difference_lower(n: int, b: int, c: int) -> float:
    if b + c > n:
        raise ValueError('improvement and regression counts are mutually exclusive')
    return cp_lower(n, b) - cp_upper(n, c)


def direct_binomial_sum(n: int, p: float, start: int, stop: int) -> float:
    return math.fsum(math.comb(n, k) * p**k * (1 - p)**(n - k)
                     for k in range(start, stop))


def numeric_checks() -> dict:
    checks = []
    for n in (5, 50, 272, 1000):
        for k in sorted({0, 1, n // 10, n // 2, n - 1, n}):
            lo, hi = cp_lower(n, k), cp_upper(n, k)
            assert 0 <= lo <= k / n <= hi <= 1
            if n <= 50 and 0 < k < n:
                lower_tail = direct_binomial_sum(n, lo, k, n + 1)
                upper_tail = direct_binomial_sum(n, hi, 0, k + 1)
                assert abs(lower_tail - ALPHA) < 1e-10
                assert abs(upper_tail - ALPHA) < 1e-10
                checks.append({'n': n, 'k': k, 'lower_tail': lower_tail,
                               'upper_tail': upper_tail})
    scipy_example = [cp_lower(50, 7, .025), cp_upper(50, 7, .025)]
    assert abs(scipy_example[0] - .05819170033997342) < 1e-11
    assert abs(scipy_example[1] - .26739600249700846) < 1e-11
    assert difference_lower(271, 0, 0) < -MARGIN
    assert difference_lower(272, 0, 0) >= -MARGIN
    return {'passed': True, 'independent_tail_checks': checks,
            'scipy_published_n50_k7_two_sided95': scipy_example}


def exact_power_small(n: int, pb: float, pc: float) -> float:
    """Finite multinomial enumeration used as an independent MC cross-check."""
    neutral = 1 - pb - pc
    total = []
    for b in range(n + 1):
        for c in range(n - b + 1):
            if difference_lower(n, b, c) < -MARGIN:
                continue
            count_neutral = n - b - c
            probability = (math.comb(n, b) * math.comb(n - b, c)
                           * pb**b * pc**c * neutral**count_neutral)
            total.append(probability)
    return math.fsum(total)


def power(n: int, pb: float, pc: float, trials: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    counts = rng.multinomial(n, [pb, pc, 1 - pb - pc], size=trials)
    b, c = counts[:, 0], counts[:, 1]
    ub, bi = np.unique(b, return_inverse=True)
    uc, ci = np.unique(c, return_inverse=True)
    lows = np.array([cp_lower(n, int(x)) for x in ub])[bi]
    highs = np.array([cp_upper(n, int(x)) for x in uc])[ci]
    passes = int(np.count_nonzero(lows - highs >= -MARGIN))
    estimate = passes / trials
    mc_lo, mc_hi = cp_lower(trials, passes, .025), cp_upper(trials, passes, .025)
    row = dict(n=n, p_improvement=pb, p_regression=pc,
               true_delta=pb - pc, discordance=pb + pc,
               expected_b=n * pb, expected_c=n * pc,
               rounded_expected_counts_lower=difference_lower(n, round(n * pb), round(n * pc)),
               trials=trials, rng_seed=seed, passed=passes,
               cell_pass_probability_estimate=estimate,
               mc_standard_error=math.sqrt(estimate * (1 - estimate) / trials),
               mc95_interval=[mc_lo, mc_hi],
               all6_iid_cells_probability_estimate=estimate**6,
               all6_iid_cells_mc95_interval=[mc_lo**6, mc_hi**6],
               all6_arbitrary_dependence_bounds=[max(0.0, 6 * estimate - 5), estimate])
    if n == 50:
        exact = exact_power_small(n, pb, pc)
        row['cell_power_exact_multinomial'] = exact
        row['mc_minus_exact'] = estimate - exact
        assert abs(estimate - exact) < max(.0002, 6 * math.sqrt(exact * (1 - exact) / trials))
    return row


def cost(n: int, copies: int = 1) -> dict:
    confirmation = 6 * n * 2
    exploration = 4 * 2 * 3 * 20 * 2
    total = confirmation + exploration
    return dict(n_per_cell=n, confirmation_pairs=6 * n,
                confirmation_battles=confirmation, exploration_battles=exploration,
                total_battles=total, task_copies=copies,
                batch_battles=total * copies,
                legacy_easy_case_cpu_hours=[total * copies * .174 / 3600,
                                            total * copies * .294 / 3600],
                full_trace_decimal_GB=[total * copies * 2.37 / 1000,
                                       total * copies * 3.24 / 1000])


def logical_and_physical_budget(logical_battles: int) -> dict:
    """Ten-percent finite recovery allowance; no statistical sample inflation."""
    assert logical_battles % 10 == 0
    recovery = logical_battles // 10
    physical = logical_battles + recovery
    return dict(logical_battles=logical_battles,
                recovery_attempt_battle_equivalents=recovery,
                physical_attempt_cap=physical,
                nominal_fault_free_cpu_hours=[logical_battles*.174/3600, logical_battles*.294/3600],
                nominal_fault_free_full_trace_decimal_GB=[logical_battles*2.37/1000, logical_battles*3.24/1000],
                recovery_inclusive_cpu_hours_extrapolation=[physical*.174/3600, physical*.294/3600],
                recovery_inclusive_full_trace_decimal_GB_extrapolation=[physical*2.37/1000, physical*3.24/1000])


def av_sign_threshold_power(m: int, success_probability: float = .6) -> dict:
    """Pre-registered AV F(.95)>=.5 gate, exact binomial power conditional on m."""
    alpha = .05 / 2
    critical = next(k for k in range(m + 1) if cp_lower(m, k, alpha) >= .5)
    boundary_size = direct_binomial_sum(m, .5, critical, m + 1)
    exact_power = direct_binomial_sum(m, success_probability, critical, m + 1)
    previous_tail = direct_binomial_sum(m, .5, critical - 1, m + 1)
    assert boundary_size <= alpha < previous_tail
    assert cp_lower(m, critical - 1, alpha) < .5 <= cp_lower(m, critical, alpha)
    return dict(m_common_wins=m, alpha_per_primary_cell=alpha,
                ratio_threshold=.95, required_probability=.5,
                critical_success_count=critical,
                exact_boundary_rejection_probability_p05=boundary_size,
                cp_lower_at_critical=cp_lower(m, critical, alpha),
                true_conditional_success_probability=success_probability,
                exact_power_without_minimum_m_guard=exact_power,
                two_independent_identical_cells_power=exact_power**2,
                two_cells_arbitrary_dependence_bounds=[max(0., 2 * exact_power - 1), exact_power],
                eligible_under_proposed_m500_minimum=m>=500)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--trials', type=int, default=200000)
    parser.add_argument('--output-dir', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'evidence' / 'statistical-budget-20261004')
    args = parser.parse_args()
    if args.trials < 10000:
        raise ValueError('use at least 10000 probability experiments per row')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    checks = numeric_checks()
    result = dict(kind='statistical_probability_calculation_not_game_simulation',
                  python=platform.python_version(), numpy=np.__version__,
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  alpha_family=.05, cells=CELLS, one_sided_bounds=12,
                  alpha_per_bound=ALPHA, ni_margin=MARGIN,
                  fixed_sample_pass_rule='cp_lower(n,b,alpha)-cp_upper(n,c,alpha) >= -0.02',
                  improvement_definition='baseline non-win (loss or game timeout), candidate win',
                  regression_definition='baseline win, candidate non-win (loss or game timeout)',
                  missing_infrastructure_results='not classified as game losses; incomplete experiment',
                  numerical_checks=checks,
                  zero_discordance_min_n=math.ceil(math.log(ALPHA) / math.log1p(-MARGIN)),
                  zero_discordance_rows=[dict(n=n, lower=difference_lower(n, 0, 0))
                    for n in (50, 100, 200, 271, 272, 300, 500, 1000, 2000, 10000)],
                  n50_absolute_best_table=dict(b=50, c=0, lower=difference_lower(50, 50, 0)),
                  n50_min_improvements_without_regressions=next(b for b in range(51)
                    if difference_lower(50, b, 0) >= -MARGIN))
    project = Path(__file__).resolve().parents[2]
    result['input_document_sha256'] = {name: hashlib.sha256((project / name).read_bytes()).hexdigest()
        for name in ['TECHNICAL_PROPOSAL.md', 'IMPLEMENTATION_ROADMAP.md']}
    scenarios = [
        ('same_outcomes', 0.0, 0.0),
        ('q01_delta00', .005, .005),
        ('q02_delta00', .01, .01),
        ('q05_delta00', .025, .025),
        ('q10_delta00', .05, .05),
        ('q20_delta00', .10, .10),
        ('q10_delta_plus02', .06, .04),
        ('q10_delta_minus01', .045, .055),
        ('q10_delta_minus02_boundary', .04, .06),
        ('q10_delta_minus03_inferior', .035, .065),
    ]
    sizes = [50, 272, 500, 1000, 2000, 5000, 8000, 10000, 20000, 40000]
    powers = []
    for scenario_index, (name, pb, pc) in enumerate(scenarios):
        for n in sizes:
            row = power(n, pb, pc, args.trials, 20261004 + 100000 * scenario_index + n)
            row['scenario'] = name
            powers.append(row)
        print(json.dumps(dict(completed=name, rows=len(powers)), ensure_ascii=False), flush=True)
    result['power_rows'] = powers
    result['budget_rows'] = [cost(n) for n in sizes]
    result['recommended_n10000_eight_tasks'] = cost(10000, 8)
    result['recommended_n10000_24_tasks_if_all_confirmed'] = cost(10000, 24)
    result['logical_physical_budget'] = dict(
        strict_one_task=logical_and_physical_budget(120960),
        formal_2_strict_plus_22_low_cost=logical_and_physical_budget(2*120960+22*1560),
        development_6_low_cost=logical_and_physical_budget(6*1560),
        combined_formal_and_development=logical_and_physical_budget(2*120960+28*1560),
        policy='Same frozen seeds/inputs only; at most one automatic retry per shard; debit complete declared shard battle equivalents before dispatch; crashes do not refund; shared recovery pool may be insufficient; no additional statistical samples; exhausted incomplete confirmation is INCONCLUSIVE',
        cost_scope='Legacy easy-case linear extrapolation, excludes IO/serialization/model/startup; not a resource sufficiency guarantee')
    result['additional_count_examples'] = [dict(n=n, b=b, c=c,
        lower=difference_lower(n, b, c), passed=difference_lower(n, b, c)>=-MARGIN)
        for n,b,c in [(50,0,0),(50,10,0),(50,11,0),(272,0,0),(272,0,1),
                      (10000,500,500),(10000,450,550),(10000,400,600)]]
    result['av_primary_exact_binomial'] = dict(
        primary_cells=['balanced_standard','survival_standard'],
        family_alpha=.05, per_cell_alpha=.025,
        pass_rule='m>=500 and cp_lower(m,k,.025)>=.5 in both primary cells',
        count_rule='k counts common-win pairs with positive baseline AV and 20*AV_candidate<=19*AV_baseline',
        ties='ratio exactly .95 is a success; use exact rational comparison',
        estimand='P(AV_candidate/AV_baseline<=.95 | both win)',
        lower_median_definition='inf{x: F_common_win_ratio(x)>=.5}',
        power_rows=[av_sign_threshold_power(m) for m in [100,300,500]])
    result['elapsed_seconds'] = time.perf_counter() - started
    result['cp_cache'] = dict(lower=str(cp_lower.cache_info()), upper=str(cp_upper.cache_info()))
    output = args.output_dir / 'results.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    columns = ['scenario','n','discordance','true_delta','expected_b','expected_c',
               'rounded_expected_counts_lower','cell_pass_probability_estimate',
               'all6_iid_cells_probability_estimate','mc_standard_error','trials','rng_seed']
    with (args.output_dir / 'power-table.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(powers)
    print(json.dumps(dict(output=str(output), numerical_checks=checks['passed'],
                          zero_discordance_min_n=result['zero_discordance_min_n'],
                          n50_min_b_c0=result['n50_min_improvements_without_regressions'],
                          rows=len(powers), elapsed_seconds=result['elapsed_seconds']), indent=2), flush=True)


if __name__ == '__main__':
    main()
