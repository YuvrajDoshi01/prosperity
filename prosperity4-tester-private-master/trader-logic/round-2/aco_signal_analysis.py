"""
Comprehensive ACO (ASH_COATED_OSMIUM) Signal Analysis
=====================================================
Analyzes every plausible trading signal for ACO across 3 days of Round 2 data.
Computes IC, multi-horizon IC, directional accuracy, quintile spreads,
correlation matrix, decay analysis, and regime dependence.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from collections import OrderedDict
import warnings
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────────────

BASE = Path("/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round2")
DAYS = [-1, 0, 1]
FV = 10000

def load_prices(day):
    df = pd.read_csv(BASE / f"prices_round_2_day_{day}.csv", sep=";")
    df = df[df["product"] == "ASH_COATED_OSMIUM"].copy()
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["day"] = day
    return df

def load_trades(day):
    df = pd.read_csv(BASE / f"trades_round_2_day_{day}.csv", sep=";")
    df = df[df["symbol"] == "ASH_COATED_OSMIUM"].copy()
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["day"] = day
    return df

prices_all = pd.concat([load_prices(d) for d in DAYS], ignore_index=True)
trades_all = pd.concat([load_trades(d) for d in DAYS], ignore_index=True)

print(f"Loaded {len(prices_all)} price ticks, {len(trades_all)} trades across {len(DAYS)} days")
print(f"Price ticks per day: {prices_all.groupby('day').size().to_dict()}")
print(f"Trades per day: {trades_all.groupby('day').size().to_dict()}")
print()

# ─────────────────────────────────────────────────────────────────────
# FEATURE ENGINEERING
# ─────────────────────────────────────────────────────────────────────

def compute_signals(df_prices, df_trades):
    """Compute all signals for a single day."""
    df = df_prices.copy()

    # Basic columns
    bp1 = df["bid_price_1"].values.astype(float)
    bv1 = df["bid_volume_1"].values.astype(float)
    bp2 = df["bid_price_2"].values.astype(float)
    bv2 = df["bid_volume_2"].values.astype(float)
    bp3 = df["bid_price_3"].values.astype(float)
    bv3 = df["bid_volume_3"].values.astype(float)
    ap1 = df["ask_price_1"].values.astype(float)
    av1 = df["ask_volume_1"].values.astype(float)
    ap2 = df["ask_price_2"].values.astype(float)
    av2 = df["ask_volume_2"].values.astype(float)
    ap3 = df["ask_price_3"].values.astype(float)
    av3 = df["ask_volume_3"].values.astype(float)
    mid = df["mid_price"].values.astype(float)
    ts = df["timestamp"].values

    signals = pd.DataFrame(index=df.index)
    signals["timestamp"] = ts
    signals["mid"] = mid
    signals["day"] = df["day"].values

    # Forward returns at multiple horizons
    for h in [1, 3, 5, 10]:
        signals[f"fwd_ret_{h}"] = pd.Series(mid).diff(h).shift(-h).values

    # ── Signal 1: Microprice deviation from mid ──
    microprice = np.where(
        (bv1 + av1) > 0,
        (ap1 * bv1 + bp1 * av1) / (bv1 + av1),
        mid
    )
    signals["microprice_dev"] = microprice - mid

    # ── Signal 2: L2 depth imbalance ──
    total_bid = np.nansum([bv1, bv2, bv3], axis=0)
    total_ask = np.nansum([av1, av2, av3], axis=0)
    total_bid = np.where(np.isnan(total_bid), 0, total_bid)
    total_ask = np.where(np.isnan(total_ask), 0, total_ask)
    denom = total_bid + total_ask
    signals["l2_depth_imb"] = np.where(denom > 0, (total_bid - total_ask) / denom, 0)

    # ── Signal 3: L1 depth imbalance ──
    l1_denom = bv1 + av1
    signals["l1_depth_imb"] = np.where(
        l1_denom > 0,
        (bv1 - av1) / l1_denom,
        0
    )

    # ── Signal 4: Spread state (width) ──
    spread = ap1 - bp1
    signals["spread"] = spread

    # ── Signal 5: Spread change ──
    signals["spread_chg"] = pd.Series(spread).diff().values

    # ── Signal 6: Distance from FV=10000 (mean reversion) ──
    signals["dist_fv"] = mid - FV

    # ── Signal 7: Rolling mid momentum ──
    mid_s = pd.Series(mid)
    for w in [5, 10, 21]:
        signals[f"momentum_{w}"] = (mid_s - mid_s.rolling(w).mean()).values

    # ── Signal 8: Mid return autocorrelation (lagged returns) ──
    ret1 = mid_s.diff().values
    signals["lag_ret_1"] = np.roll(ret1, 0)  # current 1-tick return as signal for next
    signals["lag_ret_1"] = pd.Series(mid).diff().values  # last 1-tick return
    signals["lag_ret_3"] = pd.Series(mid).diff(3).values  # last 3-tick return

    # ── Signal 9: Wall-mid (largest-volume level mid) ──
    # Find largest bid volume level and largest ask volume level
    bid_vols = np.column_stack([
        np.nan_to_num(bv1), np.nan_to_num(bv2), np.nan_to_num(bv3)
    ])
    ask_vols = np.column_stack([
        np.nan_to_num(av1), np.nan_to_num(av2), np.nan_to_num(av3)
    ])
    bid_prices = np.column_stack([
        np.nan_to_num(bp1), np.nan_to_num(bp2), np.nan_to_num(bp3)
    ])
    ask_prices = np.column_stack([
        np.nan_to_num(ap1), np.nan_to_num(ap2), np.nan_to_num(ap3)
    ])

    best_bid_idx = np.argmax(bid_vols, axis=1)
    best_ask_idx = np.argmax(ask_vols, axis=1)
    wall_bid = bid_prices[np.arange(len(bid_prices)), best_bid_idx]
    wall_ask = ask_prices[np.arange(len(ask_prices)), best_ask_idx]
    wall_mid = (wall_bid + wall_ask) / 2.0
    # Where wall_bid or wall_ask is 0 (missing), use simple mid
    wall_mid = np.where((wall_bid > 0) & (wall_ask > 0), wall_mid, mid)
    signals["wall_mid_dev"] = wall_mid - mid

    # ── Signal 10: Trade flow imbalance ──
    # Classify trades as buyer/seller initiated based on price vs mid at that timestamp
    # Create a mid lookup by timestamp
    mid_lookup = dict(zip(ts, mid))

    # For each price tick, compute net trade flow in the recent window
    trade_flow = np.zeros(len(df))
    if len(df_trades) > 0:
        for i, t in enumerate(ts):
            # Trades in the last 5 ticks (500ms window)
            window_start = t - 500
            mask = (df_trades["timestamp"].values > window_start) & (df_trades["timestamp"].values <= t)
            if mask.any():
                recent = df_trades[mask]
                for _, tr in recent.iterrows():
                    # Find closest earlier mid for trade classification
                    tr_ts = tr["timestamp"]
                    earlier_ticks = ts[ts <= tr_ts]
                    if len(earlier_ticks) > 0:
                        ref_mid = mid_lookup.get(earlier_ticks[-1], FV)
                    else:
                        ref_mid = FV
                    # Classify: price > ref_mid => buyer initiated, price < ref_mid => seller initiated
                    if tr["price"] > ref_mid:
                        trade_flow[i] += tr["quantity"]
                    elif tr["price"] < ref_mid:
                        trade_flow[i] -= tr["quantity"]
                    # price == ref_mid: ambiguous, skip
    signals["trade_flow_imb"] = trade_flow

    # ── Signal 11: Trade arrival rate ──
    trade_count = np.zeros(len(df))
    trade_volume = np.zeros(len(df))
    if len(df_trades) > 0:
        for i, t in enumerate(ts):
            # Trades in last 10 ticks (1000ms)
            window_start = t - 1000
            mask = (df_trades["timestamp"].values > window_start) & (df_trades["timestamp"].values <= t)
            trade_count[i] = mask.sum()
            if mask.any():
                trade_volume[i] = df_trades.loc[mask, "quantity"].sum()
    signals["trade_arrival_10"] = trade_count
    signals["trade_volume_10"] = trade_volume

    # ── Signal 12: Realized volatility ──
    rets = mid_s.diff()
    for w in [10, 21]:
        signals[f"rvol_{w}"] = rets.rolling(w).std().values

    # ── Signal 13: Book pressure (gravity model) ──
    # sum(bid_vol * (mid - bid_price)) vs sum(ask_vol * (ask_price - mid))
    bid_gravity = (
        np.nan_to_num(bv1) * np.maximum(mid - np.nan_to_num(bp1), 0) +
        np.nan_to_num(bv2) * np.maximum(mid - np.nan_to_num(bp2), 0) +
        np.nan_to_num(bv3) * np.maximum(mid - np.nan_to_num(bp3), 0)
    )
    ask_gravity = (
        np.nan_to_num(av1) * np.maximum(np.nan_to_num(ap1) - mid, 0) +
        np.nan_to_num(av2) * np.maximum(np.nan_to_num(ap2) - mid, 0) +
        np.nan_to_num(av3) * np.maximum(np.nan_to_num(ap3) - mid, 0)
    )
    gravity_denom = bid_gravity + ask_gravity
    signals["book_pressure"] = np.where(
        gravity_denom > 0,
        (bid_gravity - ask_gravity) / gravity_denom,
        0
    )

    # ── Signal 14: L1 size ratio ──
    max_vol = np.maximum(bv1, av1)
    min_vol = np.minimum(bv1, av1)
    # Signed: positive if bid > ask, negative if ask > bid
    raw_ratio = np.where(min_vol > 0, max_vol / min_vol, np.nan)
    sign = np.where(bv1 > av1, 1, np.where(bv1 < av1, -1, 0))
    signals["l1_size_ratio"] = raw_ratio * sign

    # ── Signal 15: Composite signals ──
    # Microprice + mean reversion
    # Normalize each component to z-score over rolling window before combining
    mp_dev = pd.Series(signals["microprice_dev"].values)
    dist_fv_s = pd.Series(signals["dist_fv"].values)

    # Simple linear combo: microprice suggests short-term direction, dist_fv suggests reversion
    # For mean reversion, signal is -dist_fv (want to BUY when below FV)
    signals["composite_mp_mr"] = signals["microprice_dev"] - 0.1 * signals["dist_fv"]

    # Microprice + trade flow
    # Normalize trade_flow to same scale as microprice
    tf_std = np.nanstd(trade_flow[trade_flow != 0]) if np.any(trade_flow != 0) else 1.0
    mp_std = np.nanstd(signals["microprice_dev"].values)
    if mp_std > 0 and tf_std > 0:
        signals["composite_mp_tf"] = (
            signals["microprice_dev"] / mp_std +
            trade_flow / tf_std
        )
    else:
        signals["composite_mp_tf"] = signals["microprice_dev"]

    return signals


# Process each day
all_signals = []
for day in DAYS:
    print(f"Processing day {day}...")
    dp = prices_all[prices_all["day"] == day].copy().reset_index(drop=True)
    dt = trades_all[trades_all["day"] == day].copy().reset_index(drop=True)
    sigs = compute_signals(dp, dt)
    all_signals.append(sigs)
    print(f"  Day {day}: {len(sigs)} ticks, {len(dt)} trades")

pooled = pd.concat(all_signals, ignore_index=True)
print(f"\nPooled: {len(pooled)} ticks total")

# ─────────────────────────────────────────────────────────────────────
# SIGNAL NAMES
# ─────────────────────────────────────────────────────────────────────

SIGNAL_NAMES = OrderedDict([
    ("microprice_dev",    "1. Microprice dev"),
    ("l2_depth_imb",      "2. L2 depth imbalance"),
    ("l1_depth_imb",      "3. L1 depth imbalance"),
    ("spread",            "4. Spread state"),
    ("spread_chg",        "5. Spread change"),
    ("dist_fv",           "6. Distance from FV"),
    ("momentum_5",        "7a. Momentum MA(5)"),
    ("momentum_10",       "7b. Momentum MA(10)"),
    ("momentum_21",       "7c. Momentum MA(21)"),
    ("lag_ret_1",         "8a. Lag return (1)"),
    ("lag_ret_3",         "8b. Lag return (3)"),
    ("wall_mid_dev",      "9. Wall-mid dev"),
    ("trade_flow_imb",    "10. Trade flow imb"),
    ("trade_arrival_10",  "11a. Trade arrival"),
    ("trade_volume_10",   "11b. Trade volume"),
    ("rvol_10",           "12a. RVol(10)"),
    ("rvol_21",           "12b. RVol(21)"),
    ("book_pressure",     "13. Book pressure"),
    ("l1_size_ratio",     "14. L1 size ratio"),
    ("composite_mp_mr",   "15a. Composite MP+MR"),
    ("composite_mp_tf",   "15b. Composite MP+TF"),
])

HORIZONS = [1, 3, 5, 10]

# ─────────────────────────────────────────────────────────────────────
# IC AND SIGNAL QUALITY COMPUTATION
# ─────────────────────────────────────────────────────────────────────

def compute_ic(signal, forward_ret):
    """Rank IC (Spearman correlation) between signal and forward return."""
    mask = np.isfinite(signal) & np.isfinite(forward_ret)
    if mask.sum() < 30:
        return np.nan
    from scipy.stats import spearmanr
    corr, pval = spearmanr(signal[mask], forward_ret[mask])
    return corr

def compute_pearson_ic(signal, forward_ret):
    """Pearson IC."""
    mask = np.isfinite(signal) & np.isfinite(forward_ret)
    if mask.sum() < 30:
        return np.nan
    return np.corrcoef(signal[mask], forward_ret[mask])[0, 1]

def directional_accuracy(signal, forward_ret):
    """% of times signal correctly predicts direction of forward return."""
    mask = np.isfinite(signal) & np.isfinite(forward_ret) & (signal != 0) & (forward_ret != 0)
    if mask.sum() < 30:
        return np.nan
    s = signal[mask]
    r = forward_ret[mask]
    return 100.0 * np.mean(np.sign(s) == np.sign(r))

def quintile_spread(signal, forward_ret):
    """Mean return in top quintile (Q5) minus bottom quintile (Q1)."""
    mask = np.isfinite(signal) & np.isfinite(forward_ret)
    if mask.sum() < 50:
        return np.nan, np.nan, np.nan
    s = signal[mask]
    r = forward_ret[mask]
    q20 = np.percentile(s, 20)
    q80 = np.percentile(s, 80)
    # Handle ties at quantile boundaries
    q1_mask = s <= q20
    q5_mask = s >= q80
    if q1_mask.sum() == 0 or q5_mask.sum() == 0:
        return np.nan, np.nan, np.nan
    q1_ret = np.mean(r[q1_mask])
    q5_ret = np.mean(r[q5_mask])
    return q5_ret - q1_ret, q1_ret, q5_ret


def analyze_signal(data, sig_col, label):
    """Full analysis for one signal across all horizons."""
    sig = data[sig_col].values.astype(float)

    results = {"signal": label, "col": sig_col}

    for h in HORIZONS:
        fwd = data[f"fwd_ret_{h}"].values.astype(float)
        results[f"ic_{h}"] = compute_ic(sig, fwd)
        results[f"pearson_ic_{h}"] = compute_pearson_ic(sig, fwd)

    # Directional accuracy at 1-tick
    fwd1 = data["fwd_ret_1"].values.astype(float)
    results["dir_acc"] = directional_accuracy(sig, fwd1)

    # Quintile spread at 1-tick
    qs, q1r, q5r = quintile_spread(sig, fwd1)
    results["q5_q1"] = qs
    results["q1_ret"] = q1r
    results["q5_ret"] = q5r

    # Basic stats
    mask = np.isfinite(sig)
    results["mean"] = np.mean(sig[mask]) if mask.any() else np.nan
    results["std"] = np.std(sig[mask]) if mask.any() else np.nan
    results["pct_nonzero"] = 100.0 * np.mean(sig[mask] != 0) if mask.any() else 0

    return results


# ─────────────────────────────────────────────────────────────────────
# RUN ANALYSIS: PER-DAY AND POOLED
# ─────────────────────────────────────────────────────────────────────

from scipy.stats import spearmanr

print("\n" + "="*100)
print("PER-DAY IC (Spearman rank IC at 1-tick horizon)")
print("="*100)

per_day_results = {}
for day in DAYS:
    day_data = pooled[pooled["day"] == day].copy()
    day_results = []
    for col, label in SIGNAL_NAMES.items():
        r = analyze_signal(day_data, col, label)
        day_results.append(r)
    per_day_results[day] = day_results

# Print per-day IC table
header = f"{'Signal':<28}"
for d in DAYS:
    header += f" | Day {d:>2} IC_1"
header += " | Pooled IC_1"
print(header)
print("-" * len(header))

pooled_results = []
for col, label in SIGNAL_NAMES.items():
    r_pooled = analyze_signal(pooled, col, label)
    pooled_results.append(r_pooled)

    row = f"{label:<28}"
    for d in DAYS:
        day_r = [x for x in per_day_results[d] if x["col"] == col][0]
        ic1 = day_r["ic_1"]
        row += f" | {ic1:>10.4f}" if not np.isnan(ic1) else f" | {'NaN':>10}"
    ic1_p = r_pooled["ic_1"]
    row += f" | {ic1_p:>10.4f}" if not np.isnan(ic1_p) else f" | {'NaN':>10}"
    print(row)

# ─────────────────────────────────────────────────────────────────────
# MULTI-HORIZON IC DECAY
# ─────────────────────────────────────────────────────────────────────

print("\n" + "="*100)
print("MULTI-HORIZON IC DECAY (Pooled, Spearman)")
print("="*100)

header = f"{'Signal':<28}"
for h in HORIZONS:
    header += f" | IC_{h:>2}"
header += " | Decay 1->10"
print(header)
print("-" * len(header))

for r in pooled_results:
    row = f"{r['signal']:<28}"
    ics = []
    for h in HORIZONS:
        ic = r[f"ic_{h}"]
        row += f" | {ic:>6.4f}" if not np.isnan(ic) else f" | {'NaN':>6}"
        ics.append(ic)
    # Decay ratio
    if not np.isnan(ics[0]) and abs(ics[0]) > 0.001 and not np.isnan(ics[-1]):
        decay = ics[-1] / ics[0]
        row += f" | {decay:>10.2f}x"
    else:
        row += f" | {'N/A':>11}"
    print(row)

# ─────────────────────────────────────────────────────────────────────
# DIRECTIONAL ACCURACY AND QUINTILE ANALYSIS
# ─────────────────────────────────────────────────────────────────────

print("\n" + "="*100)
print("DIRECTIONAL ACCURACY & QUINTILE SPREAD (Pooled, 1-tick horizon)")
print("="*100)

header = f"{'Signal':<28} | {'DirAcc%':>8} | {'Q5-Q1':>8} | {'Q1 ret':>8} | {'Q5 ret':>8} | {'%nonzero':>8}"
print(header)
print("-" * len(header))

for r in pooled_results:
    da = r["dir_acc"]
    qs = r["q5_q1"]
    q1r = r["q1_ret"]
    q5r = r["q5_ret"]
    pnz = r["pct_nonzero"]

    da_s = f"{da:>8.2f}" if not np.isnan(da) else f"{'NaN':>8}"
    qs_s = f"{qs:>8.4f}" if not np.isnan(qs) else f"{'NaN':>8}"
    q1_s = f"{q1r:>8.4f}" if not np.isnan(q1r) else f"{'NaN':>8}"
    q5_s = f"{q5r:>8.4f}" if not np.isnan(q5r) else f"{'NaN':>8}"

    print(f"{r['signal']:<28} | {da_s} | {qs_s} | {q1_s} | {q5_s} | {pnz:>8.1f}")

# ─────────────────────────────────────────────────────────────────────
# SIGNAL CORRELATION MATRIX
# ─────────────────────────────────────────────────────────────────────

print("\n" + "="*100)
print("SIGNAL CORRELATION MATRIX (Pooled, Spearman rank)")
print("="*100)

sig_cols = list(SIGNAL_NAMES.keys())
sig_labels_short = [
    "MPdev", "L2imb", "L1imb", "Sprd", "SprdChg", "DistFV",
    "Mom5", "Mom10", "Mom21", "LagR1", "LagR3", "WallMid",
    "TF_imb", "TArr", "TVol", "RV10", "RV21", "BookP",
    "L1Rat", "CmpMR", "CmpTF"
]

corr_data = pooled[sig_cols].copy()
# Replace inf with nan
corr_data = corr_data.replace([np.inf, -np.inf], np.nan)
corr_matrix = corr_data.corr(method="spearman")

# Print abbreviated correlation matrix (top triangle only)
n = len(sig_labels_short)
# Print header
print(f"{'':>8}", end="")
for lbl in sig_labels_short:
    print(f" {lbl[:6]:>6}", end="")
print()

for i in range(n):
    print(f"{sig_labels_short[i][:8]:>8}", end="")
    for j in range(n):
        if j < i:
            print(f" {'':>6}", end="")
        else:
            val = corr_matrix.iloc[i, j]
            if np.isnan(val):
                print(f" {'NaN':>6}", end="")
            else:
                print(f" {val:>6.2f}", end="")
    print()

# Highlight highly correlated pairs (|rho| > 0.5)
print("\nHighly correlated signal pairs (|rho| > 0.5):")
for i in range(n):
    for j in range(i+1, n):
        val = corr_matrix.iloc[i, j]
        if not np.isnan(val) and abs(val) > 0.5:
            print(f"  {sig_labels_short[i]} <-> {sig_labels_short[j]}: rho = {val:.3f}")

# ─────────────────────────────────────────────────────────────────────
# REGIME ANALYSIS: TIGHT vs WIDE SPREAD
# ─────────────────────────────────────────────────────────────────────

print("\n" + "="*100)
print("REGIME ANALYSIS: Tight spread (<=14) vs Wide spread (>=16)")
print("="*100)

# Check spread distribution first
spread_vals = pooled["spread"].dropna()
print(f"\nSpread distribution:")
for s in sorted(spread_vals.unique()):
    pct = 100.0 * (spread_vals == s).mean()
    if pct > 0.1:
        print(f"  Spread = {s:.0f}: {pct:.1f}% of ticks")

tight_mask = pooled["spread"] <= 14
wide_mask = pooled["spread"] >= 16
print(f"\nTight (<=14): {tight_mask.sum()} ticks ({100*tight_mask.mean():.1f}%)")
print(f"Wide  (>=16): {wide_mask.sum()} ticks ({100*wide_mask.mean():.1f}%)")

header = f"{'Signal':<28} | {'IC_tight':>10} | {'IC_wide':>10} | {'Delta':>10}"
print(header)
print("-" * len(header))

for col, label in SIGNAL_NAMES.items():
    sig_t = pooled.loc[tight_mask, col].values.astype(float)
    fwd_t = pooled.loc[tight_mask, "fwd_ret_1"].values.astype(float)
    sig_w = pooled.loc[wide_mask, col].values.astype(float)
    fwd_w = pooled.loc[wide_mask, "fwd_ret_1"].values.astype(float)

    ic_tight = compute_ic(sig_t, fwd_t)
    ic_wide = compute_ic(sig_w, fwd_w)

    delta = ic_wide - ic_tight if (not np.isnan(ic_tight) and not np.isnan(ic_wide)) else np.nan

    t_s = f"{ic_tight:>10.4f}" if not np.isnan(ic_tight) else f"{'NaN':>10}"
    w_s = f"{ic_wide:>10.4f}" if not np.isnan(ic_wide) else f"{'NaN':>10}"
    d_s = f"{delta:>10.4f}" if not np.isnan(delta) else f"{'NaN':>10}"

    print(f"{label:<28} | {t_s} | {w_s} | {d_s}")

# ─────────────────────────────────────────────────────────────────────
# PEARSON vs SPEARMAN COMPARISON
# ─────────────────────────────────────────────────────────────────────

print("\n" + "="*100)
print("PEARSON vs SPEARMAN IC (Pooled, 1-tick)")
print("="*100)

header = f"{'Signal':<28} | {'Spearman':>10} | {'Pearson':>10} | {'Diff':>10}"
print(header)
print("-" * len(header))

for r in pooled_results:
    sp = r["ic_1"]
    pe = r["pearson_ic_1"]
    diff = pe - sp if (not np.isnan(sp) and not np.isnan(pe)) else np.nan
    sp_s = f"{sp:>10.4f}" if not np.isnan(sp) else f"{'NaN':>10}"
    pe_s = f"{pe:>10.4f}" if not np.isnan(pe) else f"{'NaN':>10}"
    d_s = f"{diff:>10.4f}" if not np.isnan(diff) else f"{'NaN':>10}"
    print(f"{r['signal']:<28} | {sp_s} | {pe_s} | {d_s}")

# ─────────────────────────────────────────────────────────────────────
# IC STABILITY ACROSS DAYS
# ─────────────────────────────────────────────────────────────────────

print("\n" + "="*100)
print("IC STABILITY: Per-day IC_1, Mean, Std, IC_IR (Mean/Std)")
print("="*100)

header = f"{'Signal':<28}"
for d in DAYS:
    header += f" | Day {d:>2}"
header += " | {'Mean':>7} | {'Std':>7} | {'IC_IR':>7}"
print(f"{'Signal':<28} | {'Day -1':>8} | {'Day 0':>8} | {'Day 1':>8} | {'Mean':>8} | {'Std':>8} | {'IC_IR':>8}")
print("-" * 90)

for col, label in SIGNAL_NAMES.items():
    day_ics = []
    row = f"{label:<28}"
    for d in DAYS:
        day_r = [x for x in per_day_results[d] if x["col"] == col][0]
        ic1 = day_r["ic_1"]
        day_ics.append(ic1)
        row += f" | {ic1:>8.4f}" if not np.isnan(ic1) else f" | {'NaN':>8}"

    valid_ics = [x for x in day_ics if not np.isnan(x)]
    if len(valid_ics) >= 2:
        m = np.mean(valid_ics)
        s = np.std(valid_ics)
        ir = m / s if s > 0.001 else np.nan
        row += f" | {m:>8.4f} | {s:>8.4f}"
        row += f" | {ir:>8.2f}" if not np.isnan(ir) else f" | {'NaN':>8}"
    else:
        row += f" | {'N/A':>8} | {'N/A':>8} | {'N/A':>8}"
    print(row)

# ─────────────────────────────────────────────────────────────────────
# FINAL SUMMARY TABLE (RANKED BY |IC_1|)
# ─────────────────────────────────────────────────────────────────────

print("\n" + "="*100)
print("FINAL SUMMARY: Signals ranked by |IC_1| (Pooled Spearman)")
print("="*100)

# Sort by absolute IC at 1-tick
sorted_results = sorted(pooled_results, key=lambda x: abs(x["ic_1"]) if not np.isnan(x["ic_1"]) else 0, reverse=True)

header = f"{'Rank':>4} | {'Signal':<28} | {'IC_1':>8} | {'IC_3':>8} | {'IC_5':>8} | {'IC_10':>8} | {'DirAcc%':>8} | {'Q5-Q1':>10}"
print(header)
print("-" * len(header))

for rank, r in enumerate(sorted_results, 1):
    ic1 = r["ic_1"]
    ic3 = r["ic_3"]
    ic5 = r["ic_5"]
    ic10 = r["ic_10"]
    da = r["dir_acc"]
    qs = r["q5_q1"]

    ic1_s = f"{ic1:>8.4f}" if not np.isnan(ic1) else f"{'NaN':>8}"
    ic3_s = f"{ic3:>8.4f}" if not np.isnan(ic3) else f"{'NaN':>8}"
    ic5_s = f"{ic5:>8.4f}" if not np.isnan(ic5) else f"{'NaN':>8}"
    ic10_s = f"{ic10:>8.4f}" if not np.isnan(ic10) else f"{'NaN':>8}"
    da_s = f"{da:>8.2f}" if not np.isnan(da) else f"{'NaN':>8}"
    qs_s = f"{qs:>10.4f}" if not np.isnan(qs) else f"{'NaN':>10}"

    print(f"{rank:>4} | {r['signal']:<28} | {ic1_s} | {ic3_s} | {ic5_s} | {ic10_s} | {da_s} | {qs_s}")

# ─────────────────────────────────────────────────────────────────────
# BONUS: SIGNAL STATISTICS
# ─────────────────────────────────────────────────────────────────────

print("\n" + "="*100)
print("SIGNAL STATISTICS (Pooled)")
print("="*100)

header = f"{'Signal':<28} | {'Mean':>10} | {'Std':>10} | {'Min':>10} | {'Max':>10} | {'%NaN':>8}"
print(header)
print("-" * len(header))

for col, label in SIGNAL_NAMES.items():
    vals = pooled[col].values.astype(float)
    finite = vals[np.isfinite(vals)]
    nan_pct = 100.0 * (1 - len(finite) / len(vals)) if len(vals) > 0 else 100
    if len(finite) > 0:
        print(f"{label:<28} | {np.mean(finite):>10.4f} | {np.std(finite):>10.4f} | {np.min(finite):>10.4f} | {np.max(finite):>10.4f} | {nan_pct:>8.1f}")
    else:
        print(f"{label:<28} | {'NaN':>10} | {'NaN':>10} | {'NaN':>10} | {'NaN':>10} | {nan_pct:>8.1f}")

print("\n" + "="*100)
print("ANALYSIS COMPLETE")
print("="*100)
