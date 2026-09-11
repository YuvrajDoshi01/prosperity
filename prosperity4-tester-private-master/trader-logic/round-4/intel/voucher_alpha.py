"""voucher_alpha.py — R4 voucher portfolio alpha hunt.

Three analyses:
  (1) Per-strike "perfect-MM ceiling": post at fv ± edge, scan edge ∈ {1..15},
      simulate fills via market_trades. Fill semantics: a market trade at price
      p, side BUY, fills our resting ASK iff our ask <= p; a market trade SELL
      fills our resting BID iff our bid >= p. We assume infinite size.
  (2) Delta-hedged portfolio MM: compute aggregate Greek delta across vouchers,
      simulate hedging via VFE, quantify residual delta drift.
  (3) Vol surface: per-strike IV via Newton-bisection on wall_mid, smile fit,
      cross-strike z-score for mispricings.

Outputs printed to stdout. Numerical, no external deps (csv + math + statistics).
"""

import csv
import math
import os
from collections import defaultdict
from statistics import NormalDist, median, stdev

ND = NormalDist()
ROOT = "C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4"
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
TTE_DAYS_AT_DAY3 = 2.0  # day-3 1k tested; day1=4, day2=3, day3=2 for trading windows
TTE_YEAR = 250.0


def bs_call(spot, K, T, vol):
    if T <= 0 or vol <= 0:
        return max(spot - K, 0.0)
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    return spot * ND.cdf(d1) - K * ND.cdf(d2)


def bs_delta(spot, K, T, vol):
    if T <= 0 or vol <= 0:
        return 1.0 if spot > K else 0.0
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    return ND.cdf(d1)


def bs_vega(spot, K, T, vol):
    if T <= 0 or vol <= 0:
        return 0.0
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    return spot * math.sqrt(T) * math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)


def implied_vol(mkt, spot, K, T, lo=1e-4, hi=5.0):
    intr = max(spot - K, 0.0)
    if mkt <= intr + 1e-6 or T <= 0 or mkt >= spot:
        return None
    for _ in range(60):
        m = 0.5 * (lo + hi)
        if bs_call(spot, K, T, m) < mkt:
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


def load_prices(path):
    """Returns {ts: {sym: dict(bp1, bv1, ap1, av1, mid)}}."""
    out = defaultdict(dict)
    with open(path) as f:
        for row in csv.DictReader(f, delimiter=';'):
            ts = int(row['timestamp'])
            sym = row['product']
            d = {}
            for k in ['bid_price_1', 'bid_volume_1', 'ask_price_1', 'ask_volume_1', 'mid_price']:
                v = row.get(k, '')
                d[k] = float(v) if v != '' else None
            # wall: highest-volume bid/ask
            bps, bvs, aps, avs = [], [], [], []
            for i in [1, 2, 3]:
                bp = row.get(f'bid_price_{i}'); bv = row.get(f'bid_volume_{i}')
                ap = row.get(f'ask_price_{i}'); av = row.get(f'ask_volume_{i}')
                if bp:
                    bps.append(float(bp)); bvs.append(int(bv))
                if ap:
                    aps.append(float(ap)); avs.append(int(av))
            d['bps'] = bps; d['bvs'] = bvs; d['aps'] = aps; d['avs'] = avs
            if bps and aps:
                wb = bps[bvs.index(max(bvs))]; wa = aps[avs.index(max(avs))]
                d['wall_mid'] = 0.5 * (wb + wa)
            else:
                d['wall_mid'] = d['mid_price']
            out[ts][sym] = d
    return out


def load_trades(path):
    """Returns {ts: [(sym, price, qty, buyer, seller)]}."""
    out = defaultdict(list)
    with open(path) as f:
        for row in csv.DictReader(f, delimiter=';'):
            ts = int(row['timestamp'])
            out[ts].append((row['symbol'], float(row['price']), int(row['quantity']),
                            row['buyer'], row['seller']))
    return out


def perfect_mm_ceiling(prices, trades, K, edge_grid):
    """For each edge value, simulate posting [fv-edge, fv+edge] every tick.
    Aggressor inference: counterparties Mark 14, Mark 38 are MMs (resting).
    Anyone else is the aggressor — if they're the buyer side, they hit ASK
    (we are seller); if they're the seller, they hit BID (we are buyer).
    Mark 14 vs Mark 38 trades = MM-MM cross, treated as ambient flow.
    """
    # Per-strike aggressor identification:
    # VEV_4000: Mark 14 / Mark 38 (alternate, both can be either side)
    # VEV_5200+: Mark 01 = consistent buyer, Mark 22 = consistent seller
    # Treat ALL Marks as potential takers. Method: any trade printed,
    # if our quote was at/inside the trade price, count as a fill.
    pass
    sym = f'VEV_{K}'
    # We need fv per timestamp. Use BS price using rolling adaptive sigma from wall_mid IV.
    iv_hist = []
    fv_by_ts = {}
    for ts in sorted(prices.keys()):
        snap = prices[ts]
        if 'VELVETFRUIT_EXTRACT' not in snap or sym not in snap:
            continue
        spot = snap['VELVETFRUIT_EXTRACT']['mid_price']
        wm_v = snap[sym]['wall_mid']
        if spot is None or wm_v is None:
            continue
        T = max(TTE_DAYS_AT_DAY3 - ts / 1_000_000.0, 0.01) / TTE_YEAR
        iv = implied_vol(wm_v, spot, K, T)
        if iv is not None and 0.05 < iv < 1.5:
            iv_hist.append(iv)
            if len(iv_hist) > 50:
                iv_hist = iv_hist[-50:]
        sigma = median(iv_hist) if len(iv_hist) >= 10 else 0.18
        fv = bs_call(spot, K, T, sigma)
        fv_by_ts[ts] = fv

    results = {}
    for edge in edge_grid:
        pos = 0
        cash = 0.0
        fills_buy = 0; fills_sell = 0
        last_fv = None
        for ts in sorted(prices.keys()):
            if ts not in fv_by_ts:
                continue
            fv = fv_by_ts[ts]; last_fv = fv
            our_bid = fv - edge; our_ask = fv + edge
            # Check trades at this ts
            for (s, p, q, buyer, seller) in trades.get(ts, []):
                if s != sym:
                    continue
                # Heuristic: if trade printed at p > fv, infer aggressor BUY
                # (someone reached up); fills our ask if our_ask <= p AND <= p.
                # If p < fv, infer aggressor SELL; fills our bid if our_bid >= p.
                # If p == fv, ambient; allow both sides at half credit.
                if p > fv + 0.5:
                    if our_ask <= p:
                        pos -= q; cash += our_ask * q; fills_sell += q
                elif p < fv - 0.5:
                    if our_bid >= p:
                        pos += q; cash -= our_bid * q; fills_buy += q
                else:
                    if our_ask <= p:
                        pos -= q * 0.5; cash += our_ask * q * 0.5; fills_sell += q * 0.5
                    if our_bid >= p:
                        pos += q * 0.5; cash -= our_bid * q * 0.5; fills_buy += q * 0.5
        # MTM at last fv
        mtm = cash + pos * (last_fv if last_fv else 0)
        results[edge] = (mtm, fills_buy, fills_sell, pos)
    return results


def delta_drift_analysis(prices, day_label):
    """Compute aggregate delta if we hold +50 of each tradable strike (5000-5400)
    and how it drifts over the day."""
    strikes = [5000, 5100, 5200, 5300, 5400]
    inv = {K: 50 for K in strikes}  # toy long portfolio
    iv_hist = {K: [] for K in strikes}
    deltas_by_ts = []
    for ts in sorted(prices.keys()):
        snap = prices[ts]
        if 'VELVETFRUIT_EXTRACT' not in snap:
            continue
        spot = snap['VELVETFRUIT_EXTRACT']['mid_price']
        if spot is None:
            continue
        T = max(TTE_DAYS_AT_DAY3 - ts / 1_000_000.0, 0.01) / TTE_YEAR
        for K in strikes:
            sym = f'VEV_{K}'
            if sym not in snap:
                continue
            wm = snap[sym]['wall_mid']
            iv = implied_vol(wm, spot, K, T) if wm else None
            if iv is not None and 0.05 < iv < 1.5:
                iv_hist[K].append(iv)
                if len(iv_hist[K]) > 50:
                    iv_hist[K] = iv_hist[K][-50:]
        agg_delta = 0.0
        for K in strikes:
            sigma_h = iv_hist[K]
            sigma = median(sigma_h) if len(sigma_h) >= 5 else 0.18
            d = bs_delta(spot, K, T, sigma)
            agg_delta += inv[K] * d
        deltas_by_ts.append((ts, spot, agg_delta))
    # Stats
    deltas = [d for _, _, d in deltas_by_ts]
    spots = [s for _, s, _ in deltas_by_ts]
    print(f"\n[Delta drift] {day_label}: portfolio = +50 each of K=[5000..5400]")
    print(f"  n={len(deltas)} spot range [{min(spots):.1f},{max(spots):.1f}]")
    print(f"  agg_delta range [{min(deltas):.1f},{max(deltas):.1f}] mean={sum(deltas)/len(deltas):.1f} std={stdev(deltas):.1f}")
    # Hedge-rebalance frequency: how often does delta change > 10?
    rebal_threshold = 10
    rebals = 0
    last_hedge_delta = deltas[0]
    for d in deltas:
        if abs(d - last_hedge_delta) > rebal_threshold:
            rebals += 1
            last_hedge_delta = d
    print(f"  rebalance triggers (|d_delta|>10): {rebals} over {len(deltas)} ticks")
    # What's the unhedged P&L variance from delta×spot move?
    unhedged_pnl = 0.0
    pnl_path = []
    for i in range(1, len(deltas_by_ts)):
        _, s_prev, d_prev = deltas_by_ts[i - 1]
        _, s_cur, _ = deltas_by_ts[i]
        unhedged_pnl += d_prev * (s_cur - s_prev)
        pnl_path.append(unhedged_pnl)
    print(f"  unhedged delta P&L (cumul): {unhedged_pnl:.1f} (drift contribution if we never hedged)")
    print(f"  unhedged P&L std intraday: {stdev(pnl_path):.1f}")
    return deltas_by_ts


def vol_surface(prices, day_label):
    """Cross-strike IV smile snapshot — mean IV per strike, std, and mispricings."""
    strikes = [4500, 5000, 5100, 5200, 5300, 5400]
    iv_by_K = defaultdict(list)
    moneyness_by_K = defaultdict(list)
    for ts in sorted(prices.keys())[::100]:  # subsample every 10s
        snap = prices[ts]
        if 'VELVETFRUIT_EXTRACT' not in snap:
            continue
        spot = snap['VELVETFRUIT_EXTRACT']['mid_price']
        if spot is None:
            continue
        T = max(TTE_DAYS_AT_DAY3 - ts / 1_000_000.0, 0.01) / TTE_YEAR
        for K in strikes:
            sym = f'VEV_{K}'
            if sym not in snap:
                continue
            wm = snap[sym]['wall_mid']
            iv = implied_vol(wm, spot, K, T) if wm else None
            if iv is not None and 0.05 < iv < 1.5:
                iv_by_K[K].append(iv)
                m = math.log(K / spot) / (sigma_typ := 0.18) / math.sqrt(T) if T > 0 else 0
                moneyness_by_K[K].append(m)
    print(f"\n[Vol surface] {day_label}:")
    for K in strikes:
        arr = iv_by_K[K]
        if not arr:
            continue
        m_arr = moneyness_by_K[K]
        print(f"  K={K}: n={len(arr)} IV mean={sum(arr)/len(arr):.4f} "
              f"std={stdev(arr) if len(arr)>1 else 0:.4f} "
              f"moneyness m mean={sum(m_arr)/len(m_arr):.2f}")


def cross_strike_vol_arb(prices, day_label):
    """Identify ticks where IV(K_i) >> IV(K_j) — sell rich, buy cheap."""
    strikes = [4500, 5000, 5100, 5200, 5300, 5400]
    iv_ts_K = defaultdict(dict)  # ts -> K -> iv
    spots = {}
    for ts in sorted(prices.keys()):
        snap = prices[ts]
        if 'VELVETFRUIT_EXTRACT' not in snap:
            continue
        spot = snap['VELVETFRUIT_EXTRACT']['mid_price']
        if spot is None:
            continue
        spots[ts] = spot
        T = max(TTE_DAYS_AT_DAY3 - ts / 1_000_000.0, 0.01) / TTE_YEAR
        for K in strikes:
            sym = f'VEV_{K}'
            if sym not in snap:
                continue
            wm = snap[sym]['wall_mid']
            iv = implied_vol(wm, spot, K, T) if wm else None
            if iv is not None and 0.05 < iv < 1.5:
                iv_ts_K[ts][K] = iv
    # Compute mean smile (per strike)
    smile = {}
    for K in strikes:
        arr = [iv_ts_K[ts][K] for ts in iv_ts_K if K in iv_ts_K[ts]]
        if arr:
            smile[K] = sum(arr) / len(arr)
    # Per-tick deviation from smile mean
    devs_K = defaultdict(list)
    for ts in iv_ts_K:
        for K in iv_ts_K[ts]:
            devs_K[K].append(iv_ts_K[ts][K] - smile[K])
    print(f"\n[Cross-strike vol mispricing] {day_label}:")
    print(f"  Smile means: {{ {', '.join(f'{K}:{smile[K]:.3f}' for K in strikes if K in smile)} }}")
    for K in strikes:
        if K not in devs_K or len(devs_K[K]) < 10:
            continue
        std = stdev(devs_K[K])
        # how often |z| > 2?
        n_extreme = sum(1 for d in devs_K[K] if abs(d) > 2 * std)
        print(f"  K={K}: dev std={std:.4f}  ticks |z|>2: {n_extreme}/{len(devs_K[K])} ({100*n_extreme/len(devs_K[K]):.1f}%)")


def main():
    print("=" * 70)
    print("R4 VOUCHER ALPHA ANALYSIS")
    print("=" * 70)

    for day in [1, 2, 3]:
        prices = load_prices(f"{ROOT}/prices_round_4_day_{day}.csv")
        trades = load_trades(f"{ROOT}/trades_round_4_day_{day}.csv")

        # Total trades per voucher
        per_sym = defaultdict(int); per_sym_qty = defaultdict(int)
        for ts in trades:
            for (s, p, q, _, _) in trades[ts]:
                per_sym[s] += 1; per_sym_qty[s] += q
        print(f"\n--- DAY {day} ---")
        print("Trade counts per voucher:")
        for K in STRIKES:
            sym = f'VEV_{K}'
            print(f"  {sym}: {per_sym.get(sym, 0)} trades / {per_sym_qty.get(sym, 0)} qty")

        # Perfect MM ceiling — only on day 3 (full coverage)
        if day == 3:
            print("\n[Perfect MM ceiling] (post fv±edge, fill on market trades)")
            print(f"  {'K':>5} {'edge=2':>10} {'edge=4':>10} {'edge=6':>10} {'edge=8':>10} {'edge=10':>10}")
            for K in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500]:
                if per_sym.get(f'VEV_{K}', 0) < 5:
                    print(f"  {K:>5}  (skipped — only {per_sym.get(f'VEV_{K}',0)} trades)")
                    continue
                res = perfect_mm_ceiling(prices, trades, K, [2, 4, 6, 8, 10])
                row = f"  {K:>5}"
                for e in [2, 4, 6, 8, 10]:
                    pnl, fb, fs, pos = res[e]
                    row += f" {pnl:>10.0f}"
                print(row)

            delta_drift_analysis(prices, f"day {day}")
            vol_surface(prices, f"day {day}")
            cross_strike_vol_arb(prices, f"day {day}")


if __name__ == "__main__":
    main()
