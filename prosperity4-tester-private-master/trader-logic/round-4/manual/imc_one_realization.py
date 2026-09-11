"""ONE LITERAL IMC SCORING REALIZATION.

Walk through the IMC procedure step-by-step exactly once:
  1. Generate 1M GBM paths (= 1M seeds).
  2. For each of 100 strategies, compute the payoff on each of the 1M paths.
  3. Pick 100 random seed-indices out of 1M.
  4. For each strategy, average the payoffs of those 100 seeds and multiply by 3000.
  5. Report the score for each strategy under THIS one IMC realization.
"""
import json, time
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
    N_SEEDS = 1_000_000
    GBM_SEED = 42  # for path generation
    IMC_PICK_SEED = 99999  # for picking which 100 seeds IMC "uses"

    print("=" * 100)
    print("IMC LITERAL SCORING REALIZATION")
    print("=" * 100)

    # Load top 100 from Phase 2 (10K-seed verified)
    with open("results/phase2_10kseeds_results.json") as f:
        p2 = json.load(f)
    candidates = sorted(p2["ranking"], key=lambda x: -x["mean"])[:100]
    names = [c["name"] for c in candidates]
    positions = np.array([encode_position(c["positions"]) for c in candidates], dtype=np.int32)

    # ===== STEP 1: Generate 1M GBM paths =====
    print(f"\n[Step 1] Generating {N_SEEDS:,} independent GBM paths (seed={GBM_SEED}) ...")
    t0 = time.time()
    gen = torch.Generator(device=DEVICE).manual_seed(GBM_SEED)
    S_T, S_2w, min_S = gen_paths(N_SEEDS, gen)
    M = compute_payoff_matrix(S_T, S_2w, min_S)
    print(f"  shape S_T = {tuple(S_T.shape)}, sample S_T[0:5] = {S_T[:5].cpu().numpy().tolist()}")
    print(f"  shape M (payoffs per instrument) = {tuple(M.shape)}")
    print(f"  done in {time.time()-t0:.2f}s")

    # ===== STEP 2: Per-path PnL for all 100 strategies =====
    print(f"\n[Step 2] Computing per-path PnL for ALL {len(positions)} strategies ...")
    t1 = time.time()
    pos_gpu = torch.tensor(positions, dtype=DTYPE, device=DEVICE)
    bid_gpu = torch.tensor([QUOTES[s][0] for s in INSTR], dtype=DTYPE, device=DEVICE)
    ask_gpu = torch.tensor([QUOTES[s][1] for s in INSTR], dtype=DTYPE, device=DEVICE)
    cost_gpu = torch.clamp(pos_gpu, min=0.0) @ ask_gpu - torch.clamp(-pos_gpu, min=0.0) @ bid_gpu
    pnl_paths = pos_gpu @ M - cost_gpu.unsqueeze(1)  # shape (100, 1M)
    print(f"  pnl_paths shape = {tuple(pnl_paths.shape)} (100 strategies x {N_SEEDS:,} paths)")
    print(f"  total values computed: {pnl_paths.numel():,} = 100M payoff values on GPU")
    print(f"  done in {time.time()-t1:.2f}s")

    # ===== STEP 3: Pick 100 random seed-indices =====
    print(f"\n[Step 3] Picking 100 random seed-indices out of {N_SEEDS:,} (rng seed={IMC_PICK_SEED}) ...")
    rng = np.random.default_rng(IMC_PICK_SEED)
    chosen_seeds = rng.choice(N_SEEDS, size=SIMS_PER_TRIAL, replace=False)
    print(f"  chosen seed indices (first 10): {chosen_seeds[:10].tolist()}")
    print(f"  chosen seed indices (last 10):  {chosen_seeds[-10:].tolist()}")
    print(f"  min={chosen_seeds.min()}, max={chosen_seeds.max()}, sum={chosen_seeds.sum()}")

    # ===== STEP 4: For each strategy, average payoffs of chosen seeds, multiply by 3000 =====
    print(f"\n[Step 4] For EACH of {len(positions)} strategies: average payoffs of those 100 seeds, multiply by {CONTRACT_MULTIPLIER} ...")
    t3 = time.time()
    chosen_idx_gpu = torch.from_numpy(chosen_seeds).to(DEVICE).long()
    payoffs_chosen = pnl_paths[:, chosen_idx_gpu]  # shape (100 strats, 100 seeds)
    print(f"  payoffs_chosen shape = {tuple(payoffs_chosen.shape)}")
    sum_per_strat = payoffs_chosen.sum(dim=1)
    avg_per_strat = sum_per_strat / SIMS_PER_TRIAL
    score_per_strat = (avg_per_strat * CONTRACT_MULTIPLIER).cpu().numpy()
    print(f"  done in {time.time()-t3:.2f}s")

    # ===== STEP 5: Report each strategy's IMC score =====
    print()
    print("=" * 130)
    print(f"STEP 5: IMC SCORE FOR EACH STRATEGY UNDER THIS ONE REALIZATION (seeds chosen by RNG seed {IMC_PICK_SEED})")
    print("=" * 130)
    print(f"{'Rank':>4} {'Strategy':<55} {'Sum (raw)':>15} {'Avg':>11} {'IMC Score (x3000)':>20} {'Phase 2 EV':>13} {'Delta':>11}")

    sorted_idx = np.argsort(-score_per_strat)
    rows = []
    for rank, i in enumerate(sorted_idx[:30], 1):
        sumi = float(sum_per_strat[i].cpu())
        avgi = float(avg_per_strat[i].cpu())
        scorei = float(score_per_strat[i])
        ev = candidates[i]['mean']
        delta = scorei - ev
        print(f"{rank:>4} {names[i][:53]:<55} ${sumi:>+13,.2f} ${avgi:>+9,.2f} ${scorei:>+18,.0f} ${ev:>+11,.0f} ${delta:>+9,.0f}")
        rows.append({
            "rank": rank, "name": names[i],
            "positions": candidates[i]["positions"],
            "sum_raw": sumi, "avg": avgi, "imc_score": scorei,
            "phase2_ev": ev, "delta_vs_ev": delta,
        })

    # KEY candidates breakdown
    print()
    print("=" * 130)
    print("KEY CANDIDATES UNDER THIS REALIZATION")
    print("=" * 130)
    KEY = [
        ("DROP_60C (max EV)", {"AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
        ("DOM_NICE_v3 (recommended)", {"AC_50_C": 15, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
        ("DROP+25 AC_50_C", {"AC_50_C": 25, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
        ("DROP+50 AC_45_P+25 AC_50_C", {"AC_50_C": 25, "AC_45_P": 50, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
        ("DOM_NICE_v2 (deprecated)", {"AC_35_P": 50, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
    ]
    print(f"{'Strategy':<35} {'IMC Score':>15} {'Phase 2 EV':>13} {'Delta':>11} {'in z-units':>11}")
    cands_by_pos = {tuple(sorted(c["positions"].items())): (i, c) for i, c in enumerate(candidates)}
    for label, pos in KEY:
        key = tuple(sorted(pos.items()))
        if key in cands_by_pos:
            i, c = cands_by_pos[key]
            scorei = float(score_per_strat[i])
            ev = c['mean']
            delta = scorei - ev
            phase2_se = c['mean_se']
            # IMC SD per realization is much wider — use trial-mean SD
            imc_sd = c['sd']
            z = delta / imc_sd if imc_sd > 0 else 0
            print(f"{label[:34]:<35} ${scorei:>+13,.0f} ${ev:>+11,.0f} ${delta:>+9,.0f} {z:>+10.3f}sigma")

    print(f"\nNote: IMC score deviates from EV by up to a few hundred $k purely due to which 100 seeds are chosen.")
    print(f"This particular realization (RNG pick seed = {IMC_PICK_SEED}) is just one of infinitely many possible.")

    out = {
        "n_seeds": N_SEEDS,
        "gbm_seed": GBM_SEED,
        "imc_pick_seed": IMC_PICK_SEED,
        "chosen_seed_indices": chosen_seeds.tolist(),
        "ranking_under_this_realization": rows,
    }
    with open("results/imc_one_realization_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved to results/imc_one_realization_results.json")


if __name__ == "__main__":
    main()
