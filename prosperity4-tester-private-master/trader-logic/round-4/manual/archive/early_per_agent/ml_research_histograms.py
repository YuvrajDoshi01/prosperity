"""Distribution histograms (text-based) for the top candidates."""
import numpy as np
import time
import ml_research as MR


def histogram_text(pnl, bins=20, width=60):
    """ASCII histogram with bin labels."""
    lo, hi = np.percentile(pnl, [0.5, 99.5])
    counts, edges = np.histogram(pnl.clip(lo, hi), bins=bins)
    max_ct = counts.max()
    lines = []
    for i in range(bins):
        bar = "#" * int(width * counts[i] / max_ct)
        lines.append(f"  [{edges[i]:+9.1f}, {edges[i+1]:+9.1f})  {counts[i]:>9,d}  {bar}")
    return "\n".join(lines)


def main():
    print("Generating 10M paths...")
    SEEDS = [101, 202, 303, 404, 505]
    t0 = time.time()
    chunks = [MR.simulate_paths(2_000_000, seed=s) for s in SEEDS]
    paths = {k: np.concatenate([c[k] for c in chunks]) for k in ["S_T", "S_2w", "min_S"]}
    del chunks
    print(f"  Done in {time.time()-t0:.1f}s")
    P = MR.build_payoff_matrix(paths)
    pnl_buy, pnl_sell = MR.build_unit_pnl(P)

    candidates = {
        "MaxSize_writeup":    {"AC_50_CO": -50, "AC_45_KO": +500, "AC_40_BP": -50,
                                "AC_50_P_2": +50, "AC_50_C_2": +50, "AC_60_C": -50},
        "Hybrid_drop60C":     {"AC_50_CO": -50, "AC_45_KO": +500, "AC_40_BP": -50,
                                "AC_50_P_2": +50, "AC_50_C_2": +50},
        "ROBUST_50P2_BP_KO":  {"AC_50_P_2": +50, "AC_40_BP": -50, "AC_45_KO": +500},
        "TIGHT_BP_KO":        {"AC_40_BP": -50, "AC_45_KO": +500},
        "MinVar_BPonly":      {"AC_40_BP": -50},
        "User_reference":     {"AC_50_CO": -15, "AC_40_BP": -50, "AC_50_P": +17,
                                "AC_50_P_2": +15, "AC_50_C": +15, "AETHER": +150},
    }

    for name, d in candidates.items():
        pos = MR.positions_from_dict(d)
        pnl = MR.portfolio_pnl_per_path(pos, pnl_buy, pnl_sell)
        print("\n" + "=" * 80)
        print(f"  {name}   positions={d}")
        print(f"  mean={pnl.mean():+.2f}  SD={pnl.std(ddof=1):.1f}  "
              f"P>0={(pnl>0).mean()*100:.2f}%  median={np.median(pnl):+.2f}")
        print("  P5/P25/P50/P75/P95 = "
              f"{np.percentile(pnl,5):+.1f} / {np.percentile(pnl,25):+.1f} / "
              f"{np.percentile(pnl,50):+.1f} / {np.percentile(pnl,75):+.1f} / "
              f"{np.percentile(pnl,95):+.1f}")
        print("  Histogram (clipped to [P0.5, P99.5]):")
        print(histogram_text(pnl, bins=20, width=50))


if __name__ == "__main__":
    main()
