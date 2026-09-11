"""H5: Test executability of VEV_4000-VEV_4500 vertical arb.
Need: bid of VEV_4000 - ask of VEV_4500 > 500 (sell 4000, buy 4500).
Compute on actual book L1.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

for d in [0,1,2]:
    df = load_prices(d)
    if d==2:
        df = df[df["timestamp"]<100000]
    bb = df.pivot(index="timestamp", columns="product", values="bid_price_1")
    aa = df.pivot(index="timestamp", columns="product", values="ask_price_1")
    bv = df.pivot(index="timestamp", columns="product", values="bid_volume_1")
    av = df.pivot(index="timestamp", columns="product", values="ask_volume_1")
    # Sell 4000 at bid, buy 4500 at ask. Net = bid_4000 - ask_4500. Arbitrage if > 500.
    sell4000_buy4500 = bb["VEV_4000"] - aa["VEV_4500"]
    arb_mask = sell4000_buy4500 > 500
    n_arb = arb_mask.sum()
    if n_arb>0:
        excess = sell4000_buy4500[arb_mask] - 500
        # Cap fillable size by min(bid_vol_4000, ask_vol_4500)
        fillable = np.minimum(bv["VEV_4000"][arb_mask].values, av["VEV_4500"][arb_mask].values)
        total_pnl = (excess.values * fillable).sum()
        print(f"day{d}: sell4000+buy4500 arb: n={n_arb}/{len(df.timestamp.unique())} ticks, "
              f"mean excess={excess.mean():.2f}, mean fillable size={fillable.mean():.1f}, "
              f"TOTAL PNL (one fill per tick) = ${total_pnl:.0f}")
    else:
        print(f"day{d}: no executable sell4000+buy4500 arb")
    # Reverse direction? buy 4000 sell 4500
    buy4000_sell4500 = bb["VEV_4500"] - aa["VEV_4000"]
    # buy 4000 at ask, sell 4500 at bid. C4000 - C4500 must be <= 500 always (vertical lower? no upper).
    # buy 4000 sell 4500: receive bid_4500 - pay ask_4000 = - (ask_4000 - bid_4500).
    # Since ask_4000 > bid_4500 (4000 always pricier), this is a debit. Not arb direction.

    # Also check 4500-5000 vertical (could exist)
    spread45_50 = bb["VEV_4500"] - aa["VEV_5000"]
    arb45 = spread45_50 > 500
    if arb45.sum()>0:
        excess = spread45_50[arb45] - 500
        fillable = np.minimum(bv["VEV_4500"][arb45].values, av["VEV_5000"][arb45].values)
        print(f"  day{d}: sell4500+buy5000 arb: n={arb45.sum()}, mean excess={excess.mean():.2f}, total ${(excess.values*fillable).sum():.0f}")
