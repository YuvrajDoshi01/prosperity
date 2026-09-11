#!/usr/bin/env python3
"""
Round 3 Options Analysis: VELVETFRUIT_EXTRACT & VEV Vouchers
============================================================
- Greeks computation (Delta, Gamma, Vega, Theta, Rho)
- BSM implied volatility surface
- Arbitrage detection (put-call parity, butterfly, calendar)
- Cross-asset correlation analysis
- Trade & price visualization
"""

import csv
import math
import os
from collections import defaultdict
from statistics import mean, stdev, median

# ── BSM Functions ──────────────────────────────────────────────────────────────

def norm_cdf(x):
    """Standard normal CDF (Abramowitz & Stegun approximation)."""
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5*t + a4)*t) + a3)*t + a2)*t + a1)*t * math.exp(-x*x/2.0)
    return 0.5 * (1.0 + sign * y)

def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

def bsm_call_price(S, K, T, r, sigma):
    """Black-Scholes call price."""
    if T <= 0 or sigma <= 0:
        return max(0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)

def bsm_put_price(S, K, T, r, sigma):
    """Black-Scholes put price."""
    if T <= 0 or sigma <= 0:
        return max(0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)

def implied_vol(market_price, S, K, T, r, option_type='call', tol=1e-6, max_iter=200):
    """Newton-Raphson implied vol solver."""
    if T <= 1e-10:
        return None
    intrinsic = max(0, S - K) if option_type == 'call' else max(0, K - S)
    if market_price <= intrinsic + 1e-8:
        return None
    sigma = 0.3  # initial guess
    for _ in range(max_iter):
        if sigma <= 0.001:
            sigma = 0.001
        price = bsm_call_price(S, K, T, r, sigma) if option_type == 'call' else bsm_put_price(S, K, T, r, sigma)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        vega = S * norm_pdf(d1) * math.sqrt(T)
        if vega < 1e-12:
            return None
        diff = price - market_price
        sigma -= diff / vega
        if abs(diff) < tol:
            if 0.001 < sigma < 5.0:
                return sigma
            return None
    return None

def compute_greeks(S, K, T, r, sigma):
    """Returns dict of all Greeks for a CALL option."""
    if T <= 0 or sigma <= 0:
        return None
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    delta = norm_cdf(d1)
    gamma = norm_pdf(d1) / (S * sigma * sqrtT)
    vega = S * norm_pdf(d1) * sqrtT / 100  # per 1% vol move
    theta = (-(S * norm_pdf(d1) * sigma) / (2 * sqrtT) - r * K * math.exp(-r*T) * norm_cdf(d2)) / 365
    rho = K * T * math.exp(-r*T) * norm_cdf(d2) / 100
    return {'delta': delta, 'gamma': gamma, 'vega': vega, 'theta': theta, 'rho': rho, 'd1': d1, 'd2': d2}

# ── Data Loading ───────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_PRODUCTS = [f'VEV_{k}' for k in STRIKES]
DAYS = [0, 1, 2]
# TTE: day0=8d, day1=7d, day2=6d (from problem statement)
TTE_MAP = {0: 8/365, 1: 7/365, 2: 6/365}
R = 0.0  # risk-free rate (Prosperity convention)

def load_prices(day):
    """Load price data for a day, returns dict[product] -> list of (timestamp, mid, bid1, ask1, bid_vol1, ask_vol1)."""
    path = os.path.join(DATA_DIR, f'prices_round_3_day_{day}.csv')
    data = defaultdict(list)
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            product = row['product']
            ts = int(row['timestamp'])
            mid = float(row['mid_price']) if row['mid_price'] else None
            bid1 = float(row['bid_price_1']) if row['bid_price_1'] else None
            ask1 = float(row['ask_price_1']) if row['ask_price_1'] else None
            bv1 = int(row['bid_volume_1']) if row['bid_volume_1'] else 0
            av1 = int(row['ask_volume_1']) if row['ask_volume_1'] else 0
            if mid is not None:
                data[product].append((ts, mid, bid1, ask1, bv1, av1))
    return data

def load_trades(day):
    """Load trade data for a day."""
    path = os.path.join(DATA_DIR, f'trades_round_3_day_{day}.csv')
    data = defaultdict(list)
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            sym = row['symbol']
            ts = int(row['timestamp'])
            price = float(row['price'])
            qty = int(row['quantity'])
            data[sym].append((ts, price, qty))
    return data


# ── MAIN ANALYSIS ──────────────────────────────────────────────────────────────

def run_analysis():
    print("=" * 90)
    print("  ROUND 3 OPTIONS ANALYSIS: VELVETFRUIT_EXTRACT & VEV VOUCHERS")
    print("=" * 90)

    all_prices = {}
    all_trades = {}
    for d in DAYS:
        all_prices[d] = load_prices(d)
        all_trades[d] = load_trades(d)

    # ── 1. UNDERLYING (VELVETFRUIT_EXTRACT) SUMMARY ────────────────────────────
    print("\n" + "─" * 90)
    print("  1. UNDERLYING: VELVETFRUIT_EXTRACT PRICE SUMMARY")
    print("─" * 90)

    for d in DAYS:
        mids = [x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])]
        if mids:
            spreads = []
            for x in all_prices[d].get('VELVETFRUIT_EXTRACT', []):
                if x[2] is not None and x[3] is not None:
                    spreads.append(x[3] - x[2])
            print(f"  Day {d}: min={min(mids):.1f}  max={max(mids):.1f}  mean={mean(mids):.1f}  "
                  f"std={stdev(mids):.1f}  ticks={len(mids)}  avg_spread={mean(spreads):.2f}")

    # ── 2. OPTIONS MID-PRICE SUMMARY ──────────────────────────────────────────
    print("\n" + "─" * 90)
    print("  2. OPTIONS MID-PRICE SUMMARY PER STRIKE PER DAY")
    print("─" * 90)
    print(f"  {'Strike':<8}", end="")
    for d in DAYS:
        print(f"  {'Day'+str(d)+' Mid':>12} {'Spread':>8} {'Ticks':>6}", end="")
    print()

    for k in STRIKES:
        prod = f'VEV_{k}'
        print(f"  {k:<8}", end="")
        for d in DAYS:
            entries = all_prices[d].get(prod, [])
            mids = [x[1] for x in entries]
            spreads = [x[3]-x[2] for x in entries if x[2] is not None and x[3] is not None]
            if mids:
                print(f"  {mean(mids):>12.2f} {mean(spreads):>8.2f} {len(mids):>6}", end="")
            else:
                print(f"  {'N/A':>12} {'N/A':>8} {'N/A':>6}", end="")
        print()

    # ── 3. IMPLIED VOLATILITY SURFACE ──────────────────────────────────────────
    print("\n" + "─" * 90)
    print("  3. IMPLIED VOLATILITY SURFACE (BSM, r=0, CALL options)")
    print("─" * 90)

    iv_surface = {}  # (day, strike) -> iv
    for d in DAYS:
        T = TTE_MAP[d]
        ve_mids = [x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])]
        S_avg = mean(ve_mids) if ve_mids else 5000

        # Build timestamp -> underlying mid lookup
        ts_to_S = {}
        for x in all_prices[d].get('VELVETFRUIT_EXTRACT', []):
            ts_to_S[x[0]] = x[1]

        for k in STRIKES:
            prod = f'VEV_{k}'
            ivs = []
            for x in all_prices[d].get(prod, []):
                ts, mid_opt = x[0], x[1]
                S = ts_to_S.get(ts, S_avg)
                if mid_opt > 0.5:
                    iv = implied_vol(mid_opt, S, k, T, R, 'call')
                    if iv is not None:
                        ivs.append(iv)
            if ivs:
                iv_surface[(d, k)] = (mean(ivs), min(ivs), max(ivs), stdev(ivs) if len(ivs) > 1 else 0, len(ivs))

    print(f"  {'Strike':<8}", end="")
    for d in DAYS:
        print(f"  {'Day'+str(d)+' IV%':>10} {'StdIV%':>8} {'N':>5}", end="")
    print()

    for k in STRIKES:
        print(f"  {k:<8}", end="")
        for d in DAYS:
            entry = iv_surface.get((d, k))
            if entry:
                print(f"  {entry[0]*100:>10.2f} {entry[3]*100:>8.2f} {entry[4]:>5}", end="")
            else:
                print(f"  {'N/A':>10} {'N/A':>8} {'N/A':>5}", end="")
        print()

    # ── 4. GREEKS SNAPSHOT (using avg IV and avg S for each day) ───────────────
    print("\n" + "─" * 90)
    print("  4. GREEKS SNAPSHOT (avg mid S, avg IV per day)")
    print("─" * 90)

    for d in DAYS:
        T = TTE_MAP[d]
        ve_mids = [x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])]
        S_avg = mean(ve_mids) if ve_mids else 5000

        print(f"\n  Day {d}  |  S={S_avg:.1f}  TTE={T*365:.0f}d  r={R}")
        print(f"  {'Strike':<8} {'IV%':>7} {'Delta':>8} {'Gamma':>10} {'Vega':>8} {'Theta':>8} {'BSM':>8} {'MktMid':>8} {'Diff':>8}")

        for k in STRIKES:
            prod = f'VEV_{k}'
            entry = iv_surface.get((d, k))
            opt_mids = [x[1] for x in all_prices[d].get(prod, [])]
            mkt_mid = mean(opt_mids) if opt_mids else 0
            if entry:
                sigma = entry[0]
                g = compute_greeks(S_avg, k, T, R, sigma)
                bsm_price = bsm_call_price(S_avg, k, T, R, sigma)
                if g:
                    print(f"  {k:<8} {sigma*100:>7.2f} {g['delta']:>8.4f} {g['gamma']:>10.6f} "
                          f"{g['vega']:>8.3f} {g['theta']:>8.3f} {bsm_price:>8.2f} {mkt_mid:>8.2f} "
                          f"{mkt_mid-bsm_price:>8.2f}")
            else:
                print(f"  {k:<8} {'N/A':>7} {'N/A':>8} {'N/A':>10} {'N/A':>8} {'N/A':>8} {'N/A':>8} {mkt_mid:>8.2f} {'N/A':>8}")

    # ── 5. PUT-CALL PARITY ARB (since these are calls, synthetic put = C - S + K*exp(-rT)) ─
    print("\n" + "─" * 90)
    print("  5. PUT-CALL PARITY & INTRINSIC VALUE ARBITRAGE CHECK")
    print("─" * 90)

    for d in DAYS:
        T = TTE_MAP[d]
        ts_to_S = {}
        for x in all_prices[d].get('VELVETFRUIT_EXTRACT', []):
            ts_to_S[x[0]] = x[1]

        violations = []
        for k in STRIKES:
            prod = f'VEV_{k}'
            for x in all_prices[d].get(prod, []):
                ts, mid_opt, bid, ask = x[0], x[1], x[2], x[3]
                S = ts_to_S.get(ts)
                if S is None or bid is None or ask is None:
                    continue
                intrinsic = max(0, S - k)
                # Call should be >= intrinsic (no-arb lower bound)
                if bid < intrinsic - 0.5:
                    violations.append((d, k, ts, 'CALL_BELOW_INTRINSIC', bid, intrinsic, intrinsic - bid))
                # Call should be <= S (no-arb upper bound)
                if ask > S + 0.5:
                    violations.append((d, k, ts, 'CALL_ABOVE_S', ask, S, ask - S))

        if violations:
            print(f"\n  Day {d}: {len(violations)} no-arb violations found!")
            # Show top 10 by magnitude
            violations.sort(key=lambda v: -v[6])
            for v in violations[:10]:
                print(f"    K={v[1]} t={v[2]} type={v[3]} opt={v[4]:.1f} ref={v[5]:.1f} gap={v[6]:.2f}")
        else:
            print(f"\n  Day {d}: No basic no-arb violations.")

    # ── 6. BUTTERFLY ARBITRAGE ─────────────────────────────────────────────────
    print("\n" + "─" * 90)
    print("  6. BUTTERFLY SPREAD ARBITRAGE SCAN")
    print("  (Buy K1 + Buy K3 - 2*K2 call, for consecutive strikes)")
    print("─" * 90)

    # Find triplets with equal spacing
    for d in DAYS:
        ts_to_opts = defaultdict(dict)
        for k in STRIKES:
            prod = f'VEV_{k}'
            for x in all_prices[d].get(prod, []):
                ts = x[0]
                ts_to_opts[ts][k] = {'mid': x[1], 'bid': x[2], 'ask': x[3]}

        butterfly_opps = []
        for i in range(len(STRIKES)):
            for j in range(i+1, len(STRIKES)):
                for m in range(j+1, len(STRIKES)):
                    K1, K2, K3 = STRIKES[i], STRIKES[j], STRIKES[m]
                    # Need equal spacing for classic butterfly
                    if K3 - K2 != K2 - K1:
                        continue
                    for ts, opts in ts_to_opts.items():
                        if K1 in opts and K2 in opts and K3 in opts:
                            # Long butterfly: buy K1 + buy K3 - 2*sell K2
                            # Cost = ask(K1) + ask(K3) - 2*bid(K2)
                            if opts[K1]['ask'] and opts[K3]['ask'] and opts[K2]['bid']:
                                cost = opts[K1]['ask'] + opts[K3]['ask'] - 2 * opts[K2]['bid']
                                # Butterfly should have cost >= 0 (no-arb)
                                if cost < -0.5:
                                    butterfly_opps.append((d, K1, K2, K3, ts, cost))
                            # Short butterfly
                            if opts[K1]['bid'] and opts[K3]['bid'] and opts[K2]['ask']:
                                proceeds = opts[K1]['bid'] + opts[K3]['bid'] - 2 * opts[K2]['ask']
                                max_payoff = K2 - K1  # max butterfly payoff at K2
                                if proceeds > max_payoff + 0.5:
                                    butterfly_opps.append((d, K1, K2, K3, ts, proceeds - max_payoff))

        if butterfly_opps:
            print(f"\n  Day {d}: {len(butterfly_opps)} butterfly violations!")
            butterfly_opps.sort(key=lambda x: x[5])
            for b in butterfly_opps[:15]:
                print(f"    K=({b[1]},{b[2]},{b[3]}) t={b[4]} excess={b[5]:.2f}")
        else:
            print(f"\n  Day {d}: No butterfly arbitrage found (convexity holds).")

    # ── 7. VERTICAL SPREAD MONOTONICITY CHECK ────────────────────────────────
    print("\n" + "─" * 90)
    print("  7. VERTICAL SPREAD MONOTONICITY (call prices should decrease with strike)")
    print("─" * 90)

    for d in DAYS:
        ts_to_opts = defaultdict(dict)
        for k in STRIKES:
            prod = f'VEV_{k}'
            for x in all_prices[d].get(prod, []):
                ts_to_opts[x[0]][k] = x[1]

        violations = 0
        violation_examples = []
        for ts, opts in ts_to_opts.items():
            sorted_k = sorted(opts.keys())
            for i in range(len(sorted_k) - 1):
                if opts[sorted_k[i]] < opts[sorted_k[i+1]] - 0.5:
                    violations += 1
                    if len(violation_examples) < 5:
                        violation_examples.append((ts, sorted_k[i], opts[sorted_k[i]], sorted_k[i+1], opts[sorted_k[i+1]]))

        print(f"  Day {d}: {violations} monotonicity violations (C(K1) < C(K2) for K1 < K2)")
        for v in violation_examples:
            print(f"    t={v[0]}: C({v[1]})={v[2]:.1f} < C({v[3]})={v[4]:.1f}")

    # ── 8. BSM MISPRICING (systematic deviations from model) ───────────────────
    print("\n" + "─" * 90)
    print("  8. BSM MISPRICING ANALYSIS (market_mid vs BSM_fair per strike)")
    print("─" * 90)

    for d in DAYS:
        T = TTE_MAP[d]
        ts_to_S = {}
        for x in all_prices[d].get('VELVETFRUIT_EXTRACT', []):
            ts_to_S[x[0]] = x[1]

        # Use a single IV (ATM-weighted average) for the whole surface
        atm_ivs = []
        for k in STRIKES:
            entry = iv_surface.get((d, k))
            if entry and abs(k - mean([x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])])) < 500:
                atm_ivs.append(entry[0])
        flat_vol = mean(atm_ivs) if atm_ivs else 0.3

        print(f"\n  Day {d}: Flat vol = {flat_vol*100:.2f}%  (ATM-weighted average)")
        print(f"  {'Strike':<8} {'AvgMid':>8} {'BSM(flat)':>10} {'Diff':>8} {'OwnIV%':>8} {'Skew':>8}")

        for k in STRIKES:
            prod = f'VEV_{k}'
            opt_mids = [x[1] for x in all_prices[d].get(prod, [])]
            mkt_mid = mean(opt_mids) if opt_mids else 0
            ve_mids = [x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])]
            S_avg = mean(ve_mids) if ve_mids else 5000

            bsm_flat = bsm_call_price(S_avg, k, T, R, flat_vol)
            entry = iv_surface.get((d, k))
            own_iv = entry[0]*100 if entry else float('nan')
            skew = own_iv - flat_vol*100 if entry else float('nan')

            print(f"  {k:<8} {mkt_mid:>8.2f} {bsm_flat:>10.2f} {mkt_mid-bsm_flat:>8.2f} "
                  f"{own_iv:>8.2f} {skew:>+8.2f}")

    # ── 9. CROSS-ASSET CORRELATION ──────────────────────────────────────────────
    print("\n" + "─" * 90)
    print("  9. CROSS-ASSET CORRELATION (underlying returns vs option mid changes)")
    print("─" * 90)

    for d in DAYS:
        ve_data = all_prices[d].get('VELVETFRUIT_EXTRACT', [])
        ve_ts_mid = {x[0]: x[1] for x in ve_data}
        ve_timestamps = sorted(ve_ts_mid.keys())

        # Compute underlying returns (log returns of mid)
        ve_returns = {}
        for i in range(1, len(ve_timestamps)):
            t0, t1 = ve_timestamps[i-1], ve_timestamps[i]
            if ve_ts_mid[t0] > 0:
                ve_returns[t1] = math.log(ve_ts_mid[t1] / ve_ts_mid[t0])

        print(f"\n  Day {d}:")
        print(f"  {'Strike':<8} {'Corr(dS,dC)':>12} {'Beta':>8} {'R2':>8} {'N':>6}")

        for k in STRIKES:
            prod = f'VEV_{k}'
            opt_data = all_prices[d].get(prod, [])
            opt_ts_mid = {x[0]: x[1] for x in opt_data}

            opt_changes = {}
            opt_timestamps = sorted(opt_ts_mid.keys())
            for i in range(1, len(opt_timestamps)):
                t0, t1 = opt_timestamps[i-1], opt_timestamps[i]
                opt_changes[t1] = opt_ts_mid[t1] - opt_ts_mid[t0]

            # Align
            common_ts = sorted(set(ve_returns.keys()) & set(opt_changes.keys()))
            if len(common_ts) < 10:
                print(f"  {k:<8} {'N/A':>12} {'N/A':>8} {'N/A':>8} {len(common_ts):>6}")
                continue

            xs = [ve_returns[t] for t in common_ts]
            ys = [opt_changes[t] for t in common_ts]

            mx, my = mean(xs), mean(ys)
            sx, sy = stdev(xs), stdev(ys)
            if sx < 1e-12 or sy < 1e-12:
                print(f"  {k:<8} {'N/A':>12} {'N/A':>8} {'N/A':>8} {len(common_ts):>6}")
                continue

            cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - 1)
            corr = cov / (sx * sy)
            beta = cov / (sx**2)
            r2 = corr**2

            print(f"  {k:<8} {corr:>12.4f} {beta:>8.2f} {r2:>8.4f} {len(common_ts):>6}")

    # ── 10. VOLATILITY SMILE / SKEW ANALYSIS ──────────────────────────────────
    print("\n" + "─" * 90)
    print("  10. VOLATILITY SMILE / SKEW ANALYSIS")
    print("─" * 90)

    for d in DAYS:
        ve_mids = [x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])]
        S_avg = mean(ve_mids) if ve_mids else 5000
        print(f"\n  Day {d} (S_avg={S_avg:.0f}):")
        print(f"  {'Strike':<8} {'Moneyness':>10} {'IV%':>8} {'Smile':>30}")

        for k in STRIKES:
            entry = iv_surface.get((d, k))
            moneyness = k / S_avg
            if entry:
                iv_pct = entry[0] * 100
                bar = "█" * int(iv_pct / 2)
                print(f"  {k:<8} {moneyness:>10.4f} {iv_pct:>8.2f} {bar}")
            else:
                print(f"  {k:<8} {moneyness:>10.4f} {'N/A':>8}")

    # ── 11. IV TERM STRUCTURE (same strike across days) ───────────────────────
    print("\n" + "─" * 90)
    print("  11. IV TERM STRUCTURE (same strike across days = calendar arb check)")
    print("─" * 90)
    print(f"  {'Strike':<8}", end="")
    for d in DAYS:
        print(f"  {'Day'+str(d)+' IV%':>10} {'TTE':>5}", end="")
    print(f"  {'dIV/dT':>10}")

    for k in STRIKES:
        print(f"  {k:<8}", end="")
        ivs_for_strike = []
        for d in DAYS:
            entry = iv_surface.get((d, k))
            if entry:
                print(f"  {entry[0]*100:>10.2f} {TTE_MAP[d]*365:>5.0f}", end="")
                ivs_for_strike.append((TTE_MAP[d], entry[0]))
            else:
                print(f"  {'N/A':>10} {TTE_MAP[d]*365:>5.0f}", end="")
        # Calendar arb: total variance should increase with TTE
        if len(ivs_for_strike) >= 2:
            total_vars = [(t, iv**2 * t) for t, iv in ivs_for_strike]
            calendar_ok = all(total_vars[i][1] <= total_vars[i+1][1] + 1e-6 for i in range(len(total_vars)-1))
            status = "OK" if calendar_ok else "CAL_ARB!"
            print(f"  {status:>10}", end="")
        print()

    # ── 12. MARKET MAKING OPPORTUNITY ANALYSIS ─────────────────────────────────
    print("\n" + "─" * 90)
    print("  12. MARKET MAKING OPPORTUNITY (spread vs volatility analysis)")
    print("─" * 90)

    for d in DAYS:
        print(f"\n  Day {d}:")
        print(f"  {'Strike':<8} {'AvgSpread':>10} {'AvgMid':>8} {'Spread%':>9} {'MidStd':>8} {'Sharpe_MM':>10} {'Trades':>7}")

        for k in STRIKES:
            prod = f'VEV_{k}'
            entries = all_prices[d].get(prod, [])
            spreads = [x[3] - x[2] for x in entries if x[2] is not None and x[3] is not None]
            mids = [x[1] for x in entries]
            trades = all_trades[d].get(prod, [])

            if spreads and mids and len(mids) > 1:
                avg_spread = mean(spreads)
                avg_mid = mean(mids)
                mid_std = stdev(mids)
                spread_pct = avg_spread / avg_mid * 100 if avg_mid > 0.5 else float('inf')
                # Simple MM Sharpe proxy: spread / (2 * mid_std)
                mm_sharpe = avg_spread / (2 * mid_std) if mid_std > 0 else float('inf')
                print(f"  {k:<8} {avg_spread:>10.2f} {avg_mid:>8.2f} {spread_pct:>8.2f}% {mid_std:>8.2f} "
                      f"{mm_sharpe:>10.4f} {len(trades):>7}")
            else:
                print(f"  {k:<8} {'N/A':>10}")

    # ── 13. TRADE ACTIVITY SUMMARY ─────────────────────────────────────────────
    print("\n" + "─" * 90)
    print("  13. TRADE ACTIVITY SUMMARY")
    print("─" * 90)

    for d in DAYS:
        print(f"\n  Day {d}:")
        print(f"  {'Product':<25} {'Trades':>7} {'Volume':>8} {'AvgPrice':>10} {'MinPrice':>10} {'MaxPrice':>10}")

        for prod in ['VELVETFRUIT_EXTRACT'] + VEV_PRODUCTS:
            trades = all_trades[d].get(prod, [])
            if trades:
                prices = [t[1] for t in trades]
                vols = [t[2] for t in trades]
                print(f"  {prod:<25} {len(trades):>7} {sum(vols):>8} {mean(prices):>10.2f} "
                      f"{min(prices):>10.2f} {max(prices):>10.2f}")
            else:
                print(f"  {prod:<25} {'0':>7}")

    # ── 14. DELTA-HEDGING OPPORTUNITY ──────────────────────────────────────────
    print("\n" + "─" * 90)
    print("  14. DELTA-NEUTRAL STRATEGY ANALYSIS")
    print("─" * 90)

    for d in DAYS:
        T = TTE_MAP[d]
        ve_mids = [x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])]
        S_avg = mean(ve_mids) if ve_mids else 5000

        print(f"\n  Day {d}: For each strike, # of underlying shares to short per 1 long call")
        print(f"  {'Strike':<8} {'Delta':>7} {'HedgeQty':>9} {'Gamma':>10} {'GammaRisk':>10}")

        for k in STRIKES:
            entry = iv_surface.get((d, k))
            if entry:
                sigma = entry[0]
                g = compute_greeks(S_avg, k, T, R, sigma)
                if g:
                    # Gamma risk = gamma * S^2 * sigma^2 * T (dollar gamma for 1-day)
                    gamma_risk = g['gamma'] * S_avg**2 * sigma**2 * (1/365)
                    print(f"  {k:<8} {g['delta']:>7.4f} {-g['delta']:>9.4f} {g['gamma']:>10.6f} {gamma_risk:>10.2f}")

    # ── 15. KEY FINDINGS SUMMARY ──────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("  SUMMARY OF KEY FINDINGS")
    print("=" * 90)

    print("""
  1. IV SMILE: Check if deep OTM/ITM options have systematically higher IV
     than ATM options (classic volatility smile).

  2. BSM MISPRICING: Any systematic MktMid - BSM(flat_vol) > spread indicates
     a persistent arb opportunity via delta-hedged option trading.

  3. BUTTERFLY ARB: If C(K1) + C(K3) - 2*C(K2) < 0 for equally-spaced strikes,
     this is a risk-free arbitrage (buy the butterfly for negative cost).

  4. MARKET MAKING: Strikes with high Sharpe_MM (spread/volatility ratio) and
     decent trade volume are the best MM candidates.

  5. CROSS-ASSET: High correlation (>0.8) between underlying returns and option
     price changes confirms delta exposure. Beta ≈ BSM delta validates the model.

  6. CALENDAR ARB: If total variance (IV^2 * T) decreases with longer TTE for
     same strike, calendar spread arbitrage exists.
    """)

    return all_prices, all_trades


if __name__ == '__main__':
    run_analysis()
