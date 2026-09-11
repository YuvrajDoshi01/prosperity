"""
TOMATOES Price Microstructure Forensic Analysis
Comprehensive analysis of price levels, volumes, mid dynamics,
book state transitions, asymmetric patterns, and anomalies.
"""

import pandas as pd
import numpy as np
from collections import Counter, defaultdict
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# LOAD DATA
# ============================================================
def load_data():
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
        print(f"{name}: {len(tom)} TOMATOES rows, timestamps {tom['timestamp'].min()} to {tom['timestamp'].max()}")
    return dfs

dfs = load_data()
print()

# ============================================================
# 1. PRICE LEVEL ANALYSIS
# ============================================================
print("=" * 80)
print("1. PRICE LEVEL ANALYSIS")
print("=" * 80)

for day_name, df in dfs.items():
    print(f"\n--- {day_name} ({len(df)} ticks) ---")

    # Distinct prices at each level
    for level in [1, 2, 3]:
        bp = f'bid_price_{level}'
        ap = f'ask_price_{level}'
        if bp in df.columns:
            bid_prices = sorted(df[bp].dropna().unique())
            ask_prices = sorted(df[ap].dropna().unique())
            n_bid = df[bp].notna().sum()
            n_ask = df[ap].notna().sum()
            if len(bid_prices) > 0:
                print(f"  L{level} bid prices ({n_bid}/{len(df)} ticks present): {bid_prices[:20]}{'...' if len(bid_prices)>20 else ''} ({len(bid_prices)} distinct)")
                print(f"  L{level} ask prices ({n_ask}/{len(df)} ticks present): {ask_prices[:20]}{'...' if len(ask_prices)>20 else ''} ({len(ask_prices)} distinct)")

    # Price grid analysis
    all_bid1 = df['bid_price_1'].dropna().values
    all_ask1 = df['ask_price_1'].dropna().values
    # Check if prices are integers or have decimals
    bid1_frac = all_bid1 - np.floor(all_bid1)
    ask1_frac = all_ask1 - np.floor(all_ask1)
    print(f"  L1 bid fractional parts: {sorted(set(np.round(bid1_frac, 2)))}")
    print(f"  L1 ask fractional parts: {sorted(set(np.round(ask1_frac, 2)))}")

    # Spread distributions
    df['spread_L1'] = df['ask_price_1'] - df['bid_price_1']
    spread1_counts = df['spread_L1'].value_counts().sort_index()
    print(f"\n  L1 Spread distribution:")
    for s, c in spread1_counts.items():
        print(f"    spread={s:.0f}: {c} ticks ({100*c/len(df):.1f}%)")

    # L2 spread
    if df['ask_price_2'].notna().any():
        df['spread_L2'] = df['ask_price_2'] - df['bid_price_2']
        mask2 = df['spread_L2'].notna()
        spread2_counts = df.loc[mask2, 'spread_L2'].value_counts().sort_index()
        print(f"\n  L2 Spread distribution (on {mask2.sum()} ticks with L2):")
        for s, c in spread2_counts.items():
            print(f"    spread={s:.0f}: {c} ticks ({100*c/mask2.sum():.1f}%)")

        # L2 - L1 spread relationship
        both = df[mask2].copy()
        both['spread_diff_21'] = both['spread_L2'] - both['spread_L1']
        diff_counts = both['spread_diff_21'].value_counts().sort_index()
        print(f"\n  L2_spread - L1_spread distribution:")
        for d, c in diff_counts.items():
            print(f"    diff={d:.0f}: {c} ticks ({100*c/len(both):.1f}%)")

    # L3 spread
    if df['ask_price_3'].notna().any():
        df['spread_L3'] = df['ask_price_3'] - df['bid_price_3']
        mask3 = df['spread_L3'].notna()
        if mask3.sum() > 0:
            spread3_counts = df.loc[mask3, 'spread_L3'].value_counts().sort_index()
            print(f"\n  L3 Spread distribution (on {mask3.sum()} ticks with L3):")
            for s, c in spread3_counts.items():
                print(f"    spread={s:.0f}: {c} ticks ({100*c/mask3.sum():.1f}%)")


print("\n\n" + "=" * 80)
print("PRICE GRID ANALYSIS (Day 0)")
print("=" * 80)
df0 = dfs['day0']
# Check all price differences
all_prices = []
for col in ['bid_price_1', 'bid_price_2', 'bid_price_3', 'ask_price_1', 'ask_price_2', 'ask_price_3']:
    vals = df0[col].dropna().values
    all_prices.extend(vals)
all_prices = sorted(set(all_prices))
print(f"ALL distinct prices seen (TOMATOES, day 0): {all_prices}")
diffs = [all_prices[i+1] - all_prices[i] for i in range(len(all_prices)-1)]
print(f"Price increments between consecutive distinct prices: {[round(d,1) for d in diffs]}")
print(f"All prices are integers? {all(p == int(p) for p in all_prices)}")

# L1 bid-ask relationship
print(f"\nL1 bid prices: {sorted(df0['bid_price_1'].dropna().unique())}")
print(f"L1 ask prices: {sorted(df0['ask_price_1'].dropna().unique())}")
# Check: mid = (bid + ask) / 2
df0['mid_calc'] = (df0['bid_price_1'] + df0['ask_price_1']) / 2
df0['mid_diff'] = df0['mid_calc'] - df0['mid_price']
print(f"mid_price matches (bid1+ask1)/2? Max diff = {df0['mid_diff'].abs().max()}")
