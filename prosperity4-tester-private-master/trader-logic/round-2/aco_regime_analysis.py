"""
ACO Regime-Based Signal Analysis for Round 2
============================================
Deep analysis of non-linear and regime-based predictive signals for ASH_COATED_OSMIUM.

Focus: Effects that are CONSISTENT across all 4 days (day -2, -1, 0, 1).
"""

import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

# Configuration
DATA_DIR = Path("/Users/y0d046w/Desktop/prosperity4-tester-private/trader-logic/round-2/data")
FV = 10000  # Known fair value for ACO
DAYS = [-2, -1, 0, 1]

def load_data():
    """Load and process price data for all days."""
    all_data = []

    for day in DAYS:
        df = pd.read_csv(DATA_DIR / f"prices_round_2_day_{day}.csv", sep=';')
        # Filter to ACO only
        aco = df[df['product'] == 'ASH_COATED_OSMIUM'].copy()
        aco['day'] = day
        all_data.append(aco)

    combined = pd.concat(all_data, ignore_index=True)
    return combined

def compute_features(df):
    """Compute all relevant features for analysis."""
    df = df.copy()

    # Basic features
    df['best_bid'] = df['bid_price_1']
    df['best_ask'] = df['ask_price_1']
    df['bid_vol'] = df['bid_volume_1']
    df['ask_vol'] = df['ask_volume_1']

    # Handle missing values for one-sided books
    df['mid'] = df['mid_price']

    # Spread (only when both sides exist)
    df['spread'] = np.where(
        (df['best_bid'].notna()) & (df['best_ask'].notna()),
        df['best_ask'] - df['best_bid'],
        np.nan
    )

    # Deviation from FV
    df['dev_from_fv'] = df['mid'] - FV

    # OBI (Order Book Imbalance) using L1 volumes
    df['total_vol'] = df['bid_vol'].fillna(0) + df['ask_vol'].fillna(0)
    df['obi'] = np.where(
        df['total_vol'] > 0,
        (df['bid_vol'].fillna(0) - df['ask_vol'].fillna(0)) / df['total_vol'],
        0
    )

    # Group by day to compute changes within each day
    results = []
    for day in df['day'].unique():
        day_df = df[df['day'] == day].copy()
        day_df = day_df.sort_values('timestamp').reset_index(drop=True)

        # Mid price change (forward-looking)
        day_df['delta_mid'] = day_df['mid'].shift(-1) - day_df['mid']
        day_df['delta_mid_lag'] = day_df['mid'] - day_df['mid'].shift(1)  # Previous change

        # Spread change
        day_df['spread_change'] = day_df['spread'] - day_df['spread'].shift(1)

        # Time quartile
        max_ts = day_df['timestamp'].max()
        day_df['time_quartile'] = pd.cut(
            day_df['timestamp'],
            bins=[-1, max_ts*0.25, max_ts*0.5, max_ts*0.75, max_ts+1],
            labels=['Q1', 'Q2', 'Q3', 'Q4']
        )

        results.append(day_df)

    return pd.concat(results, ignore_index=True)

def spread_regime_analysis(df):
    """
    1. Spread Regime Analysis
    Bucket spreads into regimes: tight (<=10), normal (11-17), wide (>=18)
    """
    print("\n" + "="*80)
    print("1. SPREAD REGIME ANALYSIS")
    print("="*80)

    # Define regimes
    def spread_regime(s):
        if pd.isna(s):
            return 'one_sided'
        elif s <= 10:
            return 'tight'
        elif s <= 17:
            return 'normal'
        else:
            return 'wide'

    df['spread_regime'] = df['spread'].apply(spread_regime)

    # For each regime, compute statistics
    regimes = ['tight', 'normal', 'wide']

    print("\n--- Per-Day Statistics by Spread Regime ---")
    for day in DAYS:
        day_df = df[df['day'] == day]
        print(f"\nDay {day}:")
        for regime in regimes:
            regime_df = day_df[day_df['spread_regime'] == regime]
            if len(regime_df) > 0:
                delta = regime_df['delta_mid'].dropna()
                if len(delta) > 0:
                    e_delta = delta.mean()
                    var_delta = delta.var()
                    p_large = (delta.abs() > 2).mean()
                    print(f"  {regime:8s}: N={len(delta):5d}, E[Dmid]={e_delta:+6.3f}, Var={var_delta:6.2f}, P(|Dmid|>2)={p_large:.3f}")

    # Aggregate across all days
    print("\n--- Aggregate Statistics (All Days) ---")
    for regime in regimes:
        regime_df = df[df['spread_regime'] == regime]
        delta = regime_df['delta_mid'].dropna()
        if len(delta) > 0:
            e_delta = delta.mean()
            var_delta = delta.var()
            p_large = (delta.abs() > 2).mean()
            print(f"  {regime:8s}: N={len(delta):5d}, E[Dmid]={e_delta:+6.3f}, Var={var_delta:6.2f}, P(|Dmid|>2)={p_large:.3f}")

    # Spread-dependent volatility pattern
    print("\n--- Spread-Volatility Relationship ---")
    spread_bins = [(0,8), (8,12), (12,16), (16,20), (20,30)]
    for lo, hi in spread_bins:
        subset = df[(df['spread'] >= lo) & (df['spread'] < hi)]
        delta = subset['delta_mid'].dropna()
        if len(delta) > 10:
            print(f"  Spread [{lo:2d},{hi:2d}): N={len(delta):5d}, Std(Dmid)={delta.std():.3f}, MAD={delta.abs().mean():.3f}")

    # Transition matrix
    print("\n--- Spread Regime Transition Matrix ---")
    df_sorted = df.sort_values(['day', 'timestamp'])
    df_sorted['next_regime'] = df_sorted.groupby('day')['spread_regime'].shift(-1)

    transitions = df_sorted[df_sorted['spread_regime'].isin(regimes) & df_sorted['next_regime'].isin(regimes)]
    trans_matrix = pd.crosstab(
        transitions['spread_regime'],
        transitions['next_regime'],
        normalize='index'
    )
    print(trans_matrix.round(3).to_string())

    return df

def deviation_regime_analysis(df):
    """
    2. Deviation-from-FV Regimes
    Bucket dev_from_FV: extreme_low (<-10), low (-10 to -5), neutral (-5 to +5),
    high (+5 to +10), extreme_high (>+10)
    """
    print("\n" + "="*80)
    print("2. DEVIATION FROM FAIR VALUE REGIME ANALYSIS")
    print("="*80)

    def dev_regime(d):
        if pd.isna(d):
            return 'unknown'
        elif d < -10:
            return 'extreme_low'
        elif d < -5:
            return 'low'
        elif d <= 5:
            return 'neutral'
        elif d <= 10:
            return 'high'
        else:
            return 'extreme_high'

    df['dev_regime'] = df['dev_from_fv'].apply(dev_regime)

    regimes = ['extreme_low', 'low', 'neutral', 'high', 'extreme_high']

    print("\n--- Per-Day Statistics by Deviation Regime ---")
    for day in DAYS:
        day_df = df[df['day'] == day]
        print(f"\nDay {day}:")
        for regime in regimes:
            regime_df = day_df[day_df['dev_regime'] == regime]
            if len(regime_df) > 0:
                delta = regime_df['delta_mid'].dropna()
                if len(delta) > 5:
                    e_delta = delta.mean()
                    skew = stats.skew(delta) if len(delta) > 10 else np.nan
                    # Mean reversion rate = -correlation(dev, delta)
                    dev = regime_df.loc[delta.index, 'dev_from_fv']
                    mr_rate = -np.corrcoef(dev, delta)[0,1] if len(delta) > 10 else np.nan
                    print(f"  {regime:12s}: N={len(delta):4d}, E[Dmid]={e_delta:+7.3f}, Skew={skew:+5.2f}, MR_rate={mr_rate:+5.3f}")

    # Aggregate across all days
    print("\n--- Aggregate Statistics (All Days) ---")
    for regime in regimes:
        regime_df = df[df['dev_regime'] == regime]
        delta = regime_df['delta_mid'].dropna()
        if len(delta) > 10:
            e_delta = delta.mean()
            skew = stats.skew(delta)
            dev = regime_df.loc[delta.index, 'dev_from_fv']
            mr_rate = -np.corrcoef(dev, delta)[0,1]
            print(f"  {regime:12s}: N={len(delta):5d}, E[Dmid]={e_delta:+7.3f}, Skew={skew:+5.2f}, MR_rate={mr_rate:+5.3f}")

    # Nonlinear mean-reversion analysis
    print("\n--- Nonlinear Mean-Reversion (E[Dmid] vs Deviation) ---")
    dev_bins = [(-30,-15), (-15,-10), (-10,-5), (-5,0), (0,5), (5,10), (10,15), (15,30)]
    all_days_results = []
    for lo, hi in dev_bins:
        subset = df[(df['dev_from_fv'] >= lo) & (df['dev_from_fv'] < hi)]
        delta = subset['delta_mid'].dropna()
        if len(delta) > 10:
            e_delta = delta.mean()
            se = delta.std() / np.sqrt(len(delta))
            all_days_results.append((lo, hi, len(delta), e_delta, se))
            # Check significance
            t_stat = e_delta / se if se > 0 else 0
            sig = '*' if abs(t_stat) > 2 else ''
            print(f"  Dev [{lo:+3d},{hi:+3d}): N={len(delta):5d}, E[Dmid]={e_delta:+6.3f} +/- {se:.3f} {sig}")

    return df

def volume_regime_analysis(df):
    """
    3. Volume Regimes
    Bucket total L1 vol: low (<10), normal (10-20), high (>20)
    """
    print("\n" + "="*80)
    print("3. VOLUME REGIME ANALYSIS")
    print("="*80)

    def vol_regime(v):
        if pd.isna(v) or v == 0:
            return 'empty'
        elif v < 10:
            return 'low'
        elif v <= 20:
            return 'normal'
        else:
            return 'high'

    df['vol_regime'] = df['total_vol'].apply(vol_regime)

    regimes = ['low', 'normal', 'high']

    print("\n--- Per-Day Statistics by Volume Regime ---")
    for day in DAYS:
        day_df = df[df['day'] == day]
        print(f"\nDay {day}:")
        for regime in regimes:
            regime_df = day_df[day_df['vol_regime'] == regime]
            if len(regime_df) > 0:
                delta = regime_df['delta_mid'].dropna()
                if len(delta) > 5:
                    e_delta = delta.mean()
                    vol_delta = delta.var()
                    print(f"  {regime:8s}: N={len(delta):5d}, E[Dmid]={e_delta:+6.3f}, Var={vol_delta:6.2f}, Std={delta.std():.3f}")

    # Aggregate
    print("\n--- Aggregate Statistics (All Days) ---")
    for regime in regimes:
        regime_df = df[df['vol_regime'] == regime]
        delta = regime_df['delta_mid'].dropna()
        if len(delta) > 10:
            e_delta = delta.mean()
            vol_delta = delta.var()
            print(f"  {regime:8s}: N={len(delta):5d}, E[Dmid]={e_delta:+6.3f}, Var={vol_delta:6.2f}, Std={delta.std():.3f}")

    # Predictability by volume regime (measured by |IC|)
    print("\n--- Predictability by Volume Regime ---")
    for regime in regimes:
        regime_df = df[df['vol_regime'] == regime]
        valid = regime_df[['dev_from_fv', 'delta_mid']].dropna()
        if len(valid) > 20:
            ic = np.corrcoef(valid['dev_from_fv'], valid['delta_mid'])[0,1]
            print(f"  {regime:8s}: IC(dev,Dmid) = {ic:+.4f} (N={len(valid)})")

    return df

def time_of_day_analysis(df):
    """
    4. Time-of-Day Effects
    Split each day into quartiles Q1-Q4 (by timestamp)
    """
    print("\n" + "="*80)
    print("4. TIME-OF-DAY EFFECTS")
    print("="*80)

    quartiles = ['Q1', 'Q2', 'Q3', 'Q4']

    print("\n--- Per-Day Statistics by Time Quartile ---")
    for day in DAYS:
        day_df = df[df['day'] == day]
        print(f"\nDay {day}:")
        for q in quartiles:
            q_df = day_df[day_df['time_quartile'] == q]
            if len(q_df) > 0:
                delta = q_df['delta_mid'].dropna()
                spread = q_df['spread'].dropna()
                vol = q_df['total_vol'].dropna()
                if len(delta) > 5:
                    print(f"  {q}: N={len(delta):4d}, E[Dmid]={delta.mean():+6.3f}, Var={delta.var():5.2f}, "
                          f"Spread={spread.mean():5.1f}, Vol={vol.mean():5.1f}")

    # Aggregate across all days
    print("\n--- Aggregate Statistics by Time Quartile (All Days) ---")
    for q in quartiles:
        q_df = df[df['time_quartile'] == q]
        delta = q_df['delta_mid'].dropna()
        spread = q_df['spread'].dropna()
        vol = q_df['total_vol'].dropna()
        if len(delta) > 20:
            print(f"  {q}: N={len(delta):5d}, E[Dmid]={delta.mean():+6.3f}, Var={delta.var():5.2f}, "
                  f"Spread={spread.mean():5.1f}, Vol={vol.mean():5.1f}")

    # Opening and closing patterns
    print("\n--- Opening (First 50 ticks) vs Closing (Last 50 ticks) ---")
    for day in DAYS:
        day_df = df[df['day'] == day].sort_values('timestamp')
        open_df = day_df.head(50)
        close_df = day_df.tail(50)

        open_delta = open_df['delta_mid'].dropna()
        close_delta = close_df['delta_mid'].dropna()

        print(f"  Day {day}: Open E[Dmid]={open_delta.mean():+6.3f}, Var={open_delta.var():5.2f} | "
              f"Close E[Dmid]={close_delta.mean():+6.3f}, Var={close_delta.var():5.2f}")

    return df

def conditional_pattern_analysis(df):
    """
    5. Conditional Patterns
    - E[Dmid(t+1) | Dmid(t) > 0] vs E[Dmid(t+1) | Dmid(t) < 0]
    - E[Dmid(t+1) | spread(t) increasing] vs decreasing
    - E[Dmid(t+1) | OBI(t) > 0.5] vs OBI(t) < -0.5
    """
    print("\n" + "="*80)
    print("5. CONDITIONAL PATTERN ANALYSIS")
    print("="*80)

    # Momentum vs Reversal
    print("\n--- Momentum vs Reversal in Price Changes ---")
    for day in DAYS:
        day_df = df[df['day'] == day]

        up_prev = day_df[day_df['delta_mid_lag'] > 0]['delta_mid'].dropna()
        down_prev = day_df[day_df['delta_mid_lag'] < 0]['delta_mid'].dropna()

        if len(up_prev) > 10 and len(down_prev) > 10:
            print(f"  Day {day}: After UP: E[Dmid]={up_prev.mean():+6.3f} (N={len(up_prev)}) | "
                  f"After DOWN: E[Dmid]={down_prev.mean():+6.3f} (N={len(down_prev)})")

    # Aggregate
    up_prev = df[df['delta_mid_lag'] > 0]['delta_mid'].dropna()
    down_prev = df[df['delta_mid_lag'] < 0]['delta_mid'].dropna()
    print(f"\n  ALL DAYS: After UP: E[Dmid]={up_prev.mean():+6.3f} (N={len(up_prev)}) | "
          f"After DOWN: E[Dmid]={down_prev.mean():+6.3f} (N={len(down_prev)})")
    # T-test
    if len(up_prev) > 30 and len(down_prev) > 30:
        t_stat, p_val = stats.ttest_ind(up_prev, down_prev)
        print(f"  t-test: t={t_stat:.3f}, p={p_val:.4f}")

    # Spread change effect
    print("\n--- Effect of Spread Changes on Next Price Move ---")
    for day in DAYS:
        day_df = df[df['day'] == day]

        spread_up = day_df[day_df['spread_change'] > 0]['delta_mid'].dropna()
        spread_down = day_df[day_df['spread_change'] < 0]['delta_mid'].dropna()

        if len(spread_up) > 10 and len(spread_down) > 10:
            print(f"  Day {day}: Spread UP: E[Dmid]={spread_up.mean():+6.3f} (N={len(spread_up)}) | "
                  f"Spread DOWN: E[Dmid]={spread_down.mean():+6.3f} (N={len(spread_down)})")

    # Aggregate
    spread_up = df[df['spread_change'] > 0]['delta_mid'].dropna()
    spread_down = df[df['spread_change'] < 0]['delta_mid'].dropna()
    print(f"\n  ALL DAYS: Spread UP: E[Dmid]={spread_up.mean():+6.3f} (N={len(spread_up)}) | "
          f"Spread DOWN: E[Dmid]={spread_down.mean():+6.3f} (N={len(spread_down)})")

    # OBI effect
    print("\n--- Effect of OBI on Next Price Move ---")
    for day in DAYS:
        day_df = df[df['day'] == day]

        obi_high = day_df[day_df['obi'] > 0.5]['delta_mid'].dropna()
        obi_low = day_df[day_df['obi'] < -0.5]['delta_mid'].dropna()

        if len(obi_high) > 10 and len(obi_low) > 10:
            print(f"  Day {day}: OBI > 0.5: E[Dmid]={obi_high.mean():+6.3f} (N={len(obi_high)}) | "
                  f"OBI < -0.5: E[Dmid]={obi_low.mean():+6.3f} (N={len(obi_low)})")

    # Aggregate
    obi_high = df[df['obi'] > 0.5]['delta_mid'].dropna()
    obi_low = df[df['obi'] < -0.5]['delta_mid'].dropna()
    print(f"\n  ALL DAYS: OBI > 0.5: E[Dmid]={obi_high.mean():+6.3f} (N={len(obi_high)}) | "
          f"OBI < -0.5: E[Dmid]={obi_low.mean():+6.3f} (N={len(obi_low)})")
    if len(obi_high) > 30 and len(obi_low) > 30:
        t_stat, p_val = stats.ttest_ind(obi_high, obi_low)
        print(f"  t-test: t={t_stat:.3f}, p={p_val:.4f}")

    return df

def joint_condition_analysis(df):
    """
    6. Joint Conditions
    Does combining signals work? E.g., E[Dmid | spread=tight AND dev_from_FV > 5]
    """
    print("\n" + "="*80)
    print("6. JOINT CONDITION ANALYSIS (Interaction Effects)")
    print("="*80)

    # Define useful subsets
    conditions = [
        ("tight_spread & high_dev",
         (df['spread'] <= 12) & (df['dev_from_fv'] > 5)),
        ("tight_spread & low_dev",
         (df['spread'] <= 12) & (df['dev_from_fv'] < -5)),
        ("wide_spread & high_dev",
         (df['spread'] >= 18) & (df['dev_from_fv'] > 5)),
        ("wide_spread & low_dev",
         (df['spread'] >= 18) & (df['dev_from_fv'] < -5)),
        ("high_obi & high_dev",
         (df['obi'] > 0.3) & (df['dev_from_fv'] > 5)),
        ("low_obi & low_dev",
         (df['obi'] < -0.3) & (df['dev_from_fv'] < -5)),
        ("high_obi & low_dev",
         (df['obi'] > 0.3) & (df['dev_from_fv'] < -5)),
        ("low_obi & high_dev",
         (df['obi'] < -0.3) & (df['dev_from_fv'] > 5)),
        ("tight & high_vol",
         (df['spread'] <= 12) & (df['total_vol'] > 20)),
        ("wide & low_vol",
         (df['spread'] >= 18) & (df['total_vol'] < 15)),
    ]

    print("\n--- Joint Condition Statistics (All Days) ---")
    print(f"{'Condition':<30} {'N':>6} {'E[Dmid]':>10} {'SE':>8} {'t-stat':>8}")
    print("-" * 70)

    for name, mask in conditions:
        subset = df[mask]
        delta = subset['delta_mid'].dropna()
        if len(delta) > 10:
            e_delta = delta.mean()
            se = delta.std() / np.sqrt(len(delta))
            t_stat = e_delta / se if se > 0 else 0
            sig = '**' if abs(t_stat) > 2.58 else ('*' if abs(t_stat) > 1.96 else '')
            print(f"{name:<30} {len(delta):6d} {e_delta:+10.4f} {se:8.4f} {t_stat:+8.3f} {sig}")

    # Per-day consistency check
    print("\n--- Consistency Check Across Days ---")
    key_conditions = [
        ("tight_spread & high_dev", (df['spread'] <= 12) & (df['dev_from_fv'] > 5)),
        ("tight_spread & low_dev", (df['spread'] <= 12) & (df['dev_from_fv'] < -5)),
    ]

    for name, mask in key_conditions:
        print(f"\n  {name}:")
        day_means = []
        for day in DAYS:
            day_df = df[(df['day'] == day) & mask]
            delta = day_df['delta_mid'].dropna()
            if len(delta) > 5:
                day_means.append(delta.mean())
                print(f"    Day {day}: E[Dmid]={delta.mean():+6.3f} (N={len(delta)})")

        if len(day_means) == 4:
            # Check sign consistency
            same_sign = all(m > 0 for m in day_means) or all(m < 0 for m in day_means)
            print(f"    Sign consistent across all days: {same_sign}")

    return df

def summary_statistics(df):
    """Print overall summary statistics for reference."""
    print("\n" + "="*80)
    print("SUMMARY STATISTICS")
    print("="*80)

    # Basic stats
    valid = df[df['mid'].notna()]
    print(f"\nTotal observations: {len(valid)}")
    print(f"Days: {sorted(df['day'].unique())}")

    # Per-day stats
    print("\n--- Per-Day Summary ---")
    for day in DAYS:
        day_df = df[df['day'] == day]
        valid_day = day_df[day_df['mid'].notna()]
        print(f"  Day {day}: N={len(valid_day)}, Mid range=[{valid_day['mid'].min():.0f}, {valid_day['mid'].max():.0f}], "
              f"Dev_FV range=[{valid_day['dev_from_fv'].min():+.0f}, {valid_day['dev_from_fv'].max():+.0f}]")

    # Spread distribution
    print("\n--- Spread Distribution ---")
    spreads = df['spread'].dropna()
    print(f"  Mean: {spreads.mean():.2f}, Median: {spreads.median():.0f}, Std: {spreads.std():.2f}")
    print(f"  Percentiles: 10%={spreads.quantile(0.1):.0f}, 50%={spreads.quantile(0.5):.0f}, 90%={spreads.quantile(0.9):.0f}")

    # One-sided book frequency
    one_sided = df[(df['best_bid'].isna()) | (df['best_ask'].isna())]
    print(f"\n  One-sided book ticks: {len(one_sided)} ({100*len(one_sided)/len(df):.1f}%)")

    # Overall mean-reversion coefficient
    print("\n--- Overall Mean-Reversion Analysis ---")
    valid = df[['dev_from_fv', 'delta_mid']].dropna()
    if len(valid) > 100:
        ic = np.corrcoef(valid['dev_from_fv'], valid['delta_mid'])[0,1]
        print(f"  IC(dev_from_fv, delta_mid) = {ic:.4f}")
        print(f"  Interpretation: {'Mean-reverting' if ic < 0 else 'Trending'} (negative = mean-reversion)")

def find_tradeable_signals(df):
    """
    Identify signals that are both statistically significant AND consistent across days.
    """
    print("\n" + "="*80)
    print("7. TRADEABLE SIGNAL IDENTIFICATION")
    print("="*80)

    # Test each condition for day-by-day consistency
    conditions = {
        "extreme_low_dev": df['dev_from_fv'] < -10,
        "extreme_high_dev": df['dev_from_fv'] > 10,
        "low_dev": (df['dev_from_fv'] >= -10) & (df['dev_from_fv'] < -5),
        "high_dev": (df['dev_from_fv'] > 5) & (df['dev_from_fv'] <= 10),
        "tight_spread": df['spread'] <= 10,
        "wide_spread": df['spread'] >= 18,
        "high_obi": df['obi'] > 0.5,
        "low_obi": df['obi'] < -0.5,
        "after_up_move": df['delta_mid_lag'] > 2,
        "after_down_move": df['delta_mid_lag'] < -2,
    }

    print("\n--- Signal Consistency Analysis ---")
    print(f"{'Signal':<25} {'Day -2':>10} {'Day -1':>10} {'Day 0':>10} {'Day 1':>10} {'Consistent':>12}")
    print("-" * 85)

    consistent_signals = []

    for name, mask in conditions.items():
        day_means = []
        day_ns = []
        for day in DAYS:
            day_df = df[(df['day'] == day) & mask]
            delta = day_df['delta_mid'].dropna()
            if len(delta) > 5:
                day_means.append(delta.mean())
                day_ns.append(len(delta))
            else:
                day_means.append(np.nan)
                day_ns.append(0)

        # Format output
        mean_strs = [f"{m:+.3f}" if not np.isnan(m) else "   N/A" for m in day_means]

        # Check consistency (same sign across all days with data)
        valid_means = [m for m in day_means if not np.isnan(m)]
        if len(valid_means) >= 3:
            same_sign = all(m > 0 for m in valid_means) or all(m < 0 for m in valid_means)
            if same_sign:
                avg_effect = np.mean(valid_means)
                consistent_signals.append((name, avg_effect, sum(day_ns)))
        else:
            same_sign = False

        print(f"{name:<25} {mean_strs[0]:>10} {mean_strs[1]:>10} {mean_strs[2]:>10} {mean_strs[3]:>10} {'YES' if same_sign else 'no':>12}")

    # Print actionable signals
    if consistent_signals:
        print("\n--- ACTIONABLE SIGNALS (Consistent Across Days) ---")
        for name, effect, n in sorted(consistent_signals, key=lambda x: abs(x[1]), reverse=True):
            direction = "BUY signal" if effect > 0 else "SELL signal"
            print(f"  {name}: E[Dmid] = {effect:+.4f} ({direction}, N={n})")

    return df

def main():
    print("="*80)
    print("ACO REGIME-BASED SIGNAL ANALYSIS FOR ROUND 2")
    print("="*80)

    # Load and prepare data
    print("\nLoading data...")
    df = load_data()
    print(f"Loaded {len(df)} total rows for ASH_COATED_OSMIUM")

    # Compute features
    df = compute_features(df)

    # Summary statistics
    summary_statistics(df)

    # Run all analyses
    df = spread_regime_analysis(df)
    df = deviation_regime_analysis(df)
    df = volume_regime_analysis(df)
    df = time_of_day_analysis(df)
    df = conditional_pattern_analysis(df)
    df = joint_condition_analysis(df)
    df = find_tradeable_signals(df)

    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)

if __name__ == "__main__":
    main()
