"""Counterparty analysis: which buyers/sellers correlate with future VFE moves?"""
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_vfe(day):
    p = pd.read_csv(f"{ROOT}/prices_round_3_day_{day}.csv", sep=";")
    t = pd.read_csv(f"{ROOT}/trades_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    t = t[t["symbol"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    return p, t

print("=== Unique buyers/sellers per day ===")
for day in [0, 1, 2]:
    _, t = load_vfe(day)
    print(f"Day {day}: buyers = {sorted(t['buyer'].fillna('').unique())}")
    print(f"Day {day}: sellers = {sorted(t['seller'].fillna('').unique())}")
    print(f"  total trades: {len(t)}")

# Per-counterparty: count trades + average fwd return after their trade
print("\n=== Per-counterparty avg forward return (h=20, 100, 500 ticks) ===")
def analyze(day):
    p, t = load_vfe(day)
    mid = p["mid_price"].values
    rows = []
    for _, row in t.iterrows():
        ti = int(row["timestamp"] // 100)
        if ti >= len(mid)-500: continue
        for side, party in [("buyer", row["buyer"]), ("seller", row["seller"])]:
            if pd.isna(party) or party == "": continue
            r20 = mid[ti+20] - mid[ti]
            r100 = mid[ti+100] - mid[ti]
            r500 = mid[ti+500] - mid[ti]
            rows.append((party, side, row["quantity"], r20, r100, r500))
    df = pd.DataFrame(rows, columns=["party", "side", "qty", "r20", "r100", "r500"])
    return df

for day in [0, 1, 2]:
    df = analyze(day)
    print(f"\n--- Day {day} ---")
    g = df.groupby(["party", "side"]).agg(
        n=("qty", "count"),
        vol=("qty", "sum"),
        avg_r20=("r20", "mean"),
        avg_r100=("r100", "mean"),
        avg_r500=("r500", "mean"),
    ).reset_index()
    print(g.to_string(index=False))

# Restrict to first 1k ticks
print("\n=== First 1k ticks per-counterparty (where signals must emerge) ===")
def analyze_1k(day):
    p, t = load_vfe(day)
    mid = p["mid_price"].values
    rows = []
    for _, row in t.iterrows():
        ti = int(row["timestamp"] // 100)
        if ti >= 1000: continue
        if ti >= len(mid)-50: continue
        for side, party in [("buyer", row["buyer"]), ("seller", row["seller"])]:
            if pd.isna(party) or party == "": continue
            r20 = mid[ti+20] - mid[ti]
            r50 = mid[ti+50] - mid[ti]
            rows.append((party, side, row["quantity"], r20, r50))
    df = pd.DataFrame(rows, columns=["party", "side", "qty", "r20", "r50"])
    return df

for day in [0, 1, 2]:
    df = analyze_1k(day)
    print(f"\n--- Day {day} (first 1k) ---")
    g = df.groupby(["party", "side"]).agg(
        n=("qty", "count"),
        vol=("qty", "sum"),
        avg_r20=("r20", "mean"),
        avg_r50=("r50", "mean"),
    ).reset_index()
    print(g.to_string(index=False))
