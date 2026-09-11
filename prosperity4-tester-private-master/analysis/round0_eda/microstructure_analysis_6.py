"""
Part 6: Final synthesis — the exact MM bot mechanism
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
# DEFINITIVE: THE BOT'S SPREAD STATE MACHINE
# ============================================================
print("=" * 80)
print("THE BOT'S SPREAD STATE MACHINE: NARROW SPREADS ARE DETERMINISTIC")
print("=" * 80)

# The key discovery: spread=5 ALWAYS has DOWN entry, UP exit
# spread=9 ALWAYS has UP entry, DOWN exit
# The pattern alternates: 5=DOWN, 6=UP, 7=DOWN, 8=UP, 9=UP

# Hypothesis: narrow spreads come in two types:
# Type A (5,7): mid drops THEN reverts
# Type B (6,8,9): mid rises THEN reverts

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    # For each narrow spread, classify: was entry DOWN or UP?
    for s in [5, 6, 7, 8, 9]:
        mask = (df['spread'] == s) & df['dmid'].notna()
        if mask.sum() == 0:
            continue
        dmids = df.loc[mask, 'dmid']
        up_pct = 100 * (dmids > 0).sum() / len(dmids)
        dn_pct = 100 * (dmids < 0).sum() / len(dmids)

        # Direction of mid when ENTERING this spread:
        # spread=5: mid always moves DOWN (100% down, 0% up)
        # spread=9: mid always moves UP (98-100% up)
        print(f"  Spread={s}: entry DOWN={dn_pct:.1f}%, entry UP={up_pct:.1f}%, mean_entry={dmids.mean():+.2f}")


# ============================================================
# THE 'ROUNDING DIRECTION' HYPOTHESIS
# ============================================================
print("\n\n" + "=" * 80)
print("THE ROUNDING DIRECTION HYPOTHESIS")
print("=" * 80)

# Internal mid M changes in multiples of 0.5
# For odd spreads: bid = M - ceil(spread/2), ask = M + floor(spread/2)
#                  OR bid = M - floor(spread/2), ask = M + ceil(spread/2)

# For spread=13: bid = M-7, ask = M+6 (bid far) → obs_mid = M - 0.5
#            OR: bid = M-6, ask = M+7 (ask far) → obs_mid = M + 0.5
# For spread=5: bid = M-3, ask = M+2 (bid far) → obs_mid = M - 0.5
#           OR: bid = M-2, ask = M+3 (ask far) → obs_mid = M + 0.5

# Since spread=5 always has DOWN entry dmid, and spread=9 always has UP entry...
# Let's see: when coming from spread=13 or 14 to spread=5:

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    for s_narrow in [5, 6, 7, 8, 9]:
        for s_wide in [13, 14]:
            mask = (df['spread'].shift(1) == s_wide) & (df['spread'] == s_narrow)
            if mask.sum() == 0:
                continue
            sub = df[mask]

            # What is bid1 in terms of the wide-spread mid?
            prev_mid = df['mid'].shift(1).loc[mask]
            new_bid = sub['bid_price_1']
            new_ask = sub['ask_price_1']

            bid_shift = new_bid - prev_mid
            ask_shift = new_ask - prev_mid

            print(f"\n  {s_wide} -> {s_narrow} ({mask.sum()} transitions):")
            print(f"    bid - prev_mid: mean={bid_shift.mean():.2f}, {Counter(np.round(bid_shift, 1)).most_common(5)}")
            print(f"    ask - prev_mid: mean={ask_shift.mean():.2f}, {Counter(np.round(ask_shift, 1)).most_common(5)}")


# ============================================================
# CRITICAL OBSERVATION: NARROW SPREAD L2 STRUCTURE
# ============================================================
print("\n\n" + "=" * 80)
print("NARROW SPREAD: WHERE IS L2 RELATIVE TO L1?")
print("=" * 80)

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    for s in [5, 6, 7, 8, 9]:
        mask = df['spread'] == s
        sub = df[mask]
        if len(sub) == 0:
            continue

        # L2 positions
        l2_spread = sub['ask_price_2'] - sub['bid_price_2']
        bid_gap = sub['bid_price_1'] - sub['bid_price_2']
        ask_gap = sub['ask_price_2'] - sub['ask_price_1']

        # The key insight: during narrow spread, is L2 still at "normal" locations?
        # I.e., is L2 the same as what we'd see from a spread=13/14 book?

        print(f"\n  Spread={s} ({len(sub)} ticks):")
        print(f"    L2 spread: {Counter(l2_spread).most_common()}")
        print(f"    bid_gap: {Counter(bid_gap).most_common()}")
        print(f"    ask_gap: {Counter(ask_gap).most_common()}")

        # Compare to the previous tick's L2
        prev_bid2 = df['bid_price_2'].shift(1).loc[mask]
        prev_ask2 = df['ask_price_2'].shift(1).loc[mask]
        curr_bid2 = sub['bid_price_2']
        curr_ask2 = sub['ask_price_2']
        bid2_change = curr_bid2 - prev_bid2
        ask2_change = curr_ask2 - prev_ask2

        print(f"    L2 bid change from prev tick: {Counter(bid2_change.dropna().astype(int)).most_common(5)}")
        print(f"    L2 ask change from prev tick: {Counter(ask2_change.dropna().astype(int)).most_common(5)}")


# ============================================================
# DOES THE BOT RE-QUOTE L2 DURING NARROW SPREADS?
# ============================================================
print("\n\n" + "=" * 80)
print("NARROW SPREAD: IS L2 THE OLD L1?")
print("=" * 80)

# Hypothesis: When spread narrows, one side of L1 becomes L2
# E.g., for spread=5 (DOWN entry): the new bid jumps UP close to old ask,
# and the old L1 bid becomes L2 bid

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    for s_narrow in [5, 7]:  # DOWN entry types
        mask = (df['spread'] == s_narrow) & (df['spread'].shift(1).isin([13, 14]))
        sub = df[mask]
        if len(sub) == 0:
            continue

        prev_bid1 = df['bid_price_1'].shift(1).loc[mask]
        prev_ask1 = df['ask_price_1'].shift(1).loc[mask]
        curr_bid1 = sub['bid_price_1']
        curr_ask1 = sub['ask_price_1']
        curr_bid2 = sub['bid_price_2']
        curr_ask2 = sub['ask_price_2']

        # Is the new L2 bid = old L1 bid?
        l2bid_eq_old_l1bid = (curr_bid2 == prev_bid1).mean()
        # Is the new L2 ask = old L1 ask?
        l2ask_eq_old_l1ask = (curr_ask2 == prev_ask1).mean()

        # Is the new L1 ask = old L1 ask?
        l1ask_eq_old_l1ask = (curr_ask1 == prev_ask1).mean()

        print(f"\n  {s_narrow} (DOWN entry):")
        print(f"    new L2 bid == old L1 bid? {100*l2bid_eq_old_l1bid:.1f}%")
        print(f"    new L2 ask == old L1 ask? {100*l2ask_eq_old_l1ask:.1f}%")
        print(f"    new L1 ask == old L1 ask? {100*l1ask_eq_old_l1ask:.1f}%")
        print(f"    new L1 bid - old L1 ask: {Counter((curr_bid1 - prev_ask1).astype(int)).most_common(5)}")

    for s_narrow in [8, 9]:  # UP entry types
        mask = (df['spread'] == s_narrow) & (df['spread'].shift(1).isin([13, 14]))
        sub = df[mask]
        if len(sub) == 0:
            continue

        prev_bid1 = df['bid_price_1'].shift(1).loc[mask]
        prev_ask1 = df['ask_price_1'].shift(1).loc[mask]
        curr_bid1 = sub['bid_price_1']
        curr_ask1 = sub['ask_price_1']
        curr_bid2 = sub['bid_price_2']
        curr_ask2 = sub['ask_price_2']

        l2bid_eq_old_l1bid = (curr_bid2 == prev_bid1).mean()
        l2ask_eq_old_l1ask = (curr_ask2 == prev_ask1).mean()
        l1bid_eq_old_l1bid = (curr_bid1 == prev_bid1).mean()

        print(f"\n  {s_narrow} (UP entry):")
        print(f"    new L2 bid == old L1 bid? {100*l2bid_eq_old_l1bid:.1f}%")
        print(f"    new L2 ask == old L1 ask? {100*l2ask_eq_old_l1ask:.1f}%")
        print(f"    new L1 bid == old L1 bid? {100*l1bid_eq_old_l1bid:.1f}%")
        print(f"    new L1 ask - old L1 bid: {Counter((curr_ask1 - prev_bid1).astype(int)).most_common(5)}")


# ============================================================
# VOLUME DURING NARROW: IS IT A SECOND BOT?
# ============================================================
print("\n\n" + "=" * 80)
print("NARROW SPREAD: L1 VOL ANALYSIS — ONE BOT OR TWO?")
print("=" * 80)

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    for s in [5, 6, 7, 8, 9]:
        mask = df['spread'] == s
        sub = df[mask]
        if len(sub) == 0:
            continue

        bv1 = sub['bid_volume_1']
        av1 = sub['ask_volume_1']
        bv2 = sub['bid_volume_2']
        av2 = sub['ask_volume_2']

        # Key question: is the L1 volume at narrow spread drawn from the SAME
        # distribution as normal L1 volume ([2,12] uniform-ish)?
        print(f"\n  Spread={s} ({len(sub)} ticks):")
        print(f"    L1 bid vol: min={bv1.min()}, max={bv1.max()}, mean={bv1.mean():.1f}, dist={Counter(bv1).most_common()}")
        print(f"    L1 ask vol: min={av1.min()}, max={av1.max()}, mean={av1.mean():.1f}, dist={Counter(av1).most_common()}")
        print(f"    L2 bid vol: min={bv2.min()}, max={bv2.max()}, mean={bv2.mean():.1f}")
        print(f"    L2 ask vol: min={av2.min()}, max={av2.max()}, mean={av2.mean():.1f}")

        # Compare the L1+L2 total at narrow with L1+L2 total at wide
        total_narrow = (bv1 + bv2 + av1 + av2).mean()
        wide_mask = df['spread'].isin([13, 14])
        wide = df[wide_mask]
        total_wide = (wide['bid_volume_1'] + wide['bid_volume_2'] +
                      wide['ask_volume_1'] + wide['ask_volume_2']).mean()
        print(f"    Total book vol (L1+L2): narrow={total_narrow:.0f}, wide={total_wide:.0f}")


# ============================================================
# THE ABSOLUTE ENTRY DMID BY NARROW SPREAD TYPE
# ============================================================
print("\n\n" + "=" * 80)
print("NARROW SPREAD: ABSOLUTE ENTRY DMID CONDITIONAL ON PREV SPREAD + NEW SPREAD")
print("=" * 80)

df0 = dfs['day0']
for s_from in [13, 14]:
    for s_to in [5, 6, 7, 8, 9]:
        mask = (df0['spread'].shift(1) == s_from) & (df0['spread'] == s_to)
        if mask.sum() == 0:
            continue
        dmids = df0.loc[mask, 'dmid']
        abs_dmids = dmids.abs()
        print(f"  {s_from} -> {s_to}: n={mask.sum()}, |dmid| mean={abs_dmids.mean():.2f}, "
              f"dmid mean={dmids.mean():+.2f}, vals={sorted(dmids.unique())}")


# ============================================================
# PROBABILITY OF NARROW SPREAD BY RECENT HISTORY
# ============================================================
print("\n\n" + "=" * 80)
print("PROBABILITY OF NARROW SPREAD CONDITIONAL ON RECENT EVENTS")
print("=" * 80)

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ---")

    df['is_narrow'] = (df['spread'] <= 9).astype(int)
    df['prev_is_narrow'] = df['is_narrow'].shift(1)
    df['abs_dmid'] = df['dmid'].abs()
    df['prev_abs_dmid'] = df['abs_dmid'].shift(1)

    # P(narrow) after a large |dmid| vs small |dmid|
    for threshold in [0, 0.5, 1.0, 1.5, 2.0, 3.0]:
        mask = (df['prev_abs_dmid'] >= threshold) & df['prev_is_narrow'].notna()
        if mask.sum() > 0:
            p_narrow = df.loc[mask, 'is_narrow'].mean()
            print(f"  P(narrow | prev |dmid| >= {threshold}): {100*p_narrow:.2f}% (n={mask.sum()})")

    # Time since last narrow spread
    df['ticks_since_narrow'] = 0
    count = 0
    for i in range(len(df)):
        if df['is_narrow'].iloc[i]:
            count = 0
        else:
            count += 1
        df.loc[df.index[i], 'ticks_since_narrow'] = count

    # P(narrow) as function of time since last narrow
    for t in [0, 1, 5, 10, 20, 50]:
        mask = df['ticks_since_narrow'] == t
        if mask.sum() > 0:
            p_next_narrow = (df['is_narrow'].shift(-1).loc[mask]).mean()
            print(f"  P(narrow next | {t} ticks since last narrow): {100*p_next_narrow:.2f}% (n={mask.sum()})")
