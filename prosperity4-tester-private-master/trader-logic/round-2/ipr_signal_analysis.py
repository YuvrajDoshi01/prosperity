#!/usr/bin/env python3
"""
Comprehensive IPR Signal Analysis for IMC Prosperity 4, Round 2.

Examines every plausible trading signal for INTARIAN_PEPPER_ROOT and computes:
- Information Coefficient (IC = Spearman correlation with future mid return)
- Multi-horizon IC (1, 5, 10, 50, 100 ticks)
- Directional accuracy

Run: python trader-logic/round-2/ipr_signal_analysis.py
"""

import os
import sys
import warnings
import numpy as np
import pandas as pd
from scipy import stats
from collections import defaultdict

warnings.filterwarnings("ignore")

BASE = os.path.dirname(os.path.abspath(__file__))
RESOURCE_DIR = os.path.join(BASE, "..", "..", "prosperity4bt", "resources", "round2")

DAYS = [-1, 0, 1]
HORIZONS = [1, 5, 10, 50, 100]
PRODUCT = "INTARIAN_PEPPER_ROOT"
ACO_PRODUCT = "ASH_COATED_OSMIUM"


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

def load_prices(day):
    path = os.path.join(RESOURCE_DIR, f"prices_round_2_day_{day}.csv")
    df = pd.read_csv(path, sep=";")
    return df


def load_trades(day):
    path = os.path.join(RESOURCE_DIR, f"trades_round_2_day_{day}.csv")
    df = pd.read_csv(path, sep=";")
    return df


def build_book_df(prices_df, product):
    """Extract per-tick book snapshots for a given product."""
    pdf = prices_df[prices_df["product"] == product].copy()
    pdf = pdf.sort_values("timestamp").reset_index(drop=True)

    # Parse levels
    for side in ["bid", "ask"]:
        for lvl in [1, 2, 3]:
            pcol = f"{side}_price_{lvl}"
            vcol = f"{side}_volume_{lvl}"
            pdf[pcol] = pd.to_numeric(pdf[pcol], errors="coerce")
            pdf[vcol] = pd.to_numeric(pdf[vcol], errors="coerce")

    # Compute mid from L1 when available
    pdf["best_bid"] = pdf["bid_price_1"]
    pdf["best_ask"] = pdf["ask_price_1"]
    pdf["mid"] = pdf["mid_price"]
    pdf["spread"] = pdf["best_ask"] - pdf["best_bid"]

    # Bid/ask volumes at L1
    pdf["bid_vol_1"] = pdf["bid_volume_1"].fillna(0)
    pdf["ask_vol_1"] = pdf["ask_volume_1"].abs().fillna(0)  # ask vols are negative in raw
    # Actually in the CSV they appear positive, let's check
    pdf["bid_vol_2"] = pdf["bid_volume_2"].fillna(0)
    pdf["ask_vol_2"] = pdf["ask_volume_2"].abs().fillna(0)
    pdf["bid_vol_3"] = pdf["bid_volume_3"].fillna(0)
    pdf["ask_vol_3"] = pdf["ask_volume_3"].abs().fillna(0)

    return pdf


def build_trade_df(trades_df, product):
    """Extract trades for a given product."""
    tdf = trades_df[trades_df["symbol"] == product].copy()
    tdf = tdf.sort_values("timestamp").reset_index(drop=True)
    tdf["price"] = pd.to_numeric(tdf["price"], errors="coerce")
    tdf["quantity"] = pd.to_numeric(tdf["quantity"], errors="coerce")
    return tdf


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL COMPUTATION
# ══════════════════════════════════════════════════════════════════════════════

def rolling_slope(series, window):
    """Rolling OLS slope over a fixed window."""
    s = np.full(len(series), np.nan)
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    x_var = np.sum((x - x_mean)**2)
    for i in range(window - 1, len(series)):
        y = series[i - window + 1:i + 1]
        if np.any(np.isnan(y)):
            continue
        y_mean = np.mean(y)
        s[i] = np.sum((x - x_mean) * (y - y_mean)) / x_var
    return s


def compute_signals(ipr_book, ipr_trades, aco_book):
    """Compute all signals. Returns DataFrame aligned with ipr_book index."""
    df = ipr_book.copy()
    n = len(df)

    signals = pd.DataFrame(index=df.index)

    # ── Mid returns at multiple horizons ─────────────────────────────────────
    mid = df["mid"].values.astype(float)
    for h in HORIZONS:
        fwd = np.full(n, np.nan)
        fwd[:n-h] = mid[h:] - mid[:n-h]
        signals[f"fwd_ret_{h}"] = fwd

    # ══════════════════════════════════════════════════════════════════════════
    # PRICE SIGNALS
    # ══════════════════════════════════════════════════════════════════════════

    # 1. Microprice deviation from mid
    best_bid = df["best_bid"].values.astype(float)
    best_ask = df["best_ask"].values.astype(float)
    bid_v1 = df["bid_vol_1"].values.astype(float)
    ask_v1 = df["ask_vol_1"].values.astype(float)
    total_v1 = bid_v1 + ask_v1
    microprice = np.where(total_v1 > 0,
                          (best_ask * bid_v1 + best_bid * ask_v1) / total_v1,
                          mid)
    signals["S01_microprice_dev"] = microprice - mid

    # 2. Simple mid momentum
    signals["S02a_mom_1"] = pd.Series(mid).diff(1).values
    signals["S02b_mom_5"] = pd.Series(mid).diff(5).values
    signals["S02c_mom_10"] = pd.Series(mid).diff(10).values

    # 3. Wall-mid vs simple mid
    # Wall mid = mid of largest-volume bid and ask
    wall_bid = np.full(n, np.nan)
    wall_ask = np.full(n, np.nan)
    for i in range(n):
        row = df.iloc[i]
        max_bv, wb = 0, np.nan
        for lvl in [1, 2, 3]:
            bv = row.get(f"bid_volume_{lvl}", 0)
            bp = row.get(f"bid_price_{lvl}", np.nan)
            if pd.notna(bv) and pd.notna(bp) and bv > max_bv:
                max_bv = bv
                wb = bp
        max_av, wa = 0, np.nan
        for lvl in [1, 2, 3]:
            av = row.get(f"ask_volume_{lvl}", 0)
            ap = row.get(f"ask_price_{lvl}", np.nan)
            if pd.notna(av) and pd.notna(ap) and abs(av) > max_av:
                max_av = abs(av)
                wa = ap
        wall_bid[i] = wb
        wall_ask[i] = wa

    wall_mid_vals = (wall_bid + wall_ask) / 2
    signals["S03_wall_mid_dev"] = wall_mid_vals - mid

    # 4. Rolling regression slope (uses module-level rolling_slope)
    signals["S04a_slope_5"] = rolling_slope(mid, 5)
    signals["S04b_slope_10"] = rolling_slope(mid, 10)
    signals["S04c_slope_20"] = rolling_slope(mid, 20)

    # 5. Distance from session VWAP
    # We can compute VWAP from trades or approximate from mid * volume
    # Use cumulative mid as proxy (no true volume per tick available from book alone)
    cum_mid = np.cumsum(mid)
    count = np.arange(1, n + 1, dtype=float)
    session_vwap = cum_mid / count
    signals["S05_vwap_dev"] = mid - session_vwap

    # 6. Distance from session high / low
    cum_high = np.maximum.accumulate(mid)
    cum_low = np.minimum.accumulate(mid)
    signals["S06a_dist_high"] = mid - cum_high  # always <= 0
    signals["S06b_dist_low"] = mid - cum_low    # always >= 0

    # 7. Intraday return from open
    signals["S07_intraday_ret"] = mid - mid[0]

    # ══════════════════════════════════════════════════════════════════════════
    # BOOK SIGNALS
    # ══════════════════════════════════════════════════════════════════════════

    # 8. L1 depth imbalance
    signals["S08_l1_imbalance"] = np.where(
        total_v1 > 0, (bid_v1 - ask_v1) / total_v1, 0
    )

    # 9. L2 total depth imbalance (sum bid vols vs sum ask vols across all levels)
    total_bid_vol = (df["bid_vol_1"].values + df["bid_vol_2"].values + df["bid_vol_3"].values)
    total_ask_vol = (df["ask_vol_1"].values + df["ask_vol_2"].values + df["ask_vol_3"].values)
    total_all = total_bid_vol + total_ask_vol
    signals["S09_total_imbalance"] = np.where(total_all > 0,
        (total_bid_vol - total_ask_vol) / total_all, 0)

    # 10. Spread width
    spread = df["spread"].values.astype(float)
    signals["S10_spread"] = spread

    # 11. Spread change
    signals["S11_spread_change"] = pd.Series(spread).diff(1).values

    # 12. Book pressure / gravity: volume-weighted average distance from mid
    bid_gravity = np.zeros(n)
    ask_gravity = np.zeros(n)
    for i in range(n):
        row = df.iloc[i]
        m = mid[i]
        bg = 0
        bw = 0
        for lvl in [1, 2, 3]:
            bp = row.get(f"bid_price_{lvl}", np.nan)
            bv = row.get(f"bid_volume_{lvl}", 0)
            if pd.notna(bp) and pd.notna(bv) and bv > 0:
                bg += bv * (m - bp)
                bw += bv
        bid_gravity[i] = bg / bw if bw > 0 else np.nan

        ag = 0
        aw = 0
        for lvl in [1, 2, 3]:
            ap = row.get(f"ask_price_{lvl}", np.nan)
            av = row.get(f"ask_volume_{lvl}", 0)
            if pd.notna(ap) and pd.notna(av) and abs(av) > 0:
                ag += abs(av) * (ap - m)
                aw += abs(av)
        ask_gravity[i] = ag / aw if aw > 0 else np.nan

    # Positive = ask side further from mid → bullish
    signals["S12_gravity_asym"] = ask_gravity - bid_gravity

    # 13. One-sided book indicator
    has_bid = (~df["best_bid"].isna()).astype(float).values
    has_ask = (~df["best_ask"].isna()).astype(float).values
    signals["S13_one_sided"] = has_bid - has_ask  # +1 = only bids, -1 = only asks

    # ══════════════════════════════════════════════════════════════════════════
    # TRADE SIGNALS
    # ══════════════════════════════════════════════════════════════════════════

    # Merge trades onto tick grid by timestamp
    timestamps = df["timestamp"].values
    ts_set = set(timestamps)

    # Classify trades as buyer-initiated or seller-initiated
    # Compare trade price to prevailing mid at that timestamp
    trade_flow = np.zeros(n)  # net signed volume per tick
    trade_count = np.zeros(n)
    trade_vol = np.zeros(n)
    trade_size_sum = np.zeros(n)

    # Build timestamp-to-index map
    ts_to_idx = {}
    for idx_val, ts in enumerate(timestamps):
        if ts not in ts_to_idx:
            ts_to_idx[ts] = idx_val

    for _, trow in ipr_trades.iterrows():
        tts = trow["timestamp"]
        # Find nearest tick <= trade timestamp
        # Trades happen at arbitrary timestamps; find the last tick before/at this time
        valid_ts = timestamps[timestamps <= tts]
        if len(valid_ts) == 0:
            continue
        nearest_ts = valid_ts[-1]
        idx = ts_to_idx[nearest_ts]
        m = mid[idx]
        tp = trow["price"]
        tq = trow["quantity"]

        # Lee-Ready: trade above mid = buyer-initiated (+), below = seller-initiated (-)
        if tp > m:
            trade_flow[idx] += tq
        elif tp < m:
            trade_flow[idx] -= tq
        # At mid: ambiguous, skip

        trade_count[idx] += 1
        trade_vol[idx] += tq
        trade_size_sum[idx] += tq

    # 14. Trade flow imbalance (rolling)
    for w in [5, 10, 20]:
        signals[f"S14_flow_{w}"] = pd.Series(trade_flow).rolling(w, min_periods=1).sum().values

    # 15. Trade arrival rate (rolling)
    for w in [5, 10, 20]:
        signals[f"S15_arrival_{w}"] = pd.Series(trade_count).rolling(w, min_periods=1).sum().values

    # 16. Average trade size (rolling)
    avg_size = np.where(trade_count > 0, trade_vol / trade_count, 0)
    for w in [10, 20]:
        signals[f"S16_avg_size_{w}"] = pd.Series(avg_size).rolling(w, min_periods=1).mean().values

    # 17. Large trade indicator
    tv_series = pd.Series(trade_vol)
    tv_mean = tv_series.rolling(50, min_periods=10).mean()
    tv_std = tv_series.rolling(50, min_periods=10).std()
    signals["S17_large_trade"] = np.where(tv_std > 0,
        (trade_vol - tv_mean.values) / tv_std.values, 0)

    # ══════════════════════════════════════════════════════════════════════════
    # DERIVED SIGNALS
    # ══════════════════════════════════════════════════════════════════════════

    # 18. Realized volatility (rolling std of returns)
    ret_1 = pd.Series(mid).diff(1)
    for w in [10, 21, 50]:
        signals[f"S18_rvol_{w}"] = ret_1.rolling(w, min_periods=max(5, w//2)).std().values

    # 19. Return autocorrelation: lag-1 return × current return
    ret1 = ret_1.values
    lag_ret = np.full(n, np.nan)
    lag_ret[1:] = ret1[:-1]
    signals["S19_ret_ac1"] = ret1 * lag_ret

    # 20. Trend strength: fraction of positive slope readings in last 20 ticks
    slope5 = signals["S04a_slope_5"].values
    pos_slope = (slope5 >= 0).astype(float)
    signals["S20_trend_strength"] = pd.Series(pos_slope).rolling(20, min_periods=1).mean().values

    # 21. Optimal entry timing: fractional day position (0 to 1)
    max_ts = timestamps.max()
    signals["S21_day_fraction"] = timestamps / max_ts if max_ts > 0 else 0

    # 22. Drawdown from rolling max
    signals["S22_drawdown"] = mid - cum_high  # always <= 0

    # ══════════════════════════════════════════════════════════════════════════
    # CROSS-PRODUCT SIGNALS
    # ══════════════════════════════════════════════════════════════════════════

    # Merge ACO data by timestamp
    if aco_book is not None and len(aco_book) > 0:
        aco_ts_to_mid = dict(zip(aco_book["timestamp"].values, aco_book["mid"].values))
        aco_ts_to_spread = {}
        for _, arow in aco_book.iterrows():
            ats = arow["timestamp"]
            ab = arow.get("best_bid", np.nan)
            aa = arow.get("best_ask", np.nan)
            if pd.notna(ab) and pd.notna(aa):
                aco_ts_to_spread[ats] = aa - ab
            else:
                aco_ts_to_spread[ats] = np.nan

        aco_mid_arr = np.full(n, np.nan)
        aco_spread_arr = np.full(n, np.nan)
        for i, ts in enumerate(timestamps):
            if ts in aco_ts_to_mid:
                aco_mid_arr[i] = aco_ts_to_mid[ts]
                aco_spread_arr[i] = aco_ts_to_spread.get(ts, np.nan)

        # Forward fill ACO values (ACO ticks may not be at every IPR tick)
        aco_mid_arr = pd.Series(aco_mid_arr).ffill().values
        aco_spread_arr = pd.Series(aco_spread_arr).ffill().values

        # 23. ACO mid deviation from 10000
        signals["S23_aco_dev"] = aco_mid_arr - 10000

        # 24. ACO spread state
        signals["S24_aco_spread"] = aco_spread_arr
    else:
        signals["S23_aco_dev"] = np.nan
        signals["S24_aco_spread"] = np.nan

    return signals


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def compute_ic(signal_vals, return_vals):
    """Spearman rank correlation (IC) between signal and forward return."""
    mask = ~(np.isnan(signal_vals) | np.isnan(return_vals))
    if mask.sum() < 30:
        return np.nan, np.nan, 0
    s = signal_vals[mask]
    r = return_vals[mask]
    # Handle constant signal
    if np.std(s) == 0 or np.std(r) == 0:
        return 0.0, 1.0, mask.sum()
    corr, pval = stats.spearmanr(s, r)
    return corr, pval, mask.sum()


def directional_accuracy(signal_vals, return_vals):
    """Fraction of times sign(signal) == sign(return)."""
    mask = ~(np.isnan(signal_vals) | np.isnan(return_vals))
    s = signal_vals[mask]
    r = return_vals[mask]
    nonzero = (s != 0) & (r != 0)
    if nonzero.sum() == 0:
        return np.nan
    return np.mean(np.sign(s[nonzero]) == np.sign(r[nonzero]))


def get_signal_columns(signals_df):
    """Return columns that are signals (not forward returns)."""
    return [c for c in signals_df.columns if c.startswith("S")]


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def main():
    all_signals = {}
    all_day_results = {}

    print("=" * 100)
    print("IPR COMPREHENSIVE SIGNAL ANALYSIS — IMC Prosperity 4 Round 2")
    print("=" * 100)

    # ── Load and compute per-day ─────────────────────────────────────────────
    pooled_signals = None

    for day in DAYS:
        print(f"\n{'─' * 80}")
        print(f"  DAY {day}")
        print(f"{'─' * 80}")

        prices = load_prices(day)
        trades = load_trades(day)

        ipr_book = build_book_df(prices, PRODUCT)
        ipr_trades = build_trade_df(trades, PRODUCT)
        aco_book = build_book_df(prices, ACO_PRODUCT)

        print(f"  IPR ticks: {len(ipr_book)}, IPR trades: {len(ipr_trades)}, ACO ticks: {len(aco_book)}")
        print(f"  IPR mid range: {ipr_book['mid'].min():.1f} - {ipr_book['mid'].max():.1f}")
        print(f"  IPR drift: {ipr_book['mid'].iloc[-1] - ipr_book['mid'].iloc[0]:.1f} over {len(ipr_book)} ticks")

        # One-sided book stats
        both_sided = ipr_book["best_bid"].notna() & ipr_book["best_ask"].notna()
        bid_only = ipr_book["best_bid"].notna() & ipr_book["best_ask"].isna()
        ask_only = ipr_book["best_bid"].isna() & ipr_book["best_ask"].notna()
        print(f"  Book: both-sided={both_sided.sum()} ({100*both_sided.mean():.1f}%), "
              f"bid-only={bid_only.sum()} ({100*bid_only.mean():.1f}%), "
              f"ask-only={ask_only.sum()} ({100*ask_only.mean():.1f}%)")

        signals = compute_signals(ipr_book, ipr_trades, aco_book)
        signals["_day"] = day
        signals["_timestamp"] = ipr_book["timestamp"].values
        signals["_mid"] = ipr_book["mid"].values

        all_signals[day] = signals

        if pooled_signals is None:
            pooled_signals = signals.copy()
        else:
            pooled_signals = pd.concat([pooled_signals, signals], ignore_index=True)

        # Per-day IC table
        sig_cols = get_signal_columns(signals)
        results = []
        for sc in sig_cols:
            row = {"signal": sc}
            for h in HORIZONS:
                ic, pval, n_obs = compute_ic(signals[sc].values, signals[f"fwd_ret_{h}"].values)
                row[f"IC_{h}"] = ic
                row[f"p_{h}"] = pval
                row[f"n_{h}"] = n_obs
            row["dir_acc_10"] = directional_accuracy(signals[sc].values, signals["fwd_ret_10"].values)
            results.append(row)

        rdf = pd.DataFrame(results)
        all_day_results[day] = rdf

        # Print top signals by |IC_10|
        rdf["abs_IC_10"] = rdf["IC_10"].abs()
        rdf_sorted = rdf.sort_values("abs_IC_10", ascending=False).head(15)
        print(f"\n  Top 15 signals by |IC_10| for day {day}:")
        print(f"  {'Signal':<25s} {'IC_1':>8s} {'IC_5':>8s} {'IC_10':>8s} {'IC_50':>8s} {'IC_100':>8s} {'DirAcc':>8s}")
        print(f"  {'─'*25} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")
        for _, r in rdf_sorted.iterrows():
            print(f"  {r['signal']:<25s} {r['IC_1']:>8.4f} {r['IC_5']:>8.4f} {r['IC_10']:>8.4f} "
                  f"{r['IC_50']:>8.4f} {r['IC_100']:>8.4f} {r['dir_acc_10']:>8.3f}")

    # ══════════════════════════════════════════════════════════════════════════
    # POOLED ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("POOLED ANALYSIS (ALL 3 DAYS)")
    print(f"{'=' * 100}")
    print(f"Total ticks: {len(pooled_signals)}")

    sig_cols = get_signal_columns(pooled_signals)
    pooled_results = []
    for sc in sig_cols:
        row = {"signal": sc}
        for h in HORIZONS:
            ic, pval, n_obs = compute_ic(
                pooled_signals[sc].values,
                pooled_signals[f"fwd_ret_{h}"].values
            )
            row[f"IC_{h}"] = ic
            row[f"p_{h}"] = pval
            row[f"n_{h}"] = n_obs
        row["dir_acc_10"] = directional_accuracy(
            pooled_signals[sc].values,
            pooled_signals["fwd_ret_10"].values
        )
        pooled_results.append(row)

    pdf = pd.DataFrame(pooled_results)
    pdf["abs_IC_10"] = pdf["IC_10"].abs()

    # ── IC stability across days ─────────────────────────────────────────────
    print(f"\n{'─' * 100}")
    print("IC STABILITY ACROSS DAYS (IC_10)")
    print(f"{'─' * 100}")
    print(f"{'Signal':<25s} {'Day -1':>8s} {'Day 0':>8s} {'Day 1':>8s} {'Pooled':>8s} {'Stable?':>8s}")
    print(f"{'─'*25} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")

    for _, pr in pdf.sort_values("abs_IC_10", ascending=False).iterrows():
        sc = pr["signal"]
        d_ics = []
        for day in DAYS:
            rdf = all_day_results[day]
            ic_val = rdf.loc[rdf["signal"] == sc, "IC_10"].values
            d_ics.append(ic_val[0] if len(ic_val) > 0 else np.nan)

        # Stable = same sign across all 3 days
        signs = [np.sign(x) for x in d_ics if not np.isnan(x)]
        stable = "YES" if len(signs) == 3 and all(s == signs[0] for s in signs) and signs[0] != 0 else "NO"

        print(f"{sc:<25s} {d_ics[0]:>8.4f} {d_ics[1]:>8.4f} {d_ics[2]:>8.4f} {pr['IC_10']:>8.4f} {stable:>8s}")

    # ══════════════════════════════════════════════════════════════════════════
    # FULL RANKED TABLE
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("FULL SIGNAL RANKING BY |IC_10| (POOLED)")
    print(f"{'=' * 100}")
    pdf_sorted = pdf.sort_values("abs_IC_10", ascending=False)
    print(f"{'Rank':>4s} {'Signal':<25s} {'IC_1':>8s} {'IC_5':>8s} {'IC_10':>8s} {'IC_50':>8s} {'IC_100':>8s} {'DirAcc':>8s} {'p_10':>10s} {'N':>6s}")
    print(f"{'─'*4} {'─'*25} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*10} {'─'*6}")
    for rank, (_, r) in enumerate(pdf_sorted.iterrows(), 1):
        sig = "***" if r["p_10"] < 0.001 else "**" if r["p_10"] < 0.01 else "*" if r["p_10"] < 0.05 else ""
        print(f"{rank:>4d} {r['signal']:<25s} {r['IC_1']:>8.4f} {r['IC_5']:>8.4f} {r['IC_10']:>8.4f} "
              f"{r['IC_50']:>8.4f} {r['IC_100']:>8.4f} {r['dir_acc_10']:>8.3f} {r['p_10']:>9.2e}{sig:>1s} {r['n_10']:>6.0f}")

    # ══════════════════════════════════════════════════════════════════════════
    # DRIFT STRUCTURE ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("DRIFT STRUCTURE ANALYSIS")
    print(f"{'=' * 100}")

    for day in DAYS:
        sigs = all_signals[day]
        mid = sigs["_mid"].values
        ts = sigs["_timestamp"].values
        n = len(mid)

        # Split day into deciles
        decile_size = n // 10
        print(f"\n  Day {day}: Intraday drift by decile (each ~{decile_size} ticks)")
        print(f"  {'Decile':>6s} {'Ticks':>8s} {'Start':>10s} {'End':>10s} {'Drift':>8s} {'Drift/tick':>10s}")
        for d in range(10):
            i0 = d * decile_size
            i1 = min((d + 1) * decile_size, n) - 1
            drift = mid[i1] - mid[i0]
            dpt = drift / max(1, i1 - i0)
            print(f"  {d+1:>6d} {i1-i0+1:>8d} {mid[i0]:>10.1f} {mid[i1]:>10.1f} {drift:>8.1f} {dpt:>10.4f}")

        # Overall
        print(f"  Total drift: {mid[-1] - mid[0]:.1f}, ticks: {n}, drift/tick: {(mid[-1]-mid[0])/n:.4f}")

    # ══════════════════════════════════════════════════════════════════════════
    # AUTOCORRELATION PROFILE
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("AUTOCORRELATION PROFILE OF MID RETURNS")
    print(f"{'=' * 100}")

    for day in DAYS:
        mid = all_signals[day]["_mid"].values
        ret = np.diff(mid)
        ret = ret[~np.isnan(ret)]
        print(f"\n  Day {day}: AC(lag) of 1-tick mid returns (N={len(ret)})")
        print(f"  {'Lag':>4s} {'AC':>8s} {'95% CI':>10s}")
        ci = 1.96 / np.sqrt(len(ret))
        for lag in [1, 2, 3, 4, 5, 10, 15, 20, 30, 50]:
            if lag >= len(ret):
                break
            ac = np.corrcoef(ret[:-lag], ret[lag:])[0, 1]
            sig = " ***" if abs(ac) > ci else ""
            print(f"  {lag:>4d} {ac:>8.4f} +/-{ci:.4f}{sig}")

    # ══════════════════════════════════════════════════════════════════════════
    # ENTRY TIMING ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("ENTRY TIMING ANALYSIS")
    print(f"{'=' * 100}")
    print("If you could buy 80 units at tick T and hold to end of day, what is PnL?")

    for day in DAYS:
        mid = all_signals[day]["_mid"].values
        n = len(mid)
        end_mid = mid[-1]

        print(f"\n  Day {day}: end_mid = {end_mid:.1f}")
        print(f"  {'Entry tick':>12s} {'Entry mid':>12s} {'PnL (80 units)':>15s} {'% of max':>10s}")

        max_pnl = 80 * (end_mid - mid[0])
        for t in [0, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]:
            if t >= n:
                break
            pnl = 80 * (end_mid - mid[t])
            pct = 100 * pnl / max_pnl if max_pnl > 0 else 0
            print(f"  {t:>12d} {mid[t]:>12.1f} {pnl:>15.0f} {pct:>10.1f}%")

    # ══════════════════════════════════════════════════════════════════════════
    # THEORETICAL CEILING
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("THEORETICAL CEILING ANALYSIS")
    print(f"{'=' * 100}")

    for day in DAYS:
        mid = all_signals[day]["_mid"].values
        ret = np.diff(mid)
        n = len(ret)

        # Perfect prediction: long 80 when next return > 0, short 80 when < 0
        perfect_pnl = 80 * np.sum(np.abs(ret[~np.isnan(ret)]))

        # Buy-and-hold: long 80 from tick 0
        bah_pnl = 80 * (mid[-1] - mid[0])

        # Current strategy approx: long 80 most of the time (assume from tick ~10)
        # But also gets fills from spread capture
        # Trend following: assume long 80 whenever slope > 0 (which is ~80% of time)
        slope5 = all_signals[day]["S04a_slope_5"].values
        trend_mask = np.zeros(n)
        trend_mask[~np.isnan(slope5[:-1])] = np.where(slope5[:-1][~np.isnan(slope5[:-1])] >= 0, 1, -1)
        # For NaN slopes at start, assume long
        trend_mask[np.isnan(slope5[:-1])] = 1
        trend_pnl = 80 * np.sum(trend_mask * ret[~np.isnan(ret)][:len(trend_mask)])

        print(f"\n  Day {day}:")
        print(f"    Perfect foresight (flip each tick): {perfect_pnl:>12.0f}")
        print(f"    Buy-and-hold (long 80 from tick 0):  {bah_pnl:>12.0f}")
        print(f"    Trend-follow (slope5 direction):     {trend_pnl:>12.0f}")
        print(f"    BAH as % of perfect:                 {100*bah_pnl/perfect_pnl:>11.1f}%")
        print(f"    Trend as % of perfect:               {100*trend_pnl/perfect_pnl:>11.1f}%")

        # How much could you gain from shorting drawdowns?
        drawdown_gains = 0
        for i in range(n):
            if ret[i] < 0 and not np.isnan(ret[i]):
                # If you were short instead of long, you'd gain 2 * 80 * |ret|
                drawdown_gains += 80 * abs(ret[i])  # going from +80 to 0 saves 80*|ret|
        print(f"    Potential from avoiding ALL drawdowns: +{drawdown_gains:>10.0f}")
        print(f"    # negative returns: {np.sum(ret < 0)} / {n} = {100*np.sum(ret<0)/n:.1f}%")

    # ══════════════════════════════════════════════════════════════════════════
    # REGIME ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("REGIME ANALYSIS: TRENDING vs MEAN-REVERTING MICRO-REGIMES")
    print(f"{'=' * 100}")

    for day in DAYS:
        sigs = all_signals[day]
        mid = sigs["_mid"].values
        ret = pd.Series(mid).diff(1).values

        # Define regimes by rolling 20-tick return sign
        rolling_ret_20 = pd.Series(mid).diff(20).values
        trending_up = rolling_ret_20 > 5     # meaningful uptrend
        trending_down = rolling_ret_20 < -5  # meaningful downtrend
        ranging = ~trending_up & ~trending_down

        print(f"\n  Day {day}:")
        print(f"    Trending up: {trending_up.sum()} ticks ({100*trending_up.mean():.1f}%)")
        print(f"    Trending dn: {trending_down.sum()} ticks ({100*trending_down.mean():.1f}%)")
        print(f"    Ranging:     {ranging.sum()} ticks ({100*ranging.mean():.1f}%)")

        # IC of key signals in each regime
        print(f"\n    IC_10 by regime:")
        print(f"    {'Signal':<25s} {'Trend Up':>10s} {'Trend Dn':>10s} {'Ranging':>10s}")
        print(f"    {'─'*25} {'─'*10} {'─'*10} {'─'*10}")

        key_signals = ["S01_microprice_dev", "S04a_slope_5", "S08_l1_imbalance",
                       "S09_total_imbalance", "S14_flow_10", "S20_trend_strength",
                       "S22_drawdown", "S03_wall_mid_dev"]
        for sc in key_signals:
            ics = []
            for mask in [trending_up, trending_down, ranging]:
                if mask.sum() > 50:
                    s_vals = sigs[sc].values[mask]
                    r_vals = sigs["fwd_ret_10"].values[mask]
                    ic, _, _ = compute_ic(s_vals, r_vals)
                    ics.append(f"{ic:>10.4f}")
                else:
                    ics.append(f"{'N/A':>10s}")
            print(f"    {sc:<25s} {''.join(ics)}")

    # ══════════════════════════════════════════════════════════════════════════
    # DRAWDOWN BUYING ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("DRAWDOWN BUYING ANALYSIS: DOES BUYING DIPS HELP?")
    print(f"{'=' * 100}")

    for day in DAYS:
        mid = all_signals[day]["_mid"].values
        cum_high = np.maximum.accumulate(mid)
        drawdown = mid - cum_high  # always <= 0

        # For each drawdown depth bucket, what's the avg forward return?
        print(f"\n  Day {day}: Forward 10-tick return by drawdown depth")
        print(f"  {'Drawdown':>12s} {'Avg Fwd10':>10s} {'Med Fwd10':>10s} {'N':>6s} {'% Up':>6s}")

        fwd10 = all_signals[day]["fwd_ret_10"].values
        for lo, hi, label in [
            (-1, 0, "  0 (at high)"),
            (-5, -1, " -1 to -5"),
            (-10, -5, " -5 to -10"),
            (-20, -10, "-10 to -20"),
            (-50, -20, "-20 to -50"),
            (-999, -50, " < -50"),
        ]:
            mask = (drawdown >= lo) & (drawdown < hi) & ~np.isnan(fwd10)
            if mask.sum() > 0:
                avg = np.mean(fwd10[mask])
                med = np.median(fwd10[mask])
                pup = 100 * np.mean(fwd10[mask] > 0)
                print(f"  {label:>12s} {avg:>10.2f} {med:>10.2f} {mask.sum():>6d} {pup:>6.1f}%")

    # ══════════════════════════════════════════════════════════════════════════
    # SPREAD ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("SPREAD DISTRIBUTION AND FORWARD RETURN BY SPREAD")
    print(f"{'=' * 100}")

    for day in DAYS:
        sigs = all_signals[day]
        spread = sigs["S10_spread"].values
        fwd10 = sigs["fwd_ret_10"].values

        print(f"\n  Day {day}: Spread distribution")
        unique_spreads, counts = np.unique(spread[~np.isnan(spread)], return_counts=True)
        total = counts.sum()
        for s, c in sorted(zip(unique_spreads, counts), key=lambda x: -x[1])[:10]:
            mask = (spread == s) & ~np.isnan(fwd10)
            avg_fwd = np.mean(fwd10[mask]) if mask.sum() > 0 else np.nan
            print(f"    Spread={s:>5.0f}: {c:>5d} ticks ({100*c/total:>5.1f}%), avg fwd10={avg_fwd:>7.2f}")

    # ══════════════════════════════════════════════════════════════════════════
    # WALL-MID vs MICROPRICE vs SIMPLE MID COMPARISON
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("FV ESTIMATOR COMPARISON: WALL-MID vs MICROPRICE vs SIMPLE MID")
    print(f"{'=' * 100}")

    for day in DAYS:
        sigs = all_signals[day]
        mid = sigs["_mid"].values

        # Microprice = mid + microprice_dev
        mp = mid + sigs["S01_microprice_dev"].values
        wm = mid + sigs["S03_wall_mid_dev"].values

        # Which predicts future mid better? (lower MSE)
        for h in [1, 5, 10]:
            fwd = sigs[f"fwd_ret_{h}"].values
            mask = ~np.isnan(fwd) & ~np.isnan(sigs["S01_microprice_dev"].values) & ~np.isnan(sigs["S03_wall_mid_dev"].values)

            # Prediction error: FV - future_mid
            # For simple mid: error = 0 - fwd_ret (trivial predictor)
            # For microprice: error = microprice_dev - fwd_ret (microprice predicts future mid)
            # For wall-mid: error = wall_mid_dev - fwd_ret

            mp_dev = sigs["S01_microprice_dev"].values[mask]
            wm_dev = sigs["S03_wall_mid_dev"].values[mask]
            fr = fwd[mask]

            mse_mid = np.mean(fr**2)
            mse_mp = np.mean((mp_dev - fr)**2)
            mse_wm = np.mean((wm_dev - fr)**2)

            # Also: IC of each estimator's deviation
            ic_mp, _, _ = compute_ic(mp_dev, fr)
            ic_wm, _, _ = compute_ic(wm_dev, fr)

            if h == 10:
                print(f"\n  Day {day}, horizon={h}:")
                print(f"    Simple mid MSE:  {mse_mid:>10.2f}")
                print(f"    Microprice MSE:  {mse_mp:>10.2f} (IC={ic_mp:.4f})")
                print(f"    Wall-mid MSE:    {mse_wm:>10.2f} (IC={ic_wm:.4f})")
                if mse_mp < mse_wm:
                    print(f"    >>> Microprice wins by {100*(mse_wm-mse_mp)/mse_wm:.1f}%")
                else:
                    print(f"    >>> Wall-mid wins by {100*(mse_mp-mse_wm)/mse_mp:.1f}%")

    # ══════════════════════════════════════════════════════════════════════════
    # OPTIMAL SLOPE WINDOW
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("OPTIMAL SLOPE WINDOW ANALYSIS")
    print(f"{'=' * 100}")
    print("Current strategy uses 5-tick slope. Is there a better window?")

    for h in [10, 50]:
        print(f"\n  Target horizon: {h}-tick forward return")
        print(f"  {'Window':>8s} {'IC Day-1':>10s} {'IC Day0':>10s} {'IC Day1':>10s} {'Pooled IC':>10s}")
        print(f"  {'─'*8} {'─'*10} {'─'*10} {'─'*10} {'─'*10}")
        for w in [3, 5, 7, 10, 15, 20, 30, 50]:
            ics_per_day = []
            all_s = []
            all_r = []
            for day in DAYS:
                mid_d = all_signals[day]["_mid"].values
                slope_w = rolling_slope(mid_d, w)
                fwd_h = all_signals[day][f"fwd_ret_{h}"].values
                ic, _, _ = compute_ic(slope_w, fwd_h)
                ics_per_day.append(ic)
                mask = ~np.isnan(slope_w) & ~np.isnan(fwd_h)
                all_s.extend(slope_w[mask])
                all_r.extend(fwd_h[mask])
            pooled_ic, _, _ = compute_ic(np.array(all_s), np.array(all_r))
            print(f"  {w:>8d} {ics_per_day[0]:>10.4f} {ics_per_day[1]:>10.4f} {ics_per_day[2]:>10.4f} {pooled_ic:>10.4f}")

    # ══════════════════════════════════════════════════════════════════════════
    # TREND INDICATOR THRESHOLD ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("TREND INDICATOR THRESHOLD ANALYSIS")
    print(f"{'=' * 100}")
    print("Current strategy uses indicator >= 0.5. Is there a better threshold?")

    for day in DAYS:
        sigs = all_signals[day]
        ts20 = sigs["S20_trend_strength"].values
        mid = sigs["_mid"].values
        n = len(mid)
        ret = pd.Series(mid).diff(1).values

        print(f"\n  Day {day}: Avg 1-tick return by trend_strength bucket")
        print(f"  {'Threshold':>12s} {'Avg Ret':>10s} {'Med Ret':>10s} {'N':>6s} {'% Up':>6s}")
        for lo, hi in [(0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]:
            mask = (ts20 >= lo) & (ts20 < hi) & ~np.isnan(ret)
            # Shift mask by 1 to align signal at t with return at t+1
            # Use fwd_ret_1 instead
            fwd1 = sigs["fwd_ret_1"].values
            mask2 = (ts20 >= lo) & (ts20 < hi) & ~np.isnan(fwd1)
            if mask2.sum() > 0:
                avg = np.mean(fwd1[mask2])
                med = np.median(fwd1[mask2])
                pup = 100 * np.mean(fwd1[mask2] > 0)
                print(f"  [{lo:.1f}, {hi:.1f}){' ':>4s} {avg:>10.4f} {med:>10.4f} {mask2.sum():>6d} {pup:>6.1f}%")

    # ══════════════════════════════════════════════════════════════════════════
    # SIGNAL CORRELATION MATRIX
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("SIGNAL CORRELATION MATRIX (TOP 10 BY |IC_10|, POOLED)")
    print(f"{'=' * 100}")

    top10 = pdf.sort_values("abs_IC_10", ascending=False).head(10)["signal"].values
    corr_data = pooled_signals[list(top10)].corr(method="spearman")
    print(f"\n  {'':>25s}", end="")
    for s in top10:
        print(f" {s[:8]:>8s}", end="")
    print()
    for s1 in top10:
        print(f"  {s1:<25s}", end="")
        for s2 in top10:
            print(f" {corr_data.loc[s1, s2]:>8.3f}", end="")
        print()

    # ══════════════════════════════════════════════════════════════════════════
    # ACTIONABLE IMPROVEMENTS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 100}")
    print("ACTIONABLE IMPROVEMENTS")
    print(f"{'=' * 100}")

    # Summarize findings
    print("""
Based on the analysis above, here are specific, concrete changes supported by data:

1. FV ESTIMATOR: Switch from wall-mid to microprice?
   - Compare MSE and IC above. If microprice has higher IC across all 3 days,
     it should replace wall-mid as the FV anchor.

2. SLOPE WINDOW: Optimal window for trend detection
   - The analysis tests windows 3-50. If a window other than 5 has consistently
     higher IC at the 10-50 tick horizon, the strategy should switch.

3. TREND THRESHOLD: The 0.5 indicator threshold
   - If the return profile shows that threshold 0.3 or 0.7 captures more PnL,
     the strategy should adjust. Given the strong uptrend, lower threshold =
     more time in long position = more drift captured.

4. ENTRY TIMING: Position building speed
   - The entry timing analysis shows how much PnL is lost per tick of delay.
     If drift is front-loaded, the strategy should be even MORE aggressive at open.

5. DRAWDOWN BUYING: Does buying dips improve timing?
   - If drawdown depth predicts positive forward returns, adding a "buy the dip"
     signal when drawdown > X could improve entry prices.

6. SPREAD REGIME: Do tight spreads predict anything?
   - If tight spread ticks have systematically different forward returns,
     the strategy could condition aggression on spread state.

7. DOWNTREND GATE: The intentional long-bias (len==10 trick)
   - Given the +1000/day drift, NEVER going short is likely optimal.
     But the analysis shows whether any short-term sell signals have positive IC
     that could improve timing of position reduction.

8. BOOK IMBALANCE AS TIMING SIGNAL:
   - If L1 or L2 imbalance has meaningful IC for the 1-5 tick horizon,
     it could improve fill quality: buy more aggressively when imbalance is
     favorable, post passive when unfavorable.

9. POSITION SIZING: Is binary 0/80 optimal?
   - The strategy currently targets +80 whenever indicator >= 0.5.
   - If signal strength is continuous and IC increases with signal magnitude,
     a graduated position target (e.g., 40 when indicator=0.5, 80 when indicator=0.9)
     could reduce drawdown without sacrificing much drift capture.
""")

    # Final summary: which signals pass the "triple-day stability" test?
    print(f"\n{'=' * 100}")
    print("TRIPLE-DAY STABLE SIGNALS (same sign IC_10 all 3 days, |IC_10| > 0.02)")
    print(f"{'=' * 100}")
    stable_signals = []
    for _, pr in pdf.sort_values("abs_IC_10", ascending=False).iterrows():
        sc = pr["signal"]
        d_ics = []
        for day in DAYS:
            rdf = all_day_results[day]
            ic_val = rdf.loc[rdf["signal"] == sc, "IC_10"].values
            d_ics.append(ic_val[0] if len(ic_val) > 0 else np.nan)

        signs = [np.sign(x) for x in d_ics if not np.isnan(x)]
        if (len(signs) == 3 and all(s == signs[0] for s in signs) and signs[0] != 0
                and abs(pr["IC_10"]) > 0.02):
            stable_signals.append({
                "signal": sc,
                "IC_10": pr["IC_10"],
                "IC_50": pr["IC_50"],
                "IC_100": pr["IC_100"],
                "dir_acc": pr["dir_acc_10"],
                "d-1": d_ics[0],
                "d0": d_ics[1],
                "d1": d_ics[2],
            })

    if stable_signals:
        sdf = pd.DataFrame(stable_signals)
        print(f"\n{'Signal':<25s} {'IC_10':>8s} {'IC_50':>8s} {'IC_100':>8s} {'DirAcc':>8s} {'Day-1':>8s} {'Day0':>8s} {'Day1':>8s}")
        print(f"{'─'*25} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")
        for _, r in sdf.iterrows():
            print(f"{r['signal']:<25s} {r['IC_10']:>8.4f} {r['IC_50']:>8.4f} {r['IC_100']:>8.4f} "
                  f"{r['dir_acc']:>8.3f} {r['d-1']:>8.4f} {r['d0']:>8.4f} {r['d1']:>8.4f}")
    else:
        print("\n  No signals passed the triple-day stability filter at |IC_10| > 0.02")

    print(f"\n{'=' * 100}")
    print("ANALYSIS COMPLETE")
    print(f"{'=' * 100}")


if __name__ == "__main__":
    main()
