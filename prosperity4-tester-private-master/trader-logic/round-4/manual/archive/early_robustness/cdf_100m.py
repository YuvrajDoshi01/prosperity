"""100M-path empirical CDF analysis for R4 manual tail-risk verification.

Generates 100M GBM paths (chunked at 5M for RAM control), groups into
1M trials of 100 paths each, computes empirical realized-score CDF for
each candidate strategy. Reports exact tail probabilities (no Gaussian
approximation).

Estimated runtime: 5-10 min on a single core with numpy vectorization.
RAM peak: ~250MB per chunk.
"""
import numpy as np
import time
import json

# -- Parameters ---------------------------------------------------------------
S0 = 50.0
SIGMA = 2.51
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_2W_DAYS = 10
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W = T_3W_DAYS * STEPS_PER_DAY     # 60 steps
N_2W = T_2W_DAYS * STEPS_PER_DAY     # 40 steps

CONTRACT_MULTIPLIER = 3000

# Quotes: (bid, ask, vol_cap)
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

# Candidate strategies -- list of (instrument, side, vol)
STRATEGIES = {
    "DROP_60C (recommended)": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
    ],
    "GLOBAL_MAX (with 60C)": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
        ("AC_60_C",   "sell", 50),
    ],
    "PRIOR_FINAL (8-pos hedged)": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
        ("AC_50_P",   "buy",  50),
        ("AC_50_C",   "buy",  25),
        ("AC",        "buy",  5),
    ],
    "USER_SAFE (KO=60)": [
        ("AC_50_CO", "sell", 15),
        ("AC_40_BP", "sell", 50),
        ("AC_45_KO", "buy",  60),
        ("AC_50_P",  "buy",  17),
        ("AC_50_P_2","buy",  15),
        ("AC_50_C",  "buy",  15),
    ],
    "USER_GREEDY_57k": [
        ("AC_50_CO", "sell", 15),
        ("AC_40_BP", "sell", 55),
        ("AC_45_KO", "buy",  75),
        ("AC_50_P",  "buy",  22),
        ("AC_50_P_2","buy",  15),
        ("AC_50_C",  "buy",  15),
        ("AC",       "buy",  30),
        ("AC_45_P",  "buy",  10),
        ("AC_35_P",  "sell", 15),
    ],
}


def per_path_payoffs(S_T, S_2w, min_S):
    """Compute per-path payoffs for ALL 12 instruments. Vectorized."""
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
        # Chooser auto-converts at t=2w to ITM side
        "AC_50_CO":   np.where(S_2w >= 50, np.maximum(S_T - 50, 0.0), np.maximum(50 - S_T, 0.0)),
        "AC_40_BP":   np.where(S_T < 40, 10.0, 0.0),
        # KO put: pays only if barrier never breached during discrete monitoring
        "AC_45_KO":   np.where(min_S > 35, np.maximum(45 - S_T, 0.0), 0.0),
    }


def strategy_per_path_pnl(strategy, payoffs):
    """Compute per-path PnL of a strategy as numpy array."""
    pnl = np.zeros_like(next(iter(payoffs.values())))
    for sym, side, vol in strategy:
        bid, ask, _ = QUOTES[sym]
        p = payoffs[sym]
        if side == "buy":
            pnl += vol * (p - ask)
        else:
            pnl += vol * (bid - p)
    return pnl


def gen_path_chunk(n_paths, rng):
    """Generate n_paths GBM paths, return (S_T, S_2w, min_S)."""
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


def main():
    TOTAL_PATHS = 100_000_000
    CHUNK_SIZE = 5_000_000
    N_CHUNKS = TOTAL_PATHS // CHUNK_SIZE
    SIMS_PER_TRIAL = 100
    N_TRIALS = TOTAL_PATHS // SIMS_PER_TRIAL  # 1M trials

    print(f"Configuration:")
    print(f"  Total paths: {TOTAL_PATHS:,}")
    print(f"  Chunk size:  {CHUNK_SIZE:,}")
    print(f"  Chunks:      {N_CHUNKS}")
    print(f"  Trials:      {N_TRIALS:,} (each = mean of {SIMS_PER_TRIAL} paths)")
    print(f"  Multiplier:  x{CONTRACT_MULTIPLIER}")
    print()

    # Per-path PnL accumulators (per strategy)
    pnl_arrays = {name: np.empty(TOTAL_PATHS, dtype=np.float64) for name in STRATEGIES}

    rng = np.random.default_rng(seed=42)
    t0 = time.time()
    for chunk_idx in range(N_CHUNKS):
        t_chunk = time.time()
        S_T, S_2w, min_S = gen_path_chunk(CHUNK_SIZE, rng)
        payoffs = per_path_payoffs(S_T, S_2w, min_S)
        for name, strat in STRATEGIES.items():
            chunk_pnl = strategy_per_path_pnl(strat, payoffs)
            start = chunk_idx * CHUNK_SIZE
            pnl_arrays[name][start:start + CHUNK_SIZE] = chunk_pnl
        elapsed = time.time() - t_chunk
        total = time.time() - t0
        eta = (N_CHUNKS - chunk_idx - 1) * elapsed
        print(f"  Chunk {chunk_idx+1}/{N_CHUNKS}: {elapsed:.1f}s (total {total:.1f}s, ETA {eta:.0f}s)")

    print(f"\nPath generation done in {time.time()-t0:.1f}s. Computing trial scores...")

    # Reshape per-path PnL into (N_TRIALS, SIMS_PER_TRIAL) and take row-mean
    trial_scores = {name: pnl_arrays[name].reshape(N_TRIALS, SIMS_PER_TRIAL).mean(axis=1)
                    for name in STRATEGIES}

    # Apply x3000 multiplier and compute stats
    print(f"\n{'=' * 110}")
    print(f"EMPIRICAL CDF -- {N_TRIALS:,} TRIALS x {SIMS_PER_TRIAL} PATHS = {TOTAL_PATHS:,} TOTAL PATHS")
    print(f"All values in XIRECs (with x{CONTRACT_MULTIPLIER} multiplier)")
    print(f"{'=' * 110}")

    # Tail thresholds (in XIRECs after multiplier)
    THRESHOLDS = [-500_000, -200_000, -100_000, -50_000, 0, 50_000, 100_000, 200_000, 300_000, 500_000]
    PERCENTILES = [0.1, 1, 5, 10, 25, 50, 75, 90, 95, 99, 99.9]

    results = {}
    for name in STRATEGIES:
        scores = trial_scores[name] * CONTRACT_MULTIPLIER
        mean = float(scores.mean())
        std = float(scores.std(ddof=1))
        med = float(np.median(scores))
        # Tail probabilities
        tails = {f"P(score>{t})": float((scores > t).mean()) for t in THRESHOLDS}
        # Empirical quantiles
        quantiles = {f"q{p}": float(np.percentile(scores, p)) for p in PERCENTILES}
        results[name] = {
            "mean": mean, "sd": std, "median": med,
            "tails": tails, "quantiles": quantiles,
        }

        print(f"\n{'-' * 110}")
        print(f"{name}")
        print(f"{'-' * 110}")
        print(f"  Mean        = ${mean:>+15,.0f}")
        print(f"  Median      = ${med:>+15,.0f}")
        print(f"  SD          = ${std:>+15,.0f}")
        print(f"  Sharpe      = {mean/std:>+15.4f}")

        print(f"\n  Empirical TAIL PROBABILITIES (P(score > X)):")
        for t in THRESHOLDS:
            print(f"    P(score > ${t:>+10,}) = {tails[f'P(score>{t})']*100:5.2f}%")

        print(f"\n  Empirical QUANTILES (out of {N_TRIALS:,} trials):")
        for p in PERCENTILES:
            print(f"    {p:5.1f}% quantile = ${quantiles[f'q{p}']:>+15,.0f}")

        # CVaR (mean of trials below given percentile)
        print(f"\n  Empirical CVaR (mean of worst trials):")
        for cvar_pct in [1, 5, 10, 25]:
            thresh = quantiles[f"q{cvar_pct}"]
            cvar = float(scores[scores <= thresh].mean())
            print(f"    CVaR-{cvar_pct}% = ${cvar:>+15,.0f}")

    # Side-by-side comparison
    print(f"\n{'=' * 110}")
    print("SIDE-BY-SIDE COMPARISON")
    print(f"{'=' * 110}")
    print(f"\n{'Strategy':<28} {'Mean':>14} {'Median':>14} {'SD':>14} {'P>0':>8} {'P>$100k':>9} {'CVaR-5%':>14}")
    for name in STRATEGIES:
        r = results[name]
        print(f"{name:<28} ${r['mean']:>+13,.0f} ${r['median']:>+13,.0f} ${r['sd']:>+13,.0f} "
              f"{r['tails']['P(score>0)']*100:>6.1f}% {r['tails']['P(score>100000)']*100:>7.1f}% "
              f"${float(np.mean(trial_scores[name][trial_scores[name]*CONTRACT_MULTIPLIER <= np.percentile(trial_scores[name]*CONTRACT_MULTIPLIER, 5)])*CONTRACT_MULTIPLIER):>+13,.0f}")

    # Save JSON
    with open("trader-logic/round-4/manual/cdf_100m_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to cdf_100m_results.json")
    print(f"Total runtime: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
