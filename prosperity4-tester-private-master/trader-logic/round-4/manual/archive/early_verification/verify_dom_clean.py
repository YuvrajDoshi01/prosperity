"""Verify DOM_CLEAN1, DOM_CLEAN2, DOM_NICE on fresh 200M paths against OPTIMAL_7POS."""
import numpy as np
import time

S0 = 50.0
SIGMA = 2.51
DT = 1.0 / (252 * 4)
N_3W = 60
N_2W = 40
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

STRATEGIES = {
    "OPTIMAL_7POS": [
        ("AC_50_CO",  "sell", 50), ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50), ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50), ("AC_50_P",   "buy",  50),
        ("AC_50_C",   "buy",  25),
    ],
    "DOM_NICE": [
        ("AC_50_CO",  "sell", 50), ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50), ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50), ("AC_50_C",   "buy",  30),
        ("AC_45_P",   "buy",  50),  # NEW — replaces 50_P with 45_P
    ],
    "DOM_CLEAN2": [
        ("AC_50_CO",  "sell", 50), ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50), ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  45),  # was 50, now 45
        ("AC_50_C",   "buy",  25), ("AC_45_P",   "buy",  50),
    ],
    "DOM_CLEAN1": [
        ("AC_50_CO",  "sell", 50), ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50), ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  40),  # less C_2
        ("AC_50_C",   "buy",  30), ("AC_45_P",   "buy",  50),
    ],
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
        "AC_45_KO":   np.where(min_S >= 35, np.maximum(45 - S_T, 0.0), 0.0),
    }


def strat_pnl(strat, payoffs):
    pnl = np.zeros_like(next(iter(payoffs.values())))
    for sym, side, vol in strat:
        bid, ask, _ = QUOTES[sym]
        p = payoffs[sym]
        if side == "buy":
            pnl += vol * (p - ask)
        else:
            pnl += vol * (bid - p)
    return pnl


def gen_paths(n, rng):
    drift = -0.5 * SIGMA * SIGMA * DT
    vol = SIGMA * np.sqrt(DT)
    S = np.full(n, S0, dtype=np.float64)
    min_S = S.copy()
    S_2w = None
    for k in range(N_3W):
        z = rng.standard_normal(n)
        S = S * np.exp(drift + vol * z)
        np.minimum(min_S, S, out=min_S)
        if k+1 == N_2W: S_2w = S.copy()
    return S, S_2w, min_S


# 200M paths fresh seed
TOTAL = 200_000_000
CHUNK = 5_000_000
N_CHUNKS = TOTAL // CHUNK

results = {n: [] for n in STRATEGIES}
rng = np.random.default_rng(seed=2718281)
t0 = time.time()
for ci in range(N_CHUNKS):
    S_T, S_2w, min_S = gen_paths(CHUNK, rng)
    payoffs = per_path_payoffs(S_T, S_2w, min_S)
    for name, strat in STRATEGIES.items():
        pnl = strat_pnl(strat, payoffs)
        trials = pnl.reshape(CHUNK//100, 100).mean(axis=1) * CONTRACT_MULTIPLIER
        results[name].append(trials)
    if (ci+1) % 5 == 0:
        print(f"  chunk {ci+1}/{N_CHUNKS} ({time.time()-t0:.0f}s)")

for name in STRATEGIES:
    results[name] = np.concatenate(results[name])

print(f"\n{'='*120}")
print(f"4-WAY VERIFICATION on 200M paths fresh seed (2M trials of 100 each)")
print(f"{'='*120}")
print(f"{'Strategy':<16} {'Mean':>14} {'Median':>14} {'SD':>14} {'P>0':>6} {'CVaR-5%':>14} {'CVaR-2%':>14} {'CVaR-1%':>14} {'Sharpe':>8}")

for name in ["OPTIMAL_7POS", "DOM_NICE", "DOM_CLEAN2", "DOM_CLEAN1"]:
    s = results[name]
    mean = s.mean(); sd = s.std(ddof=1); med = np.median(s); pos = (s>0).mean()*100
    q5 = np.percentile(s, 5); cvar5 = s[s <= q5].mean()
    q2 = np.percentile(s, 2); cvar2 = s[s <= q2].mean()
    q1 = np.percentile(s, 1); cvar1 = s[s <= q1].mean()
    print(f"{name:<16} ${mean:>+13,.0f} ${med:>+13,.0f} ${sd:>13,.0f} {pos:>5.1f}% ${cvar5:>+13,.0f} ${cvar2:>+13,.0f} ${cvar1:>+13,.0f} {mean/sd:>8.4f}")

# Paired comparisons against OPTIMAL_7POS
print(f"\n{'='*120}")
print(f"PAIRED DIFFERENCES vs OPTIMAL_7POS (same paths)")
print(f"{'='*120}")
opt = results["OPTIMAL_7POS"]
for name in ["DOM_NICE", "DOM_CLEAN2", "DOM_CLEAN1"]:
    diff = results[name] - opt
    se = diff.std(ddof=1) / np.sqrt(len(diff))
    t_stat = diff.mean() / se
    cvar5_opt = opt[opt <= np.percentile(opt, 5)].mean()
    cvar5_new = results[name][results[name] <= np.percentile(results[name], 5)].mean()
    cvar5_diff = cvar5_new - cvar5_opt
    print(f"\n{name} - OPTIMAL_7POS:")
    print(f"  Mean diff      = ${diff.mean():>+10,.2f}  (SE=${se:.2f}, t={t_stat:.2f})")
    print(f"  CVaR-5% diff   = ${cvar5_diff:>+10,.0f}")
    print(f"  P(beats OPT)   = {(diff > 0).mean()*100:.2f}%")

print(f"\nTotal time: {time.time()-t0:.0f}s")
