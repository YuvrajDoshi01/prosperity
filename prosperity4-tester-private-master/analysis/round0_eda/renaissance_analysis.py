"""
Renaissance-style multi-tick sequence mining for TOMATOES.
Analyses 1-7: Triplet sequences, spread sequences, volume patterns,
bid-ask move sequences, carry-over effect, position-in-range, clock patterns.
"""

import pandas as pd
import numpy as np
from scipy import stats
from itertools import product as cart_product
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

BASE = "/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0"

def load_tomatoes(day_suffix):
    """Load TOMATOES data from CSV, return DataFrame with derived columns."""
    path = f"{BASE}/prices_round_0_day_{day_suffix}.csv"
    df = pd.read_csv(path, sep=';')
    tom = df[df['product'] == 'TOMATOES'].copy().reset_index(drop=True)

    # Core series
    tom['mid'] = tom['mid_price']
    tom['best_bid'] = tom['bid_price_1']
    tom['best_ask'] = tom['ask_price_1']
    tom['spread'] = tom['best_ask'] - tom['best_bid']
    tom['dmid'] = tom['mid'].diff().shift(-1)  # mid[t+1] - mid[t], aligned to tick t
    tom['bid_vol_1'] = tom['bid_volume_1']
    tom['ask_vol_1'] = tom['ask_volume_1']
    tom['bid_vol_2'] = tom['bid_volume_2'].fillna(0)
    tom['ask_vol_2'] = tom['ask_volume_2'].fillna(0)
    tom['l1_total_vol'] = tom['bid_vol_1'] + tom['ask_vol_1']

    # Deltas
    tom['bid_delta'] = tom['best_bid'].diff()
    tom['ask_delta'] = tom['best_ask'].diff()

    # dmid categories
    def cat_dmid(x):
        if pd.isna(x): return None
        if x <= -2: return 'big_down'
        elif x <= -0.5: return 'small_down'
        elif x < 0.5: return 'zero'
        elif x < 2: return 'small_up'
        else: return 'big_up'

    # Actual dmid for categorization (current tick's move)
    tom['dmid_actual'] = tom['mid'].diff()  # mid[t] - mid[t-1]
    tom['dmid_cat'] = tom['dmid_actual'].apply(cat_dmid)

    return tom

print("Loading data...")
day0 = load_tomatoes('0')
daym1 = load_tomatoes('-1')
daym2 = load_tomatoes('-2')

# Combine in-sample
is_data = pd.concat([daym1, daym2], ignore_index=True)

print(f"Day 0 (OOS): {len(day0)} ticks, Day -1: {len(daym1)} ticks, Day -2: {len(daym2)} ticks")
print(f"In-sample: {len(is_data)} ticks")
print(f"Spread distribution (day 0): {day0['spread'].value_counts().sort_index().to_dict()}")
print(f"dmid stats (day 0): mean={day0['dmid'].mean():.4f}, std={day0['dmid'].std():.4f}")
print()

# ============================================================================
# UNCONDITIONAL BASELINE: Lag-1 AC prediction
# ============================================================================
print("="*80)
print("BASELINE: Unconditional lag-1 autocorrelation")
print("="*80)

for name, data in [("IS (day-1 + day-2)", is_data), ("OOS (day 0)", day0)]:
    dmid_curr = data['dmid_actual'].dropna()
    dmid_next = data['dmid'].dropna()
    # Align
    valid = data[['dmid_actual', 'dmid']].dropna()
    ac1 = valid['dmid_actual'].corr(valid['dmid'])
    print(f"  {name}: AC(1) = {ac1:.4f}, unconditional E[dmid] = {dmid_next.mean():.4f}")

print()

# ============================================================================
# ANALYSIS 1: Triplet Sequence Mining
# ============================================================================
print("="*80)
print("ANALYSIS 1: TRIPLET SEQUENCE MINING")
print("="*80)

cats = ['big_down', 'small_down', 'zero', 'small_up', 'big_up']

def triplet_analysis(data, label):
    """Compute E[dmid[t+3]] for each triplet (cat[t], cat[t+1], cat[t+2])."""
    # Build sequences
    data = data.copy()
    data['cat_0'] = data['dmid_cat']
    data['cat_1'] = data['dmid_cat'].shift(-1)
    data['cat_2'] = data['dmid_cat'].shift(-2)
    data['dmid_next3'] = data['dmid'].shift(-2)  # dmid at t+3 (= mid[t+4]-mid[t+3])

    results = {}
    for c0, c1, c2 in cart_product(cats, cats, cats):
        mask = (data['cat_0'] == c0) & (data['cat_1'] == c1) & (data['cat_2'] == c2)
        subset = data.loc[mask, 'dmid_next3'].dropna()
        if len(subset) >= 5:
            results[(c0, c1, c2)] = {
                'mean': subset.mean(),
                'std': subset.std(),
                'count': len(subset),
                'tstat': subset.mean() / (subset.std() / np.sqrt(len(subset))) if subset.std() > 0 else 0,
                'signal_strength': abs(subset.mean()) * np.sqrt(len(subset))
            }
    return results

is_triplets = triplet_analysis(is_data, "IS")
oos_triplets = triplet_analysis(day0, "OOS")

# Rank by signal strength in-sample
ranked = sorted(is_triplets.items(), key=lambda x: -x[1]['signal_strength'])

print(f"\nTop 30 triplets by |E[dmid]| * sqrt(N) (in-sample):")
print(f"{'Triplet':<40} {'IS_mean':>8} {'IS_N':>6} {'IS_t':>7} {'IS_sig':>8} {'OOS_mean':>9} {'OOS_N':>6} {'OOS_t':>7}")
print("-"*120)

significant_triplets = []
for trip, vals in ranked[:30]:
    oos = oos_triplets.get(trip, {})
    oos_mean = oos.get('mean', float('nan'))
    oos_n = oos.get('count', 0)
    oos_t = oos.get('tstat', float('nan'))

    is_sig = abs(vals['tstat']) >= 1.96
    oos_sig = abs(oos_t) >= 1.96 if not np.isnan(oos_t) else False
    marker = " ***" if (is_sig and oos_sig and np.sign(vals['mean']) == np.sign(oos_mean)) else ""

    print(f"  {str(trip):<38} {vals['mean']:>8.3f} {vals['count']:>6d} {vals['tstat']:>7.2f} {vals['signal_strength']:>8.2f} {oos_mean:>9.3f} {oos_n:>6d} {oos_t:>7.2f}{marker}")

    if is_sig and oos_sig and np.sign(vals['mean']) == np.sign(oos_mean):
        significant_triplets.append((trip, vals, oos))

print(f"\n*** = significant (p<0.05) on BOTH IS and OOS with same sign")
print(f"Significant triplets found: {len(significant_triplets)}")
for trip, is_v, oos_v in significant_triplets:
    print(f"  {trip}: IS E[dmid]={is_v['mean']:.3f} (t={is_v['tstat']:.2f}, N={is_v['count']}), OOS E[dmid]={oos_v['mean']:.3f} (t={oos_v['tstat']:.2f}, N={oos_v['count']})")

# ============================================================================
# ANALYSIS 2: Spread State Sequences
# ============================================================================
print("\n" + "="*80)
print("ANALYSIS 2: SPREAD STATE SEQUENCES")
print("="*80)

def spread_sequence_analysis(data, max_len=3):
    """Analyze E[dmid] after spread sequences of length 2 and 3."""
    data = data.copy()
    results = {}

    spreads = sorted(data['spread'].dropna().unique())
    print(f"  Unique spreads: {spreads}")

    for seq_len in [2, 3]:
        for combo in cart_product(spreads, repeat=seq_len):
            # Find all positions where this spread sequence occurs
            masks = []
            for i, s in enumerate(combo):
                masks.append(data['spread'].shift(-i) == s)
            mask = masks[0]
            for m in masks[1:]:
                mask = mask & m

            # dmid on the tick AFTER the sequence
            target = data['dmid'].shift(-(seq_len - 1))  # dmid at the last tick of sequence
            subset = target[mask].dropna()

            if len(subset) >= 10:
                mean_val = subset.mean()
                std_val = subset.std()
                n = len(subset)
                tstat = mean_val / (std_val / np.sqrt(n)) if std_val > 0 else 0
                results[combo] = {
                    'mean': mean_val, 'std': std_val, 'count': n,
                    'tstat': tstat, 'signal': abs(mean_val) * np.sqrt(n)
                }
    return results

is_spread = spread_sequence_analysis(is_data)
oos_spread = spread_sequence_analysis(day0)

# Rank by signal strength
ranked_spread = sorted(is_spread.items(), key=lambda x: -x[1]['signal'])

print(f"\nTop 25 spread sequences by signal strength (IS):")
print(f"{'Sequence':<30} {'IS_mean':>8} {'IS_N':>6} {'IS_t':>7} {'OOS_mean':>9} {'OOS_N':>6} {'OOS_t':>7}")
print("-"*100)

sig_spreads = []
for seq, vals in ranked_spread[:25]:
    oos = oos_spread.get(seq, {})
    oos_mean = oos.get('mean', float('nan'))
    oos_n = oos.get('count', 0)
    oos_t = oos.get('tstat', float('nan'))

    is_sig = abs(vals['tstat']) >= 1.96
    oos_sig = abs(oos_t) >= 1.96 if not np.isnan(oos_t) else False
    marker = " ***" if (is_sig and oos_sig and np.sign(vals['mean']) == np.sign(oos_mean)) else ""

    print(f"  {str(seq):<28} {vals['mean']:>8.3f} {vals['count']:>6d} {vals['tstat']:>7.2f} {oos_mean:>9.3f} {oos_n:>6d} {oos_t:>7.2f}{marker}")

    if is_sig and oos_sig and np.sign(vals['mean']) == np.sign(oos_mean):
        sig_spreads.append((seq, vals, oos))

print(f"\nSignificant spread sequences: {len(sig_spreads)}")
for seq, is_v, oos_v in sig_spreads:
    print(f"  {seq}: IS={is_v['mean']:.3f} (t={is_v['tstat']:.2f}, N={is_v['count']}), OOS={oos_v['mean']:.3f} (t={oos_v['tstat']:.2f}, N={oos_v['count']})")

# Special comparison: 13->narrow->wide vs 14->narrow->wide
print(f"\n  Special comparison: 13->narrow->wide vs 14->narrow->wide")
narrow = [5, 6, 7, 8, 9]
wide = [13, 14]
for entry_spread in [13, 14]:
    for narrow_s in narrow:
        for exit_spread in wide:
            key = (entry_spread, narrow_s, exit_spread)
            if key in is_spread:
                is_v = is_spread[key]
                oos_v = oos_spread.get(key, {})
                print(f"    {key}: IS mean={is_v['mean']:.3f} (N={is_v['count']}), OOS mean={oos_v.get('mean', float('nan')):.3f} (N={oos_v.get('count', 0)})")

# ============================================================================
# ANALYSIS 3: Volume Pattern Sequences
# ============================================================================
print("\n" + "="*80)
print("ANALYSIS 3: VOLUME PATTERN SEQUENCES")
print("="*80)

def volume_analysis(data, label):
    data = data.copy()

    # Discretize L1 total volume
    def vol_cat(x):
        if pd.isna(x): return None
        if x < 12: return 'low'
        elif x <= 16: return 'med'
        else: return 'high'

    data['vol_cat'] = data['l1_total_vol'].apply(vol_cat)

    print(f"\n  {label} volume distribution:")
    print(f"    {data['vol_cat'].value_counts().to_dict()}")
    print(f"    L1 total vol stats: mean={data['l1_total_vol'].mean():.1f}, median={data['l1_total_vol'].median():.1f}")

    vol_cats = ['low', 'med', 'high']
    results = {}

    for v0, v1 in cart_product(vol_cats, repeat=2):
        mask = (data['vol_cat'] == v0) & (data['vol_cat'].shift(-1) == v1)
        target = data['dmid'].shift(-1)  # dmid on next tick after 2-tick sequence
        subset = target[mask].dropna()

        if len(subset) >= 10:
            mean_val = subset.mean()
            std_val = subset.std()
            n = len(subset)
            tstat = mean_val / (std_val / np.sqrt(n)) if std_val > 0 else 0
            results[(v0, v1)] = {
                'mean': mean_val, 'std': std_val, 'count': n, 'tstat': tstat
            }
    return results

is_vol = volume_analysis(is_data, "IS")
oos_vol = volume_analysis(day0, "OOS")

print(f"\n  2-tick volume sequences:")
print(f"  {'Sequence':<20} {'IS_mean':>8} {'IS_N':>6} {'IS_t':>7} {'OOS_mean':>9} {'OOS_N':>6} {'OOS_t':>7}")
print("  " + "-"*70)

for seq in sorted(is_vol.keys()):
    vals = is_vol[seq]
    oos = oos_vol.get(seq, {})
    oos_mean = oos.get('mean', float('nan'))
    oos_n = oos.get('count', 0)
    oos_t = oos.get('tstat', float('nan'))

    is_sig = abs(vals['tstat']) >= 1.96
    oos_sig = abs(oos_t) >= 1.96 if not np.isnan(oos_t) else False
    marker = " ***" if (is_sig and oos_sig and np.sign(vals['mean']) == np.sign(oos_mean)) else ""

    print(f"  {str(seq):<20} {vals['mean']:>8.3f} {vals['count']:>6d} {vals['tstat']:>7.2f} {oos_mean:>9.3f} {oos_n:>6d} {oos_t:>7.2f}{marker}")

# Volume spike then drop
print(f"\n  Volume spike->drop analysis:")
for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()
    vol_change = data['l1_total_vol'].diff()
    spike_then_drop = (vol_change > 4) & (vol_change.shift(-1) < -4)
    target = data['dmid'].shift(-1)
    subset = target[spike_then_drop].dropna()
    if len(subset) > 0:
        tstat = subset.mean() / (subset.std() / np.sqrt(len(subset))) if subset.std() > 0 and len(subset) > 1 else 0
        print(f"    {name}: N={len(subset)}, E[dmid]={subset.mean():.3f}, t={tstat:.2f}")

# ============================================================================
# ANALYSIS 4: Bid-Ask Move Sequences
# ============================================================================
print("\n" + "="*80)
print("ANALYSIS 4: BID-ASK MOVE SEQUENCES")
print("="*80)

def classify_move(bid_d, ask_d):
    """Classify tick's move type from bid and ask deltas."""
    if pd.isna(bid_d) or pd.isna(ask_d):
        return None
    bid_d = round(bid_d, 1)
    ask_d = round(ask_d, 1)

    if bid_d > 0 and ask_d > 0:
        return 'both_up'
    elif bid_d < 0 and ask_d < 0:
        return 'both_down'
    elif bid_d > 0 and ask_d == 0:
        return 'bid_up_only'
    elif bid_d < 0 and ask_d == 0:
        return 'bid_down_only'
    elif bid_d == 0 and ask_d > 0:
        return 'ask_up_only'
    elif bid_d == 0 and ask_d < 0:
        return 'ask_down_only'
    elif bid_d > 0 and ask_d < 0:
        return 'spread_narrow'
    elif bid_d < 0 and ask_d > 0:
        return 'spread_widen'
    else:
        return 'no_move'

def bidask_move_analysis(data, label):
    data = data.copy()
    data['move_type'] = [classify_move(b, a) for b, a in zip(data['bid_delta'], data['ask_delta'])]

    print(f"\n  {label} move type distribution:")
    print(f"    {data['move_type'].value_counts().to_dict()}")

    move_types = data['move_type'].dropna().unique()
    results = {}

    for m0 in move_types:
        for m1 in move_types:
            mask = (data['move_type'] == m0) & (data['move_type'].shift(-1) == m1)
            target = data['dmid'].shift(-1)  # dmid after the 2-tick sequence
            subset = target[mask].dropna()

            if len(subset) >= 10:
                mean_val = subset.mean()
                std_val = subset.std()
                n = len(subset)
                tstat = mean_val / (std_val / np.sqrt(n)) if std_val > 0 else 0
                results[(m0, m1)] = {
                    'mean': mean_val, 'std': std_val, 'count': n, 'tstat': tstat,
                    'signal': abs(mean_val) * np.sqrt(n)
                }
    return results

is_moves = bidask_move_analysis(is_data, "IS")
oos_moves = bidask_move_analysis(day0, "OOS")

ranked_moves = sorted(is_moves.items(), key=lambda x: -x[1]['signal'])

print(f"\n  Top 20 bid-ask move sequences by signal strength:")
print(f"  {'Sequence':<45} {'IS_mean':>8} {'IS_N':>6} {'IS_t':>7} {'OOS_mean':>9} {'OOS_N':>6} {'OOS_t':>7}")
print("  " + "-"*90)

sig_moves = []
for seq, vals in ranked_moves[:20]:
    oos = oos_moves.get(seq, {})
    oos_mean = oos.get('mean', float('nan'))
    oos_n = oos.get('count', 0)
    oos_t = oos.get('tstat', float('nan'))

    is_sig = abs(vals['tstat']) >= 1.96
    oos_sig = abs(oos_t) >= 1.96 if not np.isnan(oos_t) else False
    marker = " ***" if (is_sig and oos_sig and np.sign(vals['mean']) == np.sign(oos_mean)) else ""

    print(f"  {str(seq):<43} {vals['mean']:>8.3f} {vals['count']:>6d} {vals['tstat']:>7.2f} {oos_mean:>9.3f} {oos_n:>6d} {oos_t:>7.2f}{marker}")

    if is_sig and oos_sig and np.sign(vals['mean']) == np.sign(oos_mean):
        sig_moves.append((seq, vals, oos))

print(f"\n  Significant move sequences: {len(sig_moves)}")
for seq, is_v, oos_v in sig_moves:
    print(f"    {seq}: IS={is_v['mean']:.3f} (t={is_v['tstat']:.2f}, N={is_v['count']}), OOS={oos_v['mean']:.3f} (t={oos_v['tstat']:.2f}, N={oos_v['count']})")

# Specific question: bid_up_only followed by no_move vs ask_down_only
print(f"\n  Specific comparison: bid_up_only -> no_move vs bid_up_only -> ask_down_only")
for key in [('bid_up_only', 'no_move'), ('bid_up_only', 'ask_down_only'), ('bid_up_only', 'both_down')]:
    is_v = is_moves.get(key, {})
    oos_v = oos_moves.get(key, {})
    if is_v:
        print(f"    {key}: IS mean={is_v['mean']:.3f} (N={is_v['count']}, t={is_v['tstat']:.2f}), OOS mean={oos_v.get('mean', float('nan')):.3f} (N={oos_v.get('count', 0)})")

# ============================================================================
# ANALYSIS 5: The "Carry Over" Effect
# ============================================================================
print("\n" + "="*80)
print("ANALYSIS 5: CARRY OVER EFFECT (Multi-tick reversion after big moves)")
print("="*80)

def carryover_analysis(data, label, thresholds=[3, 4, 5]):
    data = data.copy()
    data['dmid_actual'] = data['mid'].diff()

    horizons = [1, 2, 3, 5, 10, 20]

    for thresh in thresholds:
        print(f"\n  {label} -- |dmid| >= {thresh}:")

        # Big UP moves
        big_up = data.index[data['dmid_actual'] >= thresh].tolist()
        # Big DOWN moves
        big_down = data.index[data['dmid_actual'] <= -thresh].tolist()

        print(f"    Big UP events: {len(big_up)}, Big DOWN events: {len(big_down)}")

        for direction, events, sign_name in [(big_up, big_up, "after UP"), (big_down, big_down, "after DOWN")]:
            if len(events) < 5:
                continue

            print(f"    Cumulative return {sign_name} (N={len(events)}):")
            for h in horizons:
                cum_returns = []
                for idx in events:
                    if idx + h < len(data):
                        ret = data['mid'].iloc[idx + h] - data['mid'].iloc[idx]
                        cum_returns.append(ret)

                if len(cum_returns) >= 5:
                    arr = np.array(cum_returns)
                    mean_r = arr.mean()
                    se = arr.std() / np.sqrt(len(arr))
                    tstat = mean_r / se if se > 0 else 0
                    marker = " *" if abs(tstat) >= 1.96 else ""
                    print(f"      h={h:>2}: E[cum_ret]={mean_r:>7.3f}, se={se:.3f}, t={tstat:>6.2f}{marker}")

carryover_analysis(is_data, "IS", thresholds=[3, 4])
carryover_analysis(day0, "OOS", thresholds=[3, 4])

# Cross-validated: IS big moves, OOS continuation
print(f"\n  CROSS-VALIDATED carryover: effect measured separately")
for thresh in [3, 4]:
    for name, data in [("IS (day-1+day-2)", is_data), ("OOS (day 0)", day0)]:
        data = data.copy()
        data['dmid_actual'] = data['mid'].diff()

        big_up = data.index[data['dmid_actual'] >= thresh]
        big_down = data.index[data['dmid_actual'] <= -thresh]

        # Measure lag-1 to lag-5 individual tick returns (not cumulative)
        for direction, events, dname in [(big_up, big_up, "UP"), (big_down, big_down, "DOWN")]:
            if len(events) < 5:
                continue
            print(f"\n    {name} | {dname} (|dmid|>={thresh}, N={len(events)}) -- Per-tick returns:")
            for lag in [1, 2, 3, 4, 5]:
                tick_returns = []
                for idx in events:
                    if idx + lag < len(data):
                        ret = data['mid'].iloc[idx + lag] - data['mid'].iloc[idx + lag - 1]
                        tick_returns.append(ret)
                if len(tick_returns) >= 5:
                    arr = np.array(tick_returns)
                    mean_r = arr.mean()
                    se = arr.std() / np.sqrt(len(arr))
                    tstat = mean_r / se if se > 0 else 0
                    marker = " *" if abs(tstat) >= 1.96 else ""
                    print(f"      lag {lag}: E[dmid]={mean_r:>7.3f} (t={tstat:>6.2f}){marker}")

# ============================================================================
# ANALYSIS 6: Position-in-Range Effect
# ============================================================================
print("\n" + "="*80)
print("ANALYSIS 6: POSITION-IN-RANGE EFFECT")
print("="*80)

def range_analysis(data, label):
    data = data.copy()

    for window in [50, 100, 200]:
        roll_min = data['mid'].rolling(window, min_periods=window).min()
        roll_max = data['mid'].rolling(window, min_periods=window).max()
        pct = (data['mid'] - roll_min) / (roll_max - roll_min)
        data[f'pct_{window}'] = pct

        print(f"\n  {label} -- Window {window}:")

        for lo, hi, bucket_name in [(0, 0.1, "BOTTOM 10%"), (0.1, 0.3, "LOW 10-30%"),
                                       (0.3, 0.7, "MID 30-70%"), (0.7, 0.9, "HIGH 70-90%"),
                                       (0.9, 1.01, "TOP 90-100%")]:
            mask = (pct >= lo) & (pct < hi)
            subset = data.loc[mask, 'dmid'].dropna()
            if len(subset) >= 10:
                mean_val = subset.mean()
                se = subset.std() / np.sqrt(len(subset))
                tstat = mean_val / se if se > 0 else 0
                marker = " *" if abs(tstat) >= 1.96 else ""
                print(f"    {bucket_name:<15}: E[dmid]={mean_val:>7.4f}, N={len(subset):>5d}, t={tstat:>6.2f}{marker}")

range_analysis(is_data, "IS")
range_analysis(day0, "OOS")

# Detailed extreme percentile analysis
print(f"\n  EXTREME percentile mean-reversion test:")
for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()
    for window in [50, 100]:
        roll_min = data['mid'].rolling(window, min_periods=window).min()
        roll_max = data['mid'].rolling(window, min_periods=window).max()
        pct = (data['mid'] - roll_min) / (roll_max - roll_min)

        # At max (pct == 1.0)
        at_max = (pct == 1.0)
        subset_max = data.loc[at_max, 'dmid'].dropna()
        at_min = (pct == 0.0)
        subset_min = data.loc[at_min, 'dmid'].dropna()

        if len(subset_max) >= 5 and len(subset_min) >= 5:
            t_max = subset_max.mean() / (subset_max.std() / np.sqrt(len(subset_max))) if subset_max.std() > 0 else 0
            t_min = subset_min.mean() / (subset_min.std() / np.sqrt(len(subset_min))) if subset_min.std() > 0 else 0
            print(f"    {name} w={window}: At MAX E[dmid]={subset_max.mean():.4f} (N={len(subset_max)}, t={t_max:.2f}), At MIN E[dmid]={subset_min.mean():.4f} (N={len(subset_min)}, t={t_min:.2f})")

# ============================================================================
# ANALYSIS 7: Clock Patterns
# ============================================================================
print("\n" + "="*80)
print("ANALYSIS 7: CLOCK PATTERNS (tick position in cycle)")
print("="*80)

def clock_analysis(data, label):
    data = data.copy()

    for cycle_len in [10, 20, 50, 100]:
        data['tick_pos'] = (data['timestamp'] / 100).astype(int) % cycle_len

        # Kruskal-Wallis test: are dmid distributions different across positions?
        groups = [data.loc[data['tick_pos'] == pos, 'dmid'].dropna().values for pos in range(cycle_len)]
        groups = [g for g in groups if len(g) >= 5]

        if len(groups) >= 3:
            stat, p_val = stats.kruskal(*groups)
            print(f"\n  {label} -- Cycle length {cycle_len}:")
            print(f"    Kruskal-Wallis: H={stat:.2f}, p={p_val:.4f}")

            # Show positions with extreme means
            pos_stats = []
            for pos in range(cycle_len):
                subset = data.loc[data['tick_pos'] == pos, 'dmid'].dropna()
                if len(subset) >= 10:
                    mean_val = subset.mean()
                    se = subset.std() / np.sqrt(len(subset))
                    tstat = mean_val / se if se > 0 else 0
                    pos_stats.append((pos, mean_val, len(subset), tstat))

            # Sort by |t|
            pos_stats.sort(key=lambda x: -abs(x[3]))
            if pos_stats:
                print(f"    Top 5 positions by |t|:")
                for pos, mean_val, n, tstat in pos_stats[:5]:
                    marker = " *" if abs(tstat) >= 1.96 else ""
                    print(f"      pos={pos:>3d}: E[dmid]={mean_val:>7.4f}, N={n:>4d}, t={tstat:>6.2f}{marker}")

clock_analysis(is_data, "IS")
clock_analysis(day0, "OOS")

# Cross-validate: find IS-significant positions and check OOS
print(f"\n  CROSS-VALIDATION of clock effects:")
for cycle_len in [10, 20, 50]:
    is_sig_positions = []
    for pos in range(cycle_len):
        is_data_copy = is_data.copy()
        is_data_copy['tick_pos'] = (is_data_copy['timestamp'] / 100).astype(int) % cycle_len
        subset = is_data_copy.loc[is_data_copy['tick_pos'] == pos, 'dmid'].dropna()
        if len(subset) >= 10:
            tstat = subset.mean() / (subset.std() / np.sqrt(len(subset))) if subset.std() > 0 else 0
            if abs(tstat) >= 1.96:
                is_sig_positions.append((pos, subset.mean(), len(subset), tstat))

    if is_sig_positions:
        print(f"\n  Cycle {cycle_len}: {len(is_sig_positions)} IS-significant positions")
        day0_copy = day0.copy()
        day0_copy['tick_pos'] = (day0_copy['timestamp'] / 100).astype(int) % cycle_len
        for pos, is_mean, is_n, is_t in is_sig_positions:
            oos_subset = day0_copy.loc[day0_copy['tick_pos'] == pos, 'dmid'].dropna()
            if len(oos_subset) >= 5:
                oos_t = oos_subset.mean() / (oos_subset.std() / np.sqrt(len(oos_subset))) if oos_subset.std() > 0 else 0
                same_sign = np.sign(is_mean) == np.sign(oos_subset.mean())
                marker = " ***" if abs(oos_t) >= 1.96 and same_sign else ""
                print(f"    pos={pos}: IS mean={is_mean:.4f} (t={is_t:.2f}, N={is_n}), OOS mean={oos_subset.mean():.4f} (t={oos_t:.2f}, N={len(oos_subset)}){marker}")

# ============================================================================
# BONUS: Asymmetric move patterns (bid/ask move independently 82% of time)
# ============================================================================
print("\n" + "="*80)
print("BONUS: ASYMMETRIC QUOTE MOVE PATTERNS")
print("="*80)

def asymmetric_analysis(data, label):
    """Analyze when bid and ask move by different amounts."""
    data = data.copy()
    data['bid_move'] = data['best_bid'].diff()
    data['ask_move'] = data['best_ask'].diff()
    data['asymmetry'] = data['ask_move'] - data['bid_move']  # >0 means ask moved more than bid

    # Discretize asymmetry
    def asym_cat(x):
        if pd.isna(x): return None
        if x < -1: return 'bid_led_big'
        elif x < 0: return 'bid_led_small'
        elif x == 0: return 'symmetric'
        elif x <= 1: return 'ask_led_small'
        else: return 'ask_led_big'

    data['asym_cat'] = data['asymmetry'].apply(asym_cat)

    print(f"\n  {label} asymmetry distribution:")
    print(f"    {data['asym_cat'].value_counts().to_dict()}")

    # 2-tick sequences of asymmetry
    asym_cats = ['bid_led_big', 'bid_led_small', 'symmetric', 'ask_led_small', 'ask_led_big']
    results = {}

    for a0, a1 in cart_product(asym_cats, repeat=2):
        mask = (data['asym_cat'] == a0) & (data['asym_cat'].shift(-1) == a1)
        target = data['dmid'].shift(-1)
        subset = target[mask].dropna()

        if len(subset) >= 10:
            mean_val = subset.mean()
            se = subset.std() / np.sqrt(len(subset))
            tstat = mean_val / se if se > 0 else 0
            results[(a0, a1)] = {
                'mean': mean_val, 'count': len(subset), 'tstat': tstat,
                'signal': abs(mean_val) * np.sqrt(len(subset))
            }
    return results

is_asym = asymmetric_analysis(is_data, "IS")
oos_asym = asymmetric_analysis(day0, "OOS")

ranked_asym = sorted(is_asym.items(), key=lambda x: -x[1]['signal'])
print(f"\n  Top 15 asymmetry sequences:")
print(f"  {'Sequence':<50} {'IS_mean':>8} {'IS_N':>6} {'IS_t':>7} {'OOS_mean':>9} {'OOS_N':>6} {'OOS_t':>7}")
print("  " + "-"*90)

for seq, vals in ranked_asym[:15]:
    oos = oos_asym.get(seq, {})
    oos_mean = oos.get('mean', float('nan'))
    oos_n = oos.get('count', 0)
    oos_t = oos.get('tstat', float('nan'))

    is_sig = abs(vals['tstat']) >= 1.96
    oos_sig = abs(oos_t) >= 1.96 if not np.isnan(oos_t) else False
    marker = " ***" if (is_sig and oos_sig and np.sign(vals['mean']) == np.sign(oos_mean)) else ""

    print(f"  {str(seq):<48} {vals['mean']:>8.3f} {vals['count']:>6d} {vals['tstat']:>7.2f} {oos_mean:>9.3f} {oos_n:>6d} {oos_t:>7.2f}{marker}")

# ============================================================================
# FINAL SUMMARY
# ============================================================================
print("\n" + "="*80)
print("FINAL SUMMARY: ALL SIGNIFICANT FINDINGS (p<0.05 BOTH IS and OOS)")
print("="*80)

print(f"\n  Analysis 1 (Triplet sequences): {len(significant_triplets)} significant")
print(f"  Analysis 2 (Spread sequences): {len(sig_spreads)} significant")
print(f"  Analysis 4 (Bid-ask move sequences): {len(sig_moves)} significant")

# Compute estimated PnL for significant findings
print(f"\n  ESTIMATED PnL IMPACT (1 unit per signal, 2000 ticks):")
print(f"  Assuming we can act on signal by adjusting posting by 0.5 tick in predicted direction")
print()

# For each significant finding, estimate PnL
total_signals = 0
total_pnl = 0

for trip, is_v, oos_v in significant_triplets:
    # On OOS data: N signals, each worth ~E[dmid] * 0.5 (partial capture)
    freq_per_2k = oos_v['count']
    edge = abs(oos_v['mean']) * 0.5  # conservative: capture half the predicted move
    pnl = freq_per_2k * edge
    total_signals += freq_per_2k
    total_pnl += pnl
    print(f"    Triplet {trip}: {freq_per_2k} signals/2k ticks, edge={edge:.3f}, est PnL={pnl:.1f}")

for seq, is_v, oos_v in sig_spreads:
    freq_per_2k = oos_v['count']
    edge = abs(oos_v['mean']) * 0.5
    pnl = freq_per_2k * edge
    total_signals += freq_per_2k
    total_pnl += pnl
    print(f"    Spread seq {seq}: {freq_per_2k} signals/2k ticks, edge={edge:.3f}, est PnL={pnl:.1f}")

for seq, is_v, oos_v in sig_moves:
    freq_per_2k = oos_v['count']
    edge = abs(oos_v['mean']) * 0.5
    pnl = freq_per_2k * edge
    total_signals += freq_per_2k
    total_pnl += pnl
    print(f"    Move seq {seq}: {freq_per_2k} signals/2k ticks, edge={edge:.3f}, est PnL={pnl:.1f}")

print(f"\n    TOTAL: {total_signals} signals, est aggregate PnL = {total_pnl:.1f}")
print(f"    (Note: many signals overlap; actual unique PnL will be lower)")

# ============================================================================
# INCREMENTAL VALUE TEST: Do significant patterns add information beyond lag-1 AC?
# ============================================================================
print("\n" + "="*80)
print("INCREMENTAL VALUE: Regression test (pattern signal vs lag-1 AC)")
print("="*80)

from sklearn.linear_model import LinearRegression

for name, data in [("IS", is_data), ("OOS", day0)]:
    data = data.copy()
    data['dmid_actual'] = data['mid'].diff()
    data['dmid_lag1'] = data['dmid_actual']  # This is mid[t]-mid[t-1]

    # Create pattern features for significant triplets
    data['cat_0'] = data['dmid_cat']
    data['cat_1'] = data['dmid_cat'].shift(-1)
    data['cat_2'] = data['dmid_cat'].shift(-2)

    # Binary features for significant triplets
    for i, (trip, _, _) in enumerate(significant_triplets[:5]):  # Top 5
        mask = (data['cat_0'] == trip[0]) & (data['cat_1'] == trip[1]) & (data['cat_2'] == trip[2])
        data[f'trip_{i}'] = mask.astype(float)

    # Combine features
    feature_cols = ['dmid_lag1'] + [f'trip_{i}' for i in range(min(5, len(significant_triplets)))]
    valid = data[feature_cols + ['dmid']].dropna()

    if len(valid) > 50:
        X = valid[feature_cols].values
        y = valid['dmid'].values

        # Model 1: lag-1 only
        reg1 = LinearRegression().fit(X[:, :1], y)
        r2_1 = reg1.score(X[:, :1], y)

        # Model 2: lag-1 + patterns
        reg2 = LinearRegression().fit(X, y)
        r2_2 = reg2.score(X, y)

        print(f"  {name}: R2(lag-1 only)={r2_1:.6f}, R2(lag-1 + patterns)={r2_2:.6f}, increment={r2_2-r2_1:.6f}")
        if len(significant_triplets) > 0:
            print(f"    Pattern coefficients: {reg2.coef_[1:]}")

print("\nDone.")
