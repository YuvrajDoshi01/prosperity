"""
FINAL ANALYSIS: Economic value of the truly incremental findings.
Focus on what SURVIVES after controlling for the 4-lag regression + microprice + OBI
that s36_medallion already uses.
"""

import pandas as pd
import numpy as np
from scipy import stats
from sklearn.linear_model import LinearRegression
import warnings
warnings.filterwarnings('ignore')

BASE = "/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0"

def load_tomatoes(day_suffix):
    path = f"{BASE}/prices_round_0_day_{day_suffix}.csv"
    df = pd.read_csv(path, sep=';')
    tom = df[df['product'] == 'TOMATOES'].copy().reset_index(drop=True)
    tom['mid'] = tom['mid_price']
    tom['best_bid'] = tom['bid_price_1']
    tom['best_ask'] = tom['ask_price_1']
    tom['spread'] = tom['best_ask'] - tom['best_bid']
    tom['dmid'] = tom['mid'].diff().shift(-1)
    tom['dmid_actual'] = tom['mid'].diff()
    tom['bid_vol_1'] = tom['bid_volume_1']
    tom['ask_vol_1'] = tom['ask_volume_1']
    tom['bid_vol_2'] = tom['bid_volume_2'].fillna(0)
    tom['ask_vol_2'] = tom['ask_volume_2'].fillna(0)
    tom['l1_total_vol'] = tom['bid_vol_1'] + tom['ask_vol_1']
    tom['bid_delta'] = tom['best_bid'].diff()
    tom['ask_delta'] = tom['best_ask'].diff()
    return tom

day0 = load_tomatoes('0')
daym1 = load_tomatoes('-1')
daym2 = load_tomatoes('-2')
is_data = pd.concat([daym1, daym2], ignore_index=True)

# ===========================================================================
# BUILD THE FULL FEATURE SET
# ===========================================================================

def build_features(data):
    data = data.copy()

    # 4-lag features (what s36 uses)
    data['lag1'] = data['dmid_actual']
    data['lag2'] = data['dmid_actual'].shift(1)
    data['lag3'] = data['dmid_actual'].shift(2)
    data['lag4'] = data['dmid_actual'].shift(3)

    # Microprice deviation (what s36 uses via regression)
    data['microprice'] = (data['best_bid'] * data['ask_vol_1'] + data['best_ask'] * data['bid_vol_1']) / (data['bid_vol_1'] + data['ask_vol_1'])
    data['mp_dev'] = data['microprice'] - data['mid']

    # OBI (what s36 uses)
    data['obi'] = ((data['bid_vol_1'] + data['bid_vol_2']) - (data['ask_vol_1'] + data['ask_vol_2'])) / \
                  ((data['bid_vol_1'] + data['bid_vol_2']) + (data['ask_vol_1'] + data['ask_vol_2']))

    # NEW FEATURES TO TEST

    # 1. Move type encoding
    def classify_move(bid_d, ask_d):
        if pd.isna(bid_d) or pd.isna(ask_d): return 'unknown'
        bid_d, ask_d = round(bid_d, 1), round(ask_d, 1)
        if bid_d > 0 and ask_d > 0: return 'both_up'
        elif bid_d < 0 and ask_d < 0: return 'both_down'
        elif bid_d > 0 and ask_d == 0: return 'bid_up_only'
        elif bid_d < 0 and ask_d == 0: return 'bid_down_only'
        elif bid_d == 0 and ask_d > 0: return 'ask_up_only'
        elif bid_d == 0 and ask_d < 0: return 'ask_down_only'
        elif bid_d > 0 and ask_d < 0: return 'spread_narrow'
        elif bid_d < 0 and ask_d > 0: return 'spread_widen'
        else: return 'no_move'

    data['move_type'] = [classify_move(b, a) for b, a in zip(data['bid_delta'], data['ask_delta'])]
    data['prev_move'] = data['move_type'].shift(1)

    # Binary features for significant move sequences
    data['seq_nomove_bidup'] = ((data['prev_move'] == 'no_move') & (data['move_type'] == 'bid_up_only')).astype(float)
    data['seq_nomove_askdn'] = ((data['prev_move'] == 'no_move') & (data['move_type'] == 'ask_down_only')).astype(float)
    data['seq_askup_bidup'] = ((data['prev_move'] == 'ask_up_only') & (data['move_type'] == 'bid_up_only')).astype(float)
    data['seq_biddn_bidup'] = ((data['prev_move'] == 'bid_down_only') & (data['move_type'] == 'bid_up_only')).astype(float)

    # Aggregated: "asymmetric move" indicator
    # bid_up_only or ask_down_only (one side moved, other stayed)
    data['asym_up'] = (data['move_type'] == 'bid_up_only').astype(float)
    data['asym_down'] = (data['move_type'] == 'ask_down_only').astype(float)

    # 2. Range percentile
    for w in [50, 100]:
        roll_min = data['mid'].rolling(w, min_periods=w).min()
        roll_max = data['mid'].rolling(w, min_periods=w).max()
        data[f'pct{w}'] = (data['mid'] - roll_min) / (roll_max - roll_min)

    # 3. Spread state features
    data['narrow_spread'] = (data['spread'] <= 9).astype(float)
    data['spread_is_5'] = (data['spread'] == 5).astype(float)
    data['spread_is_6'] = (data['spread'] == 6).astype(float)
    data['spread_is_7'] = (data['spread'] == 7).astype(float)
    data['spread_is_8'] = (data['spread'] == 8).astype(float)
    data['spread_is_9'] = (data['spread'] == 9).astype(float)

    # 4. Bid-ask asymmetry
    data['ba_asymmetry'] = data['ask_delta'] - data['bid_delta']

    # 5. Prior no_move count (how many ticks was there no move before current)
    no_move = (data['move_type'] == 'no_move').astype(int)
    data['no_move_run'] = 0
    run = 0
    for i in range(len(data)):
        if no_move.iloc[i] == 1:
            run += 1
        else:
            run = 0
        data.iloc[i, data.columns.get_loc('no_move_run')] = run

    return data

print("Building features...")
is_feat = build_features(is_data)
oos_feat = build_features(day0)

# ===========================================================================
# REGRESSION TOURNAMENT: Which features add value beyond s36 baseline?
# ===========================================================================
print("="*80)
print("REGRESSION TOURNAMENT: Incremental R2 beyond s36 baseline features")
print("="*80)

baseline_features = ['lag1', 'lag2', 'lag3', 'lag4']

candidate_features = [
    ('mp_dev', 'Microprice deviation'),
    ('obi', 'Order book imbalance'),
    ('pct50', 'Range percentile (50-tick)'),
    ('pct100', 'Range percentile (100-tick)'),
    ('seq_nomove_bidup', 'Sequence: no_move -> bid_up_only'),
    ('seq_nomove_askdn', 'Sequence: no_move -> ask_down_only'),
    ('seq_askup_bidup', 'Sequence: ask_up -> bid_up_only'),
    ('seq_biddn_bidup', 'Sequence: bid_down -> bid_up_only'),
    ('asym_up', 'Asymmetric bid-up (bid moved, ask stayed)'),
    ('asym_down', 'Asymmetric ask-down (ask moved, bid stayed)'),
    ('narrow_spread', 'Narrow spread indicator'),
    ('ba_asymmetry', 'Bid-ask move asymmetry'),
    ('no_move_run', 'Consecutive no-move count'),
]

target = 'dmid'

for label, data in [("IS (day-1+day-2)", is_feat), ("OOS (day 0)", oos_feat)]:
    print(f"\n  {label}:")

    # Baseline R2
    valid_all = data[baseline_features + [f for f, _ in candidate_features] + [target]].dropna()
    X_base = valid_all[baseline_features].values
    y = valid_all[target].values

    r2_base = LinearRegression().fit(X_base, y).score(X_base, y)
    print(f"    Baseline (4-lag): R2 = {r2_base:.6f} (N={len(valid_all)})")

    # Each candidate feature individually
    results = []
    for feat, desc in candidate_features:
        X_plus = valid_all[baseline_features + [feat]].values
        r2_plus = LinearRegression().fit(X_plus, y).score(X_plus, y)
        increment = r2_plus - r2_base

        # F-test for the additional feature
        n = len(valid_all)
        p_base = len(baseline_features)
        p_plus = p_base + 1
        f_stat = (r2_plus - r2_base) / (1 - r2_plus) * (n - p_plus) / 1 if r2_plus < 1 else float('inf')
        p_val = 1 - stats.f.cdf(f_stat, 1, n - p_plus)

        results.append((feat, desc, r2_plus, increment, f_stat, p_val))

    results.sort(key=lambda x: -x[3])
    print(f"\n    {'Feature':<40} {'R2':>10} {'Delta_R2':>10} {'F-stat':>10} {'p-value':>10}")
    print("    " + "-"*85)
    for feat, desc, r2, incr, f, p in results:
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        print(f"    {desc:<40} {r2:>10.6f} {incr:>10.6f} {f:>10.2f} {p:>10.4f} {sig}")

# ===========================================================================
# FULL MODEL: 4-lag + mp_dev + obi + best new features
# ===========================================================================
print("\n\n" + "="*80)
print("FULL MODEL COMPARISON: s36 baseline vs augmented")
print("="*80)

s36_features = ['lag1', 'lag2', 'lag3', 'lag4', 'mp_dev', 'obi']
augmented_features = s36_features + ['pct50', 'asym_up', 'asym_down']
augmented2_features = s36_features + ['pct50', 'ba_asymmetry']
augmented3_features = s36_features + ['pct50', 'seq_nomove_bidup', 'seq_nomove_askdn']

for label, data in [("IS (day-1+day-2)", is_feat), ("OOS (day 0)", oos_feat)]:
    all_feats = list(set(s36_features + augmented_features + augmented2_features + augmented3_features))
    valid = data[all_feats + [target]].dropna()
    y = valid[target].values

    print(f"\n  {label} (N={len(valid)}):")

    for name, feats in [
        ("4-lag only", baseline_features),
        ("s36 (4-lag + mp + obi)", s36_features),
        ("s36 + pct50 + asym_up/down", augmented_features),
        ("s36 + pct50 + ba_asymmetry", augmented2_features),
        ("s36 + pct50 + move_seqs", augmented3_features),
    ]:
        X = valid[feats].values
        reg = LinearRegression().fit(X, y)
        r2 = reg.score(X, y)

        # AIC approximation
        n = len(valid)
        k = len(feats) + 1  # +1 for intercept
        rss = np.sum((y - reg.predict(X))**2)
        aic = n * np.log(rss/n) + 2*k

        print(f"    {name:<35}: R2={r2:.6f}, AIC={aic:.1f}")
        if name.startswith("s36 "):
            print(f"      Coefficients: {dict(zip(feats, [f'{c:.4f}' for c in reg.coef_]))}")

# ===========================================================================
# THE BIG QUESTION: Why does the move-type matter BEYOND dmid?
# ===========================================================================
print("\n\n" + "="*80)
print("THE KEY INSIGHT: bid_up_only vs both_up (same dmid, different spread implication)")
print("="*80)

for name, data in [("IS", is_feat), ("OOS", oos_feat)]:
    print(f"\n  {name}:")

    # Both bid_up_only and both_up produce positive dmid.
    # But bid_up_only = spread NARROWED (bid went up, ask stayed)
    # both_up = spread SAME (both moved up)

    # After bid_up_only: spread is temporarily narrow => MM will widen => bid drops
    # After both_up: spread stayed same => no reversion pressure

    for mt in ['bid_up_only', 'both_up', 'ask_down_only', 'both_down']:
        mask = data['move_type'] == mt
        sub = data.loc[mask]

        dmid_at = sub['dmid_actual'].mean()
        spread_at = sub['spread'].mean()
        dmid_next = sub['dmid'].dropna().mean()
        spread_next = data.loc[data.index.isin(sub.index + 1), 'spread']

        n = mask.sum()
        se = sub['dmid'].std() / np.sqrt(len(sub['dmid'].dropna())) if len(sub['dmid'].dropna()) > 0 else float('inf')
        t = dmid_next / se if se > 0 and se != float('inf') else 0

        print(f"    {mt:>15}: N={n:>5}, dmid_at={dmid_at:>6.3f}, spread_at={spread_at:>5.1f}, E[dmid_next]={dmid_next:>7.4f} (t={t:>6.2f})")

    # The spread after move type
    print(f"\n    Spread AFTER each move type:")
    for mt in ['bid_up_only', 'both_up', 'ask_down_only', 'both_down', 'no_move']:
        mask = data['move_type'] == mt
        indices = data.loc[mask].index
        next_indices = [i+1 for i in indices if i+1 < len(data)]
        if next_indices:
            spreads = data.loc[next_indices, 'spread']
            print(f"      {mt:>15}: mean spread = {spreads.mean():.1f}, % narrow = {(spreads<=9).mean()*100:.1f}%")

# ===========================================================================
# QUANTIFY: How much PnL does the move-type signal add in a realistic strategy?
# ===========================================================================
print("\n\n" + "="*80)
print("REALISTIC PnL ESTIMATE: Move-type signal as FV adjustment")
print("="*80)

for name, data in [("IS", is_feat), ("OOS", oos_feat)]:
    data = data.copy()

    # Current s36 FV estimate (simplified): based on 4-lag regression + microprice
    # We'll compare:
    # Strategy A: predict dmid using 4-lag + mp_dev + obi (s36 baseline)
    # Strategy B: predict dmid using 4-lag + mp_dev + obi + move_type info

    feats_a = ['lag1', 'lag2', 'lag3', 'lag4', 'mp_dev', 'obi']
    feats_b = feats_a + ['asym_up', 'asym_down']

    valid = data[feats_b + ['dmid']].dropna()
    y = valid['dmid'].values

    reg_a = LinearRegression().fit(valid[feats_a].values, y)
    reg_b = LinearRegression().fit(valid[feats_b].values, y)

    pred_a = reg_a.predict(valid[feats_a].values)
    pred_b = reg_b.predict(valid[feats_b].values)

    # PnL = sum of |prediction_improvement| when direction is correct
    # More precisely: for ticks where B disagrees with A about direction,
    # how often is B correct?

    disagree = np.sign(pred_b) != np.sign(pred_a)
    n_disagree = disagree.sum()
    if n_disagree > 0:
        b_correct = (np.sign(pred_b[disagree]) == np.sign(y[disagree])).mean()
        a_correct = (np.sign(pred_a[disagree]) == np.sign(y[disagree])).mean()
        print(f"\n  {name}: Ticks where A and B disagree on direction: {n_disagree} ({n_disagree/len(y)*100:.1f}%)")
        print(f"    On these ticks: A correct {a_correct*100:.1f}%, B correct {b_correct*100:.1f}%")

    # Better metric: RMSE improvement
    rmse_a = np.sqrt(np.mean((y - pred_a)**2))
    rmse_b = np.sqrt(np.mean((y - pred_b)**2))
    print(f"  {name}: RMSE(A)={rmse_a:.4f}, RMSE(B)={rmse_b:.4f}, improvement={rmse_a-rmse_b:.4f}")

    # Average absolute prediction improvement
    abs_improvement = np.abs(pred_b - pred_a).mean()
    print(f"  {name}: Average |FV shift| from move-type: {abs_improvement:.4f}")

    # On ticks with asymmetric moves (the signal fires), what's the improvement?
    asym_mask = (valid['asym_up'].values == 1) | (valid['asym_down'].values == 1)
    if asym_mask.sum() > 0:
        shift_on_signal = np.abs(pred_b[asym_mask] - pred_a[asym_mask]).mean()
        correct_dir = (np.sign(pred_b[asym_mask]) == np.sign(y[asym_mask])).mean()
        correct_dir_a = (np.sign(pred_a[asym_mask]) == np.sign(y[asym_mask])).mean()

        print(f"  {name}: On asymmetric-move ticks (N={asym_mask.sum()}):")
        print(f"    Average FV shift: {shift_on_signal:.4f}")
        print(f"    Direction accuracy: A={correct_dir_a*100:.1f}%, B={correct_dir*100:.1f}%")

    # Coefficients
    print(f"  {name}: Model B coefficients:")
    for feat, coef in zip(feats_b, reg_b.coef_):
        print(f"    {feat}: {coef:.4f}")

# ===========================================================================
# FINAL: Correlation between candidate signals and existing s36 signals
# ===========================================================================
print("\n\n" + "="*80)
print("CORRELATION MATRIX: Are new signals redundant with s36?")
print("="*80)

for name, data in [("IS", is_feat), ("OOS", oos_feat)]:
    all_signals = ['lag1', 'mp_dev', 'obi', 'pct50', 'asym_up', 'asym_down', 'ba_asymmetry', 'narrow_spread']
    valid = data[all_signals + ['dmid']].dropna()

    print(f"\n  {name}: Correlations with dmid:")
    for sig in all_signals:
        r = valid[sig].corr(valid['dmid'])
        print(f"    {sig:<20}: r = {r:>7.4f}")

    # Cross-correlations of new vs old
    print(f"\n  {name}: Cross-correlations (new vs existing):")
    new_sigs = ['pct50', 'asym_up', 'asym_down', 'ba_asymmetry']
    old_sigs = ['lag1', 'mp_dev', 'obi']
    for new in new_sigs:
        corrs = [f"{valid[new].corr(valid[old]):>6.3f}" for old in old_sigs]
        print(f"    {new:<20} vs lag1/mp_dev/obi: {', '.join(corrs)}")

print("\n\nDone.")
