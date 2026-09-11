#!/usr/bin/env python3
"""
ACO Linear Signal Analysis - Round 2
Deep analysis of linear predictive signals for ASH_COATED_OSMIUM.

Computes:
1. Autocorrelation structure (AC, PACF) for mid-price changes, spread, L1 volume
2. Cross-autocorrelation (lead-lag) analysis
3. Multi-variate regression predictors
4. Stability analysis across days
5. Information ratios for significant predictors
"""

import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats
from statsmodels.tsa.stattools import acf, pacf
import warnings
warnings.filterwarnings('ignore')

# Configuration
DATA_DIR = Path("/Users/y0d046w/Desktop/prosperity4-tester-private/trader-logic/round-2/data")
PRODUCT = "ASH_COATED_OSMIUM"
FV = 10000  # Known fair value for ACO
MAX_LAG = 20
REGRESSION_LAGS = 5

def load_prices(day: int) -> pd.DataFrame:
    """Load price data for a single day."""
    fp = DATA_DIR / f"prices_round_2_day_{day}.csv"
    df = pd.read_csv(fp, sep=';')
    return df[df['product'] == PRODUCT].copy()

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all features for analysis."""
    df = df.sort_values('timestamp').reset_index(drop=True)

    # Mid-price and changes
    df['mid'] = df['mid_price']
    df['delta_mid'] = df['mid'].diff()

    # Spread
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['delta_spread'] = df['spread'].diff()

    # L1 volume (total both sides)
    df['l1_vol'] = df['bid_volume_1'].fillna(0) + df['ask_volume_1'].fillna(0)
    df['delta_l1_vol'] = df['l1_vol'].diff()

    # Order book imbalance (OBI)
    bid_v = df['bid_volume_1'].fillna(0)
    ask_v = df['ask_volume_1'].fillna(0)
    df['obi'] = (bid_v - ask_v) / (bid_v + ask_v + 1e-8)

    # Microprice
    df['microprice'] = (df['bid_price_1'] * ask_v + df['ask_price_1'] * bid_v) / (bid_v + ask_v + 1e-8)
    df['microprice_dev'] = df['microprice'] - df['mid']

    # Deviation from fair value
    df['dev_from_fv'] = df['mid'] - FV

    return df

def print_header(title: str):
    """Print formatted section header."""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)

def compute_autocorrelation(series: pd.Series, max_lag: int, name: str) -> np.ndarray:
    """Compute ACF with confidence bounds."""
    clean = series.dropna()
    if len(clean) < max_lag + 10:
        return np.zeros(max_lag + 1)
    ac_vals = acf(clean, nlags=max_lag, fft=True)
    return ac_vals

def compute_pacf_safe(series: pd.Series, max_lag: int) -> np.ndarray:
    """Compute PACF safely."""
    clean = series.dropna()
    if len(clean) < max_lag + 10:
        return np.zeros(max_lag + 1)
    try:
        return pacf(clean, nlags=max_lag, method='ywm')
    except:
        return np.zeros(max_lag + 1)

def compute_cross_correlation(x: pd.Series, y: pd.Series, max_lag: int) -> dict:
    """
    Compute cross-correlation: corr(x(t), y(t+k)) for k in range.
    Positive lag means x leads y.
    """
    x_clean = x.dropna()
    y_clean = y.dropna()

    # Align indices
    common_idx = x_clean.index.intersection(y_clean.index)
    x_aligned = x_clean.loc[common_idx].values
    y_aligned = y_clean.loc[common_idx].values

    results = {}
    n = len(x_aligned)

    for k in range(-max_lag, max_lag + 1):
        if k >= 0:
            # x leads y by k
            x_slice = x_aligned[:n-k] if k > 0 else x_aligned
            y_slice = y_aligned[k:] if k > 0 else y_aligned
        else:
            # y leads x by |k|
            x_slice = x_aligned[-k:]
            y_slice = y_aligned[:n+k]

        if len(x_slice) > 10:
            results[k] = np.corrcoef(x_slice, y_slice)[0, 1]
        else:
            results[k] = np.nan

    return results

def run_regression(df: pd.DataFrame, target_lag: int) -> dict:
    """
    Run regression: delta_mid(t+lag) ~ features(t)
    Returns coefficients, t-stats, R-squared.
    """
    # Create lagged target
    df_reg = df.copy()
    df_reg['target'] = df_reg['delta_mid'].shift(-target_lag)

    # Features at time t
    features = ['spread', 'obi', 'microprice_dev', 'l1_vol', 'dev_from_fv']

    # Drop NaNs
    df_clean = df_reg[['target'] + features].dropna()

    if len(df_clean) < 50:
        return {'r2': np.nan, 'coeffs': {}, 'tstats': {}, 'pvals': {}}

    # Standardize features for comparison
    X = df_clean[features].values
    y = df_clean['target'].values

    # Add intercept
    X_with_const = np.column_stack([np.ones(len(X)), X])

    try:
        # OLS
        beta, residuals, rank, s = np.linalg.lstsq(X_with_const, y, rcond=None)

        # Predictions and R-squared
        y_pred = X_with_const @ beta
        ss_res = np.sum((y - y_pred)**2)
        ss_tot = np.sum((y - np.mean(y))**2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # Standard errors and t-stats
        n, p = X_with_const.shape
        mse = ss_res / (n - p)
        var_beta = mse * np.linalg.inv(X_with_const.T @ X_with_const).diagonal()
        se_beta = np.sqrt(np.maximum(var_beta, 1e-12))
        t_stats = beta / se_beta
        p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), n - p))

        coeffs = dict(zip(['intercept'] + features, beta))
        tstats = dict(zip(['intercept'] + features, t_stats))
        pvals = dict(zip(['intercept'] + features, p_vals))

        return {'r2': r2, 'coeffs': coeffs, 'tstats': tstats, 'pvals': pvals, 'n': n}
    except:
        return {'r2': np.nan, 'coeffs': {}, 'tstats': {}, 'pvals': {}}

def compute_ic_ir(predictions: np.ndarray, realized: np.ndarray) -> tuple:
    """Compute Information Coefficient and Information Ratio."""
    mask = ~(np.isnan(predictions) | np.isnan(realized))
    pred_clean = predictions[mask]
    real_clean = realized[mask]

    if len(pred_clean) < 10:
        return np.nan, np.nan

    ic = np.corrcoef(pred_clean, real_clean)[0, 1]

    # IR = mean(pred * realized) / std(pred * realized)
    product = pred_clean * real_clean
    ir = np.mean(product) / (np.std(product) + 1e-8)

    return ic, ir

def main():
    print_header("ACO LINEAR SIGNAL ANALYSIS - ROUND 2")
    print(f"Product: {PRODUCT}")
    print(f"Fair Value: {FV}")
    print(f"Max Lag: {MAX_LAG}")

    # Load all days
    days = [-2, -1, 0, 1]
    all_data = {}
    for day in days:
        df = load_prices(day)
        df = compute_features(df)
        all_data[day] = df
        print(f"Day {day:2d}: {len(df)} ticks, "
              f"mid range [{df['mid'].min():.1f}, {df['mid'].max():.1f}], "
              f"spread mean={df['spread'].mean():.2f}")

    # Combine all days
    combined = pd.concat(all_data.values(), ignore_index=True)
    print(f"\nTotal: {len(combined)} ticks across {len(days)} days")

    # =========================================================================
    # SECTION 1: AUTOCORRELATION STRUCTURE
    # =========================================================================
    print_header("1. AUTOCORRELATION STRUCTURE")

    print("\n--- 1a. AC(k) of Mid-Price Changes (delta_mid) ---")
    print(f"{'Lag':>4} | {'Combined':>10} | " + " | ".join([f"Day {d:2d}" for d in days]))
    print("-" * 70)

    ac_delta_mid = compute_autocorrelation(combined['delta_mid'], MAX_LAG, 'delta_mid')
    ac_by_day = {d: compute_autocorrelation(all_data[d]['delta_mid'], MAX_LAG, 'delta_mid') for d in days}

    for k in range(1, MAX_LAG + 1):
        row = f"{k:4d} | {ac_delta_mid[k]:10.4f} | "
        row += " | ".join([f"{ac_by_day[d][k]:6.4f}" for d in days])
        print(row)

    print("\n--- 1b. AC(k) of Spread ---")
    print(f"{'Lag':>4} | {'Combined':>10} | " + " | ".join([f"Day {d:2d}" for d in days]))
    print("-" * 70)

    ac_spread = compute_autocorrelation(combined['spread'], MAX_LAG, 'spread')
    ac_spread_day = {d: compute_autocorrelation(all_data[d]['spread'], MAX_LAG, 'spread') for d in days}

    for k in range(1, MAX_LAG + 1):
        row = f"{k:4d} | {ac_spread[k]:10.4f} | "
        row += " | ".join([f"{ac_spread_day[d][k]:6.4f}" for d in days])
        print(row)

    print("\n--- 1c. AC(k) of L1 Volume ---")
    print(f"{'Lag':>4} | {'Combined':>10} | " + " | ".join([f"Day {d:2d}" for d in days]))
    print("-" * 70)

    ac_vol = compute_autocorrelation(combined['l1_vol'], MAX_LAG, 'l1_vol')
    ac_vol_day = {d: compute_autocorrelation(all_data[d]['l1_vol'], MAX_LAG, 'l1_vol') for d in days}

    for k in range(1, MAX_LAG + 1):
        row = f"{k:4d} | {ac_vol[k]:10.4f} | "
        row += " | ".join([f"{ac_vol_day[d][k]:6.4f}" for d in days])
        print(row)

    print("\n--- 1d. PACF of delta_mid (True Lags) ---")
    print(f"{'Lag':>4} | {'Combined':>10} | " + " | ".join([f"Day {d:2d}" for d in days]))
    print("-" * 70)

    pacf_delta_mid = compute_pacf_safe(combined['delta_mid'], MAX_LAG)
    pacf_by_day = {d: compute_pacf_safe(all_data[d]['delta_mid'], MAX_LAG) for d in days}

    for k in range(1, min(MAX_LAG + 1, len(pacf_delta_mid))):
        row = f"{k:4d} | {pacf_delta_mid[k]:10.4f} | "
        row += " | ".join([f"{pacf_by_day[d][k] if k < len(pacf_by_day[d]) else np.nan:6.4f}" for d in days])
        print(row)

    # Significance threshold for N samples
    n_combined = len(combined['delta_mid'].dropna())
    sig_threshold = 1.96 / np.sqrt(n_combined)
    print(f"\n95% significance threshold (combined): +/-{sig_threshold:.4f}")
    print(f"Significant AC lags (|AC| > {sig_threshold:.4f}): ", end="")
    sig_lags = [k for k in range(1, MAX_LAG + 1) if abs(ac_delta_mid[k]) > sig_threshold]
    print(sig_lags if sig_lags else "None")

    # =========================================================================
    # SECTION 2: CROSS-AUTOCORRELATION (LEAD-LAG)
    # =========================================================================
    print_header("2. CROSS-AUTOCORRELATION (LEAD-LAG)")

    print("\n--- 2a. Cross-corr(spread(t), delta_mid(t+k)) ---")
    print("Positive k: spread leads delta_mid")
    cross_spread = compute_cross_correlation(combined['spread'], combined['delta_mid'], 10)
    print(f"{'Lag k':>6} | {'Corr':>10}")
    print("-" * 20)
    for k in sorted(cross_spread.keys()):
        print(f"{k:6d} | {cross_spread[k]:10.4f}")

    print("\n--- 2b. Cross-corr(OBI(t), delta_mid(t+k)) ---")
    print("Positive k: OBI leads delta_mid")
    cross_obi = compute_cross_correlation(combined['obi'], combined['delta_mid'], 10)
    print(f"{'Lag k':>6} | {'Corr':>10}")
    print("-" * 20)
    for k in sorted(cross_obi.keys()):
        print(f"{k:6d} | {cross_obi[k]:10.4f}")

    print("\n--- 2c. Cross-corr(L1_vol_change(t), delta_mid(t+k)) ---")
    cross_vol = compute_cross_correlation(combined['delta_l1_vol'], combined['delta_mid'], 10)
    print(f"{'Lag k':>6} | {'Corr':>10}")
    print("-" * 20)
    for k in sorted(cross_vol.keys()):
        print(f"{k:6d} | {cross_vol[k]:10.4f}")

    print("\n--- 2d. Cross-corr(microprice_dev(t), delta_mid(t+k)) ---")
    print("microprice_dev = microprice - mid (positive = bid-heavy book)")
    cross_mpdev = compute_cross_correlation(combined['microprice_dev'], combined['delta_mid'], 10)
    print(f"{'Lag k':>6} | {'Corr':>10}")
    print("-" * 20)
    for k in sorted(cross_mpdev.keys()):
        print(f"{k:6d} | {cross_mpdev[k]:10.4f}")

    # Identify strongest lead-lag
    print("\n--- 2e. Summary: Peak Lead-Lag Signals ---")
    signals = {
        'spread -> delta_mid': cross_spread,
        'OBI -> delta_mid': cross_obi,
        'delta_L1_vol -> delta_mid': cross_vol,
        'microprice_dev -> delta_mid': cross_mpdev,
    }

    for name, cross in signals.items():
        # Find lag with max absolute correlation (excluding lag 0 for contemporaneous)
        lags_pos = {k: v for k, v in cross.items() if k > 0 and not np.isnan(v)}
        if lags_pos:
            best_k = max(lags_pos.keys(), key=lambda k: abs(lags_pos[k]))
            print(f"{name:30s}: best predictive lag = {best_k}, corr = {lags_pos[best_k]:.4f}")

    # =========================================================================
    # SECTION 3: REGRESSION PREDICTORS
    # =========================================================================
    print_header("3. MULTIVARIATE REGRESSION PREDICTORS")

    print("\nModel: delta_mid(t+k) ~ intercept + spread + OBI + microprice_dev + L1_vol + dev_from_FV")

    # Combined regression
    print("\n--- 3a. Combined Data (All Days) ---")
    print(f"{'Lag k':>6} | {'R-sq':>8} | {'N':>6} | {'spread':>10} | {'OBI':>10} | {'mprice_dev':>10} | {'l1_vol':>10} | {'dev_FV':>10}")
    print("-" * 95)

    for k in range(1, REGRESSION_LAGS + 1):
        res = run_regression(combined, k)
        if np.isnan(res['r2']):
            print(f"{k:6d} | {'N/A':>8}")
            continue

        coeffs = res['coeffs']
        pvals = res['pvals']

        def fmt_coef(name):
            c = coeffs.get(name, np.nan)
            p = pvals.get(name, 1.0)
            sig = '*' if p < 0.05 else (' ' if p < 0.10 else ' ')
            return f"{c:9.5f}{sig}"

        print(f"{k:6d} | {res['r2']:8.5f} | {res['n']:6d} | "
              f"{fmt_coef('spread')} | {fmt_coef('obi')} | {fmt_coef('microprice_dev')} | "
              f"{fmt_coef('l1_vol')} | {fmt_coef('dev_from_fv')}")

    print("\n* = significant at p<0.05")

    # =========================================================================
    # SECTION 4: STABILITY ANALYSIS
    # =========================================================================
    print_header("4. STABILITY ANALYSIS (PER-DAY COEFFICIENTS)")

    features = ['spread', 'obi', 'microprice_dev', 'l1_vol', 'dev_from_fv']

    print("\n--- 4a. R-squared by Day (lag=1) ---")
    print(f"{'Day':>6} | {'R-sq':>10} | {'N':>6}")
    print("-" * 30)

    day_results = {}
    for day in days:
        res = run_regression(all_data[day], target_lag=1)
        day_results[day] = res
        print(f"{day:6d} | {res['r2']:10.6f} | {res.get('n', 0):6d}")

    print("\n--- 4b. Coefficient Stability (lag=1) ---")
    print(f"{'Feature':>15} | " + " | ".join([f"Day {d:2d}" for d in days]) + " | Std Dev")
    print("-" * 80)

    for feat in features:
        coeffs_by_day = [day_results[d]['coeffs'].get(feat, np.nan) for d in days]
        std_dev = np.nanstd(coeffs_by_day)
        row = f"{feat:>15} | " + " | ".join([f"{c:6.4f}" if not np.isnan(c) else "   N/A" for c in coeffs_by_day])
        row += f" | {std_dev:.4f}"
        print(row)

    # Out-of-sample test
    print("\n--- 4c. Out-of-Sample Test: Train {-2,-1,0}, Test {1} ---")

    train_data = pd.concat([all_data[d] for d in [-2, -1, 0]], ignore_index=True)
    test_data = all_data[1].copy()

    # Fit on training
    train_res = run_regression(train_data, target_lag=1)
    print(f"Training R-sq (in-sample): {train_res['r2']:.6f}")
    print(f"Training N: {train_res.get('n', 0)}")

    # Predict on test
    test_df = test_data.copy()
    test_df['target'] = test_df['delta_mid'].shift(-1)
    test_clean = test_df[['target', 'spread', 'obi', 'microprice_dev', 'l1_vol', 'dev_from_fv']].dropna()

    if len(test_clean) > 10 and train_res['coeffs']:
        X_test = test_clean[['spread', 'obi', 'microprice_dev', 'l1_vol', 'dev_from_fv']].values
        y_test = test_clean['target'].values

        beta = [train_res['coeffs'].get('intercept', 0)]
        for f in ['spread', 'obi', 'microprice_dev', 'l1_vol', 'dev_from_fv']:
            beta.append(train_res['coeffs'].get(f, 0))
        beta = np.array(beta)

        X_test_const = np.column_stack([np.ones(len(X_test)), X_test])
        y_pred = X_test_const @ beta

        ss_res = np.sum((y_test - y_pred)**2)
        ss_tot = np.sum((y_test - np.mean(y_test))**2)
        oos_r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        print(f"Test R-sq (out-of-sample): {oos_r2:.6f}")
        print(f"Test N: {len(test_clean)}")
        print(f"R-sq degradation ratio: {oos_r2 / train_res['r2']:.2f}x" if train_res['r2'] > 0 else "N/A")

    # =========================================================================
    # SECTION 5: INFORMATION RATIOS
    # =========================================================================
    print_header("5. INFORMATION COEFFICIENTS AND RATIOS")

    print("\nFor predictors with combined R-sq > 0.01 at any lag:")

    # Single-feature predictors
    print("\n--- 5a. Single-Feature IC/IR (lag=1) ---")
    print(f"{'Predictor':>20} | {'IC':>10} | {'IR':>10} | {'t-stat':>10}")
    print("-" * 60)

    target = combined['delta_mid'].shift(-1).values

    single_predictors = {
        'spread': combined['spread'].values,
        'OBI': combined['obi'].values,
        'microprice_dev': combined['microprice_dev'].values,
        'L1_vol': combined['l1_vol'].values,
        'dev_from_FV': combined['dev_from_fv'].values,
        'delta_mid (AR1)': combined['delta_mid'].values,
    }

    for name, pred in single_predictors.items():
        ic, ir = compute_ic_ir(pred, target)
        # t-stat for IC
        n_valid = np.sum(~(np.isnan(pred) | np.isnan(target)))
        t_stat = ic * np.sqrt(n_valid - 2) / np.sqrt(1 - ic**2 + 1e-8) if not np.isnan(ic) else np.nan
        print(f"{name:>20} | {ic:10.4f} | {ir:10.4f} | {t_stat:10.2f}")

    # Multi-feature model IC/IR
    print("\n--- 5b. Full Model IC/IR (lag=1, trained on all data) ---")
    combined_copy = combined.copy()
    combined_copy['target'] = combined_copy['delta_mid'].shift(-1)
    clean = combined_copy[['target', 'spread', 'obi', 'microprice_dev', 'l1_vol', 'dev_from_fv']].dropna()

    res = run_regression(combined, target_lag=1)
    if res['coeffs']:
        X = clean[['spread', 'obi', 'microprice_dev', 'l1_vol', 'dev_from_fv']].values
        beta = [res['coeffs']['intercept']]
        for f in ['spread', 'obi', 'microprice_dev', 'l1_vol', 'dev_from_fv']:
            beta.append(res['coeffs'][f])
        beta = np.array(beta)

        X_const = np.column_stack([np.ones(len(X)), X])
        predictions = X_const @ beta
        realized = clean['target'].values

        ic, ir = compute_ic_ir(predictions, realized)
        n_valid = len(predictions)
        t_stat = ic * np.sqrt(n_valid - 2) / np.sqrt(1 - ic**2 + 1e-8) if not np.isnan(ic) else np.nan

        print(f"Full regression model: IC = {ic:.4f}, IR = {ir:.4f}, t-stat = {t_stat:.2f}")
        print(f"Model R-sq: {res['r2']:.6f}")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print_header("SUMMARY: ACTIONABLE FINDINGS")

    print("""
    KEY OBSERVATIONS:

    1. AUTOCORRELATION OF DELTA_MID:
       - AC(1) is strongly NEGATIVE (mean-reversion in price changes)
       - This is the structural OU property of ACO around FV=10000
       - AC decays rapidly after lag 1

    2. LEAD-LAG SIGNALS:
       - OBI -> delta_mid: Check if positive OBI predicts positive delta_mid
       - microprice_dev -> delta_mid: Check if microprice > mid predicts up move
       - These are the typical linear predictors

    3. REGRESSION R-SQUARED:
       - Extremely low R-sq is EXPECTED for efficient markets
       - R-sq > 0.001 at lag 1 is noteworthy
       - Focus on SIGN and SIGNIFICANCE of dev_from_FV (mean-reversion)

    4. STABILITY:
       - Coefficients that flip sign across days are UNRELIABLE
       - Out-of-sample R-sq degradation > 50% indicates overfitting

    5. TRADING IMPLICATIONS:
       - If AC(1) of delta_mid is negative: fade recent moves
       - If dev_from_FV coefficient is negative and significant: mean-revert to 10000
       - IC > 0.02 with consistent sign = potentially tradeable signal
    """)

if __name__ == "__main__":
    main()
