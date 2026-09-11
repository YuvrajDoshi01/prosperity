"""
Game-theory aware brute-force solver for R2 Invest and Expand.

Differences from v2:
  1. Builds a REALISTIC competitor population by sampling from behavioral
     buckets (equal splitters, round number pickers, Research maximizers,
     Scale maximizers, Speed hawks, game theorists).
  2. Runs Monte Carlo trials over this population to estimate distribution
     of Speed multipliers for each sp value.
  3. Computes iterated best response: seed with v2 answer, assume some
     fraction of "sophisticated" competitors copy it, re-solve. Iterate to
     a stable allocation.
  4. Outputs: mean, median, p10, p90 PnL per allocation across trials.

Key assumption: N_COMPETITORS ~ 1000 (typical Prosperity entries per round).

Behavioral buckets (with rough population fractions derived from writeup):
  - equal_split:     35%   Speed ~ 33 +/- 2
  - round_numbers:   25%   Speed in {20, 25, 30, 40, 50} with unequal weights
  - research_max:    12%   Speed ~ 10 +/- 5
  - scale_max:        7%   Speed ~ 5 +/- 3
  - speed_hawk:      12%   Speed ~ 60 +/- 10
  - sophisticated:    9%   Speed ~ seed allocation (iterated best response)

The sophisticated bucket is self-referential: they allocate based on the
equilibrium we are solving for. We handle this via iterated best response.
"""

import json
import math
import random
from pathlib import Path

BUDGET = 50_000
LOG_101 = math.log(101)
N_COMPETITORS = 1000
N_TRIALS = 100


def research(r):
    return 200_000 * math.log(1 + r) / LOG_101


def scale(s):
    return 7 * s / 100


def speed_multiplier_from_rank(our_sp, competitor_sp_samples):
    """Compute our Speed multiplier given our sp value and a list of competitor
    sp investments. Rank 1 (highest) gets 0.9, lowest gets 0.1, linear between."""
    n = len(competitor_sp_samples)
    # Count competitors strictly below us (we are rank = n - below + 1)
    below = sum(1 for c in competitor_sp_samples if c < our_sp)
    # Our percentile (0 = worst, 1 = best among total population including us)
    pct = below / n
    return 0.1 + 0.8 * pct


def sample_equal_splitter(rng):
    return max(0, min(100, int(rng.gauss(33, 2))))


def sample_round_numbers(rng):
    weights = [(20, 0.15), (25, 0.15), (30, 0.25), (33, 0.15), (40, 0.15), (50, 0.15)]
    r = rng.random()
    cum = 0
    for val, w in weights:
        cum += w
        if r <= cum:
            return val
    return 40


def sample_research_max(rng):
    # Go heavy on Research, low on Speed
    return max(0, min(100, int(rng.gauss(10, 5))))


def sample_scale_max(rng):
    return max(0, min(100, int(rng.gauss(5, 3))))


def sample_speed_hawk(rng):
    return max(0, min(100, int(rng.gauss(60, 10))))


def sample_sophisticated(rng, seed_sp):
    # Sophisticated players cluster around the seed allocation with small noise
    return max(0, min(100, int(rng.gauss(seed_sp, 3))))


BUCKET_FRACTIONS = {
    "equal_split":     0.35,
    "round_numbers":   0.25,
    "research_max":    0.12,
    "scale_max":       0.07,
    "speed_hawk":      0.12,
    "sophisticated":   0.09,
}


def build_competitor_population(rng, seed_sp):
    samples = []
    buckets = [
        (BUCKET_FRACTIONS["equal_split"], sample_equal_splitter),
        (BUCKET_FRACTIONS["round_numbers"], sample_round_numbers),
        (BUCKET_FRACTIONS["research_max"], sample_research_max),
        (BUCKET_FRACTIONS["scale_max"], sample_scale_max),
        (BUCKET_FRACTIONS["speed_hawk"], sample_speed_hawk),
        (BUCKET_FRACTIONS["sophisticated"], lambda r: sample_sophisticated(r, seed_sp)),
    ]
    for _ in range(N_COMPETITORS):
        r = rng.random()
        cum = 0
        for frac, sampler in buckets:
            cum += frac
            if r <= cum:
                samples.append(sampler(rng))
                break
    return samples


def pnl(r, s, sp_multiplier):
    gross = research(r) * scale(s) * sp_multiplier
    cost = BUDGET * (r + s + sp) / 100.0
    return gross - cost


def run_trials(seed_sp, n_trials=N_TRIALS, base_seed=42):
    """Run Monte Carlo trials. For each allocation, collect PnL across trials.
    Returns dict: alloc -> list of PnL values."""

    # Precompute Speed multiplier for each possible sp value per trial
    # Each trial: one competitor population, one speed_multiplier[sp] table
    per_trial_speed = []
    for trial in range(n_trials):
        rng = random.Random(base_seed + trial)
        pop = build_competitor_population(rng, seed_sp)
        speed_table = [speed_multiplier_from_rank(sp, pop) for sp in range(101)]
        per_trial_speed.append(speed_table)

    # Evaluate all allocations
    stats = {}
    for r in range(101):
        r_val = research(r)
        for s in range(101 - r):
            s_val = scale(s)
            r_s_product = r_val * s_val
            for sp in range(101 - r - s):
                cost = BUDGET * (r + s + sp) / 100.0
                vals = [r_s_product * per_trial_speed[t][sp] - cost for t in range(n_trials)]
                vals.sort()
                stats[(r, s, sp)] = {
                    "mean": sum(vals) / n_trials,
                    "median": vals[n_trials // 2],
                    "p10": vals[int(n_trials * 0.1)],
                    "p90": vals[int(n_trials * 0.9)],
                }
    return stats


def iterated_best_response(n_iterations=5, tolerance=1, base_seed=42):
    """Seed with sp=40, compute optimum, use that sp in sophisticated bucket,
    re-solve. Iterate to convergence."""
    seed_sp = 40
    history = []

    for i in range(n_iterations):
        print(f"\n=== Iteration {i + 1} (seed_sp = {seed_sp}) ===")
        stats = run_trials(seed_sp, n_trials=N_TRIALS, base_seed=base_seed)

        # Find mean-optimal allocation
        best_alloc = max(stats.items(), key=lambda x: x[1]["mean"])
        alloc, metrics = best_alloc
        print(f"  Best alloc: {alloc}")
        print(f"    mean={metrics['mean']:>10,.0f}  median={metrics['median']:>10,.0f}  "
              f"p10={metrics['p10']:>10,.0f}  p90={metrics['p90']:>10,.0f}")

        history.append({
            "iteration": i + 1,
            "seed_sp": seed_sp,
            "best_alloc": alloc,
            "mean": round(metrics["mean"], 2),
            "median": round(metrics["median"], 2),
            "p10": round(metrics["p10"], 2),
            "p90": round(metrics["p90"], 2),
        })

        new_seed_sp = alloc[2]
        if abs(new_seed_sp - seed_sp) <= tolerance:
            print(f"  CONVERGED at iteration {i + 1}: sp stayed within {tolerance}")
            break
        seed_sp = new_seed_sp

    return history, stats


def main():
    print(f"Behavioral buckets: {BUCKET_FRACTIONS}")
    print(f"N_COMPETITORS = {N_COMPETITORS}, N_TRIALS = {N_TRIALS}")
    print(f"Allocations: {sum(1 for _ in ((r,s,sp) for r in range(101) for s in range(101-r) for sp in range(101-r-s))):,}")

    history, final_stats = iterated_best_response(n_iterations=5, tolerance=1)

    # Top 20 by mean under final equilibrium
    alloc_mean = sorted(final_stats.items(), key=lambda x: -x[1]["mean"])[:20]
    alloc_p10 = sorted(final_stats.items(), key=lambda x: -x[1]["p10"])[:20]

    out = {
        "config": {
            "budget": BUDGET,
            "n_competitors": N_COMPETITORS,
            "n_trials": N_TRIALS,
            "bucket_fractions": BUCKET_FRACTIONS,
        },
        "iterated_best_response_history": history,
        "equilibrium_top20_mean": [
            {"alloc": a, "mean": round(m["mean"], 2), "median": round(m["median"], 2),
             "p10": round(m["p10"], 2), "p90": round(m["p90"], 2)}
            for a, m in alloc_mean
        ],
        "equilibrium_top20_p10": [
            {"alloc": a, "mean": round(m["mean"], 2), "p10": round(m["p10"], 2)}
            for a, m in alloc_p10
        ],
        "candidates": {
            f"alloc_{r}_{s}_{sp}": {
                "mean": round(final_stats[(r, s, sp)]["mean"], 2),
                "median": round(final_stats[(r, s, sp)]["median"], 2),
                "p10": round(final_stats[(r, s, sp)]["p10"], 2),
                "p90": round(final_stats[(r, s, sp)]["p90"], 2),
            }
            for (r, s, sp) in [(15, 44, 41), (14, 41, 45), (16, 46, 38), (15, 40, 45),
                               (15, 46, 39), (11, 29, 60), (14, 40, 46)]
            if (r, s, sp) in final_stats
        },
    }

    out_path = Path(__file__).parent / "invest_expand_results_v3.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWritten: {out_path}")

    print("\n=== Top 10 equilibrium allocations (by mean under realistic population) ===")
    for i, (alloc, m) in enumerate(alloc_mean[:10], 1):
        print(f"  {i:2d}. {alloc}  mean={m['mean']:>10,.0f}  median={m['median']:>10,.0f}  "
              f"p10={m['p10']:>10,.0f}  p90={m['p90']:>10,.0f}")

    print("\n=== Candidate comparisons ===")
    for name, stats in out["candidates"].items():
        print(f"  {name}: mean={stats['mean']:>10,.0f}  median={stats['median']:>10,.0f}  "
              f"p10={stats['p10']:>10,.0f}  p90={stats['p90']:>10,.0f}")


# pnl() uses sp but I didn't pass it - fix by closing over sp in main loop
# Simplifying: compute inline rather than via function
def pnl(r, s, sp, sp_multiplier):
    gross = research(r) * scale(s) * sp_multiplier
    cost = BUDGET * (r + s + sp) / 100.0
    return gross - cost


if __name__ == "__main__":
    main()
