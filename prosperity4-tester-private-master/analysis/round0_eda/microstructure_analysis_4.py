"""
Part 4: Novel Patterns, Anomalies, Deep Dives
"""
import pandas as pd
import numpy as np
from collections import Counter, defaultdict
import warnings
warnings.filterwarnings('ignore')

base = '/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0/'
files = {
    'day0': base + 'prices_round_0_day_0.csv',
    'day-1': base + 'prices_round_0_day_-1.csv',
    'day-2': base + 'prices_round_0_day_-2.csv',
}
dfs = {}
for name, path in files.items():
    df = pd.read_csv(path, sep=';')
    tom = df[df['product'] == 'TOMATOES'].copy().reset_index(drop=True)
    tom = tom.sort_values('timestamp').reset_index(drop=True)
    tom['spread'] = tom['ask_price_1'] - tom['bid_price_1']
    tom['mid'] = (tom['bid_price_1'] + tom['ask_price_1']) / 2
    tom['dmid'] = tom['mid'].diff()
    tom['dbid'] = tom['bid_price_1'].diff()
    tom['dask'] = tom['ask_price_1'].diff()
    dfs[name] = tom

# ============================================================
# 6. NOVEL PATTERNS / ANOMALIES
# ============================================================
print("=" * 80)
print("6A. NARROW SPREAD ANATOMY — THE MOST IMPORTANT MICROSTRUCTURE FEATURE")
print("=" * 80)

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    # Classify narrow spread types by which side expanded
    # Narrow spread means the spread went from {13,14} to {5,6,7,8,9}
    # The DIRECTION of the mid move tells us: UP move = ask stayed/dropped, DOWN move = bid stayed/rose

    # Let's look at the exact mechanics: what does spread=5 look like vs spread=9?
    for s in [5, 6, 7, 8, 9]:
        mask = df['spread'] == s
        if mask.sum() == 0:
            continue
        sub = df[mask]

        # L1-L2 price gaps during narrow spreads
        bid_gap = sub['bid_price_1'] - sub['bid_price_2']
        ask_gap = sub['ask_price_2'] - sub['ask_price_1']

        # Volume during narrow spreads
        bv1 = sub['bid_volume_1'].mean()
        av1 = sub['ask_volume_1'].mean()
        bv2 = sub['bid_volume_2'].mean()
        av2 = sub['ask_volume_2'].mean()

        print(f"  Spread={s} ({mask.sum()} ticks):")
        print(f"    Bid gap (L1-L2): {Counter(bid_gap).most_common()}")
        print(f"    Ask gap (L2-L1): {Counter(ask_gap).most_common()}")
        print(f"    L1 vol: bid={bv1:.1f}, ask={av1:.1f}")
        print(f"    L2 vol: bid={bv2:.1f}, ask={av2:.1f}")
        print(f"    L2/L1 ratio: bid={bv2/bv1:.2f}, ask={av2/av1:.2f}")


print("\n\n" + "=" * 80)
print("6B. NARROW SPREAD ENTRY/EXIT PATTERN (Day 0)")
print("=" * 80)
df0 = dfs['day0']

# For each narrow episode, trace the full lifecycle: entry → narrow → exit
is_narrow = df0['spread'] <= 9
narrow_starts = []
for i in range(1, len(df0)):
    if is_narrow.iloc[i] and not is_narrow.iloc[i-1]:
        # Find end of narrow episode
        j = i
        while j < len(df0) and is_narrow.iloc[j]:
            j += 1
        narrow_starts.append((i, j-1))  # start, end indices

print(f"Number of narrow episodes: {len(narrow_starts)}")
for idx, (start, end) in enumerate(narrow_starts[:30]):
    duration = end - start + 1
    pre_spread = df0['spread'].iloc[start-1]
    pre_mid = df0['mid'].iloc[start-1]
    entry_mid = df0['mid'].iloc[start]
    exit_mid = df0['mid'].iloc[end] if end < len(df0)-1 else df0['mid'].iloc[end]
    post_spread = df0['spread'].iloc[end+1] if end+1 < len(df0) else None
    post_mid = df0['mid'].iloc[end+1] if end+1 < len(df0) else None

    spreads_during = list(df0['spread'].iloc[start:end+1])
    dmid_entry = entry_mid - pre_mid
    dmid_exit = post_mid - exit_mid if post_mid is not None else None

    print(f"  Episode {idx+1}: t={df0['timestamp'].iloc[start]}, dur={duration}, "
          f"spreads={spreads_during}, "
          f"pre_spread={pre_spread:.0f}, post_spread={post_spread}, "
          f"dmid_entry={dmid_entry:+.1f}, dmid_exit={dmid_exit if dmid_exit is not None else 'N/A'}")


print("\n\n" + "=" * 80)
print("6C. SPREAD=5 vs SPREAD=9: DIRECTIONAL BIAS")
print("=" * 80)
# Hypothesis: spread=5 is a DOWN signal, spread=9 is an UP signal
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")
    for s in [5, 6, 7, 8, 9]:
        mask = df['spread'] == s
        if mask.sum() == 0:
            continue
        sub = df[mask]
        # What is the mid move ON this tick (entering the narrow spread)?
        entry_dmid = sub['dmid'].dropna()
        # What is the mid move on the NEXT tick (exiting)?
        next_idx = sub.index + 1
        next_idx = next_idx[next_idx < len(df)]
        exit_dmid = df.loc[next_idx, 'dmid'].dropna()

        print(f"  Spread={s} ({mask.sum()} ticks):")
        print(f"    Entry dmid: mean={entry_dmid.mean():.2f}, distribution={Counter(np.round(entry_dmid, 1)).most_common(10)}")
        print(f"    Exit dmid:  mean={exit_dmid.mean():.2f}, distribution={Counter(np.round(exit_dmid, 1)).most_common(10)}")


print("\n\n" + "=" * 80)
print("6D. MID-PRICE 'STICKY' LEVELS AND BARRIERS")
print("=" * 80)
# For each day, find the mid values and how long they persist
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    # Duration at each mid level
    mid_durations = defaultdict(list)
    current_mid = df['mid'].iloc[0]
    current_duration = 1
    for i in range(1, len(df)):
        if df['mid'].iloc[i] == current_mid:
            current_duration += 1
        else:
            mid_durations[current_mid].append(current_duration)
            current_mid = df['mid'].iloc[i]
            current_duration = 1
    mid_durations[current_mid].append(current_duration)

    # Most visited mid levels
    mid_counts = df['mid'].value_counts().sort_values(ascending=False)
    print(f"  Top 10 most visited mid levels:")
    for mid_val, count in mid_counts.head(10).items():
        avg_dur = np.mean(mid_durations[mid_val])
        n_visits = len(mid_durations[mid_val])
        print(f"    mid={mid_val}: {count} ticks, {n_visits} visits, avg duration={avg_dur:.1f}")

    # Long-duration events (mid stays same for many ticks)
    all_durations = []
    for mid_val, durs in mid_durations.items():
        for d in durs:
            all_durations.append((d, mid_val))
    all_durations.sort(reverse=True)
    print(f"\n  Longest mid persistence events:")
    for dur, mid_val in all_durations[:10]:
        print(f"    mid={mid_val}: stayed for {dur} ticks")

    # Distribution of durations
    dur_list = [d for d, _ in all_durations]
    print(f"\n  Duration distribution: mean={np.mean(dur_list):.2f}, median={np.median(dur_list):.1f}, "
          f"max={max(dur_list)}, P90={np.percentile(dur_list, 90):.0f}, P99={np.percentile(dur_list, 99):.0f}")


print("\n\n" + "=" * 80)
print("6E. VOLUME-DURATION RELATIONSHIP")
print("=" * 80)
# Does higher L1 volume predict longer stability?
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    df['next_dmid'] = df['dmid'].shift(-1)
    df['mid_unchanged_next'] = (df['next_dmid'] == 0).astype(int)

    # Group by L1 total volume
    df['l1_total_vol'] = df['bid_volume_1'] + df['ask_volume_1']

    for vol_range in [(4, 10), (10, 14), (14, 18), (18, 22)]:
        mask = (df['l1_total_vol'] >= vol_range[0]) & (df['l1_total_vol'] < vol_range[1])
        if mask.sum() > 0:
            stability = df.loc[mask, 'mid_unchanged_next'].mean()
            print(f"  L1 total vol [{vol_range[0]},{vol_range[1]}): "
                  f"n={mask.sum()}, P(mid unchanged next tick)={100*stability:.1f}%")


print("\n\n" + "=" * 80)
print("6F. THE CRITICAL OBSERVATION: NARROW SPREAD MECHANICS")
print("=" * 80)
# Narrow spreads: is the MM bot QUOTING differently, or is it an artifact of quote updates?
# Key test: when spread=5, what are bid_price_1 and ask_price_1 relative to the PREVIOUS mid?
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")
    df['prev_mid'] = df['mid'].shift(1)
    df['prev_bid'] = df['bid_price_1'].shift(1)
    df['prev_ask'] = df['ask_price_1'].shift(1)
    df['prev_spread'] = df['spread'].shift(1)

    for s in [5, 6, 7, 8, 9]:
        mask = (df['spread'] == s) & df['prev_mid'].notna()
        if mask.sum() == 0:
            continue
        sub = df[mask]

        # Where is the new bid relative to the old mid?
        bid_vs_old_mid = sub['bid_price_1'] - sub['prev_mid']
        ask_vs_old_mid = sub['ask_price_1'] - sub['prev_mid']

        # Where is the new mid relative to the old mid?
        new_mid_vs_old = sub['mid'] - sub['prev_mid']

        print(f"\n  Spread={s} ({mask.sum()} ticks):")
        print(f"    bid1 - prev_mid: {Counter(np.round(bid_vs_old_mid, 1)).most_common(10)}")
        print(f"    ask1 - prev_mid: {Counter(np.round(ask_vs_old_mid, 1)).most_common(10)}")
        print(f"    new_mid - prev_mid: {Counter(np.round(new_mid_vs_old, 1)).most_common(10)}")

        # What was the previous spread?
        prev_s = Counter(sub['prev_spread'])
        print(f"    Previous spread: {prev_s.most_common()}")


print("\n\n" + "=" * 80)
print("6G. CONSECUTIVE MOVE PATTERNS (Day 0)")
print("=" * 80)
df0 = dfs['day0']
df0['dmid'] = df0['mid'].diff()
# Look at sequences of dmid
# +0.5 followed by ?
# -0.5 followed by ?

# 2-gram analysis
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")
    df['dmid'] = df['mid'].diff()
    df['prev_dmid'] = df['dmid'].shift(1)

    # For each prev_dmid value, what is the distribution of next dmid?
    print("  E[dmid(t+1) | dmid(t)] — conditional mean of next move:")
    prev_vals = sorted(df['dmid'].dropna().unique())
    for pv in prev_vals:
        mask = (df['prev_dmid'] == pv) & df['dmid'].notna()
        if mask.sum() >= 5:
            conditional_mean = df.loc[mask, 'dmid'].mean()
            conditional_std = df.loc[mask, 'dmid'].std()
            print(f"    dmid(t)={pv:+5.1f}: n={mask.sum():4d}, E[dmid(t+1)]={conditional_mean:+6.3f}, "
                  f"std={conditional_std:.3f}")


print("\n\n" + "=" * 80)
print("6H. SPREAD STATE + VOLUME INTERACTION")
print("=" * 80)
# When spread is 13 or 14, does L1 volume predict the NEXT spread state?
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    df['next_spread'] = df['spread'].shift(-1)

    for s in [13, 14]:
        mask = (df['spread'] == s) & df['next_spread'].notna()
        sub = df[mask]

        # Split by volume imbalance
        sub_copy = sub.copy()
        sub_copy['vol_imb'] = (sub_copy['bid_volume_1'] - sub_copy['ask_volume_1'])
        sub_copy['goes_narrow'] = (sub_copy['next_spread'] <= 9).astype(int)

        # High bid vol vs high ask vol
        bid_heavy = sub_copy[sub_copy['vol_imb'] > 0]
        ask_heavy = sub_copy[sub_copy['vol_imb'] < 0]
        balanced = sub_copy[sub_copy['vol_imb'] == 0]

        p_narrow_bid = bid_heavy['goes_narrow'].mean() if len(bid_heavy) > 0 else 0
        p_narrow_ask = ask_heavy['goes_narrow'].mean() if len(ask_heavy) > 0 else 0
        p_narrow_bal = balanced['goes_narrow'].mean() if len(balanced) > 0 else 0

        print(f"  Spread={s}: P(narrow next) = "
              f"bid_heavy: {100*p_narrow_bid:.1f}% (n={len(bid_heavy)}), "
              f"ask_heavy: {100*p_narrow_ask:.1f}% (n={len(ask_heavy)}), "
              f"balanced: {100*p_narrow_bal:.1f}% (n={len(balanced)})")


print("\n\n" + "=" * 80)
print("6I. THE 'JITTER' PATTERN: SPREAD 13<->14 OSCILLATION")
print("=" * 80)
# When spread alternates 13->14->13->14, what's really happening?
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    wide_mask = df['spread'].isin([13, 14])
    wide_df = df[wide_mask].copy()

    # When spread changes from 13 to 14 or vice versa, which side moved?
    wide_df['dspread'] = wide_df['spread'].diff()

    # 13->14 (spread widens by 1)
    to_14 = wide_df[wide_df['dspread'] == 1]
    if len(to_14) > 0:
        bid_moved = (to_14['dbid'] != 0).sum()
        ask_moved = (to_14['dask'] != 0).sum()
        bid_dn = (to_14['dbid'] < 0).sum()
        ask_up = (to_14['dask'] > 0).sum()
        bid_dn1 = (to_14['dbid'] == -1).sum()
        ask_up1 = (to_14['dask'] == 1).sum()
        print(f"  13->14 ({len(to_14)} transitions):")
        print(f"    Bid moved: {bid_moved}, Ask moved: {ask_moved}")
        print(f"    Bid down: {bid_dn}, Ask up: {ask_up}")
        print(f"    Bid down by exactly 1: {bid_dn1}, Ask up by exactly 1: {ask_up1}")
        print(f"    dbid distribution: {Counter(to_14['dbid']).most_common()}")
        print(f"    dask distribution: {Counter(to_14['dask']).most_common()}")

    # 14->13 (spread narrows by 1)
    to_13 = wide_df[wide_df['dspread'] == -1]
    if len(to_13) > 0:
        bid_moved = (to_13['dbid'] != 0).sum()
        ask_moved = (to_13['dask'] != 0).sum()
        bid_up = (to_13['dbid'] > 0).sum()
        ask_dn = (to_13['dask'] < 0).sum()
        bid_up1 = (to_13['dbid'] == 1).sum()
        ask_dn1 = (to_13['dask'] == -1).sum()
        print(f"  14->13 ({len(to_13)} transitions):")
        print(f"    Bid moved: {bid_moved}, Ask moved: {ask_moved}")
        print(f"    Bid up: {bid_up}, Ask down: {ask_dn}")
        print(f"    Bid up by exactly 1: {bid_up1}, Ask down by exactly 1: {ask_dn1}")
        print(f"    dbid distribution: {Counter(to_13['dbid']).most_common()}")
        print(f"    dask distribution: {Counter(to_13['dask']).most_common()}")


print("\n\n" + "=" * 80)
print("6J. THE GENERATION FORMULA: RECONSTRUCTING THE MM BOT")
print("=" * 80)
# The MM bot likely works as: mid(t+1) = mid(t) + epsilon, then bid = floor(mid - spread/2), ask = ceil(mid + spread/2)
# Or: bid = mid - X, ask = mid + Y, where X+Y = spread
# Let's check: is bid always = floor(mid - spread/2)?

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    # Test formula: bid = floor(mid - spread/2), ask = ceil(mid + spread/2)
    df['expected_bid_floor'] = np.floor(df['mid'] - df['spread']/2)
    df['expected_ask_ceil'] = np.ceil(df['mid'] + df['spread']/2)

    bid_match = (df['bid_price_1'] == df['expected_bid_floor']).mean()
    ask_match = (df['ask_price_1'] == df['expected_ask_ceil']).mean()

    print(f"  bid = floor(mid - spread/2): {100*bid_match:.1f}% match")
    print(f"  ask = ceil(mid + spread/2):  {100*ask_match:.1f}% match")

    # When they don't match, what's happening?
    bid_mismatch = df[df['bid_price_1'] != df['expected_bid_floor']]
    ask_mismatch = df[df['ask_price_1'] != df['expected_ask_ceil']]

    if len(bid_mismatch) > 0:
        diff = bid_mismatch['bid_price_1'] - bid_mismatch['expected_bid_floor']
        print(f"  Bid mismatches ({len(bid_mismatch)} ticks): bid - floor(mid-s/2) = {Counter(diff).most_common()}")
    if len(ask_mismatch) > 0:
        diff = ask_mismatch['ask_price_1'] - ask_mismatch['expected_ask_ceil']
        print(f"  Ask mismatches ({len(ask_mismatch)} ticks): ask - ceil(mid+s/2) = {Counter(diff).most_common()}")

    # Alternative formula: maybe spread is ALWAYS odd internally, and bid/ask are computed differently
    # bid = round_down(mid - half_spread), ask = round_up(mid + half_spread)
    # This is essentially what floor/ceil does

    # For spread 13: mid = (b + a)/2, spread = a - b = 13
    # b = mid - 6.5 -> could be floor(mid - 6.5) or ceil(mid - 6.5)
    # a = mid + 6.5 -> same
    s13 = df[df['spread'] == 13]
    if len(s13) > 0:
        # When mid is integer (say 5000): b = 5000-6.5 = 4993.5 -> floor=4993, a = 5000+6.5 = 5006.5 -> ceil=5007
        # So bid = 4993, ask = 5006, mid = (4993+5006)/2 = 4999.5... wait that doesn't work
        # Actually mid is defined as (bid+ask)/2, so if spread=13: mid = bid + 6.5
        # mid = 4999.5 means bid=4993, ask=5006
        # mid = 5000.0 means bid=4993.5... that's not integer!
        # So if spread is odd, mid must have .5 fractional part. If spread is even, mid is integer.
        mid_frac_13 = s13['mid'] % 1
        print(f"\n  Spread=13: mid fractional parts: {Counter(np.round(mid_frac_13, 1)).most_common()}")

    s14 = df[df['spread'] == 14]
    if len(s14) > 0:
        mid_frac_14 = s14['mid'] % 1
        print(f"  Spread=14: mid fractional parts: {Counter(np.round(mid_frac_14, 1)).most_common()}")

    # Check ALL spreads and mid parity
    print(f"\n  Spread parity vs mid:")
    for s in sorted(df['spread'].unique()):
        sub = df[df['spread'] == s]
        mid_is_integer = (sub['mid'] % 1 == 0).mean()
        mid_is_half = (sub['mid'] % 1 == 0.5).mean()
        print(f"    Spread={s:.0f}: mid is integer {100*mid_is_integer:.1f}%, "
              f"mid is .5 {100*mid_is_half:.1f}%")


print("\n\n" + "=" * 80)
print("6K. L2 PRICE RELATIONSHIP TO L1")
print("=" * 80)
# The L2 prices relative to L1 — is there a fixed relationship?
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")
    df['bid_gap'] = df['bid_price_1'] - df['bid_price_2']
    df['ask_gap'] = df['ask_price_2'] - df['ask_price_1']

    # By spread state
    for s in sorted(df['spread'].unique()):
        sub = df[df['spread'] == s]
        print(f"  Spread={s:.0f} ({len(sub)} ticks):")
        print(f"    bid_gap (L1-L2): {Counter(sub['bid_gap']).most_common()}")
        print(f"    ask_gap (L2-L1): {Counter(sub['ask_gap']).most_common()}")

        # L2 spread
        l2_spread = sub['ask_price_2'] - sub['bid_price_2']
        print(f"    L2 spread: {Counter(l2_spread).most_common()}")
