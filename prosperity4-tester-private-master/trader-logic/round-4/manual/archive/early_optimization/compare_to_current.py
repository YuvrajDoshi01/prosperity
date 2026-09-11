"""Compare USER's current UI orders vs the empirical-optimal strategy."""
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

# User's CURRENT entry in IMC UI
USER_CURRENT = [
    ("AC",        "sell", 200),  # 200 short AETHER
    ("AC_50_P",   "buy",  17),
    ("AC_50_C",   "buy",  15),
    ("AC_35_P",   "sell", 10),
    ("AC_50_P_2", "buy",  40),
    ("AC_50_C_2", "buy",  10),
    ("AC_50_CO",  "sell", 20),
    ("AC_40_BP",  "sell", 50),
    ("AC_45_KO",  "buy",  240),
]

# Empirical Pareto-optimal
OPTIMAL = [
    ("AC_50_CO",  "sell", 50),
    ("AC_45_KO",  "buy",  500),
    ("AC_40_BP",  "sell", 50),
    ("AC_50_P_2", "buy",  50),
    ("AC_50_C_2", "buy",  50),
    ("AC_50_P",   "buy",  50),
    ("AC_50_C",   "buy",  25),
]

# Pure max-EV (DROP_60C)
MAX_EV = [
    ("AC_50_CO",  "sell", 50),
    ("AC_45_KO",  "buy",  500),
    ("AC_40_BP",  "sell", 50),
    ("AC_50_P_2", "buy",  50),
    ("AC_50_C_2", "buy",  50),
]


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


def gen_paths(n_paths, rng):
    drift = -0.5 * SIGMA * SIGMA * DT
    vol = SIGMA * np.sqrt(DT)
    S = np.full(n_paths, S0, dtype=np.float64)
    min_S = S.copy()
    S_2w = None
    for k in range(N_3W):
        z = rng.standard_normal(n_paths)
        S = S * np.exp(drift + vol * z)
        np.minimum(min_S, S, out=min_S)
        if k+1 == N_2W:
            S_2w = S.copy()
    return S, S_2w, min_S


# Generate 50M paths in chunks
TOTAL = 50_000_000
CHUNK = 2_000_000
N_CHUNKS = TOTAL // CHUNK

trial_scores = {"USER_CURRENT": [], "OPTIMAL": [], "MAX_EV": []}
strategies = {"USER_CURRENT": USER_CURRENT, "OPTIMAL": OPTIMAL, "MAX_EV": MAX_EV}

rng = np.random.default_rng(seed=42)
t0 = time.time()
for ci in range(N_CHUNKS):
    S_T, S_2w, min_S = gen_paths(CHUNK, rng)
    payoffs = per_path_payoffs(S_T, S_2w, min_S)
    for name, strat in strategies.items():
        pnl = strat_pnl(strat, payoffs)
        # Group into trials of 100
        trial_chunk = pnl.reshape(CHUNK//100, 100).mean(axis=1) * CONTRACT_MULTIPLIER
        trial_scores[name].append(trial_chunk)
    if (ci+1) % 5 == 0:
        print(f"  chunk {ci+1}/{N_CHUNKS} ({time.time()-t0:.0f}s)")

# Concatenate
for name in trial_scores:
    trial_scores[name] = np.concatenate(trial_scores[name])

# Stats
print(f"\n{'='*120}")
print(f"COMPARISON: User's Current UI vs Empirical Optimal vs Max-EV (50M paths, 500K trials)")
print(f"{'='*120}")
print(f"{'Strategy':<20} {'Mean':>13} {'Median':>13} {'SD':>13} {'P>0':>6} {'q5':>13} {'CVaR5':>13} {'q2':>13} {'CVaR2':>13}")
for name in ["USER_CURRENT", "OPTIMAL", "MAX_EV"]:
    s = trial_scores[name]
    mean = s.mean(); sd = s.std(ddof=1); med = np.median(s); pos = (s>0).mean()*100
    q5 = np.percentile(s, 5); cvar5 = s[s <= q5].mean()
    q2 = np.percentile(s, 2); cvar2 = s[s <= q2].mean()
    print(f"{name:<20} ${mean:>+12,.0f} ${med:>+12,.0f} ${sd:>12,.0f} {pos:>5.1f}% ${q5:>+12,.0f} ${cvar5:>+12,.0f} ${q2:>+12,.0f} ${cvar2:>+12,.0f}")

# Per-position breakdown
print(f"\n{'='*120}")
print(f"PER-POSITION EV BREAKDOWN")
print(f"{'='*120}")

FV = {
    "AC": 50.0, "AC_50_P": 12.027, "AC_50_C": 12.027, "AC_35_P": 4.336,
    "AC_40_P": 6.510, "AC_45_P": 9.089, "AC_60_C": 8.792,
    "AC_50_P_2": 9.871, "AC_50_C_2": 9.871, "AC_50_CO": 21.898,
    "AC_40_BP": 4.768, "AC_45_KO": 0.207,
}

for label, strat in [("USER_CURRENT", USER_CURRENT), ("OPTIMAL", OPTIMAL)]:
    print(f"\n{label}:")
    total = 0.0
    for sym, side, vol in strat:
        bid, ask, _ = QUOTES[sym]
        if side == "buy":
            edge = FV[sym] - ask
        else:
            edge = bid - FV[sym]
        ev = vol * edge
        total += ev
        print(f"  {side.upper():4s} {vol:>4d}  {sym:<12s} edge={edge:+.4f}/unit  EV={ev:+8.3f} (x3000 = ${ev*3000:>+10,.0f})")
    print(f"  {'-'*60}")
    print(f"  TOTAL:                                 EV={total:+8.3f} (x3000 = ${total*3000:>+10,.0f})")

# Paired comparison: how often does optimal beat user's current?
print(f"\n{'='*120}")
print(f"PAIRED COMPARISON (same 50M paths)")
print(f"{'='*120}")
diff = trial_scores["OPTIMAL"] - trial_scores["USER_CURRENT"]
print(f"  Difference (OPTIMAL - USER_CURRENT): mean={diff.mean():+,.0f}, SD={diff.std(ddof=1):,.0f}")
print(f"  P(OPTIMAL beats USER_CURRENT) = {(diff > 0).mean()*100:.1f}%")
print(f"  P(OPTIMAL > USER_CURRENT by $50k+) = {(diff > 50_000).mean()*100:.1f}%")
print(f"  P(USER_CURRENT > OPTIMAL by $50k+) = {(diff < -50_000).mean()*100:.1f}%")

print(f"\nDone in {time.time()-t0:.0f}s")
