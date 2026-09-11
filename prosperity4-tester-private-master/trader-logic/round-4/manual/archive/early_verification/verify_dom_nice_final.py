"""Final big-budget verification of DOM_NICE dominance over OPTIMAL_7POS.

Uses 16 seeds x 12.5M paths = 200M total paths. SEM should drop to ~$200 on mean and ~$400 on CVaR.
"""
import numpy as np
import time
from verify_dominator import run_seed, stats

PORTS = {
    "OPTIMAL_7POS": np.array([0,  50,  25,   0,   0,   0,   0,  50,  50, -50, -50, 500]),
    "DROP_60C":     np.array([0,   0,   0,   0,   0,   0,   0,  50,  50, -50, -50, 500]),
    "DOM_NICE":     np.array([0,   0,  30,   0,   0,  50,   0,  50,  50, -50, -50, 500]),
    "DOM_CLEAN2":   np.array([0,   0,  25,   0,   0,  50,   0,  50,  45, -50, -50, 500]),
}

def main():
    SEEDS = [10001, 20002, 30003, 40004, 50005, 60006, 70007, 80008,
             90009, 100010, 110011, 120012, 130013, 140014, 150015, 160016]
    PATHS_PER_SEED = 12_500_000
    print(f"{len(SEEDS)} seeds x {PATHS_PER_SEED:,} = {len(SEEDS)*PATHS_PER_SEED:,} paths total\n")
    seed_results = {n: [] for n in PORTS}
    t0 = time.time()
    for si, seed in enumerate(SEEDS):
        ts = time.time()
        buy, sell = run_seed(seed, PATHS_PER_SEED)
        for n, q in PORTS.items():
            m, sd, cv = stats(buy, sell, q)
            seed_results[n].append((m, sd, cv))
        print(f"  seed {seed}: {time.time()-ts:.1f}s (total {time.time()-t0:.0f}s)")

    print(f"\n{'='*100}")
    print(f"FINAL VERIFICATION  (16 seeds x 125,000 trials = 2,000,000 trials)")
    print(f"{'='*100}\n")
    summary = {}
    for n in PORTS:
        a = np.array(seed_results[n])
        m = a[:, 0]; sd = a[:, 1]; cv = a[:, 2]
        summary[n] = dict(
            mean=m.mean(), mean_sem=m.std(ddof=1)/np.sqrt(len(SEEDS)),
            cvar5=cv.mean(), cvar5_sem=cv.std(ddof=1)/np.sqrt(len(SEEDS)),
            sd=sd.mean(),
        )

    print(f"{'name':<14} {'mean(avg)':>13} {'mean(sem)':>10} {'CVaR-5%(avg)':>15} {'CVaR(sem)':>10} {'SD':>13}")
    for n, s in summary.items():
        print(f"{n:<14} ${s['mean']:>+12,.0f} ${s['mean_sem']:>+9,.0f} ${s['cvar5']:>+14,.0f} ${s['cvar5_sem']:>+9,.0f} ${s['sd']:>+12,.0f}")

    opt = summary["OPTIMAL_7POS"]
    print(f"\nDeltas vs OPTIMAL_7POS:")
    for n, s in summary.items():
        if n == "OPTIMAL_7POS": continue
        dm = s["mean"] - opt["mean"]; dcv = s["cvar5"] - opt["cvar5"]
        sem_m = np.sqrt(s["mean_sem"]**2 + opt["mean_sem"]**2)
        sem_cv = np.sqrt(s["cvar5_sem"]**2 + opt["cvar5_sem"]**2)
        sig_m = dm / max(sem_m, 1.0); sig_cv = dcv / max(sem_cv, 1.0)
        print(f"  {n:<14}  delta_mean=${dm:>+8,.0f} (z={sig_m:>+5.2f})  delta_cvar=${dcv:>+9,.0f} (z={sig_cv:>+5.2f})")

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
