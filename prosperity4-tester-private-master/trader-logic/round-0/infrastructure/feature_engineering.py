"""
feature_engineering.py — Systematic Feature Discovery for IMC Prosperity 4

Generates hundreds of candidate features from order book data, tests each
against future mid price returns at multiple horizons, and identifies
features with the highest predictive power.

Target: predict mid[t+h] - mid[t] for h in {1, 2, 3, 5, 10}

Run from: c:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/
Usage: python feature_engineering.py
"""

import csv
import math
import os
from collections import defaultdict, Counter
from itertools import combinations

DATA_DIR = "prosperity4bt/resources/round0"


def load_data(day):
    """Load price snapshots and trades for a given day."""
    prices = []
    fname = os.path.join(DATA_DIR, f"prices_round_0_day_{day}.csv")
    with open(fname) as f:
        for r in csv.DictReader(f, delimiter=';'):
            if r['product'] == 'TOMATOES':
                prices.append({
                    'ts': int(r['timestamp']),
                    'bid1': float(r['bid_price_1']),
                    'bv1': int(r['bid_volume_1']),
                    'bid2': float(r['bid_price_2']),
                    'bv2': int(r['bid_volume_2']),
                    'bid3': float(r['bid_price_3']) if r['bid_price_3'] else None,
                    'bv3': int(r['bid_volume_3']) if r['bid_volume_3'] else None,
                    'ask1': float(r['ask_price_1']),
                    'av1': int(r['ask_volume_1']),
                    'ask2': float(r['ask_price_2']),
                    'av2': int(r['ask_volume_2']),
                    'ask3': float(r['ask_price_3']) if r['ask_price_3'] else None,
                    'av3': int(r['ask_volume_3']) if r['ask_volume_3'] else None,
                    'mid': float(r['mid_price']),
                })

    trades_by_ts = defaultdict(list)
    fname = os.path.join(DATA_DIR, f"trades_round_0_day_{day}.csv")
    with open(fname) as f:
        for r in csv.DictReader(f, delimiter=';'):
            if r['symbol'] == 'TOMATOES':
                trades_by_ts[int(r['timestamp'])].append({
                    'price': float(r['price']),
                    'qty': int(r['quantity']),
                })

    return prices, trades_by_ts


def pearson_r(x, y):
    """Compute Pearson correlation between two lists."""
    n = len(x)
    if n < 10:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    sx = sum((xi - mx) ** 2 for xi in x)
    sy = sum((yi - my) ** 2 for yi in y)
    if sx == 0 or sy == 0:
        return 0.0
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    return sxy / math.sqrt(sx * sy)


def ols_regression(features_matrix, targets):
    """
    Simple OLS regression: y = X @ beta
    Returns beta coefficients and R-squared.
    Uses normal equations with regularization for stability.
    """
    n = len(targets)
    k = len(features_matrix[0]) if features_matrix else 0
    if n < k + 10 or k == 0:
        return None, 0.0

    # Build XtX and XtY
    XtX = [[0.0] * (k + 1) for _ in range(k + 1)]
    XtY = [0.0] * (k + 1)

    for i in range(n):
        row = [1.0] + list(features_matrix[i])  # intercept
        y = targets[i]
        for j in range(k + 1):
            XtY[j] += row[j] * y
            for l in range(k + 1):
                XtX[j][l] += row[j] * row[l]

    # Ridge regularization
    lam = 1e-6 * n
    for j in range(k + 1):
        XtX[j][j] += lam

    # Solve via Gaussian elimination
    aug = [XtX[j][:] + [XtY[j]] for j in range(k + 1)]
    m = k + 1
    for col in range(m):
        # Pivot
        max_row = max(range(col, m), key=lambda r: abs(aug[r][col]))
        aug[col], aug[max_row] = aug[max_row], aug[col]
        if abs(aug[col][col]) < 1e-12:
            return None, 0.0
        for row in range(m):
            if row == col:
                continue
            factor = aug[row][col] / aug[col][col]
            for j in range(m + 1):
                aug[row][j] -= factor * aug[col][j]

    beta = [aug[j][m] / aug[j][j] for j in range(m)]

    # Compute R-squared
    ss_res = 0.0
    ss_tot = 0.0
    mean_y = sum(targets) / n
    for i in range(n):
        row = [1.0] + list(features_matrix[i])
        pred = sum(beta[j] * row[j] for j in range(m))
        ss_res += (targets[i] - pred) ** 2
        ss_tot += (targets[i] - mean_y) ** 2

    r_sq = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return beta, r_sq


# ============================================================
# FEATURE GENERATORS
# ============================================================

def compute_all_features(prices, trades_by_ts, max_lookback=20):
    """
    Compute feature matrix. Each row is a tick, each column is a feature.
    Returns: feature_names, feature_matrix (list of lists)
    """
    n = len(prices)
    features = {}  # name -> list of values (length n)

    # ── RAW BOOK FEATURES ──
    mids = [p['mid'] for p in prices]
    bids = [p['bid1'] for p in prices]
    asks = [p['ask1'] for p in prices]
    spreads = [p['ask1'] - p['bid1'] for p in prices]
    bv1s = [p['bv1'] for p in prices]
    av1s = [p['av1'] for p in prices]
    bv2s = [p['bv2'] for p in prices]
    av2s = [p['av2'] for p in prices]

    features['spread'] = spreads
    features['bv1'] = bv1s
    features['av1'] = av1s

    # ── MICROPRICE ──
    microprices = []
    for i in range(n):
        bv = bv1s[i]
        av = av1s[i]
        if bv + av > 0:
            microprices.append(bids[i] + (bv / (bv + av)) * spreads[i])
        else:
            microprices.append(mids[i])
    features['microprice'] = microprices

    # ── MICROPRICE DEVIATION (from mid) ──
    features['mp_dev'] = [microprices[i] - mids[i] for i in range(n)]

    # ── VOLUME IMBALANCE (L1) ──
    features['vol_imb_l1'] = [
        (bv1s[i] - av1s[i]) / max(bv1s[i] + av1s[i], 1)
        for i in range(n)
    ]

    # ── VOLUME IMBALANCE (L2) ──
    features['vol_imb_l2'] = [
        (bv2s[i] - av2s[i]) / max(bv2s[i] + av2s[i], 1)
        for i in range(n)
    ]

    # ── TOTAL VOLUME IMBALANCE (L1 + L2) ──
    features['vol_imb_total'] = [
        ((bv1s[i] + bv2s[i]) - (av1s[i] + av2s[i])) /
        max(bv1s[i] + bv2s[i] + av1s[i] + av2s[i], 1)
        for i in range(n)
    ]

    # ── WEIGHTED MICROPRICE (uses L1+L2) ──
    weighted_mp = []
    for p in prices:
        total_bv = p['bv1'] + p['bv2']
        total_av = p['av1'] + p['av2']
        if total_bv + total_av > 0:
            # Volume-weighted mid using L1 and L2
            bid_vwap = (p['bid1'] * p['bv1'] + p['bid2'] * p['bv2']) / max(total_bv, 1)
            ask_vwap = (p['ask1'] * p['av1'] + p['ask2'] * p['av2']) / max(total_av, 1)
            wmp = bid_vwap + (total_bv / (total_bv + total_av)) * (ask_vwap - bid_vwap)
        else:
            wmp = p['mid']
        weighted_mp.append(wmp)
    features['weighted_mp'] = weighted_mp
    features['weighted_mp_dev'] = [weighted_mp[i] - mids[i] for i in range(n)]

    # ── SPREAD STATE ──
    features['spread_is_14'] = [1.0 if spreads[i] == 14 else 0.0 for i in range(n)]
    features['spread_is_13'] = [1.0 if spreads[i] == 13 else 0.0 for i in range(n)]
    features['spread_narrow'] = [1.0 if spreads[i] < 13 else 0.0 for i in range(n)]

    # ── BOOK PRESSURE (ratio of volumes at different levels) ──
    features['l2_l1_bid_ratio'] = [bv2s[i] / max(bv1s[i], 1) for i in range(n)]
    features['l2_l1_ask_ratio'] = [av2s[i] / max(av1s[i], 1) for i in range(n)]
    features['l2_l1_ratio_diff'] = [
        features['l2_l1_bid_ratio'][i] - features['l2_l1_ask_ratio'][i]
        for i in range(n)
    ]

    # ── PRICE GAP FEATURES ──
    features['bid_gap'] = [bids[i] - prices[i]['bid2'] for i in range(n)]
    features['ask_gap'] = [prices[i]['ask2'] - asks[i] for i in range(n)]
    features['gap_asymmetry'] = [
        features['bid_gap'][i] - features['ask_gap'][i]
        for i in range(n)
    ]

    # ── LAGGED RETURNS ──
    for lag in [1, 2, 3, 4, 5, 10]:
        ret = [0.0] * lag + [mids[i] - mids[i - lag] for i in range(lag, n)]
        features[f'ret_{lag}'] = ret

        bid_ret = [0.0] * lag + [bids[i] - bids[i - lag] for i in range(lag, n)]
        features[f'bid_ret_{lag}'] = bid_ret

        ask_ret = [0.0] * lag + [asks[i] - asks[i - lag] for i in range(lag, n)]
        features[f'ask_ret_{lag}'] = ask_ret

    # ── SPREAD CHANGE ──
    features['spread_chg_1'] = [0.0] + [spreads[i] - spreads[i-1] for i in range(1, n)]
    features['spread_chg_3'] = [0.0]*3 + [spreads[i] - spreads[i-3] for i in range(3, n)]

    # ── CUMULATIVE RETURN (momentum) ──
    for window in [3, 5, 10, 20]:
        features[f'cum_ret_{window}'] = (
            [0.0] * window +
            [mids[i] - mids[i - window] for i in range(window, n)]
        )

    # ── REALIZED VOLATILITY ──
    for window in [5, 10, 20]:
        vol = [0.0] * window
        for i in range(window, n):
            rets = [mids[j] - mids[j-1] for j in range(i - window + 1, i + 1)]
            vol.append(math.sqrt(sum(r**2 for r in rets) / window))
        features[f'rvol_{window}'] = vol

    # ── TRADE FLOW FEATURES ──
    trade_flow = [0.0] * n
    trade_count = [0.0] * n
    trade_volume = [0.0] * n
    for i in range(n):
        ts = prices[i]['ts']
        if ts in trades_by_ts:
            mid = mids[i]
            for t in trades_by_ts[ts]:
                if t['price'] >= mid:
                    trade_flow[i] += t['qty']
                else:
                    trade_flow[i] -= t['qty']
                trade_count[i] += 1
                trade_volume[i] += t['qty']

    features['trade_flow'] = trade_flow
    features['trade_count'] = trade_count
    features['trade_volume'] = trade_volume

    # Cumulative trade flow
    for window in [3, 5, 10, 20]:
        ctf = [0.0] * n
        for i in range(window, n):
            ctf[i] = sum(trade_flow[i - window + 1:i + 1])
        features[f'cum_trade_flow_{window}'] = ctf

    # ── ASYMMETRIC BID/ASK MOVEMENT ──
    # When bid moves but ask doesn't (or vice versa), this is a signal
    features['bid_only_move'] = [0.0] + [
        1.0 if (bids[i] != bids[i-1] and asks[i] == asks[i-1]) else
        (-1.0 if (bids[i] == bids[i-1] and asks[i] != asks[i-1]) else 0.0)
        for i in range(1, n)
    ]

    # ── ICT CONCEPTS ──
    # Liquidity sweep detection: price moves sharply then reverts
    # We detect this as a large |bid_ret| followed by spread narrowing
    features['sweep_up'] = [0.0] * n
    features['sweep_down'] = [0.0] * n
    for i in range(5, n):
        bid_move = bids[i] - bids[i - 5]
        if bid_move >= 4 and spreads[i] < 10:
            features['sweep_up'][i] = bid_move
        elif bid_move <= -4 and spreads[i] < 10:
            features['sweep_down'][i] = bid_move

    # Fair Value Gap: spread < typical (13) suggests recent fast move
    features['fvg_signal'] = [
        max(0, 13 - spreads[i]) for i in range(n)
    ]

    # Market Structure Shift: bid breaks above/below recent range
    for window in [10, 20, 50]:
        mss = [0.0] * n
        for i in range(window, n):
            recent_high = max(bids[j] for j in range(i - window, i))
            recent_low = min(bids[j] for j in range(i - window, i))
            if bids[i] > recent_high:
                mss[i] = 1.0
            elif bids[i] < recent_low:
                mss[i] = -1.0
        features[f'mss_{window}'] = mss

    # ── RELATIVE PRICE POSITION ──
    for window in [20, 50, 100]:
        rpp = [0.0] * n
        for i in range(window, n):
            hi = max(mids[j] for j in range(i - window, i + 1))
            lo = min(mids[j] for j in range(i - window, i + 1))
            rng = hi - lo
            if rng > 0:
                rpp[i] = (mids[i] - lo) / rng - 0.5  # centered at 0
        features[f'rel_pos_{window}'] = rpp

    # ── VOLUME LEVEL (absolute, not imbalance) ──
    features['total_l1_vol'] = [bv1s[i] + av1s[i] for i in range(n)]
    features['vol_level_zscore'] = [0.0] * n
    for i in range(20, n):
        recent_vols = [bv1s[j] + av1s[j] for j in range(i - 20, i)]
        mean_v = sum(recent_vols) / 20
        std_v = math.sqrt(sum((v - mean_v)**2 for v in recent_vols) / 20) or 1
        features['vol_level_zscore'][i] = ((bv1s[i] + av1s[i]) - mean_v) / std_v

    # ── CROSS FEATURES (interactions) ──
    # vol_imb × spread_state
    features['vol_imb_x_spread14'] = [
        features['vol_imb_l1'][i] * features['spread_is_14'][i]
        for i in range(n)
    ]

    # ret_1 × vol_imb (momentum + imbalance interaction)
    features['ret1_x_vol_imb'] = [
        features['ret_1'][i] * features['vol_imb_l1'][i]
        for i in range(n)
    ]

    # Trade flow × spread (flow matters more when spread is tight?)
    features['flow_x_spread'] = [
        trade_flow[i] * spreads[i] for i in range(n)
    ]

    # Sweep × vol_imb (directional after sweep, confirmed by imbalance)
    features['sweep_x_vol_imb'] = [
        (features['sweep_up'][i] + features['sweep_down'][i]) * features['vol_imb_l1'][i]
        for i in range(n)
    ]

    # ── NORMALIZED FEATURES (for regression stability) ──
    # Z-score the microprice deviation by recent vol
    features['mp_dev_norm'] = [0.0] * n
    for i in range(20, n):
        vol = features['rvol_10'][i]
        if vol > 0:
            features['mp_dev_norm'][i] = features['mp_dev'][i] / vol

    # ── EMA-BASED FEATURES ──
    for span in [5, 10, 20]:
        alpha = 2.0 / (span + 1)
        ema = [mids[0]]
        for i in range(1, n):
            ema.append(alpha * mids[i] + (1 - alpha) * ema[-1])
        features[f'ema_{span}_dev'] = [mids[i] - ema[i] for i in range(n)]

    # ── PRICE ACCELERATION ──
    r1 = features['ret_1']
    r2 = [0.0] + [r1[i] - r1[i-1] for i in range(1, n)]
    features['acceleration'] = r2

    return features, mids


def evaluate_features(features, mids, horizons=[1, 2, 3, 5, 10]):
    """
    Compute correlation of each feature with future returns at each horizon.
    """
    n = len(mids)
    results = {}  # (feature_name, horizon) -> correlation

    # Compute future returns
    future_rets = {}
    for h in horizons:
        future_rets[h] = [mids[i + h] - mids[i] if i + h < n else None for i in range(n)]

    for fname, fvals in features.items():
        for h in horizons:
            # Align: use features from tick max_lookback onwards
            start = 20  # skip warmup
            x = []
            y = []
            for i in range(start, n - h):
                if future_rets[h][i] is not None:
                    x.append(fvals[i])
                    y.append(future_rets[h][i])

            if len(x) > 50:
                r = pearson_r(x, y)
                results[(fname, h)] = r

    return results


def find_best_combinations(features, mids, top_features, horizon=1, max_combo=5):
    """
    Test combinations of top features to find the best multi-feature regression.
    """
    n = len(mids)
    start = 20
    target = [mids[i + horizon] - mids[i] for i in range(start, n - horizon)]

    # Build feature matrix for top features
    feat_names = list(top_features.keys())
    feat_matrix = []
    for i in range(start, n - horizon):
        row = [features[fname][i] for fname in feat_names]
        feat_matrix.append(row)

    print(f"\n  Testing combinations of {len(feat_names)} features at horizon={horizon}")

    # Test individual features first
    print(f"\n  Individual feature regressions:")
    individual_r2 = {}
    for j, fname in enumerate(feat_names):
        X = [[feat_matrix[i][j]] for i in range(len(feat_matrix))]
        beta, r2 = ols_regression(X, target)
        individual_r2[fname] = r2
        print(f"    {fname:30s}: R²={r2:.6f}, r={math.sqrt(max(0,r2)):.4f}")

    # Test all pairs
    print(f"\n  Best pairs:")
    pair_results = []
    for j1, j2 in combinations(range(len(feat_names)), 2):
        X = [[feat_matrix[i][j1], feat_matrix[i][j2]] for i in range(len(feat_matrix))]
        beta, r2 = ols_regression(X, target)
        pair_results.append((r2, feat_names[j1], feat_names[j2], beta))

    pair_results.sort(reverse=True)
    for r2, f1, f2, beta in pair_results[:10]:
        print(f"    {f1:25s} + {f2:25s}: R²={r2:.6f}, r={math.sqrt(max(0,r2)):.4f}")

    # Test all triples of top 8
    if len(feat_names) >= 3:
        print(f"\n  Best triples (from top 8):")
        triple_results = []
        top8 = list(range(min(8, len(feat_names))))
        for j1, j2, j3 in combinations(top8, 3):
            X = [[feat_matrix[i][j1], feat_matrix[i][j2], feat_matrix[i][j3]]
                 for i in range(len(feat_matrix))]
            beta, r2 = ols_regression(X, target)
            triple_results.append((r2, feat_names[j1], feat_names[j2], feat_names[j3], beta))

        triple_results.sort(reverse=True)
        for r2, f1, f2, f3, beta in triple_results[:10]:
            print(f"    {f1:20s} + {f2:20s} + {f3:20s}: R²={r2:.6f}, r={math.sqrt(max(0,r2)):.4f}")

    # Full regression with all features
    print(f"\n  Full regression ({len(feat_names)} features):")
    beta, r2 = ols_regression(feat_matrix, target)
    if beta is not None:
        print(f"    R²={r2:.6f}, r={math.sqrt(max(0,r2)):.4f}")
        print(f"    Coefficients:")
        for j, fname in enumerate(feat_names):
            print(f"      {fname:30s}: {beta[j+1]:+.6f}")
        print(f"      intercept: {beta[0]:+.6f}")

    return pair_results, triple_results if len(feat_names) >= 3 else []


def predict_multi_tick(features, mids, horizon=1):
    """
    For predicting mid[t+h], use mid[t] as baseline + feature-predicted return.
    Compute correlation of PREDICTED mid[t+h] vs ACTUAL mid[t+h].
    This is where the 0.9 correlation comes from — the baseline (mid[t]) already
    has 0.999+ correlation with mid[t+h], and features improve the residual.
    """
    n = len(mids)
    start = 20

    # Compute microprice lags
    mp = features['microprice']
    target_price = [mids[i + horizon] if i + horizon < n else None for i in range(n)]

    # Method 1: Just mid[t] predicts mid[t+h]
    x = [mids[i] for i in range(start, n - horizon)]
    y = [mids[i + horizon] for i in range(start, n - horizon)]
    r_baseline = pearson_r(x, y)

    # Method 2: Microprice predicts mid[t+h]
    x2 = [mp[i] for i in range(start, n - horizon)]
    r_mp = pearson_r(x2, y)

    # Method 3: 4-lag regression predicts mid[t+h]
    preds = []
    actuals = []
    for i in range(start, n - horizon):
        if i >= 4:
            fv = (2.208667 + 0.059694 * mp[i-3] + 0.117270 * mp[i-2] +
                  0.244154 * mp[i-1] + 0.578440 * mp[i])
            preds.append(fv)
            actuals.append(mids[i + horizon])
    r_reg = pearson_r(preds, actuals) if preds else 0

    print(f"\n  PRICE-LEVEL CORRELATION (predicting mid[t+{horizon}]):")
    print(f"    mid[t]:           r = {r_baseline:.6f}")
    print(f"    microprice[t]:    r = {r_mp:.6f}")
    print(f"    4-lag regression: r = {r_reg:.6f}")
    print(f"    (These are all near 1.0 because the price level dominates)")

    return r_baseline, r_mp, r_reg


def compute_cumulative_features(features, mids):
    """
    Build CUMULATIVE features that should have higher correlation with
    cumulative future returns. This is likely what "0.9 correlation" means:
    cumulative signal vs cumulative target.
    """
    n = len(mids)

    # Cumulative features: running sum of signal
    cum_features = {}

    for fname in ['vol_imb_l1', 'trade_flow', 'mp_dev', 'ret_1',
                   'bid_only_move', 'spread_chg_1', 'vol_imb_total',
                   'weighted_mp_dev', 'acceleration']:
        cum = [0.0] * n
        running = 0.0
        for i in range(n):
            running += features[fname][i]
            cum[i] = running
        cum_features[f'cum_{fname}'] = cum

    # Cumulative target: total return from start
    cum_return = [mids[i] - mids[0] for i in range(n)]

    print(f"\n  CUMULATIVE FEATURE vs CUMULATIVE RETURN CORRELATION:")
    for fname, fvals in cum_features.items():
        r = pearson_r(fvals[20:], cum_return[20:])
        print(f"    {fname:35s}: r = {r:+.4f}")

    return cum_features, cum_return


def main():
    for day in [-2, -1]:
        print(f"\n{'#' * 70}")
        print(f"#  DAY {day}")
        print(f"{'#' * 70}")

        prices, trades_by_ts = load_data(day)
        print(f"  Loaded {len(prices)} price ticks, {sum(len(v) for v in trades_by_ts.values())} trades")

        features, mids = compute_all_features(prices, trades_by_ts)
        print(f"  Computed {len(features)} features")

        # ── Evaluate single-feature correlations ──
        print(f"\n{'=' * 60}")
        print(f"  SINGLE FEATURE CORRELATIONS (with future mid return)")
        print(f"{'=' * 60}")

        results = evaluate_features(features, mids, horizons=[1, 2, 3, 5, 10])

        for h in [1, 2, 3, 5, 10]:
            print(f"\n  --- Horizon = {h} ticks ---")
            hr = [(fname, r) for (fname, hh), r in results.items() if hh == h]
            hr.sort(key=lambda x: abs(x[1]), reverse=True)
            for fname, r in hr[:25]:
                print(f"    {fname:35s}: r = {r:+.4f}")

        # ── Multi-feature regression ──
        print(f"\n{'=' * 60}")
        print(f"  MULTI-FEATURE REGRESSION (RETURN PREDICTION)")
        print(f"{'=' * 60}")

        # Get top features for horizon=1
        h1_results = {fname: r for (fname, h), r in results.items() if h == 1}
        top_by_abs = sorted(h1_results.items(), key=lambda x: abs(x[1]), reverse=True)
        top_features = dict(top_by_abs[:15])

        find_best_combinations(features, mids, top_features, horizon=1)

        # ── Price-level correlations (where 0.9+ comes from) ──
        print(f"\n{'=' * 60}")
        print(f"  PRICE-LEVEL PREDICTION (explaining 0.9 correlation)")
        print(f"{'=' * 60}")

        for h in [1, 5, 10]:
            predict_multi_tick(features, mids, horizon=h)

        # ── Cumulative correlations ──
        print(f"\n{'=' * 60}")
        print(f"  CUMULATIVE SIGNAL vs CUMULATIVE RETURN")
        print(f"{'=' * 60}")

        compute_cumulative_features(features, mids)

        # ── Cross-validation: train on first half, test on second ──
        print(f"\n{'=' * 60}")
        print(f"  OUT-OF-SAMPLE TEST (train first half, test second half)")
        print(f"{'=' * 60}")

        n = len(mids)
        split = n // 2
        h = 1

        # Get top features from first half only
        first_half_results = {}
        for fname, fvals in features.items():
            x = fvals[20:split]
            y = [mids[i+h] - mids[i] for i in range(20, split)]
            if len(x) == len(y) and len(x) > 50:
                r = pearson_r(x, y)
                first_half_results[fname] = r

        top_train = sorted(first_half_results.items(), key=lambda x: abs(x[1]), reverse=True)[:10]
        top_train_names = [f for f, _ in top_train]

        # Train regression on first half
        train_X = [[features[f][i] for f in top_train_names] for i in range(20, split)]
        train_Y = [mids[i+h] - mids[i] for i in range(20, split)]
        beta, train_r2 = ols_regression(train_X, train_Y)

        if beta is not None:
            # Test on second half
            test_X = [[features[f][i] for f in top_train_names] for i in range(split, n - h)]
            test_Y = [mids[i+h] - mids[i] for i in range(split, n - h)]

            preds = []
            for row in test_X:
                pred = beta[0] + sum(beta[j+1] * row[j] for j in range(len(row)))
                preds.append(pred)

            test_r = pearson_r(preds, test_Y)
            test_r2 = test_r ** 2

            print(f"  Train R²: {train_r2:.6f} (r={math.sqrt(max(0,train_r2)):.4f})")
            print(f"  Test  R²: {test_r2:.6f} (r={test_r:.4f})")
            print(f"  Features used: {top_train_names}")
            print(f"  Coefficients:")
            for j, fname in enumerate(top_train_names):
                print(f"    {fname:30s}: {beta[j+1]:+.6f}")

            # Simulated PnL on test set
            pnl = 0
            correct = 0
            total_signals = 0
            for i, (pred, actual) in enumerate(zip(preds, test_Y)):
                if abs(pred) > 0.1:  # only trade on strong signals
                    total_signals += 1
                    if (pred > 0 and actual > 0) or (pred < 0 and actual < 0):
                        correct += 1
                    pnl += pred * actual / abs(pred)  # normalize

            if total_signals > 0:
                print(f"\n  Simulated (test set):")
                print(f"    Signals: {total_signals}")
                print(f"    Hit rate: {100*correct/total_signals:.1f}%")
                print(f"    Direction PnL: {pnl:.1f}")

    print(f"\n{'#' * 70}")
    print(f"#  DONE — Use the best features in your strategy")
    print(f"{'#' * 70}")


if __name__ == "__main__":
    main()
