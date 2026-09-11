"""
HYDROGEL_PACK Price Dynamics Analysis
=====================================
Comprehensive statistical characterization of HP mid-price, spread regimes,
peak behavior, mean-reversion signals, and taker flow.

Output: structured tables with cross-day stability assessment.
"""

import pandas as pd
import numpy as np
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

BASE = "/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round3"

# ============================================================
# DATA LOADING
# ============================================================
def load_prices(day):
    df = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    hp = df[df['product'] == 'HYDROGEL_PACK'].copy()
    hp = hp.sort_values('timestamp').reset_index(drop=True)
    hp['mid'] = (hp['bid_price_1'] + hp['ask_price_1']) / 2.0
    hp['spread'] = hp['ask_price_1'] - hp['bid_price_1']
    hp['day'] = day
    return hp

def load_trades(day):
    df = pd.read_csv(f"{BASE}/trades_round_3_day_{day}.csv", sep=";")
    hp = df[df['symbol'] == 'HYDROGEL_PACK'].copy()
    hp = hp.sort_values('timestamp').reset_index(drop=True)
    hp['day'] = day
    return hp

days_prices = {d: load_prices(d) for d in range(3)}
days_trades = {d: load_trades(d) for d in range(3)}

for d in range(3):
    p = days_prices[d]
    print(f"Day {d}: {len(p)} ticks, mid range [{p['mid'].min():.1f}, {p['mid'].max():.1f}], "
          f"spread range [{p['spread'].min()}, {p['spread'].max()}]")
    t = days_trades[d]
    print(f"  Trades: {len(t)}, price range [{t['price'].min():.1f}, {t['price'].max():.1f}]")

print("\n" + "="*80)
print("SECTION 1: MID PRICE SUMMARY STATISTICS")
print("="*80)
for d in range(3):
    p = days_prices[d]
    mid = p['mid'].values
    ret = np.diff(mid)
    print(f"\nDay {d}:")
    print(f"  Mean mid: {mid.mean():.2f}, Std: {mid.std():.2f}")
    print(f"  Min: {mid.min():.1f}, Max: {mid.max():.1f}, Range: {mid.max()-mid.min():.1f}")
    print(f"  Return mean: {ret.mean():.4f}, std: {ret.std():.4f}")
    print(f"  AC(1): {np.corrcoef(ret[:-1], ret[1:])[0,1]:.4f}")
    print(f"  Skew: {pd.Series(ret).skew():.4f}, Kurt: {pd.Series(ret).kurtosis():.4f}")

# ============================================================
# SECTION 2: LOCAL HIGHS (PEAKS) ANALYSIS
# ============================================================
print("\n" + "="*80)
print("SECTION 2: LOCAL HIGHS (PEAKS) ANALYSIS")
print("="*80)

def find_peaks(mid, smooth_window=5):
    """Find peaks on both raw and smoothed mid."""
    # Raw peaks
    raw_peaks = []
    for i in range(1, len(mid)-1):
        if mid[i] > mid[i-1] and mid[i] > mid[i+1]:
            raw_peaks.append(i)

    # Smoothed peaks (5-tick rolling mean)
    smoothed = pd.Series(mid).rolling(smooth_window, center=True).mean().values
    smooth_peaks = []
    for i in range(smooth_window, len(smoothed)-smooth_window):
        if not np.isnan(smoothed[i]):
            if smoothed[i] > smoothed[i-1] and smoothed[i] > smoothed[i+1]:
                smooth_peaks.append(i)

    return raw_peaks, smooth_peaks

def measure_drawdown_after_peak(mid, peak_idx, horizons=[50, 100, 200, 500, 1000]):
    """Measure max drawdown and time-to-drawdown after each peak."""
    results = {}
    for h in horizons:
        end = min(peak_idx + h, len(mid))
        if end <= peak_idx:
            results[h] = (np.nan, np.nan)
            continue
        future = mid[peak_idx:end]
        drawdowns = future - mid[peak_idx]
        max_dd = drawdowns.min()
        time_to_dd = np.argmin(drawdowns)
        results[h] = (max_dd, time_to_dd)
    return results

def measure_forward_returns(mid, peak_idx, offsets=[1, 5, 10, 20, 50, 100, 200]):
    """Forward returns at specific offsets."""
    results = {}
    for o in offsets:
        if peak_idx + o < len(mid):
            results[o] = mid[peak_idx + o] - mid[peak_idx]
        else:
            results[o] = np.nan
    return results

# Thresholds for drop probability
drop_thresholds = [5, 10, 15, 20, 30, 50]

for d in range(3):
    mid = days_prices[d]['mid'].values
    raw_peaks, smooth_peaks = find_peaks(mid)

    print(f"\nDay {d}: {len(raw_peaks)} raw peaks, {len(smooth_peaks)} smoothed peaks (out of {len(mid)} ticks)")

    # Drawdown analysis for raw peaks
    dd_results = {h: [] for h in [50, 100, 200, 500, 1000]}
    fwd_results = {o: [] for o in [1, 5, 10, 20, 50, 100, 200]}
    drop_probs = {t: [] for t in drop_thresholds}

    for pk in raw_peaks:
        dd = measure_drawdown_after_peak(mid, pk)
        for h, (mdd, ttd) in dd.items():
            if not np.isnan(mdd):
                dd_results[h].append((mdd, ttd))

        fwd = measure_forward_returns(mid, pk)
        for o, r in fwd.items():
            if not np.isnan(r):
                fwd_results[o].append(r)

        # Drop probability within 200 ticks
        end = min(pk + 200, len(mid))
        future_min = mid[pk:end].min() - mid[pk]
        for t in drop_thresholds:
            drop_probs[t].append(1 if future_min <= -t else 0)

    print(f"\n  Max Drawdown After Raw Peaks (mean / median / worst):")
    print(f"  {'Horizon':>8}  {'Mean DD':>10}  {'Median DD':>10}  {'Worst DD':>10}  {'Mean Time':>10}")
    for h in [50, 100, 200, 500, 1000]:
        if dd_results[h]:
            dds = [x[0] for x in dd_results[h]]
            ttds = [x[1] for x in dd_results[h]]
            print(f"  {h:>8}  {np.mean(dds):>10.2f}  {np.median(dds):>10.2f}  {np.min(dds):>10.2f}  {np.mean(ttds):>10.1f}")

    print(f"\n  Drop Probability (within 200 ticks after peak):")
    for t in drop_thresholds:
        if drop_probs[t]:
            print(f"    P(drop >= {t:>2}): {np.mean(drop_probs[t]):.4f}  (N={len(drop_probs[t])})")

    print(f"\n  Mean Forward Return After Raw Peaks:")
    print(f"  {'Offset':>8}  {'Mean':>10}  {'Median':>10}  {'Std':>10}  {'t-stat':>10}  {'N':>6}")
    for o in [1, 5, 10, 20, 50, 100, 200]:
        vals = fwd_results[o]
        if vals:
            arr = np.array(vals)
            mean = arr.mean()
            std = arr.std()
            t_stat = mean / (std / np.sqrt(len(arr))) if std > 0 else 0
            print(f"  {o:>8}  {mean:>10.3f}  {np.median(arr):>10.3f}  {std:>10.3f}  {t_stat:>10.2f}  {len(arr):>6}")

# ============================================================
# SECTION 3: SMOOTHED PEAKS ANALYSIS
# ============================================================
print("\n" + "="*80)
print("SECTION 3: SMOOTHED (5-TICK) PEAKS — FORWARD RETURNS")
print("="*80)

for d in range(3):
    mid = days_prices[d]['mid'].values
    _, smooth_peaks = find_peaks(mid)

    print(f"\nDay {d}: {len(smooth_peaks)} smoothed peaks")
    fwd_results = {o: [] for o in [1, 5, 10, 20, 50, 100, 200]}
    for pk in smooth_peaks:
        fwd = measure_forward_returns(mid, pk)
        for o, r in fwd.items():
            if not np.isnan(r):
                fwd_results[o].append(r)

    print(f"  {'Offset':>8}  {'Mean':>10}  {'Median':>10}  {'Std':>10}  {'t-stat':>10}  {'N':>6}")
    for o in [1, 5, 10, 20, 50, 100, 200]:
        vals = fwd_results[o]
        if vals:
            arr = np.array(vals)
            mean = arr.mean()
            std = arr.std()
            t_stat = mean / (std / np.sqrt(len(arr))) if std > 0 else 0
            print(f"  {o:>8}  {mean:>10.3f}  {np.median(arr):>10.3f}  {std:>10.3f}  {t_stat:>10.2f}  {len(arr):>6}")

# ============================================================
# SECTION 4: SPREAD AT PEAKS VS NON-PEAKS
# ============================================================
print("\n" + "="*80)
print("SECTION 4: SPREAD AT PEAKS VS NON-PEAKS")
print("="*80)

for d in range(3):
    p = days_prices[d]
    mid = p['mid'].values
    spread = p['spread'].values
    raw_peaks, _ = find_peaks(mid)

    peak_set = set(raw_peaks)
    non_peak_set = set(range(len(mid))) - peak_set

    peak_spreads = spread[list(peak_set)]
    non_peak_spreads = spread[list(non_peak_set)]

    print(f"\nDay {d}:")
    print(f"  Peak spread:     mean={peak_spreads.mean():.2f}, median={np.median(peak_spreads):.1f}, "
          f"std={peak_spreads.std():.2f}")
    print(f"  Non-peak spread: mean={non_peak_spreads.mean():.2f}, median={np.median(non_peak_spreads):.1f}, "
          f"std={non_peak_spreads.std():.2f}")

    # Spread distribution at peaks
    unique_spreads = sorted(set(spread))
    print(f"\n  Spread distribution at PEAKS:")
    print(f"  {'Spread':>8}  {'Count':>8}  {'Pct':>8}")
    for s in unique_spreads:
        cnt = np.sum(peak_spreads == s)
        if cnt > 0:
            print(f"  {s:>8}  {cnt:>8}  {cnt/len(peak_spreads)*100:>7.1f}%")

    print(f"\n  Spread distribution OVERALL:")
    print(f"  {'Spread':>8}  {'Count':>8}  {'Pct':>8}")
    for s in unique_spreads:
        cnt = np.sum(spread == s)
        print(f"  {s:>8}  {cnt:>8}  {cnt/len(spread)*100:>7.1f}%")

    # Spread 10 ticks before/after peaks
    before_spreads = []
    after_spreads = []
    for pk in raw_peaks:
        if pk >= 10:
            before_spreads.append(spread[pk-10])
        if pk + 10 < len(spread):
            after_spreads.append(spread[pk+10])

    if before_spreads:
        print(f"\n  Spread 10 ticks BEFORE peaks: mean={np.mean(before_spreads):.2f}, median={np.median(before_spreads):.1f}")
    if after_spreads:
        print(f"  Spread 10 ticks AFTER peaks:  mean={np.mean(after_spreads):.2f}, median={np.median(after_spreads):.1f}")

# ============================================================
# SECTION 5: SPREAD=17 EVENT ANALYSIS
# ============================================================
print("\n" + "="*80)
print("SECTION 5: SPREAD=17 EVENT ANALYSIS")
print("="*80)

for d in range(3):
    p = days_prices[d]
    mid = p['mid'].values
    spread = p['spread'].values
    raw_peaks, _ = find_peaks(mid)
    peak_set = set(raw_peaks)

    sp17_idx = np.where(spread == 17)[0]
    # Also check other wide spreads
    sp16_idx = np.where(spread == 16)[0]
    sp15_idx = np.where(spread >= 15)[0]

    print(f"\nDay {d}: {len(sp17_idx)} spread=17 ticks, {len(sp16_idx)} spread=16, {len(sp15_idx)} spread>=15")

    if len(sp17_idx) > 0:
        print(f"  Mid at spread=17: mean={mid[sp17_idx].mean():.2f}, min={mid[sp17_idx].min():.1f}, max={mid[sp17_idx].max():.1f}")

        # Forward returns after spread=17
        offsets = [10, 50, 100, 200, 500]
        print(f"\n  Forward returns after spread=17 events:")
        print(f"  {'Offset':>8}  {'Mean':>10}  {'Median':>10}  {'Std':>10}  {'t-stat':>10}  {'N':>6}  {'%neg':>8}")
        for o in offsets:
            rets = []
            for idx in sp17_idx:
                if idx + o < len(mid):
                    rets.append(mid[idx + o] - mid[idx])
            if rets:
                arr = np.array(rets)
                mean = arr.mean()
                std = arr.std()
                t_stat = mean / (std / np.sqrt(len(arr))) if std > 0 else 0
                pct_neg = np.mean(arr < 0) * 100
                print(f"  {o:>8}  {mean:>10.2f}  {np.median(arr):>10.2f}  {std:>10.2f}  {t_stat:>10.2f}  {len(arr):>6}  {pct_neg:>7.1f}%")

        # Overlap with peaks
        sp17_peaks = sum(1 for idx in sp17_idx if idx in peak_set)
        print(f"\n  spread=17 that are also peaks: {sp17_peaks}/{len(sp17_idx)} ({sp17_peaks/len(sp17_idx)*100:.1f}%)")
        print(f"  peaks that have spread=17: {sp17_peaks}/{len(raw_peaks)} ({sp17_peaks/len(raw_peaks)*100:.1f}%)")

    # Also analyze spread >= 15
    if len(sp15_idx) > 0:
        print(f"\n  Forward returns after spread>=15 events:")
        print(f"  {'Offset':>8}  {'Mean':>10}  {'Median':>10}  {'Std':>10}  {'t-stat':>10}  {'N':>6}  {'%neg':>8}")
        offsets = [10, 50, 100, 200, 500]
        for o in offsets:
            rets = []
            for idx in sp15_idx:
                if idx + o < len(mid):
                    rets.append(mid[idx + o] - mid[idx])
            if rets:
                arr = np.array(rets)
                mean = arr.mean()
                std = arr.std()
                t_stat = mean / (std / np.sqrt(len(arr))) if std > 0 else 0
                pct_neg = np.mean(arr < 0) * 100
                print(f"  {o:>8}  {mean:>10.2f}  {np.median(arr):>10.2f}  {std:>10.2f}  {t_stat:>10.2f}  {len(arr):>6}  {pct_neg:>7.1f}%")

# ============================================================
# SECTION 6: REGIME ANALYSIS (SPREAD-BASED)
# ============================================================
print("\n" + "="*80)
print("SECTION 6: SPREAD REGIME ANALYSIS")
print("="*80)

def classify_regime(spread):
    if spread <= 9:
        return 'tight'
    elif spread <= 15:
        return 'medium'
    else:
        return 'wide'

for d in range(3):
    p = days_prices[d]
    mid = p['mid'].values
    spread = p['spread'].values
    ret = np.diff(mid)

    regimes = np.array([classify_regime(s) for s in spread])
    regime_labels = ['tight', 'medium', 'wide']

    print(f"\nDay {d}:")
    print(f"  Regime distribution:")
    for r in regime_labels:
        mask = regimes == r
        cnt = mask.sum()
        if cnt > 0:
            regime_rets = ret[np.where(mask)[0][np.where(mask)[0] < len(ret)]]
            print(f"    {r:>8}: {cnt:>6} ticks ({cnt/len(regimes)*100:>5.1f}%), "
                  f"mean_ret={regime_rets.mean():.4f}, std_ret={regime_rets.std():.4f}")

    # Transition matrix
    print(f"\n  Regime transition matrix P(row -> col):")
    trans = defaultdict(lambda: defaultdict(int))
    for i in range(len(regimes)-1):
        trans[regimes[i]][regimes[i+1]] += 1

    print(f"  {'':>10}", end="")
    for r2 in regime_labels:
        print(f"  {r2:>10}", end="")
    print()
    for r1 in regime_labels:
        total = sum(trans[r1][r2] for r2 in regime_labels)
        print(f"  {r1:>10}", end="")
        for r2 in regime_labels:
            if total > 0:
                print(f"  {trans[r1][r2]/total:>10.4f}", end="")
            else:
                print(f"  {'N/A':>10}", end="")
        print(f"  (N={total})")

    # Regime duration
    print(f"\n  Regime duration (consecutive ticks):")
    durations = defaultdict(list)
    current_regime = regimes[0]
    current_dur = 1
    for i in range(1, len(regimes)):
        if regimes[i] == current_regime:
            current_dur += 1
        else:
            durations[current_regime].append(current_dur)
            current_regime = regimes[i]
            current_dur = 1
    durations[current_regime].append(current_dur)

    for r in regime_labels:
        if durations[r]:
            arr = np.array(durations[r])
            print(f"    {r:>8}: mean={arr.mean():.1f}, median={np.median(arr):.0f}, "
                  f"max={arr.max()}, episodes={len(arr)}")

# ============================================================
# SECTION 7: ROLLING REALIZED VOLATILITY
# ============================================================
print("\n" + "="*80)
print("SECTION 7: ROLLING 200-TICK REALIZED VOLATILITY")
print("="*80)

for d in range(3):
    mid = days_prices[d]['mid'].values
    ret = np.diff(mid)

    # Rolling 200-tick std of returns
    rvol = pd.Series(ret).rolling(200).std().values
    valid = rvol[~np.isnan(rvol)]

    print(f"\nDay {d}:")
    print(f"  RVol(200) mean: {valid.mean():.4f}, std: {valid.std():.4f}")
    print(f"  RVol(200) min: {valid.min():.4f}, max: {valid.max():.4f}")
    print(f"  RVol(200) percentiles: p10={np.percentile(valid,10):.4f}, "
          f"p50={np.percentile(valid,50):.4f}, p90={np.percentile(valid,90):.4f}")

    # Correlation between rvol and spread
    spread = days_prices[d]['spread'].values[1:]  # align with returns
    valid_mask = ~np.isnan(rvol)
    if valid_mask.sum() > 100:
        corr = np.corrcoef(rvol[valid_mask], spread[valid_mask])[0,1]
        print(f"  Corr(rvol, spread): {corr:.4f}")

# ============================================================
# SECTION 8: MEAN REVERSION ANALYSIS
# ============================================================
print("\n" + "="*80)
print("SECTION 8: MEAN REVERSION ANALYSIS")
print("="*80)

for d in range(3):
    mid = days_prices[d]['mid'].values

    # Rolling 500-tick mean
    rolling_mean = pd.Series(mid).rolling(500).mean().values

    thresholds = [10, 15, 20, 30]
    offsets = [10, 50, 100, 200, 500]

    print(f"\nDay {d}:")
    print(f"\n  ABOVE rolling_500_mean + X:")
    print(f"  {'Thresh':>8}  {'Offset':>8}  {'Mean Ret':>10}  {'Median':>10}  {'Std':>10}  {'t-stat':>10}  {'N':>6}  {'%neg':>8}")
    for x in thresholds:
        above_idx = np.where((~np.isnan(rolling_mean)) & (mid > rolling_mean + x))[0]
        for o in offsets:
            rets = []
            for idx in above_idx:
                if idx + o < len(mid):
                    rets.append(mid[idx + o] - mid[idx])
            if len(rets) >= 5:
                arr = np.array(rets)
                mean = arr.mean()
                std = arr.std()
                t_stat = mean / (std / np.sqrt(len(arr))) if std > 0 else 0
                pct_neg = np.mean(arr < 0) * 100
                print(f"  {x:>8}  {o:>8}  {mean:>10.3f}  {np.median(arr):>10.3f}  {std:>10.3f}  {t_stat:>10.2f}  {len(arr):>6}  {pct_neg:>7.1f}%")

    print(f"\n  BELOW rolling_500_mean - X:")
    print(f"  {'Thresh':>8}  {'Offset':>8}  {'Mean Ret':>10}  {'Median':>10}  {'Std':>10}  {'t-stat':>10}  {'N':>6}  {'%neg':>8}")
    for x in thresholds:
        below_idx = np.where((~np.isnan(rolling_mean)) & (mid < rolling_mean - x))[0]
        for o in offsets:
            rets = []
            for idx in below_idx:
                if idx + o < len(mid):
                    rets.append(mid[idx + o] - mid[idx])
            if len(rets) >= 5:
                arr = np.array(rets)
                mean = arr.mean()
                std = arr.std()
                t_stat = mean / (std / np.sqrt(len(arr))) if std > 0 else 0
                pct_neg = np.mean(arr < 0) * 100
                print(f"  {x:>8}  {o:>8}  {mean:>10.3f}  {np.median(arr):>10.3f}  {std:>10.3f}  {t_stat:>10.2f}  {len(arr):>6}  {pct_neg:>7.1f}%")

# ============================================================
# SECTION 9: IDEAL SHORT ENTRY SIGNALS
# ============================================================
print("\n" + "="*80)
print("SECTION 9: IDEAL SHORT ENTRY SIGNAL SEARCH")
print("="*80)

def test_signal(mid, spread, signal_mask, label, offsets=[10, 50, 100, 200, 500]):
    """Test forward returns when signal fires."""
    results = []
    signal_idx = np.where(signal_mask)[0]
    if len(signal_idx) == 0:
        return None

    for o in offsets:
        rets = []
        for idx in signal_idx:
            if idx + o < len(mid):
                rets.append(mid[idx + o] - mid[idx])
        if rets:
            arr = np.array(rets)
            mean = arr.mean()
            std = arr.std()
            t_stat = mean / (std / np.sqrt(len(arr))) if std > 0 else 0
            pct_neg = np.mean(arr < 0) * 100
            results.append((o, mean, np.median(arr), std, t_stat, len(arr), pct_neg))
    return results

for d in range(3):
    mid = days_prices[d]['mid'].values
    spread = days_prices[d]['spread'].values

    # Derived features
    rolling_200_mean = pd.Series(mid).rolling(200).mean().values
    rolling_500_mean = pd.Series(mid).rolling(500).mean().values
    roc_20 = np.full(len(mid), np.nan)
    roc_20[20:] = mid[20:] - mid[:-20]
    rolling_20_max = pd.Series(mid).rolling(20).max().values
    rolling_50_max = pd.Series(mid).rolling(50).max().values
    rolling_20_vol = pd.Series(np.diff(mid, prepend=mid[0])).rolling(20).std().values

    signals = {}

    # Signal A: spread>=15 AND mid > rolling_200_mean + 10
    mask_a = (~np.isnan(rolling_200_mean)) & (spread >= 15) & (mid > rolling_200_mean + 10)
    signals['A: sp>=15 & mid>ma200+10'] = mask_a

    # Signal B: spread>=13 AND roc_20 > 5
    mask_b = (~np.isnan(roc_20)) & (spread >= 13) & (roc_20 > 5)
    signals['B: sp>=13 & roc20>5'] = mask_b

    # Signal C: rolling_20_max == mid (at local 20-tick high)
    mask_c = (~np.isnan(rolling_20_max)) & (mid == rolling_20_max)
    signals['C: mid==max20'] = mask_c

    # Signal D: spread==17 (baseline)
    mask_d = (spread == 17)
    signals['D: spread==17'] = mask_d

    # Signal E: spread>=15 & mid>ma200+10 & roc20>0
    mask_e = mask_a & (~np.isnan(roc_20)) & (roc_20 > 0)
    signals['E: A & roc20>0'] = mask_e

    # Signal F: spread>=16 AND mid > rolling_200_mean + 5
    mask_f = (~np.isnan(rolling_200_mean)) & (spread >= 16) & (mid > rolling_200_mean + 5)
    signals['F: sp>=16 & mid>ma200+5'] = mask_f

    # Signal G: mid == rolling_50_max AND spread >= 13
    mask_g = (~np.isnan(rolling_50_max)) & (mid == rolling_50_max) & (spread >= 13)
    signals['G: mid==max50 & sp>=13'] = mask_g

    # Signal H: spread>=15 AND mid > rolling_500_mean + 10
    mask_h = (~np.isnan(rolling_500_mean)) & (spread >= 15) & (mid > rolling_500_mean + 10)
    signals['H: sp>=15 & mid>ma500+10'] = mask_h

    # Signal I: spread==17 AND mid > 10010
    mask_i = (spread == 17) & (mid > 10010)
    signals['I: sp==17 & mid>10010'] = mask_i

    # Signal J: spread>=15 AND rolling 20-tick volatility > 2*overall_vol
    overall_vol = np.nanmean(rolling_20_vol)
    mask_j = (~np.isnan(rolling_20_vol)) & (spread >= 15) & (rolling_20_vol > 2 * overall_vol)
    signals['J: sp>=15 & hvol'] = mask_j

    # Signal K: mid > rolling_200_mean + 15 (pure deviation, any spread)
    mask_k = (~np.isnan(rolling_200_mean)) & (mid > rolling_200_mean + 15)
    signals['K: mid>ma200+15'] = mask_k

    # Signal L: roc_20 > 10 (pure momentum, any spread)
    mask_l = (~np.isnan(roc_20)) & (roc_20 > 10)
    signals['L: roc20>10'] = mask_l

    print(f"\nDay {d}:")
    for label, mask in signals.items():
        n_fires = mask.sum()
        res = test_signal(mid, spread, mask, label)
        if res and n_fires > 0:
            print(f"\n  {label} (fires {n_fires} times, {n_fires/len(mid)*100:.2f}%)")
            print(f"  {'Offset':>8}  {'Mean':>10}  {'Median':>10}  {'Std':>10}  {'t-stat':>10}  {'N':>6}  {'%neg':>8}")
            for (o, mean, med, std, t, n, pn) in res:
                print(f"  {o:>8}  {mean:>10.2f}  {med:>10.2f}  {std:>10.2f}  {t:>10.2f}  {n:>6}  {pn:>7.1f}%")

# ============================================================
# SECTION 10: TAKER FLOW ANALYSIS
# ============================================================
print("\n" + "="*80)
print("SECTION 10: TAKER FLOW ANALYSIS")
print("="*80)

for d in range(3):
    p = days_prices[d]
    t = days_trades[d]
    mid = p['mid'].values
    timestamps = p['timestamp'].values

    # Create timestamp -> tick index mapping
    ts_to_idx = {ts: i for i, ts in enumerate(timestamps)}

    # Classify trades as buyer/seller initiated
    # In IMC: buyer field filled = buyer-initiated (taker buy), seller field = seller-initiated (taker sell)
    # Actually, looking at the CSV format: buyer and seller are empty strings for bot trades
    # The price relative to mid determines direction

    buy_trades = []
    sell_trades = []

    for _, row in t.iterrows():
        ts = row['timestamp']
        if ts not in ts_to_idx:
            continue
        idx = ts_to_idx[ts]
        trade_mid = mid[idx]

        # Classify: if price >= mid, likely buyer-initiated; if price <= mid, seller-initiated
        # But for bot trades, let's just look at net signed flow per timestamp
        if row['price'] >= trade_mid:
            buy_trades.append((idx, row['price'], row['quantity']))
        else:
            sell_trades.append((idx, row['price'], row['quantity']))

    print(f"\nDay {d}: {len(buy_trades)} buyer-initiated, {len(sell_trades)} seller-initiated trades")

    offsets = [1, 5, 10, 20, 50, 100]

    # After buyer-initiated trades
    print(f"\n  Forward returns after BUYER-INITIATED trades:")
    print(f"  {'Offset':>8}  {'Mean':>10}  {'Median':>10}  {'Std':>10}  {'t-stat':>10}  {'N':>6}")
    for o in offsets:
        rets = []
        for (idx, price, qty) in buy_trades:
            if idx + o < len(mid):
                rets.append(mid[idx + o] - mid[idx])
        if rets:
            arr = np.array(rets)
            mean = arr.mean()
            std = arr.std()
            t_stat = mean / (std / np.sqrt(len(arr))) if std > 0 else 0
            print(f"  {o:>8}  {mean:>10.3f}  {np.median(arr):>10.3f}  {std:>10.3f}  {t_stat:>10.2f}  {len(arr):>6}")

    # After seller-initiated trades
    print(f"\n  Forward returns after SELLER-INITIATED trades:")
    print(f"  {'Offset':>8}  {'Mean':>10}  {'Median':>10}  {'Std':>10}  {'t-stat':>10}  {'N':>6}")
    for o in offsets:
        rets = []
        for (idx, price, qty) in sell_trades:
            if idx + o < len(mid):
                rets.append(mid[idx + o] - mid[idx])
        if rets:
            arr = np.array(rets)
            mean = arr.mean()
            std = arr.std()
            t_stat = mean / (std / np.sqrt(len(arr))) if std > 0 else 0
            print(f"  {o:>8}  {mean:>10.3f}  {np.median(arr):>10.3f}  {std:>10.3f}  {t_stat:>10.2f}  {len(arr):>6}")

    # Net flow per tick and predictive power
    # Aggregate signed volume per tick
    net_flow = np.zeros(len(mid))
    for (idx, price, qty) in buy_trades:
        net_flow[idx] += qty
    for (idx, price, qty) in sell_trades:
        net_flow[idx] -= qty

    # Rolling 10-tick net flow
    cum_flow_10 = pd.Series(net_flow).rolling(10).sum().values

    # Forward return conditioned on flow
    print(f"\n  Forward return conditioned on rolling 10-tick net flow:")
    print(f"  {'Flow Cond':>15}  {'Offset':>8}  {'Mean':>10}  {'Std':>10}  {'t-stat':>10}  {'N':>6}")
    for flow_cond, flow_label in [(lambda f: f > 5, 'flow>5'), (lambda f: f < -5, 'flow<-5'),
                                   (lambda f: f > 10, 'flow>10'), (lambda f: f < -10, 'flow<-10')]:
        for o in [10, 50, 100]:
            valid = (~np.isnan(cum_flow_10))
            mask = valid & np.array([flow_cond(f) for f in cum_flow_10])
            idxs = np.where(mask)[0]
            rets = []
            for idx in idxs:
                if idx + o < len(mid):
                    rets.append(mid[idx + o] - mid[idx])
            if len(rets) >= 5:
                arr = np.array(rets)
                mean = arr.mean()
                std = arr.std()
                t_stat = mean / (std / np.sqrt(len(arr))) if std > 0 else 0
                print(f"  {flow_label:>15}  {o:>8}  {mean:>10.3f}  {std:>10.3f}  {t_stat:>10.2f}  {len(arr):>6}")

# ============================================================
# SECTION 11: CROSS-DAY SIGNAL STABILITY
# ============================================================
print("\n" + "="*80)
print("SECTION 11: CROSS-DAY SIGNAL STABILITY SUMMARY")
print("="*80)

# For each key signal, show t+100 mean return on each day
key_signals = [
    ('spread==17', lambda mid, spread, rm200, rm500, roc20, max20, max50, vol20: spread == 17),
    ('spread>=15', lambda mid, spread, rm200, rm500, roc20, max20, max50, vol20: spread >= 15),
    ('mid>ma200+10', lambda mid, spread, rm200, rm500, roc20, max20, max50, vol20:
        (~np.isnan(rm200)) & (mid > rm200 + 10)),
    ('mid>ma200+15', lambda mid, spread, rm200, rm500, roc20, max20, max50, vol20:
        (~np.isnan(rm200)) & (mid > rm200 + 15)),
    ('sp>=15 & mid>ma200+10', lambda mid, spread, rm200, rm500, roc20, max20, max50, vol20:
        (~np.isnan(rm200)) & (spread >= 15) & (mid > rm200 + 10)),
    ('sp==17 & mid>10010', lambda mid, spread, rm200, rm500, roc20, max20, max50, vol20:
        (spread == 17) & (mid > 10010)),
    ('sp>=16 & mid>ma200+5', lambda mid, spread, rm200, rm500, roc20, max20, max50, vol20:
        (~np.isnan(rm200)) & (spread >= 16) & (mid > rm200 + 5)),
    ('mid==max50 & sp>=13', lambda mid, spread, rm200, rm500, roc20, max20, max50, vol20:
        (~np.isnan(max50)) & (mid == max50) & (spread >= 13)),
    ('roc20>10', lambda mid, spread, rm200, rm500, roc20, max20, max50, vol20:
        (~np.isnan(roc20)) & (roc20 > 10)),
    ('mid<ma500-15', lambda mid, spread, rm200, rm500, roc20, max20, max50, vol20:
        (~np.isnan(rm500)) & (mid < rm500 - 15)),
]

print(f"\n{'Signal':>30}  {'Day0 t100':>10}  {'D0 N':>6}  {'Day1 t100':>10}  {'D1 N':>6}  {'Day2 t100':>10}  {'D2 N':>6}  {'AllDay':>10}  {'Stable?':>8}")
print("-" * 120)

for label, sig_fn in key_signals:
    day_results = []
    for d in range(3):
        mid = days_prices[d]['mid'].values
        spread = days_prices[d]['spread'].values
        rm200 = pd.Series(mid).rolling(200).mean().values
        rm500 = pd.Series(mid).rolling(500).mean().values
        roc20 = np.full(len(mid), np.nan)
        roc20[20:] = mid[20:] - mid[:-20]
        max20 = pd.Series(mid).rolling(20).max().values
        max50 = pd.Series(mid).rolling(50).max().values
        vol20 = pd.Series(np.diff(mid, prepend=mid[0])).rolling(20).std().values

        mask = sig_fn(mid, spread, rm200, rm500, roc20, max20, max50, vol20)
        idxs = np.where(mask)[0]
        rets = []
        for idx in idxs:
            if idx + 100 < len(mid):
                rets.append(mid[idx + 100] - mid[idx])
        if rets:
            arr = np.array(rets)
            day_results.append((arr.mean(), len(arr)))
        else:
            day_results.append((np.nan, 0))

    # Check stability: all 3 days same sign
    means = [r[0] for r in day_results]
    all_mean = np.nanmean(means)
    same_sign = all(m < 0 for m in means if not np.isnan(m)) or all(m > 0 for m in means if not np.isnan(m))
    stable = "YES" if same_sign and all(day_results[d][1] >= 3 for d in range(3)) else "no"

    print(f"{label:>30}  {day_results[0][0]:>10.2f}  {day_results[0][1]:>6}  "
          f"{day_results[1][0]:>10.2f}  {day_results[1][1]:>6}  "
          f"{day_results[2][0]:>10.2f}  {day_results[2][1]:>6}  "
          f"{all_mean:>10.2f}  {stable:>8}")

# ============================================================
# SECTION 12: COMBINED SIGNAL — BEST SHORT ENTRY
# ============================================================
print("\n" + "="*80)
print("SECTION 12: COMBINED SIGNAL OPTIMIZATION — BEST SHORT ENTRY")
print("="*80)

# Test many combinations at multiple horizons
combos = [
    ('spread>=15 & mid>ma200+10',
     lambda m, s, r2, r5, rc, mx2, mx5, v: (~np.isnan(r2)) & (s >= 15) & (m > r2 + 10)),
    ('spread>=16 & mid>ma200+5',
     lambda m, s, r2, r5, rc, mx2, mx5, v: (~np.isnan(r2)) & (s >= 16) & (m > r2 + 5)),
    ('spread>=15 & mid>ma500+10',
     lambda m, s, r2, r5, rc, mx2, mx5, v: (~np.isnan(r5)) & (s >= 15) & (m > r5 + 10)),
    ('spread>=15 & roc20>5',
     lambda m, s, r2, r5, rc, mx2, mx5, v: (~np.isnan(rc)) & (s >= 15) & (rc > 5)),
    ('spread>=13 & roc20>10',
     lambda m, s, r2, r5, rc, mx2, mx5, v: (~np.isnan(rc)) & (s >= 13) & (rc > 10)),
    ('sp>=15 & mid>ma200+10 & roc20>0',
     lambda m, s, r2, r5, rc, mx2, mx5, v: (~np.isnan(r2)) & (~np.isnan(rc)) & (s >= 15) & (m > r2 + 10) & (rc > 0)),
    ('sp==17 & mid>ma200+5',
     lambda m, s, r2, r5, rc, mx2, mx5, v: (~np.isnan(r2)) & (s == 17) & (m > r2 + 5)),
    ('sp==17 & mid>10010',
     lambda m, s, r2, r5, rc, mx2, mx5, v: (s == 17) & (m > 10010)),
    ('mid>ma200+20',
     lambda m, s, r2, r5, rc, mx2, mx5, v: (~np.isnan(r2)) & (m > r2 + 20)),
    ('sp>=15 & mid>ma200+5 & vol20>2x',
     lambda m, s, r2, r5, rc, mx2, mx5, v: (~np.isnan(r2)) & (~np.isnan(v)) & (s >= 15) & (m > r2 + 5) & (v > 2 * np.nanmean(v))),
]

for horizon in [50, 100, 200]:
    print(f"\n  HORIZON = {horizon} ticks")
    print(f"  {'Signal':>40}  {'D0 mean':>10}  {'D1 mean':>10}  {'D2 mean':>10}  {'All mean':>10}  {'All N':>6}  {'Win%':>6}")
    print("  " + "-" * 100)

    for label, sig_fn in combos:
        all_rets = []
        day_means = []
        for d in range(3):
            mid = days_prices[d]['mid'].values
            spread = days_prices[d]['spread'].values
            rm200 = pd.Series(mid).rolling(200).mean().values
            rm500 = pd.Series(mid).rolling(500).mean().values
            roc20 = np.full(len(mid), np.nan)
            roc20[20:] = mid[20:] - mid[:-20]
            max20 = pd.Series(mid).rolling(20).max().values
            max50 = pd.Series(mid).rolling(50).max().values
            vol20 = pd.Series(np.diff(mid, prepend=mid[0])).rolling(20).std().values

            mask = sig_fn(mid, spread, rm200, rm500, roc20, max20, max50, vol20)
            idxs = np.where(mask)[0]
            rets = []
            for idx in idxs:
                if idx + horizon < len(mid):
                    rets.append(mid[idx + horizon] - mid[idx])
            if rets:
                day_means.append(np.mean(rets))
                all_rets.extend(rets)
            else:
                day_means.append(np.nan)

        if all_rets:
            arr = np.array(all_rets)
            win_pct = np.mean(arr < 0) * 100  # "win" for short = negative return
            print(f"  {label:>40}  {day_means[0]:>10.2f}  {day_means[1]:>10.2f}  {day_means[2]:>10.2f}  "
                  f"{arr.mean():>10.2f}  {len(arr):>6}  {win_pct:>5.1f}%")

# ============================================================
# SECTION 13: LONG ENTRY SIGNALS (SYMMETRY CHECK)
# ============================================================
print("\n" + "="*80)
print("SECTION 13: LONG ENTRY SIGNAL CHECK (MEAN REVERSION FROM BELOW)")
print("="*80)

long_signals = [
    ('mid<ma200-10', lambda m, s, r2, r5, rc: (~np.isnan(r2)) & (m < r2 - 10)),
    ('mid<ma200-15', lambda m, s, r2, r5, rc: (~np.isnan(r2)) & (m < r2 - 15)),
    ('mid<ma200-20', lambda m, s, r2, r5, rc: (~np.isnan(r2)) & (m < r2 - 20)),
    ('mid<ma500-10', lambda m, s, r2, r5, rc: (~np.isnan(r5)) & (m < r5 - 10)),
    ('mid<ma500-15', lambda m, s, r2, r5, rc: (~np.isnan(r5)) & (m < r5 - 15)),
    ('roc20<-10', lambda m, s, r2, r5, rc: (~np.isnan(rc)) & (rc < -10)),
    ('sp>=15 & mid<ma200-10', lambda m, s, r2, r5, rc: (~np.isnan(r2)) & (s >= 15) & (m < r2 - 10)),
    ('sp>=15 & roc20<-5', lambda m, s, r2, r5, rc: (~np.isnan(rc)) & (s >= 15) & (rc < -5)),
]

for horizon in [50, 100, 200]:
    print(f"\n  HORIZON = {horizon} ticks")
    print(f"  {'Signal':>30}  {'D0 mean':>10}  {'D1 mean':>10}  {'D2 mean':>10}  {'All mean':>10}  {'All N':>6}  {'Win%':>6}")
    print("  " + "-" * 90)

    for label, sig_fn in long_signals:
        all_rets = []
        day_means = []
        for d in range(3):
            mid = days_prices[d]['mid'].values
            spread = days_prices[d]['spread'].values
            rm200 = pd.Series(mid).rolling(200).mean().values
            rm500 = pd.Series(mid).rolling(500).mean().values
            roc20 = np.full(len(mid), np.nan)
            roc20[20:] = mid[20:] - mid[:-20]

            mask = sig_fn(mid, spread, rm200, rm500, roc20)
            idxs = np.where(mask)[0]
            rets = []
            for idx in idxs:
                if idx + horizon < len(mid):
                    rets.append(mid[idx + horizon] - mid[idx])
            if rets:
                day_means.append(np.mean(rets))
                all_rets.extend(rets)
            else:
                day_means.append(np.nan)

        if all_rets:
            arr = np.array(all_rets)
            win_pct = np.mean(arr > 0) * 100  # "win" for long = positive return
            print(f"  {label:>30}  {day_means[0]:>10.2f}  {day_means[1]:>10.2f}  {day_means[2]:>10.2f}  "
                  f"{arr.mean():>10.2f}  {len(arr):>6}  {win_pct:>5.1f}%")

print("\n" + "="*80)
print("ANALYSIS COMPLETE")
print("="*80)
