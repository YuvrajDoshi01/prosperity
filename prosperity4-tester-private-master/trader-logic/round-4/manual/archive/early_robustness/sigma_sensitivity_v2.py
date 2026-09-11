"""Sigma sensitivity analysis for R4 manual portfolio strategies.

Tasks
-----
1. sigma grid evaluation: 50M paths per sigma. True E[score], SD, Sharpe, P>0, CVaR-5%.
2. Find sigma break-even where OPTIMAL_7POS overtakes DROP_60C, to 0.005 precision.
3. Robust optimization under sigma ~ U[2.45, 2.57]: which strategy maxes min E[score]?
4. Implied-vol cross-check: invert each market quote.
5. Vega exposure of each strategy at sigma=2.51.
6. dE[score]/dsigma decomposition by instrument.
7. Convexity in sigma: 2nd derivative sign per strategy.

All MC paths use discrete monitoring (4 obs/day) - same convention as IMC engine.
PnL reported in raw per-path units AND x 3000 = USD per trial.
"""
from __future__ import annotations

import json
import math
import os
import time

import numpy as np
from scipy.stats import norm

T0 = time.time()

# ============================================================
# 0. CONSTANTS, QUOTES, STRATEGIES
# ============================================================
S0 = 50.0
SIGMA_BASE = 2.51
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_2W_DAYS = 10
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W = T_3W_DAYS * STEPS_PER_DAY  # 60
N_2W = T_2W_DAYS * STEPS_PER_DAY  # 40
T_3W = T_3W_DAYS / TRADING_DAYS_YEAR
T_2W = T_2W_DAYS / TRADING_DAYS_YEAR
CONTRACT_MULT = 3000

QUOTES = {
    "AC":          (49.975, 50.025, 200),
    "AC_50_P":     (12.00,  12.05,   50),
    "AC_50_C":     (12.00,  12.05,   50),
    "AC_35_P":     ( 4.33,   4.35,   50),
    "AC_40_P":     ( 6.50,   6.55,   50),
    "AC_45_P":     ( 9.05,   9.10,   50),
    "AC_60_C":     ( 8.80,   8.85,   50),
    "AC_50_P_2":   ( 9.70,   9.75,   50),
    "AC_50_C_2":   ( 9.70,   9.75,   50),
    "AC_50_CO":    (22.20,  22.30,   50),
    "AC_40_BP":    ( 5.00,   5.10,   50),
    "AC_45_KO":    ( 0.15,   0.175, 500),
}
SYMBOLS = list(QUOTES.keys())
N_INST = len(SYMBOLS)
BIDS = np.array([QUOTES[s][0] for s in SYMBOLS])
ASKS = np.array([QUOTES[s][1] for s in SYMBOLS])
CAPS = np.array([QUOTES[s][2] for s in SYMBOLS])


def vec(d):
    v = np.zeros(N_INST, dtype=np.int64)
    for s, q in d.items():
        v[SYMBOLS.index(s)] = q
    return v


# Strategies per spec
OPTIMAL_7POS = vec({
    "AC_50_CO":  -50,
    "AC_45_KO":  +500,
    "AC_40_BP":  -50,
    "AC_50_P_2": +50,
    "AC_50_C_2": +50,
    "AC_50_P":   +50,
    "AC_50_C":   +25,
})

DROP_60C = vec({
    "AC_50_CO":  -50,
    "AC_45_KO":  +500,
    "AC_40_BP":  -50,
    "AC_50_P_2": +50,
    "AC_50_C_2": +50,
})

KO300_HEDGED = vec({
    "AC_50_CO":  -50,
    "AC_45_KO":  +300,
    "AC_40_BP":  -50,
    "AC_50_P_2": +50,
    "AC_50_C_2": +50,
    "AC_50_P":   +50,
    "AC_50_C":   +25,
})

USER_SAFE = vec({
    "AC_50_CO":  -15,
    "AC_40_BP":  -50,
    "AC_45_KO":  +60,
    "AC_50_P":   +17,
    "AC_50_P_2": +15,
    "AC_50_C":   +15,
})

NO_KO_HEDGED = vec({
    "AC_50_CO":  -50,
    "AC_40_BP":  -50,
    "AC_50_P_2": +50,
    "AC_50_C_2": +50,
    "AC_50_P":   +50,
    "AC_50_C":   +25,
})

# Plus a "DROP_60C alias" with extra hedge as referenced in prior brief
GLOBAL_MAX = vec({
    "AC_50_CO":  -50,
    "AC_45_KO":  +500,
    "AC_40_BP":  -50,
    "AC_50_P_2": +50,
    "AC_50_C_2": +50,
    "AC_60_C":   -50,
})

STRATS = {
    "OPTIMAL_7POS": OPTIMAL_7POS,
    "DROP_60C":     DROP_60C,
    "KO300_HEDGED": KO300_HEDGED,
    "USER_SAFE":    USER_SAFE,
    "NO_KO_HEDGED": NO_KO_HEDGED,
    "GLOBAL_MAX":   GLOBAL_MAX,
}


# ============================================================
# 1. BLACK-SCHOLES + GREEKS
# ============================================================
SQRT_2PI = math.sqrt(2.0 * math.pi)


def _d12(S, K, T, sig):
    if T <= 0 or sig <= 0:
        return float("nan"), float("nan")
    sT = sig * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / sT
    d2 = d1 - sT
    return d1, d2


def bs_call(S, K, T, sig):
    if T <= 0 or sig <= 0:
        return max(S - K, 0.0)
    d1, d2 = _d12(S, K, T, sig)
    return S * norm.cdf(d1) - K * norm.cdf(d2)


def bs_put(S, K, T, sig):
    if T <= 0 or sig <= 0:
        return max(K - S, 0.0)
    d1, d2 = _d12(S, K, T, sig)
    return K * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_vega(S, K, T, sig):
    """Vega = dPrice/dsigma for both call and put (same)."""
    if T <= 0 or sig <= 0:
        return 0.0
    d1, _ = _d12(S, K, T, sig)
    return S * math.sqrt(T) * (math.exp(-0.5 * d1 * d1) / SQRT_2PI)


def bs_volga(S, K, T, sig):
    """Volga = d^2Price/dsigma^2 (convexity in vol, both call and put)."""
    if T <= 0 or sig <= 0:
        return 0.0
    d1, d2 = _d12(S, K, T, sig)
    vega = bs_vega(S, K, T, sig)
    return vega * d1 * d2 / sig


# ============================================================
# 2. PATH GENERATOR + PAYOFF MATRIX
# ============================================================
def gen_paths(n_sims: int, seed: int, sig: float, n_steps: int = N_3W, n2w: int = N_2W):
    rng = np.random.default_rng(seed)
    drift = -0.5 * sig * sig * DT
    volstep = sig * math.sqrt(DT)
    Z = rng.standard_normal((n_sims, n_steps))
    Z *= volstep  # in-place
    Z += drift    # in-place broadcast over the (n_sims, n_steps) array
    np.cumsum(Z, axis=1, out=Z)  # log-increments cumulated
    Z += np.log(S0)
    np.exp(Z, out=Z)  # Z now holds S_paths
    out = {
        "S_T":    Z[:, -1].copy(),
        "S_T_2w": Z[:, n2w - 1].copy(),
        "min_S":  Z.min(axis=1),
    }
    del Z
    return out


def payoffs_matrix(paths):
    S_T = paths["S_T"]
    S_T_2w = paths["S_T_2w"]
    min_S = paths["min_S"]
    n = S_T.size
    P = np.empty((n, N_INST), dtype=np.float64)
    for i, s in enumerate(SYMBOLS):
        if s == "AC":         P[:, i] = S_T
        elif s == "AC_50_P":  P[:, i] = np.maximum(50 - S_T, 0)
        elif s == "AC_50_C":  P[:, i] = np.maximum(S_T - 50, 0)
        elif s == "AC_35_P":  P[:, i] = np.maximum(35 - S_T, 0)
        elif s == "AC_40_P":  P[:, i] = np.maximum(40 - S_T, 0)
        elif s == "AC_45_P":  P[:, i] = np.maximum(45 - S_T, 0)
        elif s == "AC_60_C":  P[:, i] = np.maximum(S_T - 60, 0)
        elif s == "AC_50_P_2": P[:, i] = np.maximum(50 - S_T_2w, 0)
        elif s == "AC_50_C_2": P[:, i] = np.maximum(S_T_2w - 50, 0)
        elif s == "AC_50_CO":
            P[:, i] = np.where(S_T_2w >= 50,
                               np.maximum(S_T - 50, 0),
                               np.maximum(50 - S_T, 0))
        elif s == "AC_40_BP": P[:, i] = np.where(S_T < 40, 10.0, 0.0)
        elif s == "AC_45_KO": P[:, i] = np.where(min_S > 35, np.maximum(45 - S_T, 0), 0.0)
    return P


def trade_prices(qvec):
    return np.where(qvec >= 0, ASKS, BIDS)


# ============================================================
# 3. ANALYTICAL FAIR VALUES (KO via MC at given sigma)
# ============================================================
def fair_values(sig: float, ko_paths: int = 800_000, ko_seed: int = 12345) -> np.ndarray:
    fv = np.empty(N_INST)
    fv[SYMBOLS.index("AC")]       = S0
    fv[SYMBOLS.index("AC_50_P")]  = bs_put(S0, 50, T_3W, sig)
    fv[SYMBOLS.index("AC_50_C")]  = bs_call(S0, 50, T_3W, sig)
    fv[SYMBOLS.index("AC_35_P")]  = bs_put(S0, 35, T_3W, sig)
    fv[SYMBOLS.index("AC_40_P")]  = bs_put(S0, 40, T_3W, sig)
    fv[SYMBOLS.index("AC_45_P")]  = bs_put(S0, 45, T_3W, sig)
    fv[SYMBOLS.index("AC_60_C")]  = bs_call(S0, 60, T_3W, sig)
    fv[SYMBOLS.index("AC_50_P_2")] = bs_put(S0, 50, T_2W, sig)
    fv[SYMBOLS.index("AC_50_C_2")] = bs_call(S0, 50, T_2W, sig)
    # Chooser: parity for r=0 -> C_3w + P_2w
    fv[SYMBOLS.index("AC_50_CO")] = fv[SYMBOLS.index("AC_50_C")] + fv[SYMBOLS.index("AC_50_P_2")]
    # Binary put: 10 * P[S_T < 40]
    _, d2 = _d12(S0, 40, T_3W, sig)
    fv[SYMBOLS.index("AC_40_BP")] = 10.0 * (1.0 - norm.cdf(d2))
    # KO via MC
    rng = np.random.default_rng(ko_seed)
    drift = -0.5 * sig * sig * DT
    volstep = sig * math.sqrt(DT)
    Z = rng.standard_normal((ko_paths, N_3W))
    log_paths = np.log(S0) + np.cumsum(drift + volstep * Z, axis=1)
    S_paths = np.exp(log_paths)
    min_S = S_paths.min(axis=1)
    S_T = S_paths[:, -1]
    fv[SYMBOLS.index("AC_45_KO")] = float(np.where(min_S > 35, np.maximum(45 - S_T, 0.0), 0.0).mean())
    return fv


# ============================================================
# 4. SIGMA-GRID MC (CHUNKED 50M)
# ============================================================
SIGMA_GRID = [2.20, 2.30, 2.40, 2.45, 2.49, 2.50, 2.505,
              2.51, 2.515, 2.52, 2.55, 2.60, 2.65, 2.70, 2.80]
# MC budget (single tier given 30-45min wall budget).
# CHUNK=1M keeps peak RAM ~480MB. 20M/sigma x 15 = ~17min for grid.
# Bisection: 5 iters x 2 problems x 20M = ~12min more. Total ~30min wall.
# SE at 20M for paired E[7POS]-E[5POS] gap ~ $150/trial — plenty for $6k gap.
N_TOTAL = 20_000_000
N_TOTAL_FINE = 20_000_000
CHUNK = 1_000_000
N_CHUNKS = N_TOTAL // CHUNK
TRIAL_SIZE = 100  # IMC scales realized PnL x 3000; one "trial" = mean over 100 i.i.d. paths


def sigma_eval(sig: float, n_paths: int = N_TOTAL, base_seed: int = 0xBEEF) -> dict:
    """Run MC at sigma sig, evaluating all strategies in STRATS.

    Returns dict[strategy] -> {mean, sd, sharpe, p_pos, cvar5, mean_usd, ...}
    Uses Welford-style streaming aggregation per chunk to keep RAM bounded.
    """
    chunk_size = min(CHUNK, n_paths)
    n_chunks = max(1, n_paths // chunk_size)
    # If n_paths < CHUNK we still want at least one chunk equal to n_paths.
    if n_chunks * chunk_size != n_paths:
        chunk_size = n_paths // n_chunks
    # Streaming sums per strategy
    sums = {name: 0.0 for name in STRATS}
    sumsq = {name: 0.0 for name in STRATS}
    # For CVaR & P>0 we need quantiles -> keep a bounded reservoir of bottom-tail and full sample for global p_pos.
    # CLT approximation is acceptable at 50M (more accurate than empirical tail at 5%).
    # We compute exact P(>0) via empirical fraction (cheap) and CVaR via empirical quantile on a 200k-sample reservoir.
    pos_count = {name: 0 for name in STRATS}
    # Reservoir: keep ALL pnls in float32 across chunks IF n_paths * len(strats) * 4 bytes is acceptable.
    # 50M x 6 x 4 = 1.2GB - too much. Subsample 1M per strategy.
    reservoir_n = 1_000_000
    sample_keep_frac = reservoir_n / n_paths  # e.g. 0.02
    reservoirs = {name: [] for name in STRATS}

    for ch in range(n_chunks):
        seed = base_seed + ch
        paths = gen_paths(chunk_size, seed=seed, sig=sig)
        P = payoffs_matrix(paths)  # (chunk_size, N_INST)
        # Per-path PnL = qvec * (payoff ? price) where price = ask if q>=0 else bid
        for name, q in STRATS.items():
            prices = trade_prices(q)
            pnl = (q[None, :] * (P - prices[None, :])).sum(axis=1)  # (chunk_size,)
            sums[name] += float(pnl.sum())
            sumsq[name] += float((pnl * pnl).sum())
            pos_count[name] += int((pnl > 0).sum())
            # Subsample for reservoir
            mask = np.random.default_rng(seed * 7 + 13).random(chunk_size) < sample_keep_frac
            if mask.any():
                reservoirs[name].append(pnl[mask].astype(np.float32))
        del paths, P

    # Aggregate
    out = {}
    n = n_chunks * chunk_size
    for name in STRATS:
        m = sums[name] / n
        var = sumsq[name] / n - m * m
        sd = math.sqrt(max(var, 0.0))
        # Per-trial (mean of TRIAL_SIZE paths) statistics
        sd_trial = sd / math.sqrt(TRIAL_SIZE)
        sharpe_trial = m / sd_trial if sd_trial > 0 else 0.0
        p_pos_path = pos_count[name] / n
        # P(trial > 0) via CLT (mean of TRIAL_SIZE i.i.d. ~ Normal(m, sd_trial))
        p_pos_trial = float(norm.cdf(m / sd_trial)) if sd_trial > 0 else 1.0
        # Empirical CVaR-5% on per-path PnL from reservoir
        res = np.concatenate(reservoirs[name]) if reservoirs[name] else np.array([0.0])
        var5 = float(np.quantile(res, 0.05))
        tail = res[res <= var5]
        cvar5_path = float(tail.mean()) if tail.size else var5
        # CVaR-5% on per-trial CLT (mean of TRIAL_SIZE):
        z = norm.ppf(0.95)
        cvar5_trial = m - sd_trial * (norm.pdf(z) / 0.05)
        out[name] = {
            "mean":       m,
            "sd":         sd,
            "sd_trial":   sd_trial,
            "sharpe_trial": sharpe_trial,
            "p_pos_path": p_pos_path,
            "p_pos_trial": p_pos_trial,
            "cvar5_path": cvar5_path,
            "cvar5_trial": cvar5_trial,
            "mean_usd":   m * CONTRACT_MULT,
            "sd_trial_usd": sd_trial * CONTRACT_MULT,
            "cvar5_trial_usd": cvar5_trial * CONTRACT_MULT,
        }
    return out


# ============================================================
# 5. RUN GRID
# ============================================================
def main():
    print("=" * 100)
    print("R4 MANUAL - SIGMA SENSITIVITY ANALYSIS")
    print("=" * 100)
    print(f"Strategies: {list(STRATS.keys())}")
    print(f"Sigma grid: {SIGMA_GRID}")
    print(f"Paths per sigma: {N_TOTAL:,}  ({N_CHUNKS} chunks x {CHUNK:,})")
    print()

    # 4. Implied vol cross-check (no MC needed)
    print("-" * 100)
    print("STEP 4: IMPLIED VOL CROSS-CHECK (mid quote -> BS-implied sigma)")
    print("-" * 100)

    def implied_vol(price, S, K, T, is_call):
        lo, hi = 0.001, 30.0
        for _ in range(120):
            mid = 0.5 * (lo + hi)
            v = bs_call(S, K, T, mid) if is_call else bs_put(S, K, T, mid)
            if v > price:
                hi = mid
            else:
                lo = mid
        return 0.5 * (lo + hi)

    iv_table = []
    for s in ["AC_35_P", "AC_40_P", "AC_45_P", "AC_50_P", "AC_50_C", "AC_60_C",
              "AC_50_P_2", "AC_50_C_2"]:
        bid, ask, _ = QUOTES[s]
        mid = 0.5 * (bid + ask)
        is_call = s.endswith("C") or s.endswith("C_2")
        K = int(s.split("_")[1])
        T = T_2W if s.endswith("_2") else T_3W
        iv_bid = implied_vol(bid, S0, K, T, is_call)
        iv_ask = implied_vol(ask, S0, K, T, is_call)
        iv_mid = implied_vol(mid, S0, K, T, is_call)
        iv_table.append((s, K, T_3W_DAYS if T == T_3W else T_2W_DAYS, bid, ask, iv_bid, iv_mid, iv_ask))
        print(f"  {s:<14} K={K:<3} T={int(T*252):>2}td  bid={bid:>6.3f}/{iv_bid:>5.3f}  mid={mid:>6.3f}/{iv_mid:>5.3f}  ask={ask:>6.3f}/{iv_ask:>5.3f}")

    # Binary put IV (10 * N(-d2)) -> invert manually
    bp_mid = 0.5 * (QUOTES["AC_40_BP"][0] + QUOTES["AC_40_BP"][1])
    p_implied = bp_mid / 10.0
    # 10 * (1 - N(d2)) = bp_mid -> 1 - N(d2) = p_implied
    # d2 = N^-1(1 - p_implied)
    d2_target = norm.ppf(1.0 - p_implied)
    # d2 = (ln(S/K) - 0.5 sigma^2 T) / (sigma sqrtT)
    # Numeric solve in sigma
    def bp_resid(sig):
        if sig <= 0:
            return -bp_mid
        _, d2 = _d12(S0, 40, T_3W, sig)
        return 10.0 * (1.0 - norm.cdf(d2)) - bp_mid
    lo, hi = 0.01, 30.0
    for _ in range(120):
        mid = 0.5 * (lo + hi)
        if bp_resid(mid) > 0:
            hi = mid
        else:
            lo = mid
    bp_iv = 0.5 * (lo + hi)
    print(f"  AC_40_BP       K=40  T=15td  bid={QUOTES['AC_40_BP'][0]:>6.3f}  mid={bp_mid:>6.3f}/{bp_iv:>5.3f}  ask={QUOTES['AC_40_BP'][1]:>6.3f}")

    # Chooser IV (sum of 3w call + 2w put) - combined
    co_mid = 0.5 * (QUOTES["AC_50_CO"][0] + QUOTES["AC_50_CO"][1])

    def co_resid(sig):
        return bs_call(S0, 50, T_3W, sig) + bs_put(S0, 50, T_2W, sig) - co_mid
    lo, hi = 0.01, 30.0
    for _ in range(120):
        mid = 0.5 * (lo + hi)
        if co_resid(mid) > 0:
            hi = mid
        else:
            lo = mid
    co_iv = 0.5 * (lo + hi)
    print(f"  AC_50_CO       K=50  chooser  bid={QUOTES['AC_50_CO'][0]:>6.3f}  mid={co_mid:>6.3f}/{co_iv:>5.3f}  ask={QUOTES['AC_50_CO'][1]:>6.3f}")

    # 5. Vega exposure
    print()
    print("-" * 100)
    print(f"STEP 5: VEGA + VOLGA at sigma={SIGMA_BASE}")
    print("-" * 100)

    def position_greeks(qvec, sig):
        """Returns (vega_total, volga_total, KO_dvega via numerical FD)."""
        vega = 0.0
        volga = 0.0
        for i, s in enumerate(SYMBOLS):
            q = qvec[i]
            if q == 0:
                continue
            if s in ("AC_50_P", "AC_50_C"):
                v = bs_vega(S0, 50, T_3W, sig); vol = bs_volga(S0, 50, T_3W, sig)
            elif s == "AC_35_P":
                v = bs_vega(S0, 35, T_3W, sig); vol = bs_volga(S0, 35, T_3W, sig)
            elif s == "AC_40_P":
                v = bs_vega(S0, 40, T_3W, sig); vol = bs_volga(S0, 40, T_3W, sig)
            elif s == "AC_45_P":
                v = bs_vega(S0, 45, T_3W, sig); vol = bs_volga(S0, 45, T_3W, sig)
            elif s == "AC_60_C":
                v = bs_vega(S0, 60, T_3W, sig); vol = bs_volga(S0, 60, T_3W, sig)
            elif s in ("AC_50_P_2", "AC_50_C_2"):
                v = bs_vega(S0, 50, T_2W, sig); vol = bs_volga(S0, 50, T_2W, sig)
            elif s == "AC_50_CO":
                v = bs_vega(S0, 50, T_3W, sig) + bs_vega(S0, 50, T_2W, sig)
                vol = bs_volga(S0, 50, T_3W, sig) + bs_volga(S0, 50, T_2W, sig)
            elif s == "AC":
                v = 0.0; vol = 0.0
            elif s == "AC_40_BP":
                # binary put: 10 * (1-N(d2)). dPrice/dsigma = 10 * phi(d2) * (-dd2/dsigma)
                # d2 = (ln(S/K) - 0.5 sigma^2 T)/(sigmasqrtT) -> dd2/dsigma = -0.5 sqrtT - ln(S/K)/(sigma^2sqrtT) ? approximate via FD.
                eps = 0.001
                _, d2_p = _d12(S0, 40, T_3W, sig + eps)
                _, d2_m = _d12(S0, 40, T_3W, sig - eps)
                bp_p = 10.0 * (1.0 - norm.cdf(d2_p))
                bp_m = 10.0 * (1.0 - norm.cdf(d2_m))
                v = (bp_p - bp_m) / (2 * eps)
                vol = (10.0 * (1.0 - norm.cdf(d2_p)) - 2 * 10.0 * (1.0 - norm.cdf(_d12(S0,40,T_3W,sig)[1]))
                       + bp_m) / (eps * eps)
            elif s == "AC_45_KO":
                # FD via re-MC at ?eps
                eps = 0.005
                v_p = fair_values(sig + eps, ko_paths=400_000, ko_seed=777)[i]
                v_m = fair_values(sig - eps, ko_paths=400_000, ko_seed=777)[i]
                v = (v_p - v_m) / (2 * eps)
                v0 = fair_values(sig, ko_paths=400_000, ko_seed=777)[i]
                vol = (v_p - 2 * v0 + v_m) / (eps * eps)
            else:
                v = 0.0; vol = 0.0
            vega += q * v
            volga += q * vol
        return vega, volga

    greeks = {}
    for name, q in STRATS.items():
        veg, volg = position_greeks(q, SIGMA_BASE)
        greeks[name] = {"vega": veg, "volga": volg, "vega_usd_per_pct": veg * CONTRACT_MULT * 0.01}
        print(f"  {name:<14} vega = {veg:>+10.2f}/path  ({veg*CONTRACT_MULT:>+12,.0f} USD per Deltasigma=1.0)  volga = {volg:>+10.2f}")

    # 1. SIGMA GRID EVAL
    print()
    print("-" * 100)
    print(f"STEP 1: SIGMA GRID - {N_TOTAL:,} paths per sigma x {len(SIGMA_GRID)} grid points")
    print("-" * 100)

    grid_results = {}  # sigma -> {strat -> stats}
    for sig in SIGMA_GRID:
        t1 = time.time()
        res = sigma_eval(sig)
        dt = time.time() - t1
        grid_results[sig] = res
        print(f"\n  sigma={sig:<5}  ({dt:>4.1f}s elapsed)")
        print(f"    {'Strategy':<14} {'E[PnL]':>10} {'$ E[score]':>12} {'$ SD/trial':>11} {'Sharpe':>7} {'$ CVaR5':>11} {'P(>0)':>7}")
        for name, r in res.items():
            print(f"    {name:<14} {r['mean']:>+10.4f} {r['mean_usd']:>+12,.0f} {r['sd_trial_usd']:>11,.0f} "
                  f"{r['sharpe_trial']:>7.2f} {r['cvar5_trial_usd']:>+11,.0f} {r['p_pos_trial']*100:>6.2f}%")

    # 2. SIGMA BREAK-EVEN BISECTION (OPTIMAL_7POS vs DROP_60C)
    print()
    print("-" * 100)
    print("STEP 2: SIGMA BREAK-EVEN - OPTIMAL_7POS vs DROP_60C")
    print("-" * 100)
    # Compute differential EV at each sigma; bisect using MC where coarse signs differ
    diff_ev = {sig: grid_results[sig]["OPTIMAL_7POS"]["mean"] - grid_results[sig]["DROP_60C"]["mean"]
               for sig in SIGMA_GRID}
    print(f"  sigma-grid  E[7POS]-E[5POS] (per-path):")
    for sig in SIGMA_GRID:
        print(f"    sigma={sig:<5}  Delta = {diff_ev[sig]:>+8.4f}/path  ({diff_ev[sig]*CONTRACT_MULT:>+9,.0f} USD)")

    # Find sign change in coarse grid
    sigs_sorted = sorted(SIGMA_GRID)
    cross_lo = cross_hi = None
    for a, b in zip(sigs_sorted, sigs_sorted[1:]):
        if diff_ev[a] * diff_ev[b] < 0:
            cross_lo, cross_hi = a, b
            break
    if cross_lo is None:
        print("  No sign change found in sigma-grid; OPTIMAL_7POS sign of Delta is constant.")
    else:
        print(f"  Sign change between sigma={cross_lo} and sigma={cross_hi}; bisecting to 0.005 precision ...")
        # Use 10M paths at finer sigma to bisect, since Delta is small.
        a, b = cross_lo, cross_hi
        FINER_PATHS = N_TOTAL_FINE
        for it in range(6):
            mid = 0.5 * (a + b)
            res_mid = sigma_eval(mid, n_paths=FINER_PATHS, base_seed=0xCAFE + it)
            d_mid = res_mid["OPTIMAL_7POS"]["mean"] - res_mid["DROP_60C"]["mean"]
            print(f"    iter {it}: sigma_mid={mid:.5f}  Delta={d_mid:+.5f}/path  ({d_mid*CONTRACT_MULT:+,.0f} USD)")
            if (d_mid > 0) == (diff_ev[b] > 0):
                b = mid
            else:
                a = mid
            if abs(b - a) < 0.005:
                break
        print(f"  Break-even sigma in [{a:.4f}, {b:.4f}]  (precision {b-a:.4f})")
        cross_sigma = 0.5 * (a + b)
    # Find sigma at which OPTIMAL_7POS becomes negative-EV
    print()
    print("  sigma-grid where OPTIMAL_7POS E[score] is negative:")
    for sig in SIGMA_GRID:
        ev = grid_results[sig]["OPTIMAL_7POS"]["mean"]
        flag = "NEGATIVE" if ev < 0 else "positive"
        print(f"    sigma={sig:<5}  E[7POS] = {ev:>+8.4f}  ({ev*CONTRACT_MULT:>+9,.0f} USD)  {flag}")

    # Bisect for negative-EV sigma ceiling.
    sigs_sorted = sorted(SIGMA_GRID)
    neg_lo = neg_hi = None
    for a, b in zip(sigs_sorted, sigs_sorted[1:]):
        ea = grid_results[a]["OPTIMAL_7POS"]["mean"]
        eb = grid_results[b]["OPTIMAL_7POS"]["mean"]
        if ea * eb < 0:
            neg_lo, neg_hi = a, b
            break
    if neg_lo is None:
        print("  OPTIMAL_7POS does not change sign in tested grid.")
    else:
        print(f"  OPTIMAL_7POS turns negative between sigma={neg_lo} and sigma={neg_hi}; bisecting ...")
        a, b = neg_lo, neg_hi
        for it in range(6):
            mid = 0.5 * (a + b)
            res_mid = sigma_eval(mid, n_paths=N_TOTAL_FINE, base_seed=0xDEAD + it)
            ev_mid = res_mid["OPTIMAL_7POS"]["mean"]
            print(f"    iter {it}: sigma_mid={mid:.5f}  E[7POS]={ev_mid:+.5f}  ({ev_mid*CONTRACT_MULT:+,.0f} USD)")
            if ev_mid > 0:
                a = mid
            else:
                b = mid
            if abs(b - a) < 0.005:
                break
        print(f"  Negative-EV sigma in [{a:.4f}, {b:.4f}]  (precision {b-a:.4f})")
        neg_sigma = 0.5 * (a + b)

    # 3. ROBUST OPTIMIZATION - sigma ~ U[2.45, 2.57]
    print()
    print("-" * 100)
    print("STEP 3: ROBUST E[score] under sigma ~ Uniform[2.45, 2.57]")
    print("-" * 100)
    robust_grid = [s for s in SIGMA_GRID if 2.45 <= s <= 2.57]
    print(f"  Grid: {robust_grid}")
    print(f"  {'Strategy':<14} {'min E':>10} {'mean E':>10} {'max E':>10} {'minmax-USD':>12}")
    robust_summary = {}
    for name in STRATS:
        evs = [grid_results[s][name]["mean"] for s in robust_grid]
        mn, mu, mx = min(evs), sum(evs) / len(evs), max(evs)
        robust_summary[name] = {"min_ev": mn, "mean_ev": mu, "max_ev": mx,
                                "min_usd": mn * CONTRACT_MULT,
                                "mean_usd": mu * CONTRACT_MULT,
                                "max_usd": mx * CONTRACT_MULT}
        print(f"  {name:<14} {mn:>+10.4f} {mu:>+10.4f} {mx:>+10.4f} {mn*CONTRACT_MULT:>+12,.0f}")
    best_robust = max(robust_summary, key=lambda n: robust_summary[n]["min_ev"])
    print(f"\n  ROBUST OPTIMUM (max-min E[score] across sigma in [2.45, 2.57]): {best_robust}")

    # 6. SENSITIVITY DECOMPOSITION dE[score]/dsigma via finite difference + per-instrument vega
    print()
    print("-" * 100)
    print(f"STEP 6: dE[score]/dsigma DECOMPOSITION at sigma={SIGMA_BASE}")
    print("-" * 100)
    eps = 0.005
    fv_p = fair_values(SIGMA_BASE + eps)
    fv_m = fair_values(SIGMA_BASE - eps)
    dfv = (fv_p - fv_m) / (2 * eps)
    # For our portfolio P&L = sum_i q_i * (payoff_i - price_i). Expectation: E[PnL] = sum_i q_i * (FV_i - price_i).
    # dE/dsigma = sum_i q_i * dFV_i/dsigma. Note: prices are FIXED (market quotes), so the sigma derivative comes only from FV_i.
    print(f"  Per-instrument dFV/dsigma (analytic-ish):")
    print(f"    {'Symbol':<14} {'FV(sigma_b)':>9} {'dFV/dsigma':>9} {'q[7POS]':>8} {'q[5POS]':>8} {'qxdFV/dsigma (7POS)':>16}")
    contrib_7pos = {}
    contrib_5pos = {}
    for i, s in enumerate(SYMBOLS):
        c7 = OPTIMAL_7POS[i] * dfv[i]
        c5 = DROP_60C[i] * dfv[i]
        contrib_7pos[s] = c7
        contrib_5pos[s] = c5
        print(f"    {s:<14} {0.5*(fv_p[i]+fv_m[i]):>9.4f} {dfv[i]:>+9.4f} {OPTIMAL_7POS[i]:>+8d} {DROP_60C[i]:>+8d} {c7:>+16.4f}")
    print(f"  Sum qxdFV/dsigma for OPTIMAL_7POS = {sum(contrib_7pos.values()):+.4f}/path/Deltasigma")
    print(f"  Sum qxdFV/dsigma for DROP_60C    = {sum(contrib_5pos.values()):+.4f}/path/Deltasigma")
    print(f"  -> 7POS vs 5POS sigma-sensitivity gap = {sum(contrib_7pos.values()) - sum(contrib_5pos.values()):+.4f}")

    # 7. CONVEXITY (d^2E/dsigma^2) via central-difference on E[score](sigma)
    print()
    print("-" * 100)
    print("STEP 7: CONVEXITY OF E[score] IN sigma (2nd derivative, finite diff over sigma-grid)")
    print("-" * 100)
    # Use grid points near SIGMA_BASE: {2.49, 2.50, 2.51, 2.52, 2.55} for cleaner FD
    print(f"  {'Strategy':<14} {'E(2.49)':>9} {'E(2.50)':>9} {'E(2.51)':>9} {'E(2.52)':>9} {'d^2/dsigma^2':>10} {'shape':>8}")
    for name in STRATS:
        e249 = grid_results[2.49][name]["mean"]
        e250 = grid_results[2.50][name]["mean"]
        e251 = grid_results[2.51][name]["mean"]
        e252 = grid_results[2.52][name]["mean"]
        # central FD with h=0.01: (f(x+h)-2f(x)+f(x-h)) / h^2
        d2 = (e252 - 2 * e251 + e250) / (0.01 ** 2)
        d2_b = (e251 - 2 * e250 + e249) / (0.01 ** 2)
        d2_avg = 0.5 * (d2 + d2_b)
        shape = "convex" if d2_avg > 1e-3 else ("concave" if d2_avg < -1e-3 else "linear")
        print(f"  {name:<14} {e249:>+9.4f} {e250:>+9.4f} {e251:>+9.4f} {e252:>+9.4f} {d2_avg:>+10.2f} {shape:>8}")

    # ============================================================
    # SAVE JSON
    # ============================================================
    save = {
        "sigma_grid": SIGMA_GRID,
        "n_paths": N_TOTAL,
        "strategies": {name: {SYMBOLS[i]: int(STRATS[name][i]) for i in range(N_INST)} for name in STRATS},
        "grid_results": {str(s): {n: {k: float(v) for k, v in r.items()}
                                  for n, r in grid_results[s].items()} for s in SIGMA_GRID},
        "iv_table": [(s, K, days, bid, ask, ivb, ivm, iva)
                     for (s, K, days, bid, ask, ivb, ivm, iva) in iv_table],
        "vega_volga": greeks,
        "robust_summary": robust_summary,
        "robust_best": best_robust,
        "dFV_dsigma": {SYMBOLS[i]: float(dfv[i]) for i in range(N_INST)},
        "contrib_7pos_dsigma": contrib_7pos,
        "contrib_5pos_dsigma": contrib_5pos,
    }
    if cross_lo is not None:
        save["crossover_sigma_band"] = [float(a), float(b)]
        save["crossover_sigma"] = float(cross_sigma)
    if neg_lo is not None:
        save["negative_ev_sigma_band"] = [float(a), float(b)]
        save["negative_ev_sigma"] = float(neg_sigma)
    out_path = "C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/manual/sigma_sensitivity_v2.json"
    with open(out_path, "w") as f:
        json.dump(save, f, indent=2, default=float)
    print(f"\nSaved: {out_path}")

    print(f"\nTotal elapsed: {time.time()-T0:.1f}s")
    print("=" * 100)


if __name__ == "__main__":
    main()
