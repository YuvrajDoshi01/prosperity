"""
v4 brute-force solver with empirically-calibrated behavioral bucket fractions.

Builds on v3 but replaces guessed bucket fractions with data-derived ones from
R1 leaderboard analysis (22,130 teams, 73.3% ghost rate, etc.).

Bucket model (percentages of REGISTERED teams):

  GHOST (73.3%)            sp = 0 (didn't engage)
  COPY_PASTER (8.0%)       follows Discord-leaked seed allocation + noise
  PARTIAL_SOLVER (7.4%)    Uniform[20, 50] + some tail
  NASH_HUNTER (1.5%)       clusters at seed allocation with small noise
  CONTRARIAN (0.5%)        seed + {1, 2}
  ROUND_NUMBER (5.0%)      weighted choice of {20, 25, 30, 33, 40, 50}
  OVER_INVESTER (2.0%)     Normal(65, 10)
  REMAINDER (2.3%)         Uniform[0, 100]

Runs two rank interpretations:
  MODE A: "all players" -- all 22k including ghosts
  MODE B: "engaged only" -- exclude ghosts, ~5,900 competitors

Iterates seed until Nash fixed point.

Outputs to invest_expand_results_v4.json.
"""

import json
import math
import random
from pathlib import Path

BUDGET = 50_000
LOG_101 = math.log(101)
N_COMPETITORS = 22130  # matches R1 registered count
N_TRIALS = 50

# Empirical bucket fractions (from r1_leaderboard_analysis.json)
BUCKETS = {
    "ghost":           0.733,
    "copy_paster":     0.080,
    "partial_solver":  0.074,
    "round_number":    0.050,
    "over_invester":   0.020,
    "nash_hunter":     0.015,
    "contrarian":      0.005,
    "remainder":       0.023,
}
assert abs(sum(BUCKETS.values()) - 1.0) < 0.01, f"Bucket fractions sum = {sum(BUCKETS.values())}"


def research(r):
    return 200_000 * math.log(1 + r) / LOG_101


def scale(s):
    return 7 * s / 100


def sample_bucket(rng, bucket_name, seed_sp):
    """Draw a Speed investment from the given bucket."""
    if bucket_name == "ghost":
        return 0
    if bucket_name == "copy_paster":
        # Copies the viral allocation (seed) with small noise
        return max(0, min(100, int(rng.gauss(seed_sp, 2))))
    if bucket_name == "partial_solver":
        return max(0, min(100, int(rng.uniform(20, 50))))
    if bucket_name == "round_number":
        choices = [20, 25, 30, 33, 40, 50]
        weights = [0.20, 0.15, 0.25, 0.15, 0.15, 0.10]
        return rng.choices(choices, weights)[0]
    if bucket_name == "over_invester":
        return max(40, min(100, int(rng.gauss(65, 10))))
    if bucket_name == "nash_hunter":
        return max(0, min(100, int(rng.gauss(seed_sp, 2))))
    if bucket_name == "contrarian":
        return max(0, min(100, seed_sp + rng.choice([1, 2])))
    if bucket_name == "remainder":
        return rng.randint(0, 100)
    raise ValueError(f"Unknown bucket: {bucket_name}")


def build_population(rng, seed_sp, include_ghosts=True):
    """Sample N_COMPETITORS Speed values from the empirical bucket mixture.

    If include_ghosts=False, we drop the ghost bucket and rescale others.
    """
    if include_ghosts:
        buckets = BUCKETS
    else:
        non_ghost = {k: v for k, v in BUCKETS.items() if k != "ghost"}
        total = sum(non_ghost.values())
        buckets = {k: v / total for k, v in non_ghost.items()}

    # Effective competitor count
    n = N_COMPETITORS if include_ghosts else int(N_COMPETITORS * (1 - BUCKETS["ghost"]))

    samples = []
    bucket_items = list(buckets.items())
    for _ in range(n):
        r = rng.random()
        cum = 0
        for bucket_name, frac in bucket_items:
            cum += frac
            if r <= cum:
                samples.append(sample_bucket(rng, bucket_name, seed_sp))
                break

    return samples


def speed_multiplier_from_samples(our_sp, competitor_samples):
    n = len(competitor_samples)
    below = sum(1 for c in competitor_samples if c < our_sp)
    pct = below / n
    return 0.1 + 0.8 * pct


def run_trials(seed_sp, include_ghosts, n_trials=N_TRIALS, base_seed=42):
    """Run Monte Carlo. Returns dict: (r,s,sp) -> stats."""

    # Pre-compute speed multiplier per sp per trial
    per_trial_speed = []
    for trial in range(n_trials):
        rng = random.Random(base_seed + trial * 7919)
        pop = build_population(rng, seed_sp, include_ghosts)
        speed_table = [speed_multiplier_from_samples(sp, pop) for sp in range(101)]
        per_trial_speed.append(speed_table)

    # Evaluate all allocations
    stats = {}
    for r in range(101):
        r_val = research(r)
        for s in range(101 - r):
            s_val = scale(s)
            rs = r_val * s_val
            for sp in range(101 - r - s):
                cost = BUDGET * (r + s + sp) / 100.0
                vals = [rs * per_trial_speed[t][sp] - cost for t in range(n_trials)]
                vals.sort()
                stats[(r, s, sp)] = {
                    "mean": sum(vals) / n_trials,
                    "median": vals[n_trials // 2],
                    "p10": vals[int(n_trials * 0.1)],
                    "p90": vals[int(n_trials * 0.9)],
                }
    return stats


def iterated_best_response(include_ghosts, n_iter=5, tol=1, base_seed=42):
    seed_sp = 40
    history = []
    stats = None
    for i in range(n_iter):
        mode_label = "ALL" if include_ghosts else "ENGAGED"
        print(f"\n=== [{mode_label}] Iteration {i+1} (seed_sp={seed_sp}) ===")
        stats = run_trials(seed_sp, include_ghosts, n_trials=N_TRIALS, base_seed=base_seed)
        best = max(stats.items(), key=lambda x: x[1]["mean"])
        alloc, m = best
        print(f"  Best: {alloc}  mean={m['mean']:>10,.0f}  p10={m['p10']:>10,.0f}  p90={m['p90']:>10,.0f}")
        history.append({
            "iteration": i + 1, "seed_sp": seed_sp, "best_alloc": alloc,
            "mean": round(m["mean"], 2), "p10": round(m["p10"], 2), "p90": round(m["p90"], 2),
        })
        new_sp = alloc[2]
        if abs(new_sp - seed_sp) <= tol:
            print(f"  CONVERGED")
            break
        seed_sp = new_sp
    return history, stats


def main():
    print(f"Bucket fractions: {BUCKETS}")
    print(f"N_COMPETITORS = {N_COMPETITORS}, N_TRIALS = {N_TRIALS}")

    print("\n" + "=" * 60)
    print("MODE A: rank across ALL 22k players (including 73.3% ghosts)")
    print("=" * 60)
    history_all, stats_all = iterated_best_response(include_ghosts=True)

    print("\n" + "=" * 60)
    print("MODE B: rank across ENGAGED players only (~5,900, no ghosts)")
    print("=" * 60)
    history_engaged, stats_engaged = iterated_best_response(include_ghosts=False)

    # Top-10 results per mode
    def top10(stats):
        ranked = sorted(stats.items(), key=lambda x: -x[1]["mean"])[:10]
        return [
            {"alloc": a, "mean": round(m["mean"], 2), "p10": round(m["p10"], 2), "p90": round(m["p90"], 2)}
            for a, m in ranked
        ]

    # Candidate comparison
    candidates = [(15, 44, 41), (15, 43, 42), (16, 46, 38), (18, 50, 32), (11, 29, 60), (14, 41, 45)]
    def compare(stats):
        return {
            f"{r}_{s}_{sp}": {
                "mean": round(stats[(r, s, sp)]["mean"], 2),
                "p10": round(stats[(r, s, sp)]["p10"], 2),
                "p90": round(stats[(r, s, sp)]["p90"], 2),
            }
            for (r, s, sp) in candidates if (r, s, sp) in stats
        }

    out = {
        "config": {
            "budget": BUDGET,
            "n_competitors": N_COMPETITORS,
            "n_trials": N_TRIALS,
            "buckets": BUCKETS,
        },
        "mode_A_all_players": {
            "iterations": history_all,
            "top10": top10(stats_all),
            "candidate_comparison": compare(stats_all),
        },
        "mode_B_engaged_only": {
            "iterations": history_engaged,
            "top10": top10(stats_engaged),
            "candidate_comparison": compare(stats_engaged),
        },
    }

    out_path = Path(__file__).parent / "invest_expand_results_v4.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWritten: {out_path}")

    print("\n=== MODE A: Top 10 by mean PnL (all-players rank) ===")
    for i, r in enumerate(out["mode_A_all_players"]["top10"], 1):
        print(f"  {i:>2}. {r['alloc']}  mean={r['mean']:>10,.0f}  p10={r['p10']:>10,.0f}  p90={r['p90']:>10,.0f}")

    print("\n=== MODE B: Top 10 by mean PnL (engaged-only rank) ===")
    for i, r in enumerate(out["mode_B_engaged_only"]["top10"], 1):
        print(f"  {i:>2}. {r['alloc']}  mean={r['mean']:>10,.0f}  p10={r['p10']:>10,.0f}  p90={r['p90']:>10,.0f}")

    print("\n=== MODE A: Candidate comparison ===")
    for k, v in out["mode_A_all_players"]["candidate_comparison"].items():
        print(f"  alloc_{k}:  mean={v['mean']:>10,.0f}  p10={v['p10']:>10,.0f}  p90={v['p90']:>10,.0f}")

    print("\n=== MODE B: Candidate comparison ===")
    for k, v in out["mode_B_engaged_only"]["candidate_comparison"].items():
        print(f"  alloc_{k}:  mean={v['mean']:>10,.0f}  p10={v['p10']:>10,.0f}  p90={v['p90']:>10,.0f}")


if __name__ == "__main__":
    main()
