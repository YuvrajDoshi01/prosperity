"""
Multi-seed, multi-strategy synthetic regime test runner.

For each seed: generates round99 CSVs, runs each strategy, captures per-day PnL.
Aggregates mean/median/min/max across seeds per (strategy, regime).

Run:
  python trader-logic/round-1/experiments/synthetic/run_all.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from statistics import mean, median, stdev

import os as _os
# Default to 25 seeds; override via env SEEDS=N for 50+ runs.
_SEED_COUNT = int(_os.environ.get("SEEDS", "25"))
SEEDS = [42 + 73 * i for i in range(_SEED_COUNT)]
STRATEGIES = {
    "r1_v14_def": "trader-logic/round-1/r1_v14_defensive.py",
    "r1_v17": "trader-logic/round-1/r1_v17.py",
    "r1_v18": "trader-logic/round-1/r1_v18.py",
}
REGIMES = [
    "UPTREND", "FLAT", "DOWNTREND", "REVERSAL",
    "ACO_CRASH", "ACO_FLASH", "PERMANENT", "CRASH_DEEP",
    "ALT_FV_HIGH", "ALT_FV_LOW", "MID_SHIFT", "DEFENSE_BOT", "VOLUME_BURST",
    "ASYM_OPEN",
]
TICKS = 10_000

REPO = Path(__file__).resolve().parents[4]
GENERATOR = REPO / "trader-logic/round-1/experiments/synthetic/generate.py"

DAY_RE = re.compile(r"Round 99 day (\d+): ([-\d,]+)")


def run_strategy(strategy_path: str) -> dict[int, int]:
    """Return {day: pnl} for a single strategy run on round99."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "prosperity4bt")
    cmd = [
        sys.executable, "-m", "prosperity4bt",
        strategy_path, "99",
        "--ticks", str(TICKS), "--no-out", "--no-progress",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, env=env)
    pnl = {}
    for line in result.stdout.splitlines():
        m = DAY_RE.search(line)
        if m:
            pnl[int(m.group(1))] = int(m.group(2).replace(",", ""))
    return pnl


def regenerate(seed: int):
    subprocess.run(
        [sys.executable, str(GENERATOR), str(seed)],
        cwd=REPO, check=True, capture_output=True,
    )


def main():
    # results[strategy][regime_idx] = [pnl_seed1, pnl_seed2, ...]
    results = {s: {d: [] for d in range(len(REGIMES))} for s in STRATEGIES}

    for seed in SEEDS:
        print(f"\n{'='*70}\nSeed {seed}\n{'='*70}")
        regenerate(seed)
        for name, path in STRATEGIES.items():
            pnl = run_strategy(path)
            for day in range(len(REGIMES)):
                results[name][day].append(pnl.get(day, 0))
            total = sum(pnl.values())
            per_day = " | ".join(f"{REGIMES[d]}={pnl.get(d, 0):>8,}" for d in range(len(REGIMES)))
            print(f"  {name:12s}: {per_day} | total={total:>9,}")

    # Aggregate
    print("\n" + "=" * 100)
    print(f"AGGREGATE ACROSS {len(SEEDS)} SEEDS (mean, [min..max])")
    print("=" * 100)
    print(f"  {'Strategy':<12s} | " + " | ".join(f"{r:^22s}" for r in REGIMES) + " | " + "TOTAL (mean)".center(14))
    print("  " + "-" * 12 + "-|-" + "-|-".join(["-" * 22] * len(REGIMES)) + "-|-" + "-" * 14)
    for name in STRATEGIES:
        cells = []
        total_mean = 0
        for day in range(len(REGIMES)):
            vals = results[name][day]
            m = mean(vals)
            total_mean += m
            cells.append(f"{m:>8,.0f} [{min(vals):>6,.0f}..{max(vals):>6,.0f}]")
        print(f"  {name:<12s} | " + " | ".join(cells) + f" | {total_mean:>12,.0f}")

    # Ranking by total mean
    print("\nRanking by total mean PnL:")
    ranked = sorted(
        [(n, sum(mean(results[n][d]) for d in range(len(REGIMES)))) for n in STRATEGIES],
        key=lambda x: -x[1],
    )
    for i, (n, tot) in enumerate(ranked):
        print(f"  {i + 1}. {n:12s}  {tot:>12,.0f}")

    import math as _math

    def paired_delta(name_a, name_b, a_label, b_label):
        print(f"\n{name_b} vs {name_a} per regime (mean delta with SE, significance):")
        for day in range(len(REGIMES)):
            a_vals = results[name_a][day]
            b_vals = results[name_b][day]
            a_m = mean(a_vals)
            b_m = mean(b_vals)
            delta = b_m - a_m
            diffs = [x - y for x, y in zip(b_vals, a_vals)]
            se = stdev(diffs) / _math.sqrt(len(diffs)) if len(diffs) > 1 and stdev(diffs) > 0 else 0
            if se == 0:
                sig = "(identical)" if abs(delta) < 0.5 else "***"
            else:
                sig = "***" if abs(delta) > 2 * se else ("*" if abs(delta) > se else " ")
            print(f"  {REGIMES[day]:>10s}: {a_label}={a_m:>9,.0f}  {b_label}={b_m:>9,.0f}  delta={delta:+9,.0f}  SE={se:>5,.0f}  {sig}")

    paired_delta("r1_v14_def", "r1_v17", "v14", "v17")
    paired_delta("r1_v14_def", "r1_v18", "v14", "v18")
    paired_delta("r1_v17", "r1_v18", "v17", "v18")


if __name__ == "__main__":
    main()
