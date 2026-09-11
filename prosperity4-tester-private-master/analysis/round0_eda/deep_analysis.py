#!/usr/bin/env python3
"""
Deep statistical analysis of IMC Prosperity 4 market data.
Looking for exploitable patterns beyond what's been tried.
"""

import pandas as pd
import numpy as np
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

BASE = "prosperity4bt/resources/round0/"

# Load all price data
days = {}
for d in [-2, -1, 0]:
    df = pd.read_csv(f"{BASE}prices_round_0_day_{d}.csv", sep=";")
    days[d] = df

# Load all trade data
trades = {}
for d in [-2, -1, 0]:
    df = pd.read_csv(f"{BASE}trades_round_0_day_{d}.csv", sep=";")
    trades[d] = df

print("=" * 80)
print("SECTION 1: DATA OVERVIEW")
print("=" * 80)
for d, df in days.items():
    print(f"\nDay {d}: {len(df)} rows, timestamps {df['timestamp'].min()} to {df['timestamp'].max()}")
    for prod in df['product'].unique():
        sub = df[df['product'] == prod]
        print(f"  {prod}: {len(sub)} ticks, mid range [{sub['mid_price'].min()}, {sub['mid_price'].max()}]")

# Split by product for each day
def get_product(day_df, product):
    return day_df[day_df['product'] == product].copy().reset_index(drop=True)

print("\n" + "=" * 80)
print("SECTION 2: INTRADAY SEASONALITY")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    for prod in ['TOMATOES', 'EMERALDS']:
        df = get_product(days[d], prod)
        df['spread'] = df['ask_price_1'] - df['bid_price_1']
        df['time_bucket'] = (df['timestamp'] // 100000)  # 100-second buckets

        # Spread by time bucket
        spread_by_time = df.groupby('time_bucket')['spread'].agg(['mean', 'std', 'count'])

        # Mid-price absolute change
        df['mid_change'] = df['mid_price'].diff()
        df['abs_mid_change'] = df['mid_change'].abs()
        vol_by_time = df.groupby('time_bucket')['abs_mid_change'].mean()

        # L1 volume by time
        df['l1_vol'] = df['bid_volume_1'] + df['ask_volume_1']
        l1_by_time = df.groupby('time_bucket')['l1_vol'].mean()

        print(f"\n  {prod} - Spread by 100s bucket:")
        for bucket in sorted(spread_by_time.index):
            row = spread_by_time.loc[bucket]
            v = vol_by_time.get(bucket, 0)
            l1 = l1_by_time.get(bucket, 0)
            print(f"    t={int(bucket)*100:>7}s: spread={row['mean']:5.1f} (std={row['std']:4.1f}), "
                  f"vol={v:5.2f}, L1_vol={l1:5.1f}, n={int(row['count'])}")

print("\n" + "=" * 80)
print("SECTION 2b: FINER SEASONALITY (20-second buckets)")
print("=" * 80)

for d in [0]:  # Focus on day 0 (matches website)
    print(f"\n--- Day {d} ---")
    for prod in ['TOMATOES']:
        df = get_product(days[d], prod)
        df['spread'] = df['ask_price_1'] - df['bid_price_1']
        df['mid_change'] = df['mid_price'].diff()
        df['time_bucket_20s'] = (df['timestamp'] // 20000)

        spread_20s = df.groupby('time_bucket_20s')['spread'].mean()
        # Check for periods with systematically narrow spreads
        narrow_mask = df['spread'] <= 9
        narrow_pct_by_time = df.groupby('time_bucket_20s')['spread'].apply(lambda x: (x <= 9).mean())

        print(f"\n  {prod} - Narrow spread frequency (<=9) by 20s bucket:")
        for bucket in sorted(narrow_pct_by_time.index[:50]):  # first 50 buckets
            pct = narrow_pct_by_time.loc[bucket]
            if pct > 0:
                avg = spread_20s.loc[bucket]
                print(f"    t={int(bucket)*20:>6}s: narrow_pct={pct:5.1%}, avg_spread={avg:5.1f}")


print("\n" + "=" * 80)
print("SECTION 3: RUN-LENGTH ANALYSIS")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    for prod in ['TOMATOES']:
        df = get_product(days[d], prod)
        df['mid_change'] = df['mid_price'].diff()
        df['direction'] = np.sign(df['mid_change'])

        # Compute run lengths
        runs = []
        current_dir = 0
        current_len = 0
        current_sum = 0
        for i in range(1, len(df)):
            d_val = df['direction'].iloc[i]
            if d_val == 0:
                continue
            if d_val == current_dir:
                current_len += 1
                current_sum += df['mid_change'].iloc[i]
            else:
                if current_len > 0:
                    runs.append((current_dir, current_len, current_sum))
                current_dir = d_val
                current_len = 1
                current_sum = df['mid_change'].iloc[i]
        if current_len > 0:
            runs.append((current_dir, current_len, current_sum))

        # Run length distribution
        run_lengths = [r[1] for r in runs]
        print(f"\n  {prod} run-length distribution:")
        for length in range(1, max(run_lengths)+1):
            count = sum(1 for r in run_lengths if r == length)
            if count > 0:
                print(f"    length={length}: count={count} ({count/len(runs)*100:.1f}%)")

        # After run of length N, what's the probability of continuation?
        print(f"\n  {prod} continuation probability after run of length N:")
        for min_len in range(1, 6):
            continuations = 0
            reversals = 0
            for i in range(len(runs) - 1):
                if runs[i][1] >= min_len:
                    if runs[i][0] == runs[i+1][0]:
                        # This shouldn't happen since runs alternate
                        pass
                    else:
                        reversals += 1
            # Actually, let's look at this differently: after N consecutive same-direction moves,
            # what's P(next move same direction)?
            df_clean = df.dropna(subset=['direction'])
            df_clean = df_clean[df_clean['direction'] != 0].reset_index(drop=True)

            cont_count = 0
            rev_count = 0
            total = 0
            for i in range(min_len, len(df_clean)):
                # Check if last min_len moves are all same direction
                window = df_clean['direction'].iloc[i-min_len:i]
                if len(window.unique()) == 1 and window.iloc[0] != 0:
                    total += 1
                    if df_clean['direction'].iloc[i] == window.iloc[0]:
                        cont_count += 1
                    else:
                        rev_count += 1
            if total > 0:
                print(f"    after {min_len} same-dir moves: P(continue)={cont_count/total:.3f}, "
                      f"P(reverse)={rev_count/total:.3f}, n={total}")

print("\n" + "=" * 80)
print("SECTION 4: CONDITIONAL VOLATILITY CLUSTERING")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    for prod in ['TOMATOES']:
        df = get_product(days[d], prod)
        df['mid_change'] = df['mid_price'].diff()
        df['abs_change'] = df['mid_change'].abs()

        # Define "big move" as |change| >= 2
        big_move_thresholds = [1.5, 2.0, 2.5, 3.0]

        for thresh in big_move_thresholds:
            big_move_idx = df[df['abs_change'] >= thresh].index

            # Average absolute change in N ticks AFTER a big move
            horizons = [1, 2, 3, 5, 10, 20]
            print(f"\n  {prod} - After |change| >= {thresh} (n={len(big_move_idx)}):")
            unconditional_vol = df['abs_change'].mean()
            print(f"    Unconditional avg |change| = {unconditional_vol:.4f}")

            for h in horizons:
                future_vols = []
                for idx in big_move_idx:
                    if idx + h < len(df):
                        future_vols.append(df['abs_change'].iloc[idx + h])
                if future_vols:
                    avg_future = np.mean(future_vols)
                    ratio = avg_future / unconditional_vol if unconditional_vol > 0 else 0
                    print(f"    t+{h}: avg|change|={avg_future:.4f} ({ratio:.2f}x unconditional)")

        # Autocorrelation of absolute changes (ARCH effects)
        print(f"\n  {prod} - Autocorrelation of |mid_change|:")
        for lag in [1, 2, 3, 5, 10, 20]:
            ac = df['abs_change'].autocorr(lag=lag)
            print(f"    lag {lag}: {ac:.4f}")

print("\n" + "=" * 80)
print("SECTION 5: CROSS-PRODUCT TIMING CORRELATIONS")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    tom = get_product(days[d], 'TOMATOES')
    em = get_product(days[d], 'EMERALDS')

    tom['spread'] = tom['ask_price_1'] - tom['bid_price_1']
    em['spread'] = em['ask_price_1'] - em['bid_price_1']
    tom['mid_change'] = tom['mid_price'].diff()
    em['mid_change'] = em['mid_price'].diff()

    # Merge on timestamp
    merged = pd.merge(tom[['timestamp', 'spread', 'mid_change', 'mid_price', 'bid_volume_1', 'ask_volume_1']],
                       em[['timestamp', 'spread', 'mid_change', 'mid_price', 'bid_volume_1', 'ask_volume_1']],
                       on='timestamp', suffixes=('_tom', '_em'))

    # Correlation of spread changes
    merged['spread_change_tom'] = merged['spread_tom'].diff()
    merged['spread_change_em'] = merged['spread_em'].diff()

    corr_spread = merged['spread_change_tom'].corr(merged['spread_change_em'])
    print(f"  Spread change correlation: {corr_spread:.4f}")

    # When EMERALDS spread narrows, does TOMATOES spread narrow soon?
    em_narrow = merged[merged['spread_em'] < 16]  # EMERALDS narrow
    em_wide = merged[merged['spread_em'] >= 16]

    if len(em_narrow) > 0 and len(em_wide) > 0:
        tom_spread_when_em_narrow = em_narrow['spread_tom'].mean()
        tom_spread_when_em_wide = em_wide['spread_tom'].mean()
        print(f"  TOMATOES spread when EMERALDS narrow (<16): {tom_spread_when_em_narrow:.2f}")
        print(f"  TOMATOES spread when EMERALDS wide (>=16): {tom_spread_when_em_wide:.2f}")

    # Cross-product: EMERALDS narrow at t => TOMATOES narrow at t+k?
    print(f"\n  Lead-lag of narrow spread events:")
    for k in range(-5, 6):
        if k == 0:
            continue
        em_narrow_ts = set(merged[merged['spread_em'] < 16]['timestamp'])
        # Check TOMATOES spread at shifted timestamps
        shifted_mask = merged['timestamp'].apply(lambda t: (t + k*100) in em_narrow_ts)
        if shifted_mask.sum() > 0:
            avg_tom_spread = merged.loc[shifted_mask, 'spread_tom'].mean()
            baseline = merged['spread_tom'].mean()
            print(f"    EMERALDS narrow at t => TOMATOES at t{k:+d} ticks: "
                  f"avg_spread={avg_tom_spread:.2f} (baseline={baseline:.2f})")

    # Do simultaneous narrow spreads predict anything?
    both_narrow = merged[(merged['spread_tom'] <= 9) & (merged['spread_em'] < 16)]
    print(f"\n  Both products narrow simultaneously: {len(both_narrow)} ticks")
    if len(both_narrow) > 0:
        print(f"    Timestamps: {sorted(both_narrow['timestamp'].tolist())[:20]}...")

    # Trade timing correlation
    tom_trades = trades[d][trades[d]['symbol'] == 'TOMATOES']
    em_trades = trades[d][trades[d]['symbol'] == 'EMERALDS']

    print(f"\n  Trade counts: TOMATOES={len(tom_trades)}, EMERALDS={len(em_trades)}")

    # Do trades cluster at the same timestamps?
    tom_trade_ts = set(tom_trades['timestamp'])
    em_trade_ts = set(em_trades['timestamp'])
    overlap = tom_trade_ts & em_trade_ts
    print(f"  Simultaneous trades: {len(overlap)} timestamps")
    if len(tom_trade_ts) > 0 and len(em_trade_ts) > 0:
        expected_overlap = len(tom_trade_ts) * len(em_trade_ts) / len(merged)
        print(f"  Expected if independent: {expected_overlap:.1f}")
        print(f"  Ratio: {len(overlap)/expected_overlap:.2f}x" if expected_overlap > 0 else "")


print("\n" + "=" * 80)
print("SECTION 6: ORDER BOOK SHAPE ANOMALIES")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    for prod in ['TOMATOES', 'EMERALDS']:
        df = get_product(days[d], prod)
        df['spread'] = df['ask_price_1'] - df['bid_price_1']
        df['mid_change'] = df['mid_price'].diff().shift(-1)  # NEXT tick change
        df['l1_total'] = df['bid_volume_1'] + df['ask_volume_1']
        df['l2_total'] = df['bid_volume_2'].fillna(0) + df['ask_volume_2'].fillna(0)
        df['l1_imbalance'] = (df['bid_volume_1'] - df['ask_volume_1']) / df['l1_total']

        # L2/L1 volume ratio
        df['l2_l1_ratio'] = df['l2_total'] / df['l1_total'].replace(0, np.nan)

        # When L2/L1 ratio is unusually high or low
        ratio_q25 = df['l2_l1_ratio'].quantile(0.25)
        ratio_q75 = df['l2_l1_ratio'].quantile(0.75)
        ratio_median = df['l2_l1_ratio'].median()

        low_l2 = df[df['l2_l1_ratio'] < ratio_q25]
        high_l2 = df[df['l2_l1_ratio'] > ratio_q75]
        mid_l2 = df[(df['l2_l1_ratio'] >= ratio_q25) & (df['l2_l1_ratio'] <= ratio_q75)]

        print(f"\n  {prod} - L2/L1 ratio: median={ratio_median:.2f}, Q25={ratio_q25:.2f}, Q75={ratio_q75:.2f}")
        print(f"    Low L2 (n={len(low_l2)}): next |change|={low_l2['mid_change'].abs().mean():.4f}")
        print(f"    Mid L2 (n={len(mid_l2)}): next |change|={mid_l2['mid_change'].abs().mean():.4f}")
        print(f"    High L2 (n={len(high_l2)}): next |change|={high_l2['mid_change'].abs().mean():.4f}")

        # L1 total volume anomalies
        vol_q10 = df['l1_total'].quantile(0.10)
        vol_q90 = df['l1_total'].quantile(0.90)

        low_vol = df[df['l1_total'] <= vol_q10]
        high_vol = df[df['l1_total'] >= vol_q90]

        print(f"    Low L1 vol (<=Q10={vol_q10:.0f}, n={len(low_vol)}): "
              f"next |change|={low_vol['mid_change'].abs().mean():.4f}, spread={low_vol['spread'].mean():.1f}")
        print(f"    High L1 vol (>=Q90={vol_q90:.0f}, n={len(high_vol)}): "
              f"next |change|={high_vol['mid_change'].abs().mean():.4f}, spread={high_vol['spread'].mean():.1f}")

        # Asymmetric book: bid_vol >> ask_vol or vice versa
        df['vol_ratio'] = df['bid_volume_1'] / df['ask_volume_1'].replace(0, np.nan)
        extreme_bid_heavy = df[df['vol_ratio'] > 2.0]
        extreme_ask_heavy = df[df['vol_ratio'] < 0.5]

        print(f"    Bid-heavy (ratio>2, n={len(extreme_bid_heavy)}): next change={extreme_bid_heavy['mid_change'].mean():.4f}")
        print(f"    Ask-heavy (ratio<0.5, n={len(extreme_ask_heavy)}): next change={extreme_ask_heavy['mid_change'].mean():.4f}")

        # L2 gap (distance between L1 and L2 prices)
        df['bid_gap'] = df['bid_price_1'] - df['bid_price_2'].fillna(df['bid_price_1'])
        df['ask_gap'] = df['ask_price_2'].fillna(df['ask_price_1']) - df['ask_price_1']
        df['gap_asymmetry'] = df['bid_gap'] - df['ask_gap']

        # Non-standard gap
        typical_bid_gap = df['bid_gap'].mode().iloc[0] if len(df['bid_gap'].mode()) > 0 else 1
        unusual_gap = df[df['bid_gap'] != typical_bid_gap]
        print(f"    Typical bid gap: {typical_bid_gap}, unusual gap ticks: {len(unusual_gap)}")
        if len(unusual_gap) > 0:
            print(f"    Unusual gap -> next change: {unusual_gap['mid_change'].mean():.4f}")


print("\n" + "=" * 80)
print("SECTION 7: NON-LINEAR PATTERNS")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    for prod in ['TOMATOES']:
        df = get_product(days[d], prod)
        df['mid_change'] = df['mid_price'].diff()
        df['next_change'] = df['mid_change'].shift(-1)
        df['spread'] = df['ask_price_1'] - df['bid_price_1']

        # 1. Quadratic relationship: does (mid_change)^2 predict next_change?
        df['change_sq'] = df['mid_change'] ** 2
        corr_linear = df['mid_change'].corr(df['next_change'])
        corr_quad = df['change_sq'].corr(df['next_change'].abs())
        print(f"\n  {prod} - Linear autocorr(1): {corr_linear:.4f}")
        print(f"  {prod} - |change_t|^2 vs |change_t+1|: {corr_quad:.4f}")

        # 2. Conditional mean reversion strength
        # Bucket current change, compute expected next change
        print(f"\n  {prod} - Conditional next change by current change:")
        change_vals = df['mid_change'].dropna().unique()
        change_vals = sorted(change_vals)
        for cv in change_vals:
            mask = df['mid_change'] == cv
            next_avg = df.loc[mask, 'next_change'].mean()
            n = mask.sum()
            if n >= 5:
                print(f"    change={cv:+5.1f}: next_change={next_avg:+6.3f}, n={n}")

        # 3. Spread-conditioned mid change prediction
        print(f"\n  {prod} - Next change conditioned on spread:")
        for sp in sorted(df['spread'].unique()):
            mask = df['spread'] == sp
            next_avg_abs = df.loc[mask, 'next_change'].abs().mean()
            next_avg = df.loc[mask, 'next_change'].mean()
            n = mask.sum()
            if n >= 5:
                print(f"    spread={sp:>2}: next|change|={next_avg_abs:.4f}, "
                      f"next_change={next_avg:+.4f}, n={n}")

        # 4. Mid-price level effect (distance from session mean)
        session_mean = df['mid_price'].mean()
        df['dist_from_mean'] = df['mid_price'] - session_mean
        df['dist_bucket'] = pd.cut(df['dist_from_mean'], bins=10)

        print(f"\n  {prod} - Next change by distance from session mean ({session_mean:.1f}):")
        for bucket in sorted(df['dist_bucket'].dropna().unique()):
            mask = df['dist_bucket'] == bucket
            next_avg = df.loc[mask, 'next_change'].mean()
            n = mask.sum()
            if n >= 5:
                print(f"    dist={bucket}: next_change={next_avg:+.4f}, n={n}")

        # 5. Time-since-last-narrow-spread
        df['is_narrow'] = df['spread'] <= 9
        narrow_idx = df[df['is_narrow']].index
        df['ticks_since_narrow'] = np.nan
        for idx in narrow_idx:
            for j in range(1, 50):
                if idx + j < len(df):
                    if pd.isna(df.loc[idx + j, 'ticks_since_narrow']) or df.loc[idx + j, 'ticks_since_narrow'] > j:
                        df.loc[idx + j, 'ticks_since_narrow'] = j

        print(f"\n  {prod} - Behavior after narrow spread:")
        for ticks_after in [1, 2, 3, 5, 10, 20]:
            mask = df['ticks_since_narrow'] == ticks_after
            if mask.sum() > 0:
                avg_change = df.loc[mask, 'next_change'].mean()
                avg_abs_change = df.loc[mask, 'next_change'].abs().mean()
                avg_spread = df.loc[mask, 'spread'].mean()
                print(f"    {ticks_after} ticks after narrow: next_change={avg_change:+.4f}, "
                      f"|next_change|={avg_abs_change:.4f}, spread={avg_spread:.1f}, n={mask.sum()}")


print("\n" + "=" * 80)
print("SECTION 8: EMERALDS SPECIFIC PATTERNS")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'EMERALDS')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['l1_total'] = df['bid_volume_1'] + df['ask_volume_1']
    df['l1_imbalance'] = df['bid_volume_1'] - df['ask_volume_1']

    # EMERALDS spread distribution
    print(f"  Spread distribution:")
    for sp in sorted(df['spread'].unique()):
        n = (df['spread'] == sp).sum()
        print(f"    spread={sp}: {n} ({n/len(df)*100:.1f}%)")

    # When does EMERALDS get narrow spread?
    narrow = df[df['spread'] < 16]
    if len(narrow) > 0:
        print(f"\n  Narrow spread timestamps: {sorted(narrow['timestamp'].tolist())[:30]}")
        print(f"  Total narrow ticks: {len(narrow)}")

        # What L1 volume precedes narrow spread?
        narrow_idx = narrow.index
        for lookback in [1, 2, 3, 5]:
            prior_vols = []
            for idx in narrow_idx:
                if idx - lookback >= 0:
                    prior_vols.append(df.loc[idx - lookback, 'l1_total'])
            if prior_vols:
                print(f"  L1 vol {lookback} ticks before narrow: mean={np.mean(prior_vols):.1f}, "
                      f"vs overall={df['l1_total'].mean():.1f}")

    # L1 imbalance patterns
    print(f"\n  L1 imbalance distribution:")
    for imb in sorted(df['l1_imbalance'].unique()):
        n = (df['l1_imbalance'] == imb).sum()
        if n >= 3:
            print(f"    imbalance={imb:+3.0f}: n={n} ({n/len(df)*100:.1f}%)")

print("\n" + "=" * 80)
print("SECTION 9: SPREAD TRANSITION MATRIX (TOMATOES)")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['next_spread'] = df['spread'].shift(-1)

    # Transition probabilities
    spreads = sorted(df['spread'].unique())
    print(f"  Spread values: {spreads}")

    transitions = pd.crosstab(df['spread'], df['next_spread'], normalize='index')
    print(f"\n  Transition matrix (rows=current, cols=next):")
    print(transitions.round(3).to_string())

    # After narrow spread, how many ticks until next narrow?
    narrow_mask = df['spread'] <= 9
    narrow_timestamps = df[narrow_mask]['timestamp'].values
    if len(narrow_timestamps) > 1:
        gaps = np.diff(narrow_timestamps)
        print(f"\n  Gaps between narrow spreads: mean={gaps.mean():.0f}ms, "
              f"median={np.median(gaps):.0f}ms, min={gaps.min()}, max={gaps.max()}")
        # Distribution of gaps
        for threshold in [100, 200, 500, 1000, 5000, 10000, 50000]:
            pct = (gaps <= threshold).mean()
            print(f"    P(next narrow <= {threshold}ms) = {pct:.3f}")


print("\n" + "=" * 80)
print("SECTION 10: TRADE PRICE ANALYSIS")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    for prod in ['TOMATOES', 'EMERALDS']:
        t = trades[d][trades[d]['symbol'] == prod]
        p = get_product(days[d], prod)

        print(f"\n  {prod}: {len(t)} trades")
        if len(t) == 0:
            continue

        # Trade at bid vs ask
        merged = pd.merge_asof(t.sort_values('timestamp'),
                                p[['timestamp', 'bid_price_1', 'ask_price_1', 'mid_price']].sort_values('timestamp'),
                                on='timestamp', direction='backward')

        at_bid = (merged['price'] == merged['bid_price_1']).sum()
        at_ask = (merged['price'] == merged['ask_price_1']).sum()
        inside = ((merged['price'] > merged['bid_price_1']) & (merged['price'] < merged['ask_price_1'])).sum()

        print(f"    At bid: {at_bid}, At ask: {at_ask}, Inside: {inside}")

        # Trade quantity distribution
        print(f"    Quantity distribution: {dict(t['quantity'].value_counts().sort_index())}")

        # Time between trades
        ts = sorted(t['timestamp'].values)
        if len(ts) > 1:
            intervals = np.diff(ts)
            print(f"    Inter-trade interval: mean={intervals.mean():.0f}ms, "
                  f"median={np.median(intervals):.0f}ms, std={intervals.std():.0f}ms")

            # Is there clustering of trades?
            print(f"    Interval distribution:")
            for thresh in [100, 200, 500, 1000, 2000, 5000, 10000]:
                pct = (intervals <= thresh).mean()
                print(f"      P(interval <= {thresh}ms) = {pct:.3f}")

            # Do trade intervals predict future mid change?
            print(f"\n    Trade interval vs future mid change:")
            for t_row_idx in range(len(t)):
                pass  # complex merge, skip for now

        # Side inference: price at bid = sell, price at ask = buy
        merged['side'] = np.where(merged['price'] <= merged['bid_price_1'], 'SELL',
                         np.where(merged['price'] >= merged['ask_price_1'], 'BUY', 'MID'))

        # After BUY trade, does price go up? After SELL, down?
        merged['ts_idx'] = merged['timestamp'].map(
            dict(zip(p['timestamp'], range(len(p)))))

        buy_trades = merged[merged['side'] == 'BUY']
        sell_trades = merged[merged['side'] == 'SELL']

        for horizon in [1, 3, 5, 10]:
            buy_returns = []
            sell_returns = []
            for _, row in buy_trades.iterrows():
                idx = row.get('ts_idx', None)
                if idx is not None and not np.isnan(idx):
                    idx = int(idx)
                    if idx + horizon < len(p):
                        ret = p.iloc[idx + horizon]['mid_price'] - p.iloc[idx]['mid_price']
                        buy_returns.append(ret)
            for _, row in sell_trades.iterrows():
                idx = row.get('ts_idx', None)
                if idx is not None and not np.isnan(idx):
                    idx = int(idx)
                    if idx + horizon < len(p):
                        ret = p.iloc[idx + horizon]['mid_price'] - p.iloc[idx]['mid_price']
                        sell_returns.append(ret)

            if buy_returns and sell_returns:
                print(f"    t+{horizon}: after BUY={np.mean(buy_returns):+.3f} (n={len(buy_returns)}), "
                      f"after SELL={np.mean(sell_returns):+.3f} (n={len(sell_returns)})")


print("\n" + "=" * 80)
print("SECTION 11: HIDDEN MARKOV / REGIME DETECTION")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['abs_change'] = df['mid_change'].abs()

    # Rolling volatility (20-tick window)
    df['rolling_vol'] = df['abs_change'].rolling(20).mean()

    # Classify into high/low vol regimes
    vol_median = df['rolling_vol'].median()
    df['vol_regime'] = np.where(df['rolling_vol'] > vol_median, 'HIGH', 'LOW')

    # In high-vol regime, is mean reversion stronger or weaker?
    for regime in ['HIGH', 'LOW']:
        mask = df['vol_regime'] == regime
        sub = df[mask].dropna(subset=['mid_change'])
        if len(sub) > 20:
            ac = sub['mid_change'].autocorr(lag=1)
            avg_spread = sub['spread'].mean()
            print(f"  {regime} vol regime: AC(1)={ac:.3f}, avg_spread={avg_spread:.1f}, n={len(sub)}")

    # Does vol regime predict spread narrowing?
    df['next_narrow'] = (df['spread'].shift(-1) <= 9).astype(int)
    for regime in ['HIGH', 'LOW']:
        mask = df['vol_regime'] == regime
        narrow_rate = df.loc[mask, 'next_narrow'].mean()
        print(f"  {regime} vol -> P(narrow next tick) = {narrow_rate:.4f}")

    # Consecutive wide spread count vs next mid change
    df['wide'] = (df['spread'] >= 13).astype(int)
    df['consec_wide'] = 0
    count = 0
    for i in range(len(df)):
        if df.iloc[i]['wide']:
            count += 1
        else:
            count = 0
        df.iloc[i, df.columns.get_loc('consec_wide')] = count

    print(f"\n  Consecutive wide spreads vs next mid change:")
    for cw in [0, 1, 5, 10, 20, 50, 100]:
        mask = df['consec_wide'] == cw
        if mask.sum() >= 5:
            next_mc = df.loc[mask, 'mid_change'].shift(-1).mean()
            next_abs = df.loc[mask, 'mid_change'].shift(-1).abs().mean()
            print(f"    consec_wide={cw}: next_change={next_mc:+.4f}, "
                  f"|next_change|={next_abs:.4f}, n={mask.sum()}")


print("\n" + "=" * 80)
print("SECTION 12: MID-PRICE RETURN DISTRIBUTION ANALYSIS")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['mid_change'] = df['mid_price'].diff()

    changes = df['mid_change'].dropna()

    print(f"  Mid change statistics:")
    print(f"    Mean: {changes.mean():.4f}")
    print(f"    Std: {changes.std():.4f}")
    print(f"    Skew: {changes.skew():.4f}")
    print(f"    Kurtosis: {changes.kurtosis():.4f}")

    # Value distribution
    print(f"\n  Mid change value distribution:")
    for val in sorted(changes.unique()):
        n = (changes == val).sum()
        if n >= 2:
            print(f"    {val:+5.1f}: {n:5d} ({n/len(changes)*100:5.1f}%)")

    # Multi-tick returns distribution (2, 5, 10, 20 ticks)
    for horizon in [2, 5, 10, 20, 50]:
        multi_ret = df['mid_price'].diff(horizon).dropna()
        if len(multi_ret) > 10:
            print(f"\n  {horizon}-tick return: mean={multi_ret.mean():.3f}, "
                  f"std={multi_ret.std():.3f}, skew={multi_ret.skew():.3f}, "
                  f"kurt={multi_ret.kurtosis():.3f}")


print("\n" + "=" * 80)
print("SECTION 13: POSITION-OPTIMAL STRATEGY SIMULATION")
print("=" * 80)
print("(Computing theoretical max PnL from different posting strategies)")

for d in [0]:  # Day 0 only (matches website)
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()

    # What if we could perfectly predict the NEXT mid change direction?
    # Max PnL = sum of |mid_changes| (buy before up, sell before down)
    total_abs = df['mid_change'].abs().sum()
    print(f"  TOMATOES perfect foresight 1-tick PnL: {total_abs:.0f}")
    print(f"  Number of non-zero changes: {(df['mid_change'] != 0).sum()}")
    print(f"  Avg |change| when non-zero: {df.loc[df['mid_change'] != 0, 'mid_change'].abs().mean():.2f}")

    # What about N-tick foresight?
    for horizon in [1, 2, 5, 10, 20]:
        future_ret = df['mid_price'].diff(horizon).shift(-horizon)
        pnl = future_ret.abs().sum() / horizon  # Normalized per tick
        print(f"  {horizon}-tick foresight: PnL/tick = {pnl:.2f}")

print("\n" + "=" * 80)
print("SECTION 14: VOLUME CHANGE AS SIGNAL")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    for prod in ['TOMATOES', 'EMERALDS']:
        df = get_product(days[d], prod)
        df['bid_vol_change'] = df['bid_volume_1'].diff()
        df['ask_vol_change'] = df['ask_volume_1'].diff()
        df['vol_change_diff'] = df['bid_vol_change'] - df['ask_vol_change']
        df['next_mid_change'] = df['mid_price'].diff().shift(-1)

        # Does volume change predict next mid change?
        corr = df['vol_change_diff'].corr(df['next_mid_change'])
        print(f"\n  {prod} - vol_change_diff vs next_mid_change correlation: {corr:.4f}")

        # Large volume drops
        df['total_vol'] = df['bid_volume_1'] + df['ask_volume_1']
        df['vol_drop'] = df['total_vol'].diff()
        big_drop = df[df['vol_drop'] < -5]
        if len(big_drop) > 0:
            avg_next = big_drop['next_mid_change'].mean()
            avg_abs_next = big_drop['next_mid_change'].abs().mean()
            print(f"  {prod} - After big vol drop (>5): next_change={avg_next:+.4f}, "
                  f"|next_change|={avg_abs_next:.4f}, n={len(big_drop)}")

        big_add = df[df['vol_drop'] > 5]
        if len(big_add) > 0:
            avg_next = big_add['next_mid_change'].mean()
            avg_abs_next = big_add['next_mid_change'].abs().mean()
            print(f"  {prod} - After big vol add (>5): next_change={avg_next:+.4f}, "
                  f"|next_change|={avg_abs_next:.4f}, n={len(big_add)}")


print("\n" + "=" * 80)
print("SECTION 15: SPREAD-CHANGE PREDICTION")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['spread_change'] = df['spread'].diff()
    df['mid_change'] = df['mid_price'].diff()
    df['next_spread'] = df['spread'].shift(-1)

    # Does mid_change predict spread_change?
    corr = df['mid_change'].abs().corr(df['spread_change'].shift(-1).abs())
    print(f"  |mid_change| vs |next_spread_change|: {corr:.4f}")

    # After a large mid change, does spread widen or narrow?
    for thresh in [2.0, 3.0, 4.0]:
        big_up = df[df['mid_change'] >= thresh]
        big_dn = df[df['mid_change'] <= -thresh]
        if len(big_up) > 0:
            print(f"  After mid_change >= {thresh}: next_spread={big_up['next_spread'].mean():.1f} "
                  f"(current={big_up['spread'].mean():.1f}), n={len(big_up)}")
        if len(big_dn) > 0:
            print(f"  After mid_change <= -{thresh}: next_spread={big_dn['next_spread'].mean():.1f} "
                  f"(current={big_dn['spread'].mean():.1f}), n={len(big_dn)}")


print("\n\n" + "=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)
