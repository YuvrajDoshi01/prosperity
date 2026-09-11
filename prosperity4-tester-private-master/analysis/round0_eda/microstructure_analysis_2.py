"""
Part 2: Volume Structure + Mid-Price Dynamics
"""
import pandas as pd
import numpy as np
from collections import Counter
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
    dfs[name] = tom

# ============================================================
# 2. VOLUME STRUCTURE AT EACH LEVEL
# ============================================================
print("=" * 80)
print("2. VOLUME STRUCTURE AT EACH LEVEL")
print("=" * 80)

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ({len(df)} ticks) ---")

    for level in [1, 2, 3]:
        bv = f'bid_volume_{level}'
        av = f'ask_volume_{level}'
        if bv not in df.columns:
            continue
        bvols = df[bv].dropna()
        avols = df[av].dropna()
        if len(bvols) == 0:
            continue

        print(f"\n  L{level} Bid Volume: n={len(bvols)}, min={bvols.min()}, max={bvols.max()}, "
              f"mean={bvols.mean():.2f}, std={bvols.std():.2f}, median={bvols.median():.0f}")
        bv_counts = bvols.value_counts().sort_index()
        print(f"    Distribution: {dict(bv_counts)}")

        print(f"  L{level} Ask Volume: n={len(avols)}, min={avols.min()}, max={avols.max()}, "
              f"mean={avols.mean():.2f}, std={avols.std():.2f}, median={avols.median():.0f}")
        av_counts = avols.value_counts().sort_index()
        print(f"    Distribution: {dict(av_counts)}")

    # L2/L1 volume ratio
    mask = df['bid_volume_2'].notna() & df['bid_volume_1'].notna()
    if mask.sum() > 0:
        ratio_bid = df.loc[mask, 'bid_volume_2'] / df.loc[mask, 'bid_volume_1']
        ratio_ask = df.loc[mask, 'ask_volume_2'] / df.loc[mask, 'ask_volume_1']
        print(f"\n  L2/L1 volume ratio (bid): mean={ratio_bid.mean():.3f}, std={ratio_bid.std():.3f}, "
              f"min={ratio_bid.min():.2f}, max={ratio_bid.max():.2f}")
        print(f"  L2/L1 volume ratio (ask): mean={ratio_ask.mean():.3f}, std={ratio_ask.std():.3f}, "
              f"min={ratio_ask.min():.2f}, max={ratio_ask.max():.2f}")

        # Is ratio always the same?
        ratio_bid_rounded = np.round(ratio_bid, 2)
        ratio_counts = Counter(ratio_bid_rounded)
        print(f"  L2/L1 bid ratio unique values (top 20): {ratio_counts.most_common(20)}")

    # Correlation between bid and ask volumes at same level
    for level in [1, 2]:
        bv = df[f'bid_volume_{level}'].dropna()
        av = df[f'ask_volume_{level}'].dropna()
        both = df[[f'bid_volume_{level}', f'ask_volume_{level}']].dropna()
        if len(both) > 0:
            corr = both[f'bid_volume_{level}'].corr(both[f'ask_volume_{level}'])
            # How often are they equal?
            equal_pct = (both[f'bid_volume_{level}'] == both[f'ask_volume_{level}']).mean()
            print(f"\n  L{level} bid-ask vol correlation: {corr:.4f}")
            print(f"  L{level} bid == ask vol: {100*equal_pct:.1f}% of ticks")
            # Difference distribution
            diff = both[f'bid_volume_{level}'] - both[f'ask_volume_{level}']
            print(f"  L{level} bid_vol - ask_vol: mean={diff.mean():.3f}, std={diff.std():.3f}, "
                  f"min={diff.min()}, max={diff.max()}")

    # Cross-level correlation
    both_12 = df[['bid_volume_1', 'bid_volume_2']].dropna()
    if len(both_12) > 0:
        corr12 = both_12['bid_volume_1'].corr(both_12['bid_volume_2'])
        print(f"\n  L1-L2 bid vol correlation: {corr12:.4f}")

    # Zero volume check
    for level in [1, 2]:
        bv = df[f'bid_volume_{level}']
        av = df[f'ask_volume_{level}']
        zero_bid = (bv == 0).sum()
        zero_ask = (av == 0).sum()
        print(f"  L{level} zero-volume ticks: bid={zero_bid}, ask={zero_ask}")


# Deep dive on L2/L1 relationship
print("\n\n" + "=" * 80)
print("DEEP DIVE: L2/L1 VOLUME RELATIONSHIP (Day 0)")
print("=" * 80)
df0 = dfs['day0']
df0['spread'] = df0['ask_price_1'] - df0['bid_price_1']

# By spread state
for spread_val in sorted(df0['spread'].unique()):
    sub = df0[df0['spread'] == spread_val]
    ratio_bid = sub['bid_volume_2'] / sub['bid_volume_1']
    ratio_ask = sub['ask_volume_2'] / sub['ask_volume_1']
    print(f"\n  Spread={spread_val:.0f} ({len(sub)} ticks):")
    print(f"    L2/L1 bid ratio: mean={ratio_bid.mean():.3f}, std={ratio_bid.std():.3f}")
    print(f"    L2/L1 ask ratio: mean={ratio_ask.mean():.3f}, std={ratio_ask.std():.3f}")
    # Check if bid_vol_2 = bid_vol_1 * K for some integer-ish K
    ratios_r = np.round(ratio_bid, 1)
    print(f"    Rounded ratios (bid): {Counter(ratios_r).most_common(10)}")

# Check L1 bid gap (bid_price_1 vs bid_price_2)
print("\n\n" + "=" * 80)
print("L1-L2 PRICE GAP ANALYSIS (Day 0)")
print("=" * 80)
df0['bid_gap_12'] = df0['bid_price_1'] - df0['bid_price_2']
df0['ask_gap_12'] = df0['ask_price_2'] - df0['ask_price_1']
print(f"Bid gap (bid1 - bid2): {Counter(df0['bid_gap_12']).most_common()}")
print(f"Ask gap (ask2 - ask1): {Counter(df0['ask_gap_12']).most_common()}")

# When spread is narrow vs wide
for s in [5, 6, 7, 8, 9, 13, 14]:
    sub = df0[df0['spread'] == s]
    if len(sub) > 0:
        bg = Counter(sub['bid_gap_12'])
        ag = Counter(sub['ask_gap_12'])
        print(f"\n  Spread={s}: bid_gap={dict(bg)}, ask_gap={dict(ag)}")


# ============================================================
# 3. MID-PRICE DYNAMICS
# ============================================================
print("\n\n" + "=" * 80)
print("3. MID-PRICE DYNAMICS")
print("=" * 80)

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ({len(df)} ticks) ---")

    df['mid'] = (df['bid_price_1'] + df['ask_price_1']) / 2
    df['dmid'] = df['mid'].diff()
    df['spread'] = df['ask_price_1'] - df['bid_price_1']

    # All possible mid change values
    dmid_vals = df['dmid'].dropna()
    unique_dmid = sorted(dmid_vals.unique())
    print(f"  All possible dmid values ({len(unique_dmid)}): {unique_dmid}")

    # Frequency distribution
    dmid_counts = dmid_vals.value_counts().sort_index()
    print(f"\n  dmid distribution:")
    for val, count in dmid_counts.items():
        pct = 100 * count / len(dmid_vals)
        print(f"    dmid={val:+6.1f}: {count:5d} ({pct:5.1f}%)")

    # Symmetry check
    pos_sum = dmid_vals[dmid_vals > 0].sum()
    neg_sum = dmid_vals[dmid_vals < 0].sum()
    print(f"\n  Symmetry: sum(positive dmid)={pos_sum:.1f}, sum(negative dmid)={neg_sum:.1f}, "
          f"ratio={abs(pos_sum/neg_sum):.3f}")
    print(f"  Mean dmid = {dmid_vals.mean():.4f}, skew = {dmid_vals.skew():.4f}")

    # Autocorrelation
    ac1 = dmid_vals.autocorr(lag=1)
    ac2 = dmid_vals.autocorr(lag=2)
    ac3 = dmid_vals.autocorr(lag=3)
    ac4 = dmid_vals.autocorr(lag=4)
    print(f"  Autocorrelation: AC(1)={ac1:.4f}, AC(2)={ac2:.4f}, AC(3)={ac3:.4f}, AC(4)={ac4:.4f}")

    # Conditional on spread state
    print(f"\n  dmid conditioned on CURRENT spread:")
    for spread_val in sorted(df['spread'].dropna().unique()):
        mask = (df['spread'] == spread_val) & df['dmid'].notna()
        if mask.sum() > 0:
            sub = df.loc[mask, 'dmid']
            vals = sorted(sub.unique())
            print(f"    spread={spread_val:.0f} ({mask.sum()} ticks): "
                  f"mean={sub.mean():.3f}, vals={vals}")

    # Conditional on PREVIOUS spread
    df['prev_spread'] = df['spread'].shift(1)
    print(f"\n  dmid conditioned on PREVIOUS spread:")
    for spread_val in sorted(df['prev_spread'].dropna().unique()):
        mask = (df['prev_spread'] == spread_val) & df['dmid'].notna()
        if mask.sum() > 0:
            sub = df.loc[mask, 'dmid']
            nonzero = (sub != 0).sum()
            mean_abs = sub.abs().mean()
            print(f"    prev_spread={spread_val:.0f} ({mask.sum()} ticks): "
                  f"mean={sub.mean():.3f}, |mean|={mean_abs:.3f}, "
                  f"nonzero={nonzero} ({100*nonzero/mask.sum():.1f}%)")

    # Absolute mid changes
    abs_dmid = dmid_vals.abs()
    print(f"\n  |dmid| stats: mean={abs_dmid.mean():.3f}, max={abs_dmid.max():.1f}")
    print(f"  |dmid| > 0: {(abs_dmid > 0).sum()} ticks ({100*(abs_dmid > 0).sum()/len(abs_dmid):.1f}%)")
    print(f"  |dmid| >= 1: {(abs_dmid >= 1).sum()} ticks ({100*(abs_dmid >= 1).sum()/len(abs_dmid):.1f}%)")
    print(f"  |dmid| >= 2: {(abs_dmid >= 2).sum()} ticks ({100*(abs_dmid >= 2).sum()/len(abs_dmid):.1f}%)")
    print(f"  |dmid| >= 3: {(abs_dmid >= 3).sum()} ticks ({100*(abs_dmid >= 3).sum()/len(abs_dmid):.1f}%)")

print("\n\n" + "=" * 80)
print("MID-PRICE: POSSIBLE VALUES CHECK (Day 0)")
print("=" * 80)
df0 = dfs['day0']
df0['mid'] = (df0['bid_price_1'] + df0['ask_price_1']) / 2
# Are mids always multiples of 0.5?
mid_frac = df0['mid'] % 0.5
print(f"Mid is always multiple of 0.5? {(mid_frac == 0).all()}")
mid_frac2 = df0['mid'] % 1.0
print(f"Mid fractional parts (mod 1): {sorted(set(np.round(mid_frac2, 2)))}")
# How about the individual bid/ask - are they always integers?
print(f"Bid1 always integer? {(df0['bid_price_1'] == df0['bid_price_1'].astype(int)).all()}")
print(f"Ask1 always integer? {(df0['ask_price_1'] == df0['ask_price_1'].astype(int)).all()}")
# Since bid and ask are integers, mid = (b+a)/2 is either integer or half-integer
# This means dmid is always a multiple of 0.5
df0['dmid'] = df0['mid'].diff()
dmid_mod = df0['dmid'].dropna() % 0.5
print(f"dmid always multiple of 0.5? {(np.abs(dmid_mod) < 1e-10).all() | (np.abs(dmid_mod - 0.5) < 1e-10).all()}")
print(f"dmid mod 0.5 unique values: {sorted(set(np.round(dmid_mod, 3)))}")
