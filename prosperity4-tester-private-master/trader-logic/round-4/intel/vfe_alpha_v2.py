#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""VFE alpha hunt v2: deep dive into Wall-Mid MM crash failure on day 3.

Mandate items:
1) Why does Wall-Mid MM lose -$5.9k on day 3 10k? Decompose loss source.
2) Crash detection signal beyond velocity-50.
3) Long-side reversal alpha after crash.
4) Concrete code recommendation.

Outputs printed to stdout. Statistics: t-stats, IC, forward-PnL signs.
"""
import csv
import math
import os
from collections import defaultdict
from statistics import mean, median, pstdev

ROOT = "C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4"


def load_vfe(day):
    path = f"{ROOT}/prices_round_4_day_{day}.csv"
    rows = []
    with open(path, "r") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            if row["product"] != "VELVETFRUIT_EXTRACT":
                continue
            t = int(row["timestamp"])
            mid = float(row["mid_price"])
            bp1 = int(row["bid_price_1"]) if row["bid_price_1"] else None
            ap1 = int(row["ask_price_1"]) if row["ask_price_1"] else None
            bv1 = int(row["bid_volume_1"]) if row["bid_volume_1"] else 0
            av1 = int(row["ask_volume_1"]) if row["ask_volume_1"] else 0
            # Wall mid (highest-volume) levels
            bids = []
            asks = []
            for i in (1, 2, 3):
                bp = row.get(f"bid_price_{i}")
                bv = row.get(f"bid_volume_{i}")
                ap = row.get(f"ask_price_{i}")
                av = row.get(f"ask_volume_{i}")
                if bp:
                    bids.append((int(bp), int(bv)))
                if ap:
                    asks.append((int(ap), int(av)))
            wall_b = max(bids, key=lambda x: x[1])[0] if bids else None
            wall_a = min(asks, key=lambda x: x[1])[0] if asks else None
            wall_mid = 0.5 * (wall_b + wall_a) if wall_b and wall_a else mid
            obi = (bv1 - av1) / max(bv1 + av1, 1)
            spread = (ap1 - bp1) if (ap1 is not None and bp1 is not None) else None
            rows.append({
                "t": t, "mid": mid, "wall_mid": wall_mid,
                "bp1": bp1, "ap1": ap1, "bv1": bv1, "av1": av1,
                "obi": obi, "spread": spread,
            })
    rows.sort(key=lambda x: x["t"])
    return rows


def fwd_return(rows, k):
    out = []
    for i in range(len(rows) - k):
        out.append(rows[i + k]["mid"] - rows[i]["mid"])
    return out


def corr(a, b):
    n = min(len(a), len(b))
    if n < 3: return 0
    a = a[:n]; b = b[:n]
    ma = mean(a); mb = mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0 or db == 0: return 0
    return num / (da * db)


def t_stat(c, n):
    if abs(c) >= 0.999: return 99
    return c * math.sqrt(max(n - 2, 1)) / math.sqrt(1 - c * c)


# ── 1. Day 3 crash mechanic decomposition ──
print("=" * 70)
print("PART 1: Day 3 VFE WALL-MID MM CRASH DECOMPOSITION")
print("=" * 70)
d3 = load_vfe(3)
print(f"day3 rows={len(d3)} mid_open={d3[0]['mid']} mid_close={d3[-1]['mid']} drift={d3[-1]['mid']-d3[0]['mid']:.1f}")
mids3 = [r["mid"] for r in d3]
walls3 = [r["wall_mid"] for r in d3]
diffs = [w - m for w, m in zip(walls3, mids3)]
print(f"  wall_mid - simple_mid: mean={mean(diffs):+.3f} median={median(diffs):+.3f} stdev={pstdev(diffs):.3f}")
neg_count = sum(1 for d in diffs if d < -0.5)
pos_count = sum(1 for d in diffs if d > 0.5)
print(f"  wall < mid by >0.5 ticks: {neg_count} ({100*neg_count/len(diffs):.1f}%)  wall > mid: {pos_count} ({100*pos_count/len(diffs):.1f}%)")

# Forward 1-tick correlation: mid - wall_mid → forecast next mid?
fwd1 = fwd_return(d3, 1)
fwd5 = fwd_return(d3, 5)
fwd20 = fwd_return(d3, 20)
fwd50 = fwd_return(d3, 50)

# Wall-Mid lag signal: when wall>mid (book heavy on bid side), is mid going up?
sig_wall_minus_mid = [w - m for w, m in zip(walls3[:-1], mids3[:-1])]
print(f"\n  IC(wall-mid, fwd1): {corr(sig_wall_minus_mid[:len(fwd1)], fwd1):.4f}")
print(f"  IC(wall-mid, fwd5): {corr(sig_wall_minus_mid[:len(fwd5)], fwd5):.4f}")
print(f"  IC(wall-mid, fwd20): {corr(sig_wall_minus_mid[:len(fwd20)], fwd20):.4f}")
print(f"  IC(wall-mid, fwd50): {corr(sig_wall_minus_mid[:len(fwd50)], fwd50):.4f}")

# Wall-Mid stability test: count Wall-Mid jumps >2
wall_jumps = sum(1 for i in range(1, len(walls3)) if abs(walls3[i] - walls3[i-1]) > 2)
mid_jumps = sum(1 for i in range(1, len(mids3)) if abs(mids3[i] - mids3[i-1]) > 2)
print(f"\n  Wall-Mid >2tick jumps day3: {wall_jumps} ({100*wall_jumps/len(walls3):.2f}%)")
print(f"  Mid >2tick jumps day3: {mid_jumps} ({100*mid_jumps/len(mids3):.2f}%)")

# Decomposing crash periods (mid drop >$3 in 50 ticks)
crash_idx = []
for i in range(50, len(d3)):
    if mids3[i] - mids3[i-50] <= -3:
        crash_idx.append(i)
print(f"\n  Crash signals (mid_drop_50<=-3): {len(crash_idx)} ticks")
# Forward 50-tick PnL of holding LONG one share (=Wall-Mid MM is implicitly long-biased on dip)
# IF book is asymmetric (heavy bids), wall-mid > mid → MM quotes ABOVE simple mid → ask too high, bid too high
# → during crash, our bid catches falling knife.
adverse_fills = 0
favorable_fills = 0
for i in crash_idx:
    if i + 50 < len(d3):
        if mids3[i + 50] < mids3[i]: adverse_fills += 1  # mid kept dropping
        else: favorable_fills += 1
print(f"  Of those, mid kept dropping over next 50 ticks: {adverse_fills} ({100*adverse_fills/max(len(crash_idx),1):.1f}%)")

# ── 2. Crash detection signals beyond velocity-50 ──
print("\n" + "=" * 70)
print("PART 2: ALTERNATIVE CRASH DETECTION SIGNALS (forward t-stats)")
print("=" * 70)
all_d = []
for d in (1, 2, 3):
    all_d.extend(load_vfe(d))
N = len(all_d)
mids = [r["mid"] for r in all_d]
obis = [r["obi"] for r in all_d]
spreads = [r["spread"] if r["spread"] else 5 for r in all_d]
walls = [r["wall_mid"] for r in all_d]

for K in (50, 100, 200, 500):
    fwdK = [mids[i + K] - mids[i] for i in range(N - K)]
    # Velocity-K
    vel = [mids[i] - mids[i - 50] if i >= 50 else 0 for i in range(N - K)]
    c = corr(vel, fwdK); ts = t_stat(c, len(vel))
    print(f"  velocity-50 → fwd{K}: IC={c:+.4f} t={ts:+.2f} (N={len(vel)})")
    # OBI
    c = corr(obis[:N-K], fwdK); ts = t_stat(c, N-K)
    print(f"  OBI → fwd{K}: IC={c:+.4f} t={ts:+.2f}")
    # spread
    c = corr(spreads[:N-K], fwdK); ts = t_stat(c, N-K)
    print(f"  spread → fwd{K}: IC={c:+.4f} t={ts:+.2f}")
    # wall_minus_mid
    wm = [walls[i] - mids[i] for i in range(N - K)]
    c = corr(wm, fwdK); ts = t_stat(c, N-K)
    print(f"  wall-mid → fwd{K}: IC={c:+.4f} t={ts:+.2f}")
    # acceleration: vel-50 - vel-100
    acc = [(mids[i] - mids[i - 50]) - (mids[i - 50] - mids[i - 100]) if i >= 100 else 0 for i in range(N - K)]
    c = corr(acc, fwdK); ts = t_stat(c, N-K)
    print(f"  accel(50,100) → fwd{K}: IC={c:+.4f} t={ts:+.2f}")
    print()

# ── 3. Day 3 specific: long-side reversal alpha after crash? ──
print("=" * 70)
print("PART 3: POST-CRASH BOUNCE PROBABILITY (day 3)")
print("=" * 70)
# Define crash trough as local min of mid in window of 200 ticks
mids3 = [r["mid"] for r in d3]
trough_idx = []
W = 200
for i in range(W, len(d3) - W):
    if mids3[i] == min(mids3[i-W:i+W+1]):
        trough_idx.append(i)
# Filter to actual deep troughs (>$5 below 200-tick max)
trough_idx = [i for i in trough_idx if max(mids3[i-W:i]) - mids3[i] > 5]
print(f"  Day3 deep troughs detected: {len(trough_idx)} (indices ~{trough_idx[:10]}...)")
if trough_idx:
    bounces = []
    for i in trough_idx:
        for fwd in (50, 100, 200, 500, 1000):
            if i + fwd < len(d3):
                bounces.append((fwd, mids3[i + fwd] - mids3[i]))
    by_fwd = defaultdict(list)
    for f, b in bounces: by_fwd[f].append(b)
    for f in (50, 100, 200, 500, 1000):
        bs = by_fwd[f]
        if bs:
            print(f"  fwd{f}: mean_bounce={mean(bs):+.2f} median={median(bs):+.2f} pos_frac={sum(1 for b in bs if b>0)/len(bs):.2f} N={len(bs)}")

# ── 4. Day 3 mid behavior: V-shape or staircase? ──
print(f"\n  Day3 cumulative drift trajectory (every 1000 ticks):")
for k in range(0, len(d3), 1000):
    print(f"    t={d3[k]['t']:>7} mid={d3[k]['mid']:.1f}")
print(f"    t={d3[-1]['t']:>7} mid={d3[-1]['mid']:.1f}")

# ── 5. Quick alt-FV test on day 3 ──
print("\n" + "=" * 70)
print("PART 4: ALT FV BEHAVIOR DURING DAY 3 CRASH")
print("=" * 70)
# Compare wall-mid vs ema(mid, alpha=0.05) vs simple_mid lag for adverse-selection metric
# Adverse selection: did our quote (mid+1) get hit, then mid moved away from us by >2 in next 5 ticks?
adv_wall = 0; adv_simple = 0; adv_ema = 0
ema = mids3[0]; alpha = 0.05
for i in range(1, len(d3) - 5):
    ema = alpha * mids3[i] + (1 - alpha) * ema
    fv_wall = walls3[i]; fv_simple = mids3[i]; fv_ema = ema
    fwd5 = mids3[i + 5] - mids3[i]
    # If we posted ask at fv+1 and it filled (i.e. someone took at fv+1 < ap1)... approximate by
    # checking if fv+1 < ap1[i+1] -- but for adverse sel we just check sign vs fwd5
    if fv_wall > mids3[i] and fwd5 < -1: adv_wall += 1
    if fv_simple > mids3[i] and fwd5 < -1: adv_simple += 1
    if fv_ema > mids3[i] and fwd5 < -1: adv_ema += 1
print(f"  Day3 quotes-ABOVE-mid that got adverse fwd5 move (proxy for stale-FV cost):")
print(f"    wall_mid: {adv_wall} | simple_mid: {adv_simple} | ema(.05): {adv_ema}")
