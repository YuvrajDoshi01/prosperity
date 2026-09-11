"""Maximum-effort multi-objective Pareto sweep for R4 manual.

Optimizes simultaneously: max E[score], max CVaR-5% (95% CI lower), max CVaR-2% (98% CI lower).

Sweeps:
  CHOOSER size in {30, 40, 50}
  BP size in {30, 40, 50}
  KO size in {200, 300, 400, 500}
  3w put hedge in {0, 25, 50}
  3w call hedge in {0, 25, 50}
  35_P sell in {0, 25, 50}    -- tail premium
  40_P buy in {0, 25}          -- tail hedge
  Plus a few reference vectors

Total ~250 strategies, evaluated on 100M paths -> 1M trials of 100.
Identifies the Pareto-optimal points across (mean, CVaR-5%, CVaR-2%).
"""
import numpy as np
import time
import json
import itertools

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

INSTR_LIST = list(QUOTES.keys())
INSTR_IDX = {s: i for i, s in enumerate(INSTR_LIST)}


def per_path_payoff_matrix(S_T, S_2w, min_S):
    """Build (12, n_paths) payoff matrix."""
    n = len(S_T)
    M = np.zeros((12, n), dtype=np.float64)
    M[INSTR_IDX["AC"]]         = S_T
    M[INSTR_IDX["AC_50_P"]]    = np.maximum(50 - S_T, 0)
    M[INSTR_IDX["AC_50_C"]]    = np.maximum(S_T - 50, 0)
    M[INSTR_IDX["AC_35_P"]]    = np.maximum(35 - S_T, 0)
    M[INSTR_IDX["AC_40_P"]]    = np.maximum(40 - S_T, 0)
    M[INSTR_IDX["AC_45_P"]]    = np.maximum(45 - S_T, 0)
    M[INSTR_IDX["AC_60_C"]]    = np.maximum(S_T - 60, 0)
    M[INSTR_IDX["AC_50_P_2"]]  = np.maximum(50 - S_2w, 0)
    M[INSTR_IDX["AC_50_C_2"]]  = np.maximum(S_2w - 50, 0)
    M[INSTR_IDX["AC_50_CO"]]   = np.where(S_2w >= 50, np.maximum(S_T - 50, 0), np.maximum(50 - S_T, 0))
    M[INSTR_IDX["AC_40_BP"]]   = np.where(S_T < 40, 10.0, 0.0)
    M[INSTR_IDX["AC_45_KO"]]   = np.where(min_S > 35, np.maximum(45 - S_T, 0), 0.0)
    return M


def per_path_pnl_vec(strat_vec, payoff_matrix, quotes_arr):
    """strat_vec: (12,) signed quantity. positive=buy, negative=sell.
    payoff_matrix: (12, n_paths). quotes_arr: (12, 2) [bid, ask]."""
    # PnL per path = sum_i max(0, q_i)*(payoff_i - ask_i) + sum_i max(0, -q_i)*(bid_i - payoff_i)
    # = sum_i q_i*payoff_i - sum_i max(q_i,0)*ask_i - sum_i max(-q_i,0)*bid_i
    #   (where positive q_i pays ask, negative q_i receives bid)
    bid = quotes_arr[:, 0]
    ask = quotes_arr[:, 1]
    # Per-unit edge: if q>0 (buy), edge = payoff - ask; if q<0 (sell), edge = bid - payoff
    # Combined: q * payoff - ((q>0)*q*ask + (q<0)*(-q)*bid)
    # = q * payoff - (q+ * ask + q- * bid) where q+ = max(q,0), q- = max(-q,0)
    payoffs = payoff_matrix.T @ strat_vec  # (n_paths,)
    cost = np.maximum(strat_vec, 0).dot(ask) - np.maximum(-strat_vec, 0).dot(bid)
    return payoffs - cost


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


def encode(name_to_qty):
    """Convert {instrument_name: qty} to strat_vec (12,)."""
    v = np.zeros(12)
    for name, q in name_to_qty.items():
        v[INSTR_IDX[name]] = q
    return v


def build_strategies():
    """Build comprehensive grid of candidate strategies."""
    strats = {}

    # Baseline: chooser/BP/KO with 3w hedges and 2w straddle
    for co in [40, 50]:
        for bp in [40, 50]:
            for ko in [300, 400, 500]:
                for p3 in [0, 25, 50]:
                    for c3 in [0, 25, 50]:
                        positions = {
                            "AC_50_CO":  -co,
                            "AC_40_BP":  -bp,
                            "AC_45_KO":  +ko,
                            "AC_50_P_2": +50,
                            "AC_50_C_2": +50,
                        }
                        if p3 > 0: positions["AC_50_P"] = +p3
                        if c3 > 0: positions["AC_50_C"] = +c3
                        name = f"CO{co}_BP{bp}_KO{ko}_P{p3}_C{c3}"
                        strats[name] = positions

    # Add tail-hedge variants on top of best base (CO50, BP50, KO500, P50, C25)
    base = {"AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": +500,
            "AC_50_P_2": +50, "AC_50_C_2": +50, "AC_50_P": +50, "AC_50_C": +25}
    for k_extra, side_extra, q_extra in [
        ("AC_35_P", "buy",  10),  # deep-OTM tail BUY
        ("AC_35_P", "buy",  25),
        ("AC_35_P", "buy",  50),
        ("AC_35_P", "sell", 25),  # deep-OTM premium SELL (sell-edge slightly negative)
        ("AC_35_P", "sell", 50),
        ("AC_40_P", "buy",  10),
        ("AC_40_P", "buy",  25),
        ("AC_40_P", "buy",  50),
        ("AC_40_P", "sell", 25),
        ("AC_40_P", "sell", 50),
        ("AC_45_P", "buy",  25),
        ("AC_45_P", "sell", 25),
        ("AC_60_C", "sell", 25),
        ("AC_60_C", "sell", 50),
        ("AC_60_C", "buy",  25),
    ]:
        name = f"BASE+{side_extra.upper()}{q_extra}_{k_extra}"
        positions = dict(base)
        sign = +1 if side_extra == "buy" else -1
        positions[k_extra] = sign * q_extra
        strats[name] = positions

    # Combine 35_P with 40_P
    for q_35, side_35 in [(25, "buy"), (50, "sell")]:
        for q_40, side_40 in [(0, "buy"), (25, "buy"), (50, "sell")]:
            if q_40 == 0:
                continue
            name = f"BASE+{side_35.upper()}{q_35}_35P+{side_40.upper()}{q_40}_40P"
            positions = dict(base)
            positions["AC_35_P"] = (+1 if side_35=="buy" else -1) * q_35
            positions["AC_40_P"] = (+1 if side_40=="buy" else -1) * q_40
            strats[name] = positions

    # Reference points
    strats["DROP_60C"] = {"AC_50_CO":-50,"AC_40_BP":-50,"AC_45_KO":+500,"AC_50_P_2":+50,"AC_50_C_2":+50}
    strats["PRIOR_FINAL"] = {"AC_50_CO":-50,"AC_40_BP":-50,"AC_45_KO":+500,"AC_50_P_2":+50,"AC_50_C_2":+50,
                              "AC_50_P":+50,"AC_50_C":+25,"AC":+5}
    strats["USER_SAFE"] = {"AC_50_CO":-15,"AC_40_BP":-50,"AC_45_KO":+60,"AC_50_P":+17,"AC_50_P_2":+15,"AC_50_C":+15}
    strats["USER_GREEDY"] = {"AC_50_CO":-15,"AC_40_BP":-55,"AC_45_KO":+75,"AC_50_P":+22,"AC_50_P_2":+15,
                              "AC_50_C":+15,"AC":+30,"AC_45_P":+10,"AC_35_P":-15}
    strats["GLOBAL_MAX_with_60C"] = {"AC_50_CO":-50,"AC_40_BP":-50,"AC_45_KO":+500,"AC_50_P_2":+50,
                                       "AC_50_C_2":+50,"AC_60_C":-50}

    # Convert all to strat_vec format
    return {name: encode(pos) for name, pos in strats.items()}


def stats(scores, x):
    """Compute all relevant stats."""
    mean = float(scores.mean())
    sd = float(scores.std(ddof=1))
    median = float(np.median(scores))
    pos = float((scores > 0).mean() * 100)
    p_lo_2 = float(np.percentile(scores, 2))
    p_lo_5 = float(np.percentile(scores, 5))
    p_lo_10 = float(np.percentile(scores, 10))
    cvar2 = float(scores[scores <= p_lo_2].mean())
    cvar5 = float(scores[scores <= p_lo_5].mean())
    cvar10 = float(scores[scores <= p_lo_10].mean())
    return {"mean": mean, "sd": sd, "median": median, "pos": pos,
            "q2": p_lo_2, "q5": p_lo_5, "q10": p_lo_10,
            "cvar2": cvar2, "cvar5": cvar5, "cvar10": cvar10,
            "sharpe": mean/sd if sd > 0 else 0}


def main():
    strats = build_strategies()
    print(f"Total candidate strategies: {len(strats)}")
    names = list(strats.keys())
    n_strats = len(names)
    strat_matrix = np.array([strats[n] for n in names])  # (n_strats, 12)

    quotes_arr = np.array([[QUOTES[s][0], QUOTES[s][1]] for s in INSTR_LIST])  # (12, 2)

    TOTAL_PATHS = 50_000_000
    CHUNK = 1_000_000
    N_CHUNKS = TOTAL_PATHS // CHUNK
    SIMS_PER_TRIAL = 100
    N_TRIALS_PER_CHUNK = CHUNK // SIMS_PER_TRIAL  # 10K trials per chunk
    N_TRIALS = TOTAL_PATHS // SIMS_PER_TRIAL       # 500K trials total

    # Accumulate trial scores directly (much less memory)
    trial_scores = np.empty((n_strats, N_TRIALS), dtype=np.float64)

    bid = quotes_arr[:, 0]
    ask = quotes_arr[:, 1]
    # Per-strategy fixed cost
    cost = np.maximum(strat_matrix, 0) @ ask - np.maximum(-strat_matrix, 0) @ bid  # (n_strats,)

    rng = np.random.default_rng(seed=42)
    t0 = time.time()
    for ci in range(N_CHUNKS):
        S_T, S_2w, min_S = gen_paths(CHUNK, rng)
        M = per_path_payoff_matrix(S_T, S_2w, min_S)  # (12, CHUNK)

        pnl_chunk = strat_matrix @ M - cost[:, None]  # (n_strats, CHUNK)
        # Reshape into (n_strats, N_TRIALS_PER_CHUNK, 100) and take mean
        trial_chunk = pnl_chunk.reshape(n_strats, N_TRIALS_PER_CHUNK, SIMS_PER_TRIAL).mean(axis=2)
        # Apply multiplier
        trial_chunk = trial_chunk * CONTRACT_MULTIPLIER

        start = ci * N_TRIALS_PER_CHUNK
        trial_scores[:, start:start+N_TRIALS_PER_CHUNK] = trial_chunk

        del M, pnl_chunk, trial_chunk
        elapsed = time.time() - t0
        eta = (N_CHUNKS - ci - 1) * (elapsed / (ci+1))
        if (ci+1) % 5 == 0 or ci == 0:
            print(f"  chunk {ci+1}/{N_CHUNKS} ({elapsed:.0f}s, ETA {eta:.0f}s)")

    # Compute stats per strategy
    results = {}
    for i, name in enumerate(names):
        results[name] = stats(trial_scores[i], None)

    # Sort by mean and print top 50
    print(f"\n{'='*150}")
    print(f"TOP STRATEGIES BY E[score] (showing key risk metrics)")
    print(f"{'='*150}")
    print(f"{'Strategy':<42} {'Mean':>11} {'Median':>11} {'SD':>11} {'P>0':>5} {'q2':>11} {'CVaR2':>11} {'q5':>11} {'CVaR5':>11} {'Sharpe':>7}")
    sorted_names = sorted(names, key=lambda n: -results[n]["mean"])
    for name in sorted_names[:60]:
        s = results[name]
        print(f"{name:<42} ${s['mean']:>+10,.0f} ${s['median']:>+10,.0f} ${s['sd']:>10,.0f} "
              f"{s['pos']:>4.1f}% ${s['q2']:>+10,.0f} ${s['cvar2']:>+10,.0f} ${s['q5']:>+10,.0f} ${s['cvar5']:>+10,.0f} {s['sharpe']:>7.4f}")

    # 3-way Pareto frontier on (mean, CVaR-5%, CVaR-2%)
    # A is dominated if there exists B with mean_B >= A_mean AND cvar5_B >= A_cvar5 AND cvar2_B >= A_cvar2 (with at least one strict)
    print(f"\n{'='*150}")
    print(f"PARETO FRONTIER on (mean, CVaR-5%, CVaR-2%)")
    print(f"{'='*150}")
    pareto = []
    for i, name_i in enumerate(names):
        s_i = results[name_i]
        dominated = False
        for j, name_j in enumerate(names):
            if i == j: continue
            s_j = results[name_j]
            if (s_j["mean"] >= s_i["mean"] and s_j["cvar5"] >= s_i["cvar5"] and s_j["cvar2"] >= s_i["cvar2"]
                and (s_j["mean"] > s_i["mean"] or s_j["cvar5"] > s_i["cvar5"] or s_j["cvar2"] > s_i["cvar2"])):
                dominated = True
                break
        if not dominated:
            pareto.append(name_i)
    pareto.sort(key=lambda n: -results[n]["mean"])
    print(f"{'Strategy':<42} {'Mean':>11} {'CVaR5%':>11} {'CVaR2%':>11} {'SD':>11} {'P>0':>5} {'Sharpe':>7}")
    for name in pareto:
        s = results[name]
        print(f"{name:<42} ${s['mean']:>+10,.0f} ${s['cvar5']:>+10,.0f} ${s['cvar2']:>+10,.0f} ${s['sd']:>10,.0f} {s['pos']:>4.1f}% {s['sharpe']:>7.4f}")

    # Save results
    out = {name: results[name] for name in names}
    with open("trader-logic/round-4/manual/pareto_max_results.json", "w") as f:
        json.dump(out, f, indent=2)

    # Also dump the Pareto-frontier set
    pareto_data = {
        "pareto_frontier": pareto,
        "results": {name: results[name] for name in pareto},
    }
    with open("trader-logic/round-4/manual/pareto_max_frontier.json", "w") as f:
        json.dump(pareto_data, f, indent=2)

    print(f"\nDone in {time.time()-t0:.0f}s. Results saved.")


if __name__ == "__main__":
    main()
