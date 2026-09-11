"""R4 Manual: Constrained portfolio optimization across 12 instruments.

Generates a 1M-trial x 12-instrument per-unit PnL matrix (chunked over 100M paths,
grouped 100 paths per trial). Then optimizes signed integer position vector q
under three constraint families:

    (a) max E[score]  s.t. CVaR-5%    >= -X         (X-grid)
    (b) max E[score]  s.t. SD         <=  Y         (Y-grid)
    (c) max E[score]  s.t. P(score < -100k) <= p   (p-grid)

Plus:
    (d) Pareto frontier for (E[score], CVaR-5%) at fine granularity.
    (e) Verification of two reference portfolios: DROP_60C and OPTIMAL_7POS.
    (f) Robust utility: max E[score] - lam * max(0, -CVaR-5%) for lam-grid.
    (g) Kelly fractional analysis with W=$1M.
    (h) Worst-case path analysis on OPTIMAL_7POS.

Score = sum_i q_i * trial_pnl[:, i] * 3000  (per-trial PnL)
      where trial_pnl[:, i] = mean over 100 paths of per-path-PnL of unit BUY/SELL of instrument i
      with sign-handling (BUY uses +(payoff - ask), SELL uses +(bid - payoff))

We define decision variable as a SIGNED integer vector q_i with cap_i.
Sign of q_i picks the side: q_i > 0 -> BUY q_i units, q_i < 0 -> SELL |q_i| units.

Per-unit per-trial PnL:
   buy_unit_pnl_i  = (payoff_i  - ask_i)         column
   sell_unit_pnl_i = (bid_i     - payoff_i)      column = -(payoff_i - bid_i)
We track these as TWO columns per instrument and require q_buy >= 0, q_sell >= 0,
q_buy + q_sell <= cap_i, and we may have only one side active at the optimum
(though both is allowed; the bid-ask spread makes simultaneous buy+sell strictly negative-EV).

Memory: 1M x 12 (or 24 with two-sided) float32 = 48 / 96 MB. Easy.

Runtime budget: ~30 min total (10 min path gen, 20 min opt sweeps).
"""
import numpy as np
import time
import json
import os
from pathlib import Path

# -----------------------------------------------------------------------------
# Parameters (matched to cdf_100m.py)
# -----------------------------------------------------------------------------
S0 = 50.0
SIGMA = 2.51
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_2W_DAYS = 10
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W = T_3W_DAYS * STEPS_PER_DAY
N_2W = T_2W_DAYS * STEPS_PER_DAY

CONTRACT_MULTIPLIER = 3000

# Symbol order is fixed for this script
SYMBOLS = [
    "AC", "AC_50_P", "AC_50_C", "AC_35_P", "AC_40_P", "AC_45_P",
    "AC_60_C", "AC_50_P_2", "AC_50_C_2", "AC_50_CO", "AC_40_BP", "AC_45_KO",
]
N_SYM = len(SYMBOLS)

# (bid, ask, vol_cap)
QUOTES = {
    "AC":          (49.975, 50.025, 200),
    "AC_50_P":     (12.00,  12.05,  50),
    "AC_50_C":     (12.00,  12.05,  50),
    "AC_35_P":     ( 4.33,   4.35,  50),
    "AC_40_P":     ( 6.50,   6.55,  50),
    "AC_45_P":     ( 9.05,   9.10,  50),
    "AC_60_C":     ( 8.80,   8.85,  50),
    "AC_50_P_2":   ( 9.70,   9.75,  50),
    "AC_50_C_2":   ( 9.70,   9.75,  50),
    "AC_50_CO":    (22.20,  22.30,  50),
    "AC_40_BP":    ( 5.00,   5.10,  50),
    "AC_45_KO":    ( 0.15,   0.175, 500),
}
CAPS = np.array([QUOTES[s][2] for s in SYMBOLS], dtype=np.int64)

# Reference portfolios (in symbol order)
DROP_60C       = np.array([0,   0,   0,   0,   0,   0,   0,  50,  50, -50, -50, 500], dtype=np.int64)
OPTIMAL_7POS   = np.array([0,  50,  25,   0,   0,   0,   0,  50,  50, -50, -50, 500], dtype=np.int64)
GLOBAL_MAX_6P  = np.array([0,   0,   0,   0,   0,   0, -50,  50,  50, -50, -50, 500], dtype=np.int64)
PRIOR_FINAL_8P = np.array([5,  50,  25,   0,   0,   0,   0,  50,  50, -50, -50, 500], dtype=np.int64)

# -----------------------------------------------------------------------------
# Path simulation -> per-trial unit PnL matrix (MEAN over SIMS_PER_TRIAL paths)
# -----------------------------------------------------------------------------
def per_path_payoffs(S_T, S_2w, min_S):
    return {
        "AC":         S_T,
        "AC_50_P":    np.maximum(50 - S_T, 0.0),
        "AC_50_C":    np.maximum(S_T - 50, 0.0),
        "AC_35_P":    np.maximum(35 - S_T, 0.0),
        "AC_40_P":    np.maximum(40 - S_T, 0.0),
        "AC_45_P":    np.maximum(45 - S_T, 0.0),
        "AC_60_C":    np.maximum(S_T - 60, 0.0),
        "AC_50_P_2":  np.maximum(50 - S_2w, 0.0),
        "AC_50_C_2":  np.maximum(S_2w - 50, 0.0),
        "AC_50_CO":   np.where(S_2w >= 50, np.maximum(S_T - 50, 0.0), np.maximum(50 - S_T, 0.0)),
        "AC_40_BP":   np.where(S_T < 40, 10.0, 0.0),
        "AC_45_KO":   np.where(min_S > 35, np.maximum(45 - S_T, 0.0), 0.0),
    }


def gen_path_chunk(n_paths, rng):
    drift = -0.5 * SIGMA * SIGMA * DT
    vol = SIGMA * np.sqrt(DT)
    S = np.full(n_paths, S0, dtype=np.float64)
    min_S = S.copy()
    S_2w = None
    for k in range(N_3W):
        z = rng.standard_normal(n_paths)
        S = S * np.exp(drift + vol * z)
        np.minimum(min_S, S, out=min_S)
        if k + 1 == N_2W:
            S_2w = S.copy()
    return S, S_2w, min_S


def build_trial_pnl_matrix(total_paths=100_000_000, sims_per_trial=100,
                           chunk_size=5_000_000, cache_path=None, seed=42):
    """Returns (trial_buy_pnl, trial_sell_pnl), each shape (n_trials, N_SYM), float32.

    trial_buy_pnl[t, i]  = mean over 100 paths of (payoff_i - ask_i)
    trial_sell_pnl[t, i] = mean over 100 paths of (bid_i - payoff_i)

    These are PER-UNIT, PRE-MULTIPLIER. Multiply by integer position then by 3000.
    """
    if cache_path and os.path.exists(cache_path):
        print(f"[cache] loading trial PnL matrices from {cache_path}")
        d = np.load(cache_path)
        return d["buy"], d["sell"]

    n_trials = total_paths // sims_per_trial
    n_chunks = total_paths // chunk_size
    trials_per_chunk = chunk_size // sims_per_trial

    asks = np.array([QUOTES[s][1] for s in SYMBOLS], dtype=np.float64)
    bids = np.array([QUOTES[s][0] for s in SYMBOLS], dtype=np.float64)

    buy_mat  = np.empty((n_trials, N_SYM), dtype=np.float32)
    sell_mat = np.empty((n_trials, N_SYM), dtype=np.float32)

    rng = np.random.default_rng(seed=seed)
    t0 = time.time()
    for ci in range(n_chunks):
        tc = time.time()
        S_T, S_2w, min_S = gen_path_chunk(chunk_size, rng)
        payoffs_d = per_path_payoffs(S_T, S_2w, min_S)
        # Stack payoff array (chunk_size, N_SYM)
        payoff = np.empty((chunk_size, N_SYM), dtype=np.float64)
        for i, s in enumerate(SYMBOLS):
            payoff[:, i] = payoffs_d[s]
        # Per-path unit PnLs
        buy_pnl  = payoff - asks[None, :]      # (chunk, N)
        sell_pnl = bids[None, :] - payoff      # (chunk, N)
        # Reshape to (trials_per_chunk, sims_per_trial, N) then mean along axis=1
        buy_chunk_trials  = buy_pnl.reshape(trials_per_chunk, sims_per_trial, N_SYM).mean(axis=1)
        sell_chunk_trials = sell_pnl.reshape(trials_per_chunk, sims_per_trial, N_SYM).mean(axis=1)
        # Store
        a = ci * trials_per_chunk
        b = a + trials_per_chunk
        buy_mat[a:b]  = buy_chunk_trials.astype(np.float32)
        sell_mat[a:b] = sell_chunk_trials.astype(np.float32)
        elapsed = time.time() - tc
        total = time.time() - t0
        eta = (n_chunks - ci - 1) * elapsed
        print(f"  chunk {ci+1}/{n_chunks}: {elapsed:.1f}s (total {total:.1f}s, ETA {eta:.0f}s)")

    if cache_path:
        np.savez(cache_path, buy=buy_mat, sell=sell_mat)
        print(f"[cache] saved trial PnL matrices to {cache_path}")
    return buy_mat, sell_mat


# -----------------------------------------------------------------------------
# Stat helpers (operate on raw trial-PnL arrays in XIRECs (post x3000))
# -----------------------------------------------------------------------------
def _fast_q5_cvar5(s):
    """Use partition: split at 5% boundary then mean the bottom 5%."""
    n = s.shape[0]
    k = max(1, int(n * 0.05))
    # partition so that smallest k are at front (unsorted)
    part = np.partition(s, k - 1)
    bot = part[:k]
    return float(bot.max()), float(bot.mean())


def stats(trial_scores):
    """Stats from (n_trials,) score array."""
    s = trial_scores
    mean = float(s.mean())
    sd = float(s.std(ddof=1))
    median = float(np.median(s))
    q5, cvar5 = _fast_q5_cvar5(s)
    p_loss100k = float((s < -100_000).mean())
    p_pos = float((s > 0).mean())
    p_lt_neg500k = float((s < -500_000).mean())
    return dict(mean=mean, sd=sd, median=median, q5=q5, cvar5=cvar5,
                p_loss100k=p_loss100k, p_pos=p_pos, p_lt_neg500k=p_lt_neg500k)


def score_signed(q, buy_mat, sell_mat):
    """Apply signed integer position to trial PnL matrices.

    q[i] > 0 -> BUY q[i] units of i;  q[i] < 0 -> SELL |q[i]| units of i.
    Score = sum_i q[i]*buy_mat[t,i]    if q[i] > 0
            sum_i |q[i]|*sell_mat[t,i] if q[i] < 0
    """
    pos_q = np.maximum(q, 0).astype(np.float32)
    neg_q = np.maximum(-q, 0).astype(np.float32)
    s = (buy_mat @ pos_q) + (sell_mat @ neg_q)
    return s * CONTRACT_MULTIPLIER


# -----------------------------------------------------------------------------
# Per-instrument means (for greedy selection / sanity)
# -----------------------------------------------------------------------------
def per_instrument_edge(buy_mat, sell_mat):
    buy_edge = buy_mat.mean(axis=0).astype(np.float64)
    sell_edge = sell_mat.mean(axis=0).astype(np.float64)
    print("\nPer-instrument per-unit edge (buy / sell), pre-multiplier:")
    print(f"{'sym':<14} {'buy_edge':>10} {'sell_edge':>10} {'cap':>5}  best_side")
    for i, s in enumerate(SYMBOLS):
        side = "buy" if buy_edge[i] > sell_edge[i] else "sell"
        ed = max(buy_edge[i], sell_edge[i])
        print(f"{s:<14} {buy_edge[i]:>+10.4f} {sell_edge[i]:>+10.4f} {CAPS[i]:>5}  {side} ({ed:+.4f})")
    return buy_edge, sell_edge


# -----------------------------------------------------------------------------
# Optimization: simulated annealing on signed integer cube
# -----------------------------------------------------------------------------
def simulated_annealing(buy_mat, sell_mat, objective_fn, q0=None,
                        n_iter=4000, T0=1.0, T_end=0.001, step_max=20,
                        seed=0, verbose=False):
    """Minimize -objective_fn(q). objective is a (q -> scalar utility) function."""
    rng = np.random.default_rng(seed)
    if q0 is None:
        q = np.zeros(N_SYM, dtype=np.int64)
    else:
        q = q0.copy()
    best_q = q.copy()
    cur_u = objective_fn(q)
    best_u = cur_u
    log_T0 = np.log(T0)
    log_TE = np.log(T_end)
    for it in range(n_iter):
        T = np.exp(log_T0 + (log_TE - log_T0) * it / max(1, n_iter - 1))
        # Pick a coord and propose delta
        i = rng.integers(N_SYM)
        # Step magnitude shrinks with T
        sm = max(1, int(round(step_max * (T / T0) + 1)))
        delta = rng.integers(-sm, sm + 1)
        if delta == 0:
            delta = 1 if rng.random() < 0.5 else -1
        new_qi = q[i] + delta
        if abs(new_qi) > CAPS[i]:
            new_qi = int(np.sign(new_qi)) * CAPS[i]
            if new_qi == q[i]:
                continue
        old = q[i]
        q[i] = new_qi
        new_u = objective_fn(q)
        accept = (new_u > cur_u) or (rng.random() < np.exp((new_u - cur_u) / max(T, 1e-9)))
        if accept:
            cur_u = new_u
            if new_u > best_u:
                best_u = new_u
                best_q = q.copy()
                if verbose and it % 200 == 0:
                    print(f"   it={it} T={T:.4f} BEST u={best_u:.0f} q={best_q.tolist()}")
        else:
            q[i] = old
    return best_q, best_u


def coord_polish(buy_mat, sell_mat, objective_fn, q0, max_passes=4, step_set=(1, 5, 25, 50)):
    """Greedy coordinate ascent: try +-step at each coord; keep if improves."""
    q = q0.copy().astype(np.int64)
    cur_u = objective_fn(q)
    for p in range(max_passes):
        improved = False
        for i in range(N_SYM):
            for step in step_set:
                for sgn in (+1, -1):
                    new_qi = q[i] + sgn * step
                    if abs(new_qi) > CAPS[i]:
                        continue
                    old = q[i]
                    q[i] = new_qi
                    new_u = objective_fn(q)
                    if new_u > cur_u + 1e-9:
                        cur_u = new_u
                        improved = True
                    else:
                        q[i] = old
        if not improved:
            break
    return q, cur_u


# -----------------------------------------------------------------------------
# Common objectives
# -----------------------------------------------------------------------------
def make_obj_mean(buy_mat, sell_mat):
    def f(q):
        s = score_signed(q, buy_mat, sell_mat)
        return float(s.mean())
    return f


def make_obj_mean_subject_cvar(buy_mat, sell_mat, cvar_min):
    """max mean; penalize CVaR violations heavily."""
    def f(q):
        s = score_signed(q, buy_mat, sell_mat)
        mean = float(s.mean())
        _, cvar = _fast_q5_cvar5(s)
        violation = max(0.0, cvar_min - cvar)
        return mean - 100.0 * violation
    return f


def make_obj_mean_subject_sd(buy_mat, sell_mat, sd_max):
    def f(q):
        s = score_signed(q, buy_mat, sell_mat)
        mean = float(s.mean())
        sd = float(s.std(ddof=1))
        violation = max(0.0, sd - sd_max)
        return mean - 50.0 * violation
    return f


def make_obj_mean_subject_p_loss(buy_mat, sell_mat, p_max, threshold=-100_000):
    def f(q):
        s = score_signed(q, buy_mat, sell_mat)
        mean = float(s.mean())
        p = float((s < threshold).mean())
        violation = max(0.0, p - p_max)
        return mean - 5_000_000.0 * violation
    return f


def make_obj_robust(buy_mat, sell_mat, lam):
    """U = E[score] - lam * max(0, -CVaR-5%)."""
    def f(q):
        s = score_signed(q, buy_mat, sell_mat)
        mean = float(s.mean())
        _, cvar = _fast_q5_cvar5(s)
        return mean - lam * max(0.0, -cvar)
    return f


def make_obj_pareto(buy_mat, sell_mat, alpha):
    """Pareto scalar:  alpha * mean + (1-alpha) * cvar  (both maximized)."""
    def f(q):
        s = score_signed(q, buy_mat, sell_mat)
        mean = float(s.mean())
        _, cvar = _fast_q5_cvar5(s)
        return alpha * mean + (1 - alpha) * cvar
    return f


# -----------------------------------------------------------------------------
# Helpers for reporting
# -----------------------------------------------------------------------------
def fmt_q(q):
    parts = []
    for i, v in enumerate(q):
        if v != 0:
            parts.append(f"{SYMBOLS[i]}={v:+d}")
    return ", ".join(parts) if parts else "(empty)"


def report_portfolio(name, q, buy_mat, sell_mat):
    s = score_signed(q, buy_mat, sell_mat)
    st = stats(s)
    print(f"\n{name}")
    print(f"  q: {fmt_q(q)}")
    print(f"  Mean       = ${st['mean']:>+15,.0f}")
    print(f"  Median     = ${st['median']:>+15,.0f}")
    print(f"  SD         = ${st['sd']:>+15,.0f}")
    print(f"  q5         = ${st['q5']:>+15,.0f}")
    print(f"  CVaR-5%    = ${st['cvar5']:>+15,.0f}")
    print(f"  P>0        = {st['p_pos']*100:6.2f}%")
    print(f"  P<-100k    = {st['p_loss100k']*100:6.2f}%")
    print(f"  P<-500k    = {st['p_lt_neg500k']*100:6.2f}%")
    return st


# -----------------------------------------------------------------------------
# Main pipeline
# -----------------------------------------------------------------------------
def main():
    out_dir = Path("trader-logic/round-4/manual")
    cache_path = str(out_dir / "_trial_pnl_cache.npz")

    print("=" * 80)
    print("R4 Manual constrained portfolio optimization")
    print("=" * 80)

    # Step 1: Build (or load) per-trial PnL matrix
    # 20M paths -> 200K trials of 100 paths each. CVaR-5% has 10K-sample tail (~1% rel SE).
    # Sized for budget given concurrent jobs on the box.
    import sys
    total_paths = int(sys.argv[1]) if len(sys.argv) > 1 else 20_000_000
    chunk = min(2_000_000, total_paths)
    buy_mat, sell_mat = build_trial_pnl_matrix(
        total_paths=total_paths, sims_per_trial=100, chunk_size=chunk,
        cache_path=cache_path, seed=42,
    )
    n_trials = buy_mat.shape[0]
    print(f"\ntrial PnL matrix: {n_trials:,} trials x {N_SYM} symbols (float32)")

    # Step 2: per-instrument edges
    buy_edge, sell_edge = per_instrument_edge(buy_mat, sell_mat)

    results = {}

    # -----------------------------------------------------------------------
    # Step 3: verify reference portfolios
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("REFERENCE PORTFOLIO VERIFICATION")
    print("=" * 80)
    ref = {
        "DROP_60C":     DROP_60C,
        "OPTIMAL_7POS": OPTIMAL_7POS,
        "GLOBAL_MAX":   GLOBAL_MAX_6P,
        "PRIOR_FINAL":  PRIOR_FINAL_8P,
    }
    ref_stats = {}
    for name, q in ref.items():
        ref_stats[name] = report_portfolio(name, q, buy_mat, sell_mat)
        ref_stats[name]["q"] = q.tolist()
    results["reference_portfolios"] = ref_stats

    # -----------------------------------------------------------------------
    # Step 4: unconstrained max E[score]
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("UNCONSTRAINED MAX E[SCORE]")
    print("=" * 80)
    obj_mean = make_obj_mean(buy_mat, sell_mat)
    # closed-form: pick best side per instrument, scaled to cap, but only if edge > 0
    q_uc = np.zeros(N_SYM, dtype=np.int64)
    for i in range(N_SYM):
        if buy_edge[i] > 0 and buy_edge[i] >= sell_edge[i]:
            q_uc[i] = int(CAPS[i])
        elif sell_edge[i] > 0:
            q_uc[i] = -int(CAPS[i])
        # else 0
    print(f"closed-form: {fmt_q(q_uc)}")
    report_portfolio("UNCONSTRAINED (analytic)", q_uc, buy_mat, sell_mat)
    # SA polish to verify (objective is linear in q so closed-form should win)
    q_sa, u_sa = simulated_annealing(buy_mat, sell_mat, obj_mean, q0=q_uc.copy(),
                                      n_iter=2000, T0=10000.0, T_end=10.0, seed=1)
    q_sa, _ = coord_polish(buy_mat, sell_mat, obj_mean, q_sa)
    print("SA polish:")
    report_portfolio("UNCONSTRAINED (SA)", q_sa, buy_mat, sell_mat)
    # whichever is better
    if obj_mean(q_sa) > obj_mean(q_uc):
        q_unconstrained = q_sa
    else:
        q_unconstrained = q_uc
    results["unconstrained"] = {
        "q": q_unconstrained.tolist(), **stats(score_signed(q_unconstrained, buy_mat, sell_mat))
    }

    # -----------------------------------------------------------------------
    # Step 5: CVaR-constrained sweep
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("CVAR-5% CONSTRAINED SWEEP   max E[score] s.t. CVaR-5% >= -X")
    print("=" * 80)
    cvar_X_grid = [1_000_000, 750_000, 500_000, 400_000, 350_000, 300_000,
                   250_000, 200_000, 150_000, 100_000, 50_000]
    cvar_results = {}
    # Warm start from DROP_60C (it's in the feasible region for most X values)
    q_warm = DROP_60C.copy()
    for X in cvar_X_grid:
        cvar_min = -X
        obj = make_obj_mean_subject_cvar(buy_mat, sell_mat, cvar_min)
        q_sa, _ = simulated_annealing(buy_mat, sell_mat, obj, q0=q_warm.copy(),
                                       n_iter=3000, T0=200000.0, T_end=10.0, seed=X % 10000)
        q_sa, _ = coord_polish(buy_mat, sell_mat, obj, q_sa)
        st = stats(score_signed(q_sa, buy_mat, sell_mat))
        feasible = st["cvar5"] >= cvar_min - 1e-3
        print(f"  X={X:>+10,d} | mean=${st['mean']:>+12,.0f} CVaR=${st['cvar5']:>+12,.0f} SD=${st['sd']:>+11,.0f} feas={feasible}  q={fmt_q(q_sa)}")
        cvar_results[X] = {"q": q_sa.tolist(), **st, "feasible": feasible}
        if feasible:
            q_warm = q_sa
    results["cvar_constrained"] = cvar_results

    # -----------------------------------------------------------------------
    # Step 6: SD-constrained sweep
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SD CONSTRAINED SWEEP   max E[score] s.t. SD <= Y")
    print("=" * 80)
    sd_Y_grid = [1_000_000, 750_000, 500_000, 350_000, 250_000, 200_000, 150_000, 100_000]
    sd_results = {}
    q_warm = DROP_60C.copy()
    for Y in sd_Y_grid:
        obj = make_obj_mean_subject_sd(buy_mat, sell_mat, Y)
        q_sa, _ = simulated_annealing(buy_mat, sell_mat, obj, q0=q_warm.copy(),
                                       n_iter=3000, T0=100000.0, T_end=10.0, seed=Y % 10000)
        q_sa, _ = coord_polish(buy_mat, sell_mat, obj, q_sa)
        st = stats(score_signed(q_sa, buy_mat, sell_mat))
        feasible = st["sd"] <= Y + 1
        print(f"  Y={Y:>+10,d} | mean=${st['mean']:>+12,.0f} SD=${st['sd']:>+11,.0f} CVaR=${st['cvar5']:>+12,.0f} feas={feasible}  q={fmt_q(q_sa)}")
        sd_results[Y] = {"q": q_sa.tolist(), **st, "feasible": feasible}
        if feasible:
            q_warm = q_sa
    results["sd_constrained"] = sd_results

    # -----------------------------------------------------------------------
    # Step 7: P(loss < -100k) constrained sweep
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("P(score < -100k) CONSTRAINED SWEEP   max E[score] s.t. P(loss>100k) <= p")
    print("=" * 80)
    p_grid = [0.25, 0.20, 0.15, 0.10, 0.05, 0.02, 0.01]
    p_results = {}
    q_warm = DROP_60C.copy()
    for p_max in p_grid:
        obj = make_obj_mean_subject_p_loss(buy_mat, sell_mat, p_max)
        q_sa, _ = simulated_annealing(buy_mat, sell_mat, obj, q0=q_warm.copy(),
                                       n_iter=3000, T0=100000.0, T_end=10.0, seed=int(p_max*10000))
        q_sa, _ = coord_polish(buy_mat, sell_mat, obj, q_sa)
        st = stats(score_signed(q_sa, buy_mat, sell_mat))
        feasible = st["p_loss100k"] <= p_max + 1e-4
        print(f"  p<={p_max:.3f} | mean=${st['mean']:>+12,.0f} P<-100k={st['p_loss100k']*100:5.2f}% CVaR=${st['cvar5']:>+12,.0f} feas={feasible}  q={fmt_q(q_sa)}")
        p_results[p_max] = {"q": q_sa.tolist(), **st, "feasible": feasible}
        if feasible:
            q_warm = q_sa
    results["p_loss_constrained"] = p_results

    # -----------------------------------------------------------------------
    # Step 8: (E[score], CVaR-5%) Pareto frontier (~50 points via lambda sweep)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("PARETO FRONTIER (E[score] vs CVaR-5%) -- ~50 points")
    print("=" * 80)
    # Mix alpha * mean + (1-alpha) * cvar over alpha grid
    alpha_grid = np.concatenate([
        np.linspace(0.0, 0.5, 20),
        np.linspace(0.5, 0.95, 20),
        np.linspace(0.95, 1.0, 11),
    ])
    pareto_pts = []
    seen_q = set()
    q_warm = DROP_60C.copy()
    for alpha in alpha_grid:
        obj = make_obj_pareto(buy_mat, sell_mat, alpha)
        q_sa, _ = simulated_annealing(buy_mat, sell_mat, obj, q0=q_warm.copy(),
                                       n_iter=2500, T0=100000.0, T_end=10.0, seed=int(alpha*1e6))
        q_sa, _ = coord_polish(buy_mat, sell_mat, obj, q_sa)
        st = stats(score_signed(q_sa, buy_mat, sell_mat))
        key = tuple(q_sa.tolist())
        if key in seen_q:
            continue
        seen_q.add(key)
        pareto_pts.append({"alpha": float(alpha), "q": list(key), **st})
        q_warm = q_sa
    # Also include reference portfolios on the frontier diagram
    for name, q in ref.items():
        st = stats(score_signed(q, buy_mat, sell_mat))
        pareto_pts.append({"alpha": -1.0, "q": q.tolist(), "label": name, **st})

    # Print top points
    pareto_pts.sort(key=lambda d: d["mean"])
    print(f"\n{'mean':>14} {'cvar5':>14} {'sd':>13} {'p_pos':>7} {'q':<60}")
    for p in pareto_pts:
        lbl = f" [{p.get('label','')}]" if p.get("label") else ""
        print(f"  ${p['mean']:>+12,.0f} ${p['cvar5']:>+12,.0f} ${p['sd']:>+11,.0f} {p['p_pos']*100:5.1f}% {fmt_q(np.array(p['q'])):<60}{lbl}")
    results["pareto_frontier"] = pareto_pts

    # -----------------------------------------------------------------------
    # Step 9: robust utility   U = E - lam * max(0, -CVaR)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("ROBUST UTILITY  U = E[score] - lam * max(0, -CVaR-5%)")
    print("=" * 80)
    lam_grid = [0.1, 0.5, 1.0, 2.0, 5.0]
    robust_results = {}
    for lam in lam_grid:
        obj = make_obj_robust(buy_mat, sell_mat, lam)
        q_sa, _ = simulated_annealing(buy_mat, sell_mat, obj, q0=DROP_60C.copy(),
                                       n_iter=3500, T0=100000.0, T_end=10.0, seed=int(lam*1e5))
        q_sa, _ = coord_polish(buy_mat, sell_mat, obj, q_sa)
        st = stats(score_signed(q_sa, buy_mat, sell_mat))
        u = obj(q_sa)
        print(f"  lam={lam:5.2f} | U=${u:>+12,.0f}  mean=${st['mean']:>+12,.0f} CVaR=${st['cvar5']:>+12,.0f}  q={fmt_q(q_sa)}")
        robust_results[lam] = {"q": q_sa.tolist(), "U": u, **st}
    results["robust_utility"] = robust_results

    # -----------------------------------------------------------------------
    # Step 10: Kelly fractional analysis
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("KELLY FRACTIONAL ANALYSIS  max E[log(W + k*score)] for W=$1M")
    print("=" * 80)
    W = 1_000_000.0
    portfolios = [("DROP_60C", DROP_60C), ("OPTIMAL_7POS", OPTIMAL_7POS),
                  ("GLOBAL_MAX", GLOBAL_MAX_6P), ("PRIOR_FINAL", PRIOR_FINAL_8P)]
    # Add the unconstrained
    portfolios.append(("UNCONSTRAINED", q_unconstrained))
    kelly_results = {}
    for name, q in portfolios:
        s = score_signed(q, buy_mat, sell_mat)
        # avoid log(<=0): max k = (W - eps) / max(-s)
        worst = float(s.min())
        k_max = 0.999 * W / max(-worst, 1e-3)
        # Search k in (0, min(k_max, 1)) on a log grid
        ks = np.unique(np.concatenate([
            np.linspace(0.0, min(k_max, 1.0), 41),
            np.linspace(0.0, min(k_max, 0.5), 41),
            np.linspace(0.0, min(k_max, 0.1), 41),
        ]))
        best_k, best_logu = 0.0, -np.inf
        for k in ks:
            wealth = W + k * s
            if wealth.min() <= 0:
                continue
            logu = float(np.log(wealth).mean())
            if logu > best_logu:
                best_logu = logu
                best_k = float(k)
        kelly_results[name] = {"k_opt": best_k, "log_util": best_logu, "k_max_safe": float(min(k_max, 1.0))}
        print(f"  {name:<14}  k*={best_k:.4f}  E[logW']={best_logu:.6f}  (k_max_safe={min(k_max,1.0):.4f})")
    results["kelly"] = kelly_results

    # -----------------------------------------------------------------------
    # Step 11: Worst-case path analysis on OPTIMAL_7POS
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("WORST-CASE PATH ANALYSIS for OPTIMAL_7POS")
    print("=" * 80)
    s_opt = score_signed(OPTIMAL_7POS, buy_mat, sell_mat)
    # Find worst 100 trials
    worst_idx = np.argsort(s_opt)[:100]
    # We don't have the underlying path stats (S_T/S_2w/min_S) cached; reconstruct sketch
    # by running a fresh 100-path bundle for those trial indices.
    # Approach: regenerate trials and store S_T/S_2w/min_S means/aggregates.
    print("Regenerating trial-level S_T / S_2w / min_S signatures (fresh seed)...")
    # We need same seed sequence. Walk the same chunked path we did to save trial-level S_T/S_2w/min_S means.
    rng = np.random.default_rng(seed=42)
    chunk_size = chunk
    sims_per_trial = 100
    trials_per_chunk = chunk_size // sims_per_trial
    sT_mean = np.empty(n_trials, dtype=np.float32)
    s2w_mean = np.empty(n_trials, dtype=np.float32)
    minS_mean = np.empty(n_trials, dtype=np.float32)
    n_chunks_total = n_trials // trials_per_chunk
    for ci in range(n_chunks_total):
        S_T, S_2w, min_S = gen_path_chunk(chunk_size, rng)
        a = ci * trials_per_chunk
        b = a + trials_per_chunk
        sT_mean[a:b]   = S_T.reshape(trials_per_chunk, sims_per_trial).mean(axis=1).astype(np.float32)
        s2w_mean[a:b]  = S_2w.reshape(trials_per_chunk, sims_per_trial).mean(axis=1).astype(np.float32)
        minS_mean[a:b] = min_S.reshape(trials_per_chunk, sims_per_trial).mean(axis=1).astype(np.float32)
    print("Worst 100 trials for OPTIMAL_7POS:")
    print(f"  mean trial score = ${s_opt[worst_idx].mean():>+12,.0f}  (overall mean ${s_opt.mean():+,.0f})")
    print(f"  S_T:    mean={sT_mean[worst_idx].mean():.2f}  q5={np.percentile(sT_mean[worst_idx],5):.2f}  q95={np.percentile(sT_mean[worst_idx],95):.2f}  (overall mean {sT_mean.mean():.2f})")
    print(f"  S_2w:   mean={s2w_mean[worst_idx].mean():.2f}  q5={np.percentile(s2w_mean[worst_idx],5):.2f}  q95={np.percentile(s2w_mean[worst_idx],95):.2f}  (overall mean {s2w_mean.mean():.2f})")
    print(f"  min_S:  mean={minS_mean[worst_idx].mean():.2f}  q5={np.percentile(minS_mean[worst_idx],5):.2f}  q95={np.percentile(minS_mean[worst_idx],95):.2f}  (overall mean {minS_mean.mean():.2f})")
    # Pattern: do they all share min_S < 35 (KO knock-out) AND S_T > 50 (puts OTM)?
    n_ko    = int((minS_mean[worst_idx] < 35).sum())
    n_st_hi = int((sT_mean[worst_idx]   > 50).sum())
    n_st_lo = int((sT_mean[worst_idx]   < 50).sum())
    n_s2w_lo= int((s2w_mean[worst_idx]  < 50).sum())
    print(f"  trials with mean min_S < 35:  {n_ko} / 100   (KO-barrier-breach indicator)")
    print(f"  trials with mean S_T  > 50:   {n_st_hi} / 100   (puts OTM)")
    print(f"  trials with mean S_T  < 50:   {n_st_lo} / 100   (calls OTM)")
    print(f"  trials with mean S_2w < 50:   {n_s2w_lo} / 100   (chooser->put indicator)")
    results["worst_paths_opt7"] = {
        "worst_mean": float(s_opt[worst_idx].mean()),
        "ST_q5": float(np.percentile(sT_mean[worst_idx], 5)),
        "ST_q95": float(np.percentile(sT_mean[worst_idx], 95)),
        "S2w_q5": float(np.percentile(s2w_mean[worst_idx], 5)),
        "S2w_q95": float(np.percentile(s2w_mean[worst_idx], 95)),
        "minS_q5": float(np.percentile(minS_mean[worst_idx], 5)),
        "minS_q95": float(np.percentile(minS_mean[worst_idx], 95)),
        "n_ko_barrier_breach": n_ko,
        "n_ST_above_50": n_st_hi,
        "n_ST_below_50": n_st_lo,
        "n_S2w_below_50": n_s2w_lo,
    }

    # -----------------------------------------------------------------------
    # Step 12: Verify OPTIMAL_7POS Pareto-optimality at ($158k, -$360k)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("VERIFY OPTIMAL_7POS PARETO-OPTIMAL at ~($158k, -$360k)")
    print("=" * 80)
    st_opt = stats(score_signed(OPTIMAL_7POS, buy_mat, sell_mat))
    print(f"  OPTIMAL_7POS: mean=${st_opt['mean']:+,.0f}  CVaR-5%=${st_opt['cvar5']:+,.0f}")
    # Strict-improvement search: we want q with mean >= st_opt.mean AND cvar5 >= st_opt.cvar5,
    # at least one strict.
    target_mean = st_opt["mean"]
    target_cvar = st_opt["cvar5"]

    def obj_dominate(q):
        s = score_signed(q, buy_mat, sell_mat)
        m = float(s.mean()); _, cv = _fast_q5_cvar5(s)
        # Penalize falling below either coordinate.
        slack_m = m - target_mean
        slack_c = cv - target_cvar
        bad_m = max(0.0, -slack_m)
        bad_c = max(0.0, -slack_c)
        # Reward strict improvement (sum of slacks above 0)
        good = slack_m + slack_c
        return good - 50.0 * (bad_m + bad_c)

    best_dom_q = None
    best_dom_score = -np.inf
    # Multi-start SA
    starts = [OPTIMAL_7POS.copy(), DROP_60C.copy(),
              OPTIMAL_7POS + np.array([0,0,25,0,0,0,0,0,0,0,0,0]),
              OPTIMAL_7POS + np.array([0,0,0,0,0,25,0,0,0,0,0,0]),
              OPTIMAL_7POS + np.array([10,0,0,0,0,0,0,0,0,0,0,0]),
              ]
    for si, q0 in enumerate(starts):
        q_test, u = simulated_annealing(buy_mat, sell_mat, obj_dominate, q0=q0.copy(),
                                         n_iter=4000, T0=10000.0, T_end=1.0, seed=si)
        q_test, u = coord_polish(buy_mat, sell_mat, obj_dominate, q_test)
        if u > best_dom_score:
            best_dom_score = u
            best_dom_q = q_test
    st_dom = stats(score_signed(best_dom_q, buy_mat, sell_mat))
    strict_dom = (st_dom["mean"] > target_mean + 100) and (st_dom["cvar5"] >= target_cvar - 100) or \
                 (st_dom["cvar5"] > target_cvar + 100) and (st_dom["mean"] >= target_mean - 100)
    print(f"  best dominator candidate: mean=${st_dom['mean']:+,.0f}  CVaR=${st_dom['cvar5']:+,.0f}  q={fmt_q(best_dom_q)}")
    print(f"  strict dominance? {strict_dom}")
    if (st_dom["mean"] > target_mean) and (st_dom["cvar5"] > target_cvar):
        print(f"  *** OPTIMAL_7POS IS NOT PARETO-OPTIMAL at this point ***")
    else:
        print(f"  OPTIMAL_7POS is Pareto-optimal (no strict dominator found)")
    results["pareto_check_optimal7"] = {
        "OPTIMAL_7POS_mean": target_mean, "OPTIMAL_7POS_cvar5": target_cvar,
        "best_dominator": {"q": best_dom_q.tolist(), **st_dom},
        "strict_dominance": bool(st_dom["mean"] > target_mean and st_dom["cvar5"] > target_cvar),
    }

    # Save
    with open(out_dir / "constrained_opt_results.json", "w") as f:
        json.dump(results, f, indent=2, default=lambda o: float(o) if hasattr(o, "item") else str(o))
    print(f"\n[saved] constrained_opt_results.json")
    print(f"\nTotal runtime: {time.time():.0f}s wall-clock")


if __name__ == "__main__":
    main()
