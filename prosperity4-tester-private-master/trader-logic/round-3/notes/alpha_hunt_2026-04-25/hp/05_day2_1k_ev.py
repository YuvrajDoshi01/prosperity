"""Day 2 first 1k ticks: precise EV for each candidate signal at 200-lot scale."""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_hp(day, n=None):
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "HYDROGEL_PACK"].reset_index(drop=True)
    if n: p = p.head(n)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    p["dmid"] = p["mid_price"].diff()
    return p

def sim_signal(p, entry_mask, side, hold, entry_at="ask"):
    """Enter on mask True with `side` direction (+1=long), exit after hold ticks at mid."""
    idx = p.index[entry_mask]
    valid = idx[idx + hold < len(p)]
    if entry_at == "ask":
        entry = np.where(side == +1, p.loc[valid, "ask_price_1"].values, p.loc[valid, "bid_price_1"].values)
    elif entry_at == "mid":
        entry = p.loc[valid, "mid_price"].values
    else:  # passive at best
        entry = p.loc[valid, "mid_price"].values  # best-case
    exit_mid = p.loc[valid + hold, "mid_price"].values
    pnl = side * (exit_mid - entry)
    return pnl, len(valid)

def report(label, pnl, n, lot=200):
    if n == 0:
        print(f"  {label}: n=0")
        return
    avg = pnl.mean()
    hit = (pnl > 0).mean()
    total = avg * n * lot
    print(f"  {label}: n={n:3d} avg_per_lot={avg:+.2f} hit={hit:.2f} TOTAL_EV(lot={lot})=${total:+.0f}")

# Day 2 1k
p = load_hp(2, 1000)
print(f"=== DAY 2 first 1k ticks (n={len(p)}) ===\n")
print(f"mid range: {p['mid_price'].min()} - {p['mid_price'].max()}, spread=17 events: {(p['spread']==17).sum()}\n")

# H1 spread=7 long
print("--- H1a: spread=7 -> LONG at ask, exit after N ---")
for hold in [1, 5, 10, 20]:
    pnl, n = sim_signal(p, p["spread"]==7, +1, hold, "ask")
    report(f"hold={hold:3d}", pnl, n)

print("\n--- H1b: spread=9 -> SHORT at bid, exit after N ---")
for hold in [1, 5, 10, 20]:
    pnl, n = sim_signal(p, p["spread"]==9, -1, hold, "ask")
    report(f"hold={hold:3d}", pnl, n)

# H7 mid-jump reversion
print("\n--- H7a: dmid < -5 (down-jump) -> LONG at ask, exit after N ---")
for hold in [5, 10, 20, 50]:
    pnl, n = sim_signal(p, p["dmid"]<-5, +1, hold, "ask")
    report(f"hold={hold:3d}", pnl, n)
print("\n--- H7b: dmid > +5 (up-jump) -> SHORT at bid, exit after N ---")
for hold in [5, 10, 20, 50]:
    pnl, n = sim_signal(p, p["dmid"]>5, -1, hold, "ask")
    report(f"hold={hold:3d}", pnl, n)

# H9 mid extremes
print("\n--- H9a: mid > 10025 -> SHORT 200, exit after N ---")
for hold in [50, 100, 200]:
    pnl, n = sim_signal(p, p["mid_price"]>10025, -1, hold, "ask")
    report(f"hold={hold:3d}", pnl, n)
print("\n--- H9b: mid < 9970 -> LONG 200, exit after N ---")
for hold in [50, 100, 200]:
    pnl, n = sim_signal(p, p["mid_price"]<9970, +1, hold, "ask")
    report(f"hold={hold:3d}", pnl, n)

# Combined: spread=17 already known $10k. Independence test
print("\n--- spread=17 + mid>10010 -> SHORT 200 (existing v11 strategy verification) ---")
for hold in [5, 20, 50, 100]:
    mask = (p["spread"]==17) & (p["mid_price"]>10010)
    pnl, n = sim_signal(p, mask, -1, hold, "ask")
    report(f"hold={hold:3d}", pnl, n)

# OBI signal
print("\n--- H3: OBI L1 imbalance -> directional ---")
p["obi"] = (p["bid_volume_1"] - p["ask_volume_1"]) / (p["bid_volume_1"] + p["ask_volume_1"])
p["obi_d20"] = p["mid_price"].shift(-20) - p["mid_price"]
print("  Day 2 1k:")
for q_lo, q_hi, label in [(0.9, 1.01, "obi>0.9 (bid heavy)"), (-1.01, -0.9, "obi<-0.9 (ask heavy)")]:
    mask = (p["obi"] > q_lo) & (p["obi"] <= q_hi)
    if mask.sum() < 5: continue
    side = +1 if q_lo > 0 else -1
    pnl, n = sim_signal(p, mask, side, 20, "ask")
    report(f"{label} hold=20", pnl, n)

# 3-day overall confirmation
print("\n=== 3-DAY CROSS-VALIDATION (full 10k each day) ===")
for day in [0, 1, 2]:
    p_full = load_hp(day)
    print(f"--- DAY {day} ---")
    for hold in [5, 20]:
        pnl, n = sim_signal(p_full, p_full["dmid"]<-5, +1, hold, "ask")
        report(f"  H7a dmid<-5 LONG hold={hold}", pnl, n)
        pnl, n = sim_signal(p_full, p_full["dmid"]>5, -1, hold, "ask")
        report(f"  H7b dmid>+5 SHORT hold={hold}", pnl, n)
    pnl, n = sim_signal(p_full, p_full["mid_price"]>10025, -1, 100, "ask")
    report(f"  H9a mid>10025 SHORT hold=100", pnl, n)
    pnl, n = sim_signal(p_full, p_full["mid_price"]<9970, +1, 100, "ask")
    report(f"  H9b mid<9970 LONG hold=100", pnl, n)
