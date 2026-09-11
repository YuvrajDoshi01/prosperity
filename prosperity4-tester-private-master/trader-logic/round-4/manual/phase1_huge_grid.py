"""Phase 1: Huge grid sweep on GPU with strategy batching for memory.

50,000+ candidates x 50M paths each. Memory-safe: processes strategies in
batches of 500, regenerating paths per batch (GPU is fast enough that this
costs little). Outputs top 200 by various criteria for Phase 2.
"""
import argparse
import itertools
import json
import time
from pathlib import Path

import numpy as np
import torch

S0 = 50.0
SIGMA = 2.51
DT = 1.0 / (252 * 4)
N_3W = 60
N_2W = 40
CONTRACT_MULTIPLIER = 3000
SIMS_PER_TRIAL = 100
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
DTYPE = torch.float32

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


def gen_paths(n, gen):
    drift = -0.5 * SIGMA * SIGMA * DT
    vol = SIGMA * (DT ** 0.5)
    S = torch.full((n,), S0, dtype=DTYPE, device=DEVICE)
    min_S = S.clone()
    S_2w = None
    for k in range(N_3W):
        z = torch.randn(n, generator=gen, dtype=DTYPE, device=DEVICE)
        S = S * torch.exp(drift + vol * z)
        torch.minimum(min_S, S, out=min_S)
        if k+1 == N_2W: S_2w = S.clone()
    return S, S_2w, min_S


def compute_payoff_matrix(S_T, S_2w, min_S):
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
    M[INSTR.index("AC_50_CO")] = torch.where(S_2w >= 50, torch.clamp(S_T - 50, min=0.0), torch.clamp(50 - S_T, min=0.0))
    M[INSTR.index("AC_40_BP")] = torch.where(S_T < 40, torch.full_like(S_T, 10.0), torch.zeros_like(S_T))
    M[INSTR.index("AC_45_KO")] = torch.where(min_S >= 35, torch.clamp(45 - S_T, min=0.0), torch.zeros_like(S_T))
    return M


def build_huge_grid():
    """~30,000 candidates focused on plausible Pareto-optimal regions."""
    chooser_qs = [-50, -40, -30, -20, -10, 0]      # 6
    bp_qs      = [-50, -40, -30, -20, 0]            # 5
    ko_qs      = [0, 100, 200, 300, 400, 500]       # 6
    p2_qs      = [25, 50]                            # 2 (high-edge, near-max)
    c2_qs      = [25, 50]                            # 2
    p50_qs     = [0, 25, 50]                         # 3
    p45_qs     = [0, 25, 50]                         # 3
    p35_qs     = [0, 25, 50]                         # 3 (BUY only — DOM_NICE_v2)
    c50_qs     = [0, 15, 25, 30]                     # 4
    p40_qs     = [0, 25, 50]                         # 3
    c60_qs     = [0]                                 # 1 (already known dominated)
    ac_qs      = [0]                                 # 1

    # Total = 6*5*6*2*2*3*3*3*4*3*1*1 = 116,640 (will dedupe)
    # Cap any vector that exceeds limits

    rows = []
    names = []
    for co, bp, ko, p2, c2, p50, p45, p35, c50, p40, c60, ac in itertools.product(
            chooser_qs, bp_qs, ko_qs, p2_qs, c2_qs, p50_qs, p45_qs, p35_qs,
            c50_qs, p40_qs, c60_qs, ac_qs):
        v = np.zeros(N_INSTR, dtype=np.int32)
        v[INSTR.index("AC_50_CO")]  = co
        v[INSTR.index("AC_40_BP")]  = bp
        v[INSTR.index("AC_45_KO")]  = ko
        v[INSTR.index("AC_50_P_2")] = p2
        v[INSTR.index("AC_50_C_2")] = c2
        v[INSTR.index("AC_50_P")]   = p50
        v[INSTR.index("AC_45_P")]   = p45
        v[INSTR.index("AC_35_P")]   = p35
        v[INSTR.index("AC_50_C")]   = c50
        v[INSTR.index("AC_40_P")]   = p40
        v[INSTR.index("AC_60_C")]   = c60
        v[INSTR.index("AC")]        = ac
        if np.all(v == 0): continue
        if np.any(np.abs(v) > LIMITS): continue
        rows.append(v)
        names.append(f"CO{co}_BP{bp}_KO{ko}_P2{p2}_C2{c2}_P50{p50}_P45{p45}_P35{p35}_C50{c50}_P40{p40}")

    # Add canonical references
    refs = {
        "REF_DROP_60C":     {"AC_50_CO":-50, "AC_45_KO":+500, "AC_40_BP":-50, "AC_50_P_2":+50, "AC_50_C_2":+50},
        "REF_DOM_NICE":     {"AC_50_CO":-50, "AC_45_KO":+500, "AC_40_BP":-50, "AC_50_P_2":+50, "AC_50_C_2":+50, "AC_45_P":+50, "AC_50_C":+30},
        "REF_DOM_NICE_v2":  {"AC_50_CO":-50, "AC_45_KO":+500, "AC_40_BP":-50, "AC_50_P_2":+50, "AC_50_C_2":+50, "AC_35_P":+50},
        "REF_USER_SAFE":    {"AC_50_CO":-15, "AC_40_BP":-50, "AC_45_KO":+60, "AC_50_P":+17, "AC_50_P_2":+15, "AC_50_C":+15},
    }
    for ref_name, ref_pos in refs.items():
        v = np.zeros(N_INSTR, dtype=np.int32)
        for sym, q in ref_pos.items(): v[INSTR.index(sym)] = q
        rows.append(v)
        names.append(ref_name)

    return np.array(rows, dtype=np.int32), names


def sweep_streaming(positions, names, n_paths, seed, chunk_paths, strat_batch_size):
    """Process strategies in batches, computing stats per batch.
    Saves only summary stats (no full trial array)."""
    n_strats = len(positions)
    n_chunks = n_paths // chunk_paths
    n_trials_total = n_paths // SIMS_PER_TRIAL
    n_trials_per_chunk = chunk_paths // SIMS_PER_TRIAL
    n_strat_batches = (n_strats + strat_batch_size - 1) // strat_batch_size

    # Load quotes onto GPU once
    bid_gpu = torch.tensor([QUOTES[s][0] for s in INSTR], dtype=DTYPE, device=DEVICE)
    ask_gpu = torch.tensor([QUOTES[s][1] for s in INSTR], dtype=DTYPE, device=DEVICE)

    # Result accumulators (small per-strategy stats)
    means = np.empty(n_strats, dtype=np.float64)
    sds = np.empty(n_strats, dtype=np.float64)
    medians = np.empty(n_strats, dtype=np.float64)
    pct_pos = np.empty(n_strats, dtype=np.float64)
    cvar1 = np.empty(n_strats, dtype=np.float64)
    cvar2 = np.empty(n_strats, dtype=np.float64)
    cvar5 = np.empty(n_strats, dtype=np.float64)
    cvar10 = np.empty(n_strats, dtype=np.float64)

    print(f"Phase 1 sweep: {n_strats:,} strategies x {n_paths:,} paths "
          f"({n_trials_total:,} trials/strat)")
    print(f"  Strategy batches: {n_strat_batches} of {strat_batch_size}")
    print(f"  Path chunks: {n_chunks} of {chunk_paths:,}")
    print(f"  Total work: {n_strats*n_paths/1e9:.1f}B path-evals")

    t0 = time.time()
    for sb_i in range(n_strat_batches):
        s_start = sb_i * strat_batch_size
        s_end = min(s_start + strat_batch_size, n_strats)
        batch_positions = positions[s_start:s_end]
        B = len(batch_positions)

        # Move to GPU
        pos_gpu = torch.tensor(batch_positions, dtype=DTYPE, device=DEVICE)
        pos_pos = torch.clamp(pos_gpu, min=0.0)
        pos_neg = torch.clamp(-pos_gpu, min=0.0)
        cost_gpu = pos_pos @ ask_gpu - pos_neg @ bid_gpu

        # Per-batch trial scores
        trial_scores = np.empty((B, n_trials_total), dtype=np.float32)

        for ci in range(n_chunks):
            gen = torch.Generator(device=DEVICE).manual_seed(seed + sb_i * 1000 + ci)
            S_T, S_2w, min_S = gen_paths(chunk_paths, gen)
            M = compute_payoff_matrix(S_T, S_2w, min_S)
            pnl = pos_gpu @ M - cost_gpu.unsqueeze(1)
            trial_chunk = pnl.view(B, n_trials_per_chunk, SIMS_PER_TRIAL).mean(dim=2) * CONTRACT_MULTIPLIER
            tstart = ci * n_trials_per_chunk
            trial_scores[:, tstart:tstart+n_trials_per_chunk] = trial_chunk.cpu().numpy()
            del S_T, S_2w, min_S, M, pnl, trial_chunk
            torch.cuda.empty_cache()

        # Compute stats for this batch
        means[s_start:s_end] = trial_scores.mean(axis=1)
        sds[s_start:s_end] = trial_scores.std(axis=1, ddof=1)
        medians[s_start:s_end] = np.median(trial_scores, axis=1)
        pct_pos[s_start:s_end] = (trial_scores > 0).mean(axis=1) * 100
        sorted_scores = np.sort(trial_scores, axis=1)
        n_t = sorted_scores.shape[1]
        cvar1[s_start:s_end]  = sorted_scores[:, :max(1, n_t // 100)].mean(axis=1)
        cvar2[s_start:s_end]  = sorted_scores[:, :max(1, n_t * 2 // 100)].mean(axis=1)
        cvar5[s_start:s_end]  = sorted_scores[:, :max(1, n_t * 5 // 100)].mean(axis=1)
        cvar10[s_start:s_end] = sorted_scores[:, :max(1, n_t * 10 // 100)].mean(axis=1)

        del trial_scores, pos_gpu, cost_gpu, pos_pos, pos_neg

        elapsed = time.time() - t0
        eta = elapsed * (n_strat_batches - sb_i - 1) / (sb_i + 1)
        if (sb_i + 1) % 10 == 0 or sb_i == 0:
            print(f"  batch {sb_i+1:>3}/{n_strat_batches} ({s_end:,} strats done) "
                  f"elapsed {elapsed:>6.1f}s ETA {eta:>6.0f}s")

    print(f"Phase 1 sweep done in {time.time()-t0:.0f}s")
    return {"means": means, "sds": sds, "medians": medians, "pct_pos": pct_pos,
            "cvar1": cvar1, "cvar2": cvar2, "cvar5": cvar5, "cvar10": cvar10}


def find_pareto(means, cvar5, cvar2):
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
    parser.add_argument("--paths", type=int, default=50_000_000)
    parser.add_argument("--chunk", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=20260428)
    parser.add_argument("--strat_batch", type=int, default=500)
    parser.add_argument("--out", type=str, default="results/phase1_results.json")
    args = parser.parse_args()

    print("="*100)
    print(f"PHASE 1: HUGE GRID SWEEP")
    print(f"  GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"  Paths/strat: {args.paths:,}  Chunk: {args.chunk:,}  Strat batch: {args.strat_batch}")
    print("="*100)

    positions, names = build_huge_grid()
    print(f"\nGrid: {len(names):,} candidates")

    res = sweep_streaming(positions, names, args.paths, args.seed,
                          args.chunk, args.strat_batch)

    means = res["means"]; sds = res["sds"]; cvar5 = res["cvar5"]; cvar2 = res["cvar2"]
    sharpes = means / np.maximum(sds, 1e-9)

    # Identify Pareto frontier
    print("\nFinding Pareto frontier on (mean, CVaR-5%, CVaR-2%)...")
    t = time.time()
    pareto_idx = find_pareto(means, cvar5, cvar2)
    print(f"  {len(pareto_idx)} Pareto-optimal in {time.time()-t:.1f}s")

    # Top 30 by mean
    print("\n" + "="*150)
    print("TOP 30 BY E[score]")
    print("="*150)
    print(f"{'Rank':>4} {'Strategy':<48} {'Mean':>13} {'SD':>11} {'Sharpe':>7} "
          f"{'CVaR-5%':>13} {'CVaR-2%':>13} Pareto")
    sorted_idx = np.argsort(-means)
    for rank, i in enumerate(sorted_idx[:30], 1):
        flag = " **" if i in pareto_idx else ""
        print(f"{rank:>4} {names[i][:46]:<48} ${means[i]:>+12,.0f} ${sds[i]:>10,.0f} "
              f"{sharpes[i]:>7.4f} ${cvar5[i]:>+12,.0f} ${cvar2[i]:>+12,.0f}{flag}")

    # Top 30 by Sharpe
    print("\n" + "="*150)
    print("TOP 30 BY SHARPE")
    print("="*150)
    sorted_sh = np.argsort(-sharpes)
    for rank, i in enumerate(sorted_sh[:30], 1):
        flag = " **" if i in pareto_idx else ""
        print(f"{rank:>4} {names[i][:46]:<48} ${means[i]:>+12,.0f} ${sds[i]:>10,.0f} "
              f"{sharpes[i]:>7.4f} ${cvar5[i]:>+12,.0f} ${cvar2[i]:>+12,.0f}{flag}")

    # Save top-200-by-mean and top-200-by-sharpe (union) for Phase 2
    top_by_mean = sorted_idx[:200].tolist()
    top_by_sharpe = sorted_sh[:200].tolist()
    union = sorted(set(top_by_mean + top_by_sharpe))
    print(f"\nUnion of top-200-mean and top-200-sharpe: {len(union)} candidates for Phase 2")

    out = {
        "n_strategies": len(names),
        "n_paths_per_strategy": args.paths,
        "seed": args.seed,
        "pareto_frontier_count": len(pareto_idx),
        "top_for_phase2": [
            {
                "name": names[i],
                "positions": {INSTR[j]: int(positions[i, j])
                              for j in range(N_INSTR) if positions[i, j] != 0},
                "mean": float(means[i]), "sd": float(sds[i]),
                "sharpe": float(sharpes[i]),
                "cvar1": float(res["cvar1"][i]), "cvar2": float(cvar2[i]),
                "cvar5": float(cvar5[i]), "cvar10": float(res["cvar10"][i]),
                "pct_positive": float(res["pct_pos"][i]),
                "in_pareto": bool(i in pareto_idx),
                "rank_by_mean": int(np.where(sorted_idx == i)[0][0] + 1),
                "rank_by_sharpe": int(np.where(sorted_sh == i)[0][0] + 1),
            }
            for i in union
        ],
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
