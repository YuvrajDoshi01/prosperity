"""
Deep Mathematical Structure Analysis of TOMATOES Price Data
===========================================================
Jim Simons-level investigation into hidden structure beyond linear models.
"""

import numpy as np
import pandas as pd
from scipy import stats, signal, fft
from scipy.optimize import minimize
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# DATA LOADING
# =============================================================================
def load_tomatoes(path):
    """Load TOMATOES data from CSV, return structured dict."""
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

    # Microprice
    microprice = (bid1 * av1 + ask1 * bv1) / (bv1 + av1)

    return {
        'mid': mid, 'bid1': bid1, 'ask1': ask1,
        'bv1': bv1, 'av1': av1, 'bv2': bv2, 'av2': av2,
        'spread': spread, 'dmid': dmid, 'microprice': microprice,
        'timestamps': tom['timestamp'].values,
        'n': len(mid)
    }

print("=" * 80)
print("LOADING DATA")
print("=" * 80)

base = '/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0'
d0 = load_tomatoes(f'{base}/prices_round_0_day_0.csv')
d1 = load_tomatoes(f'{base}/prices_round_0_day_-1.csv')
d2 = load_tomatoes(f'{base}/prices_round_0_day_-2.csv')

print(f"Day  0: {d0['n']} ticks, mid range [{d0['mid'].min()}, {d0['mid'].max()}]")
print(f"Day -1: {d1['n']} ticks, mid range [{d1['mid'].min()}, {d1['mid'].max()}]")
print(f"Day -2: {d2['n']} ticks, mid range [{d2['mid'].min()}, {d2['mid'].max()}]")
print(f"Day  0 dmid unique values: {np.unique(d0['dmid'])}")
print(f"Day  0 spread unique values: {np.unique(d0['spread'])}")

# =============================================================================
# 1. FOURIER / SPECTRAL ANALYSIS
# =============================================================================
print("\n" + "=" * 80)
print("1. FOURIER / SPECTRAL ANALYSIS")
print("=" * 80)

def spectral_analysis(dmid, label, spread=None, volume=None):
    """Full spectral analysis of a series."""
    n = len(dmid)

    # FFT of dmid
    freqs = np.fft.rfftfreq(n, d=1.0)  # in cycles per tick
    fft_dmid = np.fft.rfft(dmid)
    psd_dmid = np.abs(fft_dmid)**2 / n

    # Find dominant frequencies (exclude DC)
    psd_no_dc = psd_dmid[1:]
    freqs_no_dc = freqs[1:]

    # Top 10 peaks
    peak_idx = np.argsort(psd_no_dc)[::-1][:10]
    print(f"\n--- {label} ---")
    print(f"  dmid FFT: {n} points, {len(freqs)} frequency bins")
    print(f"  Top 10 spectral peaks (dmid):")
    for i, idx in enumerate(peak_idx):
        freq = freqs_no_dc[idx]
        period = 1.0/freq if freq > 0 else np.inf
        power = psd_no_dc[idx]
        print(f"    #{i+1}: freq={freq:.6f} cyc/tick, period={period:.1f} ticks, power={power:.2f}")

    # Test for white noise: compare to flat spectrum
    mean_psd = np.mean(psd_no_dc)
    max_psd = np.max(psd_no_dc)
    spectral_ratio = max_psd / mean_psd
    print(f"  Max/Mean spectral ratio: {spectral_ratio:.2f} (white noise ~3-5 for this N)")

    # Kolmogorov-Smirnov test for exponential distribution of periodogram
    # Under H0 (white noise), periodogram values are exponentially distributed
    normalized_psd = psd_no_dc / mean_psd
    ks_stat, ks_p = stats.kstest(normalized_psd, 'expon', args=(0, 1))
    print(f"  KS test vs exponential (white noise): stat={ks_stat:.4f}, p={ks_p:.6f}")

    # Fisher's test for periodicity: is the largest peak significant?
    g_stat = max_psd / np.sum(psd_no_dc)
    n_freqs = len(psd_no_dc)
    # Approximate p-value for Fisher's g-test
    fisher_p = 1 - (1 - np.exp(-g_stat * n_freqs))**n_freqs
    fisher_p = max(fisher_p, 0)
    print(f"  Fisher's g-test: g={g_stat:.6f}, approx p={fisher_p:.6f}")

    # Spread spectrum
    if spread is not None:
        fft_spread = np.fft.rfft(spread - np.mean(spread))
        psd_spread = np.abs(fft_spread)**2 / len(spread)
        peak_s = np.argsort(psd_spread[1:])[::-1][:5]
        print(f"  Top 5 spectral peaks (spread):")
        for i, idx in enumerate(peak_s):
            freq = freqs_no_dc[idx] if idx < len(freqs_no_dc) else 0
            period = 1.0/freq if freq > 0 else np.inf
            print(f"    #{i+1}: freq={freq:.6f}, period={period:.1f} ticks, power={psd_spread[1:][idx]:.2f}")

    # Volume spectrum
    if volume is not None:
        fft_vol = np.fft.rfft(volume - np.mean(volume))
        psd_vol = np.abs(fft_vol)**2 / len(volume)
        peak_v = np.argsort(psd_vol[1:])[::-1][:5]
        print(f"  Top 5 spectral peaks (volume):")
        for i, idx in enumerate(peak_v):
            freq = freqs_no_dc[idx] if idx < len(freqs_no_dc) else 0
            period = 1.0/freq if freq > 0 else np.inf
            print(f"    #{i+1}: freq={freq:.6f}, period={period:.1f} ticks, power={psd_vol[1:][idx]:.2f}")

    # Cross-spectral coherence between spread and dmid
    if spread is not None:
        # Use Welch's method for coherence
        spread_diff = spread[:-1]  # align with dmid
        min_len = min(len(dmid), len(spread_diff))
        nperseg = min(256, min_len // 4)
        if nperseg >= 16:
            f_coh, coh = signal.coherence(dmid[:min_len], spread_diff[:min_len],
                                          nperseg=nperseg, fs=1.0)
            max_coh_idx = np.argmax(coh[1:]) + 1
            print(f"  Max coherence (dmid vs spread): {coh[max_coh_idx]:.4f} at freq={f_coh[max_coh_idx]:.4f}")
            print(f"  Mean coherence: {np.mean(coh[1:]):.4f}")

            # Top 5 coherence frequencies
            top_coh = np.argsort(coh[1:])[::-1][:5] + 1
            print(f"  Top 5 coherence peaks:")
            for i, idx in enumerate(top_coh):
                print(f"    freq={f_coh[idx]:.4f}, coherence={coh[idx]:.4f}, period={1/f_coh[idx]:.1f} ticks")

    return psd_dmid, freqs

# Run for all 3 days
psd0, freq0 = spectral_analysis(d0['dmid'], "Day 0", d0['spread'], d0['bv1'])
psd1, freq1 = spectral_analysis(d1['dmid'], "Day -1", d1['spread'], d1['bv1'])
psd2, freq2 = spectral_analysis(d2['dmid'], "Day -2", d2['spread'], d2['bv1'])

# Cross-day spectral stability
print("\n--- Cross-Day Spectral Stability ---")
# Compare power at similar frequencies (resample to common grid)
# Use day -1 and day -2 (same length) for direct comparison
if len(d1['dmid']) == len(d2['dmid']):
    corr_psd = np.corrcoef(
        np.log1p(np.abs(np.fft.rfft(d1['dmid']))**2),
        np.log1p(np.abs(np.fft.rfft(d2['dmid']))**2)
    )[0,1]
    print(f"  Log-PSD correlation (day -1 vs day -2): {corr_psd:.4f}")
print(f"  If < 0.3: spectra are NOT stable across days (peaks are noise)")

# =============================================================================
# 2. ENTROPY & INFORMATION THEORY
# =============================================================================
print("\n" + "=" * 80)
print("2. ENTROPY & INFORMATION THEORY")
print("=" * 80)

def entropy_analysis(dmid, spread, volume, label):
    """Full entropy and information theory analysis."""
    print(f"\n--- {label} ---")

    # Discretize dmid (it's already in 0.5 increments)
    dmid_vals, dmid_counts = np.unique(dmid, return_counts=True)
    dmid_probs = dmid_counts / len(dmid)

    # Shannon entropy of dmid
    H_dmid = -np.sum(dmid_probs * np.log2(dmid_probs + 1e-15))
    print(f"  Shannon entropy H(dmid): {H_dmid:.4f} bits")
    print(f"  Max possible entropy (uniform over {len(dmid_vals)} values): {np.log2(len(dmid_vals)):.4f} bits")
    print(f"  Efficiency: {H_dmid / np.log2(len(dmid_vals)):.4f}")

    # Distribution of dmid
    print(f"  dmid distribution:")
    for val, prob in sorted(zip(dmid_vals, dmid_probs), key=lambda x: -x[1])[:10]:
        print(f"    dmid={val:+.1f}: {prob:.4f} ({prob*100:.1f}%)")

    # Conditional entropy H(dmid[t+1] | dmid[t])
    # Build joint distribution
    pairs = list(zip(dmid[:-1], dmid[1:]))
    pair_counts = {}
    for p in pairs:
        pair_counts[p] = pair_counts.get(p, 0) + 1

    n_pairs = len(pairs)

    # H(X,Y)
    H_joint = 0
    for count in pair_counts.values():
        p = count / n_pairs
        H_joint -= p * np.log2(p)

    # H(X) for dmid[t]
    H_x = H_dmid  # same distribution

    # H(Y|X) = H(X,Y) - H(X)
    H_cond = H_joint - H_x
    print(f"  Joint entropy H(dmid[t], dmid[t+1]): {H_joint:.4f} bits")
    print(f"  Conditional entropy H(dmid[t+1] | dmid[t]): {H_cond:.4f} bits")
    print(f"  Information gain: {H_dmid - H_cond:.4f} bits ({(H_dmid - H_cond)/H_dmid*100:.1f}% reduction)")

    # Mutual information I(dmid; spread)
    spread_vals, spread_counts = np.unique(spread[:-1], return_counts=True)
    spread_probs = spread_counts / len(spread[:-1])
    H_spread = -np.sum(spread_probs * np.log2(spread_probs + 1e-15))

    # I(dmid[t+1]; spread[t])
    pairs_ds = list(zip(spread[:-1], dmid))  # spread[t] -> dmid[t+1] would need offset
    # Actually: spread at time t, dmid at time t (same tick)
    pairs_ds = list(zip(spread[:-1], dmid[:-1]))  # both at time t
    pair_ds_counts = {}
    for p in pairs_ds:
        pair_ds_counts[p] = pair_ds_counts.get(p, 0) + 1
    H_joint_ds = 0
    for count in pair_ds_counts.values():
        p = count / len(pairs_ds)
        H_joint_ds -= p * np.log2(p)
    MI_dmid_spread = H_dmid + H_spread - H_joint_ds
    print(f"\n  H(spread): {H_spread:.4f} bits")
    print(f"  MI(dmid, spread) [same tick]: {MI_dmid_spread:.4f} bits")

    # MI(spread[t], dmid[t+1]) — predictive
    pairs_pred = list(zip(spread[:-1], dmid[1:] if len(dmid) > 1 else dmid))
    min_len = min(len(spread)-1, len(dmid)-1)
    pairs_pred = list(zip(spread[:min_len], dmid[1:min_len+1]))
    pair_pred_counts = {}
    for p in pairs_pred:
        pair_pred_counts[p] = pair_pred_counts.get(p, 0) + 1
    H_joint_pred = 0
    for count in pair_pred_counts.values():
        p = count / len(pairs_pred)
        H_joint_pred -= p * np.log2(p)

    # H(dmid[t+1])
    dmid_next = dmid[1:min_len+1]
    nv, nc = np.unique(dmid_next, return_counts=True)
    H_next = -np.sum((nc/len(dmid_next)) * np.log2(nc/len(dmid_next) + 1e-15))

    MI_spread_next = H_next + H_spread - H_joint_pred
    print(f"  MI(spread[t], dmid[t+1]) [predictive]: {MI_spread_next:.4f} bits")

    # Transfer entropy: TE(spread -> dmid) = H(dmid[t+1]|dmid[t]) - H(dmid[t+1]|dmid[t],spread[t])
    # Build triple distribution
    min_len3 = min(len(dmid)-1, len(spread)-1)
    triples = list(zip(dmid[:min_len3], spread[:min_len3], dmid[1:min_len3+1]))
    triple_counts = {}
    for t in triples:
        triple_counts[t] = triple_counts.get(t, 0) + 1

    H_triple = 0
    for count in triple_counts.values():
        p = count / len(triples)
        H_triple -= p * np.log2(p)

    # H(dmid[t], spread[t])
    pair_ms = list(zip(dmid[:min_len3], spread[:min_len3]))
    pair_ms_counts = {}
    for p in pair_ms:
        pair_ms_counts[p] = pair_ms_counts.get(p, 0) + 1
    H_pair_ms = 0
    for count in pair_ms_counts.values():
        p = count / len(pair_ms)
        H_pair_ms -= p * np.log2(p)

    # TE(spread -> dmid) = H(dmid[t+1], dmid[t], spread[t]) - H(dmid[t], spread[t])
    #                     - H(dmid[t+1], dmid[t]) + H(dmid[t])
    TE_spread_to_dmid = H_triple - H_pair_ms - H_joint + H_x
    print(f"  Transfer entropy TE(spread -> dmid): {TE_spread_to_dmid:.4f} bits")

    # TE(dmid -> spread): does price change cause spread change?
    # spread[t+1] | spread[t], dmid[t]
    min_len4 = min(len(spread)-1, len(dmid))
    triples2 = list(zip(spread[:min_len4], dmid[:min_len4], spread[1:min_len4+1]))
    triple2_counts = {}
    for t in triples2:
        triple2_counts[t] = triple2_counts.get(t, 0) + 1
    H_triple2 = 0
    for count in triple2_counts.values():
        p = count / len(triples2)
        H_triple2 -= p * np.log2(p)

    # H(spread[t+1], spread[t])
    pair_ss = list(zip(spread[:min_len4], spread[1:min_len4+1]))
    pair_ss_counts = {}
    for p in pair_ss:
        pair_ss_counts[p] = pair_ss_counts.get(p, 0) + 1
    H_pair_ss = 0
    for count in pair_ss_counts.values():
        p = count / len(pair_ss)
        H_pair_ss -= p * np.log2(p)

    H_spread_single = H_spread
    TE_dmid_to_spread = H_triple2 - H_pair_ms - H_pair_ss + H_spread_single
    print(f"  Transfer entropy TE(dmid -> spread): {TE_dmid_to_spread:.4f} bits")

    if abs(TE_spread_to_dmid) > abs(TE_dmid_to_spread):
        print(f"  ==> Spread CAUSES dmid changes (TE ratio: {TE_spread_to_dmid/max(abs(TE_dmid_to_spread),1e-10):.2f}x)")
    else:
        print(f"  ==> dmid changes CAUSE spread changes (TE ratio: {TE_dmid_to_spread/max(abs(TE_spread_to_dmid),1e-10):.2f}x)")

    # Approximate entropy (ApEn)
    def approx_entropy(series, m=2, r_factor=0.2):
        """Compute approximate entropy."""
        r = r_factor * np.std(series)
        N = len(series)

        def phi(m_val):
            patterns = np.array([series[i:i+m_val] for i in range(N - m_val + 1)])
            C = np.zeros(len(patterns))
            for i in range(len(patterns)):
                dists = np.max(np.abs(patterns - patterns[i]), axis=1)
                C[i] = np.sum(dists <= r) / (N - m_val + 1)
            return np.mean(np.log(C + 1e-15))

        return abs(phi(m) - phi(m+1))

    # Use subsample for speed
    subsample = dmid[:min(1000, len(dmid))]
    apen = approx_entropy(subsample, m=2, r_factor=0.2)
    print(f"\n  Approximate entropy (m=2, r=0.2*std): {apen:.4f}")

    # Sample entropy
    def sample_entropy(series, m=2, r_factor=0.2):
        """Compute sample entropy."""
        r = r_factor * np.std(series)
        N = len(series)

        def count_matches(m_val):
            patterns = np.array([series[i:i+m_val] for i in range(N - m_val)])
            count = 0
            for i in range(len(patterns)):
                for j in range(i+1, len(patterns)):
                    if np.max(np.abs(patterns[i] - patterns[j])) <= r:
                        count += 1
            return count

        A = count_matches(m+1)
        B = count_matches(m)
        if B == 0:
            return float('inf')
        return -np.log(A / B)

    sampen = sample_entropy(subsample[:500], m=2, r_factor=0.2)
    print(f"  Sample entropy (m=2, r=0.2*std): {sampen:.4f}")
    print(f"  (Higher = more random/complex, Lower = more regular/predictable)")

    return H_dmid, H_cond, MI_dmid_spread, MI_spread_next, TE_spread_to_dmid

for data, label in [(d0, "Day 0"), (d1, "Day -1"), (d2, "Day -2")]:
    entropy_analysis(data['dmid'], data['spread'], data['bv1'], label)

# =============================================================================
# 3. HIDDEN MARKOV MODEL (from scratch)
# =============================================================================
print("\n" + "=" * 80)
print("3. HIDDEN MARKOV MODEL")
print("=" * 80)

def fit_gaussian_hmm(obs, n_states, n_iter=100, n_restarts=5):
    """
    Fit a Gaussian HMM using EM algorithm (Baum-Welch).
    obs: 1D array of observations
    n_states: number of hidden states
    """
    best_ll = -np.inf
    best_params = None

    for restart in range(n_restarts):
        np.random.seed(restart * 42)
        N = n_states
        T = len(obs)

        # Initialize parameters
        pi = np.ones(N) / N  # initial state probs
        A = np.random.dirichlet(np.ones(N) * 5, size=N)  # transition matrix

        # Initialize means by quantiles
        quantiles = np.linspace(0, 1, N+2)[1:-1]
        means = np.quantile(obs, quantiles)
        stds = np.ones(N) * np.std(obs) / N

        for iteration in range(n_iter):
            # E-step: Forward-backward
            # Emission probabilities
            B = np.zeros((T, N))
            for j in range(N):
                B[:, j] = stats.norm.pdf(obs, means[j], stds[j] + 1e-10)
            B = np.maximum(B, 1e-300)

            # Forward
            alpha = np.zeros((T, N))
            alpha[0] = pi * B[0]
            scale = np.zeros(T)
            scale[0] = np.sum(alpha[0])
            alpha[0] /= scale[0]

            for t in range(1, T):
                alpha[t] = B[t] * (alpha[t-1] @ A)
                scale[t] = np.sum(alpha[t])
                if scale[t] < 1e-300:
                    scale[t] = 1e-300
                alpha[t] /= scale[t]

            log_likelihood = np.sum(np.log(scale + 1e-300))

            # Backward
            beta = np.zeros((T, N))
            beta[-1] = 1.0

            for t in range(T-2, -1, -1):
                beta[t] = A @ (B[t+1] * beta[t+1])
                beta[t] /= scale[t+1]

            # Posterior
            gamma = alpha * beta
            gamma /= gamma.sum(axis=1, keepdims=True) + 1e-300

            # Xi
            xi = np.zeros((N, N))
            for t in range(T-1):
                tmp = np.outer(alpha[t], B[t+1] * beta[t+1]) * A
                tmp /= tmp.sum() + 1e-300
                xi += tmp

            # M-step
            pi = gamma[0] / (gamma[0].sum() + 1e-300)

            for j in range(N):
                gamma_sum = gamma[:, j].sum() + 1e-10
                means[j] = np.sum(gamma[:, j] * obs) / gamma_sum
                stds[j] = np.sqrt(np.sum(gamma[:, j] * (obs - means[j])**2) / gamma_sum)
                stds[j] = max(stds[j], 0.01)

            # Normalize transition matrix
            for i in range(N):
                row_sum = xi[i].sum()
                if row_sum > 0:
                    A[i] = xi[i] / row_sum
                else:
                    A[i] = np.ones(N) / N

        if log_likelihood > best_ll:
            best_ll = log_likelihood
            # Viterbi decoding
            delta = np.zeros((T, N))
            psi = np.zeros((T, N), dtype=int)

            log_pi = np.log(pi + 1e-300)
            log_A = np.log(A + 1e-300)
            log_B = np.zeros((T, N))
            for j in range(N):
                log_B[:, j] = stats.norm.logpdf(obs, means[j], stds[j] + 1e-10)

            delta[0] = log_pi + log_B[0]
            for t in range(1, T):
                for j in range(N):
                    candidates = delta[t-1] + log_A[:, j]
                    psi[t, j] = np.argmax(candidates)
                    delta[t, j] = candidates[psi[t, j]] + log_B[t, j]

            states = np.zeros(T, dtype=int)
            states[-1] = np.argmax(delta[-1])
            for t in range(T-2, -1, -1):
                states[t] = psi[t+1, states[t+1]]

            best_params = {
                'means': means.copy(), 'stds': stds.copy(),
                'A': A.copy(), 'pi': pi.copy(),
                'll': log_likelihood, 'states': states.copy(),
                'gamma': gamma.copy()
            }

    return best_params

def hmm_analysis(dmid, label, n_states_list=[2, 3]):
    """Fit and analyze HMMs."""
    print(f"\n--- {label} ---")

    for n_states in n_states_list:
        print(f"\n  {n_states}-state HMM:")
        params = fit_gaussian_hmm(dmid, n_states, n_iter=80, n_restarts=5)

        # Sort states by mean
        order = np.argsort(params['means'])
        means = params['means'][order]
        stds = params['stds'][order]
        A = params['A'][order][:, order]
        states = np.zeros_like(params['states'])
        for new_idx, old_idx in enumerate(order):
            states[params['states'] == old_idx] = new_idx

        print(f"    Log-likelihood: {params['ll']:.2f}")
        print(f"    State parameters:")
        for i in range(n_states):
            state_mask = states == i
            frac = np.mean(state_mask)
            print(f"      State {i}: mean={means[i]:.3f}, std={stds[i]:.3f}, fraction={frac:.3f}")

        print(f"    Transition matrix:")
        for i in range(n_states):
            row = "      " + " ".join([f"{A[i,j]:.3f}" for j in range(n_states)])
            print(row)

        # Predictive power: does state[t] predict dmid[t+1]?
        if len(dmid) > 1:
            next_dmid = dmid[1:]
            curr_states = states[:-1]
            print(f"    Predictive power (state[t] -> dmid[t+1]):")
            for s in range(n_states):
                mask = curr_states == s
                if mask.sum() > 10:
                    next_vals = next_dmid[mask]
                    print(f"      State {s}: E[dmid[t+1]]={np.mean(next_vals):+.4f}, "
                          f"std={np.std(next_vals):.4f}, n={mask.sum()}")

        # Persistence
        state_durations = []
        current_state = states[0]
        duration = 1
        for i in range(1, len(states)):
            if states[i] == current_state:
                duration += 1
            else:
                state_durations.append((current_state, duration))
                current_state = states[i]
                duration = 1
        state_durations.append((current_state, duration))

        print(f"    State duration statistics:")
        for s in range(n_states):
            durs = [d for st, d in state_durations if st == s]
            if durs:
                print(f"      State {s}: mean={np.mean(durs):.1f}, median={np.median(durs):.0f}, "
                      f"max={np.max(durs)}, n_episodes={len(durs)}")

        # BIC for model selection
        n_params = n_states**2 + 2*n_states + n_states - 1  # A + means + stds + pi
        bic = -2 * params['ll'] + n_params * np.log(len(dmid))
        aic = -2 * params['ll'] + 2 * n_params
        print(f"    BIC: {bic:.2f}, AIC: {aic:.2f}")

    return params  # return last fit

for data, label in [(d0, "Day 0"), (d1, "Day -1"), (d2, "Day -2")]:
    hmm_analysis(data['dmid'], label)

# =============================================================================
# 4. FRACTAL / SCALING ANALYSIS
# =============================================================================
print("\n" + "=" * 80)
print("4. FRACTAL / SCALING ANALYSIS")
print("=" * 80)

def hurst_rs(series):
    """R/S analysis for Hurst exponent."""
    N = len(series)
    max_k = int(np.log2(N)) - 1
    ns = []
    rs = []

    for k in range(2, max_k + 1):
        n = 2**k
        n_segments = N // n
        if n_segments < 1:
            break

        rs_vals = []
        for seg in range(n_segments):
            subseries = series[seg*n:(seg+1)*n]
            mean = np.mean(subseries)
            deviations = subseries - mean
            cumdev = np.cumsum(deviations)
            R = np.max(cumdev) - np.min(cumdev)
            S = np.std(subseries, ddof=1)
            if S > 0:
                rs_vals.append(R / S)

        if rs_vals:
            ns.append(n)
            rs.append(np.mean(rs_vals))

    log_n = np.log(ns)
    log_rs = np.log(rs)
    slope, intercept, r, p, se = stats.linregress(log_n, log_rs)
    return slope, r**2, ns, rs

def dfa(series, orders=[1, 2]):
    """Detrended Fluctuation Analysis."""
    N = len(series)
    y = np.cumsum(series - np.mean(series))

    results = {}
    for order in orders:
        scales = np.unique(np.logspace(np.log10(10), np.log10(N//4), 30).astype(int))
        scales = scales[scales >= order + 2]

        flucts = []
        valid_scales = []

        for s in scales:
            n_segments = N // s
            if n_segments < 1:
                continue

            rms_vals = []
            for seg in range(n_segments):
                segment = y[seg*s:(seg+1)*s]
                x = np.arange(s)
                coeffs = np.polyfit(x, segment, order)
                trend = np.polyval(coeffs, x)
                rms_vals.append(np.sqrt(np.mean((segment - trend)**2)))

            if rms_vals:
                flucts.append(np.mean(rms_vals))
                valid_scales.append(s)

        if len(valid_scales) > 2:
            log_s = np.log(valid_scales)
            log_f = np.log(flucts)
            slope, intercept, r, p, se = stats.linregress(log_s, log_f)
            results[order] = {
                'alpha': slope, 'r2': r**2,
                'scales': valid_scales, 'flucts': flucts
            }

            # Check for crossover
            mid = len(log_s) // 2
            if mid > 2 and len(log_s) - mid > 2:
                slope1, _, r1, _, _ = stats.linregress(log_s[:mid], log_f[:mid])
                slope2, _, r2, _, _ = stats.linregress(log_s[mid:], log_f[mid:])
                results[order]['alpha_short'] = slope1
                results[order]['alpha_long'] = slope2
                results[order]['crossover_scale'] = valid_scales[mid]

    return results

def fractal_analysis(mid, dmid, label):
    """Full fractal analysis."""
    print(f"\n--- {label} ---")

    # Hurst exponent via R/S
    H_rs, r2_rs, _, _ = hurst_rs(mid)
    print(f"  Hurst exponent (R/S): H={H_rs:.4f}, R²={r2_rs:.4f}")

    H_rs_dmid, r2_rs_dmid, _, _ = hurst_rs(dmid)
    print(f"  Hurst exponent of dmid (R/S): H={H_rs_dmid:.4f}, R²={r2_rs_dmid:.4f}")

    # DFA
    dfa_results = dfa(mid, orders=[1, 2])
    for order, res in dfa_results.items():
        print(f"  DFA-{order}: alpha={res['alpha']:.4f}, R²={res['r2']:.4f}")
        if 'alpha_short' in res:
            print(f"    Short scales (< {res['crossover_scale']} ticks): alpha={res['alpha_short']:.4f}")
            print(f"    Long scales (>= {res['crossover_scale']} ticks): alpha={res['alpha_long']:.4f}")
            if abs(res['alpha_short'] - res['alpha_long']) > 0.1:
                print(f"    ==> CROSSOVER DETECTED! Scale dependence in dynamics.")

    # Interpretation
    alpha = dfa_results.get(1, {}).get('alpha', 0.5)
    if alpha < 0.5:
        print(f"  Interpretation: alpha={alpha:.3f} < 0.5 => ANTI-PERSISTENT (mean-reverting)")
    elif alpha < 1.0:
        if alpha < 0.75:
            print(f"  Interpretation: alpha={alpha:.3f} in [0.5, 0.75) => WEAK long-range correlation")
        else:
            print(f"  Interpretation: alpha={alpha:.3f} in [0.75, 1.0) => STRONG long-range correlation")
    elif alpha < 1.5:
        print(f"  Interpretation: alpha={alpha:.3f} in [1.0, 1.5) => NON-STATIONARY, long memory")
    else:
        print(f"  Interpretation: alpha={alpha:.3f} >= 1.5 => Brownian noise or worse")

    # Expected for pure OU: H ≈ 0.5 for increments, DFA alpha ≈ 0.5 for levels at long scales
    print(f"  Pure O-U process would give: H(increments)~0.0, DFA-1(levels)~0.5 at long scales")

    return H_rs, dfa_results

for data, label in [(d0, "Day 0"), (d1, "Day -1"), (d2, "Day -2")]:
    fractal_analysis(data['mid'], data['dmid'], label)

# =============================================================================
# 5. NONLINEAR DYNAMICS
# =============================================================================
print("\n" + "=" * 80)
print("5. NONLINEAR DYNAMICS")
print("=" * 80)

def largest_lyapunov(series, m=5, tau=1, dt=1, n_neighbors=5, max_iter=50):
    """
    Estimate largest Lyapunov exponent using Rosenstein's method.
    m: embedding dimension
    tau: time delay
    """
    N = len(series)
    M = N - (m-1)*tau

    if M < max_iter + 10:
        return np.nan, []

    # Construct delay embedding
    embedded = np.zeros((M, m))
    for i in range(m):
        embedded[:, i] = series[i*tau:i*tau + M]

    # For each point, find nearest neighbor (excluding temporal neighbors)
    min_temporal_sep = m * tau + 1
    divergences = np.zeros(max_iter)
    counts = np.zeros(max_iter)

    for i in range(M - max_iter):
        # Find nearest neighbor
        dists = np.sqrt(np.sum((embedded - embedded[i])**2, axis=1))
        dists[max(0, i-min_temporal_sep):min(M, i+min_temporal_sep+1)] = np.inf

        j = np.argmin(dists)
        if dists[j] == np.inf or dists[j] < 1e-10:
            continue

        # Track divergence
        for k in range(max_iter):
            if i+k < M and j+k < M:
                d = np.sqrt(np.sum((embedded[i+k] - embedded[j+k])**2))
                if d > 1e-10:
                    divergences[k] += np.log(d)
                    counts[k] += 1

    # Average divergences
    valid = counts > 0
    avg_div = np.zeros(max_iter)
    avg_div[valid] = divergences[valid] / counts[valid]

    # Fit slope to initial linear region
    valid_idx = np.where(valid)[0]
    if len(valid_idx) > 5:
        fit_range = valid_idx[:min(20, len(valid_idx))]
        slope, _, r, _, _ = stats.linregress(fit_range * dt, avg_div[fit_range])
        return slope, avg_div

    return np.nan, avg_div

def takens_embedding_dimension(series, max_dim=10, tau=1, r_factor=0.1):
    """
    False nearest neighbors method for optimal embedding dimension.
    """
    r_threshold = r_factor * np.std(series)
    results = []

    for m in range(1, max_dim + 1):
        N = len(series) - m * tau
        if N < 50:
            break

        # Embedding
        embedded = np.zeros((N, m))
        for i in range(m):
            embedded[:, i] = series[i*tau:i*tau + N]

        # For subsample, check false nearest neighbors
        n_check = min(500, N)
        indices = np.random.choice(N, n_check, replace=False)

        n_false = 0
        n_total = 0

        for idx in indices:
            dists = np.sqrt(np.sum((embedded - embedded[idx])**2, axis=1))
            dists[idx] = np.inf
            nn_idx = np.argmin(dists)

            if dists[nn_idx] < 1e-10:
                continue

            n_total += 1

            # Check if neighbor is still close in m+1 dimensions
            if idx + m*tau < len(series) and nn_idx + m*tau < len(series):
                extra_dist = abs(series[idx + m*tau] - series[nn_idx + m*tau])
                if extra_dist / dists[nn_idx] > 10:  # Kennel's criterion
                    n_false += 1

        fnn_ratio = n_false / max(n_total, 1)
        results.append((m, fnn_ratio))

    return results

def nonlinear_analysis(mid, dmid, label):
    """Full nonlinear dynamics analysis."""
    print(f"\n--- {label} ---")

    np.random.seed(42)

    # Largest Lyapunov exponent
    lam, divs = largest_lyapunov(dmid[:2000], m=5, tau=1)
    print(f"  Largest Lyapunov exponent: {lam:.6f}")
    if lam > 0.01:
        print(f"    ==> POSITIVE: suggests chaotic dynamics")
    elif lam < -0.01:
        print(f"    ==> NEGATIVE: converging dynamics (stable)")
    else:
        print(f"    ==> NEAR ZERO: neither clearly chaotic nor stable")

    # Embedding dimension (FNN)
    fnn = takens_embedding_dimension(dmid[:2000], max_dim=8, tau=1)
    print(f"  False Nearest Neighbors analysis:")
    for m, ratio in fnn:
        marker = " <-- embedding dim" if ratio < 0.05 and (m == 1 or fnn[m-2][1] >= 0.05) else ""
        print(f"    dim={m}: FNN ratio={ratio:.4f}{marker}")

    # Determinism test: compare to shuffled surrogate
    def correlation_dimension(series, m, tau=1, r_values=None):
        """Grassberger-Procaccia correlation dimension."""
        N = len(series) - (m-1)*tau
        if N < 100:
            return np.nan

        embedded = np.zeros((N, m))
        for i in range(m):
            embedded[:, i] = series[i*tau:i*tau + N]

        # Subsample for speed
        n_sample = min(500, N)
        idx = np.random.choice(N, n_sample, replace=False)
        sub = embedded[idx]

        # Compute pairwise distances
        dists = []
        for i in range(n_sample):
            for j in range(i+1, n_sample):
                dists.append(np.sqrt(np.sum((sub[i] - sub[j])**2)))
        dists = np.array(dists)

        if r_values is None:
            r_values = np.logspace(np.log10(np.percentile(dists, 1)),
                                   np.log10(np.percentile(dists, 90)), 20)

        C_r = np.array([np.mean(dists < r) for r in r_values])

        valid = C_r > 0
        if np.sum(valid) > 3:
            log_r = np.log(r_values[valid])
            log_C = np.log(C_r[valid])
            # Use middle portion for slope
            n = len(log_r)
            mid_start = n // 4
            mid_end = 3 * n // 4
            if mid_end - mid_start > 2:
                slope, _, _, _, _ = stats.linregress(log_r[mid_start:mid_end], log_C[mid_start:mid_end])
                return slope
        return np.nan

    print(f"\n  Correlation dimension (Grassberger-Procaccia):")
    subseries = dmid[:1000]
    for m in [2, 3, 4, 5, 6]:
        d = correlation_dimension(subseries, m)
        print(f"    m={m}: D2={d:.3f}")

    # Surrogate comparison
    print(f"\n  Surrogate comparison (shuffled vs original):")
    shuffled = dmid.copy()
    np.random.shuffle(shuffled)

    lam_orig, _ = largest_lyapunov(dmid[:1000], m=3, tau=1, max_iter=30)
    lam_shuf, _ = largest_lyapunov(shuffled[:1000], m=3, tau=1, max_iter=30)
    print(f"    Lyapunov (original): {lam_orig:.6f}")
    print(f"    Lyapunov (shuffled): {lam_shuf:.6f}")
    if abs(lam_orig - lam_shuf) < 0.01:
        print(f"    ==> NO significant difference — dynamics likely STOCHASTIC, not chaotic")
    else:
        print(f"    ==> Significant difference — nonlinear deterministic structure MAY exist")

for data, label in [(d0, "Day 0"), (d1, "Day -1"), (d2, "Day -2")]:
    nonlinear_analysis(data['mid'], data['dmid'], label)

# =============================================================================
# 6. COPULA / TAIL ANALYSIS
# =============================================================================
print("\n" + "=" * 80)
print("6. COPULA / TAIL DEPENDENCE ANALYSIS")
print("=" * 80)

def tail_analysis(dmid, label):
    """Analyze tail dependence in consecutive price changes."""
    print(f"\n--- {label} ---")

    x = dmid[:-1]
    y = dmid[1:]

    # Overall statistics
    print(f"  Overall: corr(dmid[t], dmid[t+1]) = {np.corrcoef(x, y)[0,1]:.4f}")

    # Tail analysis
    for pct_label, pct in [("top 5%", 95), ("top 10%", 90), ("bottom 5%", 5), ("bottom 10%", 10)]:
        if pct > 50:
            threshold = np.percentile(x, pct)
            mask = x >= threshold
        else:
            threshold = np.percentile(x, pct)
            mask = x <= threshold

        if mask.sum() > 5:
            y_given = y[mask]
            print(f"\n  {pct_label} of dmid[t] (threshold={threshold:.1f}, n={mask.sum()}):")
            print(f"    E[dmid[t+1]]: {np.mean(y_given):+.4f} (vs unconditional {np.mean(y):+.4f})")
            print(f"    Std[dmid[t+1]]: {np.std(y_given):.4f} (vs unconditional {np.std(y):.4f})")
            print(f"    Median[dmid[t+1]]: {np.median(y_given):+.4f}")

            # Distribution of next move
            vals, counts = np.unique(y_given, return_counts=True)
            probs = counts / len(y_given)
            top3 = np.argsort(probs)[::-1][:5]
            print(f"    Top outcomes: ", end="")
            for idx in top3:
                print(f"{vals[idx]:+.1f}({probs[idx]:.2f}) ", end="")
            print()

    # Asymmetry test
    # After big up: does down probability > up probability?
    threshold_up = np.percentile(x, 90)
    threshold_dn = np.percentile(x, 10)

    after_big_up = y[x >= threshold_up]
    after_big_dn = y[x <= threshold_dn]

    p_reversal_after_up = np.mean(after_big_up < 0)
    p_reversal_after_dn = np.mean(after_big_dn > 0)

    print(f"\n  Reversal probabilities:")
    print(f"    P(down | big up): {p_reversal_after_up:.4f}")
    print(f"    P(up | big down): {p_reversal_after_dn:.4f}")
    print(f"    Asymmetry: {abs(p_reversal_after_up - p_reversal_after_dn):.4f}")

    # Rank correlation (Kendall tau) — captures nonlinear dependence
    # Use subsample for speed
    n_sub = min(2000, len(x))
    tau_corr, tau_p = stats.kendalltau(x[:n_sub], y[:n_sub])
    spearman_corr, spearman_p = stats.spearmanr(x[:n_sub], y[:n_sub])
    pearson_corr = np.corrcoef(x[:n_sub], y[:n_sub])[0,1]

    print(f"\n  Dependence measures:")
    print(f"    Pearson: {pearson_corr:.4f}")
    print(f"    Spearman: {spearman_corr:.4f}")
    print(f"    Kendall tau: {tau_corr:.4f}")
    print(f"    If Spearman >> Pearson: nonlinear monotonic dependence exists")
    print(f"    If Kendall != Pearson: tail dependence structure differs from center")

    # Exceedance correlation: correlation in tails only
    for q in [0.1, 0.25]:
        upper = (x >= np.percentile(x, 100*(1-q))) & (y >= np.percentile(y, 100*(1-q)))
        lower = (x <= np.percentile(x, 100*q)) & (y <= np.percentile(y, 100*q))

        # Chi statistic (tail dependence coefficient)
        chi_upper = np.mean(upper) / q
        chi_lower = np.mean(lower) / q

        print(f"    Chi (q={q}): upper={chi_upper:.4f}, lower={chi_lower:.4f}")
        if chi_upper > 1.5 * q or chi_lower > 1.5 * q:
            print(f"      ==> TAIL DEPENDENCE detected!")

for data, label in [(d0, "Day 0"), (d1, "Day -1"), (d2, "Day -2")]:
    tail_analysis(data['dmid'], label)

# =============================================================================
# 7. SEQUENCE PATTERNS (Renaissance-style)
# =============================================================================
print("\n" + "=" * 80)
print("7. SEQUENCE PATTERN ANALYSIS (Renaissance-style)")
print("=" * 80)

def sequence_analysis(dmid, label, min_count=10):
    """Find predictive multi-tick patterns."""
    print(f"\n--- {label} ---")

    # Categorize dmid into symbols
    # Since dmid is in 0.5 increments, use the actual values
    dmid_rounded = np.round(dmid * 2) / 2  # ensure clean 0.5 increments

    # 2-tick patterns -> predict next
    print(f"\n  2-tick patterns predicting dmid[t+2]:")
    patterns_2 = {}
    for i in range(len(dmid_rounded) - 2):
        key = (dmid_rounded[i], dmid_rounded[i+1])
        if key not in patterns_2:
            patterns_2[key] = []
        patterns_2[key].append(dmid_rounded[i+2])

    # Find most predictive patterns
    results_2 = []
    for key, nexts in patterns_2.items():
        if len(nexts) >= min_count:
            mean_next = np.mean(nexts)
            std_next = np.std(nexts)
            n = len(nexts)
            # T-test vs zero
            t_stat = mean_next / (std_next / np.sqrt(n)) if std_next > 0 else 0
            p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n-1))
            results_2.append((key, mean_next, std_next, n, t_stat, p_val))

    results_2.sort(key=lambda x: abs(x[4]), reverse=True)
    print(f"  Total 2-tick patterns with n>={min_count}: {len(results_2)}")
    print(f"  Top 15 by |t-stat|:")
    for key, mean_n, std_n, n, t, p in results_2[:15]:
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        print(f"    [{key[0]:+.1f}, {key[1]:+.1f}] -> E[next]={mean_n:+.4f}, "
              f"std={std_n:.3f}, n={n}, t={t:+.3f}, p={p:.4f} {sig}")

    # 3-tick patterns -> predict next
    print(f"\n  3-tick patterns predicting dmid[t+3]:")
    patterns_3 = {}
    for i in range(len(dmid_rounded) - 3):
        key = (dmid_rounded[i], dmid_rounded[i+1], dmid_rounded[i+2])
        if key not in patterns_3:
            patterns_3[key] = []
        patterns_3[key].append(dmid_rounded[i+3])

    results_3 = []
    for key, nexts in patterns_3.items():
        if len(nexts) >= max(min_count // 2, 5):
            mean_next = np.mean(nexts)
            std_next = np.std(nexts)
            n = len(nexts)
            t_stat = mean_next / (std_next / np.sqrt(n)) if std_next > 0 else 0
            p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n-1))
            results_3.append((key, mean_next, std_next, n, t_stat, p_val))

    results_3.sort(key=lambda x: abs(x[4]), reverse=True)
    print(f"  Total 3-tick patterns with n>={max(min_count//2, 5)}: {len(results_3)}")
    print(f"  Top 15 by |t-stat|:")
    for key, mean_n, std_n, n, t, p in results_3[:15]:
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        print(f"    [{key[0]:+.1f}, {key[1]:+.1f}, {key[2]:+.1f}] -> E[next]={mean_n:+.4f}, "
              f"std={std_n:.3f}, n={n}, t={t:+.3f}, p={p:.4f} {sig}")

    # Beyond lag-1: does the pattern add info beyond what lag-1 AC gives?
    print(f"\n  INCREMENTAL predictive power beyond lag-1:")
    # Lag-1 AC predicts E[dmid[t+1]] ≈ rho * dmid[t]
    rho = np.corrcoef(dmid[:-1], dmid[1:])[0,1]

    for key, mean_n, std_n, n, t, p in results_2[:10]:
        if n >= min_count and p < 0.05:
            # What lag-1 alone predicts
            lag1_pred = rho * key[1]  # just from the most recent change
            residual = mean_n - lag1_pred
            resid_t = residual / (std_n / np.sqrt(n)) if std_n > 0 else 0
            resid_p = 2 * (1 - stats.t.cdf(abs(resid_t), n-1))
            if resid_p < 0.1:
                print(f"    [{key[0]:+.1f}, {key[1]:+.1f}]: lag1_pred={lag1_pred:+.4f}, "
                      f"actual={mean_n:+.4f}, residual={residual:+.4f}, "
                      f"resid_t={resid_t:+.3f}, p={resid_p:.4f}")

    # Sign patterns
    print(f"\n  Sign-based patterns (more robust):")
    signs = np.sign(dmid_rounded)
    signs[signs == 0] = 0  # keep zeros separate

    sign_patterns = {}
    for i in range(len(signs) - 3):
        key = (int(signs[i]), int(signs[i+1]), int(signs[i+2]))
        if key not in sign_patterns:
            sign_patterns[key] = []
        sign_patterns[key].append(dmid_rounded[i+3])

    for key, nexts in sorted(sign_patterns.items()):
        if len(nexts) >= 5:
            mean_n = np.mean(nexts)
            std_n = np.std(nexts)
            n = len(nexts)
            t_stat = mean_n / (std_n / np.sqrt(n)) if std_n > 0 else 0
            p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n-1))
            sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
            print(f"    signs={key}: E[next]={mean_n:+.4f}, n={n}, t={t_stat:+.3f} {sig}")

    return results_2, results_3

# Run on all days, then check cross-day stability
r2_d0, r3_d0 = sequence_analysis(d0['dmid'], "Day 0", min_count=5)
r2_d1, r3_d1 = sequence_analysis(d1['dmid'], "Day -1", min_count=20)
r2_d2, r3_d2 = sequence_analysis(d2['dmid'], "Day -2", min_count=20)

# Cross-day validation of top patterns
print(f"\n--- Cross-Day Pattern Stability ---")
print("Checking if Day -1 top patterns also predict on Day -2:")
for key, mean_n, std_n, n, t, p in r2_d1[:10]:
    # Look up same pattern in day -2
    for key2, mean_n2, std_n2, n2, t2, p2 in r2_d2:
        if key == key2:
            same_sign = np.sign(mean_n) == np.sign(mean_n2)
            print(f"  [{key[0]:+.1f}, {key[1]:+.1f}]: D-1={mean_n:+.4f}(t={t:+.2f}), "
                  f"D-2={mean_n2:+.4f}(t={t2:+.2f}), same_sign={same_sign}")
            break

print()
print("=" * 80)
print("SECTIONS 1-7 COMPLETE. Continuing with 8-9...")
print("=" * 80)
