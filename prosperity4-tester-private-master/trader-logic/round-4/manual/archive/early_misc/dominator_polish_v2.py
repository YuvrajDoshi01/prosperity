"""Polish v2: search for dominators of DOM_NICE itself (find the actual Pareto frontier)."""
import numpy as np
from constrained_opt import (build_trial_pnl_matrix, simulated_annealing, coord_polish,
                              score_signed, stats, _fast_q5_cvar5, fmt_q, SYMBOLS, CAPS)

DOM_NICE = np.array([0, 0, 30, 0, 0, 50, 0, 50, 50, -50, -50, 500])
OPT_7POS = np.array([0, 50, 25, 0, 0, 0, 0, 50, 50, -50, -50, 500])


def main():
    buy_mat, sell_mat = build_trial_pnl_matrix(
        total_paths=2_000_000, sims_per_trial=100, chunk_size=2_000_000,
        cache_path="trader-logic/round-4/manual/_trial_pnl_cache.npz", seed=42)

    target_mean = stats(score_signed(DOM_NICE, buy_mat, sell_mat))["mean"]
    print(f"DOM_NICE: mean=${target_mean:+,.0f}  CVaR=${stats(score_signed(DOM_NICE, buy_mat, sell_mat))['cvar5']:+,.0f}")

    def obj(q):
        s = score_signed(q, buy_mat, sell_mat)
        m = float(s.mean()); _, cv = _fast_q5_cvar5(s)
        # max CVaR s.t. mean >= target_mean
        violation = max(0.0, target_mean - m)
        return cv - 200.0 * violation

    # Many starts
    starts = []
    for c2 in [50, 45, 40]:
        for ac50p in [0, 5, 10, 15]:
            for ac50c in [25, 30, 35, 40]:
                for ac45p in [40, 45, 50]:
                    starts.append(np.array([0, ac50p, ac50c, 0, 0, ac45p, 0, 50, c2, -50, -50, 500]))
    starts.append(DOM_NICE.copy())
    starts.append(OPT_7POS.copy())

    best = []
    for si, q0 in enumerate(starts[:60]):  # cap to 60 starts
        q_sa, _ = simulated_annealing(buy_mat, sell_mat, obj, q0=q0.copy(),
                                       n_iter=3000, T0=20000.0, T_end=5.0, seed=si)
        q_sa, _ = coord_polish(buy_mat, sell_mat, obj, q_sa, max_passes=3, step_set=(1,3,10))
        st = stats(score_signed(q_sa, buy_mat, sell_mat))
        if st["mean"] >= target_mean - 200:
            best.append((st["cvar5"], st["mean"], q_sa))

    seen = set(); uniq = []
    for cv, m, q in sorted(best, key=lambda x: -x[0]):
        k = tuple(q.tolist())
        if k not in seen:
            seen.add(k); uniq.append((cv, m, q))

    print(f"\n{len(uniq)} unique candidates with mean >= DOM_NICE - $200, sorted by CVaR desc:")
    for i, (cv, m, q) in enumerate(uniq[:10]):
        st = stats(score_signed(q, buy_mat, sell_mat))
        print(f"  #{i+1}: mean=${m:+12,.0f} CVaR=${cv:+12,.0f} SD=${st['sd']:+12,.0f}")
        print(f"       q={fmt_q(q)}")


if __name__ == "__main__":
    main()
