"""hp_deadzone_analysis.py - Analyze v22 HP passive MM dead-zone PnL.

Replays the order book data to classify each tick into the v22 HP regime
(S17, S7-cover, FLIP-hold, passive MM) and analyze whether the passive MM
fallback between alpha cycles makes or loses money.

Usage:
  PYTHONPATH=prosperity4bt python trader-logic/round-3/notes/hp_deadzone_analysis.py
"""

import csv
import json
import os
import sys
import re
from collections import defaultdict

# We'll parse the HP mid trajectory from CSV directly to avoid running the BT.
# Instead, reconstruct what v22 would do tick by tick by replaying the book data.

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CSV_PRICES = os.path.join(BASE, "prosperity4bt", "resources", "round3", "prices_round_3_day_2.csv")
CSV_TRADES = os.path.join(BASE, "prosperity4bt", "resources", "round3", "trades_round_3_day_2.csv")


def load_hp_books(csv_path):
    """Parse prices CSV (L3 format), return dict ts -> {bids: {px: qty}, asks: {px: -qty}}."""
    ticks = {}  # ts -> {"bids": {px: qty}, "asks": {px: -qty}}
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["product"] != "HYDROGEL_PACK":
                continue
            ts = int(row["timestamp"])
            bids = {}
            asks = {}
            for i in range(1, 4):
                bp = row.get(f"bid_price_{i}", "")
                bv = row.get(f"bid_volume_{i}", "")
                if bp and bv:
                    bids[int(bp)] = int(bv)
                ap = row.get(f"ask_price_{i}", "")
                av = row.get(f"ask_volume_{i}", "")
                if ap and av:
                    asks[int(ap)] = -int(av)  # negative for asks
            ticks[ts] = {"bids": bids, "asks": asks}
    return ticks


def load_hp_market_trades(csv_path):
    """Parse trades CSV for HP market trades."""
    trades = defaultdict(list)  # ts -> [(price, qty, buyer, seller)]
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["symbol"] != "HYDROGEL_PACK":
                continue
            ts = int(row["timestamp"])
            px = int(float(row["price"]))
            qty = int(row["quantity"])
            buyer = row.get("buyer", "")
            seller = row.get("seller", "")
            trades[ts].append((px, qty, buyer, seller))
    return trades


def compute_features(bids, asks):
    if not bids or not asks:
        return None
    best_bid = max(bids.keys())
    best_ask = min(asks.keys())
    spread = best_ask - best_bid
    if spread <= 0:
        return None
    mid = (best_bid + best_ask) / 2.0
    # L3 WAP edge
    sorted_bids = sorted(bids.keys(), reverse=True)[:3]
    sorted_asks = sorted(asks.keys())[:3]
    bid_num = sum(p * bids[p] for p in sorted_bids)
    bid_den = sum(bids[p] for p in sorted_bids)
    ask_num = sum(p * abs(asks[p]) for p in sorted_asks)
    ask_den = sum(abs(asks[p]) for p in sorted_asks)
    bid_wap = bid_num / bid_den if bid_den > 0 else best_bid
    ask_wap = ask_num / ask_den if ask_den > 0 else best_ask
    wap_edge = ((bid_wap + ask_wap) / 2.0) - mid
    return {
        "best_bid": best_bid, "best_ask": best_ask,
        "spread": spread, "mid": mid, "wap_edge": wap_edge,
    }


def simulate_v22_hp(hp_books, hp_trades):
    """Replay v22 HP logic tick by tick. Track regime and passive MM activity."""

    # v22 params
    REGIME2_SPREAD = 17
    ENTRY_MID_MIN = 10010
    S7_WINDOW = 500
    S7_BOTTOM_Q = 0.08
    FLIP_TARGET = 200
    FLIP_EXIT_MID = 10020
    FLIP_TIMEOUT_TICKS = 1500
    POS_LIMIT = 200
    QUOTE_SIZE = 25
    EDGE_BETA_WINDOW = 500
    EDGE_BETA_MIN_SAMPLES = 50
    EDGE_BETA_SHRINK = 0.5
    LAYER_A_SCALE = 3.0
    LAYER_A_CLIP = 1.0

    # State
    mid_buf_500 = []
    row = 0
    s17_entry_row = None
    s17_entry_mid = None
    s7_covering = False
    flip_holding = False
    flip_entry_row = None
    prev_mid = None
    prev_wap_edge = None
    edge_buf = []
    ret_buf = []

    position = 0  # We don't actually track fills, just regime classification

    timestamps = sorted(hp_books.keys())

    results = []

    for ts in timestamps:
        book = hp_books[ts]
        feat = compute_features(book["bids"], book["asks"])
        if feat is None:
            results.append({
                "ts": ts, "regime": "NO_BOOK", "mid": None, "spread": None,
                "position": position, "orders": [], "passive_mm": False,
            })
            row += 1
            continue

        mid = feat["mid"]
        spread = feat["spread"]
        best_bid = feat["best_bid"]
        best_ask = feat["best_ask"]
        wap_edge = feat["wap_edge"]

        # Update buffers
        mid_buf_500.append(mid)
        if len(mid_buf_500) > 500:
            mid_buf_500 = mid_buf_500[-500:]
        row += 1

        # Online edge -> return
        if prev_mid is not None and prev_wap_edge is not None:
            ret_1t = mid - prev_mid
            edge_buf.append(prev_wap_edge)
            ret_buf.append(ret_1t)
            if len(edge_buf) > EDGE_BETA_WINDOW:
                edge_buf = edge_buf[-EDGE_BETA_WINDOW:]
                ret_buf = ret_buf[-EDGE_BETA_WINDOW:]
        prev_mid = mid
        prev_wap_edge = wap_edge

        regime = "PASSIVE_MM"  # default
        passive_mm = True
        orders = []

        # S17 short build phase
        if s17_entry_row is not None and position < 0:
            regime = "S17_BUILD"
            passive_mm = False
            window_ready = len(mid_buf_500) >= S7_WINDOW
            if window_ready:
                sorted_window = sorted(mid_buf_500[-S7_WINDOW:])
                bottom_thresh = sorted_window[int(len(sorted_window) * S7_BOTTOM_Q)]
                s7_bottom = (spread == 7 and mid <= bottom_thresh)
            else:
                s7_bottom = False
            if s7_bottom:
                s7_covering = True
                s17_entry_row = None
                s17_entry_mid = None
                regime = "S7_COVER_START"

        # Cover+flip phase
        elif s7_covering:
            regime = "S7_FLIP"
            passive_mm = False
            if position >= FLIP_TARGET:
                s7_covering = False
                flip_holding = True
                flip_entry_row = row
                regime = "FLIP_HOLD_START"

        # HOLD-FLIP phase
        elif flip_holding:
            held_for = row - (flip_entry_row or row)
            regime = "FLIP_HOLD"
            passive_mm = False
            if mid >= FLIP_EXIT_MID or held_for >= FLIP_TIMEOUT_TICKS:
                flip_holding = False
                flip_entry_row = None
                regime = "FLIP_EXIT"

        # S17 entry check
        elif (spread == REGIME2_SPREAD and mid > ENTRY_MID_MIN and s17_entry_row is None):
            regime = "S17_ENTRY"
            passive_mm = False
            s17_entry_row = row
            s17_entry_mid = mid
            position = -POS_LIMIT  # Approximate: we go max short

        else:
            # Passive MM fallback
            regime = "PASSIVE_MM"
            passive_mm = True

        results.append({
            "ts": ts, "regime": regime, "mid": mid, "spread": spread,
            "best_bid": best_bid, "best_ask": best_ask,
            "position": position, "passive_mm": passive_mm,
            "wap_edge": wap_edge,
        })

    return results


def analyze_passive_mm_zones(results):
    """Analyze the passive MM zones: how long they last, mid movement during them."""

    # Filter to ticks >= 100000 (tick 1000+, post-DP window)
    post_dp = [r for r in results if r["ts"] >= 100000]

    print(f"\n{'='*80}")
    print(f"HYDROGEL_PACK v22 Regime Analysis — Day 2, ticks 1000+ (ts >= 100000)")
    print(f"{'='*80}")

    # Count regime ticks
    regime_counts = defaultdict(int)
    for r in post_dp:
        regime_counts[r["regime"]] += 1

    total = len(post_dp)
    print(f"\nTotal ticks in post-DP window: {total}")
    print(f"\nRegime distribution:")
    for regime, count in sorted(regime_counts.items(), key=lambda x: -x[1]):
        pct = 100.0 * count / total if total > 0 else 0
        print(f"  {regime:20s}: {count:5d} ticks ({pct:5.1f}%)")

    # Find contiguous PASSIVE_MM zones
    zones = []
    current_zone = None
    for r in post_dp:
        if r["regime"] == "PASSIVE_MM":
            if current_zone is None:
                current_zone = {"start_ts": r["ts"], "ticks": [], "mids": []}
            current_zone["ticks"].append(r["ts"])
            if r["mid"] is not None:
                current_zone["mids"].append(r["mid"])
        else:
            if current_zone is not None:
                current_zone["end_ts"] = r["ts"]
                zones.append(current_zone)
                current_zone = None
    if current_zone is not None:
        current_zone["end_ts"] = post_dp[-1]["ts"]
        zones.append(current_zone)

    print(f"\nContiguous PASSIVE_MM zones: {len(zones)}")
    print(f"\nZone details:")
    print(f"  {'Zone':>4} | {'Start TS':>10} | {'End TS':>10} | {'Duration':>8} | {'Ticks':>5} | {'Mid Start':>9} | {'Mid End':>9} | {'Mid Range':>9} | {'Mid StdDev':>10}")
    print(f"  {'-'*4}-+-{'-'*10}-+-{'-'*10}-+-{'-'*8}-+-{'-'*5}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*10}")

    total_mm_ticks = 0
    total_mid_drift = 0
    for i, z in enumerate(zones):
        n = len(z["ticks"])
        total_mm_ticks += n
        if z["mids"]:
            mid_start = z["mids"][0]
            mid_end = z["mids"][-1]
            mid_range = max(z["mids"]) - min(z["mids"])
            mid_std = (sum((m - sum(z["mids"])/len(z["mids"]))**2 for m in z["mids"]) / max(1, len(z["mids"])-1)) ** 0.5
            drift = mid_end - mid_start
            total_mid_drift += abs(drift)
        else:
            mid_start = mid_end = mid_range = mid_std = drift = 0

        duration = z["ticks"][-1] - z["ticks"][0] if n > 1 else 0

        if n >= 20:  # Only show zones >= 20 ticks
            print(f"  {i+1:4d} | {z['start_ts']:10d} | {z.get('end_ts', '?'):>10} | {duration:8d} | {n:5d} | {mid_start:9.1f} | {mid_end:9.1f} | {mid_range:9.1f} | {mid_std:10.2f}")

    # Spread distribution in passive MM zones
    spreads_in_mm = defaultdict(int)
    for r in post_dp:
        if r["regime"] == "PASSIVE_MM" and r["spread"] is not None:
            spreads_in_mm[int(r["spread"])] += 1

    print(f"\nSpread distribution during PASSIVE_MM:")
    for sp, count in sorted(spreads_in_mm.items()):
        pct = 100.0 * count / total_mm_ticks if total_mm_ticks > 0 else 0
        print(f"  spread={sp:2d}: {count:5d} ticks ({pct:5.1f}%)")

    # Key question: does passive MM make or lose money?
    # Passive MM posts bid at ~(mid-1) and ask at ~(mid+1) with QUOTE_SIZE=25.
    # If spread is wide (>= 8), posting inside spread captures spread.
    # If spread is tight (7), posting penny-better may get adverse-selected.
    #
    # We can estimate: for each passive MM tick, the THEORETICAL spread captured
    # is (best_ask - best_bid - 2) / 2 per fill. But adverse selection from mid
    # movement is the risk.

    # Estimate: 1-tick mid autocorrelation during passive MM
    mm_mids = []
    for r in post_dp:
        if r["regime"] == "PASSIVE_MM" and r["mid"] is not None:
            mm_mids.append(r["mid"])

    if len(mm_mids) > 2:
        returns = [mm_mids[i+1] - mm_mids[i] for i in range(len(mm_mids)-1)]
        mean_ret = sum(returns) / len(returns)
        var_ret = sum((r - mean_ret)**2 for r in returns) / (len(returns) - 1)
        cov_lag1 = sum((returns[i] - mean_ret) * (returns[i+1] - mean_ret)
                       for i in range(len(returns)-1)) / (len(returns) - 2)
        ac1 = cov_lag1 / var_ret if var_ret > 0 else 0

        print(f"\nMid dynamics during PASSIVE_MM:")
        print(f"  Total passive MM ticks: {len(mm_mids)}")
        print(f"  Mean 1-tick return: {mean_ret:.4f}")
        print(f"  Std of 1-tick return: {var_ret**0.5:.4f}")
        print(f"  AC(1) of returns: {ac1:.4f}")
        print(f"  Cumulative drift: {mm_mids[-1] - mm_mids[0]:.1f}")

    # Per-zone PnL estimation for passive MM
    # The passive MM posts: bid at min(fv-1, best_bid+1), ask at max(fv+1, best_ask-1)
    # where fv = round(mid). It posts QUOTE_SIZE=25 on each side.
    #
    # In the backtester, fills come from:
    #   1. Aggressive crossing (our order crosses the book) - won't happen since we post inside
    #   2. Taker hitting our passive quotes
    #
    # Without running the actual BT, we can estimate: if the taker arrival rate is ~30%
    # and our passive quotes are at the effective best, we get ~30% fill rate.
    # Each fill captures half-spread. But adverse selection = |return next tick| * position.
    #
    # Simpler: let's just identify the SPREAD states during passive MM.
    # If spread >= 9 (wide), passive MM is likely profitable (capture >= 3 per fill).
    # If spread == 7-8, it's marginal (capture 1-2 per fill, adverse selection dominates).

    wide_ticks = sum(1 for r in post_dp if r["regime"] == "PASSIVE_MM" and r["spread"] is not None and r["spread"] >= 9)
    tight_ticks = sum(1 for r in post_dp if r["regime"] == "PASSIVE_MM" and r["spread"] is not None and r["spread"] <= 8)

    print(f"\nPassive MM spread quality:")
    print(f"  Wide spread (>= 9, likely profitable): {wide_ticks} ticks ({100*wide_ticks/max(1,total_mm_ticks):.1f}%)")
    print(f"  Tight spread (<= 8, risky): {tight_ticks} ticks ({100*tight_ticks/max(1,total_mm_ticks):.1f}%)")

    # Also analyze: what happens to mid DURING passive MM zones?
    # If mid is trending (drift), passive MM gets run over.
    # Key metric: average absolute 50-tick drift during passive MM.
    if len(mm_mids) > 50:
        drifts_50 = [abs(mm_mids[i+50] - mm_mids[i]) for i in range(len(mm_mids)-50)]
        avg_50_drift = sum(drifts_50) / len(drifts_50)
        print(f"\n  Average |50-tick drift| during passive MM: {avg_50_drift:.2f}")
        print(f"  (Compare: half-spread capture per fill ~ {sum(r['spread'] for r in post_dp if r['regime']=='PASSIVE_MM' and r['spread']) / max(1, total_mm_ticks) / 2:.1f})")

    return zones


def main():
    print("Loading HP order book data from day 2 CSV...")
    hp_books = load_hp_books(CSV_PRICES)
    hp_trades = load_hp_market_trades(CSV_TRADES)
    print(f"Loaded {len(hp_books)} ticks with HP book data")
    print(f"Loaded trades for {len(hp_trades)} timestamps")

    print("\nSimulating v22 HP logic...")
    results = simulate_v22_hp(hp_books, hp_trades)

    # Full day summary
    print(f"\n{'='*80}")
    print(f"FULL DAY regime summary (all 10k ticks):")
    regime_counts = defaultdict(int)
    for r in results:
        regime_counts[r["regime"]] += 1
    for regime, count in sorted(regime_counts.items(), key=lambda x: -x[1]):
        print(f"  {regime:20s}: {count:5d}")

    zones = analyze_passive_mm_zones(results)

    # Save raw data for further analysis
    outpath = os.path.join(BASE, "trader-logic", "round-3", "notes", "hp_deadzone_data.json")
    with open(outpath, "w") as f:
        json.dump(results, f)
    print(f"\nRaw data saved to {outpath}")


if __name__ == "__main__":
    main()
