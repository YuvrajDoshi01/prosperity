"""IMC scoring for USER_SAFE + key candidates with full distribution."""
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
    N_BOOTSTRAP = 100_000
    GBM_SEED = 42
    PICK_SEED = 99999

    KEY = [
        ("DROP_60C (max EV)", {"AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
        ("DOM_NICE_v3 (recommended)", {"AC_50_C": 15, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
        ("DROP+25 AC_50_C", {"AC_50_C": 25, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
        ("DROP+50 AC_45_P+25 AC_50_C", {"AC_50_C": 25, "AC_45_P": 50, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
        ("DOM_NICE_v2 (deprecated)", {"AC_35_P": 50, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
        ("USER_SAFE (high Sharpe)", {"AC_50_P": 17, "AC_50_C": 15, "AC_50_P_2": 15, "AC_50_CO": -15, "AC_40_BP": -50, "AC_45_KO": 60}),
    ]

    names = [k[0] for k in KEY]
    positions = np.array([encode_position(k[1]) for k in KEY], dtype=np.int32)

    print("=" * 100)
    print("IMC SCORING — KEY CANDIDATES + USER_SAFE")
    print("=" * 100)
    print(f"  Universe: {N_SEEDS:,} GBM paths (GBM seed={GBM_SEED})")
    print(f"  Procedure: pick 100 random seeds, average payoffs, x{CONTRACT_MULTIPLIER}")
    print(f"  Bootstrap: {N_BOOTSTRAP:,} synthetic IMC submissions per strategy")
    print(f"  One example uses pick_seed={PICK_SEED}")

    t0 = time.time()
    gen = torch.Generator(device=DEVICE).manual_seed(GBM_SEED)
    S_T, S_2w, min_S = gen_paths(N_SEEDS, gen)
    M = compute_payoff_matrix(S_T, S_2w, min_S)
    print(f"\n[1/3] Generated {N_SEEDS:,} paths in {time.time()-t0:.2f}s")

    t1 = time.time()
    pos_gpu = torch.tensor(positions, dtype=DTYPE, device=DEVICE)
    bid_gpu = torch.tensor([QUOTES[s][0] for s in INSTR], dtype=DTYPE, device=DEVICE)
    ask_gpu = torch.tensor([QUOTES[s][1] for s in INSTR], dtype=DTYPE, device=DEVICE)
    cost_gpu = torch.clamp(pos_gpu, min=0.0) @ ask_gpu - torch.clamp(-pos_gpu, min=0.0) @ bid_gpu
    pnl_paths = pos_gpu @ M - cost_gpu.unsqueeze(1)
    print(f"[2/3] Per-path PnL for {len(positions)} strategies in {time.time()-t1:.2f}s")

    # Per-path EV (precise)
    ev_per_strat = (pnl_paths.mean(dim=1) * CONTRACT_MULTIPLIER).cpu().numpy()
    sd_path = pnl_paths.std(dim=1, unbiased=True).cpu().numpy()
    theo_imc_sd = sd_path * (CONTRACT_MULTIPLIER / np.sqrt(SIMS_PER_TRIAL))

    # ONE realization
    rng = np.random.default_rng(PICK_SEED)
    chosen_seeds = rng.choice(N_SEEDS, size=SIMS_PER_TRIAL, replace=False)
    chosen_idx_gpu = torch.from_numpy(chosen_seeds).to(DEVICE).long()
    one_payoffs = pnl_paths[:, chosen_idx_gpu]
    one_sum = one_payoffs.sum(dim=1).cpu().numpy()
    one_avg = one_sum / SIMS_PER_TRIAL
    one_score = one_avg * CONTRACT_MULTIPLIER

    # Bootstrap distribution
    t2 = time.time()
    rng2 = np.random.default_rng(PICK_SEED + 1)
    boot_idx = rng2.integers(0, N_SEEDS, size=(N_BOOTSTRAP, SIMS_PER_TRIAL), dtype=np.int64)
    boot_idx_gpu = torch.from_numpy(boot_idx).to(DEVICE)
    gathered = pnl_paths[:, boot_idx_gpu]  # (n_strats, N_BOOTSTRAP, 100)
    boot_scores = (gathered.mean(dim=2) * CONTRACT_MULTIPLIER).cpu().numpy()  # (n_strats, N_BOOTSTRAP)
    print(f"[3/3] Bootstrapped {N_BOOTSTRAP:,} IMC scorings/strat in {time.time()-t2:.2f}s")

    # ===== Output table =====
    print()
    print("=" * 130)
    print("ONE LITERAL IMC REALIZATION (pick_seed=99999, SAME 100 paths used for all strategies)")
    print("=" * 130)
    print(f"{'Strategy':<32} {'Sum (raw)':>14} {'Avg':>9} {'IMC Score (x3000)':>20} {'EV (1M)':>13} {'Delta':>11}")
    for i, name in enumerate(names):
        print(f"{name[:31]:<32} ${one_sum[i]:>+12,.2f} ${one_avg[i]:>+7,.2f} ${one_score[i]:>+18,.0f} ${ev_per_strat[i]:>+11,.0f} ${one_score[i]-ev_per_strat[i]:>+9,.0f}")

    print()
    print("=" * 130)
    print(f"FULL IMC SCORE DISTRIBUTION ({N_BOOTSTRAP:,} bootstrap samples per strategy)")
    print("=" * 130)
    print(f"{'Strategy':<32} {'EV':>11} {'IMC mean':>11} {'IMC SD':>10} {'p1 (worst 1%)':>14} {'p5':>11} {'p50':>11} {'p95':>11} {'p99':>13} {'P>0':>7}")
    for i, name in enumerate(names):
        s = boot_scores[i]
        m = s.mean(); sd = s.std(ddof=1); med = np.median(s)
        p1, p5, p95, p99 = np.percentile(s, [1, 5, 95, 99])
        p_pos = (s > 0).mean() * 100
        print(f"{name[:31]:<32} ${ev_per_strat[i]:>+10,.0f} ${m:>+10,.0f} ${sd:>9,.0f} "
              f"${p1:>+12,.0f} ${p5:>+10,.0f} ${med:>+10,.0f} ${p95:>+10,.0f} ${p99:>+12,.0f} {p_pos:>6.2f}%")

    print()
    print("=" * 130)
    print("TAIL PROBABILITIES (out of 100K simulated IMC submissions)")
    print("=" * 130)
    print(f"{'Strategy':<32} {'P(<-500k)':>10} {'P(<-300k)':>10} {'P(<-100k)':>10} {'P(<0)':>8} {'P(>0)':>8} {'P(>+100k)':>10} {'P(>+300k)':>10} {'P(>+500k)':>10}")
    for i, name in enumerate(names):
        s = boot_scores[i]
        n = len(s)
        print(f"{name[:31]:<32} {(s<-500_000).mean()*100:>9.2f}% {(s<-300_000).mean()*100:>9.2f}% {(s<-100_000).mean()*100:>9.2f}% "
              f"{(s<0).mean()*100:>7.2f}% {(s>0).mean()*100:>7.2f}% {(s>100_000).mean()*100:>9.2f}% "
              f"{(s>300_000).mean()*100:>9.2f}% {(s>500_000).mean()*100:>9.2f}%")

    out = {
        "n_seeds": N_SEEDS,
        "n_bootstrap": N_BOOTSTRAP,
        "gbm_seed": GBM_SEED,
        "pick_seed": PICK_SEED,
        "candidates": [
            {
                "name": names[i],
                "positions": KEY[i][1],
                "ev": float(ev_per_strat[i]),
                "theo_imc_sd": float(theo_imc_sd[i]),
                "one_realization": {
                    "sum_raw": float(one_sum[i]),
                    "avg": float(one_avg[i]),
                    "imc_score": float(one_score[i]),
                },
                "distribution": {
                    "mean": float(boot_scores[i].mean()),
                    "sd": float(boot_scores[i].std(ddof=1)),
                    "median": float(np.median(boot_scores[i])),
                    "p1": float(np.percentile(boot_scores[i], 1)),
                    "p5": float(np.percentile(boot_scores[i], 5)),
                    "p95": float(np.percentile(boot_scores[i], 95)),
                    "p99": float(np.percentile(boot_scores[i], 99)),
                    "p_positive_pct": float((boot_scores[i] > 0).mean() * 100),
                },
            }
            for i in range(len(names))
        ],
    }
    with open("results/imc_user_safe_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved to results/imc_user_safe_results.json")


if __name__ == "__main__":
    main()
