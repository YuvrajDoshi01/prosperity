"""
Expanded brute-force solver for R2 Invest & Expand manual challenge.

Extends the v1 solver with:
  1. Wider mu grid (12 values: 5..60)
  2. Finer sigma grid (8 values)
  3. Additional speed models:
     - Normal (original)
     - Uniform over [low, high] (agnostic prior)
     - Bimodal (mix of low-bidders and high-bidders)
     - Rank-based simulation with N=200 sampled competitors
  4. Total scenario count: ~120 (vs 18 in v1)
  5. Total evaluations: 176,851 × ~120 = ~21M (still seconds)

Goal: identify an allocation that dominates across competitor-model
uncertainty, not just across Normal(mu, sigma) variations.

Outputs:
  1. Per-scenario optimum
  2. Robust optimum (max-min across ALL scenarios)
  3. Mean optimum
  4. Top-20 by mean
  5. Top-20 by worst-case
  6. Sensitivity tables for r=15,s=44,sp=41 (point-opt) and r=14,s=40,sp=46 (robust)
"""

import json
import math
import random
from pathlib import Path

BUDGET = 50_000
LOG_101 = math.log(101)


def research(r):
    return 200_000 * math.log(1 + r) / LOG_101


def scale(s):
    return 7 * s / 100


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def speed_normal(sp, mu, sigma):
    pct = _phi((sp - mu) / sigma)
    return max(0.1, min(0.9, 0.1 + 0.8 * pct))


def speed_uniform(sp, lo, hi):
    # Competitor sp ~ Uniform(lo, hi). Percentile = (sp - lo)/(hi - lo), clamped.
    if sp <= lo:
        pct = 0.0
    elif sp >= hi:
        pct = 1.0
    else:
        pct = (sp - lo) / (hi - lo)
    return max(0.1, min(0.9, 0.1 + 0.8 * pct))


def speed_bimodal(sp, frac_low, mu_low, sigma_low, mu_high, sigma_high):
    # Mixture: frac_low are lowballers, (1-frac_low) are highrollers
    pct = frac_low * _phi((sp - mu_low) / sigma_low) + (1 - frac_low) * _phi((sp - mu_high) / sigma_high)
    return max(0.1, min(0.9, 0.1 + 0.8 * pct))


def speed_rank_sim(sp, competitor_samples):
    # Actual rank-based simulation: count how many competitors are below sp
    n = len(competitor_samples)
    below = sum(1 for c in competitor_samples if c < sp)
    pct = below / n
    return max(0.1, min(0.9, 0.1 + 0.8 * pct))


def pnl(r, s, sp, speed_multiplier):
    gross = research(r) * scale(s) * speed_multiplier
    cost = BUDGET * (r + s + sp) / 100.0
    return gross - cost


def build_scenarios():
    scenarios = []

    # Normal distribution grid (wider and finer)
    mu_range = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60]
    sigma_range = [5, 8, 10, 12, 15, 18, 20, 25]
    for mu in mu_range:
        for sigma in sigma_range:
            scenarios.append({
                "name": f"normal_mu{mu}_s{sigma}",
                "fn": lambda sp, mu=mu, sigma=sigma: speed_normal(sp, mu, sigma)
            })

    # Uniform distribution
    for lo, hi in [(0, 50), (0, 70), (0, 100), (10, 60), (20, 80), (30, 70)]:
        scenarios.append({
            "name": f"uniform_{lo}_{hi}",
            "fn": lambda sp, lo=lo, hi=hi: speed_uniform(sp, lo, hi)
        })

    # Bimodal (e.g., 60% lowballers + 40% serious players)
    bimodal_configs = [
        (0.6, 10, 8, 50, 10),
        (0.5, 15, 10, 45, 12),
        (0.7, 5, 5, 55, 10),
        (0.4, 20, 8, 60, 8),
    ]
    for frac_lo, mu_lo, s_lo, mu_hi, s_hi in bimodal_configs:
        scenarios.append({
            "name": f"bimodal_f{frac_lo}_lo{mu_lo}_hi{mu_hi}",
            "fn": lambda sp, fl=frac_lo, ml=mu_lo, sl=s_lo, mh=mu_hi, sh=s_hi:
                speed_bimodal(sp, fl, ml, sl, mh, sh)
        })

    # Rank-based sim with N=200 competitors drawn from various priors
    rng = random.Random(42)
    for prior_name, sampler in [
        ("rank_sim_normal_30_15", lambda: max(0, min(100, int(rng.gauss(30, 15))))),
        ("rank_sim_normal_40_20", lambda: max(0, min(100, int(rng.gauss(40, 20))))),
        ("rank_sim_uniform_0_100", lambda: rng.randint(0, 100)),
        ("rank_sim_beta_2_5", lambda: int(100 * rng.betavariate(2, 5))),
        ("rank_sim_bimodal", lambda: int(rng.gauss(10, 5)) if rng.random() < 0.6 else int(rng.gauss(55, 10))),
    ]:
        samples = [sampler() for _ in range(200)]
        scenarios.append({
            "name": prior_name,
            "fn": lambda sp, samples=samples: speed_rank_sim(sp, samples)
        })

    return scenarios


def all_allocations():
    for r in range(101):
        for s in range(101 - r):
            for sp in range(101 - r - s):
                yield (r, s, sp)


def main():
    allocs = list(all_allocations())
    scenarios = build_scenarios()
    n_scen = len(scenarios)
    n_alloc = len(allocs)

    print(f"Allocations: {n_alloc:,}")
    print(f"Scenarios:   {n_scen}")
    print(f"Evaluations: {n_alloc * n_scen:,}")
    print()

    per_scenario_opt = {}
    for scen in scenarios:
        best_val = -math.inf
        best_alloc = None
        fn = scen["fn"]
        for r, s, sp in allocs:
            v = pnl(r, s, sp, fn(sp))
            if v > best_val:
                best_val = v
                best_alloc = (r, s, sp)
        per_scenario_opt[scen["name"]] = {
            "alloc": best_alloc,
            "pnl": round(best_val, 2),
        }

    # Pre-compute speed multiplier table per sp per scenario
    speed_by_scen_sp = [[0.0] * 101 for _ in range(n_scen)]
    for i, scen in enumerate(scenarios):
        fn = scen["fn"]
        for sp in range(101):
            speed_by_scen_sp[i][sp] = fn(sp)

    # Per-allocation stats across all scenarios
    alloc_stats = []
    for r, s, sp in allocs:
        base = research(r) * scale(s)
        cost = BUDGET * (r + s + sp) / 100.0
        vals = [base * speed_by_scen_sp[i][sp] - cost for i in range(n_scen)]
        mean_v = sum(vals) / n_scen
        worst_v = min(vals)
        best_v = max(vals)
        alloc_stats.append(((r, s, sp), mean_v, worst_v, best_v))

    alloc_stats.sort(key=lambda x: -x[1])  # by mean descending
    top20_mean = alloc_stats[:20]
    by_worst = sorted(alloc_stats, key=lambda x: -x[2])
    top20_robust = by_worst[:20]

    # Sensitivity tables
    def sensitivity_for(alloc):
        r, s, sp = alloc
        base = research(r) * scale(s)
        cost = BUDGET * (r + s + sp) / 100.0
        vals = {scenarios[i]["name"]: round(base * speed_by_scen_sp[i][sp] - cost, 2) for i in range(n_scen)}
        return {
            "alloc": alloc,
            "mean": round(sum(vals.values()) / n_scen, 2),
            "worst": round(min(vals.values()), 2),
            "best": round(max(vals.values()), 2),
            "by_scenario": vals,
        }

    candidates = [
        (15, 44, 41),  # v1 point-opt under mu=30, sigma=15
        (14, 40, 46),  # v1 robust opt
        (15, 40, 45),  # v1 heuristic
        (15, 46, 39),  # v1 mean-opt
        top20_mean[0][0],  # v2 mean-opt
        top20_robust[0][0],  # v2 robust-opt
    ]
    unique_cands = list(dict.fromkeys(candidates))
    sensitivities = {f"alloc_{c[0]}_{c[1]}_{c[2]}": sensitivity_for(c) for c in unique_cands}

    out = {
        "budget": BUDGET,
        "search_space": {"allocations": n_alloc, "scenarios": n_scen, "evaluations": n_alloc * n_scen},
        "per_scenario_opt": per_scenario_opt,
        "top20_mean": [{"alloc": a, "mean": round(m, 2), "worst": round(w, 2), "best": round(b, 2)}
                       for a, m, w, b in top20_mean],
        "top20_robust": [{"alloc": a, "mean": round(m, 2), "worst": round(w, 2), "best": round(b, 2)}
                         for a, m, w, b in top20_robust],
        "candidate_sensitivities": sensitivities,
    }

    out_path = Path(__file__).parent / "invest_expand_results_v2.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"Written: {out_path}")
    print()

    print("=== Per-scenario optima (by family) ===")
    for name, v in per_scenario_opt.items():
        print(f"  {name:<30} alloc={v['alloc']} pnl={v['pnl']:>12,.0f}")
    print()

    print("=== Top 10 by MEAN across all scenarios ===")
    for i, (alloc, m, w, b) in enumerate(top20_mean[:10], 1):
        print(f"  {i:2d}. {alloc} mean={m:>9,.0f} worst={w:>9,.0f} best={b:>9,.0f}")
    print()

    print("=== Top 10 by WORST-CASE (robust) ===")
    for i, (alloc, m, w, b) in enumerate(top20_robust[:10], 1):
        print(f"  {i:2d}. {alloc} worst={w:>9,.0f} mean={m:>9,.0f}")
    print()

    print("=== Candidate sensitivity ===")
    for name, s in sensitivities.items():
        print(f"  {name}: mean={s['mean']:>9,.0f} worst={s['worst']:>9,.0f} best={s['best']:>9,.0f}")


if __name__ == "__main__":
    main()
