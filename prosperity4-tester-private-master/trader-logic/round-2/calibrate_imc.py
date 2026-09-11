"""Calibrate ACO TAKER_PARAMS extra_rate against R2 round98 website ground truth.

round98 CSV = submission 274128 data (verified 100% book match).
Website 274128 (r2_v2 = r1_v4 + MAF bid): IPR 7,386 / ACO 1,026.25 / TOTAL 8,412.25.

WARNING: Each R2 submission gets randomized book data ("slightly randomized
for every submission"). round98 only matches 274128; other submissions
(275130: 21.3%, 275498: 20.6%, 286442: 20.9%) have different books.

Best calibration: extra_rate=0.038 -> ACO BT 1,004 (-2.2%), total 8,407 (-0.1%).
IPR needs no supplement (+0.2% error, only 4 taker round-trips worth ~2 PnL).

Usage:
    python trader-logic/round-2/calibrate_imc.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MATCHER = REPO / "prosperity4bt" / "tools" / "order_match_maker.py"
PYTHONPATH = str(REPO / "prosperity4bt")

ACO_SWEEP = [0.00, 0.010, 0.020, 0.025, 0.030, 0.035, 0.036, 0.037, 0.038, 0.039, 0.040, 0.042, 0.045, 0.050, 0.064]

# 274128 website ground truth (round98 CSV = 274128's data, verified 100% book match)
WEBSITE_R2_ACO = 1026
WEBSITE_R2_TOTAL = 8412
WEBSITE_R1_ACO = 3091


def patch_aco_rate(rate: float) -> None:
    text = MATCHER.read_text(encoding="utf-8")
    text = re.sub(
        r'("ASH_COATED_OSMIUM":\s*\{"qty_range":\s*\(2,\s*10\),\s*\n\s+"extra_rate":\s*)[0-9.]+',
        rf'\g<1>{rate}',
        text,
    )
    MATCHER.write_text(text, encoding="utf-8")


def run_bt(strategy: Path, round_day: str, ticks: int) -> dict[str, int]:
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    result = subprocess.run(
        [
            sys.executable, "-m", "prosperity4bt",
            str(strategy), round_day,
            "--ticks", str(ticks),
            "--match-mode", "imc",
            "--no-out", "--no-progress",
        ],
        env=env, capture_output=True, text=True, cwd=str(REPO),
    )
    out = result.stdout + result.stderr
    values = {}
    for key, label in (("IPR", "INTARIAN_PEPPER_ROOT"), ("ACO", "ASH_COATED_OSMIUM"), ("TOTAL", "Total profit")):
        m = re.search(rf"{label}:\s*([-\d,]+)", out)
        if m:
            values[key] = int(m.group(1).replace(",", ""))
    return values


def main() -> None:
    # r1_v4 is the correct algo for round98 calibration (274128 = r2_v2 = r1_v4 + MAF bid, same run() logic)
    r1_v4 = REPO / "trader-logic" / "round-1" / "r1_v4.py"

    original = MATCHER.read_text(encoding="utf-8")
    try:
        print("ACO extra_rate sweep — R2 round98 (target ACO 1,026 / TOTAL 8,412) + R1 day 0 (target ACO 3,091)\n")
        print(f"{'rate':>6}  {'R2_IPR':>7}  {'R2_ACO':>7}  {'R2_TOT':>7}  {'ACO_err%':>8}  {'TOT_err':>7}  {'R1_ACO':>7}  {'R1_err%':>8}")
        print("-" * 80)

        rows = []
        for rate in ACO_SWEEP:
            patch_aco_rate(rate)
            r2 = run_bt(r1_v4, "98", 1000)
            r1 = run_bt(r1_v4, "1-0", 1000)
            if "TOTAL" not in r2 or "ACO" not in r1:
                continue
            aco_err = abs(r2["ACO"] - WEBSITE_R2_ACO) / WEBSITE_R2_ACO * 100
            tot_err = abs(r2["TOTAL"] - WEBSITE_R2_TOTAL)
            r1_err = abs(r1["ACO"] - WEBSITE_R1_ACO) / WEBSITE_R1_ACO * 100
            rows.append((rate, r2, r1, aco_err, tot_err, r1_err))
            print(f"{rate:>6.3f}  {r2['IPR']:>7}  {r2['ACO']:>7}  {r2['TOTAL']:>7}  {aco_err:>7.1f}%  {tot_err:>7}  {r1['ACO']:>7}  {r1_err:>7.1f}%")

        print()
        best = min(rows, key=lambda row: row[4]) if rows else None
        if best:
            rate, r2, r1, aco_err, tot_err, r1_err = best
            print(f"Winner by R2 total error: extra_rate = {rate}")
            print(f"  R2 breakdown: IPR={r2['IPR']} (website 7,386), ACO={r2['ACO']} (website 1,026), TOTAL={r2['TOTAL']} (website 8,412)")
            print(f"  R1 ACO drift: {r1_err:.1f}% (R1 ACO={r1['ACO']}, website 3,091)")
    finally:
        MATCHER.write_text(original, encoding="utf-8")
        print("\nRestored original TAKER_PARAMS. Edit the file manually using the winner above.")


if __name__ == "__main__":
    main()
