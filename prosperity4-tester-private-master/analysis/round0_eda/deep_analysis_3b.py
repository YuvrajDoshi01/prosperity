#!/usr/bin/env python3
"""
Deep analysis part 3b: Narrow spread sequences and multi-tick predictability.
"""

import pandas as pd
import numpy as np
from collections import Counter
import warnings
warnings.filterwarnings('ignore')

BASE = "prosperity4bt/resources/round0/"

days = {}
for d in [-2, -1, 0]:
    days[d] = pd.read_csv(f"{BASE}prices_round_0_day_{d}.csv", sep=";")

trades = {}
for d in [-2, -1, 0]:
    trades[d] = pd.read_csv(f"{BASE}trades_round_0_day_{d}.csv", sep=";")

def get_product(day_df, product):
    return day_df[day_df['product'] == product].copy().reset_index(drop=True)


# ============================================================================
# PATTERN I: NARROW SPREAD EPISODE SEQUENCES
# ============================================================================
print("=" * 80)
print("PATTERN I: NARROW SPREAD TRANSITION MICROSTRUCTURE")
print("=" * 80)

for d in [-2, -1, 0]:
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['narrow'] = (df['spread'] <= 9).astype(bool)

    # Find transitions
    prev_narrow = df['narrow'].shift(1).fillna(False).astype(bool)
    next_narrow = df['narrow'].shift(-1).fillna(False).astype(bool)

    entry = df[~prev_narrow & df['narrow']].copy()
    exit_narrow = df[prev_narrow & ~df['narrow']].copy()

    print(f"\n  Day {d}:")
    print(f"  Wide->Narrow transitions: {len(entry)}")
    print(f"  Narrow->Wide transitions: {len(exit_narrow)}")

    if len(entry) > 0:
        print(f"\n  AT ENTRY (wide->narrow):")
        print(f"    mid_change at entry: {entry['mid_change'].mean():+.3f} (std={entry['mid_change'].std():.3f})")
        print(f"    spread values at entry: {dict(entry['spread'].value_counts().sort_index())}")

    if len(exit_narrow) > 0:
        print(f"\n  AT EXIT (narrow->wide):")
        print(f"    mid_change at exit: {exit_narrow['mid_change'].mean():+.3f} (std={exit_narrow['mid_change'].std():.3f})")
        print(f"    spread values at exit: {dict(exit_narrow['spread'].value_counts().sort_index())}")

    # Collect narrow spread episode sequences
    narrow_episodes = []
    in_episode = False
    episode = []
    for i in range(len(df)):
        if df.iloc[i]['narrow']:
            if not in_episode:
                in_episode = True
                episode = []
            episode.append(int(df.iloc[i]['spread']))
        else:
            if in_episode:
                narrow_episodes.append(tuple(episode))
                in_episode = False
                episode = []

    if narrow_episodes:
        print(f"\n  Narrow spread episode sequences (top 30):")
        ep_counts = Counter(narrow_episodes)
        for ep, cnt in ep_counts.most_common(30):
            print(f"    {ep}: {cnt} times")

        # Episode length distribution
        ep_lengths = [len(ep) for ep in narrow_episodes]
        print(f"\n  Episode length: mean={np.mean(ep_lengths):.1f}, max={max(ep_lengths)}")
        for length in range(1, max(ep_lengths)+1):
            n = sum(1 for l in ep_lengths if l == length)
            if n > 0:
                print(f"    length={length}: {n} episodes ({n/len(ep_lengths)*100:.1f}%)")

        # CRITICAL: Do episodes ALWAYS follow the same sequence pattern?
        # Check: after spread=5, what's the next narrow spread value?
        for sp_from in [5, 6, 7, 8]:
            transitions_from = []
            for ep in narrow_episodes:
                for i in range(len(ep)-1):
                    if ep[i] == sp_from:
                        transitions_from.append(ep[i+1])
            if transitions_from:
                print(f"\n    After spread={sp_from} within episode: {dict(Counter(transitions_from).most_common())}")


# ============================================================================
# PATTERN J: MULTI-TICK RETURN PREDICTABILITY
# ============================================================================
print("\n\n" + "=" * 80)
print("PATTERN J: MULTI-TICK RETURN PREDICTABILITY FROM BOOK FEATURES")
print("=" * 80)

for d in [-2, -1, 0]:
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['obi'] = (df['bid_volume_1'] - df['ask_volume_1']) / (df['bid_volume_1'] + df['ask_volume_1'])
    df['l2_l1_ratio'] = (df['bid_volume_2'].fillna(0) + df['ask_volume_2'].fillna(0)) / \
                          (df['bid_volume_1'] + df['ask_volume_1']).replace(0, np.nan)
    df['microprice'] = (df['bid_price_1'] * df['ask_volume_1'] + df['ask_price_1'] * df['bid_volume_1']) / \
                       (df['bid_volume_1'] + df['ask_volume_1'])
    df['microprice_dev'] = df['microprice'] - df['mid_price']

    for h in [1, 2, 3, 5, 10]:
        df[f'ret_{h}'] = df['mid_price'].diff(h).shift(-h)

    print(f"\n  Day {d}:")
    features = ['microprice_dev', 'obi', 'l2_l1_ratio', 'mid_change']
    for feat in features:
        corrs = []
        for h in [1, 2, 3, 5, 10]:
            corr = df[feat].corr(df[f'ret_{h}'])
            corrs.append(f"r{h}={corr:+.4f}")
        print(f"    {feat:>20s}: {', '.join(corrs)}")


# ============================================================================
# PATTERN K: VOLUME CHANGE DYNAMICS
# Does bid_volume change BEFORE mid_price moves?
# ============================================================================
print("\n\n" + "=" * 80)
print("PATTERN K: VOLUME CHANGES AS LEADING INDICATOR")
print("=" * 80)

for d in [-2, -1, 0]:
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['bid_vol_change'] = df['bid_volume_1'].diff()
    df['ask_vol_change'] = df['ask_volume_1'].diff()

    # Net volume change: positive = more on bid side (bullish)
    df['net_vol_change'] = df['bid_vol_change'] - df['ask_vol_change']

    # Does volume change LEAD mid change?
    print(f"\n  Day {d}:")
    for lag in [0, 1, 2, 3]:
        corr = df['net_vol_change'].corr(df['mid_change'].shift(-lag))
        print(f"    net_vol_change vs mid_change(t+{lag}): r={corr:+.4f}")

    # Does a BIG volume change predict anything?
    big_bid_add = df[df['bid_vol_change'] >= 5]
    big_ask_add = df[df['ask_vol_change'] >= 5]
    big_bid_drop = df[df['bid_vol_change'] <= -5]
    big_ask_drop = df[df['ask_vol_change'] <= -5]

    for label, sub in [("Big bid add", big_bid_add), ("Big ask add", big_ask_add),
                        ("Big bid drop", big_bid_drop), ("Big ask drop", big_ask_drop)]:
        if len(sub) > 0:
            next_change = sub['mid_change'].shift(-1).mean()
            print(f"    {label} (n={len(sub)}): next_mid_change={next_change:+.4f}")


# ============================================================================
# PATTERN L: EMERALDS MID MOVEMENT AND TOMATOES CORRELATION
# Extremely fine-grained: does EM mid move BEFORE TOM mid?
# ============================================================================
print("\n\n" + "=" * 80)
print("PATTERN L: EMERALDS-TOMATOES LEAD-LAG AT TICK LEVEL")
print("=" * 80)

for d in [-2, -1, 0]:
    tom = get_product(days[d], 'TOMATOES')
    em = get_product(days[d], 'EMERALDS')

    merged = pd.merge(tom[['timestamp', 'mid_price']].rename(columns={'mid_price': 'tom_mid'}),
                       em[['timestamp', 'mid_price']].rename(columns={'mid_price': 'em_mid'}),
                       on='timestamp')
    merged['tom_change'] = merged['tom_mid'].diff()
    merged['em_change'] = merged['em_mid'].diff()

    print(f"\n  Day {d}:")
    for lag in range(-5, 6):
        if lag == 0:
            corr = merged['em_change'].corr(merged['tom_change'])
        elif lag > 0:
            corr = merged['em_change'].corr(merged['tom_change'].shift(-lag))
        else:
            corr = merged['em_change'].corr(merged['tom_change'].shift(lag))
        if abs(corr) > 0.005:
            print(f"    em_change(t) vs tom_change(t{lag:+d}): r={corr:+.4f}")

    # What about EM spread narrowing leading TOM mid change?
    merged2 = pd.merge(tom[['timestamp', 'mid_price']].rename(columns={'mid_price': 'tom_mid'}),
                        em[['timestamp', 'ask_price_1', 'bid_price_1']],
                        on='timestamp')
    merged2['em_spread'] = merged2['ask_price_1'] - merged2['bid_price_1']
    merged2['tom_change_1'] = merged2['tom_mid'].diff().shift(-1)
    merged2['tom_change_3'] = merged2['tom_mid'].diff(3).shift(-3)
    merged2['tom_change_5'] = merged2['tom_mid'].diff(5).shift(-5)

    em_narrow = merged2[merged2['em_spread'] == 8]
    em_wide = merged2[merged2['em_spread'] == 16]

    print(f"\n  When EM spread=8 (n={len(em_narrow)}):")
    if len(em_narrow) > 0:
        for h in [1, 3, 5]:
            nc = em_narrow[f'tom_change_{h}'].mean()
            print(f"    TOM {h}-tick return: {nc:+.4f}")

    print(f"  When EM spread=16 (n={len(em_wide)}):")
    if len(em_wide) > 0:
        for h in [1, 3, 5]:
            nc = em_wide[f'tom_change_{h}'].mean()
            print(f"    TOM {h}-tick return: {nc:+.4f}")


# ============================================================================
# PATTERN M: BID/ASK PRICE GAP FROM MID - ASYMMETRY SIGNAL
# ============================================================================
print("\n\n" + "=" * 80)
print("PATTERN M: BID-MID vs ASK-MID ASYMMETRY")
print("=" * 80)

for d in [-2, -1, 0]:
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['next_change'] = df['mid_change'].shift(-1)

    # When spread is odd (5,7,9,13), mid is not centered
    # bid_to_mid = mid - bid, ask_to_mid = ask - mid
    df['bid_to_mid'] = df['mid_price'] - df['bid_price_1']
    df['ask_to_mid'] = df['ask_price_1'] - df['mid_price']
    df['ba_asymmetry'] = df['bid_to_mid'] - df['ask_to_mid']

    print(f"\n  Day {d}:")
    print(f"  Unique asymmetry values: {sorted(df['ba_asymmetry'].unique())}")

    # For odd spreads: bid_to_mid != ask_to_mid
    # E.g., spread=13: bid_to_mid = 6 or 7, ask_to_mid = 7 or 6
    # If bid_to_mid > ask_to_mid, mid is closer to ask => bearish?

    for asym in sorted(df['ba_asymmetry'].unique()):
        mask = df['ba_asymmetry'] == asym
        n = mask.sum()
        if n >= 5:
            nc = df.loc[mask, 'next_change'].mean()
            sp = df.loc[mask, 'spread'].mean()
            print(f"  asymmetry={asym:+.1f}: next_change={nc:+.4f}, avg_spread={sp:.1f}, n={n}")


# ============================================================================
# PATTERN N: WHAT COMBINATION OF SIGNALS HASN'T BEEN TRIED?
# Specifically: volatility-adaptive spread + asymmetric FV
# ============================================================================
print("\n\n" + "=" * 80)
print("PATTERN N: VOLATILITY-ADAPTIVE STRATEGY SIMULATION")
print("=" * 80)

for d in [0]:
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['abs_change'] = df['mid_change'].abs()
    df['next_change'] = df['mid_change'].shift(-1)

    # Current strategy: constant posting at best+1
    # Proposed: after big move (|change| >= 3), widen posting by 1 tick
    # Rationale: next |move| is 2.5x bigger, so reversal is reliable.
    # If we widen on the CONTINUATION side, we avoid getting filled
    # on the wrong side of the reversal.

    # Simulate: at each tick, what would be our PnL from different offsets?
    # Assume we always get filled (optimistic but relative comparison works)

    # Baseline: buy at bid+1, sell at ask-1 (= mid ± (spread/2 - 1))
    df['edge_baseline'] = (df['spread'] / 2) - 1  # 5.5 for spread=13

    # After big up: skew sell side tighter (ask-2), buy side wider (bid+0)
    # After big down: skew buy side tighter (bid+2), sell side wider (ask-0)
    df['prev_change'] = df['mid_change']
    df['big_up'] = df['prev_change'] >= 3.0
    df['big_dn'] = df['prev_change'] <= -3.0

    # Edge if we sell (getting filled on ask side):
    # Normal: ask-1 = mid + spread/2 - 1, edge = spread/2 - 1
    # Tighter (after big up, expecting reversal): ask-2, edge = spread/2 - 2
    # BUT we might get filled SOONER

    # The key metric: edge * P(fill) * correct_side
    # After big up: we WANT to sell (reversal), so we should post sell aggressively
    # This is what directional posting already does

    # What HASN'T been tried: WIDENING the opposite side
    # After big up: widen buy (bid-1 instead of bid+1), tighten sell (ask-2 instead of ask-1)
    # Net effect: asymmetric spread that captures the reversal edge

    # Count how many big moves occur
    n_big_up = df['big_up'].sum()
    n_big_dn = df['big_dn'].sum()
    print(f"  Day {d}: big_up={n_big_up}, big_dn={n_big_dn}")

    # Expected edge improvement per big-move event:
    # Old: symmetric posting at ±(spread/2 - 1) = ±5.5
    # New: after big up, sell at ask-2, buy at bid-1
    #   Sell edge = spread/2 - 2 = 4.5 (worse)
    #   But P(sell fill) increases AND reversal makes it more profitable
    #   Buy edge = spread/2 + 1 = 7.5 (better if filled, but unlikely)

    # Actually the directional posting in s3 already does similar asymmetry.
    # What's truly DIFFERENT would be:
    # 1. Increasing position SIZE after big moves (volatility scaling)
    # 2. Using the |change|^2 as a scaling factor for FV shift

    print("\n  The key untried combination:")
    print("  1. Piecewise FV: stronger shift for |change|>2 (slope=-0.50 vs -0.15)")
    print("  2. Asymmetric FV: larger bullish shift after big DOWN than bearish after big UP")
    print("  3. Vol-scaling: multiply FV shift by |change|/avg_|change| as a multiplier")


# ============================================================================
# FINAL: What are the EXACT coefficient values for the current 4-lag regression?
# And how would piecewise/asymmetric coefficients differ?
# ============================================================================
print("\n\n" + "=" * 80)
print("FINAL: REGRESSION COEFFICIENT COMPARISON")
print("=" * 80)

for d in [-2, -1, 0]:
    df = get_product(days[d], 'TOMATOES')
    df['mid_change'] = df['mid_price'].diff()

    # 4-lag microprice deviation
    df['microprice'] = (df['bid_price_1'] * df['ask_volume_1'] + df['ask_price_1'] * df['bid_volume_1']) / \
                       (df['bid_volume_1'] + df['ask_volume_1'])
    df['mp_dev'] = df['microprice'] - df['mid_price']

    # Create lagged features
    for lag in range(1, 5):
        df[f'mp_dev_lag{lag}'] = df['mp_dev'].shift(lag)

    valid = df.dropna().copy()

    # Standard linear regression
    X = valid[[f'mp_dev_lag{i}' for i in range(1, 5)]].values
    y = valid['mid_change'].values

    # OLS
    from numpy.linalg import lstsq
    X_bias = np.column_stack([np.ones(len(X)), X])
    coefs, _, _, _ = lstsq(X_bias, y, rcond=None)
    pred = X_bias @ coefs
    rmse = np.sqrt(np.mean((y - pred)**2))

    print(f"\n  Day {d} - Standard 4-lag regression:")
    print(f"    Intercept: {coefs[0]:.4f}")
    print(f"    Lag coefficients: {coefs[1:]}")
    print(f"    RMSE: {rmse:.4f}")

    # Piecewise regression: separate for |mp_dev| > 2 vs <= 2
    # This captures the non-linearity in mean reversion
    mask_small = valid['mp_dev'].abs() <= 2
    mask_large = ~mask_small

    for label, mask in [("Small |dev|<=2", mask_small), ("Large |dev|>2", mask_large)]:
        sub = valid[mask]
        if len(sub) > 20:
            X_sub = sub[[f'mp_dev_lag{i}' for i in range(1, 5)]].values
            y_sub = sub['mid_change'].values
            X_sub_bias = np.column_stack([np.ones(len(X_sub)), X_sub])
            coefs_sub, _, _, _ = lstsq(X_sub_bias, y_sub, rcond=None)
            pred_sub = X_sub_bias @ coefs_sub
            rmse_sub = np.sqrt(np.mean((y_sub - pred_sub)**2))
            print(f"\n    {label} (n={len(sub)}):")
            print(f"      Intercept: {coefs_sub[0]:.4f}")
            print(f"      Lag coefficients: {coefs_sub[1:]}")
            print(f"      RMSE: {rmse_sub:.4f}")

    # Asymmetric regression: separate for negative vs positive mp_dev
    mask_pos = valid['mp_dev'] > 0
    mask_neg = valid['mp_dev'] < 0

    for label, mask in [("Positive dev (bullish)", mask_pos), ("Negative dev (bearish)", mask_neg)]:
        sub = valid[mask]
        if len(sub) > 20:
            X_sub = sub[[f'mp_dev_lag{i}' for i in range(1, 5)]].values
            y_sub = sub['mid_change'].values
            X_sub_bias = np.column_stack([np.ones(len(X_sub)), X_sub])
            coefs_sub, _, _, _ = lstsq(X_sub_bias, y_sub, rcond=None)
            print(f"\n    {label} (n={len(sub)}):")
            print(f"      Intercept: {coefs_sub[0]:.4f}")
            print(f"      Lag 1 coefficient: {coefs_sub[1]:.4f}")
            print(f"      Sum of lag coefficients: {sum(coefs_sub[1:]):.4f}")


print("\n\n" + "=" * 80)
print("COMPLETE ANALYSIS DONE")
print("=" * 80)
