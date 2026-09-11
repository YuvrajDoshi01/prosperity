#!/usr/bin/env python3
"""
ou_model_tomatoes.py — Ornstein-Uhlenbeck Process Model for TOMATOES
=====================================================================

Models the TOMATOES mid price as a discrete-time OU process:
    dX_t = kappa * (theta - X_t) * dt + sigma * dW_t

Equivalent discrete AR(1):
    X_{t+1} = alpha + beta * X_t + epsilon_t
    where beta = exp(-kappa*dt), alpha = theta*(1 - beta), Var(eps) = sigma^2*(1-beta^2)/(2*kappa)

This script performs:
  1. AR(1) MLE calibration of OU parameters per day
  2. AR(2) extension check (is there structure beyond OU?)
  3. Half-life and mean-reversion speed analysis
  4. Residual diagnostics (normality, heteroskedasticity, independence)
  5. Multi-scale autocorrelation structure
  6. Regime analysis: is kappa/sigma constant or time-varying?
  7. Price level discreteness analysis (0.5-tick grid)
  8. Implications for trading (optimal spread, reservation price, inventory penalty)

Run: python trader-logic/round-0/analysis/ou_model_tomatoes.py
"""

import csv
import math
import os
from collections import defaultdict

# ==============================================================================
# DATA LOADING
# ==============================================================================

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "prosperity4bt", "resources", "round0")


def load_tomatoes(day):
    """Load TOMATOES order book data for a given day."""
    fname = os.path.join(DATA_DIR, f"prices_round_0_day_{day}.csv")
    rows = []
    with open(fname) as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["product"] == "TOMATOES":
                rows.append({
                    "timestamp": int(r["timestamp"]),
                    "bid1": float(r["bid_price_1"]),
                    "bid1_vol": int(r["bid_volume_1"]),
                    "bid2": float(r["bid_price_2"]) if r["bid_price_2"] else None,
                    "bid2_vol": int(r["bid_volume_2"]) if r["bid_volume_2"] else 0,
                    "ask1": float(r["ask_price_1"]),
                    "ask1_vol": int(r["ask_volume_1"]),
                    "ask2": float(r["ask_price_2"]) if r["ask_price_2"] else None,
                    "ask2_vol": int(r["ask_volume_2"]) if r["ask_volume_2"] else 0,
                    "mid": float(r["mid_price"]),
                })
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def load_trades(day):
    """Load TOMATOES trades for a given day."""
    fname = os.path.join(DATA_DIR, f"trades_round_0_day_{day}.csv")
    trades = []
    if os.path.exists(fname):
        with open(fname) as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r["symbol"] == "TOMATOES":
                    trades.append({
                        "timestamp": int(r["timestamp"]),
                        "price": float(r["price"]),
                        "quantity": int(r["quantity"]),
                    })
    trades.sort(key=lambda t: t["timestamp"])
    return trades


# ==============================================================================
# STATISTICS HELPERS (no numpy/pandas dependency)
# ==============================================================================

def mean(xs):
    return sum(xs) / len(xs)


def var(xs, ddof=0):
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - ddof)


def std(xs, ddof=0):
    return math.sqrt(var(xs, ddof))


def cov(xs, ys, ddof=0):
    mx, my = mean(xs), mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - ddof)


def corr(xs, ys):
    sx, sy = std(xs), std(ys)
    if sx == 0 or sy == 0:
        return 0.0
    return cov(xs, ys) / (sx * sy)


def autocorr(xs, lag):
    """Autocorrelation of xs at given lag."""
    n = len(xs)
    if n <= lag:
        return 0.0
    m = mean(xs)
    v = sum((x - m) ** 2 for x in xs) / n
    if v == 0:
        return 0.0
    c = sum((xs[i] - m) * (xs[i + lag] - m) for i in range(n - lag)) / n
    return c / v


def percentile(xs, p):
    """Simple percentile (linear interpolation)."""
    s = sorted(xs)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = f + 1
    if c >= len(s):
        return s[-1]
    return s[f] + (k - f) * (s[c] - s[f])


def ols_1d(x, y):
    """Simple OLS: y = a + b*x. Returns (a, b, r2, residuals)."""
    n = len(x)
    mx, my = mean(x), mean(y)
    sxx = sum((xi - mx) ** 2 for xi in x)
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    b = sxy / sxx if sxx > 0 else 0.0
    a = my - b * mx
    y_hat = [a + b * xi for xi in x]
    residuals = [yi - yhi for yi, yhi in zip(y, y_hat)]
    ss_res = sum(r ** 2 for r in residuals)
    ss_tot = sum((yi - my) ** 2 for yi in y)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return a, b, r2, residuals


def ols_multi(X_cols, y):
    """
    Multi-variate OLS using normal equations (no numpy).
    X_cols: list of lists (each column is a feature), intercept added automatically.
    Returns: coefficients [b0, b1, ..., bk], r2, residuals
    """
    n = len(y)
    k = len(X_cols) + 1  # +1 for intercept
    # Build X^T X and X^T y
    # Columns: [1, x1, x2, ..., xk]
    cols = [[1.0] * n] + X_cols

    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for i in range(k):
        for j in range(k):
            xtx[i][j] = sum(cols[i][t] * cols[j][t] for t in range(n))
        xty[i] = sum(cols[i][t] * y[t] for t in range(n))

    # Solve via Gaussian elimination
    aug = [row + [rhs] for row, rhs in zip(xtx, xty)]
    for col in range(k):
        # Partial pivoting
        max_row = col
        for row in range(col + 1, k):
            if abs(aug[row][col]) > abs(aug[max_row][col]):
                max_row = row
        aug[col], aug[max_row] = aug[max_row], aug[col]
        if abs(aug[col][col]) < 1e-12:
            continue
        for row in range(col + 1, k):
            factor = aug[row][col] / aug[col][col]
            for j in range(col, k + 1):
                aug[row][j] -= factor * aug[col][j]
    # Back substitution
    beta = [0.0] * k
    for i in range(k - 1, -1, -1):
        beta[i] = aug[i][k]
        for j in range(i + 1, k):
            beta[i] -= aug[i][j] * beta[j]
        if abs(aug[i][i]) > 1e-12:
            beta[i] /= aug[i][i]

    y_hat = [sum(beta[j] * cols[j][t] for j in range(k)) for t in range(n)]
    residuals = [y[t] - y_hat[t] for t in range(n)]
    my = mean(y)
    ss_res = sum(r ** 2 for r in residuals)
    ss_tot = sum((yi - my) ** 2 for yi in y)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return beta, r2, residuals


# ==============================================================================
# SECTION 1: OU CALIBRATION (AR(1) ON LEVELS)
# ==============================================================================

def calibrate_ou_ar1(mids, dt=1.0):
    """
    Calibrate OU via AR(1) on levels:
        X_{t+1} = alpha + beta * X_t + eps
        kappa = -ln(beta) / dt   (continuous-time mean-reversion rate)
        theta = alpha / (1 - beta) (long-run mean)
        sigma = std(eps) * sqrt(2*kappa / (1-beta^2))
    """
    x = mids[:-1]
    y = mids[1:]
    alpha, beta, r2, residuals = ols_1d(x, y)

    if beta <= 0 or beta >= 1:
        # Process is not mean-reverting in this sample
        kappa = 0.0
        theta = mean(mids)
        sigma_ou = std(residuals)
        half_life = float("inf")
    else:
        kappa = -math.log(beta) / dt
        theta = alpha / (1 - beta)
        eps_var = var(residuals)
        # OU sigma: Var(eps) = sigma^2 * (1 - exp(-2*kappa*dt)) / (2*kappa)
        # => sigma^2 = Var(eps) * 2*kappa / (1 - exp(-2*kappa*dt))
        denom = 1 - math.exp(-2 * kappa * dt)
        sigma_ou = math.sqrt(eps_var * 2 * kappa / denom) if denom > 0 else math.sqrt(eps_var)
        half_life = math.log(2) / kappa if kappa > 0 else float("inf")

    return {
        "alpha": alpha,
        "beta": beta,
        "r2": r2,
        "kappa": kappa,
        "theta": theta,
        "sigma": sigma_ou,
        "eps_std": std(residuals),
        "half_life": half_life,
        "residuals": residuals,
    }


# ==============================================================================
# SECTION 2: AR(2) ON CHANGES — IS THERE STRUCTURE BEYOND OU?
# ==============================================================================

def fit_ar2_changes(mids):
    """
    AR(2) on dmid:
        dmid[t] = a1*dmid[t-1] + a2*dmid[t-2] + c + eps
    OU predicts a1 ≈ beta-1 (negative), a2 ≈ 0.
    If a2 is significantly nonzero, the OU model is incomplete.
    """
    dmid = [mids[i + 1] - mids[i] for i in range(len(mids) - 1)]
    n = len(dmid)

    y = dmid[2:]
    x1 = dmid[1:-1]
    x2 = dmid[:-2]

    beta, r2, residuals = ols_multi([x1, x2], y)
    # beta = [intercept, a1, a2]
    return {
        "intercept": beta[0],
        "a1": beta[1],
        "a2": beta[2],
        "r2": r2,
        "residuals": residuals,
        "dmid": dmid,
    }


# ==============================================================================
# SECTION 3: MULTI-SCALE AUTOCORRELATION
# ==============================================================================

def compute_ac_structure(mids, max_lag=50):
    """Autocorrelation of mid changes at multiple lags."""
    dmid = [mids[i + 1] - mids[i] for i in range(len(mids) - 1)]
    result = {}
    for lag in range(1, min(max_lag + 1, len(dmid))):
        result[lag] = autocorr(dmid, lag)
    return result


def compute_ac_levels(mids, max_lag=50):
    """Autocorrelation of mid LEVELS (should be very high for near-unit-root)."""
    result = {}
    for lag in range(1, min(max_lag + 1, len(mids))):
        result[lag] = autocorr(mids, lag)
    return result


# ==============================================================================
# SECTION 4: RESIDUAL DIAGNOSTICS
# ==============================================================================

def jarque_bera(residuals):
    """Jarque-Bera normality test (S^2/6 + K^2/24) * n/6."""
    n = len(residuals)
    m = mean(residuals)
    m2 = sum((r - m) ** 2 for r in residuals) / n
    m3 = sum((r - m) ** 3 for r in residuals) / n
    m4 = sum((r - m) ** 4 for r in residuals) / n
    if m2 == 0:
        return 0, 0, 0
    skewness = m3 / m2 ** 1.5
    kurtosis = m4 / m2 ** 2  # excess kurtosis = kurtosis - 3
    jb = n * (skewness ** 2 / 6 + (kurtosis - 3) ** 2 / 24)
    return skewness, kurtosis, jb


def ljung_box(xs, max_lag=10):
    """Ljung-Box Q statistic for residual autocorrelation."""
    n = len(xs)
    q = 0.0
    for lag in range(1, max_lag + 1):
        rk = autocorr(xs, lag)
        q += rk ** 2 / (n - lag)
    q *= n * (n + 2)
    return q


def heteroskedasticity_test(residuals, window=100):
    """
    Simple test: compare variance in first half vs second half,
    and rolling variance to check for time-varying sigma.
    """
    n = len(residuals)
    h1 = residuals[: n // 2]
    h2 = residuals[n // 2:]
    var1 = var(h1)
    var2 = var(h2)
    ratio = var2 / var1 if var1 > 0 else float("inf")

    # Rolling variance
    rolling_vars = []
    for i in range(0, n - window, window // 2):
        chunk = residuals[i: i + window]
        rolling_vars.append((i, var(chunk)))

    return {
        "var_first_half": var1,
        "var_second_half": var2,
        "ratio": ratio,
        "rolling": rolling_vars,
    }


# ==============================================================================
# SECTION 5: DISCRETENESS ANALYSIS
# ==============================================================================

def analyze_discreteness(mids):
    """
    TOMATOES mid moves in multiples of 0.5 (confirmed: MM bot quotes in integers,
    mid = (bid+ask)/2). Analyze the actual step-size distribution.
    """
    dmid = [mids[i + 1] - mids[i] for i in range(len(mids) - 1)]
    step_counts = defaultdict(int)
    for d in dmid:
        # Round to nearest 0.5
        rounded = round(d * 2) / 2
        step_counts[rounded] += 1

    total = len(dmid)
    zero_frac = step_counts[0.0] / total if 0.0 in step_counts else 0.0
    nonzero = [d for d in dmid if abs(d) > 0.01]
    abs_steps = [abs(d) for d in nonzero]

    return {
        "step_counts": dict(sorted(step_counts.items())),
        "zero_fraction": zero_frac,
        "nonzero_count": len(nonzero),
        "mean_abs_step": mean(abs_steps) if abs_steps else 0,
        "max_step": max(abs_steps) if abs_steps else 0,
    }


# ==============================================================================
# SECTION 6: TIME-VARYING PARAMETERS (REGIME CHECK)
# ==============================================================================

def rolling_ou_calibration(mids, window=200, step=50):
    """
    Calibrate OU in rolling windows to check parameter stability.
    If kappa varies a lot, the OU model with constant parameters is wrong.
    """
    results = []
    for start in range(0, len(mids) - window, step):
        chunk = mids[start: start + window]
        ou = calibrate_ou_ar1(chunk)
        results.append({
            "start_tick": start,
            "kappa": ou["kappa"],
            "theta": ou["theta"],
            "sigma": ou["sigma"],
            "half_life": ou["half_life"],
            "beta": ou["beta"],
        })
    return results


# ==============================================================================
# SECTION 7: SPREAD STATE ANALYSIS (INFORMING OU FIT)
# ==============================================================================

def analyze_spread_states(data):
    """
    Spread = ask1 - bid1. MM bot has discrete spread states {5,6,7,8,9,13,14}.
    Spread state affects effective volatility (narrow spread → larger true moves).
    """
    spreads = [r["ask1"] - r["bid1"] for r in data]
    spread_counts = defaultdict(int)
    for s in spreads:
        spread_counts[int(s)] += 1

    # Conditional volatility by spread state
    mids = [r["mid"] for r in data]
    dmid = [mids[i + 1] - mids[i] for i in range(len(mids) - 1)]

    cond_vol = {}
    for i, d in enumerate(dmid):
        s = int(spreads[i])
        if s not in cond_vol:
            cond_vol[s] = []
        cond_vol[s].append(d)

    cond_stats = {}
    for s, vals in sorted(cond_vol.items()):
        cond_stats[s] = {
            "count": len(vals),
            "mean_dmid": mean(vals),
            "std_dmid": std(vals) if len(vals) > 1 else 0,
            "mean_abs_dmid": mean([abs(v) for v in vals]),
            "frac": len(vals) / len(dmid),
        }

    return {
        "spread_counts": dict(sorted(spread_counts.items())),
        "total": len(spreads),
        "cond_stats": cond_stats,
    }


# ==============================================================================
# SECTION 8: TRADING IMPLICATIONS
# ==============================================================================

def compute_trading_implications(ou_params, fill_rate=0.04):
    """
    Given calibrated OU parameters, derive:
    - Avellaneda-Stoikov optimal half-spread
    - Reservation price shift per unit inventory
    - Expected PnL per round-trip at various spreads
    """
    kappa = ou_params["kappa"]
    sigma = ou_params["sigma"]
    sigma_sq = sigma ** 2

    results = {}

    # A-S optimal half-spread: delta = gamma*sigma^2*tau/2 + (1/gamma)*ln(1+gamma/k)
    # where k = fill rate intensity
    gamma_values = [0.001, 0.005, 0.01, 0.02, 0.05, 0.1]
    for gamma in gamma_values:
        for tau in [1.0, 0.5, 0.2]:
            inv_penalty = gamma * sigma_sq * tau
            if fill_rate > 0:
                spread_term = (1.0 / gamma) * math.log(1 + gamma / fill_rate)
            else:
                spread_term = 0
            half_spread = inv_penalty / 2.0 + spread_term
            reservation_shift_at_40 = 40 * gamma * sigma_sq * tau
            reservation_shift_at_80 = 80 * gamma * sigma_sq * tau
            results[(gamma, tau)] = {
                "half_spread": half_spread,
                "inv_penalty_per_unit": gamma * sigma_sq * tau,
                "res_shift_40": reservation_shift_at_40,
                "res_shift_80": reservation_shift_at_80,
            }

    # Variance of position carry over N ticks
    # For OU: Var(X_t - X_0) = sigma^2/(2*kappa) * (1 - exp(-2*kappa*t))
    carry_risk = {}
    for n_ticks in [10, 50, 100, 500, 1000, 2000]:
        t = n_ticks  # dt = 1 tick
        if kappa > 0:
            var_displacement = sigma_sq / (2 * kappa) * (1 - math.exp(-2 * kappa * t))
        else:
            var_displacement = sigma_sq * t  # random walk limit
        carry_risk[n_ticks] = {
            "std_displacement": math.sqrt(var_displacement),
            "var_displacement": var_displacement,
        }

    return {
        "as_spreads": results,
        "carry_risk": carry_risk,
    }


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    days = [-2, -1, 0]
    all_data = {}
    all_mids = {}
    all_trades = {}

    for day in days:
        data = load_tomatoes(day)
        trades = load_trades(day)
        all_data[day] = data
        all_mids[day] = [r["mid"] for r in data]
        all_trades[day] = trades
        print(f"Day {day:+d}: {len(data)} ticks, {len(trades)} trades")

    # ══════════════════════════════════════════════════════════════
    # 1. OU CALIBRATION (AR(1) ON LEVELS)
    # ══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("1. OU CALIBRATION VIA AR(1) ON MID PRICE LEVELS")
    print("=" * 80)
    print(f"   Model: X_{{t+1}} = alpha + beta * X_t + eps")
    print(f"   OU:    dX = kappa*(theta - X)*dt + sigma*dW")
    print()

    ou_params = {}
    for day in days:
        mids = all_mids[day]
        ou = calibrate_ou_ar1(mids)
        ou_params[day] = ou
        n = len(mids)
        trades = all_trades[day]

        print(f"  Day {day:+d} ({n} ticks, {len(trades)} trades):")
        print(f"    AR(1):  alpha = {ou['alpha']:.6f},  beta = {ou['beta']:.6f},  R² = {ou['r2']:.8f}")
        print(f"    OU:     kappa = {ou['kappa']:.6f},  theta = {ou['theta']:.2f},  sigma = {ou['sigma']:.4f}")
        print(f"    Half-life = {ou['half_life']:.1f} ticks ({ou['half_life'] * 0.1:.1f} seconds)")
        print(f"    eps_std = {ou['eps_std']:.4f}")
        print(f"    Mid range: [{min(mids):.1f}, {max(mids):.1f}],  mid_mean = {mean(mids):.2f}")
        print()

    # Cross-day stability
    kappas = [ou_params[d]["kappa"] for d in days]
    sigmas = [ou_params[d]["sigma"] for d in days]
    thetas = [ou_params[d]["theta"] for d in days]
    print(f"  STABILITY across days:")
    print(f"    kappa:  min={min(kappas):.6f}, max={max(kappas):.6f}, range={max(kappas)-min(kappas):.6f}  {'UNSTABLE' if max(kappas)/max(min(kappas),1e-9) > 2 else 'stable'}")
    print(f"    sigma:  min={min(sigmas):.4f}, max={max(sigmas):.4f}, range={max(sigmas)-min(sigmas):.4f}  {'UNSTABLE' if max(sigmas)/max(min(sigmas),1e-9) > 1.5 else 'stable'}")
    print(f"    theta:  [{', '.join(f'{t:.1f}' for t in thetas)}]  (long-run mean, should track daily FV)")

    # ══════════════════════════════════════════════════════════════
    # 2. AR(2) ON CHANGES — IS THERE MORE THAN OU?
    # ══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("2. AR(2) ON MID CHANGES — CHECKING FOR STRUCTURE BEYOND OU")
    print("=" * 80)
    print(f"   Model: dmid[t] = a1*dmid[t-1] + a2*dmid[t-2] + c + eps")
    print(f"   Pure OU predicts a2 ≈ 0. If a2 is significant, OU is incomplete.")
    print()

    for day in days:
        ar2 = fit_ar2_changes(all_mids[day])
        print(f"  Day {day:+d}:")
        print(f"    a1 = {ar2['a1']:.6f}  (OU predicts ~ {ou_params[day]['beta'] - 1:.4f})")
        print(f"    a2 = {ar2['a2']:.6f}  (OU predicts ~ 0)")
        print(f"    intercept = {ar2['intercept']:.6f}")
        print(f"    R² = {ar2['r2']:.6f}")
        a2_tstat = ar2["a2"] / (std(ar2["residuals"]) / math.sqrt(len(ar2["residuals"]))) if std(ar2["residuals"]) > 0 else 0
        print(f"    a2 t-stat ≈ {a2_tstat:.1f}  ({'SIGNIFICANT — OU model INCOMPLETE' if abs(a2_tstat) > 2 else 'not significant'})")
        print(f"    R² gain over AR(1): {ar2['r2'] - (1 - var(ar2['residuals']) / var(ar2['dmid'][2:])):.6f}")
        print()

    # ══════════════════════════════════════════════════════════════
    # 3. AUTOCORRELATION STRUCTURE OF MID CHANGES
    # ══════════════════════════════════════════════════════════════
    print("=" * 80)
    print("3. AUTOCORRELATION STRUCTURE OF dmid")
    print("=" * 80)
    print(f"   OU predicts: AC(1) = beta-1 ≈ -kappa*dt, AC(k>1) ≈ 0")
    print(f"   Real market: AC(1) large negative, AC(2) small negative, then ~0")
    print()

    for day in days:
        ac = compute_ac_structure(all_mids[day], max_lag=20)
        print(f"  Day {day:+d}: ", end="")
        lags_to_show = [1, 2, 3, 4, 5, 10, 15, 20]
        for lag in lags_to_show:
            if lag in ac:
                v = ac[lag]
                marker = " ***" if abs(v) > 2 / math.sqrt(len(all_mids[day])) else ""
                print(f"AC({lag})={v:+.4f}{marker}", end="  ")
        print()

    print(f"\n  2/sqrt(N) significance threshold: ±{2/math.sqrt(len(all_mids[0])):.4f}")
    print(f"\n  INTERPRETATION:")
    print(f"    AC(1) ≈ -0.44: Strong 1-tick mean-reversion (OU captures this)")
    print(f"    AC(2) ≈ -0.22: Residual 2-tick structure (OU MISSES this)")
    print(f"    AC(3+) ≈ 0: No further structure")
    print(f"    => AR(2) on changes is the minimal correct model, NOT AR(1)/OU")

    # ══════════════════════════════════════════════════════════════
    # 4. RESIDUAL DIAGNOSTICS
    # ══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("4. RESIDUAL DIAGNOSTICS (AR(1) FIT)")
    print("=" * 80)

    for day in days:
        resid = ou_params[day]["residuals"]
        skew, kurt, jb = jarque_bera(resid)
        lb_q = ljung_box(resid, max_lag=10)
        het = heteroskedasticity_test(resid, window=200)

        print(f"\n  Day {day:+d}:")
        print(f"    Normality:  skewness = {skew:.4f}, kurtosis = {kurt:.4f} (normal=3)")
        print(f"                Jarque-Bera = {jb:.1f}  ({'REJECT normality' if jb > 5.99 else 'accept'})")
        print(f"    Independence: Ljung-Box Q(10) = {lb_q:.1f}  ({'REJECT independence' if lb_q > 18.31 else 'accept'})")
        print(f"    Heterosked:  Var(first half) = {het['var_first_half']:.4f}")
        print(f"                 Var(second half) = {het['var_second_half']:.4f}")
        print(f"                 Ratio = {het['ratio']:.3f}  ({'HETEROSKEDASTIC' if abs(het['ratio'] - 1) > 0.3 else 'homoskedastic'})")

    # ══════════════════════════════════════════════════════════════
    # 5. DISCRETENESS ANALYSIS
    # ══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("5. PRICE DISCRETENESS (0.5-TICK GRID)")
    print("=" * 80)
    print(f"   MM bot quotes integers → mid moves in 0.5 increments")

    for day in days:
        disc = analyze_discreteness(all_mids[day])
        print(f"\n  Day {day:+d}:")
        print(f"    Zero-change fraction: {disc['zero_fraction']:.1%}  ({disc['step_counts'].get(0.0, 0)}/{len(all_mids[day])-1} ticks)")
        print(f"    Non-zero moves: {disc['nonzero_count']}  mean|step| = {disc['mean_abs_step']:.3f}")
        print(f"    Max |step| = {disc['max_step']:.1f}")
        print(f"    Step distribution:")
        for step, count in sorted(disc["step_counts"].items()):
            frac = count / (len(all_mids[day]) - 1)
            if frac >= 0.001:  # show only > 0.1%
                bar = "#" * int(frac * 200)
                print(f"      {step:+5.1f}: {count:5d} ({frac:6.2%}) {bar}")

    # ══════════════════════════════════════════════════════════════
    # 6. ROLLING OU CALIBRATION (TIME-VARYING PARAMETERS)
    # ══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("6. ROLLING OU CALIBRATION (window=200, step=50)")
    print("=" * 80)
    print(f"   Tests whether kappa/sigma are constant or regime-switching")

    for day in days:
        rolling = rolling_ou_calibration(all_mids[day], window=200, step=50)
        kappas_r = [r["kappa"] for r in rolling if r["kappa"] > 0]
        sigmas_r = [r["sigma"] for r in rolling]
        hls = [r["half_life"] for r in rolling if r["half_life"] < 10000]

        print(f"\n  Day {day:+d} ({len(rolling)} windows):")
        if kappas_r:
            print(f"    kappa:     mean={mean(kappas_r):.6f}, std={std(kappas_r):.6f}, "
                  f"CV={std(kappas_r)/mean(kappas_r):.2f}")
        if sigmas_r:
            print(f"    sigma:     mean={mean(sigmas_r):.4f}, std={std(sigmas_r):.4f}, "
                  f"CV={std(sigmas_r)/mean(sigmas_r):.2f}")
        if hls:
            print(f"    half-life: mean={mean(hls):.0f}, std={std(hls):.0f}, "
                  f"range=[{min(hls):.0f}, {max(hls):.0f}]")

        # Show a few snapshots
        print(f"    Snapshots (tick → kappa, sigma, half_life):")
        for r in rolling[::max(1, len(rolling) // 5)]:
            hl_str = f"{r['half_life']:.0f}" if r["half_life"] < 10000 else "inf"
            print(f"      tick {r['start_tick']:5d}: kappa={r['kappa']:.6f}, "
                  f"sigma={r['sigma']:.4f}, HL={hl_str}")

    # ══════════════════════════════════════════════════════════════
    # 7. SPREAD STATE CONDITIONING
    # ══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("7. VOLATILITY BY SPREAD STATE")
    print("=" * 80)
    print(f"   OU assumes constant sigma. Does sigma depend on spread state?")

    for day in days:
        ss = analyze_spread_states(all_data[day])
        print(f"\n  Day {day:+d}:")
        print(f"    {'Spread':>6s} | {'Count':>6s} | {'Frac':>6s} | {'std(dmid)':>9s} | {'mean|dmid|':>10s} | {'mean(dmid)':>10s}")
        print(f"    {'-' * 6}-+-{'-' * 6}-+-{'-' * 6}-+-{'-' * 9}-+-{'-' * 10}-+-{'-' * 10}")
        for s, st in sorted(ss["cond_stats"].items()):
            print(f"    {s:6d} | {st['count']:6d} | {st['frac']:5.1%} | {st['std_dmid']:9.4f} | {st['mean_abs_dmid']:10.4f} | {st['mean_dmid']:+10.6f}")

    # ══════════════════════════════════════════════════════════════
    # 8. TRADING IMPLICATIONS
    # ══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("8. TRADING IMPLICATIONS")
    print("=" * 80)

    # Use day 0 parameters (matches website)
    ou = ou_params[0]
    n_trades_0 = len(all_trades[0])
    n_ticks_0 = len(all_mids[0])
    fill_rate = n_trades_0 / n_ticks_0 if n_ticks_0 > 0 else 0.04

    print(f"\n  Using day 0 calibration:")
    print(f"    kappa = {ou['kappa']:.6f}, sigma = {ou['sigma']:.4f}, theta = {ou['theta']:.1f}")
    print(f"    Fill rate = {fill_rate:.4f} ({n_trades_0} trades / {n_ticks_0} ticks)")

    impl = compute_trading_implications(ou, fill_rate)

    print(f"\n  A-S OPTIMAL HALF-SPREAD (at various gamma and tau):")
    print(f"    {'gamma':>7s} | {'tau=1.0':>8s} | {'tau=0.5':>8s} | {'tau=0.2':>8s} | {'shift@40':>9s} | {'shift@80':>9s}")
    print(f"    {'-' * 7}-+-{'-' * 8}-+-{'-' * 8}-+-{'-' * 8}-+-{'-' * 9}-+-{'-' * 9}")
    for gamma in [0.001, 0.005, 0.01, 0.02, 0.05, 0.1]:
        hs = [impl["as_spreads"][(gamma, tau)]["half_spread"] for tau in [1.0, 0.5, 0.2]]
        s40 = impl["as_spreads"][(gamma, 1.0)]["res_shift_40"]
        s80 = impl["as_spreads"][(gamma, 1.0)]["res_shift_80"]
        print(f"    {gamma:7.3f} | {hs[0]:8.2f} | {hs[1]:8.2f} | {hs[2]:8.2f} | {s40:+9.2f} | {s80:+9.2f}")

    print(f"\n  MM BOT HALF-SPREAD: ~6.5 (from observed spread mean ~13)")
    print(f"  OUR POSTING: best±1 (half-spread = ~5.5-6.5 depending on FV rounding)")
    print(f"  => A-S optimal is MUCH wider than MM bot at all reasonable gamma values")
    print(f"  => Confirms: A-S framework doesn't help — we can't set spread wider than the MM bot")

    print(f"\n  DISPLACEMENT RISK (OU prediction of price uncertainty):")
    print(f"    {'Horizon':>8s} | {'std(X_t-X_0)':>12s} | {'Implication':>30s}")
    print(f"    {'-' * 8}-+-{'-' * 12}-+-{'-' * 30}")
    for n_ticks in [10, 50, 100, 500, 1000, 2000]:
        cr = impl["carry_risk"][n_ticks]
        # Compare to half-spread
        hs = 6.5  # MM bot half-spread
        impl_str = f"{'< half-spread (safe)' if cr['std_displacement'] < hs else '> half-spread (RISK)'}"
        print(f"    {n_ticks:8d} | {cr['std_displacement']:12.2f} | {impl_str}")

    # ══════════════════════════════════════════════════════════════
    # 9. SUMMARY: OU MODEL SCORECARD
    # ══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("9. OU MODEL SCORECARD — WHAT IT GETS RIGHT AND WRONG")
    print("=" * 80)

    print(f"""
  WHAT OU CAPTURES:
    [+] Mean-reversion exists (AC(1) ≈ -0.44, kappa > 0)
    [+] sigma ≈ 1.34 is stable across all 3 days
    [+] Stationary distribution: mid stays within ±15 of theta
    [+] Level-level R² ≈ 0.993 (near unit root but mean-reverting)

  WHAT OU MISSES:
    [-] AC(2) ≈ -0.22 is NOT zero — OU predicts AC(k>1)=0
        => AR(2) on changes is the correct minimal model
    [-] Kappa is UNSTABLE across days ({min(kappas):.6f} to {max(kappas):.6f})
        => Mean-reversion speed varies; OU's constant kappa is wrong
    [-] Discreteness: mid moves in 0.5 increments, not continuous
        => Gaussian innovations are wrong; true noise is discrete
    [-] Spread states: sigma varies by spread state
        => Wide spread (13-14): lower dmid volatility (more ticks between moves)
        => Narrow spread (5-9): higher dmid volatility (prices jumping)
    [-] A-S optimal half-spread ≈ 21 ticks >> MM bot's 6.5
        => OU + A-S framework gives USELESS spread recommendations

  TRADING CONCLUSION:
    The OU model describes WHAT HAPPENS (mean-reverting mid with sigma ≈ 1.34)
    but NOT what to DO about it. The A-S framework assumes we SET the spread,
    but in this market the MM bot sets it and we post INSIDE.

    What actually matters for PnL:
      1. TAKE: buy below FV, sell above FV (microprice regression does this)
      2. POST: at best±1 for queue priority (exploits inside-spread vs MM bot)
      3. DIRECTION: carry signal for post-direction (uses mean-reversion timing)

    The OU sigma IS useful for one thing: INVENTORY RISK SIZING.
      At sigma=1.34, holding 80 units for 100 ticks has std ≈ {math.sqrt(1.34**2 / (2 * 0.006) * (1 - math.exp(-2 * 0.006 * 100))):.1f} ticks.
      This is why position aggression at |pos|>40 helps — it limits tail risk.
""")


if __name__ == "__main__":
    main()
