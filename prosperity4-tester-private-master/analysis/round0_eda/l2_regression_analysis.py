"""
L2 microprice regression analysis for TOMATOES.
Fits 4-lag L2-only and 8-lag combined (L1+L2) models.
"""

import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

# ── Load data ──────────────────────────────────────────────────────────────
base = "prosperity4bt/resources/round0"
files = {
    -2: f"{base}/prices_round_0_day_-2.csv",
    -1: f"{base}/prices_round_0_day_-1.csv",
     0: f"{base}/prices_round_0_day_0.csv",
}

dfs = {}
for day, path in files.items():
    df = pd.read_csv(path, sep=";")
    df = df[df["product"] == "TOMATOES"].copy()
    df = df.sort_values("timestamp").reset_index(drop=True)
    dfs[day] = df

print("Row counts per day:")
for day, df in dfs.items():
    print(f"  Day {day:>2}: {len(df)} rows, timestamps {df['timestamp'].min()}-{df['timestamp'].max()}")

# ── Compute features ──────────────────────────────────────────────────────
def compute_features(df):
    """Compute mid, L1 microprice, L2 microprice for each tick."""
    best_bid = df["bid_price_1"].values.astype(float)
    best_ask = df["ask_price_1"].values.astype(float)
    bid_vol_1 = df["bid_volume_1"].values.astype(float)
    ask_vol_1 = np.abs(df["ask_volume_1"].values.astype(float))
    bid_vol_2 = df["bid_volume_2"].values.astype(float)
    ask_vol_2 = np.abs(df["ask_volume_2"].values.astype(float))

    # Check for L3
    has_l3 = "bid_price_3" in df.columns and df["bid_price_3"].notna().any()

    # Total bid/ask volumes (all levels)
    total_bid = bid_vol_1 + bid_vol_2
    total_ask = ask_vol_1 + ask_vol_2
    if has_l3:
        bid_vol_3 = df["bid_volume_3"].values.astype(float)
        ask_vol_3 = np.abs(df["ask_volume_3"].values.astype(float))
        # Only add where not NaN
        bid_vol_3 = np.nan_to_num(bid_vol_3, nan=0.0)
        ask_vol_3 = np.nan_to_num(ask_vol_3, nan=0.0)
        total_bid += bid_vol_3
        total_ask += ask_vol_3

    mid = (best_bid + best_ask) / 2.0

    # L1 microprice: bid + (total_bid_vol / (total_bid + total_ask)) * spread
    spread = best_ask - best_bid
    l1_mp = best_bid + (total_bid / (total_bid + total_ask)) * spread

    # L2 microprice: l2_bid * l2_ask_vol / (l2_bid_vol + l2_ask_vol) + l2_ask * l2_bid_vol / (l2_bid_vol + l2_ask_vol)
    l2_bid_price = df["bid_price_2"].values.astype(float)
    l2_ask_price = df["ask_price_2"].values.astype(float)
    l2_total = bid_vol_2 + ask_vol_2
    l2_mp = l2_bid_price * (ask_vol_2 / l2_total) + l2_ask_price * (bid_vol_2 / l2_total)

    return mid, l1_mp, l2_mp


for day in dfs:
    mid, l1_mp, l2_mp = compute_features(dfs[day])
    dfs[day]["mid"] = mid
    dfs[day]["l1_mp"] = l1_mp
    dfs[day]["l2_mp"] = l2_mp

# Sanity check
for day in [-2, -1, 0]:
    df = dfs[day]
    print(f"\nDay {day} sanity check (first 5 rows):")
    print(f"  mid:   {df['mid'].values[:5]}")
    print(f"  l1_mp: {df['l1_mp'].values[:5]}")
    print(f"  l2_mp: {df['l2_mp'].values[:5]}")
    print(f"  l1_mp mean: {df['l1_mp'].mean():.4f}, l2_mp mean: {df['l2_mp'].mean():.4f}")
    print(f"  l1_mp - mid mean: {(df['l1_mp'] - df['mid']).mean():.6f}")
    print(f"  l2_mp - mid mean: {(df['l2_mp'] - df['mid']).mean():.6f}")

# ── Build regression datasets ─────────────────────────────────────────────
def build_lag_dataset(df, n_lags=4):
    """
    Build X (lagged features) and y (mid[t+1]) arrays.
    Returns X_l1, X_l2, y where:
      X_l1 columns = [l1_mp[t-3], l1_mp[t-2], l1_mp[t-1], l1_mp[t]]  (for 4 lags)
      X_l2 columns = [l2_mp[t-3], l2_mp[t-2], l2_mp[t-1], l2_mp[t]]
      y = mid[t+1]
    """
    mid = df["mid"].values
    l1_mp = df["l1_mp"].values
    l2_mp = df["l2_mp"].values
    n = len(mid)

    # Need n_lags previous values + 1 future value
    # For lag indices: t - (n_lags-1) ... t, and target t+1
    # So valid range: t from (n_lags-1) to (n-2)
    start = n_lags - 1
    end = n - 1  # exclusive: we need mid[t+1] so t goes up to n-2

    rows = end - start
    X_l1 = np.zeros((rows, n_lags))
    X_l2 = np.zeros((rows, n_lags))
    y = np.zeros(rows)

    for i, t in enumerate(range(start, end)):
        for lag in range(n_lags):
            # lag 0 = oldest (t - (n_lags-1)), lag n_lags-1 = newest (t)
            idx = t - (n_lags - 1 - lag)
            X_l1[i, lag] = l1_mp[idx]
            X_l2[i, lag] = l2_mp[idx]
        y[i] = mid[t + 1]

    return X_l1, X_l2, y


# Build datasets per day
datasets = {}
for day in [-2, -1, 0]:
    X_l1, X_l2, y = build_lag_dataset(dfs[day], n_lags=4)
    datasets[day] = (X_l1, X_l2, y)
    print(f"\nDay {day}: {len(y)} samples (after lag construction)")

# ── Training datasets ─────────────────────────────────────────────────────
# Pooled: days -2 and -1 combined
X_l1_train = np.vstack([datasets[-2][0], datasets[-1][0]])
X_l2_train = np.vstack([datasets[-2][1], datasets[-1][1]])
y_train = np.concatenate([datasets[-2][2], datasets[-1][2]])

# OOS: day 0
X_l1_oos = datasets[0][0]
X_l2_oos = datasets[0][1]
y_oos = datasets[0][2]

print(f"\nTraining samples (pooled): {len(y_train)}")
print(f"OOS samples (day 0):      {len(y_oos)}")


# ── Helper ─────────────────────────────────────────────────────────────────
def r_squared(y_true, y_pred):
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return 1 - ss_res / ss_tot


# ══════════════════════════════════════════════════════════════════════════
# MODEL 1: L2-only 4-lag regression
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("MODEL 1: L2-only 4-lag regression")
print("  mid[t+1] = intercept + c1*l2mp[t-3] + c2*l2mp[t-2] + c3*l2mp[t-1] + c4*l2mp[t]")
print("=" * 80)

# ── Pooled training ──
reg1_pooled = LinearRegression()
reg1_pooled.fit(X_l2_train, y_train)
y_pred_train = reg1_pooled.predict(X_l2_train)
y_pred_oos = reg1_pooled.predict(X_l2_oos)
r2_train = r_squared(y_train, y_pred_train)
r2_oos = r_squared(y_oos, y_pred_oos)

print(f"\n[POOLED] Trained on days -2,-1 combined:")
print(f"  intercept = {reg1_pooled.intercept_:.6f}")
for i, c in enumerate(reg1_pooled.coef_):
    print(f"  c{i+1} (lag {3-i}) = {c:.6f}")
print(f"  coef sum = {sum(reg1_pooled.coef_):.6f}")
print(f"  R² in-sample  = {r2_train:.6f}")
print(f"  R² OOS (day 0) = {r2_oos:.6f}")

# ── Per-day fits for averaging ──
reg1_day2 = LinearRegression()
reg1_day2.fit(datasets[-2][1], datasets[-2][2])
reg1_day1 = LinearRegression()
reg1_day1.fit(datasets[-1][1], datasets[-1][2])

print(f"\n[DAY -2 only]:")
print(f"  intercept = {reg1_day2.intercept_:.6f}")
for i, c in enumerate(reg1_day2.coef_):
    print(f"  c{i+1} = {c:.6f}")
r2_d2 = r_squared(datasets[-2][2], reg1_day2.predict(datasets[-2][1]))
print(f"  R² in-sample = {r2_d2:.6f}")

print(f"\n[DAY -1 only]:")
print(f"  intercept = {reg1_day1.intercept_:.6f}")
for i, c in enumerate(reg1_day1.coef_):
    print(f"  c{i+1} = {c:.6f}")
r2_d1 = r_squared(datasets[-1][2], reg1_day1.predict(datasets[-1][1]))
print(f"  R² in-sample = {r2_d1:.6f}")

# Averaged coefficients
avg_intercept_1 = (reg1_day2.intercept_ + reg1_day1.intercept_) / 2
avg_coefs_1 = (reg1_day2.coef_ + reg1_day1.coef_) / 2

print(f"\n[AVERAGED] (day -2 + day -1) / 2:")
print(f"  intercept = {avg_intercept_1:.6f}")
for i, c in enumerate(avg_coefs_1):
    print(f"  c{i+1} = {c:.6f}")
print(f"  coef sum = {sum(avg_coefs_1):.6f}")

# Evaluate averaged on OOS
y_pred_avg_oos = X_l2_oos @ avg_coefs_1 + avg_intercept_1
r2_avg_oos = r_squared(y_oos, y_pred_avg_oos)
# Evaluate averaged on combined training
y_pred_avg_train = X_l2_train @ avg_coefs_1 + avg_intercept_1
r2_avg_train = r_squared(y_train, y_pred_avg_train)
print(f"  R² on training (applied to pooled) = {r2_avg_train:.6f}")
print(f"  R² OOS (day 0) = {r2_avg_oos:.6f}")


# ══════════════════════════════════════════════════════════════════════════
# MODEL 2: Combined 8-lag regression (4 L1 + 4 L2)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("MODEL 2: Combined 8-lag (4 L1 + 4 L2) regression")
print("  mid[t+1] = intercept + a1*l1mp[t-3] + ... + a4*l1mp[t] + b1*l2mp[t-3] + ... + b4*l2mp[t]")
print("=" * 80)

# Combined features: [L1 lags, L2 lags]
X_comb_train = np.hstack([X_l1_train, X_l2_train])
X_comb_oos = np.hstack([X_l1_oos, X_l2_oos])

# ── Pooled training ──
reg2_pooled = LinearRegression()
reg2_pooled.fit(X_comb_train, y_train)
y_pred_train2 = reg2_pooled.predict(X_comb_train)
y_pred_oos2 = reg2_pooled.predict(X_comb_oos)
r2_train2 = r_squared(y_train, y_pred_train2)
r2_oos2 = r_squared(y_oos, y_pred_oos2)

print(f"\n[POOLED] Trained on days -2,-1 combined:")
print(f"  intercept = {reg2_pooled.intercept_:.6f}")
coefs2 = reg2_pooled.coef_
for i in range(4):
    print(f"  a{i+1} (L1 lag {3-i}) = {coefs2[i]:.6f}")
for i in range(4):
    print(f"  b{i+1} (L2 lag {3-i}) = {coefs2[4+i]:.6f}")
print(f"  L1 coef sum = {sum(coefs2[:4]):.6f}")
print(f"  L2 coef sum = {sum(coefs2[4:]):.6f}")
print(f"  total coef sum = {sum(coefs2):.6f}")
print(f"  R² in-sample  = {r2_train2:.6f}")
print(f"  R² OOS (day 0) = {r2_oos2:.6f}")

# ── Per-day fits for averaging ──
X_comb_d2 = np.hstack([datasets[-2][0], datasets[-2][1]])
X_comb_d1 = np.hstack([datasets[-1][0], datasets[-1][1]])

reg2_day2 = LinearRegression()
reg2_day2.fit(X_comb_d2, datasets[-2][2])
reg2_day1 = LinearRegression()
reg2_day1.fit(X_comb_d1, datasets[-1][2])

print(f"\n[DAY -2 only]:")
print(f"  intercept = {reg2_day2.intercept_:.6f}")
c2d2 = reg2_day2.coef_
for i in range(4):
    print(f"  a{i+1} = {c2d2[i]:.6f}")
for i in range(4):
    print(f"  b{i+1} = {c2d2[4+i]:.6f}")
r2_2d2 = r_squared(datasets[-2][2], reg2_day2.predict(X_comb_d2))
print(f"  R² in-sample = {r2_2d2:.6f}")

print(f"\n[DAY -1 only]:")
print(f"  intercept = {reg2_day1.intercept_:.6f}")
c2d1 = reg2_day1.coef_
for i in range(4):
    print(f"  a{i+1} = {c2d1[i]:.6f}")
for i in range(4):
    print(f"  b{i+1} = {c2d1[4+i]:.6f}")
r2_2d1 = r_squared(datasets[-1][2], reg2_day1.predict(X_comb_d1))
print(f"  R² in-sample = {r2_2d1:.6f}")

# Averaged coefficients
avg_intercept_2 = (reg2_day2.intercept_ + reg2_day1.intercept_) / 2
avg_coefs_2 = (reg2_day2.coef_ + reg2_day1.coef_) / 2

print(f"\n[AVERAGED] (day -2 + day -1) / 2:")
print(f"  intercept = {avg_intercept_2:.6f}")
for i in range(4):
    print(f"  a{i+1} (L1 lag {3-i}) = {avg_coefs_2[i]:.6f}")
for i in range(4):
    print(f"  b{i+1} (L2 lag {3-i}) = {avg_coefs_2[4+i]:.6f}")
print(f"  L1 coef sum = {sum(avg_coefs_2[:4]):.6f}")
print(f"  L2 coef sum = {sum(avg_coefs_2[4:]):.6f}")
print(f"  total coef sum = {sum(avg_coefs_2):.6f}")

# Evaluate averaged on OOS
y_pred_avg_oos2 = X_comb_oos @ avg_coefs_2 + avg_intercept_2
r2_avg_oos2 = r_squared(y_oos, y_pred_avg_oos2)
y_pred_avg_train2 = X_comb_train @ avg_coefs_2 + avg_intercept_2
r2_avg_train2 = r_squared(y_train, y_pred_avg_train2)
print(f"  R² on training (applied to pooled) = {r2_avg_train2:.6f}")
print(f"  R² OOS (day 0) = {r2_avg_oos2:.6f}")


# ══════════════════════════════════════════════════════════════════════════
# COMPARISON WITH EXISTING L1-ONLY MODEL
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("COMPARISON: L1-only 4-lag (existing baseline)")
print("  mid[t+1] = intercept + c1*l1mp[t-3] + c2*l1mp[t-2] + c3*l1mp[t-1] + c4*l1mp[t]")
print("=" * 80)

reg_l1 = LinearRegression()
reg_l1.fit(X_l1_train, y_train)
y_pred_l1_train = reg_l1.predict(X_l1_train)
y_pred_l1_oos = reg_l1.predict(X_l1_oos)
r2_l1_train = r_squared(y_train, y_pred_l1_train)
r2_l1_oos = r_squared(y_oos, y_pred_l1_oos)

print(f"\n[POOLED] L1-only:")
print(f"  intercept = {reg_l1.intercept_:.6f}")
for i, c in enumerate(reg_l1.coef_):
    print(f"  c{i+1} = {c:.6f}")
print(f"  coef sum = {sum(reg_l1.coef_):.6f}")
print(f"  R² in-sample  = {r2_l1_train:.6f}")
print(f"  R² OOS (day 0) = {r2_l1_oos:.6f}")

# ── Per-day L1 for averaged ──
reg_l1_d2 = LinearRegression()
reg_l1_d2.fit(datasets[-2][0], datasets[-2][2])
reg_l1_d1 = LinearRegression()
reg_l1_d1.fit(datasets[-1][0], datasets[-1][2])

avg_intercept_l1 = (reg_l1_d2.intercept_ + reg_l1_d1.intercept_) / 2
avg_coefs_l1 = (reg_l1_d2.coef_ + reg_l1_d1.coef_) / 2

print(f"\n[AVERAGED] L1-only:")
print(f"  intercept = {avg_intercept_l1:.6f}")
for i, c in enumerate(avg_coefs_l1):
    print(f"  c{i+1} = {c:.6f}")
print(f"  coef sum = {sum(avg_coefs_l1):.6f}")
y_pred_avgl1_oos = X_l1_oos @ avg_coefs_l1 + avg_intercept_l1
r2_avgl1_oos = r_squared(y_oos, y_pred_avgl1_oos)
print(f"  R² OOS (day 0) = {r2_avgl1_oos:.6f}")


# ══════════════════════════════════════════════════════════════════════════
# SUMMARY TABLE
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("SUMMARY: R² comparison")
print("=" * 80)
print(f"{'Model':<35} {'R² Train':>10} {'R² OOS':>10} {'Delta vs L1':>12}")
print("-" * 67)
print(f"{'L1-only 4-lag (pooled)':<35} {r2_l1_train:>10.6f} {r2_l1_oos:>10.6f} {'baseline':>12}")
print(f"{'L1-only 4-lag (averaged)':<35} {'':>10} {r2_avgl1_oos:>10.6f} {'baseline':>12}")
print(f"{'L2-only 4-lag (pooled)':<35} {r2_train:>10.6f} {r2_oos:>10.6f} {r2_oos - r2_l1_oos:>+12.6f}")
r2_avg_train_s = f"{r2_avg_train:.6f}"
print(f"{'L2-only 4-lag (averaged)':<35} {r2_avg_train_s:>10} {r2_avg_oos:>10.6f} {r2_avg_oos - r2_avgl1_oos:>+12.6f}")
print(f"{'Combined 8-lag (pooled)':<35} {r2_train2:>10.6f} {r2_oos2:>10.6f} {r2_oos2 - r2_l1_oos:>+12.6f}")
r2_avg_train2_s = f"{r2_avg_train2:.6f}"
print(f"{'Combined 8-lag (averaged)':<35} {r2_avg_train2_s:>10} {r2_avg_oos2:>10.6f} {r2_avg_oos2 - r2_avgl1_oos:>+12.6f}")


# ══════════════════════════════════════════════════════════════════════════
# RESIDUAL DIAGNOSTICS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("RESIDUAL DIAGNOSTICS (OOS day 0)")
print("=" * 80)

for name, y_pred in [("L1-only", reg_l1.predict(X_l1_oos)),
                      ("L2-only", reg1_pooled.predict(X_l2_oos)),
                      ("Combined", reg2_pooled.predict(X_comb_oos))]:
    resid = y_oos - y_pred
    print(f"\n{name}:")
    print(f"  RMSE:       {np.sqrt(np.mean(resid**2)):.6f}")
    print(f"  MAE:        {np.mean(np.abs(resid)):.6f}")
    print(f"  Mean resid: {np.mean(resid):.6f}")
    print(f"  Std resid:  {np.std(resid):.6f}")
    # Autocorrelation of residuals
    ac1 = np.corrcoef(resid[:-1], resid[1:])[0, 1]
    print(f"  AC(1) of residuals: {ac1:.6f}")


# ══════════════════════════════════════════════════════════════════════════
# COLLINEARITY CHECK
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("COLLINEARITY: Correlation between L1 and L2 microprice (same lag)")
print("=" * 80)
for lag in range(4):
    corr = np.corrcoef(X_l1_train[:, lag], X_l2_train[:, lag])[0, 1]
    print(f"  Lag {3-lag}: r = {corr:.6f}")

# VIF-like: correlation among all 8 regressors
print("\nFull 8-regressor correlation matrix (training):")
labels = [f"L1_lag{3-i}" for i in range(4)] + [f"L2_lag{3-i}" for i in range(4)]
corr_matrix = np.corrcoef(X_comb_train.T)
print(f"{'':>10}", end="")
for l in labels:
    print(f"{l:>10}", end="")
print()
for i, l in enumerate(labels):
    print(f"{l:>10}", end="")
    for j in range(8):
        print(f"{corr_matrix[i,j]:>10.4f}", end="")
    print()


# ══════════════════════════════════════════════════════════════════════════
# HARD-COPY COEFFICIENTS FOR TRADER
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("HARD-COPY COEFFICIENTS (for trader code)")
print("=" * 80)

print("\n# Model 1: L2-only 4-lag (pooled)")
print(f"L2_INTERCEPT = {reg1_pooled.intercept_:.6f}")
print(f"L2_COEFS = [{', '.join(f'{c:.6f}' for c in reg1_pooled.coef_)}]  # [lag3, lag2, lag1, lag0]")

print("\n# Model 1: L2-only 4-lag (averaged)")
print(f"L2_INTERCEPT_AVG = {avg_intercept_1:.6f}")
print(f"L2_COEFS_AVG = [{', '.join(f'{c:.6f}' for c in avg_coefs_1)}]  # [lag3, lag2, lag1, lag0]")

print("\n# Model 2: Combined 8-lag (pooled)")
print(f"COMB_INTERCEPT = {reg2_pooled.intercept_:.6f}")
print(f"L1_COEFS = [{', '.join(f'{c:.6f}' for c in coefs2[:4])}]  # [lag3, lag2, lag1, lag0]")
print(f"L2_COEFS = [{', '.join(f'{c:.6f}' for c in coefs2[4:])}]  # [lag3, lag2, lag1, lag0]")

print("\n# Model 2: Combined 8-lag (averaged)")
print(f"COMB_INTERCEPT_AVG = {avg_intercept_2:.6f}")
print(f"L1_COEFS_AVG = [{', '.join(f'{c:.6f}' for c in avg_coefs_2[:4])}]  # [lag3, lag2, lag1, lag0]")
print(f"L2_COEFS_AVG = [{', '.join(f'{c:.6f}' for c in avg_coefs_2[4:])}]  # [lag3, lag2, lag1, lag0]")

print("\n# Existing L1-only 4-lag (pooled, for reference)")
print(f"L1_INTERCEPT = {reg_l1.intercept_:.6f}")
print(f"L1_COEFS = [{', '.join(f'{c:.6f}' for c in reg_l1.coef_)}]  # [lag3, lag2, lag1, lag0]")

print("\n# Existing L1-only 4-lag (averaged, for reference)")
print(f"L1_INTERCEPT_AVG = {avg_intercept_l1:.6f}")
print(f"L1_COEFS_AVG = [{', '.join(f'{c:.6f}' for c in avg_coefs_l1)}]  # [lag3, lag2, lag1, lag0]")
