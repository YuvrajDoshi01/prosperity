"""H1: Narrow-spread {7,8,9} → directional. Quantify EV at 200-lot, persistence, exit horizon."""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_hp(day):
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "HYDROGEL_PACK"].reset_index(drop=True)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    return p

# Hypothesis: narrow spread = MM about to skew quote up/down based on which side is tight
# Decompose: is narrowness from bid up (bullish) or ask down (bearish)?
print("=== Spread=7 vs 9 - decomposition: which side moved? ===")
for day in [0,1,2]:
    p = load_hp(day)
    p["bid_d"] = p["bid_price_1"].diff()
    p["ask_d"] = p["ask_price_1"].diff()
    p["mid_d_next"] = p["mid_price"].shift(-1) - p["mid_price"]
    p["mid_d_5"] = p["mid_price"].shift(-5) - p["mid_price"]
    p["mid_d_20"] = p["mid_price"].shift(-20) - p["mid_price"]
    print(f"--- DAY {day} ---")
    for s in [7,8,9]:
        m = p[p["spread"] == s]
        print(f"  spread={s} n={len(m)}: avg bid_d={m['bid_d'].mean():+.2f} ask_d={m['ask_d'].mean():+.2f} | fwd1={m['mid_d_next'].mean():+.2f} fwd5={m['mid_d_5'].mean():+.2f} fwd20={m['mid_d_20'].mean():+.2f}")

# Hit rate / EV at 200 lot for entry-on-spread-event, exit-after-N
print("\n=== EV simulation: enter at next bid/ask after spread event, hold N ticks ===")
print("(model: spread=7 -> BUY 200 at ask, exit at mid+N. spread=9 -> SHORT 200 at bid, exit at mid+N)")
for day in [0,1,2]:
    p = load_hp(day)
    print(f"--- DAY {day} ---")
    for s, side in [(7, +1), (9, -1)]:
        for hold in [1, 5, 10, 20, 50]:
            mask = p["spread"] == s
            n = mask.sum()
            if n == 0: continue
            entry_idx = p.index[mask]
            valid = entry_idx[entry_idx + hold < len(p)]
            if side == +1:  # buy at ask
                entry_px = p.loc[valid, "ask_price_1"].values
            else:  # sell at bid
                entry_px = p.loc[valid, "bid_price_1"].values
            exit_px = p.loc[valid + hold, "mid_price"].values
            pnl_per = side * (exit_px - entry_px)
            avg = pnl_per.mean()
            hit = (pnl_per > 0).mean()
            ev_200 = avg * 200
            print(f"  spread={s} hold={hold:3d}: n={len(valid):3d} avg_pnl_per_lot={avg:+.2f} hit={hit:.2f} | EV_200lot=${ev_200:+.0f}")

# 1k-tick day 2 specific
print("\n=== Day 2 first 1k ticks (website BT zone) ===")
p = load_hp(2).head(1000)
for s in [7,8,9,17]:
    n = (p["spread"] == s).sum()
    print(f"  spread={s}: n={n} in first 1k ticks")
