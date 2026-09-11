"""
R2 vs R1 data diff.

Loads all available days for both rounds and reports:
  - Price level + range per product
  - Spread distribution (mean, p50, p95, most common)
  - L1/L2 volume distribution
  - Mid autocorrelation (lag 1)
  - Per-tick % change distribution
  - One-sided book frequency
  - Trade count, avg qty, cadence

Outputs a side-by-side markdown table.
"""

import csv
from pathlib import Path
from statistics import mean, median, stdev
from collections import Counter
import math

REPO = Path(__file__).resolve().parents[2]
R1_DIR = REPO / "prosperity4bt/resources/round1"
R2_DIR = REPO / "prosperity4bt/resources/round2"


def load_prices(csv_path):
    """Returns dict[product] -> list of (ts, bid1, bv1, bid2, bv2, ask1, av1, ask2, av2, mid)."""
    out = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            prod = row["product"]
            ts = int(row["timestamp"])
            bid1 = int(row["bid_price_1"]) if row["bid_price_1"] else None
            bv1 = int(row["bid_volume_1"]) if row["bid_volume_1"] else 0
            bid2 = int(row["bid_price_2"]) if row["bid_price_2"] else None
            bv2 = int(row["bid_volume_2"]) if row["bid_volume_2"] else 0
            ask1 = int(row["ask_price_1"]) if row["ask_price_1"] else None
            av1 = int(row["ask_volume_1"]) if row["ask_volume_1"] else 0
            ask2 = int(row["ask_price_2"]) if row["ask_price_2"] else None
            av2 = int(row["ask_volume_2"]) if row["ask_volume_2"] else 0
            mid = float(row["mid_price"]) if row["mid_price"] else None
            out.setdefault(prod, []).append((ts, bid1, bv1, bid2, bv2, ask1, av1, ask2, av2, mid))
    return out


def load_trades(csv_path):
    out = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            prod = row.get("symbol") or row.get("product")
            ts = int(row["timestamp"])
            qty = int(row["quantity"])
            out.setdefault(prod, []).append((ts, qty))
    return out


def analyze_prices(rows, prod):
    mids = [r[9] for r in rows if r[9] is not None]
    bids = [r[1] for r in rows if r[1] is not None]
    asks = [r[5] for r in rows if r[5] is not None]
    spreads = [r[5] - r[1] for r in rows if r[1] is not None and r[5] is not None]
    bv1 = [r[2] for r in rows if r[1] is not None]
    av1 = [r[6] for r in rows if r[5] is not None]
    bv2 = [r[4] for r in rows if r[3] is not None]
    av2 = [r[8] for r in rows if r[7] is not None]

    # one-sided book frequency
    one_sided = sum(1 for r in rows if (r[1] is None) ^ (r[5] is None))
    both_sided = sum(1 for r in rows if (r[1] is not None) and (r[5] is not None))

    # AC(1) on mid
    n = len(mids)
    if n >= 3:
        m_mean = mean(mids)
        num = sum((mids[i] - m_mean) * (mids[i - 1] - m_mean) for i in range(1, n))
        den = sum((x - m_mean) ** 2 for x in mids)
        ac1 = num / den if den > 0 else 0.0
    else:
        ac1 = 0.0

    # diff AC(1) — mean reversion
    if n >= 3:
        diffs = [mids[i] - mids[i - 1] for i in range(1, n)]
        d_mean = mean(diffs)
        num = sum((diffs[i] - d_mean) * (diffs[i - 1] - d_mean) for i in range(1, len(diffs)))
        den = sum((x - d_mean) ** 2 for x in diffs)
        diff_ac1 = num / den if den > 0 else 0.0
    else:
        diff_ac1 = 0.0

    spread_hist = Counter(spreads)

    return {
        "product": prod,
        "n": len(rows),
        "mids_n": n,
        "mid_mean": mean(mids) if mids else 0,
        "mid_min": min(mids) if mids else 0,
        "mid_max": max(mids) if mids else 0,
        "mid_std": stdev(mids) if len(mids) > 1 else 0,
        "spread_mean": mean(spreads) if spreads else 0,
        "spread_median": median(spreads) if spreads else 0,
        "spread_mode": spread_hist.most_common(3),
        "bv1_mean": mean(bv1) if bv1 else 0,
        "av1_mean": mean(av1) if av1 else 0,
        "bv2_mean": mean(bv2) if bv2 else 0,
        "av2_mean": mean(av2) if av2 else 0,
        "one_sided_pct": one_sided / len(rows) * 100 if rows else 0,
        "ac1": ac1,
        "diff_ac1": diff_ac1,
    }


def analyze_trades(rows, prod):
    if not rows:
        return {"product": prod, "n": 0}
    qtys = [r[1] for r in rows]
    tss = [r[0] for r in rows]
    gaps = [tss[i] - tss[i - 1] for i in range(1, len(tss))]
    return {
        "product": prod,
        "n": len(rows),
        "qty_mean": mean(qtys),
        "qty_min": min(qtys),
        "qty_max": max(qtys),
        "gap_mean": mean(gaps) if gaps else 0,
        "gap_median": median(gaps) if gaps else 0,
    }


def round_summary(round_dir, days):
    all_prices = {}
    all_trades = {}
    for day in days:
        p_path = round_dir / f"prices_round_{round_dir.name[-1]}_day_{day}.csv"
        t_path = round_dir / f"trades_round_{round_dir.name[-1]}_day_{day}.csv"
        if not p_path.exists():
            continue
        prices = load_prices(p_path)
        trades = load_trades(t_path) if t_path.exists() else {}
        for prod, rows in prices.items():
            all_prices.setdefault(prod, []).extend(rows)
        for prod, rows in trades.items():
            all_trades.setdefault(prod, []).extend(rows)
    return all_prices, all_trades


def fmt(x, dp=2):
    if isinstance(x, (int, float)):
        return f"{x:,.{dp}f}"
    return str(x)


def main():
    r1_prices, r1_trades = round_summary(R1_DIR, [-2, -1, 0])  # R1 3 days
    r2_prices, r2_trades = round_summary(R2_DIR, [-1, 0, 1])  # R2 3 days

    print("# R2 vs R1 Data Diff\n")
    print(f"R1 days analyzed: -2, -1, 0 (3 days)")
    print(f"R2 days analyzed: -1, 0, 1 (3 days)\n")

    for prod in ("INTARIAN_PEPPER_ROOT", "ASH_COATED_OSMIUM"):
        print(f"\n## {prod}\n")
        r1 = analyze_prices(r1_prices.get(prod, []), prod)
        r2 = analyze_prices(r2_prices.get(prod, []), prod)

        print(f"| Metric | R1 | R2 | Delta |")
        print(f"|--------|-----:|-----:|-----:|")
        rows = [
            ("Rows (3d)", r1["n"], r2["n"]),
            ("Mid mean", r1["mid_mean"], r2["mid_mean"]),
            ("Mid min", r1["mid_min"], r2["mid_min"]),
            ("Mid max", r1["mid_max"], r2["mid_max"]),
            ("Mid range", r1["mid_max"] - r1["mid_min"], r2["mid_max"] - r2["mid_min"]),
            ("Mid stdev", r1["mid_std"], r2["mid_std"]),
            ("Spread mean", r1["spread_mean"], r2["spread_mean"]),
            ("Spread median", r1["spread_median"], r2["spread_median"]),
            ("L1 bid vol", r1["bv1_mean"], r2["bv1_mean"]),
            ("L1 ask vol", r1["av1_mean"], r2["av1_mean"]),
            ("L2 bid vol", r1["bv2_mean"], r2["bv2_mean"]),
            ("L2 ask vol", r1["av2_mean"], r2["av2_mean"]),
            ("One-sided %", r1["one_sided_pct"], r2["one_sided_pct"]),
            ("AC(1) mid", r1["ac1"], r2["ac1"]),
            ("AC(1) diff", r1["diff_ac1"], r2["diff_ac1"]),
        ]
        for name, r1v, r2v in rows:
            delta = r2v - r1v
            print(f"| {name} | {fmt(r1v)} | {fmt(r2v)} | {fmt(delta, 2)} |")

        print(f"\n**Spread mode (top-3)**")
        print(f"- R1: {r1['spread_mode']}")
        print(f"- R2: {r2['spread_mode']}")

        t1 = analyze_trades(r1_trades.get(prod, []), prod)
        t2 = analyze_trades(r2_trades.get(prod, []), prod)
        print(f"\n**Trades**")
        print(f"| Metric | R1 | R2 |")
        print(f"|--------|---:|---:|")
        for k in ("n", "qty_mean", "qty_min", "qty_max", "gap_mean", "gap_median"):
            print(f"| {k} | {fmt(t1.get(k, 0))} | {fmt(t2.get(k, 0))} |")


if __name__ == "__main__":
    main()
