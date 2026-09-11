"""
DEEP DIVE: Decompose findings into what's genuinely new vs lag-1 AC repackaging.

Key question: Are the "significant" triplets just saying "after big_down, bounce up"?
If so, they add ZERO information beyond lag-1 AC.

Also: deep-dive on the TRULY interesting findings (bid-ask moves, spread states, range).
"""

import pandas as pd
import numpy as np
from scipy import stats
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
    tom['dmid'] = tom['mid'].diff().shift(-1)  # forward-looking: mid[t+1]-mid[t]
    tom['dmid_actual'] = tom['mid'].diff()  # backward-looking: mid[t]-mid[t-1]
    tom['bid_vol_1'] = tom['bid_volume_1']
    tom['ask_vol_1'] = tom['ask_volume_1']
    tom['l1_total_vol'] = tom['bid_vol_1'] + tom['ask_vol_1']
    tom['bid_delta'] = tom['best_bid'].diff()
    tom['ask_delta'] = tom['best_ask'].diff()

    def cat_dmid(x):
        if pd.isna(x): return None
        if x <= -2: return 'big_down'
        elif x <= -0.5: return 'small_down'
        elif x < 0.5: return 'zero'
        elif x < 2: return 'small_up'
        else: return 'big_up'
    tom['dmid_cat'] = tom['dmid_actual'].apply(cat_dmid)
    return tom

day0 = load_tomatoes('0')
daym1 = load_tomatoes('-1')
daym2 = load_tomatoes('-2')
is_data = pd.concat([daym1, daym2], ignore_index=True)

# ==========================================================================
# DEEP DIVE 1: Are triplets just repackaged lag-1 AC?
# ==========================================================================
print("="*80)
print("DEEP DIVE 1: TRIPLET DECOMPOSITION — What's truly new?")
print("="*80)

# The unconditional prediction after seeing dmid_cat[t] = X:
print("\n  Unconditional E[dmid[t+1]] given dmid_cat[t]:")
for name, data in [("IS", is_data), ("OOS", day0)]:
    print(f"\n  {name}:")
    for cat in ['big_down', 'small_down', 'zero', 'small_up', 'big_up']:
        mask = data['dmid_cat'] == cat
        subset = data.loc[mask, 'dmid'].dropna()
        if len(subset) > 0:
            se = subset.std() / np.sqrt(len(subset))
            print(f"    {cat:>12}: E[dmid]={subset.mean():.4f} (N={len(subset)}, t={subset.mean()/se:.2f})")

# KEY TEST: After conditioning on dmid_cat[t+2] = big_down, does knowing
# dmid_cat[t] and dmid_cat[t+1] add ANY predictive power for dmid[t+3]?
print("\n\n  CRITICAL TEST: Conditioning on dmid_cat[t+2]")
print("  If triplet (A, B, big_down) -> E[dmid[t+3]] ≈ same for ALL A, B,")
print("  then triplets are just repackaging 'after big_down, bounce up'.")

for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()
    data['cat_2'] = data['dmid_cat'].shift(-2)
    data['dmid_next3'] = data['dmid'].shift(-2)  # dmid[t+3]

    print(f"\n  {name}: E[dmid[t+3]] | dmid_cat[t+2] = big_down (unconditional on first 2 lags):")
    mask = data['cat_2'] == 'big_down'
    subset = data.loc[mask, 'dmid_next3'].dropna()
    if len(subset) > 0:
        se = subset.std() / np.sqrt(len(subset))
        print(f"    UNCONDITIONAL: E={subset.mean():.4f} (N={len(subset)}, t={subset.mean()/se:.2f})")

    print(f"\n  {name}: E[dmid[t+3]] | dmid_cat[t+2] = big_up:")
    mask = data['cat_2'] == 'big_up'
    subset = data.loc[mask, 'dmid_next3'].dropna()
    if len(subset) > 0:
        se = subset.std() / np.sqrt(len(subset))
        print(f"    UNCONDITIONAL: E={subset.mean():.4f} (N={len(subset)}, t={subset.mean()/se:.2f})")

    # Now break down by first two lags
    cats = ['big_down', 'small_down', 'zero', 'small_up', 'big_up']
    data['cat_0'] = data['dmid_cat']
    data['cat_1'] = data['dmid_cat'].shift(-1)

    for terminal in ['big_down', 'big_up']:
        print(f"\n  {name}: Variation in E[dmid[t+3]] | cat[t+2]={terminal}, by first two lags:")
        all_means = []
        for c0 in cats:
            for c1 in cats:
                mask = (data['cat_0'] == c0) & (data['cat_1'] == c1) & (data['cat_2'] == terminal)
                subset = data.loc[mask, 'dmid_next3'].dropna()
                if len(subset) >= 10:
                    all_means.append(subset.mean())
                    print(f"    ({c0:>10}, {c1:>10}, {terminal:>9}): E={subset.mean():.3f} (N={len(subset)})")
        if all_means:
            print(f"    RANGE of means: [{min(all_means):.3f}, {max(all_means):.3f}], spread={max(all_means)-min(all_means):.3f}")

# ==========================================================================
# DEEP DIVE 2: Spread transitions — are they the REAL signal?
# ==========================================================================
print("\n\n" + "="*80)
print("DEEP DIVE 2: SPREAD TRANSITIONS — The narrow-spread signal")
print("="*80)

# Narrow spread (5-9) is rare (7.2%) and ALWAYS follows a big mid move.
# Does the spread transition encode the DIRECTION of the preceding move?
print("\n  When spread narrows from 13/14 to 5/6/7/8/9, what was the preceding dmid?")

for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()
    data['spread_prev'] = data['spread'].shift(1)
    narrow_mask = (data['spread'] <= 9) & (data['spread_prev'] >= 13)

    print(f"\n  {name}: Spread transition wide->narrow events (N={narrow_mask.sum()}):")
    for s in sorted(data.loc[narrow_mask, 'spread'].unique()):
        sub_mask = narrow_mask & (data['spread'] == s)
        dmid_at = data.loc[sub_mask, 'dmid_actual']
        print(f"    To spread={s}: N={sub_mask.sum()}, E[dmid_at_transition]={dmid_at.mean():.2f}, dmid values={dmid_at.value_counts().sort_index().to_dict()}")

    # After the narrow spread, what's E[dmid]?
    print(f"\n  {name}: E[dmid] AFTER narrow spread event:")
    dmid_after = data.loc[narrow_mask, 'dmid'].dropna()
    if len(dmid_after) > 0:
        # Split by direction of the narrow-spread move
        up_at = narrow_mask & (data['dmid_actual'] > 0)
        down_at = narrow_mask & (data['dmid_actual'] < 0)

        for label, m in [("After UP narrow", up_at), ("After DOWN narrow", down_at)]:
            subset = data.loc[m, 'dmid'].dropna()
            if len(subset) > 0:
                se = subset.std() / np.sqrt(len(subset))
                t = subset.mean() / se if se > 0 else 0
                print(f"    {label}: E[dmid]={subset.mean():.3f} (N={len(subset)}, t={t:.2f})")

# Does the SPECIFIC narrow spread value (5 vs 7 vs 8) encode direction?
print("\n  Narrow spread value as direction signal:")
for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()
    data['spread_prev'] = data['spread'].shift(1)

    print(f"\n  {name}:")
    for s in [5, 6, 7, 8, 9]:
        mask = (data['spread'] == s) & (data['spread_prev'] >= 13)
        if mask.sum() > 0:
            dmid_at = data.loc[mask, 'dmid_actual']
            up_pct = (dmid_at > 0).mean() * 100
            dmid_next = data.loc[mask, 'dmid'].dropna()
            if len(dmid_next) > 0:
                se = dmid_next.std() / np.sqrt(len(dmid_next))
                t = dmid_next.mean() / se if se > 0 else 0
                print(f"    Spread={s}: N={mask.sum()}, %UP={up_pct:.0f}%, E[dmid_after]={dmid_next.mean():.3f} (t={t:.2f})")

# The key 13->5 signal: IS it just "after big move, bounce" or is spread=5 special?
print("\n  13->5 vs 13->7: Is spread=5 more predictive than spread=7?")
for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()
    data['spread_prev'] = data['spread'].shift(1)

    for s in [5, 7, 8]:
        mask = (data['spread'] == s) & (data['spread_prev'] == 13)
        dmid_at = data.loc[mask, 'dmid_actual'].dropna()
        dmid_after = data.loc[mask, 'dmid'].dropna()
        if len(dmid_after) > 0 and len(dmid_at) > 0:
            se = dmid_after.std() / np.sqrt(len(dmid_after))
            t = dmid_after.mean() / se if se > 0 else 0
            print(f"    {name}: 13->{s}: N={mask.sum()}, avg_move_at={dmid_at.mean():.2f}, E[dmid_after]={dmid_after.mean():.3f} (t={t:.2f})")

# ==========================================================================
# DEEP DIVE 3: Bid-Ask Move Sequences — The REAL incremental signal
# ==========================================================================
print("\n\n" + "="*80)
print("DEEP DIVE 3: BID-ASK MOVE SEQUENCES — Residual after lag-1 AC")
print("="*80)

# The 4 significant move sequences suggest information in the STRUCTURE of moves
# beyond just mid-price direction. Let's test residual prediction.

def classify_move(bid_d, ask_d):
    if pd.isna(bid_d) or pd.isna(ask_d): return None
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

for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()
    data['move_type'] = [classify_move(b, a) for b, a in zip(data['bid_delta'], data['ask_delta'])]
    data['move_type_next'] = data['move_type'].shift(-1)

    # After no_move -> bid_up_only, the LAG-1 AC prediction would be:
    # dmid[t] at the bid_up_only tick is positive => predict reversion (negative)
    # The signal IS negative (E=-0.493 OOS). Is it just lag-1 AC?

    # Compute: conditional on move_type[t+1] = bid_up_only, what is unconditional E[dmid[t+2]]?
    print(f"\n  {name}:")
    for mt in ['bid_up_only', 'ask_down_only']:
        mask_mt = data['move_type'] == mt
        sub = data.loc[mask_mt]
        dmid_at_mt = sub['dmid_actual'].dropna()  # the mid-price move at this tick
        dmid_after_mt = sub['dmid'].dropna()  # next tick's move

        if len(dmid_after_mt) > 0:
            se = dmid_after_mt.std() / np.sqrt(len(dmid_after_mt))
            t = dmid_after_mt.mean() / se if se > 0 else 0
            print(f"    UNCONDITIONAL | move={mt}: E[dmid]={dmid_after_mt.mean():.4f} (t={t:.2f}, N={len(dmid_after_mt)})")
            print(f"      Mean dmid_at: {dmid_at_mt.mean():.4f}")

    # Now: does the PRECEDING tick's move type add information?
    for seq in [('no_move', 'bid_up_only'), ('no_move', 'ask_down_only'),
                ('ask_up_only', 'bid_up_only'), ('bid_down_only', 'bid_up_only')]:
        m0, m1 = seq
        mask = (data['move_type'] == m0) & (data['move_type_next'] == m1)
        dmid_after_seq = data.loc[mask, 'dmid'].shift(-1)  # dmid after the second tick

        # Compare to just conditioning on m1 alone
        mask_m1 = data['move_type'] == m1
        dmid_after_m1 = data.loc[mask_m1, 'dmid'].dropna()

        # Residual after subtracting unconditional m1 prediction
        subset = data.loc[mask, 'dmid'].dropna()
        if len(subset) > 0 and len(dmid_after_m1) > 0:
            residual = subset.mean() - dmid_after_m1.mean()
            se_residual = subset.std() / np.sqrt(len(subset))
            print(f"\n    Sequence {seq}:")
            print(f"      E[dmid|seq]={subset.mean():.4f} (N={len(subset)})")
            print(f"      E[dmid|just {m1}]={dmid_after_m1.mean():.4f} (N={len(dmid_after_m1)})")
            print(f"      Residual (incremental)={residual:.4f}")

# ==========================================================================
# DEEP DIVE 4: Position-in-Range — BEYOND lag-1 AC
# ==========================================================================
print("\n\n" + "="*80)
print("DEEP DIVE 4: RANGE POSITION — Residual after controlling for dmid[t]")
print("="*80)

# The range effect is STRONG (t=5+ OOS). But is it just capturing that after
# a big move to the top, lag-1 AC predicts reversion?

for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()

    for window in [50, 100]:
        roll_min = data['mid'].rolling(window, min_periods=window).min()
        roll_max = data['mid'].rolling(window, min_periods=window).max()
        pct = (data['mid'] - roll_min) / (roll_max - roll_min)

        # Double-sort: range position AND dmid_actual
        print(f"\n  {name}, window={window}: E[dmid] by range percentile AND dmid_actual:")
        print(f"    {'':>15} {'dmid<=-2':>10} {'-2<dmid<0':>10} {'dmid=0':>10} {'0<dmid<2':>10} {'dmid>=2':>10}")

        for lo, hi, label in [(0, 0.1, "Bottom 10%"), (0.3, 0.7, "Mid 30-70%"), (0.9, 1.01, "Top 90-100%")]:
            row = f"    {label:>15}"
            for dlo, dhi, _ in [(-99, -2, "big_down"), (-2, -0.01, "small_down"), (-0.01, 0.01, "zero"),
                                (0.01, 2, "small_up"), (2, 99, "big_up")]:
                mask = (pct >= lo) & (pct < hi) & (data['dmid_actual'] > dlo) & (data['dmid_actual'] <= dhi)
                subset = data.loc[mask, 'dmid'].dropna()
                if len(subset) >= 10:
                    row += f" {subset.mean():>10.3f}"
                else:
                    row += f" {'N<10':>10}"
            print(row)

    # REGRESSION: dmid[t+1] ~ dmid[t] + range_percentile
    from sklearn.linear_model import LinearRegression

    data_copy = data.copy()
    roll_min = data_copy['mid'].rolling(50, min_periods=50).min()
    roll_max = data_copy['mid'].rolling(50, min_periods=50).max()
    data_copy['pct50'] = (data_copy['mid'] - roll_min) / (roll_max - roll_min)

    valid = data_copy[['dmid_actual', 'pct50', 'dmid']].dropna()
    if len(valid) > 50:
        X1 = valid[['dmid_actual']].values
        X2 = valid[['dmid_actual', 'pct50']].values
        y = valid['dmid'].values

        reg1 = LinearRegression().fit(X1, y)
        reg2 = LinearRegression().fit(X2, y)

        r2_1 = reg1.score(X1, y)
        r2_2 = reg2.score(X2, y)

        print(f"\n  {name} regression: R2(dmid_lag1 only)={r2_1:.6f}, R2(dmid_lag1 + pct50)={r2_2:.6f}")
        print(f"    Increment: {r2_2-r2_1:.6f}")
        print(f"    Coefficients: dmid_lag1={reg2.coef_[0]:.4f}, pct50={reg2.coef_[1]:.4f}, intercept={reg2.intercept_:.4f}")

# ==========================================================================
# DEEP DIVE 5: The ONLY signal that might be new — spread asymmetry
# ==========================================================================
print("\n\n" + "="*80)
print("DEEP DIVE 5: SPREAD VALUE AS DIRECTIONAL INDICATOR")
print("="*80)

# Spread=5 after 13 means UP move (+4 on avg). Spread=8 after 13 means DOWN.
# This is deterministic: spread value ENCODES the direction of the big move.
# The "signal" is: after a big move (any direction), the next tick reverts.
# This is JUST lag-1 AC.

# BUT: does the MAGNITUDE of the spread change add info beyond dmid?
for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()
    data['spread_change'] = data['spread'].diff()

    # When spread narrows (change < 0), is the magnitude informative?
    narrow = data['spread_change'] < -3  # big narrowing
    if narrow.sum() > 0:
        print(f"\n  {name}: Big spread narrowing (change < -3, N={narrow.sum()}):")
        for col in ['dmid_actual', 'dmid']:
            subset = data.loc[narrow, col].dropna()
            if len(subset) > 0:
                se = subset.std() / np.sqrt(len(subset))
                t = subset.mean() / se if se > 0 else 0
                print(f"    E[{col}]={subset.mean():.3f} (t={t:.2f})")

    # When spread widens (change > 3), same question
    widen = data['spread_change'] > 3
    if widen.sum() > 0:
        print(f"\n  {name}: Big spread widening (change > 3, N={widen.sum()}):")
        for col in ['dmid_actual', 'dmid']:
            subset = data.loc[widen, col].dropna()
            if len(subset) > 0:
                se = subset.std() / np.sqrt(len(subset))
                t = subset.mean() / se if se > 0 else 0
                print(f"    E[{col}]={subset.mean():.3f} (t={t:.2f})")

# ==========================================================================
# DEEP DIVE 6: The REAL test — can any finding survive double conditioning?
# ==========================================================================
print("\n\n" + "="*80)
print("DEEP DIVE 6: DOUBLE-CONDITIONED TESTS (beyond lag-1 AC + microprice)")
print("="*80)

# Test: after controlling for dmid[t] (lag-1 AC), does ANY additional feature
# predict dmid[t+1]?

for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()
    data['move_type'] = [classify_move(b, a) for b, a in zip(data['bid_delta'], data['ask_delta'])]

    # Microprice
    data['microprice'] = (data['best_bid'] * data['ask_vol_1'] + data['best_ask'] * data['bid_vol_1']) / (data['bid_vol_1'] + data['ask_vol_1'])
    data['mp_dev'] = data['microprice'] - data['mid']

    roll_min = data['mid'].rolling(50, min_periods=50).min()
    roll_max = data['mid'].rolling(50, min_periods=50).max()
    data['pct50'] = (data['mid'] - roll_min) / (roll_max - roll_min)

    # OBI
    data['bid_vol_2'] = data['bid_volume_2'].fillna(0)
    data['ask_vol_2'] = data['ask_volume_2'].fillna(0)
    data['obi'] = ((data['bid_vol_1'] + data['bid_vol_2']) - (data['ask_vol_1'] + data['ask_vol_2'])) / \
                  ((data['bid_vol_1'] + data['bid_vol_2']) + (data['ask_vol_1'] + data['ask_vol_2']))

    # Is bid_up_only vs both_up informative AFTER controlling for dmid?
    # Both have positive dmid_actual, but bid_up_only = spread narrowed
    print(f"\n  {name}: Conditioning on dmid_actual ∈ [0.5, 1.5] (small_up):")
    small_up_mask = (data['dmid_actual'] >= 0.5) & (data['dmid_actual'] < 2.0)

    for mt in ['bid_up_only', 'ask_down_only', 'both_up', 'both_down', 'no_move']:
        mask = small_up_mask & (data['move_type'] == mt)
        subset = data.loc[mask, 'dmid'].dropna()
        if len(subset) >= 10:
            se = subset.std() / np.sqrt(len(subset))
            t = subset.mean() / se if se > 0 else 0
            print(f"    move={mt:>15}: E[dmid]={subset.mean():.4f} (N={len(subset)}, t={t:.2f})")

    print(f"\n  {name}: Conditioning on dmid_actual ∈ [-1.5, -0.5] (small_down):")
    small_down_mask = (data['dmid_actual'] <= -0.5) & (data['dmid_actual'] > -2.0)

    for mt in ['bid_up_only', 'ask_down_only', 'both_up', 'both_down', 'no_move', 'bid_down_only', 'ask_up_only']:
        mask = small_down_mask & (data['move_type'] == mt)
        subset = data.loc[mask, 'dmid'].dropna()
        if len(subset) >= 10:
            se = subset.std() / np.sqrt(len(subset))
            t = subset.mean() / se if se > 0 else 0
            print(f"    move={mt:>15}: E[dmid]={subset.mean():.4f} (N={len(subset)}, t={t:.2f})")

    # MULTI-FEATURE REGRESSION: everything vs lag-1 only
    from sklearn.linear_model import LinearRegression

    features = ['dmid_actual', 'mp_dev', 'pct50', 'obi']
    valid = data[features + ['dmid']].dropna()

    if len(valid) > 50:
        X_base = valid[['dmid_actual']].values
        X_full = valid[features].values
        y = valid['dmid'].values

        reg_base = LinearRegression().fit(X_base, y)
        reg_full = LinearRegression().fit(X_full, y)

        r2_base = reg_base.score(X_base, y)
        r2_full = reg_full.score(X_full, y)

        print(f"\n  {name} full regression:")
        print(f"    R2(dmid_lag1 only) = {r2_base:.6f}")
        print(f"    R2(dmid_lag1 + mp_dev + pct50 + obi) = {r2_full:.6f}")
        print(f"    Increment from extra features: {r2_full-r2_base:.6f}")
        for feat, coef in zip(features, reg_full.coef_):
            print(f"      {feat}: coef={coef:.4f}")
        print(f"      intercept: {reg_full.intercept_:.4f}")

# ==========================================================================
# DEEP DIVE 7: Net new PnL simulation for the BEST candidate signals
# ==========================================================================
print("\n\n" + "="*80)
print("DEEP DIVE 7: SIMULATED PnL FOR CANDIDATE SIGNALS")
print("="*80)

# Simulate: on every tick, compute FV adjustment from each signal.
# PnL = sum over fills of (FV_adjusted - execution_price)

# Signal 1: Range position (pct50)
# Signal 2: OBI FV shift
# Signal 3: Move-type sequence

for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()

    # Range signal: when at extreme, shift FV toward reversion
    roll_min = data['mid'].rolling(50, min_periods=50).min()
    roll_max = data['mid'].rolling(50, min_periods=50).max()
    pct50 = (data['mid'] - roll_min) / (roll_max - roll_min)

    # Signal: FV_shift = -k * (pct50 - 0.5) where k is chosen for ~0.5 tick max shift
    k_range = 1.0  # shift = -0.5 at extreme, 0 at median
    range_signal = -k_range * (pct50 - 0.5)
    range_signal = range_signal.fillna(0)

    # How well does this predict next dmid?
    valid_idx = (~pct50.isna()) & (~data['dmid'].isna())
    if valid_idx.sum() > 0:
        corr = range_signal[valid_idx].corr(data.loc[valid_idx, 'dmid'])
        # IC * sqrt(N) * avg_edge
        avg_shift = range_signal[valid_idx].abs().mean()
        predicted_pnl = corr * avg_shift * valid_idx.sum()
        print(f"\n  {name}: Range signal (k={k_range}): IC={corr:.4f}, avg|shift|={avg_shift:.3f}, ticks={valid_idx.sum()}, predicted edge={predicted_pnl:.1f}")

    # Compare to dmid_lag1 prediction
    valid = data[['dmid_actual', 'dmid']].dropna()
    if len(valid) > 0:
        corr_lag1 = valid['dmid_actual'].corr(valid['dmid'])
        print(f"  {name}: Lag-1 AC: IC={corr_lag1:.4f}")

    # Incremental IC (residual after lag-1)
    if valid_idx.sum() > 50:
        from sklearn.linear_model import LinearRegression
        # Need to also filter NaNs from dmid_actual
        both_valid = valid_idx & (~data['dmid_actual'].isna())
        X_lag = data.loc[both_valid, 'dmid_actual'].values.reshape(-1, 1)
        y = data.loc[both_valid, 'dmid'].values
        residual = y - LinearRegression().fit(X_lag, y).predict(X_lag)
        incremental_corr = np.corrcoef(range_signal[both_valid].values, residual)[0, 1]
        print(f"  {name}: Range signal INCREMENTAL IC (after lag-1 residual) = {incremental_corr:.4f}")

# ==========================================================================
# DEEP DIVE 8: The "no_move -> bid_up_only" signal decomposed
# ==========================================================================
print("\n\n" + "="*80)
print("DEEP DIVE 8: WHY no_move -> bid_up_only PREDICTS NEGATIVE dmid")
print("="*80)

# Hypothesis: bid_up_only means bid moved up but ask didn't. This creates a
# narrow spread, which reverts. The "no_move" preceding it means the market
# was quiet before the bid moved. This is the MM bot updating ASYMMETRICALLY.
# The next tick, the ask should catch up (both_up) or the bid should revert (bid_down_only).

for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()
    data['move_type'] = [classify_move(b, a) for b, a in zip(data['bid_delta'], data['ask_delta'])]
    data['move_type_next'] = data['move_type'].shift(-1)

    # After no_move -> bid_up_only, what happens next?
    mask = (data['move_type'] == 'no_move') & (data['move_type_next'] == 'bid_up_only')

    # What's the move type TWO ticks later?
    data['move_type_2'] = data['move_type'].shift(-2)
    subset = data.loc[mask, 'move_type_2'].value_counts()
    print(f"\n  {name}: What move type follows no_move -> bid_up_only?")
    total = subset.sum()
    for mt, count in subset.items():
        pct = count / total * 100
        print(f"    {mt:>20}: {count:>5d} ({pct:.1f}%)")

    # After no_move -> bid_up_only, what's the spread?
    spread_at = data.loc[mask].index + 1  # tick after bid_up_only
    valid_spread_at = [i for i in spread_at if i < len(data)]
    if valid_spread_at:
        spreads_after = data.loc[valid_spread_at, 'spread']
        print(f"    Spread distribution after bid_up_only: {spreads_after.value_counts().sort_index().to_dict()}")

    # Similarly for no_move -> ask_down_only
    mask2 = (data['move_type'] == 'no_move') & (data['move_type_next'] == 'ask_down_only')
    subset2 = data.loc[mask2, 'move_type_2'].value_counts()
    print(f"\n  {name}: What move type follows no_move -> ask_down_only?")
    total2 = subset2.sum()
    for mt, count in subset2.items():
        pct = count / total2 * 100
        print(f"    {mt:>20}: {count:>5d} ({pct:.1f}%)")

# ==========================================================================
# DEEP DIVE 9: How much of the range signal is already in the 4-lag regression?
# ==========================================================================
print("\n\n" + "="*80)
print("DEEP DIVE 9: RANGE vs 4-LAG REGRESSION — Overlap check")
print("="*80)

for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()

    # 4-lag features (matching s36_medallion)
    data['lag1'] = data['dmid_actual']
    data['lag2'] = data['dmid_actual'].shift(1)
    data['lag3'] = data['dmid_actual'].shift(2)
    data['lag4'] = data['dmid_actual'].shift(3)

    roll_min = data['mid'].rolling(50, min_periods=50).min()
    roll_max = data['mid'].rolling(50, min_periods=50).max()
    data['pct50'] = (data['mid'] - roll_min) / (roll_max - roll_min)

    # Microprice
    data['microprice'] = (data['best_bid'] * data['ask_vol_1'] + data['best_ask'] * data['bid_vol_1']) / (data['bid_vol_1'] + data['ask_vol_1'])
    data['mp_dev'] = data['microprice'] - data['mid']

    from sklearn.linear_model import LinearRegression

    # Model 1: 4-lag regression (what s36 uses)
    feat_4lag = ['lag1', 'lag2', 'lag3', 'lag4']
    valid = data[feat_4lag + ['pct50', 'mp_dev', 'dmid']].dropna()

    if len(valid) > 50:
        X_4lag = valid[feat_4lag].values
        X_4lag_range = valid[feat_4lag + ['pct50']].values
        X_4lag_mp = valid[feat_4lag + ['mp_dev']].values
        X_all = valid[feat_4lag + ['pct50', 'mp_dev']].values
        y = valid['dmid'].values

        r2_4lag = LinearRegression().fit(X_4lag, y).score(X_4lag, y)
        r2_4lag_range = LinearRegression().fit(X_4lag_range, y).score(X_4lag_range, y)
        r2_4lag_mp = LinearRegression().fit(X_4lag_mp, y).score(X_4lag_mp, y)
        r2_all = LinearRegression().fit(X_all, y).score(X_all, y)

        reg_range = LinearRegression().fit(X_4lag_range, y)
        reg_all = LinearRegression().fit(X_all, y)

        print(f"\n  {name}:")
        print(f"    R2(4-lag)              = {r2_4lag:.6f}")
        print(f"    R2(4-lag + pct50)      = {r2_4lag_range:.6f}  (+{r2_4lag_range-r2_4lag:.6f})")
        print(f"    R2(4-lag + mp_dev)     = {r2_4lag_mp:.6f}  (+{r2_4lag_mp-r2_4lag:.6f})")
        print(f"    R2(4-lag + pct50 + mp) = {r2_all:.6f}  (+{r2_all-r2_4lag:.6f})")
        print(f"    pct50 coefficient: {reg_range.coef_[-1]:.4f}")
        print(f"    All coefficients: {dict(zip(feat_4lag + ['pct50', 'mp_dev'], reg_all.coef_))}")

print("\n\nDone with deep dives.")
