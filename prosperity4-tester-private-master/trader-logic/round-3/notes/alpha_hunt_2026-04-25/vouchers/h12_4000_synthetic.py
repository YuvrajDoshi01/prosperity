"""H12: VEV_4000 is deep ITM (S~5290, K=4000). Delta should be ~1.0.
Synthetic: long VFE = long VEV_4000 + cash_K.
We can replicate VFE LONG via: buy VEV_4000 at ask. Cost = ask_4000.
Delta-1 means dVEV_4000 ~= dVFE.

Trade strategy: when VEV_4000 ask < VFE_bid - K, BUY VEV_4000, SHORT VFE.
At close, VEV_4000 -> S - K (intrinsic), VFE -> S. Position closes at: -K + (intrinsic - ask_4000) + (VFE_bid - S_close).
Need ask_4000 + K < VFE_bid simultaneously (already done in v11 — only 1 tick day 2).

Look at: trades on VEV_4000 day 2 1k-tick. Are there many cheap fills?
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

for d in [0,1,2]:
    pr = load_prices(d)
    tr = load_trades(d)
    if d==2:
        pr = pr[pr["timestamp"]<100000]
        tr = tr[tr["timestamp"]<100000]
    print(f"\n=== Day {d} ===")
    # VEV_4000 trade direction
    sub = tr[tr["symbol"]=="VEV_4000"]
    n = len(sub)
    if n>0:
        # Compare trade price to mid at that timestamp
        mid_4k = pr[pr["product"]=="VEV_4000"].set_index("timestamp")["mid_price"]
        sub2 = sub.copy()
        sub2["mid"] = sub2["timestamp"].map(mid_4k)
        sub2["above_mid"] = sub2["price"] > sub2["mid"]
        sub2["below_mid"] = sub2["price"] < sub2["mid"]
        # If price > mid: buyer initiated (paid ask). If <: seller initiated.
        n_buy = sub2["above_mid"].sum()
        n_sell = sub2["below_mid"].sum()
        print(f"  VEV_4000 trades: total={n}, buy-init (above mid)={n_buy}, sell-init={n_sell}")
        # Also: is there free intrinsic?
        # Check book intrinsic on 4000 ITM: ask_4000 + 4000 < bid_VFE means free $
        bb = pr[pr["product"]==UND].set_index("timestamp")["bid_price_1"]
        aa_4k = pr[pr["product"]=="VEV_4000"].set_index("timestamp")["ask_price_1"]
        edge = bb - aa_4k - 4000
        e_pos = (edge > 0).sum()
        if e_pos>0:
            print(f"  intrinsic arb (buy 4000 ask, sell VFE bid): {e_pos} ticks, mean ${edge[edge>0].mean():.2f}")

    # VEV_4500 cheap fills
    sub = tr[tr["symbol"]=="VEV_4500"]
    n = len(sub)
    if n>0:
        mid_45k = pr[pr["product"]=="VEV_4500"].set_index("timestamp")["mid_price"]
        sub2 = sub.copy()
        sub2["mid"] = sub2["timestamp"].map(mid_45k)
        n_buy = (sub2["price"] > sub2["mid"]).sum()
        n_sell = (sub2["price"] < sub2["mid"]).sum()
        print(f"  VEV_4500 trades: total={n}, buy-init={n_buy}, sell-init={n_sell}, avg_p={sub['price'].mean():.1f}")
