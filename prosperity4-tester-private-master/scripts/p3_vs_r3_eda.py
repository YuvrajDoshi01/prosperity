"""Cross-year EDA: P3 2025 round 3 vs R3 2026.

Validates Nancy's findings (Discord 2026-04-25):
  1. IV smile shape (P3: pronounced quadratic / R3: flat)
  2. BS-fair-value deviation lag-1 autocorr (P3: negative oscillate / R3: +0.99 drift)
  3. OU parameters for stable products (Resin/Kelp ↔ HP)

Usage:
    python scripts/p3_vs_r3_eda.py [day_filter]
"""
import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

P3 = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/previous-prosperity/p3_r3")
R3_DATA = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round3")

# Cumulative normal via erf
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


def load_prices(path, day_filter=None):
    """Returns dict[product] -> list[(ts, mid)] sorted by ts."""
    out = defaultdict(list)
    with open(path, newline='', encoding='utf-8') as f:
        rdr = csv.DictReader(f, delimiter=';')
        for row in rdr:
            if day_filter is not None and int(row['day']) != day_filter:
                continue
            try:
                ts = int(row['timestamp']); prod = row['product']
                mid = float(row['mid_price']) if row['mid_price'] else None
            except (KeyError, ValueError):
                continue
            if mid and mid > 0:
                out[prod].append((ts, mid))
    for k in out:
        out[k].sort()
    return out


def autocorr(series, lag=1):
    """Lag-k autocorrelation of a series."""
    if len(series) < lag + 2:
        return None
    s1 = series[:-lag]
    s2 = series[lag:]
    m = statistics.mean(series)
    n = sum((s1[i] - m) * (s2[i] - m) for i in range(len(s1)))
    d = sum((x - m) ** 2 for x in series)
    return n / d if d > 0 else None


def fit_smile_parabola(ivs_by_strike, k_atm):
    """Fit IV(K) = a*(K-K_atm)^2 + b*(K-K_atm) + c. Return (a, b, c, R^2)."""
    pts = [(K - k_atm, iv) for K, iv in ivs_by_strike.items() if iv is not None]
    if len(pts) < 3:
        return None
    n = len(pts)
    # Normal equations
    sx = sy = sxx = sxxx = sxxxx = sxy = sxxy = 0.0
    for x, y in pts:
        x2 = x * x
        sx += x; sy += y; sxx += x2; sxxx += x2 * x; sxxxx += x2 * x2
        sxy += x * y; sxxy += x2 * y
    M = [[n, sx, sxx], [sx, sxx, sxxx], [sxx, sxxx, sxxxx]]
    rhs = [sy, sxy, sxxy]
    det = (
        M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1])
        - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0])
        + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0])
    )
    if abs(det) < 1e-12:
        return None
    def cof(i, j):
        m2 = [[M[r][c] for c in range(3) if c != j] for r in range(3) if r != i]
        return ((-1) ** (i + j)) * (m2[0][0] * m2[1][1] - m2[0][1] * m2[1][0])
    inv = 1.0 / det
    a = (cof(0, 0) * rhs[0] + cof(1, 0) * rhs[1] + cof(2, 0) * rhs[2]) * inv
    b = (cof(0, 1) * rhs[0] + cof(1, 1) * rhs[1] + cof(2, 1) * rhs[2]) * inv
    c = (cof(0, 2) * rhs[0] + cof(1, 2) * rhs[1] + cof(2, 2) * rhs[2]) * inv
    # NOTE: sign of a/b conventions here are reversed from common (a=quadratic, b=linear, c=intercept)
    # Compute R^2
    y_mean = sy / n
    ss_res = sum((y - (c + b * x + a * x * x)) ** 2 for x, y in pts)
    ss_tot = sum((y - y_mean) ** 2 for x, y in pts)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    return (a, b, c, r2)


def ou_half_life(series):
    """Estimate OU half-life via lag-1 AR fit: x_{t+1} - mu = phi*(x_t - mu)
    half_life = -log(2) / log(|phi|)."""
    if len(series) < 50:
        return None, None, None
    mu = statistics.mean(series)
    s1 = [x - mu for x in series[:-1]]
    s2 = [x - mu for x in series[1:]]
    num = sum(a * b for a, b in zip(s1, s2))
    den = sum(a * a for a in s1)
    if den < 1e-9:
        return mu, None, None
    phi = num / den
    if not (0 < phi < 1):
        return mu, phi, None
    half_life = -math.log(2) / math.log(phi)
    return mu, phi, half_life


def analyze_underlying(prices, name):
    """Compute mid stats + OU half-life for the underlying."""
    series = [m for _, m in prices.get(name, [])]
    if not series:
        return f"{name}: no data"
    mu, phi, hl = ou_half_life(series)
    return (f"{name}: n={len(series)} mean={statistics.mean(series):.2f} "
            f"std={statistics.stdev(series):.2f} "
            f"min={min(series):.0f} max={max(series):.0f} "
            f"OU mu={mu:.2f} phi={phi if phi else float('nan'):.4f} "
            f"half_life={hl if hl else float('nan'):.1f}")


def analyze_options(prices, underlying_name, voucher_strikes, tte_days):
    """Build smile + autocorr per strike."""
    underlying = dict(prices.get(underlying_name, []))
    if not underlying:
        return f"No underlying data for {underlying_name}"

    T = tte_days / 250.0   # standard 250 trading-day-year convention

    # For each timestamp, compute mid IV using market mid
    iv_series = {K: [] for K in voucher_strikes}
    spot_series = []

    timestamps = sorted(set(t for t, _ in prices.get(underlying_name, [])))
    for ts in timestamps:
        S = underlying.get(ts)
        if S is None: continue
        spot_series.append(S)
        for K in voucher_strikes:
            sym = f"VOLCANIC_ROCK_VOUCHER_{K}" if "ROCK" in underlying_name.upper() else f"VEV_{K}"
            voucher_mids = dict(prices.get(sym, []))
            mkt = voucher_mids.get(ts)
            if mkt is None:
                continue
            iv = implied_vol(mkt, S, K, T)
            if iv is not None:
                iv_series[K].append(iv)

    out = [f"Underlying {underlying_name}: spot mean={statistics.mean(spot_series):.2f}, T={tte_days:.2f}d"]

    # Filter to LIQUID strikes only: at least 100 IV samples AND IV in reasonable range
    spot_mean = statistics.mean(spot_series)
    liquid_strikes = []
    mean_iv = {}
    for K in voucher_strikes:
        if len(iv_series[K]) > 100:
            mu = statistics.mean(iv_series[K])
            if 0.001 < mu < 1.0:
                liquid_strikes.append(K)
                mean_iv[K] = mu
    out.append(f"Liquid strikes (n>100, IV in [0.001, 1.0]): {liquid_strikes}")
    for K in liquid_strikes:
        out.append(f"  K={K}: n={len(iv_series[K])}, mean IV={mean_iv[K]:.4f} ({mean_iv[K]*100:.2f}%)")

    if len(liquid_strikes) >= 3:
        # Use moneyness m = log(K/S)/sqrt(T) per Nancy
        k_atm = min(liquid_strikes, key=lambda k: abs(k - spot_mean))
        moneyness_iv = {}
        for K in liquid_strikes:
            m = math.log(K / spot_mean) / math.sqrt(T)
            moneyness_iv[m] = mean_iv[K]
        # Fit IV(m) = c + b*m + a*m^2
        pts = [(m, iv) for m, iv in moneyness_iv.items()]
        pts.sort()
        n = len(pts)
        sx = sy = sxx = sxxx = sxxxx = sxy = sxxy = 0.0
        for x, y in pts:
            x2 = x * x
            sx += x; sy += y; sxx += x2; sxxx += x2 * x; sxxxx += x2 * x2
            sxy += x * y; sxxy += x2 * y
        M = [[n, sx, sxx], [sx, sxx, sxxx], [sxx, sxxx, sxxxx]]
        rhs = [sy, sxy, sxxy]
        det = (
            M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1])
            - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0])
            + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0])
        )
        if abs(det) > 1e-12:
            def cof(i, j):
                m2 = [[M[r][c] for c in range(3) if c != j] for r in range(3) if r != i]
                return ((-1) ** (i + j)) * (m2[0][0] * m2[1][1] - m2[0][1] * m2[1][0])
            inv = 1.0 / det
            c_int = (cof(0, 0) * rhs[0] + cof(1, 0) * rhs[1] + cof(2, 0) * rhs[2]) * inv
            b_lin = (cof(0, 1) * rhs[0] + cof(1, 1) * rhs[1] + cof(2, 1) * rhs[2]) * inv
            a_quad = (cof(0, 2) * rhs[0] + cof(1, 2) * rhs[1] + cof(2, 2) * rhs[2]) * inv
            y_mean = sy / n
            ss_res = sum((y - (c_int + b_lin * x + a_quad * x * x)) ** 2 for x, y in pts)
            ss_tot = sum((y - y_mean) ** 2 for x, y in pts)
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
            out.append(f"Smile fit (moneyness m=log(K/S)/sqrt(T)):")
            out.append(f"  IV(m) = {a_quad:.4f}*m^2 + {b_lin:.4f}*m + {c_int:.4f}")
            out.append(f"  ATM IV (m=0) = {c_int:.4f} ({c_int*100:.2f}%), R^2 = {r2:.4f}")
            out.append(f"  Quadratic coef a = {a_quad:.4f} {'(flat)' if abs(a_quad) < 0.5 else '(pronounced)'}")

    # Per-strike: deviation = market mid - BS fair (using mean strike IV); compute lag-1 autocorr
    out.append("Per-strike: dev_lag1_autocorr (BS fair using mean IV per strike):")
    for K in voucher_strikes:
        if K not in mean_iv:
            out.append(f"  K={K}: no IV data")
            continue
        sigma = mean_iv[K]
        sym = f"VOLCANIC_ROCK_VOUCHER_{K}" if "ROCK" in underlying_name.upper() else f"VEV_{K}"
        voucher_mids_dict = dict(prices.get(sym, []))
        deviations = []
        for ts in timestamps:
            S = underlying.get(ts)
            mkt = voucher_mids_dict.get(ts)
            if S is None or mkt is None: continue
            fair = bs_call(S, K, T, sigma)
            deviations.append(mkt - fair)
        if len(deviations) < 50:
            out.append(f"  K={K}: not enough data (n={len(deviations)})")
            continue
        ac = autocorr(deviations, lag=1)
        ac10 = autocorr(deviations, lag=10)
        dev_std = statistics.stdev(deviations)
        out.append(f"  K={K}: n={len(deviations)} dev_std={dev_std:.3f} ac(1)={ac:.4f} ac(10)={ac10:.4f}")

    return "\n".join(out)


def main():
    day = int(sys.argv[1]) if len(sys.argv) > 1 else 2

    print("=" * 80)
    print(f"P3 2025 round 3 day {day}")
    print("=" * 80)
    p3_path = P3 / f"prices_round_3_day_{day}.csv"
    p3 = load_prices(p3_path, day_filter=day)
    print(f"Products: {sorted(p3.keys())}")
    print()
    print(analyze_underlying(p3, "RAINFOREST_RESIN"))
    print(analyze_underlying(p3, "KELP"))
    print(analyze_underlying(p3, "SQUID_INK"))
    print()
    print("--- VOLCANIC_ROCK options ---")
    # P3 2025 round 3 TTE ≈ 5 days at start of round (matches P4 2026 R3)
    print(analyze_options(p3, "VOLCANIC_ROCK", [9500, 9750, 10000, 10250, 10500], tte_days=5.0))
    print()

    print("=" * 80)
    print(f"R3 2026 round 3 day {day}")
    print("=" * 80)
    r3_path = R3_DATA / f"prices_round_3_day_{day}.csv"
    if not r3_path.exists():
        # Try alternative location
        r3_path = Path(f"prosperity4bt/resources/round3/prices_round_3_day_{day}.csv")
    r3 = load_prices(r3_path, day_filter=day)
    print(f"Products: {sorted(r3.keys())}")
    print()
    print(analyze_underlying(r3, "HYDROGEL_PACK"))
    print(analyze_underlying(r3, "VELVETFRUIT_EXTRACT"))
    print()
    print("--- VFE options ---")
    print(analyze_options(r3, "VELVETFRUIT_EXTRACT",
                          [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500],
                          tte_days=3.0))   # day 2 of R3, started at 5d, now 5-2=3


if __name__ == "__main__":
    main()
