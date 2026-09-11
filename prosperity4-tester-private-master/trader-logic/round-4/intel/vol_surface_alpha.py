"""vol_surface_alpha.py — R4 voucher VOLATILITY SURFACE deep dive.

Mandate beyond prior voucher_alpha.py:
  1. IV(K,t) matrix across 10 strikes × 30k timestamps (3 days).
  2. Term structure: IV evolution over time, per-strike AC(1), cross-strike corr.
  3. Vol-of-vol (sigma of d(IV_t)) for ATM, defines vol-arb edge.
  4. Mispricings: ticks with |z(IV_K - cross-section median)| > 1, forward 100t PnL.
  5. Greeks decomposition at typical position size.
  6. Recommendation: vol-surface MM strategy with parameters.

Usage:
    cd C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester
    python trader-logic/round-4/intel/vol_surface_alpha.py
"""

import csv
import math
import os
from collections import defaultdict
from statistics import NormalDist, median, mean, stdev, pstdev

ND = NormalDist()
ROOT = "C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4"
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
TTE_YEAR = 250.0
DAY_TTE = {1: 4.0, 2: 3.0, 3: 2.0}  # remaining trading days at start of each day


def bs_call(S, K, T, v):
    if T <= 0 or v <= 0:
        return max(S - K, 0.0)
    sv = v * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * v * v * T) / sv
    d2 = d1 - sv
    return S * ND.cdf(d1) - K * ND.cdf(d2)


def bs_greeks(S, K, T, v):
    if T <= 0 or v <= 0:
        return {'delta': 1.0 if S > K else 0.0, 'gamma': 0, 'vega': 0, 'theta': 0}
    sv = v * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * v * v * T) / sv
    d2 = d1 - sv
    pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    return {
        'delta': ND.cdf(d1),
        'gamma': pdf_d1 / (S * sv),
        'vega': S * math.sqrt(T) * pdf_d1,        # per 1.0 vol
        'theta': -S * pdf_d1 * v / (2 * math.sqrt(T)) / TTE_YEAR,  # per day
    }


def implied_vol(mkt, S, K, T, lo=1e-4, hi=5.0):
    intr = max(S - K, 0.0)
    if mkt is None or mkt <= intr + 1e-6 or T <= 0 or mkt >= S:
        return None
    for _ in range(60):
        m = 0.5 * (lo + hi)
        if bs_call(S, K, T, m) < mkt:
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


def load_prices(path):
    out = defaultdict(dict)
    with open(path) as f:
        for row in csv.DictReader(f, delimiter=';'):
            ts = int(row['timestamp'])
            sym = row['product']
            d = {}
            mid = row['mid_price']
            d['mid'] = float(mid) if mid else None
            bps, bvs, aps, avs = [], [], [], []
            for i in [1, 2, 3]:
                bp, bv = row.get(f'bid_price_{i}'), row.get(f'bid_volume_{i}')
                ap, av = row.get(f'ask_price_{i}'), row.get(f'ask_volume_{i}')
                if bp:
                    bps.append(float(bp)); bvs.append(int(bv))
                if ap:
                    aps.append(float(ap)); avs.append(int(av))
            if bps and aps:
                wb = bps[bvs.index(max(bvs))]; wa = aps[avs.index(max(avs))]
                d['wall_mid'] = 0.5 * (wb + wa)
            else:
                d['wall_mid'] = d['mid']
            out[ts][sym] = d
    return out


def build_iv_surface(prices_by_day):
    """Returns surface[(day,ts)][K] = iv,  spots[(day,ts)] = S."""
    surface = {}
    spots = {}
    for day, prices in prices_by_day.items():
        for ts in sorted(prices.keys()):
            snap = prices[ts]
            if 'VELVETFRUIT_EXTRACT' not in snap:
                continue
            S = snap['VELVETFRUIT_EXTRACT']['wall_mid']
            if S is None:
                continue
            T = max(DAY_TTE[day] - ts / 1_000_000.0, 0.01) / TTE_YEAR
            spots[(day, ts)] = (S, T)
            slice_iv = {}
            for K in STRIKES:
                sym = f'VEV_{K}'
                if sym not in snap:
                    continue
                wm = snap[sym]['wall_mid']
                iv = implied_vol(wm, S, K, T)
                if iv is not None and 0.02 < iv < 2.0:
                    slice_iv[K] = iv
            surface[(day, ts)] = slice_iv
    return surface, spots


def autocorr(xs, lag=1):
    if len(xs) <= lag + 1:
        return None
    m = mean(xs)
    num = sum((xs[i] - m) * (xs[i - lag] - m) for i in range(lag, len(xs)))
    den = sum((x - m) ** 2 for x in xs)
    return num / den if den else None


def pearson(xs, ys):
    if len(xs) < 5 or len(xs) != len(ys):
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else None


def section_iv_matrix(surface, spots):
    """6 representative timestamps spanning 3 days × 10 strikes IV."""
    picks = [(1, 0), (1, 500_000), (2, 0), (2, 500_000), (3, 0), (3, 500_000)]
    print("\n## IV(K,t) matrix — 6 snapshots × 10 strikes\n")
    hdr = "| day-ts (S, T_yr) | " + " | ".join(f"K={K}" for K in STRIKES) + " |"
    print(hdr)
    print("|" + "---|" * (len(STRIKES) + 1))
    for (d, t) in picks:
        slice_iv = surface.get((d, t), {})
        S, T = spots.get((d, t), (None, None))
        if S is None:
            print(f"| d{d}-{t} (n/a) | " + " | ".join("-" for _ in STRIKES) + " |")
            continue
        cells = []
        for K in STRIKES:
            iv = slice_iv.get(K)
            cells.append(f"{iv:.3f}" if iv else "—")
        print(f"| d{d}-{t} (S={S:.0f}, T={T:.4f}) | " + " | ".join(cells) + " |")


def section_term_structure(surface, spots):
    print("\n## Term structure & smile dynamics\n")
    # Per-strike series
    series = defaultdict(list)
    for (d, t), slc in sorted(surface.items()):
        for K, iv in slc.items():
            series[K].append(iv)
    print("| K | n | mean IV | std IV | AC(1) | AC(10) | AC(100) |")
    print("|---|---|---|---|---|---|---|")
    for K in STRIKES:
        s = series[K]
        if len(s) < 200:
            continue
        ac1 = autocorr(s, 1); ac10 = autocorr(s, 10); ac100 = autocorr(s, 100)
        print(f"| {K} | {len(s)} | {mean(s):.4f} | {stdev(s):.4f} | "
              f"{ac1:.3f} | {ac10:.3f} | {ac100:.3f} |")
    # Cross-strike correlation matrix on common ticks (use ATM cluster)
    common_K = [5000, 5100, 5200, 5300, 5400]
    by_key = defaultdict(dict)
    for (d, t), slc in surface.items():
        for K in common_K:
            if K in slc:
                by_key[(d, t)][K] = slc[K]
    common_keys = [k for k in by_key if all(K in by_key[k] for K in common_K)]
    arrs = {K: [by_key[k][K] for k in common_keys] for K in common_K}
    print(f"\n### Cross-strike Pearson corr (n={len(common_keys)} common ticks, ATM cluster)\n")
    print("| K | " + " | ".join(str(K) for K in common_K) + " |")
    print("|---|" + "---|" * len(common_K))
    for Ki in common_K:
        row = [str(Ki)]
        for Kj in common_K:
            r = pearson(arrs[Ki], arrs[Kj])
            row.append(f"{r:.3f}" if r else "-")
        print("| " + " | ".join(row) + " |")


def section_vol_of_vol(surface, spots):
    print("\n## Vol-of-vol (ATM = K=5300)\n")
    K_atm = 5300
    series = []
    for (d, t), slc in sorted(surface.items()):
        if K_atm in slc:
            series.append(((d, t), slc[K_atm]))
    if len(series) < 20:
        print("Insufficient ATM data."); return
    ivs = [iv for _, iv in series]
    diffs = [series[i][1] - series[i - 1][1] for i in range(1, len(series))]
    vov = stdev(diffs)
    print(f"- ATM (K=5300) IV mean = {mean(ivs):.4f}, std = {stdev(ivs):.4f}")
    print(f"- Per-tick delta-IV stdev (vol-of-vol per 100ms) = **{vov:.5f}**")
    # Rolling 100-tick std of IV (slower drift):
    rolling_stds = []
    for i in range(100, len(ivs), 100):
        rolling_stds.append(stdev(ivs[i - 100:i]))
    if rolling_stds:
        print(f"- Rolling 100-tick IV std: median {median(rolling_stds):.4f}, "
              f"p95 {sorted(rolling_stds)[int(0.95 * len(rolling_stds))]:.4f}")
    # Vol-arb edge: vega(K=5300, S=5300, T=2/250, sigma=0.34)
    v = bs_greeks(5300, 5300, 2 / TTE_YEAR, 0.34)['vega']
    edge_per_unit = v * vov
    print(f"- Vega(K=5300, ATM, T=2d) ~ {v:.2f} per 1.0 vol -> per 0.01 IV = ${v * 0.01:.3f}")
    print(f"- Per-tick vol-arb expected $ edge = vega * vov = ${edge_per_unit:.3f}")
    print(f"  (1-tick spread ~$1 -> vol-arb {'PROFITABLE' if edge_per_unit > 1 else 'BELOW SPREAD'})")


def section_mispricings(surface, spots):
    """Per-tick z-score of IV(K) vs cross-section median IV across ATM cluster.
    For ticks with |z|>1 on a strike, compute forward 100t PnL of buying cheap /
    selling rich at wall_mid."""
    print("\n## Cross-sectional mispricings & forward 100-tick PnL\n")
    cluster = [5000, 5100, 5200, 5300, 5400]
    keys = sorted(surface.keys())
    # For each tick, cross-section median IV; flag |dev|>1*per-strike-stdev
    per_K_dev = defaultdict(list)
    flags = []  # (key, K, dev_iv)
    for k in keys:
        slc = surface[k]
        ivs_now = [slc[K] for K in cluster if K in slc]
        if len(ivs_now) < 3:
            continue
        med = median(ivs_now)
        for K in cluster:
            if K in slc:
                d = slc[K] - med
                per_K_dev[K].append((k, d))
    # Per-strike threshold
    thresholds = {K: stdev([d for _, d in per_K_dev[K]]) for K in cluster if len(per_K_dev[K]) > 5}
    # Forward 100t PnL: buy if dev<-thr (cheap), sell if dev>+thr (rich), hold 100 ticks, exit at wall_mid
    # Build wall_mid index
    wall = {}
    for d in DAY_TTE:
        try:
            prices = load_prices(f"{ROOT}/prices_round_4_day_{d}.csv")
        except FileNotFoundError:
            continue
        for ts, snap in prices.items():
            for K in cluster:
                sym = f'VEV_{K}'
                if sym in snap:
                    wall[(d, ts, K)] = snap[sym]['wall_mid']

    print("| K | thr (1σ) | n |z|>1 | mean fwd-100t PnL | win % |")
    print("|---|---|---|---|---|")
    summary = {}
    for K in cluster:
        thr = thresholds.get(K)
        if not thr:
            continue
        pnls = []
        for (k, dev) in per_K_dev[K]:
            if abs(dev) < thr:
                continue
            day, ts = k
            entry = wall.get((day, ts, K))
            exit_ts = ts + 10_000  # 100 ticks × 100ms
            exit_p = wall.get((day, exit_ts, K))
            if entry is None or exit_p is None:
                continue
            # If IV rich (dev>0), short at entry, cover at exit -> PnL = entry - exit
            # If cheap (dev<0), long -> PnL = exit - entry
            sign = -1 if dev > 0 else 1
            pnls.append(sign * (exit_p - entry))
        if pnls:
            wins = sum(1 for p in pnls if p > 0)
            summary[K] = (thr, len(pnls), mean(pnls), wins / len(pnls))
            print(f"| {K} | {thr:.4f} | {len(pnls)} | {mean(pnls):.3f} | {100*wins/len(pnls):.1f}% |")
    return summary


def section_greeks(surface, spots):
    print("\n## Greeks decomposition at typical pos sizes\n")
    # Use day 3 ts=500000 representative state
    key = (3, 500_000)
    if key not in spots:
        # fallback to first available
        for k in sorted(spots.keys()):
            if k[0] == 3:
                key = k; break
    S, T = spots[key]
    slc = surface.get(key, {})
    pos_per_strike = 50  # baseline scenario
    print(f"Reference: day 3 ts={key[1]}, S={S:.0f}, T={T:.4f} yr.\n")
    print(f"Per-strike position = +{pos_per_strike} (long).\n")
    print("| K | IV | Δ | Γ | Vega | Θ/day | $/1% spot | $/1% vol | $/day theta |")
    print("|---|---|---|---|---|---|---|---|---|")
    tot_d = tot_g = tot_v = tot_t = 0.0
    for K in STRIKES:
        iv = slc.get(K)
        if iv is None:
            iv = 0.34  # fallback
        g = bs_greeks(S, K, T, iv)
        # $ exposures at pos=50
        usd_spot = pos_per_strike * g['delta'] * S * 0.01
        usd_vol = pos_per_strike * g['vega'] * 0.01
        usd_theta = pos_per_strike * g['theta']
        tot_d += pos_per_strike * g['delta']
        tot_g += pos_per_strike * g['gamma']
        tot_v += pos_per_strike * g['vega']
        tot_t += pos_per_strike * g['theta']
        print(f"| {K} | {iv:.3f} | {g['delta']:.3f} | {g['gamma']:.5f} | "
              f"{g['vega']:.2f} | {g['theta']:.2f} | "
              f"{usd_spot:.0f} | {usd_vol:.0f} | {usd_theta:.1f} |")
    print(f"\n**Aggregate** Δ={tot_d:.0f}, Γ={tot_g:.4f}, Vega={tot_v:.0f}, Θ/day={tot_t:.0f}")
    print(f"**$ exposure**: 1% spot move = ${tot_d * S * 0.01:.0f}, "
          f"1% vol move = ${tot_v * 0.01:.0f}, daily theta = ${tot_t:.0f}")


def main():
    prices_by_day = {}
    for d in [1, 2, 3]:
        prices_by_day[d] = load_prices(f"{ROOT}/prices_round_4_day_{d}.csv")

    surface, spots = build_iv_surface(prices_by_day)
    print(f"Surface built: {len(surface)} (day,ts) snapshots, "
          f"{sum(len(s) for s in surface.values())} IV points")

    section_iv_matrix(surface, spots)
    section_term_structure(surface, spots)
    section_vol_of_vol(surface, spots)
    section_mispricings(surface, spots)
    section_greeks(surface, spots)


if __name__ == "__main__":
    main()
