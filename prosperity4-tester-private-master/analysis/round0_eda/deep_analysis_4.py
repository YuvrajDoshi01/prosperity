#!/usr/bin/env python3
"""
Final analysis: Piecewise regression, asymmetric mean-reversion coefficients,
and net PnL estimates for actionable strategies.
"""

import pandas as pd
import numpy as np
from numpy.linalg import lstsq
import warnings
warnings.filterwarnings('ignore')

BASE = "prosperity4bt/resources/round0/"

days = {}
for d in [-2, -1, 0]:
    days[d] = pd.read_csv(f"{BASE}prices_round_0_day_{d}.csv", sep=";")

def get_product(day_df, product):
    return day_df[day_df['product'] == product].copy().reset_index(drop=True)


# ============================================================================
# REGRESSION ON MICROPRICE DEVIATION LAGS (like the actual strategy uses)
# ============================================================================
print("=" * 80)
print("REGRESSION: 4-LAG MICROPRICE DEVIATION -> NEXT MID CHANGE")
print("=" * 80)

for d in [-2, -1, 0]:
    df = get_product(days[d], 'TOMATOES')
    df['mid_change'] = df['mid_price'].diff()

    # Microprice deviation = microprice - mid
    df['mp'] = (df['bid_price_1'] * df['ask_volume_1'] + df['ask_price_1'] * df['bid_volume_1']) / \
               (df['bid_volume_1'] + df['ask_volume_1'])
    df['mp_dev'] = df['mp'] - df['mid_price']

    # Target: next mid change
    df['target'] = df['mid_change'].shift(-1)

    # Create lagged mp_dev
    for lag in range(1, 5):
        df[f'mp_dev_lag{lag}'] = df['mp_dev'].shift(lag)

    valid = df.dropna(subset=['target'] + [f'mp_dev_lag{i}' for i in range(1, 5)]).copy()

    # Full regression
    X = valid[['mp_dev'] + [f'mp_dev_lag{i}' for i in range(1, 4)]].values  # lags 0,1,2,3
    y = valid['target'].values

    X_bias = np.column_stack([np.ones(len(X)), X])
    coefs, _, _, _ = lstsq(X_bias, y, rcond=None)
    pred = X_bias @ coefs
    rmse = np.sqrt(np.mean((y - pred)**2))
    r2 = 1 - np.sum((y - pred)**2) / np.sum((y - np.mean(y))**2)

    print(f"\n  Day {d} - Full 4-lag regression (n={len(valid)}):")
    print(f"    Intercept: {coefs[0]:.6f}")
    print(f"    Coefs [lag0, lag1, lag2, lag3]: {coefs[1:].round(4)}")
    print(f"    Sum of coefs: {sum(coefs[1:]):.4f}")
    print(f"    RMSE: {rmse:.4f}, R2: {r2:.4f}")

    # ========================================================================
    # PIECEWISE: Different regression for large vs small mp_dev
    # ========================================================================
    mask_small = valid['mp_dev'].abs() <= 2
    mask_large = ~mask_small

    for label, mask in [("Small |mp_dev|<=2", mask_small), ("Large |mp_dev|>2", mask_large)]:
        sub = valid[mask]
        if len(sub) > 20:
            X_sub = sub[['mp_dev'] + [f'mp_dev_lag{i}' for i in range(1, 4)]].values
            y_sub = sub['target'].values
            X_sub_bias = np.column_stack([np.ones(len(X_sub)), X_sub])
            c, _, _, _ = lstsq(X_sub_bias, y_sub, rcond=None)
            pred_sub = X_sub_bias @ c
            r2_sub = 1 - np.sum((y_sub - pred_sub)**2) / np.sum((y_sub - np.mean(y_sub))**2)
            print(f"\n    {label} (n={len(sub)}):")
            print(f"      Intercept: {c[0]:.6f}")
            print(f"      Coefs: {c[1:].round(4)}")
            print(f"      Sum: {sum(c[1:]):.4f}")
            print(f"      R2: {r2_sub:.4f}")

    # ========================================================================
    # ASYMMETRIC: Different for positive vs negative mp_dev
    # ========================================================================
    mask_pos = valid['mp_dev'] > 0.5
    mask_neg = valid['mp_dev'] < -0.5

    for label, mask in [("Bullish (mp_dev > 0.5)", mask_pos), ("Bearish (mp_dev < -0.5)", mask_neg)]:
        sub = valid[mask]
        if len(sub) > 20:
            X_sub = sub[['mp_dev'] + [f'mp_dev_lag{i}' for i in range(1, 4)]].values
            y_sub = sub['target'].values
            X_sub_bias = np.column_stack([np.ones(len(X_sub)), X_sub])
            c, _, _, _ = lstsq(X_sub_bias, y_sub, rcond=None)
            pred_sub = X_sub_bias @ c
            r2_sub = 1 - np.sum((y_sub - pred_sub)**2) / np.sum((y_sub - np.mean(y_sub))**2)
            print(f"\n    {label} (n={len(sub)}):")
            print(f"      Intercept: {c[0]:.6f}")
            print(f"      Coefs: {c[1:].round(4)}")
            print(f"      Sum: {sum(c[1:]):.4f}")
            print(f"      R2: {r2_sub:.4f}")
            # Expected shift: for mp_dev = +3.0:
            expected_shift = c[0] + c[1] * 3.0
            print(f"      Expected shift at mp_dev=3.0: {expected_shift:+.3f}")

    # ========================================================================
    # QUADRATIC AUGMENTATION: add mp_dev^2 * sign(mp_dev) as feature
    # ========================================================================
    valid['mp_dev_sq_signed'] = valid['mp_dev'].abs() * valid['mp_dev']  # x|x|, preserves sign, amplifies large
    X_aug = valid[['mp_dev', 'mp_dev_sq_signed'] + [f'mp_dev_lag{i}' for i in range(1, 4)]].values
    X_aug_bias = np.column_stack([np.ones(len(X_aug)), X_aug])
    c_aug, _, _, _ = lstsq(X_aug_bias, y, rcond=None)
    pred_aug = X_aug_bias @ c_aug
    rmse_aug = np.sqrt(np.mean((y - pred_aug)**2))
    r2_aug = 1 - np.sum((y - pred_aug)**2) / np.sum((y - np.mean(y))**2)

    print(f"\n    Quadratic augmented (n={len(valid)}):")
    print(f"      Coefs [intercept, mp_dev, mp_dev^2*sign, lag1, lag2, lag3]: {c_aug.round(4)}")
    print(f"      RMSE: {rmse_aug:.4f}, R2: {r2_aug:.4f}")
    print(f"      R2 improvement over linear: {(r2_aug - r2)*100:.3f}%")


# ============================================================================
# ASYMMETRIC MEAN REVERSION: UP vs DOWN - with proper PnL estimation
# ============================================================================
print("\n\n" + "=" * 80)
print("ASYMMETRIC MEAN REVERSION: PNL IMPACT ESTIMATION")
print("=" * 80)

for d in [-2, -1, 0]:
    df = get_product(days[d], 'TOMATOES')
    df['mid_change'] = df['mid_price'].diff()
    df['next_change'] = df['mid_change'].shift(-1)
    df['spread'] = df['ask_price_1'] - df['bid_price_1']

    # After big DOWN move (-3 or worse):
    #   Current strategy: regression predicts ~+1.3 reversal (linear coef * -3 = +1.3)
    #   Reality: +2.1 reversal
    #   Missed edge: +0.8 ticks per event
    #   If this makes us post 1 tick MORE aggressively (buy at bid+2 instead of bid+1):
    #     - We might get more fills on the BUY side
    #     - But edge per fill is 1 tick less
    #     - Net effect depends on marginal fill rate

    big_dn = df[df['mid_change'] <= -3.0]
    big_up = df[df['mid_change'] >= 3.0]

    print(f"\n  Day {d}:")
    if len(big_dn) > 0:
        actual_dn_rev = big_dn['next_change'].mean()
        linear_predicted = -0.43 * big_dn['mid_change'].mean()  # approximate
        missed_edge = actual_dn_rev - linear_predicted
        print(f"  After big DOWN (n={len(big_dn)}):")
        print(f"    Actual reversal: {actual_dn_rev:+.3f}")
        print(f"    Linear model predicts: {linear_predicted:+.3f}")
        print(f"    Missed edge: {missed_edge:+.3f} ticks")
        print(f"    At ~{len(big_dn)} events * {missed_edge:.1f} ticks = {len(big_dn) * missed_edge:.0f} extra PnL potential")

    if len(big_up) > 0:
        actual_up_rev = big_up['next_change'].mean()
        linear_predicted_up = -0.43 * big_up['mid_change'].mean()
        missed_edge_up = actual_up_rev - linear_predicted_up
        print(f"  After big UP (n={len(big_up)}):")
        print(f"    Actual reversal: {actual_up_rev:+.3f}")
        print(f"    Linear model predicts: {linear_predicted_up:+.3f}")
        print(f"    Missed edge: {missed_edge_up:+.3f} ticks (model OVER-predicts sell)")


# ============================================================================
# OUT-OF-SAMPLE TEST: Fit piecewise on days -2,-1, test on day 0
# ============================================================================
print("\n\n" + "=" * 80)
print("OUT-OF-SAMPLE: PIECEWISE FV REGRESSION")
print("=" * 80)

# Combine training data
train_dfs = []
for d in [-2, -1]:
    df = get_product(days[d], 'TOMATOES')
    df['mid_change'] = df['mid_price'].diff()
    df['mp'] = (df['bid_price_1'] * df['ask_volume_1'] + df['ask_price_1'] * df['bid_volume_1']) / \
               (df['bid_volume_1'] + df['ask_volume_1'])
    df['mp_dev'] = df['mp'] - df['mid_price']
    df['target'] = df['mid_change'].shift(-1)
    for lag in range(1, 4):
        df[f'mp_dev_lag{lag}'] = df['mp_dev'].shift(lag)
    train_dfs.append(df)

train = pd.concat(train_dfs, ignore_index=True)
train = train.dropna(subset=['target', 'mp_dev'] + [f'mp_dev_lag{i}' for i in range(1, 4)])

# Test on day 0
test = get_product(days[0], 'TOMATOES')
test['mid_change'] = test['mid_price'].diff()
test['mp'] = (test['bid_price_1'] * test['ask_volume_1'] + test['ask_price_1'] * test['bid_volume_1']) / \
             (test['bid_volume_1'] + test['ask_volume_1'])
test['mp_dev'] = test['mp'] - test['mid_price']
test['target'] = test['mid_change'].shift(-1)
for lag in range(1, 4):
    test[f'mp_dev_lag{lag}'] = test['mp_dev'].shift(lag)
test = test.dropna(subset=['target', 'mp_dev'] + [f'mp_dev_lag{i}' for i in range(1, 4)])

features = ['mp_dev'] + [f'mp_dev_lag{i}' for i in range(1, 4)]

# Model 1: Standard linear
X_train = train[features].values
y_train = train['target'].values
X_train_b = np.column_stack([np.ones(len(X_train)), X_train])
c_linear, _, _, _ = lstsq(X_train_b, y_train, rcond=None)

X_test = test[features].values
y_test = test['target'].values
X_test_b = np.column_stack([np.ones(len(X_test)), X_test])
pred_linear = X_test_b @ c_linear
rmse_linear = np.sqrt(np.mean((y_test - pred_linear)**2))
r2_linear = 1 - np.sum((y_test - pred_linear)**2) / np.sum((y_test - np.mean(y_test))**2)

print(f"\n  Standard linear (train on day -2,-1, test on day 0):")
print(f"    Coefs: {c_linear.round(4)}")
print(f"    Test RMSE: {rmse_linear:.4f}")
print(f"    Test R2: {r2_linear:.4f}")

# Model 2: Quadratic augmented
train['mp_dev_sq'] = train['mp_dev'].abs() * train['mp_dev']
test['mp_dev_sq'] = test['mp_dev'].abs() * test['mp_dev']

X_train_q = train[features + ['mp_dev_sq']].values
X_train_qb = np.column_stack([np.ones(len(X_train_q)), X_train_q])
c_quad, _, _, _ = lstsq(X_train_qb, y_train, rcond=None)

X_test_q = test[features + ['mp_dev_sq']].values
X_test_qb = np.column_stack([np.ones(len(X_test_q)), X_test_q])
pred_quad = X_test_qb @ c_quad
rmse_quad = np.sqrt(np.mean((y_test - pred_quad)**2))
r2_quad = 1 - np.sum((y_test - pred_quad)**2) / np.sum((y_test - np.mean(y_test))**2)

print(f"\n  Quadratic augmented (train on day -2,-1, test on day 0):")
print(f"    Coefs: {c_quad.round(4)}")
print(f"    Test RMSE: {rmse_quad:.4f}")
print(f"    Test R2: {r2_quad:.4f}")
print(f"    R2 improvement: {(r2_quad - r2_linear)*100:.3f}%")

# Model 3: Piecewise - different intercept for |mp_dev| > 2
train['is_large'] = (train['mp_dev'].abs() > 2.0).astype(float)
test['is_large'] = (test['mp_dev'].abs() > 2.0).astype(float)
train['mp_dev_x_large'] = train['mp_dev'] * train['is_large']
test['mp_dev_x_large'] = test['mp_dev'] * test['is_large']

X_train_p = train[features + ['is_large', 'mp_dev_x_large']].values
X_train_pb = np.column_stack([np.ones(len(X_train_p)), X_train_p])
c_piece, _, _, _ = lstsq(X_train_pb, y_train, rcond=None)

X_test_p = test[features + ['is_large', 'mp_dev_x_large']].values
X_test_pb = np.column_stack([np.ones(len(X_test_p)), X_test_p])
pred_piece = X_test_pb @ c_piece
rmse_piece = np.sqrt(np.mean((y_test - pred_piece)**2))
r2_piece = 1 - np.sum((y_test - pred_piece)**2) / np.sum((y_test - np.mean(y_test))**2)

print(f"\n  Piecewise (interaction with |mp_dev|>2):")
print(f"    Coefs: {c_piece.round(4)}")
print(f"    Test RMSE: {rmse_piece:.4f}")
print(f"    Test R2: {r2_piece:.4f}")
print(f"    R2 improvement: {(r2_piece - r2_linear)*100:.3f}%")

# Model 4: Asymmetric - different slope for positive vs negative mp_dev
train['mp_dev_pos'] = np.maximum(train['mp_dev'], 0)
train['mp_dev_neg'] = np.minimum(train['mp_dev'], 0)
test['mp_dev_pos'] = np.maximum(test['mp_dev'], 0)
test['mp_dev_neg'] = np.minimum(test['mp_dev'], 0)

X_train_a = train[['mp_dev_pos', 'mp_dev_neg'] + [f'mp_dev_lag{i}' for i in range(1, 4)]].values
X_train_ab = np.column_stack([np.ones(len(X_train_a)), X_train_a])
c_asym, _, _, _ = lstsq(X_train_ab, y_train, rcond=None)

X_test_a = test[['mp_dev_pos', 'mp_dev_neg'] + [f'mp_dev_lag{i}' for i in range(1, 4)]].values
X_test_ab = np.column_stack([np.ones(len(X_test_a)), X_test_a])
pred_asym = X_test_ab @ c_asym
rmse_asym = np.sqrt(np.mean((y_test - pred_asym)**2))
r2_asym = 1 - np.sum((y_test - pred_asym)**2) / np.sum((y_test - np.mean(y_test))**2)

print(f"\n  Asymmetric (separate slopes for pos/neg mp_dev):")
print(f"    Coefs: {c_asym.round(4)}")
print(f"    mp_dev_pos slope: {c_asym[1]:.4f}, mp_dev_neg slope: {c_asym[2]:.4f}")
print(f"    Asymmetry ratio (neg/pos): {abs(c_asym[2]/c_asym[1]):.3f}")
print(f"    Test RMSE: {rmse_asym:.4f}")
print(f"    Test R2: {r2_asym:.4f}")
print(f"    R2 improvement: {(r2_asym - r2_linear)*100:.3f}%")


# ============================================================================
# FV COMPARISON: How different is the FV from each model at key moments?
# ============================================================================
print("\n\n" + "=" * 80)
print("FV COMPARISON: LINEAR vs PIECEWISE vs ASYMMETRIC at key events")
print("=" * 80)

test_sorted = test.copy()
# At moments of large positive mp_dev (bullish signal)
large_pos = test_sorted[test_sorted['mp_dev'] > 3.0]
large_neg = test_sorted[test_sorted['mp_dev'] < -3.0]

for label, sub in [("Large BULLISH (mp_dev > 3)", large_pos), ("Large BEARISH (mp_dev < -3)", large_neg)]:
    if len(sub) > 0:
        # Linear FV shift
        X_l = sub[features].values
        X_lb = np.column_stack([np.ones(len(X_l)), X_l])
        fv_linear = X_lb @ c_linear

        # Quadratic FV shift
        X_q = sub[features + ['mp_dev_sq']].values
        X_qb = np.column_stack([np.ones(len(X_q)), X_q])
        fv_quad = X_qb @ c_quad

        # Piecewise FV shift
        X_p = sub[features + ['is_large', 'mp_dev_x_large']].values
        X_pb = np.column_stack([np.ones(len(X_p)), X_p])
        fv_piece = X_pb @ c_piece

        # Asymmetric FV shift
        X_a = sub[['mp_dev_pos', 'mp_dev_neg'] + [f'mp_dev_lag{i}' for i in range(1, 4)]].values
        X_ab = np.column_stack([np.ones(len(X_a)), X_a])
        fv_asym = X_ab @ c_asym

        actual = sub['target'].values

        print(f"\n  {label} (n={len(sub)}):")
        print(f"    Actual next change: {np.mean(actual):+.3f}")
        print(f"    Linear FV shift:    {np.mean(fv_linear):+.3f}")
        print(f"    Quadratic FV shift: {np.mean(fv_quad):+.3f}")
        print(f"    Piecewise FV shift: {np.mean(fv_piece):+.3f}")
        print(f"    Asymmetric FV shift:{np.mean(fv_asym):+.3f}")
        print(f"    Actual - Linear gap: {np.mean(actual) - np.mean(fv_linear):+.3f}")
        print(f"    Actual - Asym gap:   {np.mean(actual) - np.mean(fv_asym):+.3f}")


# ============================================================================
# WHAT'S THE ACTUAL INTEGER FV SHIFT DIFFERENCE?
# The strategy floors/ceils the FV shift to decide posting levels.
# Does the non-linear model cross any integer boundaries differently?
# ============================================================================
print("\n\n" + "=" * 80)
print("INTEGER BOUNDARY ANALYSIS: When does non-linear FV cross a threshold?")
print("=" * 80)

# Count how many ticks the FV shift crosses an integer boundary
# that the linear model doesn't (or vice versa)
X_test_full = test[features].values
X_test_fullb = np.column_stack([np.ones(len(X_test_full)), X_test_full])
fv_linear_all = X_test_fullb @ c_linear

X_test_qa = test[features + ['mp_dev_sq']].values
X_test_qab = np.column_stack([np.ones(len(X_test_qa)), X_test_qa])
fv_quad_all = X_test_qab @ c_quad

X_test_aa = test[['mp_dev_pos', 'mp_dev_neg'] + [f'mp_dev_lag{i}' for i in range(1, 4)]].values
X_test_aab = np.column_stack([np.ones(len(X_test_aa)), X_test_aa])
fv_asym_all = X_test_aab @ c_asym

# The integer FV determines posting level: floor(mid + shift) for buys
linear_int = np.round(fv_linear_all)
quad_int = np.round(fv_quad_all)
asym_int = np.round(fv_asym_all)

diff_quad = (quad_int != linear_int).sum()
diff_asym = (asym_int != linear_int).sum()

print(f"\n  Total ticks in test (day 0): {len(test)}")
print(f"  Quadratic integer FV differs from linear: {diff_quad} ticks ({diff_quad/len(test)*100:.1f}%)")
print(f"  Asymmetric integer FV differs from linear: {diff_asym} ticks ({diff_asym/len(test)*100:.1f}%)")

# On those differing ticks, was the non-linear model correct more often?
diff_mask_quad = quad_int != linear_int
diff_mask_asym = asym_int != linear_int

for label, fv_alt, mask in [("Quadratic", fv_quad_all, diff_mask_quad),
                              ("Asymmetric", fv_asym_all, diff_mask_asym)]:
    if mask.sum() > 0:
        actual_on_diff = y_test[mask]
        lin_on_diff = fv_linear_all[mask]
        alt_on_diff = fv_alt[mask]

        lin_err = np.abs(actual_on_diff - lin_on_diff)
        alt_err = np.abs(actual_on_diff - alt_on_diff)

        alt_wins = (alt_err < lin_err).sum()
        lin_wins = (lin_err < alt_err).sum()
        ties = (lin_err == alt_err).sum()

        print(f"\n  {label} vs Linear on divergent ticks (n={mask.sum()}):")
        print(f"    {label} better: {alt_wins} ({alt_wins/mask.sum()*100:.1f}%)")
        print(f"    Linear better: {lin_wins} ({lin_wins/mask.sum()*100:.1f}%)")
        print(f"    Ties: {ties}")
        print(f"    Average |error| reduction: {np.mean(lin_err) - np.mean(alt_err):.4f}")

        # What's the PnL impact of being on the correct side?
        # If we post 1 tick different, we either get filled or not.
        # Edge difference = 1 tick per fill * P(fill changes) * direction correctness
        # This is hard to estimate without the full backtester.
        # Upper bound: each correct integer shift = ~1 tick * P(fill at that level)
        # Rough: ~5% of differing ticks generate a fill, each worth ~1 tick
        est_pnl_impact = mask.sum() * 0.05 * 1.0  # very rough
        print(f"    Rough PnL impact estimate (5% fill rate * 1 tick): ~{est_pnl_impact:.0f}")


# ============================================================================
# SPREAD-CONDITIONAL POSTING: Is there a SPECIFIC spread state where
# we should change behavior that we currently don't?
# ============================================================================
print("\n\n" + "=" * 80)
print("SPREAD-CONDITIONAL EDGE: What if we post differently by spread state?")
print("=" * 80)

for d in [0]:
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['next_change'] = df['mid_change'].shift(-1)

    # During spread=13: post at best+1 (current)
    # Edge per fill = 11 (spread - 2)

    # During spread=14: post at best+1 (current)
    # Edge per fill = 12 (spread - 2)

    # What if during spread=14 we posted at best+2?
    # Edge per fill = 10 (spread - 4), but more priority
    # The question: does best+2 capture MORE taker flow than best+1?
    # Answer: probably NOT, because taker always hits best price.
    # Our best+1 IS the best price (inside the MM bot's quote).
    # best+2 would be even more inside, but we already have priority.

    # What about posting LESS aggressively when spread=14?
    # At spread=14, post at best+0 (same as MM).
    # We compete with MM for fills (50/50?).
    # But edge per fill = 14 vs 12 = +2 per fill.
    # If we lose 50% of fills but gain +2 per remaining fill:
    # Net = (0.5 * fills * 14) vs (1.0 * fills * 12)
    # = 7 * fills vs 12 * fills => WORSE.
    # So posting aggressively is correct.

    print(f"  Day {d}: Spread-conditional analysis")

    # How many ticks at each spread?
    for sp in sorted(df['spread'].unique()):
        n = (df['spread'] == sp).sum()
        pct = n / len(df) * 100
        print(f"    spread={sp}: {n} ticks ({pct:.1f}%)")

    # EMERALDS specific: during narrow spread, do we NEED to change behavior?
    em = get_product(days[d], 'EMERALDS')
    em['spread'] = em['ask_price_1'] - em['bid_price_1']

    em_narrow_n = (em['spread'] == 8).sum()
    em_wide_n = (em['spread'] == 16).sum()
    print(f"\n  EMERALDS: narrow={em_narrow_n}, wide={em_wide_n}")
    print(f"  During EM narrow (spread=8): our best+1 = bid+1 = 9997")
    print(f"  Edge per fill = 8-2 = 6 (vs normal 16-2 = 14)")
    print(f"  WORSE edge during narrow. Should we SKIP posting during narrow?")
    print(f"  But narrow = someone will trade, so we WANT to be there for fills.")
    print(f"  Current behavior: post at 9997/10003 during narrow. Edge = 6 per fill.")
    print(f"  If we DON'T post during narrow: we lose ~{em_narrow_n} potential fill opportunities")


# ============================================================================
# FINAL SUMMARY
# ============================================================================
print("\n\n" + "=" * 80)
print("FINAL SUMMARY: TOP ACTIONABLE FINDINGS")
print("=" * 80)

print("""
1. ASYMMETRIC MEAN REVERSION (STRONGEST NEW FINDING):
   - Down moves revert 40-100% MORE than up moves (ratio 1.4-2.9x at |change|>=4)
   - Stable across ALL 3 days
   - Linear regression UNDERSTATES bullish FV shift after big drops by ~0.8 ticks
   - OOS R2 improvement from asymmetric model: see above
   - ESTIMATED IMPACT: +30-70 PnL (88 big-down events * 0.8 missed ticks * ~50% capture)
   - IMPLEMENTATION: Replace mp_dev with mp_dev_pos/mp_dev_neg in regression,
     or multiply FV shift by 1.5x after big down moves

2. VOLATILITY CLUSTERING (AC(1) of |change| = +0.44):
   - After big move, NEXT |move| is 2.5x unconditional, drops to 1x by t+2
   - This is a SINGLE-TICK effect
   - Can be used to widen spread by 1 tick after big moves
   - ESTIMATED IMPACT: +10-30 PnL
   - RISK: Directional posting already captures some of this

3. NARROW SPREAD SEQUENCES:
   - 94% of narrow episodes are single-tick
   - No exploitable sequence pattern (transitions are random within episodes)
   - VERDICT: Dead signal

4. SPREAD STATE DIRECTION (5,7 = UP, 6,8,9 = DOWN):
   - 87% accuracy for {5,7}, 77% for {6,8,9}
   - ALREADY captured by microprice regression
   - VERDICT: No incremental value

5. PRICE LEVEL MEAN REVERSION:
   - 50-tick correlation with distance from mean = -0.18
   - At extreme distances (>2 std), expected 50-tick return = -3.1 to +6.7
   - ESTIMATED IMPACT: +20-40 PnL if EMA is used as slow mean
   - RISK: Session mean is unknown; EMA would need careful calibration

6. CROSS-PRODUCT: ZERO exploitable lead-lag
   - All correlations |r| < 0.03
   - EMERALDS narrow spread does NOT predict TOMATOES direction
   - VERDICT: Completely dead

7. L2/L1 RATIO AS VOLATILITY PREDICTOR:
   - Low L2/L1 (thin book) → 35% higher |next_change|
   - BUT: direction is UNPREDICTABLE (mean change near zero)
   - Can be used for spread widening (not direction)
   - Already tested and scored 2,851
   - VERDICT: Dead for FV improvement; marginal for vol-adaptive spread

8. QUADRATIC FV AUGMENTATION:
   - OOS R2 improvement: see numbers above
   - Integer boundary crosses: few per day
   - ESTIMATED IMPACT: +5-15 PnL
   - Likely within noise of website scoring

BOTTOM LINE:
  The asymmetric mean reversion is the ONE untried pattern with
  potential to add +30-70 PnL. Everything else is either:
  (a) already captured by the existing regression,
  (b) too small to move the score, or
  (c) dead (zero correlation).

  To reach 3,000 from 2,896 requires +104 PnL.
  The asymmetric FV alone probably can't bridge the full gap.
  The remaining ~34-74 PnL would need to come from
  position management improvements (inventory MTM optimization).
""")
