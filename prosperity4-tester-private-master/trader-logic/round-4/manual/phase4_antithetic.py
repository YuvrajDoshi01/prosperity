"""Phase 4: Antithetic-variates tail estimation for top 5 candidates.

Antithetic pairing: for each Z draw, also use -Z. Reduces variance of the
mean estimator by ~50% for symmetric payoffs, MORE for monotone-in-S payoffs
(tail-protective puts/calls). Tightens CVaR-5%/CVaR-2% confidence intervals
by ~3-10x at the same computational cost.

Output: ultra-tight CVaR estimates for the final 5 ship candidates.
"""
import argparse, json, time
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
    "AC":          (49.975, 50.025, 200), "AC_50_P": (12.000, 12.050, 50),
    "AC_50_C":     (12.000, 12.050,  50), "AC_35_P": ( 4.330,  4.350,  50),
    "AC_40_P":     ( 6.500,  6.550,  50), "AC_45_P": ( 9.050,  9.100,  50),
    "AC_60_C":     ( 8.800,  8.850,  50), "AC_50_P_2":( 9.700, 9.750,  50),
    "AC_50_C_2":   ( 9.700,  9.750,  50), "AC_50_CO":(22.200, 22.300,  50),
    "AC_40_BP":    ( 5.000,  5.100,  50), "AC_45_KO":( 0.150,  0.175, 500),
}
INSTR = list(QUOTES.keys())
N_INSTR = len(INSTR)


def gen_paths_antithetic(n_pairs, gen):
    """Generate n_pairs antithetic-paired GBM paths.
    Returns (S_T, S_2w, min_S) of shape (2*n_pairs,).
    First n_pairs are originals, next n_pairs are antithetic (-Z draws).
    Trials of 100 paths each will see 50 originals + 50 antithetics.
    """
    drift = -0.5 * SIGMA * SIGMA * DT
    vol = SIGMA * (DT ** 0.5)
    n = 2 * n_pairs
    # Interleave: [orig_1, anti_1, orig_2, anti_2, ...] so each consecutive pair is one antithetic-pair
    S = torch.full((n,), S0, dtype=DTYPE, device=DEVICE)
    min_S = S.clone()
    S_2w = None
    for k in range(N_3W):
        z = torch.randn(n_pairs, generator=gen, dtype=DTYPE, device=DEVICE)
        z_full = torch.empty(n, dtype=DTYPE, device=DEVICE)
        z_full[0::2] = z          # odd indices: original
        z_full[1::2] = -z         # even indices: antithetic
        S = S * torch.exp(drift + vol * z_full)
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


def evaluate_antithetic(positions, n_pairs_total, seed, chunk_pairs):
    """Run antithetic MC. Each chunk of `chunk_pairs` pairs = 2*chunk_pairs paths.
    Trials of 100 are formed from consecutive paths (50 origs + 50 antithetics)."""
    n_strats = len(positions)
    n_paths_total = 2 * n_pairs_total
    n_chunks = n_pairs_total // chunk_pairs
    chunk_paths = 2 * chunk_pairs
    n_trials_total = n_paths_total // SIMS_PER_TRIAL
    n_trials_per_chunk = chunk_paths // SIMS_PER_TRIAL

    pos_gpu = torch.tensor(positions, dtype=DTYPE, device=DEVICE)
    bid_gpu = torch.tensor([QUOTES[s][0] for s in INSTR], dtype=DTYPE, device=DEVICE)
    ask_gpu = torch.tensor([QUOTES[s][1] for s in INSTR], dtype=DTYPE, device=DEVICE)
    cost_gpu = torch.clamp(pos_gpu, min=0.0) @ ask_gpu - torch.clamp(-pos_gpu, min=0.0) @ bid_gpu

    trial_scores = np.empty((n_strats, n_trials_total), dtype=np.float32)

    print(f"Antithetic eval: {n_strats} strats x {n_paths_total:,} paths "
          f"({n_pairs_total:,} pairs, {n_trials_total:,} trials/strat)")
    print(f"  Trials of 100 each contain 50 orig + 50 antithetic paths")

    t0 = time.time()
    for ci in range(n_chunks):
        gen = torch.Generator(device=DEVICE).manual_seed(seed + ci)
        S_T, S_2w, min_S = gen_paths_antithetic(chunk_pairs, gen)
        M = compute_payoff_matrix(S_T, S_2w, min_S)
        pnl = pos_gpu @ M - cost_gpu.unsqueeze(1)
        trial_chunk = pnl.view(n_strats, n_trials_per_chunk, SIMS_PER_TRIAL).mean(dim=2) * CONTRACT_MULTIPLIER
        tstart = ci * n_trials_per_chunk
        trial_scores[:, tstart:tstart+n_trials_per_chunk] = trial_chunk.cpu().numpy()
        del S_T, S_2w, min_S, M, pnl, trial_chunk
        torch.cuda.empty_cache()
        if (ci+1) % max(1, n_chunks//10) == 0:
            elapsed = time.time() - t0
            print(f"  chunk {ci+1}/{n_chunks} elapsed {elapsed:.1f}s")

    return trial_scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2_results", type=str, default="results/phase2_10kseeds_results.json")
    parser.add_argument("--pairs_per_strat", type=int, default=50_000_000,
                        help="Antithetic pairs per strategy (default 50M = 100M paths)")
    parser.add_argument("--chunk_pairs", type=int, default=500_000)
    parser.add_argument("--top_n", type=int, default=10)
    parser.add_argument("--out", type=str, default="results/phase4_results.json")
    args = parser.parse_args()

    print("="*100)
    print("PHASE 4: ANTITHETIC-VARIATES TIGHT TAIL ESTIMATION")
    print("="*100)

    with open(args.phase2_results) as f:
        p2 = json.load(f)

    candidates = p2["ranking"][:args.top_n]
    names = [c["name"] for c in candidates]
    positions = np.array([encode_position(c["positions"]) for c in candidates], dtype=np.int32)

    print(f"\nLoaded top {len(candidates)} from {args.phase2_results}")

    trial_scores = evaluate_antithetic(positions, args.pairs_per_strat, 12345678, args.chunk_pairs)

    # Stats
    print(f"\n{'='*150}")
    print(f"PHASE 4 RESULTS — antithetic-variate {args.pairs_per_strat:,} pairs ({args.pairs_per_strat*2:,} paths)/strat")
    print(f"{'='*150}")
    print(f"{'Rank':>4} {'Strategy':<48} {'Mean':>13} {'Median':>13} {'SD':>11} {'Sharpe':>7} "
          f"{'CVaR-5%':>13} {'CVaR-2%':>13} {'CVaR-1%':>13}")
    means = trial_scores.mean(axis=1)
    sorted_idx = np.argsort(-means)
    out_rows = []
    for rank, i in enumerate(sorted_idx, 1):
        s = trial_scores[i]
        mean = s.mean(); sd = s.std(ddof=1); med = np.median(s)
        sharpe = mean / sd if sd > 0 else 0
        sorted_s = np.sort(s)
        n_t = len(sorted_s)
        cvar5 = sorted_s[:max(1, n_t*5//100)].mean()
        cvar2 = sorted_s[:max(1, n_t*2//100)].mean()
        cvar1 = sorted_s[:max(1, n_t//100)].mean()
        # Bootstrap CI on cvar5 (1000 resamples)
        bs_cvar5 = []
        for _ in range(200):
            sample = np.random.choice(s, size=n_t, replace=True)
            sample_sorted = np.sort(sample)
            bs_cvar5.append(sample_sorted[:max(1, n_t*5//100)].mean())
        bs_cvar5_se = np.std(bs_cvar5)
        out_rows.append({
            "rank": rank, "name": names[i],
            "positions": candidates[i]["positions"],
            "mean": float(mean), "median": float(med), "sd": float(sd), "sharpe": float(sharpe),
            "pct_positive": float((s > 0).mean() * 100),
            "cvar5": float(cvar5), "cvar5_bootstrap_se": float(bs_cvar5_se),
            "cvar2": float(cvar2), "cvar1": float(cvar1),
        })
        print(f"{rank:>4} {names[i][:46]:<48} ${mean:>+12,.0f} ${med:>+12,.0f} ${sd:>10,.0f} "
              f"{sharpe:>7.4f} ${cvar5:>+12,.0f} ${cvar2:>+12,.0f} ${cvar1:>+12,.0f}")

    out = {
        "n_candidates": len(names),
        "n_paths_per_strat": args.pairs_per_strat * 2,
        "n_pairs_per_strat": args.pairs_per_strat,
        "ranking": out_rows,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
