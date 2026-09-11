"""
ACO Regime-Based Signal Analysis for Round 2 - V2
==================================================
Refined analysis with proper handling of one-sided books and deeper signal validation.
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

def load_and_clean_data():
    """Load and process price data for all days, filtering out problematic ticks."""
    all_data = []

    for day in DAYS:
        df = pd.read_csv(DATA_DIR / f"prices_round_2_day_{day}.csv", sep=';')
        # Filter to ACO only
        aco = df[df['product'] == 'ASH_COATED_OSMIUM'].copy()
        aco['day'] = day
        all_data.append(aco)

    combined = pd.concat(all_data, ignore_index=True)

    # Filter to only two-sided books (both bid and ask present)
    combined = combined[
        (combined['bid_price_1'].notna()) &
        (combined['ask_price_1'].notna()) &
        (combined['mid_price'] > 0)  # Filter out broken mid calculations
    ].copy()

    return combined

def compute_features(df):
    """Compute all relevant features for analysis."""
    df = df.copy()

    # Basic features
    df['best_bid'] = df['bid_price_1']
    df['best_ask'] = df['ask_price_1']
    df['bid_vol'] = df['bid_volume_1']
    df['ask_vol'] = df['ask_volume_1']
    df['mid'] = df['mid_price']

    # Spread
    df['spread'] = df['best_ask'] - df['best_bid']

    # Deviation from FV
    df['dev_from_fv'] = df['mid'] - FV

    # Microprice
    df['microprice'] = (df['best_bid'] * df['ask_vol'] + df['best_ask'] * df['bid_vol']) / (df['bid_vol'] + df['ask_vol'])

    # OBI (Order Book Imbalance) using L1 volumes
    df['total_vol'] = df['bid_vol'] + df['ask_vol']
    df['obi'] = (df['bid_vol'] - df['ask_vol']) / df['total_vol']

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

def compute_signal_statistics(df, mask, name="signal"):
    """Compute comprehensive statistics for a signal condition."""
    day_results = {}
    for day in DAYS:
        day_df = df[(df['day'] == day) & mask]
        delta = day_df['delta_mid'].dropna()
        if len(delta) > 5:
            day_results[day] = {
                'n': len(delta),
                'mean': delta.mean(),
                'std': delta.std(),
                'se': delta.std() / np.sqrt(len(delta)),
            }
        else:
            day_results[day] = None

    # Aggregate
    all_delta = df[mask]['delta_mid'].dropna()
    if len(all_delta) > 10:
        agg = {
            'n': len(all_delta),
            'mean': all_delta.mean(),
            'std': all_delta.std(),
            'se': all_delta.std() / np.sqrt(len(all_delta)),
            't_stat': all_delta.mean() / (all_delta.std() / np.sqrt(len(all_delta))) if all_delta.std() > 0 else 0
        }
    else:
        agg = None

    # Check consistency
    valid_means = [r['mean'] for r in day_results.values() if r is not None]
    if len(valid_means) >= 3:
        same_sign = all(m > 0 for m in valid_means) or all(m < 0 for m in valid_means)
    else:
        same_sign = False

    return day_results, agg, same_sign

def print_summary(df):
    """Print summary statistics."""
    print("="*80)
    print("DATA SUMMARY (Two-Sided Books Only)")
    print("="*80)

    print(f"\nTotal observations: {len(df)}")
    for day in DAYS:
        day_df = df[df['day'] == day]
        print(f"  Day {day}: N={len(day_df)}, Mid range=[{day_df['mid'].min():.0f}, {day_df['mid'].max():.0f}], "
              f"Dev range=[{day_df['dev_from_fv'].min():+.0f}, {day_df['dev_from_fv'].max():+.0f}]")

    print("\n--- Spread Statistics ---")
    spreads = df['spread']
    print(f"  Mean: {spreads.mean():.2f}, Std: {spreads.std():.2f}")
    print(f"  Distribution: ", end='')
    for pct in [10, 25, 50, 75, 90]:
        print(f"p{pct}={spreads.quantile(pct/100):.0f} ", end='')
    print()

    print("\n--- Overall Mean-Reversion ---")
    valid = df[['dev_from_fv', 'delta_mid']].dropna()
    ic = np.corrcoef(valid['dev_from_fv'], valid['delta_mid'])[0,1]
    print(f"  IC(dev_from_fv, delta_mid) = {ic:.4f}")

    # AC(1) of mid changes
    ac1 = df['delta_mid'].dropna().autocorr(lag=1)
    print(f"  AC(1) of delta_mid = {ac1:.4f}")

def analyze_spread_regimes(df):
    """Spread regime analysis with proper statistics."""
    print("\n" + "="*80)
    print("1. SPREAD REGIME ANALYSIS")
    print("="*80)

    # Define regimes using quantiles
    p33, p66 = df['spread'].quantile([0.33, 0.66])
    print(f"\nSpread quantiles: p33={p33:.0f}, p66={p66:.0f}")

    def spread_regime(s):
        if s <= p33:
            return 'tight'
        elif s <= p66:
            return 'normal'
        else:
            return 'wide'

    df['spread_regime'] = df['spread'].apply(spread_regime)

    # Statistics by regime
    print("\n--- Per-Regime Statistics (All Days) ---")
    print(f"{'Regime':<12} {'N':>8} {'E[Dmid]':>12} {'Std':>10} {'P(|D|>2)':>10}")
    print("-"*54)

    for regime in ['tight', 'normal', 'wide']:
        delta = df[df['spread_regime'] == regime]['delta_mid'].dropna()
        if len(delta) > 10:
            p_large = (delta.abs() > 2).mean()
            print(f"{regime:<12} {len(delta):8d} {delta.mean():+12.4f} {delta.std():10.4f} {p_large:10.4f}")

    # Transition matrix
    print("\n--- Spread Regime Transition Matrix P(next | current) ---")
    df_sorted = df.sort_values(['day', 'timestamp'])
    df_sorted['next_regime'] = df_sorted.groupby('day')['spread_regime'].shift(-1)

    trans_matrix = pd.crosstab(
        df_sorted['spread_regime'],
        df_sorted['next_regime'],
        normalize='index'
    )
    print(trans_matrix.round(3).to_string())

    # Key finding: Does spread predict volatility?
    print("\n--- Spread vs Volatility (Std of Dmid) ---")
    for spread_val in range(12, 22, 2):
        subset = df[(df['spread'] >= spread_val) & (df['spread'] < spread_val + 2)]
        delta = subset['delta_mid'].dropna()
        if len(delta) > 50:
            print(f"  Spread [{spread_val:2d},{spread_val+2:2d}): N={len(delta):5d}, Std(Dmid)={delta.std():.4f}")

    return df

def analyze_deviation_regimes(df):
    """Deviation from FV regime analysis."""
    print("\n" + "="*80)
    print("2. DEVIATION FROM FV REGIME ANALYSIS")
    print("="*80)

    # Buckets
    dev_bins = [(-25,-15), (-15,-10), (-10,-5), (-5,0), (0,5), (5,10), (10,15), (15,25)]

    print("\n--- E[Dmid] by Deviation Bucket (CRITICAL for Mean-Reversion) ---")
    print(f"{'Bucket':<15} {'N':>7} {'E[Dmid]':>12} {'SE':>10} {'t-stat':>8} {'Sig':>5}")
    print("-"*60)

    for lo, hi in dev_bins:
        subset = df[(df['dev_from_fv'] >= lo) & (df['dev_from_fv'] < hi)]
        delta = subset['delta_mid'].dropna()
        if len(delta) > 10:
            e_delta = delta.mean()
            se = delta.std() / np.sqrt(len(delta))
            t_stat = e_delta / se if se > 0 else 0
            sig = '***' if abs(t_stat) > 3.29 else ('**' if abs(t_stat) > 2.58 else ('*' if abs(t_stat) > 1.96 else ''))
            print(f"[{lo:+3d},{hi:+3d})       {len(delta):7d} {e_delta:+12.4f} {se:10.4f} {t_stat:+8.3f} {sig:>5}")

    # Day-by-day consistency for extreme deviations
    print("\n--- Day-by-Day Consistency: Extreme Deviations ---")

    extreme_low_mask = df['dev_from_fv'] < -10
    extreme_high_mask = df['dev_from_fv'] > 10

    print("\n  Extreme LOW (dev < -10):")
    for day in DAYS:
        delta = df[(df['day'] == day) & extreme_low_mask]['delta_mid'].dropna()
        if len(delta) > 5:
            print(f"    Day {day}: E[Dmid]={delta.mean():+8.4f}, N={len(delta)}")

    print("\n  Extreme HIGH (dev > 10):")
    for day in DAYS:
        delta = df[(df['day'] == day) & extreme_high_mask]['delta_mid'].dropna()
        if len(delta) > 5:
            print(f"    Day {day}: E[Dmid]={delta.mean():+8.4f}, N={len(delta)}")

    # Regression: Delta_mid = alpha + beta * dev_from_fv
    print("\n--- Linear Mean-Reversion Regression ---")
    valid = df[['dev_from_fv', 'delta_mid']].dropna()
    slope, intercept, r_value, p_value, std_err = stats.linregress(valid['dev_from_fv'], valid['delta_mid'])
    print(f"  Dmid = {intercept:+.4f} + ({slope:+.4f}) * dev_from_fv")
    print(f"  R-squared: {r_value**2:.4f}, p-value: {p_value:.2e}")
    print(f"  Interpretation: {abs(slope)*100:.2f}% of deviation is corrected per tick on average")

    return df

def analyze_momentum_reversal(df):
    """Analyze momentum vs reversal patterns."""
    print("\n" + "="*80)
    print("3. MOMENTUM VS REVERSAL ANALYSIS")
    print("="*80)

    # After UP move
    print("\n--- After UP vs DOWN Moves (Lagged Analysis) ---")
    print(f"{'Day':<8} {'After UP':>20} {'After DOWN':>20}")
    print("-"*50)

    for day in DAYS:
        day_df = df[df['day'] == day]
        up_delta = day_df[day_df['delta_mid_lag'] > 0]['delta_mid'].dropna()
        down_delta = day_df[day_df['delta_mid_lag'] < 0]['delta_mid'].dropna()
        if len(up_delta) > 10 and len(down_delta) > 10:
            print(f"{day:+3d}      {up_delta.mean():+10.4f} (N={len(up_delta):4d}) {down_delta.mean():+10.4f} (N={len(down_delta):4d})")

    # Aggregate
    up_delta = df[df['delta_mid_lag'] > 0]['delta_mid'].dropna()
    down_delta = df[df['delta_mid_lag'] < 0]['delta_mid'].dropna()
    print("-"*50)
    print(f"{'ALL':<8} {up_delta.mean():+10.4f} (N={len(up_delta):4d}) {down_delta.mean():+10.4f} (N={len(down_delta):4d})")

    # Statistical test
    t_stat, p_val = stats.ttest_ind(up_delta, down_delta)
    print(f"\n  t-test: t={t_stat:.3f}, p={p_val:.2e}")
    print(f"  Conclusion: {'STRONG REVERSAL' if p_val < 0.01 and up_delta.mean() * down_delta.mean() < 0 else 'No clear pattern'}")

    # By magnitude of previous move
    print("\n--- By Magnitude of Previous Move ---")
    move_bins = [(0, 0.5), (0.5, 1), (1, 2), (2, 5), (5, 20)]

    print("\n  After UP moves of size:")
    for lo, hi in move_bins:
        subset = df[(df['delta_mid_lag'] > lo) & (df['delta_mid_lag'] <= hi)]
        delta = subset['delta_mid'].dropna()
        if len(delta) > 50:
            print(f"    ({lo:.1f},{hi:.1f}]: E[Dmid]={delta.mean():+8.4f}, N={len(delta)}")

    print("\n  After DOWN moves of size:")
    for lo, hi in move_bins:
        subset = df[(df['delta_mid_lag'] < -lo) & (df['delta_mid_lag'] >= -hi)]
        delta = subset['delta_mid'].dropna()
        if len(delta) > 50:
            print(f"    ({lo:.1f},{hi:.1f}]: E[Dmid]={delta.mean():+8.4f}, N={len(delta)}")

    return df

def analyze_obi_signal(df):
    """Analyze Order Book Imbalance signal."""
    print("\n" + "="*80)
    print("4. ORDER BOOK IMBALANCE (OBI) ANALYSIS")
    print("="*80)

    # OBI distribution
    print("\n--- OBI Distribution ---")
    obi = df['obi']
    print(f"  Mean: {obi.mean():.4f}, Std: {obi.std():.4f}")
    print(f"  Distribution: p10={obi.quantile(0.1):.2f}, p50={obi.quantile(0.5):.2f}, p90={obi.quantile(0.9):.2f}")

    # OBI buckets
    obi_bins = [(-1, -0.7), (-0.7, -0.4), (-0.4, -0.1), (-0.1, 0.1), (0.1, 0.4), (0.4, 0.7), (0.7, 1)]

    print("\n--- E[Dmid] by OBI Bucket ---")
    print(f"{'OBI Range':<15} {'N':>7} {'E[Dmid]':>12} {'SE':>10} {'t-stat':>8}")
    print("-"*55)

    for lo, hi in obi_bins:
        subset = df[(df['obi'] >= lo) & (df['obi'] < hi)]
        delta = subset['delta_mid'].dropna()
        if len(delta) > 20:
            e_delta = delta.mean()
            se = delta.std() / np.sqrt(len(delta))
            t_stat = e_delta / se if se > 0 else 0
            sig = '*' if abs(t_stat) > 1.96 else ''
            print(f"[{lo:+.1f},{hi:+.1f})      {len(delta):7d} {e_delta:+12.4f} {se:10.4f} {t_stat:+8.3f} {sig}")

    # Day-by-day consistency
    print("\n--- OBI Day-by-Day Consistency ---")
    high_obi = df['obi'] > 0.5
    low_obi = df['obi'] < -0.5

    print("\n  High OBI (> 0.5):")
    for day in DAYS:
        delta = df[(df['day'] == day) & high_obi]['delta_mid'].dropna()
        if len(delta) > 10:
            print(f"    Day {day}: E[Dmid]={delta.mean():+8.4f}, N={len(delta)}")

    print("\n  Low OBI (< -0.5):")
    for day in DAYS:
        delta = df[(df['day'] == day) & low_obi]['delta_mid'].dropna()
        if len(delta) > 10:
            print(f"    Day {day}: E[Dmid]={delta.mean():+8.4f}, N={len(delta)}")

    return df

def analyze_joint_signals(df):
    """Analyze interaction effects between signals."""
    print("\n" + "="*80)
    print("5. JOINT SIGNAL ANALYSIS (Interaction Effects)")
    print("="*80)

    # Key joint conditions
    conditions = [
        # Deviation + OBI alignment (should reinforce)
        ("high_dev + low_obi (bearish alignment)",
         (df['dev_from_fv'] > 5) & (df['obi'] < -0.3)),
        ("low_dev + high_obi (bullish alignment)",
         (df['dev_from_fv'] < -5) & (df['obi'] > 0.3)),

        # Deviation + OBI conflict (should weaken)
        ("high_dev + high_obi (conflict)",
         (df['dev_from_fv'] > 5) & (df['obi'] > 0.3)),
        ("low_dev + low_obi (conflict)",
         (df['dev_from_fv'] < -5) & (df['obi'] < -0.3)),

        # Spread + Deviation
        ("tight_spread + extreme_dev",
         (df['spread'] <= 14) & (df['dev_from_fv'].abs() > 8)),
        ("wide_spread + extreme_dev",
         (df['spread'] >= 18) & (df['dev_from_fv'].abs() > 8)),

        # Momentum + Deviation
        ("after_up + high_dev (double sell)",
         (df['delta_mid_lag'] > 1) & (df['dev_from_fv'] > 5)),
        ("after_down + low_dev (double buy)",
         (df['delta_mid_lag'] < -1) & (df['dev_from_fv'] < -5)),
    ]

    print("\n--- Joint Condition Statistics ---")
    print(f"{'Condition':<40} {'N':>6} {'E[Dmid]':>12} {'SE':>10} {'t':>8} {'Consistent':>12}")
    print("-"*95)

    for name, mask in conditions:
        day_results, agg, consistent = compute_signal_statistics(df, mask, name)
        if agg is not None:
            sig = '**' if abs(agg['t_stat']) > 2.58 else ('*' if abs(agg['t_stat']) > 1.96 else '')
            con_str = 'YES' if consistent else 'no'
            print(f"{name:<40} {agg['n']:6d} {agg['mean']:+12.4f} {agg['se']:10.4f} {agg['t_stat']:+8.2f}{sig:>3} {con_str:>12}")

    return df

def identify_actionable_signals(df):
    """Identify and rank signals by actionability."""
    print("\n" + "="*80)
    print("6. ACTIONABLE SIGNAL SUMMARY")
    print("="*80)

    signals = []

    # Test each signal
    signal_defs = [
        ("extreme_low_dev (<-10)", df['dev_from_fv'] < -10),
        ("low_dev (-10 to -5)", (df['dev_from_fv'] >= -10) & (df['dev_from_fv'] < -5)),
        ("high_dev (5 to 10)", (df['dev_from_fv'] > 5) & (df['dev_from_fv'] <= 10)),
        ("extreme_high_dev (>10)", df['dev_from_fv'] > 10),
        ("after_large_up (>2)", df['delta_mid_lag'] > 2),
        ("after_large_down (<-2)", df['delta_mid_lag'] < -2),
        ("high_obi (>0.5)", df['obi'] > 0.5),
        ("low_obi (<-0.5)", df['obi'] < -0.5),
        ("tight_spread (<=14)", df['spread'] <= 14),
        ("wide_spread (>=18)", df['spread'] >= 18),
        ("bearish_alignment (high_dev + low_obi)", (df['dev_from_fv'] > 5) & (df['obi'] < -0.2)),
        ("bullish_alignment (low_dev + high_obi)", (df['dev_from_fv'] < -5) & (df['obi'] > 0.2)),
    ]

    print("\n--- All Signals (Sorted by |E[Dmid]|) ---")
    print(f"{'Signal':<45} {'N':>6} {'E[Dmid]':>10} {'SE':>8} {'t':>7} {'Days':>6}")
    print("-"*85)

    results = []
    for name, mask in signal_defs:
        day_results, agg, consistent = compute_signal_statistics(df, mask, name)
        if agg is not None:
            n_days = sum(1 for d in day_results.values() if d is not None)
            results.append({
                'name': name,
                'n': agg['n'],
                'mean': agg['mean'],
                'se': agg['se'],
                't_stat': agg['t_stat'],
                'n_days': n_days,
                'consistent': consistent
            })

    # Sort by absolute effect size
    results.sort(key=lambda x: abs(x['mean']), reverse=True)

    for r in results:
        sig = '**' if abs(r['t_stat']) > 2.58 else ('*' if abs(r['t_stat']) > 1.96 else '')
        con = 'Y' if r['consistent'] else 'n'
        print(f"{r['name']:<45} {r['n']:6d} {r['mean']:+10.4f} {r['se']:8.4f} {r['t_stat']:+7.2f}{sig:>2} {r['n_days']:3d}/4 {con}")

    # Final recommendations
    print("\n" + "="*80)
    print("FINAL RECOMMENDATIONS")
    print("="*80)

    # Filter for consistent, significant signals
    actionable = [r for r in results if r['consistent'] and abs(r['t_stat']) > 1.96]

    print("\n--- CONFIRMED ACTIONABLE SIGNALS (Consistent + Significant) ---")
    for r in actionable:
        direction = "BUY" if r['mean'] > 0 else "SELL"
        print(f"  {direction}: {r['name']}")
        print(f"       E[Dmid] = {r['mean']:+.4f} (t={r['t_stat']:+.2f}, N={r['n']})")

    return df

def main():
    print("="*80)
    print("ACO REGIME-BASED SIGNAL ANALYSIS V2 (Refined)")
    print("="*80)

    # Load and clean data
    print("\nLoading data (filtering to two-sided books only)...")
    df = load_and_clean_data()
    print(f"Loaded {len(df)} clean observations for ASH_COATED_OSMIUM")

    # Compute features
    df = compute_features(df)

    # Run analyses
    print_summary(df)
    df = analyze_spread_regimes(df)
    df = analyze_deviation_regimes(df)
    df = analyze_momentum_reversal(df)
    df = analyze_obi_signal(df)
    df = analyze_joint_signals(df)
    df = identify_actionable_signals(df)

    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)

if __name__ == "__main__":
    main()
