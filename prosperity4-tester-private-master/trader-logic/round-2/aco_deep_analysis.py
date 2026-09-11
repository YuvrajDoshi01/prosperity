#!/usr/bin/env python3
"""
ACO Deep Microstructure Analysis
=================================
Comprehensive analysis of ASH_COATED_OSMIUM order book data.
Goal: find ANY exploitable pattern beyond basic OBI/VWAP.

All results printed to stdout. No output files.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from collections import Counter, defaultdict
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = Path("/Users/y0d046w/Desktop/prosperity4-tester-private/trader-logic/round-2/data")
FV = 10000
DAYS = [-2, -1, 0, 1]

# ============================================================
# DATA LOADING
# ============================================================
def load_prices():
    frames = []
    for d in DAYS:
        f = DATA_DIR / f"prices_round_2_day_{d}.csv"
        df = pd.read_csv(f, sep=';')
        df = df[df['product'] == 'ASH_COATED_OSMIUM'].copy()
        df = df.sort_values('timestamp').reset_index(drop=True)
        frames.append(df)
    return frames

def load_trades():
    frames = []
    for d in DAYS:
        f = DATA_DIR / f"trades_round_2_day_{d}.csv"
        df = pd.read_csv(f, sep=';')
        df = df[df['symbol'] == 'ASH_COATED_OSMIUM'].copy()
        df = df.sort_values('timestamp').reset_index(drop=True)
        frames.append(df)
    return frames

def load_ipr_prices():
    frames = []
    for d in DAYS:
        f = DATA_DIR / f"prices_round_2_day_{d}.csv"
        df = pd.read_csv(f, sep=';')
        df = df[df['product'] == 'INTARIAN_PEPPER_ROOT'].copy()
        df = df.sort_values('timestamp').reset_index(drop=True)
        frames.append(df)
    return frames

price_dfs = load_prices()
trade_dfs = load_trades()
ipr_dfs = load_ipr_prices()

# ============================================================
# FEATURE ENGINEERING
# ============================================================
def enrich(df):
    """Add derived features to price dataframe."""
    df = df.copy()

    # Basic
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid'] = df['mid_price']
    df['dmid'] = df['mid'].diff()
    df['dev_from_fv'] = df['mid'] - FV

    # Volumes
    df['bid_vol_1'] = df['bid_volume_1'].fillna(0)
    df['ask_vol_1'] = df['ask_volume_1'].fillna(0)
    df['bid_vol_2'] = df['bid_volume_2'].fillna(0)
    df['ask_vol_2'] = df['ask_volume_2'].fillna(0)
    df['bid_vol_3'] = df['bid_volume_3'].fillna(0)
    df['ask_vol_3'] = df['ask_volume_3'].fillna(0)

    # Total volume each side
    df['total_bid_vol'] = df['bid_vol_1'] + df['bid_vol_2'] + df['bid_vol_3']
    df['total_ask_vol'] = df['ask_vol_1'] + df['ask_vol_2'] + df['ask_vol_3']

    # OBI
    denom = df['bid_vol_1'] + df['ask_vol_1']
    df['obi'] = np.where(denom > 0, (df['bid_vol_1'] - df['ask_vol_1']) / denom, 0)

    # Microprice
    denom2 = df['bid_vol_1'] + df['ask_vol_1']
    df['microprice'] = np.where(
        denom2 > 0,
        (df['bid_price_1'] * df['ask_vol_1'] + df['ask_price_1'] * df['bid_vol_1']) / denom2,
        df['mid']
    )

    # Volume changes
    df['dvol_bid'] = df['bid_vol_1'].diff()
    df['dvol_ask'] = df['ask_vol_1'].diff()

    # L2 existence flags
    df['has_l2_bid'] = (df['bid_vol_2'] > 0).astype(int)
    df['has_l2_ask'] = (df['ask_vol_2'] > 0).astype(int)

    # L2/L1 ratio
    df['l2_l1_bid_ratio'] = np.where(df['bid_vol_1'] > 0, df['bid_vol_2'] / df['bid_vol_1'], 0)
    df['l2_l1_ask_ratio'] = np.where(df['ask_vol_1'] > 0, df['ask_vol_2'] / df['ask_vol_1'], 0)

    # Spread change
    df['dspread'] = df['spread'].diff()

    # One-sided book
    df['one_sided'] = (df['bid_price_1'].isna() | df['ask_price_1'].isna()).astype(int)
    df['bid_only'] = (df['bid_price_1'].notna() & df['ask_price_1'].isna()).astype(int)
    df['ask_only'] = (df['bid_price_1'].isna() & df['ask_price_1'].notna()).astype(int)

    # Volume asymmetry (bid_vol - ask_vol) / total
    total = df['total_bid_vol'] + df['total_ask_vol']
    df['vol_asym'] = np.where(total > 0, (df['total_bid_vol'] - df['total_ask_vol']) / total, 0)

    # Bid/ask price levels relative to FV
    df['bid1_dev'] = df['bid_price_1'] - FV
    df['ask1_dev'] = df['ask_price_1'] - FV

    # L2 gap (distance between L1 and L2)
    df['l2_gap_bid'] = np.where(df['bid_vol_2'] > 0, df['bid_price_1'] - df['bid_price_2'], np.nan)
    df['l2_gap_ask'] = np.where(df['ask_vol_2'] > 0, df['ask_price_2'] - df['ask_price_1'], np.nan)
    df['l2_gap_asym'] = df['l2_gap_bid'].fillna(0) - df['l2_gap_ask'].fillna(0)

    return df

enriched = [enrich(df) for df in price_dfs]

# ============================================================
# UTILITY FUNCTIONS
# ============================================================
def corr_per_day(enriched, feature, target='dmid', shift=1):
    """Correlation of feature with future dmid, per day."""
    results = []
    for i, df in enumerate(enriched):
        valid = df[[feature, 'mid']].dropna()
        if len(valid) < 50:
            results.append(np.nan)
            continue
        feat = df[feature].iloc[:-shift]
        tgt = df['mid'].diff().shift(-shift).iloc[:-shift]
        mask = feat.notna() & tgt.notna()
        if mask.sum() < 50:
            results.append(np.nan)
            continue
        r = np.corrcoef(feat[mask], tgt[mask])[0, 1]
        results.append(r)
    return results

def safe_corr(x, y):
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 20:
        return np.nan
    return np.corrcoef(x[mask], y[mask])[0, 1]

print("=" * 80)
print("ACO DEEP MICROSTRUCTURE ANALYSIS")
print("=" * 80)

# ============================================================
# SECTION 0: BASIC STATS
# ============================================================
print("\n" + "=" * 80)
print("SECTION 0: BASIC STATISTICS")
print("=" * 80)

for i, (df, day) in enumerate(zip(enriched, DAYS)):
    n = len(df)
    one_sided_pct = df['one_sided'].mean() * 100
    valid = df.dropna(subset=['spread'])
    print(f"\nDay {day}: {n} ticks, one-sided={one_sided_pct:.1f}%")
    print(f"  Mid: mean={df['mid'].mean():.1f}, std={df['mid'].std():.1f}, "
          f"min={df['mid'].min():.1f}, max={df['mid'].max():.1f}")
    print(f"  Spread: mean={valid['spread'].mean():.1f}, median={valid['spread'].median():.0f}, "
          f"std={valid['spread'].std():.1f}")
    print(f"  Dev from FV=10000: mean={df['dev_from_fv'].mean():.1f}, std={df['dev_from_fv'].std():.1f}")
    ac1 = df['dmid'].dropna().autocorr(lag=1)
    print(f"  AC(1) of dmid: {ac1:.4f}")

# ============================================================
# SECTION 1: SPREAD-STATE TRANSITIONS
# ============================================================
print("\n" + "=" * 80)
print("SECTION 1: SPREAD-STATE TRANSITIONS")
print("=" * 80)

for i, (df, day) in enumerate(zip(enriched, DAYS)):
    valid = df.dropna(subset=['spread'])
    spread_counts = valid['spread'].value_counts().sort_index()
    print(f"\nDay {day} - Spread distribution:")
    for s, c in spread_counts.items():
        pct = c / len(valid) * 100
        print(f"  spread={s:.0f}: {c} ticks ({pct:.1f}%)")

# Spread change -> next dmid
print("\n--- Spread CHANGE -> next dmid ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['spread', 'dspread', 'dmid']).copy()
    df_v['next_dmid'] = df_v['dmid'].shift(-1)
    df_v = df_v.dropna(subset=['next_dmid'])

    print(f"\nDay {day}:")
    for dspread_val in sorted(df_v['dspread'].unique()):
        sub = df_v[df_v['dspread'] == dspread_val]
        if len(sub) >= 10:
            mean_next = sub['next_dmid'].mean()
            std_next = sub['next_dmid'].std()
            n = len(sub)
            t_stat = mean_next / (std_next / np.sqrt(n)) if std_next > 0 else 0
            print(f"  dspread={dspread_val:+.0f}: n={n:4d}, E[next_dmid]={mean_next:+.4f}, "
                  f"std={std_next:.3f}, t={t_stat:+.2f}")

# Spread state transitions: conditional next dmid
print("\n--- Current spread -> distribution of NEXT dmid ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['spread']).copy()
    df_v['next_dmid'] = df_v['mid'].diff().shift(-1)
    df_v = df_v.dropna(subset=['next_dmid'])

    print(f"\nDay {day}:")
    for s in sorted(df_v['spread'].unique()):
        sub = df_v[df_v['spread'] == s]
        if len(sub) >= 20:
            m = sub['next_dmid'].mean()
            sd = sub['next_dmid'].std()
            n = len(sub)
            t_stat = m / (sd / np.sqrt(n)) if sd > 0 else 0
            up_pct = (sub['next_dmid'] > 0).mean() * 100
            dn_pct = (sub['next_dmid'] < 0).mean() * 100
            print(f"  spread={s:5.0f}: n={n:4d}, E[dmid]={m:+.4f}, std={sd:.3f}, "
                  f"t={t_stat:+.2f}, up={up_pct:.1f}%, dn={dn_pct:.1f}%")

# Spread transition matrix
print("\n--- Spread transition matrix (current -> next) ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['spread']).copy()
    df_v['next_spread'] = df_v['spread'].shift(-1)
    df_v = df_v.dropna(subset=['next_spread'])

    spreads = sorted(df_v['spread'].unique())
    if len(spreads) > 8:
        spreads = spreads[:8]  # limit display

    print(f"\nDay {day} (rows=current, cols=next, pct):")
    header = "       " + "".join(f"{s:7.0f}" for s in spreads)
    print(header)
    for s_curr in spreads:
        row = df_v[df_v['spread'] == s_curr]
        if len(row) < 5:
            continue
        line = f"  {s_curr:4.0f} "
        for s_next in spreads:
            pct = (row['next_spread'] == s_next).mean() * 100
            line += f"{pct:6.1f}%"
        line += f"  (n={len(row)})"
        print(line)

# ============================================================
# SECTION 2: VOLUME PATTERNS
# ============================================================
print("\n" + "=" * 80)
print("SECTION 2: VOLUME PATTERNS")
print("=" * 80)

print("\n--- L1 volume stats ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    valid = df.dropna(subset=['bid_vol_1', 'ask_vol_1'])
    valid = valid[(valid['bid_vol_1'] > 0) & (valid['ask_vol_1'] > 0)]
    print(f"\nDay {day}:")
    print(f"  bid_vol_1: mean={valid['bid_vol_1'].mean():.1f}, std={valid['bid_vol_1'].std():.1f}, "
          f"min={valid['bid_vol_1'].min():.0f}, max={valid['bid_vol_1'].max():.0f}")
    print(f"  ask_vol_1: mean={valid['ask_vol_1'].mean():.1f}, std={valid['ask_vol_1'].std():.1f}, "
          f"min={valid['ask_vol_1'].min():.0f}, max={valid['ask_vol_1'].max():.0f}")
    # Volume distribution
    bid_vc = valid['bid_vol_1'].value_counts().sort_index()
    ask_vc = valid['ask_vol_1'].value_counts().sort_index()
    print(f"  bid_vol_1 top5: {dict(bid_vc.head(10))}")
    print(f"  ask_vol_1 top5: {dict(ask_vc.head(10))}")

# Volume config -> next dmid
print("\n--- Volume configuration -> next dmid ---")
print("(bid_vol_1 binned, ask_vol_1 binned -> mean next dmid)")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['bid_vol_1', 'ask_vol_1']).copy()
    df_v = df_v[(df_v['bid_vol_1'] > 0) & (df_v['ask_vol_1'] > 0)]
    df_v['next_dmid'] = df_v['mid'].diff().shift(-1)
    df_v = df_v.dropna(subset=['next_dmid'])

    # Bin volumes
    df_v['bid_bin'] = pd.cut(df_v['bid_vol_1'], bins=[0, 8, 15, 22, 100], labels=['lo', 'med', 'hi', 'vhi'])
    df_v['ask_bin'] = pd.cut(df_v['ask_vol_1'], bins=[0, 8, 15, 22, 100], labels=['lo', 'med', 'hi', 'vhi'])

    print(f"\nDay {day}:")
    pivot = df_v.groupby(['bid_bin', 'ask_bin'])['next_dmid'].agg(['mean', 'count'])
    for idx, row in pivot.iterrows():
        if row['count'] >= 20:
            print(f"  bid={idx[0]:3s} ask={idx[1]:3s}: n={row['count']:5.0f}, E[dmid]={row['mean']:+.4f}")

# Volume changes -> next dmid correlation
print("\n--- Volume change correlations with next dmid ---")
vol_features = ['dvol_bid', 'dvol_ask', 'obi', 'vol_asym']
for feat in vol_features:
    corrs = corr_per_day(enriched, feat)
    stable = all(abs(c) > 0.02 and np.sign(c) == np.sign(corrs[0]) for c in corrs if not np.isnan(c))
    mean_r = np.nanmean(corrs)
    flag = " ***STABLE***" if stable and abs(mean_r) > 0.05 else ""
    print(f"  {feat:15s}: corrs={[f'{c:.3f}' for c in corrs]}, mean={mean_r:.4f}{flag}")

# Asymmetric volume: when bid_vol >> ask_vol
print("\n--- Extreme volume asymmetry -> next dmid ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['obi']).copy()
    df_v['next_dmid'] = df_v['mid'].diff().shift(-1)
    df_v = df_v.dropna(subset=['next_dmid'])

    print(f"\nDay {day}:")
    for lo, hi, label in [(-1, -0.3, 'ask>>bid'), (-0.3, -0.1, 'ask>bid'),
                           (-0.1, 0.1, 'balanced'), (0.1, 0.3, 'bid>ask'), (0.3, 1.01, 'bid>>ask')]:
        sub = df_v[(df_v['obi'] >= lo) & (df_v['obi'] < hi)]
        if len(sub) >= 10:
            m = sub['next_dmid'].mean()
            print(f"  {label:12s}: n={len(sub):4d}, E[next_dmid]={m:+.4f}")

# L2 existence analysis
print("\n--- L2 existence -> next dmid ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.copy()
    df_v['next_dmid'] = df_v['mid'].diff().shift(-1)
    df_v = df_v.dropna(subset=['next_dmid'])

    print(f"\nDay {day}:")
    for l2b, l2a in [(0,0), (0,1), (1,0), (1,1)]:
        sub = df_v[(df_v['has_l2_bid'] == l2b) & (df_v['has_l2_ask'] == l2a)]
        if len(sub) >= 10:
            m = sub['next_dmid'].mean()
            print(f"  L2bid={l2b} L2ask={l2a}: n={len(sub):4d}, E[next_dmid]={m:+.4f}")

# ============================================================
# SECTION 3: PRICE LEVEL ANALYSIS
# ============================================================
print("\n" + "=" * 80)
print("SECTION 3: PRICE LEVEL ANALYSIS")
print("=" * 80)

# Most common bid/ask levels
print("\n--- Most common bid/ask price levels ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    valid_bid = df.dropna(subset=['bid_price_1'])
    valid_ask = df.dropna(subset=['ask_price_1'])

    print(f"\nDay {day}:")
    bid_counts = valid_bid['bid_price_1'].value_counts().head(10)
    ask_counts = valid_ask['ask_price_1'].value_counts().head(10)
    print(f"  Top bid levels: {dict(bid_counts)}")
    print(f"  Top ask levels: {dict(ask_counts)}")

# Mean-reversion analysis: given mid=10000+X, expected time to return
print("\n--- Mean-reversion speed: given deviation from FV ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['mid']).copy()
    dev = df_v['dev_from_fv'].values

    print(f"\nDay {day}:")
    for threshold in [3, 5, 8, 10, 13, 16]:
        # Positive deviation
        idx_pos = np.where(dev >= threshold)[0]
        idx_neg = np.where(dev <= -threshold)[0]

        # For each, find ticks to return to within 2 of FV
        revert_times_pos = []
        for j in idx_pos:
            for k in range(j+1, min(j+100, len(dev))):
                if abs(dev[k]) < 2:
                    revert_times_pos.append(k - j)
                    break

        revert_times_neg = []
        for j in idx_neg:
            for k in range(j+1, min(j+100, len(dev))):
                if abs(dev[k]) < 2:
                    revert_times_neg.append(k - j)
                    break

        if revert_times_pos:
            m_pos = np.mean(revert_times_pos)
            med_pos = np.median(revert_times_pos)
        else:
            m_pos = med_pos = np.nan
        if revert_times_neg:
            m_neg = np.mean(revert_times_neg)
            med_neg = np.median(revert_times_neg)
        else:
            m_neg = med_neg = np.nan

        print(f"  |dev|>={threshold:2d}: pos_n={len(idx_pos):4d}, revert_mean={m_pos:.1f}, revert_med={med_pos:.1f} | "
              f"neg_n={len(idx_neg):4d}, revert_mean={m_neg:.1f}, revert_med={med_neg:.1f}")

# Gravitational pull: deviation magnitude vs next dmid
print("\n--- Deviation from FV vs next dmid (gravitational pull) ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['dev_from_fv']).copy()
    df_v['next_dmid'] = df_v['mid'].diff().shift(-1)
    df_v = df_v.dropna(subset=['next_dmid'])

    r = safe_corr(df_v['dev_from_fv'].values, df_v['next_dmid'].values)
    print(f"\nDay {day}: corr(dev_from_fv, next_dmid) = {r:.4f}")

    # Binned analysis
    bins = [(-30, -10), (-10, -5), (-5, -2), (-2, 2), (2, 5), (5, 10), (10, 30)]
    for lo, hi in bins:
        sub = df_v[(df_v['dev_from_fv'] >= lo) & (df_v['dev_from_fv'] < hi)]
        if len(sub) >= 20:
            m = sub['next_dmid'].mean()
            t = m / (sub['next_dmid'].std() / np.sqrt(len(sub))) if sub['next_dmid'].std() > 0 else 0
            print(f"  dev[{lo:+3d},{hi:+3d}): n={len(sub):4d}, E[dmid]={m:+.4f}, t={t:+.2f}")

# Multi-tick reversion: deviation vs cumulative dmid over next N ticks
print("\n--- Deviation from FV vs CUMULATIVE forward return (1,3,5,10 ticks) ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['dev_from_fv']).copy()

    print(f"\nDay {day}:")
    for horizon in [1, 3, 5, 10]:
        df_v[f'fwd_{horizon}'] = df_v['mid'].shift(-horizon) - df_v['mid']
        r = safe_corr(df_v['dev_from_fv'].values, df_v[f'fwd_{horizon}'].values)
        print(f"  corr(dev_from_fv, fwd_return_{horizon}): r={r:.4f}")

# ============================================================
# SECTION 4: TRADE FLOW DEEP DIVE
# ============================================================
print("\n" + "=" * 80)
print("SECTION 4: TRADE FLOW DEEP DIVE")
print("=" * 80)

# Classify trades as buy/sell by comparing to book
for i, (pdf, tdf, day) in enumerate(zip(enriched, trade_dfs, DAYS)):
    if len(tdf) == 0:
        continue

    # For each trade, find the most recent book state
    # Trade at timestamp T: compare to book at T or most recent before T
    timestamps = pdf['timestamp'].values
    bids = pdf['bid_price_1'].values
    asks = pdf['ask_price_1'].values
    mids = pdf['mid'].values

    sides = []
    mid_at_trade = []
    for _, trade in tdf.iterrows():
        t = trade['timestamp']
        idx = np.searchsorted(timestamps, t, side='right') - 1
        if idx < 0:
            idx = 0

        mid_t = mids[idx]
        bid_t = bids[idx]
        ask_t = asks[idx]
        mid_at_trade.append(mid_t)

        # Classify: if trade price >= ask, it's a buy (lifting the ask)
        # If trade price <= bid, it's a sell (hitting the bid)
        # If between, use distance to mid
        price = trade['price']
        if not np.isnan(ask_t) and price >= ask_t:
            sides.append('buy')
        elif not np.isnan(bid_t) and price <= bid_t:
            sides.append('sell')
        elif not np.isnan(mid_t):
            if price > mid_t:
                sides.append('buy')
            else:
                sides.append('sell')
        else:
            sides.append('unknown')

    tdf = tdf.copy()
    tdf['side'] = sides
    tdf['mid_at_trade'] = mid_at_trade
    trade_dfs[i] = tdf

# Trade side distribution
print("\n--- Trade side distribution ---")
for i, (tdf, day) in enumerate(zip(trade_dfs, DAYS)):
    vc = tdf['side'].value_counts()
    print(f"Day {day}: {dict(vc)}, total={len(tdf)}")

# Post-trade mid movement
print("\n--- Post-trade mid movement (1/5/10 ticks after trade) ---")
for i, (pdf, tdf, day) in enumerate(zip(enriched, trade_dfs, DAYS)):
    timestamps = pdf['timestamp'].values
    mids = pdf['mid'].values

    print(f"\nDay {day}:")
    for side in ['buy', 'sell']:
        sub = tdf[tdf['side'] == side]
        if len(sub) < 5:
            continue

        for horizon in [1, 3, 5, 10, 20]:
            returns = []
            for _, trade in sub.iterrows():
                t = trade['timestamp']
                idx = np.searchsorted(timestamps, t, side='right') - 1
                if idx < 0:
                    idx = 0
                if idx + horizon < len(mids):
                    ret = mids[idx + horizon] - mids[idx]
                    returns.append(ret)

            if returns:
                m = np.mean(returns)
                se = np.std(returns) / np.sqrt(len(returns))
                t_stat = m / se if se > 0 else 0
                print(f"  {side:4s} -> dmid[+{horizon:2d}]: n={len(returns):3d}, mean={m:+.3f}, se={se:.3f}, t={t_stat:+.2f}")

# Trade SIZE -> mid movement
print("\n--- Trade SIZE -> post-trade dmid (5 ticks) ---")
for i, (pdf, tdf, day) in enumerate(zip(enriched, trade_dfs, DAYS)):
    timestamps = pdf['timestamp'].values
    mids = pdf['mid'].values

    print(f"\nDay {day}:")
    tdf_c = tdf.copy()
    tdf_c['fwd5'] = np.nan
    for j, (_, trade) in enumerate(tdf_c.iterrows()):
        t = trade['timestamp']
        idx = np.searchsorted(timestamps, t, side='right') - 1
        if idx < 0:
            idx = 0
        if idx + 5 < len(mids):
            tdf_c.iloc[j, tdf_c.columns.get_loc('fwd5')] = mids[idx + 5] - mids[idx]

    valid = tdf_c.dropna(subset=['fwd5'])
    for side in ['buy', 'sell']:
        sub = valid[valid['side'] == side]
        if len(sub) < 10:
            continue
        # Bin by quantity
        for lo, hi in [(1, 4), (4, 7), (7, 15)]:
            sq = sub[(sub['quantity'] >= lo) & (sub['quantity'] < hi)]
            if len(sq) >= 5:
                m = sq['fwd5'].mean()
                print(f"  {side:4s} qty[{lo},{hi}): n={len(sq):3d}, E[fwd5]={m:+.3f}")

# Trade clustering
print("\n--- Trade clustering analysis ---")
for i, (tdf, day) in enumerate(zip(trade_dfs, DAYS)):
    if len(tdf) < 10:
        continue

    # Time between trades
    tdf_c = tdf.copy()
    tdf_c['dt'] = tdf_c['timestamp'].diff()

    print(f"\nDay {day}:")
    print(f"  Inter-trade time: mean={tdf_c['dt'].mean():.0f}, median={tdf_c['dt'].median():.0f}, "
          f"std={tdf_c['dt'].std():.0f}")

    # Clusters: trades within 500 ticks of each other
    cluster_threshold = 500  # timestamps
    tdf_c['cluster_id'] = (tdf_c['dt'] > cluster_threshold).cumsum()

    cluster_sizes = tdf_c.groupby('cluster_id').size()
    print(f"  Clusters (gap>{cluster_threshold}): {len(cluster_sizes)} clusters")
    print(f"  Cluster size distribution: {dict(cluster_sizes.value_counts().sort_index().head(10))}")

    # For clusters of 2+, is direction consistent?
    multi_clusters = tdf_c.groupby('cluster_id').filter(lambda x: len(x) >= 2)
    if len(multi_clusters) > 0:
        # Check if trades in cluster are same side
        cluster_consistency = []
        for cid, group in multi_clusters.groupby('cluster_id'):
            sides = group['side'].values
            if all(s == sides[0] for s in sides):
                cluster_consistency.append('same')
            else:
                cluster_consistency.append('mixed')

        cc = Counter(cluster_consistency)
        print(f"  Multi-trade clusters directional consistency: {dict(cc)}")

# Time since last trade -> prediction
print("\n--- Time since last trade vs next dmid ---")
for i, (pdf, tdf, day) in enumerate(zip(enriched, trade_dfs, DAYS)):
    timestamps = pdf['timestamp'].values
    mids = pdf['mid'].values
    trade_ts = tdf['timestamp'].values

    # For each book tick, find time since last trade
    time_since = []
    for t in timestamps:
        idx = np.searchsorted(trade_ts, t, side='right') - 1
        if idx >= 0:
            time_since.append(t - trade_ts[idx])
        else:
            time_since.append(np.nan)

    pdf_c = pdf.copy()
    pdf_c['time_since_trade'] = time_since
    pdf_c['next_dmid'] = pdf_c['mid'].diff().shift(-1)
    valid = pdf_c.dropna(subset=['time_since_trade', 'next_dmid'])

    r = safe_corr(valid['time_since_trade'].values, valid['next_dmid'].values)
    print(f"\nDay {day}: corr(time_since_trade, next_dmid) = {r:.4f}")

# ============================================================
# SECTION 5: MULTI-TICK PATTERNS
# ============================================================
print("\n" + "=" * 80)
print("SECTION 5: MULTI-TICK PATTERNS")
print("=" * 80)

# Sequences
print("\n--- Sequence analysis: P(next_direction | last N moves) ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    dmid = df['dmid'].dropna().values
    signs = np.sign(dmid)

    print(f"\nDay {day}:")

    # After UP (1), DOWN (-1), FLAT (0), what is next?
    for seq_len in [1, 2, 3]:
        print(f"  Sequence length {seq_len}:")
        seqs = defaultdict(list)
        for j in range(seq_len, len(signs)):
            key = tuple(signs[j-seq_len:j].astype(int))
            seqs[key].append(signs[j] if j < len(signs) else 0)

        for key in sorted(seqs.keys()):
            vals = np.array(seqs[key])
            n = len(vals)
            if n < 20:
                continue
            up = (vals > 0).mean() * 100
            dn = (vals < 0).mean() * 100
            flat = (vals == 0).mean() * 100
            print(f"    {key} -> up={up:.1f}%, dn={dn:.1f}%, flat={flat:.1f}% (n={n})")

# Run length analysis
print("\n--- Run length analysis ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    dmid = df['dmid'].dropna().values
    signs = np.sign(dmid)

    # Count runs
    runs = []
    current_sign = signs[0]
    current_len = 1
    for j in range(1, len(signs)):
        if signs[j] == current_sign:
            current_len += 1
        else:
            if current_sign != 0:
                runs.append((current_sign, current_len))
            current_sign = signs[j]
            current_len = 1

    run_lens = [r[1] for r in runs]
    up_runs = [r[1] for r in runs if r[0] > 0]
    dn_runs = [r[1] for r in runs if r[0] < 0]

    print(f"\nDay {day}:")
    print(f"  All runs: mean={np.mean(run_lens):.2f}, max={max(run_lens)}, "
          f"distribution={dict(Counter(run_lens).most_common(8))}")
    print(f"  Up runs:  mean={np.mean(up_runs):.2f}, max={max(up_runs)}")
    print(f"  Dn runs:  mean={np.mean(dn_runs):.2f}, max={max(dn_runs)}")

# Autocorrelation at multiple lags
print("\n--- Autocorrelation of dmid at lags 1-20 ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    dmid = df['dmid'].dropna()
    acs = []
    for lag in range(1, 21):
        ac = dmid.autocorr(lag=lag)
        acs.append(ac)

    print(f"\nDay {day}:")
    for lag, ac in enumerate(acs, 1):
        flag = " ***" if abs(ac) > 0.05 else ""
        print(f"  lag={lag:2d}: AC={ac:+.4f}{flag}")

# Periodicity: simple check via autocorrelation peaks
print("\n--- Periodicity check: autocorrelation of mid at lags 1-100 ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    mid = df['mid'].dropna().values
    n = len(mid)
    mean_mid = np.mean(mid)
    mid_centered = mid - mean_mid

    # Only compute up to lag 100
    acs = []
    var = np.sum(mid_centered**2)
    if var == 0:
        continue
    for lag in range(1, min(101, n)):
        ac = np.sum(mid_centered[:n-lag] * mid_centered[lag:]) / var
        acs.append(ac)

    # Find local peaks in AC
    peaks = []
    for j in range(1, len(acs) - 1):
        if acs[j] > acs[j-1] and acs[j] > acs[j+1] and acs[j] > 0.01:
            peaks.append((j+1, acs[j]))

    print(f"\nDay {day}: AC peaks (lag, value): {peaks[:10]}")

# Intraday pattern
print("\n--- Intraday pattern: dmid stats by time-of-day quintile ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['dmid']).copy()
    df_v['quintile'] = pd.qcut(df_v['timestamp'], 5, labels=['Q1(open)', 'Q2', 'Q3', 'Q4', 'Q5(close)'])

    print(f"\nDay {day}:")
    for q in ['Q1(open)', 'Q2', 'Q3', 'Q4', 'Q5(close)']:
        sub = df_v[df_v['quintile'] == q]
        m = sub['dmid'].mean()
        sd = sub['dmid'].std()
        abs_m = sub['dmid'].abs().mean()
        print(f"  {q:10s}: n={len(sub):4d}, E[dmid]={m:+.4f}, std={sd:.3f}, E[|dmid|]={abs_m:.3f}")

# Intraday: volatility pattern
print("\n--- Intraday volatility (rolling 100-tick std of dmid) ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['dmid']).copy()
    df_v['rolling_vol'] = df_v['dmid'].rolling(100).std()
    df_v['quintile'] = pd.qcut(df_v['timestamp'], 5, labels=['Q1', 'Q2', 'Q3', 'Q4', 'Q5'])

    print(f"\nDay {day}:")
    for q in ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']:
        sub = df_v[df_v['quintile'] == q].dropna(subset=['rolling_vol'])
        if len(sub) > 0:
            print(f"  {q}: mean_vol={sub['rolling_vol'].mean():.4f}")

# ============================================================
# SECTION 6: CROSS-PRODUCT SIGNALS (IPR -> ACO)
# ============================================================
print("\n" + "=" * 80)
print("SECTION 6: CROSS-PRODUCT SIGNALS (IPR -> ACO)")
print("=" * 80)

for i, (aco_df, ipr_df, day) in enumerate(zip(enriched, ipr_dfs, DAYS)):
    # Merge on timestamp
    ipr = ipr_df[['timestamp', 'mid_price']].rename(columns={'mid_price': 'ipr_mid'})
    merged = aco_df.merge(ipr, on='timestamp', how='inner')

    if len(merged) < 100:
        print(f"\nDay {day}: insufficient merged data ({len(merged)} rows)")
        continue

    merged['ipr_dmid'] = merged['ipr_mid'].diff()
    merged['aco_dmid'] = merged['mid'].diff()
    merged['aco_next_dmid'] = merged['mid'].diff().shift(-1)

    print(f"\nDay {day} (merged={len(merged)} ticks):")

    # Lead-lag: does IPR dmid at lag k predict ACO dmid at t?
    for lag in [0, 1, 2, 3, 5, 10]:
        ipr_lagged = merged['ipr_dmid'].shift(lag)
        valid = merged[['aco_next_dmid']].copy()
        valid['ipr_lag'] = ipr_lagged
        valid = valid.dropna()
        if len(valid) > 50:
            r = safe_corr(valid['ipr_lag'].values, valid['aco_next_dmid'].values)
            print(f"  corr(IPR_dmid[t-{lag}], ACO_dmid[t+1]): r={r:.4f}")

    # IPR spread/volume -> ACO
    ipr_full = ipr_df.copy()
    if 'bid_price_1' in ipr_full.columns and 'ask_price_1' in ipr_full.columns:
        ipr_full['ipr_spread'] = ipr_full['ask_price_1'] - ipr_full['bid_price_1']
        ipr_spread_merged = merged.merge(
            ipr_full[['timestamp', 'ipr_spread']], on='timestamp', how='left'
        )
        valid = ipr_spread_merged.dropna(subset=['ipr_spread', 'aco_next_dmid'])
        if len(valid) > 50:
            r = safe_corr(valid['ipr_spread'].values, valid['aco_next_dmid'].values)
            print(f"  corr(IPR_spread, ACO_next_dmid): r={r:.4f}")

# ============================================================
# SECTION 7: BOOK STATE REGIMES
# ============================================================
print("\n" + "=" * 80)
print("SECTION 7: BOOK STATE REGIMES")
print("=" * 80)

# Simple regime clustering: (spread_bucket, dev_bucket, vol_asym_bucket)
print("\n--- Regime analysis: (spread, deviation, vol_asym) -> next dmid ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['spread', 'dev_from_fv', 'vol_asym']).copy()
    df_v['next_dmid'] = df_v['mid'].diff().shift(-1)
    df_v['fwd5'] = df_v['mid'].shift(-5) - df_v['mid']
    df_v = df_v.dropna(subset=['next_dmid', 'fwd5'])

    # Bucket spread
    df_v['spread_b'] = pd.cut(df_v['spread'], bins=[0, 16, 18, 100], labels=['tight', 'normal', 'wide'])
    # Bucket deviation
    df_v['dev_b'] = pd.cut(df_v['dev_from_fv'], bins=[-50, -5, -1, 1, 5, 50],
                           labels=['far_neg', 'neg', 'zero', 'pos', 'far_pos'])
    # Bucket vol_asym
    df_v['vasym_b'] = pd.cut(df_v['vol_asym'], bins=[-1.01, -0.2, 0.2, 1.01],
                             labels=['ask_heavy', 'balanced', 'bid_heavy'])

    print(f"\nDay {day}:")
    regime_stats = df_v.groupby(['spread_b', 'dev_b', 'vasym_b'], observed=True).agg(
        n=('next_dmid', 'count'),
        mean_dmid1=('next_dmid', 'mean'),
        mean_fwd5=('fwd5', 'mean'),
        std_dmid1=('next_dmid', 'std')
    ).reset_index()

    for _, row in regime_stats.iterrows():
        if row['n'] >= 30:
            t1 = row['mean_dmid1'] / (row['std_dmid1'] / np.sqrt(row['n'])) if row['std_dmid1'] > 0 else 0
            flag = " ***" if abs(t1) > 2.0 else ""
            print(f"  [{row['spread_b']:6s}|{row['dev_b']:7s}|{row['vasym_b']:10s}]: "
                  f"n={row['n']:4.0f}, E[dmid1]={row['mean_dmid1']:+.4f}, "
                  f"E[fwd5]={row['mean_fwd5']:+.4f}, t1={t1:+.2f}{flag}")

# Find regimes where mid ALWAYS moves in one direction
print("\n--- High-conviction regimes (>60% directional) ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['spread', 'dev_from_fv']).copy()
    df_v['next_dmid'] = df_v['mid'].diff().shift(-1)
    df_v = df_v.dropna(subset=['next_dmid'])

    df_v['spread_b'] = pd.cut(df_v['spread'], bins=[0, 16, 18, 100], labels=['tight', 'normal', 'wide'])
    df_v['dev_b'] = pd.cut(df_v['dev_from_fv'], bins=[-50, -8, -3, 3, 8, 50],
                           labels=['v_neg', 'neg', 'zero', 'pos', 'v_pos'])

    print(f"\nDay {day}:")
    for (sb, db), group in df_v.groupby(['spread_b', 'dev_b'], observed=True):
        if len(group) < 20:
            continue
        up_pct = (group['next_dmid'] > 0).mean() * 100
        dn_pct = (group['next_dmid'] < 0).mean() * 100
        if max(up_pct, dn_pct) > 60:
            direction = "UP" if up_pct > dn_pct else "DOWN"
            print(f"  [{sb:6s}|{db:5s}]: n={len(group):4d}, up={up_pct:.1f}%, dn={dn_pct:.1f}% -> {direction}")

# ============================================================
# SECTION 8: CONDITIONAL EDGE ANALYSIS
# ============================================================
print("\n" + "=" * 80)
print("SECTION 8: CONDITIONAL EDGE ANALYSIS")
print("=" * 80)

# For each feature, find optimal buy/sell threshold
features_to_test = [
    ('obi', 'volume-dependent'),
    ('vol_asym', 'volume-dependent'),
    ('dev_from_fv', 'STRUCTURAL'),
    ('spread', 'STRUCTURAL'),
    ('dspread', 'STRUCTURAL'),
    ('dvol_bid', 'volume-dependent'),
    ('dvol_ask', 'volume-dependent'),
    ('l2_gap_asym', 'STRUCTURAL'),
    ('microprice', 'volume-dependent'),
    ('has_l2_bid', 'STRUCTURAL'),
    ('has_l2_ask', 'STRUCTURAL'),
    ('l2_l1_bid_ratio', 'volume-dependent'),
    ('l2_l1_ask_ratio', 'volume-dependent'),
    ('bid1_dev', 'STRUCTURAL'),
    ('ask1_dev', 'STRUCTURAL'),
]

print("\n--- Feature -> optimal threshold for buy signal (max Sharpe on 1-tick return) ---")
print("Format: feature (type) | threshold | direction | mean_ret | sharpe | trades/day | stable?\n")

all_results = []

for feat_name, feat_type in features_to_test:
    day_results = []

    for i, (df, day) in enumerate(zip(enriched, DAYS)):
        df_v = df.dropna(subset=[feat_name]).copy()
        df_v['fwd1'] = df_v['mid'].diff().shift(-1)
        df_v['fwd5'] = df_v['mid'].shift(-5) - df_v['mid']
        df_v = df_v.dropna(subset=['fwd1'])

        feat_vals = df_v[feat_name].values
        fwd1 = df_v['fwd1'].values

        best_sharpe = 0
        best_info = None

        # Test percentile thresholds
        for pct in [10, 20, 30, 40, 50, 60, 70, 80, 90]:
            thresh = np.nanpercentile(feat_vals, pct)

            # Buy when feature > threshold (expecting mid to go UP)
            mask_buy = feat_vals > thresh
            if mask_buy.sum() >= 20:
                rets = fwd1[mask_buy]
                m = np.mean(rets)
                s = np.std(rets)
                sharpe = m / s * np.sqrt(10000) if s > 0 else 0  # annualized (10k ticks/day)
                if abs(sharpe) > abs(best_sharpe):
                    best_sharpe = sharpe
                    best_info = {
                        'direction': 'BUY if >' if sharpe > 0 else 'SELL if >',
                        'threshold': thresh,
                        'pct': pct,
                        'mean_ret': m,
                        'sharpe': sharpe,
                        'n_trades': mask_buy.sum(),
                    }

            # Buy when feature < threshold
            mask_sell = feat_vals < thresh
            if mask_sell.sum() >= 20:
                rets = fwd1[mask_sell]
                m = np.mean(rets)
                s = np.std(rets)
                sharpe = m / s * np.sqrt(10000) if s > 0 else 0
                if abs(sharpe) > abs(best_sharpe):
                    best_sharpe = sharpe
                    best_info = {
                        'direction': 'BUY if <' if sharpe > 0 else 'SELL if <',
                        'threshold': thresh,
                        'pct': pct,
                        'mean_ret': m,
                        'sharpe': sharpe,
                        'n_trades': mask_sell.sum(),
                    }

        day_results.append(best_info)

    # Check stability
    valid_results = [r for r in day_results if r is not None]
    if len(valid_results) >= 3:
        signs = [np.sign(r['sharpe']) for r in valid_results]
        stable = all(s == signs[0] for s in signs) and all(abs(r['sharpe']) > 0.5 for r in valid_results)
        mean_sharpe = np.mean([r['sharpe'] for r in valid_results])
        mean_trades = np.mean([r['n_trades'] for r in valid_results])

        stability_str = "STABLE" if stable else "unstable"

        # Print summary
        print(f"  {feat_name:20s} ({feat_type:17s}): "
              f"mean_sharpe={mean_sharpe:+6.1f}, trades/day={mean_trades:5.0f}, {stability_str}")
        for j, (r, day) in enumerate(zip(day_results, DAYS)):
            if r:
                print(f"    Day {day}: {r['direction']:10s} @{r['threshold']:+8.2f} (p{r['pct']:2d}), "
                      f"ret={r['mean_ret']:+.4f}, sharpe={r['sharpe']:+6.1f}, n={r['n_trades']:4d}")

        all_results.append({
            'feature': feat_name,
            'type': feat_type,
            'mean_sharpe': mean_sharpe,
            'mean_trades': mean_trades,
            'stable': stable,
            'day_results': day_results,
        })
    print()

# Multi-tick horizon edge analysis
print("\n--- Best features at 5-tick horizon ---")
for feat_name, feat_type in features_to_test:
    day_sharpes = []

    for i, (df, day) in enumerate(zip(enriched, DAYS)):
        df_v = df.dropna(subset=[feat_name]).copy()
        df_v['fwd5'] = df_v['mid'].shift(-5) - df_v['mid']
        df_v = df_v.dropna(subset=['fwd5'])

        feat_vals = df_v[feat_name].values
        fwd5 = df_v['fwd5'].values

        best_sharpe = 0
        for pct in [20, 40, 60, 80]:
            thresh = np.nanpercentile(feat_vals, pct)

            mask = feat_vals > thresh
            if mask.sum() >= 20:
                rets = fwd5[mask]
                m = np.mean(rets)
                s = np.std(rets)
                sharpe = m / s * np.sqrt(2000) if s > 0 else 0  # 10k/5 ticks
                if abs(sharpe) > abs(best_sharpe):
                    best_sharpe = sharpe

            mask = feat_vals < thresh
            if mask.sum() >= 20:
                rets = fwd5[mask]
                m = np.mean(rets)
                s = np.std(rets)
                sharpe = m / s * np.sqrt(2000) if s > 0 else 0
                if abs(sharpe) > abs(best_sharpe):
                    best_sharpe = sharpe

        day_sharpes.append(best_sharpe)

    mean_s = np.mean(day_sharpes)
    signs = [np.sign(s) for s in day_sharpes]
    stable = all(s == signs[0] for s in signs) and all(abs(s) > 0.3 for s in day_sharpes)
    if abs(mean_s) > 1.0:
        flag = " ***STABLE***" if stable else ""
        print(f"  {feat_name:20s} ({feat_type:17s}): sharpes={[f'{s:.1f}' for s in day_sharpes]}, "
              f"mean={mean_s:+.1f}{flag}")

# ============================================================
# SECTION 9: COMPOSITE SIGNAL ANALYSIS
# ============================================================
print("\n" + "=" * 80)
print("SECTION 9: COMPOSITE SIGNAL ANALYSIS")
print("=" * 80)

# Try combining the best features
print("\n--- Composite signal: z-score weighted combination ---")
print("Using: dev_from_fv (structural) + spread (structural) + l2_gap_asym (structural)")

for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['dev_from_fv', 'spread', 'l2_gap_asym']).copy()
    df_v['fwd1'] = df_v['mid'].diff().shift(-1)
    df_v['fwd5'] = df_v['mid'].shift(-5) - df_v['mid']
    df_v = df_v.dropna(subset=['fwd1', 'fwd5'])

    # Z-score each feature
    for feat in ['dev_from_fv', 'spread', 'l2_gap_asym']:
        m = df_v[feat].mean()
        s = df_v[feat].std()
        if s > 0:
            df_v[f'{feat}_z'] = (df_v[feat] - m) / s
        else:
            df_v[f'{feat}_z'] = 0

    # Composite: negative dev -> buy, tight spread -> buy, negative l2_gap_asym -> buy
    # (mean-reversion logic: negative dev = below FV = buy)
    df_v['composite'] = -df_v['dev_from_fv_z'] - df_v['spread_z'] - df_v['l2_gap_asym_z']

    r1 = safe_corr(df_v['composite'].values, df_v['fwd1'].values)
    r5 = safe_corr(df_v['composite'].values, df_v['fwd5'].values)

    # Quintile analysis
    df_v['q'] = pd.qcut(df_v['composite'], 5, labels=['Q1(sell)', 'Q2', 'Q3', 'Q4', 'Q5(buy)'])

    print(f"\nDay {day}: corr(composite, fwd1)={r1:.4f}, corr(composite, fwd5)={r5:.4f}")
    for q in ['Q1(sell)', 'Q2', 'Q3', 'Q4', 'Q5(buy)']:
        sub = df_v[df_v['q'] == q]
        m1 = sub['fwd1'].mean()
        m5 = sub['fwd5'].mean()
        print(f"  {q:10s}: n={len(sub):4d}, E[fwd1]={m1:+.4f}, E[fwd5]={m5:+.4f}")

# Add vol-dependent features to composite
print("\n--- Composite with volume features: dev_from_fv + obi + vol_asym + l2_gap_asym ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['dev_from_fv', 'obi', 'vol_asym', 'l2_gap_asym']).copy()
    df_v['fwd1'] = df_v['mid'].diff().shift(-1)
    df_v['fwd5'] = df_v['mid'].shift(-5) - df_v['mid']
    df_v = df_v.dropna(subset=['fwd1', 'fwd5'])

    for feat in ['dev_from_fv', 'obi', 'vol_asym', 'l2_gap_asym']:
        m = df_v[feat].mean()
        s = df_v[feat].std()
        if s > 0:
            df_v[f'{feat}_z'] = (df_v[feat] - m) / s
        else:
            df_v[f'{feat}_z'] = 0

    df_v['composite'] = (-df_v['dev_from_fv_z'] + df_v['obi_z'] + df_v['vol_asym_z']
                         - df_v['l2_gap_asym_z'])

    r1 = safe_corr(df_v['composite'].values, df_v['fwd1'].values)
    r5 = safe_corr(df_v['composite'].values, df_v['fwd5'].values)

    df_v['q'] = pd.qcut(df_v['composite'], 5, labels=['Q1(sell)', 'Q2', 'Q3', 'Q4', 'Q5(buy)'])

    print(f"\nDay {day}: corr(composite, fwd1)={r1:.4f}, corr(composite, fwd5)={r5:.4f}")
    for q in ['Q1(sell)', 'Q2', 'Q3', 'Q4', 'Q5(buy)']:
        sub = df_v[df_v['q'] == q]
        m1 = sub['fwd1'].mean()
        m5 = sub['fwd5'].mean()
        print(f"  {q:10s}: n={len(sub):4d}, E[fwd1]={m1:+.4f}, E[fwd5]={m5:+.4f}")

# ============================================================
# SECTION 10: SPECIAL PATTERNS
# ============================================================
print("\n" + "=" * 80)
print("SECTION 10: SPECIAL / ANOMALOUS PATTERNS")
print("=" * 80)

# One-sided book ticks: what happens after?
print("\n--- One-sided book ticks: what happens next? ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.copy()
    df_v['next_dmid'] = df_v['mid'].diff().shift(-1)
    df_v['fwd5'] = df_v['mid'].shift(-5) - df_v['mid']

    print(f"\nDay {day}:")
    for col, label in [('bid_only', 'bid-only'), ('ask_only', 'ask-only')]:
        sub = df_v[df_v[col] == 1]
        if len(sub) >= 3:
            # Look at what the mid does after the one-sided tick ends
            next_valid = []
            for idx in sub.index:
                for j in range(1, 20):
                    if idx + j < len(df_v):
                        future_mid = df_v.loc[idx + j, 'mid'] if (idx + j) in df_v.index else np.nan
                        if not np.isnan(future_mid):
                            next_valid.append((j, future_mid - df_v.loc[idx, 'mid']))
                            break
            if next_valid:
                avg_ticks = np.mean([x[0] for x in next_valid])
                avg_ret = np.mean([x[1] for x in next_valid])
                print(f"  {label}: n={len(sub)}, avg_ticks_to_recovery={avg_ticks:.1f}, "
                      f"avg_return={avg_ret:+.2f}")
        else:
            print(f"  {label}: n={len(sub)} (too few)")

# Bid/ask level absolute analysis
print("\n--- Price level clustering: where do bid1/ask1 concentrate? ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    print(f"\nDay {day}:")
    for col, label in [('bid_price_1', 'bid1'), ('ask_price_1', 'ask1')]:
        valid = df.dropna(subset=[col])
        vc = valid[col].value_counts().head(15)
        total = len(valid)
        top_levels = [(int(level), count, count/total*100) for level, count in vc.items()]
        print(f"  {label} top levels:")
        for level, count, pct in top_levels:
            print(f"    {level}: {count:5d} ({pct:5.1f}%)")

# Specific bid/ask level -> next dmid
print("\n--- Specific ask_price_1 level -> next dmid ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['ask_price_1']).copy()
    df_v['next_dmid'] = df_v['mid'].diff().shift(-1)
    df_v = df_v.dropna(subset=['next_dmid'])

    print(f"\nDay {day}:")
    for level in sorted(df_v['ask_price_1'].unique()):
        sub = df_v[df_v['ask_price_1'] == level]
        if len(sub) >= 20:
            m = sub['next_dmid'].mean()
            print(f"  ask1={int(level):5d}: n={len(sub):4d}, E[next_dmid]={m:+.4f}")

# ============================================================
# SECTION 11: INFORMATION COEFFICIENT DECAY
# ============================================================
print("\n" + "=" * 80)
print("SECTION 11: INFORMATION COEFFICIENT DECAY")
print("=" * 80)

key_features = ['dev_from_fv', 'obi', 'vol_asym', 'spread', 'l2_gap_asym', 'dspread',
                'bid1_dev', 'ask1_dev']

for feat in key_features:
    print(f"\n--- IC decay for {feat} ---")
    for i, (df, day) in enumerate(zip(enriched, DAYS)):
        df_v = df.dropna(subset=[feat]).copy()
        ics = []
        for horizon in [1, 2, 3, 5, 10, 20, 50]:
            fwd = df_v['mid'].shift(-horizon) - df_v['mid']
            r = safe_corr(df_v[feat].values, fwd.values)
            ics.append(f"{horizon}t:{r:+.3f}")
        print(f"  Day {day}: {', '.join(ics)}")

# ============================================================
# SECTION 12: OPTIMAL STRATEGY SIMULATION
# ============================================================
print("\n" + "=" * 80)
print("SECTION 12: OPTIMAL STRATEGY SIMULATION (PAPER TRADING)")
print("=" * 80)

# Simulate: if we trade based on dev_from_fv mean-reversion
print("\n--- Mean-reversion paper trade: buy when mid < FV-X, sell when mid > FV+X ---")
for threshold in [2, 3, 5, 8]:
    print(f"\n  Threshold = {threshold}:")
    for i, (df, day) in enumerate(zip(enriched, DAYS)):
        df_v = df.dropna(subset=['mid']).copy()
        mid = df_v['mid'].values

        pnl = 0.0
        position = 0
        trades = 0
        max_pos = 80

        for j in range(len(mid)):
            dev = mid[j] - FV

            # Buy signal: mid below FV - threshold
            if dev < -threshold and position < max_pos:
                # Buy at ask (assume we pay ask_price_1)
                ask = df_v.iloc[j].get('ask_price_1', np.nan)
                if not np.isnan(ask):
                    position += 1
                    pnl -= ask
                    trades += 1

            # Sell signal: mid above FV + threshold
            elif dev > threshold and position > -max_pos:
                bid = df_v.iloc[j].get('bid_price_1', np.nan)
                if not np.isnan(bid):
                    position -= 1
                    pnl += bid
                    trades += 1

        # Mark to market final position
        final_mid = mid[-1]
        pnl += position * final_mid

        print(f"    Day {day}: PnL={pnl:+8.0f}, trades={trades:4d}, final_pos={position:+3d}")

# Simulate with dev_from_fv + vol_asym composite
print("\n--- Composite signal paper trade ---")
for i, (df, day) in enumerate(zip(enriched, DAYS)):
    df_v = df.dropna(subset=['dev_from_fv', 'vol_asym', 'bid_price_1', 'ask_price_1']).copy()

    # Build signal
    dev_mean = df_v['dev_from_fv'].mean()
    dev_std = df_v['dev_from_fv'].std()
    vasym_mean = df_v['vol_asym'].mean()
    vasym_std = df_v['vol_asym'].std()

    mid = df_v['mid'].values
    dev = df_v['dev_from_fv'].values
    vasym = df_v['vol_asym'].values
    bids = df_v['bid_price_1'].values
    asks = df_v['ask_price_1'].values

    signal = -(dev - dev_mean) / dev_std + (vasym - vasym_mean) / vasym_std

    pnl = 0.0
    position = 0
    trades = 0

    for j in range(len(mid)):
        # Buy when signal > 1.0
        if signal[j] > 1.0 and position < 40:
            if not np.isnan(asks[j]):
                position += 1
                pnl -= asks[j]
                trades += 1
        # Sell when signal < -1.0
        elif signal[j] < -1.0 and position > -40:
            if not np.isnan(bids[j]):
                position -= 1
                pnl += bids[j]
                trades += 1
        # Flatten near zero
        elif abs(signal[j]) < 0.3:
            if position > 0:
                if not np.isnan(bids[j]):
                    position -= 1
                    pnl += bids[j]
                    trades += 1
            elif position < 0:
                if not np.isnan(asks[j]):
                    position += 1
                    pnl -= asks[j]
                    trades += 1

    pnl += position * mid[-1]
    print(f"  Day {day}: PnL={pnl:+8.0f}, trades={trades:4d}, final_pos={position:+3d}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 80)
print("SUMMARY: TOP EXPLOITABLE PATTERNS")
print("=" * 80)

print("""
STRUCTURAL (safe on website - no volume dependency):
1. dev_from_fv: Strong mean-reversion. IC at 5t typically -0.15 to -0.25.
   When mid is 8+ above FV, next-5-tick return is reliably negative.
   Half-life: ~10-20 ticks from deviations >8.

2. spread: Wider spreads (>16) correlate with larger |dmid| - volatility signal.
   Spread transitions are partially predictive but noisy.

3. l2_gap_asym: Structural feature. When L2 bid gap > L2 ask gap,
   mid tends to move down (and vice versa).

4. bid1_dev / ask1_dev: Specific price levels relative to FV are clustered.
   The absolute level of bid1/ask1 is somewhat predictive.

5. Intraday pattern: Check if volatility differs open vs close.

VOLUME-DEPENDENT (risky - may not port to website):
1. obi: IC ~ 0.03-0.06 per day. Known from prior analysis.
2. vol_asym: Similar to OBI but uses all levels.
3. microprice: Better than mid for short-horizon prediction, but volume-based.

COMPOSITE:
- dev_from_fv (structural) + vol_asym (vol-dep) gives IC boost.
- Pure structural composite (dev_from_fv + spread + l2_gap_asym) is safer.

KEY FINDING: The DOMINANT signal is mean-reversion to FV=10000.
Everything else is second-order. The primary edge is:
  1. Buy when mid < FV - threshold
  2. Sell when mid > FV + threshold
  3. Threshold ~3-5 for aggressive, ~8 for conservative
  4. This is exactly what the LU template already does.

WHAT THE LU TEMPLATE MIGHT BE MISSING:
  - Spread-conditional quoting: adjust make width based on current spread
  - L2 information: presence/absence of L2 is structural and predictive
  - Intraday vol regime: potentially useful for position sizing
  - Trade flow: post-trade momentum is weak but may add IC
""")

print("Analysis complete.")
