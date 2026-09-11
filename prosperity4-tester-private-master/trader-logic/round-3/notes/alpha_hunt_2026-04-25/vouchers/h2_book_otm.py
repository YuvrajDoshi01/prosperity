"""H2: Look at bid/ask structure on far-OTM vouchers, especially 6000/6500.
If best_bid is 0 always (or NaN) and asks are high, can we sell at ask and let it expire worthless?
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

for d in [0,1,2]:
    df = load_prices(d)
    print(f"\n=== Day {d} OTM book stats (1k-tick window for day 2) ===")
    if d==2:
        df = df[df["timestamp"]<100000]
    for k in [5200,5300,5400,5500,6000,6500]:
        v = f"VEV_{k}"
        sub = df[df["product"]==v]
        bb = sub["bid_price_1"].dropna()
        aa = sub["ask_price_1"].dropna()
        bv = sub["bid_volume_1"].dropna()
        av = sub["ask_volume_1"].dropna()
        spread = (aa.values - bb.values) if len(aa)==len(bb) else None
        print(f"{v}: bb mean={bb.mean():.2f} (min={bb.min()},max={bb.max()}), "
              f"aa mean={aa.mean():.2f} (min={aa.min()},max={aa.max()}), "
              f"spread mean={spread.mean() if spread is not None else 'na':.2f}, "
              f"bv mean={bv.mean():.1f}, av mean={av.mean():.1f}")
        # Distribution of bb
        print(f"  bb counts: {bb.value_counts().head(5).to_dict()}")
        print(f"  aa counts: {aa.value_counts().head(5).to_dict()}")
