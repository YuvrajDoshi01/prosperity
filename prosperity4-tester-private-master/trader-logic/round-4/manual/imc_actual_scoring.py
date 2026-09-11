"""Simulate IMC's actual scoring procedure literally.

Step 1: Generate 1M independent paths (each = 1 IMC 'seed').
Step 2: Compute per-path PnL for each strategy (without averaging or multiplier).
Step 3: For each strategy, sample 100 random seeds (without replacement),
        sum, average, then * 3000 = ONE realized IMC score.
Step 4: Repeat 100K times -> empirical distribution of "what IMC could score".
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
SIMS_PER_TRIAL = 100  # IMC averages over 100 simulations
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
DTYPE = torch.float32

QUOTES = {
    "AC":(49.975,50.025,200), "AC_50_P":(12.000,12.050,50), "AC_50_C":(12.000,12.050,50),
    "AC_35_P":(4.330,4.350,50), "AC_40_P":(6.500,6.550,50), "AC_45_P":(9.050,9.100,50),
    "AC_60_C":(8.800,8.850,50), "AC_50_P_2":(9.700,9.750,50), "AC_50_C_2":(9.700,9.750,50),
    "AC_50_CO":(22.200,22.300,50), "AC_40_BP":(5.000,5.100,50), "AC_45_KO":(0.150,0.175,500),
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
    M[INSTR.index("AC")] = S_T
    M[INSTR.index("AC_50_P")] = torch.clamp(50 - S_T, min=0.0)
    M[INSTR.index("AC_50_C")] = torch.clamp(S_T - 50, min=0.0)
    M[INSTR.index("AC_35_P")] = torch.clamp(35 - S_T, min=0.0)
    M[INSTR.index("AC_40_P")] = torch.clamp(40 - S_T, min=0.0)
    M[INSTR.index("AC_45_P")] = torch.clamp(45 - S_T, min=0.0)
    M[INSTR.index("AC_60_C")] = torch.clamp(S_T - 60, min=0.0)
    M[INSTR.index("AC_50_P_2")] = torch.clamp(50 - S_2w, min=0.0)
    M[INSTR.index("AC_50_C_2")] = torch.clamp(S_2w - 50, min=0.0)
    M[INSTR.index("AC_50_CO")] = torch.where(S_2w >= 50, torch.clamp(S_T - 50, min=0.0), torch.clamp(50 - S_T, min=0.0))
    M[INSTR.index("AC_40_BP")] = torch.where(S_T < 40, torch.full_like(S_T, 10.0), torch.zeros_like(S_T))
    M[INSTR.index("AC_45_KO")] = torch.where(min_S >= 35, torch.clamp(45 - S_T, min=0.0), torch.zeros_like(S_T))
    return M


def encode_position(d):
    v = np.zeros(N_INSTR, dtype=np.int32)
    for k, q in d.items(): v[INSTR.index(k)] = q
    return v


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2_results", type=str, default="results/phase2_10kseeds_results.json")
    parser.add_argument("--n_seeds", type=int, default=1_000_000, help="Universe of independent paths")
    parser.add_argument("--n_bootstrap", type=int, default=100_000, help="Synthetic IMC submission runs per strat")
    parser.add_argument("--top_n", type=int, default=100, help="How many strats to score")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default="results/imc_actual_scoring_results.json")
    args = parser.parse_args()

    print("=" * 100)
    print("IMC ACTUAL SCORING SIMULATION")
    print("=" * 100)
    print(f"  Universe size: {args.n_seeds:,} independent paths (= IMC 'seeds')")
    print(f"  Per-IMC-score: pick 100 random seeds, sum, /100, * {CONTRACT_MULTIPLIER}")
    print(f"  Bootstrap runs: {args.n_bootstrap:,} synthetic IMC submissions per strategy")

    with open(args.phase2_results) as f:
        p2 = json.load(f)
    candidates = sorted(p2["ranking"], key=lambda x: -x["mean"])[:args.top_n]
    names = [c["name"] for c in candidates]
    positions = np.array([encode_position(c["positions"]) for c in candidates], dtype=np.int32)

    print(f"\nLoaded {len(candidates)} strategies from {args.phase2_results}")

    t0 = time.time()
    print(f"\n[1/3] Generating {args.n_seeds:,} GBM paths on GPU...")
    gen = torch.Generator(device=DEVICE).manual_seed(args.seed)
    S_T, S_2w, min_S = gen_paths(args.n_seeds, gen)
    M = compute_payoff_matrix(S_T, S_2w, min_S)
    print(f"  done ({time.time()-t0:.1f}s)")

    t1 = time.time()
    print(f"\n[2/3] Computing per-path PnL for {len(positions)} strategies...")
    pos_gpu = torch.tensor(positions, dtype=DTYPE, device=DEVICE)
    bid_gpu = torch.tensor([QUOTES[s][0] for s in INSTR], dtype=DTYPE, device=DEVICE)
    ask_gpu = torch.tensor([QUOTES[s][1] for s in INSTR], dtype=DTYPE, device=DEVICE)
    cost_gpu = torch.clamp(pos_gpu, min=0.0) @ ask_gpu - torch.clamp(-pos_gpu, min=0.0) @ bid_gpu
    pnl_paths = pos_gpu @ M - cost_gpu.unsqueeze(1)  # (N_STRATS, N_SEEDS)
    print(f"  pnl_paths shape: {tuple(pnl_paths.shape)}, mem {pnl_paths.element_size()*pnl_paths.numel()/1e6:.0f}MB")
    print(f"  done ({time.time()-t1:.1f}s)")

    # Free intermediate tensors
    del S_T, S_2w, min_S, M
    torch.cuda.empty_cache()

    t2 = time.time()
    print(f"\n[3/3] Bootstrapping {args.n_bootstrap:,} IMC scoring runs per strategy...")
    print(f"  Each run: pick 100 random seeds from {args.n_seeds:,}, sum, /100, * {CONTRACT_MULTIPLIER}")

    # Vectorized bootstrap: for each strategy, generate (n_bootstrap, 100) random indices
    # Then gather + mean.
    # Memory: idx (100K, 100) int64 = 80MB; gathered (100K, 100) float32 = 40MB per strat.
    # Process strats in batches to avoid OOM.
    n_strats = len(positions)
    imc_scores = np.empty((n_strats, args.n_bootstrap), dtype=np.float32)

    # Sample indices once (shared across strats for fair comparison)
    rng = np.random.default_rng(args.seed)
    idx_np = rng.integers(0, args.n_seeds, size=(args.n_bootstrap, SIMS_PER_TRIAL), dtype=np.int64)
    idx_gpu = torch.from_numpy(idx_np).to(DEVICE)  # (n_bootstrap, 100)

    STRAT_BATCH = 25
    for sb in range(0, n_strats, STRAT_BATCH):
        se = min(sb + STRAT_BATCH, n_strats)
        # pnl_paths[sb:se] shape (B, N_SEEDS); gather rows (B, n_bootstrap, 100)
        gathered = pnl_paths[sb:se][:, idx_gpu]  # (B, n_bootstrap, 100)
        scores_chunk = gathered.mean(dim=2) * CONTRACT_MULTIPLIER  # (B, n_bootstrap)
        imc_scores[sb:se] = scores_chunk.cpu().numpy()
        del gathered, scores_chunk
        torch.cuda.empty_cache()
        if sb % 50 == 0:
            print(f"  strats {sb}-{se}/{n_strats} done at {time.time()-t2:.1f}s")
    print(f"  done ({time.time()-t2:.1f}s)")
    print(f"\nTotal: {time.time()-t0:.1f}s")

    # Stats
    print(f"\n{'='*150}")
    print(f"IMC SCORING DISTRIBUTION SUMMARY (1M-seed universe, 100K synthetic IMC runs/strat)")
    print(f"{'='*150}")

    pnl_mean_per_path = pnl_paths.mean(dim=1).cpu().numpy()  # ground-truth EV per path
    ev_per_strat = pnl_mean_per_path * CONTRACT_MULTIPLIER
    pnl_sd_per_path = pnl_paths.std(dim=1, unbiased=True).cpu().numpy()
    # Theoretical IMC score SD = sd_path/sqrt(100) * 3000 = sd_path * 300
    theo_sd = pnl_sd_per_path * (CONTRACT_MULTIPLIER / np.sqrt(SIMS_PER_TRIAL))

    print(f"{'Rank':>4} {'Strategy':<48} {'EV (1M)':>13} {'IMC mean':>13} {'IMC sd':>11} {'Theo sd':>11} "
          f"{'IMC p5':>13} {'IMC p50':>13} {'IMC p95':>13} {'P(score>0)':>10}")
    sorted_idx = np.argsort(-ev_per_strat)
    out_rows = []
    for rank, i in enumerate(sorted_idx, 1):
        s = imc_scores[i]
        m = s.mean(); sd = s.std(ddof=1); med = np.median(s)
        p1, p5, p25, p75, p95, p99 = np.percentile(s, [1, 5, 25, 75, 95, 99])
        p_pos = (s > 0).mean() * 100
        p_below_neg100k = (s < -100_000).mean() * 100
        p_below_neg300k = (s < -300_000).mean() * 100
        p_below_neg500k = (s < -500_000).mean() * 100
        p_above_pos200k = (s > 200_000).mean() * 100
        p_above_pos500k = (s > 500_000).mean() * 100
        if rank <= 30:
            print(f"{rank:>4} {names[i][:46]:<48} ${ev_per_strat[i]:>+12,.0f} "
                  f"${m:>+12,.0f} ${sd:>10,.0f} ${theo_sd[i]:>10,.0f} "
                  f"${p5:>+12,.0f} ${med:>+12,.0f} ${p95:>+12,.0f} {p_pos:>9.2f}%")
        out_rows.append({
            "rank": rank, "name": names[i], "positions": candidates[i]["positions"],
            "ev_per_path": float(pnl_mean_per_path[i]),
            "ev_full": float(ev_per_strat[i]),
            "imc_mean": float(m), "imc_sd": float(sd), "imc_median": float(med),
            "imc_p1": float(p1), "imc_p5": float(p5), "imc_p25": float(p25),
            "imc_p75": float(p75), "imc_p95": float(p95), "imc_p99": float(p99),
            "theo_sd": float(theo_sd[i]),
            "p_positive_pct": float(p_pos),
            "p_below_neg100k_pct": float(p_below_neg100k),
            "p_below_neg300k_pct": float(p_below_neg300k),
            "p_below_neg500k_pct": float(p_below_neg500k),
            "p_above_pos200k_pct": float(p_above_pos200k),
            "p_above_pos500k_pct": float(p_above_pos500k),
        })

    # Show 10 example IMC realizations for top 6 candidates
    print(f"\n{'='*100}")
    print(f"10 EXAMPLE IMC REALIZATIONS for top 6 candidates")
    print(f"{'='*100}")
    for rank, i in enumerate(sorted_idx[:6], 1):
        examples = imc_scores[i, :10]
        print(f"\n  #{rank} {names[i][:50]} (EV $ {ev_per_strat[i]:+,.0f}):")
        for j, score in enumerate(examples):
            print(f"     run {j+1}: ${score:>+10,.0f}")

    out = {
        "n_seeds": args.n_seeds,
        "n_bootstrap": args.n_bootstrap,
        "sims_per_trial": SIMS_PER_TRIAL,
        "contract_multiplier": CONTRACT_MULTIPLIER,
        "ranking": out_rows,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
