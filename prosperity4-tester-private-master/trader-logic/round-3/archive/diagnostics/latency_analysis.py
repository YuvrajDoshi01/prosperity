#!/usr/bin/env python3
"""Microstructure latency: does underlying lead options?"""

import csv, os, math
from collections import defaultdict
from statistics import mean, stdev

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
DAYS = [0, 1, 2]
MAX_LAG = 20  # ticks (each tick = 100ms, so 20 ticks = 2 seconds)

def load_prices(day):
    path = os.path.join(DATA_DIR, f'prices_round_3_day_{day}.csv')
    data = defaultdict(dict)  # product -> {ts: mid}
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            product = row['product']
            ts = int(row['timestamp'])
            mid = float(row['mid_price']) if row['mid_price'] else None
            if mid is not None:
                data[product][ts] = mid
    return data

def cross_corr(xs, ys, lag):
    """Correlation between xs[t] and ys[t+lag]."""
    n = len(xs) - abs(lag)
    if n < 50:
        return None
    if lag >= 0:
        a = xs[:n]
        b = ys[lag:lag+n]
    else:
        a = xs[-lag:-lag+n]
        b = ys[:n]
    ma, mb = mean(a), mean(b)
    sa, sb = stdev(a), stdev(b)
    if sa < 1e-12 or sb < 1e-12:
        return None
    cov = sum((ai - ma) * (bi - mb) for ai, bi in zip(a, b)) / (n - 1)
    return cov / (sa * sb)

def predictive_r2(xs, ys, lag):
    """R² of regression: ys[t+lag] = a + b * xs[t]."""
    n = len(xs) - lag
    if n < 50:
        return None, None
    a_vals = xs[:n]
    b_vals = ys[lag:lag+n]
    ma, mb = mean(a_vals), mean(b_vals)
    sa = stdev(a_vals)
    if sa < 1e-12:
        return None, None
    cov = sum((ai - ma) * (bi - mb) for ai, bi in zip(a_vals, b_vals)) / (n - 1)
    beta = cov / (sa**2)
    corr = cross_corr(xs, ys, lag)
    r2 = corr**2 if corr else None
    return beta, r2

print("=" * 100)
print("  MICROSTRUCTURE LATENCY ANALYSIS: Does underlying lead options?")
print("=" * 100)

for d in DAYS:
    prices = load_prices(d)
    ve_ts = prices.get('VELVETFRUIT_EXTRACT', {})
    timestamps = sorted(ve_ts.keys())

    # Compute underlying mid changes (returns)
    ve_changes = []
    for i in range(1, len(timestamps)):
        ve_changes.append(ve_ts[timestamps[i]] - ve_ts[timestamps[i-1]])

    print(f"\n{'─'*100}")
    print(f"  DAY {d} — {len(timestamps)} ticks, underlying std(Δmid)={stdev(ve_changes):.4f}")
    print(f"{'─'*100}")

    for k in STRIKES:
        prod = f'VEV_{k}'
        opt_ts = prices.get(prod, {})

        # Align timestamps
        common_ts = sorted(set(timestamps) & set(opt_ts.keys()))
        if len(common_ts) < 100:
            continue

        # Build aligned change series
        ve_chg, opt_chg = [], []
        for i in range(1, len(common_ts)):
            t0, t1 = common_ts[i-1], common_ts[i]
            ve_chg.append(ve_ts[t1] - ve_ts[t0])
            opt_chg.append(opt_ts[t1] - opt_ts[t0])

        # Cross-correlation at various lags
        # Positive lag = underlying LEADS options (ve_chg[t] predicts opt_chg[t+lag])
        print(f"\n  Strike {k} (n={len(ve_chg)})")
        print(f"  {'Lag':>5}  {'Corr(ΔS[t], ΔC[t+lag])':>25}  {'Beta':>10}  {'R²':>8}  {'Bar':>30}")

        peak_corr = 0
        peak_lag = 0
        for lag in range(-5, MAX_LAG + 1):
            corr = cross_corr(ve_chg, opt_chg, lag)
            beta, r2 = predictive_r2(ve_chg, opt_chg, lag) if lag >= 0 else (None, None)

            if corr is not None:
                bar_len = int(abs(corr) * 50)
                bar_char = '█' if corr > 0 else '░'
                bar = bar_char * bar_len
                beta_str = f"{beta:.4f}" if beta is not None else "N/A"
                r2_str = f"{r2:.6f}" if r2 is not None else "N/A"
                marker = " ◄ PEAK" if abs(corr) > abs(peak_corr) else ""
                if abs(corr) > abs(peak_corr):
                    peak_corr = corr
                    peak_lag = lag
                print(f"  {lag:>+5}  {corr:>+25.6f}  {beta_str:>10}  {r2_str:>8}  {bar}{marker}")

        print(f"  → Peak cross-corr at lag={peak_lag} (corr={peak_corr:+.6f})")
        if peak_lag > 0:
            print(f"    ⚡ UNDERLYING LEADS by {peak_lag} tick(s) = {peak_lag * 100}ms")
        elif peak_lag < 0:
            print(f"    ⚡ OPTIONS LEAD by {abs(peak_lag)} tick(s) = {abs(peak_lag) * 100}ms")
        else:
            print(f"    → Contemporaneous (no lag)")

# ── Incremental R² analysis: how much does lag-1 ΔS add over lag-0? ──────────
print(f"\n{'='*100}")
print("  INCREMENTAL PREDICTABILITY: Does lag-1 ΔS predict ΔC beyond contemporaneous?")
print("="*100)

for d in DAYS:
    prices = load_prices(d)
    ve_ts = prices['VELVETFRUIT_EXTRACT']
    timestamps = sorted(ve_ts.keys())

    print(f"\n  Day {d}:")
    print(f"  {'Strike':<8} {'R²(lag0)':>10} {'R²(lag1)':>10} {'R²(lag2)':>10} {'R²(lag0+1)':>12} {'Incr R²':>10} {'Edge?':>8}")

    for k in STRIKES:
        prod = f'VEV_{k}'
        opt_ts = prices.get(prod, {})
        common_ts = sorted(set(timestamps) & set(opt_ts.keys()))
        if len(common_ts) < 100:
            continue

        ve_chg, opt_chg = [], []
        for i in range(1, len(common_ts)):
            t0, t1 = common_ts[i-1], common_ts[i]
            ve_chg.append(ve_ts[t1] - ve_ts[t0])
            opt_chg.append(opt_ts[t1] - opt_ts[t0])

        # Simple R² at lag 0
        _, r2_0 = predictive_r2(ve_chg, opt_chg, 0)

        # R² at lag 1 (does ΔS[t-1] predict ΔC[t]?)
        _, r2_1 = predictive_r2(ve_chg, opt_chg, 1)

        # R² at lag 2
        _, r2_2 = predictive_r2(ve_chg, opt_chg, 2)

        # Multivariate: ΔC[t] = a + b0*ΔS[t] + b1*ΔS[t-1]
        # Compute via residual regression
        n = len(ve_chg) - 1
        if n < 50:
            continue
        x0 = ve_chg[1:n+1]    # ΔS[t] (contemporaneous)
        x1 = ve_chg[0:n]      # ΔS[t-1] (lagged)
        y  = opt_chg[1:n+1]   # ΔC[t]

        # Simple OLS for 2-var regression
        mx0, mx1, my = mean(x0), mean(x1), mean(y)
        sx0 = sum((a-mx0)**2 for a in x0)
        sx1 = sum((a-mx1)**2 for a in x1)
        sx01 = sum((a-mx0)*(b-mx1) for a,b in zip(x0,x1))
        sy0 = sum((a-mx0)*(b-my) for a,b in zip(x0,y))
        sy1 = sum((a-mx1)*(b-my) for a,b in zip(x1,y))

        det = sx0*sx1 - sx01**2
        if abs(det) < 1e-20:
            continue
        b0 = (sx1*sy0 - sx01*sy1) / det
        b1 = (sx0*sy1 - sx01*sy0) / det
        a = my - b0*mx0 - b1*mx1

        ss_res = sum((yi - a - b0*xi0 - b1*xi1)**2 for yi,xi0,xi1 in zip(y,x0,x1))
        ss_tot = sum((yi - my)**2 for yi in y)
        r2_multi = 1 - ss_res/ss_tot if ss_tot > 0 else 0

        incr = r2_multi - (r2_0 if r2_0 else 0)
        edge = "YES ⚡" if incr > 0.005 else "maybe" if incr > 0.001 else "no"

        r2_0_s = f"{r2_0:.6f}" if r2_0 else "N/A"
        r2_1_s = f"{r2_1:.6f}" if r2_1 else "N/A"
        r2_2_s = f"{r2_2:.6f}" if r2_2 else "N/A"

        print(f"  {k:<8} {r2_0_s:>10} {r2_1_s:>10} {r2_2_s:>10} {r2_multi:>12.6f} {incr:>+10.6f} {edge:>8}")

# ── Signed analysis: does direction of ΔS predict direction of next ΔC? ──────
print(f"\n{'='*100}")
print("  DIRECTION PREDICTION: P(ΔC[t+1] same sign as ΔS[t]) — exploitable signal?")
print("="*100)

for d in DAYS:
    prices = load_prices(d)
    ve_ts = prices['VELVETFRUIT_EXTRACT']
    timestamps = sorted(ve_ts.keys())

    print(f"\n  Day {d}:")
    print(f"  {'Strike':<8} {'P(same sign)':>14} {'N_events':>10} {'Avg|ΔC|_hit':>14} {'Avg|ΔC|_miss':>14} {'E[PnL/trade]':>14}")

    for k in STRIKES:
        prod = f'VEV_{k}'
        opt_ts = prices.get(prod, {})
        common_ts = sorted(set(timestamps) & set(opt_ts.keys()))
        if len(common_ts) < 100:
            continue

        ve_chg, opt_chg = [], []
        for i in range(1, len(common_ts)):
            ve_chg.append(ve_ts[common_ts[i]] - ve_ts[common_ts[i-1]])
            opt_chg.append(opt_ts[common_ts[i]] - opt_ts[common_ts[i-1]])

        hits, misses = 0, 0
        hit_sizes, miss_sizes = [], []
        n = len(ve_chg) - 1
        for i in range(n):
            if abs(ve_chg[i]) < 0.01:  # skip zero moves
                continue
            if ve_chg[i] * opt_chg[i+1] > 0:
                hits += 1
                hit_sizes.append(abs(opt_chg[i+1]))
            elif opt_chg[i+1] != 0:
                misses += 1
                miss_sizes.append(abs(opt_chg[i+1]))

        total = hits + misses
        if total < 10:
            continue
        p_hit = hits / total
        avg_hit = mean(hit_sizes) if hit_sizes else 0
        avg_miss = mean(miss_sizes) if miss_sizes else 0
        # E[PnL] = P(hit)*avg_hit - P(miss)*avg_miss
        e_pnl = p_hit * avg_hit - (1-p_hit) * avg_miss

        print(f"  {k:<8} {p_hit:>14.4f} {total:>10} {avg_hit:>14.4f} {avg_miss:>14.4f} {e_pnl:>+14.4f}")

print()
