"""Extra exploration: scan all 2^6=64 on/off combinations of the 6 edge-positive
instruments, plus several KO sizing strategies, to find the global Pareto front
under both mean and 'expected leaderboard score' objectives.

Reuses the MC engine in ml_research.py.
"""
from __future__ import annotations

import math
import time
import itertools
import numpy as np

import ml_research as MR


def main():
    SEEDS = [101, 202, 303, 404, 505]
    PER_SEED = 2_000_000
    print(f"Generating {len(SEEDS)*PER_SEED:,} paths...")
    t0 = time.time()
    chunks = [MR.simulate_paths(PER_SEED, seed=s, sigma=MR.SIGMA) for s in SEEDS]
    paths = {
        "S_T":   np.concatenate([c["S_T"]   for c in chunks]),
        "S_2w":  np.concatenate([c["S_2w"]  for c in chunks]),
        "min_S": np.concatenate([c["min_S"] for c in chunks]),
    }
    del chunks
    print(f"  Done in {time.time()-t0:.1f}s")

    P = MR.build_payoff_matrix(paths)
    pnl_buy, pnl_sell = MR.build_unit_pnl(P)

    # 6 edge-positive instruments and their max-EV signed positions:
    EDGES = [
        ("AC_60_C",   -50),   # +0.41 EV
        ("AC_50_P_2", +50),   # +6.10
        ("AC_50_C_2", +50),   # +5.65
        ("AC_50_CO",  -50),   # +15.27
        ("AC_40_BP",  -50),   # +11.53
        ("AC_45_KO", +500),   # +15.79
    ]

    # ── Subset enumeration: 2^6 = 64 portfolios (each edge in or out) ───────
    print("\n" + "=" * 95)
    print("SUBSET SEARCH — all 2^6=64 on/off combinations of the 6 edges")
    print("=" * 95)
    print(f"  {'incl':<10} {'mean':>9} {'SD':>9} {'sharpe':>9} {'P>0%':>7} "
          f"{'score_SE':>10} {'score_P5':>10} {'score_P95':>10}")
    rows = []
    for mask in range(64):
        pos = np.zeros(MR.N_INST, dtype=np.int64)
        included = []
        for k, (sym, q) in enumerate(EDGES):
            if mask & (1 << k):
                pos[MR.INSTRUMENTS.index(sym)] = q
                included.append(sym.replace("AC_", ""))
        if not included:
            continue
        pnl = MR.portfolio_pnl_per_path(pos, pnl_buy, pnl_sell)
        m = float(pnl.mean()); sd = float(pnl.std(ddof=1))
        sharpe = m / sd if sd > 0 else float("nan")
        ppos = float((pnl > 0).mean()) * 100
        # Approximate 100-sim score sub-sample
        rng = np.random.default_rng(2026)
        sm = np.array([pnl[rng.integers(0, len(pnl), 100)].mean() for _ in range(2000)])
        score_se = float(sm.std(ddof=1))
        score_p5 = float(np.percentile(sm, 5))
        score_p95 = float(np.percentile(sm, 95))
        rows.append((mask, included, m, sd, sharpe, ppos, score_se, score_p5, score_p95, pos))

    # Sort by score_p5 descending (most robust)
    rows_p5 = sorted(rows, key=lambda r: -r[7])
    print("\n--- Top 12 by 5th-percentile of 100-sim score (ROBUST) ---")
    for r in rows_p5[:12]:
        mask, incl, m, sd, sh, pp, se, p5, p95, _ = r
        print(f"  {','.join(incl):<40} mean={m:+8.2f} SD={sd:8.1f} sharpe={sh:+.4f} "
              f"P>0={pp:5.1f}% SE={se:7.1f} P5={p5:+8.2f} P95={p95:+8.2f}")

    print("\n--- Top 12 by SHARPE ---")
    rows_sh = sorted(rows, key=lambda r: -r[4])
    for r in rows_sh[:12]:
        mask, incl, m, sd, sh, pp, se, p5, p95, _ = r
        print(f"  {','.join(incl):<40} mean={m:+8.2f} SD={sd:8.1f} sharpe={sh:+.4f} "
              f"P>0={pp:5.1f}% SE={se:7.1f} P5={p5:+8.2f} P95={p95:+8.2f}")

    print("\n--- Top 8 by MEAN ---")
    rows_mean = sorted(rows, key=lambda r: -r[2])
    for r in rows_mean[:8]:
        mask, incl, m, sd, sh, pp, se, p5, p95, _ = r
        print(f"  {','.join(incl):<40} mean={m:+8.2f} SD={sd:8.1f} sharpe={sh:+.4f} "
              f"P>0={pp:5.1f}% SE={se:7.1f} P5={p5:+8.2f} P95={p95:+8.2f}")

    # ── KO sizing on the Hybrid (drop 60C) base ─────────────────────────────
    print("\n" + "=" * 95)
    print("KO SIZING SWEEP on Hybrid (P_2/C_2/CO/BP fixed at max) — finer grid")
    print("=" * 95)
    base = np.zeros(MR.N_INST, dtype=np.int64)
    base[MR.INSTRUMENTS.index("AC_50_P_2")] = +50
    base[MR.INSTRUMENTS.index("AC_50_C_2")] = +50
    base[MR.INSTRUMENTS.index("AC_50_CO")]  = -50
    base[MR.INSTRUMENTS.index("AC_40_BP")]  = -50

    print(f"  {'KO_qty':>7} {'mean':>9} {'SD':>9} {'sharpe':>9} {'P>0%':>7} "
          f"{'score_SE':>10} {'score_P5':>10}")
    for ko in [0, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500]:
        pos = base.copy()
        pos[MR.INSTRUMENTS.index("AC_45_KO")] = ko
        pnl = MR.portfolio_pnl_per_path(pos, pnl_buy, pnl_sell)
        m = pnl.mean(); sd = pnl.std(ddof=1)
        rng = np.random.default_rng(2026)
        sm = np.array([pnl[rng.integers(0, len(pnl), 100)].mean() for _ in range(2000)])
        print(f"  {ko:>7d} {m:+9.2f} {sd:9.1f} {m/sd:+9.4f} {(pnl>0).mean()*100:7.2f} "
              f"{sm.std(ddof=1):10.2f} {np.percentile(sm,5):+10.2f}")

    # ── Drop the chooser short (largest SD contributor) ─────────────────────
    print("\n" + "=" * 95)
    print("DROP-ONE ablation — start from MaxSize and remove each edge")
    print("=" * 95)
    full = MR.positions_from_dict({
        "AC_50_CO": -50, "AC_45_KO": +500, "AC_40_BP": -50,
        "AC_50_P_2": +50, "AC_50_C_2": +50, "AC_60_C": -50,
    })
    print(f"  {'drop':<12} {'mean':>9} {'SD':>9} {'sharpe':>9} {'P>0%':>7} {'score_SE':>10} {'score_P5':>10}")
    pnl_full = MR.portfolio_pnl_per_path(full, pnl_buy, pnl_sell)
    rng = np.random.default_rng(2026)
    sm_full = np.array([pnl_full[rng.integers(0, len(pnl_full), 100)].mean() for _ in range(2000)])
    print(f"  {'(none)':<12} {pnl_full.mean():+9.2f} {pnl_full.std(ddof=1):9.1f} "
          f"{pnl_full.mean()/pnl_full.std(ddof=1):+9.4f} {(pnl_full>0).mean()*100:7.2f} "
          f"{sm_full.std(ddof=1):10.2f} {np.percentile(sm_full,5):+10.2f}")
    for sym in ["AC_50_CO", "AC_45_KO", "AC_40_BP", "AC_50_P_2", "AC_50_C_2", "AC_60_C"]:
        pos = full.copy()
        pos[MR.INSTRUMENTS.index(sym)] = 0
        pnl = MR.portfolio_pnl_per_path(pos, pnl_buy, pnl_sell)
        m = pnl.mean(); sd = pnl.std(ddof=1)
        rng = np.random.default_rng(2026)
        sm = np.array([pnl[rng.integers(0, len(pnl), 100)].mean() for _ in range(2000)])
        print(f"  {sym:<12} {m:+9.2f} {sd:9.1f} {m/sd:+9.4f} {(pnl>0).mean()*100:7.2f} "
              f"{sm.std(ddof=1):10.2f} {np.percentile(sm,5):+10.2f}")


if __name__ == "__main__":
    main()
