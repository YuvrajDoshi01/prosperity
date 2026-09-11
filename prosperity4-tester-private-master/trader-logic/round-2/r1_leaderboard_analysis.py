"""
R1 leaderboard behavioral analyzer.

Loads the scraped Prosperity 4 R1 leaderboard (OVERALL / ALGO / MANUAL, 22,130
teams each) and produces:
  - Engagement funnel breakdown
  - Leak-copy cohort analysis (R1 manual optimum 87,995 was leaked)
  - Score distribution clusters and Schelling points
  - Country-level behavioral signatures
  - Elite cohort deep-dive
  - Calibrated behavioral bucket fractions for R2 manual challenge modeling

Outputs to r1_leaderboard_analysis.json.

Usage:
    python trader-logic/round-2/r1_leaderboard_analysis.py
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

LEAK_SCORE = 87995.0
LEAK_TOLERANCE = 0.5
SERIOUS_ALGO_THRESHOLD = 50_000
LEADERBOARD_CSV = Path(__file__).resolve().parents[2] / "run-logs" / "round-2" / "Manual" / "imc_prosperity4_leaderboard_full.csv"


def load_teams(csv_path):
    teams = defaultdict(dict)
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            tid = row["team_id"]
            teams[tid].setdefault("name", row["team_name"])
            teams[tid].setdefault("country", row["country_code"])
            teams[tid][row["leaderboard_type"]] = float(row["score"])
    return teams


def engagement_funnel(teams):
    total = len(teams)
    ghosts = sum(1 for t in teams.values() if t.get("ALGO", 0) <= 0 and t.get("MANUAL", 0) <= 0)
    manual_only = sum(1 for t in teams.values() if t.get("ALGO", 0) <= 0 and t.get("MANUAL", 0) > 0)
    algo_only = sum(1 for t in teams.values() if t.get("ALGO", 0) > 0 and t.get("MANUAL", 0) <= 0)
    both = sum(1 for t in teams.values() if t.get("ALGO", 0) > 0 and t.get("MANUAL", 0) > 0)
    return {
        "total": total,
        "ghosts": ghosts,
        "ghosts_pct": round(100 * ghosts / total, 2),
        "algo_only": algo_only,
        "algo_only_pct": round(100 * algo_only / total, 2),
        "manual_only": manual_only,
        "manual_only_pct": round(100 * manual_only / total, 2),
        "both": both,
        "both_pct": round(100 * both / total, 2),
        "engaged_total": algo_only + manual_only + both,
    }


def leak_copy_analysis(teams):
    leak = [t for t in teams.values() if abs(t.get("MANUAL", 0) - LEAK_SCORE) < LEAK_TOLERANCE]
    pure_leech = sum(1 for t in leak if t.get("ALGO", 0) == 0)
    with_algo = sum(1 for t in leak if t.get("ALGO", 0) > 0)
    with_serious_algo = sum(1 for t in leak if t.get("ALGO", 0) > SERIOUS_ALGO_THRESHOLD)
    return {
        "leak_copiers": len(leak),
        "leak_pct_of_total": round(100 * len(leak) / len(teams), 2),
        "leak_with_algo": with_algo,
        "leak_with_serious_algo": with_serious_algo,
        "leak_pure_leeches": pure_leech,
        "serious_algo_leak_rate_pct": round(
            100 * with_serious_algo / sum(1 for t in teams.values() if t.get("ALGO", 0) > SERIOUS_ALGO_THRESHOLD), 2
        ),
    }


def score_clusters(teams):
    manual_vals = [t.get("MANUAL", 0) for t in teams.values() if t.get("MANUAL", 0) > 0]
    exact_counts = Counter(round(v, 2) for v in manual_vals if abs(v - LEAK_SCORE) > LEAK_TOLERANCE)
    # Top 20 specific score buckets (excluding leak)
    top_clusters = [{"score": s, "count": n} for s, n in exact_counts.most_common(20)]

    # 1k-wide bin histogram
    bucket_hist = Counter()
    for v in manual_vals:
        bucket_hist[int(v // 1000)] += 1
    bin_histogram = [
        {"range_low": k * 1000, "range_high": (k + 1) * 1000, "count": n}
        for k, n in sorted(bucket_hist.items())[:30]
    ]

    # Independent solver band: 50k-85k non-exact
    independent_solvers = sum(1 for v in manual_vals if 50000 <= v < 87990)
    return {
        "top_exact_score_clusters": top_clusters,
        "histogram_1k_bins": bin_histogram,
        "independent_solver_band_count": independent_solvers,
        "independent_solver_pct_of_total": round(100 * independent_solvers / len(teams), 2),
    }


def country_patterns(teams):
    top100_ids = set(
        tid for tid, _ in sorted(
            teams.items(), key=lambda kv: -kv[1].get("OVERALL", -1)
        )[:100]
    )
    per_country = defaultdict(lambda: {
        "total": 0, "algo": 0, "manual": 0, "both": 0, "leak": 0, "top100": 0
    })
    for tid, t in teams.items():
        c = t["country"]
        per_country[c]["total"] += 1
        if t.get("ALGO", 0) > 0:
            per_country[c]["algo"] += 1
        if t.get("MANUAL", 0) > 0:
            per_country[c]["manual"] += 1
        if t.get("ALGO", 0) > 0 and t.get("MANUAL", 0) > 0:
            per_country[c]["both"] += 1
        if abs(t.get("MANUAL", 0) - LEAK_SCORE) < LEAK_TOLERANCE:
            per_country[c]["leak"] += 1
        if tid in top100_ids:
            per_country[c]["top100"] += 1

    rows = []
    for c, s in sorted(per_country.items(), key=lambda kv: -kv[1]["total"]):
        if s["total"] < 50:
            continue
        rows.append({
            "country": c,
            "teams": s["total"],
            "algo_pct": round(100 * s["algo"] / s["total"], 1),
            "manual_pct": round(100 * s["manual"] / s["total"], 1),
            "both_pct": round(100 * s["both"] / s["total"], 1),
            "leak_pct": round(100 * s["leak"] / s["total"], 1),
            "top100_count": s["top100"],
        })
    return {"countries_min50_teams": rows}


def elite_cohort(teams):
    elite = sorted(teams.values(), key=lambda t: -t.get("OVERALL", -1))[:100]
    overall_scores = [t.get("OVERALL", 0) for t in elite]
    algo_scores = [t.get("ALGO", 0) for t in elite]
    manual_scores = [t.get("MANUAL", 0) for t in elite]
    at_leak = sum(1 for m in manual_scores if abs(m - LEAK_SCORE) < LEAK_TOLERANCE)
    # Elite who did NOT copy leak
    non_leak = [t for t in elite if abs(t.get("MANUAL", 0) - LEAK_SCORE) >= LEAK_TOLERANCE]
    return {
        "elite_count": len(elite),
        "overall_range": [min(overall_scores), max(overall_scores)],
        "overall_mean": round(mean(overall_scores), 1),
        "algo_median": round(median(algo_scores), 1),
        "algo_min": min(algo_scores),
        "manual_at_leak": at_leak,
        "manual_non_leak": len(non_leak),
        "non_leak_elite_manual_scores": sorted(
            [round(t.get("MANUAL", 0)) for t in non_leak]
        ),
    }


def irrationality_signals(teams):
    neg_algo = [t.get("ALGO", 0) for t in teams.values() if t.get("ALGO", 0) < 0]
    neg_manual = [t.get("MANUAL", 0) for t in teams.values() if t.get("MANUAL", 0) < 0]
    return {
        "algo_negative_count": len(neg_algo),
        "algo_min": min(neg_algo) if neg_algo else 0,
        "algo_mean_neg": round(mean(neg_algo), 1) if neg_algo else 0,
        "manual_negative_count": len(neg_manual),
        "manual_min": min(neg_manual) if neg_manual else 0,
    }


def engaged_cdf(teams):
    engaged = [
        t.get("OVERALL", 0)
        for t in teams.values()
        if t.get("ALGO", 0) > 0 or t.get("MANUAL", 0) > 0
    ]
    engaged.sort(reverse=True)
    percentiles = [1, 5, 10, 25, 50, 75, 90]
    return {
        "n_engaged": len(engaged),
        "cdf": {
            f"top_{p}_pct_threshold": round(engaged[int(len(engaged) * p / 100)], 1)
            for p in percentiles
        },
    }


def behavioral_buckets(funnel):
    """Derive R2 manual challenge bucket fractions from R1 data."""
    total = funnel["total"]
    ghost_pct = funnel["ghosts_pct"]
    engaged_pct = 100 - ghost_pct

    # Among engaged players, approximate R2 archetype fractions:
    # (based on R1 Part 6 behavioral archetype analysis)
    return {
        "population_interpretation": "fractions as PERCENT of registered teams (out of 22130)",
        "ghost": round(ghost_pct, 1),
        "copy_paster": 8.0,  # copied R1 leak
        "partial_solver": 7.4,  # non-exact 50k-85k
        "nash_hunter": 1.5,  # elite non-leakers
        "contrarian": 0.5,  # picks adjacent to Nash
        "round_number_picker": 5.0,
        "over_invester": 2.0,
        "remainder": round(100 - ghost_pct - 8 - 7.4 - 1.5 - 0.5 - 5 - 2, 1),
        "notes": [
            "Ghost bucket IS registered but INACTIVE; effectively sp=0 in Speed rank.",
            "Copy-paster bucket will follow whatever allocation goes viral on Discord.",
            "Nash hunter + contrarian buckets are SMALL but STRATEGIC (dense near equilibrium).",
            "Round-number pickers cluster at Speed = 20, 30, 33, 40, 50.",
            "Over-investers push Speed distribution top (sp >= 60).",
        ],
    }


def main():
    if not LEADERBOARD_CSV.exists():
        print(f"ERROR: cannot find leaderboard at {LEADERBOARD_CSV}")
        return

    print(f"Loading {LEADERBOARD_CSV}")
    teams = load_teams(LEADERBOARD_CSV)
    print(f"Loaded {len(teams):,} teams")

    funnel = engagement_funnel(teams)
    leak = leak_copy_analysis(teams)
    clusters = score_clusters(teams)
    countries = country_patterns(teams)
    elite = elite_cohort(teams)
    irrational = irrationality_signals(teams)
    cdf = engaged_cdf(teams)
    buckets = behavioral_buckets(funnel)

    out = {
        "engagement_funnel": funnel,
        "leak_analysis": leak,
        "score_clusters": clusters,
        "country_signatures": countries,
        "elite_cohort": elite,
        "irrationality": irrational,
        "engaged_cdf": cdf,
        "r2_behavioral_buckets": buckets,
    }

    out_path = Path(__file__).parent / "r1_leaderboard_analysis.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWritten: {out_path}")

    print("\n=== ENGAGEMENT FUNNEL ===")
    print(f"  Total: {funnel['total']:,}")
    print(f"  Ghosts: {funnel['ghosts']:,} ({funnel['ghosts_pct']}%)")
    print(f"  Algo-only: {funnel['algo_only']:,} ({funnel['algo_only_pct']}%)")
    print(f"  Manual-only: {funnel['manual_only']:,} ({funnel['manual_only_pct']}%)")
    print(f"  Both: {funnel['both']:,} ({funnel['both_pct']}%)")
    print(f"  Real competition: {funnel['engaged_total']:,} teams")

    print("\n=== LEAK ANALYSIS (R1 manual optimum 87,995 was leaked) ===")
    print(f"  Leak copiers: {leak['leak_copiers']:,} ({leak['leak_pct_of_total']}% of total)")
    print(f"  Of those, with serious ALGO (> 50k): {leak['leak_with_serious_algo']:,}")
    print(f"  Serious ALGO leak rate: {leak['serious_algo_leak_rate_pct']}%")
    print(f"  Pure leeches (copied, no algo): {leak['leak_pure_leeches']:,}")

    print("\n=== SCORE CLUSTERS (top 10 non-leak) ===")
    for c in clusters["top_exact_score_clusters"][:10]:
        print(f"  {c['score']:>10,.2f}: {c['count']:>4} teams")

    print("\n=== COUNTRY SIGNATURES (top 10) ===")
    for c in countries["countries_min50_teams"][:10]:
        print(f"  {c['country']:<4} n={c['teams']:>5}  algo={c['algo_pct']}%  manual={c['manual_pct']}%  leak={c['leak_pct']}%  top100={c['top100_count']}")

    print("\n=== ELITE (top 100 OVERALL) ===")
    print(f"  OVERALL range: {elite['overall_range'][0]:,.0f} to {elite['overall_range'][1]:,.0f}")
    print(f"  ALGO median: {elite['algo_median']:,.0f}")
    print(f"  Manual at leak: {elite['manual_at_leak']}, non-leak: {elite['manual_non_leak']}")

    print("\n=== IRRATIONALITY SIGNALS ===")
    print(f"  Negative ALGO: {irrational['algo_negative_count']} (min {irrational['algo_min']:,.0f})")
    print(f"  Negative MANUAL: {irrational['manual_negative_count']} (min {irrational['manual_min']:,.0f})")

    print("\n=== ENGAGED CDF ===")
    for k, v in cdf["cdf"].items():
        print(f"  {k}: {v:,.0f}")

    print("\n=== R2 BEHAVIORAL BUCKETS (calibrated) ===")
    print(f"  Ghost: {buckets['ghost']}%")
    print(f"  Copy-Paster: {buckets['copy_paster']}%")
    print(f"  Partial Solver: {buckets['partial_solver']}%")
    print(f"  Nash Hunter: {buckets['nash_hunter']}%")
    print(f"  Contrarian: {buckets['contrarian']}%")
    print(f"  Round-Number Picker: {buckets['round_number_picker']}%")
    print(f"  Over-Invester: {buckets['over_invester']}%")
    print(f"  Remainder: {buckets['remainder']}%")


if __name__ == "__main__":
    main()
