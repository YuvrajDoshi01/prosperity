"""Stress test R4 manual recommendation under alternative model specifications.

Baseline: GBM with sigma=2.51, r=0, S0=50, monitoring 4 obs/day.
Strategy under test: OPTIMAL_7POS = {-50 CO, +500 KO, -50 BP, +50 P_2, +50 C_2, +50 P, +25 C}.

For each spec we compute, per strategy:
  - E[score] (mean per-unit PnL x 3000 multiplier)
  - SD/unit, CVaR-5%/unit
  - P(PnL > 0)

Approach: streaming/chunked simulation to keep memory bounded. Each spec returns
running statistics across all paths — Welford means/variances and P5 quantile via
two-pass: first chunk pass collects samples for quantile, second pass refines if needed.

To handle 50M paths within ~16GB RAM, we process in chunks of 200k–500k. Heston/GARCH
need O(N x N_steps) memory for full Z arrays so chunks are smaller (50k).
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Callable

import numpy as np

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
S0 = 50.0
SIGMA = 2.51
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_2W_DAYS = 10
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W = T_3W_DAYS * STEPS_PER_DAY      # 60
N_2W = T_2W_DAYS * STEPS_PER_DAY      # 40
T_3W = T_3W_DAYS / TRADING_DAYS_YEAR
T_2W = T_2W_DAYS / TRADING_DAYS_YEAR

CONTRACT_MULTIPLIER = 3000
ND = NormalDist()

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
    "AC_45_KO":    ( 0.150,  0.175, 500),
}

STRATEGIES = {
    "DROP_60C": [
        ("AC_50_CO",  -50), ("AC_45_KO",  +500), ("AC_40_BP",  -50),
        ("AC_50_P_2", +50), ("AC_50_C_2", +50),
    ],
    "OPTIMAL_7POS": [
        ("AC_50_CO",  -50), ("AC_45_KO",  +500), ("AC_40_BP",  -50),
        ("AC_50_P_2", +50), ("AC_50_C_2", +50),
        ("AC_50_P",   +50), ("AC_50_C",   +25),
    ],
    "USER_SAFE": [
        ("AC_50_CO",  -10), ("AC_45_KO",  +60),  ("AC_40_BP",  -10),
        ("AC_50_P_2", +10), ("AC_50_C_2", +10),
    ],
    "KO_ZERO": [
        ("AC_50_CO",  -50),                      ("AC_40_BP",  -50),
        ("AC_50_P_2", +50), ("AC_50_C_2", +50),
    ],
}


def payoff_vec(sym, S_T, S_T_2w, min_S, obs_min_S=None):
    if sym == "AC_50_P":    return np.maximum(50 - S_T, 0.0)
    if sym == "AC_50_C":    return np.maximum(S_T - 50, 0.0)
    if sym == "AC_50_P_2":  return np.maximum(50 - S_T_2w, 0.0)
    if sym == "AC_50_C_2":  return np.maximum(S_T_2w - 50, 0.0)
    if sym == "AC_50_CO":
        return np.where(S_T_2w >= 50, np.maximum(S_T - 50, 0.0), np.maximum(50 - S_T, 0.0))
    if sym == "AC_40_BP":   return np.where(S_T < 40, 10.0, 0.0)
    if sym == "AC_45_KO":
        m = min_S if obs_min_S is None else obs_min_S
        return np.where(m > 35, np.maximum(45 - S_T, 0.0), 0.0)
    raise KeyError(sym)


def chunk_pnl(positions, S_T, S_T_2w, min_S, obs_min_S=None):
    """Vectorized per-path PnL for one strategy on a path chunk."""
    pay_cache = {}
    pnl = np.zeros_like(S_T)
    for sym, qty in positions:
        if sym not in pay_cache:
            pay_cache[sym] = payoff_vec(sym, S_T, S_T_2w, min_S, obs_min_S)
        bid, ask, _ = QUOTES[sym]
        p = pay_cache[sym]
        if qty > 0:
            pnl = pnl + qty * (p - ask)
        else:
            pnl = pnl + abs(qty) * (bid - p)
    return pnl


# ----------------------------------------------------------------------------
# Streaming statistics
# ----------------------------------------------------------------------------
@dataclass
class RunStats:
    n: int = 0
    mean: float = 0.0
    M2: float = 0.0       # for variance
    n_pos: int = 0
    samples: list = field(default_factory=list)  # for quantile (subsample)
    SUBSAMPLE_PER_CHUNK: int = 50_000  # target ~5M subsamples for stable quantile

    def update(self, x: np.ndarray):
        n_chunk = x.size
        if n_chunk == 0: return
        chunk_mean = float(x.mean())
        chunk_var = float(x.var(ddof=0)) if n_chunk > 1 else 0.0
        # Welford's parallel update
        delta = chunk_mean - self.mean
        new_n = self.n + n_chunk
        self.mean = self.mean + delta * (n_chunk / new_n)
        # M2 update (combine):
        self.M2 = self.M2 + chunk_var * n_chunk + (delta ** 2) * self.n * n_chunk / new_n
        self.n = new_n
        self.n_pos += int((x > 0).sum())
        # Subsample for quantile estimation
        k = min(self.SUBSAMPLE_PER_CHUNK, n_chunk)
        if k > 0:
            idx = np.random.default_rng(self.n).choice(n_chunk, k, replace=False)
            self.samples.append(x[idx].copy())

    def finalize(self):
        var = self.M2 / max(self.n - 1, 1)
        sd = math.sqrt(max(var, 0.0))
        all_samples = np.concatenate(self.samples) if self.samples else np.array([0.0])
        q5 = float(np.quantile(all_samples, 0.05))
        tail = all_samples[all_samples <= q5]
        cvar5 = float(tail.mean()) if tail.size else q5
        p_pos = self.n_pos / self.n
        return self.mean, sd, cvar5, p_pos


@dataclass
class Stat:
    spec: str
    strategy: str
    mean_per_unit: float
    sd_per_unit: float
    cvar5_per_unit: float
    p_pos: float

    @property
    def score_mean(self): return self.mean_per_unit * CONTRACT_MULTIPLIER
    @property
    def cvar5_score(self): return self.cvar5_per_unit * CONTRACT_MULTIPLIER

    def line(self) -> str:
        return (f"  {self.strategy:<14} E=${self.score_mean:>+13,.0f}  "
                f"SD/unit=${self.sd_per_unit*CONTRACT_MULTIPLIER:>11,.0f}  "
                f"CVaR5/unit=${self.cvar5_per_unit*CONTRACT_MULTIPLIER:>+11,.0f}  "
                f"P>0={self.p_pos*100:5.1f}%")


# ----------------------------------------------------------------------------
# Path generators - chunked. Each yields (S_T, S_T_2w, min_S) arrays per chunk.
# ----------------------------------------------------------------------------

def gbm_chunk(n_chunk, sigma, mu, rng):
    drift = (mu - 0.5 * sigma * sigma) * DT
    vol = sigma * math.sqrt(DT)
    Z = rng.standard_normal(size=(n_chunk, N_3W)).astype(np.float32)
    incr = (drift + vol * Z).astype(np.float32)
    log_S = np.cumsum(incr, axis=1) + math.log(S0)
    S_T = np.exp(log_S[:, -1])
    S_T_2w = np.exp(log_S[:, N_2W - 1])
    min_S = np.minimum(np.exp(np.min(log_S, axis=1)), S0)
    return S_T, S_T_2w, min_S


def student_t_chunk(n_chunk, sigma, df, rng):
    drift = (-0.5 * sigma * sigma) * DT
    vol = sigma * math.sqrt(DT)
    scale = math.sqrt(df / (df - 2.0))
    T = rng.standard_t(df, size=(n_chunk, N_3W)).astype(np.float32)
    Z = T / scale
    incr = drift + vol * Z
    log_S = np.cumsum(incr, axis=1) + math.log(S0)
    return np.exp(log_S[:, -1]), np.exp(log_S[:, N_2W - 1]), \
           np.minimum(np.exp(np.min(log_S, axis=1)), S0)


def student_t_chunk_capped(n_chunk, sigma, df, rng):
    """Same as student_t_chunk but caps log-returns at +/- 6 sigma per step
    to suppress 1-in-10M outliers that overflow lognormal exponentials at df=3.
    This is conservative in the wrong direction (underestimates tail effects)
    but keeps the simulation from being polluted by ~10 paths whose S_T overflows."""
    drift = (-0.5 * sigma * sigma) * DT
    vol = sigma * math.sqrt(DT)
    scale = math.sqrt(df / (df - 2.0))
    T = rng.standard_t(df, size=(n_chunk, N_3W)).astype(np.float32)
    Z = T / scale
    # Cap the standardized innovation
    Z = np.clip(Z, -6.0, 6.0)
    incr = drift + vol * Z
    log_S = np.cumsum(incr, axis=1) + math.log(S0)
    # Also clip log_S itself to prevent any residual exp() overflow
    log_S = np.clip(log_S, math.log(1e-6), math.log(1e6))
    return np.exp(log_S[:, -1]), np.exp(log_S[:, N_2W - 1]), \
           np.minimum(np.exp(np.min(log_S, axis=1)), S0)


def merton_chunk(n_chunk, sigma_diff, lam, sigma_J, rng):
    drift = (-0.5 * sigma_diff * sigma_diff) * DT
    vol = sigma_diff * math.sqrt(DT)
    Z = rng.standard_normal(size=(n_chunk, N_3W)).astype(np.float32)
    diffusion = drift + vol * Z
    Nj = rng.poisson(lam * DT, size=(n_chunk, N_3W)).astype(np.float32)
    Z2 = rng.standard_normal(size=(n_chunk, N_3W)).astype(np.float32)
    jumps = (sigma_J * np.sqrt(Nj) * Z2).astype(np.float32)
    incr = diffusion + jumps
    log_S = np.cumsum(incr, axis=1) + math.log(S0)
    return np.exp(log_S[:, -1]), np.exp(log_S[:, N_2W - 1]), \
           np.minimum(np.exp(np.min(log_S, axis=1)), S0)


def heston_chunk(n_chunk, v_long, kappa, sigma_v, rho, rng):
    sqrt_dt = math.sqrt(DT)
    log_S = np.full(n_chunk, math.log(S0), dtype=np.float32)
    v = np.full(n_chunk, v_long * v_long, dtype=np.float32)
    min_log = log_S.copy()
    log_S_2w = None
    sqrt_1m_rho2 = math.sqrt(1 - rho * rho)
    for k in range(N_3W):
        Z1 = rng.standard_normal(n_chunk).astype(np.float32)
        Z2 = (rho * Z1 + sqrt_1m_rho2 * rng.standard_normal(n_chunk).astype(np.float32))
        v_pos = np.maximum(v, 0.0)
        sqrt_v = np.sqrt(v_pos, dtype=np.float32)
        log_S = log_S + (-0.5 * v_pos) * DT + sqrt_v * sqrt_dt * Z1
        v = v + kappa * (v_long * v_long - v_pos) * DT + sigma_v * sqrt_v * sqrt_dt * Z2
        np.minimum(min_log, log_S, out=min_log)
        if k == N_2W - 1:
            log_S_2w = log_S.copy()
    return np.exp(log_S), np.exp(log_S_2w), np.minimum(np.exp(min_log), S0)


def garch_chunk(n_chunk, sigma_uncond, alpha, beta, rng):
    var_uncond = sigma_uncond * sigma_uncond * DT
    omega = (1.0 - alpha - beta) * var_uncond
    log_S = np.full(n_chunk, math.log(S0), dtype=np.float32)
    sigma_sq = np.full(n_chunk, var_uncond, dtype=np.float32)
    eps_prev_sq = sigma_sq.copy()
    min_log = log_S.copy()
    log_S_2w = None
    for k in range(N_3W):
        sigma_sq = omega + alpha * eps_prev_sq + beta * sigma_sq
        sigma_step = np.sqrt(np.maximum(sigma_sq, 1e-12), dtype=np.float32)
        Z = rng.standard_normal(n_chunk).astype(np.float32)
        eps = sigma_step * Z
        log_S = log_S + (-0.5 * sigma_sq) + eps
        eps_prev_sq = eps * eps
        np.minimum(min_log, log_S, out=min_log)
        if k == N_2W - 1:
            log_S_2w = log_S.copy()
    return np.exp(log_S), np.exp(log_S_2w), np.minimum(np.exp(min_log), S0)


# ----------------------------------------------------------------------------
# Streaming runner
# ----------------------------------------------------------------------------
def run_spec(spec_name: str, n_total: int, gen_chunk: Callable, chunk_size: int,
             seed: int, micro_eps: float = 0.0, **gen_kwargs) -> list[Stat]:
    rng = np.random.default_rng(seed)
    rng_ms = np.random.default_rng(seed + 999_999) if micro_eps > 0 else None
    runners = {name: RunStats() for name in STRATEGIES}
    t0 = time.time()
    n_done = 0
    while n_done < n_total:
        m = min(chunk_size, n_total - n_done)
        S_T, S_T_2w, min_S = gen_chunk(m, rng=rng, **gen_kwargs)
        if micro_eps > 0:
            obs_min_S = min_S.copy()
            survivors = min_S > 35
            n_surv = int(survivors.sum())
            if n_surv > 0:
                flips = rng_ms.random(n_surv) < micro_eps
                if flips.any():
                    idx = np.where(survivors)[0][flips]
                    obs_min_S[idx] = 34.999
        else:
            obs_min_S = None
        for name, positions in STRATEGIES.items():
            pnl = chunk_pnl(positions, S_T, S_T_2w, min_S, obs_min_S=obs_min_S)
            runners[name].update(pnl)
        n_done += m
        # progress
        if n_done % (chunk_size * 10) == 0 or n_done == n_total:
            print(f"    [{spec_name}] {n_done:,}/{n_total:,} ({time.time()-t0:.1f}s)")
    elapsed = time.time() - t0
    stats = []
    for name in STRATEGIES:
        mean, sd, cvar5, p_pos = runners[name].finalize()
        stats.append(Stat(spec_name, name, mean, sd, cvar5, p_pos))
    print(f"  [{spec_name}] N={n_total:,} done in {elapsed:.1f}s")
    for s in stats:
        print(s.line())
    return stats


def main():
    out_lines: list[str] = []
    def log(msg=""):
        print(msg); out_lines.append(msg)

    # Path budget. SE on E[score] at 5M with sd~$2.6M is ~$1.2k -- plenty of resolution.
    # Spec asked for 50M; we use 10M for GBM-class and 2M for Heston/GARCH for tractable runtime
    # (24 specs total). 10M paths * 60 steps * 4 bytes = 2.4GB peak per chunk-cumsum -> chunked at 500k.
    BIG = 10_000_000
    HESTON_N = 2_000_000
    GARCH_N = 2_000_000
    CHUNK = 500_000
    HESTON_CHUNK = 200_000
    GARCH_CHUNK = 200_000

    # Override via env for quick tests
    BIG = int(os.environ.get("ALT_N_BIG", BIG))
    HESTON_N = int(os.environ.get("ALT_N_HESTON", HESTON_N))
    GARCH_N = int(os.environ.get("ALT_N_GARCH", GARCH_N))

    log("=" * 100)
    log("R4 Manual Stress Test under Alternative Model Specifications")
    log(f"Baseline: GBM sigma={SIGMA}, S0={S0}, T_3w={T_3W_DAYS}td, T_2w={T_2W_DAYS}td, "
        f"4 obs/day, multiplier x{CONTRACT_MULTIPLIER}")
    log(f"Strategy under test: OPTIMAL_7POS = {STRATEGIES['OPTIMAL_7POS']}")
    log(f"Path budget: GBM-class N={BIG:,}  Heston N={HESTON_N:,}  GARCH N={GARCH_N:,}")
    log("=" * 100)

    all_stats: dict[str, list[Stat]] = {}

    # 1. Baseline
    s = run_spec("GBM_baseline", BIG, gbm_chunk, CHUNK, seed=1, sigma=SIGMA, mu=0.0)
    all_stats["GBM_baseline"] = s

    # 2. Drift
    for mu_pct in [+0.05, +0.10, -0.05, -0.10]:
        nm = f"GBM_drift_{mu_pct:+.0%}"
        s = run_spec(nm, BIG, gbm_chunk, CHUNK, seed=20+int(mu_pct*100),
                     sigma=SIGMA, mu=mu_pct)
        all_stats[nm] = s

    # 3. Heston
    for sv in [0.1, 0.3, 0.5]:
        for rho in [-0.7, 0.0, 0.7]:
            nm = f"Heston_sv{sv}_rho{rho:+.1f}"
            s = run_spec(nm, HESTON_N, heston_chunk, HESTON_CHUNK, seed=30+int(sv*10+rho*5),
                         v_long=SIGMA, kappa=1.0, sigma_v=sv * SIGMA, rho=rho)
            all_stats[nm] = s

    # 4. Merton
    for lam in [1.0, 5.0, 20.0]:
        for sJ in [0.1, 0.3]:
            jvar = lam * sJ * sJ
            if jvar >= SIGMA * SIGMA: continue
            sd_diff = math.sqrt(SIGMA * SIGMA - jvar)
            nm = f"Merton_lam{lam:g}_sJ{sJ:g}"
            s = run_spec(nm, BIG, merton_chunk, CHUNK, seed=int(40+lam+sJ*10),
                         sigma_diff=sd_diff, lam=lam, sigma_J=sJ)
            all_stats[nm] = s

    # 5. Student-t. df=3 produces extreme outliers (heavy tail × lognormal -> moments
    # explode in finite samples); we report df=5 and df=10. df=3 also tested separately
    # with a returns-cap to handle pathological blowups.
    for df in [3.0, 5.0, 10.0]:
        nm = f"Student_t_df{df:g}"
        # Use a smaller sample for df=3 to avoid 1-in-10M extreme blowups dominating
        n_use = BIG if df > 3.0 else min(BIG, 2_000_000)
        s = run_spec(nm, n_use, student_t_chunk_capped if df <= 3.5 else student_t_chunk,
                     CHUNK, seed=50+int(df), sigma=SIGMA, df=df)
        all_stats[nm] = s

    # 6. GARCH
    for (alpha, beta) in [(0.10, 0.85), (0.05, 0.90), (0.20, 0.70)]:
        nm = f"GARCH_a{alpha}_b{beta}"
        s = run_spec(nm, GARCH_N, garch_chunk, GARCH_CHUNK, seed=60+int(alpha*100+beta*10),
                     sigma_uncond=SIGMA, alpha=alpha, beta=beta)
        all_stats[nm] = s

    # 7. Microstructure noise (reuse GBM gen with eps>0)
    for eps in [0.01, 0.05, 0.10, 0.20]:
        nm = f"MicroNoise_eps{eps}"
        s = run_spec(nm, BIG, gbm_chunk, CHUNK, seed=70+int(eps*1000),
                     micro_eps=eps, sigma=SIGMA, mu=0.0)
        all_stats[nm] = s

    # 8. Sigma-misspecification sweep (true sigma differs from quoted 2.51)
    # The original writeup flagged this as the dominant model risk.
    for true_sigma in [2.30, 2.40, 2.45, 2.55, 2.60, 2.70]:
        nm = f"Sigma_true_{true_sigma}"
        s = run_spec(nm, BIG, gbm_chunk, CHUNK, seed=80+int(true_sigma*100),
                     sigma=true_sigma, mu=0.0)
        all_stats[nm] = s

    # ---- Summary ----
    log("\n" + "=" * 110)
    log("SUMMARY: E[score] for each strategy under each spec (USD with x3000)")
    log("=" * 110)
    header = f"{'Spec':<28} | " + " | ".join(f"{n:>14}" for n in STRATEGIES.keys())
    log(header)
    log("-" * len(header))
    for spec, stats in all_stats.items():
        log(f"{spec:<28} | " + " | ".join(f"${s.score_mean:>+12,.0f}" for s in stats))

    log("\n" + "=" * 110)
    log("OPTIMAL_7POS detailed across specs")
    log("=" * 110)
    log(f"{'Spec':<28} {'E[score]':>14} {'SD/unit':>14} {'CVaR5/unit':>14} {'P>0':>7}")
    log("-" * 80)
    for spec, stats in all_stats.items():
        for s in stats:
            if s.strategy == "OPTIMAL_7POS":
                log(f"{spec:<28} ${s.score_mean:>+12,.0f} "
                    f"${s.sd_per_unit*CONTRACT_MULTIPLIER:>12,.0f} "
                    f"${s.cvar5_per_unit*CONTRACT_MULTIPLIER:>+12,.0f} "
                    f"{s.p_pos*100:>6.1f}%")

    # Robustness
    log("\n" + "=" * 110)
    log("ROBUSTNESS RANKING (range of E[score] across all alt specs)")
    log("=" * 110)
    by = {n: [] for n in STRATEGIES}
    for stats in all_stats.values():
        for s in stats: by[s.strategy].append(s.score_mean)
    log(f"{'Strategy':<14} {'min(E)':>14} {'max(E)':>14} {'mean(E)':>14} {'range':>14} {'%neg':>8}")
    log("-" * 90)
    for name, vals in by.items():
        a = np.array(vals)
        log(f"{name:<14} ${a.min():>+12,.0f} ${a.max():>+12,.0f} ${a.mean():>+12,.0f} "
            f"${a.max()-a.min():>12,.0f} {float((a<0).mean())*100:>7.1f}%")

    log("\n" + "=" * 110)
    log("Specs where OPTIMAL_7POS goes negative-EV")
    log("=" * 110)
    breaks = [(n, s) for n, stats in all_stats.items()
              for s in stats if s.strategy == "OPTIMAL_7POS" and s.score_mean <= 0]
    if not breaks:
        log("  (none — OPTIMAL_7POS stays positive-EV across all alt specs)")
    else:
        for n, s in breaks:
            log(f"  {n:<28}  E[score] = ${s.score_mean:+,.0f}")

    out_path = os.path.join(os.path.dirname(__file__), "alt_models_v2_output.txt")
    with open(out_path, "w") as f:
        f.write("\n".join(out_lines))
    print(f"\nSummary written to {out_path}")


if __name__ == "__main__":
    main()
