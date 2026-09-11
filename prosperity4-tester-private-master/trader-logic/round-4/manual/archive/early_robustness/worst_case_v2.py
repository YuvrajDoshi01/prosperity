"""Worst-case path analysis for OPTIMAL_7POS R4 manual strategy.

Strategy under analysis (7 positions):
    SELL 50 AC_50_CO  (chooser, 2w decision, 3w expiry)
    BUY 500 AC_45_KO  (knock-out put, barrier 35, 3w)
    SELL 50 AC_40_BP  (binary put, pays 10 if S_T<40)
    BUY 50  AC_50_P_2 (2w put)
    BUY 50  AC_50_C_2 (2w call)
    BUY 50  AC_50_P   (3w put)
    BUY 25  AC_50_C   (3w call)

Setup: S0=50, sigma=2.51, GBM, 4 obs/day, 60 steps for 3w. x3000 multiplier.

This script:
  1. Generates 100M GBM paths in chunks
  2. Groups into 1M trials of 100 paths
  3. Identifies worst 50K trials (CVaR-5% bucket)
  4. Conditions path distribution on being-in-worst-bucket
  5. Decomposes per-position contributions to tail loss
  6. Tests specific scenarios (up crash, down crash, mean revert, volatile)
  7. Evaluates candidate hedges by their effect on CVaR-5% and EV

Runtime: ~10-15 min on a single core. Peak RAM ~5GB.
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

# OPTIMAL_7POS strategy under analysis
STRATEGY = [
    ("AC_50_CO",  "sell", 50),
    ("AC_45_KO",  "buy",  500),
    ("AC_40_BP",  "sell", 50),
    ("AC_50_P_2", "buy",  50),
    ("AC_50_C_2", "buy",  50),
    ("AC_50_P",   "buy",  50),
    ("AC_50_C",   "buy",  25),
]


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
        "AC_50_CO":   np.where(S_2w >= 50, np.maximum(S_T - 50, 0.0), np.maximum(50 - S_T, 0.0)),
        "AC_40_BP":   np.where(S_T < 40, 10.0, 0.0),
        "AC_45_KO":   np.where(min_S > 35, np.maximum(45 - S_T, 0.0), 0.0),
    }


def position_pnl(sym, side, vol, payoffs):
    bid, ask, _ = QUOTES[sym]
    p = payoffs[sym]
    if side == "buy":
        return vol * (p - ask)
    else:
        return vol * (bid - p)


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


def main():
    TOTAL_PATHS = 100_000_000
    CHUNK_SIZE = 5_000_000
    N_CHUNKS = TOTAL_PATHS // CHUNK_SIZE
    SIMS_PER_TRIAL = 100
    N_TRIALS = TOTAL_PATHS // SIMS_PER_TRIAL  # 1M trials
    WORST_FRAC = 0.05
    N_WORST = int(N_TRIALS * WORST_FRAC)  # 50K worst trials

    print(f"WORST-CASE PATH ANALYSIS -- OPTIMAL_7POS")
    print(f"=" * 80)
    print(f"  Total paths: {TOTAL_PATHS:,}")
    print(f"  Trials:      {N_TRIALS:,} of {SIMS_PER_TRIAL} paths each")
    print(f"  Worst 5%:    {N_WORST:,} trials")
    print()

    # Position names for tracking
    pos_names = [f"{side.upper()}_{vol}_{sym}" for sym, side, vol in STRATEGY]

    # Storage: per-path PnL per position + path features (S_T, S_2w, min_S)
    # 100M paths x 7 positions x 8 bytes = 5.6 GB - too big
    # Solution: keep total per-path PnL + only path features in memory
    # Then on second pass through worst-trial path indices, recompute per-pos PnL
    print("Pass 1: Generate paths, compute total PnL + cache features")
    pnl_total = np.empty(TOTAL_PATHS, dtype=np.float64)
    sT_all = np.empty(TOTAL_PATHS, dtype=np.float32)
    s2w_all = np.empty(TOTAL_PATHS, dtype=np.float32)
    minS_all = np.empty(TOTAL_PATHS, dtype=np.float32)

    rng = np.random.default_rng(seed=42)
    t0 = time.time()
    for chunk_idx in range(N_CHUNKS):
        t_chunk = time.time()
        S_T, S_2w, min_S = gen_path_chunk(CHUNK_SIZE, rng)
        payoffs = per_path_payoffs(S_T, S_2w, min_S)
        chunk_pnl = np.zeros(CHUNK_SIZE)
        for sym, side, vol in STRATEGY:
            chunk_pnl += position_pnl(sym, side, vol, payoffs)
        start = chunk_idx * CHUNK_SIZE
        pnl_total[start:start + CHUNK_SIZE] = chunk_pnl
        sT_all[start:start + CHUNK_SIZE] = S_T.astype(np.float32)
        s2w_all[start:start + CHUNK_SIZE] = S_2w.astype(np.float32)
        minS_all[start:start + CHUNK_SIZE] = min_S.astype(np.float32)
        elapsed = time.time() - t_chunk
        total = time.time() - t0
        eta = (N_CHUNKS - chunk_idx - 1) * elapsed
        print(f"  Chunk {chunk_idx+1}/{N_CHUNKS}: {elapsed:.1f}s (total {total:.1f}s, ETA {eta:.0f}s)")

    print(f"\nPass 1 done in {time.time()-t0:.1f}s")

    # -- Trial-level scores -----------------------------------------------------
    trial_pnl = pnl_total.reshape(N_TRIALS, SIMS_PER_TRIAL).mean(axis=1)
    trial_scores = trial_pnl * CONTRACT_MULTIPLIER

    mean_score = trial_scores.mean()
    sd_score = trial_scores.std(ddof=1)
    print(f"\nTrial score stats: mean=${mean_score:+,.0f} sd=${sd_score:+,.0f}")
    p_pos = float((trial_scores > 0).mean())
    print(f"  P(score>0) = {p_pos*100:.1f}%")

    # Worst trials
    cutoff = np.quantile(trial_scores, WORST_FRAC)
    worst_mask = trial_scores <= cutoff
    n_worst_actual = int(worst_mask.sum())
    print(f"\nCVaR-5% threshold: ${cutoff:+,.0f}  (n={n_worst_actual:,} trials below)")
    cvar5 = trial_scores[worst_mask].mean()
    print(f"CVaR-5% (mean of worst 5%): ${cvar5:+,.0f}")

    # Worst trial indices
    worst_idx = np.where(worst_mask)[0]

    # Path indices in worst trials: each trial has 100 paths
    # path_idx = trial_idx*100 + path_offset
    # So worst paths = trial_idx*100 + range(100), broadcast
    worst_path_idx = (worst_idx[:, None] * SIMS_PER_TRIAL +
                      np.arange(SIMS_PER_TRIAL)[None, :]).reshape(-1)
    print(f"  Worst paths: {len(worst_path_idx):,}")

    # -- Path conditioning ------------------------------------------------------
    sT_worst = sT_all[worst_path_idx].astype(np.float64)
    s2w_worst = s2w_all[worst_path_idx].astype(np.float64)
    minS_worst = minS_all[worst_path_idx].astype(np.float64)

    sT_full = sT_all.astype(np.float64)
    s2w_full = s2w_all.astype(np.float64)
    minS_full = minS_all.astype(np.float64)

    print(f"\n{'='*80}")
    print("PATH DISTRIBUTION: WORST 5% TRIALS vs OVERALL")
    print(f"{'='*80}")
    print(f"\n{'Feature':<10} {'Stat':<10} {'Worst-5%':>12} {'Overall':>12} {'Delta':>12}")

    for name, w_arr, full_arr in [
        ("S_T",   sT_worst,   sT_full),
        ("S_2w",  s2w_worst,  s2w_full),
        ("min_S", minS_worst, minS_full),
    ]:
        for stat_name, fn in [("mean", np.mean), ("median", np.median),
                              ("std", np.std), ("p1", lambda x: np.percentile(x, 1)),
                              ("p5", lambda x: np.percentile(x, 5)),
                              ("p95", lambda x: np.percentile(x, 95)),
                              ("p99", lambda x: np.percentile(x, 99))]:
            w = fn(w_arr)
            o = fn(full_arr)
            print(f"{name:<10} {stat_name:<10} {w:>12.3f} {o:>12.3f} {w-o:>+12.3f}")
        print()

    # Histograms of S_T in worst trials
    print(f"\n{'='*80}")
    print("S_T HISTOGRAM (worst 5% paths)")
    print(f"{'='*80}")
    bins = [0, 30, 35, 38, 40, 42, 44, 46, 48, 50, 52, 54, 56, 58, 60, 62, 65, 70, 100]
    h_w, _ = np.histogram(sT_worst, bins=bins)
    h_o, _ = np.histogram(sT_full, bins=bins)
    print(f"\n{'Range':<14} {'Worst%':>10} {'Overall%':>10} {'Lift':>10}")
    for i in range(len(bins)-1):
        wp = h_w[i] / len(sT_worst) * 100
        op = h_o[i] / len(sT_full) * 100
        lift = wp / op if op > 0 else float('inf')
        print(f"[{bins[i]:>5},{bins[i+1]:>5}) {wp:>9.2f}% {op:>9.2f}% {lift:>9.2f}x")

    # min_S histogram (KO barrier impact)
    print(f"\n{'='*80}")
    print("min_S HISTOGRAM (worst 5% paths) -- KO barrier=35")
    print(f"{'='*80}")
    bins_min = [0, 25, 30, 32, 34, 35, 36, 38, 40, 42, 45, 48, 50, 100]
    h_w, _ = np.histogram(minS_worst, bins=bins_min)
    h_o, _ = np.histogram(minS_full, bins=bins_min)
    print(f"\n{'Range':<14} {'Worst%':>10} {'Overall%':>10} {'Lift':>10}")
    for i in range(len(bins_min)-1):
        wp = h_w[i] / len(minS_worst) * 100
        op = h_o[i] / len(minS_full) * 100
        lift = wp / op if op > 0 else float('inf')
        print(f"[{bins_min[i]:>5},{bins_min[i+1]:>5}) {wp:>9.2f}% {op:>9.2f}% {lift:>9.2f}x")

    # P(KO knocked out) in worst vs overall
    p_ko_w = float((minS_worst <= 35).mean())
    p_ko_o = float((minS_full <= 35).mean())
    print(f"\nP(min_S <= 35, KO knocked out):  worst={p_ko_w*100:.2f}%  overall={p_ko_o*100:.2f}%")

    # P(BP pays) = P(S_T < 40)
    p_bp_w = float((sT_worst < 40).mean())
    p_bp_o = float((sT_full < 40).mean())
    print(f"P(S_T < 40, BP pays):            worst={p_bp_w*100:.2f}%  overall={p_bp_o*100:.2f}%")

    # P(chooser becomes call vs put) -- chooses call if S_2w >= 50
    p_call_w = float((s2w_worst >= 50).mean())
    p_call_o = float((s2w_full >= 50).mean())
    print(f"P(S_2w >= 50, chooser->call):    worst={p_call_w*100:.2f}%  overall={p_call_o*100:.2f}%")

    # -- Loss attribution per position -----------------------------------------
    print(f"\n{'='*80}")
    print("LOSS ATTRIBUTION PER POSITION (worst 5% paths)")
    print(f"{'='*80}")

    # Recompute per-position PnL for worst paths only
    payoffs_worst = per_path_payoffs(sT_worst, s2w_worst, minS_worst)
    pos_pnl_worst = {}
    for sym, side, vol in STRATEGY:
        key = f"{side.upper()}_{vol}_{sym}"
        pnl = position_pnl(sym, side, vol, payoffs_worst)
        pos_pnl_worst[key] = pnl

    # Also compute for ALL paths (to compare overall mean contribution)
    payoffs_all = per_path_payoffs(sT_full, s2w_full, minS_full)
    pos_pnl_all = {}
    for sym, side, vol in STRATEGY:
        key = f"{side.upper()}_{vol}_{sym}"
        pnl = position_pnl(sym, side, vol, payoffs_all)
        pos_pnl_all[key] = pnl

    print(f"\n{'Position':<28} {'Mean(worst)':>14} {'Mean(all)':>14} {'Delta':>14} {'%total worst':>14}")
    total_w_pp = sum(pos_pnl_worst[k].mean() for k in pos_pnl_worst)  # per-path sum
    total_a_pp = sum(pos_pnl_all[k].mean() for k in pos_pnl_all)

    pos_attrib = {}
    for key in pos_pnl_worst:
        mw = pos_pnl_worst[key].mean()
        ma = pos_pnl_all[key].mean()
        pct = mw / total_w_pp * 100 if total_w_pp != 0 else 0.0
        pos_attrib[key] = {"mean_worst": float(mw), "mean_all": float(ma),
                           "delta": float(mw - ma), "pct_total": float(pct)}
        print(f"{key:<28} {mw*CONTRACT_MULTIPLIER:>+14,.2f} {ma*CONTRACT_MULTIPLIER:>+14,.2f} "
              f"{(mw-ma)*CONTRACT_MULTIPLIER:>+14,.2f} {pct:>13.1f}%")
    print(f"{'TOTAL':<28} {total_w_pp*CONTRACT_MULTIPLIER:>+14,.2f} {total_a_pp*CONTRACT_MULTIPLIER:>+14,.2f}")

    # NOTE: the trial-score CVaR is x3000 of the trial-mean of per-path PnL.
    # Per-path mean over worst paths * 3000 = approx per-path CVaR (different from trial CVaR).
    # The trial-CVaR includes averaging-over-100-paths smoothing.

    # -- Tail risk decomposition (trial-level) ---------------------------------
    print(f"\n{'='*80}")
    print("TAIL RISK DECOMPOSITION (trial level)")
    print(f"{'='*80}")
    print("Per-trial losses: which position dominated?")

    # Compute per-trial position contributions: per-path -> reshape to trials -> mean
    pos_pnl_trial = {}
    # Need per-position per-trial mean. Recompute fully.
    print("Recomputing per-position per-trial mean (chunked)...")
    pos_pnl_full_arrays = {}
    for sym, side, vol in STRATEGY:
        key = f"{side.upper()}_{vol}_{sym}"
        pnl = position_pnl(sym, side, vol, payoffs_all)
        pos_pnl_full_arrays[key] = pnl

    for key, arr in pos_pnl_full_arrays.items():
        pos_pnl_trial[key] = arr.reshape(N_TRIALS, SIMS_PER_TRIAL).mean(axis=1)

    # For worst trials, find dominant losing position
    worst_trial_pos = {key: pos_pnl_trial[key][worst_idx] for key in pos_pnl_trial}

    # For each worst trial, identify the position with the most-negative contribution
    pos_keys = list(pos_pnl_trial.keys())
    n_worst = len(worst_idx)
    pos_matrix = np.stack([worst_trial_pos[k] for k in pos_keys], axis=1)  # (n_worst, n_pos)
    dom_pos_idx = np.argmin(pos_matrix, axis=1)

    print(f"\nDominant negative position in each worst trial:")
    for i, key in enumerate(pos_keys):
        cnt = int((dom_pos_idx == i).sum())
        pct = cnt / n_worst * 100
        avg_contrib = float(pos_matrix[dom_pos_idx == i, i].mean()) * CONTRACT_MULTIPLIER if cnt > 0 else 0.0
        print(f"  {key:<28} {cnt:>8,} ({pct:>5.1f}%)  avg dom contrib: ${avg_contrib:+,.0f}")

    # P(position contributes > 50% of total trial loss in worst trials)
    print(f"\nP(position's share of trial-loss > 50% | worst trial):")
    trial_total_worst = trial_pnl[worst_idx]  # per-path-mean per worst trial (in raw units)
    for key in pos_keys:
        share = worst_trial_pos[key] / trial_total_worst
        # Only meaningful when trial_total_worst < 0
        neg_trial_mask = trial_total_worst < 0
        if neg_trial_mask.sum() == 0:
            continue
        # When trial total is negative, position-share > 50% means
        # position contributes more than half the loss (i.e., position_pnl < 0 and share > 0.5)
        loss_pos_mask = (worst_trial_pos[key] < 0) & neg_trial_mask
        big_share = loss_pos_mask & (worst_trial_pos[key] / trial_total_worst > 0.5)
        p = float(big_share.sum()) / float(neg_trial_mask.sum())
        print(f"  {key:<28} P > 50% share = {p*100:>5.2f}%")

    # -- Specific scenario tests ------------------------------------------------
    print(f"\n{'='*80}")
    print("SPECIFIC SCENARIO TESTS (single-path PnL, x3000)")
    print(f"{'='*80}")

    def eval_scenario(name, S_T_val, S_2w_val, min_S_val):
        S_T_arr = np.array([S_T_val], dtype=np.float64)
        S_2w_arr = np.array([S_2w_val], dtype=np.float64)
        min_S_arr = np.array([min_S_val], dtype=np.float64)
        payoffs = per_path_payoffs(S_T_arr, S_2w_arr, min_S_arr)
        total = 0.0
        breakdown = {}
        for sym, side, vol in STRATEGY:
            key = f"{side.upper()}_{vol}_{sym}"
            pnl = float(position_pnl(sym, side, vol, payoffs)[0]) * CONTRACT_MULTIPLIER
            breakdown[key] = pnl
            total += pnl
        print(f"\n[{name}] S_T={S_T_val} S_2w={S_2w_val} min_S={min_S_val}")
        for k, v in breakdown.items():
            print(f"  {k:<28} = ${v:+,.0f}")
        print(f"  {'TOTAL':<28} = ${total:+,.0f}")
        return total

    eval_scenario("UP_CRASH",          80,  70,  50)
    eval_scenario("UP_CRASH_extreme",  90,  80,  50)
    eval_scenario("DOWN_CRASH_KO",     20,  30,  15)
    eval_scenario("DOWN_CRASH_no_KO",  30,  35,  36)  # min_S>35, KO pays
    eval_scenario("MEAN_REVERT",       50,  50,  45)
    eval_scenario("MEAN_REVERT_p49",   49,  51,  45)
    eval_scenario("STAY_NEAR_50",      52,  48,  44)  # all worth little
    eval_scenario("VOLATILE_END_50",   50,  60,  35.5)
    eval_scenario("STRONG_DOWN_S_T_38",38,  45,  36)  # BP pays, KO pays
    eval_scenario("MOD_DOWN_S_T_42",   42,  46,  40)  # near everything

    # -- Hedge proposal evaluation ---------------------------------------------
    print(f"\n{'='*80}")
    print("HEDGE PROPOSAL EVALUATION")
    print(f"{'='*80}")
    print("Evaluates: how does adding/changing a hedge affect EV and CVaR-5%?")

    # Cache base metric
    base_mean = mean_score
    base_cvar = cvar5
    base_sd = sd_score

    HEDGES = {
        "BUY 5  AC_60_C  (upside cat)":    [("AC_60_C", "buy", 5)],
        "BUY 10 AC_60_C  (upside cat)":    [("AC_60_C", "buy", 10)],
        "BUY 25 AC_60_C  (upside cat)":    [("AC_60_C", "buy", 25)],
        "BUY 50 AC_60_C  (upside cat)":    [("AC_60_C", "buy", 50)],
        "SELL 25 AC_50_CO -> 25 fewer":    [("AC_50_CO", "buy", 25)],  # offset half the chooser short
        "BUY 25 AC_45_P (extra OTM put)":  [("AC_45_P",  "buy", 25)],
        "BUY 50 AC_45_P":                  [("AC_45_P",  "buy", 50)],
        "BUY 25 AC_40_P (deeper put)":     [("AC_40_P",  "buy", 25)],
        "SELL 25 AC_35_P (premium recoup)": [("AC_35_P",  "sell", 25)],
        "BUY 100 AC underlying":           [("AC",       "buy", 100)],
        "SELL 100 AC underlying":          [("AC",       "sell", 100)],
        "ADD GLOBAL_MAX SELL 50 AC_60_C":  [("AC_60_C",  "sell", 50)],
    }

    # For each hedge, compute new per-path PnL = base + hedge contribution
    def hedge_metrics(hedge_legs):
        # hedge contribution per-path
        hedge_pp = np.zeros(TOTAL_PATHS, dtype=np.float64)
        # need a payoffs_all-like structure but it doesn't fit in memory...
        # Compute in chunks
        chunk_size_h = 5_000_000
        for s in range(0, TOTAL_PATHS, chunk_size_h):
            e = min(s + chunk_size_h, TOTAL_PATHS)
            sT = sT_all[s:e].astype(np.float64)
            s2w = s2w_all[s:e].astype(np.float64)
            mS = minS_all[s:e].astype(np.float64)
            p = per_path_payoffs(sT, s2w, mS)
            for sym, side, vol in hedge_legs:
                hedge_pp[s:e] += position_pnl(sym, side, vol, p)
        new_pp = pnl_total + hedge_pp
        new_trial = new_pp.reshape(N_TRIALS, SIMS_PER_TRIAL).mean(axis=1) * CONTRACT_MULTIPLIER
        new_mean = float(new_trial.mean())
        new_sd = float(new_trial.std(ddof=1))
        new_cvar_thresh = np.quantile(new_trial, WORST_FRAC)
        new_cvar = float(new_trial[new_trial <= new_cvar_thresh].mean())
        new_p_pos = float((new_trial > 0).mean())
        return new_mean, new_sd, new_cvar, new_p_pos

    print(f"\n{'Hedge':<40} {'Mean':>12} {'dEV':>10} {'SD':>12} {'CVaR-5%':>14} {'dCVaR':>12} {'P>0':>8}")
    print(f"{'BASE (no hedge)':<40} ${base_mean:>+11,.0f} {'':>10} ${base_sd:>+11,.0f} ${base_cvar:>+13,.0f} {'':>12} {p_pos*100:>6.1f}%")

    hedge_results = {"base": {"mean": float(base_mean), "sd": float(base_sd),
                              "cvar5": float(base_cvar), "p_pos": float(p_pos)}}
    for label, legs in HEDGES.items():
        nm, nsd, nc, npp = hedge_metrics(legs)
        dev = nm - base_mean
        dcvar = nc - base_cvar
        print(f"{label:<40} ${nm:>+11,.0f} ${dev:>+9,.0f} ${nsd:>+11,.0f} ${nc:>+13,.0f} ${dcvar:>+11,.0f} {npp*100:>6.1f}%")
        hedge_results[label] = {"mean": nm, "sd": nsd, "cvar5": nc, "p_pos": npp,
                                "delta_ev": dev, "delta_cvar": dcvar}

    # Save JSON
    out = {
        "strategy": [{"sym": s, "side": d, "vol": v} for s, d, v in STRATEGY],
        "n_paths": TOTAL_PATHS,
        "n_trials": N_TRIALS,
        "base": {
            "mean": float(base_mean), "sd": float(base_sd),
            "median": float(np.median(trial_scores)),
            "p_pos": float(p_pos),
            "cvar5_threshold": float(cutoff),
            "cvar5_mean": float(cvar5),
        },
        "worst_path_features": {
            "S_T":   {"mean": float(sT_worst.mean()), "median": float(np.median(sT_worst)),
                      "std": float(sT_worst.std()), "p1": float(np.percentile(sT_worst, 1)),
                      "p99": float(np.percentile(sT_worst, 99))},
            "S_2w":  {"mean": float(s2w_worst.mean()), "median": float(np.median(s2w_worst)),
                      "std": float(s2w_worst.std())},
            "min_S": {"mean": float(minS_worst.mean()), "median": float(np.median(minS_worst)),
                      "std": float(minS_worst.std())},
            "P_KO_knocked_out": p_ko_w, "P_BP_pays": p_bp_w, "P_chooser_call": p_call_w,
        },
        "overall_path_features": {
            "P_KO_knocked_out": p_ko_o, "P_BP_pays": p_bp_o, "P_chooser_call": p_call_o,
        },
        "position_attribution_worst_paths": pos_attrib,
        "hedges": hedge_results,
    }
    with open("trader-logic/round-4/manual/worst_case_v2_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to worst_case_v2_results.json")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
