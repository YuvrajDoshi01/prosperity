"""H7: Simulate delta-hedged voucher trade across day 2 1k-tick.
Strategy: at t=0 buy 300 contracts at ask, hedge delta with VFE (limit 200).
Rehedge each tick. PnL at end.

Compare buying ATM vs OTM vouchers.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

def simulate(day, voucher, qty_voucher=300, voucher_side="buy", hedge=True):
    df = load_prices(day)
    if day==2:
        df = df[df["timestamp"]<100000]
    # Price series for voucher and underlying
    bb_v = df[df["product"]==voucher].set_index("timestamp")
    bb_u = df[df["product"]==UND].set_index("timestamp")
    ts = sorted(set(bb_v.index) & set(bb_u.index))
    if len(ts)<10: return None
    K = int(voucher.split("_")[1])
    T0 = TTE[day]
    n = len(ts)
    cash = 0.0
    pos_v = 0
    pos_u = 0
    # Initial entry at t=0: pay/receive ask/bid
    t0 = ts[0]
    v0 = bb_v.loc[t0]
    u0 = bb_u.loc[t0]
    # Buy at ask
    if voucher_side=="buy":
        entry_price = v0["ask_price_1"]
        pos_v = qty_voucher
        cash -= qty_voucher * entry_price
    else:
        entry_price = v0["bid_price_1"]
        pos_v = -qty_voucher
        cash += qty_voucher * entry_price
    # Hedge: compute initial delta
    iv0 = implied_vol(v0["mid_price"], u0["mid_price"], K, T0)
    if np.isnan(iv0): iv0 = 0.20
    # Walk through ticks, mark to mid at end. No rehedge to keep simple.
    # For rehedge: each tick recompute delta, adjust pos_u with VFE mid (assume mid = fair fill).
    # Position limit on VFE = 200.
    delta_sum_pnl = 0.0
    last_S = u0["mid_price"]
    if hedge:
        delta = bs_delta(u0["mid_price"], K, T0, iv0)
        target_u = -int(round(qty_voucher * delta)) if voucher_side=="buy" else int(round(qty_voucher * delta))
        target_u = max(-200, min(200, target_u))
        # Initial hedge cross spread: assume mid fill (optimistic).
        cash -= target_u * u0["mid_price"]
        pos_u = target_u
    for i in range(1, n):
        t = ts[i]
        v = bb_v.loc[t]
        u = bb_u.loc[t]
        T = T0 - i/n / 250  # very small change
        if hedge:
            iv = implied_vol(v["mid_price"], u["mid_price"], K, T)
            if np.isnan(iv): iv = iv0
            delta = bs_delta(u["mid_price"], K, T, iv)
            target_u = -int(round(pos_v * delta))
            target_u = max(-200, min(200, target_u))
            d = target_u - pos_u
            cash -= d * u["mid_price"]
            pos_u = target_u
    # Final mark-to-mid (round-end approximation)
    tN = ts[-1]
    vN = bb_v.loc[tN]
    uN = bb_u.loc[tN]
    final_value = pos_v * vN["mid_price"] + pos_u * uN["mid_price"] + cash
    return {
        "voucher": voucher,
        "side": voucher_side,
        "entry_px": entry_price,
        "exit_mid": vN["mid_price"],
        "S0": u0["mid_price"],
        "SN": uN["mid_price"],
        "PnL": final_value,
        "PnL_voucher_only": qty_voucher * (vN["mid_price"] - entry_price) * (1 if voucher_side=="buy" else -1),
    }

print("Buy 300 vouchers @ ask, delta-hedge each tick, exit at mid. Day 2 1k-tick.")
for v in VOUCHERS:
    r = simulate(2, v, voucher_side="buy", hedge=True)
    if r:
        print(f"  {r['voucher']}: entry={r['entry_px']:.2f} exit={r['exit_mid']:.2f} | "
              f"S {r['S0']:.0f}->{r['SN']:.0f} | "
              f"PnL hedged=${r['PnL']:.0f}  unhedged=${r['PnL_voucher_only']:.0f}")
print()
print("SELL 300 vouchers @ bid, delta-hedge each tick. Day 2 1k-tick.")
for v in VOUCHERS:
    r = simulate(2, v, voucher_side="sell", hedge=True)
    if r:
        print(f"  {r['voucher']}: entry={r['entry_px']:.2f} exit={r['exit_mid']:.2f} | "
              f"PnL hedged=${r['PnL']:.0f}  unhedged=${r['PnL_voucher_only']:.0f}")

print()
print("Cross-day check: BUY @ ask, hedged, day 0/1/2 entire day:")
for d in [0,1,2]:
    print(f" --- day {d}, 1k-tick={'yes' if d==2 else 'no (full day)'} ---")
    for v in ["VEV_5000","VEV_5100","VEV_5200","VEV_5300"]:
        r = simulate(d, v, voucher_side="buy", hedge=True)
        if r:
            print(f"   {v}: PnL hedged=${r['PnL']:.0f}  unhedged=${r['PnL_voucher_only']:.0f}")
