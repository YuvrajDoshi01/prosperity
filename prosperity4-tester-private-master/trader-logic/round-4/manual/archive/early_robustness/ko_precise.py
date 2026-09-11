"""High-precision KO put fair value (multiple seeds, 2M paths each)."""
import math
import random
from statistics import NormalDist

S0 = 50.0
SIGMA = 2.51
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_3W = T_3W_DAYS / TRADING_DAYS_YEAR
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_STEPS = T_3W_DAYS * STEPS_PER_DAY  # 60

K = 45
B = 35

def ko_mc(n_paths, seed):
    rng = random.Random(seed)
    drift_step = -0.5 * SIGMA * SIGMA * DT
    vol_step = SIGMA * math.sqrt(DT)
    payoffs = []
    for _ in range(n_paths):
        S = S0
        breached = False
        for k in range(N_STEPS):
            z = rng.gauss(0.0, 1.0)
            S = S * math.exp(drift_step + vol_step * z)
            if S <= B:
                breached = True
        if not breached:
            payoffs.append(max(K - S, 0.0))
        else:
            payoffs.append(0.0)
    mean = sum(payoffs) / n_paths
    var = sum((p - mean) ** 2 for p in payoffs) / (n_paths - 1)
    return mean, var ** 0.5

print(f"KO put fair value (K={K}, B={B}, T={T_3W_DAYS}td, sigma={SIGMA}):")
print(f"Steps per simulation: {N_STEPS} (4/day x {T_3W_DAYS}d)")
print()

n_paths = 1_000_000
seeds = [1, 2, 3, 4, 5]
estimates = []
for seed in seeds:
    mean, sd = ko_mc(n_paths, seed)
    se = sd / (n_paths ** 0.5)
    estimates.append(mean)
    print(f"  Seed {seed}: fair = {mean:.4f} (SE = {se:.4f})")

avg = sum(estimates) / len(estimates)
spread = max(estimates) - min(estimates)
print(f"\n  Avg over {len(seeds)} seeds: {avg:.4f}")
print(f"  Spread: {spread:.4f}")
print(f"\n  Market: bid 0.150 / ask 0.175")
print(f"  BUY at 0.175 -> edge per unit = {avg - 0.175:+.4f}")
print(f"  SELL at 0.150 -> edge per unit = {0.150 - avg:+.4f}")
print(f"  At max vol 500: BUY EV = {500 * (avg - 0.175):+.2f}, SELL EV = {500 * (0.150 - avg):+.2f}")

# Distribution analysis: P(survive) and conditional payoff
print(f"\n--- Distribution (seed 7, 500k paths) ---")
rng = random.Random(7)
drift_step = -0.5 * SIGMA * SIGMA * DT
vol_step = SIGMA * math.sqrt(DT)
N_PATHS_DIST = 500_000
n_breach = 0
n_survive = 0
n_survive_itm = 0
itm_payoffs = []
for _ in range(N_PATHS_DIST):
    S = S0
    breached = False
    for k in range(N_STEPS):
        z = rng.gauss(0.0, 1.0)
        S = S * math.exp(drift_step + vol_step * z)
        if S <= B:
            breached = True
    if breached:
        n_breach += 1
    else:
        n_survive += 1
        if S < K:
            n_survive_itm += 1
            itm_payoffs.append(K - S)

print(f"  P(barrier breach) = {n_breach/N_PATHS_DIST:.3f}")
print(f"  P(barrier survives) = {n_survive/N_PATHS_DIST:.3f}")
print(f"  P(survive AND S_T < K=45) = {n_survive_itm/N_PATHS_DIST:.3f}")
if itm_payoffs:
    print(f"  E[payoff | survive AND ITM] = {sum(itm_payoffs)/len(itm_payoffs):.3f}")
    print(f"  E[payoff overall] = {sum(itm_payoffs)/N_PATHS_DIST:.4f}")
