"""Verify the candidate Pareto dominator against OPTIMAL_7POS at high fidelity.

Uses 10M paths (100K trials, ~5K-sample 5% tail). Multi-seed averaging to bound
noise. Compares (mean, CVaR-5%) of three candidates:
  - OPTIMAL_7POS                         (user-claimed Pareto point)
  - DOM_CANDIDATE (from 200K-trial run)  (proposed dominator)
  - DROP_60C                             (highest-mean reference)

If DOM_CANDIDATE has BOTH mean >= OPTIMAL_7POS and CVaR-5% > OPTIMAL_7POS within noise,
report as confirmed Pareto dominator.
"""
import numpy as np
import time

S0 = 50.0
SIGMA = 2.51
DT = 1.0 / (252 * 4)
N_3W = 60
N_2W = 40
MULT = 3000

SYMBOLS = ["AC", "AC_50_P", "AC_50_C", "AC_35_P", "AC_40_P", "AC_45_P",
           "AC_60_C", "AC_50_P_2", "AC_50_C_2", "AC_50_CO", "AC_40_BP", "AC_45_KO"]
QUOTES = {
    "AC": (49.975, 50.025), "AC_50_P": (12.00, 12.05), "AC_50_C": (12.00, 12.05),
    "AC_35_P": (4.33, 4.35), "AC_40_P": (6.50, 6.55), "AC_45_P": (9.05, 9.10),
    "AC_60_C": (8.80, 8.85), "AC_50_P_2": (9.70, 9.75), "AC_50_C_2": (9.70, 9.75),
    "AC_50_CO": (22.20, 22.30), "AC_40_BP": (5.00, 5.10), "AC_45_KO": (0.15, 0.175),
}

OPT7    = np.array([0,  50,  25,   0,   0,   0,   0,  50,  50, -50, -50, 500])
DROP_60 = np.array([0,   0,   0,   0,   0,   0,   0,  50,  50, -50, -50, 500])
DOM     = np.array([0,  25,  30,   0,   0,  21,   0,  50,  47, -50, -50, 500])
DOM_INT = np.array([0,  25,  30,   0,   0,  21,   0,  50,  50, -50, -50, 500])  # +AC_50_C_2 to 50

PORTS = {"OPTIMAL_7POS": OPT7, "DROP_60C": DROP_60, "DOM_CANDIDATE": DOM, "DOM_C2_at_50": DOM_INT}


def gen_path(n, rng):
    drift = -0.5 * SIGMA * SIGMA * DT
    vol = SIGMA * np.sqrt(DT)
    S = np.full(n, S0)
    minS = S.copy()
    S2w = None
    for k in range(N_3W):
        S = S * np.exp(drift + vol * rng.standard_normal(n))
        np.minimum(minS, S, out=minS)
        if k + 1 == N_2W:
            S2w = S.copy()
    return S, S2w, minS


def payoffs(S_T, S_2w, min_S):
    return np.stack([
        S_T,
        np.maximum(50 - S_T, 0.0),
        np.maximum(S_T - 50, 0.0),
        np.maximum(35 - S_T, 0.0),
        np.maximum(40 - S_T, 0.0),
        np.maximum(45 - S_T, 0.0),
        np.maximum(S_T - 60, 0.0),
        np.maximum(50 - S_2w, 0.0),
        np.maximum(S_2w - 50, 0.0),
        np.where(S_2w >= 50, np.maximum(S_T - 50, 0.0), np.maximum(50 - S_T, 0.0)),
        np.where(S_T < 40, 10.0, 0.0),
        np.where(min_S > 35, np.maximum(45 - S_T, 0.0), 0.0),
    ], axis=1)  # (n, 12)


def run_seed(seed, total_paths, sims_per_trial=100, chunk=2_000_000):
    asks = np.array([QUOTES[s][1] for s in SYMBOLS])
    bids = np.array([QUOTES[s][0] for s in SYMBOLS])
    n_trials = total_paths // sims_per_trial
    trials_per_chunk = chunk // sims_per_trial
    rng = np.random.default_rng(seed)
    buy_mat = np.empty((n_trials, 12), dtype=np.float32)
    sell_mat = np.empty((n_trials, 12), dtype=np.float32)
    for ci in range(total_paths // chunk):
        S_T, S_2w, min_S = gen_path(chunk, rng)
        pay = payoffs(S_T, S_2w, min_S)  # (chunk, 12)
        buy_pp = pay - asks[None, :]
        sell_pp = bids[None, :] - pay
        a = ci * trials_per_chunk
        b = a + trials_per_chunk
        buy_mat[a:b]  = buy_pp.reshape(trials_per_chunk, sims_per_trial, 12).mean(axis=1).astype(np.float32)
        sell_mat[a:b] = sell_pp.reshape(trials_per_chunk, sims_per_trial, 12).mean(axis=1).astype(np.float32)
    return buy_mat, sell_mat


def stats(buy_mat, sell_mat, q):
    pos_q = np.maximum(q, 0).astype(np.float32)
    neg_q = np.maximum(-q, 0).astype(np.float32)
    s = (buy_mat @ pos_q + sell_mat @ neg_q) * MULT
    n = s.shape[0]
    k = max(1, int(n * 0.05))
    part = np.partition(s, k - 1)
    cvar5 = float(part[:k].mean())
    return float(s.mean()), float(s.std(ddof=1)), cvar5


def main():
    SEEDS = [101, 202, 303, 404, 505]
    PATHS_PER_SEED = 10_000_000  # 100K trials each
    print(f"Verifying with {len(SEEDS)} seeds x {PATHS_PER_SEED:,} paths = {len(SEEDS)*PATHS_PER_SEED:,} total")
    print(f"Each seed -> {PATHS_PER_SEED // 100:,} trials\n")

    seed_results = {name: [] for name in PORTS}
    t0 = time.time()
    for si, seed in enumerate(SEEDS):
        ts = time.time()
        buy, sell = run_seed(seed, PATHS_PER_SEED)
        for name, q in PORTS.items():
            m, sd, cv = stats(buy, sell, q)
            seed_results[name].append((m, sd, cv))
        print(f"  seed {seed}: {time.time()-ts:.1f}s  (total {time.time()-t0:.1f}s)")

    print(f"\n{'='*92}")
    print(f"VERIFICATION RESULTS  ({len(SEEDS)} seeds, {PATHS_PER_SEED//100:,} trials/seed)")
    print(f"{'='*92}")
    print(f"{'portfolio':<18} {'mean (avg)':>14} {'mean (sem)':>12} {'CVaR-5% (avg)':>16} {'CVaR (sem)':>12} {'SD (avg)':>14}")
    summary = {}
    for name in PORTS:
        arr = np.array(seed_results[name])  # (5, 3)
        means = arr[:, 0]
        sds = arr[:, 1]
        cvs = arr[:, 2]
        m_avg, m_sem = means.mean(), means.std(ddof=1) / np.sqrt(len(SEEDS))
        cv_avg, cv_sem = cvs.mean(), cvs.std(ddof=1) / np.sqrt(len(SEEDS))
        sd_avg = sds.mean()
        print(f"{name:<18} ${m_avg:>+13,.0f} ${m_sem:>+11,.0f} ${cv_avg:>+15,.0f} ${cv_sem:>+11,.0f} ${sd_avg:>+13,.0f}")
        summary[name] = dict(mean=m_avg, mean_sem=m_sem, cvar5=cv_avg, cvar5_sem=cv_sem, sd=sd_avg)

    # Pareto comparison
    opt = summary["OPTIMAL_7POS"]
    dom = summary["DOM_CANDIDATE"]
    dom2 = summary["DOM_C2_at_50"]
    print(f"\n{'='*92}")
    print("PARETO COMPARISON: DOM_CANDIDATE vs OPTIMAL_7POS")
    print(f"{'='*92}")
    delta_m  = dom["mean"] - opt["mean"]
    delta_cv = dom["cvar5"] - opt["cvar5"]
    sem_m  = np.sqrt(dom["mean_sem"]**2 + opt["mean_sem"]**2)
    sem_cv = np.sqrt(dom["cvar5_sem"]**2 + opt["cvar5_sem"]**2)
    print(f"  mean delta:    ${delta_m:>+12,.0f}  +/- ${sem_m:>10,.0f}  (z={delta_m/sem_m:>+5.2f})")
    print(f"  CVaR-5% delta: ${delta_cv:>+12,.0f}  +/- ${sem_cv:>10,.0f}  (z={delta_cv/sem_cv:>+5.2f})")
    if delta_m / sem_m > -1.0 and delta_cv / sem_cv > 2.0:
        print(f"  >>> DOM_CANDIDATE PARETO-DOMINATES OPTIMAL_7POS (CVaR much better, mean within noise)")
    else:
        print(f"  >>> Pareto dominance INCONCLUSIVE; differences not robust at this fidelity.")

    print(f"\n{'='*92}")
    print("ALSO: DOM_C2_at_50 (rounded to integer caps)")
    print(f"{'='*92}")
    delta_m  = dom2["mean"] - opt["mean"]
    delta_cv = dom2["cvar5"] - opt["cvar5"]
    sem_m  = np.sqrt(dom2["mean_sem"]**2 + opt["mean_sem"]**2)
    sem_cv = np.sqrt(dom2["cvar5_sem"]**2 + opt["cvar5_sem"]**2)
    print(f"  mean delta:    ${delta_m:>+12,.0f}  +/- ${sem_m:>10,.0f}  (z={delta_m/sem_m:>+5.2f})")
    print(f"  CVaR-5% delta: ${delta_cv:>+12,.0f}  +/- ${sem_cv:>10,.0f}  (z={delta_cv/sem_cv:>+5.2f})")

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
