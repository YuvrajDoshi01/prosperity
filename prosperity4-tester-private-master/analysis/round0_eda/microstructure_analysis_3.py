"""
Part 3: Book State Transitions + Asymmetric Patterns
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
    # Compute derived fields
    tom['spread'] = tom['ask_price_1'] - tom['bid_price_1']
    tom['mid'] = (tom['bid_price_1'] + tom['ask_price_1']) / 2
    tom['dmid'] = tom['mid'].diff()
    tom['dbid'] = tom['bid_price_1'].diff()
    tom['dask'] = tom['ask_price_1'].diff()
    dfs[name] = tom

# ============================================================
# 4. BOOK STATE TRANSITIONS
# ============================================================
print("=" * 80)
print("4. BOOK STATE TRANSITIONS")
print("=" * 80)

# Spread state transition matrix
for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    # Spread transition
    df['next_spread'] = df['spread'].shift(-1)
    trans = df[df['next_spread'].notna()].groupby(['spread', 'next_spread']).size().reset_index(name='count')
    total_by_spread = trans.groupby('spread')['count'].sum()

    print(f"\n  Spread Transition Matrix (row=current, col=next, as %):")
    spreads_all = sorted(df['spread'].unique())
    header = "  from\\to  " + "".join(f"{s:8.0f}" for s in spreads_all)
    print(header)
    for s_from in spreads_all:
        row = trans[trans['spread'] == s_from]
        total = total_by_spread[s_from]
        row_str = f"  {s_from:6.0f}   "
        for s_to in spreads_all:
            match = row[row['next_spread'] == s_to]
            if len(match) > 0:
                pct = 100 * match['count'].values[0] / total
                row_str += f"{pct:7.1f}%"
            else:
                row_str += f"      -"
        row_str += f"  (n={total})"
        print(row_str)

    # Spread narrowing: what happens to mid?
    print(f"\n  SPREAD NARROWING ANALYSIS:")
    for s_wide in [13, 14]:
        for s_narrow in [5, 6, 7, 8, 9]:
            mask = (df['spread'].shift(1) == s_wide) & (df['spread'] == s_narrow)
            if mask.sum() > 0:
                dmids = df.loc[mask, 'dmid']
                print(f"    {s_wide}->{s_narrow}: n={mask.sum()}, dmid mean={dmids.mean():.2f}, "
                      f"std={dmids.std():.2f}, all vals={sorted(dmids.unique())}")

    # Spread widening: what happens to mid?
    print(f"\n  SPREAD WIDENING ANALYSIS:")
    for s_narrow in [5, 6, 7, 8, 9]:
        for s_wide in [13, 14]:
            mask = (df['spread'].shift(1) == s_narrow) & (df['spread'] == s_wide)
            if mask.sum() > 0:
                dmids = df.loc[mask, 'dmid']
                print(f"    {s_narrow}->{s_wide}: n={mask.sum()}, dmid mean={dmids.mean():.2f}, "
                      f"std={dmids.std():.2f}, all vals={sorted(dmids.unique())}")

    # Narrow spread duration
    print(f"\n  NARROW SPREAD DURATION (consecutive ticks in narrow state):")
    is_narrow = df['spread'] <= 9
    # Find runs of narrow spread
    runs = []
    current_run = 0
    current_spreads = []
    for i in range(len(df)):
        if is_narrow.iloc[i]:
            current_run += 1
            current_spreads.append(df['spread'].iloc[i])
        else:
            if current_run > 0:
                runs.append((current_run, current_spreads.copy()))
            current_run = 0
            current_spreads = []
    if current_run > 0:
        runs.append((current_run, current_spreads.copy()))

    run_lens = [r[0] for r in runs]
    if run_lens:
        print(f"    Number of narrow episodes: {len(runs)}")
        print(f"    Duration distribution: {Counter(run_lens).most_common()}")
        print(f"    Mean duration: {np.mean(run_lens):.2f} ticks")
        print(f"    Max duration: {max(run_lens)} ticks")

    # Wide-to-wide (13 vs 14) oscillation
    wide_mask = df['spread'].isin([13, 14])
    wide_only = df[wide_mask]['spread'].values
    if len(wide_only) > 1:
        stays = (wide_only[1:] == wide_only[:-1]).sum()
        changes = (wide_only[1:] != wide_only[:-1]).sum()
        print(f"\n  Wide spread oscillation (13<->14):")
        print(f"    Stays same: {stays} ({100*stays/(stays+changes):.1f}%)")
        print(f"    Changes: {changes} ({100*changes/(stays+changes):.1f}%)")


# ============================================================
# 5. ASYMMETRIC PATTERNS (BID VS ASK)
# ============================================================
print("\n\n" + "=" * 80)
print("5. ASYMMETRIC PATTERNS")
print("=" * 80)

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    # Classify each tick by what moved
    df['bid_moved'] = df['dbid'] != 0
    df['ask_moved'] = df['dask'] != 0

    # Four categories
    neither = (~df['bid_moved'] & ~df['ask_moved']).sum()
    both = (df['bid_moved'] & df['ask_moved']).sum()
    bid_only = (df['bid_moved'] & ~df['ask_moved']).sum()
    ask_only = (~df['bid_moved'] & df['ask_moved']).sum()
    total = neither + both + bid_only + ask_only

    print(f"  Move classification (excluding first tick):")
    print(f"    Neither moved:  {neither} ({100*neither/total:.1f}%)")
    print(f"    Both moved:     {both} ({100*both/total:.1f}%)")
    print(f"    Bid only:       {bid_only} ({100*bid_only/total:.1f}%)")
    print(f"    Ask only:       {ask_only} ({100*ask_only/total:.1f}%)")

    # When both move, do they move by the same amount?
    both_mask = df['bid_moved'] & df['ask_moved']
    both_df = df[both_mask]
    if len(both_df) > 0:
        same_dir_same_amt = (both_df['dbid'] == both_df['dask']).sum()
        same_dir_diff_amt = ((both_df['dbid'] * both_df['dask'] > 0) & (both_df['dbid'] != both_df['dask'])).sum()
        opposite = (both_df['dbid'] * both_df['dask'] < 0).sum()
        print(f"\n  When both move ({len(both_df)} ticks):")
        print(f"    Same direction, same amount: {same_dir_same_amt} ({100*same_dir_same_amt/len(both_df):.1f}%)")
        print(f"    Same direction, diff amount: {same_dir_diff_amt} ({100*same_dir_diff_amt/len(both_df):.1f}%)")
        print(f"    Opposite directions:         {opposite} ({100*opposite/len(both_df):.1f}%)")

        # Distribution of dbid - dask when both move
        diff_ba = both_df['dbid'] - both_df['dask']
        print(f"    dbid - dask distribution: {Counter(diff_ba).most_common(20)}")

    # BID-ONLY moves: what happens next tick?
    print(f"\n  BID-ONLY moves ({bid_only} ticks):")
    bid_only_mask = df['bid_moved'] & ~df['ask_moved']
    for idx in df.index[bid_only_mask]:
        pass  # just count

    if bid_only > 0:
        bid_only_df = df[bid_only_mask].copy()
        bid_only_df['next_dbid'] = df['dbid'].shift(-1).loc[bid_only_mask]
        bid_only_df['next_dask'] = df['dask'].shift(-1).loc[bid_only_mask]
        bid_only_df['next_dmid'] = df['dmid'].shift(-1).loc[bid_only_mask]

        print(f"    dbid values when bid-only: {Counter(bid_only_df['dbid']).most_common()}")
        # Next tick: does ask follow?
        next_ask_follows = (bid_only_df['next_dask'] != 0).sum()
        next_bid_continues = (bid_only_df['next_dbid'] != 0).sum()
        print(f"    Next tick: ask follows={next_ask_follows} ({100*next_ask_follows/len(bid_only_df):.1f}%), "
              f"bid continues={next_bid_continues} ({100*next_bid_continues/len(bid_only_df):.1f}%)")
        print(f"    Next tick dmid: mean={bid_only_df['next_dmid'].dropna().mean():.3f}")

        # Conditional: bid-only UP vs bid-only DOWN
        bid_up = bid_only_df[bid_only_df['dbid'] > 0]
        bid_dn = bid_only_df[bid_only_df['dbid'] < 0]
        if len(bid_up) > 0:
            print(f"    Bid-only UP ({len(bid_up)}): next dmid mean={bid_up['next_dmid'].dropna().mean():.3f}")
        if len(bid_dn) > 0:
            print(f"    Bid-only DOWN ({len(bid_dn)}): next dmid mean={bid_dn['next_dmid'].dropna().mean():.3f}")

    # ASK-ONLY moves
    print(f"\n  ASK-ONLY moves ({ask_only} ticks):")
    ask_only_mask = ~df['bid_moved'] & df['ask_moved']

    if ask_only > 0:
        ask_only_df = df[ask_only_mask].copy()
        ask_only_df['next_dbid'] = df['dbid'].shift(-1).loc[ask_only_mask]
        ask_only_df['next_dask'] = df['dask'].shift(-1).loc[ask_only_mask]
        ask_only_df['next_dmid'] = df['dmid'].shift(-1).loc[ask_only_mask]

        print(f"    dask values when ask-only: {Counter(ask_only_df['dask']).most_common()}")
        next_bid_follows = (ask_only_df['next_dbid'] != 0).sum()
        next_ask_continues = (ask_only_df['next_dask'] != 0).sum()
        print(f"    Next tick: bid follows={next_bid_follows} ({100*next_bid_follows/len(ask_only_df):.1f}%), "
              f"ask continues={next_ask_continues} ({100*next_ask_continues/len(ask_only_df):.1f}%)")
        print(f"    Next tick dmid: mean={ask_only_df['next_dmid'].dropna().mean():.3f}")

        ask_up = ask_only_df[ask_only_df['dask'] > 0]
        ask_dn = ask_only_df[ask_only_df['dask'] < 0]
        if len(ask_up) > 0:
            print(f"    Ask-only UP ({len(ask_up)}): next dmid mean={ask_up['next_dmid'].dropna().mean():.3f}")
        if len(ask_dn) > 0:
            print(f"    Ask-only DOWN ({len(ask_dn)}): next dmid mean={ask_dn['next_dmid'].dropna().mean():.3f}")

    # Are asymmetric moves more predictive than symmetric ones?
    print(f"\n  PREDICTIVE COMPARISON:")
    # Symmetric moves (both by same amount)
    sym_mask = (df['dbid'] == df['dask']) & (df['dbid'] != 0)
    sym_df = df[sym_mask].copy()
    sym_df['next_dmid'] = df['dmid'].shift(-1).loc[sym_mask]
    if len(sym_df) > 0:
        # Correlation of current dmid with next dmid
        sym_corr = sym_df['dmid'].corr(sym_df['next_dmid'])
        print(f"    Symmetric moves: n={len(sym_df)}, dmid->next_dmid corr={sym_corr:.4f}")

    asym_mask = (df['dbid'] != df['dask']) & (df['bid_moved'] | df['ask_moved'])
    asym_df = df[asym_mask].copy()
    asym_df['next_dmid'] = df['dmid'].shift(-1).loc[asym_mask]
    if len(asym_df) > 0:
        asym_corr = asym_df['dmid'].corr(asym_df['next_dmid'])
        print(f"    Asymmetric moves: n={len(asym_df)}, dmid->next_dmid corr={asym_corr:.4f}")

    # SPREAD CHANGES as asymmetry
    print(f"\n  SPREAD CHANGE ANALYSIS:")
    df['dspread'] = df['spread'].diff()
    dspread_counts = df['dspread'].dropna().value_counts().sort_index()
    print(f"    dspread distribution:")
    for val, cnt in dspread_counts.items():
        print(f"      dspread={val:+6.0f}: {cnt:5d}")

    # When spread narrows by 1 (e.g., 14->13): which side moved?
    s_narrow_by_1 = df['dspread'] == -1
    if s_narrow_by_1.sum() > 0:
        sub = df[s_narrow_by_1]
        bid_up_ask_same = (sub['dbid'] > 0) & (sub['dask'] == 0)
        bid_same_ask_dn = (sub['dbid'] == 0) & (sub['dask'] < 0)
        both_moved = (sub['dbid'] != 0) & (sub['dask'] != 0)
        print(f"\n    Spread narrows by 1 ({s_narrow_by_1.sum()} ticks):")
        print(f"      Bid UP, ask same: {bid_up_ask_same.sum()}")
        print(f"      Bid same, ask DOWN: {bid_same_ask_dn.sum()}")
        print(f"      Both moved: {both_moved.sum()}")
