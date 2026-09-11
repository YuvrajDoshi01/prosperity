"""H8: Short vol delta-hedged. Day 2 1k-tick has IV~0.20 vs RV~0.11.
Sell at mid (using both sides bid/ask average), delta-hedge each tick.
Better than naive sell-at-bid since spread is wide.

ALSO: short straddle = short ATM call + short ATM put. We don't have puts.
But short-call delta-hedge IS short vol.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

def short_vol_pnl(day, voucher, qty=300, max_window=1000, entry_mode="bid"):
    df = load_prices(day)
    if day==2 and max_window:
        df = df[df["timestamp"]<max_window*100]
    K = int(voucher.split("_")[1])
    T0 = TTE[day]
    bv = df[df["product"]==voucher].set_index("timestamp")
    bu = df[df["product"]==UND].set_index("timestamp")
    ts = sorted(set(bv.index) & set(bu.index))
    n = len(ts)
    cash, pos_v, pos_u = 0.0, 0, 0
    t0 = ts[0]
    v0, u0 = bv.loc[t0], bu.loc[t0]
    iv0 = implied_vol(v0["mid_price"], u0["mid_price"], K, T0)
    if np.isnan(iv0): iv0 = 0.20
    # Entry: SELL at bid (qty)
    if entry_mode=="bid":
        entry_px = v0["bid_price_1"]
    elif entry_mode=="mid":
        entry_px = v0["mid_price"]
    else:
        entry_px = v0["ask_price_1"]
    pos_v = -qty
    cash += qty * entry_px
    # Hedge: long delta in VFE
    delta = bs_delta(u0["mid_price"], K, T0, iv0)
    target_u = int(round(qty * delta))
    target_u = max(-200, min(200, target_u))
    cash -= target_u * u0["mid_price"]
    pos_u = target_u
    iv_used = iv0
    for i in range(1, n):
        t = ts[i]
        v, u = bv.loc[t], bu.loc[t]
        T = max(1e-6, T0 - i/n/250)
        iv = implied_vol(v["mid_price"], u["mid_price"], K, T)
        if not np.isnan(iv): iv_used = iv
        delta = bs_delta(u["mid_price"], K, T, iv_used)
        target_u = int(round(-pos_v * delta))
        target_u = max(-200, min(200, target_u))
        d = target_u - pos_u
        cash -= d * u["mid_price"]
        pos_u = target_u
    tN = ts[-1]
    vN, uN = bv.loc[tN], bu.loc[tN]
    final = pos_v * vN["mid_price"] + pos_u * uN["mid_price"] + cash
    return final, entry_px, vN["mid_price"], iv0

print("SHORT vol delta-hedged on day 2 1k-tick (entry@BID):")
for v in VOUCHERS:
    p, ent, ex, iv = short_vol_pnl(2, v, qty=300, max_window=1000, entry_mode="bid")
    print(f"  {v}: PnL=${p:+.0f} entry@bid={ent:.2f} exit_mid={ex:.2f} iv0={iv:.3f}")
print("\nSHORT vol delta-hedged on day 2 1k-tick (entry@MID — optimistic):")
for v in VOUCHERS:
    p, ent, ex, iv = short_vol_pnl(2, v, qty=300, max_window=1000, entry_mode="mid")
    print(f"  {v}: PnL=${p:+.0f} entry@mid={ent:.2f} exit_mid={ex:.2f}")

print("\nCross-day stability (full day each, entry@bid):")
for d in [0,1,2]:
    print(f" day {d}:")
    for v in ["VEV_5000","VEV_5100","VEV_5200","VEV_5300","VEV_5400"]:
        p, ent, ex, iv = short_vol_pnl(d, v, qty=300, max_window=None, entry_mode="bid")
        print(f"   {v}: PnL=${p:+.0f}")
