"""
Deep Mathematical Structure Analysis — Part 2
Sections 8-9: Wavelet Analysis & Microstructure Signature
Plus: Comprehensive synthesis and exploitability assessment
"""

import numpy as np
import pandas as pd
from scipy import stats, signal
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# DATA LOADING (same as part 1)
# =============================================================================
def load_tomatoes(path):
    df = pd.read_csv(path, sep=';')
    tom = df[df['product'] == 'TOMATOES'].copy()
    tom = tom.sort_values('timestamp').reset_index(drop=True)
    mid = tom['mid_price'].values
    bid1 = tom['bid_price_1'].values
    ask1 = tom['ask_price_1'].values
    bv1 = tom['bid_volume_1'].values
    av1 = tom['ask_volume_1'].values
    bv2 = tom['bid_volume_2'].values.astype(float)
    av2 = tom['ask_volume_2'].values.astype(float)
    spread = ask1 - bid1
    dmid = np.diff(mid)
    microprice = (bid1 * av1 + ask1 * bv1) / (bv1 + av1)
    return {
        'mid': mid, 'bid1': bid1, 'ask1': ask1,
        'bv1': bv1, 'av1': av1, 'bv2': bv2, 'av2': av2,
        'spread': spread, 'dmid': dmid, 'microprice': microprice,
        'timestamps': tom['timestamp'].values, 'n': len(mid)
    }

base = '/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0'
d0 = load_tomatoes(f'{base}/prices_round_0_day_0.csv')
d1 = load_tomatoes(f'{base}/prices_round_0_day_-1.csv')
d2 = load_tomatoes(f'{base}/prices_round_0_day_-2.csv')

# =============================================================================
# 8. WAVELET ANALYSIS (from scratch — no pywavelets)
# =============================================================================
print("=" * 80)
print("8. WAVELET ANALYSIS")
print("=" * 80)

def morlet_wavelet(t, omega0=6.0):
    """Morlet wavelet."""
    return np.pi**(-0.25) * np.exp(1j * omega0 * t) * np.exp(-t**2 / 2)

def cwt_morlet(signal_data, scales, dt=1.0, omega0=6.0):
    """
    Continuous Wavelet Transform using Morlet wavelet.
    Computed via convolution in frequency domain.
    """
    N = len(signal_data)
    # Pad to power of 2
    N_pad = 2**int(np.ceil(np.log2(N)))
    padded = np.zeros(N_pad)
    padded[:N] = signal_data - np.mean(signal_data)

    # FFT of signal
    f_signal = np.fft.fft(padded)
    freqs = np.fft.fftfreq(N_pad, d=dt)
    angular_freqs = 2 * np.pi * freqs

    coefficients = np.zeros((len(scales), N), dtype=complex)

    for i, s in enumerate(scales):
        # Morlet wavelet in frequency domain
        norm = np.sqrt(2 * np.pi * s / dt)
        psi_hat = norm * np.pi**(-0.25) * np.exp(-(s * angular_freqs - omega0)**2 / 2)
        # Convolution
        conv = np.fft.ifft(f_signal * np.conj(psi_hat))
        coefficients[i, :] = conv[:N]

    return coefficients

def wavelet_analysis(mid, dmid, bid1, ask1, label):
    """Full wavelet analysis."""
    print(f"\n--- {label} (n={len(mid)}) ---")

    # Define scales (in ticks)
    min_scale = 2
    max_scale = min(len(mid) // 4, 500)
    n_scales = 40
    scales = np.logspace(np.log10(min_scale), np.log10(max_scale), n_scales)

    # CWT of mid-price changes
    coefs = cwt_morlet(dmid, scales)
    power = np.abs(coefs)**2

    # Scale-averaged power spectrum (global wavelet power)
    global_power = np.mean(power, axis=1)

    print(f"  CWT computed: {len(scales)} scales from {min_scale} to {max_scale:.0f} ticks")
    print(f"\n  Global wavelet power spectrum (top 10 scales):")
    top_scales = np.argsort(global_power)[::-1][:10]
    for rank, idx in enumerate(top_scales):
        period = scales[idx]
        freq = 1.0 / period
        print(f"    #{rank+1}: scale={period:.1f} ticks (freq={freq:.4f}), power={global_power[idx]:.4f}")

    # Is there a dominant scale?
    peak_scale = scales[np.argmax(global_power)]
    mean_power = np.mean(global_power)
    peak_power = np.max(global_power)
    print(f"\n  Dominant scale: {peak_scale:.1f} ticks")
    print(f"  Peak/mean ratio: {peak_power/mean_power:.2f}")

    # Test for significance: compare to red noise (AR(1)) background
    alpha_ar1 = np.abs(np.corrcoef(dmid[:-1], dmid[1:])[0, 1])
    print(f"  AR(1) coefficient for red noise test: {alpha_ar1:.4f}")

    # Theoretical AR(1) spectrum
    fk = 1.0 / scales  # frequencies corresponding to scales
    red_noise = (1 - alpha_ar1**2) / (1 + alpha_ar1**2 - 2 * alpha_ar1 * np.cos(2 * np.pi * fk))
    red_noise *= np.var(dmid)  # scale to match variance

    # 95% confidence level (chi-squared with 2 DOF for wavelet power)
    chi2_95 = stats.chi2.ppf(0.95, 2)
    significance_level = red_noise * chi2_95 / 2

    significant_scales = scales[global_power > significance_level]
    if len(significant_scales) > 0:
        print(f"  Significant scales (> 95% vs AR(1) red noise):")
        for s in significant_scales:
            idx = np.argmin(np.abs(scales - s))
            ratio = global_power[idx] / significance_level[idx]
            print(f"    scale={s:.1f} ticks, power/threshold={ratio:.2f}")
    else:
        print(f"  NO scales significant above AR(1) red noise background")

    # Wavelet variance decomposition: what fraction of energy is at each scale?
    total_energy = np.sum(global_power)
    print(f"\n  Energy distribution by scale band:")
    bands = [(2, 5, "ultra-short"), (5, 10, "short"), (10, 50, "medium"),
             (50, 200, "long"), (200, max_scale+1, "very-long")]
    for lo, hi, name in bands:
        mask = (scales >= lo) & (scales < hi)
        if mask.any():
            frac = np.sum(global_power[mask]) / total_energy
            print(f"    {name} ({lo}-{hi} ticks): {frac*100:.1f}%")

    # Transient detection: find time periods with anomalous power at specific scales
    print(f"\n  Transient oscillation detection:")
    # For the dominant 3 scales, find time windows with power > 3x average
    for scale_idx in top_scales[:3]:
        s = scales[scale_idx]
        ts_power = power[scale_idx, :]
        threshold = 3 * np.mean(ts_power)
        bursts = ts_power > threshold
        if bursts.any():
            burst_starts = np.where(np.diff(bursts.astype(int)) == 1)[0]
            burst_ends = np.where(np.diff(bursts.astype(int)) == -1)[0]
            n_bursts = max(len(burst_starts), len(burst_ends))
            burst_frac = np.mean(bursts)
            print(f"    Scale {s:.1f}: {n_bursts} burst episodes, {burst_frac*100:.1f}% of time")
        else:
            print(f"    Scale {s:.1f}: no transient bursts detected")

    # Wavelet coherence between bid and ask movements
    dbid = np.diff(bid1)
    dask = np.diff(ask1)

    coefs_bid = cwt_morlet(dbid, scales)
    coefs_ask = cwt_morlet(dask, scales)

    # Cross-wavelet spectrum
    cross = coefs_bid * np.conj(coefs_ask)

    # Smoothed coherence (time-average for each scale)
    smooth_window = 10
    coherence = np.zeros(len(scales))
    for i in range(len(scales)):
        # Smooth cross-spectrum and auto-spectra
        S_xy = np.convolve(np.abs(cross[i, :]), np.ones(smooth_window)/smooth_window, mode='valid')
        S_xx = np.convolve(np.abs(coefs_bid[i, :])**2, np.ones(smooth_window)/smooth_window, mode='valid')
        S_yy = np.convolve(np.abs(coefs_ask[i, :])**2, np.ones(smooth_window)/smooth_window, mode='valid')
        denom = np.sqrt(S_xx * S_yy)
        valid = denom > 0
        if valid.any():
            coherence[i] = np.mean(S_xy[valid] / denom[valid])

    print(f"\n  Wavelet coherence (bid vs ask movements):")
    print(f"    Mean coherence across all scales: {np.mean(coherence):.4f}")
    top_coh = np.argsort(coherence)[::-1][:5]
    for idx in top_coh:
        print(f"    Scale {scales[idx]:.1f}: coherence={coherence[idx]:.4f}")

    # Phase relationship at coherent scales
    for idx in top_coh[:3]:
        phase = np.angle(np.mean(cross[idx, :]))
        phase_deg = np.degrees(phase)
        print(f"    Scale {scales[idx]:.1f}: phase difference = {phase_deg:.1f} degrees "
              f"({'in-phase' if abs(phase_deg) < 30 else 'anti-phase' if abs(phase_deg) > 150 else 'lagged'})")

for data, label in [(d0, "Day 0"), (d1, "Day -1"), (d2, "Day -2")]:
    wavelet_analysis(data['mid'], data['dmid'], data['bid1'], data['ask1'], label)

# =============================================================================
# 9. MICROSTRUCTURE SIGNATURE PLOT
# =============================================================================
print("\n" + "=" * 80)
print("9. MICROSTRUCTURE SIGNATURE PLOT")
print("=" * 80)

def signature_plot(mid, dmid, label):
    """Realized variance at different sampling frequencies."""
    print(f"\n--- {label} (n={len(mid)}) ---")

    N = len(mid)
    max_skip = min(N // 10, 200)
    skips = np.unique(np.logspace(0, np.log10(max_skip), 50).astype(int))

    results = []
    for skip in skips:
        # Subsample the mid series
        subsampled = mid[::skip]
        if len(subsampled) < 5:
            continue

        returns = np.diff(subsampled)
        n_obs = len(returns)

        # Realized variance (annualized is meaningless here, keep per-tick)
        rv = np.sum(returns**2)  # total realized variance
        rv_per_tick = rv / (N - 1)  # normalized by total time span

        # Bias-corrected realized variance (subtract 2 * noise variance)
        # AC1 correction: RV_corrected = RV + 2 * sum(r_i * r_{i+1})
        if n_obs > 1:
            ac_correction = 2 * np.sum(returns[:-1] * returns[1:])
            rv_corrected = rv + ac_correction
            rv_corrected_per_tick = rv_corrected / (N - 1)
        else:
            rv_corrected_per_tick = rv_per_tick

        results.append({
            'skip': skip,
            'n_obs': n_obs,
            'rv_per_tick': rv_per_tick,
            'rv_corrected': rv_corrected_per_tick,
            'mean_return': np.mean(returns),
            'var_return': np.var(returns),
            'ac1': np.corrcoef(returns[:-1], returns[1:])[0,1] if n_obs > 2 else 0
        })

    print(f"  Sampling freq | RV/tick    | RV_corrected | AC(1)     | n_obs")
    print(f"  " + "-" * 70)
    for r in results[::max(1, len(results)//15)]:
        print(f"  skip={r['skip']:4d}      | {r['rv_per_tick']:.6f} | {r['rv_corrected']:.6f}   | {r['ac1']:+.4f}  | {r['n_obs']}")

    # Extract key metrics
    rv_1tick = results[0]['rv_per_tick'] if results else 0
    rv_10tick = None
    for r in results:
        if r['skip'] >= 10:
            rv_10tick = r['rv_per_tick']
            break

    if rv_10tick and rv_1tick > 0:
        noise_ratio = (rv_1tick - rv_10tick) / rv_1tick
        print(f"\n  Microstructure noise metrics:")
        print(f"    RV at 1-tick sampling: {rv_1tick:.6f}")
        print(f"    RV at 10-tick sampling: {rv_10tick:.6f}")
        print(f"    Noise fraction: {noise_ratio*100:.1f}%")

        # Estimate noise variance
        # Under bid-ask bounce: noise_var = spread^2 / 4
        # RV_1 = sigma^2 + 2*noise_var
        noise_var = (rv_1tick - rv_10tick) / 2 if rv_1tick > rv_10tick else 0
        print(f"    Estimated noise variance: {noise_var:.6f}")
        print(f"    Estimated noise std: {np.sqrt(noise_var):.4f}")

    # Optimal sampling frequency (minimize MSE of RV estimator)
    # Bandi-Russell: n* = (N / (4 * noise_var / sigma^2))^(1/3)  ... rough
    if rv_10tick and rv_1tick > rv_10tick:
        sigma2 = rv_10tick
        noise2 = noise_var
        if noise2 > 0 and sigma2 > 0:
            n_star = (len(mid) / (4 * noise2 / sigma2))**(1/3)
            optimal_skip = max(1, int(len(mid) / n_star))
            print(f"    Bandi-Russell optimal sampling: every {optimal_skip} ticks ({n_star:.0f} observations)")

    # AC structure at different frequencies
    print(f"\n  Autocorrelation decay across frequencies:")
    for r in results:
        if r['skip'] in [1, 2, 3, 5, 10, 20, 50]:
            print(f"    skip={r['skip']}: AC(1)={r['ac1']:+.4f}")

    # The key question: at what frequency does AC(1) cross zero?
    zero_crossing = None
    for i in range(1, len(results)):
        if results[i-1]['ac1'] < 0 and results[i]['ac1'] >= 0:
            zero_crossing = results[i]['skip']
            break

    if zero_crossing:
        print(f"\n  AC(1) crosses zero at skip={zero_crossing}")
        print(f"  ==> Below this frequency, mean-reversion dominates")
        print(f"  ==> Above this, the process looks like a random walk")
    else:
        last_ac = results[-1]['ac1'] if results else 0
        print(f"\n  AC(1) never crosses zero (last: {last_ac:.4f})")

    # Variance ratio test
    print(f"\n  Variance ratio tests (H0: random walk):")
    for q in [2, 5, 10, 20, 50]:
        if q < len(mid) // 5:
            ret_1 = np.diff(mid)
            ret_q = mid[q:] - mid[:-q]

            vr = np.var(ret_q) / (q * np.var(ret_1))

            # Z-statistic under heteroscedasticity
            T = len(ret_1)
            theta = 0
            for j in range(1, q):
                delta_j = T * np.sum((ret_1[j:]**2) * (ret_1[:-j]**2)) / (np.sum(ret_1**2))**2
                theta += (2 * (q - j) / q)**2 * delta_j

            z = (vr - 1) / np.sqrt(theta) if theta > 0 else 0
            p_val = 2 * (1 - stats.norm.cdf(abs(z)))

            sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
            print(f"    VR({q}): {vr:.4f}, z={z:+.3f}, p={p_val:.4f} {sig}")

for data, label in [(d0, "Day 0"), (d1, "Day -1"), (d2, "Day -2")]:
    signature_plot(data['mid'], data['dmid'], label)

# =============================================================================
# 10. EXPLOITABILITY SYNTHESIS
# =============================================================================
print("\n" + "=" * 80)
print("10. COMPREHENSIVE EXPLOITABILITY SYNTHESIS")
print("=" * 80)

print("""
=== QUESTION: Does any analysis reveal an EXPLOITABLE pattern ===
=== that the linear 4-lag regression doesn't already capture? ===
""")

# Quantitative test: build nonlinear predictors and compare to linear baseline
print("--- Quantitative Comparison: Linear vs Nonlinear Predictors ---")

for data, label in [(d0, "Day 0"), (d1, "Day -1"), (d2, "Day -2")]:
    dmid = data['dmid']
    spread = data['spread']
    n = len(dmid)

    # Dependent variable: dmid[t+1]
    y = dmid[4:]  # need 4 lags

    # Feature set 1: Linear 4-lag regression (baseline)
    X_linear = np.column_stack([dmid[3:-1], dmid[2:-2], dmid[1:-3], dmid[0:-4]])

    # Feature set 2: + spread state
    X_spread = np.column_stack([X_linear, spread[4:len(dmid)]])

    # Feature set 3: + nonlinear (squared terms, interactions)
    sq1 = dmid[3:-1]**2
    sq2 = dmid[2:-2]**2
    interact = dmid[3:-1] * dmid[2:-2]
    abs1 = np.abs(dmid[3:-1])
    sign_run = np.sign(dmid[3:-1]) * np.sign(dmid[2:-2])  # same-direction indicator
    X_nonlinear = np.column_stack([X_linear, sq1, sq2, interact, abs1, sign_run])

    # Feature set 4: + HMM state proxy (|dmid| > 2.5 as "volatile state")
    hmm_proxy = (np.abs(dmid[3:-1]) > 2.5).astype(float)
    X_hmm = np.column_stack([X_linear, hmm_proxy, hmm_proxy * dmid[3:-1]])

    # Feature set 5: + sign-sequence features
    sign_triple = (np.sign(dmid[3:-1]) + np.sign(dmid[2:-2]) + np.sign(dmid[1:-3]))
    momentum = np.sign(dmid[3:-1]) == np.sign(dmid[2:-2])  # consecutive same sign
    X_seq = np.column_stack([X_linear, sign_triple, momentum.astype(float)])

    # Fit each model and compute OOS R²
    split = int(0.6 * len(y))

    models = {
        'Linear 4-lag': X_linear,
        '+ spread': X_spread,
        '+ nonlinear': X_nonlinear,
        '+ HMM proxy': X_hmm,
        '+ sequences': X_seq,
    }

    print(f"\n  {label}: OOS R² comparison (60/40 split, n={len(y)})")
    for name, X in models.items():
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        # OLS fit
        X_train_b = np.column_stack([np.ones(len(X_train)), X_train])
        X_test_b = np.column_stack([np.ones(len(X_test)), X_test])

        try:
            beta = np.linalg.lstsq(X_train_b, y_train, rcond=None)[0]
            y_pred = X_test_b @ beta
            ss_res = np.sum((y_test - y_pred)**2)
            ss_tot = np.sum((y_test - np.mean(y_test))**2)
            r2_oos = 1 - ss_res / ss_tot

            # Also in-sample
            y_pred_is = X_train_b @ beta
            ss_res_is = np.sum((y_train - y_pred_is)**2)
            ss_tot_is = np.sum((y_train - np.mean(y_train))**2)
            r2_is = 1 - ss_res_is / ss_tot_is

            # RMSE
            rmse = np.sqrt(np.mean((y_test - y_pred)**2))

            print(f"    {name:20s}: IS R²={r2_is:.4f}, OOS R²={r2_oos:.4f}, RMSE={rmse:.4f}")
        except:
            print(f"    {name:20s}: FAILED (singular matrix)")

    # Direct test: after removing linear prediction, is there nonlinear structure?
    print(f"\n  Residual nonlinearity test (after removing linear prediction):")
    X_b = np.column_stack([np.ones(len(X_linear)), X_linear])
    beta = np.linalg.lstsq(X_b, y, rcond=None)[0]
    residuals = y - X_b @ beta

    # Test 1: BDS test for independence (simplified)
    # Correlation integral ratio at different epsilons
    eps_vals = [0.5, 1.0, 1.5]
    for eps in eps_vals:
        n_res = len(residuals)
        # C(2, eps)
        n_close = 0
        n_total = 0
        subsample_idx = np.random.choice(n_res, min(500, n_res), replace=False)
        for i in range(len(subsample_idx)):
            for j in range(i+1, len(subsample_idx)):
                ii, jj = subsample_idx[i], subsample_idx[j]
                n_total += 1
                if abs(residuals[ii] - residuals[jj]) < eps:
                    n_close += 1
        C1 = n_close / max(n_total, 1)

        # C(2, eps) for pairs
        n_close_pair = 0
        n_total_pair = 0
        for i in range(len(subsample_idx)):
            for j in range(i+1, len(subsample_idx)):
                ii, jj = subsample_idx[i], subsample_idx[j]
                if ii + 1 < n_res and jj + 1 < n_res:
                    n_total_pair += 1
                    if (abs(residuals[ii] - residuals[jj]) < eps and
                        abs(residuals[ii+1] - residuals[jj+1]) < eps):
                        n_close_pair += 1
        C2 = n_close_pair / max(n_total_pair, 1)

        bds_stat = C2 - C1**2
        print(f"    BDS(eps={eps}): C1={C1:.4f}, C2={C2:.4f}, C2-C1²={bds_stat:+.6f}")

    # Test 2: ARCH effects in residuals
    res_sq = residuals**2
    ac1_sq = np.corrcoef(res_sq[:-1], res_sq[1:])[0,1]
    ac2_sq = np.corrcoef(res_sq[:-2], res_sq[2:])[0,1]
    print(f"    ARCH test: AC(1) of residuals²={ac1_sq:.4f}, AC(2)={ac2_sq:.4f}")

    # Test 3: Quantile-specific prediction accuracy
    # Does the linear model work better in some ranges?
    pred_full = X_b @ beta
    for q_lo, q_hi, qlabel in [(0, 10, "bottom 10%"), (45, 55, "middle 10%"), (90, 100, "top 10%")]:
        lo = np.percentile(dmid[3:-1], q_lo)
        hi = np.percentile(dmid[3:-1], q_hi)
        mask = (dmid[3:-1] >= lo) & (dmid[3:-1] <= hi)
        if mask.sum() > 10:
            r2_q = 1 - np.sum(residuals[mask]**2) / np.sum((y[mask] - np.mean(y[mask]))**2) if np.var(y[mask]) > 0 else 0
            print(f"    R² for {qlabel} of lag-1: {r2_q:.4f} (n={mask.sum()})")

# =============================================================================
# FINAL: The PnL Implication
# =============================================================================
print("\n" + "=" * 80)
print("FINAL: TRADING IMPLICATIONS")
print("=" * 80)

print("""
For each analysis, the key question: what would change in our trading?

Remember the PnL formula:
  PnL = Fill_Rate x Spread_Captured - Inventory_Risk

And the constraint: Fill rate is EXOGENOUS (random taker bot, ~82 fills/2k ticks).
""")

# Compute the theoretical maximum gain from perfect nonlinear prediction
for data, label in [(d0, "Day 0")]:
    dmid = data['dmid']
    spread = data['spread']

    # Current strategy: 4-lag regression predicts dmid, posts at best+/-1
    # The regression shifts our FV by ~1 tick on ~20 ticks/day
    # What if we had PERFECT prediction of dmid[t+1]?

    print(f"\n  {label} — Theoretical PnL bounds:")

    # If we know dmid[t+1] perfectly:
    # - When |predicted_dmid| > half_spread, we should take (cross the spread)
    # - Otherwise, post at best+/-1 as usual

    # How often would perfect knowledge change our decision?
    half_spread = spread[:-1] / 2.0
    optimal_take = np.abs(dmid) > half_spread
    print(f"    Ticks where |dmid| > half_spread (profitable cross): {optimal_take.sum()} ({optimal_take.mean()*100:.1f}%)")
    print(f"    Average |dmid| on those ticks: {np.mean(np.abs(dmid[optimal_take])):.2f}")
    print(f"    Average half_spread on those ticks: {np.mean(half_spread[optimal_take]):.2f}")
    print(f"    Average edge per cross: {np.mean(np.abs(dmid[optimal_take]) - half_spread[optimal_take]):.2f}")

    # With perfect prediction, additional PnL from taking:
    # Edge = |dmid| - half_spread (only when positive)
    edge = np.abs(dmid) - half_spread
    positive_edge = edge[edge > 0]
    print(f"    Total possible take edge (perfect prediction): {np.sum(positive_edge):.2f} over {len(positive_edge)} takes")
    print(f"    Our ACTUAL total PnL (s36): ~2,896 over 2k ticks")
    print(f"    ==> Perfect prediction max additional: {np.sum(positive_edge):.0f}")

    # But... we can only trade 80 lots max, and each take costs spread
    # Realistic: with 80 lot limit, ~82 fills, avg spread ~7
    # Even perfect prediction only helps at the MARGIN

    # What does the nonlinear structure buy?
    # If HMM state gives +0.3 bits (10% info gain), and linear gives R²=0.20:
    # Max nonlinear R² improvement: 0.20 * 1.1 = 0.22
    # RMSE reduction: sqrt(1-0.22)/sqrt(1-0.20) = 0.99 -> 1% improvement
    print(f"\n    Even 10% information gain translates to ~1% RMSE improvement")
    print(f"    At ~82 fills with ~7 spread: 1% x 82 x 7 = ~5.7 PnL")
    print(f"    Current score: 2,896. Theoretical ceiling: ~2,901")
    print(f"    ==> NONLINEAR FEATURES CANNOT MEANINGFULLY IMPROVE PnL")

    # But wait — what about the SIGN prediction?
    # If we can predict the SIGN of dmid better, we can post on the right side
    print(f"\n  Sign prediction accuracy:")
    # Linear model sign accuracy
    X_b = np.column_stack([np.ones(len(dmid)-4), dmid[3:-1], dmid[2:-2], dmid[1:-3], dmid[0:-4]])
    y = dmid[4:]
    beta = np.linalg.lstsq(X_b, y, rcond=None)[0]
    pred = X_b @ beta

    sign_correct_linear = np.mean(np.sign(pred) == np.sign(y))
    # Nonlinear (using HMM proxy)
    # After big move: reversal probability is ~0.53 (section 6)
    # After small move: 0.5 (no info)
    # Overall sign accuracy is bounded by the prediction quality

    # What matters: sign accuracy WHEN WE HAVE A FILL
    # Fill happens when taker crosses spread
    # We profit when our post is on the right side of FV
    print(f"    Linear model sign accuracy: {sign_correct_linear:.4f}")
    print(f"    Baseline (always predict reversal): ~0.53")
    print(f"    Gap: {sign_correct_linear - 0.53:.4f}")
    print(f"    Per-fill value of correct sign: ~3.5 ticks (half spread)")
    print(f"    Fills per day: ~82")
    print(f"    ==> Sign improvement worth: {(sign_correct_linear - 0.53) * 82 * 3.5:.1f} PnL")

print("\n" + "=" * 80)
print("SYNTHESIS COMPLETE")
print("=" * 80)
