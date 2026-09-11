"""
GPU-accelerated full-grid sweep over R4 manual strategy space using PyTorch.
RTX 4070 Ti: ~100M paths/sec end-to-end including stats.

Approach:
  1. Generate paths in chunks on GPU
  2. Compute 12-instrument payoff matrix on GPU
  3. Batch-evaluate ALL candidates: positions @ payoffs - cost = per-path PnLs
  4. Reshape to trials of 100, mean -> stats per candidate
  5. Pareto frontier on (mean, CVaR-5%, CVaR-2%)

Usage:
    python gpu_sweep.py                      # 5M paths, full grid (~5000 candidates)
    python gpu_sweep.py --paths 50000000     # 50M paths, tighter SE
    python gpu_sweep.py --grid huge          # ~50000 candidates
    python gpu_sweep.py --grid coarse        # ~1000 candidates
"""
import argparse
import itertools
import json
import time
from typing import List, Tuple

import numpy as np
import torch

# ────────────────────────────────────────────────────────────────────────────
# MODEL CONFIG
# ────────────────────────────────────────────────────────────────────────────
S0 = 50.0
SIGMA = 2.51
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_2W_DAYS = 10
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W_STEPS = T_3W_DAYS * STEPS_PER_DAY
N_2W_STEPS = T_2W_DAYS * STEPS_PER_DAY
CONTRACT_MULTIPLIER = 3000
SIMS_PER_TRIAL = 100

QUOTES = {
    "AC":          (49.975, 50.025, 200),
    "AC_50_P":     (12.000, 12.050,  50),
    "AC_50_C":     (12.000, 12.050,  50),
    "AC_35_P":     ( 4.330,  4.350,  50),
    "AC_40_P":     ( 6.500,  6.550,  50),
    "AC_45_P":     ( 9.050,  9.100,  50),
    "AC_60_C":     ( 8.800,  8.850,  50),
    "AC_50_P_2":   ( 9.700,  9.750,  50),
    "AC_50_C_2":   ( 9.700,  9.750,  50),
    "AC_50_CO":    (22.200, 22.300,  50),
    "AC_40_BP":    ( 5.000,  5.100,  50),
    "AC_45_KO":    ( 0.150,  0.175, 500),
}
INSTR = list(QUOTES.keys())
N_INSTR = len(INSTR)
LIMITS = np.array([QUOTES[s][2] for s in INSTR], dtype=np.int32)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
DTYPE = torch.float32


def gen_paths_gpu(n: int, gen: torch.Generator) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Generate n GBM paths on GPU. Returns (S_T, S_2w, min_S)."""
    drift_step = -0.5 * SIGMA * SIGMA * DT
    vol_step = SIGMA * (DT ** 0.5)
    S = torch.full((n,), S0, dtype=DTYPE, device=DEVICE)
    min_S = S.clone()
    S_2w = None
    for k in range(N_3W_STEPS):
        z = torch.randn(n, generator=gen, dtype=DTYPE, device=DEVICE)
        S = S * torch.exp(drift_step + vol_step * z)
        torch.minimum(min_S, S, out=min_S)
        if k + 1 == N_2W_STEPS:
            S_2w = S.clone()
    return S, S_2w, min_S


def compute_payoff_matrix(S_T: torch.Tensor, S_2w: torch.Tensor,
                          min_S: torch.Tensor) -> torch.Tensor:
    """Build (12, n) payoff matrix on GPU."""
    n = S_T.shape[0]
    M = torch.zeros((N_INSTR, n), dtype=DTYPE, device=DEVICE)
    M[INSTR.index("AC")]         = S_T
    M[INSTR.index("AC_50_P")]    = torch.clamp(50 - S_T, min=0.0)
    M[INSTR.index("AC_50_C")]    = torch.clamp(S_T - 50, min=0.0)
    M[INSTR.index("AC_35_P")]    = torch.clamp(35 - S_T, min=0.0)
    M[INSTR.index("AC_40_P")]    = torch.clamp(40 - S_T, min=0.0)
    M[INSTR.index("AC_45_P")]    = torch.clamp(45 - S_T, min=0.0)
    M[INSTR.index("AC_60_C")]    = torch.clamp(S_T - 60, min=0.0)
    M[INSTR.index("AC_50_P_2")]  = torch.clamp(50 - S_2w, min=0.0)
    M[INSTR.index("AC_50_C_2")]  = torch.clamp(S_2w - 50, min=0.0)
    # Chooser: ITM-side at t=2w
    M[INSTR.index("AC_50_CO")] = torch.where(
        S_2w >= 50,
        torch.clamp(S_T - 50, min=0.0),
        torch.clamp(50 - S_T, min=0.0)
    )
    M[INSTR.index("AC_40_BP")] = torch.where(
        S_T < 40,
        torch.full_like(S_T, 10.0),
        torch.zeros_like(S_T)
    )
    # KO put: pay only if barrier (35) never breached. min_S >= 35 = survives.
    M[INSTR.index("AC_45_KO")] = torch.where(
        min_S >= 35,
        torch.clamp(45 - S_T, min=0.0),
        torch.zeros_like(S_T)
    )
    return M


def build_strategy_grid(grid_size: str = "full") -> Tuple[np.ndarray, List[str]]:
    """Returns (positions [N, 12], names list)."""
    if grid_size == "coarse":
        chooser_qs = [-50, -30, 0]
        bp_qs      = [-50, -30, 0]
        ko_qs      = [200, 300, 500]
        p2_qs      = [50]
        c2_qs      = [50]
        p50_qs     = [0, 25, 50]
        p45_qs     = [0, 25, 50]
        c50_qs     = [0, 15, 25, 30]
        p35_qs     = [0]
        p40_qs     = [0]
        c60_qs     = [0]
        ac_qs      = [0]
    elif grid_size == "full":
        # ~6,500 candidates — focused on the core 4 sells/buys + hedges
        chooser_qs = [-50, -30, 0]
        bp_qs      = [-50, -30, 0]
        ko_qs      = [0, 200, 300, 400, 500]
        p2_qs      = [50]                    # always max (positive edge)
        c2_qs      = [50]                    # always max (positive edge)
        p50_qs     = [0, 25, 50]
        p45_qs     = [0, 25, 50]
        c50_qs     = [0, 15, 25, 30]
        p35_qs     = [-25, 0, 25]
        p40_qs     = [0]
        c60_qs     = [-50, 0]
        ac_qs      = [0]
    elif grid_size == "huge":
        # ~30,000 candidates — wider sweep
        chooser_qs = [-50, -40, -30, -20, 0]
        bp_qs      = [-50, -40, -30, 0]
        ko_qs      = [0, 100, 200, 300, 400, 500]
        p2_qs      = [25, 50]
        c2_qs      = [25, 50]
        p50_qs     = [0, 25, 50]
        p45_qs     = [0, 25, 50]
        c50_qs     = [0, 15, 25, 30, 50]
        p35_qs     = [-25, 0, 25]
        p40_qs     = [0]
        c60_qs     = [-50, 0]
        ac_qs      = [0]
    else:
        raise ValueError(f"unknown grid {grid_size}")

    rows = []
    names = []
    for co, bp, ko, p2, c2, p50, p45, c50, p35, p40, c60, ac in itertools.product(
            chooser_qs, bp_qs, ko_qs, p2_qs, c2_qs, p50_qs, p45_qs, c50_qs,
            p35_qs, p40_qs, c60_qs, ac_qs):
        v = np.zeros(N_INSTR, dtype=np.int32)
        v[INSTR.index("AC_50_CO")]  = co
        v[INSTR.index("AC_40_BP")]  = bp
        v[INSTR.index("AC_45_KO")]  = ko
        v[INSTR.index("AC_50_P_2")] = p2
        v[INSTR.index("AC_50_C_2")] = c2
        v[INSTR.index("AC_50_P")]   = p50
        v[INSTR.index("AC_45_P")]   = p45
        v[INSTR.index("AC_50_C")]   = c50
        v[INSTR.index("AC_35_P")]   = p35
        v[INSTR.index("AC_40_P")]   = p40
        v[INSTR.index("AC_60_C")]   = c60
        v[INSTR.index("AC")]        = ac
        if np.all(v == 0): continue
        if np.any(np.abs(v) > LIMITS): continue
        rows.append(v)
        names.append(f"CO{co}_BP{bp}_KO{ko}_P2{p2}_C2{c2}_P50{p50}_P45{p45}_C50{c50}"
                     + (f"_P35{p35:+d}" if p35 else "")
                     + (f"_C60{c60:+d}" if c60 else ""))

    # Add canonical references
    refs = {
        "REF_DROP_60C":    {"AC_50_CO":-50, "AC_45_KO":+500, "AC_40_BP":-50, "AC_50_P_2":+50, "AC_50_C_2":+50},
        "REF_OPTIMAL_7":   {"AC_50_CO":-50, "AC_45_KO":+500, "AC_40_BP":-50, "AC_50_P_2":+50, "AC_50_C_2":+50, "AC_50_P":+50, "AC_50_C":+25},
        "REF_DOM_NICE":    {"AC_50_CO":-50, "AC_45_KO":+500, "AC_40_BP":-50, "AC_50_P_2":+50, "AC_50_C_2":+50, "AC_45_P":+50, "AC_50_C":+30},
        "REF_DOM_CLEAN2":  {"AC_50_CO":-50, "AC_45_KO":+500, "AC_40_BP":-50, "AC_50_P_2":+50, "AC_50_C_2":+45, "AC_45_P":+50, "AC_50_C":+25},
        "REF_USER_SAFE":   {"AC_50_CO":-15, "AC_40_BP":-50, "AC_45_KO":+60, "AC_50_P":+17, "AC_50_P_2":+15, "AC_50_C":+15},
    }
    for ref_name, ref_pos in refs.items():
        v = np.zeros(N_INSTR, dtype=np.int32)
        for sym, q in ref_pos.items():
            v[INSTR.index(sym)] = q
        rows.append(v)
        names.append(ref_name)

    return np.array(rows, dtype=np.int32), names


def sweep(positions: np.ndarray, names: List[str], n_paths: int, seed: int,
          chunk_paths: int = 5_000_000, sims_per_trial: int = SIMS_PER_TRIAL,
          strat_batch: int = 2000):
    """Evaluate all positions on shared paths.

    For memory safety on GPU, processes strategies in batches of `strat_batch`.
    For each chunk of paths, compute payoff matrix once, then loop strategy batches.
    """
    n_strats = len(positions)
    if n_paths % chunk_paths != 0:
        raise ValueError(f"n_paths ({n_paths}) must be divisible by chunk_paths ({chunk_paths})")
    if chunk_paths % sims_per_trial != 0:
        raise ValueError(f"chunk_paths must be divisible by sims_per_trial")
    if n_paths % sims_per_trial != 0:
        raise ValueError(f"n_paths must be divisible by sims_per_trial")

    n_chunks = n_paths // chunk_paths
    n_trials_total = n_paths // sims_per_trial
    n_trials_per_chunk = chunk_paths // sims_per_trial

    print(f"\nGPU sweep: {n_strats:,} strategies x {n_paths:,} paths "
          f"({n_trials_total:,} trials per strategy)")
    print(f"  Chunks:        {n_chunks} of {chunk_paths:,} paths")
    print(f"  Strat batches: {(n_strats + strat_batch - 1) // strat_batch} of up to {strat_batch}")
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        print(f"  GPU mem:       {free/1e9:.1f}/{total/1e9:.1f} GB free")
    # Memory check on CPU side for trial_scores array
    bytes_needed = n_strats * n_trials_total * 4
    print(f"  trial_scores:  {bytes_needed/1e9:.1f} GB CPU memory needed")
    if bytes_needed > 32_000_000_000:  # 32 GB safety margin
        raise MemoryError(
            f"trial_scores would need {bytes_needed/1e9:.1f} GB. "
            f"Reduce grid size or n_trials. Current: {n_strats:,} strats x "
            f"{n_trials_total:,} trials. Try grid='coarse' or fewer paths.")

    # Move position matrix and quotes to GPU (once)
    pos_gpu = torch.tensor(positions, dtype=DTYPE, device=DEVICE)        # (N, 12)
    bid_gpu = torch.tensor([QUOTES[s][0] for s in INSTR], dtype=DTYPE, device=DEVICE)
    ask_gpu = torch.tensor([QUOTES[s][1] for s in INSTR], dtype=DTYPE, device=DEVICE)

    # Per-strategy fixed cost: q_pos · ask - q_neg · bid
    # PnL_per_path = positions @ payoffs - cost
    pos_pos = torch.clamp(pos_gpu, min=0.0)
    pos_neg = torch.clamp(-pos_gpu, min=0.0)
    cost_gpu = pos_pos @ ask_gpu - pos_neg @ bid_gpu                    # (N,)

    # Pre-allocate all trial scores on CPU (numpy, float32)
    trial_scores = np.empty((n_strats, n_trials_total), dtype=np.float32)

    rng_seeds = [seed + ci for ci in range(n_chunks)]
    t0 = time.time()
    for ci in range(n_chunks):
        gen = torch.Generator(device=DEVICE).manual_seed(rng_seeds[ci])
        S_T, S_2w, min_S = gen_paths_gpu(chunk_paths, gen)
        M = compute_payoff_matrix(S_T, S_2w, min_S)  # (12, chunk_paths)

        # Process strategies in batches to fit GPU memory
        for s_start in range(0, n_strats, strat_batch):
            s_end = min(s_start + strat_batch, n_strats)
            batch_pos = pos_gpu[s_start:s_end]               # (B, 12)
            batch_cost = cost_gpu[s_start:s_end]             # (B,)
            # PnL: (B, 12) @ (12, P) - (B, 1) -> (B, P)
            pnl = batch_pos @ M - batch_cost.unsqueeze(1)
            # Reshape to (B, n_trials_per_chunk, sims_per_trial); mean over axis 2
            trial_chunk = pnl.view(s_end - s_start, n_trials_per_chunk, sims_per_trial).mean(dim=2)
            trial_chunk *= CONTRACT_MULTIPLIER
            # CPU
            tstart = ci * n_trials_per_chunk
            trial_scores[s_start:s_end, tstart:tstart + n_trials_per_chunk] = trial_chunk.cpu().numpy()
            del pnl, trial_chunk

        del S_T, S_2w, min_S, M
        torch.cuda.empty_cache()

        if (ci + 1) % max(1, n_chunks // 10) == 0:
            elapsed = time.time() - t0
            eta = elapsed * (n_chunks - ci - 1) / (ci + 1)
            print(f"  chunk {ci+1:>3}/{n_chunks} | elapsed {elapsed:>6.1f}s | ETA {eta:>6.0f}s")

    print(f"\nPath gen + per-strat PnL complete in {time.time()-t0:.0f}s "
          f"({n_strats * n_paths / (time.time()-t0) / 1e6:.1f}M strat-paths/sec)")

    print("Computing stats...")
    t1 = time.time()
    means   = trial_scores.mean(axis=1)
    sds     = trial_scores.std(axis=1, ddof=1)
    medians = np.median(trial_scores, axis=1)
    pct_pos = (trial_scores > 0).mean(axis=1) * 100

    sorted_scores = np.sort(trial_scores, axis=1)
    n_t = sorted_scores.shape[1]
    p1, p2, p5, p10 = max(1, n_t // 100), max(1, n_t * 2 // 100), max(1, n_t * 5 // 100), max(1, n_t * 10 // 100)
    cvar1  = sorted_scores[:, :p1].mean(axis=1)
    cvar2  = sorted_scores[:, :p2].mean(axis=1)
    cvar5  = sorted_scores[:, :p5].mean(axis=1)
    cvar10 = sorted_scores[:, :p10].mean(axis=1)
    print(f"Stats in {time.time()-t1:.1f}s")

    return {
        "names": names, "positions": positions,
        "mean": means, "sd": sds, "median": medians, "pct_pos": pct_pos,
        "cvar1": cvar1, "cvar2": cvar2, "cvar5": cvar5, "cvar10": cvar10,
        "n_trials": n_t,
    }


def find_pareto_3d(means, cvar5, cvar2):
    """Pareto-optimal indices on (mean^, cvar5^, cvar2^)."""
    n = len(means)
    pareto = np.ones(n, dtype=bool)
    for i in range(n):
        if not pareto[i]: continue
        better = ((means >= means[i]) & (cvar5 >= cvar5[i]) & (cvar2 >= cvar2[i])
                  & ((means > means[i]) | (cvar5 > cvar5[i]) | (cvar2 > cvar2[i])))
        better[i] = False
        if better.any(): pareto[i] = False
    return np.where(pareto)[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", type=int, default=5_000_000)
    parser.add_argument("--chunk", type=int, default=1_000_000,
                        help="Paths per GPU chunk (default 1M; smaller = less GPU memory)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--grid", choices=["coarse", "full", "huge"], default="full")
    parser.add_argument("--strat_batch", type=int, default=500,
                        help="Strategies per GPU batch (default 500; with chunk=1M needs ~2GB)")
    parser.add_argument("--out", type=str, default="gpu_sweep_results.json")
    args = parser.parse_args()

    print("=" * 100)
    print("GPU FULL-GRID SWEEP")
    print(f"  Backend: PyTorch on {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"  S0={S0} sigma={SIGMA} T_3w={T_3W_DAYS}td T_2w={T_2W_DAYS}td  multiplier x{CONTRACT_MULTIPLIER}")
    print("=" * 100)

    positions, names = build_strategy_grid(args.grid)
    print(f"\nGrid: {args.grid}  ->  {len(names):,} candidates")

    results = sweep(positions, names, args.paths, args.seed, args.chunk, strat_batch=args.strat_batch)

    print("\nFinding Pareto frontier on (mean, CVaR-5%, CVaR-2%)...")
    t = time.time()
    pareto_idx = find_pareto_3d(results["mean"], results["cvar5"], results["cvar2"])
    print(f"  {len(pareto_idx)} Pareto-optimal strategies in {time.time()-t:.1f}s")

    # Top 30 by mean
    print("\n" + "=" * 150)
    print("TOP 30 BY E[score]")
    print("=" * 150)
    print(f"{'Rank':>4} {'Strategy':<48} {'Mean':>12} {'Median':>12} {'SD':>11} {'Sharpe':>7} "
          f"{'P>0':>5} {'CVaR-5%':>13} {'CVaR-2%':>13} Pareto?")
    sorted_idx = np.argsort(-results["mean"])[:30]
    for rank, i in enumerate(sorted_idx, 1):
        sharpe = results["mean"][i] / results["sd"][i] if results["sd"][i] > 0 else 0
        is_pareto = i in pareto_idx
        flag = " **" if is_pareto else ""
        print(f"{rank:>4} {names[i][:46]:<48} ${results['mean'][i]:>+11,.0f} "
              f"${results['median'][i]:>+11,.0f} ${results['sd'][i]:>10,.0f} {sharpe:>7.4f} "
              f"{results['pct_pos'][i]:>4.1f}% ${results['cvar5'][i]:>+12,.0f} "
              f"${results['cvar2'][i]:>+12,.0f}{flag}")

    print("\n" + "=" * 150)
    print(f"PARETO FRONTIER ({len(pareto_idx)} strategies, sorted by mean, top 50)")
    print("=" * 150)
    pareto_sorted = pareto_idx[np.argsort(-results["mean"][pareto_idx])][:50]
    print(f"{'Strategy':<60} {'Mean':>12} {'SD':>11} {'Sharpe':>7} {'CVaR-5%':>13} {'CVaR-2%':>13}")
    for i in pareto_sorted:
        sharpe = results["mean"][i] / results["sd"][i] if results["sd"][i] > 0 else 0
        pos_str = "  ".join([f"{INSTR[j]}={int(positions[i, j])}"
                              for j in range(N_INSTR) if positions[i, j] != 0])
        print(f"{pos_str[:58]:<60} ${results['mean'][i]:>+11,.0f} ${results['sd'][i]:>10,.0f} "
              f"{sharpe:>7.4f} ${results['cvar5'][i]:>+12,.0f} ${results['cvar2'][i]:>+12,.0f}")

    # JSON
    out = {
        "n_strategies": len(names), "n_paths_per_strategy": args.paths,
        "n_trials_per_strategy": int(results["n_trials"]),
        "grid": args.grid, "seed": args.seed,
        "top_30_by_mean": [
            {
                "rank": rank, "name": names[i],
                "positions": {INSTR[j]: int(positions[i, j])
                              for j in range(N_INSTR) if positions[i, j] != 0},
                "mean": float(results["mean"][i]), "median": float(results["median"][i]),
                "sd": float(results["sd"][i]),
                "sharpe": float(results["mean"][i] / results["sd"][i]) if results["sd"][i] > 0 else 0,
                "pct_positive": float(results["pct_pos"][i]),
                "cvar1": float(results["cvar1"][i]), "cvar2": float(results["cvar2"][i]),
                "cvar5": float(results["cvar5"][i]), "cvar10": float(results["cvar10"][i]),
                "is_pareto": bool(i in pareto_idx),
            }
            for rank, i in enumerate(np.argsort(-results["mean"])[:30], 1)
        ],
        "pareto_frontier": [
            {
                "name": names[i],
                "positions": {INSTR[j]: int(positions[i, j])
                              for j in range(N_INSTR) if positions[i, j] != 0},
                "mean": float(results["mean"][i]), "sd": float(results["sd"][i]),
                "cvar2": float(results["cvar2"][i]), "cvar5": float(results["cvar5"][i]),
            }
            for i in pareto_sorted
        ],
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
