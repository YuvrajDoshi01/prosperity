"""
Part 5: Final deep dives - bot formula, asymmetry reversal, and critical discoveries
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
# THE BOT'S GENERATION FORMULA
# ============================================================
print("=" * 80)
print("THE BOT'S GENERATION FORMULA")
print("=" * 80)

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    # Test: bid = floor(mid - spread/2), ask = ceil(mid + spread/2)
    # But mid = (bid + ask)/2, so this is circular
    # The real question: what is the TRUE mid the bot uses?

    # For spread=13: if true_mid is M, then bid = M - 6 or M - 7, ask = M + 6 or M + 7
    # Since bid + ask = 2*(observed mid), and spread = ask - bid = 13
    # If bid = M - 7, ask = M + 6, then observed mid = M - 0.5
    # If bid = M - 6, ask = M + 7, then observed mid = M + 0.5

    # For spread=14: if true_mid is M, then bid = M - 7, ask = M + 7, observed mid = M

    # The key insight: when spread toggles between 13 and 14, what happens to the true mid?
    # If spread goes 13 -> 14 with bid dropping by 1: bid(13) = M-6 -> bid(14) = M-7
    # That means the TRUE mid stayed the same!

    # Let's check: during 13<->14 transitions, does the "true mid" change?

    # Strategy: when spread=14, true_mid = mid (integer)
    # When spread=13, true_mid = mid + 0.5 if bid = true_mid - 7 (ask side is closer)
    #                            mid - 0.5 if bid = true_mid - 6 (bid side is closer)
    # But we don't know the true mid...

    # Alternative approach: track the bid independently
    # The bid can only be set by the bot. If the bot has a "true mid" M,
    # then for spread=14: bid = M - 7
    # for spread=13: bid = M - 7 (ask = M + 6) OR bid = M - 6 (ask = M + 7)

    # During a 13->14 transition:
    # If the bot keeps the same true_mid and just changes the spread:
    #   Case 1: was bid = M-6, ask = M+7 (spread 13). Now bid = M-7, ask = M+7 (spread 14)
    #     -> bid drops by 1, ask stays. dmid = -0.5
    #   Case 2: was bid = M-7, ask = M+6 (spread 13). Now bid = M-7, ask = M+7 (spread 14)
    #     -> bid stays, ask rises by 1. dmid = +0.5

    # Let's check this hypothesis
    for s_from, s_to in [(13, 14), (14, 13)]:
        mask = (df['spread'].shift(1) == s_from) & (df['spread'] == s_to) & df['dmid'].notna()
        sub = df[mask]
        if len(sub) == 0:
            continue

        # Classify by bid/ask movement
        bid_only = sub[(sub['dbid'] != 0) & (sub['dask'] == 0)]
        ask_only = sub[(sub['dbid'] == 0) & (sub['dask'] != 0)]
        both = sub[(sub['dbid'] != 0) & (sub['dask'] != 0)]
        neither = sub[(sub['dbid'] == 0) & (sub['dask'] == 0)]

        print(f"\n  {s_from}->{s_to} ({len(sub)} transitions):")
        print(f"    Bid only: {len(bid_only)} ({100*len(bid_only)/len(sub):.1f}%)")
        print(f"    Ask only: {len(ask_only)} ({100*len(ask_only)/len(sub):.1f}%)")
        print(f"    Both:     {len(both)} ({100*len(both)/len(sub):.1f}%)")
        print(f"    Neither:  {len(neither)} ({100*len(neither)/len(sub):.1f}%)")

        if len(bid_only) > 0:
            print(f"    Bid-only dbid: {Counter(bid_only['dbid']).most_common()}")
            print(f"    Bid-only dmid: {Counter(bid_only['dmid']).most_common()}")
        if len(ask_only) > 0:
            print(f"    Ask-only dask: {Counter(ask_only['dask']).most_common()}")
            print(f"    Ask-only dmid: {Counter(ask_only['dmid']).most_common()}")


print("\n\n" + "=" * 80)
print("TESTING THE 'INTERNAL MID' HYPOTHESIS")
print("=" * 80)
# If the bot has a true internal mid M that changes in multiples of 0.5,
# then for spread=14: M = observed_mid (exactly)
# for spread=13: M = observed_mid + 0.5 or observed_mid - 0.5
# Which one? If bid = M - 7, ask = M + 6 (bid further from M):
#   observed_mid = (M-7 + M+6)/2 = M - 0.5 => M = observed_mid + 0.5
# If bid = M - 6, ask = M + 7 (ask further from M):
#   observed_mid = (M-6 + M+7)/2 = M + 0.5 => M = observed_mid - 0.5

# Can we determine which case by looking at where the NEXT wide-spread (14) mid goes?
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    # For each spread=13 tick, compute "bid version" (M = mid + 0.5, meaning bid is far side)
    # vs "ask version" (M = mid - 0.5, meaning ask is far side)
    # Then check which is closer to the NEXT spread=14 mid

    s13_mask = df['spread'] == 13
    s13_indices = df.index[s13_mask]

    bid_far_correct = 0  # M = mid + 0.5 (bid = M - 7, ask = M + 6)
    ask_far_correct = 0  # M = mid - 0.5 (bid = M - 6, ask = M + 7)
    total_checked = 0

    for idx in s13_indices:
        # Find next spread=14 tick
        future = df.loc[idx+1:]
        s14_future = future[future['spread'] == 14]
        if len(s14_future) > 0 and s14_future.index[0] - idx <= 3:  # within 3 ticks
            next_s14_mid = s14_future['mid'].iloc[0]
            current_mid = df.loc[idx, 'mid']
            bid_far_M = current_mid + 0.5
            ask_far_M = current_mid - 0.5

            if abs(next_s14_mid - bid_far_M) < abs(next_s14_mid - ask_far_M):
                bid_far_correct += 1
            elif abs(next_s14_mid - ask_far_M) < abs(next_s14_mid - bid_far_M):
                ask_far_correct += 1
            total_checked += 1

    if total_checked > 0:
        print(f"  Spread=13 -> next spread=14: "
              f"bid_far (M=mid+0.5) correct: {bid_far_correct}/{total_checked} ({100*bid_far_correct/total_checked:.1f}%)")
        print(f"  ask_far (M=mid-0.5) correct: {ask_far_correct}/{total_checked} ({100*ask_far_correct/total_checked:.1f}%)")

    # Alternative: for spread=13, check the L1 gap to L2
    # If bid is the "far" side (bid = M-7), then bid_gap to L2 should be 1 (L2 at M-8)
    # If bid is the "near" side (bid = M-6), then bid_gap should be different
    # Actually no - L2 is at a fixed location regardless

    # Let's instead look at the asymmetry directly:
    # For spread=13, is bid_gap (L1-L2) == ask_gap (L2-L1)?
    s13 = df[s13_mask]
    if len(s13) > 0:
        s13_bid_gap = s13['bid_price_1'] - s13['bid_price_2']
        s13_ask_gap = s13['ask_price_2'] - s13['ask_price_1']
        print(f"\n  Spread=13: bid_gap (L1-L2) vs ask_gap (L2-L1)")
        print(f"    bid_gap: {Counter(s13_bid_gap).most_common()}")
        print(f"    ask_gap: {Counter(s13_ask_gap).most_common()}")
        # Are they always the same?
        same = (s13_bid_gap == s13_ask_gap).mean()
        print(f"    bid_gap == ask_gap: {100*same:.1f}%")

        # When different, which is bigger?
        diff_mask = s13_bid_gap != s13_ask_gap
        if diff_mask.sum() > 0:
            bg = s13_bid_gap[diff_mask]
            ag = s13_ask_gap[diff_mask]
            print(f"    When different: bid_gap > ask_gap: {(bg > ag).sum()}, bid_gap < ask_gap: {(bg < ag).sum()}")


print("\n\n" + "=" * 80)
print("KEY ASYMMETRY: SPREAD=13 BID/ASK RELATIVE TO L2")
print("=" * 80)
# For spread=13, the L2 spread is always 16 (from earlier analysis)
# L2 bid = bid_price_2, L2 ask = ask_price_2
# L1 bid = bid_price_1 = L2_bid + bid_gap
# L1 ask = ask_price_1 = L2_ask - ask_gap
# spread_L1 = ask_price_1 - bid_price_1 = L2_ask - ask_gap - L2_bid - bid_gap
#           = L2_spread - ask_gap - bid_gap = 16 - ask_gap - bid_gap
# For spread=13: bid_gap + ask_gap = 3
# For spread=14: bid_gap + ask_gap = 2

# So for spread=13: either (bid_gap=1, ask_gap=2) or (bid_gap=2, ask_gap=1)
# This tells us WHICH SIDE the bid/ask is closer to!

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    for s in [13, 14]:
        mask = df['spread'] == s
        sub = df[mask]
        bg = sub['bid_price_1'] - sub['bid_price_2']
        ag = sub['ask_price_2'] - sub['ask_price_1']

        print(f"\n  Spread={s}:")
        print(f"    bid_gap + ask_gap sum: {Counter(bg + ag).most_common()}")

        if s == 13:
            # Split into bid_gap=1/ask_gap=2 vs bid_gap=2/ask_gap=1
            type_a = (bg == 1) & (ag == 2)  # bid closer to L2 bid
            type_b = (bg == 2) & (ag == 1)  # ask closer to L2 ask

            print(f"    bid_gap=1, ask_gap=2 (bid close, ask far): {type_a.sum()} ({100*type_a.sum()/len(sub):.1f}%)")
            print(f"    bid_gap=2, ask_gap=1 (bid far, ask close): {type_b.sum()} ({100*type_b.sum()/len(sub):.1f}%)")

            # What is the dmid when transitioning FROM these types?
            type_a_indices = sub.index[type_a]
            type_b_indices = sub.index[type_b]

            # Next tick dmid
            for label, indices in [("bid_close", type_a_indices), ("bid_far", type_b_indices)]:
                next_indices = indices + 1
                next_indices = next_indices[next_indices < len(df)]
                if len(next_indices) > 0:
                    next_dmid = df.loc[next_indices, 'dmid']
                    print(f"    {label} -> next dmid: mean={next_dmid.mean():.4f}, "
                          f"std={next_dmid.std():.3f}, n={len(next_dmid)}")


print("\n\n" + "=" * 80)
print("VOLUME SYMMETRY: WHEN SPREAD=13, IS L1 VOL ALWAYS SYMMETRIC?")
print("=" * 80)
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    # At wide spreads, when bid_vol != ask_vol, what's the relationship?
    for s in [13, 14]:
        mask = df['spread'] == s
        sub = df[mask]
        sym = (sub['bid_volume_1'] == sub['ask_volume_1']).mean()
        print(f"  Spread={s}: L1 vol symmetric: {100*sym:.1f}%")
        # When asymmetric
        asym = sub[sub['bid_volume_1'] != sub['ask_volume_1']]
        if len(asym) > 0:
            vol_diff = asym['bid_volume_1'] - asym['ask_volume_1']
            print(f"    Asymmetric ticks: {len(asym)}")
            print(f"    bid_vol - ask_vol: {Counter(vol_diff).most_common(10)}")

    # Narrow spreads: is volume ALWAYS asymmetric?
    for s in [5, 6, 7, 8, 9]:
        mask = df['spread'] == s
        sub = df[mask]
        if len(sub) == 0:
            continue
        sym = (sub['bid_volume_1'] == sub['ask_volume_1']).mean()
        print(f"  Spread={s}: L1 vol symmetric: {100*sym:.1f}%")


print("\n\n" + "=" * 80)
print("THE ASYMMETRIC MOVE REVERSAL SIGNAL")
print("=" * 80)
# Key finding: after bid-only UP, E[dmid(t+1)] is VERY negative (-0.55)
# After ask-only DOWN, E[dmid(t+1)] is VERY positive (+0.57)
# This is much stronger than the overall AC(1) = -0.44
# Is this usable?

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    df['bid_moved'] = df['dbid'] != 0
    df['ask_moved'] = df['dask'] != 0

    # Signal: bid moved up, ask didn't -> next tick reversal expected
    bid_up_only = (df['dbid'] > 0) & (df['dask'] == 0)
    bid_dn_only = (df['dbid'] < 0) & (df['dask'] == 0)
    ask_up_only = (df['dask'] > 0) & (df['dbid'] == 0)
    ask_dn_only = (df['dask'] < 0) & (df['dbid'] == 0)

    for label, mask in [
        ("bid UP only", bid_up_only),
        ("bid DOWN only", bid_dn_only),
        ("ask UP only", ask_up_only),
        ("ask DOWN only", ask_dn_only),
    ]:
        indices = df.index[mask]
        next_indices = indices + 1
        next_indices = next_indices[next_indices < len(df)]
        if len(next_indices) > 0:
            next_dmid = df.loc[next_indices, 'dmid']
            # What is the current dmid at these ticks?
            curr_dmid = df.loc[indices, 'dmid'].dropna()
            print(f"  {label}: n={mask.sum()}, "
                  f"curr_dmid={curr_dmid.mean():.3f}, "
                  f"next_dmid={next_dmid.mean():.3f}, "
                  f"reversal_ratio={-next_dmid.mean()/(curr_dmid.mean()+1e-10):.3f}")

    # Compare with symmetric moves
    sym = (df['dbid'] == df['dask']) & (df['dbid'] != 0)
    sym_indices = df.index[sym]
    next_sym = sym_indices + 1
    next_sym = next_sym[next_sym < len(df)]
    curr_sym_dmid = df.loc[sym_indices, 'dmid'].dropna()
    next_sym_dmid = df.loc[next_sym, 'dmid']
    print(f"  symmetric: n={sym.sum()}, "
          f"curr_dmid={curr_sym_dmid.mean():.3f}, "
          f"next_dmid={next_sym_dmid.mean():.3f}")


print("\n\n" + "=" * 80)
print("MULTI-TICK NARROW SPREAD SEQUENCES")
print("=" * 80)
# When we see 2+ tick narrow episodes, what's the internal sequence?
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")
    is_narrow = df['spread'] <= 9
    runs = []
    current_run_start = None
    for i in range(len(df)):
        if is_narrow.iloc[i]:
            if current_run_start is None:
                current_run_start = i
        else:
            if current_run_start is not None:
                run_len = i - current_run_start
                if run_len >= 2:
                    runs.append((current_run_start, i-1))
                current_run_start = None

    print(f"  Multi-tick narrow episodes (duration >= 2): {len(runs)}")
    for start, end in runs[:20]:
        spreads = list(df['spread'].iloc[start:end+1])
        mids = list(df['mid'].iloc[start:end+1])
        dmids = list(df['dmid'].iloc[start:end+1])
        print(f"    t={df['timestamp'].iloc[start]}-{df['timestamp'].iloc[end]}: "
              f"spreads={spreads}, dmids=[{', '.join(f'{d:+.1f}' for d in dmids if pd.notna(d))}]")


print("\n\n" + "=" * 80)
print("FINAL: SPREAD=5 IS ALWAYS DOWN, SPREAD=9 IS ALWAYS UP")
print("=" * 80)
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")
    for s in [5, 6, 7, 8, 9]:
        mask = df['spread'] == s
        if mask.sum() == 0:
            continue
        dmids = df.loc[mask, 'dmid'].dropna()
        up = (dmids > 0).sum()
        down = (dmids < 0).sum()
        zero = (dmids == 0).sum()
        print(f"  Spread={s}: UP={up}, DOWN={down}, ZERO={zero} -> "
              f"{'UP BIAS' if up > down else 'DOWN BIAS' if down > up else 'BALANCED'} "
              f"({100*up/(up+down+zero+1e-10):.1f}% up)")

    # And the exit dmid
    print(f"\n  EXIT from narrow (dmid of the tick AFTER narrow):")
    for s in [5, 6, 7, 8, 9]:
        mask = df['spread'] == s
        if mask.sum() == 0:
            continue
        indices = df.index[mask]
        next_indices = indices + 1
        next_indices = next_indices[next_indices < len(df)]
        exit_dmids = df.loc[next_indices, 'dmid'].dropna()
        up = (exit_dmids > 0).sum()
        down = (exit_dmids < 0).sum()
        zero = (exit_dmids == 0).sum()
        print(f"  After spread={s}: UP={up}, DOWN={down}, ZERO={zero}, "
              f"mean={exit_dmids.mean():+.2f}")
