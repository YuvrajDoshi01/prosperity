"""
IV Smile Structure Analysis for VEV Vouchers (R3)
==================================================
Computes implied volatility per strike per tick via bisection on BS call formula,
fits quadratic smile (IV vs log-moneyness), and reports:
  a. Average IV per strike per day
  b. Average residual per strike (rich/cheap vs fitted smile)
  c. AR(1) of residuals per strike
  d. Cross-day sign stability of residuals
  e. Residual half-life in ticks
"""

import csv
import math
import numpy as np
from collections import defaultdict
import warnings
warnings.filterwarnings("ignore")

# ─── Configuration ───────────────────────────────────────────────────────────

STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
STRIKE_NAMES = {k: f"VEV_{k}" for k in STRIKES}
UNDERLYING = "VELVETFRUIT_EXTRACT"

# Time to expiry at tick 0 of each day (in trading days)
# Day 0: 8 days, Day 1: 6 days, Day 2: 5 days remaining
TTE_DAY0_START = 8.0
TTE_DAY1_START = 6.0
TTE_DAY2_START = 5.0
YEAR = 250.0

# Each day spans 10,000 ticks (0 to 999900 step 100) = 1 trading day
# So within a day, T decreases from TTE_START/250 to (TTE_START-1)/250
TICKS_PER_DAY = 10000
TICK_STEP = 100

DATA_DIR = "/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round3"

# ─── Black-Scholes ───────────────────────────────────────────────────────────

def norm_cdf(x):
    """Standard normal CDF via error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bs_call(S, K, T, sigma):
    """Black-Scholes call price, r=0, no dividends."""
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * norm_cdf(d1) - K * norm_cdf(d2)

def implied_vol_bisection(S, K, T, C_market, tol=1e-6, max_iter=200):
    """Compute IV via bisection. Returns None if no solution."""
    intrinsic = max(S - K, 0.0)
    if C_market < intrinsic - 0.5:
        return None
    if C_market <= intrinsic + 0.01:
        return None  # at intrinsic, IV ~ 0 or undefined
    if T <= 1e-10:
        return None

    lo, hi = 0.001, 5.0

    # Check bounds
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

# ─── Data Loading ────────────────────────────────────────────────────────────

def load_day(day_idx):
    """Load CSV for a day, return dict: timestamp -> {product: mid_price}."""
    filepath = f"{DATA_DIR}/prices_round_3_day_{day_idx}.csv"
    data = defaultdict(dict)
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            ts = int(row['timestamp'])
            product = row['product']
            bid1 = row.get('bid_price_1', '')
            ask1 = row.get('ask_price_1', '')

            # Compute mid from best bid/ask
            if bid1 and ask1 and bid1 != '' and ask1 != '':
                try:
                    b = float(bid1)
                    a = float(ask1)
                    if b > 0 and a > 0:
                        mid = (b + a) / 2.0
                        data[ts][product] = mid
                except ValueError:
                    pass
    return data

# ─── Main Analysis ───────────────────────────────────────────────────────────

def analyze():
    tte_starts = {0: TTE_DAY0_START, 1: TTE_DAY1_START, 2: TTE_DAY2_START}

    # Storage for per-day results
    # iv_by_day_strike[day][strike] = list of IVs
    # residual_by_day_strike[day][strike] = list of residuals
    iv_by_day_strike = {d: {k: [] for k in STRIKES} for d in range(3)}
    residual_by_day_strike = {d: {k: [] for k in STRIKES} for d in range(3)}
    # For AR(1) and half-life, store time-ordered residuals per strike per day
    residual_timeseries = {d: {k: [] for k in STRIKES} for d in range(3)}

    for day in range(3):
        print(f"\n{'='*60}")
        print(f"Processing Day {day} (TTE_start = {tte_starts[day]} days)")
        print(f"{'='*60}")

        data = load_day(day)
        timestamps = sorted(data.keys())
        print(f"  Loaded {len(timestamps)} timestamps")

        n_valid_ticks = 0
        n_smile_fits = 0

        for ts in timestamps:
            tick_data = data[ts]

            # Need underlying
            if UNDERLYING not in tick_data:
                continue
            S = tick_data[UNDERLYING]
            if S <= 0:
                continue

            # Time to expiry: linearly interpolate within the day
            # tick 0 = start of day, tick 999900 = end of day
            day_frac = ts / (TICKS_PER_DAY * TICK_STEP - TICK_STEP)  # 0 to 1
            tte_days = tte_starts[day] - day_frac  # decreases through day
            T = tte_days / YEAR

            if T <= 1e-10:
                continue

            # Compute IV for each strike
            tick_ivs = {}
            tick_moneyness = {}
            for K in STRIKES:
                name = STRIKE_NAMES[K]
                if name not in tick_data:
                    continue
                C_mid = tick_data[name]
                if C_mid <= 0:
                    continue

                iv = implied_vol_bisection(S, K, T, C_mid)
                if iv is not None and 0.01 < iv < 3.0:
                    m = math.log(K / S)
                    tick_ivs[K] = iv
                    tick_moneyness[K] = m

            # Need at least 4 strikes to fit quadratic
            if len(tick_ivs) < 4:
                continue

            n_valid_ticks += 1

            # Store IVs
            for K, iv in tick_ivs.items():
                iv_by_day_strike[day][K].append(iv)

            # Fit quadratic: IV = a*m^2 + b*m + c
            strikes_list = sorted(tick_ivs.keys())
            m_arr = np.array([tick_moneyness[K] for K in strikes_list])
            iv_arr = np.array([tick_ivs[K] for K in strikes_list])

            # Weighted least squares (equal weight for now)
            A = np.column_stack([m_arr**2, m_arr, np.ones_like(m_arr)])
            try:
                coeffs, _, _, _ = np.linalg.lstsq(A, iv_arr, rcond=None)
            except np.linalg.LinAlgError:
                continue

            n_smile_fits += 1
            fitted = A @ coeffs
            residuals = iv_arr - fitted

            for i, K in enumerate(strikes_list):
                residual_by_day_strike[day][K].append(residuals[i])
                residual_timeseries[day][K].append((ts, residuals[i]))

        print(f"  Valid ticks with >= 4 strike IVs: {n_valid_ticks}")
        print(f"  Successful smile fits: {n_smile_fits}")

    # ─── Report (a): Average IV per strike per day ───────────────────────────

    print("\n\n" + "=" * 80)
    print("(a) AVERAGE IMPLIED VOLATILITY PER STRIKE PER DAY")
    print("=" * 80)
    header = f"{'Strike':>8}"
    for d in range(3):
        header += f"  {'Day '+str(d)+' IV':>12}  {'N':>6}"
    print(header)
    print("-" * 80)

    for K in STRIKES:
        row = f"{K:>8}"
        for d in range(3):
            ivs = iv_by_day_strike[d][K]
            if len(ivs) > 0:
                row += f"  {np.mean(ivs):>12.6f}  {len(ivs):>6}"
            else:
                row += f"  {'N/A':>12}  {0:>6}"
        print(row)

    # ─── Report (b): Average residual per strike ─────────────────────────────

    print("\n\n" + "=" * 80)
    print("(b) AVERAGE RESIDUAL PER STRIKE (actual IV - fitted IV)")
    print("    Positive = RICH (overpriced), Negative = CHEAP (underpriced)")
    print("=" * 80)
    header = f"{'Strike':>8}"
    for d in range(3):
        header += f"  {'Day '+str(d)+' Res':>12}  {'StdDev':>10}  {'N':>6}"
    print(header)
    print("-" * 100)

    avg_resid_by_day = {}
    for K in STRIKES:
        row = f"{K:>8}"
        for d in range(3):
            res = residual_by_day_strike[d][K]
            if len(res) > 10:
                mean_r = np.mean(res)
                std_r = np.std(res)
                row += f"  {mean_r:>12.6f}  {std_r:>10.6f}  {len(res):>6}"
                if K not in avg_resid_by_day:
                    avg_resid_by_day[K] = {}
                avg_resid_by_day[K][d] = mean_r
            else:
                row += f"  {'N/A':>12}  {'N/A':>10}  {len(res):>6}"
        print(row)

    # ─── Report (c): AR(1) of residuals per strike ──────────────────────────

    print("\n\n" + "=" * 80)
    print("(c) AR(1) AUTOCORRELATION OF RESIDUALS PER STRIKE")
    print("    High AR(1) = persistent mispricing = exploitable")
    print("=" * 80)
    header = f"{'Strike':>8}"
    for d in range(3):
        header += f"  {'Day '+str(d)+' AR1':>12}  {'N':>6}"
    print(header)
    print("-" * 80)

    ar1_by_day_strike = {}
    for K in STRIKES:
        row = f"{K:>8}"
        ar1_by_day_strike[K] = {}
        for d in range(3):
            ts_data = residual_timeseries[d][K]
            if len(ts_data) > 30:
                # Sort by timestamp
                ts_data_sorted = sorted(ts_data, key=lambda x: x[0])
                res_series = np.array([r for _, r in ts_data_sorted])
                # AR(1) = correlation of r[t] with r[t-1]
                if np.std(res_series[:-1]) > 1e-12 and np.std(res_series[1:]) > 1e-12:
                    ar1 = np.corrcoef(res_series[:-1], res_series[1:])[0, 1]
                    row += f"  {ar1:>12.4f}  {len(ts_data):>6}"
                    ar1_by_day_strike[K][d] = ar1
                else:
                    row += f"  {'const':>12}  {len(ts_data):>6}"
            else:
                row += f"  {'N/A':>12}  {len(ts_data):>6}"
        print(row)

    # Average AR(1) across strikes
    print("\n  Average AR(1) across all strikes with data:")
    for d in range(3):
        vals = [ar1_by_day_strike[K][d] for K in STRIKES if d in ar1_by_day_strike[K]]
        if vals:
            print(f"    Day {d}: mean AR(1) = {np.mean(vals):.4f}, "
                  f"min = {np.min(vals):.4f}, max = {np.max(vals):.4f}")

    # ─── Report (d): Cross-day sign stability ────────────────────────────────

    print("\n\n" + "=" * 80)
    print("(d) CROSS-DAY SIGN STABILITY OF AVERAGE RESIDUALS")
    print("    Stable = same sign all 3 days = structural smile deviation")
    print("=" * 80)
    print(f"{'Strike':>8}  {'Day0 sign':>10}  {'Day1 sign':>10}  {'Day2 sign':>10}  {'Stable?':>10}  {'Avg Resid':>10}")
    print("-" * 70)

    for K in STRIKES:
        if K in avg_resid_by_day and len(avg_resid_by_day[K]) == 3:
            signs = ['+' if avg_resid_by_day[K][d] > 0 else '-' for d in range(3)]
            stable = "YES" if len(set(signs)) == 1 else "NO"
            avg_all = np.mean([avg_resid_by_day[K][d] for d in range(3)])
            print(f"{K:>8}  {signs[0]:>10}  {signs[1]:>10}  {signs[2]:>10}  {stable:>10}  {avg_all:>10.6f}")
        else:
            print(f"{K:>8}  {'insufficient data':>42}")

    # ─── Report (e): Residual half-life ──────────────────────────────────────

    print("\n\n" + "=" * 80)
    print("(e) RESIDUAL HALF-LIFE IN TICKS (via exponential decay of ACF)")
    print("    Method: fit ACF(lag) = exp(-lag/tau), half-life = tau * ln(2)")
    print("=" * 80)
    header = f"{'Strike':>8}"
    for d in range(3):
        header += f"  {'Day '+str(d)+' HL':>12}"
    print(header)
    print("-" * 60)

    for K in STRIKES:
        row = f"{K:>8}"
        for d in range(3):
            ts_data = residual_timeseries[d][K]
            if len(ts_data) > 100:
                ts_data_sorted = sorted(ts_data, key=lambda x: x[0])
                res_series = np.array([r for _, r in ts_data_sorted])

                # Compute ACF up to lag 50
                n = len(res_series)
                mean_r = np.mean(res_series)
                var_r = np.var(res_series)
                if var_r < 1e-15:
                    row += f"  {'const':>12}"
                    continue

                max_lag = min(50, n // 4)
                acf = np.zeros(max_lag)
                for lag in range(max_lag):
                    if lag == 0:
                        acf[lag] = 1.0
                    else:
                        cov = np.mean((res_series[lag:] - mean_r) * (res_series[:-lag] - mean_r))
                        acf[lag] = cov / var_r

                # Fit exp decay: log(acf) = -lag/tau for positive acf values
                # Use lags 1 to first zero-crossing
                valid_lags = []
                valid_log_acf = []
                for lag in range(1, max_lag):
                    if acf[lag] > 0.01:
                        valid_lags.append(lag)
                        valid_log_acf.append(math.log(acf[lag]))
                    else:
                        break

                if len(valid_lags) >= 3:
                    lags_arr = np.array(valid_lags, dtype=float)
                    log_acf_arr = np.array(valid_log_acf)
                    # Linear regression: log(acf) = -lag/tau + intercept
                    A_fit = np.column_stack([lags_arr, np.ones_like(lags_arr)])
                    try:
                        fit, _, _, _ = np.linalg.lstsq(A_fit, log_acf_arr, rcond=None)
                        slope = fit[0]
                        if slope < -1e-6:
                            tau = -1.0 / slope
                            half_life = tau * math.log(2)
                            row += f"  {half_life:>10.1f} t"
                        else:
                            row += f"  {'non-decay':>12}"
                    except:
                        row += f"  {'fit-fail':>12}"
                else:
                    row += f"  {'<1 tick':>12}"
            else:
                row += f"  {'N/A':>12}"
        print(row)

    # ─── Summary Statistics ──────────────────────────────────────────────────

    print("\n\n" + "=" * 80)
    print("SUMMARY: EXPLOITABILITY ASSESSMENT")
    print("=" * 80)

    # Compute average absolute residual and AR(1)
    print("\nStrike-level signal quality (averaged across 3 days):")
    print(f"{'Strike':>8}  {'|Avg Resid|':>12}  {'Avg AR(1)':>12}  {'Signal':>10}")
    print("-" * 55)

    for K in STRIKES:
        if K in avg_resid_by_day and len(avg_resid_by_day[K]) == 3:
            abs_res = np.mean([abs(avg_resid_by_day[K][d]) for d in range(3)])
            ar1_vals = [ar1_by_day_strike[K].get(d, 0) for d in range(3)]
            avg_ar1 = np.mean(ar1_vals) if ar1_vals else 0
            # Signal = persistent AND non-trivial residual
            signal = "STRONG" if abs_res > 0.005 and avg_ar1 > 0.8 else \
                     "MODERATE" if abs_res > 0.002 and avg_ar1 > 0.5 else "WEAK"
            print(f"{K:>8}  {abs_res:>12.6f}  {avg_ar1:>12.4f}  {signal:>10}")
        else:
            print(f"{K:>8}  {'N/A':>36}")

    print("\nInterpretation:")
    print("  - STRONG: persistent structural mispricing, potentially exploitable")
    print("  - MODERATE: some signal but may be eaten by spread")
    print("  - WEAK: noise-dominated, not worth trading the residual")
    print("  - Key question: is |residual| in IV terms > bid-ask spread in IV terms?")


if __name__ == "__main__":
    analyze()
