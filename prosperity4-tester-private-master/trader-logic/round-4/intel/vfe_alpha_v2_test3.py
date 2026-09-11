#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test variants of the existing one-shot momentum SHORT.
Current: enter when (mid - mid_50_ago) <= -3, exit at TP=+$2k or SL=-$3k or EOD.

Variants:
  A) Larger drop threshold for higher-quality entries (-5, -8)
  B) Re-armable (multi-shot)
  C) Trailing stop on profit
  D) Time-based exit instead of TP/SL
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


def sim_short(rows, drop_thresh=-3, lookback=50, tp=10, sl=15, size=200,
              one_shot=True, cooldown=500, trail=None, time_exit=None):
    """Short when mid drops by drop_thresh over lookback. Exit at TP/SL/trailing/time/EOD."""
    mids = [r[1] for r in rows]
    asks = [r[3] if r[3] else r[1]+1 for r in rows]
    bids = [r[2] if r[2] else r[1]-1 for r in rows]
    in_pos = False; entry_idx = entry_px = None; cooldown_until = -1
    pnl = 0; trades = []
    fired_count = 0
    peak_profit = 0
    for i in range(lookback + 1, len(rows) - 1):
        if not in_pos:
            if i < cooldown_until: continue
            if one_shot and fired_count >= 1: continue
            vel = mids[i] - mids[i - lookback]
            if vel <= drop_thresh:
                entry_px = bids[i]; entry_idx = i; in_pos = True; peak_profit = 0
        else:
            held = i - entry_idx
            mtm_per = entry_px - mids[i]  # short profit per share
            mtm = mtm_per * size
            peak_profit = max(peak_profit, mtm)
            cover = False; reason = ""
            if mtm >= tp * size: cover, reason = True, "TP"
            elif mtm <= -sl * size: cover, reason = True, "SL"
            elif trail is not None and peak_profit > 0 and (peak_profit - mtm) >= trail * size:
                cover, reason = True, "TRAIL"
            elif time_exit is not None and held >= time_exit:
                cover, reason = True, "TIME"
            if cover:
                exit_px = asks[i]
                pnl += (entry_px - exit_px) * size
                trades.append((entry_idx, entry_px, i, exit_px, entry_px - exit_px, reason))
                in_pos = False; cooldown_until = i + cooldown; fired_count += 1
    if in_pos:  # close at EOD
        exit_px = asks[-1]
        pnl += (entry_px - exit_px) * size
        trades.append((entry_idx, entry_px, len(rows)-1, exit_px, entry_px-exit_px, "EOD"))
    return pnl, trades


configs = [
    ("BASELINE v2 (one-shot, drop=-3, TP=10, SL=15)", dict(drop_thresh=-3, tp=10, sl=15, one_shot=True)),
    ("Wider drop -5",                                  dict(drop_thresh=-5, tp=10, sl=15, one_shot=True)),
    ("Wider drop -8",                                  dict(drop_thresh=-8, tp=10, sl=15, one_shot=True)),
    ("REARMABLE drop=-3 cd=500",                       dict(drop_thresh=-3, tp=10, sl=15, one_shot=False, cooldown=500)),
    ("REARMABLE drop=-5 cd=500",                       dict(drop_thresh=-5, tp=10, sl=15, one_shot=False, cooldown=500)),
    ("REARMABLE drop=-5 cd=1000",                      dict(drop_thresh=-5, tp=10, sl=15, one_shot=False, cooldown=1000)),
    ("REARMABLE drop=-7 cd=1000",                      dict(drop_thresh=-7, tp=10, sl=15, one_shot=False, cooldown=1000)),
    ("REARMABLE drop=-7 cd=1000 trail=5",              dict(drop_thresh=-7, tp=10, sl=15, one_shot=False, cooldown=1000, trail=5)),
    ("REARMABLE drop=-7 cd=1000 trail=3",              dict(drop_thresh=-7, tp=10, sl=15, one_shot=False, cooldown=1000, trail=3)),
    ("REARMABLE drop=-5 trail=5",                      dict(drop_thresh=-5, tp=15, sl=15, one_shot=False, cooldown=500, trail=5)),
    ("REARMABLE drop=-5 trail=3",                      dict(drop_thresh=-5, tp=15, sl=15, one_shot=False, cooldown=500, trail=3)),
    ("ONE-SHOT drop=-5 trail=3",                       dict(drop_thresh=-5, tp=15, sl=15, one_shot=True, trail=3)),
    ("ONE-SHOT drop=-3 time=300",                      dict(drop_thresh=-3, tp=999, sl=999, one_shot=True, time_exit=300)),
    ("ONE-SHOT drop=-3 time=500",                      dict(drop_thresh=-3, tp=999, sl=999, one_shot=True, time_exit=500)),
    ("ONE-SHOT drop=-3 trail=3",                       dict(drop_thresh=-3, tp=15, sl=15, one_shot=True, trail=3)),
    ("ONE-SHOT drop=-3 trail=5",                       dict(drop_thresh=-3, tp=15, sl=15, one_shot=True, trail=5)),
]

# 1k window each day (matches IMC probe)
print("=== 1K WINDOW (first 1000 ticks of each day) ===")
for name, params in configs:
    totals = []
    for d in (1, 2, 3):
        rows = load(d)[:1000]
        p, _ = sim_short(rows, **params); totals.append(p)
    print(f"  d1={totals[0]:+8,.0f}  d2={totals[1]:+8,.0f}  d3={totals[2]:+8,.0f}  TOT={sum(totals):+9,.0f}  | {name}")

print("\n=== 10K (full day) ===")
for name, params in configs:
    totals = []
    for d in (1, 2, 3):
        rows = load(d)
        p, _ = sim_short(rows, **params); totals.append(p)
    print(f"  d1={totals[0]:+8,.0f}  d2={totals[1]:+8,.0f}  d3={totals[2]:+8,.0f}  TOT={sum(totals):+9,.0f}  | {name}")
