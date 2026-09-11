#!/usr/bin/env python3
"""
Invest & Expand — Monte Carlo Simulation (v6)

Comprehensive population-based MC simulation for the R2 manual challenge.
Addresses user's behavioral model critique and runs large-scale optimization.

Usage:
    python invest_expand_mc_v6.py [--epochs 10000] [--fast]
"""

import math
import random
import json
import argparse
from collections import defaultdict
from pathlib import Path
from typing import List, Tuple, Callable, Dict, Any

# =============================================================================
# Constants
# =============================================================================

BUDGET = 50_000
LOG_101 = math.log(101)
COST_PER_PCT = BUDGET / 100  # = 500

# =============================================================================
# Core Functions
# =============================================================================

def research(r: int) -> float:
    """Research payoff: concave log, [0, 200000]."""
    if r <= 0:
        return 0.0
    return 200_000 * math.log(1 + r) / LOG_101

def scale(s: int) -> float:
    """Scale multiplier: linear, [0, 7]."""
    return 7.0 * s / 100.0

def pnl(r: int, s: int, sp: int, h: float) -> float:
    """PnL given allocation (r, s, sp) and speed multiplier h."""
    return research(r) * scale(s) * h - COST_PER_PCT * (r + s + sp)

def speed_multiplier_rank(our_sp: int, population_sps: List[int]) -> float:
    """
    Compute speed multiplier based on rank.
    Ties share the top rank of the tied group.
    h = 0.1 + 0.8 * (N_below) / N  where N_below = count strictly below us.
    """
    n = len(population_sps)
    if n == 0:
        return 0.5
    below = sum(1 for x in population_sps if x < our_sp)
    return 0.1 + 0.8 * below / n

# =============================================================================
# Population Models
# =============================================================================

def pop_user_model_v1(rng: random.Random, n: int, seed_sp: int) -> List[int]:
    """
    User's original proposed model:
    - 20% random [0,100]
    - 25% Nash-style (allocate optimal R/S, remainder to Speed based on guess)
    - 5% equal (33)
    - 50% Speed-aware (distribution around seed)
    """
    samples = []
    for _ in range(n):
        r = rng.random()
        if r < 0.20:
            # Random
            samples.append(rng.randint(0, 100))
        elif r < 0.45:
            # "Nash-style" - interpret as: pick sp first based on gut, then optimize r/s
            # Most people guess sp ~ 30-50
            sp = max(0, min(100, int(rng.gauss(40, 12))))
            samples.append(sp)
        elif r < 0.50:
            # Equal split
            samples.append(rng.choice([33, 34]))
        else:
            # Speed-aware: cluster around current "smart" consensus
            sp = max(0, min(100, int(rng.gauss(seed_sp, 8))))
            samples.append(sp)
    return samples


def pop_empirical_all(rng: random.Random, n: int, seed_sp: int) -> List[int]:
    """
    Empirical model from R1 leaderboard analysis — ALL 22k teams.
    73.3% ghosts with sp=0.
    """
    BUCKETS = [
        ("ghost",          0.733, lambda rng, sp: 0),
        ("random",         0.023, lambda rng, sp: rng.randint(0, 100)),
        ("equal",          0.013, lambda rng, sp: rng.choice([33, 34])),
        ("round_number",   0.013, lambda rng, sp: rng.choices([20, 25, 30, 40, 50], [0.20, 0.20, 0.25, 0.20, 0.15])[0]),
        ("partial_solver", 0.020, lambda rng, sp: rng.randint(15, 50)),
        ("copy_paster",    0.021, lambda rng, sp: max(0, min(100, int(rng.gauss(sp, 3))))),
        ("over_invester",  0.005, lambda rng, sp: max(40, min(100, int(rng.gauss(65, 10))))),
        ("nash_hunter",    0.004, lambda rng, sp: max(0, min(100, int(rng.gauss(sp, 2))))),
        ("contrarian",     0.001, lambda rng, sp: max(0, min(100, sp + rng.choice([1, 2, 3])))),
        ("speed_aware",    0.167, lambda rng, sp: max(0, min(100, int(rng.gauss(sp - 5, 10))))),
    ]
    return _sample_buckets(rng, n, seed_sp, BUCKETS)


def pop_empirical_engaged(rng: random.Random, n: int, seed_sp: int) -> List[int]:
    """
    Empirical model — ENGAGED players only (~5,900 teams).
    Excludes ghosts, rescales remaining buckets.
    """
    BUCKETS = [
        ("random",         0.086, lambda rng, sp: rng.randint(0, 100)),
        ("equal",          0.050, lambda rng, sp: rng.choice([33, 34])),
        ("round_number",   0.050, lambda rng, sp: rng.choices([20, 25, 30, 40, 50], [0.20, 0.20, 0.25, 0.20, 0.15])[0]),
        ("partial_solver", 0.074, lambda rng, sp: rng.randint(15, 50)),
        ("copy_paster",    0.080, lambda rng, sp: max(0, min(100, int(rng.gauss(sp, 3))))),
        ("over_invester",  0.020, lambda rng, sp: max(40, min(100, int(rng.gauss(65, 10))))),
        ("nash_hunter",    0.015, lambda rng, sp: max(0, min(100, int(rng.gauss(sp, 2))))),
        ("contrarian",     0.005, lambda rng, sp: max(0, min(100, sp + rng.choice([1, 2, 3])))),
        ("speed_aware",    0.620, lambda rng, sp: max(0, min(100, int(rng.gauss(sp - 5, 10))))),
    ]
    return _sample_buckets(rng, n, seed_sp, BUCKETS)


def pop_corrected_user(rng: random.Random, n: int, seed_sp: int) -> List[int]:
    """
    Corrected user model (no ghosts assumed, for MODE B analysis):
    - 20% random [0,100]
    - 25% Nash-style (sp ~ N(40, 12))
    - 5% equal (33/34)
    - 10% round numbers
    - 40% Speed-aware (cluster around seed)
    """
    samples = []
    for _ in range(n):
        r = rng.random()
        if r < 0.20:
            samples.append(rng.randint(0, 100))
        elif r < 0.45:
            samples.append(max(0, min(100, int(rng.gauss(40, 12)))))
        elif r < 0.50:
            samples.append(rng.choice([33, 34]))
        elif r < 0.60:
            samples.append(rng.choices([20, 25, 30, 33, 40, 50], [0.15, 0.15, 0.25, 0.15, 0.15, 0.15])[0])
        else:
            samples.append(max(0, min(100, int(rng.gauss(seed_sp, 8)))))
    return samples


def _sample_buckets(rng, n, seed_sp, buckets):
    """Helper to sample from bucket distribution."""
    weights = [b[1] for b in buckets]
    samplers = [b[2] for b in buckets]
    total = sum(weights)
    weights = [w / total for w in weights]

    samples = []
    for _ in range(n):
        idx = rng.choices(range(len(buckets)), weights=weights)[0]
        samples.append(samplers[idx](rng, seed_sp))
    return samples


# All population models
POPULATION_MODELS = {
    "user_v1": pop_user_model_v1,
    "user_corrected": pop_corrected_user,
    "empirical_all": pop_empirical_all,
    "empirical_engaged": pop_empirical_engaged,
}

# =============================================================================
# Monte Carlo Simulation
# =============================================================================

def run_mc_simulation(
    pop_builder: Callable,
    pop_size: int,
    n_epochs: int,
    seed_sp: int,
    candidates: List[Tuple[int, int, int]] = None,
    verbose: bool = False,
) -> Dict[Tuple[int, int, int], Dict[str, float]]:
    """
    Run Monte Carlo simulation for given population model.

    Returns dict mapping (r, s, sp) -> {mean, std, p10, median, p90, mean_h}
    """
    # If no candidates specified, do full grid search
    if candidates is None:
        candidates = []
        for r in range(1, 50):
            for sp in range(0, 101 - r):
                s = 100 - r - sp
                if s >= 0:
                    candidates.append((r, s, sp))

    # Pre-build population samples for each epoch
    # This is the expensive part - generate all at once
    all_pops = []
    for epoch in range(n_epochs):
        rng = random.Random(42 + epoch * 7919)
        pop = pop_builder(rng, pop_size, seed_sp)
        all_pops.append(pop)

    # Pre-compute speed multiplier lookup tables for efficiency
    # For each epoch, compute h for each possible sp value [0, 100]
    speed_tables = []
    for epoch in range(n_epochs):
        table = [speed_multiplier_rank(sp, all_pops[epoch]) for sp in range(101)]
        speed_tables.append(table)

    # Evaluate all candidates
    results = {}
    for r, s, sp in candidates:
        rv = research(r)
        sv = scale(s)

        pnls = []
        hs = []
        for epoch in range(n_epochs):
            h = speed_tables[epoch][sp]
            p = rv * sv * h - 50000
            pnls.append(p)
            hs.append(h)

        pnls.sort()
        results[(r, s, sp)] = {
            "mean": sum(pnls) / n_epochs,
            "std": (sum((p - sum(pnls)/n_epochs)**2 for p in pnls) / n_epochs) ** 0.5,
            "p10": pnls[int(0.10 * n_epochs)],
            "p25": pnls[int(0.25 * n_epochs)],
            "median": pnls[n_epochs // 2],
            "p75": pnls[int(0.75 * n_epochs)],
            "p90": pnls[int(0.90 * n_epochs)],
            "mean_h": sum(hs) / n_epochs,
            "min": pnls[0],
            "max": pnls[-1],
        }

    return results


def find_optimal(results: Dict) -> Tuple[Tuple[int, int, int], Dict]:
    """Find allocation with highest mean PnL."""
    best = max(results.items(), key=lambda x: x[1]["mean"])
    return best


def iterated_best_response(
    pop_builder: Callable,
    pop_size: int,
    n_epochs: int,
    max_iters: int = 10,
    verbose: bool = True,
) -> List[Dict]:
    """
    Run iterated best response to find approximate Nash.
    Each iteration, find best allocation given population seeded at current sp.
    """
    history = []
    seed_sp = 40  # Start with moderate guess

    for iteration in range(max_iters):
        results = run_mc_simulation(pop_builder, pop_size, n_epochs, seed_sp)
        best_alloc, best_stats = find_optimal(results)

        entry = {
            "iteration": iteration + 1,
            "seed_sp": seed_sp,
            "best_alloc": best_alloc,
            "pnl": best_stats["mean"],
            "mean_h": best_stats["mean_h"],
        }
        history.append(entry)

        if verbose:
            r, s, sp = best_alloc
            print(f"  Iter {iteration+1}: seed_sp={seed_sp:2d} -> best=({r:2d},{s:2d},{sp:2d}) "
                  f"PnL={best_stats['mean']:>10,.0f} h={best_stats['mean_h']:.3f}")

        new_sp = best_alloc[2]
        if abs(new_sp - seed_sp) <= 1:
            if verbose:
                print(f"  CONVERGED at sp={new_sp}")
            break
        seed_sp = new_sp

    return history


# =============================================================================
# Analysis Functions
# =============================================================================

def analyze_population_distribution(
    pop_builder: Callable,
    pop_size: int,
    n_samples: int,
    seed_sp: int,
) -> Dict[str, Any]:
    """Analyze the distribution of sp values in a population model."""
    all_sp = []
    for i in range(n_samples):
        rng = random.Random(42 + i * 7919)
        pop = pop_builder(rng, pop_size, seed_sp)
        all_sp.extend(pop)

    all_sp.sort()
    n = len(all_sp)

    # Compute percentiles
    percentiles = {
        f"p{p}": all_sp[int(p/100 * n)]
        for p in [10, 25, 50, 75, 90, 95, 99]
    }

    # Count zeros (ghosts)
    n_zeros = sum(1 for x in all_sp if x == 0)

    # Bucket distribution
    buckets = defaultdict(int)
    for sp in all_sp:
        if sp == 0:
            buckets["0 (ghost)"] += 1
        elif sp <= 20:
            buckets["1-20"] += 1
        elif sp <= 40:
            buckets["21-40"] += 1
        elif sp <= 60:
            buckets["41-60"] += 1
        elif sp <= 80:
            buckets["61-80"] += 1
        else:
            buckets["81-100"] += 1

    bucket_pcts = {k: v/n*100 for k, v in sorted(buckets.items())}

    return {
        "mean": sum(all_sp) / n,
        "std": (sum((x - sum(all_sp)/n)**2 for x in all_sp) / n) ** 0.5,
        "percentiles": percentiles,
        "pct_zeros": n_zeros / n * 100,
        "bucket_pcts": bucket_pcts,
    }


def run_robustness_analysis(
    candidates: List[Tuple[int, int, int]],
    n_epochs: int,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Run each candidate against all population models and compute robust metrics.
    """
    results_by_model = {}

    for model_name, pop_builder in POPULATION_MODELS.items():
        pop_size = 22000 if "all" in model_name else 5900
        seed_sp = 44  # Use v5's recommendation as seed

        if verbose:
            print(f"\n  Running {model_name} (n={pop_size})...")

        results = run_mc_simulation(
            pop_builder, pop_size, n_epochs, seed_sp,
            candidates=candidates
        )
        results_by_model[model_name] = results

    # Compute cross-model statistics for each candidate
    cross_model = {}
    for alloc in candidates:
        means = [results_by_model[m][alloc]["mean"] for m in POPULATION_MODELS]
        cross_model[alloc] = {
            "min_mean": min(means),
            "max_mean": max(means),
            "avg_mean": sum(means) / len(means),
            "by_model": {m: results_by_model[m][alloc]["mean"] for m in POPULATION_MODELS}
        }

    return {
        "by_model": results_by_model,
        "cross_model": cross_model,
    }


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Invest & Expand MC Simulation v6")
    parser.add_argument("--epochs", type=int, default=10000, help="Number of MC epochs")
    parser.add_argument("--fast", action="store_true", help="Fast mode (1000 epochs)")
    args = parser.parse_args()

    n_epochs = 1000 if args.fast else args.epochs

    print("=" * 80)
    print("INVEST & EXPAND — MONTE CARLO SIMULATION v6")
    print("=" * 80)
    print(f"Epochs: {n_epochs:,}")
    print()

    # ==========================================================================
    # SECTION 1: Population Model Analysis
    # ==========================================================================
    print("\n" + "=" * 80)
    print("SECTION 1: POPULATION MODEL ANALYSIS")
    print("=" * 80)

    for model_name, pop_builder in POPULATION_MODELS.items():
        pop_size = 22000 if "all" in model_name else 5900
        print(f"\n--- {model_name} (n={pop_size}) ---")

        stats = analyze_population_distribution(pop_builder, pop_size, 100, seed_sp=44)
        print(f"  Mean sp: {stats['mean']:.1f}, Std: {stats['std']:.1f}")
        print(f"  % zeros: {stats['pct_zeros']:.1f}%")
        print(f"  Percentiles: {stats['percentiles']}")
        print(f"  Buckets: {stats['bucket_pcts']}")

    # ==========================================================================
    # SECTION 2: Grid Search for Each Population Model
    # ==========================================================================
    print("\n" + "=" * 80)
    print("SECTION 2: GRID SEARCH OPTIMIZATION")
    print("=" * 80)

    key_results = {}

    for model_name, pop_builder in POPULATION_MODELS.items():
        pop_size = 22000 if "all" in model_name else 5900
        seed_sp = 44

        print(f"\n--- {model_name} ---")

        results = run_mc_simulation(pop_builder, pop_size, n_epochs, seed_sp)
        best_alloc, best_stats = find_optimal(results)

        # Top 10 allocations
        sorted_results = sorted(results.items(), key=lambda x: -x[1]["mean"])[:10]

        print(f"  Top 10 allocations:")
        print(f"  {'Rank':>4} {'(r,s,sp)':>12} {'Mean PnL':>12} {'Std':>10} {'h_mean':>8} {'P10':>10} {'P90':>10}")
        print("  " + "-" * 75)
        for rank, (alloc, stats) in enumerate(sorted_results, 1):
            r, s, sp = alloc
            print(f"  {rank:>4} ({r:>2},{s:>2},{sp:>2}) {stats['mean']:>12,.0f} "
                  f"{stats['std']:>10,.0f} {stats['mean_h']:>8.3f} "
                  f"{stats['p10']:>10,.0f} {stats['p90']:>10,.0f}")

        key_results[model_name] = {
            "best": best_alloc,
            "stats": best_stats,
            "top10": sorted_results[:10],
        }

    # ==========================================================================
    # SECTION 3: Iterated Best Response (Nash Approximation)
    # ==========================================================================
    print("\n" + "=" * 80)
    print("SECTION 3: ITERATED BEST RESPONSE")
    print("=" * 80)

    ibr_results = {}

    for model_name in ["empirical_engaged", "user_corrected"]:
        pop_builder = POPULATION_MODELS[model_name]
        pop_size = 5900

        print(f"\n--- {model_name} ---")
        history = iterated_best_response(pop_builder, pop_size, n_epochs // 10, max_iters=8)
        ibr_results[model_name] = history

    # ==========================================================================
    # SECTION 4: Robustness Analysis
    # ==========================================================================
    print("\n" + "=" * 80)
    print("SECTION 4: ROBUSTNESS ANALYSIS")
    print("=" * 80)

    # Key candidates to evaluate
    candidates = [
        (14, 42, 44),  # v5 recommendation
        (15, 44, 41),  # v3 Nash
        (16, 46, 38),  # v2 mean-opt
        (23, 74, 3),   # MODE A exploit
        (11, 29, 60),  # Robust
        (18, 50, 32),  # Moderate
        (15, 43, 42),  # Contrarian
        (13, 43, 44),  # Variant
        (14, 41, 45),  # +1 sp
        (12, 36, 52),  # IBR iter3
    ]

    print(f"\n  Evaluating {len(candidates)} candidates across {len(POPULATION_MODELS)} models...")
    robust = run_robustness_analysis(candidates, n_epochs, verbose=True)

    print(f"\n  Cross-model summary:")
    print(f"  {'(r,s,sp)':>12} | {'Min':>10} {'Max':>10} {'Avg':>10} | "
          f"{'user_v1':>10} {'user_cor':>10} {'emp_all':>10} {'emp_eng':>10}")
    print("  " + "-" * 95)

    sorted_robust = sorted(robust["cross_model"].items(), key=lambda x: -x[1]["min_mean"])
    for alloc, stats in sorted_robust:
        r, s, sp = alloc
        print(f"  ({r:>2},{s:>2},{sp:>2}) | {stats['min_mean']:>10,.0f} "
              f"{stats['max_mean']:>10,.0f} {stats['avg_mean']:>10,.0f} | ", end="")
        for m in ["user_v1", "user_corrected", "empirical_all", "empirical_engaged"]:
            print(f"{stats['by_model'][m]:>10,.0f}", end=" ")
        print()

    # ==========================================================================
    # SECTION 5: Mode A vs Mode B Decision Matrix
    # ==========================================================================
    print("\n" + "=" * 80)
    print("SECTION 5: MODE UNCERTAINTY DECISION MATRIX")
    print("=" * 80)

    mode_a_results = run_mc_simulation(
        pop_empirical_all, 22000, n_epochs, 44,
        candidates=candidates
    )
    mode_b_results = run_mc_simulation(
        pop_empirical_engaged, 5900, n_epochs, 44,
        candidates=candidates
    )

    print(f"\n  P(A) = probability that ghosts count in ranking")
    print(f"\n  {'(r,s,sp)':>12} | {'MODE A':>10} {'MODE B':>10} | "
          f"{'P=0.2':>10} {'P=0.5':>10} {'P=0.8':>10} | {'Worst':>10} {'MaxMin':>8}")
    print("  " + "-" * 95)

    decision_matrix = []
    for alloc in candidates:
        pnl_a = mode_a_results[alloc]["mean"]
        pnl_b = mode_b_results[alloc]["mean"]
        worst = min(pnl_a, pnl_b)

        row = {
            "alloc": alloc,
            "mode_a": pnl_a,
            "mode_b": pnl_b,
            "ev_02": 0.2 * pnl_a + 0.8 * pnl_b,
            "ev_05": 0.5 * pnl_a + 0.5 * pnl_b,
            "ev_08": 0.8 * pnl_a + 0.2 * pnl_b,
            "worst": worst,
        }
        decision_matrix.append(row)

    # Sort by worst-case (maximin)
    decision_matrix.sort(key=lambda x: -x["worst"])

    for row in decision_matrix:
        r, s, sp = row["alloc"]
        is_maximin = row == decision_matrix[0]
        marker = " <-- MAXIMIN" if is_maximin else ""
        print(f"  ({r:>2},{s:>2},{sp:>2}) | {row['mode_a']:>10,.0f} {row['mode_b']:>10,.0f} | "
              f"{row['ev_02']:>10,.0f} {row['ev_05']:>10,.0f} {row['ev_08']:>10,.0f} | "
              f"{row['worst']:>10,.0f}{marker}")

    # ==========================================================================
    # SECTION 6: FINAL RECOMMENDATION
    # ==========================================================================
    print("\n" + "=" * 80)
    print("SECTION 6: FINAL RECOMMENDATION")
    print("=" * 80)

    # Find optimal under each criterion
    maximin_alloc = decision_matrix[0]["alloc"]
    max_ev_02 = max(decision_matrix, key=lambda x: x["ev_02"])["alloc"]
    max_ev_05 = max(decision_matrix, key=lambda x: x["ev_05"])["alloc"]
    max_mode_a = max(decision_matrix, key=lambda x: x["mode_a"])["alloc"]
    max_mode_b = max(decision_matrix, key=lambda x: x["mode_b"])["alloc"]

    print(f"""
SUMMARY:
  - MAXIMIN (worst-case optimal):    {maximin_alloc}
  - Best at P(A)=0.2:                {max_ev_02}
  - Best at P(A)=0.5:                {max_ev_05}
  - Best for MODE A (ghosts count):  {max_mode_a}
  - Best for MODE B (engaged only):  {max_mode_b}

RECOMMENDATION:

  Under mode uncertainty (P(A) = 0.1–0.3 estimated from problem wording),
  the MAXIMIN strategy {maximin_alloc} provides the best worst-case guarantee.

  If confident ghosts don't count (MODE B certain): {max_mode_b}
  If confident ghosts count (MODE A certain):      {max_mode_a}

  Given R1 177k already banked, any of the top candidates clears 200k threshold.
""")

    # ==========================================================================
    # Save Results
    # ==========================================================================
    output = {
        "version": "v6",
        "epochs": n_epochs,
        "key_results": {
            k: {"best": v["best"], "mean_pnl": v["stats"]["mean"]}
            for k, v in key_results.items()
        },
        "iterated_br": ibr_results,
        "decision_matrix": [
            {"alloc": list(r["alloc"]), **{k: v for k, v in r.items() if k != "alloc"}}
            for r in decision_matrix
        ],
        "recommendation": {
            "maximin": list(maximin_alloc),
            "best_ev_02": list(max_ev_02),
            "best_ev_05": list(max_ev_05),
            "mode_a_optimal": list(max_mode_a),
            "mode_b_optimal": list(max_mode_b),
        }
    }

    out_path = Path(__file__).parent / "invest_expand_mc_v6_results.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
