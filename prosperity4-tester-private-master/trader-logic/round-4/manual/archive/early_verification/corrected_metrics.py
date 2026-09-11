"""Correctly distinguish PER-PATH tail risk from PER-TRIAL (trial-mean) tail risk.

Per the user's review:
- Per-trial (mean of 100 sims) CVaR = "confidence bound on E[score]" — relevant for IMC scoring
- Per-path PnL CVaR = "actuarial single-realization tail" — the traditional risk measure

We report BOTH for the candidate strategies. Also fixes:
- KO barrier inequality (>= instead of >)
- Position limit validation
- Honest naming
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
LIMITS = {k: v[2] for k, v in QUOTES.items()}


def validate(name, strat):
    """User's bug-fix: enforce position limits."""
    for sym, side, vol in strat:
        cap = LIMITS[sym]
        assert vol <= cap, f"{name}: |{sym}|={vol} > cap {cap}"


STRATEGIES = {
    "DROP_60C": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
    ],
    "OPTIMAL_7POS": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
        ("AC_50_P",   "buy",  50),
        ("AC_50_C",   "buy",  25),
    ],
    "USER_SAFE": [
        ("AC_50_CO", "sell", 15),
        ("AC_40_BP", "sell", 50),
        ("AC_45_KO", "buy",  60),
        ("AC_50_P",  "buy",  17),
        ("AC_50_P_2","buy",  15),
        ("AC_50_C",  "buy",  15),
    ],
    "GLOBAL_MAX": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
        ("AC_60_C",   "sell", 50),
    ],
}

for name, strat in STRATEGIES.items():
    validate(name, strat)
print("All strategies validated against position limits.")


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
        # FIXED: brief says "falls BELOW 35" => strict < => survival = min_S >= 35 (NOT > 35)
        "AC_45_KO":   np.where(min_S >= 35, np.maximum(45 - S_T, 0.0), 0.0),
    }


def strat_pnl_per_path(strat, payoffs):
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


def percentile_stats(arr, name, label):
    """Compute mean, SD, percentiles for an array."""
    mean = float(arr.mean())
    sd = float(arr.std(ddof=1))
    median = float(np.median(arr))
    pct_pos = float((arr > 0).mean() * 100)
    quantiles = {p: float(np.percentile(arr, p)) for p in [0.1, 1, 2, 5, 10, 25, 50, 75, 90, 95, 99, 99.9]}
    cvar = {}
    for p in [1, 2, 5, 10, 25]:
        thresh = quantiles[p]
        cvar[p] = float(arr[arr <= thresh].mean())
    return {
        "label": label, "mean": mean, "sd": sd, "median": median,
        "pct_pos": pct_pos, "quantiles": quantiles, "cvar": cvar,
    }


# Generate 100M paths in chunks of 5M
TOTAL = 100_000_000
CHUNK = 5_000_000
N_CHUNKS = TOTAL // CHUNK

# Two collections: per-path PnL × 3000 (raw single-sim PnL), and trial means × 3000
per_path_results = {name: [] for name in STRATEGIES}
trial_results = {name: [] for name in STRATEGIES}

rng = np.random.default_rng(seed=42)
t0 = time.time()
for ci in range(N_CHUNKS):
    S_T, S_2w, min_S = gen_paths(CHUNK, rng)
    payoffs = per_path_payoffs(S_T, S_2w, min_S)
    for name, strat in STRATEGIES.items():
        pnl = strat_pnl_per_path(strat, payoffs)
        # Per-path PnL (single-sim level), scaled by 3000
        per_path_results[name].append(pnl * CONTRACT_MULTIPLIER)
        # Per-trial mean (100-sim average), scaled by 3000
        trial = pnl.reshape(CHUNK//100, 100).mean(axis=1) * CONTRACT_MULTIPLIER
        trial_results[name].append(trial)
    if (ci+1) % 5 == 0:
        print(f"  chunk {ci+1}/{N_CHUNKS} ({time.time()-t0:.0f}s)")

# Concatenate
for name in STRATEGIES:
    per_path_results[name] = np.concatenate(per_path_results[name])
    trial_results[name] = np.concatenate(trial_results[name])

print(f"\nDone generating in {time.time()-t0:.0f}s")
print(f"Per-path arrays: {TOTAL:,} entries each")
print(f"Per-trial arrays: {TOTAL//100:,} entries each (1M trials × 100 paths)")

# Compute and report stats for both perspectives
print("\n" + "="*120)
print("BOTH PERSPECTIVES SIDE-BY-SIDE")
print("All values in XIRECs (×3000 multiplier applied)")
print("="*120)

for name in STRATEGIES:
    per_path_st = percentile_stats(per_path_results[name], name, "PER-PATH (single-sim PnL)")
    trial_st = percentile_stats(trial_results[name], name, "PER-TRIAL (mean of 100 sims = IMC score)")

    print(f"\n{'-'*120}")
    print(f"  STRATEGY: {name}")
    print(f"{'-'*120}")

    print(f"  {'METRIC':<25} {'PER-PATH (1 GBM realization)':>40} {'PER-TRIAL (100-path mean = IMC score)':>45}")
    print(f"  {'-'*25} {'-'*40} {'-'*45}")
    print(f"  {'Mean':<25} {'$' + format(int(per_path_st['mean']), '+,'):>40} {'$' + format(int(trial_st['mean']), '+,'):>45}")
    print(f"  {'Median':<25} {'$' + format(int(per_path_st['median']), '+,'):>40} {'$' + format(int(trial_st['median']), '+,'):>45}")
    print(f"  {'SD':<25} {'$' + format(int(per_path_st['sd']), '+,'):>40} {'$' + format(int(trial_st['sd']), '+,'):>45}")
    print(f"  {'Sharpe':<25} {per_path_st['mean']/per_path_st['sd']:>40.4f} {trial_st['mean']/trial_st['sd']:>45.4f}")
    print(f"  {'P(>0)':<25} {per_path_st['pct_pos']:>39.2f}% {trial_st['pct_pos']:>44.2f}%")
    print(f"  {'q5 (5th percentile)':<25} {'$' + format(int(per_path_st['quantiles'][5]), '+,'):>40} {'$' + format(int(trial_st['quantiles'][5]), '+,'):>45}")
    print(f"  {'q2 (2nd percentile)':<25} {'$' + format(int(per_path_st['quantiles'][2]), '+,'):>40} {'$' + format(int(trial_st['quantiles'][2]), '+,'):>45}")
    print(f"  {'q1 (1st percentile)':<25} {'$' + format(int(per_path_st['quantiles'][1]), '+,'):>40} {'$' + format(int(trial_st['quantiles'][1]), '+,'):>45}")
    print(f"  {'q0.1 (one-in-1000)':<25} {'$' + format(int(per_path_st['quantiles'][0.1]), '+,'):>40} {'$' + format(int(trial_st['quantiles'][0.1]), '+,'):>45}")
    print(f"  {'CVaR-5%':<25} {'$' + format(int(per_path_st['cvar'][5]), '+,'):>40} {'$' + format(int(trial_st['cvar'][5]), '+,'):>45}")
    print(f"  {'CVaR-1%':<25} {'$' + format(int(per_path_st['cvar'][1]), '+,'):>40} {'$' + format(int(trial_st['cvar'][1]), '+,'):>45}")

print("\n" + "="*120)
print("INTERPRETATION GUIDE")
print("="*120)
print("""
PER-PATH = if IMC scoring used a SINGLE GBM realization (which it does NOT),
           or if you exposed yourself to one path's outcome.
           The TRADITIONAL CVaR / actuarial tail-risk measure.

PER-TRIAL = mean of 100 paths = WHAT IMC ACTUALLY REPORTS AS YOUR SCORE.
            CVaR here = "in the worst 5% of possible IMC scoring runs (varying random seed),
            what score do you get?"
            This is the realistic worst-case for your final leaderboard score.

For the TRIAL-MEAN distribution (which is what IMC reports), SD = per_path_SD / sqrt(100) = per_path_SD / 10.
So tail-risk on the actual reported score is 10x tighter than per-path CVaR suggests.
""")
