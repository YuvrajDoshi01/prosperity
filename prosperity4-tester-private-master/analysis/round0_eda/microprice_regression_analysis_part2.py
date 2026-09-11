"""
Part 2: Deep diagnostics on the L2 microprice anomaly and PnL simulation.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

np.set_printoptions(precision=6, suppress=True)

BASE = Path("/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0")

def load_day(day_label):
    fname = f"prices_round_0_day_{day_label}.csv"
    df = pd.read_csv(BASE / fname, sep=";")
    tom = df[df["product"] == "TOMATOES"].copy()
    tom = tom.sort_values("timestamp").reset_index(drop=True)
    return tom

days = {"-2": load_day("-2"), "-1": load_day("-1"), "0": load_day("0")}

def compute_microprices(df):
    bp1 = df["bid_price_1"].values.astype(float)
    bv1 = df["bid_volume_1"].values.astype(float)
    bp2 = df["bid_price_2"].values.astype(float)
    bv2 = df["bid_volume_2"].values.astype(float)
    ap1 = df["ask_price_1"].values.astype(float)
    av1 = df["ask_volume_1"].values.astype(float)
    ap2 = df["ask_price_2"].values.astype(float)
    av2 = df["ask_volume_2"].values.astype(float)
    mid = df["mid_price"].values.astype(float)

    has_l2 = np.isfinite(bp2) & np.isfinite(bv2) & np.isfinite(ap2) & np.isfinite(av2)

    total_bid_vol = bv1.copy()
    total_ask_vol = av1.copy()
    total_bid_vol[has_l2] += bv2[has_l2]
    total_ask_vol[has_l2] += av2[has_l2]

    spread = ap1 - bp1
    l1_mp = bp1 + (total_bid_vol / (total_bid_vol + total_ask_vol)) * spread

    l2_mp = np.full_like(bp1, np.nan)
    l2_total = bv2 + av2
    mask = has_l2 & (l2_total > 0)
    l2_mp[mask] = (bp2[mask] * av2[mask] + ap2[mask] * bv2[mask]) / l2_total[mask]

    num = bp1 * bv1 + ap1 * av1
    den = bv1 + av1
    num[has_l2] += bp2[has_l2] * bv2[has_l2] + ap2[has_l2] * av2[has_l2]
    den[has_l2] += bv2[has_l2] + av2[has_l2]
    vwap_mp = num / den

    return l1_mp, l2_mp, vwap_mp, mid, has_l2, bp1, ap1, bv1, av1, bp2, ap2, bv2, av2

# ============================================================
# DIAGNOSE: Why does L2 change ANTI-correlate with mid change?
# ============================================================

print("="*70)
print("DIAGNOSING L2 MICROPRICE ANTI-CORRELATION WITH MID CHANGES")
print("="*70)

for label in ["-2", "0"]:
    df = days[label]
    l1_mp, l2_mp, vwap_mp, mid, has_l2, bp1, ap1, bv1, av1, bp2, ap2, bv2, av2 = compute_microprices(df)

    print(f"\n--- Day {label} ---")

    # When mid goes up, what happens to L2?
    dmid = np.diff(mid)
    dl2 = np.diff(l2_mp)
    dl1 = np.diff(l1_mp)

    # L2 spread: distance from L1 to L2
    l2_bid_gap = bp1 - bp2  # distance from best bid to L2 bid
    l2_ask_gap = ap2 - ap1  # distance from best ask to L2 ask

    print(f"  L2 bid gap (bp1-bp2): mean={np.nanmean(l2_bid_gap):.2f}, std={np.nanstd(l2_bid_gap):.2f}")
    print(f"  L2 ask gap (ap2-ap1): mean={np.nanmean(l2_ask_gap):.2f}, std={np.nanstd(l2_ask_gap):.2f}")
    print(f"  L1 spread (ap1-bp1):  mean={np.nanmean(ap1-bp1):.2f}")
    print(f"  L2 spread (ap2-bp2):  mean={np.nanmean(ap2-bp2):.2f}")

    # The L2 microprice is essentially a weighted average of bp2 and ap2
    # If bv2 > av2, L2_mp is closer to ap2 (higher)
    # This is standard microprice: more resting volume on bid → price likely to go UP

    # But L2 changes anti-correlate with mid changes. Why?
    # Hypothesis: When mid goes UP (ask side lifts), the OLD L2 ask price
    # becomes the new L1 price. The new L2 ask is further out.
    # Meanwhile L2 bid stays put. Net effect: L2 mid shifts DOWN.

    # Check: when mid goes UP by 0.5, what happens to L2 prices?
    up_ticks = np.where(dmid > 0)[0]
    down_ticks = np.where(dmid < 0)[0]
    flat_ticks = np.where(dmid == 0)[0]

    print(f"\n  Up ticks: {len(up_ticks)}, Down ticks: {len(down_ticks)}, Flat: {len(flat_ticks)}")

    if len(up_ticks) > 0:
        dbp2_up = np.diff(bp2)[up_ticks]
        dap2_up = np.diff(ap2)[up_ticks]
        dbv2_up = np.diff(bv2)[up_ticks]
        dav2_up = np.diff(av2)[up_ticks]
        dl2_up = dl2[up_ticks]

        print(f"\n  When mid goes UP:")
        print(f"    d(bp2): mean={np.mean(dbp2_up):.3f}, d(ap2): mean={np.mean(dap2_up):.3f}")
        print(f"    d(bv2): mean={np.mean(dbv2_up):.3f}, d(av2): mean={np.mean(dav2_up):.3f}")
        print(f"    d(L2_mp): mean={np.mean(dl2_up):.3f}")
        print(f"    d(L1_mp): mean={np.mean(dl1[up_ticks]):.3f}")

    if len(down_ticks) > 0:
        dbp2_dn = np.diff(bp2)[down_ticks]
        dap2_dn = np.diff(ap2)[down_ticks]
        dl2_dn = dl2[down_ticks]

        print(f"\n  When mid goes DOWN:")
        print(f"    d(bp2): mean={np.mean(dbp2_dn):.3f}, d(ap2): mean={np.mean(dap2_dn):.3f}")
        print(f"    d(L2_mp): mean={np.mean(dl2_dn):.3f}")
        print(f"    d(L1_mp): mean={np.mean(dl1[down_ticks]):.3f}")


# ============================================================
# The real question: does L2 add MARGINAL information beyond L1?
# ============================================================

print("\n" + "="*70)
print("MARGINAL VALUE OF L2 OVER L1: COMBINED REGRESSION")
print("="*70)
print("mid[t+1] = a + c1*L1[t-3] + c2*L1[t-2] + c3*L1[t-1] + c4*L1[t]")
print("                + d1*L2[t-3] + d2*L2[t-2] + d3*L2[t-1] + d4*L2[t]")

for label in ["-2", "-1", "0"]:
    df = days[label]
    l1_mp, l2_mp, vwap_mp, mid, *_ = compute_microprices(df)

    n = len(l1_mp)
    valid = np.isfinite(l1_mp) & np.isfinite(l2_mp) & np.isfinite(mid)

    rows_x = []
    y_vals = []
    for t in range(3, n - 1):
        if all(valid[t-j] for j in range(4)) and valid[t+1]:
            row = [l1_mp[t-3], l1_mp[t-2], l1_mp[t-1], l1_mp[t],
                   l2_mp[t-3], l2_mp[t-2], l2_mp[t-1], l2_mp[t]]
            rows_x.append(row)
            y_vals.append(mid[t+1])

    X = np.array(rows_x)
    y = np.array(y_vals)

    # L1-only
    X_l1 = X[:, :4]
    X_aug_l1 = np.column_stack([np.ones(len(y)), X_l1])
    beta_l1 = np.linalg.lstsq(X_aug_l1, y, rcond=None)[0]
    ss_res_l1 = np.sum((y - X_aug_l1 @ beta_l1)**2)
    ss_tot = np.sum((y - np.mean(y))**2)
    r2_l1 = 1 - ss_res_l1 / ss_tot

    # L1 + L2 combined
    X_aug_both = np.column_stack([np.ones(len(y)), X])
    beta_both = np.linalg.lstsq(X_aug_both, y, rcond=None)[0]
    ss_res_both = np.sum((y - X_aug_both @ beta_both)**2)
    r2_both = 1 - ss_res_both / ss_tot

    # L2-only
    X_l2 = X[:, 4:]
    X_aug_l2 = np.column_stack([np.ones(len(y)), X_l2])
    beta_l2 = np.linalg.lstsq(X_aug_l2, y, rcond=None)[0]
    ss_res_l2 = np.sum((y - X_aug_l2 @ beta_l2)**2)
    r2_l2 = 1 - ss_res_l2 / ss_tot

    # F-test for marginal L2 contribution
    k_restricted = 5  # intercept + 4 L1 coefs
    k_full = 9        # intercept + 4 L1 + 4 L2 coefs
    n_obs = len(y)
    f_stat = ((ss_res_l1 - ss_res_both) / (k_full - k_restricted)) / (ss_res_both / (n_obs - k_full))
    from scipy.stats import f as f_dist
    p_val = 1 - f_dist.cdf(f_stat, k_full - k_restricted, n_obs - k_full)

    print(f"\nDay {label} (n={len(y)}):")
    print(f"  L1 only:    R² = {r2_l1:.8f}")
    print(f"  L2 only:    R² = {r2_l2:.8f}")
    print(f"  L1 + L2:    R² = {r2_both:.8f}")
    print(f"  Marginal R² from L2: {r2_both - r2_l1:.8f}")
    print(f"  F-statistic: {f_stat:.2f}, p-value: {p_val:.2e}")
    print(f"  Combined coefs:")
    print(f"    L1: [{', '.join(f'{c:.6f}' for c in beta_both[1:5])}]")
    print(f"    L2: [{', '.join(f'{c:.6f}' for c in beta_both[5:9])}]")
    print(f"    Intercept: {beta_both[0]:.4f}")


# ============================================================
# OOS COMBINED: Train -2/-1, test day 0
# ============================================================

print("\n" + "="*70)
print("OOS COMBINED MODEL: Train days -2,-1, test day 0")
print("="*70)

# Build training data
X_trains, y_trains = [], []
for train_label in ["-2", "-1"]:
    df = days[train_label]
    l1_mp, l2_mp, vwap_mp, mid, *_ = compute_microprices(df)
    n = len(l1_mp)
    valid = np.isfinite(l1_mp) & np.isfinite(l2_mp) & np.isfinite(mid)

    for t in range(3, n - 1):
        if all(valid[t-j] for j in range(4)) and valid[t+1]:
            X_trains.append([l1_mp[t-3], l1_mp[t-2], l1_mp[t-1], l1_mp[t],
                             l2_mp[t-3], l2_mp[t-2], l2_mp[t-1], l2_mp[t]])
            y_trains.append(mid[t+1])

X_train = np.array(X_trains)
y_train = np.array(y_trains)

# Test data
df0 = days["0"]
l1_0, l2_0, vwap_0, mid_0, *_ = compute_microprices(df0)
n = len(l1_0)
valid0 = np.isfinite(l1_0) & np.isfinite(l2_0) & np.isfinite(mid_0)

X_test_list, y_test_list = [], []
for t in range(3, n - 1):
    if all(valid0[t-j] for j in range(4)) and valid0[t+1]:
        X_test_list.append([l1_0[t-3], l1_0[t-2], l1_0[t-1], l1_0[t],
                            l2_0[t-3], l2_0[t-2], l2_0[t-1], l2_0[t]])
        y_test_list.append(mid_0[t+1])

X_test = np.array(X_test_list)
y_test = np.array(y_test_list)

# Fit L1-only on training
X_aug_l1_train = np.column_stack([np.ones(len(y_train)), X_train[:, :4]])
beta_l1 = np.linalg.lstsq(X_aug_l1_train, y_train, rcond=None)[0]

# Fit L1+L2 on training
X_aug_both_train = np.column_stack([np.ones(len(y_train)), X_train])
beta_both = np.linalg.lstsq(X_aug_both_train, y_train, rcond=None)[0]

# Fit L2-only on training
X_aug_l2_train = np.column_stack([np.ones(len(y_train)), X_train[:, 4:]])
beta_l2 = np.linalg.lstsq(X_aug_l2_train, y_train, rcond=None)[0]

# Predict on test
y_hat_l1 = np.column_stack([np.ones(len(y_test)), X_test[:, :4]]) @ beta_l1
y_hat_both = np.column_stack([np.ones(len(y_test)), X_test]) @ beta_both
y_hat_l2 = np.column_stack([np.ones(len(y_test)), X_test[:, 4:]]) @ beta_l2

ss_tot_test = np.sum((y_test - np.mean(y_test))**2)
r2_l1_oos = 1 - np.sum((y_test - y_hat_l1)**2) / ss_tot_test
r2_both_oos = 1 - np.sum((y_test - y_hat_both)**2) / ss_tot_test
r2_l2_oos = 1 - np.sum((y_test - y_hat_l2)**2) / ss_tot_test

rmse_l1_oos = np.sqrt(np.mean((y_test - y_hat_l1)**2))
rmse_both_oos = np.sqrt(np.mean((y_test - y_hat_both)**2))
rmse_l2_oos = np.sqrt(np.mean((y_test - y_hat_l2)**2))

print(f"\nOOS (day 0) results:")
print(f"  L1 only:    R² = {r2_l1_oos:.8f}, RMSE = {rmse_l1_oos:.6f}")
print(f"  L2 only:    R² = {r2_l2_oos:.8f}, RMSE = {rmse_l2_oos:.6f}")
print(f"  L1 + L2:    R² = {r2_both_oos:.8f}, RMSE = {rmse_both_oos:.6f}")
print(f"  Marginal R² from L2 (OOS): {r2_both_oos - r2_l1_oos:.8f}")

# Integer FV comparison for combined model
fv_l1 = np.round(y_hat_l1)
fv_both = np.round(y_hat_both)
fv_l2 = np.round(y_hat_l2)

diff_combined = fv_l1 != fv_both
n_diff = np.sum(diff_combined)
print(f"\n  Ticks where integer FV differs (L1 vs L1+L2): {n_diff}/{len(y_test)} ({100*n_diff/len(y_test):.1f}%)")

if n_diff > 0:
    err_l1 = np.abs(y_hat_l1[diff_combined] - y_test[diff_combined])
    err_both = np.abs(y_hat_both[diff_combined] - y_test[diff_combined])
    l1_wins = np.sum(err_l1 < err_both)
    both_wins = np.sum(err_both < err_l1)

    int_err_l1 = np.abs(fv_l1[diff_combined] - y_test[diff_combined])
    int_err_both = np.abs(fv_both[diff_combined] - y_test[diff_combined])
    int_l1_wins = np.sum(int_err_l1 < int_err_both)
    int_both_wins = np.sum(int_err_both < int_err_l1)
    int_ties = np.sum(int_err_l1 == int_err_both)

    print(f"  On disagreement ticks:")
    print(f"    Raw: L1 wins={l1_wins}, L1+L2 wins={both_wins}")
    print(f"    Int: L1 wins={int_l1_wins}, L1+L2 wins={int_both_wins}, ties={int_ties}")

print(f"\n  Combined model coefs (train -2,-1):")
print(f"    L1: [{', '.join(f'{c:.6f}' for c in beta_both[1:5])}]")
print(f"    L2: [{', '.join(f'{c:.6f}' for c in beta_both[5:9])}]")
print(f"    Intercept: {beta_both[0]:.4f}")


# ============================================================
# STRUCTURAL EXPLANATION: L2 vs L1 spread gap analysis
# ============================================================

print("\n" + "="*70)
print("L2 STRUCTURAL ANALYSIS: WHY L2 ANTI-CORRELATES")
print("="*70)

for label in ["0"]:
    df = days[label]
    l1_mp, l2_mp, vwap_mp, mid, has_l2, bp1, ap1, bv1, av1, bp2, ap2, bv2, av2 = compute_microprices(df)

    # L2 microprice is a weighted average of bp2 and ap2
    # Standard microprice: mp = bp * av / (bv+av) + ap * bv / (bv+av)
    # When bv2 > av2: L2_mp is pulled toward ap2 (higher)
    # This is the OPPOSITE of what L1 imbalance predicts

    # Check: L1 imbalance vs L2 imbalance correlation
    l1_imb = (bv1 + bv2) / (bv1 + bv2 + av1 + av2)  # Total imbalance
    l2_imb = bv2 / (bv2 + av2)  # L2-only imbalance

    print(f"\nDay {label}:")
    print(f"  corr(L1 total imbalance, L2 imbalance): {np.corrcoef(l1_imb[has_l2], l2_imb[has_l2])[0,1]:.4f}")

    # The key: L2 bid/ask are FURTHER from mid, so L2 microprice has different range
    l2_spread = ap2 - bp2
    l1_spread = ap1 - bp1
    print(f"  L1 spread mean: {np.mean(l1_spread):.2f}, L2 spread mean: {np.mean(l2_spread):.2f}")
    print(f"  L2/L1 spread ratio: {np.mean(l2_spread)/np.mean(l1_spread):.2f}")

    # The anti-correlation: when mid moves UP, L2 prices often lag or move asymmetrically
    # because the MM bot updates L1 and L2 with potentially different patterns
    dmid = np.diff(mid)
    dl2 = np.diff(l2_mp)
    dl1 = np.diff(l1_mp)

    # Decompose L2 change into price change vs volume rebalance
    # L2_mp = bp2 * av2/(bv2+av2) + ap2 * bv2/(bv2+av2)
    # = (bp2 * av2 + ap2 * bv2) / (bv2 + av2)

    # Let's just check the correlation spectrum
    for lag in range(1, 6):
        if lag < len(dl2):
            corr_l2_mid = np.corrcoef(dl2[:-lag] if lag > 0 else dl2, dmid[lag:])[0,1] if lag > 0 else 0
            corr_l1_mid = np.corrcoef(dl1[:-lag] if lag > 0 else dl1, dmid[lag:])[0,1] if lag > 0 else 0
            print(f"  corr(dL2[t], dMid[t+{lag}]) = {corr_l2_mid:.4f},  corr(dL1[t], dMid[t+{lag}]) = {corr_l1_mid:.4f}")


# ============================================================
# SIMULATED PnL: How many more/fewer profitable FV decisions?
# ============================================================

print("\n" + "="*70)
print("SIMULATED PNL IMPACT: INTEGER FV DECISIONS")
print("="*70)

# For each model, compute integer FV on day 0 using OOS coefs
# Then count ticks where FV is above/below mid and what the actual outcome was

df0 = days["0"]
l1_mp, l2_mp, vwap_mp, mid, *_ = compute_microprices(df0)
n = len(l1_mp)
valid = np.isfinite(l1_mp) & np.isfinite(l2_mp) & np.isfinite(mid)

# Rebuild with aligned mid[t]
def build_aligned_data(mp_series, mid_series, valid_mask):
    rows = []
    mid_t_vals = []
    mid_t1_vals = []
    for t in range(3, len(mp_series) - 1):
        if all(valid_mask[t-j] for j in range(4)) and valid_mask[t+1]:
            rows.append([mp_series[t-3], mp_series[t-2], mp_series[t-1], mp_series[t]])
            mid_t_vals.append(mid_series[t])
            mid_t1_vals.append(mid_series[t+1])
    return np.array(rows), np.array(mid_t_vals), np.array(mid_t1_vals)

# Get OOS coefficients (train on -2,-1)
def get_oos_coefs(mp_key):
    X_trains, y_trains = [], []
    for train_label in ["-2", "-1"]:
        df = days[train_label]
        mp_all = compute_microprices(df)
        mp_idx = {"l1_mp": 0, "l2_mp": 1, "vwap_mp": 2}[mp_key]
        mp_s = mp_all[mp_idx]
        mid_s = mp_all[3]
        v = np.isfinite(mp_s) & np.isfinite(mid_s)

        for t in range(3, len(mp_s) - 1):
            if all(v[t-j] for j in range(4)) and v[t+1]:
                X_trains.append([mp_s[t-3], mp_s[t-2], mp_s[t-1], mp_s[t]])
                y_trains.append(mid_s[t+1])

    X = np.array(X_trains)
    y = np.array(y_trains)
    X_aug = np.column_stack([np.ones(len(y)), X])
    beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
    return beta[0], beta[1:]

for mp_name, mp_key, mp_series in [("L1", "l1_mp", l1_mp), ("L2", "l2_mp", l2_mp), ("VWAP", "vwap_mp", vwap_mp)]:
    intercept, coefs = get_oos_coefs(mp_key)

    X_test, mid_t, mid_t1 = build_aligned_data(mp_series, mid, valid)
    fv = np.column_stack([np.ones(len(X_test)), X_test]) @ np.concatenate([[intercept], coefs])
    fv_int = np.round(fv)

    # FV > mid[t] → predict UP → benefit from buying
    # FV < mid[t] → predict DOWN → benefit from selling
    # FV == mid[t] → neutral

    pred_up = fv_int > mid_t
    pred_down = fv_int < mid_t
    pred_flat = fv_int == mid_t

    actual_up = mid_t1 > mid_t
    actual_down = mid_t1 < mid_t
    actual_flat = mid_t1 == mid_t

    # Correct directional predictions (from integer FV)
    correct_up = np.sum(pred_up & actual_up)
    correct_down = np.sum(pred_down & actual_down)
    wrong_up = np.sum(pred_up & actual_down)
    wrong_down = np.sum(pred_down & actual_up)

    total_signals = np.sum(pred_up | pred_down)
    correct_signals = correct_up + correct_down
    wrong_signals = wrong_up + wrong_down

    print(f"\n{mp_name} Microprice (OOS coefs, day 0):")
    print(f"  Integer FV signals: {total_signals}/{len(fv)} active ({100*total_signals/len(fv):.1f}%)")
    print(f"    Predict UP:   {np.sum(pred_up)} (correct: {correct_up}, wrong: {wrong_up})")
    print(f"    Predict DOWN: {np.sum(pred_down)} (correct: {correct_down}, wrong: {wrong_down})")
    print(f"    Neutral:      {np.sum(pred_flat)}")
    print(f"  Directional accuracy (on signals): {correct_signals}/{total_signals} ({100*correct_signals/total_signals:.1f}%)" if total_signals > 0 else "  No signals")

    # PnL proxy: +1 for correct direction, -1 for wrong direction (per tick, not per lot)
    pnl_proxy = correct_up - wrong_up + correct_down - wrong_down
    print(f"  Directional PnL proxy: +{correct_signals} - {wrong_signals} = {pnl_proxy}")


# ============================================================
# TICK-LEVEL GRANULARITY: L1 vs L2 FV on CRITICAL ticks only
# ============================================================

print("\n" + "="*70)
print("CRITICAL TICK ANALYSIS: L1 vs L2 on high-signal ticks")
print("="*70)

# Focus on ticks where L1 and L2 integer FVs disagree AND the actual mid moved
intercept_l1, coefs_l1 = get_oos_coefs("l1_mp")
intercept_l2, coefs_l2 = get_oos_coefs("l2_mp")

X_l1, mid_t, mid_t1 = build_aligned_data(l1_mp, mid, valid)
X_l2, _, _ = build_aligned_data(l2_mp, mid, valid)

fv_l1 = np.column_stack([np.ones(len(X_l1)), X_l1]) @ np.concatenate([[intercept_l1], coefs_l1])
fv_l2 = np.column_stack([np.ones(len(X_l2)), X_l2]) @ np.concatenate([[intercept_l2], coefs_l2])

fv_l1_int = np.round(fv_l1)
fv_l2_int = np.round(fv_l2)

disagree = fv_l1_int != fv_l2_int
moved = mid_t1 != mid_t
critical = disagree & moved

n_critical = np.sum(critical)
print(f"\nCritical ticks (disagree AND mid moved): {n_critical}/{len(fv_l1)} ({100*n_critical/len(fv_l1):.1f}%)")

if n_critical > 0:
    err_l1_c = np.abs(fv_l1_int[critical] - mid_t1[critical])
    err_l2_c = np.abs(fv_l2_int[critical] - mid_t1[critical])

    l1_closer = np.sum(err_l1_c < err_l2_c)
    l2_closer = np.sum(err_l2_c < err_l1_c)
    ties = np.sum(err_l1_c == err_l2_c)

    print(f"  L1 closer to actual: {l1_closer} ({100*l1_closer/n_critical:.1f}%)")
    print(f"  L2 closer to actual: {l2_closer} ({100*l2_closer/n_critical:.1f}%)")
    print(f"  Ties: {ties} ({100*ties/n_critical:.1f}%)")
    print(f"  Mean |error|: L1={np.mean(err_l1_c):.4f}, L2={np.mean(err_l2_c):.4f}")

    # Direction accuracy on critical ticks
    actual_dir = np.sign(mid_t1[critical] - mid_t[critical])
    l1_dir = np.sign(fv_l1_int[critical] - mid_t[critical])
    l2_dir = np.sign(fv_l2_int[critical] - mid_t[critical])

    l1_dir_correct = np.sum(l1_dir == actual_dir)
    l2_dir_correct = np.sum(l2_dir == actual_dir)

    print(f"  Direction accuracy: L1={l1_dir_correct}/{n_critical} ({100*l1_dir_correct/n_critical:.1f}%), L2={l2_dir_correct}/{n_critical} ({100*l2_dir_correct/n_critical:.1f}%)")


print("\n" + "="*70)
print("ANALYSIS COMPLETE")
print("="*70)
