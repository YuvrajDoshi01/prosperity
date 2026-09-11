"""
Wall Mid Fair Value Analysis for TOMATOES
Comprehensive analysis of Wall Mid variants vs microprice vs asymmetric move classifier
"""

import pandas as pd
import numpy as np
from collections import defaultdict

# ============================================================
# SECTION 1: Load and Parse Data
# ============================================================

def load_day(day_num):
    """Load CSV and extract TOMATOES rows with proper column parsing."""
    path = f"prosperity4bt/resources/round0/prices_round_0_day_{day_num}.csv"
    df = pd.read_csv(path, sep=';')
    tom = df[df['product'] == 'TOMATOES'].copy().reset_index(drop=True)

    # Rename for clarity
    tom = tom.rename(columns={
        'bid_price_1': 'bp1', 'bid_volume_1': 'bv1',
        'bid_price_2': 'bp2', 'bid_volume_2': 'bv2',
        'bid_price_3': 'bp3', 'bid_volume_3': 'bv3',
        'ask_price_1': 'ap1', 'ask_volume_1': 'av1',
        'ask_price_2': 'ap2', 'ask_volume_2': 'av2',
        'ask_price_3': 'ap3', 'ask_volume_3': 'av3',
    })

    # Fill NaN volumes with 0
    for col in ['bv1','bv2','bv3','av1','av2','av3','bp2','bp3','ap2','ap3']:
        tom[col] = tom[col].fillna(0)

    return tom

print("=" * 80)
print("WALL MID ANALYSIS FOR TOMATOES")
print("=" * 80)

days = {}
for d in [0, -1, -2]:
    days[d] = load_day(d)
    print(f"Day {d}: {len(days[d])} TOMATOES ticks")

print()

# ============================================================
# SECTION 2: Compute All Wall Mid Variants
# ============================================================

def compute_variants(df):
    """Compute all Wall Mid variants on a TOMATOES dataframe."""

    bp1, bv1 = df['bp1'].values, df['bv1'].values.astype(float)
    bp2, bv2 = df['bp2'].values, df['bv2'].values.astype(float)
    ap1, av1 = df['ap1'].values, df['av1'].values.astype(float)
    ap2, av2 = df['ap2'].values, df['av2'].values.astype(float)
    mid = df['mid_price'].values

    spread = ap1 - bp1
    n = len(df)

    results = {}
    results['mid'] = mid
    results['spread'] = spread
    results['bp1'] = bp1
    results['ap1'] = ap1
    results['bv1'] = bv1
    results['av1'] = av1
    results['bv2'] = bv2
    results['av2'] = av2

    # --- 1. Simple Wall Mid (binary: bigger L1 side wins) ---
    simple_wm = np.where(bv1 > av1, ap1.astype(float),   # bid wall -> price goes up -> FV = ask
                np.where(av1 > bv1, bp1.astype(float),    # ask wall -> price goes down -> FV = bid
                mid))                                      # equal -> mid
    results['simple_wall_mid'] = simple_wm

    # --- 2. L1 Microprice (= volume-weighted wall mid) ---
    total_v1 = bv1 + av1
    microprice = np.where(total_v1 > 0,
                         bp1 + (bv1 / total_v1) * (ap1 - bp1),
                         mid)
    results['microprice'] = microprice

    # --- 3. L2 Wall Mid (L2 volumes only, binary) ---
    l2_wm = np.where(bv2 > av2, ap1.astype(float),
            np.where(av2 > bv2, bp1.astype(float),
            mid))
    results['l2_wall_mid'] = l2_wm

    # --- 4. Threshold Wall Mid variants ---
    for thresh in [1.5, 2.0, 3.0]:
        ratio = np.where(av1 > 0, bv1 / av1, 1.0)
        twm = np.where(ratio > thresh, ap1.astype(float),    # bid vol >> ask vol -> up
              np.where(ratio < 1.0/thresh, bp1.astype(float), # ask vol >> bid vol -> down
              mid))
        results[f'threshold_{thresh}_wall_mid'] = twm

    # --- 5. "True Wall Mid" (volume INCREASED side is wall) ---
    # Track volume changes tick-to-tick
    bv1_change = np.zeros(n)
    av1_change = np.zeros(n)
    bv1_change[1:] = bv1[1:] - bv1[:-1]
    av1_change[1:] = av1[1:] - av1[:-1]

    true_wm = np.where(bv1_change > av1_change, ap1.astype(float),  # bid increased more -> wall on bid -> up
             np.where(av1_change > bv1_change, bp1.astype(float),   # ask increased more -> wall on ask -> down
             mid))
    results['true_wall_mid'] = true_wm

    # --- 6. Cross-level Wall Mid (L1+L2 total volume) ---
    total_bid = bv1 + bv2
    total_ask = av1 + av2
    cross_wm = np.where(total_bid > total_ask, ap1.astype(float),
              np.where(total_ask > total_bid, bp1.astype(float),
              mid))
    results['cross_level_wall_mid'] = cross_wm

    # --- 7. Cross-level microprice ---
    total_all = total_bid + total_ask
    cross_mp = np.where(total_all > 0,
                       bp1 + (total_bid / total_all) * (ap1 - bp1),
                       mid)
    results['cross_level_microprice'] = cross_mp

    # --- 8. Delta Wall Mid (volume change signal) ---
    delta_signal = bv1_change - av1_change
    # Shift FV by K * delta_signal, clipped to [bid, ask]
    for K in [0.5, 1.0, 2.0]:
        delta_wm = mid + delta_signal * K
        delta_wm = np.clip(delta_wm, bp1, ap1)
        results[f'delta_wall_mid_K{K}'] = delta_wm

    # --- 9. L2 microprice ---
    l2_total = bv2 + av2
    l2_mp = np.where(l2_total > 0,
                    bp1 + (bv2 / l2_total) * (ap1 - bp1),
                    mid)
    results['l2_microprice'] = l2_mp

    # --- 10. Threshold L2 Wall Mid ---
    for thresh in [1.5, 2.0]:
        ratio_l2 = np.where(av2 > 0, bv2 / av2, 1.0)
        twm_l2 = np.where(ratio_l2 > thresh, ap1.astype(float),
                 np.where(ratio_l2 < 1.0/thresh, bp1.astype(float),
                 mid))
        results[f'threshold_l2_{thresh}_wall_mid'] = twm_l2

    return results

# Compute for all days
all_results = {}
for d in [0, -1, -2]:
    all_results[d] = compute_variants(days[d])

# ============================================================
# SECTION 3: Signal Frequency Analysis
# ============================================================

print("=" * 80)
print("SECTION 3: HOW OFTEN DOES EACH VARIANT DIFFER FROM MID?")
print("=" * 80)

variant_names = [
    'simple_wall_mid', 'microprice', 'l2_wall_mid',
    'threshold_1.5_wall_mid', 'threshold_2.0_wall_mid', 'threshold_3.0_wall_mid',
    'true_wall_mid', 'cross_level_wall_mid', 'cross_level_microprice',
    'delta_wall_mid_K0.5', 'delta_wall_mid_K1.0', 'delta_wall_mid_K2.0',
    'l2_microprice', 'threshold_l2_1.5_wall_mid', 'threshold_l2_2.0_wall_mid',
]

for d in [0, -1, -2]:
    r = all_results[d]
    mid = r['mid']
    n = len(mid)
    print(f"\n--- Day {d} ({n} ticks) ---")
    print(f"{'Variant':<35} {'Differs from mid':>18} {'Pct':>8}")
    print("-" * 65)
    for vn in variant_names:
        v = r[vn]
        differs = np.sum(np.abs(v - mid) > 1e-6)
        print(f"{vn:<35} {differs:>18} {differs/n*100:>7.2f}%")

# L1 symmetry analysis
print("\n" + "=" * 80)
print("L1 VOLUME SYMMETRY BY SPREAD")
print("=" * 80)

for d in [0, -1, -2]:
    r = all_results[d]
    spread = r['spread']
    bv1, av1 = r['bv1'], r['av1']
    n = len(spread)

    print(f"\n--- Day {d} ---")
    print(f"{'Spread':>8} {'Count':>8} {'Symmetric':>10} {'Pct':>8} {'bv1>av1':>8} {'av1>bv1':>8}")
    print("-" * 60)

    for s in sorted(np.unique(spread)):
        mask = spread == s
        cnt = np.sum(mask)
        sym = np.sum((bv1[mask] == av1[mask]))
        bgt = np.sum(bv1[mask] > av1[mask])
        agt = np.sum(av1[mask] > bv1[mask])
        print(f"{s:>8.0f} {cnt:>8} {sym:>10} {sym/cnt*100:>7.1f}% {bgt:>8} {agt:>8}")

# ============================================================
# SECTION 4: Predictive Metrics
# ============================================================

print("\n" + "=" * 80)
print("SECTION 4: PREDICTIVE METRICS (correlation, accuracy, RMSE)")
print("=" * 80)

def compute_metrics(r, variant_name):
    """Compute predictive metrics for a variant."""
    v = r[variant_name]
    mid = r['mid']
    n = len(mid)

    # Next-tick mid change
    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    # Signal: deviation from mid
    signal = v - mid

    # Correlation with next-tick mid change (exclude last tick)
    valid = slice(0, n-1)
    if np.std(signal[valid]) < 1e-10:
        corr = 0.0
    else:
        corr = np.corrcoef(signal[valid], dmid[valid])[0, 1]

    # Directional accuracy (only on ticks where signal != 0 AND dmid != 0)
    sig_dir = np.sign(signal[valid])
    mid_dir = np.sign(dmid[valid])
    active = (sig_dir != 0) & (mid_dir != 0)
    if np.sum(active) > 0:
        accuracy = np.mean(sig_dir[active] == mid_dir[active])
        n_active = np.sum(active)
    else:
        accuracy = np.nan
        n_active = 0

    # RMSE as next-mid predictor
    # Variant predicts next mid = v[t], vs baseline: next mid = mid[t]
    next_mid = np.zeros(n)
    next_mid[:-1] = mid[1:]
    next_mid[-1] = mid[-1]

    rmse_variant = np.sqrt(np.mean((v[valid] - next_mid[valid])**2))
    rmse_mid = np.sqrt(np.mean((mid[valid] - next_mid[valid])**2))

    return {
        'corr': corr,
        'accuracy': accuracy,
        'n_active': n_active,
        'rmse_variant': rmse_variant,
        'rmse_mid': rmse_mid,
        'rmse_improvement': rmse_mid - rmse_variant,
    }

for d in [0, -1, -2]:
    r = all_results[d]
    n = len(r['mid'])
    print(f"\n--- Day {d} ({n} ticks) ---")
    print(f"{'Variant':<35} {'Corr':>8} {'DirAcc':>8} {'N_active':>10} {'RMSE_var':>10} {'RMSE_mid':>10} {'RMSE_impr':>10}")
    print("-" * 95)

    for vn in variant_names:
        m = compute_metrics(r, vn)
        print(f"{vn:<35} {m['corr']:>8.4f} {m['accuracy']:>8.3f} {m['n_active']:>10} {m['rmse_variant']:>10.4f} {m['rmse_mid']:>10.4f} {m['rmse_improvement']:>10.4f}")

# ============================================================
# SECTION 5: Narrow vs Wide Spread Decomposition
# ============================================================

print("\n" + "=" * 80)
print("SECTION 5: NARROW vs WIDE SPREAD DECOMPOSITION")
print("The critical question: Wall Mid's signal comes only from asymmetric ticks")
print("=" * 80)

for d in [0, -1, -2]:
    r = all_results[d]
    mid = r['mid']
    spread = r['spread']
    n = len(mid)

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    narrow_mask = spread <= 9
    wide_mask = spread >= 13

    print(f"\n--- Day {d} ---")
    print(f"Narrow spread (<=9): {np.sum(narrow_mask)} ticks ({np.sum(narrow_mask)/n*100:.1f}%)")
    print(f"Wide spread (>=13):  {np.sum(wide_mask)} ticks ({np.sum(wide_mask)/n*100:.1f}%)")

    # For key variants, compute metrics on narrow vs wide separately
    key_variants = ['simple_wall_mid', 'microprice', 'l2_wall_mid', 'cross_level_wall_mid',
                    'true_wall_mid', 'cross_level_microprice']

    for regime_name, mask in [("NARROW (<=9)", narrow_mask), ("WIDE (>=13)", wide_mask)]:
        print(f"\n  {regime_name} ticks:")
        print(f"  {'Variant':<35} {'Corr':>8} {'DirAcc':>8} {'N_active':>10} {'Signal!=0':>10}")
        print("  " + "-" * 75)

        idx = np.where(mask)[0]
        # Exclude last tick of day
        idx = idx[idx < n-1]

        for vn in key_variants:
            v = r[vn]
            signal = v - mid
            sig_vals = signal[idx]
            dmid_vals = dmid[idx]

            n_signal = np.sum(np.abs(sig_vals) > 1e-6)

            if np.std(sig_vals) < 1e-10:
                corr = 0.0
            else:
                corr = np.corrcoef(sig_vals, dmid_vals)[0, 1]

            sig_dir = np.sign(sig_vals)
            mid_dir = np.sign(dmid_vals)
            active = (sig_dir != 0) & (mid_dir != 0)
            if np.sum(active) > 0:
                acc = np.mean(sig_dir[active] == mid_dir[active])
                n_act = np.sum(active)
            else:
                acc = np.nan
                n_act = 0

            print(f"  {vn:<35} {corr:>8.4f} {acc:>8.3f} {n_act:>10} {n_signal:>10}")

# ============================================================
# SECTION 6: Expected PnL from Wall Mid on Narrow Spread Ticks
# ============================================================

print("\n" + "=" * 80)
print("SECTION 6: EXPECTED PNL FROM WALL MID SIGNAL ON NARROW SPREAD TICKS")
print("=" * 80)

for d in [0, -1, -2]:
    r = all_results[d]
    mid = r['mid']
    spread = r['spread']
    n = len(mid)

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    narrow = np.where((spread <= 9) & (np.arange(n) < n-1))[0]

    print(f"\n--- Day {d} ({len(narrow)} narrow ticks) ---")

    for vn in ['simple_wall_mid', 'microprice', 'cross_level_wall_mid', 'true_wall_mid']:
        v = r[vn]
        signal = v[narrow] - mid[narrow]
        next_dmid = dmid[narrow]

        # PnL if we trade 1 unit in signal direction at mid
        pnl_per_tick = np.sign(signal) * next_dmid

        # Only on active ticks
        active = np.abs(signal) > 1e-6
        if np.sum(active) > 0:
            total_pnl = np.sum(pnl_per_tick[active])
            avg_pnl = np.mean(pnl_per_tick[active])
            n_trades = np.sum(active)
            win_rate = np.mean(pnl_per_tick[active] > 0)
            # Realistic: trade at mid + 0.5*spread cost
            half_spread_cost = spread[narrow][active] / 2.0
            net_pnl = np.sum(np.abs(signal[active]) * np.sign(signal[active]) * next_dmid[active])
        else:
            total_pnl = 0
            avg_pnl = 0
            n_trades = 0
            win_rate = 0

        print(f"  {vn:<35} Trades: {n_trades:>5}  TotalPnL: {total_pnl:>8.1f}  AvgPnL: {avg_pnl:>6.3f}  WinRate: {win_rate:>5.1%}")

# ============================================================
# SECTION 7: Novel Wall Mid Ideas
# ============================================================

print("\n" + "=" * 80)
print("SECTION 7: NOVEL WALL MID IDEAS")
print("=" * 80)

for d in [0, -1, -2]:
    r = all_results[d]
    mid = r['mid']
    n = len(mid)

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    print(f"\n--- Day {d} ---")

    novel_variants = [
        'true_wall_mid',           # volume increased side = wall
        'delta_wall_mid_K0.5',
        'delta_wall_mid_K1.0',
        'delta_wall_mid_K2.0',
        'cross_level_wall_mid',
        'cross_level_microprice',
        'l2_microprice',
        'threshold_l2_1.5_wall_mid',
        'threshold_l2_2.0_wall_mid',
    ]

    print(f"  {'Variant':<35} {'Corr':>8} {'DirAcc':>8} {'N_active':>10} {'SumPnL':>10} {'AvgPnL':>10}")
    print("  " + "-" * 85)

    for vn in novel_variants:
        v = r[vn]
        signal = v - mid
        valid = slice(0, n-1)

        if np.std(signal[valid]) < 1e-10:
            corr = 0.0
        else:
            corr = np.corrcoef(signal[valid], dmid[valid])[0, 1]

        sig_dir = np.sign(signal[valid])
        mid_dir = np.sign(dmid[valid])
        active = (sig_dir != 0) & (mid_dir != 0)

        if np.sum(active) > 0:
            acc = np.mean(sig_dir[active] == mid_dir[active])
            n_act = np.sum(active)
            pnl = np.sum(np.sign(signal[valid][active]) * dmid[valid][active])
            avg_pnl = pnl / n_act
        else:
            acc = np.nan
            n_act = 0
            pnl = 0
            avg_pnl = 0

        print(f"  {vn:<35} {corr:>8.4f} {acc:>8.3f} {n_act:>10} {pnl:>10.1f} {avg_pnl:>10.4f}")

# ============================================================
# SECTION 8: Asymmetric Move Classifier
# ============================================================

print("\n" + "=" * 80)
print("SECTION 8: ASYMMETRIC MOVE CLASSIFIER vs WALL MID")
print("=" * 80)

def compute_asymmetric_classifier(r):
    """
    Asymmetric move classifier: when bid and ask move by different amounts,
    predict continuation in the direction of the larger move.
    """
    bp1, ap1 = r['bp1'], r['ap1']
    mid = r['mid']
    n = len(mid)

    # Bid and ask changes
    dbid = np.zeros(n)
    dask = np.zeros(n)
    dbid[1:] = bp1[1:] - bp1[:-1]
    dask[1:] = ap1[1:] - ap1[:-1]

    # Asymmetric = bid moved differently than ask
    is_asymmetric = np.abs(dbid - dask) > 0.5

    # Signal: direction of larger move
    # If bid moved more, expect mid to catch up (up if bid up more, down if bid down more)
    # Actually: if ask moved up more than bid, expect up continuation
    # If bid moved down more than ask, expect down continuation
    asym_signal = np.zeros(n)
    # The "faster" side predicts direction
    # If dask > dbid: ask is leading upward -> expect UP
    # If dbid < dask: bid is leading downward -> expect DOWN
    asym_signal = dask - dbid  # positive = ask moving up faster = bullish

    return is_asymmetric, asym_signal

for d in [0, -1, -2]:
    r = all_results[d]
    mid = r['mid']
    n = len(mid)

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    is_asym, asym_signal = compute_asymmetric_classifier(r)

    print(f"\n--- Day {d} ---")
    print(f"Asymmetric ticks: {np.sum(is_asym)} ({np.sum(is_asym)/n*100:.1f}%)")

    # Metrics for asymmetric classifier
    valid = slice(1, n-1)  # skip first tick (no previous) and last (no next)

    asym_idx = np.where(is_asym[1:n-1])[0] + 1
    if len(asym_idx) > 0:
        sig = asym_signal[asym_idx]
        dm = dmid[asym_idx]

        corr_asym = np.corrcoef(sig, dm)[0, 1] if np.std(sig) > 1e-10 else 0

        active_a = (np.sign(sig) != 0) & (np.sign(dm) != 0)
        acc_asym = np.mean(np.sign(sig[active_a]) == np.sign(dm[active_a])) if np.sum(active_a) > 0 else 0
        pnl_asym = np.sum(np.sign(sig[active_a]) * dm[active_a]) if np.sum(active_a) > 0 else 0

        print(f"Asymmetric classifier: Corr={corr_asym:.4f}, Acc={acc_asym:.3f}, N={np.sum(active_a)}, PnL={pnl_asym:.1f}")

    # Now compare: on the SAME asymmetric ticks, what does each Wall Mid variant say?
    print(f"\n  On asymmetric ticks, compare signals:")
    print(f"  {'Variant':<35} {'Corr_w_asym':>12} {'Same_sign':>10} {'DirAcc':>8} {'PnL':>10}")
    print("  " + "-" * 80)

    key_variants = ['simple_wall_mid', 'microprice', 'l2_wall_mid', 'cross_level_wall_mid',
                    'true_wall_mid', 'cross_level_microprice']

    for vn in key_variants:
        v = r[vn]
        wm_signal = v - mid

        wm_on_asym = wm_signal[asym_idx]
        asym_on_asym = asym_signal[asym_idx]
        dm_on_asym = dmid[asym_idx]

        # Correlation between Wall Mid signal and asymmetric signal
        if np.std(wm_on_asym) > 1e-10 and np.std(asym_on_asym) > 1e-10:
            corr_wa = np.corrcoef(wm_on_asym, asym_on_asym)[0, 1]
        else:
            corr_wa = 0.0

        # Same sign rate
        both_active = (np.abs(wm_on_asym) > 1e-6) & (np.abs(asym_on_asym) > 1e-6)
        if np.sum(both_active) > 0:
            same_sign = np.mean(np.sign(wm_on_asym[both_active]) == np.sign(asym_on_asym[both_active]))
        else:
            same_sign = np.nan

        # Wall Mid accuracy on these ticks
        wm_active = (np.abs(wm_on_asym) > 1e-6) & (np.abs(dm_on_asym) > 1e-6)
        if np.sum(wm_active) > 0:
            acc_wm = np.mean(np.sign(wm_on_asym[wm_active]) == np.sign(dm_on_asym[wm_active]))
            pnl_wm = np.sum(np.sign(wm_on_asym[wm_active]) * dm_on_asym[wm_active])
        else:
            acc_wm = np.nan
            pnl_wm = 0

        print(f"  {vn:<35} {corr_wa:>12.4f} {same_sign:>10.3f} {acc_wm:>8.3f} {pnl_wm:>10.1f}")

# ============================================================
# SECTION 9: Complementarity Analysis
# ============================================================

print("\n" + "=" * 80)
print("SECTION 9: COMPLEMENTARITY — CAN WALL MID ADD TO ASYMMETRIC CLASSIFIER?")
print("=" * 80)

for d in [0, -1, -2]:
    r = all_results[d]
    mid = r['mid']
    n = len(mid)

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    is_asym, asym_signal = compute_asymmetric_classifier(r)

    print(f"\n--- Day {d} ---")

    # Four quadrants: asym fires vs not, wall mid fires vs not
    for vn in ['simple_wall_mid', 'cross_level_wall_mid', 'true_wall_mid']:
        v = r[vn]
        wm_signal = v - mid
        wm_fires = np.abs(wm_signal) > 1e-6

        # Quadrant analysis (skip tick 0 and last)
        q = np.zeros(n, dtype=int)
        q[(is_asym) & (wm_fires)] = 1   # both fire
        q[(is_asym) & (~wm_fires)] = 2  # only asym
        q[(~is_asym) & (wm_fires)] = 3  # only wm
        q[(~is_asym) & (~wm_fires)] = 4 # neither

        print(f"\n  {vn}:")
        for qi, label in [(1, "Both fire"), (2, "Only asym"), (3, "Only WM"), (4, "Neither")]:
            idx = np.where((q == qi) & (np.arange(n) > 0) & (np.arange(n) < n-1))[0]
            if len(idx) == 0:
                print(f"    {label:<20} N={0:>6}")
                continue

            dm = dmid[idx]
            n_move = np.sum(np.abs(dm) > 1e-6)

            # For "both fire" and "only WM", check WM accuracy
            if qi in [1, 3]:
                sig = np.sign(wm_signal[idx])
                active = (sig != 0) & (np.sign(dm) != 0)
                if np.sum(active) > 0:
                    acc = np.mean(sig[active] == np.sign(dm[active]))
                    pnl = np.sum(sig[active] * dm[active])
                    print(f"    {label:<20} N={len(idx):>6}  WM_Acc={acc:.3f}  WM_PnL={pnl:.1f}")
                else:
                    print(f"    {label:<20} N={len(idx):>6}  WM_Acc=N/A")
            elif qi == 2:
                sig = np.sign(asym_signal[idx])
                active = (sig != 0) & (np.sign(dm) != 0)
                if np.sum(active) > 0:
                    acc = np.mean(sig[active] == np.sign(dm[active]))
                    pnl = np.sum(sig[active] * dm[active])
                    print(f"    {label:<20} N={len(idx):>6}  Asym_Acc={acc:.3f}  Asym_PnL={pnl:.1f}")
                else:
                    print(f"    {label:<20} N={len(idx):>6}  Asym_Acc=N/A")
            else:
                avg_abs_dm = np.mean(np.abs(dm))
                print(f"    {label:<20} N={len(idx):>6}  Avg|dmid|={avg_abs_dm:.4f}")

    # Combined signal: asym + wall mid
    print(f"\n  Combined signal (asym + cross_level_wall_mid):")
    v = r['cross_level_wall_mid']
    wm_signal = v - mid

    # Normalize both signals to [-1, 1]
    asym_norm = np.sign(asym_signal)
    wm_norm = np.sign(wm_signal)

    combined = asym_norm + wm_norm  # ranges from -2 to +2

    for strength in [-2, -1, 0, 1, 2]:
        idx = np.where((combined[1:n-1] == strength))[0] + 1
        if len(idx) == 0:
            print(f"    Strength {strength:>3}: N={0:>6}")
            continue
        dm = dmid[idx]
        avg_dm = np.mean(dm)
        n_up = np.sum(dm > 0)
        n_down = np.sum(dm < 0)
        n_flat = np.sum(dm == 0)
        print(f"    Strength {strength:>3}: N={len(idx):>6}  Avg_dmid={avg_dm:>7.4f}  Up={n_up}  Down={n_down}  Flat={n_flat}")

# ============================================================
# SECTION 10: OBI (Order Book Imbalance) Comparison
# ============================================================

print("\n" + "=" * 80)
print("SECTION 10: OBI vs WALL MID — Are they the same signal?")
print("=" * 80)

for d in [0, -1, -2]:
    r = all_results[d]
    mid = r['mid']
    bv1, av1 = r['bv1'], r['av1']
    bv2, av2 = r['bv2'], r['av2']
    n = len(mid)

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    # OBI variants
    obi_l1 = (bv1 - av1) / (bv1 + av1 + 1e-10)
    obi_l2 = (bv2 - av2) / (bv2 + av2 + 1e-10)
    obi_total = ((bv1 + bv2) - (av1 + av2)) / (bv1 + bv2 + av1 + av2 + 1e-10)

    # Wall mid signal (as continuous value)
    wm_l1 = r['microprice'] - mid  # L1 microprice deviation
    wm_cross = r['cross_level_microprice'] - mid

    print(f"\n--- Day {d} ---")
    print(f"Correlation between OBI and Wall Mid signals:")

    valid = slice(0, n-1)

    # OBI vs microprice deviation
    if np.std(obi_l1[valid]) > 1e-10 and np.std(wm_l1[valid]) > 1e-10:
        c1 = np.corrcoef(obi_l1[valid], wm_l1[valid])[0, 1]
    else:
        c1 = 0
    print(f"  OBI_L1 vs microprice_dev:       r = {c1:.4f}")

    if np.std(obi_total[valid]) > 1e-10 and np.std(wm_cross[valid]) > 1e-10:
        c2 = np.corrcoef(obi_total[valid], wm_cross[valid])[0, 1]
    else:
        c2 = 0
    print(f"  OBI_total vs cross_mp_dev:      r = {c2:.4f}")

    # Both vs dmid
    c3 = np.corrcoef(obi_l1[valid], dmid[valid])[0, 1] if np.std(obi_l1[valid]) > 1e-10 else 0
    c4 = np.corrcoef(obi_total[valid], dmid[valid])[0, 1] if np.std(obi_total[valid]) > 1e-10 else 0
    c5 = np.corrcoef(wm_l1[valid], dmid[valid])[0, 1] if np.std(wm_l1[valid]) > 1e-10 else 0
    c6 = np.corrcoef(wm_cross[valid], dmid[valid])[0, 1] if np.std(wm_cross[valid]) > 1e-10 else 0

    print(f"\n  Signal -> next dmid correlations:")
    print(f"    OBI_L1:              r = {c3:.4f}")
    print(f"    OBI_total:           r = {c4:.4f}")
    print(f"    microprice_dev:      r = {c5:.4f}")
    print(f"    cross_mp_dev:        r = {c6:.4f}")

# ============================================================
# SECTION 11: Summary Statistics Table
# ============================================================

print("\n" + "=" * 80)
print("SECTION 11: GRAND SUMMARY — ALL VARIANTS, ALL DAYS")
print("=" * 80)

all_variants = variant_names + ['obi_l1_shift', 'obi_total_shift']

print(f"\n{'Variant':<35} {'D0_corr':>8} {'D-1_corr':>8} {'D-2_corr':>8} {'D0_acc':>8} {'D-1_acc':>8} {'D-2_acc':>8}")
print("-" * 95)

for vn in variant_names:
    row = f"{vn:<35}"
    for d in [0, -1, -2]:
        m = compute_metrics(all_results[d], vn)
        row += f" {m['corr']:>8.4f}"
    for d in [0, -1, -2]:
        m = compute_metrics(all_results[d], vn)
        row += f" {m['accuracy']:>8.3f}"
    print(row)

print("\n" + "=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)
