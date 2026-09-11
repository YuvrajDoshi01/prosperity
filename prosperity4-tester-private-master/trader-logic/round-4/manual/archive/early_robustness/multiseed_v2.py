"""Multi-seed reproducibility analysis for R4 manual recommendation.

20 seeds x 50M paths = 1B paths total. Each seed groups its 50M paths into
500K trials of 100 paths each (the IMC scoring rule averages across 100
simulated paths per trial).

Strategies compared:
  OPTIMAL_7POS  -- the 7-position recommendation under audit
  DROP_60C      -- the 5-position variant we actually shipped
  USER_SAFE     -- low-variance teammate alternative

Outputs per-seed mean/SD/CVaR/tail probs, aggregate cross-seed CIs,
bootstrap CI on aggregate CVaR-5%, and a stability verdict.

Implementation notes:
  - GBM paths in float32 for speed (2x faster than float64, MC noise < float32 eps).
  - Path generation is the bottleneck (60 timesteps x 50M paths x 20 seeds).
  - For each chunk we compute per-strategy per-path PnL, write into a
    50M-element float32 array per strategy per seed, then reshape to
    (500K, 100) and row-mean.
"""
import json
import time
import numpy as np

# -- Parameters ---------------------------------------------------------------
S0 = 50.0
SIGMA = 2.51
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_2W_DAYS = 10
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W = T_3W_DAYS * STEPS_PER_DAY     # 60
N_2W = T_2W_DAYS * STEPS_PER_DAY     # 40

CONTRACT_MULTIPLIER = 3000

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

# The strategy under audit -- 7 positions (PRIOR_FINAL minus the 5 AC underlying).
OPTIMAL_7POS = [
    ("AC_50_CO",  "sell", 50),
    ("AC_45_KO",  "buy",  500),
    ("AC_40_BP",  "sell", 50),
    ("AC_50_P_2", "buy",  50),
    ("AC_50_C_2", "buy",  50),
    ("AC_50_P",   "buy",  50),
    ("AC_50_C",   "buy",  25),
]

# Our shipped recommendation: 5-pos DROP_60C
DROP_60C = [
    ("AC_50_CO",  "sell", 50),
    ("AC_45_KO",  "buy",  500),
    ("AC_40_BP",  "sell", 50),
    ("AC_50_P_2", "buy",  50),
    ("AC_50_C_2", "buy",  50),
]

# Conservative teammate alternative
USER_SAFE = [
    ("AC_50_CO", "sell", 15),
    ("AC_40_BP", "sell", 50),
    ("AC_45_KO", "buy",  60),
    ("AC_50_P",  "buy",  17),
    ("AC_50_P_2","buy",  15),
    ("AC_50_C",  "buy",  15),
]

STRATEGIES = {
    "OPTIMAL_7POS": OPTIMAL_7POS,
    "DROP_60C":     DROP_60C,
    "USER_SAFE":    USER_SAFE,
}

INSTRUMENTS_USED = sorted({sym for s in STRATEGIES.values() for sym, *_ in s})


def per_path_payoffs(S_T, S_2w, min_S):
    """Return dict instrument -> per-path payoff array (float32)."""
    return {
        "AC":         S_T,
        "AC_50_P":    np.maximum(50.0 - S_T, 0.0),
        "AC_50_C":    np.maximum(S_T - 50.0, 0.0),
        "AC_35_P":    np.maximum(35.0 - S_T, 0.0),
        "AC_40_P":    np.maximum(40.0 - S_T, 0.0),
        "AC_45_P":    np.maximum(45.0 - S_T, 0.0),
        "AC_60_C":    np.maximum(S_T - 60.0, 0.0),
        "AC_50_P_2":  np.maximum(50.0 - S_2w, 0.0),
        "AC_50_C_2":  np.maximum(S_2w - 50.0, 0.0),
        "AC_50_CO":   np.where(S_2w >= 50.0,
                               np.maximum(S_T - 50.0, 0.0),
                               np.maximum(50.0 - S_T, 0.0)),
        "AC_40_BP":   np.where(S_T < 40.0,
                               np.float32(10.0),
                               np.float32(0.0)),
        "AC_45_KO":   np.where(min_S > 35.0,
                               np.maximum(45.0 - S_T, 0.0),
                               np.float32(0.0)),
    }


def strategy_per_path_pnl(strategy, payoffs):
    """Per-path PnL of a strategy (float32 array)."""
    n = next(iter(payoffs.values())).shape[0]
    pnl = np.zeros(n, dtype=np.float32)
    for sym, side, vol in strategy:
        bid, ask, _ = QUOTES[sym]
        p = payoffs[sym]
        if side == "buy":
            pnl += np.float32(vol) * (p - np.float32(ask))
        else:
            pnl += np.float32(vol) * (np.float32(bid) - p)
    return pnl


def gen_path_chunk(n_paths, rng):
    """Generate n_paths GBM paths in float32. Returns (S_T, S_2w, min_S)."""
    drift = np.float32(-0.5 * SIGMA * SIGMA * DT)
    vol = np.float32(SIGMA * np.sqrt(DT))
    S = np.full(n_paths, np.float32(S0), dtype=np.float32)
    min_S = S.copy()
    S_2w = None
    for k in range(N_3W):
        # Generate normals as float32 directly
        z = rng.standard_normal(n_paths, dtype=np.float32)
        S = S * np.exp(drift + vol * z)
        np.minimum(min_S, S, out=min_S)
        if k + 1 == N_2W:
            S_2w = S.copy()
    return S, S_2w, min_S


def run_one_seed(seed, n_paths, chunk_size, sims_per_trial, verbose=True):
    """Run one seed, return per-strategy trial-score arrays (float64, multiplied)."""
    n_chunks = n_paths // chunk_size
    n_trials = n_paths // sims_per_trial

    # Per-strategy buffer for per-path PnL across the seed (float32 to save RAM)
    buf = {name: np.empty(n_paths, dtype=np.float32) for name in STRATEGIES}

    rng = np.random.default_rng(seed=seed)
    t0 = time.time()
    for c in range(n_chunks):
        S_T, S_2w, min_S = gen_path_chunk(chunk_size, rng)
        payoffs = per_path_payoffs(S_T, S_2w, min_S)
        for name, strat in STRATEGIES.items():
            chunk_pnl = strategy_per_path_pnl(strat, payoffs)
            buf[name][c * chunk_size:(c + 1) * chunk_size] = chunk_pnl
        if verbose and (c == 0 or c == n_chunks - 1):
            print(f"    [seed {seed}] chunk {c+1}/{n_chunks} done t={time.time()-t0:.1f}s",
                  flush=True)

    # Reshape into (n_trials, sims_per_trial), row-mean, apply ×3000 multiplier
    trial_scores = {}
    for name in STRATEGIES:
        ts = buf[name].reshape(n_trials, sims_per_trial).mean(axis=1)
        trial_scores[name] = (ts.astype(np.float64) * CONTRACT_MULTIPLIER)
    return trial_scores


def stats_for_scores(scores):
    """Return dict of summary stats for a 1D array of trial scores."""
    sorted_scores = np.sort(scores)
    n = len(sorted_scores)
    cvar5_thresh = sorted_scores[int(0.05 * n)]      # 5th-percentile threshold
    cvar5 = sorted_scores[:int(0.05 * n)].mean()     # mean of worst 5%
    cvar1 = sorted_scores[:int(0.01 * n)].mean()
    return {
        "mean":   float(scores.mean()),
        "sd":     float(scores.std(ddof=1)),
        "median": float(np.median(scores)),
        "cvar5":  float(cvar5),
        "cvar1":  float(cvar1),
        "p_pos":  float((scores > 0).mean()),
        "p_100k": float((scores > 100_000).mean()),
        "p_neg100k": float((scores < -100_000).mean()),
        "p_neg1M":   float((scores < -1_000_000).mean()),
        "p_neg500k": float((scores < -500_000).mean()),
        "p_neg200k": float((scores < -200_000).mean()),
        "q01":    float(sorted_scores[int(0.001 * n)]),
        "q05":    float(sorted_scores[int(0.05 * n)]),
        "q25":    float(sorted_scores[int(0.25 * n)]),
        "q50":    float(sorted_scores[int(0.50 * n)]),
        "q75":    float(sorted_scores[int(0.75 * n)]),
        "q95":    float(sorted_scores[int(0.95 * n)]),
        "q99":    float(sorted_scores[int(0.999 * n)]),
        "min":    float(sorted_scores[0]),
        "max":    float(sorted_scores[-1]),
        "sharpe": float(scores.mean() / scores.std(ddof=1)),
    }


def main():
    SEEDS = list(range(1, 21))
    PATHS_PER_SEED = 50_000_000
    CHUNK_SIZE = 5_000_000
    SIMS_PER_TRIAL = 100
    TRIALS_PER_SEED = PATHS_PER_SEED // SIMS_PER_TRIAL  # 500,000

    print(f"Multi-seed reproducibility (R4 manual)")
    print(f"  Seeds:           {len(SEEDS)} ({SEEDS[0]}..{SEEDS[-1]})")
    print(f"  Paths per seed:  {PATHS_PER_SEED:,}")
    print(f"  Total paths:     {len(SEEDS) * PATHS_PER_SEED:,}")
    print(f"  Trials per seed: {TRIALS_PER_SEED:,}")
    print(f"  Strategies:      {list(STRATEGIES.keys())}")
    print()

    # Per-seed stats
    per_seed = {name: [] for name in STRATEGIES}
    # Optionally aggregate trial scores from all seeds (only for bootstrap on
    # one focal strategy to limit RAM: 20 x 500K x 8B = 80 MB per strategy).
    all_trial_scores = {name: np.empty(len(SEEDS) * TRIALS_PER_SEED, dtype=np.float64)
                        for name in STRATEGIES}

    t0 = time.time()
    for i, seed in enumerate(SEEDS):
        t_seed = time.time()
        ts = run_one_seed(seed, PATHS_PER_SEED, CHUNK_SIZE, SIMS_PER_TRIAL,
                          verbose=(i < 2 or i == len(SEEDS) - 1))
        for name in STRATEGIES:
            s = stats_for_scores(ts[name])
            s["seed"] = seed
            per_seed[name].append(s)
            all_trial_scores[name][i * TRIALS_PER_SEED:(i + 1) * TRIALS_PER_SEED] = ts[name]
        elapsed = time.time() - t_seed
        total = time.time() - t0
        eta = (len(SEEDS) - i - 1) * (total / (i + 1))
        print(f"  Seed {seed:>2} done in {elapsed:.1f}s  | total {total/60:.1f}m | ETA {eta/60:.1f}m",
              flush=True)

    # ----- Cross-seed aggregate stats -----
    print(f"\n{'='*100}")
    print("CROSS-SEED AGGREGATE")
    print(f"{'='*100}")

    aggregate = {}
    for name in STRATEGIES:
        means = np.array([s["mean"] for s in per_seed[name]])
        sds   = np.array([s["sd"]   for s in per_seed[name]])
        cvars5 = np.array([s["cvar5"] for s in per_seed[name]])
        sharpes = np.array([s["sharpe"] for s in per_seed[name]])
        ppos = np.array([s["p_pos"] for s in per_seed[name]])
        pneg1m = np.array([s["p_neg1M"] for s in per_seed[name]])
        # Welch t critical for 19 dof at 95% ~ 2.093
        t_crit = 2.093
        n = len(means)
        agg = {
            "mean_of_means":    float(means.mean()),
            "mean_of_means_se": float(means.std(ddof=1) / np.sqrt(n)),
            "mean_of_means_ci95": [float(means.mean() - t_crit * means.std(ddof=1)/np.sqrt(n)),
                                   float(means.mean() + t_crit * means.std(ddof=1)/np.sqrt(n))],
            "mean_of_sds":      float(sds.mean()),
            "mean_of_sds_se":   float(sds.std(ddof=1) / np.sqrt(n)),
            "mean_of_cvar5":    float(cvars5.mean()),
            "mean_of_cvar5_se": float(cvars5.std(ddof=1) / np.sqrt(n)),
            "mean_of_cvar5_ci95": [float(cvars5.mean() - t_crit * cvars5.std(ddof=1)/np.sqrt(n)),
                                    float(cvars5.mean() + t_crit * cvars5.std(ddof=1)/np.sqrt(n))],
            "mean_of_sharpe":   float(sharpes.mean()),
            "sharpe_ci95":      [float(sharpes.mean() - t_crit * sharpes.std(ddof=1)/np.sqrt(n)),
                                  float(sharpes.mean() + t_crit * sharpes.std(ddof=1)/np.sqrt(n))],
            "range_mean":       [float(means.min()), float(means.max())],
            "range_sd":         [float(sds.min()), float(sds.max())],
            "range_cvar5":      [float(cvars5.min()), float(cvars5.max())],
            "range_p_pos":      [float(ppos.min()), float(ppos.max())],
            "range_p_neg1M":    [float(pneg1m.min()), float(pneg1m.max())],
            "mean_p_neg1M":     float(pneg1m.mean()),
            "p_neg1M_se":       float(pneg1m.std(ddof=1) / np.sqrt(n)),
        }
        aggregate[name] = agg
        print(f"\n[{name}]")
        print(f"  E[score]:    ${agg['mean_of_means']:>+12,.0f}  "
              f"SE ${agg['mean_of_means_se']:>+10,.0f}  "
              f"CI95 [${agg['mean_of_means_ci95'][0]:>+12,.0f}, ${agg['mean_of_means_ci95'][1]:>+12,.0f}]")
        print(f"  SD/trial:    ${agg['mean_of_sds']:>+12,.0f}  range [${agg['range_sd'][0]:,.0f}, ${agg['range_sd'][1]:,.0f}]")
        print(f"  CVaR-5%:     ${agg['mean_of_cvar5']:>+12,.0f}  "
              f"SE ${agg['mean_of_cvar5_se']:>+10,.0f}  "
              f"CI95 [${agg['mean_of_cvar5_ci95'][0]:>+12,.0f}, ${agg['mean_of_cvar5_ci95'][1]:>+12,.0f}]")
        print(f"  Sharpe:      {agg['mean_of_sharpe']:>+.4f}  CI95 [{agg['sharpe_ci95'][0]:+.4f}, {agg['sharpe_ci95'][1]:+.4f}]")
        print(f"  P(score<-$1M): mean={agg['mean_p_neg1M']*100:.4f}%  range "
              f"[{agg['range_p_neg1M'][0]*100:.4f}%, {agg['range_p_neg1M'][1]*100:.4f}%]  "
              f"SE={agg['p_neg1M_se']*100:.4f}%")

    # ----- Pairwise ranking check -----
    print(f"\n{'='*100}")
    print("RANKING STABILITY: OPTIMAL_7POS  vs  USER_SAFE  (per seed)")
    print(f"{'='*100}")
    n_wins_7pos = 0
    n_wins_safe = 0
    diffs = []
    for i, seed in enumerate(SEEDS):
        m7 = per_seed["OPTIMAL_7POS"][i]["mean"]
        ms = per_seed["USER_SAFE"][i]["mean"]
        diff = m7 - ms
        diffs.append(diff)
        winner = "OPTIMAL_7POS" if diff > 0 else "USER_SAFE"
        if diff > 0:
            n_wins_7pos += 1
        else:
            n_wins_safe += 1
        print(f"  seed {seed:>2}: 7POS=${m7:>+12,.0f}  SAFE=${ms:>+12,.0f}  "
              f"diff=${diff:>+12,.0f}  winner={winner}")
    print(f"\n  OPTIMAL_7POS wins on {n_wins_7pos}/{len(SEEDS)} seeds")
    diffs = np.array(diffs)
    t_crit = 2.093
    print(f"  Mean diff: ${diffs.mean():+,.0f}  CI95 [${diffs.mean() - t_crit*diffs.std(ddof=1)/np.sqrt(len(diffs)):+,.0f}, "
          f"${diffs.mean() + t_crit*diffs.std(ddof=1)/np.sqrt(len(diffs)):+,.0f}]")

    # Also DROP_60C vs OPTIMAL_7POS
    print(f"\nRANKING STABILITY: DROP_60C  vs  OPTIMAL_7POS")
    n_wins_drop = 0
    diffs2 = []
    for i, seed in enumerate(SEEDS):
        md = per_seed["DROP_60C"][i]["mean"]
        m7 = per_seed["OPTIMAL_7POS"][i]["mean"]
        diff = md - m7
        diffs2.append(diff)
        if diff > 0:
            n_wins_drop += 1
    diffs2 = np.array(diffs2)
    print(f"  DROP_60C beats OPTIMAL_7POS on {n_wins_drop}/{len(SEEDS)} seeds")
    print(f"  Mean diff: ${diffs2.mean():+,.0f}  CI95 [${diffs2.mean() - t_crit*diffs2.std(ddof=1)/np.sqrt(len(diffs2)):+,.0f}, "
          f"${diffs2.mean() + t_crit*diffs2.std(ddof=1)/np.sqrt(len(diffs2)):+,.0f}]")

    # ----- Bootstrap CI on aggregate CVaR-5% (for OPTIMAL_7POS) -----
    print(f"\n{'='*100}")
    print("BOOTSTRAP CI on aggregate CVaR-5% (OPTIMAL_7POS)")
    print(f"{'='*100}")
    rng_b = np.random.default_rng(seed=987654321)
    pool = all_trial_scores["OPTIMAL_7POS"]
    BOOT_REPS = 1000
    BOOT_SIZE = 1_000_000
    t_b = time.time()
    cvars = np.empty(BOOT_REPS, dtype=np.float64)
    for b in range(BOOT_REPS):
        idx = rng_b.integers(0, pool.size, BOOT_SIZE)
        sample = pool[idx]
        # 5th percentile
        thresh = np.partition(sample, BOOT_SIZE // 20)[BOOT_SIZE // 20]
        cvars[b] = sample[sample <= thresh].mean()
    print(f"  Bootstrap done in {time.time()-t_b:.1f}s")
    print(f"  Aggregate pool size: {pool.size:,}")
    print(f"  Bootstrap CVaR-5% : mean ${cvars.mean():+,.0f}  SD ${cvars.std(ddof=1):+,.0f}")
    print(f"                      CI95 [${np.percentile(cvars, 2.5):+,.0f}, "
          f"${np.percentile(cvars, 97.5):+,.0f}]")

    # Repeat for DROP_60C and USER_SAFE
    pool_d = all_trial_scores["DROP_60C"]
    pool_s = all_trial_scores["USER_SAFE"]
    cvars_d = np.empty(BOOT_REPS, dtype=np.float64)
    cvars_s = np.empty(BOOT_REPS, dtype=np.float64)
    for b in range(BOOT_REPS):
        idx = rng_b.integers(0, pool_d.size, BOOT_SIZE)
        sd = pool_d[idx]; thd = np.partition(sd, BOOT_SIZE//20)[BOOT_SIZE//20]
        cvars_d[b] = sd[sd <= thd].mean()
        idx = rng_b.integers(0, pool_s.size, BOOT_SIZE)
        ss = pool_s[idx]; ths = np.partition(ss, BOOT_SIZE//20)[BOOT_SIZE//20]
        cvars_s[b] = ss[ss <= ths].mean()
    print(f"\n  DROP_60C bootstrap CVaR-5% : ${cvars_d.mean():+,.0f}  "
          f"CI95 [${np.percentile(cvars_d, 2.5):+,.0f}, ${np.percentile(cvars_d, 97.5):+,.0f}]")
    print(f"  USER_SAFE bootstrap CVaR-5%: ${cvars_s.mean():+,.0f}  "
          f"CI95 [${np.percentile(cvars_s, 2.5):+,.0f}, ${np.percentile(cvars_s, 97.5):+,.0f}]")

    # ----- Tail probability stability for P(score<-$1M) -----
    # already in aggregate; print summary
    print(f"\n{'='*100}")
    print("TAIL PROBABILITY STABILITY  P(score<-$1M)")
    print(f"{'='*100}")
    for name in STRATEGIES:
        agg = aggregate[name]
        print(f"  [{name}]  mean={agg['mean_p_neg1M']*100:.4f}%  "
              f"range [{agg['range_p_neg1M'][0]*100:.4f}%, {agg['range_p_neg1M'][1]*100:.4f}%]  "
              f"SE={agg['p_neg1M_se']*100:.4f}%")

    # Aggregate (pooled) tail probabilities, precision
    print(f"\n  Pooled (1B trials per strategy):")
    for name in STRATEGIES:
        pool = all_trial_scores[name]
        p1m = (pool < -1_000_000).mean()
        p500k = (pool < -500_000).mean()
        # Wilson-like SE for proportion
        n = pool.size
        se1m = np.sqrt(p1m * (1 - p1m) / n)
        print(f"    [{name}] P(<-$1M) = {p1m*100:.4f}%  +/- {se1m*100*1.96:.4f}% (95% CI)  | "
              f"P(<-$500k) = {p500k*100:.4f}%")

    # ----- Persist results -----
    out = {
        "config": {
            "seeds": SEEDS,
            "paths_per_seed": PATHS_PER_SEED,
            "trials_per_seed": TRIALS_PER_SEED,
            "sims_per_trial": SIMS_PER_TRIAL,
            "sigma": SIGMA, "S0": S0,
            "T_3w_days": T_3W_DAYS, "T_2w_days": T_2W_DAYS,
            "steps_per_day": STEPS_PER_DAY,
            "multiplier": CONTRACT_MULTIPLIER,
        },
        "strategies": {name: STRATEGIES[name] for name in STRATEGIES},
        "per_seed": per_seed,
        "aggregate": aggregate,
        "ranking_7pos_vs_safe": {
            "wins_7pos": n_wins_7pos,
            "wins_safe": n_wins_safe,
            "mean_diff": float(diffs.mean()),
            "ci95_diff": [float(diffs.mean() - 2.093 * diffs.std(ddof=1)/np.sqrt(len(diffs))),
                          float(diffs.mean() + 2.093 * diffs.std(ddof=1)/np.sqrt(len(diffs)))],
        },
        "ranking_drop_vs_7pos": {
            "wins_drop": n_wins_drop,
            "mean_diff": float(diffs2.mean()),
        },
        "bootstrap_cvar5": {
            "OPTIMAL_7POS": {"mean": float(cvars.mean()), "sd": float(cvars.std(ddof=1)),
                             "ci95": [float(np.percentile(cvars, 2.5)),
                                      float(np.percentile(cvars, 97.5))]},
            "DROP_60C": {"mean": float(cvars_d.mean()), "sd": float(cvars_d.std(ddof=1)),
                         "ci95": [float(np.percentile(cvars_d, 2.5)),
                                  float(np.percentile(cvars_d, 97.5))]},
            "USER_SAFE": {"mean": float(cvars_s.mean()), "sd": float(cvars_s.std(ddof=1)),
                          "ci95": [float(np.percentile(cvars_s, 2.5)),
                                   float(np.percentile(cvars_s, 97.5))]},
        },
        "pooled_tails": {
            name: {
                "p_neg1M": float((all_trial_scores[name] < -1_000_000).mean()),
                "p_neg500k": float((all_trial_scores[name] < -500_000).mean()),
                "p_pos": float((all_trial_scores[name] > 0).mean()),
                "p_100k": float((all_trial_scores[name] > 100_000).mean()),
                "mean": float(all_trial_scores[name].mean()),
                "sd":   float(all_trial_scores[name].std(ddof=1)),
            } for name in STRATEGIES
        },
        "runtime_sec": float(time.time() - t0),
    }

    out_path = "trader-logic/round-4/manual/multiseed_v2_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved results to {out_path}")
    print(f"Total runtime: {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()
