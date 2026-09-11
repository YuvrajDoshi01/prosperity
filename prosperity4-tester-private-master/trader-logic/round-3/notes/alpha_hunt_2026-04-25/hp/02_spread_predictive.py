"""H1+H2: spread regime → forward returns. Especially narrow spreads {7,8,9}."""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_hp(day):
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "HYDROGEL_PACK"].reset_index(drop=True)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    for k in [1,5,10,20,50,100]:
        p[f"fwd{k}"] = p["mid_price"].shift(-k) - p["mid_price"]
    return p

print("=== Forward mid moves by spread regime ===")
print("spread | n     | mean_fwd1 | mean_fwd5 | mean_fwd20 | mean_fwd100 | std_fwd20 |")
for day in [0,1,2]:
    p = load_hp(day)
    print(f"--- DAY {day} ---")
    for s in [7,8,9,15,16,17]:
        mask = p["spread"] == s
        n = mask.sum()
        if n < 5: continue
        m1 = p.loc[mask, "fwd1"].mean()
        m5 = p.loc[mask, "fwd5"].mean()
        m20 = p.loc[mask, "fwd20"].mean()
        m100 = p.loc[mask, "fwd100"].mean()
        s20 = p.loc[mask, "fwd20"].std()
        print(f"  {s:5d} | {n:5d} | {m1:+.3f}    | {m5:+.3f}    | {m20:+.3f}     | {m100:+.3f}      | {s20:.2f}")

# Conditional: spread regime + price level
print("\n=== Spread + Mid relative to day-mean (z-score) → fwd20 mid move ===")
for day in [0,1,2]:
    p = load_hp(day).head(2000)  # restrict to first 2k for day-2 alignment
    mid_mean = p["mid_price"].mean()
    mid_std = p["mid_price"].std()
    p["mid_z"] = (p["mid_price"] - mid_mean) / mid_std
    print(f"--- DAY {day} (first 2k) mean={mid_mean:.1f} std={mid_std:.2f} ---")
    for s in [7,8,9,17]:
        for zlo, zhi, label in [(-99,-1,"low z<-1"), (-1,1,"mid"), (1,99,"high z>1")]:
            mask = (p["spread"] == s) & (p["mid_z"] >= zlo) & (p["mid_z"] < zhi)
            n = mask.sum()
            if n < 3: continue
            m20 = p.loc[mask, "fwd20"].mean()
            print(f"  spr={s} {label:12s}: n={n:3d} fwd20={m20:+.3f}")
