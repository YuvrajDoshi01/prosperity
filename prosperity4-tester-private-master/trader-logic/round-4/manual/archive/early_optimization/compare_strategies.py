"""Compare manual strategies on per-sim PnL distribution: Mean, SD, CVaR, Sharpe.

Strategies:
  A. Mine (max-size): SELL 50 chooser, BUY 500 KO, SELL 50 BP, BUY 50 P_2, BUY 50 C_2, SELL 50 60C
  B. Theirs (hedged, smaller): SELL 15 chooser, SELL 50 BP, BUY 17 P, BUY 15 P_2, BUY 15 C, BUY 150 AC
  C. Hybrid: theirs + the rejected positions (KO + 60C) at moderate size
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
N_3W = T_3W_DAYS * STEPS_PER_DAY  # 60
N_2W = T_2W_DAYS * STEPS_PER_DAY  # 40
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


# Quotes (bid, ask)
QUOTES = {
    "AC":          (49.975, 50.025),
    "AC_50_P":     (12.00,  12.05),
    "AC_50_C":     (12.00,  12.05),
    "AC_35_P":     (4.33,   4.35),
    "AC_40_P":     (6.50,   6.55),
    "AC_45_P":     (9.05,   9.10),
    "AC_60_C":     (8.80,   8.85),
    "AC_50_P_2":   (9.70,   9.75),
    "AC_50_C_2":   (9.70,   9.75),
    "AC_50_CO":    (22.20,  22.30),
    "AC_40_BP":    (5.00,   5.10),
    "AC_45_KO":    (0.15,   0.175),
}

# Strategies: list of (instrument, side, volume)
STRAT_A_MINE = [
    ("AC_50_CO",  "sell", 50),
    ("AC_45_KO",  "buy",  500),
    ("AC_40_BP",  "sell", 50),
    ("AC_50_P_2", "buy",  50),
    ("AC_50_C_2", "buy",  50),
    ("AC_60_C",   "sell", 50),
]

STRAT_B_THEIRS = [
    ("AC_50_CO",  "sell", 15),
    ("AC_40_BP",  "sell", 50),
    ("AC_50_P",   "buy",  17),
    ("AC_50_P_2", "buy",  15),
    ("AC_50_C",   "buy",  15),
    ("AC",        "buy",  150),
]

STRAT_C_HYBRID = [
    # Theirs (hedged core)
    ("AC_50_CO",  "sell", 30),
    ("AC_40_BP",  "sell", 50),
    ("AC_50_P_2", "buy",  30),
    ("AC_50_C_2", "buy",  30),
    # Add KO at conservative size + 60C
    ("AC_45_KO",  "buy",  300),
    ("AC_60_C",   "sell", 50),
]


def payoff(sym, S_T, S_T_2w, min_S):
    if sym == "AC":         return S_T   # mark-to-end
    if sym == "AC_50_P":    return max(50 - S_T, 0)
    if sym == "AC_50_C":    return max(S_T - 50, 0)
    if sym == "AC_35_P":    return max(35 - S_T, 0)
    if sym == "AC_40_P":    return max(40 - S_T, 0)
    if sym == "AC_45_P":    return max(45 - S_T, 0)
    if sym == "AC_60_C":    return max(S_T - 60, 0)
    if sym == "AC_50_P_2":  return max(50 - S_T_2w, 0) if S_T_2w is not None else 0
    if sym == "AC_50_C_2":  return max(S_T_2w - 50, 0) if S_T_2w is not None else 0
    if sym == "AC_50_CO":
        # auto-convert to ITM side at 2w
        if S_T_2w is None: return 0
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
        S = S0
        min_S = S0
        S_at_2w = None
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
            bid, ask = QUOTES[sym]
            p = payoff(sym, S_T, S_T_2w, min_S)
            if side == "buy":
                pnl += vol * (p - ask)
            else:  # sell
                pnl += vol * (bid - p)
        pnls.append(pnl)
    return pnls


def stats(pnls, name):
    n = len(pnls)
    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    sd = var ** 0.5
    sorted_pnls = sorted(pnls)
    cvar5 = sum(sorted_pnls[:int(n * 0.05)]) / int(n * 0.05) if n >= 20 else min(pnls)
    cvar10 = sum(sorted_pnls[:int(n * 0.10)]) / int(n * 0.10) if n >= 10 else min(pnls)
    cvar25 = sum(sorted_pnls[:int(n * 0.25)]) / int(n * 0.25) if n >= 4 else min(pnls)
    median = sorted_pnls[n // 2]
    pos_pct = sum(1 for p in pnls if p > 0) / n * 100
    sharpe = mean / sd if sd > 0 else 0
    return {
        "name": name, "n": n, "mean": mean, "sd": sd, "min": min(pnls), "max": max(pnls),
        "cvar5": cvar5, "cvar10": cvar10, "cvar25": cvar25, "median": median,
        "pos_pct": pos_pct, "sharpe": sharpe,
    }


def print_stats(s):
    print(f"\n  {s['name']}  (n={s['n']:,})")
    print(f"    Mean      = {s['mean']:+10.2f}")
    print(f"    SD        = {s['sd']:10.2f}")
    print(f"    Sharpe    = {s['sharpe']:10.4f}")
    print(f"    Median    = {s['median']:+10.2f}")
    print(f"    P(>0)     = {s['pos_pct']:9.1f}%")
    print(f"    Min       = {s['min']:+10.2f}")
    print(f"    Max       = {s['max']:+10.2f}")
    print(f"    CVaR  5%  = {s['cvar5']:+10.2f}")
    print(f"    CVaR 10%  = {s['cvar10']:+10.2f}")
    print(f"    CVaR 25%  = {s['cvar25']:+10.2f}")


N_SIMS = 100_000
print(f"Running {N_SIMS:,} simulations per strategy (seed=42)...")
paths = gen_paths(N_SIMS, seed=42)

for strat, name in [
    (STRAT_A_MINE,   "STRAT A — mine (max-size, no hedges)"),
    (STRAT_B_THEIRS, "STRAT B — theirs (hedged, smaller)"),
    (STRAT_C_HYBRID, "STRAT C — hybrid (hedged + KO/60C kept)"),
]:
    pnls = strategy_pnl(strat, paths)
    print_stats(stats(pnls, name))

# Per-position EV decomposition
print("\n\n=== Per-position EV (theoretical, no MC) ===")
# Use closed-form fair values
T_3W = T_3W_DAYS / 252; T_2W = T_2W_DAYS / 252
fv = {
    "AC":         50.0,
    "AC_50_P":    bs_put(S0, 50, T_3W, SIGMA),
    "AC_50_C":    bs_call(S0, 50, T_3W, SIGMA),
    "AC_35_P":    bs_put(S0, 35, T_3W, SIGMA),
    "AC_40_P":    bs_put(S0, 40, T_3W, SIGMA),
    "AC_45_P":    bs_put(S0, 45, T_3W, SIGMA),
    "AC_60_C":    bs_call(S0, 60, T_3W, SIGMA),
    "AC_50_P_2":  bs_put(S0, 50, T_2W, SIGMA),
    "AC_50_C_2": bs_call(S0, 50, T_2W, SIGMA),
    "AC_50_CO":   bs_call(S0, 50, T_3W, SIGMA) + bs_put(S0, 50, T_2W, SIGMA),  # chooser
    "AC_40_BP":   10.0 * (1 - ND.cdf((math.log(S0/40) - 0.5*SIGMA**2*T_3W)/(SIGMA*math.sqrt(T_3W)))),
    # AC_45_KO: use MC value (computed elsewhere as 0.207)
    "AC_45_KO":   0.207,
}
for sym, fv_val in fv.items():
    bid, ask = QUOTES[sym]
    print(f"  {sym:12s} fair={fv_val:8.4f}  bid={bid:7.3f}  ask={ask:7.3f}  "
          f"BUY edge={fv_val-ask:+.4f}  SELL edge={bid-fv_val:+.4f}")

print("\n\n=== Per-strategy theoretical EV (sum of per-position EV) ===")
for strat, name in [
    (STRAT_A_MINE, "A — mine"),
    (STRAT_B_THEIRS, "B — theirs"),
    (STRAT_C_HYBRID, "C — hybrid"),
]:
    total = 0.0
    breakdown = []
    for sym, side, vol in strat:
        bid, ask = QUOTES[sym]
        if side == "buy":
            edge = fv[sym] - ask
        else:
            edge = bid - fv[sym]
        ev = vol * edge
        total += ev
        breakdown.append((sym, side, vol, edge, ev))
    print(f"\n  {name}:")
    for sym, side, vol, edge, ev in breakdown:
        print(f"    {side.upper():4s} {vol:4d} {sym:12s} edge={edge:+.4f}  EV={ev:+8.3f}")
    print(f"    -> TOTAL EV = {total:+.3f}")
