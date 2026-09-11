#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Diagnose: why is day-3 VFE -$3,709 in v2 BT? Decompose Wall-Mid MM PnL during sustained drift."""
import csv
ROOT = "C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4"

def load(day):
    path = f"{ROOT}/prices_round_4_day_{day}.csv"
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["product"] != "VELVETFRUIT_EXTRACT": continue
            rows.append((int(row["timestamp"]), float(row["mid_price"]),
                         int(row["bid_price_1"]), int(row["ask_price_1"]),
                         int(row["bid_volume_1"]), int(row["ask_volume_1"])))
    rows.sort(); return rows

# Day-3 sustained drift analysis
d3 = load(3)
print(f"day3 VFE drift trajectory:")
mids = [r[1] for r in d3]
# Per-1k-tick drift
print(f"  per-1k-tick drift:")
for k in range(0, len(d3), 1000):
    end = min(k + 1000, len(d3) - 1)
    print(f"   t={d3[k][0]:>7}-{d3[end][0]:>7}: mid {d3[k][1]:.1f} -> {d3[end][1]:.1f} (Δ={d3[end][1]-d3[k][1]:+.1f})")

# Total sum of |consecutive drops|
total_dn = sum(max(0, mids[i] - mids[i+1]) for i in range(len(mids) - 1))
total_up = sum(max(0, mids[i+1] - mids[i]) for i in range(len(mids) - 1))
print(f"\n  Total down-moves: {total_dn:.1f}, total up-moves: {total_up:.1f}")
print(f"  Net drift: {mids[-1] - mids[0]:.1f}")
print(f"  Round-trip volume (sum |moves|): {total_dn + total_up:.1f}")

# How often is drift sustained — count 1k-tick windows where drift < -10?
windows_sustained = 0
for i in range(0, len(mids) - 1000, 100):
    if mids[i + 1000] - mids[i] < -10: windows_sustained += 1
print(f"  1k-windows with drift < -10: {windows_sustained} (at 100-tick step)")
windows_sustained_d2 = 0
d2 = load(2); mids2 = [r[1] for r in d2]
for i in range(0, len(mids2) - 1000, 100):
    if mids2[i + 1000] - mids2[i] < -10: windows_sustained_d2 += 1
print(f"  Day 2 same metric: {windows_sustained_d2}")
d1 = load(1); mids1 = [r[1] for r in d1]
windows_sustained_d1 = 0
for i in range(0, len(mids1) - 1000, 100):
    if mids1[i + 1000] - mids1[i] < -10: windows_sustained_d1 += 1
print(f"  Day 1 same metric: {windows_sustained_d1}")

# Volatility per day
def realized_vol(mids):
    rets = [mids[i+1] - mids[i] for i in range(len(mids) - 1)]
    n = len(rets)
    m = sum(rets) / n
    var = sum((r - m) ** 2 for r in rets) / n
    return var ** 0.5
print(f"\n  Realized 1-tick vol: d1={realized_vol(mids1):.3f} d2={realized_vol(mids2):.3f} d3={realized_vol(mids):.3f}")

# Auto-correlation (lag 1)
def ac1(mids):
    rets = [mids[i+1] - mids[i] for i in range(len(mids) - 1)]
    n = len(rets); m = sum(rets) / n
    num = sum((rets[i] - m) * (rets[i+1] - m) for i in range(n - 1))
    den = sum((r - m) ** 2 for r in rets)
    return num / den if den else 0

print(f"  AC(1) of returns:    d1={ac1(mids1):.4f} d2={ac1(mids2):.4f} d3={ac1(mids):.4f}")
