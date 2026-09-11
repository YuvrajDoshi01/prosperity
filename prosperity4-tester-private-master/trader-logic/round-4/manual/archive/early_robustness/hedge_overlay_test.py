"""
Hedge Overlay Test — DROP_60C base vs vanilla put add-ons (Synthia hint #4).

Tests whether adding 3-week vanilla puts at K=40 and/or K=35 to DROP_60C
softens the cliff/barrier discontinuities. Acceptance criteria:
    - Mean drop  <  $5/unit  (= < $15k per-trial PnL after x3000)
    - 5%-CVaR improves > $5/unit (= > $15k risk reduction)
    - Sharpe improves

Synthia hint context:
    - BP cliff at S=40 (binary jumps $0->$10): a vanilla put at K=40 pays
      max(40 - S_T, 0), partially offsetting the SELLER's cliff loss.
    - KO barrier at B=35 (KO put extinguishes at min_S<35, exact zone of
      tail loss): a vanilla put at K=35 pays max(35 - S_T, 0), giving
      uncapped down-protection beyond the KO barrier.

Variants tested vs DROP_60C base:
    H1: +25 AC_40_P
    H2: +50 AC_40_P
    H3: +25 AC_35_P
    H4: +50 AC_35_P
    H5: +25 AC_40_P + +25 AC_35_P  (combined)

Engine: identical to r4_simulation_FINAL.py. 50M paths default for stability.
We use COMMON RANDOM NUMBERS — every variant evaluated on the SAME GBM paths
as DROP_60C, so paired-difference statistics are tight.
"""
import numpy as np
import time
import argparse
import json
from typing import Dict, List, Tuple

# Locked model params (mirror r4_simulation_FINAL.py exactly)
S0 = 50.0
SIGMA_ANNUAL = 2.51
TRADING_DAYS_PER_YEAR = 252
STEPS_PER_DAY = 4
DT = 1.0 / (TRADING_DAYS_PER_YEAR * STEPS_PER_DAY)
T_3W_DAYS = 15
T_2W_DAYS = 10
N_3W_STEPS = T_3W_DAYS * STEPS_PER_DAY
N_2W_STEPS = T_2W_DAYS * STEPS_PER_DAY
CONTRACT_MULTIPLIER = 3000
SIMS_PER_TRIAL = 100

QUOTES: Dict[str, Tuple[float, float, int]] = {
    "AC":          (49.975, 50.025, 200),
    "AC_50_P":     (12.000, 12.050,  50),
    "AC_50_C":     (12.000, 12.050,  50),
    "AC_35_P":     ( 4.330,  4.350,  50),
    "AC_40_P":     ( 6.500,  6.550,  50),
    "AC_45_P":     ( 9.050,  9.100,  50),
    "AC_60_C":     ( 8.800,  8.850,  50),
    "AC_50_P_2":   ( 9.700,  9.750,  50),
    "AC_50_C_2":   ( 9.700,  9.750,  50),
    "AC_50_CO":    (22.200, 22.300,  50),
    "AC_40_BP":    ( 5.000,  5.100,  50),
    "AC_45_KO":    ( 0.150,  0.175, 500),
}
LIMITS = {k: v[2] for k, v in QUOTES.items()}

# Base + hedge variants
BASE = [
    ("AC_50_CO",  "sell", 50),
    ("AC_45_KO",  "buy",  500),
    ("AC_40_BP",  "sell", 50),
    ("AC_50_P_2", "buy",  50),
    ("AC_50_C_2", "buy",  50),
]

STRATEGIES: Dict[str, List[Tuple[str, str, int]]] = {
    "DROP_60C":         BASE,
    "H1_40P25":         BASE + [("AC_40_P", "buy", 25)],
    "H2_40P50":         BASE + [("AC_40_P", "buy", 50)],
    "H3_35P25":         BASE + [("AC_35_P", "buy", 25)],
    "H4_35P50":         BASE + [("AC_35_P", "buy", 50)],
    "H5_40P25_35P25":   BASE + [("AC_40_P", "buy", 25), ("AC_35_P", "buy", 25)],
    # Bonus exploration
    "H6_40P50_35P50":   BASE + [("AC_40_P", "buy", 50), ("AC_35_P", "buy", 50)],
    "H7_35P50_40P25":   BASE + [("AC_40_P", "buy", 25), ("AC_35_P", "buy", 50)],
}


def validate(name: str, strat) -> None:
    net = {}
    for sym, side, vol in strat:
        net[sym] = net.get(sym, 0) + (vol if side == "buy" else -vol)
    for sym, q in net.items():
        if abs(q) > LIMITS[sym]:
            raise ValueError(f"{name}: |{sym}|={abs(q)} > cap {LIMITS[sym]}")


def generate_paths(n_paths: int, rng):
    drift_step = -0.5 * SIGMA_ANNUAL * SIGMA_ANNUAL * DT
    vol_step = SIGMA_ANNUAL * np.sqrt(DT)
    S = np.full(n_paths, S0, dtype=np.float64)
    min_S = S.copy()
    S_2w = None
    for k in range(N_3W_STEPS):
        z = rng.standard_normal(n_paths)
        S = S * np.exp(drift_step + vol_step * z)
        np.minimum(min_S, S, out=min_S)
        if k + 1 == N_2W_STEPS:
            S_2w = S.copy()
    return S, S_2w, min_S


def compute_payoffs(S_T, S_2w, min_S):
    return {
        "AC":         S_T,
        "AC_50_P":    np.maximum(50 - S_T, 0.0),
        "AC_50_C":    np.maximum(S_T - 50, 0.0),
        "AC_35_P":    np.maximum(35 - S_T, 0.0),
        "AC_40_P":    np.maximum(40 - S_T, 0.0),
        "AC_45_P":    np.maximum(45 - S_T, 0.0),
        "AC_60_C":    np.maximum(S_T - 60, 0.0),
        "AC_50_P_2":  np.maximum(50 - S_2w, 0.0),
        "AC_50_C_2":  np.maximum(S_2w - 50, 0.0),
        "AC_50_CO":   np.where(S_2w >= 50,
                               np.maximum(S_T - 50, 0.0),
                               np.maximum(50 - S_T, 0.0)),
        "AC_40_BP":   np.where(S_T < 40, 10.0, 0.0),
        "AC_45_KO":   np.where(min_S >= 35, np.maximum(45 - S_T, 0.0), 0.0),
    }


def per_path_pnl(strategy, payoffs):
    pnl = np.zeros_like(next(iter(payoffs.values())))
    for sym, side, vol in strategy:
        bid, ask, _ = QUOTES[sym]
        p = payoffs[sym]
        if side == "buy":
            pnl += vol * (p - ask)
        else:
            pnl += vol * (bid - p)
    return pnl


def summarize(scores, label):
    n = len(scores)
    mean = float(scores.mean())
    sd = float(scores.std(ddof=1))
    pcts = {p: float(np.percentile(scores, p)) for p in [0.1, 1, 2, 5, 10]}
    cvar = {p: float(scores[scores <= pcts[p]].mean()) for p in [1, 2, 5, 10]}
    return {
        "label": label, "n": n, "mean": mean, "sd": sd,
        "sharpe": mean / sd if sd > 0 else 0.0,
        "pct_pos": float((scores > 0).mean() * 100),
        "percentiles": pcts, "cvar": cvar,
    }


def run(strategies, total_paths, chunk_size, seed):
    if total_paths % chunk_size != 0 or chunk_size % SIMS_PER_TRIAL != 0:
        raise ValueError("size mismatch")
    n_chunks = total_paths // chunk_size
    n_trials = total_paths // SIMS_PER_TRIAL
    n_trials_per_chunk = chunk_size // SIMS_PER_TRIAL

    for name, s in strategies.items():
        validate(name, s)

    trial_scores = {name: np.empty(n_trials, dtype=np.float64) for name in strategies}
    rng = np.random.default_rng(seed)
    t0 = time.time()
    print(f"Generating {total_paths:,} paths in {n_chunks} chunks of {chunk_size:,}, seed={seed}")

    for ci in range(n_chunks):
        S_T, S_2w, min_S = generate_paths(chunk_size, rng)
        payoffs = compute_payoffs(S_T, S_2w, min_S)

        for name, strat in strategies.items():
            pnl_per_path = per_path_pnl(strat, payoffs)
            chunk_trials = (
                pnl_per_path[:n_trials_per_chunk * SIMS_PER_TRIAL]
                .reshape(n_trials_per_chunk, SIMS_PER_TRIAL)
                .mean(axis=1) * CONTRACT_MULTIPLIER
            )
            start = ci * n_trials_per_chunk
            trial_scores[name][start:start + n_trials_per_chunk] = chunk_trials

        del payoffs, S_T, S_2w, min_S
        if (ci + 1) % max(1, n_chunks // 10) == 0:
            elapsed = time.time() - t0
            eta = elapsed * (n_chunks - ci - 1) / (ci + 1)
            print(f"  chunk {ci+1:>3}/{n_chunks} elapsed {elapsed:>5.1f}s ETA {eta:>5.0f}s")

    print(f"Path gen done in {time.time()-t0:.0f}s\n")

    summaries = {name: summarize(trial_scores[name], name) for name in strategies}
    return summaries, trial_scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=50_000_000)
    ap.add_argument("--chunk", type=int, default=2_500_000)
    ap.add_argument("--seed", type=int, default=20260427)
    ap.add_argument("--out", type=str, default="hedge_overlay_results.json")
    args = ap.parse_args()

    print("="*100)
    print("HEDGE OVERLAY TEST — DROP_60C base vs vanilla put add-ons")
    print(f"sigma={SIGMA_ANNUAL}  T_3w={T_3W_DAYS}td  multiplier x{CONTRACT_MULTIPLIER}")
    print("="*100 + "\n")

    summaries, scores = run(STRATEGIES, args.paths, args.chunk, args.seed)

    # Print absolute summary
    print("="*120)
    print(f"{'Strategy':<22} {'Mean':>14} {'SD':>13} {'Sharpe':>8} {'P>0':>7} "
          f"{'CVaR-5%':>14} {'CVaR-2%':>14} {'CVaR-1%':>14}")
    print("-"*120)
    order = ["DROP_60C"] + [k for k in STRATEGIES if k != "DROP_60C"]
    for n in order:
        r = summaries[n]
        print(f"{n:<22} ${r['mean']:>+13,.0f} ${r['sd']:>12,.0f} {r['sharpe']:>8.4f} "
              f"{r['pct_pos']:>6.2f}% ${r['cvar'][5]:>+13,.0f} ${r['cvar'][2]:>+13,.0f} "
              f"${r['cvar'][1]:>+13,.0f}")

    # Paired diff vs DROP_60C (tight via common random numbers)
    print("\n" + "="*120)
    print("PAIRED DELTAS vs DROP_60C (common random numbers; identical paths)")
    print("="*120)
    base = scores["DROP_60C"]
    base_mean = base.mean()
    base_sd = base.std(ddof=1)
    base_sharpe = base_mean / base_sd if base_sd > 0 else 0.0
    print(f"{'Variant':<22} {'dMean':>12} {'dSD':>12} {'dSharpe':>10} "
          f"{'dCVaR-5%':>14} {'dCVaR-2%':>14} {'t-stat(mean)':>14} {'verdict':<14}")
    print("-"*120)
    deltas = {}
    for n in order:
        if n == "DROP_60C":
            continue
        s = scores[n]
        diff = s - base
        d_mean = diff.mean()
        d_sd = s.std(ddof=1) - base_sd
        d_sharpe = (s.mean() / s.std(ddof=1) if s.std(ddof=1) > 0 else 0.0) - base_sharpe
        # paired t (per-trial)
        t_stat = d_mean / (diff.std(ddof=1) / np.sqrt(len(diff)))

        # CVaR deltas (strategy-specific tail; not paired in a strict sense)
        for p in [5, 2]:
            pass
        d_cvar_5 = summaries[n]["cvar"][5] - summaries["DROP_60C"]["cvar"][5]
        d_cvar_2 = summaries[n]["cvar"][2] - summaries["DROP_60C"]["cvar"][2]

        # Acceptance: mean drop < $15k AND CVaR-5% improves > $15k AND Sharpe improves
        mean_ok = d_mean > -15_000
        cvar_ok = d_cvar_5 > 15_000
        sharpe_ok = d_sharpe > 0
        accept = mean_ok and cvar_ok and sharpe_ok
        verdict = "ACCEPT" if accept else "reject"
        print(f"{n:<22} ${d_mean:>+11,.0f} ${d_sd:>+11,.0f} {d_sharpe:>+10.4f} "
              f"${d_cvar_5:>+13,.0f} ${d_cvar_2:>+13,.0f} {t_stat:>+14.2f} {verdict:<14}")
        deltas[n] = {
            "d_mean": float(d_mean), "d_sd": float(d_sd), "d_sharpe": float(d_sharpe),
            "d_cvar_5": float(d_cvar_5), "d_cvar_2": float(d_cvar_2),
            "t_mean": float(t_stat),
            "mean_ok": mean_ok, "cvar_ok": cvar_ok, "sharpe_ok": sharpe_ok,
            "accept": accept,
        }

    # Persist
    out = {
        "config": {"paths": args.paths, "seed": args.seed, "sigma": SIGMA_ANNUAL,
                   "multiplier": CONTRACT_MULTIPLIER, "trials": args.paths // SIMS_PER_TRIAL},
        "summaries": {n: {k: v for k, v in r.items() if k != "label"}
                      for n, r in summaries.items()},
        "deltas_vs_DROP_60C": deltas,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
