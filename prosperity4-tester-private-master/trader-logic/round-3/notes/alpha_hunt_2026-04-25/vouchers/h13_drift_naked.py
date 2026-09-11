"""H13: Naked long voucher on day 2 1k tick.
VFE drift +28 means voucher mid moves up by ~delta * 28.
For limits=300, capacity per strike = 300.

Most CAPITAL EFFICIENT: pick voucher with highest delta * (1k drift) / spread cost.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

# Day 2 1k tick: VFE moves S0 -> SN.
# Naked long 300 vouchers: PnL = 300 * (mid_end - ask_start)
# Or: 300 * (bid_end - ask_start) if we sell out at the end.

for d in [0,1,2]:
    df = load_prices(d)
    if d==2:
        df = df[df["timestamp"]<100000]
    print(f"\n=== Day {d} naked-long (entry@ask, exit@bid) at 300 contracts ===")
    sums = 0
    for v in VOUCHERS:
        sub = df[df["product"]==v]
        ask0 = sub["ask_price_1"].iloc[0]
        bidN = sub["bid_price_1"].iloc[-1]
        midN = sub["mid_price"].iloc[-1]
        pnl_exit_bid = 300 * (bidN - ask0)
        pnl_exit_mid = 300 * (midN - ask0)
        S0 = df[df["product"]==UND]["mid_price"].iloc[0]
        SN = df[df["product"]==UND]["mid_price"].iloc[-1]
        print(f"  {v}: ask0={ask0:.0f} bidN={bidN:.0f} midN={midN:.0f}  PnL exit@bid=${pnl_exit_bid:+.0f} exit@mid=${pnl_exit_mid:+.0f}")
        sums += pnl_exit_bid
    print(f"  S0={S0} SN={SN} drift={SN-S0:+.0f}, total all-strikes naked PnL=${sums:+.0f}")

# But the website uses 1k-tick of Day 2 only. The terminal mid AT website-end may not match end-of-day mid.
# Let's check: at tick=99900 (the website end), where is VFE and each voucher?
print("\n=== AT website-end (tick=99900) for each day ===")
for d in [0,1,2]:
    df = load_prices(d)
    sub = df[df["timestamp"]==99900]
    print(f" Day {d} at t=99900:")
    for v in [UND]+VOUCHERS:
        s = sub[sub["product"]==v]
        if len(s)==0: continue
        print(f"   {v}: bid={s['bid_price_1'].iloc[0]} ask={s['ask_price_1'].iloc[0]} mid={s['mid_price'].iloc[0]}")
