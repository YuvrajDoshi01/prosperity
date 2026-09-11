"""Trend-reversion SHORT: when mid up >X over Y ticks, short, exit on reversion.
Cross-validate Day 0/1/2."""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_hp(day, n=None):
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "HYDROGEL_PACK"].reset_index(drop=True)
    if n: p = p.head(n)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    return p

def trend_short_sim(p, lookback=50, trigger=10, exit_d=-5, lot=200):
    """SHORT when mid - mid[i-lookback] >= trigger. Exit when (current - entry) <= exit_d."""
    pos = 0; entry_px = 0; entry_mid = 0; total_pnl = 0; trades = []
    for i in range(lookback, len(p)):
        cur_mid = p["mid_price"].iloc[i]
        if pos == 0:
            roll = cur_mid - p["mid_price"].iloc[i - lookback]
            if roll >= trigger:
                entry_px = p["bid_price_1"].iloc[i]  # passive short at bid
                entry_mid = cur_mid
                pos = -lot
        else:
            if cur_mid - entry_mid <= exit_d or i == len(p) - 1:
                exit_px = p["ask_price_1"].iloc[i]
                pnl = (entry_px - exit_px) * lot
                total_pnl += pnl
                trades.append((i, entry_mid, cur_mid, pnl))
                pos = 0
    return total_pnl, trades

print("=== Trend-reversion SHORT: enter when mid rose by TRIGGER over LOOKBACK ticks; exit when mid drops EXIT_D from entry ===\n")
print(f"{'lookback':>8} {'trig':>5} {'exit':>5} | day0_full | day1_full | day2_1k | day2_full")
for lookback in [30, 50, 100]:
    for trigger in [8, 10, 15, 20]:
        for exit_d in [-3, -5, -8, -15]:
            row = f"{lookback:>8} {trigger:>5} {exit_d:>5} |"
            for spec in [("d0_full", 0, None), ("d1_full", 1, None), ("d2_1k", 2, 1000), ("d2_full", 2, None)]:
                lbl, d, n = spec
                p = load_hp(d, n)
                pnl, tr = trend_short_sim(p, lookback, trigger, exit_d)
                row += f" ${pnl:+7.0f}({len(tr):2d}) |"
            print(row)
    print()

# Mirror: trend-following LONG when mid drops sharply (mean revert)
print("=== Mirror: LONG when mid DROPPED >= TRIGGER over LOOKBACK ticks; exit when up by EXIT_D ===")
def trend_long_sim(p, lookback=50, trigger=10, exit_d=5, lot=200):
    pos = 0; entry_px = 0; entry_mid = 0; total_pnl = 0; trades = []
    for i in range(lookback, len(p)):
        cur_mid = p["mid_price"].iloc[i]
        if pos == 0:
            roll = p["mid_price"].iloc[i - lookback] - cur_mid  # drop
            if roll >= trigger:
                entry_px = p["ask_price_1"].iloc[i]  # cross to buy
                entry_mid = cur_mid
                pos = +lot
        else:
            if cur_mid - entry_mid >= exit_d or i == len(p) - 1:
                exit_px = p["bid_price_1"].iloc[i]
                pnl = (exit_px - entry_px) * lot
                total_pnl += pnl
                trades.append((i, entry_mid, cur_mid, pnl))
                pos = 0
    return total_pnl, trades

print(f"{'lookback':>8} {'trig':>5} {'exit':>5} | day0_full | day1_full | day2_1k | day2_full")
for lookback in [30, 50, 100]:
    for trigger in [8, 15, 20]:
        for exit_d in [3, 5, 10]:
            row = f"{lookback:>8} {trigger:>5} {exit_d:>5} |"
            for spec in [("d0_full", 0, None), ("d1_full", 1, None), ("d2_1k", 2, 1000), ("d2_full", 2, None)]:
                lbl, d, n = spec
                p = load_hp(d, n)
                pnl, tr = trend_long_sim(p, lookback, trigger, exit_d)
                row += f" ${pnl:+7.0f}({len(tr):2d}) |"
            print(row)
    print()
