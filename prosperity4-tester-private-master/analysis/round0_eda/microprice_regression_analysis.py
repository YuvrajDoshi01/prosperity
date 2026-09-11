"""
L1 vs L2 vs VWAP Microprice Regression Analysis for TOMATOES
============================================================
Rigorous comparison of microprice variants as inputs to 4-lag linear regression
predicting next-tick mid-price change.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

np.set_printoptions(precision=6, suppress=True)

# ============================================================
# DATA LOADING
# ============================================================

BASE = Path("/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0")

def load_day(day_label):
    """Load and filter TOMATOES data for a given day."""
    fname = f"prices_round_0_day_{day_label}.csv"
    df = pd.read_csv(BASE / fname, sep=";")
    tom = df[df["product"] == "TOMATOES"].copy()
    tom = tom.sort_values("timestamp").reset_index(drop=True)
    return tom

days = {"-2": load_day("-2"), "-1": load_day("-1"), "0": load_day("0")}

for label, df in days.items():
    print(f"Day {label}: {len(df)} rows, timestamps {df['timestamp'].min()}-{df['timestamp'].max()}")
    # Check for L3 data
    l3_bid = df["bid_price_3"].notna().sum()
    l3_ask = df["ask_price_3"].notna().sum()
    print(f"  L3 data present: bid={l3_bid}/{len(df)}, ask={l3_ask}/{len(df)}")
    print(f"  L2 data present: bid={df['bid_price_2'].notna().sum()}/{len(df)}, ask={df['ask_price_2'].notna().sum()}/{len(df)}")
    print()

# ============================================================
# MICROPRICE COMPUTATION
# ============================================================

def compute_microprices(df):
    """
    Compute three microprice variants:
    1. L1 microprice: best_bid + (total_bid_vol / (total_bid_vol + total_ask_vol)) * spread
       where total_bid_vol/ask_vol = sum of ALL level volumes
    2. L2 microprice: using ONLY second-level prices and volumes
    3. VWAP microprice: volume-weighted average across ALL levels
    """
    # Extract columns
    bp1 = df["bid_price_1"].values.astype(float)
    bv1 = df["bid_volume_1"].values.astype(float)
    bp2 = df["bid_price_2"].values.astype(float)
    bv2 = df["bid_volume_2"].values.astype(float)
    ap1 = df["ask_price_1"].values.astype(float)
    av1 = df["ask_volume_1"].values.astype(float)  # Note: ask volumes in CSV are positive
    ap2 = df["ask_price_2"].values.astype(float)
    av2 = df["ask_volume_2"].values.astype(float)

    mid = df["mid_price"].values.astype(float)

    # Handle NaN in L2 (shouldn't be present for TOMATOES but be safe)
    has_l2 = np.isfinite(bp2) & np.isfinite(bv2) & np.isfinite(ap2) & np.isfinite(av2)

    # --- L1 Microprice ---
    # best_bid + (total_bid_vol / (total_bid_vol + total_ask_vol)) * (best_ask - best_bid)
    # total volumes = sum across ALL levels
    total_bid_vol = bv1.copy()
    total_ask_vol = av1.copy()
    total_bid_vol[has_l2] += bv2[has_l2]
    total_ask_vol[has_l2] += av2[has_l2]

    spread = ap1 - bp1
    l1_mp = bp1 + (total_bid_vol / (total_bid_vol + total_ask_vol)) * spread

    # --- L2 Microprice ---
    # l2_bid_price * l2_ask_vol / (l2_bid_vol + l2_ask_vol) + l2_ask_price * l2_bid_vol / (l2_bid_vol + l2_ask_vol)
    l2_mp = np.full_like(bp1, np.nan)
    l2_total = bv2 + av2
    mask = has_l2 & (l2_total > 0)
    l2_mp[mask] = (bp2[mask] * av2[mask] + ap2[mask] * bv2[mask]) / l2_total[mask]

    # --- VWAP Microprice ---
    # Volume-weighted average across ALL levels
    vwap_mp = np.full_like(bp1, np.nan)
    # Numerator: sum(price_i * volume_i) for all levels
    num = bp1 * bv1 + ap1 * av1
    den = bv1 + av1
    num[has_l2] += bp2[has_l2] * bv2[has_l2] + ap2[has_l2] * av2[has_l2]
    den[has_l2] += bv2[has_l2] + av2[has_l2]
    vwap_mp = num / den

    return l1_mp, l2_mp, vwap_mp, mid, has_l2


# Compute for all days
results = {}
for label, df in days.items():
    l1, l2, vwap, mid, has_l2 = compute_microprices(df)
    results[label] = {
        "l1_mp": l1, "l2_mp": l2, "vwap_mp": vwap, "mid": mid,
        "has_l2": has_l2, "timestamp": df["timestamp"].values
    }

    # Basic stats
    print(f"\n=== Day {label} Microprice Statistics ===")
    print(f"  L1 microprice:   mean={np.nanmean(l1):.4f}, std={np.nanstd(l1):.4f}")
    print(f"  L2 microprice:   mean={np.nanmean(l2):.4f}, std={np.nanstd(l2):.4f}")
    print(f"  VWAP microprice: mean={np.nanmean(vwap):.4f}, std={np.nanstd(vwap):.4f}")
    print(f"  Mid price:       mean={np.nanmean(mid):.4f}, std={np.nanstd(mid):.4f}")
    print(f"  L2 available: {has_l2.sum()}/{len(has_l2)} ticks")

    # Spread between variants
    diff_l1_l2 = l1 - l2
    diff_l1_vwap = l1 - vwap
    print(f"  L1 - L2:   mean={np.nanmean(diff_l1_l2):.4f}, std={np.nanstd(diff_l1_l2):.4f}, max_abs={np.nanmax(np.abs(diff_l1_l2)):.4f}")
    print(f"  L1 - VWAP: mean={np.nanmean(diff_l1_vwap):.4f}, std={np.nanstd(diff_l1_vwap):.4f}, max_abs={np.nanmax(np.abs(diff_l1_vwap)):.4f}")


# ============================================================
# AUTOCORRELATION ANALYSIS
# ============================================================

print("\n" + "="*70)
print("AUTOCORRELATION ANALYSIS")
print("="*70)

for label in ["-2", "-1", "0"]:
    d = results[label]
    print(f"\n--- Day {label} ---")
    for mp_name, mp_series in [("L1", d["l1_mp"]), ("L2", d["l2_mp"]), ("VWAP", d["vwap_mp"]), ("Mid", d["mid"])]:
        valid = mp_series[np.isfinite(mp_series)]
        if len(valid) < 10:
            print(f"  {mp_name}: insufficient data")
            continue
        ac1 = np.corrcoef(valid[:-1], valid[1:])[0, 1]
        # Autocorrelation of CHANGES
        changes = np.diff(valid)
        if np.std(changes) > 0:
            ac1_changes = np.corrcoef(changes[:-1], changes[1:])[0, 1]
        else:
            ac1_changes = 0.0
        print(f"  {mp_name} levels AC(1): {ac1:.6f}  |  Changes AC(1): {ac1_changes:.6f}")

# Cross-correlation between variants
print("\n--- Cross-correlations (levels) ---")
for label in ["-2", "-1", "0"]:
    d = results[label]
    mask = np.isfinite(d["l1_mp"]) & np.isfinite(d["l2_mp"]) & np.isfinite(d["vwap_mp"])
    l1 = d["l1_mp"][mask]
    l2 = d["l2_mp"][mask]
    vwap = d["vwap_mp"][mask]
    mid = d["mid"][mask]

    print(f"\nDay {label}:")
    print(f"  corr(L1, L2)   = {np.corrcoef(l1, l2)[0,1]:.8f}")
    print(f"  corr(L1, VWAP) = {np.corrcoef(l1, vwap)[0,1]:.8f}")
    print(f"  corr(L2, VWAP) = {np.corrcoef(l2, vwap)[0,1]:.8f}")
    print(f"  corr(L1, Mid)  = {np.corrcoef(l1, mid)[0,1]:.8f}")

# Cross-correlation of CHANGES
print("\n--- Cross-correlations (changes) ---")
for label in ["-2", "-1", "0"]:
    d = results[label]
    mask = np.isfinite(d["l1_mp"]) & np.isfinite(d["l2_mp"]) & np.isfinite(d["vwap_mp"])
    l1_c = np.diff(d["l1_mp"][mask])
    l2_c = np.diff(d["l2_mp"][mask])
    vwap_c = np.diff(d["vwap_mp"][mask])
    mid_c = np.diff(d["mid"][mask])

    print(f"\nDay {label}:")
    print(f"  corr(dL1, dL2)   = {np.corrcoef(l1_c, l2_c)[0,1]:.6f}")
    print(f"  corr(dL1, dVWAP) = {np.corrcoef(l1_c, vwap_c)[0,1]:.6f}")
    print(f"  corr(dL2, dVWAP) = {np.corrcoef(l2_c, vwap_c)[0,1]:.6f}")
    print(f"  corr(dL1, dMid)  = {np.corrcoef(l1_c, mid_c)[0,1]:.6f}")
    print(f"  corr(dL2, dMid)  = {np.corrcoef(l2_c, mid_c)[0,1]:.6f}")


# ============================================================
# 4-LAG REGRESSION
# ============================================================

print("\n" + "="*70)
print("4-LAG REGRESSION: mid[t+1] = a + c1*mp[t-3] + c2*mp[t-2] + c3*mp[t-1] + c4*mp[t]")
print("="*70)

def build_regression_data(mp_series, mid_series):
    """
    Build X (4 lags of microprice) and y (next-tick mid) arrays.

    mid[t+1] = intercept + c1*mp[t-3] + c2*mp[t-2] + c3*mp[t-1] + c4*mp[t]

    For tick index t (where t >= 3), we need:
      y = mid[t+1]
      X = [mp[t-3], mp[t-2], mp[t-1], mp[t]]

    So valid indices: t = 3, 4, ..., N-2 (need t+1 <= N-1)
    """
    n = len(mp_series)
    valid_mask = np.ones(n, dtype=bool)
    valid_mask &= np.isfinite(mp_series)
    valid_mask &= np.isfinite(mid_series)

    # Build lag matrix
    rows = []
    y_vals = []

    for t in range(3, n - 1):
        # Check all needed indices are valid
        if all(valid_mask[t-j] for j in range(4)) and valid_mask[t+1]:
            rows.append([mp_series[t-3], mp_series[t-2], mp_series[t-1], mp_series[t]])
            y_vals.append(mid_series[t+1])

    X = np.array(rows)
    y = np.array(y_vals)
    return X, y


def fit_ols(X, y):
    """Fit OLS with intercept. Return coefficients, intercept, R², RMSE, residuals."""
    n, k = X.shape
    X_aug = np.column_stack([np.ones(n), X])
    beta, residuals, rank, sv = np.linalg.lstsq(X_aug, y, rcond=None)

    y_hat = X_aug @ beta
    ss_res = np.sum((y - y_hat)**2)
    ss_tot = np.sum((y - np.mean(y))**2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    rmse = np.sqrt(ss_res / n)

    intercept = beta[0]
    coefs = beta[1:]

    return coefs, intercept, r2, rmse, y_hat


def oos_predict(X_test, y_test, coefs, intercept):
    """Out-of-sample R² and RMSE."""
    X_aug = np.column_stack([np.ones(len(X_test)), X_test])
    beta = np.concatenate([[intercept], coefs])
    y_hat = X_aug @ beta

    ss_res = np.sum((y_test - y_hat)**2)
    ss_tot = np.sum((y_test - np.mean(y_test))**2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    rmse = np.sqrt(ss_res / len(y_test))

    return r2, rmse, y_hat


# ============================================================
# IN-SAMPLE: Fit on each day separately
# ============================================================

print("\n--- IN-SAMPLE RESULTS (each day separately) ---\n")

for label in ["-2", "-1", "0"]:
    d = results[label]
    print(f"{'='*60}")
    print(f"Day {label}")
    print(f"{'='*60}")

    for mp_name, mp_series in [("L1", d["l1_mp"]), ("L2", d["l2_mp"]), ("VWAP", d["vwap_mp"])]:
        X, y = build_regression_data(mp_series, d["mid"])
        if len(X) < 10:
            print(f"  {mp_name}: insufficient data ({len(X)} rows)")
            continue

        coefs, intercept, r2, rmse, y_hat = fit_ols(X, y)

        print(f"\n  {mp_name} Microprice (n={len(y)})")
        print(f"    R²:        {r2:.6f}")
        print(f"    RMSE:      {rmse:.6f}")
        print(f"    Intercept: {intercept:.6f}")
        print(f"    Coefs:     [{', '.join(f'{c:.6f}' for c in coefs)}]")
        print(f"    Coef sum:  {np.sum(coefs):.6f}")


# ============================================================
# OUT-OF-SAMPLE: Train on days -2 & -1, test on day 0
# ============================================================

print("\n" + "="*70)
print("OUT-OF-SAMPLE: Train on days -2 & -1, test on day 0")
print("="*70)

oos_results = {}

for mp_name in ["L1", "L2", "VWAP"]:
    mp_key = {"L1": "l1_mp", "L2": "l2_mp", "VWAP": "vwap_mp"}[mp_name]

    # Build training data from days -2 and -1
    X_trains, y_trains = [], []
    for train_label in ["-2", "-1"]:
        d = results[train_label]
        X_d, y_d = build_regression_data(d[mp_key], d["mid"])
        X_trains.append(X_d)
        y_trains.append(y_d)

    X_train = np.vstack(X_trains)
    y_train = np.concatenate(y_trains)

    # Fit on training
    coefs, intercept, r2_train, rmse_train, _ = fit_ols(X_train, y_train)

    # Test on day 0
    d0 = results["0"]
    X_test, y_test = build_regression_data(d0[mp_key], d0["mid"])
    r2_test, rmse_test, y_hat_test = oos_predict(X_test, y_test, coefs, intercept)

    # Also fit day 0 in-sample for comparison
    coefs_d0, intercept_d0, r2_d0, rmse_d0, y_hat_d0 = fit_ols(X_test, y_test)

    print(f"\n{mp_name} Microprice:")
    print(f"  TRAIN (days -2,-1):  n={len(y_train)}, R²={r2_train:.6f}, RMSE={rmse_train:.6f}")
    print(f"  TEST  (day 0):       n={len(y_test)},  R²={r2_test:.6f},  RMSE={rmse_test:.6f}")
    print(f"  Day 0 IS:            n={len(y_test)},  R²={r2_d0:.6f},  RMSE={rmse_d0:.6f}")
    print(f"  R² drop (IS→OOS):    {r2_d0 - r2_test:.6f}")
    print(f"  Train coefs:  [{', '.join(f'{c:.6f}' for c in coefs)}], intercept={intercept:.6f}")
    print(f"  Day0 coefs:   [{', '.join(f'{c:.6f}' for c in coefs_d0)}], intercept={intercept_d0:.6f}")

    oos_results[mp_name] = {
        "coefs": coefs, "intercept": intercept,
        "coefs_d0": coefs_d0, "intercept_d0": intercept_d0,
        "r2_train": r2_train, "r2_test": r2_test, "r2_d0": r2_d0,
        "rmse_train": rmse_train, "rmse_test": rmse_test, "rmse_d0": rmse_d0,
        "y_hat_test": y_hat_test, "y_hat_d0": y_hat_d0,
        "y_test": y_test, "X_test": X_test,
    }


# ============================================================
# CRITICAL: INTEGER FV COMPARISON
# ============================================================

print("\n" + "="*70)
print("CRITICAL: INTEGER-ROUNDED FV COMPARISON (L1 vs L2 vs VWAP)")
print("="*70)

# Use OOS coefficients (trained on -2/-1) for real predictive comparison
# Also compare with in-sample day 0 coefficients

for coef_source, coef_label in [("oos", "OOS (train -2/-1)"), ("is", "IS (day 0)")]:
    print(f"\n{'='*60}")
    print(f"Using {coef_label} coefficients")
    print(f"{'='*60}")

    d0 = results["0"]

    # Get predictions from each model
    preds = {}
    for mp_name in ["L1", "L2", "VWAP"]:
        r = oos_results[mp_name]
        if coef_source == "oos":
            preds[mp_name] = r["y_hat_test"]
        else:
            preds[mp_name] = r["y_hat_d0"]

    y_actual = oos_results["L1"]["y_test"]  # same y for all

    # Integer-rounded FV
    fv_int = {}
    for mp_name in ["L1", "L2", "VWAP"]:
        fv_int[mp_name] = np.round(preds[mp_name])

    # Where do they differ?
    n_total = len(y_actual)

    # Pairwise comparison: L1 vs L2
    diff_l1_l2 = fv_int["L1"] != fv_int["L2"]
    n_diff_l1_l2 = np.sum(diff_l1_l2)

    # Pairwise comparison: L1 vs VWAP
    diff_l1_vwap = fv_int["L1"] != fv_int["VWAP"]
    n_diff_l1_vwap = np.sum(diff_l1_vwap)

    # Pairwise comparison: L2 vs VWAP
    diff_l2_vwap = fv_int["L2"] != fv_int["VWAP"]
    n_diff_l2_vwap = np.sum(diff_l2_vwap)

    # Any differ
    any_diff = diff_l1_l2 | diff_l1_vwap | diff_l2_vwap
    n_any_diff = np.sum(any_diff)

    print(f"\n  Total ticks: {n_total}")
    print(f"  Ticks where integer FV differs:")
    print(f"    L1 vs L2:   {n_diff_l1_l2} ({100*n_diff_l1_l2/n_total:.2f}%)")
    print(f"    L1 vs VWAP: {n_diff_l1_vwap} ({100*n_diff_l1_vwap/n_total:.2f}%)")
    print(f"    L2 vs VWAP: {n_diff_l2_vwap} ({100*n_diff_l2_vwap/n_total:.2f}%)")
    print(f"    Any pair:   {n_any_diff} ({100*n_any_diff/n_total:.2f}%)")

    # On disagreement ticks: which model was closer to actual next mid?
    for pair_name, diff_mask, mp_a, mp_b in [
        ("L1 vs L2", diff_l1_l2, "L1", "L2"),
        ("L1 vs VWAP", diff_l1_vwap, "L1", "VWAP"),
        ("L2 vs VWAP", diff_l2_vwap, "L2", "VWAP"),
    ]:
        if np.sum(diff_mask) == 0:
            print(f"\n  {pair_name}: No disagreements")
            continue

        err_a = np.abs(preds[mp_a][diff_mask] - y_actual[diff_mask])
        err_b = np.abs(preds[mp_b][diff_mask] - y_actual[diff_mask])

        a_wins = np.sum(err_a < err_b)
        b_wins = np.sum(err_b < err_a)
        ties = np.sum(err_a == err_b)
        n_diff = np.sum(diff_mask)

        # Also check integer-rounded accuracy
        int_err_a = np.abs(fv_int[mp_a][diff_mask] - y_actual[diff_mask])
        int_err_b = np.abs(fv_int[mp_b][diff_mask] - y_actual[diff_mask])

        int_a_wins = np.sum(int_err_a < int_err_b)
        int_b_wins = np.sum(int_err_b < int_err_a)
        int_ties = np.sum(int_err_a == int_err_b)

        print(f"\n  {pair_name} ({n_diff} disagreement ticks):")
        print(f"    Raw prediction closer to actual:")
        print(f"      {mp_a} wins: {a_wins} ({100*a_wins/n_diff:.1f}%)")
        print(f"      {mp_b} wins: {b_wins} ({100*b_wins/n_diff:.1f}%)")
        print(f"      Ties:       {ties} ({100*ties/n_diff:.1f}%)")
        print(f"    Integer FV closer to actual:")
        print(f"      {mp_a} wins: {int_a_wins} ({100*int_a_wins/n_diff:.1f}%)")
        print(f"      {mp_b} wins: {int_b_wins} ({100*int_b_wins/n_diff:.1f}%)")
        print(f"      Ties:       {int_ties} ({100*int_ties/n_diff:.1f}%)")

        # Mean absolute error on disagreement ticks
        print(f"    Mean |error| on disagreement ticks:")
        print(f"      {mp_a}: {np.mean(err_a):.4f} (int: {np.mean(int_err_a):.4f})")
        print(f"      {mp_b}: {np.mean(err_b):.4f} (int: {np.mean(int_err_b):.4f})")


# ============================================================
# DETAILED INTEGER BOUNDARY ANALYSIS
# ============================================================

print("\n" + "="*70)
print("INTEGER BOUNDARY ANALYSIS")
print("="*70)

# The key question: does L2 microprice help select better integer-rounded FVs?
# Compute for day 0 using OOS coefficients

d0 = results["0"]

for mp_name in ["L1", "L2", "VWAP"]:
    r = oos_results[mp_name]
    y_hat = r["y_hat_test"]
    y_actual = r["y_test"]

    fv_int = np.round(y_hat)

    # How often is integer FV correct (== actual next mid)?
    exact_match = np.sum(fv_int == y_actual)
    within_half = np.sum(np.abs(fv_int - y_actual) <= 0.5)

    # Direction: does FV correctly predict mid change?
    # mid[t+1] > mid[t] and FV > mid[t]
    # We need mid[t] which corresponds to the y at t-1
    # Actually, y_actual = mid[t+1]. We need mid[t].
    # From build_regression_data, for row i in our arrays:
    #   y[i] = mid[t+1] where t = i + 3
    #   X[i] = [mp[t-3], ..., mp[t]]
    # So mid[t] corresponds to d0["mid"][i+3]

    # Let's rebuild to get mid[t] aligned
    mp_key = {"L1": "l1_mp", "L2": "l2_mp", "VWAP": "vwap_mp"}[mp_name]
    mp_series = d0[mp_key]
    mid_series = d0["mid"]
    n = len(mp_series)

    mid_t_list = []
    valid_mask = np.isfinite(mp_series) & np.isfinite(mid_series)
    for t in range(3, n - 1):
        if all(valid_mask[t-j] for j in range(4)) and valid_mask[t+1]:
            mid_t_list.append(mid_series[t])
    mid_t = np.array(mid_t_list)

    # Direction accuracy
    actual_dir = np.sign(y_actual - mid_t)
    pred_dir = np.sign(y_hat - mid_t)

    # Only count ticks where there IS a move
    moving = actual_dir != 0
    if np.sum(moving) > 0:
        dir_correct = np.sum((actual_dir[moving] == pred_dir[moving]))
        dir_total = np.sum(moving)
        dir_accuracy = dir_correct / dir_total
    else:
        dir_accuracy = 0.0
        dir_total = 0

    print(f"\n{mp_name} Microprice (OOS coefs, day 0):")
    print(f"  Exact match (int FV == next mid): {exact_match}/{len(y_actual)} ({100*exact_match/len(y_actual):.1f}%)")
    print(f"  Within 0.5 of next mid:           {within_half}/{len(y_actual)} ({100*within_half/len(y_actual):.1f}%)")
    print(f"  Direction accuracy (on moves):     {dir_correct if np.sum(moving)>0 else 0}/{dir_total} ({100*dir_accuracy:.1f}%)")
    print(f"  Mean |FV - next_mid|:              {np.mean(np.abs(y_hat - y_actual)):.4f}")
    print(f"  Mean |int(FV) - next_mid|:         {np.mean(np.abs(np.round(y_hat) - y_actual)):.4f}")


# ============================================================
# ADDITIONAL: Regression using MID[t] changes instead of levels
# ============================================================

print("\n" + "="*70)
print("BONUS: PREDICTIVE POWER OF MP DEVIATION FROM MID")
print("="*70)
print("Testing: mid[t+1] - mid[t] = a + b*(mp[t] - mid[t])")

for label in ["-2", "-1", "0"]:
    d = results[label]
    mid = d["mid"]

    print(f"\n--- Day {label} ---")
    for mp_name, mp_series in [("L1", d["l1_mp"]), ("L2", d["l2_mp"]), ("VWAP", d["vwap_mp"])]:
        mask = np.isfinite(mp_series) & np.isfinite(mid)
        # Ensure consecutive ticks
        valid_idx = np.where(mask)[0]
        # Only keep indices where i+1 is also valid
        pairs = [(i, i+1) for i in valid_idx if i+1 in set(valid_idx)]

        if len(pairs) < 10:
            print(f"  {mp_name}: insufficient data")
            continue

        x_vals = np.array([mp_series[i] - mid[i] for i, _ in pairs])
        y_vals = np.array([mid[j] - mid[i] for i, j in pairs])

        # Simple regression
        slope, intercept_lr, r_value, p_value, std_err = stats.linregress(x_vals, y_vals)

        print(f"  {mp_name}: slope={slope:.4f}, R²={r_value**2:.6f}, p={p_value:.2e}")


# ============================================================
# FINAL SUMMARY TABLE
# ============================================================

print("\n" + "="*70)
print("FINAL SUMMARY TABLE")
print("="*70)

print(f"\n{'Metric':<40} {'L1':>12} {'L2':>12} {'VWAP':>12}")
print("-" * 76)

for mp_name in ["L1", "L2", "VWAP"]:
    r = oos_results[mp_name]
    row_data = {
        "R² train (days -2,-1)": f"{r['r2_train']:.6f}",
        "R² test (day 0, OOS)": f"{r['r2_test']:.6f}",
        "R² day 0 (IS)": f"{r['r2_d0']:.6f}",
        "RMSE train": f"{r['rmse_train']:.6f}",
        "RMSE test (OOS)": f"{r['rmse_test']:.6f}",
        "RMSE day 0 (IS)": f"{r['rmse_d0']:.6f}",
        "Intercept (OOS)": f"{r['intercept']:.4f}",
        "Coef sum (OOS)": f"{np.sum(r['coefs']):.6f}",
    }

    if mp_name == "L1":
        for metric, val in row_data.items():
            print(f"  {metric:<38} {val:>12}", end="")
            # Will fill in other columns on their turns
            # Actually let's do it differently
        break

# Better formatting:
print()  # Clear partial output
metrics = [
    ("R² train (days -2,-1)", lambda r: f"{r['r2_train']:.6f}"),
    ("R² test (day 0, OOS)", lambda r: f"{r['r2_test']:.6f}"),
    ("R² day 0 (IS)", lambda r: f"{r['r2_d0']:.6f}"),
    ("R² drop (IS→OOS)", lambda r: f"{r['r2_d0'] - r['r2_test']:.6f}"),
    ("RMSE train", lambda r: f"{r['rmse_train']:.6f}"),
    ("RMSE test (OOS)", lambda r: f"{r['rmse_test']:.6f}"),
    ("Intercept (OOS)", lambda r: f"{r['intercept']:.4f}"),
    ("Coef sum (OOS)", lambda r: f"{np.sum(r['coefs']):.6f}"),
    ("c1 (lag-3)", lambda r: f"{r['coefs'][0]:.6f}"),
    ("c2 (lag-2)", lambda r: f"{r['coefs'][1]:.6f}"),
    ("c3 (lag-1)", lambda r: f"{r['coefs'][2]:.6f}"),
    ("c4 (lag-0)", lambda r: f"{r['coefs'][3]:.6f}"),
]

print(f"{'Metric':<30} {'L1':>14} {'L2':>14} {'VWAP':>14}")
print("-" * 72)

for metric_name, metric_fn in metrics:
    vals = [metric_fn(oos_results[mp]) for mp in ["L1", "L2", "VWAP"]]
    print(f"  {metric_name:<28} {vals[0]:>14} {vals[1]:>14} {vals[2]:>14}")

print("\n" + "="*70)
print("ANALYSIS COMPLETE")
print("="*70)
