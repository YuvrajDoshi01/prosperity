"""Realistic passive MM simulator: place inside-spread quotes, get hit by takers from CSV.

Reuses R3 engine logic: passive orders join the book, external takers hit by price priority.
For each tick, we know:
  - Best bid/ask
  - Existing book volume at L1, L2, L3
  - Aggregate taker volume that arrived (from trades CSV at this timestamp)
  - Whether takers were buying (price >= ask) or selling (price <= bid)

Our strategy:
  - Post 1 lot at bp1+1 (penny-bid), 1 lot at ap1-1 (penny-ask) — inside spread
  - We get filled if a taker arrives on our side (assume queue priority — most aggressive level fills first)
  - With cap at total LIMIT=200 by side
"""
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load(day):
    p = pd.read_csv(f"{ROOT}/prices_round_3_day_{day}.csv", sep=";")
    t = pd.read_csv(f"{ROOT}/trades_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    t = t[t["symbol"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    return p, t

def gen_signals(p):
    bp1 = p["bid_price_1"].values; bv1 = p["bid_volume_1"].fillna(0).values
    bp2 = p["bid_price_2"].fillna(0).values; bv2 = p["bid_volume_2"].fillna(0).values
    bp3 = p["bid_price_3"].fillna(0).values; bv3 = p["bid_volume_3"].fillna(0).values
    ap1 = p["ask_price_1"].values; av1 = p["ask_volume_1"].fillna(0).values
    ap2 = p["ask_price_2"].fillna(0).values; av2 = p["ask_volume_2"].fillna(0).values
    ap3 = p["ask_price_3"].fillna(0).values; av3 = p["ask_volume_3"].fillna(0).values
    mid = p["mid_price"].values
    obi_l1 = (bv1 - av1) / np.maximum(bv1 + av1, 1)
    obi_deep = (bv2+bv3 - av2-av3) / np.maximum(bv2+bv3+av2+av3, 1)
    bv_arr = np.column_stack([bv1, bv2, bv3])
    bp_arr = np.column_stack([bp1, bp2, bp3])
    av_arr = np.column_stack([av1, av2, av3])
    ap_arr = np.column_stack([ap1, ap2, ap3])
    wall_b = bp_arr[np.arange(len(bv1)), np.argmax(bv_arr, axis=1)]
    wall_a = ap_arr[np.arange(len(av1)), np.argmax(av_arr, axis=1)]
    return {
        "OBI_L1": obi_l1,
        "L1-deep": obi_l1 - obi_deep,
        "wall_mid": (wall_b + wall_a) / 2,
        "ap1": ap1, "bp1": bp1, "mid": mid, "spread": ap1 - bp1,
    }

def simulate_mm(day, signal_fn, ticks=1000, edge=1, skew_thresh=0.5, fill_size_per_tick=20):
    """signal_fn(state, i) -> (post_bid: bool, post_ask: bool)

    For each tick:
      1. We post bid at bp1+edge, ask at ap1-edge (penny inside).
      2. Taker arrives (from trades CSV). If taker buys at ask, our ask gets hit (we own the inside).
         If taker sells at bid, our bid gets hit.
      3. Fill quantity = min(taker_qty_at_our_level, our_post_size).
    """
    p, t = load(day)
    sigs = gen_signals(p)
    bp1 = sigs["bp1"]; ap1 = sigs["ap1"]; mid = sigs["mid"]; spread = sigs["spread"]

    # Bin trades by tick
    buy_at_ask = np.zeros(len(mid))   # taker bought at ask price (consumed liquidity)
    sell_at_bid = np.zeros(len(mid))
    taker_buy_pric = [[] for _ in range(len(mid))]
    taker_sell_pric = [[] for _ in range(len(mid))]
    for _, row in t.iterrows():
        ti = int(row["timestamp"] // 100)
        if ti >= len(mid): continue
        if row["price"] >= ap1[ti]:
            buy_at_ask[ti] += row["quantity"]
        elif row["price"] <= bp1[ti]:
            sell_at_bid[ti] += row["quantity"]
        # else inside spread = ambiguous, ignore

    pos, cash = 0, 0.0
    LIMIT = 200
    fills_b = fills_s = 0
    for i in range(min(ticks, len(mid)-1)):
        if spread[i] < 2:
            continue  # can't post inside if spread=1
        post_bid, post_ask = signal_fn(sigs, i)
        my_bid_px = bp1[i] + edge
        my_ask_px = ap1[i] - edge
        # Fill rate: if taker buys at ask, they hit our ask first (we are inside)
        if post_ask and pos > -LIMIT:
            qty = min(int(buy_at_ask[i]), fill_size_per_tick, LIMIT + pos)
            if qty > 0:
                cash += qty * my_ask_px; pos -= qty; fills_s += qty
        if post_bid and pos < LIMIT:
            qty = min(int(sell_at_bid[i]), fill_size_per_tick, LIMIT - pos)
            if qty > 0:
                cash -= qty * my_bid_px; pos += qty; fills_b += qty
    n = min(ticks, len(mid)-1)
    pnl = cash + pos * mid[n]
    return pnl, pos, fills_b, fills_s

# Baseline: post both sides always
def both_sides(sigs, i): return True, True

# Skewed: pull bid when L1-deep < -thresh; pull ask when L1-deep > +thresh
def make_skew_fn(sig_name, thresh):
    def f(sigs, i):
        s = sigs[sig_name][i]
        post_bid = s > -thresh
        post_ask = s < thresh
        return post_bid, post_ask
    return f

# Pyramid skew: post 2 lots on signal side, 1 on other (asymmetric)
print("=== BASELINE: Penny-MM both sides, no skew ===")
for day in [0, 1, 2]:
    pnl, pos, fb, fs = simulate_mm(day, both_sides)
    print(f"Day {day}: pnl={pnl:>+8.1f} pos={pos:>+5} fills_buy={fb} fills_sell={fs}")

print("\n=== Signal-skewed MM (pull opposite side when signal strong) ===")
for sname in ["OBI_L1", "L1-deep"]:
    for thresh in [0.1, 0.3, 0.5]:
        results = []
        for day in [0, 1, 2]:
            pnl, _, _, _ = simulate_mm(day, make_skew_fn(sname, thresh))
            results.append(pnl)
        print(f"  {sname} thresh={thresh}: d0={results[0]:>+7.1f} d1={results[1]:>+7.1f} d2={results[2]:>+7.1f} sum={sum(results):>+8.1f}")

# Wall-mid based: post inside spread always, but reference price = wall_mid not mid
print("\n=== Wall-mid reference (post bid at min(wall_mid-1, ap1-1, bp1+1), ask similarly) ===")
def simulate_wall(day, ticks=1000, edge=1, fill_size=20):
    p, t = load(day)
    sigs = gen_signals(p)
    bp1 = sigs["bp1"]; ap1 = sigs["ap1"]; mid = sigs["mid"]; spread = sigs["spread"]; wall = sigs["wall_mid"]
    buy_at_ask = np.zeros(len(mid)); sell_at_bid = np.zeros(len(mid))
    for _, row in t.iterrows():
        ti = int(row["timestamp"] // 100)
        if ti >= len(mid): continue
        if row["price"] >= ap1[ti]: buy_at_ask[ti] += row["quantity"]
        elif row["price"] <= bp1[ti]: sell_at_bid[ti] += row["quantity"]
    pos, cash = 0, 0.0; LIMIT = 200
    for i in range(min(ticks, len(mid)-1)):
        if spread[i] < 2: continue
        # Asymmetric quotes around wall_mid; floor/ceil to ints
        target_bid = int(np.floor(wall[i] - 1))
        target_ask = int(np.ceil(wall[i] + 1))
        my_bid_px = max(bp1[i]+1, min(ap1[i]-1, target_bid))
        my_ask_px = min(ap1[i]-1, max(bp1[i]+1, target_ask))
        # Skip if quote sides crossed
        if my_bid_px >= my_ask_px:
            continue
        # Fills: conditional on quoted at inside
        if pos > -LIMIT:
            q = min(int(buy_at_ask[i]), fill_size, LIMIT + pos)
            if q > 0:
                cash += q * my_ask_px; pos -= q
        if pos < LIMIT:
            q = min(int(sell_at_bid[i]), fill_size, LIMIT - pos)
            if q > 0:
                cash -= q * my_bid_px; pos += q
    n = min(ticks, len(mid)-1)
    return cash + pos * mid[n], pos

for day in [0, 1, 2]:
    pnl, pos = simulate_wall(day)
    print(f"Day {day}: pnl={pnl:>+8.1f} pos={pos:>+5}")
