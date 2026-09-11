"""
Supplement: Compute bid-ask spread in IV terms per strike
to assess whether smile residuals exceed transaction costs.
"""

import csv
import math
import numpy as np
from collections import defaultdict

STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
STRIKE_NAMES = {k: f"VEV_{k}" for k in STRIKES}
UNDERLYING = "VELVETFRUIT_EXTRACT"
DATA_DIR = "/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round3"

TTE_STARTS = {0: 8.0, 1: 6.0, 2: 5.0}
YEAR = 250.0
TICKS_PER_DAY = 10000
TICK_STEP = 100

def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bs_call(S, K, T, sigma):
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * norm_cdf(d1) - K * norm_cdf(d2)

def implied_vol_bisection(S, K, T, C_market, tol=1e-6, max_iter=200):
    intrinsic = max(S - K, 0.0)
    if C_market < intrinsic - 0.5:
        return None
    if C_market <= intrinsic + 0.01:
        return None
    if T <= 1e-10:
        return None
    lo, hi = 0.001, 5.0
    c_lo = bs_call(S, K, T, lo)
    c_hi = bs_call(S, K, T, hi)
    if C_market < c_lo or C_market > c_hi:
        return None
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        c_mid = bs_call(S, K, T, mid)
        if abs(c_mid - C_market) < tol:
            return mid
        if c_mid < C_market:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0

# For each strike, compute IV(bid) and IV(ask) and report spread in IV terms
spread_iv = {d: {K: [] for K in STRIKES} for d in range(3)}
spread_price = {d: {K: [] for K in STRIKES} for d in range(3)}

for day in range(3):
    filepath = f"{DATA_DIR}/prices_round_3_day_{day}.csv"
    # Load raw bid/ask
    tick_data = defaultdict(dict)
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            ts = int(row['timestamp'])
            product = row['product']
            bid1 = row.get('bid_price_1', '')
            ask1 = row.get('ask_price_1', '')
            if bid1 and ask1:
                try:
                    b = float(bid1)
                    a = float(ask1)
                    if b > 0 and a > 0:
                        tick_data[ts][product] = (b, a)
                except ValueError:
                    pass

    timestamps = sorted(tick_data.keys())
    for ts in timestamps:
        td = tick_data[ts]
        if UNDERLYING not in td:
            continue
        S = (td[UNDERLYING][0] + td[UNDERLYING][1]) / 2.0

        day_frac = ts / (TICKS_PER_DAY * TICK_STEP - TICK_STEP)
        tte_days = TTE_STARTS[day] - day_frac
        T = tte_days / YEAR
        if T <= 1e-10:
            continue

        for K in STRIKES:
            name = STRIKE_NAMES[K]
            if name not in td:
                continue
            bid, ask = td[name]
            if bid <= 0 or ask <= 0:
                continue

            iv_bid = implied_vol_bisection(S, K, T, bid)
            iv_ask = implied_vol_bisection(S, K, T, ask)
            if iv_bid is not None and iv_ask is not None:
                spread_iv[day][K].append(iv_ask - iv_bid)
                spread_price[day][K].append(ask - bid)

print("=" * 90)
print("BID-ASK SPREAD IN IV TERMS (and price terms) PER STRIKE PER DAY")
print("=" * 90)
header = f"{'Strike':>8}"
for d in range(3):
    header += f"  {'D'+str(d)+' IV spr':>10}  {'D'+str(d)+' $ spr':>10}"
print(header)
print("-" * 90)

for K in STRIKES:
    row = f"{K:>8}"
    for d in range(3):
        if len(spread_iv[d][K]) > 10:
            avg_iv_spr = np.mean(spread_iv[d][K])
            avg_p_spr = np.mean(spread_price[d][K])
            row += f"  {avg_iv_spr:>10.6f}  {avg_p_spr:>10.2f}"
        else:
            row += f"  {'N/A':>10}  {'N/A':>10}"
    print(row)

print("\n\nCOMPARISON: |Avg Residual| vs Avg IV Spread (all-day average)")
print("=" * 70)
print(f"{'Strike':>8}  {'|Resid|':>10}  {'IV Spread':>10}  {'Ratio':>10}  {'Tradeable?':>12}")
print("-" * 55)

# Load residual averages from the main analysis (hardcoded from output)
avg_resid = {
    4000: 0.006762, 4500: 0.008769, 5000: 0.004610, 5100: 0.003415,
    5200: 0.003606, 5300: 0.006293, 5400: 0.009343, 5500: 0.003784
}

for K in STRIKES:
    all_iv_spr = []
    for d in range(3):
        all_iv_spr.extend(spread_iv[d][K])
    if len(all_iv_spr) > 10 and K in avg_resid:
        avg_spr = np.mean(all_iv_spr)
        res = avg_resid[K]
        ratio = res / avg_spr if avg_spr > 0 else 0
        tradeable = "YES" if ratio > 0.5 else "NO"
        print(f"{K:>8}  {res:>10.6f}  {avg_spr:>10.6f}  {ratio:>10.2f}  {tradeable:>12}")
    else:
        print(f"{K:>8}  {'N/A':>45}")
