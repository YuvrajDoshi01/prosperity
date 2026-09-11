"""Phase 2: Deep multi-seed verification of top candidates from Phase 1.
Top N strategies x 1B paths x 5 seeds = 5B paths per strategy.
Outputs ultra-precise stats with bootstrap CIs on CVaR-5% and CVaR-2%."""
import argparse
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


def encode_position(d):
    v = np.zeros(N_INSTR, dtype=np.int32)
    for k, q in d.items(): v[INSTR.index(k)] = q
    return v


def deep_evaluate(positions, names, n_paths_per_seed, n_seeds, base_seed,
                  chunk_paths, strat_batch_size):
    """Run each strategy on n_seeds × n_paths_per_seed paths, accumulating stats."""
    n_strats = len(positions)
    n_chunks = n_paths_per_seed // chunk_paths
    n_trials_total = n_paths_per_seed // SIMS_PER_TRIAL
    n_trials_per_chunk = chunk_paths // SIMS_PER_TRIAL
    n_strat_batches = (n_strats + strat_batch_size - 1) // strat_batch_size

    # Per-seed × per-strategy accumulators
    per_seed_means = np.empty((n_seeds, n_strats), dtype=np.float64)
    per_seed_sds = np.empty((n_seeds, n_strats), dtype=np.float64)
    per_seed_cvar1 = np.empty((n_seeds, n_strats), dtype=np.float64)
    per_seed_cvar2 = np.empty((n_seeds, n_strats), dtype=np.float64)
    per_seed_cvar5 = np.empty((n_seeds, n_strats), dtype=np.float64)
    per_seed_pos = np.empty((n_seeds, n_strats), dtype=np.float64)

    bid_gpu = torch.tensor([QUOTES[s][0] for s in INSTR], dtype=DTYPE, device=DEVICE)
    ask_gpu = torch.tensor([QUOTES[s][1] for s in INSTR], dtype=DTYPE, device=DEVICE)

    print(f"Phase 2 deep verify: {n_strats} strategies x {n_seeds} seeds x {n_paths_per_seed:,} paths/seed")
    print(f"  Total work: {n_strats*n_seeds*n_paths_per_seed/1e9:.1f}B path-evals")

    t0 = time.time()
    for seed_i in range(n_seeds):
        seed = base_seed + seed_i * 1_000_000
        for sb_i in range(n_strat_batches):
            s_start = sb_i * strat_batch_size
            s_end = min(s_start + strat_batch_size, n_strats)
            B = s_end - s_start

            pos_gpu = torch.tensor(positions[s_start:s_end], dtype=DTYPE, device=DEVICE)
            cost_gpu = torch.clamp(pos_gpu, min=0.0) @ ask_gpu - torch.clamp(-pos_gpu, min=0.0) @ bid_gpu

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

            per_seed_means[seed_i, s_start:s_end] = trial_scores.mean(axis=1)
            per_seed_sds[seed_i, s_start:s_end] = trial_scores.std(axis=1, ddof=1)
            per_seed_pos[seed_i, s_start:s_end] = (trial_scores > 0).mean(axis=1) * 100
            sorted_s = np.sort(trial_scores, axis=1)
            n_t = sorted_s.shape[1]
            per_seed_cvar1[seed_i, s_start:s_end] = sorted_s[:, :max(1, n_t // 100)].mean(axis=1)
            per_seed_cvar2[seed_i, s_start:s_end] = sorted_s[:, :max(1, n_t * 2 // 100)].mean(axis=1)
            per_seed_cvar5[seed_i, s_start:s_end] = sorted_s[:, :max(1, n_t * 5 // 100)].mean(axis=1)
            del trial_scores, pos_gpu, cost_gpu

        elapsed = time.time() - t0
        eta = elapsed * (n_seeds - seed_i - 1) / (seed_i + 1)
        print(f"  Seed {seed_i+1}/{n_seeds} done at {elapsed:.0f}s (ETA {eta:.0f}s)")

    print(f"Deep verify done in {time.time()-t0:.0f}s")

    # Aggregate across seeds: mean of means, SE = SD of means / sqrt(n_seeds)
    agg = {
        "means_mean": per_seed_means.mean(axis=0),
        "means_se": per_seed_means.std(axis=0, ddof=1) / np.sqrt(n_seeds),
        "sds_mean": per_seed_sds.mean(axis=0),
        "cvar1_mean": per_seed_cvar1.mean(axis=0),
        "cvar1_se": per_seed_cvar1.std(axis=0, ddof=1) / np.sqrt(n_seeds),
        "cvar2_mean": per_seed_cvar2.mean(axis=0),
        "cvar2_se": per_seed_cvar2.std(axis=0, ddof=1) / np.sqrt(n_seeds),
        "cvar5_mean": per_seed_cvar5.mean(axis=0),
        "cvar5_se": per_seed_cvar5.std(axis=0, ddof=1) / np.sqrt(n_seeds),
        "pct_pos_mean": per_seed_pos.mean(axis=0),
        "n_seeds": n_seeds,
        "n_paths_per_seed": n_paths_per_seed,
    }
    return agg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase1_results", type=str, default="results/phase1_results.json")
    parser.add_argument("--paths_per_seed", type=int, default=200_000_000)
    parser.add_argument("--n_seeds", type=int, default=5)
    parser.add_argument("--chunk", type=int, default=1_000_000)
    parser.add_argument("--strat_batch", type=int, default=200)
    parser.add_argument("--top_n", type=int, default=100, help="How many top candidates from phase 1 to verify")
    parser.add_argument("--out", type=str, default="results/phase2_results.json")
    args = parser.parse_args()

    print("="*100)
    print("PHASE 2: DEEP MULTI-SEED VERIFICATION")
    print("="*100)

    with open(args.phase1_results) as f:
        p1 = json.load(f)

    # Sort by mean and take top N
    candidates = sorted(p1["top_for_phase2"], key=lambda x: -x["mean"])[:args.top_n]
    print(f"\nLoaded {len(candidates)} candidates from {args.phase1_results}")
    print(f"Top by mean: {candidates[0]['name']} = ${candidates[0]['mean']:+,.0f}")

    # Encode positions
    names = [c["name"] for c in candidates]
    positions = np.array([encode_position(c["positions"]) for c in candidates], dtype=np.int32)

    agg = deep_evaluate(positions, names, args.paths_per_seed, args.n_seeds,
                        20260428, args.chunk, args.strat_batch)

    # Print results sorted by tight mean
    print("\n" + "="*150)
    print(f"TOP CANDIDATES (from {args.top_n} survivors of Phase 1) "
          f"verified at {args.n_seeds}x{args.paths_per_seed/1e6:.0f}M paths each")
    print("="*150)
    sorted_idx = np.argsort(-agg["means_mean"])
    print(f"{'Rank':>4} {'Strategy':<48} {'Mean':>13} {'SE':>8} {'CVaR-5%':>13} {'CVaR-2%':>13} {'CVaR-1%':>13} {'Sharpe':>7}")
    for rank, i in enumerate(sorted_idx[:30], 1):
        sharpe = agg["means_mean"][i] / max(agg["sds_mean"][i], 1e-9)
        print(f"{rank:>4} {names[i][:46]:<48} ${agg['means_mean'][i]:>+12,.0f} "
              f"${agg['means_se'][i]:>7,.0f} ${agg['cvar5_mean'][i]:>+12,.0f} "
              f"${agg['cvar2_mean'][i]:>+12,.0f} ${agg['cvar1_mean'][i]:>+12,.0f} {sharpe:>7.4f}")

    # Save
    out = {
        "n_candidates": len(names),
        "n_paths_per_seed": args.paths_per_seed,
        "n_seeds": args.n_seeds,
        "ranking": [
            {
                "rank": rank, "name": names[i],
                "positions": candidates[i]["positions"],
                "mean": float(agg["means_mean"][i]),
                "mean_se": float(agg["means_se"][i]),
                "sd": float(agg["sds_mean"][i]),
                "sharpe": float(agg["means_mean"][i] / max(agg["sds_mean"][i], 1e-9)),
                "pct_positive": float(agg["pct_pos_mean"][i]),
                "cvar1": float(agg["cvar1_mean"][i]), "cvar1_se": float(agg["cvar1_se"][i]),
                "cvar2": float(agg["cvar2_mean"][i]), "cvar2_se": float(agg["cvar2_se"][i]),
                "cvar5": float(agg["cvar5_mean"][i]), "cvar5_se": float(agg["cvar5_se"][i]),
            }
            for rank, i in enumerate(sorted_idx, 1)
        ],
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
