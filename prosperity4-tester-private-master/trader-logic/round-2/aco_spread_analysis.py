"""
ACO (ASH_COATED_OSMIUM) Round 2 Spread & Microstructure Analysis
================================================================
Research-only script. Analyzes bid-mid/ask-mid spreads, spread regimes,
FV location, trade flow, and structural changes vs R1.
"""

import pandas as pd
import numpy as np
from collections import Counter
from pathlib import Path

DATA_DIR = Path("/Users/y0d046w/Desktop/prosperity4-tester-private/trader-logic/round-2/data")
PRODUCT = "ASH_COATED_OSMIUM"
DAYS = [-2, -1, 0, 1]

SEP = "=" * 80


def load_prices(day):
    fp = DATA_DIR / f"prices_round_2_day_{day}.csv"
    df = pd.read_csv(fp, sep=";")
    return df[df["product"] == PRODUCT].copy()


def load_trades(day):
    fp = DATA_DIR / f"trades_round_2_day_{day}.csv"
    df = pd.read_csv(fp, sep=";")
    return df[df["symbol"] == PRODUCT].copy()


def analyze_prices(day):
    df = load_prices(day)
    n_total = len(df)

    # Identify book state
    has_bid = df["bid_price_1"].notna()
    has_ask = df["ask_price_1"].notna()
    both_sides = has_bid & has_ask
    bid_only = has_bid & ~has_ask
    ask_only = ~has_bid & has_ask
    empty_book = ~has_bid & ~has_ask

    print(f"\n{'=' * 80}")
    print(f"  DAY {day}: ACO PRICE ANALYSIS")
    print(f"{'=' * 80}")
    print(f"  Total ticks: {n_total}")
    print(f"  Two-sided book: {both_sides.sum()} ({100*both_sides.sum()/n_total:.1f}%)")
    print(f"  Bid-only:       {bid_only.sum()} ({100*bid_only.sum()/n_total:.1f}%)")
    print(f"  Ask-only:       {ask_only.sum()} ({100*ask_only.sum()/n_total:.1f}%)")
    print(f"  Empty book:     {empty_book.sum()} ({100*empty_book.sum()/n_total:.1f}%)")

    # Work with two-sided ticks only for spread analysis
    ts = df[both_sides].copy()
    n_ts = len(ts)

    best_bid = ts["bid_price_1"].values
    best_ask = ts["ask_price_1"].values
    mid = (best_bid + best_ask) / 2.0

    spread = best_ask - best_bid
    bid_to_mid = mid - best_bid  # always >= 0
    ask_to_mid = best_ask - mid  # always >= 0

    # Mid price stats
    print(f"\n  --- Mid Price ---")
    print(f"  Mean:   {np.mean(mid):.2f}")
    print(f"  Median: {np.median(mid):.2f}")
    print(f"  Min:    {np.min(mid):.2f}")
    print(f"  Max:    {np.max(mid):.2f}")
    print(f"  Range:  {np.max(mid) - np.min(mid):.2f}")
    print(f"  Std:    {np.std(mid):.2f}")

    # FV analysis: distance from 10000
    dist_from_10k = mid - 10000
    print(f"\n  --- Distance from FV=10000 ---")
    print(f"  Mean deviation:   {np.mean(dist_from_10k):+.2f}")
    print(f"  Median deviation: {np.median(dist_from_10k):+.2f}")
    print(f"  Max above 10000:  {np.max(dist_from_10k):+.2f}")
    print(f"  Max below 10000:  {np.min(dist_from_10k):+.2f}")

    # Best bid / best ask raw stats
    print(f"\n  --- Best Bid ---")
    print(f"  Mean: {np.mean(best_bid):.2f}  Median: {np.median(best_bid):.1f}  "
          f"Min: {np.min(best_bid):.0f}  Max: {np.max(best_bid):.0f}")
    print(f"  --- Best Ask ---")
    print(f"  Mean: {np.mean(best_ask):.2f}  Median: {np.median(best_ask):.1f}  "
          f"Min: {np.min(best_ask):.0f}  Max: {np.max(best_ask):.0f}")

    # Spread distribution
    print(f"\n  --- Spread (best_ask - best_bid) ---")
    print(f"  N (two-sided): {n_ts}")
    print(f"  Mean:   {np.mean(spread):.2f}")
    print(f"  Median: {np.median(spread):.1f}")
    print(f"  Std:    {np.std(spread):.2f}")
    print(f"  Min:    {np.min(spread):.0f}")
    print(f"  Max:    {np.max(spread):.0f}")
    pcts = [10, 25, 50, 75, 90, 95, 99]
    pvals = np.percentile(spread, pcts)
    print(f"  Percentiles: " + "  ".join(f"p{p}={v:.0f}" for p, v in zip(pcts, pvals)))

    # Modal spreads
    spread_int = spread.astype(int)
    spread_counts = Counter(spread_int)
    print(f"\n  --- Spread Value Distribution (top 10) ---")
    for val, cnt in spread_counts.most_common(10):
        print(f"    Spread={val:>3d}: {cnt:>5d} ticks ({100*cnt/n_ts:.1f}%)")

    # Bid-to-mid distribution
    print(f"\n  --- Bid-to-Mid (mid - best_bid) ---")
    print(f"  Mean:   {np.mean(bid_to_mid):.2f}")
    print(f"  Median: {np.median(bid_to_mid):.1f}")
    print(f"  Std:    {np.std(bid_to_mid):.2f}")
    print(f"  Min:    {np.min(bid_to_mid):.1f}")
    print(f"  Max:    {np.max(bid_to_mid):.1f}")
    pvals_b = np.percentile(bid_to_mid, pcts)
    print(f"  Percentiles: " + "  ".join(f"p{p}={v:.1f}" for p, v in zip(pcts, pvals_b)))

    # Ask-to-mid distribution
    print(f"\n  --- Ask-to-Mid (best_ask - mid) ---")
    print(f"  Mean:   {np.mean(ask_to_mid):.2f}")
    print(f"  Median: {np.median(ask_to_mid):.1f}")
    print(f"  Std:    {np.std(ask_to_mid):.2f}")
    print(f"  Min:    {np.min(ask_to_mid):.1f}")
    print(f"  Max:    {np.max(ask_to_mid):.1f}")
    pvals_a = np.percentile(ask_to_mid, pcts)
    print(f"  Percentiles: " + "  ".join(f"p{p}={v:.1f}" for p, v in zip(pcts, pvals_a)))

    # Asymmetry analysis
    asym = np.abs(bid_to_mid - ask_to_mid)
    n_asym = np.sum(asym > 0.01)  # float tolerance
    print(f"\n  --- Asymmetry (bid_to_mid != ask_to_mid) ---")
    print(f"  Asymmetric ticks: {n_asym} / {n_ts} ({100*n_asym/n_ts:.1f}%)")
    print(f"  Mean |bid_half - ask_half|: {np.mean(asym):.2f}")
    print(f"  Median: {np.median(asym):.1f}")
    print(f"  Mean (bid_to_mid - ask_to_mid): {np.mean(bid_to_mid - ask_to_mid):+.3f}  "
          f"(positive = bid further from mid = ask-heavy)")

    # Bid-to-mid vs ask-to-mid value distributions
    btm_counts = Counter(bid_to_mid.round(1))
    atm_counts = Counter(ask_to_mid.round(1))
    print(f"\n  --- Bid-to-Mid Value Distribution (top 8) ---")
    for val, cnt in btm_counts.most_common(8):
        print(f"    bid_to_mid={val:>5.1f}: {cnt:>5d} ({100*cnt/n_ts:.1f}%)")
    print(f"  --- Ask-to-Mid Value Distribution (top 8) ---")
    for val, cnt in atm_counts.most_common(8):
        print(f"    ask_to_mid={val:>5.1f}: {cnt:>5d} ({100*cnt/n_ts:.1f}%)")

    # Spread regime detection: segment into buckets
    tight = spread <= 10
    medium = (spread > 10) & (spread <= 16)
    wide = (spread > 16) & (spread <= 22)
    very_wide = spread > 22
    print(f"\n  --- Spread Regimes ---")
    print(f"  Tight  (<=10): {tight.sum():>5d} ({100*tight.sum()/n_ts:.1f}%)")
    print(f"  Medium (11-16): {medium.sum():>5d} ({100*medium.sum()/n_ts:.1f}%)")
    print(f"  Wide   (17-22): {wide.sum():>5d} ({100*wide.sum()/n_ts:.1f}%)")
    print(f"  V.Wide (>22):   {very_wide.sum():>5d} ({100*very_wide.sum()/n_ts:.1f}%)")

    # Time evolution of spread (first quarter vs last quarter)
    timestamps = ts["timestamp"].values
    q1_mask = timestamps < np.percentile(timestamps, 25)
    q4_mask = timestamps >= np.percentile(timestamps, 75)
    print(f"\n  --- Spread Evolution (Q1 vs Q4 of day) ---")
    print(f"  Q1 mean spread: {np.mean(spread[q1_mask]):.1f}  "
          f"median: {np.median(spread[q1_mask]):.0f}")
    print(f"  Q4 mean spread: {np.mean(spread[q4_mask]):.1f}  "
          f"median: {np.median(spread[q4_mask]):.0f}")

    # Time evolution of mid (first quarter vs last quarter)
    print(f"\n  --- Mid Evolution (Q1 vs Q4 of day) ---")
    print(f"  Q1 mean mid: {np.mean(mid[q1_mask]):.2f}")
    print(f"  Q4 mean mid: {np.mean(mid[q4_mask]):.2f}")
    print(f"  Drift:       {np.mean(mid[q4_mask]) - np.mean(mid[q1_mask]):+.2f}")

    # Autocorrelation of mid (lag 1)
    mid_diff = np.diff(mid)
    if len(mid_diff) > 10:
        ac1 = np.corrcoef(mid_diff[:-1], mid_diff[1:])[0, 1]
        print(f"\n  --- Mid Return AC(1) ---")
        print(f"  AC(1) of mid changes: {ac1:.4f}")

    # L1 volume analysis (two-sided only)
    bid_vol = ts["bid_volume_1"].values
    ask_vol = ts["ask_volume_1"].values
    print(f"\n  --- L1 Volume ---")
    print(f"  Bid vol: mean={np.mean(bid_vol):.1f} median={np.median(bid_vol):.0f} "
          f"min={np.min(bid_vol):.0f} max={np.max(bid_vol):.0f}")
    print(f"  Ask vol: mean={np.mean(ask_vol):.1f} median={np.median(ask_vol):.0f} "
          f"min={np.min(ask_vol):.0f} max={np.max(ask_vol):.0f}")

    return {
        "n_total": n_total,
        "n_two_sided": n_ts,
        "one_sided_pct": 100 * (1 - n_ts / n_total),
        "mid_mean": np.mean(mid),
        "mid_range": np.max(mid) - np.min(mid),
        "spread_mean": np.mean(spread),
        "spread_median": np.median(spread),
        "asym_pct": 100 * n_asym / n_ts,
        "ac1": ac1 if len(mid_diff) > 10 else np.nan,
    }


def analyze_trades(day):
    df = load_trades(day)
    n = len(df)
    print(f"\n  --- Day {day}: ACO TRADE ANALYSIS ---")
    print(f"  Total trades: {n}")

    if n == 0:
        return {}

    prices = df["price"].values
    qtys = df["quantity"].values
    timestamps = df["timestamp"].values

    print(f"  Price: mean={np.mean(prices):.2f}  median={np.median(prices):.1f}  "
          f"min={np.min(prices):.0f}  max={np.max(prices):.0f}")
    print(f"  Qty:   mean={np.mean(qtys):.2f}  median={np.median(qtys):.1f}  "
          f"min={np.min(qtys):.0f}  max={np.max(qtys):.0f}")
    print(f"  Total volume: {np.sum(qtys)}")

    # Trade frequency
    day_duration_s = (timestamps[-1] - timestamps[0]) / 100  # timestamps in 100ms units
    if day_duration_s > 0:
        trades_per_1k_ticks = n / (day_duration_s / 10)  # ~10 ticks per second
        print(f"  Day span: {timestamps[0]} to {timestamps[-1]} "
              f"(~{(timestamps[-1]-timestamps[0])/100:.0f}s)")
    else:
        trades_per_1k_ticks = 0

    # Inter-trade time
    if n > 1:
        inter = np.diff(timestamps)
        print(f"  Inter-trade time: mean={np.mean(inter):.0f}  "
              f"median={np.median(inter):.0f}  "
              f"min={np.min(inter):.0f}  max={np.max(inter):.0f} (x100ms)")

    # Buy vs sell inference: compare trade price to concurrent mid
    # Load price data to get mid at each trade timestamp
    pdf = load_prices(day)
    # Merge: for each trade, find the price tick at same or most recent timestamp
    pdf_both = pdf[pdf["bid_price_1"].notna() & pdf["ask_price_1"].notna()].copy()
    if len(pdf_both) > 0:
        pdf_both["mid"] = (pdf_both["bid_price_1"] + pdf_both["ask_price_1"]) / 2.0
        # For each trade, get nearest prior mid
        buy_count = 0
        sell_count = 0
        at_mid_count = 0
        mids_ts = pdf_both["timestamp"].values
        mids_val = pdf_both["mid"].values

        for i in range(n):
            t = timestamps[i]
            p = prices[i]
            # Find latest mid before or at this timestamp
            idx = np.searchsorted(mids_ts, t, side="right") - 1
            if idx >= 0:
                m = mids_val[idx]
                if p > m:
                    buy_count += 1
                elif p < m:
                    sell_count += 1
                else:
                    at_mid_count += 1

        print(f"\n  --- Buy/Sell Classification (vs prior mid) ---")
        print(f"  Buys (price > mid):  {buy_count} ({100*buy_count/n:.1f}%)")
        print(f"  Sells (price < mid): {sell_count} ({100*sell_count/n:.1f}%)")
        print(f"  At mid:              {at_mid_count} ({100*at_mid_count/n:.1f}%)")

    # Qty distribution
    qty_counts = Counter(qtys)
    print(f"\n  --- Qty Distribution (top 10) ---")
    for val, cnt in qty_counts.most_common(10):
        print(f"    qty={val:>3.0f}: {cnt:>4d} ({100*cnt/n:.1f}%)")

    return {
        "n_trades": n,
        "avg_qty": np.mean(qtys),
        "total_vol": np.sum(qtys),
        "avg_price": np.mean(prices),
    }


def cross_day_summary(price_stats, trade_stats):
    print(f"\n\n{'#' * 80}")
    print(f"  CROSS-DAY SUMMARY")
    print(f"{'#' * 80}")

    print(f"\n  {'Day':>4s}  {'Ticks':>6s}  {'2-Sided':>7s}  {'1-Sided%':>8s}  "
          f"{'MidMean':>10s}  {'MidRange':>8s}  {'SprMean':>7s}  {'SprMed':>6s}  "
          f"{'Asym%':>6s}  {'AC(1)':>7s}")
    print(f"  {'-'*4}  {'-'*6}  {'-'*7}  {'-'*8}  {'-'*10}  {'-'*8}  {'-'*7}  "
          f"{'-'*6}  {'-'*6}  {'-'*7}")
    for day in DAYS:
        s = price_stats[day]
        print(f"  {day:>4d}  {s['n_total']:>6d}  {s['n_two_sided']:>7d}  "
              f"{s['one_sided_pct']:>7.1f}%  {s['mid_mean']:>10.2f}  "
              f"{s['mid_range']:>8.1f}  {s['spread_mean']:>7.1f}  "
              f"{s['spread_median']:>6.0f}  {s['asym_pct']:>5.1f}%  "
              f"{s['ac1']:>7.4f}")

    print(f"\n  {'Day':>4s}  {'Trades':>6s}  {'AvgQty':>7s}  {'TotVol':>7s}  {'AvgPrice':>10s}")
    print(f"  {'-'*4}  {'-'*6}  {'-'*7}  {'-'*7}  {'-'*10}")
    for day in DAYS:
        t = trade_stats[day]
        if t:
            print(f"  {day:>4d}  {t['n_trades']:>6d}  {t['avg_qty']:>7.1f}  "
                  f"{t['total_vol']:>7.0f}  {t['avg_price']:>10.2f}")

    # FV hypothesis test
    print(f"\n  --- FV Hypothesis: Is ACO still mean-reverting to 10000? ---")
    all_deviations = []
    for day in DAYS:
        s = price_stats[day]
        dev = s['mid_mean'] - 10000
        all_deviations.append(dev)
        print(f"    Day {day}: mean mid = {s['mid_mean']:.2f}  deviation from 10000 = {dev:+.2f}")
    avg_dev = np.mean(all_deviations)
    print(f"    Average deviation across days: {avg_dev:+.2f}")
    if abs(avg_dev) < 5:
        print(f"    CONCLUSION: FV=10000 hypothesis SUPPORTED (avg deviation < 5)")
    else:
        print(f"    CONCLUSION: FV may have shifted. Average deviation = {avg_dev:+.2f}")

    # Comparison with R1
    print(f"\n  --- Comparison with R1 (from CLAUDE.md) ---")
    print(f"  R1 spread: ~16 (62% of ticks), range 27-36/day, AC(1) ~ -0.49")
    print(f"  R2 spread: mean={np.mean([price_stats[d]['spread_mean'] for d in DAYS]):.1f}  "
          f"median={np.mean([price_stats[d]['spread_median'] for d in DAYS]):.0f}")
    print(f"  R2 AC(1):  avg={np.mean([price_stats[d]['ac1'] for d in DAYS]):.4f}")
    print(f"  R2 range:  avg={np.mean([price_stats[d]['mid_range'] for d in DAYS]):.1f}")


if __name__ == "__main__":
    print(SEP)
    print("  ACO ROUND 2 MICROSTRUCTURE ANALYSIS")
    print(SEP)

    price_stats = {}
    trade_stats = {}

    for day in DAYS:
        price_stats[day] = analyze_prices(day)

    print(f"\n\n{'#' * 80}")
    print(f"  TRADE ANALYSIS")
    print(f"{'#' * 80}")

    for day in DAYS:
        trade_stats[day] = analyze_trades(day)

    cross_day_summary(price_stats, trade_stats)

    print(f"\n{SEP}")
    print(f"  END OF ANALYSIS")
    print(f"{SEP}")
