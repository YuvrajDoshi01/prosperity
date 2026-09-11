#!/usr/bin/env python3
"""
CORRECTED Arbitrage Analysis — accounts for:
  1. No early exercise (can't realize intrinsic directly)
  2. Must cross the spread on BOTH legs (buy at ask, sell at bid)
  3. Settlement: options settle at max(0, S_expiry - K) at end of round 7
  4. Underlying positions mark-to-market
"""

import csv, os, math
from collections import defaultdict
from statistics import mean, stdev

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
DAYS = [0, 1, 2]

def load_prices(day):
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

print("=" * 100)
print("  CORRECTED ARB ANALYSIS — actual round-trip economics")
print("=" * 100)

# ══════════════════════════════════════════════════════════════════════════════
# 1. CONVERSION / REVERSAL ARB (put-call parity with real bid/ask)
# ══════════════════════════════════════════════════════════════════════════════
#
# These are CALL options. Put-call parity: C - P = S - K*exp(-rT)
# With r=0: C = P + S - K, or equivalently C - S + K = P >= 0
#
# Conversion (lock in K): buy call at ask_C, short underlying at bid_S
#   At expiry: option pays max(0, S-K), short costs S
#   If S > K (very likely for deep ITM): net = (S-K) - S = -K
#   Cash received at open: bid_S - ask_C
#   PnL = (bid_S - ask_C) - K   ... need this > 0
#
# Reversal: sell call at bid_C, buy underlying at ask_S
#   At expiry: owe max(0, S-K), long pays S
#   If S > K: net = S - (S-K) = K
#   Cash paid at open: ask_S - bid_C
#   PnL = K - (ask_S - bid_C)   ... need this > 0

print("\n" + "─" * 100)
print("  1. CONVERSION ARB: buy call + short underlying → lock in K at expiry")
print("     PnL = bid_S - ask_C - K  (need > 0)")
print("─" * 100)

for d in DAYS:
    prices = load_prices(d)
    ve_data = {x[0]: x for x in prices.get('VELVETFRUIT_EXTRACT', [])}

    print(f"\n  Day {d}:")
    print(f"  {'Strike':<8} {'AvgPnL':>10} {'MaxPnL':>10} {'MinPnL':>10} {'%Positive':>10} {'AvgGap':>10} {'N':>6}")

    for k in STRIKES:
        prod = f'VEV_{k}'
        opt_data = prices.get(prod, [])
        pnls = []
        for x in opt_data:
            ts = x[0]
            ask_C = x[3]  # option ask
            ve = ve_data.get(ts)
            if ve is None or ask_C is None or ve[2] is None:
                continue
            bid_S = ve[2]  # underlying bid
            pnl = bid_S - ask_C - k
            pnls.append(pnl)

        if pnls:
            pos_pct = sum(1 for p in pnls if p > 0) / len(pnls) * 100
            print(f"  {k:<8} {mean(pnls):>10.2f} {max(pnls):>10.2f} {min(pnls):>10.2f} "
                  f"{pos_pct:>9.1f}% {mean(pnls):>10.2f} {len(pnls):>6}")

print("\n" + "─" * 100)
print("  2. REVERSAL ARB: sell call + buy underlying → lock in K at expiry")
print("     PnL = K - ask_S + bid_C  (need > 0)")
print("─" * 100)

for d in DAYS:
    prices = load_prices(d)
    ve_data = {x[0]: x for x in prices.get('VELVETFRUIT_EXTRACT', [])}

    print(f"\n  Day {d}:")
    print(f"  {'Strike':<8} {'AvgPnL':>10} {'MaxPnL':>10} {'MinPnL':>10} {'%Positive':>10} {'N':>6}")

    for k in STRIKES:
        prod = f'VEV_{k}'
        opt_data = prices.get(prod, [])
        pnls = []
        for x in opt_data:
            ts = x[0]
            bid_C = x[2]  # option bid
            ve = ve_data.get(ts)
            if ve is None or bid_C is None or ve[3] is None:
                continue
            ask_S = ve[3]  # underlying ask
            pnl = k - ask_S + bid_C
            pnls.append(pnl)

        if pnls:
            pos_pct = sum(1 for p in pnls if p > 0) / len(pnls) * 100
            print(f"  {k:<8} {mean(pnls):>10.2f} {max(pnls):>10.2f} {min(pnls):>10.2f} "
                  f"{pos_pct:>9.1f}% {len(pnls):>6}")

# ══════════════════════════════════════════════════════════════════════════════
# 3. BOX SPREAD (synthetic forward at two strikes)
# ══════════════════════════════════════════════════════════════════════════════
# Since these are all calls (no puts traded), we can't do a traditional box.
# But we CAN do a call spread arb:
#   Bull call spread: buy C(K1) at ask, sell C(K2) at bid, K1 < K2
#   Max payoff at expiry = K2 - K1 (if S > K2)
#   Cost = ask_C(K1) - bid_C(K2)
#   If cost < 0: FREE MONEY (negative cost spread with non-negative payoff)
#   If cost > K2 - K1: GUARANTEED LOSS (pay more than max payoff)

print("\n" + "─" * 100)
print("  3. VERTICAL SPREAD ARB (using actual bid/ask)")
print("     Bull spread: buy C(K1) at ask, sell C(K2) at bid")
print("     Arb if cost < 0 (free money) or cost > K2-K1 (guaranteed loss for seller)")
print("─" * 100)

for d in DAYS:
    prices = load_prices(d)

    arb_opps = []
    # Build timestamp -> strike -> (bid, ask)
    ts_opts = defaultdict(dict)
    for k in STRIKES:
        prod = f'VEV_{k}'
        for x in prices.get(prod, []):
            if x[2] is not None and x[3] is not None:
                ts_opts[x[0]][k] = (x[2], x[3])

    for ts, opts in ts_opts.items():
        sorted_k = sorted(opts.keys())
        for i in range(len(sorted_k)):
            for j in range(i+1, len(sorted_k)):
                K1, K2 = sorted_k[i], sorted_k[j]
                bid1, ask1 = opts[K1]
                bid2, ask2 = opts[K2]
                max_payoff = K2 - K1

                # Bull spread cost (buy low strike at ask, sell high strike at bid)
                cost = ask1 - bid2
                if cost < -0.01:  # negative cost = free arb
                    arb_opps.append(('NEGATIVE_COST', K1, K2, ts, cost, max_payoff))
                if cost > max_payoff + 0.01:  # overpay = sell this spread
                    arb_opps.append(('OVERPAY', K1, K2, ts, cost - max_payoff, max_payoff))

    if arb_opps:
        print(f"\n  Day {d}: {len(arb_opps)} vertical spread arb opportunities!")
        by_type = defaultdict(list)
        for a in arb_opps:
            by_type[a[0]].append(a)
        for typ, opps in by_type.items():
            opps.sort(key=lambda x: -abs(x[4]))
            print(f"    {typ}: {len(opps)} occurrences, best edge = {opps[0][4]:.2f}")
            for o in opps[:5]:
                print(f"      K=({o[1]},{o[2]}) t={o[3]} edge={o[4]:.2f} max_payoff={o[5]}")
    else:
        print(f"\n  Day {d}: No vertical spread arb (bid/ask respects monotonicity).")

# ══════════════════════════════════════════════════════════════════════════════
# 4. BUTTERFLY SPREAD ARB (actual bid/ask)
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "─" * 100)
print("  4. BUTTERFLY ARB (actual bid/ask, not mid prices)")
print("     Buy wing calls at ask, sell body at bid")
print("     Arb if net cost < 0")
print("─" * 100)

for d in DAYS:
    prices = load_prices(d)
    ts_opts = defaultdict(dict)
    for k in STRIKES:
        prod = f'VEV_{k}'
        for x in prices.get(prod, []):
            if x[2] is not None and x[3] is not None:
                ts_opts[x[0]][k] = (x[2], x[3])

    arb_opps = []
    for ts, opts in ts_opts.items():
        sorted_k = sorted(opts.keys())
        for i in range(len(sorted_k)):
            for j in range(i+1, len(sorted_k)):
                for m in range(j+1, len(sorted_k)):
                    K1, K2, K3 = sorted_k[i], sorted_k[j], sorted_k[m]
                    if K3 - K2 != K2 - K1:
                        continue
                    b1, a1 = opts[K1]
                    b2, a2 = opts[K2]
                    b3, a3 = opts[K3]

                    # Long butterfly: buy wings at ask, sell body at bid
                    cost = a1 + a3 - 2 * b2
                    if cost < -0.01:
                        arb_opps.append((K1, K2, K3, ts, cost))

                    # Short butterfly: sell wings at bid, buy body at ask
                    max_payoff = K2 - K1
                    proceeds = b1 + b3 - 2 * a2
                    if proceeds > max_payoff + 0.01:
                        arb_opps.append((K1, K2, K3, ts, proceeds - max_payoff))

    if arb_opps:
        print(f"\n  Day {d}: {len(arb_opps)} butterfly arb opportunities!")
        arb_opps.sort(key=lambda x: x[4])
        for o in arb_opps[:10]:
            print(f"    K=({o[0]},{o[1]},{o[2]}) t={o[3]} edge={o[4]:.2f}")
    else:
        print(f"\n  Day {d}: No butterfly arb with real bid/ask.")

# ══════════════════════════════════════════════════════════════════════════════
# 5. BSM MISPRICING vs ACTUAL SPREAD (is the edge bigger than the spread?)
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "─" * 100)
print("  5. BSM MISPRICING vs SPREAD (can you profit after crossing the spread?)")
print("     Using per-strike IV. Edge = |BSM_fair - mid| - half_spread")
print("─" * 100)

def norm_cdf(x):
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5*t + a4)*t) + a3)*t + a2)*t + a1)*t * math.exp(-x*x/2.0)
    return 0.5 * (1.0 + sign * y)

def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

def bsm_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(0, S - K)
    d1 = (math.log(S/K) + 0.5*sigma**2*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return S * norm_cdf(d1) - K * norm_cdf(d2)

def imp_vol(price, S, K, T, tol=1e-6):
    if T <= 1e-10 or price <= max(0, S-K) + 1e-8:
        return None
    sigma = 0.3
    for _ in range(200):
        if sigma <= 0.001: sigma = 0.001
        d1 = (math.log(S/K) + 0.5*sigma**2*T) / (sigma*math.sqrt(T))
        d2 = d1 - sigma*math.sqrt(T)
        p = S * norm_cdf(d1) - K * norm_cdf(d2)
        vega = S * norm_pdf(d1) * math.sqrt(T)
        if vega < 1e-12: return None
        sigma -= (p - price) / vega
        if abs(p - price) < tol:
            return sigma if 0.001 < sigma < 5.0 else None
    return None

TTE_MAP = {0: 8/365, 1: 7/365, 2: 6/365}

for d in DAYS:
    T = TTE_MAP[d]
    prices = load_prices(d)
    ve_ts = {x[0]: x[1] for x in prices.get('VELVETFRUIT_EXTRACT', [])}

    print(f"\n  Day {d} (TTE={T*365:.0f}d):")
    print(f"  {'Strike':<8} {'AvgMid':>8} {'BSM_fair':>10} {'AvgSpread':>10} {'HalfSprd':>10} "
          f"{'|Misprice|':>10} {'NetEdge':>10} {'Tradeable?':>12}")

    for k in [5000, 5100, 5200, 5300, 5400, 5500]:
        prod = f'VEV_{k}'
        opt_data = prices.get(prod, [])

        # Compute avg IV from all ticks
        ivs = []
        for x in opt_data:
            S = ve_ts.get(x[0])
            if S and x[1] > 0.5:
                iv = imp_vol(x[1], S, k, T)
                if iv: ivs.append(iv)

        if not ivs:
            continue

        avg_iv = mean(ivs)
        mids = [x[1] for x in opt_data]
        spreads = [x[3] - x[2] for x in opt_data if x[2] is not None and x[3] is not None]

        # BSM fair using average IV (this IS the market's own fair value)
        avg_S = mean(ve_ts[x[0]] for x in opt_data if x[0] in ve_ts)
        bsm_fair = bsm_call(avg_S, k, T, avg_iv)
        avg_mid = mean(mids)
        avg_spread = mean(spreads)
        half_spread = avg_spread / 2
        mispricing = abs(avg_mid - bsm_fair)
        net_edge = mispricing - half_spread

        tradeable = "YES ✓" if net_edge > 0.5 else "marginal" if net_edge > 0 else "NO ✗"
        print(f"  {k:<8} {avg_mid:>8.2f} {bsm_fair:>10.2f} {avg_spread:>10.2f} {half_spread:>10.2f} "
              f"{mispricing:>10.2f} {net_edge:>+10.2f} {tradeable:>12}")

# ══════════════════════════════════════════════════════════════════════════════
# 6. INTRADAY MEAN-REVERSION: buy/sell mispriced options and close same day
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "─" * 100)
print("  6. INTRADAY MEAN REVERSION: buy cheap / sell rich vs BSM, close within N ticks")
print("     Simulates: enter when |mid - BSM| > threshold, exit when it reverts")
print("─" * 100)

for d in DAYS:
    T = TTE_MAP[d]
    prices = load_prices(d)
    ve_ts_data = {x[0]: x[1] for x in prices.get('VELVETFRUIT_EXTRACT', [])}

    print(f"\n  Day {d}:")
    print(f"  {'Strike':<8} {'AvgResidual':>12} {'StdResidual':>12} {'AC(1)':>8} {'AC(5)':>8} "
          f"{'MeanRev?':>10} {'HalfLife':>10}")

    for k in [5000, 5100, 5200, 5300, 5400, 5500]:
        prod = f'VEV_{k}'
        opt_data = prices.get(prod, [])

        # Compute IV from a rolling window, then track residuals
        # Simpler: compute BSM residual = mid - BSM(rolling_avg_IV)
        # Use first 500 ticks to calibrate IV, then track residuals

        ivs_all = []
        residuals = []
        timestamps = []
        for x in opt_data:
            S = ve_ts_data.get(x[0])
            if S is None or x[1] <= 0.5:
                continue
            iv = imp_vol(x[1], S, k, T)
            if iv is None:
                continue
            ivs_all.append(iv)
            timestamps.append(x[0])

        if len(ivs_all) < 200:
            continue

        # Use expanding window IV
        cum_iv = 0
        for i in range(len(ivs_all)):
            cum_iv += ivs_all[i]
            avg_iv = cum_iv / (i + 1)
            if i > 50:  # skip initial calibration
                S = ve_ts_data.get(timestamps[i])
                if S:
                    bsm_fair = bsm_call(S, k, T, avg_iv)
                    opt_mid = next(x[1] for x in opt_data if x[0] == timestamps[i])
                    residuals.append(opt_mid - bsm_fair)

        if len(residuals) < 100:
            continue

        avg_res = mean(residuals)
        std_res = stdev(residuals)

        # Autocorrelation
        def autocorr(xs, lag):
            n = len(xs) - lag
            mx = mean(xs)
            num = sum((xs[i]-mx)*(xs[i+lag]-mx) for i in range(n))
            den = sum((x-mx)**2 for x in xs)
            return num / den if den > 0 else 0

        ac1 = autocorr(residuals, 1)
        ac5 = autocorr(residuals, 5)

        mean_rev = "YES ⚡" if ac1 > 0.5 else "weak" if ac1 > 0.2 else "NO"
        half_life = -1 / math.log(abs(ac1)) if 0 < abs(ac1) < 1 else float('inf')
        hl_str = f"{half_life:.1f}" if half_life < 1000 else "∞"

        print(f"  {k:<8} {avg_res:>12.4f} {std_res:>12.4f} {ac1:>8.4f} {ac5:>8.4f} "
              f"{mean_rev:>10} {hl_str:>10}")

# ══════════════════════════════════════════════════════════════════════════════
# 7. THE REAL QUESTION: where's the actual edge?
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 100)
print("  SUMMARY: WHERE IS THE REAL EDGE?")
print("=" * 100)
print("""
  DEBUNKED:
  ✗ Intrinsic value arb on VEV_4000 — can't exercise early, spread eats the gap
  ✗ Latency arb — underlying and options update same tick (lag=0)
  ✗ Butterfly arb — convexity holds with real bid/ask
  ✗ Direction prediction — P(same sign) ≈ 50%, zero E[PnL]

  STILL CHECKING:
  ? Conversion/reversal arb — check results above
  ? Vertical spread arb — check results above
  ? BSM mispricing vs spread — check if net edge > 0
  ? Intraday mean reversion of BSM residuals — check AC(1) above
""")
