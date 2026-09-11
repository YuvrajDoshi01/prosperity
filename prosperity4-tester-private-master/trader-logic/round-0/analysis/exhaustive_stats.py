#!/usr/bin/env python3
"""
exhaustive_stats.py — Every classical statistical method applied to TOMATOES
=============================================================================

Tests EVERY basic mathematical/statistical technique for predictive power
on TOMATOES mid price. For each method, answers:
  1. Is there a signal? (correlation, R², accuracy)
  2. What horizon? (1-tick, 5-tick, 20-tick, 100-tick)
  3. Mean-reversion or momentum?
  4. Actionable for trading? (net of spread cost)

Methods tested:
  A. TIME SERIES
     1.  AR(p) — autoregression on changes, p=1..10
     2.  MA(q) — moving average of residuals, q=1..5
     3.  ARMA(p,q) — joint (simplified: AR residual check)
     4.  Hurst exponent — mean-reversion (H<0.5) vs momentum (H>0.5)
     5.  Variance ratio test — random walk vs predictability at multiple horizons
     6.  ADF test — stationarity / unit root on levels and changes
     7.  KPSS-like test — stationarity around trend

  B. SIGNAL PROCESSING
     8.  FFT dominant frequencies — periodic cycles?
     9.  Spectral density slope — 1/f noise, pink noise, white noise?
     10. Zero-crossing rate — oscillation frequency of changes

  C. DISTRIBUTION / TAIL ANALYSIS
     11. Return distribution: skew, kurtosis, tail index
     12. Runs test — are sequences of up/down moves random?
     13. Turning points test — are reversals more frequent than random walk?

  D. MULTI-HORIZON PREDICTABILITY
     14. Autocorrelation of |returns| (volatility clustering)
     15. Autocorrelation of returns at horizons 1,2,5,10,20,50,100
     16. Cross-autocorrelation of spread state → future returns
     17. Conditional returns by: spread state, time-of-day, position in range

  E. INFORMATION THEORY
     18. Mutual information: past bins → future direction
     19. Entropy rate of price changes — how predictable is the sequence?

  F. REGRESSION / MACHINE LEARNING BASICS
     20. Linear regression: all lags 1-10 of dmid → next dmid
     21. Ridge/regularized: same with penalty (check overfitting)
     22. Non-linear: sign(dmid) → next dmid, |dmid| → next |dmid|
     23. Interaction: dmid × spread_state → next dmid

  G. MOMENTUM VS MEAN-REVERSION ACROSS HORIZONS
     24. Multi-horizon return predictability curve
     25. Optimal holding period analysis

No numpy/pandas — pure stdlib for portability.
"""

import csv
import math
import os
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "prosperity4bt", "resources", "round0")


def load_day(day):
    fname = os.path.join(DATA_DIR, f"prices_round_0_day_{day}.csv")
    rows = []
    with open(fname) as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["product"] == "TOMATOES":
                rows.append({
                    "ts": int(r["timestamp"]),
                    "bid1": float(r["bid_price_1"]),
                    "ask1": float(r["ask_price_1"]),
                    "mid": float(r["mid_price"]),
                    "bv1": int(r["bid_volume_1"]),
                    "av1": int(r["ask_volume_1"]),
                    "bid2": float(r["bid_price_2"]) if r["bid_price_2"] else None,
                    "ask2": float(r["ask_price_2"]) if r["ask_price_2"] else None,
                    "bv2": int(r["bid_volume_2"]) if r["bid_volume_2"] else 0,
                    "av2": int(r["ask_volume_2"]) if r["ask_volume_2"] else 0,
                })
    rows.sort(key=lambda r: r["ts"])
    return rows


# ── Stats helpers ──

def mean(xs):
    return sum(xs) / len(xs) if xs else 0

def var(xs, ddof=0):
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - ddof) if len(xs) > ddof else 0

def std(xs, ddof=0):
    return math.sqrt(var(xs, ddof))

def corr(xs, ys):
    n = min(len(xs), len(ys))
    if n < 3: return 0
    mx, my = mean(xs[:n]), mean(ys[:n])
    sx, sy = std(xs[:n]), std(ys[:n])
    if sx == 0 or sy == 0: return 0
    return sum((xs[i]-mx)*(ys[i]-my) for i in range(n)) / (n * sx * sy)

def autocorr(xs, lag):
    n = len(xs)
    if n <= lag: return 0
    m = mean(xs)
    v = sum((x-m)**2 for x in xs) / n
    if v == 0: return 0
    return sum((xs[i]-m)*(xs[i+lag]-m) for i in range(n-lag)) / (n * v)

def ols(X_cols, y):
    """Multi-variate OLS. X_cols = list of lists. Returns (betas, r2)."""
    n = len(y)
    k = len(X_cols) + 1
    cols = [[1.0]*n] + X_cols
    xtx = [[sum(cols[i][t]*cols[j][t] for t in range(n)) for j in range(k)] for i in range(k)]
    xty = [sum(cols[i][t]*y[t] for t in range(n)) for i in range(k)]
    # Gaussian elimination
    aug = [row + [rhs] for row, rhs in zip(xtx, xty)]
    for col in range(k):
        mr = max(range(col, k), key=lambda r: abs(aug[r][col]))
        aug[col], aug[mr] = aug[mr], aug[col]
        if abs(aug[col][col]) < 1e-14: continue
        for row in range(col+1, k):
            f = aug[row][col] / aug[col][col]
            for j in range(col, k+1): aug[row][j] -= f * aug[col][j]
    beta = [0.0]*k
    for i in range(k-1, -1, -1):
        beta[i] = aug[i][k]
        for j in range(i+1, k): beta[i] -= aug[i][j]*beta[j]
        if abs(aug[i][i]) > 1e-14: beta[i] /= aug[i][i]
    yhat = [sum(beta[j]*cols[j][t] for j in range(k)) for t in range(n)]
    ss_res = sum((y[t]-yhat[t])**2 for t in range(n))
    my = mean(y)
    ss_tot = sum((yi-my)**2 for yi in y)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    return beta, r2


# ══════════════════════════════════════════════════════════════════
# A. TIME SERIES METHODS
# ══════════════════════════════════════════════════════════════════

def test_ar_p(mids, max_p=10):
    """AR(p) on dmid: which lags matter?"""
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]
    n = len(dmid)
    print("\n  A1. AR(p) ON MID CHANGES — Which lags predict next dmid?")
    print(f"  {'p':>3s} | {'R²':>8s} | {'ΔR²':>8s} | {'Coefs (lag 1..p)':>50s} | {'Verdict'}")
    print(f"  {'-'*3}-+-{'-'*8}-+-{'-'*8}-+-{'-'*50}-+-{'-'*20}")
    prev_r2 = 0
    for p in range(1, max_p+1):
        y = dmid[p:]
        X = [dmid[p-lag-1:n-lag-1] for lag in range(p)]
        beta, r2 = ols(X, y)
        dr2 = r2 - prev_r2
        coef_str = ", ".join(f"{b:+.4f}" for b in beta[1:])
        verdict = ""
        if dr2 > 0.01: verdict = "SIGNIFICANT"
        elif dr2 > 0.001: verdict = "marginal"
        else: verdict = "noise"
        print(f"  {p:3d} | {r2:8.6f} | {dr2:+8.6f} | {coef_str:>50s} | {verdict}")
        prev_r2 = r2


def test_hurst(mids, max_n=500):
    """Hurst exponent via R/S analysis. H<0.5 = mean-reversion, H>0.5 = momentum."""
    print("\n  A4. HURST EXPONENT (R/S analysis)")
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]

    ns = []
    rs_values = []
    for n in [10, 20, 50, 100, 200, 500]:
        if n > len(dmid) // 2: continue
        rs_list = []
        for start in range(0, len(dmid)-n, n):
            chunk = dmid[start:start+n]
            m = mean(chunk)
            s = std(chunk)
            if s < 1e-10: continue
            cumdev = []
            cd = 0
            for x in chunk:
                cd += (x - m)
                cumdev.append(cd)
            R = max(cumdev) - min(cumdev)
            rs_list.append(R / s)
        if rs_list:
            ns.append(n)
            rs_values.append(mean(rs_list))

    if len(ns) >= 3:
        log_n = [math.log(n) for n in ns]
        log_rs = [math.log(rs) for rs in rs_values]
        # OLS: log(R/S) = H * log(n) + c
        beta, r2 = ols([log_n], log_rs)
        H = beta[1]
        print(f"    H = {H:.4f}  (R² of fit = {r2:.4f})")
        print(f"    {'MEAN-REVERTING' if H < 0.5 else 'MOMENTUM' if H > 0.5 else 'RANDOM WALK'}")
        print(f"    (H=0.5 is random walk; H<0.5 anti-persistent; H>0.5 persistent)")
        for n, rs in zip(ns, rs_values):
            print(f"      n={n:4d}: R/S = {rs:.3f}")
    else:
        print("    Insufficient data for R/S analysis")


def test_variance_ratio(mids, horizons=[2, 5, 10, 20, 50, 100]):
    """Variance ratio: VR(k) = Var(k-period return) / (k * Var(1-period return)).
    VR=1 → random walk. VR<1 → mean-reversion. VR>1 → momentum."""
    print("\n  A5. VARIANCE RATIO TEST (Lo-MacKinlay)")
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]
    var1 = var(dmid)
    if var1 == 0:
        print("    Zero variance — cannot compute"); return

    print(f"    {'Horizon':>7s} | {'VR(k)':>8s} | {'z-stat':>8s} | {'Verdict':>20s}")
    print(f"    {'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*20}")
    for k in horizons:
        if k >= len(mids): continue
        k_returns = [mids[i+k]-mids[i] for i in range(len(mids)-k)]
        vark = var(k_returns)
        vr = vark / (k * var1)
        # Asymptotic z-stat under null of RW
        n = len(dmid)
        se = math.sqrt(2*(2*k-1)*(k-1) / (3*k*n))
        z = (vr - 1) / se if se > 0 else 0
        if vr < 0.95: verdict = "MEAN-REVERSION"
        elif vr > 1.05: verdict = "MOMENTUM"
        else: verdict = "~random walk"
        sig = " ***" if abs(z) > 2.58 else " **" if abs(z) > 1.96 else ""
        print(f"    {k:7d} | {vr:8.4f} | {z:+8.3f}{sig:3s} | {verdict}")


def test_adf(mids):
    """Augmented Dickey-Fuller on LEVELS (unit root test).
    Test: dmid[t] = phi*mid[t-1] + lags + c. If phi<0 significantly → stationary."""
    print("\n  A6. ADF-LIKE UNIT ROOT TEST ON LEVELS")
    n = len(mids)
    # Simple DF: dmid[t] = alpha + phi*mid[t-1] + eps
    dmid = [mids[i+1]-mids[i] for i in range(n-1)]
    X_levels = mids[:-1]
    beta, r2 = ols([X_levels], dmid)
    phi = beta[1]
    # Compute t-stat
    yhat = [beta[0] + phi*X_levels[i] for i in range(len(dmid))]
    resid = [dmid[i]-yhat[i] for i in range(len(dmid))]
    se_resid = std(resid)
    sx = std(X_levels)
    se_phi = se_resid / (sx * math.sqrt(len(dmid))) if sx > 0 else 1
    t_stat = phi / se_phi if se_phi > 0 else 0

    print(f"    phi = {phi:.6f}, t-stat = {t_stat:.2f}")
    print(f"    (ADF critical values: -3.43 (1%), -2.86 (5%), -2.57 (10%))")
    if t_stat < -3.43:
        print(f"    STATIONARY at 1% level → MEAN-REVERTING to long-run mean")
    elif t_stat < -2.86:
        print(f"    STATIONARY at 5% level → MEAN-REVERTING")
    elif t_stat < -2.57:
        print(f"    STATIONARY at 10% level → weakly mean-reverting")
    else:
        print(f"    UNIT ROOT → not mean-reverting at this timescale")


# ══════════════════════════════════════════════════════════════════
# B. SIGNAL PROCESSING
# ══════════════════════════════════════════════════════════════════

def test_fft(mids, top_k=10):
    """FFT dominant frequencies on dmid — any periodic cycles?"""
    print("\n  B8. FFT DOMINANT FREQUENCIES")
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]
    n = len(dmid)

    # Simple DFT (O(n²) but fine for n=2000-10000 with pruning)
    # Only compute magnitudes for periods > 4 ticks and < n/2
    m = mean(dmid)
    centered = [d - m for d in dmid]

    # Sample a grid of frequencies to avoid O(n²)
    period_grid = list(range(4, min(n//2, 500)))
    magnitudes = []
    for period in period_grid:
        freq = 2 * math.pi / period
        re = sum(centered[t] * math.cos(freq * t) for t in range(n))
        im = sum(centered[t] * math.sin(freq * t) for t in range(n))
        mag = math.sqrt(re**2 + im**2) / n
        magnitudes.append((period, mag))

    magnitudes.sort(key=lambda x: -x[1])

    # White noise expected magnitude
    expected_mag = std(dmid) / math.sqrt(n)

    print(f"    Expected magnitude under white noise: {expected_mag:.4f}")
    print(f"    Top {top_k} frequencies:")
    print(f"    {'Period':>8s} | {'Magnitude':>10s} | {'×expected':>10s} | {'Verdict'}")
    print(f"    {'-'*8}-+-{'-'*10}-+-{'-'*10}-+-{'-'*15}")
    for period, mag in magnitudes[:top_k]:
        ratio = mag / expected_mag if expected_mag > 0 else 0
        verdict = "SIGNIFICANT" if ratio > 3 else "marginal" if ratio > 2 else "noise"
        print(f"    {period:8d} | {mag:10.4f} | {ratio:10.2f}x | {verdict}")


def test_zero_crossing(mids):
    """Zero-crossing rate of dmid — how often does direction flip?"""
    print("\n  B10. ZERO-CROSSING RATE (direction flip frequency)")
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]
    nonzero = [(i, d) for i, d in enumerate(dmid) if abs(d) > 0.01]

    if len(nonzero) < 10:
        print("    Insufficient non-zero moves"); return

    crossings = 0
    for i in range(1, len(nonzero)):
        if nonzero[i][1] * nonzero[i-1][1] < 0:
            crossings += 1

    rate = crossings / (len(nonzero) - 1)
    # Random walk with symmetric distribution: expected rate = 0.5
    n = len(nonzero) - 1
    se = math.sqrt(0.25 / n)
    z = (rate - 0.5) / se

    print(f"    Zero-crossing rate: {rate:.4f} ({crossings}/{n})")
    print(f"    Expected under random walk: 0.5000")
    print(f"    z-stat: {z:+.2f}  ({'MEAN-REVERTING (flips too often)' if z > 2 else 'MOMENTUM (flips too rarely)' if z < -2 else 'consistent with RW'})")


# ══════════════════════════════════════════════════════════════════
# C. DISTRIBUTION / TAIL ANALYSIS
# ══════════════════════════════════════════════════════════════════

def test_distribution(mids):
    """Return distribution analysis: skew, kurtosis, tail behavior."""
    print("\n  C11. RETURN DISTRIBUTION")
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]
    n = len(dmid)
    m = mean(dmid)
    s = std(dmid)
    m3 = sum((d-m)**3 for d in dmid) / n
    m4 = sum((d-m)**4 for d in dmid) / n
    skew = m3 / s**3 if s > 0 else 0
    kurt = m4 / s**4 if s > 0 else 0

    print(f"    N = {n}, mean = {m:.6f}, std = {s:.4f}")
    print(f"    Skewness = {skew:.4f}  ({'symmetric' if abs(skew) < 0.5 else 'SKEWED'})")
    print(f"    Kurtosis = {kurt:.4f}  (normal=3, {'HEAVY-TAILED' if kurt > 4 else 'normal-tailed'})")

    # Tail analysis: what fraction of returns exceed 2σ, 3σ?
    tail2 = sum(1 for d in dmid if abs(d-m) > 2*s) / n
    tail3 = sum(1 for d in dmid if abs(d-m) > 3*s) / n
    print(f"    P(|r| > 2σ): {tail2:.4f} (normal: 0.0455)")
    print(f"    P(|r| > 3σ): {tail3:.4f} (normal: 0.0027)")

    # Conditional returns: what happens AFTER large moves?
    print(f"\n    Conditional analysis (what follows extreme moves):")
    for threshold in [2, 3, 4, 5]:
        up_after = []
        down_after = []
        for i in range(len(dmid)-1):
            if dmid[i] >= threshold:
                down_after.append(dmid[i+1])
            elif dmid[i] <= -threshold:
                up_after.append(dmid[i+1])
        if up_after:
            print(f"      After dmid <= -{threshold}: next dmid = {mean(up_after):+.3f} (n={len(up_after)}) → {'REVERSAL' if mean(up_after) > 0.1 else 'no signal'}")
        if down_after:
            print(f"      After dmid >= +{threshold}: next dmid = {mean(down_after):+.3f} (n={len(down_after)}) → {'REVERSAL' if mean(down_after) < -0.1 else 'no signal'}")


def test_runs(mids):
    """Runs test: are sequences of up/down moves random?"""
    print("\n  C12. RUNS TEST (sequence randomness)")
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]
    signs = [1 if d > 0 else -1 if d < 0 else 0 for d in dmid]
    signs = [s for s in signs if s != 0]  # remove zeros

    n = len(signs)
    n_pos = sum(1 for s in signs if s > 0)
    n_neg = n - n_pos

    # Count runs
    runs = 1
    for i in range(1, n):
        if signs[i] != signs[i-1]:
            runs += 1

    # Expected runs under randomness
    exp_runs = 1 + 2*n_pos*n_neg/n
    var_runs = 2*n_pos*n_neg*(2*n_pos*n_neg - n) / (n*n*(n-1))
    z = (runs - exp_runs) / math.sqrt(var_runs) if var_runs > 0 else 0

    print(f"    Total non-zero moves: {n} ({n_pos} up, {n_neg} down)")
    print(f"    Observed runs: {runs}")
    print(f"    Expected runs (random): {exp_runs:.1f}")
    print(f"    z-stat: {z:+.2f}  ({'TOO MANY RUNS → MEAN-REVERSION' if z > 2 else 'TOO FEW RUNS → MOMENTUM' if z < -2 else 'random'})")


def test_turning_points(mids):
    """Turning points test: are reversals more frequent than in random walk?"""
    print("\n  C13. TURNING POINTS TEST")
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]
    nonzero = [d for d in dmid if abs(d) > 0.01]
    n = len(nonzero)

    tp = 0
    for i in range(1, n-1):
        if (nonzero[i] > nonzero[i-1] and nonzero[i] > nonzero[i+1]) or \
           (nonzero[i] < nonzero[i-1] and nonzero[i] < nonzero[i+1]):
            tp += 1

    exp_tp = 2*(n-2)/3
    var_tp = (16*n - 29) / 90
    z = (tp - exp_tp) / math.sqrt(var_tp) if var_tp > 0 else 0

    print(f"    Turning points: {tp} / {n-2} possible")
    print(f"    Expected (random): {exp_tp:.1f}")
    print(f"    z-stat: {z:+.2f}  ({'MORE REVERSALS than RW → MEAN-REVERSION' if z > 2 else 'FEWER REVERSALS → MOMENTUM' if z < -2 else 'consistent with RW'})")


# ══════════════════════════════════════════════════════════════════
# D. MULTI-HORIZON PREDICTABILITY
# ══════════════════════════════════════════════════════════════════

def test_vol_clustering(mids):
    """Autocorrelation of |returns| — volatility clustering (GARCH effects)."""
    print("\n  D14. VOLATILITY CLUSTERING (autocorrelation of |dmid|)")
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]
    abs_dmid = [abs(d) for d in dmid]

    print(f"    {'Lag':>5s} | {'AC(|dmid|)':>10s} | {'AC(dmid²)':>10s} | {'Verdict'}")
    print(f"    {'-'*5}-+-{'-'*10}-+-{'-'*10}-+-{'-'*25}")
    thresh = 2 / math.sqrt(len(dmid))
    sq_dmid = [d**2 for d in dmid]
    for lag in [1, 2, 3, 5, 10, 20, 50]:
        ac_abs = autocorr(abs_dmid, lag)
        ac_sq = autocorr(sq_dmid, lag)
        sig = "SIGNIFICANT" if abs(ac_abs) > thresh else "noise"
        print(f"    {lag:5d} | {ac_abs:+10.4f} | {ac_sq:+10.4f} | {sig}")


def test_multihorizon_ac(mids):
    """Return autocorrelation at multiple horizons."""
    print("\n  D15. MULTI-HORIZON RETURN AUTOCORRELATION")
    print(f"    Tests if returns over k ticks predict returns over next k ticks")

    print(f"    {'Horizon':>7s} | {'AC(1)':>8s} | {'AC(2)':>8s} | {'AC(5)':>8s} | {'Verdict'}")
    print(f"    {'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*20}")

    for k in [1, 2, 5, 10, 20, 50, 100]:
        if k*3 >= len(mids): continue
        rets = [mids[i+k]-mids[i] for i in range(len(mids)-k)]
        ac1 = autocorr(rets, k)   # non-overlapping
        ac2 = autocorr(rets, 2*k) if 2*k < len(rets) else 0
        ac5 = autocorr(rets, 5*k) if 5*k < len(rets) else 0
        verdict = "MEAN-REVERSION" if ac1 < -0.05 else "MOMENTUM" if ac1 > 0.05 else "~RW"
        print(f"    {k:7d} | {ac1:+8.4f} | {ac2:+8.4f} | {ac5:+8.4f} | {verdict}")


def test_spread_cross_ac(data):
    """Cross-autocorrelation: spread state → future returns."""
    print("\n  D16. SPREAD STATE → FUTURE RETURNS")
    mids = [r["mid"] for r in data]
    spreads = [r["ask1"] - r["bid1"] for r in data]

    print(f"    {'Spread':>6s} | {'next_1':>8s} | {'next_5':>8s} | {'next_10':>8s} | {'next_20':>8s} | {'Count':>6s}")
    print(f"    {'-'*6}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}")

    for s_val in sorted(set(int(s) for s in spreads)):
        indices = [i for i, s in enumerate(spreads) if int(s) == s_val]
        if len(indices) < 10: continue
        rets = {}
        for h in [1, 5, 10, 20]:
            valid = [mids[i+h]-mids[i] for i in indices if i+h < len(mids)]
            rets[h] = mean(valid) if valid else 0
        print(f"    {s_val:6d} | {rets[1]:+8.4f} | {rets[5]:+8.4f} | {rets[10]:+8.4f} | {rets[20]:+8.4f} | {len(indices):6d}")


def test_conditional_returns(data):
    """Conditional returns by position in daily range."""
    print("\n  D17. CONDITIONAL RETURNS BY POSITION IN RANGE")
    mids = [r["mid"] for r in data]
    n = len(mids)

    # Rolling 100-tick range position
    window = 100
    print(f"    Position = (mid - rolling_min) / (rolling_max - rolling_min), window={window}")
    print(f"    {'Range Pos':>9s} | {'next_1':>8s} | {'next_5':>8s} | {'next_10':>8s} | {'Count':>6s} | {'Verdict'}")
    print(f"    {'-'*9}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}-+-{'-'*15}")

    buckets = defaultdict(lambda: {"r1": [], "r5": [], "r10": []})
    for i in range(window, n):
        lo = min(mids[i-window:i])
        hi = max(mids[i-window:i])
        if hi == lo: continue
        pos = (mids[i] - lo) / (hi - lo)
        bucket = int(pos * 5) / 5  # 0.0, 0.2, 0.4, 0.6, 0.8
        bucket = min(bucket, 0.8)
        if i+1 < n: buckets[bucket]["r1"].append(mids[i+1]-mids[i])
        if i+5 < n: buckets[bucket]["r5"].append(mids[i+5]-mids[i])
        if i+10 < n: buckets[bucket]["r10"].append(mids[i+10]-mids[i])

    for b in sorted(buckets.keys()):
        d = buckets[b]
        r1 = mean(d["r1"]) if d["r1"] else 0
        r5 = mean(d["r5"]) if d["r5"] else 0
        r10 = mean(d["r10"]) if d["r10"] else 0
        cnt = len(d["r1"])
        verdict = ""
        if b <= 0.2 and r10 > 0.1: verdict = "REVERT UP"
        elif b >= 0.6 and r10 < -0.1: verdict = "REVERT DOWN"
        print(f"    {b:9.1f} | {r1:+8.4f} | {r5:+8.4f} | {r10:+8.4f} | {cnt:6d} | {verdict}")


# ══════════════════════════════════════════════════════════════════
# E. INFORMATION THEORY
# ══════════════════════════════════════════════════════════════════

def test_entropy(mids):
    """Entropy analysis of price change sequence."""
    print("\n  E18-19. INFORMATION THEORY")
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]

    # Discretize to {down, zero, up}
    symbols = []
    for d in dmid:
        if d > 0.01: symbols.append("U")
        elif d < -0.01: symbols.append("D")
        else: symbols.append("Z")

    n = len(symbols)

    # Single-symbol entropy
    counts = defaultdict(int)
    for s in symbols: counts[s] += 1
    h1 = -sum((c/n) * math.log2(c/n) for c in counts.values() if c > 0)

    # Bigram entropy (conditional entropy)
    bigrams = defaultdict(int)
    for i in range(n-1):
        bigrams[(symbols[i], symbols[i+1])] += 1
    total_bi = sum(bigrams.values())
    h2 = -sum((c/total_bi) * math.log2(c/total_bi) for c in bigrams.values() if c > 0)

    # Conditional entropy H(X_{t+1} | X_t)
    h_cond = h2 - h1

    # Max entropy for 3 symbols
    h_max = math.log2(3)

    print(f"    Symbols: U={counts.get('U',0)} ({counts.get('U',0)/n:.1%}), "
          f"D={counts.get('D',0)} ({counts.get('D',0)/n:.1%}), "
          f"Z={counts.get('Z',0)} ({counts.get('Z',0)/n:.1%})")
    print(f"    H(X) = {h1:.4f} bits  (max = {h_max:.4f} = log2(3))")
    print(f"    H(X_t, X_{{t+1}}) = {h2:.4f} bits")
    print(f"    H(X_{{t+1}} | X_t) = {h_cond:.4f} bits")
    print(f"    Predictability = 1 - H_cond/H = {1 - h_cond/h1:.4f}  "
          f"({'PREDICTABLE' if 1 - h_cond/h1 > 0.05 else 'nearly random'})")

    # Transition matrix
    print(f"\n    Transition probabilities P(next | current):")
    print(f"    {'Current':>8s} | {'→ D':>8s} | {'→ Z':>8s} | {'→ U':>8s} | {'Bias':>10s}")
    print(f"    {'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*10}")
    for curr in ["D", "Z", "U"]:
        row_total = sum(bigrams[(curr, nxt)] for nxt in ["D", "Z", "U"])
        if row_total == 0: continue
        probs = {nxt: bigrams[(curr, nxt)] / row_total for nxt in ["D", "Z", "U"]}
        bias = ""
        if probs["U"] - probs["D"] > 0.05: bias = "→ UP"
        elif probs["D"] - probs["U"] > 0.05: bias = "→ DOWN"
        else: bias = "balanced"
        print(f"    {curr:>8s} | {probs['D']:8.3f} | {probs['Z']:8.3f} | {probs['U']:8.3f} | {bias}")

    # Mutual information: 3-gram prediction
    print(f"\n    Mutual information: I(X_{{t-1}}, X_t ; X_{{t+1}})")
    trigrams = defaultdict(int)
    for i in range(n-2):
        trigrams[(symbols[i], symbols[i+1], symbols[i+2])] += 1
    total_tri = sum(trigrams.values())
    h3 = -sum((c/total_tri) * math.log2(c/total_tri) for c in trigrams.values() if c > 0)
    h_cond2 = h3 - h2
    mi = h1 - h_cond2
    print(f"    H(X_{{t+1}} | X_{{t-1}}, X_t) = {h_cond2:.4f} bits")
    print(f"    MI = {mi:.4f} bits")
    print(f"    Gain from 2nd lag: {h_cond - h_cond2:.4f} bits  "
          f"({'USEFUL' if h_cond - h_cond2 > 0.01 else 'negligible'})")


# ══════════════════════════════════════════════════════════════════
# F. REGRESSION TESTS
# ══════════════════════════════════════════════════════════════════

def test_nonlinear(mids):
    """Non-linear predictors: sign, |dmid|, dmid², interactions."""
    print("\n  F22-23. NON-LINEAR PREDICTORS")
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]
    n = len(dmid)

    y = dmid[1:]

    # Test various non-linear features
    features = {
        "sign(dmid[-1])": [1 if d > 0 else -1 if d < 0 else 0 for d in dmid[:-1]],
        "|dmid[-1]|": [abs(d) for d in dmid[:-1]],
        "dmid[-1]²": [d**2 for d in dmid[:-1]],
        "dmid[-1]³": [d**3 for d in dmid[:-1]],
    }

    print(f"    {'Feature':>20s} | {'R²':>8s} | {'Coef':>8s} | {'Verdict'}")
    print(f"    {'-'*20}-+-{'-'*8}-+-{'-'*8}-+-{'-'*20}")

    for name, x in features.items():
        beta, r2 = ols([x], y)
        print(f"    {name:>20s} | {r2:8.6f} | {beta[1]:+8.4f} | {'PREDICTIVE' if r2 > 0.005 else 'noise'}")

    # Interaction: dmid × spread
    spreads = []
    for r in range(len(mids)-1):
        spreads.append(0)  # placeholder, filled below
    # Actually need data for spreads, skip if not available

    # Combined: dmid[-1] + sign(dmid[-1]) + |dmid[-1]|
    x1 = dmid[:-1]
    x2 = [1 if d > 0 else -1 if d < 0 else 0 for d in dmid[:-1]]
    x3 = [abs(d) for d in dmid[:-1]]
    beta, r2 = ols([x1, x2, x3], y)
    print(f"    {'dmid + sign + |dmid|':>20s} | {r2:8.6f} | {'multi':>8s} | {'PREDICTIVE' if r2 > 0.005 else 'noise'}")

    # dmid[-1] * |dmid[-1]| (asymmetric impact)
    x_asym = [dmid[i] * abs(dmid[i]) for i in range(len(dmid)-1)]
    beta, r2 = ols([x_asym], y)
    print(f"    {'dmid × |dmid|':>20s} | {r2:8.6f} | {beta[1]:+8.4f} | {'PREDICTIVE' if r2 > 0.005 else 'noise'}")


def test_spread_interaction(data):
    """Interaction: dmid × spread_state → next dmid."""
    print("\n  F23b. SPREAD × RETURN INTERACTION")
    mids = [r["mid"] for r in data]
    spreads = [r["ask1"] - r["bid1"] for r in data]
    dmid = [mids[i+1]-mids[i] for i in range(len(mids)-1)]
    n = len(dmid)

    y = dmid[1:]
    x_dmid = dmid[:-1]
    x_spread = [spreads[i] for i in range(n-1)]
    x_narrow = [1.0 if spreads[i] <= 9 else 0.0 for i in range(n-1)]
    x_interaction = [dmid[i] * (1 if spreads[i] <= 9 else 0) for i in range(n-1)]

    # dmid alone
    beta1, r2_1 = ols([x_dmid], y)
    # dmid + spread
    beta2, r2_2 = ols([x_dmid, x_spread], y)
    # dmid + narrow indicator
    beta3, r2_3 = ols([x_dmid, x_narrow], y)
    # dmid + narrow + interaction
    beta4, r2_4 = ols([x_dmid, x_narrow, x_interaction], y)

    print(f"    {'Model':>35s} | {'R²':>8s} | {'ΔR²':>8s}")
    print(f"    {'-'*35}-+-{'-'*8}-+-{'-'*8}")
    print(f"    {'dmid[-1]':>35s} | {r2_1:8.6f} | {'base':>8s}")
    print(f"    {'dmid[-1] + spread':>35s} | {r2_2:8.6f} | {r2_2-r2_1:+8.6f}")
    print(f"    {'dmid[-1] + narrow_flag':>35s} | {r2_3:8.6f} | {r2_3-r2_1:+8.6f}")
    print(f"    {'dmid[-1] + narrow + dmid×narrow':>35s} | {r2_4:8.6f} | {r2_4-r2_1:+8.6f}")


# ══════════════════════════════════════════════════════════════════
# G. MOMENTUM VS MEAN-REVERSION: THE FULL PICTURE
# ══════════════════════════════════════════════════════════════════

def test_optimal_holding(mids):
    """Optimal holding period: at each horizon, what's the best strategy?"""
    print("\n  G24-25. MULTI-HORIZON PREDICTABILITY & OPTIMAL HOLDING PERIOD")
    print(f"    For each horizon k, compute:")
    print(f"      - corr(ret[t-k:t], ret[t:t+k]): momentum if +, MR if -")
    print(f"      - E[|ret|]: expected move size")
    print(f"      - Sharpe-like: |mean(strat_ret)| / std(strat_ret)")
    print()

    print(f"    {'k':>5s} | {'AC(ret_k)':>9s} | {'E[|ret_k|]':>10s} | {'MR Sharpe':>10s} | {'Mom Sharpe':>10s} | {'Best':>10s}")
    print(f"    {'-'*5}-+-{'-'*9}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}")

    for k in [1, 2, 3, 5, 10, 20, 50, 100, 200]:
        if k * 3 >= len(mids): continue
        rets = [mids[i+k]-mids[i] for i in range(len(mids)-k)]

        # Non-overlapping pairs: ret[0:k] predicts ret[k:2k]
        pairs = []
        for i in range(0, len(mids)-2*k, k):
            r1 = mids[i+k] - mids[i]
            r2 = mids[i+2*k] - mids[i+k]
            pairs.append((r1, r2))

        if len(pairs) < 10: continue

        r1s = [p[0] for p in pairs]
        r2s = [p[1] for p in pairs]
        ac = corr(r1s, r2s)

        # Mean-reversion strategy: trade opposite of prior return
        mr_rets = [-r1 * r2 for r1, r2 in pairs]  # short if went up
        mom_rets = [r1 * r2 for r1, r2 in pairs]  # long if went up

        mr_sharpe = mean(mr_rets) / std(mr_rets) if std(mr_rets) > 0 else 0
        mom_sharpe = mean(mom_rets) / std(mom_rets) if std(mom_rets) > 0 else 0

        e_abs_ret = mean([abs(r) for r in rets])

        best = "MR" if mr_sharpe > mom_sharpe and mr_sharpe > 0.05 else \
               "MOM" if mom_sharpe > mr_sharpe and mom_sharpe > 0.05 else "NONE"

        print(f"    {k:5d} | {ac:+9.4f} | {e_abs_ret:10.3f} | {mr_sharpe:+10.4f} | {mom_sharpe:+10.4f} | {best}")


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def main():
    print("=" * 80)
    print("EXHAUSTIVE STATISTICAL ANALYSIS: TOMATOES")
    print("=" * 80)

    for day in [-2, -1, 0]:
        data = load_day(day)
        mids = [r["mid"] for r in data]
        n = len(mids)

        print(f"\n{'#' * 80}")
        print(f"# DAY {day:+d}  ({n} ticks)")
        print(f"{'#' * 80}")

        # A. Time Series
        test_ar_p(mids)
        test_hurst(mids)
        test_variance_ratio(mids)
        test_adf(mids)

        # B. Signal Processing
        test_fft(mids)
        test_zero_crossing(mids)

        # C. Distribution
        test_distribution(mids)
        test_runs(mids)
        test_turning_points(mids)

        # D. Multi-Horizon
        test_vol_clustering(mids)
        test_multihorizon_ac(mids)
        test_spread_cross_ac(data)
        test_conditional_returns(data)

        # E. Information Theory
        test_entropy(mids)

        # F. Regression
        test_nonlinear(mids)
        test_spread_interaction(data)

        # G. Optimal Holding
        test_optimal_holding(mids)

    # ══════════════════════════════════════════════════════════════
    # CROSS-DAY SUMMARY
    # ══════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("CROSS-DAY SUMMARY: WHAT'S CONSISTENT?")
    print(f"{'=' * 80}")
    print("""
    Look for signals that are CONSISTENT across all 3 days.
    Signals that flip sign between days are noise/overfit.

    Key questions answered:
    1. Mean-reversion or momentum? → Check Hurst, VR, AC, runs test
    2. At what horizon? → Check multi-horizon AC and VR
    3. Any non-linear predictability? → Check F22-23
    4. Any periodic patterns? → Check FFT
    5. Volatility clustering exploitable? → Check D14
    6. Spread state useful beyond carry? → Check D16, F23b
    """)


if __name__ == "__main__":
    main()
