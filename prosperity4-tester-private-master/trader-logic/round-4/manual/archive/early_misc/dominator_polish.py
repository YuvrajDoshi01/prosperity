"""Polish the Pareto dominator: search for max-CVaR portfolio with mean >= OPTIMAL_7POS - $1k.

Use the cached 200K-trial PnL matrix. Run intensive multi-start coord-descent + SA from
several promising basins, keeping all candidates with mean >= 154,500 and CVaR-5% > -360k.
Then re-rank top 30 with a fresh 1M-trial sample (multi-seed) to break ties.
"""
import numpy as np
import time
from constrained_opt import (
    build_trial_pnl_matrix, simulated_annealing, coord_polish, score_signed,
    stats, _fast_q5_cvar5, fmt_q, SYMBOLS, CAPS,
    DROP_60C, OPTIMAL_7POS, GLOBAL_MAX_6P, PRIOR_FINAL_8P,
    make_obj_pareto,
)


def main():
    cache_path = "trader-logic/round-4/manual/_trial_pnl_cache.npz"
    buy_mat, sell_mat = build_trial_pnl_matrix(
        total_paths=2_000_000, sims_per_trial=100, chunk_size=2_000_000,
        cache_path=cache_path, seed=42,
    )
    print(f"trial mat: {buy_mat.shape}\n")

    OPT_MEAN = stats(score_signed(OPTIMAL_7POS, buy_mat, sell_mat))["mean"]
    OPT_CVAR = stats(score_signed(OPTIMAL_7POS, buy_mat, sell_mat))["cvar5"]
    print(f"OPTIMAL_7POS reference: mean=${OPT_MEAN:+,.0f}  CVaR-5%=${OPT_CVAR:+,.0f}\n")

    # Multi-start: many SA runs from perturbed starts, alpha mostly weighted toward CVaR
    # subject to mean >= OPT_MEAN - 2000
    candidates = []
    starts = [
        OPTIMAL_7POS.copy(),
        np.array([0,  25,  30,   0,   0,  21,   0,  50,  47, -50, -50, 500]),  # the dominator we found
        np.array([0,  25,  30,   0,   0,  21,   0,  50,  50, -50, -50, 500]),
        np.array([0,  30,  30,   0,   0,  20,   0,  50,  50, -50, -50, 500]),
        np.array([0,  20,  35,   0,   0,  25,   0,  50,  50, -50, -50, 500]),
        np.array([0,   0,  50,   0,   0,  30,   0,  50,  50, -50, -50, 500]),
        np.array([0,  50,  50,   0,   0,  20,   0,  50,  50, -50, -50, 500]),
        np.array([0,   0,   0,   0,   0,   0,   0,  50,  50, -50, -50, 500]),  # DROP_60C
        np.array([5,  25,  25,   0,   0,  20,   0,  50,  50, -50, -50, 500]),
    ]

    # Build constrained objective: max CVaR subject to mean >= OPT_MEAN - 2000
    target = OPT_MEAN - 2000.0  # allow small mean slack to find big CVaR gains
    def constrained_max_cvar(q):
        s = score_signed(q, buy_mat, sell_mat)
        m = float(s.mean()); _, cv = _fast_q5_cvar5(s)
        violation = max(0.0, target - m)
        return cv - 200.0 * violation

    print(f"Constrained search: max CVaR-5% s.t. mean >= ${target:+,.0f}")
    print(f"{'-'*92}")
    for si, q0 in enumerate(starts):
        # Multiple random alphas for diversity
        for alpha_seed in range(3):
            np.random.seed(si*7 + alpha_seed)
            q_sa, _ = simulated_annealing(buy_mat, sell_mat, constrained_max_cvar,
                                           q0=q0.copy(), n_iter=4000, T0=50000.0,
                                           T_end=10.0, seed=si*100 + alpha_seed)
            q_sa, _ = coord_polish(buy_mat, sell_mat, constrained_max_cvar, q_sa,
                                    max_passes=4, step_set=(1, 3, 10, 25))
            st = stats(score_signed(q_sa, buy_mat, sell_mat))
            if st["mean"] >= target - 100 and st["cvar5"] > OPT_CVAR + 1000:
                candidates.append((st["cvar5"], st["mean"], q_sa))

    # Deduplicate
    seen = set()
    uniq = []
    for cv, m, q in sorted(candidates, key=lambda x: -x[0]):
        key = tuple(q.tolist())
        if key not in seen:
            seen.add(key)
            uniq.append((cv, m, q))

    print(f"\nFound {len(uniq)} unique candidates with mean>=${target:+,.0f} and CVaR>OPT+$1k:")
    for i, (cv, m, q) in enumerate(uniq[:15]):
        st = stats(score_signed(q, buy_mat, sell_mat))
        print(f"  #{i+1:2d}: mean=${m:+12,.0f} CVaR=${cv:+12,.0f} SD=${st['sd']:+12,.0f}")
        print(f"       q={fmt_q(q)}")

    # Save top 5 for high-fidelity re-rank
    if uniq:
        with open("trader-logic/round-4/manual/dominator_candidates.txt", "w") as f:
            for i, (cv, m, q) in enumerate(uniq[:30]):
                f.write(f"#{i+1}: cvar5={cv:.1f} mean={m:.1f} q={q.tolist()}\n")

if __name__ == "__main__":
    main()
