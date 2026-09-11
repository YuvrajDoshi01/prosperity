"""
ASH_COATED_OSMIUM Microstructure Edge Case Analysis - Round 2
Analyzing anomalies and exploitable patterns in ACO order book data.

Focus areas:
1. One-sided book behavior
2. Price level clustering / magnetic levels
3. Extreme moves and their context
4. Book depth signals (L2/L3 predictive power)
5. Spread jumps
6. Consecutive direction runs
7. Volume spikes
"""

import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = Path("/Users/y0d046w/Desktop/prosperity4-tester-private/trader-logic/round-2/data")
PRODUCT = "ASH_COATED_OSMIUM"
FV = 10000  # Known fair value for ACO

def load_all_days():
    """Load and concatenate all days of price data for ACO."""
    dfs = []
    for day in [-2, -1, 0, 1]:
        path = DATA_DIR / f"prices_round_2_day_{day}.csv"
        df = pd.read_csv(path, sep=';')
        df = df[df['product'] == PRODUCT].copy()
        df['day'] = day
        dfs.append(df)
    combined = pd.concat(dfs, ignore_index=True)
    return combined

def compute_derived_features(df):
    """Compute derived features for analysis."""
    # Calculate mid from bid/ask when available
    df['has_bid'] = df['bid_price_1'].notna()
    df['has_ask'] = df['ask_price_1'].notna()
    df['has_both'] = df['has_bid'] & df['has_ask']
    df['bid_only'] = df['has_bid'] & ~df['has_ask']
    df['ask_only'] = df['has_ask'] & ~df['has_bid']
    df['empty_book'] = ~df['has_bid'] & ~df['has_ask']

    # Recalculate mid properly
    df['calc_mid'] = np.where(
        df['has_both'],
        (df['bid_price_1'] + df['ask_price_1']) / 2,
        np.where(df['has_bid'], df['bid_price_1'],
                 np.where(df['has_ask'], df['ask_price_1'], np.nan))
    )

    # Spread
    df['spread'] = np.where(df['has_both'], df['ask_price_1'] - df['bid_price_1'], np.nan)

    # L1 volumes
    df['L1_bid_vol'] = df['bid_volume_1'].fillna(0)
    df['L1_ask_vol'] = df['ask_volume_1'].fillna(0)
    df['L1_total_vol'] = df['L1_bid_vol'] + df['L1_ask_vol']

    # L2 volumes
    df['L2_bid_vol'] = df['bid_volume_2'].fillna(0)
    df['L2_ask_vol'] = df['ask_volume_2'].fillna(0)

    # L3 volumes
    df['L3_bid_vol'] = df['bid_volume_3'].fillna(0)
    df['L3_ask_vol'] = df['ask_volume_3'].fillna(0)

    # Total depth
    df['total_bid_vol'] = df['L1_bid_vol'] + df['L2_bid_vol'] + df['L3_bid_vol']
    df['total_ask_vol'] = df['L1_ask_vol'] + df['L2_ask_vol'] + df['L3_ask_vol']

    # Order book imbalance
    df['OBI'] = np.where(
        df['L1_total_vol'] > 0,
        (df['L1_bid_vol'] - df['L1_ask_vol']) / df['L1_total_vol'],
        0
    )

    # Sort by day and timestamp
    df = df.sort_values(['day', 'timestamp']).reset_index(drop=True)

    # Compute changes (within each day)
    df['delta_mid'] = df.groupby('day')['calc_mid'].diff()
    df['delta_spread'] = df.groupby('day')['spread'].diff()

    # Forward returns
    df['next_mid'] = df.groupby('day')['calc_mid'].shift(-1)
    df['fwd_delta_mid'] = df['next_mid'] - df['calc_mid']

    # Distance from FV
    df['dist_from_fv'] = df['calc_mid'] - FV

    return df

def analyze_one_sided_books(df):
    """
    SECTION 1: One-Sided Book Analysis
    When book is bid-only or ask-only, what happens next?
    """
    print("=" * 80)
    print("SECTION 1: ONE-SIDED BOOK ANALYSIS")
    print("=" * 80)

    total_ticks = len(df)

    # Count book states
    bid_only_count = df['bid_only'].sum()
    ask_only_count = df['ask_only'].sum()
    empty_count = df['empty_book'].sum()
    both_count = df['has_both'].sum()

    print(f"\nBook State Distribution (N={total_ticks}):")
    print(f"  Both sides:  {both_count:6d} ({100*both_count/total_ticks:.2f}%)")
    print(f"  Bid only:    {bid_only_count:6d} ({100*bid_only_count/total_ticks:.2f}%)")
    print(f"  Ask only:    {ask_only_count:6d} ({100*ask_only_count/total_ticks:.2f}%)")
    print(f"  Empty:       {empty_count:6d} ({100*empty_count/total_ticks:.2f}%)")

    # Forward returns conditional on book state
    print("\n--- Forward Mid Change Conditional on Book State ---")

    # Bid-only: market just took all asks, expect downward pressure?
    bid_only_df = df[df['bid_only'] & df['fwd_delta_mid'].notna()]
    if len(bid_only_df) > 0:
        mean_fwd = bid_only_df['fwd_delta_mid'].mean()
        std_fwd = bid_only_df['fwd_delta_mid'].std()
        pct_up = (bid_only_df['fwd_delta_mid'] > 0).mean()
        pct_down = (bid_only_df['fwd_delta_mid'] < 0).mean()
        print(f"\nBID-ONLY ticks (N={len(bid_only_df)}):")
        print(f"  E[delta_mid(t+1)] = {mean_fwd:+.3f} (std={std_fwd:.3f})")
        print(f"  P(up)   = {100*pct_up:.1f}%")
        print(f"  P(down) = {100*pct_down:.1f}%")
        print(f"  t-stat  = {mean_fwd / (std_fwd / np.sqrt(len(bid_only_df))):.2f}")

    # Ask-only: market just took all bids, expect upward pressure?
    ask_only_df = df[df['ask_only'] & df['fwd_delta_mid'].notna()]
    if len(ask_only_df) > 0:
        mean_fwd = ask_only_df['fwd_delta_mid'].mean()
        std_fwd = ask_only_df['fwd_delta_mid'].std()
        pct_up = (ask_only_df['fwd_delta_mid'] > 0).mean()
        pct_down = (ask_only_df['fwd_delta_mid'] < 0).mean()
        print(f"\nASK-ONLY ticks (N={len(ask_only_df)}):")
        print(f"  E[delta_mid(t+1)] = {mean_fwd:+.3f} (std={std_fwd:.3f})")
        print(f"  P(up)   = {100*pct_up:.1f}%")
        print(f"  P(down) = {100*pct_down:.1f}%")
        print(f"  t-stat  = {mean_fwd / (std_fwd / np.sqrt(len(ask_only_df))):.2f}")

    # Two-sided book baseline
    both_df = df[df['has_both'] & df['fwd_delta_mid'].notna()]
    if len(both_df) > 0:
        mean_fwd = both_df['fwd_delta_mid'].mean()
        std_fwd = both_df['fwd_delta_mid'].std()
        print(f"\nTWO-SIDED baseline (N={len(both_df)}):")
        print(f"  E[delta_mid(t+1)] = {mean_fwd:+.3f} (std={std_fwd:.3f})")

    # Multi-tick persistence
    print("\n--- Multi-Tick Forward Returns After One-Sided Book ---")
    for horizon in [1, 2, 5, 10]:
        df[f'fwd_{horizon}'] = df.groupby('day')['calc_mid'].shift(-horizon) - df['calc_mid']

        if df['bid_only'].sum() > 0:
            bid_only_fwd = df.loc[df['bid_only'], f'fwd_{horizon}'].dropna()
            if len(bid_only_fwd) > 5:
                print(f"  Bid-only -> +{horizon} ticks: E = {bid_only_fwd.mean():+.3f}, N={len(bid_only_fwd)}")

        if df['ask_only'].sum() > 0:
            ask_only_fwd = df.loc[df['ask_only'], f'fwd_{horizon}'].dropna()
            if len(ask_only_fwd) > 5:
                print(f"  Ask-only -> +{horizon} ticks: E = {ask_only_fwd.mean():+.3f}, N={len(ask_only_fwd)}")

def analyze_price_clustering(df):
    """
    SECTION 2: Price Level Clustering
    Does mid-price cluster at certain values?
    """
    print("\n" + "=" * 80)
    print("SECTION 2: PRICE LEVEL CLUSTERING / MAGNETIC LEVELS")
    print("=" * 80)

    valid_mid = df[df['calc_mid'].notna()]['calc_mid']

    print(f"\nMid-price statistics (N={len(valid_mid)}):")
    print(f"  Mean:   {valid_mid.mean():.2f}")
    print(f"  Median: {valid_mid.median():.2f}")
    print(f"  Std:    {valid_mid.std():.2f}")
    print(f"  Min:    {valid_mid.min():.2f}")
    print(f"  Max:    {valid_mid.max():.2f}")

    # Modulo analysis
    print("\n--- Mid % 10 distribution (round number clustering) ---")
    mod10 = (valid_mid % 10).round(1)
    mod10_counts = mod10.value_counts().sort_index()
    expected_pct = 100.0 / 10  # 10% uniform
    print(f"Expected if uniform: {expected_pct:.1f}% per bucket")
    for val, count in mod10_counts.head(15).items():
        pct = 100 * count / len(valid_mid)
        deviation = pct - expected_pct
        print(f"  mid % 10 = {val:5.1f}: {pct:5.2f}% (N={count:5d}) {'*' if abs(deviation) > 2 else ''}")

    print("\n--- Mid % 5 distribution ---")
    mod5 = (valid_mid % 5).round(1)
    mod5_counts = mod5.value_counts().sort_index()
    expected_pct = 100.0 / 5  # 20% uniform
    print(f"Expected if uniform: {expected_pct:.1f}% per bucket")
    for val, count in mod5_counts.head(10).items():
        pct = 100 * count / len(valid_mid)
        deviation = pct - expected_pct
        print(f"  mid % 5 = {val:5.1f}: {pct:5.2f}% (N={count:5d}) {'*' if abs(deviation) > 3 else ''}")

    # Fair value clustering
    print(f"\n--- Distance from FV={FV} ---")
    dist = df[df['calc_mid'].notna()]['dist_from_fv']
    print(f"  Mean distance: {dist.mean():+.3f}")
    print(f"  Median distance: {dist.median():+.3f}")
    print(f"  |dist| <= 5:  {100*(abs(dist) <= 5).mean():.1f}% of ticks")
    print(f"  |dist| <= 10: {100*(abs(dist) <= 10).mean():.1f}% of ticks")
    print(f"  |dist| <= 20: {100*(abs(dist) <= 20).mean():.1f}% of ticks")

    # Distribution of exact mid values
    print("\n--- Most common mid values ---")
    mid_counts = valid_mid.value_counts().head(20)
    for mid_val, count in mid_counts.items():
        pct = 100 * count / len(valid_mid)
        dist_fv = mid_val - FV
        print(f"  {mid_val:.1f} (FV{dist_fv:+.1f}): {pct:.2f}% (N={count})")

    # Forward returns by distance from FV (mean-reversion test)
    print("\n--- Mean-Reversion by Distance from FV ---")
    df['dist_bucket'] = pd.cut(df['dist_from_fv'], bins=[-50, -15, -5, 5, 15, 50])
    grouped = df.groupby('dist_bucket', observed=True)['fwd_delta_mid'].agg(['mean', 'std', 'count'])
    for bucket, row in grouped.iterrows():
        if row['count'] > 10:
            t_stat = row['mean'] / (row['std'] / np.sqrt(row['count'])) if row['std'] > 0 else 0
            print(f"  {bucket}: E[fwd] = {row['mean']:+.4f}, N={int(row['count']):5d}, t={t_stat:.2f}")

def analyze_extreme_moves(df):
    """
    SECTION 3: Extreme Moves Analysis
    Identify ticks where |delta_mid| > 5
    """
    print("\n" + "=" * 80)
    print("SECTION 3: EXTREME MOVES (|delta_mid| > 5)")
    print("=" * 80)

    valid = df[df['delta_mid'].notna()]

    # Distribution of delta_mid
    print(f"\nDelta_mid distribution (N={len(valid)}):")
    print(f"  Mean:   {valid['delta_mid'].mean():+.3f}")
    print(f"  Std:    {valid['delta_mid'].std():.3f}")
    print(f"  Median: {valid['delta_mid'].median():.3f}")

    for threshold in [3, 5, 7, 10]:
        extreme = valid[abs(valid['delta_mid']) > threshold]
        print(f"  |delta| > {threshold}: {len(extreme):5d} ticks ({100*len(extreme)/len(valid):.2f}%)")

    # Analyze extreme moves
    extreme_df = valid[abs(valid['delta_mid']) > 5].copy()
    print(f"\n--- Extreme moves (|delta_mid| > 5): N={len(extreme_df)} ---")

    if len(extreme_df) == 0:
        print("No extreme moves found!")
        return

    # Direction breakdown
    big_up = extreme_df[extreme_df['delta_mid'] > 5]
    big_down = extreme_df[extreme_df['delta_mid'] < -5]
    print(f"\n  Large UP moves (delta > +5):   N={len(big_up)}")
    print(f"  Large DOWN moves (delta < -5): N={len(big_down)}")

    # What preceded extreme moves?
    print("\n--- Context BEFORE extreme moves ---")

    # Lag features
    df['lag_spread'] = df.groupby('day')['spread'].shift(1)
    df['lag_L1_vol'] = df.groupby('day')['L1_total_vol'].shift(1)
    df['lag_OBI'] = df.groupby('day')['OBI'].shift(1)
    df['lag_delta_mid'] = df.groupby('day')['delta_mid'].shift(1)

    extreme_df = df[abs(df['delta_mid']) > 5].copy()
    normal_df = df[(abs(df['delta_mid']) <= 5) & df['delta_mid'].notna()].copy()

    print(f"\n  Lag spread:     Extreme={extreme_df['lag_spread'].mean():.2f} vs Normal={normal_df['lag_spread'].mean():.2f}")
    print(f"  Lag L1 volume:  Extreme={extreme_df['lag_L1_vol'].mean():.2f} vs Normal={normal_df['lag_L1_vol'].mean():.2f}")
    print(f"  Lag OBI:        Extreme={extreme_df['lag_OBI'].mean():.3f} vs Normal={normal_df['lag_OBI'].mean():.3f}")

    # Were there one-sided books before?
    lag_bid_only = df.groupby('day')['bid_only'].shift(1)
    lag_ask_only = df.groupby('day')['ask_only'].shift(1)

    extreme_mask = abs(df['delta_mid']) > 5
    print(f"\n  Preceded by bid-only: {100*(lag_bid_only[extreme_mask].fillna(False)).mean():.1f}% (normal: {100*lag_bid_only[~extreme_mask].fillna(False).mean():.1f}%)")
    print(f"  Preceded by ask-only: {100*(lag_ask_only[extreme_mask].fillna(False)).mean():.1f}% (normal: {100*lag_ask_only[~extreme_mask].fillna(False).mean():.1f}%)")

    # What followed extreme moves? Momentum or reversal?
    print("\n--- What FOLLOWS extreme moves? ---")
    extreme_with_fwd = extreme_df[extreme_df['fwd_delta_mid'].notna()]

    # After big up moves
    big_up_fwd = extreme_with_fwd[extreme_with_fwd['delta_mid'] > 5]['fwd_delta_mid']
    if len(big_up_fwd) > 0:
        print(f"\n  After big UP (delta > +5): N={len(big_up_fwd)}")
        print(f"    E[next delta] = {big_up_fwd.mean():+.3f}")
        print(f"    P(continues up) = {100*(big_up_fwd > 0).mean():.1f}%")
        print(f"    P(reverses)     = {100*(big_up_fwd < 0).mean():.1f}%")

    # After big down moves
    big_down_fwd = extreme_with_fwd[extreme_with_fwd['delta_mid'] < -5]['fwd_delta_mid']
    if len(big_down_fwd) > 0:
        print(f"\n  After big DOWN (delta < -5): N={len(big_down_fwd)}")
        print(f"    E[next delta] = {big_down_fwd.mean():+.3f}")
        print(f"    P(continues down) = {100*(big_down_fwd < 0).mean():.1f}%")
        print(f"    P(reverses)       = {100*(big_down_fwd > 0).mean():.1f}%")

def analyze_book_depth_signals(df):
    """
    SECTION 4: Book Depth Signals
    Does L2/L3 volume add predictive power?
    """
    print("\n" + "=" * 80)
    print("SECTION 4: BOOK DEPTH SIGNALS (L2/L3 PREDICTIVE POWER)")
    print("=" * 80)

    # L2 availability
    has_L2_bid = df['bid_volume_2'].notna().sum()
    has_L2_ask = df['ask_volume_2'].notna().sum()
    has_L3_bid = df['bid_volume_3'].notna().sum()
    has_L3_ask = df['ask_volume_3'].notna().sum()

    print(f"\nDepth availability (N={len(df)}):")
    print(f"  L2 bid: {has_L2_bid:6d} ({100*has_L2_bid/len(df):.1f}%)")
    print(f"  L2 ask: {has_L2_ask:6d} ({100*has_L2_ask/len(df):.1f}%)")
    print(f"  L3 bid: {has_L3_bid:6d} ({100*has_L3_bid/len(df):.1f}%)")
    print(f"  L3 ask: {has_L3_ask:6d} ({100*has_L3_ask/len(df):.1f}%)")

    # L2 imbalance
    df['L2_imbalance'] = np.where(
        (df['L2_bid_vol'] + df['L2_ask_vol']) > 0,
        (df['L2_bid_vol'] - df['L2_ask_vol']) / (df['L2_bid_vol'] + df['L2_ask_vol']),
        np.nan
    )

    # Total depth imbalance
    df['total_imbalance'] = np.where(
        (df['total_bid_vol'] + df['total_ask_vol']) > 0,
        (df['total_bid_vol'] - df['total_ask_vol']) / (df['total_bid_vol'] + df['total_ask_vol']),
        np.nan
    )

    # Correlation with forward returns
    print("\n--- Correlation with forward mid change ---")
    valid = df[df['fwd_delta_mid'].notna() & df['OBI'].notna()]

    if len(valid) > 100:
        corr_L1 = valid['OBI'].corr(valid['fwd_delta_mid'])
        print(f"  L1 OBI vs fwd_delta_mid: r = {corr_L1:+.4f} (N={len(valid)})")

    valid_L2 = df[df['fwd_delta_mid'].notna() & df['L2_imbalance'].notna()]
    if len(valid_L2) > 100:
        corr_L2 = valid_L2['L2_imbalance'].corr(valid_L2['fwd_delta_mid'])
        print(f"  L2 imbalance vs fwd_delta_mid: r = {corr_L2:+.4f} (N={len(valid_L2)})")

    valid_total = df[df['fwd_delta_mid'].notna() & df['total_imbalance'].notna()]
    if len(valid_total) > 100:
        corr_total = valid_total['total_imbalance'].corr(valid_total['fwd_delta_mid'])
        print(f"  Total imbalance vs fwd_delta_mid: r = {corr_total:+.4f} (N={len(valid_total)})")

    # Bucket analysis: extreme L2 imbalance
    print("\n--- Forward returns by L2 imbalance bucket ---")
    df['L2_imb_bucket'] = pd.cut(df['L2_imbalance'], bins=[-1.01, -0.5, -0.2, 0.2, 0.5, 1.01],
                                  labels=['<-0.5', '-0.5 to -0.2', '-0.2 to 0.2', '0.2 to 0.5', '>0.5'])
    grouped = df.groupby('L2_imb_bucket', observed=True)['fwd_delta_mid'].agg(['mean', 'std', 'count'])
    for bucket, row in grouped.iterrows():
        if row['count'] > 10:
            t_stat = row['mean'] / (row['std'] / np.sqrt(row['count'])) if row['std'] > 0 else 0
            print(f"  L2_imb {bucket}: E[fwd] = {row['mean']:+.4f}, N={int(row['count']):5d}, t={t_stat:.2f}")

    # "Hidden depth" signal: large L2 volume relative to L1
    df['L2_L1_ratio_bid'] = df['L2_bid_vol'] / (df['L1_bid_vol'] + 0.1)
    df['L2_L1_ratio_ask'] = df['L2_ask_vol'] / (df['L1_ask_vol'] + 0.1)
    df['hidden_bid_depth'] = df['L2_L1_ratio_bid'] > 2  # L2 > 2x L1
    df['hidden_ask_depth'] = df['L2_L1_ratio_ask'] > 2

    print("\n--- Hidden Depth Signal (L2 > 2x L1) ---")
    hidden_bid = df[df['hidden_bid_depth'] & df['fwd_delta_mid'].notna()]
    hidden_ask = df[df['hidden_ask_depth'] & df['fwd_delta_mid'].notna()]
    baseline = df[~df['hidden_bid_depth'] & ~df['hidden_ask_depth'] & df['fwd_delta_mid'].notna()]

    print(f"  Hidden bid depth ticks: {len(hidden_bid)} ({100*len(hidden_bid)/len(df):.1f}%)")
    if len(hidden_bid) > 20:
        print(f"    E[fwd_delta] = {hidden_bid['fwd_delta_mid'].mean():+.4f}")

    print(f"  Hidden ask depth ticks: {len(hidden_ask)} ({100*len(hidden_ask)/len(df):.1f}%)")
    if len(hidden_ask) > 20:
        print(f"    E[fwd_delta] = {hidden_ask['fwd_delta_mid'].mean():+.4f}")

    print(f"  Baseline: E[fwd_delta] = {baseline['fwd_delta_mid'].mean():+.4f}")

def analyze_spread_jumps(df):
    """
    SECTION 5: Spread Jumps
    When spread changes by >= 4 ticks between observations
    """
    print("\n" + "=" * 80)
    print("SECTION 5: SPREAD JUMPS")
    print("=" * 80)

    valid = df[df['delta_spread'].notna() & df['spread'].notna()]

    print(f"\nSpread statistics (N={len(valid)}):")
    print(f"  Mean spread:   {valid['spread'].mean():.2f}")
    print(f"  Median spread: {valid['spread'].median():.2f}")
    print(f"  Std spread:    {valid['spread'].std():.2f}")

    print("\n--- Spread distribution ---")
    spread_counts = valid['spread'].value_counts().sort_index().head(20)
    for spread_val, count in spread_counts.items():
        pct = 100 * count / len(valid)
        print(f"  Spread = {spread_val:5.1f}: {pct:5.2f}% (N={count})")

    # Spread changes
    print("\n--- Spread change distribution ---")
    print(f"  Mean delta_spread: {valid['delta_spread'].mean():+.3f}")
    print(f"  Std delta_spread:  {valid['delta_spread'].std():.3f}")

    for threshold in [2, 4, 6]:
        expansions = valid[valid['delta_spread'] >= threshold]
        contractions = valid[valid['delta_spread'] <= -threshold]
        print(f"\n  |delta_spread| >= {threshold}:")
        print(f"    Expansions:   N={len(expansions)} ({100*len(expansions)/len(valid):.2f}%)")
        print(f"    Contractions: N={len(contractions)} ({100*len(contractions)/len(valid):.2f}%)")

    # Forward returns after spread changes
    print("\n--- Forward returns after spread changes ---")

    # Spread expansion (spread widening)
    expansion = valid[valid['delta_spread'] >= 4]
    if len(expansion) > 5:
        fwd = expansion['fwd_delta_mid'].dropna()
        print(f"\n  Spread EXPANSION (delta >= +4): N={len(fwd)}")
        if len(fwd) > 0:
            print(f"    E[fwd_delta_mid] = {fwd.mean():+.4f}")
            print(f"    Std = {fwd.std():.4f}")

    # Spread contraction
    contraction = valid[valid['delta_spread'] <= -4]
    if len(contraction) > 5:
        fwd = contraction['fwd_delta_mid'].dropna()
        print(f"\n  Spread CONTRACTION (delta <= -4): N={len(fwd)}")
        if len(fwd) > 0:
            print(f"    E[fwd_delta_mid] = {fwd.mean():+.4f}")
            print(f"    Std = {fwd.std():.4f}")

    # Spread level effects
    print("\n--- Forward returns by spread level ---")
    df['spread_bucket'] = pd.cut(df['spread'], bins=[0, 12, 14, 16, 18, 25, 100],
                                  labels=['<12', '12-14', '14-16', '16-18', '18-25', '>25'])
    grouped = df.groupby('spread_bucket', observed=True)['fwd_delta_mid'].agg(['mean', 'std', 'count'])
    for bucket, row in grouped.iterrows():
        if row['count'] > 10:
            t_stat = row['mean'] / (row['std'] / np.sqrt(row['count'])) if row['std'] > 0 else 0
            print(f"  Spread {bucket}: E[fwd] = {row['mean']:+.4f}, N={int(row['count']):5d}, t={t_stat:.2f}")

def analyze_consecutive_runs(df):
    """
    SECTION 6: Consecutive Direction Runs
    After 3+ consecutive up/down moves, what's P(continuation)?
    """
    print("\n" + "=" * 80)
    print("SECTION 6: CONSECUTIVE DIRECTION RUNS")
    print("=" * 80)

    # Compute run direction
    df['direction'] = np.sign(df['delta_mid'])

    # Count consecutive runs
    def compute_run_length(direction_series):
        """Compute run length ending at each tick."""
        run_lengths = []
        current_run = 0
        prev_dir = 0
        for d in direction_series:
            if np.isnan(d):
                current_run = 0
                prev_dir = 0
            elif d == prev_dir and d != 0:
                current_run += 1
            elif d != 0:
                current_run = 1
                prev_dir = d
            else:  # d == 0
                current_run = 0
            run_lengths.append(current_run)
        return run_lengths

    df['run_length'] = compute_run_length(df['direction'].values)

    # Distribution of run lengths
    print("\n--- Run length distribution ---")
    run_counts = df[df['run_length'] > 0]['run_length'].value_counts().sort_index()
    total_runs = run_counts.sum()
    for length, count in run_counts.head(10).items():
        pct = 100 * count / total_runs
        print(f"  Run length {length}: {count:5d} ({pct:.2f}%)")

    # After N consecutive up moves, P(next up)?
    print("\n--- P(continuation | run length) for UP runs ---")
    for run_len in [2, 3, 4, 5]:
        # Find ticks at end of run of this length (direction = +1)
        mask = (df['run_length'] == run_len) & (df['direction'] == 1) & df['fwd_delta_mid'].notna()
        subset = df[mask]
        if len(subset) > 10:
            p_continue = (subset['fwd_delta_mid'] > 0).mean()
            p_reverse = (subset['fwd_delta_mid'] < 0).mean()
            p_flat = (subset['fwd_delta_mid'] == 0).mean()
            print(f"  After {run_len} up moves: P(up)={100*p_continue:.1f}%, P(down)={100*p_reverse:.1f}%, P(flat)={100*p_flat:.1f}% (N={len(subset)})")

    print("\n--- P(continuation | run length) for DOWN runs ---")
    for run_len in [2, 3, 4, 5]:
        mask = (df['run_length'] == run_len) & (df['direction'] == -1) & df['fwd_delta_mid'].notna()
        subset = df[mask]
        if len(subset) > 10:
            p_continue = (subset['fwd_delta_mid'] < 0).mean()
            p_reverse = (subset['fwd_delta_mid'] > 0).mean()
            p_flat = (subset['fwd_delta_mid'] == 0).mean()
            print(f"  After {run_len} down moves: P(down)={100*p_continue:.1f}%, P(up)={100*p_reverse:.1f}%, P(flat)={100*p_flat:.1f}% (N={len(subset)})")

    # Mean forward return by run length
    print("\n--- Mean forward return by run length ---")
    print("\n  UP runs:")
    for run_len in [1, 2, 3, 4, 5]:
        mask = (df['run_length'] == run_len) & (df['direction'] == 1) & df['fwd_delta_mid'].notna()
        subset = df[mask]
        if len(subset) > 10:
            mean_fwd = subset['fwd_delta_mid'].mean()
            std_fwd = subset['fwd_delta_mid'].std()
            t_stat = mean_fwd / (std_fwd / np.sqrt(len(subset))) if std_fwd > 0 else 0
            print(f"    Run {run_len}: E[fwd] = {mean_fwd:+.4f}, t = {t_stat:.2f} (N={len(subset)})")

    print("\n  DOWN runs:")
    for run_len in [1, 2, 3, 4, 5]:
        mask = (df['run_length'] == run_len) & (df['direction'] == -1) & df['fwd_delta_mid'].notna()
        subset = df[mask]
        if len(subset) > 10:
            mean_fwd = subset['fwd_delta_mid'].mean()
            std_fwd = subset['fwd_delta_mid'].std()
            t_stat = mean_fwd / (std_fwd / np.sqrt(len(subset))) if std_fwd > 0 else 0
            print(f"    Run {run_len}: E[fwd] = {mean_fwd:+.4f}, t = {t_stat:.2f} (N={len(subset)})")

def analyze_volume_spikes(df):
    """
    SECTION 7: Volume Spikes
    Identify ticks where L1_vol > 25
    """
    print("\n" + "=" * 80)
    print("SECTION 7: VOLUME SPIKES (L1 Volume > 25)")
    print("=" * 80)

    print("\n--- L1 volume distribution ---")
    print(f"  Mean L1_bid_vol: {df['L1_bid_vol'].mean():.2f}")
    print(f"  Mean L1_ask_vol: {df['L1_ask_vol'].mean():.2f}")
    print(f"  Mean L1_total:   {df['L1_total_vol'].mean():.2f}")

    for threshold in [20, 25, 30, 40]:
        high_vol = df[df['L1_total_vol'] > threshold]
        print(f"  L1_total > {threshold}: {len(high_vol):5d} ({100*len(high_vol)/len(df):.2f}%)")

    # High bid volume
    print("\n--- High BID volume (L1_bid > 25) ---")
    high_bid = df[df['L1_bid_vol'] > 25]
    print(f"  Count: {len(high_bid)} ({100*len(high_bid)/len(df):.2f}%)")
    if len(high_bid) > 10:
        fwd = high_bid['fwd_delta_mid'].dropna()
        if len(fwd) > 5:
            print(f"  E[fwd_delta_mid] = {fwd.mean():+.4f}")
            print(f"  P(up) = {100*(fwd > 0).mean():.1f}%")

    # High ask volume
    print("\n--- High ASK volume (L1_ask > 25) ---")
    high_ask = df[df['L1_ask_vol'] > 25]
    print(f"  Count: {len(high_ask)} ({100*len(high_ask)/len(df):.2f}%)")
    if len(high_ask) > 10:
        fwd = high_ask['fwd_delta_mid'].dropna()
        if len(fwd) > 5:
            print(f"  E[fwd_delta_mid] = {fwd.mean():+.4f}")
            print(f"  P(down) = {100*(fwd < 0).mean():.1f}%")

    # Combined high volume
    print("\n--- High TOTAL volume (L1_total > 25) ---")
    high_total = df[df['L1_total_vol'] > 25]
    print(f"  Count: {len(high_total)} ({100*len(high_total)/len(df):.2f}%)")
    if len(high_total) > 10:
        fwd = high_total['fwd_delta_mid'].dropna()
        if len(fwd) > 5:
            print(f"  E[fwd_delta_mid] = {fwd.mean():+.4f}")

    # Volume spike with OBI filter
    print("\n--- Volume spike + OBI filter ---")
    high_vol_pos_obi = df[(df['L1_total_vol'] > 25) & (df['OBI'] > 0.3)]
    high_vol_neg_obi = df[(df['L1_total_vol'] > 25) & (df['OBI'] < -0.3)]

    if len(high_vol_pos_obi) > 5:
        fwd = high_vol_pos_obi['fwd_delta_mid'].dropna()
        print(f"\n  High vol + positive OBI (N={len(fwd)}):")
        if len(fwd) > 0:
            print(f"    E[fwd_delta] = {fwd.mean():+.4f}")

    if len(high_vol_neg_obi) > 5:
        fwd = high_vol_neg_obi['fwd_delta_mid'].dropna()
        print(f"\n  High vol + negative OBI (N={len(fwd)}):")
        if len(fwd) > 0:
            print(f"    E[fwd_delta] = {fwd.mean():+.4f}")

    # Volume asymmetry as signal
    print("\n--- Volume asymmetry (L1_bid - L1_ask) ---")
    df['vol_asymmetry'] = df['L1_bid_vol'] - df['L1_ask_vol']
    df['vol_asym_bucket'] = pd.cut(df['vol_asymmetry'], bins=[-30, -10, -3, 3, 10, 30],
                                    labels=['<-10', '-10 to -3', '-3 to 3', '3 to 10', '>10'])
    grouped = df.groupby('vol_asym_bucket', observed=True)['fwd_delta_mid'].agg(['mean', 'std', 'count'])
    for bucket, row in grouped.iterrows():
        if row['count'] > 20:
            t_stat = row['mean'] / (row['std'] / np.sqrt(row['count'])) if row['std'] > 0 else 0
            print(f"  Vol asym {bucket}: E[fwd] = {row['mean']:+.4f}, N={int(row['count']):5d}, t={t_stat:.2f}")

def summarize_exploitable_edges(df):
    """
    SUMMARY: Identify the most exploitable edge cases
    """
    print("\n" + "=" * 80)
    print("SUMMARY: EXPLOITABLE EDGE CASES (frequency > 1%)")
    print("=" * 80)

    n_total = len(df)
    exploitable = []

    # Check each potential edge

    # 1. One-sided books
    bid_only = df[df['bid_only'] & df['fwd_delta_mid'].notna()]
    if len(bid_only) > 0.01 * n_total:
        mean_fwd = bid_only['fwd_delta_mid'].mean()
        std_fwd = bid_only['fwd_delta_mid'].std()
        t_stat = mean_fwd / (std_fwd / np.sqrt(len(bid_only))) if std_fwd > 0 else 0
        if abs(t_stat) > 1.5:
            exploitable.append(f"BID-ONLY: freq={100*len(bid_only)/n_total:.1f}%, E[fwd]={mean_fwd:+.3f}, t={t_stat:.2f}")

    ask_only = df[df['ask_only'] & df['fwd_delta_mid'].notna()]
    if len(ask_only) > 0.01 * n_total:
        mean_fwd = ask_only['fwd_delta_mid'].mean()
        std_fwd = ask_only['fwd_delta_mid'].std()
        t_stat = mean_fwd / (std_fwd / np.sqrt(len(ask_only))) if std_fwd > 0 else 0
        if abs(t_stat) > 1.5:
            exploitable.append(f"ASK-ONLY: freq={100*len(ask_only)/n_total:.1f}%, E[fwd]={mean_fwd:+.3f}, t={t_stat:.2f}")

    # 2. Distance from FV
    far_above = df[(df['dist_from_fv'] > 10) & df['fwd_delta_mid'].notna()]
    far_below = df[(df['dist_from_fv'] < -10) & df['fwd_delta_mid'].notna()]

    if len(far_above) > 0.01 * n_total:
        mean_fwd = far_above['fwd_delta_mid'].mean()
        std_fwd = far_above['fwd_delta_mid'].std()
        t_stat = mean_fwd / (std_fwd / np.sqrt(len(far_above))) if std_fwd > 0 else 0
        if abs(t_stat) > 1.5:
            exploitable.append(f"FAR ABOVE FV (>+10): freq={100*len(far_above)/n_total:.1f}%, E[fwd]={mean_fwd:+.3f}, t={t_stat:.2f}")

    if len(far_below) > 0.01 * n_total:
        mean_fwd = far_below['fwd_delta_mid'].mean()
        std_fwd = far_below['fwd_delta_mid'].std()
        t_stat = mean_fwd / (std_fwd / np.sqrt(len(far_below))) if std_fwd > 0 else 0
        if abs(t_stat) > 1.5:
            exploitable.append(f"FAR BELOW FV (<-10): freq={100*len(far_below)/n_total:.1f}%, E[fwd]={mean_fwd:+.3f}, t={t_stat:.2f}")

    # 3. Run continuation/reversal
    df['direction'] = np.sign(df['delta_mid'])
    def compute_run_length(direction_series):
        run_lengths = []
        current_run = 0
        prev_dir = 0
        for d in direction_series:
            if np.isnan(d):
                current_run = 0
                prev_dir = 0
            elif d == prev_dir and d != 0:
                current_run += 1
            elif d != 0:
                current_run = 1
                prev_dir = d
            else:
                current_run = 0
            run_lengths.append(current_run)
        return run_lengths

    df['run_length'] = compute_run_length(df['direction'].values)

    for run_len in [3, 4, 5]:
        up_run = df[(df['run_length'] == run_len) & (df['direction'] == 1) & df['fwd_delta_mid'].notna()]
        if len(up_run) > 0.01 * n_total:
            mean_fwd = up_run['fwd_delta_mid'].mean()
            std_fwd = up_run['fwd_delta_mid'].std()
            t_stat = mean_fwd / (std_fwd / np.sqrt(len(up_run))) if std_fwd > 0 else 0
            if abs(t_stat) > 1.5:
                exploitable.append(f"AFTER {run_len} UP MOVES: freq={100*len(up_run)/n_total:.1f}%, E[fwd]={mean_fwd:+.3f}, t={t_stat:.2f}")

    # 4. Wide spread
    wide_spread = df[(df['spread'] > 18) & df['fwd_delta_mid'].notna()]
    if len(wide_spread) > 0.01 * n_total:
        mean_fwd = wide_spread['fwd_delta_mid'].mean()
        std_fwd = wide_spread['fwd_delta_mid'].std()
        t_stat = mean_fwd / (std_fwd / np.sqrt(len(wide_spread))) if std_fwd > 0 else 0
        if abs(t_stat) > 1.5:
            exploitable.append(f"WIDE SPREAD (>18): freq={100*len(wide_spread)/n_total:.1f}%, E[fwd]={mean_fwd:+.3f}, t={t_stat:.2f}")

    print("\n--- Exploitable edges found (freq > 1%, |t| > 1.5): ---")
    if exploitable:
        for edge in exploitable:
            print(f"  * {edge}")
    else:
        print("  No strong exploitable edges found meeting criteria.")

    print("\n--- Additional insights (may have lower t-stats): ---")

    # Mean-reversion from FV
    below_fv = df[(df['dist_from_fv'] < -5) & df['fwd_delta_mid'].notna()]
    above_fv = df[(df['dist_from_fv'] > 5) & df['fwd_delta_mid'].notna()]

    if len(below_fv) > 100 and len(above_fv) > 100:
        below_mean = below_fv['fwd_delta_mid'].mean()
        above_mean = above_fv['fwd_delta_mid'].mean()
        print(f"\n  Mean-reversion to FV:")
        print(f"    Below FV by >5: E[fwd] = {below_mean:+.4f} (N={len(below_fv)})")
        print(f"    Above FV by >5: E[fwd] = {above_mean:+.4f} (N={len(above_fv)})")
        print(f"    Spread: {below_mean - above_mean:+.4f}")

def main():
    print("Loading ASH_COATED_OSMIUM data from Round 2...")
    df = load_all_days()
    print(f"Loaded {len(df)} ticks across 4 days")

    print("\nComputing derived features...")
    df = compute_derived_features(df)

    # Run all analyses
    analyze_one_sided_books(df)
    analyze_price_clustering(df)
    analyze_extreme_moves(df)
    analyze_book_depth_signals(df)
    analyze_spread_jumps(df)
    analyze_consecutive_runs(df)
    analyze_volume_spikes(df)
    summarize_exploitable_edges(df)

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()
