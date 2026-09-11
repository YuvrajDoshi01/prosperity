"""High-fidelity verification of the top dominator candidates from polish."""
import numpy as np
import time
from verify_dominator import run_seed, stats

# Top candidates from dominator_polish.py (200K-trial fits)
PORTS = {
    "OPTIMAL_7POS":  np.array([0,  50,  25,   0,   0,   0,   0,  50,  50, -50, -50, 500]),
    "DROP_60C":      np.array([0,   0,   0,   0,   0,   0,   0,  50,  50, -50, -50, 500]),
    "DOM_TOP1":      np.array([0,   2,  31,  -2,   0,  50,   0,  50,  41, -50, -50, 500]),
    "DOM_TOP2":      np.array([0,   4,  31,  -4,   0,  50,   0,  50,  42, -50, -50, 498]),
    "DOM_TOP7":      np.array([0,   7,  31,   0,   0,  46,   0,  50,  43, -50, -50, 494]),
    # Cleaner integer variants
    "DOM_CLEAN1":    np.array([0,   0,  30,   0,   0,  50,   0,  50,  40, -50, -50, 500]),
    "DOM_CLEAN2":    np.array([0,   0,  25,   0,   0,  50,   0,  50,  45, -50, -50, 500]),
    "DOM_NICE":      np.array([0,   0,  30,   0,   0,  50,   0,  50,  50, -50, -50, 500]),
}


def main():
    SEEDS = [1001, 2002, 3003, 4004, 5005, 6006, 7007, 8008]
    PATHS_PER_SEED = 10_000_000
    print(f"{len(SEEDS)} seeds x {PATHS_PER_SEED:,} paths = {len(SEEDS)*PATHS_PER_SEED:,} total")

    seed_results = {name: [] for name in PORTS}
    t0 = time.time()
    for si, seed in enumerate(SEEDS):
        ts = time.time()
        buy, sell = run_seed(seed, PATHS_PER_SEED)
        for name, q in PORTS.items():
            m, sd, cv = stats(buy, sell, q)
            seed_results[name].append((m, sd, cv))
        print(f"  seed {seed}: {time.time()-ts:.1f}s")

    print(f"\n{'='*100}")
    print(f"VERIFICATION  ({len(SEEDS)} seeds x {PATHS_PER_SEED//100:,} trials)")
    print(f"{'='*100}")
    print(f"{'name':<16} {'mean(avg)':>13} {'mean(sem)':>11} {'CVaR-5%(avg)':>15} {'CVaR(sem)':>11} {'SD(avg)':>13}  delta_m  delta_cv")
    summary = {}
    for name in PORTS:
        a = np.array(seed_results[name])
        m = a[:, 0]; sd = a[:, 1]; cv = a[:, 2]
        summary[name] = dict(
            mean=m.mean(), mean_sem=m.std(ddof=1) / np.sqrt(len(SEEDS)),
            cvar5=cv.mean(), cvar5_sem=cv.std(ddof=1) / np.sqrt(len(SEEDS)),
            sd=sd.mean(),
        )

    opt = summary["OPTIMAL_7POS"]
    for name, s in summary.items():
        dm = s["mean"] - opt["mean"]
        dcv = s["cvar5"] - opt["cvar5"]
        sem_m = np.sqrt(s["mean_sem"]**2 + opt["mean_sem"]**2)
        sem_cv = np.sqrt(s["cvar5_sem"]**2 + opt["cvar5_sem"]**2)
        print(f"{name:<16} ${s['mean']:>+12,.0f} ${s['mean_sem']:>+10,.0f} ${s['cvar5']:>+14,.0f} ${s['cvar5_sem']:>+10,.0f} ${s['sd']:>+12,.0f}"
              f"  dm=${dm:>+7,.0f}({dm/sem_m:+.1f}s) dcv=${dcv:>+8,.0f}({dcv/sem_cv:+.1f}s)")

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
