"""Verify the REFINED_9POS dominator over OPTIMAL_7POS on fresh paths.

The constrained_opt agent found a strategy that strictly dominates OPTIMAL_7POS
on (mean, CVaR-5%). This script independently verifies on a different seed.
"""
import numpy as np
import time

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

OPTIMAL_7POS = [
    ("AC_50_CO",  "sell", 50),
    ("AC_45_KO",  "buy",  500),
    ("AC_40_BP",  "sell", 50),
    ("AC_50_P_2", "buy",  50),
    ("AC_50_C_2", "buy",  50),
    ("AC_50_P",   "buy",  50),
    ("AC_50_C",   "buy",  25),
]

# REFINED_9POS = OPTIMAL_7POS + 45_P BUY 50 + 35_P SELL 11 - 40 P_3w - 2 C_2 + 4 C_3w
REFINED_9POS = [
    ("AC_50_CO",  "sell", 50),
    ("AC_45_KO",  "buy",  500),
    ("AC_40_BP",  "sell", 50),
    ("AC_50_P_2", "buy",  50),
    ("AC_50_C_2", "buy",  48),  # was 50
    ("AC_50_P",   "buy",  10),  # was 50
    ("AC_50_C",   "buy",  29),  # was 25
    ("AC_45_P",   "buy",  50),  # NEW
    ("AC_35_P",   "sell", 11),  # NEW
]

# Sanity: verify limits
LIMITS = {k: v[2] for k, v in QUOTES.items()}
for name, strat in [("OPTIMAL_7POS", OPTIMAL_7POS), ("REFINED_9POS", REFINED_9POS)]:
    for sym, side, vol in strat:
        cap = LIMITS[sym]
        assert vol <= cap, f"{name}: |{sym}|={vol} > cap {cap}"
print("Position limits OK.")


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
        "AC_50_C_2": np.maximum(S_2w - 50, 0.0),
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
        if k+1 == N_2W:
            S_2w = S.copy()
    return S, S_2w, min_S


# Use FRESH seed (NOT 42) to avoid aligning with original MC
rng = np.random.default_rng(seed=999_999)

# 200M paths = 2M trials of 100 each — high precision
TOTAL = 200_000_000
CHUNK = 5_000_000
N_CHUNKS = TOTAL // CHUNK

results = {"OPTIMAL_7POS": [], "REFINED_9POS": []}
diff_list = []

t0 = time.time()
for ci in range(N_CHUNKS):
    S_T, S_2w, min_S = gen_paths(CHUNK, rng)
    payoffs = per_path_payoffs(S_T, S_2w, min_S)

    pnl_opt = strat_pnl(OPTIMAL_7POS, payoffs)
    pnl_ref = strat_pnl(REFINED_9POS, payoffs)

    # Group into 50K trials of 100 paths each
    trials_opt = pnl_opt.reshape(CHUNK//100, 100).mean(axis=1) * CONTRACT_MULTIPLIER
    trials_ref = pnl_ref.reshape(CHUNK//100, 100).mean(axis=1) * CONTRACT_MULTIPLIER

    results["OPTIMAL_7POS"].append(trials_opt)
    results["REFINED_9POS"].append(trials_ref)
    # Same paths -> paired diff
    diff_list.append(trials_ref - trials_opt)

    if (ci+1) % 5 == 0:
        print(f"  chunk {ci+1}/{N_CHUNKS} ({time.time()-t0:.0f}s)")

# Concat
results["OPTIMAL_7POS"] = np.concatenate(results["OPTIMAL_7POS"])
results["REFINED_9POS"] = np.concatenate(results["REFINED_9POS"])
diff_arr = np.concatenate(diff_list)

print(f"\n2M trials × 100 paths each = {TOTAL:,} total paths")
print(f"Generated in {time.time()-t0:.0f}s")

print("\n" + "="*100)
print("RESULTS — fresh seed, 2M trials per strategy")
print("="*100)
for name in ["OPTIMAL_7POS", "REFINED_9POS"]:
    s = results[name]
    mean = s.mean(); sd = s.std(ddof=1); med = np.median(s); pos = (s>0).mean()*100
    q5 = np.percentile(s, 5); cvar5 = s[s <= q5].mean()
    q2 = np.percentile(s, 2); cvar2 = s[s <= q2].mean()
    q1 = np.percentile(s, 1); cvar1 = s[s <= q1].mean()
    print(f"\n{name}:")
    print(f"  Mean      = ${mean:>+13,.0f}")
    print(f"  Median    = ${med:>+13,.0f}")
    print(f"  SD        = ${sd:>+13,.0f}")
    print(f"  Sharpe    = {mean/sd:>+13.4f}")
    print(f"  P>0       = {pos:>13.2f}%")
    print(f"  q5        = ${q5:>+13,.0f}")
    print(f"  CVaR-5%   = ${cvar5:>+13,.0f}")
    print(f"  q2        = ${q2:>+13,.0f}")
    print(f"  CVaR-2%   = ${cvar2:>+13,.0f}")
    print(f"  CVaR-1%   = ${cvar1:>+13,.0f}")

print("\n" + "="*100)
print("PAIRED DIFFERENCE: REFINED_9POS - OPTIMAL_7POS (same paths)")
print("="*100)
print(f"  Mean diff   = ${diff_arr.mean():>+13,.2f}")
print(f"  SD diff     = ${diff_arr.std(ddof=1):>+13,.2f}")
print(f"  SE on diff  = ${diff_arr.std(ddof=1)/np.sqrt(len(diff_arr)):>+13,.2f}  (2M-trial estimate)")
print(f"  P(REFINED beats OPT) = {(diff_arr > 0).mean()*100:.2f}%")
print(f"  Sigma of diff in units of SE: {diff_arr.mean() / (diff_arr.std(ddof=1)/np.sqrt(len(diff_arr))):.2f}")

# CVaR comparison: same percentiles?
opt_cvar5 = results["OPTIMAL_7POS"][results["OPTIMAL_7POS"] <= np.percentile(results["OPTIMAL_7POS"], 5)].mean()
ref_cvar5 = results["REFINED_9POS"][results["REFINED_9POS"] <= np.percentile(results["REFINED_9POS"], 5)].mean()
print(f"\nCVaR-5% comparison (independent percentile per strategy):")
print(f"  OPTIMAL_7POS CVaR-5% = ${opt_cvar5:>+13,.0f}")
print(f"  REFINED_9POS CVaR-5% = ${ref_cvar5:>+13,.0f}")
print(f"  REFINED improvement  = ${ref_cvar5 - opt_cvar5:>+13,.0f}")

print(f"\nDone in {time.time()-t0:.0f}s")
