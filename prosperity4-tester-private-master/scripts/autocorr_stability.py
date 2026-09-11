"""3-day autocorrelation stability check.

Validates the bimodal autocorr finding (deep ITM ~0, ATM ~0.95+) is consistent
across all 3 R3 2026 days, not a day-2 artifact.
"""
import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

R3_DATA = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round3")


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * ncdf(d1) - K * ncdf(d2)


def implied_vol(market_price, S, K, T, lo=1e-4, hi=5.0, iters=60):
    intrinsic = max(S - K, 0.0)
    if market_price <= intrinsic + 1e-6 or T <= 0 or market_price >= S:
        return None
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if bs_call(S, K, T, mid) < market_price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def autocorr(series, lag=1):
    if len(series) < lag + 2:
        return None
    s1 = series[:-lag]
    s2 = series[lag:]
    m = statistics.mean(series)
    n = sum((s1[i] - m) * (s2[i] - m) for i in range(len(s1)))
    d = sum((x - m) ** 2 for x in series)
    return n / d if d > 0 else None


def load_day(day):
    path = R3_DATA / f"prices_round_3_day_{day}.csv"
    out = defaultdict(dict)
    with open(path, encoding='utf-8') as f:
        rdr = csv.DictReader(f, delimiter=';')
        for row in rdr:
            try:
                ts = int(row['timestamp']); prod = row['product']
                mid = float(row['mid_price']) if row['mid_price'] else None
            except (ValueError, KeyError):
                continue
            if mid and mid > 0:
                out[prod][ts] = mid
    return out


def analyze_day(day):
    """Return per-strike (mean_iv, dev_std, ac_lag1) for VEV vouchers."""
    prices = load_day(day)
    spot_dict = prices.get("VELVETFRUIT_EXTRACT", {})
    if not spot_dict:
        return None

    # TTE: starts at 5d for R3, decreases by 1 per day
    tte_days = 5.0 - day
    T = tte_days / 250.0

    strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
    results = {}

    timestamps = sorted(spot_dict.keys())
    iv_series_per_strike = {K: [] for K in strikes}
    for ts in timestamps:
        S = spot_dict[ts]
        for K in strikes:
            sym = f"VEV_{K}"
            mkt = prices.get(sym, {}).get(ts)
            if mkt is None:
                continue
            iv = implied_vol(mkt, S, K, T)
            if iv is not None:
                iv_series_per_strike[K].append(iv)

    for K in strikes:
        iv_list = iv_series_per_strike[K]
        if len(iv_list) > 100 and 0.001 < statistics.mean(iv_list) < 1.0:
            mean_iv = statistics.mean(iv_list)
        else:
            mean_iv = None

        # Deviations using mean_iv as fixed sigma
        deviations = []
        sym = f"VEV_{K}"
        sigma = mean_iv if mean_iv else 0.0
        for ts in timestamps:
            S = spot_dict[ts]
            mkt = prices.get(sym, {}).get(ts)
            if mkt is None:
                continue
            fair = bs_call(S, K, T, sigma)
            deviations.append(mkt - fair)

        if len(deviations) >= 50:
            dev_std = statistics.stdev(deviations)
            ac1 = autocorr(deviations, lag=1)
            results[K] = (mean_iv, dev_std, ac1, len(deviations))
        else:
            results[K] = (mean_iv, None, None, len(deviations))

    return results, tte_days


def main():
    print(f"{'Strike':>6} | {'Day 0 (T=5)':>30} | {'Day 1 (T=4)':>30} | {'Day 2 (T=3)':>30}")
    print(f"{'':>6} | {'IV':>5} {'devstd':>7} {'ac(1)':>7} {'n':>6} | {'IV':>5} {'devstd':>7} {'ac(1)':>7} {'n':>6} | {'IV':>5} {'devstd':>7} {'ac(1)':>7} {'n':>6}")
    print("-" * 110)

    day_results = {}
    for d in [0, 1, 2]:
        r, _ = analyze_day(d)
        day_results[d] = r

    strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
    for K in strikes:
        cells = []
        for d in [0, 1, 2]:
            r = day_results[d].get(K)
            if not r:
                cells.append(f"{'no data':>30}")
                continue
            iv, ds, ac, n = r
            iv_s = f"{iv*100:.1f}%" if iv else "—"
            ds_s = f"{ds:.3f}" if ds else "—"
            ac_s = f"{ac:.3f}" if ac is not None else "—"
            cells.append(f"{iv_s:>5} {ds_s:>7} {ac_s:>7} {n:>6}")
        print(f"{K:>6} | {cells[0]} | {cells[1]} | {cells[2]}")

    print()
    print("Verdict: bimodal autocorr is " + ("STABLE across days" if all(
        day_results[d].get(4000, (None,)*4)[2] is not None and
        day_results[d].get(4000)[2] < 0.1 and
        day_results[d].get(5300, (None,)*4)[2] is not None and
        day_results[d].get(5300)[2] > 0.9
        for d in [0, 1, 2]
    ) else "NOT stable — investigate"))


if __name__ == "__main__":
    main()
