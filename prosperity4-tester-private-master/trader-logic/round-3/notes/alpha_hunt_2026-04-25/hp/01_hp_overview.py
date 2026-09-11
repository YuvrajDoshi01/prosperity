"""HP overview: load 3 days, basic stats, spread distribution, jump distribution."""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_hp(day):
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    t = pd.read_csv(f"{BASE}/trades_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "HYDROGEL_PACK"].reset_index(drop=True)
    t = t[t["symbol"] == "HYDROGEL_PACK"].reset_index(drop=True)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    p["dmid"] = p["mid_price"].diff()
    p["mid_5"] = p["mid_price"].shift(-5)
    p["fwd5"] = p["mid_5"] - p["mid_price"]
    p["mid_20"] = p["mid_price"].shift(-20)
    p["fwd20"] = p["mid_20"] - p["mid_price"]
    return p, t

for d in [0,1,2]:
    p, t = load_hp(d)
    print(f"\n=== Day {d} | n={len(p)} | trades={len(t)} ===")
    print(f"  mid: open={p['mid_price'].iloc[0]:.0f} close={p['mid_price'].iloc[-1]:.0f} min={p['mid_price'].min():.0f} max={p['mid_price'].max():.0f}")
    print(f"  spread distribution:\n{p['spread'].value_counts().sort_index().to_string()}")
    print(f"  abs(dmid) > 5 count: {(p['dmid'].abs() > 5).sum()} | >10: {(p['dmid'].abs() > 10).sum()}")
