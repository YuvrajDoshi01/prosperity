"""
v11 parameter sweep for the ACO defensive frontier.

Sweeps ACO_MAX_CONCESSION (cubic skew magnitude at pos=LIMIT) and
ACO_CRASH_THRESHOLD (mid deviation at which circuit breaker fires) across
a 3x3 Cartesian grid. Evaluates each combo on 4 regimes x N seeds.

The goal is to find the insurance/cost frontier:
  - Too-tight THRESHOLD = false positives in normal noise
  - Too-loose THRESHOLD = late detection of real crashes
  - Too-small CONCESSION = inventory piles up during sustained adverse flow
  - Too-large CONCESSION = crosses own quotes in normal conditions

Usage:
  python trader-logic/round-1/experiments/synthetic/param_sweep.py
  SEEDS=50 python trader-logic/round-1/experiments/synthetic/param_sweep.py
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from statistics import mean, stdev
import math

SEEDS_N = int(os.environ.get("SEEDS", "25"))
SEEDS = [42 + 73 * i for i in range(SEEDS_N)]

# Param grid
MAX_CONCESSIONS = [4.0, 8.0, 12.0]
CRASH_THRESHOLDS = [15, 25, 35]

# Regimes to evaluate (day index in round 99)
REGIMES = {
    "UPTREND": 0,
    "ACO_CRASH": 4,
    "ACO_FLASH": 5,
    "PERMANENT": 6,
}
TICKS = 10_000

REPO = Path(__file__).resolve().parents[4]
GENERATOR = REPO / "trader-logic/round-1/experiments/synthetic/generate.py"
V11_SOURCE = REPO / "trader-logic/round-1/r1_v11_defensive.py"

DAY_RE = re.compile(r"Round 99 day (\d+): ([-\d,]+)")


def make_variant(max_concession: float, crash_threshold: int) -> Path:
    """Write a copy of v11 with overridden params into a tempfile. Returns path."""
    src = V11_SOURCE.read_text(encoding="utf-8")
    patched = re.sub(
        r"ACO_MAX_CONCESSION\s*=\s*[\d.]+",
        f"ACO_MAX_CONCESSION = {max_concession}",
        src,
    )
    patched = re.sub(
        r"ACO_CRASH_THRESHOLD\s*=\s*\d+",
        f"ACO_CRASH_THRESHOLD = {crash_threshold}",
        patched,
    )
    tmp = Path(tempfile.mkdtemp(prefix="v11_sweep_")) / f"v11_c{int(max_concession)}_t{crash_threshold}.py"
    tmp.write_text(patched, encoding="utf-8")
    return tmp


def regenerate(seed: int):
    subprocess.run(
        [sys.executable, str(GENERATOR), str(seed)],
        cwd=REPO, check=True, capture_output=True,
    )


def run_variant(strategy_path: Path) -> dict[int, int]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "prosperity4bt")
    cmd = [
        sys.executable, "-m", "prosperity4bt",
        str(strategy_path), "99",
        "--ticks", str(TICKS), "--no-out", "--no-progress",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, env=env)
    pnl = {}
    for line in result.stdout.splitlines():
        m = DAY_RE.search(line)
        if m:
            pnl[int(m.group(1))] = int(m.group(2).replace(",", ""))
    return pnl


def main():
    combos = [(c, t) for c in MAX_CONCESSIONS for t in CRASH_THRESHOLDS]
    print(f"Sweeping {len(combos)} param combos x {len(REGIMES)} regimes x {len(SEEDS)} seeds = {len(combos) * len(REGIMES) * len(SEEDS)} runs")
    print(f"MAX_CONCESSION: {MAX_CONCESSIONS}")
    print(f"CRASH_THRESHOLD: {CRASH_THRESHOLDS}")
    print(f"Regimes: {list(REGIMES.keys())}")
    print()

    # results[(c, t)][regime_name] = [pnl_per_seed, ...]
    results = {combo: {r: [] for r in REGIMES} for combo in combos}

    variants = {combo: make_variant(*combo) for combo in combos}

    for i, seed in enumerate(SEEDS):
        print(f"Seed {seed} ({i + 1}/{len(SEEDS)})", flush=True)
        regenerate(seed)
        for combo in combos:
            pnl = run_variant(variants[combo])
            for rname, day_idx in REGIMES.items():
                results[combo][rname].append(pnl.get(day_idx, 0))

    # Aggregate
    print("\n" + "=" * 110)
    print(f"PARAMETER SWEEP RESULTS ({len(SEEDS)} seeds, mean PnL per regime)")
    print("=" * 110)
    header = "  (CONC, THRESH) | " + " | ".join(f"{r:^20s}" for r in REGIMES) + " |  TOTAL (mean)"
    print(header)
    print("  " + "-" * 15 + "-|-" + "-|-".join(["-" * 20] * len(REGIMES)) + "-|-" + "-" * 14)

    for combo in combos:
        c, t = combo
        cells = []
        total = 0
        for rname in REGIMES:
            vals = results[combo][rname]
            m = mean(vals)
            s = stdev(vals) / math.sqrt(len(vals)) if len(vals) > 1 else 0
            cells.append(f"{m:>8,.0f} +/-{s:>5,.0f}")
            total += m
        print(f"  ({c:>4.0f}, {t:>4d})  | " + " | ".join(cells) + f" |  {total:>12,.0f}")

    # Highlight: v11 baseline (8, 25) vs best combo per regime
    print("\nBest combo per regime (mean PnL):")
    for rname in REGIMES:
        best = max(combos, key=lambda c: mean(results[c][rname]))
        baseline_combo = (8.0, 25)
        best_m = mean(results[best][rname])
        base_m = mean(results[baseline_combo][rname])
        print(f"  {rname:>10s}: baseline(8,25)={base_m:>9,.0f}  best={best} -> {best_m:>9,.0f}  delta={best_m - base_m:+8,.0f}")

    # Total ranking
    totals = [(combo, sum(mean(results[combo][r]) for r in REGIMES)) for combo in combos]
    totals.sort(key=lambda x: -x[1])
    print("\nTop 5 by total mean PnL across all regimes:")
    for rank, (combo, t) in enumerate(totals[:5], 1):
        print(f"  {rank}. {combo}: {t:>12,.0f}")


if __name__ == "__main__":
    main()
