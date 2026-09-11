"""Phase 3: Sigma + KO monitoring + alt-model sensitivity for top candidates from Phase 2.
Tests robustness of recommendation across model misspecifications."""
import argparse, json, time
import numpy as np
import torch

S0 = 50.0
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


def gen_paths(n, gen, sigma=2.51, obs_per_day=4, jump_lambda=0.0, jump_sigma=0.0):
    """GBM with optional jumps. obs_per_day controls KO monitoring frequency."""
    n_steps = N_3W * (obs_per_day // 4) if obs_per_day > 4 else N_3W
    n_2w_step = N_2W * (obs_per_day // 4) if obs_per_day > 4 else N_2W
    if obs_per_day == 1: n_steps = 15; n_2w_step = 10
    if obs_per_day == 2: n_steps = 30; n_2w_step = 20
    if obs_per_day == 4: n_steps = 60; n_2w_step = 40
    if obs_per_day == 8: n_steps = 120; n_2w_step = 80
    if obs_per_day == 16: n_steps = 240; n_2w_step = 160
    dt = 1.0 / (252 * obs_per_day)
    drift = -0.5 * sigma * sigma * dt
    vol = sigma * (dt ** 0.5)
    S = torch.full((n,), S0, dtype=DTYPE, device=DEVICE)
    min_S = S.clone()
    S_2w = None
    for k in range(n_steps):
        z = torch.randn(n, generator=gen, dtype=DTYPE, device=DEVICE)
        increment = drift + vol * z
        if jump_lambda > 0:
            jumps = torch.poisson(torch.full((n,), jump_lambda * dt, device=DEVICE, dtype=DTYPE), generator=gen)
            jump_z = torch.randn(n, generator=gen, dtype=DTYPE, device=DEVICE)
            increment += jumps * jump_sigma * jump_z
        S = S * torch.exp(increment)
        torch.minimum(min_S, S, out=min_S)
        if k+1 == n_2w_step: S_2w = S.clone()
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


def evaluate_under_model(positions, n_paths, seed, chunk_paths,
                          sigma=2.51, obs_per_day=4, jump_lambda=0.0, jump_sigma=0.0):
    """Evaluate all positions under specified model parameters."""
    n_strats = len(positions)
    n_chunks = n_paths // chunk_paths
    n_trials_total = n_paths // SIMS_PER_TRIAL
    n_trials_per_chunk = chunk_paths // SIMS_PER_TRIAL

    pos_gpu = torch.tensor(positions, dtype=DTYPE, device=DEVICE)
    bid_gpu = torch.tensor([QUOTES[s][0] for s in INSTR], dtype=DTYPE, device=DEVICE)
    ask_gpu = torch.tensor([QUOTES[s][1] for s in INSTR], dtype=DTYPE, device=DEVICE)
    cost_gpu = torch.clamp(pos_gpu, min=0.0) @ ask_gpu - torch.clamp(-pos_gpu, min=0.0) @ bid_gpu

    trial_scores = np.empty((n_strats, n_trials_total), dtype=np.float32)
    for ci in range(n_chunks):
        gen = torch.Generator(device=DEVICE).manual_seed(seed + ci)
        S_T, S_2w, min_S = gen_paths(chunk_paths, gen, sigma=sigma, obs_per_day=obs_per_day,
                                      jump_lambda=jump_lambda, jump_sigma=jump_sigma)
        M = compute_payoff_matrix(S_T, S_2w, min_S)
        pnl = pos_gpu @ M - cost_gpu.unsqueeze(1)
        trial_chunk = pnl.view(n_strats, n_trials_per_chunk, SIMS_PER_TRIAL).mean(dim=2) * CONTRACT_MULTIPLIER
        tstart = ci * n_trials_per_chunk
        trial_scores[:, tstart:tstart+n_trials_per_chunk] = trial_chunk.cpu().numpy()
        del S_T, S_2w, min_S, M, pnl, trial_chunk
        torch.cuda.empty_cache()

    means = trial_scores.mean(axis=1)
    sds = trial_scores.std(axis=1, ddof=1)
    sorted_s = np.sort(trial_scores, axis=1)
    n_t = sorted_s.shape[1]
    cvar5 = sorted_s[:, :max(1, n_t * 5 // 100)].mean(axis=1)
    return means, sds, cvar5


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2_results", type=str, default="results/phase2_10kseeds_results.json")
    parser.add_argument("--paths_per_test", type=int, default=50_000_000)
    parser.add_argument("--chunk", type=int, default=1_000_000)
    parser.add_argument("--top_n", type=int, default=20)
    parser.add_argument("--out", type=str, default="results/phase3_results.json")
    args = parser.parse_args()

    print("="*100)
    print("PHASE 3: SENSITIVITY (sigma, KO monitoring, jumps)")
    print("="*100)

    with open(args.phase2_results) as f:
        p2 = json.load(f)

    # Take top N from Phase 2 ranking
    candidates = p2["ranking"][:args.top_n]
    names = [c["name"] for c in candidates]
    positions = np.array([encode_position(c["positions"]) for c in candidates], dtype=np.int32)

    print(f"\nLoaded {len(candidates)} top candidates from {args.phase2_results}")

    # Sigma sweep
    print(f"\n--- SIGMA SWEEP ({args.paths_per_test:,} paths per sigma) ---")
    sigma_grid = [2.20, 2.30, 2.40, 2.45, 2.49, 2.51, 2.515, 2.52, 2.55, 2.60, 2.70, 2.80]
    sigma_results = {}
    for sigma in sigma_grid:
        t0 = time.time()
        means, sds, cvar5 = evaluate_under_model(positions, args.paths_per_test, 30000000,
                                                  args.chunk, sigma=sigma)
        sigma_results[sigma] = {"means": means.tolist(), "sds": sds.tolist(), "cvar5": cvar5.tolist()}
        print(f"  sigma={sigma:.3f}: {time.time()-t0:.0f}s, top mean = ${means.max():,.0f}")

    # KO monitoring frequency sweep
    print(f"\n--- KO MONITORING SWEEP ---")
    obs_grid = [1, 2, 4, 8, 16]
    ko_results = {}
    for obs in obs_grid:
        t0 = time.time()
        means, sds, cvar5 = evaluate_under_model(positions, args.paths_per_test, 40000000,
                                                  args.chunk, obs_per_day=obs)
        ko_results[obs] = {"means": means.tolist(), "sds": sds.tolist(), "cvar5": cvar5.tolist()}
        print(f"  obs/day={obs:>3}: {time.time()-t0:.0f}s, top mean = ${means.max():,.0f}")

    # Jump-diffusion sensitivity
    print(f"\n--- MERTON JUMP-DIFFUSION SWEEP ---")
    jump_grid = [(0, 0), (1, 0.1), (5, 0.1), (10, 0.2), (20, 0.3)]
    jump_results = {}
    for lam, jsig in jump_grid:
        t0 = time.time()
        means, sds, cvar5 = evaluate_under_model(positions, args.paths_per_test, 50000000,
                                                  args.chunk, jump_lambda=lam, jump_sigma=jsig)
        jump_results[f"l{lam}_s{jsig}"] = {"means": means.tolist(), "sds": sds.tolist(), "cvar5": cvar5.tolist()}
        print(f"  lambda={lam}, jump_sigma={jsig}: {time.time()-t0:.0f}s, top mean = ${means.max():,.0f}")

    # Print summary table
    print("\n" + "="*150)
    print(f"SIGMA SENSITIVITY (E[score] for each strategy across sigma)")
    print("="*150)
    print(f"{'Strategy':<48}", end="")
    for sigma in sigma_grid:
        print(f"{'sigma=' + str(sigma):>11}", end="")
    print()
    for i, name in enumerate(names[:10]):
        print(f"{name[:46]:<48}", end="")
        for sigma in sigma_grid:
            print(f"${sigma_results[sigma]['means'][i]:>+9,.0f}".replace(',', ','), end="  ")
        print()

    out = {
        "n_candidates": len(names),
        "names": names,
        "positions": [c["positions"] for c in candidates],
        "sigma_grid": sigma_grid,
        "sigma_results": {str(k): v for k, v in sigma_results.items()},
        "ko_obs_grid": obs_grid,
        "ko_results": {str(k): v for k, v in ko_results.items()},
        "jump_grid": [list(t) for t in jump_grid],
        "jump_results": jump_results,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {args.out}")


if __name__ == "__main__":
    main()
