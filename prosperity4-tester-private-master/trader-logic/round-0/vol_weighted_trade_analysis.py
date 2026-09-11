#!/usr/bin/env python3
"""
Volume-Weighted Trade Analysis for IMC Prosperity 4
=====================================================
Comprehensive analysis of L1/L2 order book volume patterns and trades.
Analyzes correlation with future price movements (dmid).

20+ analyses covering:
- Volume-weighted mid prices (VWMP)
- Volume-weighted price levels (VWAP)
- Volume ratios and concentration
- Trade volume analysis
- Volume changes (deltas)
- Volume-price interactions
- Cross-level volume flow
- Volume-weighted returns
- Volume at price extremes
- Trade-to-book ratios
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple
import warnings
warnings.filterwarnings('ignore')

# Data paths
DATA_DIR = Path("/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0")

def load_prices(day: int) -> pd.DataFrame:
    """Load prices CSV for a given day."""
    path = DATA_DIR / f"prices_round_0_day_{day}.csv"
    df = pd.read_csv(path, sep=';')
    return df

def load_trades(day: int) -> pd.DataFrame:
    """Load trades CSV for a given day."""
    path = DATA_DIR / f"trades_round_0_day_{day}.csv"
    df = pd.read_csv(path, sep=';')
    return df

def prepare_tomatoes_data(day: int) -> pd.DataFrame:
    """Filter and prepare TOMATOES data with computed columns."""
    prices = load_prices(day)
    trades = load_trades(day)

    # Filter TOMATOES
    tom = prices[prices['product'] == 'TOMATOES'].copy()
    tom = tom.sort_values('timestamp').reset_index(drop=True)

    # Rename for clarity
    tom.rename(columns={
        'bid_price_1': 'bid1', 'bid_volume_1': 'bid1_vol',
        'bid_price_2': 'bid2', 'bid_volume_2': 'bid2_vol',
        'bid_price_3': 'bid3', 'bid_volume_3': 'bid3_vol',
        'ask_price_1': 'ask1', 'ask_volume_1': 'ask1_vol',
        'ask_price_2': 'ask2', 'ask_volume_2': 'ask2_vol',
        'ask_price_3': 'ask3', 'ask_volume_3': 'ask3_vol',
    }, inplace=True)

    # Fill NaN volumes with 0
    vol_cols = ['bid1_vol', 'bid2_vol', 'bid3_vol', 'ask1_vol', 'ask2_vol', 'ask3_vol']
    tom[vol_cols] = tom[vol_cols].fillna(0)

    # Simple mid
    tom['mid'] = tom['mid_price']

    # Next tick mid change (target)
    tom['dmid'] = tom['mid'].shift(-1) - tom['mid']

    # Spread
    tom['spread'] = tom['ask1'] - tom['bid1']

    # Total volumes
    tom['total_bid_vol'] = tom['bid1_vol'] + tom['bid2_vol'] + tom['bid3_vol']
    tom['total_ask_vol'] = tom['ask1_vol'] + tom['ask2_vol'] + tom['ask3_vol']
    tom['total_vol'] = tom['total_bid_vol'] + tom['total_ask_vol']

    # Trade data - merge
    tom_trades = trades[trades['symbol'] == 'TOMATOES'].copy()
    tom_trades['trade_dir'] = np.where(tom_trades['price'] >= tom_trades['price'].shift(0), 1, -1)
    # Determine direction based on price vs mid (will need to merge)

    # Merge trades with book data
    if len(tom_trades) > 0:
        tom_trades = tom_trades.sort_values('timestamp')
        # For each price row, sum trade volume since last tick
        tom['trade_buy_vol'] = 0.0
        tom['trade_sell_vol'] = 0.0
        tom['trade_count'] = 0

        for idx, row in tom.iterrows():
            ts = row['timestamp']
            prev_ts = tom.iloc[idx-1]['timestamp'] if idx > 0 else -100

            # Trades in this interval
            interval_trades = tom_trades[(tom_trades['timestamp'] > prev_ts) &
                                          (tom_trades['timestamp'] <= ts)]

            if len(interval_trades) > 0:
                mid = row['mid']
                for _, trade in interval_trades.iterrows():
                    if trade['price'] >= mid:  # Buy (at or above mid)
                        tom.loc[idx, 'trade_buy_vol'] += trade['quantity']
                    else:  # Sell (below mid)
                        tom.loc[idx, 'trade_sell_vol'] += trade['quantity']
                    tom.loc[idx, 'trade_count'] += 1
    else:
        tom['trade_buy_vol'] = 0.0
        tom['trade_sell_vol'] = 0.0
        tom['trade_count'] = 0

    return tom

def analyze_signal(df: pd.DataFrame, signal_col, target_col: str = 'dmid',
                   signal_name: str = "", vol_dependent: bool = False) -> Dict:
    """
    Analyze a signal's predictive power for target.
    Returns correlation, directional accuracy, and frequency stats.
    signal_col can be a column name (str) or a Series directly.
    """
    # Handle both column name and Series
    if isinstance(signal_col, str):
        signal_series = df[signal_col]
    else:
        signal_series = signal_col

    target_series = df[target_col]

    # Remove NaN
    mask = signal_series.notna() & target_series.notna()
    signal = signal_series.loc[mask].values
    target = target_series.loc[mask].values

    n = len(signal)
    if n < 10:
        return {'r': np.nan, 'accuracy': np.nan, 'freq': 0, 'n': n, 'vol_dependent': vol_dependent}

    # Correlation
    r = np.corrcoef(signal, target)[0, 1] if np.std(signal) > 0 else 0

    # Directional accuracy (when signal != 0)
    signal_sign = np.sign(signal)
    target_sign = np.sign(target)

    nonzero_mask = signal_sign != 0
    if np.sum(nonzero_mask) > 0:
        accuracy = np.mean(signal_sign[nonzero_mask] == target_sign[nonzero_mask])
        freq = np.sum(nonzero_mask) / n
    else:
        accuracy = 0.5
        freq = 0

    return {
        'r': r,
        'accuracy': accuracy,
        'freq': freq,
        'n': n,
        'vol_dependent': vol_dependent
    }

def analyze_threshold_signal(df: pd.DataFrame, signal_col: str, threshold: float,
                              direction: int, target_col: str = 'dmid',
                              signal_name: str = "", vol_dependent: bool = False) -> Dict:
    """
    Analyze signal when it exceeds a threshold.
    direction: 1 = signal > threshold predicts UP, -1 = predicts DOWN
    """
    mask = df[signal_col].notna() & df[target_col].notna()
    signal = df.loc[mask, signal_col].values
    target = df.loc[mask, target_col].values

    # When signal fires
    if direction > 0:
        fire_mask = signal > threshold
    else:
        fire_mask = signal < threshold

    n_fire = np.sum(fire_mask)
    n_total = len(signal)

    if n_fire < 5:
        return {'r': np.nan, 'accuracy': np.nan, 'freq': 0, 'n': n_fire, 'vol_dependent': vol_dependent}

    # Accuracy when signal fires
    target_when_fire = target[fire_mask]
    if direction > 0:
        accuracy = np.mean(target_when_fire > 0)
    else:
        accuracy = np.mean(target_when_fire < 0)

    # Average move when signal fires
    avg_move = np.mean(target_when_fire)

    return {
        'r': np.nan,  # Not applicable for threshold signals
        'accuracy': accuracy,
        'freq': n_fire / n_total,
        'n': n_fire,
        'avg_move': avg_move,
        'vol_dependent': vol_dependent
    }

def print_analysis(name: str, results: Dict, indent: int = 2):
    """Print analysis results in a formatted way."""
    indent_str = " " * indent
    vol_tag = "[VOL-DEP]" if results.get('vol_dependent', False) else "[VOL-IND]"

    r = results.get('r', np.nan)
    acc = results.get('accuracy', np.nan)
    freq = results.get('freq', 0)
    n = results.get('n', 0)

    r_str = f"r={r:+.4f}" if not np.isnan(r) else "r=N/A    "
    acc_str = f"acc={acc*100:5.1f}%" if not np.isnan(acc) else "acc= N/A "
    freq_str = f"freq={freq*100:5.1f}%" if freq > 0 else "freq= 0.0%"

    extra = ""
    if 'avg_move' in results:
        extra = f" avg_move={results['avg_move']:+.3f}"

    print(f"{indent_str}{name:50s} {vol_tag:10s} {r_str:12s} {acc_str:12s} {freq_str:12s} n={n:5d}{extra}")

def run_vwmp_analysis(df: pd.DataFrame, day: int):
    """Analysis 1: Volume-Weighted Mid Price (VWMP)."""
    print(f"\n{'='*80}")
    print(f"1. VOLUME-WEIGHTED MID PRICE (VWMP) - Day {day}")
    print(f"{'='*80}")

    # VWMP at L1: (bid1 * ask1_vol + ask1 * bid1_vol) / (bid1_vol + ask1_vol)
    df['vwmp_l1'] = (df['bid1'] * df['ask1_vol'] + df['ask1'] * df['bid1_vol']) / (df['bid1_vol'] + df['ask1_vol'])
    df['vwmp_l1_dev'] = df['vwmp_l1'] - df['mid']  # Deviation from simple mid

    # VWMP at L2
    df['vwmp_l2'] = (df['bid2'] * df['ask2_vol'] + df['ask2'] * df['bid2_vol']) / (df['bid2_vol'] + df['ask2_vol'])
    df['vwmp_l2_dev'] = df['vwmp_l2'] - df['mid']

    # Full VWMP (weighted by total volume at each level)
    l1_weight = (df['bid1_vol'] + df['ask1_vol'])
    l2_weight = (df['bid2_vol'] + df['ask2_vol'])
    total_weight = l1_weight + l2_weight
    df['vwmp_full'] = (df['vwmp_l1'] * l1_weight + df['vwmp_l2'] * l2_weight) / total_weight
    df['vwmp_full'] = df['vwmp_full'].fillna(df['vwmp_l1'])  # Fallback if L2 missing
    df['vwmp_full_dev'] = df['vwmp_full'] - df['mid']

    # Microprice (standard)
    df['microprice'] = (df['bid1'] * df['ask1_vol'] + df['ask1'] * df['bid1_vol']) / (df['bid1_vol'] + df['ask1_vol'])
    df['microprice_dev'] = df['microprice'] - df['mid']

    results = {
        'VWMP_L1 deviation': analyze_signal(df, 'vwmp_l1_dev', vol_dependent=True),
        'VWMP_L2 deviation': analyze_signal(df, 'vwmp_l2_dev', vol_dependent=True),
        'VWMP_full deviation': analyze_signal(df, 'vwmp_full_dev', vol_dependent=True),
        'Microprice deviation': analyze_signal(df, 'microprice_dev', vol_dependent=True),
    }

    for name, res in results.items():
        print_analysis(name, res)

    return results

def run_vwap_analysis(df: pd.DataFrame, day: int):
    """Analysis 2: Volume-Weighted Average Prices (VWAP) for bid/ask sides."""
    print(f"\n{'='*80}")
    print(f"2. VOLUME-WEIGHTED AVERAGE PRICES (VWAP) - Day {day}")
    print(f"{'='*80}")

    # VWAP bid side
    df['vwap_bid'] = (df['bid1'] * df['bid1_vol'] + df['bid2'] * df['bid2_vol']) / (df['bid1_vol'] + df['bid2_vol'])

    # VWAP ask side
    df['vwap_ask'] = (df['ask1'] * df['ask1_vol'] + df['ask2'] * df['ask2_vol']) / (df['ask1_vol'] + df['ask2_vol'])

    # VWAP spread vs simple spread
    df['vwap_spread'] = df['vwap_ask'] - df['vwap_bid']
    df['vwap_spread_diff'] = df['vwap_spread'] - df['spread']

    # VWAP mid
    df['vwap_mid'] = (df['vwap_bid'] + df['vwap_ask']) / 2
    df['vwap_mid_dev'] = df['vwap_mid'] - df['mid']

    results = {
        'VWAP_bid - bid1': analyze_signal(df, df['vwap_bid'] - df['bid1'], vol_dependent=True),
        'VWAP_ask - ask1': analyze_signal(df, df['vwap_ask'] - df['ask1'], vol_dependent=True),
        'VWAP spread diff': analyze_signal(df, 'vwap_spread_diff', vol_dependent=True),
        'VWAP mid deviation': analyze_signal(df, 'vwap_mid_dev', vol_dependent=True),
    }

    # Create temp columns for analysis
    df['temp_vwap_bid_diff'] = df['vwap_bid'] - df['bid1']
    df['temp_vwap_ask_diff'] = df['vwap_ask'] - df['ask1']

    results = {
        'VWAP_bid - bid1': analyze_signal(df, 'temp_vwap_bid_diff', vol_dependent=True),
        'VWAP_ask - ask1': analyze_signal(df, 'temp_vwap_ask_diff', vol_dependent=True),
        'VWAP spread diff': analyze_signal(df, 'vwap_spread_diff', vol_dependent=True),
        'VWAP mid deviation': analyze_signal(df, 'vwap_mid_dev', vol_dependent=True),
    }

    for name, res in results.items():
        print_analysis(name, res)

    return results

def run_volume_ratio_analysis(df: pd.DataFrame, day: int):
    """Analysis 3: Volume Ratios and Concentration."""
    print(f"\n{'='*80}")
    print(f"3. VOLUME RATIOS AND CONCENTRATION - Day {day}")
    print(f"{'='*80}")

    # L1/L2 ratio for bid side
    df['bid_l1l2_ratio'] = df['bid1_vol'] / (df['bid2_vol'] + 0.1)  # +0.1 to avoid div by zero
    df['ask_l1l2_ratio'] = df['ask1_vol'] / (df['ask2_vol'] + 0.1)

    # L1 concentration = L1_vol / (L1_vol + L2_vol) for each side
    df['bid_l1_conc'] = df['bid1_vol'] / (df['bid1_vol'] + df['bid2_vol'] + 0.1)
    df['ask_l1_conc'] = df['ask1_vol'] / (df['ask1_vol'] + df['ask2_vol'] + 0.1)

    # Total volume imbalance (bid - ask) / (bid + ask)
    df['vol_imb'] = (df['total_bid_vol'] - df['total_ask_vol']) / (df['total_bid_vol'] + df['total_ask_vol'] + 0.1)

    # L1 only volume imbalance
    df['vol_imb_l1'] = (df['bid1_vol'] - df['ask1_vol']) / (df['bid1_vol'] + df['ask1_vol'] + 0.1)

    # Changes in ratios
    df['d_vol_imb'] = df['vol_imb'].diff()
    df['d_vol_imb_l1'] = df['vol_imb_l1'].diff()

    results = {
        'Volume imbalance (total)': analyze_signal(df, 'vol_imb', vol_dependent=True),
        'Volume imbalance (L1 only)': analyze_signal(df, 'vol_imb_l1', vol_dependent=True),
        'Bid L1/L2 ratio': analyze_signal(df, 'bid_l1l2_ratio', vol_dependent=True),
        'Ask L1/L2 ratio': analyze_signal(df, 'ask_l1l2_ratio', vol_dependent=True),
        'Bid L1 concentration': analyze_signal(df, 'bid_l1_conc', vol_dependent=True),
        'Ask L1 concentration': analyze_signal(df, 'ask_l1_conc', vol_dependent=True),
        'Delta volume imbalance': analyze_signal(df, 'd_vol_imb', vol_dependent=True),
        'Delta volume imbalance (L1)': analyze_signal(df, 'd_vol_imb_l1', vol_dependent=True),
    }

    for name, res in results.items():
        print_analysis(name, res)

    return results

def run_trade_volume_analysis(df: pd.DataFrame, day: int):
    """Analysis 4: Trade Volume Analysis."""
    print(f"\n{'='*80}")
    print(f"4. TRADE VOLUME ANALYSIS - Day {day}")
    print(f"{'='*80}")

    # Trade volume direction
    df['trade_net_vol'] = df['trade_buy_vol'] - df['trade_sell_vol']
    df['trade_total_vol'] = df['trade_buy_vol'] + df['trade_sell_vol']

    # Cumulative trade imbalance
    df['cum_trade_imb'] = df['trade_net_vol'].cumsum()
    df['d_cum_trade_imb'] = df['cum_trade_imb'].diff()

    # Trade volume relative to book
    df['trade_to_book'] = df['trade_total_vol'] / (df['total_bid_vol'] + df['total_ask_vol'] + 0.1)

    # Has trade indicator
    df['has_trade'] = (df['trade_count'] > 0).astype(int)

    results = {
        'Trade net volume': analyze_signal(df, 'trade_net_vol', vol_dependent=True),
        'Trade total volume': analyze_signal(df, 'trade_total_vol', vol_dependent=True),
        'Cumulative trade imbalance': analyze_signal(df, 'cum_trade_imb', vol_dependent=True),
        'Delta cumulative trade imb': analyze_signal(df, 'd_cum_trade_imb', vol_dependent=True),
        'Trade-to-book ratio': analyze_signal(df, 'trade_to_book', vol_dependent=True),
        'Has trade indicator': analyze_signal(df, 'has_trade', vol_dependent=False),
    }

    for name, res in results.items():
        print_analysis(name, res)

    # Trade impact analysis
    print(f"\n  Trade Impact Statistics:")
    trades_with_dmid = df[df['has_trade'] == 1].dropna(subset=['dmid'])
    if len(trades_with_dmid) > 0:
        buy_trades = trades_with_dmid[trades_with_dmid['trade_buy_vol'] > trades_with_dmid['trade_sell_vol']]
        sell_trades = trades_with_dmid[trades_with_dmid['trade_sell_vol'] > trades_with_dmid['trade_buy_vol']]

        print(f"    Buy trades (n={len(buy_trades)}): avg next dmid = {buy_trades['dmid'].mean():+.4f}")
        print(f"    Sell trades (n={len(sell_trades)}): avg next dmid = {sell_trades['dmid'].mean():+.4f}")

        # Large vs small trades (by total volume)
        if len(trades_with_dmid) > 20:
            median_vol = trades_with_dmid['trade_total_vol'].median()
            large = trades_with_dmid[trades_with_dmid['trade_total_vol'] > median_vol]
            small = trades_with_dmid[trades_with_dmid['trade_total_vol'] <= median_vol]
            print(f"    Large trades (>{median_vol:.1f} vol, n={len(large)}): avg next dmid = {large['dmid'].mean():+.4f}")
            print(f"    Small trades (<={median_vol:.1f} vol, n={len(small)}): avg next dmid = {small['dmid'].mean():+.4f}")

    return results

def run_volume_delta_analysis(df: pd.DataFrame, day: int):
    """Analysis 5: Volume Changes (Deltas)."""
    print(f"\n{'='*80}")
    print(f"5. VOLUME CHANGES (DELTAS) - Day {day}")
    print(f"{'='*80}")

    # Delta volumes
    df['d_bid1_vol'] = df['bid1_vol'].diff()
    df['d_ask1_vol'] = df['ask1_vol'].diff()
    df['d_bid2_vol'] = df['bid2_vol'].diff()
    df['d_ask2_vol'] = df['ask2_vol'].diff()
    df['d_total_bid_vol'] = df['total_bid_vol'].diff()
    df['d_total_ask_vol'] = df['total_ask_vol'].diff()

    # Volume change asymmetry
    df['vol_change_asym'] = df['d_total_bid_vol'] - df['d_total_ask_vol']
    df['vol_change_asym_l1'] = df['d_bid1_vol'] - df['d_ask1_vol']

    results = {
        'Delta bid1 volume': analyze_signal(df, 'd_bid1_vol', vol_dependent=True),
        'Delta ask1 volume': analyze_signal(df, 'd_ask1_vol', vol_dependent=True),
        'Delta bid2 volume': analyze_signal(df, 'd_bid2_vol', vol_dependent=True),
        'Delta ask2 volume': analyze_signal(df, 'd_ask2_vol', vol_dependent=True),
        'Delta total bid volume': analyze_signal(df, 'd_total_bid_vol', vol_dependent=True),
        'Delta total ask volume': analyze_signal(df, 'd_total_ask_vol', vol_dependent=True),
        'Volume change asymmetry': analyze_signal(df, 'vol_change_asym', vol_dependent=True),
        'Volume change asymmetry (L1)': analyze_signal(df, 'vol_change_asym_l1', vol_dependent=True),
    }

    for name, res in results.items():
        print_analysis(name, res)

    return results

def run_volume_price_interaction_analysis(df: pd.DataFrame, day: int):
    """Analysis 6: Volume-Price Interactions."""
    print(f"\n{'='*80}")
    print(f"6. VOLUME-PRICE INTERACTIONS - Day {day}")
    print(f"{'='*80}")

    # Price unchanged but volume changes
    df['dmid_lag'] = df['mid'].diff()  # Price change this tick
    df['price_unchanged'] = (df['dmid_lag'] == 0).astype(int)

    # Volume increase on bid while price unchanged
    df['bid_vol_up_price_flat'] = ((df['d_total_bid_vol'] > 0) & (df['dmid_lag'] == 0)).astype(int)
    df['ask_vol_down_price_flat'] = ((df['d_total_ask_vol'] < 0) & (df['dmid_lag'] == 0)).astype(int)
    df['bid_vol_down_price_flat'] = ((df['d_total_bid_vol'] < 0) & (df['dmid_lag'] == 0)).astype(int)
    df['ask_vol_up_price_flat'] = ((df['d_total_ask_vol'] > 0) & (df['dmid_lag'] == 0)).astype(int)

    # Volume surge/drought detection
    vol_total = df['total_bid_vol'] + df['total_ask_vol']
    vol_mean = vol_total.mean()
    vol_std = vol_total.std()

    df['vol_surge'] = (vol_total > vol_mean + 2*vol_std).astype(int)
    df['vol_drought'] = (vol_total < vol_mean - 0.5*vol_std).astype(int)

    results = {
        'Bid vol UP, price flat -> next dmid': analyze_signal(df, 'bid_vol_up_price_flat', vol_dependent=True),
        'Ask vol DOWN, price flat -> next dmid': analyze_signal(df, 'ask_vol_down_price_flat', vol_dependent=True),
        'Bid vol DOWN, price flat -> next dmid': analyze_signal(df, 'bid_vol_down_price_flat', vol_dependent=True),
        'Ask vol UP, price flat -> next dmid': analyze_signal(df, 'ask_vol_up_price_flat', vol_dependent=True),
        'Volume surge (>2 sigma)': analyze_signal(df, 'vol_surge', vol_dependent=True),
        'Volume drought (<0.5 sigma)': analyze_signal(df, 'vol_drought', vol_dependent=True),
    }

    for name, res in results.items():
        print_analysis(name, res)

    # Conditional analysis
    print(f"\n  Conditional Move Analysis:")

    # Bid vol up, price flat
    mask = df['bid_vol_up_price_flat'] == 1
    if mask.sum() > 5:
        avg_dmid = df.loc[mask, 'dmid'].mean()
        pct_up = (df.loc[mask, 'dmid'] > 0).mean() * 100
        print(f"    Bid vol UP + price flat (n={mask.sum()}): avg next dmid={avg_dmid:+.4f}, {pct_up:.1f}% up")

    mask = df['ask_vol_down_price_flat'] == 1
    if mask.sum() > 5:
        avg_dmid = df.loc[mask, 'dmid'].mean()
        pct_up = (df.loc[mask, 'dmid'] > 0).mean() * 100
        print(f"    Ask vol DOWN + price flat (n={mask.sum()}): avg next dmid={avg_dmid:+.4f}, {pct_up:.1f}% up")

    # Volume surge
    mask = df['vol_surge'] == 1
    if mask.sum() > 5:
        avg_dmid = df.loc[mask, 'dmid'].mean()
        pct_up = (df.loc[mask, 'dmid'] > 0).mean() * 100
        print(f"    Volume surge (n={mask.sum()}): avg next dmid={avg_dmid:+.4f}, {pct_up:.1f}% up")

    return results

def run_cross_level_flow_analysis(df: pd.DataFrame, day: int):
    """Analysis 7: Cross-Level Volume Flow."""
    print(f"\n{'='*80}")
    print(f"7. CROSS-LEVEL VOLUME FLOW - Day {day}")
    print(f"{'='*80}")

    # Volume migration: L1 drops but L2 rises
    df['bid_vol_migration'] = ((df['d_bid1_vol'] < 0) & (df['d_bid2_vol'] > 0)).astype(int)
    df['ask_vol_migration'] = ((df['d_ask1_vol'] < 0) & (df['d_ask2_vol'] > 0)).astype(int)

    # Net flow = dL1 - dL2
    df['bid_net_flow'] = df['d_bid1_vol'] - df['d_bid2_vol']
    df['ask_net_flow'] = df['d_ask1_vol'] - df['d_ask2_vol']

    # L1 absorption = big drop in L1 without L2 replacement
    df['bid_l1_absorbed'] = ((df['d_bid1_vol'] < -2) & (df['d_bid2_vol'] <= 0)).astype(int)
    df['ask_l1_absorbed'] = ((df['d_ask1_vol'] < -2) & (df['d_ask2_vol'] <= 0)).astype(int)

    results = {
        'Bid volume migration (L1->L2)': analyze_signal(df, 'bid_vol_migration', vol_dependent=True),
        'Ask volume migration (L1->L2)': analyze_signal(df, 'ask_vol_migration', vol_dependent=True),
        'Bid net flow (dL1 - dL2)': analyze_signal(df, 'bid_net_flow', vol_dependent=True),
        'Ask net flow (dL1 - dL2)': analyze_signal(df, 'ask_net_flow', vol_dependent=True),
        'Bid L1 absorbed': analyze_signal(df, 'bid_l1_absorbed', vol_dependent=True),
        'Ask L1 absorbed': analyze_signal(df, 'ask_l1_absorbed', vol_dependent=True),
    }

    for name, res in results.items():
        print_analysis(name, res)

    # Directional stats
    print(f"\n  Volume Migration Impact:")
    mask = df['bid_vol_migration'] == 1
    if mask.sum() > 5:
        avg_dmid = df.loc[mask, 'dmid'].mean()
        pct_down = (df.loc[mask, 'dmid'] < 0).mean() * 100
        print(f"    Bid L1 vol drops, L2 rises (n={mask.sum()}): avg next dmid={avg_dmid:+.4f}, {pct_down:.1f}% down")

    mask = df['ask_vol_migration'] == 1
    if mask.sum() > 5:
        avg_dmid = df.loc[mask, 'dmid'].mean()
        pct_up = (df.loc[mask, 'dmid'] > 0).mean() * 100
        print(f"    Ask L1 vol drops, L2 rises (n={mask.sum()}): avg next dmid={avg_dmid:+.4f}, {pct_up:.1f}% up")

    return results

def run_volume_weighted_returns_analysis(df: pd.DataFrame, day: int):
    """Analysis 8: Volume-Weighted Returns."""
    print(f"\n{'='*80}")
    print(f"8. VOLUME-WEIGHTED RETURNS - Day {day}")
    print(f"{'='*80}")

    # Volume at time of return
    df['total_vol'] = df['total_bid_vol'] + df['total_ask_vol']

    # Volume-weighted dmid (weight by concurrent volume)
    df['vol_weighted_dmid'] = df['dmid_lag'] * df['total_vol']  # Using dmid_lag (previous tick's dmid)

    # Normalize by average volume
    avg_vol = df['total_vol'].mean()
    df['vol_weight'] = df['total_vol'] / avg_vol

    # AR(1) coefficient for raw vs volume-weighted returns
    dmid = df['dmid'].dropna().values
    dmid_lag = df['dmid'].shift(1).dropna().values[:-1]

    if len(dmid) > 100:
        # Raw return AC(1)
        ac1_raw = np.corrcoef(dmid[1:], dmid[:-1])[0, 1]

        # Volume-weighted return AC(1)
        vol_weighted_ret = df['dmid'] * df['vol_weight']
        vwr = vol_weighted_ret.dropna().values
        if len(vwr) > 100:
            ac1_vw = np.corrcoef(vwr[1:], vwr[:-1])[0, 1]
        else:
            ac1_vw = np.nan

        print(f"  Raw return AC(1): {ac1_raw:+.4f}")
        print(f"  Volume-weighted return AC(1): {ac1_vw:+.4f}")

        # High volume vs low volume returns
        vol_median = df['total_vol'].median()
        high_vol_ticks = df[df['total_vol'] > vol_median]
        low_vol_ticks = df[df['total_vol'] <= vol_median]

        hv_dmid = high_vol_ticks['dmid'].dropna()
        lv_dmid = low_vol_ticks['dmid'].dropna()

        print(f"\n  High volume ticks (n={len(hv_dmid)}): dmid std = {hv_dmid.std():.4f}, mean = {hv_dmid.mean():+.4f}")
        print(f"  Low volume ticks (n={len(lv_dmid)}):  dmid std = {lv_dmid.std():.4f}, mean = {lv_dmid.mean():+.4f}")

    results = {
        'Volume weight -> dmid': analyze_signal(df, 'vol_weight', vol_dependent=True),
        'Vol-weighted prior dmid': analyze_signal(df, 'vol_weighted_dmid', vol_dependent=True),
    }

    for name, res in results.items():
        print_analysis(name, res)

    return results

def run_volume_at_extremes_analysis(df: pd.DataFrame, day: int):
    """Analysis 9: Volume at Price Extremes."""
    print(f"\n{'='*80}")
    print(f"9. VOLUME AT PRICE EXTREMES - Day {day}")
    print(f"{'='*80}")

    # Spread categories
    df['spread_narrow'] = (df['spread'] <= 9).astype(int)
    df['spread_wide'] = (df['spread'] >= 13).astype(int)

    # Volume stats by spread
    narrow_ticks = df[df['spread_narrow'] == 1]
    wide_ticks = df[df['spread_wide'] == 1]

    print(f"  Narrow spread (5-9):")
    if len(narrow_ticks) > 0:
        print(f"    Count: {len(narrow_ticks)} ({100*len(narrow_ticks)/len(df):.1f}%)")
        print(f"    Avg total volume: {narrow_ticks['total_vol'].mean():.1f}")
        print(f"    Avg next dmid: {narrow_ticks['dmid'].mean():+.4f}")
        print(f"    Pct dmid > 0: {(narrow_ticks['dmid'] > 0).mean()*100:.1f}%")

    print(f"\n  Wide spread (13-14):")
    if len(wide_ticks) > 0:
        print(f"    Count: {len(wide_ticks)} ({100*len(wide_ticks)/len(df):.1f}%)")
        print(f"    Avg total volume: {wide_ticks['total_vol'].mean():.1f}")
        print(f"    Avg next dmid: {wide_ticks['dmid'].mean():+.4f}")
        print(f"    Pct dmid > 0: {(wide_ticks['dmid'] > 0).mean()*100:.1f}%")

    # Volume conditional on recent dmid direction
    df['recent_dmid_pos'] = (df['dmid_lag'] > 0).astype(int)
    df['recent_dmid_neg'] = (df['dmid_lag'] < 0).astype(int)

    pos_ticks = df[df['recent_dmid_pos'] == 1]
    neg_ticks = df[df['recent_dmid_neg'] == 1]

    print(f"\n  After UP move (dmid > 0, n={len(pos_ticks)}):")
    if len(pos_ticks) > 0:
        print(f"    Avg bid volume: {pos_ticks['total_bid_vol'].mean():.1f}")
        print(f"    Avg ask volume: {pos_ticks['total_ask_vol'].mean():.1f}")
        print(f"    Vol imbalance: {pos_ticks['vol_imb'].mean():+.4f}")

    print(f"\n  After DOWN move (dmid < 0, n={len(neg_ticks)}):")
    if len(neg_ticks) > 0:
        print(f"    Avg bid volume: {neg_ticks['total_bid_vol'].mean():.1f}")
        print(f"    Avg ask volume: {neg_ticks['total_ask_vol'].mean():.1f}")
        print(f"    Vol imbalance: {neg_ticks['vol_imb'].mean():+.4f}")

    # Does high volume predict spread narrowing?
    df['next_spread'] = df['spread'].shift(-1)
    df['spread_narrows'] = (df['next_spread'] < df['spread']).astype(int)

    high_vol_ticks = df[df['total_vol'] > df['total_vol'].quantile(0.75)]
    print(f"\n  High volume ticks -> spread narrows next tick: {high_vol_ticks['spread_narrows'].mean()*100:.1f}%")
    print(f"  All ticks -> spread narrows next tick: {df['spread_narrows'].mean()*100:.1f}%")

    results = {
        'Spread narrow indicator': analyze_signal(df, 'spread_narrow', vol_dependent=False),
        'Spread wide indicator': analyze_signal(df, 'spread_wide', vol_dependent=False),
        'Recent dmid positive': analyze_signal(df, 'recent_dmid_pos', vol_dependent=False),
        'Recent dmid negative': analyze_signal(df, 'recent_dmid_neg', vol_dependent=False),
    }

    for name, res in results.items():
        print_analysis(name, res)

    return results

def run_trade_to_book_ratio_analysis(df: pd.DataFrame, day: int):
    """Analysis 10: Trade-to-Book Ratio."""
    print(f"\n{'='*80}")
    print(f"10. TRADE-TO-BOOK RATIO ANALYSIS - Day {day}")
    print(f"{'='*80}")

    # Overall trade-to-book
    df['ttb_ratio'] = df['trade_total_vol'] / (df['total_vol'] + 0.1)

    # Directional trade-to-book
    df['ttb_buy_ratio'] = df['trade_buy_vol'] / (df['total_bid_vol'] + 0.1)
    df['ttb_sell_ratio'] = df['trade_sell_vol'] / (df['total_ask_vol'] + 0.1)

    # TTB imbalance
    df['ttb_imb'] = df['ttb_buy_ratio'] - df['ttb_sell_ratio']

    results = {
        'Trade-to-book ratio': analyze_signal(df, 'ttb_ratio', vol_dependent=True),
        'TTB buy ratio': analyze_signal(df, 'ttb_buy_ratio', vol_dependent=True),
        'TTB sell ratio': analyze_signal(df, 'ttb_sell_ratio', vol_dependent=True),
        'TTB imbalance (buy-sell)': analyze_signal(df, 'ttb_imb', vol_dependent=True),
    }

    for name, res in results.items():
        print_analysis(name, res)

    # Impact when TTB is high
    high_ttb = df[df['ttb_ratio'] > df['ttb_ratio'].quantile(0.9)]
    if len(high_ttb) > 5:
        print(f"\n  High TTB (top 10%) -> next dmid: {high_ttb['dmid'].mean():+.4f}")

    return results

def run_additional_analyses(df: pd.DataFrame, day: int):
    """Additional analyses: OBI variants, gap asymmetry, etc."""
    print(f"\n{'='*80}")
    print(f"11. ADDITIONAL VOLUME ANALYSES - Day {day}")
    print(f"{'='*80}")

    # Gap asymmetry = (bid1-bid2) - (ask2-ask1)
    df['gap_bid'] = df['bid1'] - df['bid2']
    df['gap_ask'] = df['ask2'] - df['ask1']
    df['gap_asymmetry'] = df['gap_bid'] - df['gap_ask']

    # Distance-weighted volume imbalance
    df['dist_weighted_bid'] = df['bid1_vol'] / 1 + df['bid2_vol'] / 2
    df['dist_weighted_ask'] = df['ask1_vol'] / 1 + df['ask2_vol'] / 2
    df['dist_weighted_imb'] = (df['dist_weighted_bid'] - df['dist_weighted_ask']) / (df['dist_weighted_bid'] + df['dist_weighted_ask'] + 0.1)

    # L2 only imbalance
    df['vol_imb_l2'] = (df['bid2_vol'] - df['ask2_vol']) / (df['bid2_vol'] + df['ask2_vol'] + 0.1)

    # Weighted microprice deviation (L1 + L2)
    l1_mp = (df['bid1'] * df['ask1_vol'] + df['ask1'] * df['bid1_vol']) / (df['bid1_vol'] + df['ask1_vol'] + 0.1)
    l2_mp = (df['bid2'] * df['ask2_vol'] + df['ask2'] * df['bid2_vol']) / (df['bid2_vol'] + df['ask2_vol'] + 0.1)
    l1_wt = df['bid1_vol'] + df['ask1_vol']
    l2_wt = df['bid2_vol'] + df['ask2_vol']
    df['weighted_mp'] = (l1_mp * l1_wt + l2_mp * l2_wt) / (l1_wt + l2_wt + 0.1)
    df['weighted_mp_dev'] = df['weighted_mp'] - df['mid']

    # OBI change
    df['d_vol_imb'] = df['vol_imb'].diff()

    # Book pressure = bid_vol - ask_vol (raw, not normalized)
    df['book_pressure'] = df['total_bid_vol'] - df['total_ask_vol']
    df['d_book_pressure'] = df['book_pressure'].diff()

    results = {
        'Gap asymmetry (bid1-bid2) - (ask2-ask1)': analyze_signal(df, 'gap_asymmetry', vol_dependent=False),
        'Distance-weighted imbalance': analyze_signal(df, 'dist_weighted_imb', vol_dependent=True),
        'L2 volume imbalance': analyze_signal(df, 'vol_imb_l2', vol_dependent=True),
        'Weighted microprice deviation': analyze_signal(df, 'weighted_mp_dev', vol_dependent=True),
        'Delta volume imbalance': analyze_signal(df, 'd_vol_imb', vol_dependent=True),
        'Book pressure (bid-ask vol)': analyze_signal(df, 'book_pressure', vol_dependent=True),
        'Delta book pressure': analyze_signal(df, 'd_book_pressure', vol_dependent=True),
    }

    for name, res in results.items():
        print_analysis(name, res)

    return results

def run_lagged_analysis(df: pd.DataFrame, day: int):
    """Analysis of lagged signals."""
    print(f"\n{'='*80}")
    print(f"12. LAGGED SIGNAL ANALYSIS - Day {day}")
    print(f"{'='*80}")

    # Multi-lag microprice
    for lag in [1, 2, 3, 4]:
        df[f'microprice_lag{lag}'] = df['microprice'].shift(lag)
        df[f'microprice_dev_lag{lag}'] = df[f'microprice_lag{lag}'] - df['mid'].shift(lag)

    # Multi-lag volume imbalance
    for lag in [1, 2, 3, 4]:
        df[f'vol_imb_lag{lag}'] = df['vol_imb'].shift(lag)

    results = {}
    for lag in [1, 2, 3, 4]:
        results[f'Microprice dev lag-{lag}'] = analyze_signal(df, f'microprice_dev_lag{lag}', vol_dependent=True)
        results[f'Volume imb lag-{lag}'] = analyze_signal(df, f'vol_imb_lag{lag}', vol_dependent=True)

    for name, res in results.items():
        print_analysis(name, res)

    return results

def run_regime_analysis(df: pd.DataFrame, day: int):
    """Analysis by market regime."""
    print(f"\n{'='*80}")
    print(f"13. REGIME-CONDITIONAL ANALYSIS - Day {day}")
    print(f"{'='*80}")

    # Define regimes
    df['high_vol_regime'] = (df['total_vol'] > df['total_vol'].quantile(0.75)).astype(int)
    df['trending_up'] = (df['mid'].rolling(20).mean() > df['mid'].rolling(50).mean()).astype(int)
    df['volatile_regime'] = (df['dmid_lag'].abs().rolling(10).mean() > df['dmid_lag'].abs().mean()).astype(int)

    # Volume imbalance by regime
    regimes = {
        'High volume': df[df['high_vol_regime'] == 1],
        'Low volume': df[df['high_vol_regime'] == 0],
        'Trending up': df[df['trending_up'] == 1],
        'Trending down': df[df['trending_up'] == 0],
        'High volatility': df[df['volatile_regime'] == 1],
        'Low volatility': df[df['volatile_regime'] == 0],
    }

    print(f"  Volume Imbalance -> dmid by Regime:")
    for regime_name, regime_df in regimes.items():
        if len(regime_df) > 50:
            res = analyze_signal(regime_df, 'vol_imb', vol_dependent=True)
            print(f"    {regime_name:20s}: r={res['r']:+.4f}, acc={res['accuracy']*100:.1f}%, n={res['n']}")

    return {}

def run_combination_signals(df: pd.DataFrame, day: int):
    """Analysis of combined signals."""
    print(f"\n{'='*80}")
    print(f"14. COMBINATION SIGNALS - Day {day}")
    print(f"{'='*80}")

    # Combine microprice + vol imb
    df['combo_mp_vi'] = df['microprice_dev'] + 0.5 * df['vol_imb']

    # Combine L1 + L2 imbalance
    df['combo_l1l2_imb'] = df['vol_imb_l1'] + 0.5 * df['vol_imb_l2']

    # Volume confirmation: vol imb in same direction as microprice
    df['vol_confirms_mp'] = (np.sign(df['vol_imb']) == np.sign(df['microprice_dev'])).astype(int)

    # Strong signal: both agree and magnitude is large
    df['strong_signal'] = ((df['vol_confirms_mp'] == 1) &
                           (df['microprice_dev'].abs() > df['microprice_dev'].abs().quantile(0.75))).astype(int)

    results = {
        'Combo microprice + vol_imb': analyze_signal(df, 'combo_mp_vi', vol_dependent=True),
        'Combo L1+L2 imbalance': analyze_signal(df, 'combo_l1l2_imb', vol_dependent=True),
        'Volume confirms microprice': analyze_signal(df, 'vol_confirms_mp', vol_dependent=True),
        'Strong signal (confirms + large)': analyze_signal(df, 'strong_signal', vol_dependent=True),
    }

    for name, res in results.items():
        print_analysis(name, res)

    # Accuracy when strong signal fires
    strong = df[df['strong_signal'] == 1]
    if len(strong) > 10:
        correct = (np.sign(strong['microprice_dev']) == np.sign(strong['dmid'])).mean()
        print(f"\n  Strong signal accuracy: {correct*100:.1f}% (n={len(strong)})")

    return results

def run_spread_transition_analysis(df: pd.DataFrame, day: int):
    """Analysis around spread state transitions."""
    print(f"\n{'='*80}")
    print(f"15. SPREAD TRANSITION ANALYSIS - Day {day}")
    print(f"{'='*80}")

    # Spread state changes
    df['spread_change'] = df['spread'].diff()
    df['spread_narrowing'] = (df['spread_change'] < 0).astype(int)
    df['spread_widening'] = (df['spread_change'] > 0).astype(int)

    # Volume before spread transition
    df['vol_before_narrow'] = df['total_vol'].shift(1) * df['spread_narrowing']
    df['vol_before_widen'] = df['total_vol'].shift(1) * df['spread_widening']

    # dmid after transition
    narrowing_ticks = df[df['spread_narrowing'] == 1]
    widening_ticks = df[df['spread_widening'] == 1]

    print(f"  Spread Narrowing Events (n={len(narrowing_ticks)}):")
    if len(narrowing_ticks) > 0:
        print(f"    Avg next dmid: {narrowing_ticks['dmid'].mean():+.4f}")
        print(f"    Avg vol_imb before: {narrowing_ticks['vol_imb'].shift(1).mean():+.4f}")

    print(f"\n  Spread Widening Events (n={len(widening_ticks)}):")
    if len(widening_ticks) > 0:
        print(f"    Avg next dmid: {widening_ticks['dmid'].mean():+.4f}")
        print(f"    Avg vol_imb before: {widening_ticks['vol_imb'].shift(1).mean():+.4f}")

    results = {
        'Spread narrowing': analyze_signal(df, 'spread_narrowing', vol_dependent=False),
        'Spread widening': analyze_signal(df, 'spread_widening', vol_dependent=False),
    }

    for name, res in results.items():
        print_analysis(name, res)

    return results

def run_summary_statistics(df: pd.DataFrame, day: int):
    """Print summary statistics."""
    print(f"\n{'='*80}")
    print(f"SUMMARY STATISTICS - Day {day}")
    print(f"{'='*80}")

    # Make sure total_vol exists
    if 'total_vol' not in df.columns:
        df['total_vol'] = df['total_bid_vol'] + df['total_ask_vol']

    print(f"\n  Price Statistics:")
    print(f"    Mid range: [{df['mid'].min():.1f}, {df['mid'].max():.1f}]")
    print(f"    Mid mean: {df['mid'].mean():.2f}")
    print(f"    dmid mean: {df['dmid'].mean():+.4f}, std: {df['dmid'].std():.4f}")
    print(f"    Spread mean: {df['spread'].mean():.2f}")

    print(f"\n  Volume Statistics:")
    print(f"    Total vol mean: {df['total_vol'].mean():.1f}")
    print(f"    L1 bid vol mean: {df['bid1_vol'].mean():.1f}")
    print(f"    L1 ask vol mean: {df['ask1_vol'].mean():.1f}")
    print(f"    L2 bid vol mean: {df['bid2_vol'].mean():.1f}")
    print(f"    L2 ask vol mean: {df['ask2_vol'].mean():.1f}")

    print(f"\n  Trade Statistics:")
    total_trades = df['trade_count'].sum()
    total_buy_vol = df['trade_buy_vol'].sum()
    total_sell_vol = df['trade_sell_vol'].sum()
    print(f"    Total trade events: {int(total_trades)}")
    print(f"    Total buy volume: {int(total_buy_vol)}")
    print(f"    Total sell volume: {int(total_sell_vol)}")
    print(f"    Net trade volume: {int(total_buy_vol - total_sell_vol)}")

def run_all_analyses(day: int):
    """Run all analyses for a given day."""
    print(f"\n{'#'*80}")
    print(f"# VOLUME-WEIGHTED ANALYSIS FOR TOMATOES - DAY {day}")
    print(f"{'#'*80}")

    df = prepare_tomatoes_data(day)

    # Run all analyses
    run_summary_statistics(df, day)
    run_vwmp_analysis(df, day)
    run_vwap_analysis(df, day)
    run_volume_ratio_analysis(df, day)
    run_trade_volume_analysis(df, day)
    run_volume_delta_analysis(df, day)
    run_volume_price_interaction_analysis(df, day)
    run_cross_level_flow_analysis(df, day)
    run_volume_weighted_returns_analysis(df, day)
    run_volume_at_extremes_analysis(df, day)
    run_trade_to_book_ratio_analysis(df, day)
    run_additional_analyses(df, day)
    run_lagged_analysis(df, day)
    run_regime_analysis(df, day)
    run_combination_signals(df, day)
    run_spread_transition_analysis(df, day)

    return df

def cross_day_comparison():
    """Compare signal stability across days."""
    print(f"\n{'#'*80}")
    print(f"# CROSS-DAY SIGNAL STABILITY COMPARISON")
    print(f"{'#'*80}")

    key_signals = [
        ('vol_imb', 'Volume imbalance', True),
        ('vol_imb_l1', 'L1 volume imbalance', True),
        ('microprice_dev', 'Microprice deviation', True),
        ('gap_asymmetry', 'Gap asymmetry', False),
        ('d_vol_imb', 'Delta vol imb', True),
        ('vol_imb_l2', 'L2 volume imbalance', True),
        ('dist_weighted_imb', 'Dist-weighted imb', True),
    ]

    print(f"\n{'Signal':<35s} {'Day -2':>12s} {'Day -1':>12s} {'Day 0':>12s} {'Stable?':>10s} {'Vol-Dep':<10s}")
    print("-" * 95)

    for signal_col, signal_name, vol_dep in key_signals:
        correlations = []
        for day in [-2, -1, 0]:
            df = prepare_tomatoes_data(day)

            # Need to compute all signals
            df['microprice'] = (df['bid1'] * df['ask1_vol'] + df['ask1'] * df['bid1_vol']) / (df['bid1_vol'] + df['ask1_vol'])
            df['microprice_dev'] = df['microprice'] - df['mid']
            df['vol_imb'] = (df['total_bid_vol'] - df['total_ask_vol']) / (df['total_bid_vol'] + df['total_ask_vol'] + 0.1)
            df['vol_imb_l1'] = (df['bid1_vol'] - df['ask1_vol']) / (df['bid1_vol'] + df['ask1_vol'] + 0.1)
            df['vol_imb_l2'] = (df['bid2_vol'] - df['ask2_vol']) / (df['bid2_vol'] + df['ask2_vol'] + 0.1)
            df['gap_asymmetry'] = (df['bid1'] - df['bid2']) - (df['ask2'] - df['ask1'])
            df['d_vol_imb'] = df['vol_imb'].diff()
            df['dist_weighted_bid'] = df['bid1_vol'] / 1 + df['bid2_vol'] / 2
            df['dist_weighted_ask'] = df['ask1_vol'] / 1 + df['ask2_vol'] / 2
            df['dist_weighted_imb'] = (df['dist_weighted_bid'] - df['dist_weighted_ask']) / (df['dist_weighted_bid'] + df['dist_weighted_ask'] + 0.1)

            res = analyze_signal(df, signal_col, vol_dependent=vol_dep)
            correlations.append(res['r'])

        # Check stability: all correlations same sign and similar magnitude
        signs = [np.sign(r) for r in correlations]
        stable = "YES" if len(set(signs)) == 1 and all(abs(r) > 0.05 for r in correlations) else "NO"
        vol_tag = "YES" if vol_dep else "NO"

        print(f"{signal_name:<35s} {correlations[0]:>+12.4f} {correlations[1]:>+12.4f} {correlations[2]:>+12.4f} {stable:>10s} {vol_tag:<10s}")

def main():
    """Main entry point."""
    print("=" * 80)
    print("VOLUME-WEIGHTED TRADE ANALYSIS FOR IMC PROSPERITY 4")
    print("=" * 80)
    print("\nAnalyzing TOMATOES across all 3 days (day -2, -1, 0)")
    print("Target: next-tick dmid (mid price change)")
    print("\nLegend:")
    print("  [VOL-DEP] = Uses absolute volume values (may not transfer to website)")
    print("  [VOL-IND] = Uses only ratios/prices (should transfer to website)")
    print("  r = correlation with next dmid")
    print("  acc = directional accuracy when signal != 0")
    print("  freq = fraction of ticks where signal fires")

    # Run for each day
    for day in [-2, -1, 0]:
        run_all_analyses(day)

    # Cross-day comparison
    cross_day_comparison()

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()
