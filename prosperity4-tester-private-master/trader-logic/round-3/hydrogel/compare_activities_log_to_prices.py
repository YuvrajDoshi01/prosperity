#!/usr/bin/env python3
"""
Compare IMC website submission JSON (activitiesLog) to official Round 3 price CSVs.

The website file is a single JSON object with an `activitiesLog` string: semicolon-separated
rows with the same header as `prices_round_3_day_*.csv`. The backtester loads those CSVs
as the source of truth, so row-equality (for keys present in both) is the right consistency check.

Example (from this `hydrogel` folder):
  python3 compare_activities_log_to_prices.py \\
    imc_website_logs/387381.log \\
    ../../../prosperity4bt/resources/round3
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from io import StringIO
from pathlib import Path


def load_activities_rows(activities_log: str) -> tuple[list[str], list[dict[str, str]]]:
    lines = [ln for ln in activities_log.strip().split("\n") if ln.strip()]
    if not lines:
        return [], []
    r = csv.DictReader(StringIO("\n".join(lines)), delimiter=";")
    fieldnames = r.fieldnames or []
    return list(fieldnames), list(r)


def index_prices_file(path: Path) -> dict[tuple[int, int, str], dict[str, str]]:
    out: dict[tuple[int, int, str], dict[str, str]] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            key = (int(row["day"]), int(row["timestamp"]), row["product"])
            out[key] = row
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("website_json", type=Path, help="IMC export, e.g. 387381.log (JSON with activitiesLog)")
    ap.add_argument(
        "prices_dir",
        type=Path,
        help="Directory containing prices_round_3_day_0.csv, ...",
    )
    ap.add_argument("--product", default=None, help="Only this product (default: all in log)")
    args = ap.parse_args()

    raw = json.loads(args.website_json.read_text(encoding="utf-8"))
    alog = raw.get("activitiesLog")
    if not alog or not str(alog).strip():
        print("No activitiesLog in JSON", file=sys.stderr)
        return 1

    header, act_rows = load_activities_rows(str(alog))
    if not act_rows:
        print("Empty activitiesLog", file=sys.stderr)
        return 1

    if args.product:
        act_rows = [r for r in act_rows if r.get("product") == args.product]
        if not act_rows:
            print(f"No rows for product {args.product!r}", file=sys.stderr)
            return 1

    key_cols = ("day", "timestamp", "product")
    compare_cols = [c for c in header if c not in key_cols]

    by_day: dict[int, list[dict[str, str]]] = {}
    for r in act_rows:
        d = int(r["day"])
        by_day.setdefault(d, []).append(r)

    total_rows = 0
    missing_in_file = 0
    value_mismatches = 0
    first_mismatch_examples: list[str] = []

    for day, rows in sorted(by_day.items()):
        ppath = args.prices_dir / f"prices_round_3_day_{day}.csv"
        if not ppath.exists():
            print(f"Missing price file for day {day}: {ppath}", file=sys.stderr)
            return 1
        file_index = index_prices_file(ppath)
        for r in rows:
            total_rows += 1
            key = (int(r["day"]), int(r["timestamp"]), r["product"])
            if key not in file_index:
                missing_in_file += 1
                continue
            frow = file_index[key]
            for c in compare_cols:
                a = (r.get(c) or "").strip()
                b = (frow.get(c) or "").strip()
                if a != b:
                    value_mismatches += 1
                    if len(first_mismatch_examples) < 8:
                        first_mismatch_examples.append(
                            f"day={day} ts={r['timestamp']} product={r['product']} col={c!r} web={a!r} file={b!r}"
                        )

    print(f"Website activity rows considered: {total_rows}")
    print(f"Keys not found in price CSV:        {missing_in_file}")
    print(f"Column value mismatches:            {value_mismatches}")
    if first_mismatch_examples:
        print("\nFirst mismatches:")
        for line in first_mismatch_examples:
            print(" ", line)

    # Coverage: for each (day, product) in log, what fraction of file rows are present
    for day in sorted(by_day):
        ppath = args.prices_dir / f"prices_round_3_day_{day}.csv"
        for product in sorted({r["product"] for r in by_day[day]}):
            wkeys = {
                (int(r["day"]), int(r["timestamp"]), r["product"])
                for r in by_day[day]
                if r["product"] == product
            }
            fcount = 0
            with ppath.open(newline="") as f:
                for row in csv.DictReader(f, delimiter=";"):
                    if int(row["day"]) == day and row["product"] == product:
                        fcount += 1
            if fcount:
                print(f"Coverage day={day} product={product}: log {len(wkeys)} / file {fcount} timestamps ({100.0 * len(wkeys) / fcount:.1f}%)")

    if missing_in_file or value_mismatches:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
