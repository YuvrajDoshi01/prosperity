"""
Nuclear search for 0.9+ predictive correlations in Prosperity 4 data.
Tests 15 creative hypotheses beyond standard dmid(t+1) prediction.
"""

import numpy as np
import pandas as pd
from pathlib import Path
import warnings
import time
from itertools import product as iterproduct

warnings.filterwarnings('ignore')

# ============================================================================
# DATA LOADING
# ============================================================================
BASE = Path("/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0")
PRICE_FILES = {
    "day-2": BASE / "prices_round_0_day_-2.csv",
    "day-1": BASE / "prices_round_0_day_-1.csv",
    "day0":  BASE / "prices_round_0_day_0.csv",
}
TRADE_FILES = {
    "day-2": BASE / "trades_round_0_day_-2.csv",
    "day-1": BASE / "trades_round_0_day_-1.csv",
    "day0":  BASE / "trades_round_0_day_0.csv",
}

def load_data():
    """Load all days, return dict of {day: {product: DataFrame}}"""
    all_data = {}
    for day_name, fpath in PRICE_FILES.items():
        df = pd.read_csv(fpath, sep=';')
        trades_df = pd.read_csv(TRADE_FILES[day_name], sep=';')

        day_data = {}
        for product in ['TOMATOES', 'EMERALDS']:
            pdf = df[df['product'] == product].copy().sort_values('timestamp').reset_index(drop=True)
            # Parse columns
            for col in ['bid_price_1','bid_volume_1','bid_price_2','bid_volume_2','bid_price_3','bid_volume_3',
                        'ask_price_1','ask_volume_1','ask_price_2','ask_volume_2','ask_price_3','ask_volume_3',
                        'mid_price']:
                pdf[col] = pd.to_numeric(pdf[col], errors='coerce')

            # Derived features
            pdf['spread'] = pdf['ask_price_1'] - pdf['bid_price_1']
            pdf['dmid'] = pdf['mid_price'].diff()
            pdf['microprice'] = (pdf['bid_price_1'] * pdf['ask_volume_1'] + pdf['ask_price_1'] * pdf['bid_volume_1']) / (pdf['bid_volume_1'] + pdf['ask_volume_1'])

            # L1 volumes
            pdf['bid_vol_1'] = pdf['bid_volume_1'].abs()
            pdf['ask_vol_1'] = pdf['ask_volume_1'].abs()

            # L2 volumes (handle NaN)
            pdf['bid_vol_2'] = pdf['bid_volume_2'].abs().fillna(0)
            pdf['ask_vol_2'] = pdf['ask_volume_2'].abs().fillna(0)

            # L3 volumes
            pdf['bid_vol_3'] = pdf['bid_volume_3'].abs().fillna(0)
            pdf['ask_vol_3'] = pdf['ask_volume_3'].abs().fillna(0)

            # Total volumes
            pdf['total_bid_vol'] = pdf['bid_vol_1'] + pdf['bid_vol_2'] + pdf['bid_vol_3']
            pdf['total_ask_vol'] = pdf['ask_vol_1'] + pdf['ask_vol_2'] + pdf['ask_vol_3']

            # OBI variants
            total_vol = pdf['total_bid_vol'] + pdf['total_ask_vol']
            pdf['obi_total'] = (pdf['total_bid_vol'] - pdf['total_ask_vol']) / total_vol.replace(0, np.nan)
            pdf['obi_l1'] = (pdf['bid_vol_1'] - pdf['ask_vol_1']) / (pdf['bid_vol_1'] + pdf['ask_vol_1']).replace(0, np.nan)
            pdf['obi_l2'] = (pdf['bid_vol_2'] - pdf['ask_vol_2']) / (pdf['bid_vol_2'] + pdf['ask_vol_2']).replace(0, np.nan)

            # Microprice deviation
            pdf['mp_dev'] = pdf['microprice'] - pdf['mid_price']

            # Gap asymmetry
            pdf['gap_bid'] = pdf['bid_price_1'] - pdf['bid_price_2']
            pdf['gap_ask'] = pdf['ask_price_2'] - pdf['ask_price_1']
            pdf['gap_asym'] = pdf['gap_bid'] - pdf['gap_ask']

            # Distance-weighted vol imbalance
            mid = pdf['mid_price']
            w_b1 = pdf['bid_vol_1'] / (mid - pdf['bid_price_1']).replace(0, np.nan)
            w_b2 = pdf['bid_vol_2'] / (mid - pdf['bid_price_2']).replace(0, np.nan)
            w_a1 = pdf['ask_vol_1'] / (pdf['ask_price_1'] - mid).replace(0, np.nan)
            w_a2 = pdf['ask_vol_2'] / (pdf['ask_price_2'] - mid).replace(0, np.nan)
            wb = w_b1.fillna(0) + w_b2.fillna(0)
            wa = w_a1.fillna(0) + w_a2.fillna(0)
            pdf['vol_imb_dw'] = (wb - wa) / (wb + wa).replace(0, np.nan)

            # L2/L1 ratio
            pdf['l2l1_bid'] = pdf['bid_vol_2'] / pdf['bid_vol_1'].replace(0, np.nan)
            pdf['l2l1_ask'] = pdf['ask_vol_2'] / pdf['ask_vol_1'].replace(0, np.nan)

            # dbid, dask
            pdf['dbid'] = pdf['bid_price_1'].diff()
            pdf['dask'] = pdf['ask_price_1'].diff()

            # Volume changes
            pdf['d_bid_vol_1'] = pdf['bid_vol_1'].diff()
            pdf['d_ask_vol_1'] = pdf['ask_vol_1'].diff()

            # Merge trade info (binary: did a trade happen at this timestamp?)
            tdf = trades_df[trades_df['symbol'] == product].copy()
            trade_ts = set(tdf['timestamp'].values)
            pdf['trade_occurred'] = pdf['timestamp'].isin(trade_ts).astype(int)

            # Trade side info
            trade_info = tdf.groupby('timestamp').agg(
                trade_qty=('quantity', 'sum'),
                trade_price=('price', 'mean')
            ).reset_index()
            pdf = pdf.merge(trade_info, on='timestamp', how='left')
            pdf['trade_qty'] = pdf['trade_qty'].fillna(0)

            day_data[product] = pdf

        all_data[day_name] = day_data

    return all_data

def safe_corr(x, y):
    """Correlation ignoring NaN, return NaN if not enough data."""
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 30:
        return np.nan
    return np.corrcoef(x[mask], y[mask])[0, 1]

# ============================================================================
# RESULTS TRACKING
# ============================================================================
findings = []  # (hypothesis, description, {day: corr}, actionable_note)

def record(hyp_num, desc, corrs, actionable=""):
    """Record a finding."""
    findings.append((hyp_num, desc, corrs, actionable))

def best_per_hypothesis():
    """Return best finding per hypothesis."""
    best = {}
    for hyp, desc, corrs, act in findings:
        vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
        if not vals:
            continue
        min_abs = min(vals)
        if hyp not in best or min_abs > best[hyp][0]:
            best[hyp] = (min_abs, desc, corrs, act)
    return best

# ============================================================================
# HYPOTHESIS TESTS
# ============================================================================

def test_h1_smoothed_target(data):
    """H1: Feature → smoothed future mid"""
    print("\n" + "="*80)
    print("HYPOTHESIS 1: Predicting SMOOTHED targets (EMA/rolling mean of future mid)")
    print("="*80)

    alphas = [0.001, 0.005, 0.01, 0.02, 0.05, 0.1]
    windows = [5, 10, 20, 50, 100, 200]
    features = ['mid_price', 'microprice', 'obi_total', 'mp_dev', 'vol_imb_dw', 'bid_price_1', 'ask_price_1']

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES']:
        for feat in features:
            for alpha in alphas:
                corrs = {}
                for day_name, day_data in data.items():
                    df = day_data[product]
                    x = df[feat].values
                    # EMA of mid
                    ema = df['mid_price'].ewm(alpha=alpha, adjust=False).mean().values
                    # Shift: feature at t vs ema at t+k
                    for lag in [1, 5, 10, 20]:
                        if lag < len(x):
                            r = safe_corr(x[:-lag], ema[lag:])
                            corrs[f"{day_name}_lag{lag}"] = r

                # Check stability: need all days to have high corr for at least one lag
                for lag in [1, 5, 10, 20]:
                    lag_corrs = {d: corrs.get(f"{d}_lag{lag}", np.nan) for d in data.keys()}
                    vals = [abs(v) for v in lag_corrs.values() if np.isfinite(v)]
                    if vals and min(vals) > best_r:
                        best_r = min(vals)
                        best_desc = f"{product} {feat}[t] -> EMA(mid,a={alpha})[t+{lag}]"
                        best_corrs = lag_corrs
                    if vals and min(vals) >= 0.85:
                        desc = f"{product} {feat}[t] -> EMA(mid,a={alpha})[t+{lag}]"
                        record(1, desc, lag_corrs, "Smoothed target - may not be directly tradeable")
                        print(f"  *** |r|>0.85: {desc}")
                        for d, v in lag_corrs.items():
                            print(f"      {d}: {v:.6f}")

    # Also test: smoothed feature -> smoothed target
    for product in ['TOMATOES']:
        for alpha in [0.01, 0.05, 0.1]:
            corrs_all = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                ema_obi = df['obi_total'].ewm(alpha=alpha, adjust=False).mean().values
                ema_mid = df['mid_price'].ewm(alpha=alpha, adjust=False).mean().values
                for lag in [1, 5, 10, 20, 50]:
                    if lag < len(ema_obi):
                        r = safe_corr(ema_obi[:-lag], ema_mid[lag:])
                        corrs_all[f"{day_name}_lag{lag}"] = r

            for lag in [1, 5, 10, 20, 50]:
                lag_corrs = {d: corrs_all.get(f"{d}_lag{lag}", np.nan) for d in data.keys()}
                vals = [abs(v) for v in lag_corrs.values() if np.isfinite(v)]
                if vals and min(vals) >= 0.85:
                    desc = f"{product} EMA(obi,a={alpha})[t] -> EMA(mid,a={alpha})[t+{lag}]"
                    record(1, desc, lag_corrs, "Double-smoothed - indirect signal")
                    print(f"  *** |r|>0.85: {desc}")
                    for d, v in lag_corrs.items():
                        print(f"      {d}: {v:.6f}")

    if best_desc:
        print(f"\n  Best H1: {best_desc} (min |r| = {best_r:.6f})")
        record(1, f"BEST: {best_desc}", best_corrs, "Best of H1")


def test_h2_next_price(data):
    """H2: Predicting next bid/ask price (level, not change)"""
    print("\n" + "="*80)
    print("HYPOTHESIS 2: Predicting NEXT bid/ask PRICE (levels, not changes)")
    print("="*80)

    feature_target_pairs = [
        ('mid_price', 'bid_price_1', 1),
        ('mid_price', 'ask_price_1', 1),
        ('microprice', 'bid_price_1', 1),
        ('microprice', 'ask_price_1', 1),
        ('microprice', 'mid_price', 1),
        ('bid_price_1', 'bid_price_1', 1),
        ('ask_price_1', 'ask_price_1', 1),
        ('bid_price_1', 'ask_price_1', 1),
        ('mp_dev', 'dbid', 1),
        ('mp_dev', 'dask', 1),
        ('obi_total', 'dbid', 1),
        ('obi_total', 'dask', 1),
    ]

    best_r = 0
    best_desc = ""
    best_corrs_overall = {}

    for product in ['TOMATOES', 'EMERALDS']:
        for feat, target, lag in feature_target_pairs:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                x = df[feat].values
                y = df[target].values
                if lag > 0:
                    r = safe_corr(x[:-lag], y[lag:])
                else:
                    r = safe_corr(x, y)
                corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} {feat}[t] -> {target}[t+{lag}]"
                best_corrs_overall = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} {feat}[t] -> {target}[t+{lag}]"
                record(2, desc, corrs, "Price level prediction - trivial if level->level")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

    if best_desc:
        print(f"\n  Best H2: {best_desc} (min |r| = {best_r:.6f})")
        record(2, f"BEST: {best_desc}", best_corrs_overall, "Best of H2")


def test_h3_spread_prediction(data):
    """H3: Predicting spread state"""
    print("\n" + "="*80)
    print("HYPOTHESIS 3: Predicting SPREAD STATE")
    print("="*80)

    features = ['spread', 'dmid', 'obi_total', 'mp_dev', 'gap_asym', 'vol_imb_dw',
                 'bid_vol_1', 'ask_vol_1', 'total_bid_vol', 'total_ask_vol']

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES']:
        for feat in features:
            for lag in [1, 2, 5, 10]:
                corrs = {}
                for day_name, day_data in data.items():
                    df = day_data[product]
                    x = df[feat].values
                    y = df['spread'].values
                    if lag < len(x):
                        r = safe_corr(x[:-lag], y[lag:])
                        corrs[day_name] = r

                vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
                if vals and min(vals) > best_r:
                    best_r = min(vals)
                    best_desc = f"{product} {feat}[t] -> spread[t+{lag}]"
                    best_corrs = corrs
                if vals and min(vals) >= 0.85:
                    desc = f"{product} {feat}[t] -> spread[t+{lag}]"
                    record(3, desc, corrs, "Spread prediction -> narrow spread timing")
                    print(f"  *** |r|>0.85: {desc}")
                    for d, v in corrs.items():
                        print(f"      {d}: {v:.6f}")

        # Also: abs(dmid) -> spread narrowing
        for lag in [1, 2, 5]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                x = np.abs(df['dmid'].values)
                y = (df['spread'] < 10).astype(float).values  # binary: narrow spread
                if lag < len(x):
                    r = safe_corr(x[:-lag], y[lag:])
                    corrs[day_name] = r
            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) >= 0.85:
                desc = f"{product} |dmid|[t] -> narrow_spread[t+{lag}]"
                record(3, desc, corrs, "Directly actionable: time aggressive takes")
                print(f"  *** |r|>0.85: {desc}")

    if best_desc:
        print(f"\n  Best H3: {best_desc} (min |r| = {best_r:.6f})")
        record(3, f"BEST: {best_desc}", best_corrs, "Best of H3")


def test_h4_composite_score(data):
    """H4: Multivariate composite score"""
    print("\n" + "="*80)
    print("HYPOTHESIS 4: Composite feature SCORE (multivariate regression fitted values)")
    print("="*80)

    best_r = 0
    best_desc = ""
    best_corrs = {}

    feat_names = ['obi_total', 'obi_l1', 'mp_dev', 'gap_asym', 'vol_imb_dw']

    # Test various targets
    targets_desc = {
        'dmid': 'dmid(t+1)',
        'dbid': 'dbid(t+1)',
        'dask': 'dask(t+1)',
    }

    for product in ['TOMATOES']:
        for target_col, target_name in targets_desc.items():
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product].dropna(subset=feat_names + [target_col])
                X = df[feat_names].values
                y = df[target_col].shift(-1).values[:-1]
                X = X[:-1]

                mask = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
                X, y = X[mask], y[mask]

                if len(y) < 50:
                    continue

                # OLS fit
                X_aug = np.column_stack([X, np.ones(len(X))])
                try:
                    beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
                    yhat = X_aug @ beta
                    r = np.corrcoef(yhat, y)[0, 1]
                    corrs[day_name] = r
                except:
                    corrs[day_name] = np.nan

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} OLS({','.join(feat_names)}) -> {target_name}"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} OLS({','.join(feat_names)}) -> {target_name}"
                record(4, desc, corrs, "R = sqrt(R^2) of fitted model")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

        # Kitchen sink: more features + smoothed targets
        all_feats = ['obi_total', 'obi_l1', 'obi_l2', 'mp_dev', 'gap_asym', 'vol_imb_dw',
                      'bid_vol_1', 'ask_vol_1', 'spread', 'l2l1_bid', 'l2l1_ask']

        for alpha in [0.01, 0.05, 0.1, 0.2]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product].copy()
                df['ema_mid'] = df['mid_price'].ewm(alpha=alpha, adjust=False).mean()
                df['d_ema_mid'] = df['ema_mid'].diff()

                valid_feats = [f for f in all_feats if f in df.columns]
                df_clean = df.dropna(subset=valid_feats + ['d_ema_mid'])

                X = df_clean[valid_feats].values
                y = df_clean['d_ema_mid'].shift(-1).values[:-1]
                X = X[:-1]

                mask = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
                X, y = X[mask], y[mask]

                if len(y) < 50:
                    continue

                X_aug = np.column_stack([X, np.ones(len(X))])
                try:
                    beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
                    yhat = X_aug @ beta
                    r = np.corrcoef(yhat, y)[0, 1]
                    corrs[day_name] = r
                except:
                    corrs[day_name] = np.nan

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} kitchen_sink -> d_EMA(mid,a={alpha})[t+1]"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} kitchen_sink -> d_EMA(mid,a={alpha})[t+1]"
                record(4, desc, corrs, "Overfitting risk - check OOS")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

        # What about fitting features to SMOOTHED mid TARGET directly (not change)?
        for alpha in [0.001, 0.005, 0.01]:
            for lag in [10, 20, 50]:
                corrs = {}
                for day_name, day_data in data.items():
                    df = day_data[product].copy()
                    ema_mid = df['mid_price'].ewm(alpha=alpha, adjust=False).mean().values

                    valid_feats = [f for f in all_feats if f in df.columns]
                    X = df[valid_feats].values

                    if lag >= len(X):
                        continue

                    y = ema_mid[lag:]
                    X = X[:-lag]

                    mask = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
                    X, y = X[mask], y[mask]

                    if len(y) < 50:
                        continue

                    X_aug = np.column_stack([X, np.ones(len(X))])
                    try:
                        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
                        yhat = X_aug @ beta
                        r = np.corrcoef(yhat, y)[0, 1]
                        corrs[day_name] = r
                    except:
                        corrs[day_name] = np.nan

                vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
                if vals and min(vals) > best_r:
                    best_r = min(vals)
                    best_desc = f"{product} kitchen_sink -> EMA(mid,a={alpha})[t+{lag}]"
                    best_corrs = corrs
                if vals and min(vals) >= 0.85:
                    desc = f"{product} kitchen_sink -> EMA(mid,a={alpha})[t+{lag}]"
                    record(4, desc, corrs, "Level prediction via regression")
                    print(f"  *** |r|>0.85: {desc}")
                    for d, v in corrs.items():
                        print(f"      {d}: {v:.6f}")

    if best_desc:
        print(f"\n  Best H4: {best_desc} (min |r| = {best_r:.6f})")
        record(4, f"BEST: {best_desc}", best_corrs, "Best of H4")


def test_h5_volume_prediction(data):
    """H5: Volume autocorrelation"""
    print("\n" + "="*80)
    print("HYPOTHESIS 5: Volume prediction (autocorrelation of volumes)")
    print("="*80)

    vol_feats = ['bid_vol_1', 'ask_vol_1', 'bid_vol_2', 'ask_vol_2',
                  'total_bid_vol', 'total_ask_vol']

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES', 'EMERALDS']:
        for feat in vol_feats:
            for lag in [1, 2, 5]:
                corrs = {}
                for day_name, day_data in data.items():
                    df = day_data[product]
                    x = df[feat].values
                    if lag < len(x):
                        r = safe_corr(x[:-lag], x[lag:])
                        corrs[day_name] = r

                vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
                if vals and min(vals) > best_r:
                    best_r = min(vals)
                    best_desc = f"{product} {feat}[t] -> {feat}[t+{lag}]"
                    best_corrs = corrs
                if vals and min(vals) >= 0.85:
                    desc = f"{product} {feat}[t] -> {feat}[t+{lag}]"
                    record(5, desc, corrs, "Volume persistence - useful for sizing/fill prediction")
                    print(f"  *** |r|>0.85: {desc}")
                    for d, v in corrs.items():
                        print(f"      {d}: {v:.6f}")

        # Cross-level: L1 -> L2
        for lag in [0, 1]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                x = df['bid_vol_1'].values
                y = df['bid_vol_2'].values
                if lag == 0:
                    r = safe_corr(x, y)
                else:
                    r = safe_corr(x[:-lag], y[lag:])
                corrs[day_name] = r
            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} bid_vol_1[t] -> bid_vol_2[t+{lag}]"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} bid_vol_1[t] -> bid_vol_2[t+{lag}]"
                record(5, desc, corrs, "L1->L2 vol relationship")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

    if best_desc:
        print(f"\n  Best H5: {best_desc} (min |r| = {best_r:.6f})")
        record(5, f"BEST: {best_desc}", best_corrs, "Best of H5")


def test_h6_volume_next_tick(data):
    """H6: Predict bid/ask volume at next tick"""
    print("\n" + "="*80)
    print("HYPOTHESIS 6: Predicting bid/ask VOLUME at next tick")
    print("="*80)
    # Covered by H5 lag=1, but also test cross (bid vol -> ask vol etc)

    pairs = [
        ('bid_vol_1', 'ask_vol_1'),
        ('ask_vol_1', 'bid_vol_1'),
        ('total_bid_vol', 'total_ask_vol'),
        ('bid_vol_1', 'total_bid_vol'),
        ('obi_total', 'bid_vol_1'),
        ('obi_total', 'ask_vol_1'),
    ]

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES', 'EMERALDS']:
        for feat, target in pairs:
            for lag in [1, 2]:
                corrs = {}
                for day_name, day_data in data.items():
                    df = day_data[product]
                    x = df[feat].values
                    y = df[target].values
                    if lag < len(x):
                        r = safe_corr(x[:-lag], y[lag:])
                        corrs[day_name] = r

                vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
                if vals and min(vals) > best_r:
                    best_r = min(vals)
                    best_desc = f"{product} {feat}[t] -> {target}[t+{lag}]"
                    best_corrs = corrs
                if vals and min(vals) >= 0.85:
                    desc = f"{product} {feat}[t] -> {target}[t+{lag}]"
                    record(6, desc, corrs, "Cross-volume prediction")
                    print(f"  *** |r|>0.85: {desc}")
                    for d, v in corrs.items():
                        print(f"      {d}: {v:.6f}")

    if best_desc:
        print(f"\n  Best H6: {best_desc} (min |r| = {best_r:.6f})")
        record(6, f"BEST: {best_desc}", best_corrs, "Best of H6")


def test_h7_conditional(data):
    """H7: Filtered/conditional correlation (only when price moves)"""
    print("\n" + "="*80)
    print("HYPOTHESIS 7: FILTERED/CONDITIONAL correlation (price moves, narrow spread)")
    print("="*80)

    features = ['obi_total', 'obi_l1', 'mp_dev', 'gap_asym', 'vol_imb_dw', 'microprice']

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES']:
        for feat in features:
            # Filter: only ticks where dmid != 0
            corrs_move = {}
            for day_name, day_data in data.items():
                df = day_data[product].copy()
                df['dmid_next'] = df['dmid'].shift(-1)
                df_filt = df[df['dmid_next'] != 0].dropna(subset=[feat, 'dmid_next'])

                if len(df_filt) > 30:
                    r = safe_corr(df_filt[feat].values, df_filt['dmid_next'].values)
                    corrs_move[day_name] = r

            vals = [abs(v) for v in corrs_move.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} {feat}[t] -> dmid[t+1] | dmid!=0"
                best_corrs = corrs_move
            if vals and min(vals) >= 0.85:
                desc = f"{product} {feat}[t] -> dmid[t+1] | dmid!=0"
                record(7, desc, corrs_move, "HIGHLY ACTIONABLE if stable - only trade when price moves")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs_move.items():
                    print(f"      {d}: {v:.6f}")

            # Filter: narrow spread ticks
            corrs_narrow = {}
            for day_name, day_data in data.items():
                df = day_data[product].copy()
                df['dmid_next'] = df['dmid'].shift(-1)
                df_filt = df[df['spread'] < 10].dropna(subset=[feat, 'dmid_next'])

                if len(df_filt) > 30:
                    r = safe_corr(df_filt[feat].values, df_filt['dmid_next'].values)
                    corrs_narrow[day_name] = r

            vals = [abs(v) for v in corrs_narrow.values() if np.isfinite(v)]
            if vals and min(vals) >= 0.85:
                desc = f"{product} {feat}[t] -> dmid[t+1] | spread<10"
                record(7, desc, corrs_narrow, "Narrow spread conditional - VERY actionable")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs_narrow.items():
                    print(f"      {d}: {v:.6f}")

        # What about: on ticks where price will move, predict DIRECTION?
        # This is sign(dmid_next) when dmid_next != 0
        for feat in features:
            corrs_dir = {}
            for day_name, day_data in data.items():
                df = day_data[product].copy()
                df['dmid_next'] = df['dmid'].shift(-1)
                df_filt = df[df['dmid_next'] != 0].dropna(subset=[feat, 'dmid_next'])

                if len(df_filt) > 30:
                    r = safe_corr(df_filt[feat].values, np.sign(df_filt['dmid_next'].values))
                    corrs_dir[day_name] = r

            vals = [abs(v) for v in corrs_dir.values() if np.isfinite(v)]
            if vals and min(vals) >= 0.85:
                desc = f"{product} {feat}[t] -> sign(dmid[t+1]) | dmid!=0"
                record(7, desc, corrs_dir, "Direction prediction conditional - EXTREMELY actionable")
                print(f"  *** |r|>0.85: {desc}")

    if best_desc:
        print(f"\n  Best H7: {best_desc} (min |r| = {best_r:.6f})")
        record(7, f"BEST: {best_desc}", best_corrs, "Best of H7")


def test_h8_mm_mid_prediction(data):
    """H8: Predicting MM bot's next mid"""
    print("\n" + "="*80)
    print("HYPOTHESIS 8: Predicting MM bot's NEXT mid (mean reversion from reference)")
    print("="*80)

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES']:
        # mid deviation from rolling mean -> dmid
        for window in [10, 20, 50, 100, 200, 500]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product].copy()
                df['mid_dev'] = df['mid_price'] - df['mid_price'].rolling(window).mean()
                df['dmid_next'] = df['dmid'].shift(-1)
                df_clean = df.dropna(subset=['mid_dev', 'dmid_next'])

                if len(df_clean) > 30:
                    r = safe_corr(df_clean['mid_dev'].values, df_clean['dmid_next'].values)
                    corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} mid_dev(w={window})[t] -> dmid[t+1]"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} mid_dev(w={window})[t] -> dmid[t+1]"
                record(8, desc, corrs, "Mean reversion prediction")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

        # mid deviation -> SMOOTHED future dmid
        for window in [50, 100, 200]:
            for alpha in [0.01, 0.05, 0.1]:
                corrs = {}
                for day_name, day_data in data.items():
                    df = day_data[product].copy()
                    df['mid_dev'] = df['mid_price'] - df['mid_price'].rolling(window).mean()
                    df['ema_dmid'] = df['dmid'].ewm(alpha=alpha, adjust=False).mean()

                    for lag in [1, 5, 10]:
                        df_clean = df.dropna(subset=['mid_dev'])
                        x = df_clean['mid_dev'].values
                        y = df_clean['ema_dmid'].values
                        if lag < len(x):
                            r = safe_corr(x[:-lag], y[lag:])
                            corrs[f"{day_name}_lag{lag}"] = r

                for lag in [1, 5, 10]:
                    lag_corrs = {d: corrs.get(f"{d}_lag{lag}", np.nan) for d in data.keys()}
                    vals = [abs(v) for v in lag_corrs.values() if np.isfinite(v)]
                    if vals and min(vals) > best_r:
                        best_r = min(vals)
                        best_desc = f"{product} mid_dev(w={window})[t] -> EMA(dmid,a={alpha})[t+{lag}]"
                        best_corrs = lag_corrs
                    if vals and min(vals) >= 0.85:
                        desc = f"{product} mid_dev(w={window})[t] -> EMA(dmid,a={alpha})[t+{lag}]"
                        record(8, desc, lag_corrs, "Smoothed mean reversion")
                        print(f"  *** |r|>0.85: {desc}")

        # Cumulative dmid (= mid level path) prediction via EMA
        for alpha in [0.005, 0.01, 0.02, 0.05]:
            for lag in [1, 5, 10, 20]:
                corrs = {}
                for day_name, day_data in data.items():
                    df = day_data[product].copy()
                    ema_mid = df['mid_price'].ewm(alpha=alpha, adjust=False).mean().values
                    mid = df['mid_price'].values
                    if lag < len(mid):
                        r = safe_corr(ema_mid[:-lag], mid[lag:])
                        corrs[day_name] = r

                vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
                if vals and min(vals) > best_r:
                    best_r = min(vals)
                    best_desc = f"{product} EMA(mid,a={alpha})[t] -> mid[t+{lag}]"
                    best_corrs = corrs
                if vals and min(vals) >= 0.85:
                    desc = f"{product} EMA(mid,a={alpha})[t] -> mid[t+{lag}]"
                    record(8, desc, corrs, "EMA->level prediction (includes trivial level persistence)")
                    print(f"  *** |r|>0.85: {desc}")
                    for d, v in corrs.items():
                        print(f"      {d}: {v:.6f}")

    if best_desc:
        print(f"\n  Best H8: {best_desc} (min |r| = {best_r:.6f})")
        record(8, f"BEST: {best_desc}", best_corrs, "Best of H8")


def test_h9_deviation_from_reference(data):
    """H9: Deviation from reference level"""
    print("\n" + "="*80)
    print("HYPOTHESIS 9: Deviation from reference level predictions")
    print("="*80)

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES', 'EMERALDS']:
        ref_val = 5000 if product == 'TOMATOES' else 10000

        # mid - reference -> future mid change
        corrs = {}
        for day_name, day_data in data.items():
            df = day_data[product]
            x = df['mid_price'].values - ref_val
            y = df['dmid'].values
            for lag in [1, 5, 10, 20]:
                if lag < len(x):
                    r = safe_corr(x[:-lag], y[lag:])
                    corrs[f"{day_name}_lag{lag}"] = r

        for lag in [1, 5, 10, 20]:
            lag_corrs = {d: corrs.get(f"{d}_lag{lag}", np.nan) for d in data.keys()}
            vals = [abs(v) for v in lag_corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} (mid-{ref_val})[t] -> dmid[t+{lag}]"
                best_corrs = lag_corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} (mid-{ref_val})[t] -> dmid[t+{lag}]"
                record(9, desc, lag_corrs, "Mean reversion to fair value")
                print(f"  *** |r|>0.85: {desc}")

        # mid - VWAP
        for window in [20, 50, 100]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product].copy()
                df['vwap'] = (df['mid_price'] * (df['bid_vol_1'] + df['ask_vol_1'])).rolling(window).sum() / (df['bid_vol_1'] + df['ask_vol_1']).rolling(window).sum()
                df['mid_vwap_dev'] = df['mid_price'] - df['vwap']
                df['dmid_next'] = df['dmid'].shift(-1)
                df_clean = df.dropna(subset=['mid_vwap_dev', 'dmid_next'])

                r = safe_corr(df_clean['mid_vwap_dev'].values, df_clean['dmid_next'].values)
                corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} (mid-VWAP{window})[t] -> dmid[t+1]"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} (mid-VWAP{window})[t] -> dmid[t+1]"
                record(9, desc, corrs, "VWAP deviation mean reversion")
                print(f"  *** |r|>0.85: {desc}")

        # Fractional part: mid - floor(mid)
        corrs = {}
        for day_name, day_data in data.items():
            df = day_data[product].copy()
            df['frac_mid'] = df['mid_price'] - np.floor(df['mid_price'])
            df['dmid_next'] = df['dmid'].shift(-1)
            df_clean = df.dropna(subset=['frac_mid', 'dmid_next'])
            r = safe_corr(df_clean['frac_mid'].values, df_clean['dmid_next'].values)
            corrs[day_name] = r

        vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
        if vals and min(vals) > best_r:
            best_r = min(vals)
            best_desc = f"{product} frac(mid)[t] -> dmid[t+1]"
            best_corrs = corrs
        if vals and min(vals) >= 0.85:
            desc = f"{product} frac(mid)[t] -> dmid[t+1]"
            record(9, desc, corrs, "Fractional mid reversion")
            print(f"  *** |r|>0.85: {desc}")

    if best_desc:
        print(f"\n  Best H9: {best_desc} (min |r| = {best_r:.6f})")
        record(9, f"BEST: {best_desc}", best_corrs, "Best of H9")


def test_h10_cross_product(data):
    """H10: Cross-product correlations"""
    print("\n" + "="*80)
    print("HYPOTHESIS 10: CROSS-PRODUCT predictions")
    print("="*80)

    best_r = 0
    best_desc = ""
    best_corrs = {}

    feats_em = ['mid_price', 'dmid', 'obi_total', 'spread', 'microprice']
    targets_tom = ['dmid', 'mid_price', 'spread']

    for feat_em in feats_em:
        for target_tom in targets_tom:
            for lag in [0, 1, 2, 5]:
                corrs = {}
                for day_name, day_data in data.items():
                    tom = day_data['TOMATOES']
                    em = day_data['EMERALDS']

                    # Align on timestamp
                    merged = pd.merge(
                        tom[['timestamp', target_tom]].rename(columns={target_tom: 'tom_target'}),
                        em[['timestamp', feat_em]].rename(columns={feat_em: 'em_feat'}),
                        on='timestamp'
                    )

                    if len(merged) < 30:
                        continue

                    x = merged['em_feat'].values
                    y = merged['tom_target'].values

                    if lag > 0 and lag < len(x):
                        r = safe_corr(x[:-lag], y[lag:])
                    elif lag == 0:
                        r = safe_corr(x, y)
                    else:
                        r = np.nan
                    corrs[day_name] = r

                vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
                if vals and min(vals) > best_r:
                    best_r = min(vals)
                    best_desc = f"EMERALDS {feat_em}[t] -> TOMATOES {target_tom}[t+{lag}]"
                    best_corrs = corrs
                if vals and min(vals) >= 0.85:
                    desc = f"EMERALDS {feat_em}[t] -> TOMATOES {target_tom}[t+{lag}]"
                    record(10, desc, corrs, "Cross-product signal")
                    print(f"  *** |r|>0.85: {desc}")
                    for d, v in corrs.items():
                        print(f"      {d}: {v:.6f}")

    # Cumulative cross: cumsum of EMERALDS dmid vs cumsum of TOMATOES dmid
    corrs = {}
    for day_name, day_data in data.items():
        tom = day_data['TOMATOES']
        em = day_data['EMERALDS']
        merged = pd.merge(
            tom[['timestamp', 'mid_price']].rename(columns={'mid_price': 'tom_mid'}),
            em[['timestamp', 'mid_price']].rename(columns={'mid_price': 'em_mid'}),
            on='timestamp'
        )
        if len(merged) > 30:
            r = safe_corr(merged['em_mid'].values, merged['tom_mid'].values)
            corrs[day_name] = r

    vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
    if vals and min(vals) > best_r:
        best_r = min(vals)
        best_desc = "EMERALDS mid_price vs TOMATOES mid_price (levels)"
        best_corrs = corrs
    if vals and min(vals) >= 0.85:
        desc = "EMERALDS mid_price vs TOMATOES mid_price (levels)"
        record(10, desc, corrs, "Level correlation (trivially high?)")
        print(f"  *** |r|>0.85: {desc}")
        for d, v in corrs.items():
            print(f"      {d}: {v:.6f}")

    if best_desc:
        print(f"\n  Best H10: {best_desc} (min |r| = {best_r:.6f})")
        record(10, f"BEST: {best_desc}", best_corrs, "Best of H10")


def test_h11_vol_clustering(data):
    """H11: Volatility clustering / absolute/squared changes"""
    print("\n" + "="*80)
    print("HYPOTHESIS 11: Volatility clustering (|dmid|, dmid^2, rolling_std)")
    print("="*80)

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES']:
        # |dmid| autocorrelation at various lags
        for lag in [1, 2, 5, 10]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                x = np.abs(df['dmid'].values)
                if lag < len(x):
                    r = safe_corr(x[:-lag], x[lag:])
                    corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} |dmid|[t] -> |dmid|[t+{lag}]"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} |dmid|[t] -> |dmid|[t+{lag}]"
                record(11, desc, corrs, "Vol clustering")
                print(f"  *** |r|>0.85: {desc}")

        # Rolling std -> future rolling std
        for window in [10, 20, 50]:
            for lag in [1, 5, 10, 20]:
                corrs = {}
                for day_name, day_data in data.items():
                    df = day_data[product].copy()
                    rs = df['dmid'].rolling(window).std().values
                    if lag < len(rs):
                        r = safe_corr(rs[:-lag], rs[lag:])
                        corrs[day_name] = r

                vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
                if vals and min(vals) > best_r:
                    best_r = min(vals)
                    best_desc = f"{product} roll_std(dmid,{window})[t] -> roll_std(dmid,{window})[t+{lag}]"
                    best_corrs = corrs
                if vals and min(vals) >= 0.85:
                    desc = f"{product} roll_std(dmid,{window})[t] -> roll_std(dmid,{window})[t+{lag}]"
                    record(11, desc, corrs, "Smoothed vol clustering - useful for regime detection")
                    print(f"  *** |r|>0.85: {desc}")
                    for d, v in corrs.items():
                        print(f"      {d}: {v:.6f}")

    if best_desc:
        print(f"\n  Best H11: {best_desc} (min |r| = {best_r:.6f})")
        record(11, f"BEST: {best_desc}", best_corrs, "Best of H11")


def test_h12_trade_prediction(data):
    """H12: Predict trade occurrence"""
    print("\n" + "="*80)
    print("HYPOTHESIS 12: Predict TRADE occurrence (point-biserial)")
    print("="*80)

    features = ['obi_total', 'obi_l1', 'mp_dev', 'gap_asym', 'spread', 'dmid',
                 'bid_vol_1', 'ask_vol_1', 'vol_imb_dw']

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES']:
        for feat in features:
            for lag in [1, 2, 5]:
                corrs = {}
                for day_name, day_data in data.items():
                    df = day_data[product]
                    x = df[feat].values
                    y = df['trade_occurred'].values
                    if lag < len(x):
                        r = safe_corr(x[:-lag], y[lag:].astype(float))
                        corrs[day_name] = r

                vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
                if vals and min(vals) > best_r:
                    best_r = min(vals)
                    best_desc = f"{product} {feat}[t] -> trade_occurred[t+{lag}]"
                    best_corrs = corrs
                if vals and min(vals) >= 0.85:
                    desc = f"{product} {feat}[t] -> trade_occurred[t+{lag}]"
                    record(12, desc, corrs, "Trade timing prediction - ACTIONABLE")
                    print(f"  *** |r|>0.85: {desc}")

        # Trade occurrence autocorrelation
        for lag in [1, 2, 5, 10]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                x = df['trade_occurred'].values.astype(float)
                if lag < len(x):
                    r = safe_corr(x[:-lag], x[lag:])
                    corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} trade_occurred[t] -> trade_occurred[t+{lag}]"
                best_corrs = corrs

    if best_desc:
        print(f"\n  Best H12: {best_desc} (min |r| = {best_r:.6f})")
        record(12, f"BEST: {best_desc}", best_corrs, "Best of H12")


def test_h13_model_r_squared(data):
    """H13: Kitchen-sink R^2 (they might report sqrt(R^2) as 'correlation')"""
    print("\n" + "="*80)
    print("HYPOTHESIS 13: Kitchen-sink model R^2 -> 'correlation' = sqrt(R^2)")
    print("="*80)

    all_feats = ['obi_total', 'obi_l1', 'obi_l2', 'mp_dev', 'gap_asym', 'vol_imb_dw',
                  'bid_vol_1', 'ask_vol_1', 'spread', 'l2l1_bid', 'l2l1_ask',
                  'd_bid_vol_1', 'd_ask_vol_1', 'dbid', 'dask']

    # Various targets
    targets = {
        'dmid_next': lambda df: df['dmid'].shift(-1),
        'dbid_next': lambda df: df['dbid'].shift(-1),
        'dask_next': lambda df: df['dask'].shift(-1),
        'spread_next': lambda df: df['spread'].shift(-1),
        'bid_vol_1_next': lambda df: df['bid_vol_1'].shift(-1),
        'abs_dmid_next': lambda df: df['dmid'].shift(-1).abs(),
    }

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES']:
        for target_name, target_fn in targets.items():
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product].copy()
                df['target'] = target_fn(df)

                valid_feats = [f for f in all_feats if f in df.columns]
                df_clean = df.dropna(subset=valid_feats + ['target'])

                X = df_clean[valid_feats].values
                y = df_clean['target'].values

                mask = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
                X, y = X[mask], y[mask]

                if len(y) < 50:
                    continue

                X_aug = np.column_stack([X, np.ones(len(X))])
                try:
                    beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
                    yhat = X_aug @ beta
                    ss_res = np.sum((y - yhat)**2)
                    ss_tot = np.sum((y - y.mean())**2)
                    r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                    r_val = np.sqrt(max(r_sq, 0))
                    corrs[day_name] = r_val
                except:
                    corrs[day_name] = np.nan

            vals = [v for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} kitchen_sink(15 feats) -> {target_name}, sqrt(R^2)"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} kitchen_sink(15 feats) -> {target_name}, sqrt(R^2)"
                record(13, desc, corrs, "Multi-feature R^2, risk of in-sample overfit")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

    if best_desc:
        print(f"\n  Best H13: {best_desc} (min |r| = {best_r:.6f})")
        record(13, f"BEST: {best_desc}", best_corrs, "Best of H13")


def test_h14_combined_midspread(data):
    """H14: Predict combined mid+spread (= ask/bid price) at next tick"""
    print("\n" + "="*80)
    print("HYPOTHESIS 14: Predict mid + spread/2 (= ask) or mid - spread/2 (= bid)")
    print("="*80)

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES', 'EMERALDS']:
        # Construct combined targets
        for day_name, day_data in data.items():
            df = day_data[product]
            df['ask_composite'] = df['mid_price'] + df['spread'] / 2
            df['bid_composite'] = df['mid_price'] - df['spread'] / 2

        # Feature -> combined target
        features_and_targets = [
            ('ask_composite', 'ask_composite', 1),  # ask(t) -> ask(t+1)
            ('bid_composite', 'bid_composite', 1),   # bid(t) -> bid(t+1)
            ('microprice', 'ask_composite', 1),
            ('microprice', 'bid_composite', 1),
            ('mid_price', 'ask_composite', 1),
            ('mid_price', 'bid_composite', 1),
            ('spread', 'spread', 1),                  # spread autocorr
            ('spread', 'spread', 2),
            ('spread', 'spread', 5),
        ]

        for feat, target, lag in features_and_targets:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                x = df[feat].values
                y = df[target].values
                if lag < len(x):
                    r = safe_corr(x[:-lag], y[lag:])
                    corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} {feat}[t] -> {target}[t+{lag}]"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} {feat}[t] -> {target}[t+{lag}]"
                record(14, desc, corrs, "Combined mid+spread prediction (may be trivial level correlation)")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

    if best_desc:
        print(f"\n  Best H14: {best_desc} (min |r| = {best_r:.6f})")
        record(14, f"BEST: {best_desc}", best_corrs, "Best of H14")


def test_h15_rolling_coef_stability(data):
    """H15: Rolling regression coefficient stability"""
    print("\n" + "="*80)
    print("HYPOTHESIS 15: Rolling regression coefficient stability")
    print("="*80)

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES']:
        # Rolling beta of obi -> dmid
        for window in [50, 100, 200, 500]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product].copy()
                df['dmid_next'] = df['dmid'].shift(-1)
                df_clean = df.dropna(subset=['obi_total', 'dmid_next'])

                x = df_clean['obi_total'].values
                y = df_clean['dmid_next'].values

                betas = []
                for i in range(window, len(x)):
                    x_w = x[i-window:i]
                    y_w = y[i-window:i]
                    X_w = np.column_stack([x_w, np.ones(window)])
                    try:
                        b = np.linalg.lstsq(X_w, y_w, rcond=None)[0]
                        betas.append(b[0])
                    except:
                        betas.append(np.nan)

                betas = np.array(betas)
                if len(betas) > 30:
                    # Autocorrelation of betas
                    r = safe_corr(betas[:-1], betas[1:])
                    corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} rolling_beta(obi->dmid,w={window}) autocorr(1)"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} rolling_beta(obi->dmid,w={window}) autocorr(1)"
                record(15, desc, corrs, "Stable coefficient -> adaptive strategy may work")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

    if best_desc:
        print(f"\n  Best H15: {best_desc} (min |r| = {best_r:.6f})")
        record(15, f"BEST: {best_desc}", best_corrs, "Best of H15")


def test_bonus_exotic(data):
    """BONUS: Exotic ideas - cumulative features, rank correlations, etc."""
    print("\n" + "="*80)
    print("BONUS: Exotic / unconventional approaches")
    print("="*80)

    best_r = 0
    best_desc = ""
    best_corrs = {}

    for product in ['TOMATOES']:
        # 1) Cumulative OBI -> cumulative dmid (like cointegration)
        for day_name, day_data in data.items():
            df = day_data[product].copy()
            cum_obi = df['obi_total'].cumsum().values
            cum_dmid = df['dmid'].cumsum().values

            for lag in [0, 1, 5, 10]:
                if lag == 0:
                    r = safe_corr(cum_obi, cum_dmid)
                elif lag < len(cum_obi):
                    r = safe_corr(cum_obi[:-lag], cum_dmid[lag:])
                else:
                    r = np.nan

                key = f"cum_obi -> cum_dmid lag={lag}"
                if key not in best_corrs or True:
                    if not hasattr(test_bonus_exotic, 'results'):
                        test_bonus_exotic.results = {}
                    test_bonus_exotic.results.setdefault(key, {})[day_name] = r

        # 2) Rank correlation (Spearman) for features -> dmid
        from scipy.stats import spearmanr
        features = ['obi_total', 'mp_dev', 'vol_imb_dw']
        for feat in features:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product].copy()
                df['dmid_next'] = df['dmid'].shift(-1)
                df_clean = df.dropna(subset=[feat, 'dmid_next'])
                x = df_clean[feat].values
                y = df_clean['dmid_next'].values
                mask = np.isfinite(x) & np.isfinite(y)
                if mask.sum() > 30:
                    rho, _ = spearmanr(x[mask], y[mask])
                    corrs[day_name] = rho

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} Spearman({feat}, dmid[t+1])"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} Spearman({feat}, dmid[t+1])"
                record(99, desc, corrs, "Rank correlation may capture nonlinear relationship")
                print(f"  *** |r|>0.85: {desc}")

        # 3) Mid price -> future mid price (the trivial but powerful one)
        for lag in [1, 2, 5, 10, 20, 50]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                x = df['mid_price'].values
                if lag < len(x):
                    r = safe_corr(x[:-lag], x[lag:])
                    corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} mid[t] -> mid[t+{lag}] (trivial level autocorr)"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} mid[t] -> mid[t+{lag}]"
                record(99, desc, corrs, "TRIVIAL level autocorrelation - the '0.9 correlation' everyone knows")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

        # 4) microprice -> future mid (the Prosperity Fundamentals "0.9" claim?)
        for lag in [1, 2, 5, 10, 20]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                x = df['microprice'].values
                y = df['mid_price'].values
                if lag < len(x):
                    r = safe_corr(x[:-lag], y[lag:])
                    corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} microprice[t] -> mid[t+{lag}]"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} microprice[t] -> mid[t+{lag}]"
                record(99, desc, corrs, "Microprice predicts level - trivial but maybe what they mean")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

        # 5) Feature at t predicting feature at t+1 (any high autocorrelation features)
        auto_feats = ['obi_total', 'mp_dev', 'microprice', 'vol_imb_dw', 'gap_asym',
                       'l2l1_bid', 'l2l1_ask', 'obi_l1', 'obi_l2']
        for feat in auto_feats:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                x = df[feat].values
                if len(x) > 1:
                    r = safe_corr(x[:-1], x[1:])
                    corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} {feat}[t] -> {feat}[t+1] (autocorr)"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} {feat}[t] -> {feat}[t+1]"
                record(99, desc, corrs, "Feature autocorrelation")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

        # 6) OBI -> future OBI (persistence of signal = useful for trading)
        for lag in [1, 2, 5, 10]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                x = df['obi_total'].values
                if lag < len(x):
                    r = safe_corr(x[:-lag], x[lag:])
                    corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) >= 0.85:
                desc = f"{product} obi_total[t] -> obi_total[t+{lag}]"
                record(99, desc, corrs, "OBI persistence")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

        # 7) mid(t) -> microprice(t+k) (does current mid predict future microprice?)
        for lag in [1, 5, 10]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product]
                x = df['mid_price'].values
                y = df['microprice'].values
                if lag < len(x):
                    r = safe_corr(x[:-lag], y[lag:])
                    corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) >= 0.85:
                desc = f"{product} mid[t] -> microprice[t+{lag}]"
                record(99, desc, corrs, "Level persistence")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

        # 8) The REAL question: can we find a NON-TRIVIAL 0.9 correlation?
        # Non-trivial = not level->level, not smoothed->smoothed
        # What about: microprice DEVIATION from mid -> future mid CHANGE direction over N ticks?
        for n_ticks in [5, 10, 20, 50]:
            corrs = {}
            for day_name, day_data in data.items():
                df = day_data[product].copy()
                df['mp_dev'] = df['microprice'] - df['mid_price']
                df['future_ret'] = df['mid_price'].shift(-n_ticks) - df['mid_price']
                df_clean = df.dropna(subset=['mp_dev', 'future_ret'])

                r = safe_corr(df_clean['mp_dev'].values, df_clean['future_ret'].values)
                corrs[day_name] = r

            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and min(vals) > best_r:
                best_r = min(vals)
                best_desc = f"{product} mp_dev[t] -> mid_change[t:{t+n_ticks}]"
                best_corrs = corrs
            if vals and min(vals) >= 0.85:
                desc = f"{product} mp_dev[t] -> mid_change[t to t+{n_ticks}]"
                record(99, desc, corrs, "ACTIONABLE: microprice deviation -> multi-tick return")
                print(f"  *** |r|>0.85: {desc}")
                for d, v in corrs.items():
                    print(f"      {d}: {v:.6f}")

        # 9) Feature combinations: obi * spread, obi * |dmid|, etc.
        combos = [
            ('obi_spread', lambda df: df['obi_total'] * df['spread']),
            ('obi_absdmid', lambda df: df['obi_total'] * df['dmid'].abs()),
            ('mpdev_spread', lambda df: df['mp_dev'] * df['spread']),
            ('obi_mpdev', lambda df: df['obi_total'] + df['mp_dev']),
        ]
        for combo_name, combo_fn in combos:
            for target in ['dmid']:
                for lag in [1, 5]:
                    corrs = {}
                    for day_name, day_data in data.items():
                        df = day_data[product].copy()
                        df['combo'] = combo_fn(df)
                        df['target_next'] = df[target].shift(-lag)
                        df_clean = df.dropna(subset=['combo', 'target_next'])
                        r = safe_corr(df_clean['combo'].values, df_clean['target_next'].values)
                        corrs[day_name] = r

                    vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
                    if vals and min(vals) > best_r:
                        best_r = min(vals)
                        best_desc = f"{product} {combo_name}[t] -> {target}[t+{lag}]"
                        best_corrs = corrs
                    if vals and min(vals) >= 0.85:
                        desc = f"{product} {combo_name}[t] -> {target}[t+{lag}]"
                        record(99, desc, corrs, "Feature interaction")
                        print(f"  *** |r|>0.85: {desc}")

    if best_desc:
        print(f"\n  Best BONUS: {best_desc} (min |r| = {best_r:.6f})")
        record(99, f"BEST: {best_desc}", best_corrs, "Best of BONUS")


# ============================================================================
# MAIN
# ============================================================================

def main():
    start = time.time()

    print("="*80)
    print("NUCLEAR SEARCH: Finding 0.9+ predictive correlations in Prosperity 4 data")
    print("="*80)

    print("\nLoading data...")
    data = load_data()
    for day_name, day_data in data.items():
        for product, df in day_data.items():
            print(f"  {day_name} {product}: {len(df)} ticks")

    # Run all hypothesis tests
    test_h1_smoothed_target(data)
    test_h2_next_price(data)
    test_h3_spread_prediction(data)
    test_h4_composite_score(data)
    test_h5_volume_prediction(data)
    test_h6_volume_next_tick(data)
    test_h7_conditional(data)
    test_h8_mm_mid_prediction(data)
    test_h9_deviation_from_reference(data)
    test_h10_cross_product(data)
    test_h11_vol_clustering(data)
    test_h12_trade_prediction(data)
    test_h13_model_r_squared(data)
    test_h14_combined_midspread(data)
    test_h15_rolling_coef_stability(data)
    test_bonus_exotic(data)

    # ================================================================
    # SUMMARY
    # ================================================================
    print("\n" + "="*80)
    print("="*80)
    print("FINAL SUMMARY")
    print("="*80)
    print("="*80)

    # Collect all findings with |r| >= 0.85 stable across ALL days
    print("\n" + "-"*80)
    print("ALL FINDINGS WITH |r| >= 0.85 STABLE ACROSS ALL 3 DAYS:")
    print("-"*80)

    found_085 = False
    for hyp, desc, corrs, act in findings:
        if 'BEST' in desc:
            continue
        vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
        if vals and len(vals) >= 3 and min(vals) >= 0.85:
            found_085 = True
            print(f"\n  [H{hyp}] {desc}")
            for d, v in sorted(corrs.items()):
                print(f"    {d}: {v:.6f}")
            print(f"    Actionable: {act}")

    if not found_085:
        print("\n  *** NO findings with |r| >= 0.85 stable across all 3 days ***")

        # Lower threshold
        print("\n  Lowering threshold to |r| >= 0.80:")
        for hyp, desc, corrs, act in findings:
            if 'BEST' in desc:
                continue
            vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
            if vals and len(vals) >= 3 and min(vals) >= 0.80:
                print(f"\n  [H{hyp}] {desc}")
                for d, v in sorted(corrs.items()):
                    print(f"    {d}: {v:.6f}")
                print(f"    Actionable: {act}")

    # Best finding per hypothesis
    print("\n" + "-"*80)
    print("BEST FINDING PER HYPOTHESIS:")
    print("-"*80)

    best = best_per_hypothesis()
    for hyp in sorted(best.keys()):
        min_r, desc, corrs, act = best[hyp]
        print(f"\n  H{hyp}: {desc}")
        for d, v in sorted(corrs.items()):
            print(f"    {d}: {v:.6f}")
        print(f"    Min |r| across days: {min_r:.6f}")
        print(f"    Actionable: {act}")

    # Overall best
    print("\n" + "-"*80)
    print("OVERALL TOP 10 (by min |r| across days):")
    print("-"*80)

    all_scored = []
    for hyp, desc, corrs, act in findings:
        vals = [abs(v) for v in corrs.values() if np.isfinite(v)]
        if vals and len(vals) >= 3:
            all_scored.append((min(vals), hyp, desc, corrs, act))

    all_scored.sort(reverse=True)
    for i, (min_r, hyp, desc, corrs, act) in enumerate(all_scored[:10]):
        print(f"\n  #{i+1} [H{hyp}] {desc}")
        for d, v in sorted(corrs.items()):
            print(f"    {d}: {v:.6f}")
        print(f"    Min |r|: {min_r:.6f} | Actionable: {act}")

    # THE VERDICT
    print("\n" + "="*80)
    print("THE VERDICT: What is the '0.9+ correlation'?")
    print("="*80)

    max_r = all_scored[0][0] if all_scored else 0
    if max_r >= 0.9:
        print(f"\n  FOUND IT! Max stable |r| = {max_r:.6f}")
        print(f"  {all_scored[0][2]}")
    elif max_r >= 0.85:
        print(f"\n  CLOSE! Max stable |r| = {max_r:.6f}")
        print(f"  {all_scored[0][2]}")
        print(f"  This is likely what they mean by '0.9 correlation' (rounding up)")
    else:
        print(f"\n  Max stable |r| = {max_r:.6f}")
        print(f"  The '0.9 correlation' is most likely one of these:")
        print(f"  1) mid(t) -> mid(t+1) = 0.993+ (trivial level autocorrelation)")
        print(f"  2) microprice(t) -> mid(t+1) = 0.993+ (same thing with microprice)")
        print(f"  3) sqrt(R^2) of a multi-feature model (0.63 for dmid, not 0.9)")
        print(f"  4) Smoothed feature -> smoothed target (artificial inflation)")
        print(f"  5) In-sample overfit on one day (doesn't replicate across days)")

    elapsed = time.time() - start
    print(f"\n  Runtime: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
