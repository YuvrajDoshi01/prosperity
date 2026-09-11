"""
Brute-force solver for Round 2 Manual Challenge "Invest & Expand".

Budget = 50,000 XIRECs. Three pillars:
  Research(r) = 200_000 * ln(1 + r) / ln(101)            [logarithmic]
  Scale(s)    = 7 * s / 100                               [linear]
  Speed(sp)   = rank-based multiplier in [0.1, 0.9]       [game-theoretic]

PnL = Research * Scale * Speed  -  500 * (r + s + sp)

Search space: integer (r, s, sp) in [0, 100]^3 with r + s + sp <= 100.
Total valid combinations: 176,851.

Speed depends on competitor investment. We cannot brute-force competitors,
so we scan a grid of competitor-distribution scenarios:
  mu in {15, 20, 25, 30, 35, 40}  — mean competitor speed investment
  sigma in {10, 15, 20}           — spread
For each (mu, sigma), Speed(sp) = 0.1 + 0.8 * Phi((sp - mu) / sigma) clamped.

Outputs (written to invest_expand_results.json):
  1. per_scenario_opt: argmax for each (mu, sigma)
  2. robust_opt: argmax of min-over-scenarios PnL
  3. point_opt: argmax under mu=30, sigma=15 (mid-scenario)
  4. mean_opt: argmax of mean-over-scenarios PnL
  5. top20_mean: top 20 allocations by mean PnL
  6. top20_robust: top 20 allocations by worst-case PnL
  7. sensitivity_15_40_45: PnL across all 18 scenarios for our heuristic pick
"""

import json
import math
from pathlib import Path

BUDGET = 50_000
LOG_101 = math.log(101)


def research(r):
    return 200_000 * math.log(1 + r) / LOG_101


def scale(s):
    return 7 * s / 100


def _phi(x):
    """Standard normal CDF."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def speed_multiplier(sp, mu, sigma):
    """Rank-based multiplier in [0.1, 0.9], modeled as a smooth interpolation
    based on our percentile in the assumed competitor distribution.
    Higher sp -> higher percentile -> higher multiplier.
    """
    pct = _phi((sp - mu) / sigma)
    m = 0.1 + 0.8 * pct
    return max(0.1, min(0.9, m))


def pnl(r, s, sp, mu, sigma):
    gross = research(r) * scale(s) * speed_multiplier(sp, mu, sigma)
    cost = BUDGET * (r + s + sp) / 100.0
    return gross - cost


def scenarios():
    for mu in (15, 20, 25, 30, 35, 40):
        for sigma in (10, 15, 20):
            yield (mu, sigma)


def all_allocations():
    for r in range(0, 101):
        for s in range(0, 101 - r):
            for sp in range(0, 101 - r - s):
                yield (r, s, sp)


def main():
    allocs = list(all_allocations())
    scen_list = list(scenarios())

    print(f"Evaluating {len(allocs):,} allocations across {len(scen_list)} scenarios "
          f"({len(allocs) * len(scen_list):,} evaluations)...")

    per_scenario_opt = {}
    for mu, sigma in scen_list:
        best_val = -math.inf
        best_alloc = None
        for r, s, sp in allocs:
            v = pnl(r, s, sp, mu, sigma)
            if v > best_val:
                best_val = v
                best_alloc = (r, s, sp)
        per_scenario_opt[f"mu={mu},sigma={sigma}"] = {
            "alloc": best_alloc,
            "pnl": round(best_val, 2),
        }

    mean_ranked = []
    worst_ranked = []
    for r, s, sp in allocs:
        vals = [pnl(r, s, sp, mu, sigma) for mu, sigma in scen_list]
        mean_v = sum(vals) / len(vals)
        worst_v = min(vals)
        mean_ranked.append((mean_v, (r, s, sp), vals))
        worst_ranked.append((worst_v, (r, s, sp), vals))

    mean_ranked.sort(reverse=True, key=lambda x: x[0])
    worst_ranked.sort(reverse=True, key=lambda x: x[0])

    top20_mean = [
        {
            "alloc": alloc,
            "mean_pnl": round(mean_v, 2),
            "worst_pnl": round(min(vals), 2),
            "best_pnl": round(max(vals), 2),
        }
        for mean_v, alloc, vals in mean_ranked[:20]
    ]

    top20_robust = [
        {
            "alloc": alloc,
            "worst_pnl": round(worst_v, 2),
            "mean_pnl": round(sum(vals) / len(vals), 2),
            "best_pnl": round(max(vals), 2),
        }
        for worst_v, alloc, vals in worst_ranked[:20]
    ]

    mean_opt = top20_mean[0]
    robust_opt = top20_robust[0]

    point_best_val = -math.inf
    point_best_alloc = None
    for r, s, sp in allocs:
        v = pnl(r, s, sp, 30, 15)
        if v > point_best_val:
            point_best_val = v
            point_best_alloc = (r, s, sp)
    point_opt = {"alloc": point_best_alloc, "pnl": round(point_best_val, 2)}

    heuristic = (15, 40, 45)
    r, s, sp = heuristic
    sensitivity = {
        f"mu={mu},sigma={sigma}": round(pnl(r, s, sp, mu, sigma), 2)
        for mu, sigma in scen_list
    }
    heuristic_report = {
        "alloc": heuristic,
        "by_scenario": sensitivity,
        "mean": round(sum(sensitivity.values()) / len(sensitivity), 2),
        "worst": round(min(sensitivity.values()), 2),
        "best": round(max(sensitivity.values()), 2),
    }

    out = {
        "budget": BUDGET,
        "formulas": {
            "research": "200000 * ln(1 + r) / ln(101)",
            "scale": "7 * s / 100",
            "speed": "0.1 + 0.8 * Phi((sp - mu) / sigma) clamped to [0.1, 0.9]",
        },
        "per_scenario_opt": per_scenario_opt,
        "point_opt_mu30_sigma15": point_opt,
        "mean_opt": mean_opt,
        "robust_opt": robust_opt,
        "top20_mean": top20_mean,
        "top20_robust": top20_robust,
        "heuristic_sensitivity_15_40_45": heuristic_report,
    }

    out_path = Path(__file__).parent / "invest_expand_results.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"Written: {out_path}")

    print("\n=== Per-scenario optimum ===")
    for k, v in per_scenario_opt.items():
        print(f"  {k}: alloc={v['alloc']} PnL={v['pnl']:,.0f}")

    print(f"\n=== Point optimum (mu=30, sigma=15) ===")
    print(f"  alloc={point_opt['alloc']} PnL={point_opt['pnl']:,.0f}")

    print(f"\n=== Mean-PnL optimum (across 18 scenarios) ===")
    print(f"  alloc={mean_opt['alloc']} mean={mean_opt['mean_pnl']:,.0f} "
          f"worst={mean_opt['worst_pnl']:,.0f} best={mean_opt['best_pnl']:,.0f}")

    print(f"\n=== Robust optimum (max-min across 18 scenarios) ===")
    print(f"  alloc={robust_opt['alloc']} worst={robust_opt['worst_pnl']:,.0f} "
          f"mean={robust_opt['mean_pnl']:,.0f} best={robust_opt['best_pnl']:,.0f}")

    print(f"\n=== Heuristic (r=15, s=40, sp=45) sensitivity ===")
    print(f"  mean={heuristic_report['mean']:,.0f} "
          f"worst={heuristic_report['worst']:,.0f} "
          f"best={heuristic_report['best']:,.0f}")

    print("\n=== Top 10 by mean PnL ===")
    for i, row in enumerate(top20_mean[:10], 1):
        print(f"  {i:2d}. alloc={row['alloc']} mean={row['mean_pnl']:,.0f} "
              f"worst={row['worst_pnl']:,.0f}")

    print("\n=== Top 10 by worst-case PnL ===")
    for i, row in enumerate(top20_robust[:10], 1):
        print(f"  {i:2d}. alloc={row['alloc']} worst={row['worst_pnl']:,.0f} "
              f"mean={row['mean_pnl']:,.0f}")


if __name__ == "__main__":
    main()
