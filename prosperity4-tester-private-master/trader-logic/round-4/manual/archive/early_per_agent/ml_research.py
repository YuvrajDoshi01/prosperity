"""R4 Manual Challenge — ML/MC research script.

Vectorized 10M-path Monte Carlo over the 12 Aether Crystal instruments,
followed by linear-greedy portfolio search, risk metrics on top portfolios,
sensitivity analysis on sigma misspecification, and a head-to-head bake-off
between user-supplied candidate portfolios and the optimum.

Run:
    python ml_research.py

Output:
    Console summary
    ml_research_results.md  (full report, written by the companion notebook
                              cell — this script just prints; markdown is
                              authored separately so the user can re-run with
                              tweaks).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

# ─────────────────────────────────────────────────────────────────────────────
# 1. Parameters
# ─────────────────────────────────────────────────────────────────────────────

S0 = 50.0
SIGMA = 2.51
R = 0.0
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_2W_DAYS = 10
T_3W = T_3W_DAYS / TRADING_DAYS_YEAR
T_2W = T_2W_DAYS / TRADING_DAYS_YEAR
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W_STEPS = T_3W_DAYS * STEPS_PER_DAY      # 60
N_2W_STEPS = T_2W_DAYS * STEPS_PER_DAY      # 40

# Quotes: (bid, ask, vol_cap)
QUOTES = {
    "AETHER":    (49.975, 50.025, 200),
    "AC_50_P":   (12.00, 12.05, 50),
    "AC_50_C":   (12.00, 12.05, 50),
    "AC_35_P":   (4.33,  4.35,  50),
    "AC_40_P":   (6.50,  6.55,  50),
    "AC_45_P":   (9.05,  9.10,  50),
    "AC_60_C":   (8.80,  8.85,  50),
    "AC_50_P_2": (9.70,  9.75,  50),
    "AC_50_C_2": (9.70,  9.75,  50),
    "AC_50_CO":  (22.20, 22.30, 50),
    "AC_40_BP":  (5.00,  5.10,  50),
    "AC_45_KO":  (0.15,  0.175, 500),
}

INSTRUMENTS = list(QUOTES.keys())
N_INST = len(INSTRUMENTS)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Black-Scholes helpers (vectorized + scalar)
# ─────────────────────────────────────────────────────────────────────────────

def bs_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    sqT = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sqT
    d2 = d1 - sqT
    return S * norm.cdf(d1) - K * norm.cdf(d2)


def bs_put(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    sqT = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sqT
    d2 = d1 - sqT
    return K * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_call_vec(S, K, T, sigma):
    """Vectorized BS call. S can be array."""
    S = np.asarray(S, dtype=np.float64)
    sqT = sigma * math.sqrt(T)
    d1 = (np.log(S / K) + 0.5 * sigma * sigma * T) / sqT
    d2 = d1 - sqT
    return S * norm.cdf(d1) - K * norm.cdf(d2)


def bs_put_vec(S, K, T, sigma):
    S = np.asarray(S, dtype=np.float64)
    sqT = sigma * math.sqrt(T)
    d1 = (np.log(S / K) + 0.5 * sigma * sigma * T) / sqT
    d2 = d1 - sqT
    return K * norm.cdf(-d2) - S * norm.cdf(-d1)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Vectorized MC path generator
# ─────────────────────────────────────────────────────────────────────────────

def simulate_paths(n_paths: int, seed: int, sigma: float = SIGMA):
    """
    Vectorized GBM over N_3W_STEPS=60 steps.
    Returns dict with arrays of shape (n_paths,):
        S_T       — terminal S at 3w
        S_2w      — S at the 2w intermediate timestep (step 40)
        min_S     — running min over the full path (for KO put)
    Memory-efficient: streams in chunks if n_paths is huge.
    """
    rng = np.random.default_rng(seed)
    drift_step = -0.5 * sigma * sigma * DT
    vol_step = sigma * math.sqrt(DT)

    CHUNK = 200_000  # process this many paths at a time to control RAM
    S_T_out = np.empty(n_paths, dtype=np.float64)
    S_2w_out = np.empty(n_paths, dtype=np.float64)
    min_S_out = np.empty(n_paths, dtype=np.float64)

    done = 0
    while done < n_paths:
        n = min(CHUNK, n_paths - done)
        # Generate (n, N_3W_STEPS) standard normals
        Z = rng.standard_normal(size=(n, N_3W_STEPS))
        # Log-returns per step
        log_returns = drift_step + vol_step * Z
        # Cumulative log price relative to S0
        log_S = np.log(S0) + np.cumsum(log_returns, axis=1)
        S = np.exp(log_S)
        S_T_out[done:done + n] = S[:, -1]
        S_2w_out[done:done + n] = S[:, N_2W_STEPS - 1]
        # Running min over path INCLUDING S0? KO barrier is monitored after t=0,
        # but S0=50 > B=35, so initial point safe. Track min of the path values
        # (post t=0). This matches the original solver convention.
        min_S_out[done:done + n] = S.min(axis=1)
        done += n

    return {"S_T": S_T_out, "S_2w": S_2w_out, "min_S": min_S_out}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Per-unit payoff matrix (12 × N_paths)
# ─────────────────────────────────────────────────────────────────────────────

def build_payoff_matrix(paths: dict, sigma_for_chooser: float = SIGMA) -> np.ndarray:
    """
    Compute per-unit payoff at expiry for each (instrument, path).
    Returns shape (N_INST, n_paths).

    Convention for AETHER: PnL of holding 1 spot unit from t=0 to expiry =
    (S_T - S0) for buy-and-hold-then-MTM-at-end. We treat it as just S_T,
    consistent with the existing solver (cost=ask, payoff=S_T at end).

    For chooser: at 2w pick the side with higher BS continuation value at 2w
    given remaining time = 5 trading days under sigma=SIGMA (calibration vol;
    not the sensitivity vol — the holder's optimal exercise is fixed by the
    real vol they believe in, which we anchor to SIGMA=2.51 throughout).
    """
    S_T = paths["S_T"]
    S_2w = paths["S_2w"]
    min_S = paths["min_S"]
    n = S_T.shape[0]

    P = np.zeros((N_INST, n), dtype=np.float64)

    # AETHER spot — payoff "at expiry" = S_T (treated like a forward held to 3w)
    P[INSTRUMENTS.index("AETHER")]    = S_T

    # 3w vanillas
    P[INSTRUMENTS.index("AC_50_P")]   = np.maximum(50 - S_T, 0)
    P[INSTRUMENTS.index("AC_50_C")]   = np.maximum(S_T - 50, 0)
    P[INSTRUMENTS.index("AC_35_P")]   = np.maximum(35 - S_T, 0)
    P[INSTRUMENTS.index("AC_40_P")]   = np.maximum(40 - S_T, 0)
    P[INSTRUMENTS.index("AC_45_P")]   = np.maximum(45 - S_T, 0)
    P[INSTRUMENTS.index("AC_60_C")]   = np.maximum(S_T - 60, 0)

    # 2w vanillas
    P[INSTRUMENTS.index("AC_50_P_2")] = np.maximum(50 - S_2w, 0)
    P[INSTRUMENTS.index("AC_50_C_2")] = np.maximum(S_2w - 50, 0)

    # Chooser: at 2w, pick the side with higher BS value (sigma=SIGMA fixed)
    T_remaining = (N_3W_STEPS - N_2W_STEPS) * DT
    c_at_2w = bs_call_vec(S_2w, 50, T_remaining, sigma_for_chooser)
    p_at_2w = bs_put_vec(S_2w, 50, T_remaining, sigma_for_chooser)
    chose_call = c_at_2w >= p_at_2w
    chooser_payoff = np.where(chose_call,
                              np.maximum(S_T - 50, 0),
                              np.maximum(50 - S_T, 0))
    P[INSTRUMENTS.index("AC_50_CO")]  = chooser_payoff

    # Binary put
    P[INSTRUMENTS.index("AC_40_BP")]  = np.where(S_T < 40, 10.0, 0.0)

    # KO put: barrier monitored at each MC step; pays max(K-S_T, 0) if min_S > 35
    survived = min_S > 35.0
    P[INSTRUMENTS.index("AC_45_KO")]  = np.where(survived, np.maximum(45 - S_T, 0), 0.0)

    return P


# ─────────────────────────────────────────────────────────────────────────────
# 5. Per-unit signed-PnL vectors
# ─────────────────────────────────────────────────────────────────────────────

def build_unit_pnl(payoff_matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    For each instrument, build the per-unit PnL of holding +1 (BUY @ ask) and
    -1 (SELL @ bid). Returns:
        pnl_buy:  (N_INST, n_paths)  = payoff - ask
        pnl_sell: (N_INST, n_paths)  = bid    - payoff
    Holding `q` units (signed: +q = buy, -q = sell) gives PnL =
        q > 0:  q * pnl_buy[i]
        q < 0: |q| * pnl_sell[i]
    But because each side has its own price, the PnL is PIECEWISE-LINEAR in q:
    each instrument should be optimized independently (linear payoff per side).
    """
    n_paths = payoff_matrix.shape[1]
    pnl_buy = np.empty_like(payoff_matrix)
    pnl_sell = np.empty_like(payoff_matrix)
    for i, sym in enumerate(INSTRUMENTS):
        bid, ask, _ = QUOTES[sym]
        pnl_buy[i]  = payoff_matrix[i] - ask
        pnl_sell[i] = bid - payoff_matrix[i]
    return pnl_buy, pnl_sell


# ─────────────────────────────────────────────────────────────────────────────
# 6. Optimal portfolio: per-instrument greedy (decomposes!)
# ─────────────────────────────────────────────────────────────────────────────

def optimal_portfolio_meanopt(pnl_buy: np.ndarray,
                              pnl_sell: np.ndarray) -> np.ndarray:
    """
    Pure mean-EV optimum.

    Each instrument's PnL is independent of others (no shared book / margin).
    Per instrument:
        Mean PnL of +q units = q * E[pnl_buy[i]]    (q in 0..vol_cap)
        Mean PnL of -q units = q * E[pnl_sell[i]]   (q in 0..vol_cap)
    so the optimal sign is whichever side has positive expectation, sized
    at the volume cap.
    Returns signed-quantity vector of length N_INST (positive = long).
    """
    pos = np.zeros(N_INST, dtype=np.int64)
    for i, sym in enumerate(INSTRUMENTS):
        _, _, cap = QUOTES[sym]
        e_buy  = pnl_buy[i].mean()
        e_sell = pnl_sell[i].mean()
        if e_buy <= 0 and e_sell <= 0:
            pos[i] = 0
        elif e_buy >= e_sell:
            pos[i] = +cap
        else:
            pos[i] = -cap
    return pos


def portfolio_pnl_per_path(positions: np.ndarray,
                           pnl_buy: np.ndarray,
                           pnl_sell: np.ndarray) -> np.ndarray:
    """Per-path PnL of a signed-position vector."""
    n_paths = pnl_buy.shape[1]
    pnl = np.zeros(n_paths, dtype=np.float64)
    for i, q in enumerate(positions):
        if q == 0:
            continue
        if q > 0:
            pnl += q * pnl_buy[i]
        else:
            pnl += (-q) * pnl_sell[i]
    return pnl


# ─────────────────────────────────────────────────────────────────────────────
# 7. Risk metrics
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RiskReport:
    name: str
    positions: dict
    mean: float
    sd: float
    sharpe: float
    median: float
    p_pos: float
    cvar_05: float
    cvar_10: float
    cvar_25: float
    p01: float
    p99: float
    p_min: float
    p_max: float
    score_se_100: float  # SD of the mean of 100 sims
    score_p05_100: float
    score_p95_100: float


def compute_risk(name: str, positions: np.ndarray,
                 pnl_buy: np.ndarray, pnl_sell: np.ndarray,
                 n_subsamples_for_score: int = 5000) -> RiskReport:
    pnl = portfolio_pnl_per_path(positions, pnl_buy, pnl_sell)
    n = pnl.shape[0]
    mean = float(pnl.mean())
    sd = float(pnl.std(ddof=1))
    sharpe = mean / sd if sd > 0 else float("nan")
    median = float(np.median(pnl))
    p_pos = float((pnl > 0).mean())
    p01 = float(np.percentile(pnl, 1))
    p99 = float(np.percentile(pnl, 99))
    cvar_05 = float(pnl[pnl <= np.percentile(pnl, 5)].mean())
    cvar_10 = float(pnl[pnl <= np.percentile(pnl, 10)].mean())
    cvar_25 = float(pnl[pnl <= np.percentile(pnl, 25)].mean())

    # Score = mean of 100 sims. Sub-sample 100 paths from full pool many times.
    rng = np.random.default_rng(2026)
    sample_means = np.empty(n_subsamples_for_score, dtype=np.float64)
    for k in range(n_subsamples_for_score):
        idx = rng.integers(0, n, size=100)
        sample_means[k] = pnl[idx].mean()
    score_sd = float(sample_means.std(ddof=1))
    score_p05 = float(np.percentile(sample_means, 5))
    score_p95 = float(np.percentile(sample_means, 95))

    pos_dict = {INSTRUMENTS[i]: int(q) for i, q in enumerate(positions) if q != 0}

    return RiskReport(
        name=name, positions=pos_dict,
        mean=mean, sd=sd, sharpe=sharpe, median=median, p_pos=p_pos,
        cvar_05=cvar_05, cvar_10=cvar_10, cvar_25=cvar_25,
        p01=p01, p99=p99, p_min=float(pnl.min()), p_max=float(pnl.max()),
        score_se_100=score_sd, score_p05_100=score_p05, score_p95_100=score_p95,
    )


def print_risk(r: RiskReport):
    print(f"\n=== {r.name} ===")
    print(f"  Positions: {r.positions}")
    print(f"  Per-path stats over the MC pool:")
    print(f"    Mean    = {r.mean:+10.3f}")
    print(f"    SD      = {r.sd:10.3f}")
    print(f"    Sharpe  = {r.sharpe:+10.4f}")
    print(f"    Median  = {r.median:+10.3f}")
    print(f"    P(>0)   = {r.p_pos*100:6.2f}%")
    print(f"    P1/P99  = {r.p01:+10.2f} / {r.p99:+10.2f}")
    print(f"    Min/Max = {r.p_min:+10.2f} / {r.p_max:+10.2f}")
    print(f"    CVaR05  = {r.cvar_05:+10.2f}   CVaR10 = {r.cvar_10:+10.2f}   CVaR25 = {r.cvar_25:+10.2f}")
    print(f"  100-sim leaderboard score distribution (5,000 sub-samples):")
    print(f"    SE      = {r.score_se_100:10.3f}")
    print(f"    P5/P95  = {r.score_p05_100:+10.2f} / {r.score_p95_100:+10.2f}")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Candidate portfolio constructors
# ─────────────────────────────────────────────────────────────────────────────

def positions_from_dict(d: dict) -> np.ndarray:
    pos = np.zeros(N_INST, dtype=np.int64)
    for sym, q in d.items():
        pos[INSTRUMENTS.index(sym)] = q
    return pos


CANDIDATES = {
    # Mine: max-size at every signed edge (matches the existing manual writeup,
    # extended to the full set of edge-positive instruments).
    "MaxSize (writeup)": positions_from_dict({
        "AC_50_CO": -50,
        "AC_45_KO": +500,
        "AC_40_BP": -50,
        "AC_50_P_2": +50,
        "AC_50_C_2": +50,
        "AC_60_C": -50,
    }),

    # User's reference (literal interpretation).
    "User reference": positions_from_dict({
        "AC_50_CO": -15,
        "AC_40_BP": -50,
        "AC_50_P":  +17,
        "AC_50_P_2": +15,
        "AC_50_C":  +15,
        "AETHER":   +150,
    }),

    # Hybrid: max-size on the high-EV edges (chooser, KO, binary, 2w straddle)
    # but DROP the noisy "marginal" 60C edge (only +0.41 EV but adds tail).
    "Hybrid (drop 60C)": positions_from_dict({
        "AC_50_CO": -50,
        "AC_45_KO": +500,
        "AC_40_BP": -50,
        "AC_50_P_2": +50,
        "AC_50_C_2": +50,
    }),

    # Conservative: drop the KO (highest variance), keep the rest.
    "Conservative (drop KO)": positions_from_dict({
        "AC_50_CO": -50,
        "AC_40_BP": -50,
        "AC_50_P_2": +50,
        "AC_50_C_2": +50,
        "AC_60_C": -50,
    }),

    # Pure mean-Sharpe blend: all positive-edge sized at cap (computed below
    # by optimal_portfolio_meanopt, added to dict before reporting).
}


# ─────────────────────────────────────────────────────────────────────────────
# 9. Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    np.set_printoptions(suppress=True, linewidth=120)
    print("=" * 80)
    print("R4 MANUAL — ML/MC Research")
    print("=" * 80)
    print(f"S0={S0}  sigma={SIGMA}  steps/day={STEPS_PER_DAY}  3w={N_3W_STEPS} steps  2w={N_2W_STEPS} steps")
    print(f"DT={DT:.6f}  T_3w={T_3W:.5f}  T_2w={T_2W:.5f}")

    # ── 1. Generate paths in 5 seeded batches of 2M each (10M total) ────────
    SEEDS = [101, 202, 303, 404, 505]
    PER_SEED = 2_000_000
    print(f"\n--- Generating {len(SEEDS)} × {PER_SEED:,} = {len(SEEDS)*PER_SEED:,} MC paths ---")
    t0 = time.time()
    chunks = []
    for s in SEEDS:
        t_seed = time.time()
        c = simulate_paths(PER_SEED, seed=s, sigma=SIGMA)
        print(f"  seed={s}  {PER_SEED:,} paths  in {time.time()-t_seed:.1f}s")
        chunks.append(c)
    paths = {
        "S_T":   np.concatenate([c["S_T"]   for c in chunks]),
        "S_2w":  np.concatenate([c["S_2w"]  for c in chunks]),
        "min_S": np.concatenate([c["min_S"] for c in chunks]),
    }
    del chunks
    print(f"  Total {time.time()-t0:.1f}s — {paths['S_T'].shape[0]:,} paths in pool")

    # Sanity: BS vs MC means
    print("\n--- Sanity check: BS prices vs MC means ---")
    P = build_payoff_matrix(paths, sigma_for_chooser=SIGMA)
    print(f"  {'Instrument':12s} {'BS':>10} {'MC mean':>10} {'diff':>10}")
    bs_prices = {
        "AC_50_P":   bs_put(S0, 50, T_3W, SIGMA),
        "AC_50_C":   bs_call(S0, 50, T_3W, SIGMA),
        "AC_35_P":   bs_put(S0, 35, T_3W, SIGMA),
        "AC_40_P":   bs_put(S0, 40, T_3W, SIGMA),
        "AC_45_P":   bs_put(S0, 45, T_3W, SIGMA),
        "AC_60_C":   bs_call(S0, 60, T_3W, SIGMA),
        "AC_50_P_2": bs_put(S0, 50, T_2W, SIGMA),
        "AC_50_C_2": bs_call(S0, 50, T_2W, SIGMA),
        "AC_50_CO":  bs_call(S0, 50, T_3W, SIGMA) + bs_put(S0, 50, T_2W, SIGMA),
        "AC_40_BP":  10.0 * norm.cdf(-(math.log(S0/40) - 0.5*SIGMA**2*T_3W) / (SIGMA*math.sqrt(T_3W))),
    }
    for sym in INSTRUMENTS:
        idx = INSTRUMENTS.index(sym)
        mc_mean = float(P[idx].mean())
        bs = bs_prices.get(sym, None)
        bs_str = f"{bs:10.4f}" if bs is not None else f"{'—':>10}"
        diff_str = f"{mc_mean - bs:+10.5f}" if bs is not None else f"{'—':>10}"
        print(f"  {sym:12s} {bs_str} {mc_mean:10.4f} {diff_str}")

    # KO put: only MC available (discrete monitoring); print stand-alone
    print(f"\n  KO put MC = {P[INSTRUMENTS.index('AC_45_KO')].mean():.4f}  "
          f"(market ask 0.175 — buy edge {P[INSTRUMENTS.index('AC_45_KO')].mean()-0.175:+.4f})")

    # ── 2. Build per-side per-unit PnL matrices ──────────────────────────────
    pnl_buy, pnl_sell = build_unit_pnl(P)

    # ── 3. Linear-greedy optimum (each instrument independent) ──────────────
    opt_pos = optimal_portfolio_meanopt(pnl_buy, pnl_sell)
    print("\n--- Linear-greedy optimum (per-instrument independent) ---")
    print(f"  {'Instrument':12s} {'E[buy]':>10} {'E[sell]':>10} {'Cap':>5} {'Choice':>8} {'EV':>10}")
    total_ev = 0.0
    for i, sym in enumerate(INSTRUMENTS):
        e_b = pnl_buy[i].mean()
        e_s = pnl_sell[i].mean()
        _, _, cap = QUOTES[sym]
        q = opt_pos[i]
        if q > 0:
            choice = f"+{cap}"
            ev = q * e_b
        elif q < 0:
            choice = f"-{cap}"
            ev = (-q) * e_s
        else:
            choice = "0"
            ev = 0.0
        total_ev += ev
        print(f"  {sym:12s} {e_b:+10.4f} {e_s:+10.4f} {cap:>5d} {choice:>8s} {ev:+10.3f}")
    print(f"  {'TOTAL':12s} {'':>10} {'':>10} {'':>5} {'':>8} {total_ev:+10.3f}")

    CANDIDATES["LinearOpt (greedy)"] = opt_pos.copy()

    # ── 4. Risk report on top candidates ─────────────────────────────────────
    print("\n" + "=" * 80)
    print("RISK REPORTS — top candidate portfolios (per-path stats over 10M paths)")
    print("=" * 80)
    reports = []
    for name, pos in CANDIDATES.items():
        r = compute_risk(name, pos, pnl_buy, pnl_sell)
        reports.append(r)
        print_risk(r)

    # ── 5. Pareto frontier: vary the KO position to trade off mean vs SD ────
    print("\n" + "=" * 80)
    print("PARETO FRONTIER: KO put size sweep (fixing other 5 edges at max)")
    print("=" * 80)
    base_pos = positions_from_dict({
        "AC_50_CO": -50,
        "AC_40_BP": -50,
        "AC_50_P_2": +50,
        "AC_50_C_2": +50,
        "AC_60_C": -50,
    })
    print(f"  {'KO_qty':>8} {'mean':>10} {'SD':>10} {'sharpe':>10} {'P>0%':>8} {'CVaR05':>10}")
    pareto = []
    for ko_qty in [0, 50, 100, 200, 300, 400, 500]:
        pos = base_pos.copy()
        pos[INSTRUMENTS.index("AC_45_KO")] = ko_qty
        pnl = portfolio_pnl_per_path(pos, pnl_buy, pnl_sell)
        m = pnl.mean()
        s = pnl.std(ddof=1)
        cv5 = pnl[pnl <= np.percentile(pnl, 5)].mean()
        ppos = (pnl > 0).mean() * 100
        sharpe = m / s if s > 0 else float("nan")
        pareto.append((ko_qty, m, s, sharpe, ppos, cv5))
        print(f"  {ko_qty:>8d} {m:+10.3f} {s:10.3f} {sharpe:+10.4f} {ppos:>8.2f} {cv5:+10.2f}")

    # ── 6. Sigma sensitivity: re-price at sigma in {2.20, 2.40, 2.60, 2.80} ─
    print("\n" + "=" * 80)
    print("SIGMA-SENSITIVITY: re-simulate under different generative sigmas")
    print("=" * 80)
    print("(market QUOTES held fixed at the calibrated values; only the true sigma changes)")
    print(f"  {'sigma':>6} {'name':<24} {'mean':>10} {'SD':>10} {'P>0%':>8}")
    sens_seeds = [777, 888]  # smaller pool for speed (4M paths total)
    sens_per_seed = 2_000_000
    for sigma_test in [2.20, 2.40, 2.60, 2.80]:
        chunks = [simulate_paths(sens_per_seed, seed=s, sigma=sigma_test) for s in sens_seeds]
        paths_s = {
            "S_T":   np.concatenate([c["S_T"]   for c in chunks]),
            "S_2w":  np.concatenate([c["S_2w"]  for c in chunks]),
            "min_S": np.concatenate([c["min_S"] for c in chunks]),
        }
        # Note: chooser exercise STILL uses sigma=SIGMA (holder's belief).
        P_s = build_payoff_matrix(paths_s, sigma_for_chooser=SIGMA)
        pnl_buy_s, pnl_sell_s = build_unit_pnl(P_s)
        for name, pos in CANDIDATES.items():
            pnl = portfolio_pnl_per_path(pos, pnl_buy_s, pnl_sell_s)
            print(f"  {sigma_test:>6.2f} {name:<24} {pnl.mean():+10.3f} {pnl.std(ddof=1):10.3f} "
                  f"{(pnl>0).mean()*100:>8.2f}")
        del paths_s, P_s, pnl_buy_s, pnl_sell_s

    # ── 7. Final recommendation ──────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    best = max(reports, key=lambda r: r.score_p05_100)  # robust: max P5 of leaderboard score
    print(f"\n  Robust pick (max P5 of 100-sim score): {best.name}")
    print(f"    Mean      = {best.mean:+.3f}")
    print(f"    SD        = {best.sd:.3f}")
    print(f"    Sharpe    = {best.sharpe:+.4f}")
    print(f"    P(>0)     = {best.p_pos*100:.2f}%")
    print(f"    Score P5  = {best.score_p05_100:+.2f}  (5th percentile of 100-sim mean)")
    print(f"    Positions = {best.positions}")

    best_mean = max(reports, key=lambda r: r.mean)
    print(f"\n  Mean-EV pick: {best_mean.name}")
    print(f"    Mean      = {best_mean.mean:+.3f}")
    print(f"    Score P5  = {best_mean.score_p05_100:+.2f}")
    print(f"    Positions = {best_mean.positions}")


if __name__ == "__main__":
    main()
