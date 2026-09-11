"""Extended strategy comparison: 12 candidate portfolios, 200k MC paths, full risk metrics.

Includes Pareto frontier exploration. Run while quant/ml/cp agents work in parallel.
"""
import math
import random
from statistics import NormalDist

S0 = 50.0
SIGMA = 2.51
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_2W_DAYS = 10
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W = T_3W_DAYS * STEPS_PER_DAY
N_2W = T_2W_DAYS * STEPS_PER_DAY
ND = NormalDist()


def bs_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0: return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * ND.cdf(d1) - K * ND.cdf(d2)

def bs_put(S, K, T, sigma):
    if T <= 0 or sigma <= 0: return max(K - S, 0.0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * ND.cdf(-d2) - S * ND.cdf(-d1)


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

T_3W = T_3W_DAYS / 252; T_2W = T_2W_DAYS / 252
FV = {
    "AC":         50.0,
    "AC_50_P":    bs_put(S0, 50, T_3W, SIGMA),
    "AC_50_C":    bs_call(S0, 50, T_3W, SIGMA),
    "AC_35_P":    bs_put(S0, 35, T_3W, SIGMA),
    "AC_40_P":    bs_put(S0, 40, T_3W, SIGMA),
    "AC_45_P":    bs_put(S0, 45, T_3W, SIGMA),
    "AC_60_C":    bs_call(S0, 60, T_3W, SIGMA),
    "AC_50_P_2":  bs_put(S0, 50, T_2W, SIGMA),
    "AC_50_C_2":  bs_call(S0, 50, T_2W, SIGMA),
    "AC_50_CO":   bs_call(S0, 50, T_3W, SIGMA) + bs_put(S0, 50, T_2W, SIGMA),
    "AC_40_BP":   10.0 * (1 - ND.cdf((math.log(S0/40) - 0.5*SIGMA**2*T_3W)/(SIGMA*math.sqrt(T_3W)))),
    "AC_45_KO":   0.207,
}


def payoff(sym, S_T, S_T_2w, min_S):
    if sym == "AC":         return S_T
    if sym == "AC_50_P":    return max(50 - S_T, 0)
    if sym == "AC_50_C":    return max(S_T - 50, 0)
    if sym == "AC_35_P":    return max(35 - S_T, 0)
    if sym == "AC_40_P":    return max(40 - S_T, 0)
    if sym == "AC_45_P":    return max(45 - S_T, 0)
    if sym == "AC_60_C":    return max(S_T - 60, 0)
    if sym == "AC_50_P_2":  return max(50 - S_T_2w, 0)
    if sym == "AC_50_C_2":  return max(S_T_2w - 50, 0)
    if sym == "AC_50_CO":
        if S_T_2w >= 50: return max(S_T - 50, 0)
        else:            return max(50 - S_T, 0)
    if sym == "AC_40_BP":   return 10.0 if S_T < 40 else 0.0
    if sym == "AC_45_KO":   return max(45 - S_T, 0) if min_S > 35 else 0.0
    return 0.0


def gen_paths(n_sims, seed):
    rng = random.Random(seed)
    drift_step = -0.5 * SIGMA * SIGMA * DT
    vol_step = SIGMA * math.sqrt(DT)
    paths = []
    for _ in range(n_sims):
        S = S0; min_S = S0; S_at_2w = None
        for k in range(N_3W):
            z = rng.gauss(0.0, 1.0)
            S = S * math.exp(drift_step + vol_step * z)
            if S < min_S: min_S = S
            if k + 1 == N_2W: S_at_2w = S
        paths.append((S, min_S, S_at_2w))
    return paths


def strategy_pnl(strategy, paths):
    pnls = []
    for S_T, min_S, S_T_2w in paths:
        pnl = 0.0
        for sym, side, vol in strategy:
            bid, ask, _ = QUOTES[sym]
            p = payoff(sym, S_T, S_T_2w, min_S)
            if side == "buy":
                pnl += vol * (p - ask)
            else:
                pnl += vol * (bid - p)
        pnls.append(pnl)
    return pnls


def stats(pnls):
    n = len(pnls)
    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    sd = var ** 0.5
    sorted_p = sorted(pnls)
    return {
        "mean": mean, "sd": sd,
        "median": sorted_p[n // 2],
        "p_pos": sum(1 for p in pnls if p > 0) / n * 100,
        "min": min(pnls), "max": max(pnls),
        "cvar5": sum(sorted_p[:int(n*0.05)]) / int(n*0.05),
        "cvar10": sum(sorted_p[:int(n*0.10)]) / int(n*0.10),
        "cvar25": sum(sorted_p[:int(n*0.25)]) / int(n*0.25),
        "p95": sorted_p[int(n*0.95)],
        "p05": sorted_p[int(n*0.05)],
        "sharpe": mean / sd if sd > 0 else 0,
    }


CANDIDATES = {
    "MAX_EV": [  # all positive-edge at max size
        ("AC_50_CO", "sell", 50),
        ("AC_45_KO", "buy",  500),
        ("AC_40_BP", "sell", 50),
        ("AC_50_P_2","buy",  50),
        ("AC_50_C_2","buy",  50),
        ("AC_60_C",  "sell", 50),
    ],
    "USER_REF": [  # the strategy the user shared
        ("AC_50_CO", "sell", 15),
        ("AC_40_BP", "sell", 50),
        ("AC_50_P",  "buy",  17),
        ("AC_50_P_2","buy",  15),
        ("AC_50_C",  "buy",  15),
        ("AC",       "buy",  150),
    ],
    "KO_HALF": [  # max EV but KO at 250
        ("AC_50_CO", "sell", 50),
        ("AC_45_KO", "buy",  250),
        ("AC_40_BP", "sell", 50),
        ("AC_50_P_2","buy",  50),
        ("AC_50_C_2","buy",  50),
        ("AC_60_C",  "sell", 50),
    ],
    "KO_QTR": [  # max EV but KO at 100
        ("AC_50_CO", "sell", 50),
        ("AC_45_KO", "buy",  100),
        ("AC_40_BP", "sell", 50),
        ("AC_50_P_2","buy",  50),
        ("AC_50_C_2","buy",  50),
        ("AC_60_C",  "sell", 50),
    ],
    "NO_KO": [  # remove KO entirely
        ("AC_50_CO", "sell", 50),
        ("AC_40_BP", "sell", 50),
        ("AC_50_P_2","buy",  50),
        ("AC_50_C_2","buy",  50),
        ("AC_60_C",  "sell", 50),
    ],
    "PURE_PREMIUM": [  # only the highest-edge shorts
        ("AC_50_CO", "sell", 50),
        ("AC_40_BP", "sell", 50),
    ],
    "HEDGED_PREM": [  # premium shorts + 2w straddle hedge
        ("AC_50_CO", "sell", 50),
        ("AC_40_BP", "sell", 50),
        ("AC_50_P_2","buy",  50),
        ("AC_50_C_2","buy",  50),
    ],
    "FULL_HEDGE": [  # premium shorts + full hedge with 3w straddle long
        ("AC_50_CO", "sell", 50),
        ("AC_40_BP", "sell", 50),
        ("AC_50_P_2","buy",  50),
        ("AC_50_C_2","buy",  50),
        ("AC_50_P",  "buy",  10),
        ("AC_50_C",  "buy",  10),
    ],
    "MAX_PLUS": [  # max EV plus chooser-hedging straddle on 3w
        ("AC_50_CO", "sell", 50),
        ("AC_45_KO", "buy",  500),
        ("AC_40_BP", "sell", 50),
        ("AC_50_P_2","buy",  50),
        ("AC_50_C_2","buy",  50),
        ("AC_60_C",  "sell", 50),
        ("AC_50_P",  "buy",  10),  # hedge chooser-put-leg
    ],
    "WALL_ONLY": [  # ONLY KO (highest reward)
        ("AC_45_KO", "buy",  500),
    ],
    "NO_VANILLA_KO": [  # premium shorts + 2w straddle + KO at moderate size
        ("AC_50_CO", "sell", 50),
        ("AC_45_KO", "buy",  300),
        ("AC_40_BP", "sell", 50),
        ("AC_50_P_2","buy",  50),
        ("AC_50_C_2","buy",  50),
    ],
}


N_SIMS = 200_000
print(f"Generating {N_SIMS:,} paths (seed=42)...")
paths = gen_paths(N_SIMS, seed=42)
print("done.\n")

# Compute theoretical EV for each candidate
print("--- Theoretical EV (sum of per-position edge) ---")
for name, strat in CANDIDATES.items():
    ev = 0.0
    for sym, side, vol in strat:
        bid, ask, _ = QUOTES[sym]
        if side == "buy":
            ev += vol * (FV[sym] - ask)
        else:
            ev += vol * (bid - FV[sym])
    print(f"  {name:18s} EV = {ev:+8.3f}")

# MC stats for each
print(f"\n--- {N_SIMS:,}-path MC results ---")
print(f"{'Name':<18} {'Mean':>9} {'Median':>9} {'SD':>9} {'Sharpe':>8} {'P>0':>7} {'CVaR5':>10} {'CVaR10':>10} {'CVaR25':>10} {'P95':>9}")
results = {}
for name, strat in CANDIDATES.items():
    pnls = strategy_pnl(strat, paths)
    s = stats(pnls)
    results[name] = s
    print(f"{name:<18} {s['mean']:+9.2f} {s['median']:+9.2f} {s['sd']:>9.1f} {s['sharpe']:>8.4f} "
          f"{s['p_pos']:>6.1f}% {s['cvar5']:>+10.1f} {s['cvar10']:>+10.1f} {s['cvar25']:>+10.1f} {s['p95']:>+9.1f}")

# Pareto frontier (mean vs SD)
print("\n--- Pareto frontier candidates (high mean / low SD) ---")
sorted_by_sharpe = sorted(results.items(), key=lambda x: -x[1]["sharpe"])
print(f"{'Rank':<5} {'Name':<18} {'Mean':>9} {'SD':>9} {'Sharpe':>8}")
for i, (name, s) in enumerate(sorted_by_sharpe, 1):
    print(f"{i:<5} {name:<18} {s['mean']:+9.2f} {s['sd']:>9.1f} {s['sharpe']:>8.4f}")

# Score noise analysis
print("\n--- 100-sim score noise (SE/sqrt(100) = SD/10) ---")
for name in ["MAX_EV", "USER_REF", "KO_HALF", "KO_QTR", "NO_KO", "HEDGED_PREM", "MAX_PLUS"]:
    s = results[name]
    se = s["sd"] / 10
    lo, hi = s["mean"] - 1.96 * se, s["mean"] + 1.96 * se
    print(f"  {name:<18} predicted score = {s['mean']:+8.2f} ± {1.96*se:5.1f} (95% CI: [{lo:+8.1f}, {hi:+8.1f}])")
