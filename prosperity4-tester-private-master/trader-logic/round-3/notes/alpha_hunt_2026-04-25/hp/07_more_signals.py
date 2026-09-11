"""More signals: LONG side mean-rev, narrow spread refinement, depth thinning, time-of-day, regime detection."""
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

def single_shot_sim(p, entry_pred, exit_pred, side, lot=200, label=""):
    """Single position: enter when entry_pred(row), exit when exit_pred(row, entry_px)."""
    pos = 0; entry_px = 0; total_pnl = 0; trades = []
    for i, row in p.iterrows():
        if pos == 0 and entry_pred(row, i):
            entry_px = row["ask_price_1"] if side == +1 else row["bid_price_1"]
            pos = side * lot
        elif pos != 0 and exit_pred(row, entry_px, i):
            exit_px = row["bid_price_1"] if side == +1 else row["ask_price_1"]
            pnl = side * (exit_px - entry_px) * lot
            total_pnl += pnl
            trades.append((i, entry_px, exit_px, pnl))
            pos = 0
    if pos != 0:
        exit_px = p.iloc[-1]["mid_price"]
        pnl = side * (exit_px - entry_px) * lot
        total_pnl += pnl
        trades.append((len(p)-1, entry_px, exit_px, pnl))
    return total_pnl, trades

print("=== Single-shot LONG: mid<=THR_IN, exit when mid>=THR_OUT ===")
for d in [0, 1, 2]:
    p = load_hp(d, 1000) if d == 2 else load_hp(d)
    label = f"Day {d}" + (" 1k" if d == 2 else " full")
    print(f"--- {label} ---")
    for thr_in, thr_out in [(9970, 9990), (9970, 10000), (9960, 9985), (9950, 9980)]:
        pnl, trades = single_shot_sim(p,
            lambda r, i: r["mid_price"] <= thr_in,
            lambda r, ep, i: r["mid_price"] >= thr_out,
            +1)
        print(f"  enter<={thr_in} exit>={thr_out}: trades={len(trades)} EV=${pnl:+.0f}")

# Check spread=17 with mid<10010 (LONG side)
print("\n=== Single-shot LONG: spread==17 AND mid<thr -> LONG, exit mid>=exit_thr ===")
for d in [0, 1, 2]:
    p = load_hp(d, 1000) if d == 2 else load_hp(d)
    label = f"Day {d}" + (" 1k" if d == 2 else " full")
    print(f"--- {label} ---")
    for thr_in, thr_out in [(9990, 9998), (9985, 9995), (9980, 9995), (9990, 10005)]:
        pnl, trades = single_shot_sim(p,
            lambda r, i: r["spread"] == 17 and r["mid_price"] < thr_in,
            lambda r, ep, i: r["mid_price"] >= thr_out,
            +1)
        if trades:
            print(f"  spread==17 + mid<{thr_in} exit>={thr_out}: trades={len(trades)} EV=${pnl:+.0f}")

# Spread sequence pattern: spread=15 then 17 - is that an alarm?
print("\n=== Spread state TRANSITIONS - 16->17, 16->15, 7-8-9 sequences ===")
for d in [0, 1, 2]:
    p = load_hp(d, 1000) if d == 2 else load_hp(d)
    p["spread_lag"] = p["spread"].shift(1)
    p["fwd20"] = p["mid_price"].shift(-20) - p["mid_price"]
    label = f"Day {d}" + (" 1k" if d == 2 else " full")
    print(f"--- {label} ---")
    for s_prev, s_now in [(16, 17), (16, 15), (15, 17), (16, 7), (16, 9), (8, 7), (8, 9)]:
        m = (p["spread_lag"] == s_prev) & (p["spread"] == s_now)
        n = m.sum()
        if n < 3: continue
        f20 = p.loc[m, "fwd20"].mean()
        print(f"  {s_prev}->{s_now}: n={n:4d} fwd20={f20:+.2f}")

# Time-of-day buckets
print("\n=== Time-of-day buckets (1k chunks) - mid drift ===")
for d in [0, 1, 2]:
    p = load_hp(d)
    p["bucket"] = p.index // 1000
    print(f"  Day {d}:")
    for b in range(10):
        sub = p[p["bucket"] == b]
        if len(sub) == 0: continue
        m_open = sub["mid_price"].iloc[0]
        m_close = sub["mid_price"].iloc[-1]
        spread17 = (sub["spread"]==17).sum()
        narrow = (sub["spread"].isin([7,8,9])).sum()
        print(f"    bucket{b}: open={m_open:.0f} close={m_close:.0f} d={m_close-m_open:+.0f} | s=17:{spread17} narrow:{narrow}")
