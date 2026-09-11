"""Passive capture strategies + spread=17 short side and refinements.
Look for asymmetric trigger: spread=17 + mid<9990 -> LONG?
"""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_hp(day, n=None):
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "HYDROGEL_PACK"].reset_index(drop=True)
    if n: p = p.head(n)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    return p

# spread=17 distribution by mid
print("=== spread=17 events: mid distribution ===")
for d in [0, 1, 2]:
    p = load_hp(d, 1000) if d == 2 else load_hp(d)
    s17 = p[p["spread"]==17]
    label = f"Day {d}" + (" 1k" if d == 2 else "")
    if len(s17) == 0:
        print(f"  {label}: no s=17 events"); continue
    print(f"  {label} n={len(s17)}: mid 25%={s17['mid_price'].quantile(0.25):.0f} 50%={s17['mid_price'].quantile(0.5):.0f} 75%={s17['mid_price'].quantile(0.75):.0f} mean={s17['mid_price'].mean():.0f}")

# Test: spread=17 AND mid <= MEDIAN -> LONG?
print("\n=== spread=17 LONG side test: when s=17 AND mid<=THR, LONG hold N ===")
for d in [0, 1, 2]:
    p = load_hp(d, 1000) if d == 2 else load_hp(d)
    label = f"Day {d}" + (" 1k" if d == 2 else "")
    s17 = p["spread"]==17
    if s17.sum() == 0: continue
    print(f"--- {label} ---")
    for thr in [9990, 9995, 10000]:
        for hold in [50, 100]:
            mask = s17 & (p["mid_price"] <= thr)
            idx = p.index[mask]
            valid = idx[idx + hold < len(p)]
            if len(valid)==0: continue
            entry_ask = p.loc[valid, "ask_price_1"].values
            exit_mid = p.loc[valid + hold, "mid_price"].values
            pnl = (exit_mid - entry_ask).mean() * 200 * len(valid)
            print(f"  s=17 mid<={thr} LONG hold={hold}: n={len(valid)} EV=${pnl:+.0f}")

# Currently r3_v11 spread==17 SHORT: enter at bid (passive sell), exit at ask (cross).
# Variant: keep that, but also LONG on spread==17 + mid<=9990?
# More importantly: r3_v11 uses spread==17 + mid > 10010. Let's test other thresholds.
print("\n=== s=17 SHORT trigger thresholds + exit thresholds (single-shot, Day 2 1k) ===")
def gigashort_sim(p, thr_in, thr_out, lot=200):
    pos = 0; entry_px = 0; total_pnl = 0; trades = []
    for i, row in p.iterrows():
        if pos == 0 and row["spread"] == 17 and row["mid_price"] > thr_in:
            entry_px = row["bid_price_1"]
            pos = -lot
        elif pos < 0 and row["mid_price"] < thr_out:
            exit_px = row["ask_price_1"]
            pnl = (entry_px - exit_px) * lot
            total_pnl += pnl
            trades.append((i, entry_px, exit_px, pnl))
            pos = 0
    if pos < 0:
        exit_px = p.iloc[-1]["mid_price"]
        pnl = (entry_px - exit_px) * lot
        total_pnl += pnl
    return total_pnl, trades

for d in [0, 1, 2]:
    p = load_hp(d, 1000) if d == 2 else load_hp(d)
    label = f"Day {d}" + (" 1k" if d == 2 else " full")
    print(f"--- {label} ---")
    for thr_in, thr_out in [(10010, 9998), (10005, 9998), (10005, 10000), (10000, 9998), (10010, 10000), (10015, 9998)]:
        pnl, tr = gigashort_sim(p, thr_in, thr_out)
        if tr:
            print(f"  in>{thr_in} out<{thr_out}: trades={len(tr)} EV=${pnl:+.0f}")

# Mirror for LONG on spread=17 dump
print("\n=== s=17 LONG mirror: spread=17 + mid<=THR_IN, exit mid>=THR_OUT ===")
def gigalong_sim(p, thr_in, thr_out, lot=200):
    pos = 0; entry_px = 0; total_pnl = 0; trades = []
    for i, row in p.iterrows():
        if pos == 0 and row["spread"] == 17 and row["mid_price"] <= thr_in:
            entry_px = row["ask_price_1"]
            pos = +lot
        elif pos > 0 and row["mid_price"] > thr_out:
            exit_px = row["bid_price_1"]
            pnl = (exit_px - entry_px) * lot
            total_pnl += pnl
            trades.append((i, entry_px, exit_px, pnl))
            pos = 0
    if pos > 0:
        exit_px = p.iloc[-1]["mid_price"]
        pnl = (exit_px - entry_px) * lot
        total_pnl += pnl
    return total_pnl, trades

for d in [0, 1, 2]:
    p = load_hp(d, 1000) if d == 2 else load_hp(d)
    label = f"Day {d}" + (" 1k" if d == 2 else " full")
    print(f"--- {label} ---")
    for thr_in, thr_out in [(9990, 10002), (9985, 10000), (9990, 10000), (9995, 10005), (9985, 9995)]:
        pnl, tr = gigalong_sim(p, thr_in, thr_out)
        if tr:
            print(f"  in<{thr_in} out>{thr_out}: trades={len(tr)} EV=${pnl:+.0f}")

# Combined long+short on s=17
print("\n=== Combined: s=17 SHORT (mid>THR_HI) + s=17 LONG (mid<THR_LO), exit on cross ===")
def combined_sim(p, lo, hi, exit_lo, exit_hi, lot=200):
    pos = 0; entry_px = 0; total_pnl = 0; trades = []
    for i, row in p.iterrows():
        if pos == 0 and row["spread"] == 17:
            if row["mid_price"] > hi:
                entry_px = row["bid_price_1"]; pos = -lot
            elif row["mid_price"] <= lo:
                entry_px = row["ask_price_1"]; pos = +lot
        elif pos < 0 and row["mid_price"] < exit_lo:
            pnl = (entry_px - row["ask_price_1"]) * lot
            total_pnl += pnl; trades.append(("SHORT", i, pnl)); pos = 0
        elif pos > 0 and row["mid_price"] > exit_hi:
            pnl = (row["bid_price_1"] - entry_px) * lot
            total_pnl += pnl; trades.append(("LONG", i, pnl)); pos = 0
    if pos != 0:
        if pos < 0:
            pnl = (entry_px - p.iloc[-1]["mid_price"]) * lot
        else:
            pnl = (p.iloc[-1]["mid_price"] - entry_px) * lot
        total_pnl += pnl; trades.append(("EOD", len(p)-1, pnl))
    return total_pnl, trades

for d in [0, 1, 2]:
    p = load_hp(d, 1000) if d == 2 else load_hp(d)
    label = f"Day {d}" + (" 1k" if d == 2 else " full")
    print(f"--- {label} ---")
    for lo, hi, el, eh in [(9990, 10010, 9998, 10002), (9985, 10010, 9998, 10002), (9990, 10005, 9998, 10000), (9995, 10010, 10000, 10000)]:
        pnl, tr = combined_sim(p, lo, hi, el, eh)
        print(f"  s=17 LONG<={lo}, SHORT>{hi}, exits {el}/{eh}: trades={len(tr)} EV=${pnl:+.0f}")
