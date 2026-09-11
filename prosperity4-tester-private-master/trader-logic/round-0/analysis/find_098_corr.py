#!/usr/bin/env python3
"""
find_098_corr.py — Exhaustive search for 0.98 correlation in Prosperity 4 data
===============================================================================

Someone reported a 0.98 correlation between two things.
This script tests EVERY plausible pair across all 3 days to find it.

Candidate pairs:
  A. Cross-product: TOMATOES mid vs EMERALDS mid (already known ~0, but check)
  B. Cross-product: TOMATOES spread vs EMERALDS spread
  C. L1 vs L2: bid_vol_1 vs bid_vol_2, ask_vol_1 vs ask_vol_2
  D. L1 vs L2: bid_vol vs ask_vol (same level)
  E. Bid volume vs ask volume (symmetry)
  F. TOMATOES bid_vol_1 vs ask_vol_1 (known ~93% symmetric)
  G. L2/L1 volume ratio stability
  H. Microprice vs mid
  I. Bid price gaps: (bid1 - bid2) vs (ask2 - ask1)
  J. Total bid volume vs total ask volume
  K. TOMATOES total volume vs EMERALDS total volume
  L. Cross-product volume ratios
  M. Price returns cross-correlation at various lags
  N. Spread-state matching between products
  O. Mid-price changes: TOMATOES dmid vs EMERALDS dmid
  P. Volume imbalance correlation across products
  Q. TOMATOES L1 bid vol vs L2 bid vol
  R. TOMATOES L1 ask vol vs L2 ask vol
"""

import csv
import os
import math
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "prosperity4bt", "resources", "round0")


def load_all(day):
    """Load prices for both products, aligned by timestamp."""
    fname = os.path.join(DATA_DIR, f"prices_round_0_day_{day}.csv")
    tom_data = {}
    em_data = {}

    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            ts = int(row["timestamp"])
            entry = {
                "bid1": int(row["bid_price_1"]) if row["bid_price_1"] else None,
                "bv1": int(row["bid_volume_1"]) if row["bid_volume_1"] else 0,
                "bid2": int(row["bid_price_2"]) if row["bid_price_2"] else None,
                "bv2": int(row["bid_volume_2"]) if row["bid_volume_2"] else 0,
                "bid3": int(row["bid_price_3"]) if row["bid_price_3"] else None,
                "bv3": int(row["bid_volume_3"]) if row["bid_volume_3"] else 0,
                "ask1": int(row["ask_price_1"]) if row["ask_price_1"] else None,
                "av1": int(row["ask_volume_1"]) if row["ask_volume_1"] else 0,
                "ask2": int(row["ask_price_2"]) if row["ask_price_2"] else None,
                "av2": int(row["ask_volume_2"]) if row["ask_volume_2"] else 0,
                "ask3": int(row["ask_price_3"]) if row["ask_price_3"] else None,
                "av3": int(row["ask_volume_3"]) if row["ask_volume_3"] else 0,
                "mid": float(row["mid_price"]) if row["mid_price"] else None,
            }
            if row["product"] == "TOMATOES":
                tom_data[ts] = entry
            elif row["product"] == "EMERALDS":
                em_data[ts] = entry

    return tom_data, em_data


def load_trades(day):
    """Load trades for both products."""
    fname = os.path.join(DATA_DIR, f"trades_round_0_day_{day}.csv")
    tom_trades = []
    em_trades = []
    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            t = {
                "ts": int(row["timestamp"]),
                "price": float(row["price"]),
                "qty": int(float(row["quantity"])),
            }
            if row["symbol"] == "TOMATOES":
                tom_trades.append(t)
            elif row["symbol"] == "EMERALDS":
                em_trades.append(t)
    return tom_trades, em_trades


def corr(x, y):
    """Pearson correlation between two lists."""
    n = len(x)
    if n < 3:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    sx = math.sqrt(max(0, sum((xi - mx) ** 2 for xi in x) / n))
    sy = math.sqrt(max(0, sum((yi - my) ** 2 for yi in y) / n))
    if sx < 1e-12 or sy < 1e-12:
        return 0.0
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / n
    return cov / (sx * sy)


def rank_corr(x, y):
    """Spearman rank correlation."""
    def ranks(vals):
        indexed = sorted(enumerate(vals), key=lambda t: t[1])
        r = [0.0] * len(vals)
        for rank, (orig_idx, _) in enumerate(indexed):
            r[orig_idx] = rank
        return r

    return corr(ranks(x), ranks(y))


def main():
    results = []

    for day in [-2, -1, 0]:
        print(f"\n{'='*70}")
        print(f"  DAY {day}")
        print(f"{'='*70}")

        tom, em = load_all(day)
        tom_trades, em_trades = load_trades(day)

        # Align timestamps
        common_ts = sorted(set(tom.keys()) & set(em.keys()))
        print(f"  Common timestamps: {len(common_ts)}")

        # Extract aligned series
        t_mid = [tom[ts]["mid"] for ts in common_ts]
        e_mid = [em[ts]["mid"] for ts in common_ts]
        t_bv1 = [tom[ts]["bv1"] for ts in common_ts]
        t_av1 = [tom[ts]["av1"] for ts in common_ts]
        t_bv2 = [tom[ts]["bv2"] for ts in common_ts]
        t_av2 = [tom[ts]["av2"] for ts in common_ts]
        e_bv1 = [em[ts]["bv1"] for ts in common_ts]
        e_av1 = [em[ts]["av1"] for ts in common_ts]
        e_bv2 = [em[ts]["bv2"] for ts in common_ts]
        e_av2 = [em[ts]["av2"] for ts in common_ts]
        t_bid1 = [tom[ts]["bid1"] for ts in common_ts if tom[ts]["bid1"]]
        t_ask1 = [tom[ts]["ask1"] for ts in common_ts if tom[ts]["ask1"]]
        e_bid1 = [em[ts]["bid1"] for ts in common_ts if em[ts]["bid1"]]
        e_ask1 = [em[ts]["ask1"] for ts in common_ts if em[ts]["ask1"]]

        t_spread = [tom[ts]["ask1"] - tom[ts]["bid1"] for ts in common_ts
                     if tom[ts]["ask1"] and tom[ts]["bid1"]]
        e_spread = [em[ts]["ask1"] - em[ts]["bid1"] for ts in common_ts
                     if em[ts]["ask1"] and em[ts]["bid1"]]

        # Derived
        t_dmid = [t_mid[i] - t_mid[i - 1] for i in range(1, len(t_mid))]
        e_dmid = [e_mid[i] - e_mid[i - 1] for i in range(1, len(e_mid))]

        t_total_bid = [tom[ts]["bv1"] + tom[ts]["bv2"] + tom[ts].get("bv3", 0) for ts in common_ts]
        t_total_ask = [tom[ts]["av1"] + tom[ts]["av2"] + tom[ts].get("av3", 0) for ts in common_ts]
        e_total_bid = [em[ts]["bv1"] + em[ts]["bv2"] + em[ts].get("bv3", 0) for ts in common_ts]
        e_total_ask = [em[ts]["av1"] + em[ts]["av2"] + em[ts].get("av3", 0) for ts in common_ts]

        t_obi = [(b - a) / (b + a) if (b + a) > 0 else 0 for b, a in zip(t_total_bid, t_total_ask)]
        e_obi = [(b - a) / (b + a) if (b + a) > 0 else 0 for b, a in zip(e_total_bid, e_total_ask)]

        # L2/L1 ratios
        t_l2l1_bid = [tom[ts]["bv2"] / tom[ts]["bv1"] if tom[ts]["bv1"] > 0 else 0 for ts in common_ts]
        t_l2l1_ask = [tom[ts]["av2"] / tom[ts]["av1"] if tom[ts]["av1"] > 0 else 0 for ts in common_ts]
        e_l2l1_bid = [em[ts]["bv2"] / em[ts]["bv1"] if em[ts]["bv1"] > 0 else 0 for ts in common_ts]
        e_l2l1_ask = [em[ts]["av2"] / em[ts]["av1"] if em[ts]["av1"] > 0 else 0 for ts in common_ts]

        # Microprice
        t_mp = [tom[ts]["bid1"] + tom[ts]["bv1"] / (tom[ts]["bv1"] + tom[ts]["av1"])
                * (tom[ts]["ask1"] - tom[ts]["bid1"])
                if (tom[ts]["bv1"] + tom[ts]["av1"]) > 0 else tom[ts]["mid"]
                for ts in common_ts]
        e_mp = [em[ts]["bid1"] + em[ts]["bv1"] / (em[ts]["bv1"] + em[ts]["av1"])
                * (em[ts]["ask1"] - em[ts]["bid1"])
                if (em[ts]["bv1"] + em[ts]["av1"]) > 0 else em[ts]["mid"]
                for ts in common_ts]

        # ── TEST ALL PAIRS ──
        pairs = [
            # Cross-product price
            ("TOM mid vs EM mid", t_mid, e_mid),
            ("TOM dmid vs EM dmid", t_dmid, e_dmid),
            ("TOM spread vs EM spread", t_spread[:len(e_spread)], e_spread[:len(t_spread)]),
            ("TOM microprice vs EM microprice", t_mp, e_mp),

            # Same-product symmetry
            ("TOM bv1 vs av1", t_bv1, t_av1),
            ("TOM bv2 vs av2", t_bv2, t_av2),
            ("EM bv1 vs av1", e_bv1, e_av1),
            ("EM bv2 vs av2", e_bv2, e_av2),
            ("TOM total_bid vs total_ask", t_total_bid, t_total_ask),
            ("EM total_bid vs total_ask", e_total_bid, e_total_ask),

            # Cross-product volume
            ("TOM bv1 vs EM bv1", t_bv1, e_bv1),
            ("TOM av1 vs EM av1", t_av1, e_av1),
            ("TOM bv2 vs EM bv2", t_bv2, e_bv2),
            ("TOM av2 vs EM av2", t_av2, e_av2),
            ("TOM total_bid vs EM total_bid", t_total_bid, e_total_bid),
            ("TOM total_ask vs EM total_ask", t_total_ask, e_total_ask),
            ("TOM OBI vs EM OBI", t_obi, e_obi),

            # L2/L1 ratios
            ("TOM L2/L1 bid ratio vs EM L2/L1 bid ratio", t_l2l1_bid, e_l2l1_bid),
            ("TOM L2/L1 ask ratio vs EM L2/L1 ask ratio", t_l2l1_ask, e_l2l1_ask),
            ("TOM L2/L1 bid vs TOM L2/L1 ask", t_l2l1_bid, t_l2l1_ask),
            ("EM L2/L1 bid vs EM L2/L1 ask", e_l2l1_bid, e_l2l1_ask),

            # Cross-level same product
            ("TOM bv1 vs TOM bv2", t_bv1, t_bv2),
            ("TOM av1 vs TOM av2", t_av1, t_av2),
            ("EM bv1 vs EM bv2", e_bv1, e_bv2),
            ("EM av1 vs EM av2", e_av1, e_av2),

            # Microprice vs mid
            ("TOM microprice vs TOM mid", t_mp, t_mid),
            ("EM microprice vs EM mid", e_mp, e_mid),

            # Cross-product OBI and volume imbalance
            ("TOM microprice vs EM microprice", t_mp, e_mp),
        ]

        # Rolling correlations / windowed
        # Check if bid1 changes are correlated across products
        t_dbid = [t_bid1[i] - t_bid1[i-1] for i in range(1, len(t_bid1))]
        e_dbid = [e_bid1[i] - e_bid1[i-1] for i in range(1, len(e_bid1))]
        min_len = min(len(t_dbid), len(e_dbid))
        pairs.append(("TOM dbid1 vs EM dbid1", t_dbid[:min_len], e_dbid[:min_len]))

        t_dask = [t_ask1[i] - t_ask1[i-1] for i in range(1, len(t_ask1))]
        e_dask = [e_ask1[i] - e_ask1[i-1] for i in range(1, len(e_ask1))]
        min_len = min(len(t_dask), len(e_dask))
        pairs.append(("TOM dask1 vs EM dask1", t_dask[:min_len], e_dask[:min_len]))

        # Absolute mid changes
        t_abs_dmid = [abs(d) for d in t_dmid]
        e_abs_dmid = [abs(d) for d in e_dmid]
        pairs.append(("TOM |dmid| vs EM |dmid|", t_abs_dmid, e_abs_dmid))

        # Cumulative sums
        t_cum = [sum(t_dmid[:i+1]) for i in range(len(t_dmid))]
        e_cum = [sum(e_dmid[:i+1]) for i in range(len(e_dmid))]
        pairs.append(("TOM cumulative dmid vs EM cumulative dmid", t_cum, e_cum))

        # Volume change correlations
        t_dbv1 = [t_bv1[i] - t_bv1[i-1] for i in range(1, len(t_bv1))]
        t_dav1 = [t_av1[i] - t_av1[i-1] for i in range(1, len(t_av1))]
        e_dbv1 = [e_bv1[i] - e_bv1[i-1] for i in range(1, len(e_bv1))]
        e_dav1 = [e_av1[i] - e_av1[i-1] for i in range(1, len(e_av1))]
        pairs.append(("TOM d(bv1) vs TOM d(av1)", t_dbv1, t_dav1))
        pairs.append(("EM d(bv1) vs EM d(av1)", e_dbv1, e_dav1))
        pairs.append(("TOM d(bv1) vs EM d(bv1)", t_dbv1, e_dbv1))

        # Spread states matching
        # Mid changes lagged cross-correlation
        for lag in [1, 2, 3, 5, 10]:
            n_lag = min(len(t_dmid), len(e_dmid)) - lag
            if n_lag > 10:
                pairs.append((f"TOM dmid vs EM dmid lag-{lag}", t_dmid[:n_lag], e_dmid[lag:lag+n_lag]))
                pairs.append((f"EM dmid vs TOM dmid lag-{lag}", e_dmid[:n_lag], t_dmid[lag:lag+n_lag]))

        # NOW: compute and sort
        day_results = []
        for name, x, y in pairs:
            n = min(len(x), len(y))
            if n < 10:
                continue
            r = corr(x[:n], y[:n])
            day_results.append((abs(r), r, n, name))

        day_results.sort(reverse=True)

        print(f"\n  {'Pair':<55s} {'r':>8s} {'|r|':>8s} {'n':>7s}")
        print(f"  {'-'*55} {'-'*8} {'-'*8} {'-'*7}")
        for abs_r, r, n, name in day_results[:30]:
            marker = " <<<" if abs_r > 0.95 else ""
            print(f"  {name:<55s} {r:>+8.4f} {abs_r:>8.4f} {n:>7d}{marker}")

        results.append((day, day_results))

    # ── CROSS-DAY CONSISTENCY ──
    print(f"\n\n{'='*70}")
    print("  CROSS-DAY CONSISTENCY (pairs with |r| > 0.90 on ANY day)")
    print(f"{'='*70}")

    all_names = set()
    for day, dr in results:
        for abs_r, r, n, name in dr:
            if abs_r > 0.90:
                all_names.add(name)

    if all_names:
        print(f"\n  {'Pair':<55s} {'Day -2':>8s} {'Day -1':>8s} {'Day 0':>8s}")
        print(f"  {'-'*55} {'-'*8} {'-'*8} {'-'*8}")
        for name in sorted(all_names):
            vals = []
            for day, dr in results:
                found = [r for abs_r, r, n, nm in dr if nm == name]
                vals.append(found[0] if found else 0)
            marker = " <<<" if all(abs(v) > 0.95 for v in vals) else ""
            print(f"  {name:<55s} {vals[0]:>+8.4f} {vals[1]:>+8.4f} {vals[2]:>+8.4f}{marker}")
    else:
        print("  None found with |r| > 0.90")


if __name__ == "__main__":
    main()
