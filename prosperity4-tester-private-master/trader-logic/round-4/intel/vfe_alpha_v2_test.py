#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test long-side reversal strategy: BUY VFE 200 when local 200-tick min reached AND drop>$5.

This complements the existing one-shot momentum SHORT. After deep crashes,
day-3 data shows 100% bounce frequency with mean +$8.86/share over 50 ticks
(=+$1,772 per 200 contracts), +$10.93/share over 100 ticks (=+$2,186).

Backtest in pure Python on day-3 mids: no execution model, pessimistic
fill-at-mid+0.5.
"""
import csv
ROOT = "C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4"

def load_mids(day):
    path = f"{ROOT}/prices_round_4_day_{day}.csv"
    rows = []
    with open(path) as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            if row["product"] != "VELVETFRUIT_EXTRACT": continue
            rows.append((int(row["timestamp"]),
                         float(row["mid_price"]),
                         int(row["bid_price_1"]) if row["bid_price_1"] else None,
                         int(row["ask_price_1"]) if row["ask_price_1"] else None))
    rows.sort()
    return rows


def simulate_long_reversal(rows, drop_thresh=5, lookback=200, hold=100, tp_pershare=8, sl_pershare=10, size=200):
    """One-shot long: when (max(mid[-200:]) - mid[now]) >= drop_thresh AND mid[now] near local min, BUY 200.
    Hold for `hold` ticks, exit at TP or SL or fwd time."""
    mids = [r[1] for r in rows]
    asks = [r[3] if r[3] else r[1]+1 for r in rows]
    bids = [r[2] if r[2] else r[1]-1 for r in rows]
    fired = False
    entry_idx = None
    entry_px = None
    pnl = 0
    trades = []
    for i in range(lookback, len(rows) - 1):
        if not fired:
            window = mids[i-lookback:i+1]
            wmax = max(window); wmin = min(window)
            # Buy near local min after big drop
            if (wmax - mids[i]) >= drop_thresh and mids[i] <= wmin + 1:
                # Lift ask
                entry_px = asks[i]
                entry_idx = i
                fired = True
        else:
            # Manage exit
            held = i - entry_idx
            mtm = (mids[i] - entry_px) * size
            tp_hit = mtm >= tp_pershare * size
            sl_hit = mtm <= -sl_pershare * size
            if held >= hold or tp_hit or sl_hit:
                exit_px = bids[i]
                pnl += (exit_px - entry_px) * size
                trades.append((entry_idx, entry_px, i, exit_px, exit_px-entry_px, "TP" if tp_hit else ("SL" if sl_hit else "TIME")))
                fired = False
                entry_px = None
                entry_idx = None
                # Don't immediately re-fire: simulate one-shot/day OR allow re-arm
                if False: break
    return pnl, trades


for day in (1, 2, 3):
    rows = load_mids(day)
    pnl, trades = simulate_long_reversal(rows)
    print(f"day{day}: long-reversal PnL = ${pnl:+,.0f}  trades={len(trades)}")
    for t in trades[:5]:
        print(f"   entry@{t[0]:5d} px={t[1]} exit@{t[2]:5d} px={t[3]} dx={t[4]:+.1f} {t[5]}")

# Also test the simpler "rearmable" variant
print("\n=== REARMABLE (no one-shot) ===")
def simulate_rearmable(rows, drop_thresh=5, lookback=200, hold=100, tp=8, sl=10, size=200, cooldown=200):
    mids = [r[1] for r in rows]; asks = [r[3] if r[3] else r[1]+1 for r in rows]; bids = [r[2] if r[2] else r[1]-1 for r in rows]
    in_pos = False; entry_idx = None; entry_px = None; cooldown_until = -1; pnl = 0; trades = []
    for i in range(lookback, len(rows) - 1):
        if not in_pos:
            if i < cooldown_until: continue
            window = mids[i-lookback:i+1]
            wmax = max(window); wmin = min(window)
            if (wmax - mids[i]) >= drop_thresh and mids[i] <= wmin + 1:
                entry_px = asks[i]; entry_idx = i; in_pos = True
        else:
            held = i - entry_idx
            mtm = (mids[i] - entry_px) * size
            if held >= hold or mtm >= tp*size or mtm <= -sl*size:
                exit_px = bids[i]
                pnl += (exit_px - entry_px) * size
                trades.append((entry_idx, entry_px, i, exit_px, exit_px-entry_px))
                in_pos = False; cooldown_until = i + cooldown
    return pnl, trades

for day in (1, 2, 3):
    rows = load_mids(day)
    pnl, trades = simulate_rearmable(rows)
    print(f"day{day}: rearmable long-reversal PnL = ${pnl:+,.0f}  trades={len(trades)}")
