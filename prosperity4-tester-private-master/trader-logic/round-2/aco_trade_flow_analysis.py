#!/usr/bin/env python3
"""
ACO Trade Flow Deep Analysis - Round 2
Analyzing predictive signals from trade arrivals, sizes, and directions.

Hypothesis: Can trade flow information predict future mid-price movements?
"""

import pandas as pd
import numpy as np
from scipy import stats
from scipy.stats import spearmanr, pearsonr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score, classification_report
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = "/Users/y0d046w/Desktop/prosperity4-tester-private/trader-logic/round-2/data"
DAYS = [-2, -1, 0, 1]
ACO_FV = 10000  # Known fair value for ACO

def load_data(day):
    """Load prices and trades for a given day."""
    prices = pd.read_csv(f"{DATA_DIR}/prices_round_2_day_{day}.csv", sep=';')
    trades = pd.read_csv(f"{DATA_DIR}/trades_round_2_day_{day}.csv", sep=';')

    # Filter for ACO only
    prices_aco = prices[prices['product'] == 'ASH_COATED_OSMIUM'].copy()
    trades_aco = trades[trades['symbol'] == 'ASH_COATED_OSMIUM'].copy()

    return prices_aco, trades_aco

def classify_trade_direction(trade_price, best_bid, best_ask, mid):
    """
    Classify trade as buy or sell based on price location.
    Buy = aggressor hitting the ask (trade price >= mid)
    Sell = aggressor hitting the bid (trade price < mid)
    """
    if pd.isna(best_bid) and pd.isna(best_ask):
        return np.nan
    if trade_price >= mid:
        return 1  # Buy
    else:
        return -1  # Sell

def runs_test(arrivals):
    """
    Runs test for randomness of inter-arrival times.
    H0: Inter-arrival times are randomly distributed.
    """
    if len(arrivals) < 10:
        return np.nan, np.nan

    # Convert to above/below median
    median = np.median(arrivals)
    binary = np.array([1 if x > median else 0 for x in arrivals])

    # Count runs
    runs = 1
    for i in range(1, len(binary)):
        if binary[i] != binary[i-1]:
            runs += 1

    # Expected runs and variance under H0
    n1 = np.sum(binary)
    n0 = len(binary) - n1
    if n0 == 0 or n1 == 0:
        return np.nan, np.nan

    expected_runs = 1 + (2 * n0 * n1) / (n0 + n1)
    var_runs = (2 * n0 * n1 * (2 * n0 * n1 - n0 - n1)) / ((n0 + n1)**2 * (n0 + n1 - 1))

    if var_runs <= 0:
        return np.nan, np.nan

    z_stat = (runs - expected_runs) / np.sqrt(var_runs)
    p_value = 2 * (1 - stats.norm.cdf(abs(z_stat)))

    return z_stat, p_value


print("=" * 80)
print("ACO TRADE FLOW DEEP ANALYSIS - ROUND 2")
print("=" * 80)

all_results = {}

for day in DAYS:
    print(f"\n{'='*80}")
    print(f"DAY {day}")
    print("=" * 80)

    prices, trades = load_data(day)

    # Create timestamp-indexed price lookup
    prices = prices.sort_values('timestamp').reset_index(drop=True)
    trades = trades.sort_values('timestamp').reset_index(drop=True)

    print(f"\nData shape: {len(prices)} price ticks, {len(trades)} trades")

    # =========================================================================
    # 1. TRADE ARRIVAL PATTERNS
    # =========================================================================
    print("\n" + "-" * 40)
    print("1. TRADE ARRIVAL PATTERNS")
    print("-" * 40)

    timestamps = trades['timestamp'].values
    inter_arrivals = np.diff(timestamps)

    print(f"Trade count: {len(trades)}")
    print(f"Inter-arrival stats:")
    print(f"  Mean: {np.mean(inter_arrivals):.1f} ms")
    print(f"  Median: {np.median(inter_arrivals):.1f} ms")
    print(f"  Std: {np.std(inter_arrivals):.1f} ms")
    print(f"  Min: {np.min(inter_arrivals):.1f} ms")
    print(f"  Max: {np.max(inter_arrivals):.1f} ms")

    cov = np.std(inter_arrivals) / np.mean(inter_arrivals)
    print(f"  Coefficient of Variation: {cov:.3f}")
    print(f"    (CoV=1 => exponential/Poisson, <1 => more regular, >1 => more bursty)")

    # Runs test
    z_runs, p_runs = runs_test(inter_arrivals)
    print(f"  Runs test Z-stat: {z_runs:.3f}, p-value: {p_runs:.4f}")
    if p_runs < 0.05:
        print("    => Significant clustering (rejects randomness)")
    else:
        print("    => No significant clustering detected")

    # Distribution test - exponential fit
    _, p_exp = stats.kstest(inter_arrivals, 'expon', args=(0, np.mean(inter_arrivals)))
    print(f"  K-S test vs exponential: p-value = {p_exp:.4f}")

    # =========================================================================
    # 2. TRADE SIZE ANALYSIS
    # =========================================================================
    print("\n" + "-" * 40)
    print("2. TRADE SIZE ANALYSIS")
    print("-" * 40)

    quantities = trades['quantity'].values
    print(f"Quantity distribution:")
    print(f"  Mean: {np.mean(quantities):.2f}")
    print(f"  Median: {np.median(quantities):.1f}")
    print(f"  Std: {np.std(quantities):.2f}")
    print(f"  Min: {np.min(quantities)}")
    print(f"  Max: {np.max(quantities)}")

    # Value counts
    qty_counts = pd.Series(quantities).value_counts().sort_index()
    print(f"\n  Qty frequency (top 10):")
    for q in qty_counts.head(10).index:
        pct = qty_counts[q] / len(quantities) * 100
        print(f"    qty={q}: {qty_counts[q]} ({pct:.1f}%)")

    # Test for uniformity
    unique_qtys = np.unique(quantities)
    if len(unique_qtys) > 1:
        _, p_uniform = stats.chisquare(qty_counts.values)
        print(f"\n  Chi-square test for uniformity: p-value = {p_uniform:.4f}")
        if p_uniform < 0.05:
            print("    => Distribution is NOT uniform")
        else:
            print("    => Distribution consistent with uniform")

    # =========================================================================
    # 3. TRADE DIRECTION & BOOK STATE
    # =========================================================================
    print("\n" + "-" * 40)
    print("3. TRADE DIRECTION & BOOK STATE ANALYSIS")
    print("-" * 40)

    # Merge trades with book state at trade time
    price_lookup = prices.set_index('timestamp')[['bid_price_1', 'ask_price_1', 'mid_price',
                                                   'bid_volume_1', 'ask_volume_1',
                                                   'bid_price_2', 'ask_price_2']].to_dict('index')

    trade_features = []
    for _, row in trades.iterrows():
        ts = row['timestamp']
        # Find book state at or just before trade
        available_ts = [t for t in price_lookup.keys() if t <= ts]
        if not available_ts:
            continue
        book_ts = max(available_ts)
        book = price_lookup[book_ts]

        bid = book['bid_price_1']
        ask = book['ask_price_1']
        mid = book['mid_price']

        # Skip if no valid book
        if pd.isna(mid) or mid == 0:
            continue

        # Classify direction
        direction = classify_trade_direction(row['price'], bid, ask, mid)

        # Features
        spread = ask - bid if not pd.isna(bid) and not pd.isna(ask) else np.nan
        dev_from_fv = mid - ACO_FV
        obi = 0
        if not pd.isna(book['bid_volume_1']) and not pd.isna(book['ask_volume_1']):
            total_vol = book['bid_volume_1'] + book['ask_volume_1']
            if total_vol > 0:
                obi = (book['bid_volume_1'] - book['ask_volume_1']) / total_vol

        trade_features.append({
            'timestamp': ts,
            'price': row['price'],
            'quantity': row['quantity'],
            'direction': direction,
            'bid': bid,
            'ask': ask,
            'mid': mid,
            'spread': spread,
            'dev_from_fv': dev_from_fv,
            'obi': obi,
            'bid_vol': book['bid_volume_1'],
            'ask_vol': book['ask_volume_1']
        })

    trade_df = pd.DataFrame(trade_features)

    buy_count = (trade_df['direction'] == 1).sum()
    sell_count = (trade_df['direction'] == -1).sum()
    print(f"\nTrade direction breakdown:")
    print(f"  Buys:  {buy_count} ({100*buy_count/len(trade_df):.1f}%)")
    print(f"  Sells: {sell_count} ({100*sell_count/len(trade_df):.1f}%)")

    # =========================================================================
    # 4. LARGE TRADE IMPACT ANALYSIS
    # =========================================================================
    print("\n" + "-" * 40)
    print("4. LARGE TRADE IMPACT ANALYSIS")
    print("-" * 40)

    # Create time series of mid prices
    mid_series = prices[['timestamp', 'mid_price']].dropna()
    mid_series = mid_series[mid_series['mid_price'] > 0].set_index('timestamp')['mid_price']

    large_threshold = 7
    large_trades = trade_df[trade_df['quantity'] > large_threshold].copy()
    small_trades = trade_df[trade_df['quantity'] <= large_threshold].copy()

    print(f"\nLarge trades (qty > {large_threshold}): {len(large_trades)}")
    print(f"Small trades (qty <= {large_threshold}): {len(small_trades)}")

    def compute_impact(trades_subset, mid_series, max_lag=5):
        """Compute E[delta_mid(t+k)] for k = 0..max_lag after trades."""
        impacts = {k: [] for k in range(max_lag + 1)}

        for _, trade in trades_subset.iterrows():
            ts = trade['timestamp']
            direction = trade['direction']

            # Get mid at trade time
            available_ts = [t for t in mid_series.index if t <= ts]
            if not available_ts:
                continue
            base_ts = max(available_ts)
            base_mid = mid_series.loc[base_ts]

            # Get mid at future lags
            for k in range(max_lag + 1):
                future_ts = ts + k * 100  # Assuming 100ms ticks
                future_available = [t for t in mid_series.index if t >= future_ts]
                if future_available:
                    future_mid = mid_series.loc[min(future_available)]
                    delta = (future_mid - base_mid) * direction  # Signed by trade direction
                    impacts[k].append(delta)

        return {k: (np.mean(v), np.std(v)/np.sqrt(len(v)) if len(v) > 1 else np.nan, len(v))
                for k, v in impacts.items() if len(v) > 0}

    if len(large_trades) > 10:
        large_impact = compute_impact(large_trades, mid_series)
        print(f"\nLarge trade signed impact E[delta_mid * direction] by lag:")
        for k, (mean, se, n) in large_impact.items():
            t_stat = mean / se if se > 0 else np.nan
            sig = "*" if abs(t_stat) > 1.96 else ""
            print(f"  k={k}: {mean:+.3f} (SE={se:.3f}, t={t_stat:.2f}, n={n}) {sig}")

    if len(small_trades) > 10:
        small_impact = compute_impact(small_trades, mid_series)
        print(f"\nSmall trade signed impact E[delta_mid * direction] by lag:")
        for k, (mean, se, n) in small_impact.items():
            t_stat = mean / se if se > 0 else np.nan
            sig = "*" if abs(t_stat) > 1.96 else ""
            print(f"  k={k}: {mean:+.3f} (SE={se:.3f}, t={t_stat:.2f}, n={n}) {sig}")

    # =========================================================================
    # 5. POST-TRADE DYNAMICS: MOMENTUM vs REVERSION
    # =========================================================================
    print("\n" + "-" * 40)
    print("5. POST-TRADE DYNAMICS: MOMENTUM vs REVERSION")
    print("-" * 40)

    buys = trade_df[trade_df['direction'] == 1]
    sells = trade_df[trade_df['direction'] == -1]

    def compute_raw_impact(trades_subset, mid_series, max_lag=5):
        """Compute E[delta_mid(t+k)] (unsigned) for k = 0..max_lag after trades."""
        impacts = {k: [] for k in range(max_lag + 1)}

        for _, trade in trades_subset.iterrows():
            ts = trade['timestamp']

            available_ts = [t for t in mid_series.index if t <= ts]
            if not available_ts:
                continue
            base_ts = max(available_ts)
            base_mid = mid_series.loc[base_ts]

            for k in range(max_lag + 1):
                future_ts = ts + k * 100
                future_available = [t for t in mid_series.index if t >= future_ts]
                if future_available:
                    future_mid = mid_series.loc[min(future_available)]
                    delta = future_mid - base_mid
                    impacts[k].append(delta)

        return {k: (np.mean(v), np.std(v)/np.sqrt(len(v)) if len(v) > 1 else np.nan, len(v))
                for k, v in impacts.items() if len(v) > 0}

    if len(buys) > 10:
        buy_impact = compute_raw_impact(buys, mid_series)
        print(f"\nE[delta_mid(t+k)] | buy_trade (n={len(buys)}):")
        for k, (mean, se, n) in buy_impact.items():
            t_stat = mean / se if se > 0 else np.nan
            sig = "*" if abs(t_stat) > 1.96 else ""
            print(f"  k={k}: {mean:+.4f} (SE={se:.4f}, t={t_stat:.2f}) {sig}")

    if len(sells) > 10:
        sell_impact = compute_raw_impact(sells, mid_series)
        print(f"\nE[delta_mid(t+k)] | sell_trade (n={len(sells)}):")
        for k, (mean, se, n) in sell_impact.items():
            t_stat = mean / se if se > 0 else np.nan
            sig = "*" if abs(t_stat) > 1.96 else ""
            print(f"  k={k}: {mean:+.4f} (SE={se:.4f}, t={t_stat:.2f}) {sig}")

    # Compute permanent vs transient
    if len(buys) > 10 and len(sells) > 10:
        # Permanent = impact at k=5, Transient = impact at k=0 - impact at k=5
        buy_perm = buy_impact[5][0] if 5 in buy_impact else np.nan
        buy_trans = (buy_impact[0][0] - buy_impact[5][0]) if 0 in buy_impact and 5 in buy_impact else np.nan
        sell_perm = sell_impact[5][0] if 5 in sell_impact else np.nan
        sell_trans = (sell_impact[0][0] - sell_impact[5][0]) if 0 in sell_impact and 5 in sell_impact else np.nan

        print(f"\nPermanent vs Transient Impact:")
        print(f"  Buys:  Permanent={buy_perm:+.4f}, Transient={buy_trans:+.4f}")
        print(f"  Sells: Permanent={sell_perm:+.4f}, Transient={sell_trans:+.4f}")

        # Is it momentum or reversion?
        if buy_perm > 0 and sell_perm < 0:
            print("  => MOMENTUM: trades push price in their direction")
        elif buy_perm < 0 and sell_perm > 0:
            print("  => REVERSION: price bounces back after trades")
        else:
            print("  => MIXED signal")

    # =========================================================================
    # 6. TRADE-BOOK INTERACTION
    # =========================================================================
    print("\n" + "-" * 40)
    print("6. TRADE-BOOK INTERACTION")
    print("-" * 40)

    valid_trades = trade_df.dropna(subset=['spread', 'dev_from_fv'])

    if len(valid_trades) > 10:
        spread_mean = valid_trades['spread'].mean()
        spread_at_trades = valid_trades['spread'].mean()

        # Compare to unconditional spread
        all_spreads = prices['ask_price_1'] - prices['bid_price_1']
        all_spreads = all_spreads.dropna()
        uncond_spread = all_spreads.mean()

        print(f"\nSpread at trade time vs unconditional:")
        print(f"  Spread at trades: {spread_at_trades:.2f}")
        print(f"  Unconditional spread: {uncond_spread:.2f}")
        print(f"  Difference: {spread_at_trades - uncond_spread:+.2f}")

        # Correlation: do trades occur more when spread is tight?
        # Need to sample non-trade ticks for comparison

        # Dev from FV analysis
        dev_at_trades = valid_trades['dev_from_fv'].mean()
        all_devs = prices['mid_price'] - ACO_FV
        all_devs = all_devs.dropna()
        uncond_dev = all_devs[all_devs != -ACO_FV].mean()  # Exclude zeros

        print(f"\nDev from FV at trade time vs unconditional:")
        print(f"  Dev at trades: {dev_at_trades:+.2f}")
        print(f"  Unconditional dev: {uncond_dev:+.2f}")

        # Do trades cluster when dev is extreme?
        extreme_threshold = 10
        extreme_trades = valid_trades[abs(valid_trades['dev_from_fv']) > extreme_threshold]
        print(f"\n  Trades when |dev| > {extreme_threshold}: {len(extreme_trades)} ({100*len(extreme_trades)/len(valid_trades):.1f}%)")

        all_extreme_ticks = len(all_devs[abs(all_devs) > extreme_threshold])
        pct_extreme_ticks = 100 * all_extreme_ticks / len(all_devs)
        print(f"  Ticks when |dev| > {extreme_threshold}: {all_extreme_ticks} ({pct_extreme_ticks:.1f}%)")

    # =========================================================================
    # 7. LOGISTIC REGRESSION: PREDICT TRADE DIRECTION
    # =========================================================================
    print("\n" + "-" * 40)
    print("7. LOGISTIC REGRESSION: PREDICT TRADE DIRECTION")
    print("-" * 40)

    # Prepare features
    model_df = trade_df.dropna(subset=['direction', 'obi', 'spread', 'dev_from_fv']).copy()
    model_df = model_df[model_df['direction'].isin([1, -1])]

    # Add lagged mid changes
    price_ts = prices.set_index('timestamp')['mid_price'].dropna()

    def get_recent_delta_mid(ts, lag_ticks=3):
        """Get mid change over last lag_ticks."""
        available = [t for t in price_ts.index if t <= ts]
        if len(available) < 2:
            return np.nan
        recent = sorted(available)[-min(lag_ticks+1, len(available)):]
        if len(recent) < 2:
            return np.nan
        return price_ts.loc[recent[-1]] - price_ts.loc[recent[0]]

    model_df['recent_delta_mid'] = model_df['timestamp'].apply(lambda x: get_recent_delta_mid(x, 3))

    # L1 volume asymmetry
    model_df['vol_asym'] = (model_df['bid_vol'] - model_df['ask_vol']) / (model_df['bid_vol'] + model_df['ask_vol'] + 1e-6)

    # Final features
    feature_cols = ['obi', 'spread', 'dev_from_fv', 'recent_delta_mid', 'vol_asym']
    model_df = model_df.dropna(subset=feature_cols)

    if len(model_df) < 20:
        print("  Insufficient data for logistic regression")
    else:
        X = model_df[feature_cols].values
        y = (model_df['direction'] == 1).astype(int).values  # 1 = buy, 0 = sell

        # Standardize
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # Fit model
        lr = LogisticRegression(random_state=42, max_iter=1000)
        lr.fit(X_scaled, y)

        # Predictions
        y_pred = lr.predict(X_scaled)
        y_prob = lr.predict_proba(X_scaled)[:, 1]

        acc = accuracy_score(y, y_pred)
        auc = roc_auc_score(y, y_prob) if len(np.unique(y)) > 1 else np.nan

        print(f"\n  Sample size: {len(model_df)}")
        print(f"  Accuracy: {acc:.3f}")
        print(f"  AUC: {auc:.3f}")

        print(f"\n  Feature coefficients:")
        for feat, coef in zip(feature_cols, lr.coef_[0]):
            print(f"    {feat}: {coef:+.4f}")
        print(f"    intercept: {lr.intercept_[0]:+.4f}")

        # Null hypothesis: AUC = 0.5
        # SE(AUC) ~ sqrt(p(1-p)/n) for balanced
        n_pos = np.sum(y)
        n_neg = len(y) - n_pos
        se_auc = np.sqrt((auc * (1 - auc)) / min(n_pos, n_neg))
        z_auc = (auc - 0.5) / se_auc if se_auc > 0 else np.nan
        p_auc = 2 * (1 - stats.norm.cdf(abs(z_auc)))
        print(f"\n  AUC significance test: Z={z_auc:.2f}, p={p_auc:.4f}")
        if p_auc < 0.05:
            print("    => Direction IS predictable from book state!")
        else:
            print("    => Direction NOT significantly predictable")

    # =========================================================================
    # 8. SIGNED FLOW ACCUMULATION
    # =========================================================================
    print("\n" + "-" * 40)
    print("8. SIGNED FLOW ACCUMULATION")
    print("-" * 40)

    # Compute cumulative signed flow
    valid_flow = trade_df.dropna(subset=['direction']).copy()
    valid_flow['signed_qty'] = valid_flow['quantity'] * valid_flow['direction']
    valid_flow = valid_flow.sort_values('timestamp')
    valid_flow['cum_flow'] = valid_flow['signed_qty'].cumsum()

    # Align with price ticks
    flow_by_ts = valid_flow.groupby('timestamp').agg({
        'signed_qty': 'sum',
        'cum_flow': 'last'
    }).reset_index()

    # Merge with prices
    merged = prices.merge(flow_by_ts, on='timestamp', how='left')
    merged['signed_qty'] = merged['signed_qty'].fillna(0)
    merged['cum_flow'] = merged['cum_flow'].ffill().fillna(0)
    merged = merged[merged['mid_price'] > 0].copy()

    # Compute next-tick mid
    merged['next_mid'] = merged['mid_price'].shift(-1)
    merged['delta_mid'] = merged['next_mid'] - merged['mid_price']

    # Cross-correlation: cum_flow vs next delta_mid
    valid_merged = merged.dropna(subset=['cum_flow', 'delta_mid'])

    if len(valid_merged) > 20:
        corr, p_corr = pearsonr(valid_merged['cum_flow'], valid_merged['delta_mid'])
        print(f"\nCum flow vs next-tick delta_mid:")
        print(f"  Pearson r: {corr:.4f}")
        print(f"  p-value: {p_corr:.4f}")

        # Spearman (rank-based)
        scorr, p_scorr = spearmanr(valid_merged['cum_flow'], valid_merged['delta_mid'])
        print(f"  Spearman rho: {scorr:.4f}")
        print(f"  p-value: {p_scorr:.4f}")

        # Flow this tick vs delta_mid
        corr_instant, p_instant = pearsonr(valid_merged['signed_qty'], valid_merged['delta_mid'])
        print(f"\nThis-tick signed_qty vs next-tick delta_mid:")
        print(f"  Pearson r: {corr_instant:.4f}")
        print(f"  p-value: {p_instant:.4f}")

    # =========================================================================
    # 9. QUANTITY-PRICE RELATIONSHIP
    # =========================================================================
    print("\n" + "-" * 40)
    print("9. QUANTITY-PRICE MOVEMENT RELATIONSHIP")
    print("-" * 40)

    # Does large qty predict larger subsequent moves?
    valid_qty = trade_df.copy()
    valid_qty = valid_qty[valid_qty['mid'] > 0]

    if len(valid_qty) > 20:
        # Get next-tick mid for each trade
        for _, row in valid_qty.iterrows():
            ts = row['timestamp']
            future_ts = ts + 100
            future_available = [t for t in mid_series.index if t >= future_ts]
            if future_available:
                valid_qty.loc[valid_qty['timestamp'] == ts, 'next_mid'] = mid_series.loc[min(future_available)]

        valid_qty['abs_delta_mid'] = abs(valid_qty['next_mid'] - valid_qty['mid'])
        valid_qty = valid_qty.dropna(subset=['abs_delta_mid'])

        if len(valid_qty) > 10:
            corr_qty, p_qty = pearsonr(valid_qty['quantity'], valid_qty['abs_delta_mid'])
            print(f"Correlation: qty vs |delta_mid|:")
            print(f"  Pearson r: {corr_qty:.4f}")
            print(f"  p-value: {p_qty:.4f}")

    # Store results for cross-day comparison
    all_results[day] = {
        'n_trades': len(trades),
        'inter_arrival_cov': cov,
        'buy_pct': 100 * buy_count / len(trade_df) if len(trade_df) > 0 else np.nan,
        'mean_qty': np.mean(quantities),
    }

# =========================================================================
# CROSS-DAY SUMMARY
# =========================================================================
print("\n" + "=" * 80)
print("CROSS-DAY SUMMARY")
print("=" * 80)

print("\nKey metrics by day:")
print(f"{'Day':<8} {'Trades':<10} {'IAT CoV':<12} {'Buy %':<10} {'Mean Qty':<10}")
print("-" * 50)
for day in DAYS:
    r = all_results[day]
    print(f"{day:<8} {r['n_trades']:<10} {r['inter_arrival_cov']:<12.3f} {r['buy_pct']:<10.1f} {r['mean_qty']:<10.2f}")

print("\n" + "=" * 80)
print("KEY FINDINGS SUMMARY")
print("=" * 80)
print("""
Evaluate each signal based on:
1. Statistical significance (p < 0.05)
2. Consistency across days
3. Economic magnitude (is the effect tradeable?)
4. Potential for alpha extraction

Look for:
- Trade flow predicting price moves (alpha signal)
- Large trade impact patterns (information content)
- Book state predicting trade direction (order anticipation)
- Momentum vs reversion dynamics (market microstructure)
""")
