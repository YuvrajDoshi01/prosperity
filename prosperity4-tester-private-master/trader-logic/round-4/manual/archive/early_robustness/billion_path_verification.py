"""
Billion-path empirical CDF verification for R4 manual options challenge.

GOAL: Nail down statistics with extreme precision (SE drops by sqrt(10) vs 100M).

DESIGN
------
- 1,000,000,000 GBM paths total, split into 5 seeds x 200M paths each.
- Each 200M-seed split into 10 chunks of 20M paths (50 chunks total).
- Per-chunk: simulate paths, compute payoffs, compute strategy PnLs * 3000,
            reshape to (chunk/100, 100), row-mean -> trial scores (200k/chunk).
- Store only trial scores (10M trials x 4 strategies x float64 = 320 MB).
- Per-path PnL never materialized for the full 1B; only chunk-local arrays exist
  during processing, peak RAM ~ 1-1.5 GB.

NUMERICS
--------
- Paths simulated in float32 for RAM (1B paths in float32 still impossible to
  store, so this only matters in-chunk), with chunk-local accumulators in
  float32 -> conversion to float64 before reshape/mean for the trial score.
- Verification: re-run a 10M-path probe with float64 paths and compare means
  to the float32 arm to confirm < 1e-3 relative error.

SCOPE
-----
Strategies (4):
  1. OPTIMAL_7POS    -- 7 positions: SELL CO, BUY 500 KO, SELL BP, BUY P_2,
                       BUY C_2, BUY P, BUY 25 C
  2. DROP_60C_5POS   -- 5 positions: SELL CO, BUY 500 KO, SELL BP, BUY P_2,
                       BUY C_2
  3. KO300_HEDGED    -- 7 positions, KO=300 instead of 500
  4. USER_SAFE       -- 6 positions, KO=60, BP-sell, light hedge

Statistics (per strategy):
  - mean, median, SD, Sharpe, P(>0)
  - percentiles: 0.001, 0.01, 0.1, 1, 2, 5, 10, 25, 50, 75, 90, 95, 98, 99,
                 99.9, 99.99, 99.999
  - CVaR @ {1, 2, 5, 10, 25}%
  - tail probabilities: P(score > X) for X in {-1M, -500k, -200k, -100k,
                                                -50k, 0, 50k, 100k, 200k,
                                                500k, 1M}
Pairwise comparisons:
  - same-trial bootstrap difference (via paired structure: trials are
    matched 1:1 since they share paths). We compute paired diffs directly.
  - 95% CI on mean diff (gaussian SE / sqrt(N)).

Sigma stress test:
  - 100M extra paths each at sigma in {2.46, 2.51, 2.56, 2.61}, single seed
    each. Re-simulated under each sigma since paths depend on sigma.

Outputs:
  - trader-logic/round-4/manual/billion_path_results.md
  - trader-logic/round-4/manual/billion_path_results.json

Estimated runtime: ~50-90 min (single core, vectorized numpy).
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np


# ============================================================================
# CONFIG
# ============================================================================

S0 = 50.0
SIGMA = 2.51
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_2W_DAYS = 10
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W = T_3W_DAYS * STEPS_PER_DAY  # 60
N_2W = T_2W_DAYS * STEPS_PER_DAY  # 40
CONTRACT_MULTIPLIER = 3000

QUOTES = {
    "AC":          (49.975, 50.025, 200),
    "AC_50_P":     (12.00,  12.05,  50),
    "AC_50_C":     (12.00,  12.05,  50),
    "AC_50_P_2":   ( 9.70,   9.75,  50),
    "AC_50_C_2":   ( 9.70,   9.75,  50),
    "AC_50_CO":    (22.20,  22.30,  50),
    "AC_40_BP":    ( 5.00,   5.10,  50),
    "AC_45_KO":    ( 0.15,   0.175, 500),
}

STRATEGIES = {
    "OPTIMAL_7POS": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
        ("AC_50_P",   "buy",  50),
        ("AC_50_C",   "buy",  25),
    ],
    "DROP_60C_5POS": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
    ],
    "KO300_HEDGED": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  300),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
        ("AC_50_P",   "buy",  50),
        ("AC_50_C",   "buy",  25),
    ],
    "USER_SAFE": [
        ("AC_50_CO",  "sell", 15),
        ("AC_40_BP",  "sell", 50),
        ("AC_45_KO",  "buy",  60),
        ("AC_50_P",   "buy",  17),
        ("AC_50_P_2", "buy",  15),
        ("AC_50_C",   "buy",  15),
    ],
}

TOTAL_PATHS = 1_000_000_000
SEEDS = [42, 1729, 2718, 31415, 8675309]
PATHS_PER_SEED = TOTAL_PATHS // len(SEEDS)        # 200M
CHUNK_SIZE = 10_000_000                            # 10M paths per chunk (f64 RAM-tuned)
SIMS_PER_TRIAL = 100
TRIALS_PER_CHUNK = CHUNK_SIZE // SIMS_PER_TRIAL    # 100k
TOTAL_TRIALS = TOTAL_PATHS // SIMS_PER_TRIAL       # 10M
N_CHUNKS_PER_SEED = PATHS_PER_SEED // CHUNK_SIZE   # 20
N_CHUNKS_TOTAL = TOTAL_PATHS // CHUNK_SIZE         # 100
DTYPE_PATHS = np.float64                           # f32 had rel-err ~ 1.6e-3, exceeds target SE

OUT_DIR = Path(r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-4\manual")
RESULTS_JSON = OUT_DIR / "billion_path_results.json"
RESULTS_MD = OUT_DIR / "billion_path_results.md"


# ============================================================================
# CORE: GBM SIMULATION + PAYOFFS
# ============================================================================

def gen_chunk(n_paths: int, rng: np.random.Generator, sigma: float = SIGMA, dtype=np.float64):
    """Generate n_paths GBM paths with discrete monitoring (4 obs/day).

    Returns (S_T, S_2w, min_S) each shape (n_paths,) in dtype (default float64).
    Drift = -0.5 sigma^2 dt (risk-neutral, r=0).
    Uses log-space accumulation for numerical stability across 60 steps.
    """
    drift = float(-0.5 * sigma * sigma * DT)
    vol = float(sigma * math.sqrt(DT))
    # Accumulate log-price in dtype, then exponentiate at endpoints.
    # This is more numerically stable than repeated S *= exp(...) in f32.
    logS = np.full(n_paths, math.log(S0), dtype=dtype)
    log_min = logS.copy()
    S_2w = None
    for k in range(N_3W):
        z = rng.standard_normal(n_paths, dtype=dtype)
        logS += drift
        logS += vol * z
        np.minimum(log_min, logS, out=log_min)
        if k + 1 == N_2W:
            S_2w = np.exp(logS)
    S_T = np.exp(logS)
    min_S = np.exp(log_min)
    return S_T, S_2w, min_S


def per_path_payoffs(S_T, S_2w, min_S):
    """Vectorized payoffs for the 8 instruments referenced by the 4 strategies."""
    return {
        "AC":         S_T,
        "AC_50_P":    np.maximum(50.0 - S_T, 0.0),
        "AC_50_C":    np.maximum(S_T - 50.0, 0.0),
        "AC_50_P_2":  np.maximum(50.0 - S_2w, 0.0),
        "AC_50_C_2":  np.maximum(S_2w - 50.0, 0.0),
        # Chooser: holder selects ITM side at t=2w; ITM-side European payoff at T
        "AC_50_CO":   np.where(S_2w >= 50.0,
                               np.maximum(S_T - 50.0, 0.0),
                               np.maximum(50.0 - S_T, 0.0)),
        "AC_40_BP":   np.where(S_T < 40.0, 10.0, 0.0),
        # Up-and-out put with barrier at S=35 (KO if min ever <= 35)
        "AC_45_KO":   np.where(min_S > 35.0, np.maximum(45.0 - S_T, 0.0), 0.0),
    }


def strategy_per_path_pnl(strategy, payoffs):
    """Per-path PnL (pre-multiplier) for a strategy. Float64 for numerical safety."""
    n = next(iter(payoffs.values())).shape[0]
    pnl = np.zeros(n, dtype=np.float64)
    for sym, side, vol in strategy:
        bid, ask, _cap = QUOTES[sym]
        p = payoffs[sym].astype(np.float64, copy=False)
        if side == "buy":
            pnl += vol * (p - ask)
        else:
            pnl += vol * (bid - p)
    return pnl


# ============================================================================
# 1B-PATH MAIN PIPELINE
# ============================================================================

def run_billion(verbose=True):
    print("=" * 80)
    print("1-BILLION PATH EMPIRICAL CDF VERIFICATION")
    print("=" * 80)
    print(f"  TOTAL_PATHS         = {TOTAL_PATHS:,}")
    print(f"  SEEDS               = {SEEDS}")
    print(f"  CHUNK_SIZE          = {CHUNK_SIZE:,}")
    print(f"  CHUNKS              = {N_CHUNKS_TOTAL} ({N_CHUNKS_PER_SEED}/seed)")
    print(f"  TRIALS              = {TOTAL_TRIALS:,} (mean of {SIMS_PER_TRIAL} paths)")
    print(f"  CONTRACT_MULTIPLIER = x{CONTRACT_MULTIPLIER}")
    print(f"  SIGMA (annualized)  = {SIGMA}")
    print()

    # 10M trial scores per strategy, in float64. 320 MB total.
    trial_scores = {name: np.empty(TOTAL_TRIALS, dtype=np.float64) for name in STRATEGIES}

    chunk_global = 0
    t_start = time.time()

    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        for c_local in range(N_CHUNKS_PER_SEED):
            t_c = time.time()
            S_T, S_2w, min_S = gen_chunk(CHUNK_SIZE, rng, sigma=SIGMA, dtype=DTYPE_PATHS)
            payoffs = per_path_payoffs(S_T, S_2w, min_S)
            del S_T, S_2w, min_S

            offset_trials = chunk_global * TRIALS_PER_CHUNK
            for name, strat in STRATEGIES.items():
                pp = strategy_per_path_pnl(strat, payoffs) * CONTRACT_MULTIPLIER
                # Reshape to (200k, 100) and row-mean -> trial scores
                t_chunk = pp.reshape(TRIALS_PER_CHUNK, SIMS_PER_TRIAL).mean(axis=1)
                trial_scores[name][offset_trials:offset_trials + TRIALS_PER_CHUNK] = t_chunk
                del pp, t_chunk
            del payoffs

            chunk_global += 1
            elapsed = time.time() - t_c
            total = time.time() - t_start
            done = chunk_global / N_CHUNKS_TOTAL
            eta = total * (1.0 / done - 1.0) if done > 0 else 0.0
            if verbose:
                print(f"  [seed {seed}] chunk {c_local+1:2d}/{N_CHUNKS_PER_SEED} "
                      f"({chunk_global}/{N_CHUNKS_TOTAL} global) "
                      f"{elapsed:5.1f}s | total {total:7.1f}s | ETA {eta:7.0f}s")

    total = time.time() - t_start
    print(f"\nPath generation + trial-score reduction complete in {total:.1f}s "
          f"({total/60:.1f} min)\n")

    return trial_scores


# ============================================================================
# STATISTICS
# ============================================================================

def empirical_stats(scores: np.ndarray):
    """All requested statistics for a (10M,) trial-score array."""
    N = scores.size
    PERCENTILES = [0.001, 0.01, 0.1, 1, 2, 5, 10, 25, 50, 75, 90, 95, 98, 99, 99.9, 99.99, 99.999]
    THRESHOLDS = [-1_000_000, -500_000, -200_000, -100_000, -50_000,
                  0, 50_000, 100_000, 200_000, 500_000, 1_000_000]
    CVAR_LEVELS = [1, 2, 5, 10, 25]

    mean = float(scores.mean())
    median = float(np.median(scores))
    sd = float(scores.std(ddof=1))
    sharpe = mean / sd if sd > 0 else float("nan")
    p_pos = float((scores > 0).mean())

    qs = np.percentile(scores, PERCENTILES)
    quantiles = {f"p{p}": float(qs[i]) for i, p in enumerate(PERCENTILES)}

    cvars = {}
    for level in CVAR_LEVELS:
        thresh = quantiles[f"p{level}"]
        tail = scores[scores <= thresh]
        cvars[f"cvar_{level}"] = float(tail.mean()) if tail.size else float("nan")

    tails = {}
    for t in THRESHOLDS:
        # P(score > t) and P(score < t)
        gt = float((scores > t).mean())
        lt = float((scores < t).mean())
        tails[f"P(score>{t:+d})"] = gt
        tails[f"P(score<{t:+d})"] = lt

    se_mean = sd / math.sqrt(N)

    return {
        "N": N,
        "mean": mean,
        "se_mean": se_mean,
        "median": median,
        "sd": sd,
        "sharpe": sharpe,
        "p_positive": p_pos,
        "quantiles": quantiles,
        "cvars": cvars,
        "tails": tails,
    }


def pairwise_diff(a: np.ndarray, b: np.ndarray):
    """Paired difference statistics: a beats b iff a - b > 0.

    Same-trial: trials are matched 1:1 (same underlying paths). So this is
    an exact paired comparison, no bootstrap required.
    """
    diff = a - b
    N = diff.size
    mean = float(diff.mean())
    sd = float(diff.std(ddof=1))
    se = sd / math.sqrt(N)
    p_a_beats_b = float((diff > 0).mean())
    ci_lo = mean - 1.959964 * se
    ci_hi = mean + 1.959964 * se
    return {
        "N": N,
        "mean_diff": mean,
        "sd_diff": sd,
        "se_diff": se,
        "ci95": [ci_lo, ci_hi],
        "P(a_beats_b)": p_a_beats_b,
    }


# ============================================================================
# SIGMA STRESS TEST
# ============================================================================

def sigma_stress_summary(strategies, sigma, n_paths=100_000_000, seed=2024,
                         chunk_size=10_000_000, sims_per_trial=100):
    """Re-simulate n_paths under a different sigma; compute mean PnL per strategy."""
    n_chunks = n_paths // chunk_size
    n_trials = n_paths // sims_per_trial
    trials_per_chunk = chunk_size // sims_per_trial

    # Per-strategy trial accumulator
    out = {name: np.empty(n_trials, dtype=np.float64) for name in strategies}
    rng = np.random.default_rng(seed)

    for c in range(n_chunks):
        S_T, S_2w, min_S = gen_chunk(chunk_size, rng, sigma=sigma, dtype=DTYPE_PATHS)
        payoffs = per_path_payoffs(S_T, S_2w, min_S)
        del S_T, S_2w, min_S
        offset = c * trials_per_chunk
        for name, strat in strategies.items():
            pp = strategy_per_path_pnl(strat, payoffs) * CONTRACT_MULTIPLIER
            t = pp.reshape(trials_per_chunk, sims_per_trial).mean(axis=1)
            out[name][offset:offset + trials_per_chunk] = t

    # Quick stats per strategy
    return {name: {
        "sigma": sigma,
        "N_paths": n_paths,
        "N_trials": n_trials,
        "mean": float(out[name].mean()),
        "se_mean": float(out[name].std(ddof=1) / math.sqrt(n_trials)),
        "median": float(np.median(out[name])),
        "sd": float(out[name].std(ddof=1)),
        "p_positive": float((out[name] > 0).mean()),
    } for name in strategies}


# ============================================================================
# FLOAT32-vs-FLOAT64 ACCURACY SPOT CHECK
# ============================================================================

def precision_spot_check(n_paths=10_000_000, seed=999):
    """Run two independent 10M-path simulations under f32 and f64 with SAME seed
    sequence, compare per-strategy means. Threshold: |rel err| < 1e-3.
    """
    out = {}
    for dtype, label in [(np.float32, "f32"), (np.float64, "f64")]:
        rng = np.random.default_rng(seed)
        S_T, S_2w, min_S = gen_chunk(n_paths, rng, sigma=SIGMA, dtype=dtype)
        payoffs = per_path_payoffs(S_T, S_2w, min_S)
        for name, strat in STRATEGIES.items():
            pp = strategy_per_path_pnl(strat, payoffs) * CONTRACT_MULTIPLIER
            out.setdefault(name, {})[f"mean_{label}"] = float(pp.mean())
            out[name][f"sd_{label}"] = float(pp.std(ddof=1))
        del S_T, S_2w, min_S, payoffs

    # Compute relative errors
    for name in STRATEGIES:
        m32 = out[name]["mean_f32"]
        m64 = out[name]["mean_f64"]
        rel = abs(m32 - m64) / max(abs(m64), 1.0)
        out[name]["rel_err"] = rel
    return out


# ============================================================================
# REPORTING
# ============================================================================

def fmt_money(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "nan"
    return f"${x:>+15,.2f}"


def write_markdown(results: dict, path: Path):
    lines = []
    lines.append("# R4 Manual Options - 1 Billion Path Empirical CDF\n")
    lines.append(f"_Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}_\n")
    lines.append(f"\n**Total paths**: {results['config']['total_paths']:,}  ")
    lines.append(f"**Trials**: {results['config']['total_trials']:,} (each = mean of 100 paths)  ")
    lines.append(f"**Multiplier**: x{CONTRACT_MULTIPLIER}  ")
    lines.append(f"**Sigma**: {SIGMA}  ")
    lines.append(f"**Wallclock**: {results['config']['wall_seconds']:.1f}s "
                 f"({results['config']['wall_seconds']/60:.1f} min)\n")

    # Headline summary table
    lines.append("\n## Headline summary\n")
    lines.append("| Strategy | Mean | SE(mean) | Median | SD | Sharpe | P(>0) |\n")
    lines.append("|---|---:|---:|---:|---:|---:|---:|\n")
    for name in STRATEGIES:
        s = results["stats"][name]
        lines.append(
            f"| {name} | {fmt_money(s['mean'])} | {fmt_money(s['se_mean'])} | "
            f"{fmt_money(s['median'])} | {fmt_money(s['sd'])} | "
            f"{s['sharpe']:+.4f} | {s['p_positive']*100:.3f}% |\n"
        )

    # Per-strategy detail
    lines.append("\n## Per-strategy detail\n")
    for name in STRATEGIES:
        s = results["stats"][name]
        lines.append(f"\n### {name}\n")
        lines.append(f"- Mean   = {fmt_money(s['mean'])} +/- {fmt_money(s['se_mean'])}\n")
        lines.append(f"- Median = {fmt_money(s['median'])}\n")
        lines.append(f"- SD     = {fmt_money(s['sd'])}\n")
        lines.append(f"- Sharpe = {s['sharpe']:+.4f}\n")
        lines.append(f"- P(>0)  = {s['p_positive']*100:.4f}%\n")

        lines.append("\n**Percentiles**:\n\n")
        lines.append("| p | value |\n|---:|---:|\n")
        for k, v in s["quantiles"].items():
            lines.append(f"| {k} | {fmt_money(v)} |\n")

        lines.append("\n**CVaR (mean of worst x%)**:\n\n")
        lines.append("| level | value |\n|---:|---:|\n")
        for k, v in s["cvars"].items():
            lines.append(f"| {k} | {fmt_money(v)} |\n")

        lines.append("\n**Tail probabilities**:\n\n")
        lines.append("| threshold | P(score>X) | P(score<X) |\n|---:|---:|---:|\n")
        for X in [-1_000_000, -500_000, -200_000, -100_000, -50_000,
                  0, 50_000, 100_000, 200_000, 500_000, 1_000_000]:
            gt = s["tails"][f"P(score>{X:+d})"]
            lt = s["tails"][f"P(score<{X:+d})"]
            lines.append(f"| {X:+,} | {gt*100:.5f}% | {lt*100:.5f}% |\n")

    # Pairwise comparisons
    lines.append("\n## Pairwise comparisons (paired, same trials)\n")
    lines.append("| A | B | mean(A-B) | SE | 95% CI | P(A beats B) |\n|---|---|---:|---:|---|---:|\n")
    for (a, b), pc in results["pairs"].items():
        lo, hi = pc["ci95"]
        lines.append(
            f"| {a} | {b} | {fmt_money(pc['mean_diff'])} | "
            f"{fmt_money(pc['se_diff'])} | "
            f"[{fmt_money(lo)}, {fmt_money(hi)}] | "
            f"{pc['P(a_beats_b)']*100:.4f}% |\n"
        )

    # Sigma stress
    lines.append("\n## Sigma stress test (100M paths each, separate seeds)\n")
    lines.append("Per-strategy mean PnL under different sigma (re-simulated paths).\n\n")
    sig_list = results["sigma_stress_sigmas"]
    header = "| Strategy | " + " | ".join(f"sigma={s}" for s in sig_list) + " |\n"
    sep = "|---|" + "|".join(["---:"] * len(sig_list)) + "|\n"
    lines.append(header)
    lines.append(sep)
    for name in STRATEGIES:
        cells = []
        for s in sig_list:
            d = results["sigma_stress"][f"sigma={s}"][name]
            cells.append(f"{fmt_money(d['mean'])} +/- {fmt_money(d['se_mean'])}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |\n")

    # Convergence vs 100M
    lines.append("\n## Convergence vs 100M-path run\n")
    cmp = results.get("vs_100m", {})
    if cmp:
        lines.append("| Strategy | Mean (1B) | Mean (100M) | abs diff | rel diff | SE (1B) |\n")
        lines.append("|---|---:|---:|---:|---:|---:|\n")
        for name, row in cmp.items():
            lines.append(
                f"| {name} | {fmt_money(row['mean_1b'])} | "
                f"{fmt_money(row['mean_100m'])} | "
                f"{fmt_money(row['abs_diff'])} | "
                f"{row['rel_diff']*100:.4f}% | {fmt_money(row['se_1b'])} |\n"
            )

    # Precision
    if "precision" in results:
        lines.append("\n## Float32 vs Float64 precision spot-check (10M paths)\n")
        lines.append("| Strategy | mean(f32) | mean(f64) | rel err |\n|---|---:|---:|---:|\n")
        for name, row in results["precision"].items():
            lines.append(
                f"| {name} | {fmt_money(row['mean_f32'])} | "
                f"{fmt_money(row['mean_f64'])} | {row['rel_err']:.2e} |\n"
            )

    path.write_text("".join(lines), encoding="utf-8")


# ============================================================================
# MAIN
# ============================================================================

def main():
    t0 = time.time()

    # 1. Precision check FIRST (cheap, ~30s)
    print("Step 1: float32 vs float64 precision spot-check (10M paths each)...")
    t_prec = time.time()
    precision = precision_spot_check(n_paths=10_000_000, seed=999)
    print(f"  done in {time.time()-t_prec:.1f}s.")
    for name, row in precision.items():
        print(f"  {name}: f32 mean={row['mean_f32']:+.4f}, f64 mean={row['mean_f64']:+.4f}, "
              f"rel err = {row['rel_err']:.2e}")
    print()

    # 2. 1B-path main run
    print("Step 2: 1-billion path main run...")
    t_main = time.time()
    trial_scores = run_billion(verbose=True)
    wall_main = time.time() - t_main

    # 3. Per-strategy stats
    print("Step 3: computing empirical statistics...")
    stats = {}
    for name in STRATEGIES:
        stats[name] = empirical_stats(trial_scores[name])
        print(f"  {name}: mean={stats[name]['mean']:+,.2f} "
              f"+/- {stats[name]['se_mean']:.2f}, sd={stats[name]['sd']:,.0f}, "
              f"P(>0)={stats[name]['p_positive']*100:.3f}%")

    # 4. Pairwise comparisons (paired)
    print("\nStep 4: pairwise comparisons...")
    pair_keys = [
        ("OPTIMAL_7POS", "DROP_60C_5POS"),
        ("KO300_HEDGED", "OPTIMAL_7POS"),
        ("DROP_60C_5POS", "USER_SAFE"),
        ("OPTIMAL_7POS", "USER_SAFE"),
        ("KO300_HEDGED", "DROP_60C_5POS"),
    ]
    pairs = {}
    for a, b in pair_keys:
        pc = pairwise_diff(trial_scores[a], trial_scores[b])
        pairs[(a, b)] = pc
        print(f"  {a} - {b}: mean_diff={pc['mean_diff']:+,.2f} "
              f"+/- {pc['se_diff']:.2f}, P(A>B)={pc['P(a_beats_b)']*100:.4f}%")

    # Free trial-score arrays before sigma stress to free RAM
    del trial_scores

    # 5. Sigma stress test
    print("\nStep 5: sigma stress test (100M paths per sigma)...")
    sig_list = [2.46, 2.51, 2.56, 2.61]
    sigma_stress = {}
    for i, s in enumerate(sig_list):
        ts = time.time()
        d = sigma_stress_summary(STRATEGIES, sigma=s, n_paths=100_000_000,
                                 seed=2024 + i, chunk_size=20_000_000)
        sigma_stress[f"sigma={s}"] = d
        print(f"  sigma_stress sigma={s}: done in {time.time()-ts:.1f}s")
        for name, dd in d.items():
            print(f"    {name}: mean={dd['mean']:+,.2f} +/- {dd['se_mean']:.2f}")

    # 6. Compare to 100M run
    print("\nStep 6: load 100M results for convergence comparison...")
    vs_100m = {}
    p100 = OUT_DIR / "cdf_100m_results.json"
    if p100.exists():
        with open(p100) as f:
            old = json.load(f)
        # Map names: 100M used "DROP_60C (recommended)" etc.
        name_map = {
            "OPTIMAL_7POS": "PRIOR_FINAL (8-pos hedged)",  # was 8-pos with AC=5; closest available
            "DROP_60C_5POS": "DROP_60C (recommended)",
            "KO300_HEDGED": None,
            "USER_SAFE": "USER_SAFE (KO=60)",
        }
        for new, old_key in name_map.items():
            if old_key and old_key in old:
                m1b = stats[new]["mean"]
                se1b = stats[new]["se_mean"]
                m100 = old[old_key]["mean"]
                vs_100m[new] = {
                    "mean_1b": m1b,
                    "mean_100m": m100,
                    "abs_diff": m1b - m100,
                    "rel_diff": (m1b - m100) / max(abs(m100), 1.0),
                    "se_1b": se1b,
                    "old_key": old_key,
                }

    # 7. Save outputs
    print("\nStep 7: save JSON + Markdown outputs...")
    wall = time.time() - t0
    out = {
        "config": {
            "total_paths": TOTAL_PATHS,
            "total_trials": TOTAL_TRIALS,
            "sigma": SIGMA,
            "S0": S0,
            "trading_days_year": TRADING_DAYS_YEAR,
            "steps_per_day": STEPS_PER_DAY,
            "T_3W_DAYS": T_3W_DAYS,
            "T_2W_DAYS": T_2W_DAYS,
            "multiplier": CONTRACT_MULTIPLIER,
            "seeds": SEEDS,
            "chunk_size": CHUNK_SIZE,
            "wall_seconds": wall,
        },
        "stats": stats,
        "pairs": {f"{a}_vs_{b}": v for (a, b), v in pairs.items()},
        "sigma_stress": sigma_stress,
        "sigma_stress_sigmas": sig_list,
        "precision": precision,
        "vs_100m": vs_100m,
    }
    # JSON-serializable normalization
    def _ser(o):
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return str(o)
    RESULTS_JSON.write_text(json.dumps(out, indent=2, default=_ser))

    # For markdown, retain pairs as tuple-keyed dict
    out_md = dict(out)
    out_md["pairs"] = pairs
    write_markdown(out_md, RESULTS_MD)

    print(f"\nWrote {RESULTS_JSON}")
    print(f"Wrote {RESULTS_MD}")
    print(f"\nTotal wallclock: {wall:.1f}s ({wall/60:.1f} min)")


if __name__ == "__main__":
    main()
