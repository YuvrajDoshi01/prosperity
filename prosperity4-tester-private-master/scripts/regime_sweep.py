"""Synthetic regime sweep — run a strategy against all 19 round99 regimes
and report per-regime PnL deltas vs a baseline.

Usage:
    python scripts/regime_sweep.py <strategy.py> [--baseline <baseline.py>] [--ticks N]

Phase 5.3 of the R4-prep roadmap. Verifies that strategy changes pass the
"≥ 11/13 regimes non-negative" acceptance criterion before merging.

Outputs a markdown table:

    | day | regime              | strategy | baseline | delta |
    |-----|---------------------|----------|----------|---|
    | 0   | UPTREND             | 12,500   | 12,200   | +300 |
    | ... |                     |          |          |   |
    | TOT | (sum)               | 235,000  | 230,000  | +5,000 |
    | NEG |                     |          |          | 2 of 19 |

Acceptance per the verification matrix:
- Phase 1/2 changes: ≥ 11/13 (or 16/19 for full sweep) regimes non-negative
- Phase 3 fidelity: rankings preserved (delta-rank stays stable across regimes)
- Phase 4 alphas: ≥ 10/13 non-negative
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Tuple


# Regime labels match generate.py REGIME_LABELS
REGIME_LABELS = [
    "UPTREND", "FLAT", "DOWNTREND", "REVERSAL",
    "ACO_CRASH", "ACO_FLASH", "PERMANENT", "CRASH_DEEP",
    "ALT_FV_HIGH", "ALT_FV_LOW", "MID_SHIFT", "DEFENSE_BOT", "VOLUME_BURST",
    "ASYM_OPEN",
    # R4-prep Phase 3.2
    "ASYM_MEAN", "MULTI_LEVEL_POST", "DRIFT_REVERSAL", "FLAT_WIDE_SPREAD", "DYNAMIC_TAKER",
]


def run_bt(strategy: str, day: int, ticks: int, match_mode: str = "default") -> Optional[float]:
    """Run BT for a single round99 day and return total PnL.

    Returns None on error.
    """
    cmd = [
        sys.executable, "-m", "prosperity4bt", strategy,
        f"99-{day}", "--ticks", str(ticks), "--no-out", "--no-progress",
        "--match-mode", match_mode,
    ]
    env = {"PYTHONPATH": "prosperity4bt"}
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180,
            env={**__import__("os").environ, **env},
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    # Parse "Total profit: X" from output
    m = re.search(r"Total profit: ([-\d,]+)", proc.stdout)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy", help="Path to strategy .py file")
    ap.add_argument("--baseline", default=None, help="Optional baseline strategy for delta comparison")
    ap.add_argument("--ticks", type=int, default=10000, help="Ticks per day (default 10000)")
    ap.add_argument("--match-mode", default="default", choices=["default", "imc"])
    ap.add_argument("--days", default=None, help="Comma-separated day list (default: all 19)")
    args = ap.parse_args()

    if args.days:
        days = [int(x) for x in args.days.split(",")]
    else:
        days = list(range(len(REGIME_LABELS)))

    print(f"# Regime sweep: {args.strategy}")
    if args.baseline:
        print(f"# Baseline:      {args.baseline}")
    print(f"# Ticks/day:     {args.ticks}")
    print(f"# Match mode:    {args.match_mode}")
    print(f"# Regimes:       {len(days)}")
    print()

    results: List[Tuple[int, str, Optional[float], Optional[float]]] = []
    for day in days:
        label = REGIME_LABELS[day] if day < len(REGIME_LABELS) else f"day{day}"
        strat_pnl = run_bt(args.strategy, day, args.ticks, args.match_mode)
        baseline_pnl = run_bt(args.baseline, day, args.ticks, args.match_mode) if args.baseline else None
        results.append((day, label, strat_pnl, baseline_pnl))
        delta = (strat_pnl - baseline_pnl) if (strat_pnl is not None and baseline_pnl is not None) else None
        delta_str = f"{delta:+,.0f}" if delta is not None else "-"
        s_str = f"{strat_pnl:,.0f}" if strat_pnl is not None else "ERR"
        b_str = f"{baseline_pnl:,.0f}" if baseline_pnl is not None else "-"
        print(f"day {day:>2} {label:<22} {s_str:>10}  vs  {b_str:>10}  delta={delta_str:>10}")

    # Summary
    if args.baseline:
        deltas = [(s - b) for _, _, s, b in results
                  if s is not None and b is not None]
        if deltas:
            total_delta = sum(deltas)
            negative_count = sum(1 for d in deltas if d < 0)
            print()
            print(f"# TOTAL  delta = {total_delta:+,.0f}")
            print(f"# NEG    {negative_count} of {len(deltas)} regimes negative")
            threshold_pass = negative_count <= len(deltas) - 11
            print(f"# ≥11/{len(deltas)} non-negative? {'PASS' if threshold_pass else 'FAIL'}")
    else:
        totals = [s for _, _, s, _ in results if s is not None]
        if totals:
            print()
            print(f"# TOTAL strategy PnL across {len(totals)} regimes: {sum(totals):,.0f}")


if __name__ == "__main__":
    main()
