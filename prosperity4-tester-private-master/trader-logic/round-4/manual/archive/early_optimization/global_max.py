"""GLOBAL MAXIMUM search under IMC's E[score] = mean of 100 sims objective.

KEY MATHEMATICAL FACT:
  Per-unit EV is LINEAR in position quantity. So for any instrument:
    EV(q) = q * edge_per_unit
  This is maximized at the BOUNDARY: q = +cap (if buy edge positive) or -cap (if sell edge positive).
  No interior optimum exists.

Hence the global mean-EV optimum is the union of all positive-edge positions at max cap.

This script:
1. Enumerates all 12 instruments and computes both buy-edge and sell-edge per unit
2. Picks the positive-edge side for each (or zero if both negative)
3. Sums total EV
4. Verifies with 1M-path MC that this is indeed the maximum
5. Sweeps a few "shrink" alternatives to confirm no superlinear effects
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

CONTRACT_MULTIPLIER = 3000  # confirmed from team chat

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


T_3W = T_3W_DAYS / TRADING_DAYS_YEAR
T_2W = T_2W_DAYS / TRADING_DAYS_YEAR

# Compute fair values rigorously (BS for vanilla; closed-form for chooser/binary; MC for KO)
print("=" * 100)
print("STEP 1: Fair value computation")
print("=" * 100)

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
            if k+1 == N_2W: S_at_2w = S
        paths.append((S, min_S, S_at_2w))
    return paths

# Compute KO fair via 1M-path MC
print("Generating 1M paths for KO put fair value verification...")
paths_ko = gen_paths(1_000_000, seed=12345)
ko_payoffs = [max(45 - S_T, 0.0) if min_S > 35 else 0.0 for S_T, min_S, _ in paths_ko]
ko_fair = sum(ko_payoffs) / len(ko_payoffs)
ko_se = (sum((p - ko_fair)**2 for p in ko_payoffs) / (len(ko_payoffs)-1))**0.5 / (len(ko_payoffs)**0.5)
print(f"KO put fair (1M MC, 4 obs/day): {ko_fair:.4f} ± {ko_se:.4f}")

# Binary put fair
bp_d2 = (math.log(S0/40) - 0.5*SIGMA**2*T_3W)/(SIGMA*math.sqrt(T_3W))
bp_fair = 10.0 * (1 - ND.cdf(bp_d2))

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
    "AC_40_BP":   bp_fair,
    "AC_45_KO":   ko_fair,
}

print(f"\n{'Instrument':<14} {'Fair':>9} {'Bid':>8} {'Ask':>8} {'Cap':>5} {'BuyEdge':>8} {'SellEdge':>9} {'Optimal':<14}")
print("-" * 100)
total_ev = 0.0
optimal_positions = []
for sym, (bid, ask, cap) in QUOTES.items():
    fair = FV[sym]
    buy_edge = fair - ask
    sell_edge = bid - fair
    if buy_edge > 0 and buy_edge > sell_edge:
        action, vol = "BUY", cap
        ev = buy_edge * vol
    elif sell_edge > 0:
        action, vol = "SELL", cap
        ev = sell_edge * vol
    else:
        action, vol = "SKIP", 0
        ev = 0.0
    total_ev += ev
    optimal_positions.append((sym, action, vol, ev))
    flag = " ***" if ev > 5 else ("  +" if ev > 0 else "")
    print(f"{sym:<14} {fair:>9.4f} {bid:>8.3f} {ask:>8.3f} {cap:>5} {buy_edge:>+8.4f} {sell_edge:>+9.4f} {action} {vol:<3} EV={ev:+7.3f}{flag}")

print()
print(f"GLOBAL MAXIMUM E[score] (per unit): {total_ev:+.3f}")
print(f"With x{CONTRACT_MULTIPLIER} multiplier: ${total_ev * CONTRACT_MULTIPLIER:+,.0f}")

# Verify with MC
print()
print("=" * 100)
print("STEP 2: Verify global max via 1M-path MC (same paths as KO above)")
print("=" * 100)

def payoff(sym, S_T, S_T_2w, min_S):
    if sym == "AC":         return S_T
    if sym == "AC_50_P":    return max(50 - S_T, 0)
    if sym == "AC_50_C":    return max(S_T - 50, 0)
    if sym == "AC_35_P":    return max(35 - S_T, 0)
    if sym == "AC_40_P":    return max(40 - S_T, 0)
    if sym == "AC_45_P":    return max(45 - S_T, 0)
    if sym == "AC_60_C":    return max(S_T - 60, 0)
    if sym == "AC_50_P_2":  return max(50 - S_T_2w, 0) if S_T_2w is not None else 0
    if sym == "AC_50_C_2":  return max(S_T_2w - 50, 0) if S_T_2w is not None else 0
    if sym == "AC_50_CO":
        if S_T_2w >= 50: return max(S_T - 50, 0)
        else:            return max(50 - S_T, 0)
    if sym == "AC_40_BP":   return 10.0 if S_T < 40 else 0.0
    if sym == "AC_45_KO":   return max(45 - S_T, 0) if min_S > 35 else 0.0
    return 0.0

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

active = [(sym, action.lower(), vol) for sym, action, vol, ev in optimal_positions if action != "SKIP"]
print(f"Active positions: {len(active)}")
for sym, side, vol in active:
    print(f"  {side.upper():4s} {vol:>4d}  {sym}")

pnls = strategy_pnl(active, paths_ko)
n = len(pnls)
mc_mean = sum(pnls) / n
mc_sd = (sum((p - mc_mean)**2 for p in pnls) / (n-1))**0.5
print(f"\nMC (1M paths) per-unit: Mean = {mc_mean:+.3f} (theoretical {total_ev:+.3f}, diff {mc_mean-total_ev:+.3f})")
print(f"                          SD = {mc_sd:.1f}")
print(f"With x{CONTRACT_MULTIPLIER}: Expected score = ${mc_mean*CONTRACT_MULTIPLIER:+,.0f}, per-trial SE = ±${mc_sd/10*CONTRACT_MULTIPLIER:,.0f}")

# Also test: removing 60C (low-edge) — what's the EV cost?
print()
print("=" * 100)
print("STEP 3: Sensitivity — does removing the lowest-edge position help?")
print("=" * 100)

for drop_sym in ["AC_60_C", "AC_45_KO"]:
    test = [(s, side, v) for s, side, v in active if s != drop_sym]
    pnls = strategy_pnl(test, paths_ko)
    test_mean = sum(pnls) / len(pnls)
    test_sd = (sum((p - test_mean)**2 for p in pnls) / (len(pnls)-1))**0.5
    print(f"  Drop {drop_sym}: per-unit Mean = {test_mean:+.3f} (delta {test_mean-mc_mean:+.3f}), "
          f"SD = {test_sd:.1f} (delta {test_sd-mc_sd:+.1f})")

# Test: shrinking each position by 50% — confirms LINEAR scaling
print()
print("=" * 100)
print("STEP 4: Confirm linearity by halving each position")
print("=" * 100)

half = [(s, side, v//2) for s, side, v in active]
pnls = strategy_pnl(half, paths_ko)
half_mean = sum(pnls) / len(pnls)
half_sd = (sum((p - half_mean)**2 for p in pnls) / (len(pnls)-1))**0.5
print(f"  HALF size:   per-unit Mean = {half_mean:+.3f} (theoretical {total_ev/2:+.3f})")
print(f"               per-unit SD = {half_sd:.1f} (theoretical ~{mc_sd/2:.1f})")
print(f"  Confirms: EV scales linearly with position size; SD also scales linearly.")
print(f"  → For pure E[score], FULL SIZE on every positive-edge position is optimal.")

print()
print("=" * 100)
print("FINAL: GLOBAL MAXIMUM under IMC E[score] = mean(100 sims) objective")
print("=" * 100)
print(f"\n  E[score] = ${mc_mean * CONTRACT_MULTIPLIER:+,.0f} (per-trial SE = ±${mc_sd/10 * CONTRACT_MULTIPLIER:,.0f})")
print(f"  P(score > 0) = {ND.cdf(mc_mean / (mc_sd/10))*100:.1f}%")
print(f"  95% CI on actual score: [${(mc_mean - 1.96*mc_sd/10)*CONTRACT_MULTIPLIER:+,.0f}, ${(mc_mean + 1.96*mc_sd/10)*CONTRACT_MULTIPLIER:+,.0f}]")
print()
print("FINAL ORDERS TO ENTER:")
for sym, side, vol in active:
    bid, ask, _ = QUOTES[sym]
    price = ask if side == "buy" else bid
    print(f"  {side.upper():4s} {vol:>4d}  {sym:<14} @ {price:.3f}")
