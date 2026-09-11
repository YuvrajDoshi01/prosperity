#!/usr/bin/env python3
"""
Build a `hydrogel_full_diagnostic.py` report folder from an IMC website submission JSON.

The website file contains `activitiesLog` (semicolon CSV) with the same columns as
`prices_round_3_day_*.csv`. This script writes those rows to a price file, then runs
the full diagnostic so you can open the result in the Streamlit dashboard next to
`day0` / `day1` / `day2` reports (multiselect compares series by `__day` color).

Example:
  python3 website_activities_to_report.py \\
    imc_website_logs/387381.log \\
    --out dashboard_r3/day2_log_387381 \\
    --product HYDROGEL_PACK
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from io import StringIO
from pathlib import Path


def activities_to_prices_csv(website_json: Path, out_csv: Path, product: str) -> int:
    data = json.loads(website_json.read_text(encoding="utf-8"))
    alog = data.get("activitiesLog")
    if not alog or not str(alog).strip():
        raise SystemExit("No activitiesLog in JSON")

    lines = [ln for ln in str(alog).strip().split("\n") if ln.strip()]
    r = csv.DictReader(StringIO("\n".join(lines)), delimiter=";")
    fieldnames = r.fieldnames
    if not fieldnames:
        raise SystemExit("Empty activities header")

    rows = [row for row in r if (row.get("product") or "").strip() == product]
    if not rows:
        raise SystemExit(f"No rows for product={product!r}")

    # Stable order: one row per (day, timestamp) for this product
    def sort_key(row: dict[str, str]) -> tuple:
        return (int(row["day"]), int(row["timestamp"]))

    rows.sort(key=sort_key)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("website_json", type=Path, help="IMC export (JSON with activitiesLog)")
    ap.add_argument("--out", type=Path, required=True, help="Output report directory for hydrogel_full_diagnostic")
    ap.add_argument("--product", default="HYDROGEL_PACK")
    ap.add_argument(
        "--trades",
        type=Path,
        default=None,
        help="Optional trades_round_3_day_*.csv for the same day (joins only where timestamps align)",
    )
    ap.add_argument("--make-plots", action="store_true", help="Pass through to hydrogel_full_diagnostic")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    diag = here / "hydrogel_full_diagnostic.py"
    if not diag.exists():
        print(f"Missing {diag}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    prices_path = args.out / "_prices_from_website_activitiesLog.csv"
    n = activities_to_prices_csv(args.website_json, prices_path, args.product)

    cmd: list[str | Path] = [
        sys.executable,
        str(diag),
        "--prices",
        str(prices_path),
        "--out",
        str(args.out),
        "--product",
        args.product,
    ]
    if args.trades:
        cmd += ["--trades", str(args.trades)]
    if args.make_plots:
        cmd += ["--make-plots"]

    rc = subprocess.call(cmd)
    if rc != 0:
        return rc
    print(f"OK: {n} {args.product!r} website rows; price snapshot: {prices_path} → report: {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
