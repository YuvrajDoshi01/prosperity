"""Load all 3 days, build mid-price wide tables, save pickles for downstream."""
import pandas as pd
import numpy as np
import os, pickle

DATA = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"
OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"

VOUCHERS = [4000,4500,5000,5100,5200,5300,5400,5500,6000,6500]
PRODUCTS = ["HYDROGEL_PACK","VELVETFRUIT_EXTRACT"] + [f"VEV_{k}" for k in VOUCHERS]

mids = {}
obi  = {}
spreads = {}
trades_per_day = {}
for day in [0,1,2]:
    p = pd.read_csv(os.path.join(DATA, f"prices_round_3_day_{day}.csv"), sep=";")
    t = pd.read_csv(os.path.join(DATA, f"trades_round_3_day_{day}.csv"), sep=";")
    p = p.sort_values(["timestamp","product"])
    # mid pivot
    mid = p.pivot(index="timestamp", columns="product", values="mid_price")
    mids[day] = mid
    # obi: (b1 - a1) / (b1+a1)
    bv = p.pivot(index="timestamp", columns="product", values="bid_volume_1").fillna(0)
    av = p.pivot(index="timestamp", columns="product", values="ask_volume_1").fillna(0)
    o = (bv - av) / (bv + av).replace(0, np.nan)
    obi[day] = o
    # bid-ask spread
    bp = p.pivot(index="timestamp", columns="product", values="bid_price_1")
    ap = p.pivot(index="timestamp", columns="product", values="ask_price_1")
    spreads[day] = ap - bp
    trades_per_day[day] = t

with open(os.path.join(OUT, "data.pkl"), "wb") as f:
    pickle.dump({"mids":mids,"obi":obi,"spreads":spreads,"trades":trades_per_day,
                 "vouchers":VOUCHERS,"products":PRODUCTS}, f)

# Summary
for day in [0,1,2]:
    m = mids[day]
    print(f"\n=== Day {day} ===")
    print(f"Ticks: {len(m)}, products: {list(m.columns)[:3]}...")
    print("Open->Close:")
    for c in ["HYDROGEL_PACK","VELVETFRUIT_EXTRACT","VEV_4000","VEV_5000","VEV_5300","VEV_5500"]:
        if c in m.columns:
            o = m[c].dropna().iloc[0]; cl = m[c].dropna().iloc[-1]
            print(f"  {c}: {o:.1f} -> {cl:.1f} (drift {cl-o:+.1f})")
print("\nSaved data.pkl")
