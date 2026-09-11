"""Day 2 1k = first 1k of day 2. Big down move 10011 -> 9960 then back. Find ENTRY signal that fires
at the open and shorts in. Test cross-day."""
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

# Day 2 1k trajectory
print("=== Day 2 first 1k mid trajectory (every 100 ticks) ===")
p2 = load_hp(2, 1000)
for i in range(0, 1000, 100):
    print(f"  tick={i*100:6d} mid={p2['mid_price'].iloc[i]:.0f} spread={p2['spread'].iloc[i]:.0f}")
print(f"  tick={999*100} mid={p2['mid_price'].iloc[-1]:.0f}")
print(f"  min over 1k: {p2['mid_price'].min():.0f} at tick {p2['mid_price'].idxmin()*100}")

# What signal fires early (in first 200 ticks) that says "go short"?
print("\n=== First 200 ticks of each day - early indicators ===")
for d in [0, 1, 2]:
    p = load_hp(d, 200)
    print(f"--- Day {d} first 200 ticks ---")
    print(f"  mid open->close: {p['mid_price'].iloc[0]:.0f} -> {p['mid_price'].iloc[-1]:.0f}")
    print(f"  mid_min over 200: {p['mid_price'].min():.0f} idx {p['mid_price'].idxmin()}")
    print(f"  cumulative dmid: {p['dmid'].sum():+.0f}")
    print(f"  spread distribution: {dict(p['spread'].value_counts().sort_index())}")
    p_50 = p.head(50)
    print(f"  first 50 ticks: mid {p_50['mid_price'].iloc[0]:.0f} -> {p_50['mid_price'].iloc[-1]:.0f} | spread mode={p_50['spread'].mode().iloc[0]}")

# Check: does the rolling-mean comparison strategy from r3_v3 day-type detection work for shorting?
# At tick 20: rolling_mean(window=20) compared to current mid - does mid > rolling indicate down trend coming?
print("\n=== Rolling mean signal at tick 20 ===")
for d in [0, 1, 2]:
    p = load_hp(d)
    if len(p) < 1000: continue
    mid_at_20 = p["mid_price"].iloc[20]
    mid_at_open = p["mid_price"].iloc[0]
    rolling_mean = p["mid_price"].iloc[:20].mean()
    cur_minus_rolling = mid_at_20 - rolling_mean
    cur_minus_open = mid_at_20 - mid_at_open
    print(f"  Day {d}: open={mid_at_open:.0f} mid@20={mid_at_20:.0f} roll_mean@20={rolling_mean:.1f} d_open={cur_minus_open:+.1f} d_roll={cur_minus_rolling:+.2f}")

# Volatility burst -> reversion?
print("\n=== Rolling std as regime signal ===")
for d in [0, 1, 2]:
    p = load_hp(d, 1000) if d == 2 else load_hp(d)
    p["std20"] = p["mid_price"].rolling(20).std()
    p["std50"] = p["mid_price"].rolling(50).std()
    print(f"  Day {d}: std20 mean={p['std20'].mean():.2f} max={p['std20'].max():.2f} | std50 mean={p['std50'].mean():.2f}")

# Net dmid over rolling window as trend signal
print("\n=== Net dmid over rolling 50 - persistence vs reversion ===")
for d in [0, 1, 2]:
    p = load_hp(d, 1000) if d == 2 else load_hp(d)
    p["dmid_50"] = p["mid_price"].diff(50)
    p["fwd50"] = p["mid_price"].shift(-50) - p["mid_price"]
    p["fwd200"] = p["mid_price"].shift(-200) - p["mid_price"]
    label = f"Day {d}" + (" 1k" if d == 2 else "")
    print(f"--- {label} ---")
    p["q"] = pd.qcut(p["dmid_50"].dropna(), q=5, labels=False, duplicates="drop")
    for q in [0, 4]:
        m = p["q"] == q
        if m.sum() < 5: continue
        avg_dmid = p.loc[m, "dmid_50"].mean()
        f50 = p.loc[m, "fwd50"].mean()
        f200 = p.loc[m, "fwd200"].mean()
        print(f"  dmid50 q{q} avg={avg_dmid:+.1f} | fwd50={f50:+.2f} fwd200={f200:+.2f}")
