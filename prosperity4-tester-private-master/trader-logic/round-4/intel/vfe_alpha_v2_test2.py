#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test better long-reversal: require crash already happened AND momentum reversing.

Signal:
  drop_50 = mid - mid_50_ago   (negative during crash)
  if drop_50 was <= -3 in the past 100 ticks (crash occurred)
  AND now vel_20 = mid - mid_20_ago > +1 (momentum reversed up)
  AND not already long → BUY.
"""
import csv
ROOT = "C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4"

def load(day):
    path = f"{ROOT}/prices_round_4_day_{day}.csv"
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["product"] != "VELVETFRUIT_EXTRACT": continue
            rows.append((int(row["timestamp"]), float(row["mid_price"]),
                         int(row["bid_price_1"]) if row["bid_price_1"] else None,
                         int(row["ask_price_1"]) if row["ask_price_1"] else None))
    rows.sort(); return rows


def sim(rows, drop_thresh=-5, vel_reverse=2, hold=100, tp=8, sl=10, size=200, cooldown=300, recent_crash_window=100):
    mids = [r[1] for r in rows]
    asks = [r[3] if r[3] else r[1]+1 for r in rows]
    bids = [r[2] if r[2] else r[1]-1 for r in rows]
    in_pos = False; entry_idx = entry_px = None; cooldown_until = -1; pnl = 0; trades = []
    for i in range(200, len(rows) - 1):
        # check recent crash within last `recent_crash_window` ticks
        recent_min_drop = min(mids[i-50-j] - mids[i-100-j] for j in range(recent_crash_window) if i-100-j >= 0) if i >= 100 else 0
        vel20 = mids[i] - mids[i-20]
        if not in_pos:
            if i < cooldown_until: continue
            if recent_min_drop <= drop_thresh and vel20 >= vel_reverse:
                entry_px = asks[i]; entry_idx = i; in_pos = True
        else:
            held = i - entry_idx
            mtm = (mids[i] - entry_px) * size
            if held >= hold or mtm >= tp*size or mtm <= -sl*size:
                exit_px = bids[i]
                pnl += (exit_px - entry_px) * size
                trades.append((entry_idx, entry_px, i, exit_px, exit_px - entry_px))
                in_pos = False; cooldown_until = i + cooldown
    return pnl, trades


for day in (1, 2, 3):
    rows = load(day)
    for params in [
        dict(drop_thresh=-5, vel_reverse=2, hold=100, tp=8, sl=10, cooldown=300),
        dict(drop_thresh=-7, vel_reverse=3, hold=150, tp=10, sl=8, cooldown=500),
        dict(drop_thresh=-10, vel_reverse=3, hold=200, tp=12, sl=8, cooldown=500),
        dict(drop_thresh=-5, vel_reverse=1, hold=50,  tp=5, sl=5,  cooldown=100),
    ]:
        pnl, trades = sim(rows, **params)
        print(f"day{day} {params}: PnL=${pnl:+,.0f} trades={len(trades)}")
    print()

# 3-day total for best params
print("=== TOTAL 3-DAY by config ===")
configs = [
    dict(drop_thresh=-5, vel_reverse=2, hold=100, tp=8, sl=10, cooldown=300),
    dict(drop_thresh=-7, vel_reverse=3, hold=150, tp=10, sl=8, cooldown=500),
    dict(drop_thresh=-10, vel_reverse=3, hold=200, tp=12, sl=8, cooldown=500),
    dict(drop_thresh=-5, vel_reverse=1, hold=50,  tp=5,  sl=5,  cooldown=100),
    dict(drop_thresh=-8, vel_reverse=4, hold=200, tp=12, sl=6, cooldown=500),
]
for params in configs:
    total = 0; nt = 0
    for d in (1, 2, 3):
        rows = load(d); p, t = sim(rows, **params); total += p; nt += len(t)
    print(f"  {params}: 3-day=${total:+,.0f} trades={nt}")
