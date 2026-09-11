"""Deep Pareto-frontier sweep: 50+ candidate strategies, 10M paths,
empirical (E[score], CVaR-5%) frontier + sensitivity to KO fair value & sigma.

Goal: confirm or refine PRIOR_FINAL as the risk-adjusted Pareto-optimal pick.
"""
import numpy as np
import time
import json

S0 = 50.0
SIGMA = 2.51
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_2W_DAYS = 10
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W = T_3W_DAYS * STEPS_PER_DAY
N_2W = T_2W_DAYS * STEPS_PER_DAY
CONTRACT_MULTIPLIER = 3000

QUOTES = {
    "AC":          (49.975, 50.025, 200),
    "AC_50_P":     (12.00,  12.05,  50),
    "AC_50_C":     (12.00,  12.05,  50),
    "AC_35_P":     ( 4.33,   4.35,  50),
    "AC_40_P":     ( 6.50,   6.55,  50),
    "AC_45_P":     ( 9.05,   9.10,  50),
    "AC_60_C":     ( 8.80,   8.85,  50),
    "AC_50_P_2":   ( 9.70,   9.75,  50),
    "AC_50_C_2":   ( 9.70,   9.75,  50),
    "AC_50_CO":    (22.20,  22.30,  50),
    "AC_40_BP":    ( 5.00,   5.10,  50),
    "AC_45_KO":    ( 0.15,   0.175, 500),
}

def per_path_payoffs(S_T, S_2w, min_S):
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
        "AC_50_CO":   np.where(S_2w >= 50, np.maximum(S_T - 50, 0.0), np.maximum(50 - S_T, 0.0)),
        "AC_40_BP":   np.where(S_T < 40, 10.0, 0.0),
        "AC_45_KO":   np.where(min_S > 35, np.maximum(45 - S_T, 0.0), 0.0),
    }

def strategy_per_path_pnl(strategy, payoffs):
    pnl = np.zeros_like(next(iter(payoffs.values())))
    for sym, side, vol in strategy:
        bid, ask, _ = QUOTES[sym]
        p = payoffs[sym]
        if side == "buy":
            pnl += vol * (p - ask)
        else:
            pnl += vol * (bid - p)
    return pnl

def gen_paths(n_paths, rng, sigma=SIGMA):
    drift = -0.5 * sigma * sigma * DT
    vol = sigma * np.sqrt(DT)
    S = np.full(n_paths, S0, dtype=np.float64)
    min_S = S.copy()
    S_2w = None
    for k in range(N_3W):
        z = rng.standard_normal(n_paths)
        S = S * np.exp(drift + vol * z)
        np.minimum(min_S, S, out=min_S)
        if k + 1 == N_2W:
            S_2w = S.copy()
    return S, S_2w, min_S


def build_candidates():
    """Build a comprehensive grid of candidate strategies for Pareto sweep."""
    cands = {}
    # Baseline: drop_60c with various KO sizes
    for ko in [0, 50, 100, 150, 200, 250, 300, 400, 500]:
        s = [("AC_50_CO","sell",50),("AC_40_BP","sell",50),("AC_50_P_2","buy",50),("AC_50_C_2","buy",50)]
        if ko > 0:
            s.append(("AC_45_KO","buy",ko))
        cands[f"NoHedge_KO{ko}"] = s

    # With 3w put hedges (no call hedge, no AC)
    for ko in [200, 300, 500]:
        for n_p in [25, 50]:
            s = [("AC_50_CO","sell",50),("AC_40_BP","sell",50),("AC_50_P_2","buy",50),("AC_50_C_2","buy",50),
                 ("AC_50_P","buy",n_p)]
            if ko > 0:
                s.append(("AC_45_KO","buy",ko))
            cands[f"P{n_p}_KO{ko}"] = s

    # With both P and C 3w hedges
    for ko in [200, 300, 500]:
        for n_p in [25, 50]:
            for n_c in [10, 25, 50]:
                s = [("AC_50_CO","sell",50),("AC_40_BP","sell",50),("AC_50_P_2","buy",50),("AC_50_C_2","buy",50),
                     ("AC_50_P","buy",n_p),("AC_50_C","buy",n_c)]
                if ko > 0:
                    s.append(("AC_45_KO","buy",ko))
                cands[f"P{n_p}_C{n_c}_KO{ko}"] = s

    # Symmetric hedge with AETHER long
    for ac in [0, 5, 10, 25, 50]:
        s = [("AC_50_CO","sell",50),("AC_45_KO","buy",500),("AC_40_BP","sell",50),
             ("AC_50_P_2","buy",50),("AC_50_C_2","buy",50),
             ("AC_50_P","buy",50),("AC_50_C","buy",25)]
        if ac > 0:
            s.append(("AC",  "buy", ac))
        cands[f"PRIOR_FINAL_AC{ac}"] = s

    # Tail-protect: BUY deep-OTM puts (negative EV but tail hedge)
    for ko in [200, 300, 500]:
        for n_p35 in [10, 25]:
            s = [("AC_50_CO","sell",50),("AC_40_BP","sell",50),("AC_50_P_2","buy",50),("AC_50_C_2","buy",50),
                 ("AC_50_P","buy",50),("AC_50_C","buy",25),("AC_45_KO","buy",ko),
                 ("AC_35_P","buy",n_p35)]
            cands[f"TailHedge_P35={n_p35}_KO{ko}"] = s

    # Reference points
    cands["DROP_60C"] = [("AC_50_CO","sell",50),("AC_45_KO","buy",500),("AC_40_BP","sell",50),
                        ("AC_50_P_2","buy",50),("AC_50_C_2","buy",50)]
    cands["PRIOR_FINAL"] = [("AC_50_CO","sell",50),("AC_45_KO","buy",500),("AC_40_BP","sell",50),
                           ("AC_50_P_2","buy",50),("AC_50_C_2","buy",50),
                           ("AC_50_P","buy",50),("AC_50_C","buy",25),("AC","buy",5)]
    cands["USER_SAFE"] = [("AC_50_CO","sell",15),("AC_40_BP","sell",50),("AC_45_KO","buy",60),
                         ("AC_50_P","buy",17),("AC_50_P_2","buy",15),("AC_50_C","buy",15)]
    return cands


def eval_strategies(strategies, S_T, S_2w, min_S, sims_per_trial=100, mult=CONTRACT_MULTIPLIER):
    """Evaluate all strategies on the same paths. Return per-trial-score arrays."""
    payoffs = per_path_payoffs(S_T, S_2w, min_S)
    n_paths = len(S_T)
    n_trials = n_paths // sims_per_trial
    results = {}
    for name, strat in strategies.items():
        pnl = strategy_per_path_pnl(strat, payoffs)
        # Group into trials
        trial_scores = pnl[:n_trials*sims_per_trial].reshape(n_trials, sims_per_trial).mean(axis=1) * mult
        results[name] = trial_scores
    return results


def stats(scores):
    n = len(scores)
    mean = float(np.mean(scores))
    sd = float(np.std(scores, ddof=1))
    median = float(np.median(scores))
    pct_pos = float((scores > 0).mean() * 100)
    p1 = float(np.percentile(scores, 1))
    p5 = float(np.percentile(scores, 5))
    p10 = float(np.percentile(scores, 10))
    cvar5 = float(np.mean(scores[scores <= p5]))
    cvar1 = float(np.mean(scores[scores <= p1]))
    return {"mean": mean, "sd": sd, "median": median, "pos": pct_pos,
            "p1": p1, "p5": p5, "p10": p10, "cvar1": cvar1, "cvar5": cvar5}


def main():
    print("Building candidates...")
    cands = build_candidates()
    print(f"Total candidates: {len(cands)}")

    # Generate 50M paths for the Pareto sweep (500K trials × 100 each)
    TOTAL_PATHS = 50_000_000
    CHUNK = 5_000_000
    print(f"\nGenerating {TOTAL_PATHS:,} paths in {TOTAL_PATHS//CHUNK} chunks...")
    rng = np.random.default_rng(seed=42)

    # Concatenate per-strategy PnL across chunks
    all_pnls = {name: [] for name in cands}
    t0 = time.time()
    for ci in range(TOTAL_PATHS // CHUNK):
        S_T, S_2w, min_S = gen_paths(CHUNK, rng, sigma=SIGMA)
        payoffs = per_path_payoffs(S_T, S_2w, min_S)
        for name, strat in cands.items():
            pnl = strategy_per_path_pnl(strat, payoffs)
            all_pnls[name].append(pnl)
        print(f"  chunk {ci+1}/{TOTAL_PATHS//CHUNK} ({time.time()-t0:.0f}s)")

    # Concatenate and form trial scores
    print(f"\nForming trial scores...")
    results = {}
    for name in cands:
        all_pnl = np.concatenate(all_pnls[name])
        n_trials = len(all_pnl) // 100
        trial_scores = all_pnl[:n_trials*100].reshape(n_trials, 100).mean(axis=1) * CONTRACT_MULTIPLIER
        results[name] = stats(trial_scores)

    # Print sorted by mean (top 30)
    print("\n" + "=" * 130)
    print(f"{'Strategy':<28} {'Mean':>12} {'Median':>12} {'SD':>12} {'P>0':>6} {'CVaR1%':>13} {'CVaR5%':>13} {'Sharpe':>8}")
    print("=" * 130)
    sorted_by_mean = sorted(results.items(), key=lambda x: -x[1]["mean"])
    for name, s in sorted_by_mean[:35]:
        sharpe = s["mean"]/s["sd"] if s["sd"] > 0 else 0
        print(f"{name:<28} ${s['mean']:>+11,.0f} ${s['median']:>+11,.0f} ${s['sd']:>11,.0f} "
              f"{s['pos']:>5.1f}% ${s['cvar1']:>+12,.0f} ${s['cvar5']:>+12,.0f} {sharpe:>8.4f}")

    # Pareto frontier on (mean, CVaR5)
    print("\n" + "=" * 130)
    print("PARETO FRONTIER on (mean, CVaR-5%)")
    print("=" * 130)
    pts = [(name, s["mean"], s["cvar5"], s["sd"], s["pos"]) for name, s in results.items()]
    # A is dominated if there exists B with mean_B >= mean_A AND cvar_B >= cvar_A AND (strictly better in at least one)
    pareto = []
    for i, (name_i, m_i, c_i, sd_i, p_i) in enumerate(pts):
        dominated = False
        for j, (name_j, m_j, c_j, sd_j, p_j) in enumerate(pts):
            if i == j: continue
            if m_j >= m_i and c_j >= c_i and (m_j > m_i or c_j > c_i):
                dominated = True
                break
        if not dominated:
            pareto.append((name_i, m_i, c_i, sd_i, p_i))
    pareto.sort(key=lambda x: -x[1])
    print(f"{'Strategy':<28} {'Mean':>12} {'CVaR5%':>13} {'SD':>12} {'P>0':>6}")
    for name, m, c, sd, p in pareto:
        print(f"{name:<28} ${m:>+11,.0f} ${c:>+12,.0f} ${sd:>11,.0f} {p:>5.1f}%")

    # Save
    with open("trader-logic/round-4/manual/pareto_deep_results.json", "w") as f:
        json.dump({k: {kk: vv for kk, vv in v.items()} for k, v in results.items()}, f, indent=2)

    print(f"\nDone. {time.time()-t0:.0f}s total. Saved to pareto_deep_results.json")


if __name__ == "__main__":
    main()
