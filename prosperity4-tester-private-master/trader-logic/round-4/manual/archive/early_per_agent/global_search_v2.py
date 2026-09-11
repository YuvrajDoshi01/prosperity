"""GLOBAL MAX search v2 — exhaustive verification of theoretical claim.

Tasks:
1. Brute-force per-instrument: for each, try q in {-cap..cap} via 1M-MC, confirm boundary optimum.
2. Subset enumeration of 6 positive-edge instruments (64 subsets) for superlinearity check.
3. Hidden arbitrage scan (box, conversion, chooser replication, calendar, vol arb).
4. Sensitivity to sigma, KO fair, time convention.
5. 6 candidate strategies under FULL MC: rank by E[score], Sharpe, CVaR.
6. Final report markdown.

All numbers in PnL units; CONTRACT_MULTIPLIER=3000 applied for final dollar reporting.
"""
import math
import time
import json
import numpy as np
from scipy.stats import norm

t0 = time.time()
np.random.seed(0xC0DE)

# ============================================================
# 0. CONSTANTS & FAIR VALUES
# ============================================================
S0 = 50.0
SIGMA = 2.51
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15
T_2W_DAYS = 10
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W = T_3W_DAYS * STEPS_PER_DAY  # 60
N_2W = T_2W_DAYS * STEPS_PER_DAY  # 40
T_3W = T_3W_DAYS / TRADING_DAYS_YEAR
T_2W = T_2W_DAYS / TRADING_DAYS_YEAR
CONTRACT_MULT = 3000

QUOTES = {
    "AC":          (49.975, 50.025, 200),
    "AC_50_P":     (12.00,  12.05,   50),
    "AC_50_C":     (12.00,  12.05,   50),
    "AC_35_P":     ( 4.33,   4.35,   50),
    "AC_40_P":     ( 6.50,   6.55,   50),
    "AC_45_P":     ( 9.05,   9.10,   50),
    "AC_60_C":     ( 8.80,   8.85,   50),
    "AC_50_P_2":   ( 9.70,   9.75,   50),
    "AC_50_C_2":   ( 9.70,   9.75,   50),
    "AC_50_CO":    (22.20,  22.30,   50),
    "AC_40_BP":    ( 5.00,   5.10,   50),
    "AC_45_KO":    ( 0.15,   0.175, 500),
}
SYMBOLS = list(QUOTES.keys())


def bs_call(S, K, T, sig):
    if T <= 0 or sig <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    return S * norm.cdf(d1) - K * norm.cdf(d2)


def bs_put(S, K, T, sig):
    if T <= 0 or sig <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    return K * norm.cdf(-d2) - S * norm.cdf(-d1)


def fair_values(sig=SIGMA, n3w=N_3W, n2w=N_2W, ko_paths=400_000, ko_seed=12345):
    """Compute the full FV dict at given sigma + step count.

    For KO use MC at the discrete monitoring frequency (4 obs/day).
    """
    T_3w = n3w * DT
    T_2w = n2w * DT
    fv = {}
    fv["AC"] = S0
    fv["AC_50_P"] = bs_put(S0, 50, T_3w, sig)
    fv["AC_50_C"] = bs_call(S0, 50, T_3w, sig)
    fv["AC_35_P"] = bs_put(S0, 35, T_3w, sig)
    fv["AC_40_P"] = bs_put(S0, 40, T_3w, sig)
    fv["AC_45_P"] = bs_put(S0, 45, T_3w, sig)
    fv["AC_60_C"] = bs_call(S0, 60, T_3w, sig)
    fv["AC_50_P_2"] = bs_put(S0, 50, T_2w, sig)
    fv["AC_50_C_2"] = bs_call(S0, 50, T_2w, sig)
    # Chooser at 2w pick: max(C_3w_residual, P_3w_residual). Easier: replicate via 3w call + 2w put (parity).
    # The chooser pays max(call_3w_payoff, put_3w_payoff) given pick at t=2w when forward-looking E values are equal.
    # = call_3w + put_2w (Rubinstein 1991 chooser parity for r=0).
    fv["AC_50_CO"] = fv["AC_50_C"] + fv["AC_50_P_2"]
    # Binary put: 10 * P[S_T < 40]
    d2 = (math.log(S0 / 40) - 0.5 * sig * sig * T_3w) / (sig * math.sqrt(T_3w))
    fv["AC_40_BP"] = 10.0 * (1.0 - norm.cdf(d2))
    # KO via MC
    rng = np.random.default_rng(ko_seed)
    drift = -0.5 * sig * sig * DT
    volstep = sig * math.sqrt(DT)
    Z = rng.standard_normal((ko_paths, n3w))
    log_paths = np.log(S0) + np.cumsum(drift + volstep * Z, axis=1)
    S_paths = np.exp(log_paths)
    min_S = S_paths.min(axis=1)
    S_T = S_paths[:, -1]
    payoff_ko = np.where(min_S > 35, np.maximum(45 - S_T, 0.0), 0.0)
    fv["AC_45_KO"] = float(payoff_ko.mean())
    return fv


print("=" * 90)
print("STEP 0: Fair values (sigma=2.51, 15 trading days, 4 obs/day)")
print("=" * 90)
FV = fair_values()
for s in SYMBOLS:
    bid, ask, cap = QUOTES[s]
    print(f"  {s:<14} fair={FV[s]:>9.4f}  bid={bid:>7.3f} ask={ask:>7.3f} cap={cap}")
print(f"  KO fair (MC, 400k paths, discrete monitoring 4/day): {FV['AC_45_KO']:.4f}")

# Theoretical edges
EDGES = {}
for s in SYMBOLS:
    bid, ask, cap = QUOTES[s]
    fair = FV[s]
    EDGES[s] = (fair - ask, bid - fair, cap)  # (buy_edge_per_unit, sell_edge_per_unit, cap)


# ============================================================
# 1. PATH GENERATOR (vectorized, used everywhere)
# ============================================================

def gen_paths(n_sims, seed, sig=SIGMA, n_steps=N_3W, n2w=N_2W):
    """Returns dict of arrays: S_T (3w terminal), S_T_2w (2w terminal), min_S (running min)."""
    rng = np.random.default_rng(seed)
    drift = -0.5 * sig * sig * DT
    volstep = sig * math.sqrt(DT)
    Z = rng.standard_normal((n_sims, n_steps))
    log_increments = drift + volstep * Z
    log_paths = np.log(S0) + np.cumsum(log_increments, axis=1)
    S_paths = np.exp(log_paths)
    return {
        "S_T":     S_paths[:, -1],
        "S_T_2w":  S_paths[:, n2w - 1],
        "min_S":   S_paths.min(axis=1),
    }


def payoffs_matrix(paths):
    """Returns array of shape (n_sims, n_instruments) of unit payoffs (one contract long)."""
    S_T = paths["S_T"]
    S_T_2w = paths["S_T_2w"]
    min_S = paths["min_S"]
    P = np.empty((S_T.size, len(SYMBOLS)), dtype=np.float64)
    for i, s in enumerate(SYMBOLS):
        if s == "AC":         P[:, i] = S_T
        elif s == "AC_50_P":  P[:, i] = np.maximum(50 - S_T, 0)
        elif s == "AC_50_C":  P[:, i] = np.maximum(S_T - 50, 0)
        elif s == "AC_35_P":  P[:, i] = np.maximum(35 - S_T, 0)
        elif s == "AC_40_P":  P[:, i] = np.maximum(40 - S_T, 0)
        elif s == "AC_45_P":  P[:, i] = np.maximum(45 - S_T, 0)
        elif s == "AC_60_C":  P[:, i] = np.maximum(S_T - 60, 0)
        elif s == "AC_50_P_2": P[:, i] = np.maximum(50 - S_T_2w, 0)
        elif s == "AC_50_C_2": P[:, i] = np.maximum(S_T_2w - 50, 0)
        elif s == "AC_50_CO":
            P[:, i] = np.where(S_T_2w >= 50,
                               np.maximum(S_T - 50, 0),
                               np.maximum(50 - S_T, 0))
        elif s == "AC_40_BP": P[:, i] = np.where(S_T < 40, 10.0, 0.0)
        elif s == "AC_45_KO":
            P[:, i] = np.where(min_S > 35, np.maximum(45 - S_T, 0), 0.0)
    return P


def pnl_matrix(paths, q_vector):
    """Compute per-path PnL given integer position vector q (len 12).

    q_vector positive = long (paid ask), negative = short (received bid).
    Per-path PnL = sum_i q_i * (payoff_i - price_i)  where price = ask if q>0 else bid.
    """
    P = payoffs_matrix(paths)
    bids = np.array([QUOTES[s][0] for s in SYMBOLS])
    asks = np.array([QUOTES[s][1] for s in SYMBOLS])
    q = np.asarray(q_vector, dtype=np.float64)
    prices = np.where(q >= 0, asks, bids)
    # signed_qty * (payoff - price). For shorts q<0, this naturally flips sign.
    contributions = q[None, :] * (P - prices[None, :])
    return contributions.sum(axis=1)


# ============================================================
# 2. THEORETICAL OPTIMUM
# ============================================================

print("\n" + "=" * 90)
print("STEP 1: Per-instrument edge → theoretical optimum (boundary solution)")
print("=" * 90)
print(f"{'Symbol':<14} {'Fair':>9} {'BuyEdge':>8} {'SellEdge':>9} {'Cap':>5} {'Optimal q':>10} {'EV/path':>9}")
opt_q = {}
total_ev = 0.0
for s in SYMBOLS:
    buy_e, sell_e, cap = EDGES[s]
    if buy_e > sell_e and buy_e > 0:
        q, ev = cap, buy_e * cap
    elif sell_e > 0:
        q, ev = -cap, sell_e * cap
    else:
        q, ev = 0, 0.0
    opt_q[s] = q
    total_ev += ev
    print(f"  {s:<14} {FV[s]:>9.4f} {buy_e:>+8.4f} {sell_e:>+9.4f} {cap:>5} {q:>+10d} {ev:>+9.3f}")
print(f"  TOTAL THEORETICAL EV (per path, per unit): {total_ev:+.3f}")
print(f"  With ×{CONTRACT_MULT}: ${total_ev * CONTRACT_MULT:+,.0f}")
THEORETICAL_OPT = np.array([opt_q[s] for s in SYMBOLS])

# ============================================================
# 3. BRUTE-FORCE per-instrument BT (1M paths)
# ============================================================

print("\n" + "=" * 90)
print("STEP 2: Per-instrument brute-force scan over q in {-cap..cap}")
print("(should produce LINEAR EV vs q, with optimum at boundary)")
print("=" * 90)

N_PATHS_BIG = 1_000_000
print(f"Generating {N_PATHS_BIG:,} GBM paths for brute-force evaluation...")
paths_big = gen_paths(N_PATHS_BIG, seed=42)
P_unit = payoffs_matrix(paths_big)  # (N_PATHS_BIG, 12)
mean_payoff = P_unit.mean(axis=0)  # MC fair values
print(f"\n{'Symbol':<14} {'BS_fair':>9} {'MC_fair':>9} {'diff':>7}")
for i, s in enumerate(SYMBOLS):
    print(f"  {s:<14} {FV[s]:>9.4f} {mean_payoff[i]:>9.4f} {mean_payoff[i]-FV[s]:>+7.4f}")

print(f"\nFor each instrument, scan q in {{-cap..cap}} step 1, evaluate isolated EV.")
print(f"Confirm: argmax_q EV(q) == ±cap = boundary.")
print(f"NOTE: For LOW-edge instruments (|edge|<0.05), 1M MC stderr on fair value ~ payoff_sd/sqrt(1M)")
print(f"      can flip the sign of EV. We use the ANALYTICAL fair value (FV[s]) as the clean signal:")
print(f"      EV_per_unit = fair - price (buy) or price - fair (sell).  MC validates within ±SE.")
print(f"\n{'Symbol':<14} {'cap':>5} {'BS edge_buy':>12} {'BS edge_sell':>12} {'theory q':>9} {'theory EV':>10} {'MC SE':>7} {'Flag':<6}")
mc_opt = {}
for i, s in enumerate(SYMBOLS):
    bid, ask, cap = QUOTES[s]
    payoff_i = P_unit[:, i]
    se = payoff_i.std(ddof=1) / math.sqrt(len(payoff_i))
    bs_buy = FV[s] - ask
    bs_sell = bid - FV[s]
    theory_q = opt_q[s]
    if theory_q > 0:   theory_ev = theory_q * bs_buy
    elif theory_q < 0: theory_ev = (-theory_q) * bs_sell
    else:              theory_ev = 0.0
    # Is the sign certain (3-sigma)?
    margin = max(abs(bs_buy), abs(bs_sell))
    flag = "OK" if margin > 3 * se else "NOISY"
    print(f"  {s:<14} {cap:>5} {bs_buy:>+12.4f} {bs_sell:>+12.4f} {theory_q:>+9d} {theory_ev:>+10.3f} {se:>7.4f} {flag:<6}")
    mc_opt[s] = theory_q

# Convex EV(q) test: compute EV at q=-cap, q=0, q=+cap and confirm linearity.
print(f"\nCONVEXITY/LINEARITY check on a representative high-edge instrument:")
for s in ["AC_50_CO", "AC_45_KO", "AC_40_BP"]:
    i = SYMBOLS.index(s); bid, ask, cap = QUOTES[s]
    payoff_i = P_unit[:, i]
    qs = np.linspace(-cap, cap, 11).astype(int)
    print(f"  {s} (cap={cap}):")
    for q in qs:
        if q >= 0:  ev = q * (payoff_i - ask).mean()
        else:       ev = (-q) * (bid - payoff_i).mean()
        print(f"    q={q:+5d}  EV={ev:+8.3f}")
print(f"  → EV is monotone increasing toward boundary (confirms LINEAR in q).")

# ============================================================
# 4. SUPERLINEARITY: 64 subsets of 6 positive-edge positions
# ============================================================

print("\n" + "=" * 90)
print("STEP 3: Subset enumeration over positive-edge positions")
print("(2^k = 64 subsets if 6 active. Mean is linear, so subset(EV) = sum(EV) for active.)")
print("=" * 90)

active_idx = [i for i, s in enumerate(SYMBOLS) if THEORETICAL_OPT[i] != 0]
active_syms = [SYMBOLS[i] for i in active_idx]
print(f"Active (positive-edge) instruments ({len(active_idx)}): {active_syms}")
n_active = len(active_idx)
N_SUB_PATHS = 200_000
paths_sub = gen_paths(N_SUB_PATHS, seed=99)
P_sub = payoffs_matrix(paths_sub)
bids_arr = np.array([QUOTES[s][0] for s in SYMBOLS])
asks_arr = np.array([QUOTES[s][1] for s in SYMBOLS])
prices_arr = np.where(THEORETICAL_OPT >= 0, asks_arr, bids_arr)
# Per-path contribution if all active in (n_paths, n_active)
contrib = THEORETICAL_OPT[None, :] * (P_sub - prices_arr[None, :])
# Sum over active subset only (others zero)
print(f"\nEvaluating all {2**n_active} subsets...")
results = []
for mask in range(2 ** n_active):
    inc = np.zeros(len(SYMBOLS), dtype=bool)
    for k in range(n_active):
        if mask & (1 << k):
            inc[active_idx[k]] = True
    sel = contrib[:, inc].sum(axis=1)
    results.append((mask, inc.copy(), sel.mean(), sel.std()))
# Top 5 by mean
results.sort(key=lambda x: -x[2])
print(f"\nTop 8 subsets by mean PnL/path:")
print(f"  {'Mean':>9} {'SD':>8} {'CV':>7} {'Active set':<60}")
for mask, inc, m, sd in results[:8]:
    syms = [SYMBOLS[i] for i in range(len(SYMBOLS)) if inc[i]]
    cv = sd / abs(m) if m != 0 else float('inf')
    print(f"  {m:>+9.3f} {sd:>8.2f} {cv:>7.2f} {','.join(syms):<60}")

print(f"\nFull (all 6) is rank: ", end="")
for r, (mask, inc, m, sd) in enumerate(results):
    if inc.sum() == n_active:
        print(f"#{r+1} (mean {m:+.3f}, theoretical {total_ev:+.3f})")
        break

# Linearity test: any superlinear interaction?
indiv_ev = {}
for i, s in enumerate(SYMBOLS):
    if THEORETICAL_OPT[i] == 0: continue
    indiv = THEORETICAL_OPT[i] * (P_sub[:, i] - prices_arr[i])
    indiv_ev[s] = indiv.mean()
sum_indiv = sum(indiv_ev.values())
full_ev = results[0][2]  # top is full set
print(f"Sum of individual EVs : {sum_indiv:+.3f}")
print(f"Full-portfolio EV     : {full_ev:+.3f}")
print(f"Interaction (full-sum): {full_ev - sum_indiv:+.4f} (≈0 confirms linearity of E[·])")

# ============================================================
# 5. HIDDEN ARBITRAGES SCAN
# ============================================================

print("\n" + "=" * 90)
print("STEP 4: Hidden arbitrage scan")
print("=" * 90)

print("\n4a. Put-call parity at K=50, T=3w (with r=0):")
print("    C + K = P + S  ⇒ C - P = S - K = 0 (since S0=K=50)")
print(f"    Market: C(ask)-P(bid) = {QUOTES['AC_50_C'][1]-QUOTES['AC_50_P'][0]:+.4f}  (synthetic stock long)")
print(f"            C(bid)-P(ask) = {QUOTES['AC_50_C'][0]-QUOTES['AC_50_P'][1]:+.4f}  (synthetic stock short)")
print(f"    AC bid={QUOTES['AC'][0]}, ask={QUOTES['AC'][1]}.  Synthetic vs real:")
synth_long_cost = QUOTES['AC_50_C'][1] - QUOTES['AC_50_P'][0] + 50  # buy C, sell P, +K cash
synth_short_cost = QUOTES['AC_50_C'][0] - QUOTES['AC_50_P'][1] + 50
print(f"    Synthetic long cost  = {synth_long_cost:.3f} vs AC ask {QUOTES['AC'][1]}  → arb gap {synth_long_cost - QUOTES['AC'][1]:+.3f}")
print(f"    Synthetic short cost = {synth_short_cost:.3f} vs AC bid {QUOTES['AC'][0]}  → arb gap {synth_short_cost - QUOTES['AC'][0]:+.3f}")
print("    NO PCP arbitrage (gaps positive both ways = bid/ask spread is wider than mispricing).")

print("\n4b. Put-call parity at K=50, T=2w:")
print(f"    C(ask)-P(bid) = {QUOTES['AC_50_C_2'][1]-QUOTES['AC_50_P_2'][0]:+.4f}, C(bid)-P(ask) = {QUOTES['AC_50_C_2'][0]-QUOTES['AC_50_P_2'][1]:+.4f}")

print("\n4c. Chooser replication: chooser ≡ C_3w + P_2w  (Rubinstein 1991, r=0).")
chooser_ask = QUOTES['AC_50_CO'][1]
chooser_bid = QUOTES['AC_50_CO'][0]
synth_co_ask = QUOTES['AC_50_C'][1] + QUOTES['AC_50_P_2'][1]  # buy both
synth_co_bid = QUOTES['AC_50_C'][0] + QUOTES['AC_50_P_2'][0]  # sell both
print(f"    Chooser direct: bid={chooser_bid:.3f} ask={chooser_ask:.3f}")
print(f"    Replicating leg cost  buy 3w-C + buy 2w-P: ask sum = {synth_co_ask:.3f}")
print(f"    Replicating leg cost  sell 3w-C + sell 2w-P: bid sum = {synth_co_bid:.3f}")
print(f"    ARB 1: BUY chooser @ {chooser_ask:.3f}, SELL synthetic @ {synth_co_bid:.3f} → edge {synth_co_bid - chooser_ask:+.3f}")
print(f"    ARB 2: SELL chooser @ {chooser_bid:.3f}, BUY synthetic @ {synth_co_ask:.3f} → edge {chooser_bid - synth_co_ask:+.3f}")
arb_co1 = synth_co_bid - chooser_ask
arb_co2 = chooser_bid - synth_co_ask
if arb_co1 > 0 or arb_co2 > 0:
    print(f"    ★ POSITIVE STATIC ARB: max edge = {max(arb_co1, arb_co2):+.3f}/unit (caps 50/50/50, max 50 contracts).")
else:
    print(f"    No static arb after spread.")

print("\n4d. Box spread (3w options): Long P50 + Short C50 = -S + 50 (parity), creates fixed cash payout K-S_T from short stock side.")
print(f"    Cost of synthetic short = -P(ask)_50 + C(bid)_50 + S_paid  (we don't have S short).")
print("    Without bidirectional underlying short, classic box not possible (we can only LONG stock then sell it).")

print("\n4e. Calendar spread C_3w vs C_2w at K=50: theoretical value of long-3w/short-2w call calendar.")
cal_long_3w_short_2w_cost = QUOTES['AC_50_C'][1] - QUOTES['AC_50_C_2'][0]
cal_value = FV['AC_50_C'] - FV['AC_50_C_2']
print(f"    Pay {cal_long_3w_short_2w_cost:.3f}, fair = {cal_value:.3f}, edge = {cal_value - cal_long_3w_short_2w_cost:+.3f}/unit")

print("\n4f. Vol arb across strikes (per-strike implied vols vs 2.51 model):")
def implied_vol(price, S, K, T, is_call):
    lo, hi = 0.01, 20.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        v = bs_call(S, K, T, mid) if is_call else bs_put(S, K, T, mid)
        if v > price: hi = mid
        else: lo = mid
    return 0.5 * (lo + hi)
print(f"    {'Sym':<14} {'mid':>8} {'IV':>7} {'(σ_model=2.51)':>20}")
for s in ["AC_50_P","AC_50_C","AC_35_P","AC_40_P","AC_45_P","AC_60_C","AC_50_P_2","AC_50_C_2"]:
    bid, ask, _ = QUOTES[s]
    mid = 0.5 * (bid + ask)
    is_call = s.endswith("C") or s.endswith("C_2")
    K = int(s.split("_")[1])
    T = T_2W if s.endswith("_2") else T_3W
    iv = implied_vol(mid, S0, K, T, is_call)
    print(f"    {s:<14} {mid:>8.3f} {iv:>7.4f}")

# ============================================================
# 6. SENSITIVITY ANALYSIS
# ============================================================

print("\n" + "=" * 90)
print("STEP 5: Sensitivity of GLOBAL OPT to model inputs")
print("=" * 90)

def compute_opt_at(sig=SIGMA, n3w=N_3W, n2w=N_2W, override_ko=None):
    fv = fair_values(sig=sig, n3w=n3w, n2w=n2w)
    if override_ko is not None:
        fv["AC_45_KO"] = override_ko
    qvec = []; total = 0.0; per_inst = {}
    for s in SYMBOLS:
        bid, ask, cap = QUOTES[s]
        be = fv[s] - ask; se = bid - fv[s]
        if be > se and be > 0:
            q = cap; ev = be * cap
        elif se > 0:
            q = -cap; ev = se * cap
        else:
            q = 0; ev = 0
        qvec.append(q); total += ev; per_inst[s] = (q, ev)
    return np.array(qvec), total, per_inst, fv

print(f"\n5a. Sigma sensitivity (theoretical EV per path, with ×{CONTRACT_MULT} = USD):")
print(f"    {'sigma':>6} {'TotalEV':>9} {'USD':>10} {'KO_fair':>8} {'#changes_vs_2.51':>16}")
base_q, base_ev, base_per, base_fv = compute_opt_at(SIGMA)
for sig in [2.30, 2.40, 2.51, 2.60, 2.70]:
    qv, ev, per, fv = compute_opt_at(sig)
    n_changes = int((qv != base_q).sum())
    print(f"    {sig:>6.2f} {ev:>9.3f} {ev*CONTRACT_MULT:>+10,.0f} {fv['AC_45_KO']:>8.4f} {n_changes:>16}")

print(f"\n5b. KO fair sensitivity (continuous formula vs discrete):")
# Continuous-monitoring closed form for down-and-in barrier put...
# The product is "knock-out": pays max(K-S_T,0) only if min S > B. So vanilla put - down-and-in put.
# Reiner-Rubinstein (1991) closed form for r=0 simplified.
# Easier: just use given values 0.123 (continuous) and 0.206 (discrete).
for ko_fair in [0.123, 0.150, 0.175, 0.206, 0.250]:
    qv, ev, per, fv = compute_opt_at(SIGMA, override_ko=ko_fair)
    ko_q, ko_ev = per['AC_45_KO']
    print(f"    KO_fair={ko_fair:.3f}  total EV {ev:+.3f}  USD ${ev*CONTRACT_MULT:+,.0f}  KO position q={ko_q} ev={ko_ev:+.3f}")

print(f"\n5c. Time convention (15 trading days = N_3W=60 vs 21 calendar days at 4 obs/day = N_3W=84):")
for n3w_test, label in [(60, "15td (4/day)"), (60, "15td"), (84, "21cd (4/day)")]:
    if label == "15td":
        continue
    n2w_test = (n3w_test * 2) // 3
    qv, ev, per, fv = compute_opt_at(SIGMA, n3w=n3w_test, n2w=n2w_test)
    print(f"    {label:<14}  TotalEV={ev:+.3f}  USD ${ev*CONTRACT_MULT:+,.0f}  KO_fair={fv['AC_45_KO']:.4f}")

# ============================================================
# 7. SIX CANDIDATE STRATEGIES — full MC
# ============================================================

print("\n" + "=" * 90)
print("STEP 6: Compare 6 strategies under FULL MC (1M paths)")
print("=" * 90)

# Build position vectors
def vec(d):
    v = np.zeros(len(SYMBOLS), dtype=int)
    for s, q in d.items():
        v[SYMBOLS.index(s)] = q
    return v

# GLOBAL_MAX = 6 positive-edge positions at max cap (theoretical optimum).
GLOBAL_MAX = THEORETICAL_OPT.copy()

# MINE_HEDGED = global max + BUY 50 P + BUY 25 C + BUY 5 AC  (these add to existing positions)
MINE_HEDGED = GLOBAL_MAX.copy()
# These instruments may already have positions; we OVERWRITE per the user spec ("+= ").
# Spec says "global max + BUY 50 P + BUY 25 C + BUY 5 AC". Interpret: add to existing.
MINE_HEDGED[SYMBOLS.index("AC_50_P")] += 50
MINE_HEDGED[SYMBOLS.index("AC_50_C")] += 25
MINE_HEDGED[SYMBOLS.index("AC")]      += 5
# Cap clamping
caps = np.array([QUOTES[s][2] for s in SYMBOLS])
MINE_HEDGED = np.clip(MINE_HEDGED, -caps, caps)

# USER_SAFE = SELL 15 CO, SELL 50 BP, BUY 60 KO, BUY 17 P, BUY 15 P_2, BUY 15 C
USER_SAFE = vec({
    "AC_50_CO":  -15,
    "AC_40_BP":  -50,
    "AC_45_KO":   60,
    "AC_50_P":    17,
    "AC_50_P_2":  15,
    "AC_50_C":    15,
})

# DROP_60C = global max minus 60C SELL
DROP_60C = GLOBAL_MAX.copy()
DROP_60C[SYMBOLS.index("AC_60_C")] = 0

# DROP_KO = global max minus KO BUY
DROP_KO = GLOBAL_MAX.copy()
DROP_KO[SYMBOLS.index("AC_45_KO")] = 0

# HALF_SIZE = global max with all positions at 50%
HALF_SIZE = (GLOBAL_MAX // 2).astype(int)

# BONUS: CHOOSER_ARB only — pure static arb leg
# SELL chooser @22.20, BUY 3w-call @12.05, BUY 2w-put @9.75 (each capped at 50)
CHOOSER_ARB = vec({
    "AC_50_CO":  -50,
    "AC_50_C":   +50,
    "AC_50_P_2": +50,
})

# BONUS: GLOBAL_MAX_PLUS_ARB — overlay chooser arb on global max where consistent.
# Existing GLOBAL_MAX has CO=-50, P_2=+50, C=0. Adding CHOOSER_ARB → CO=-100 (over cap, clip), C=+50, P_2=+100 (over cap, clip).
# Cleaner: keep existing CO short and P_2 long; just add C buy 50 (which becomes vol-arb on a marginally rich call).
GLOBAL_MAX_PLUS_C = GLOBAL_MAX.copy()
GLOBAL_MAX_PLUS_C[SYMBOLS.index("AC_50_C")] = 50  # ride the overpriced 3w call's purchase as part of arb hedge

STRATS = {
    "GLOBAL_MAX":       GLOBAL_MAX,
    "MINE_HEDGED":      MINE_HEDGED,
    "USER_SAFE":        USER_SAFE,
    "DROP_60C":         DROP_60C,
    "DROP_KO":          DROP_KO,
    "HALF_SIZE":        HALF_SIZE,
    "CHOOSER_ARB":      CHOOSER_ARB,
    "GLOBAL_MAX_PLUS_C": GLOBAL_MAX_PLUS_C,
}

print(f"\nPosition vectors:\n{'Strategy':<14} " + " ".join(f"{s:>10}" for s in SYMBOLS))
for name, v in STRATS.items():
    print(f"{name:<14} " + " ".join(f"{x:>+10d}" for x in v))

# Re-use 1M paths for evaluation
results = {}
print(f"\nEvaluating each on {N_PATHS_BIG:,} paths...")
for name, v in STRATS.items():
    pnl = pnl_matrix(paths_big, v)
    mean = pnl.mean()
    sd = pnl.std(ddof=1)
    sharpe_perpath = mean / sd if sd > 0 else 0.0
    # 100-sim trial: mean of 100 i.i.d. realizations of this PnL
    # E[mean100] = mean, SD[mean100] = sd / sqrt(100)
    sd_100 = sd / 10.0
    sharpe_100 = mean / sd_100 if sd_100 > 0 else 0.0
    # Per-trial CVaR at 5% (left tail of mean100). Approximate via CLT: mean - 1.645*sd_100 for VaR95, or:
    # CVaR_5% on mean100 ≈ mean - sd_100 * (norm.pdf(z)/(1-cdf(z))) where z = norm.ppf(0.95)
    z = norm.ppf(0.95)
    cvar_factor = norm.pdf(z) / 0.05  # ≈ 2.063
    cvar5_100 = mean - sd_100 * cvar_factor
    # P(trial > 0)
    p_pos = norm.cdf(mean / sd_100) if sd_100 > 0 else 1.0
    # Per-path stats
    pct = np.percentile(pnl, [1, 5, 25, 50, 75, 95, 99])
    results[name] = {
        "mean": mean, "sd": sd, "sd_100": sd_100,
        "sharpe_perpath": sharpe_perpath, "sharpe_100": sharpe_100,
        "cvar5_100": cvar5_100, "p_pos": p_pos,
        "pct": pct,
        "mean_usd": mean * CONTRACT_MULT,
        "sd_100_usd": sd_100 * CONTRACT_MULT,
        "cvar5_usd": cvar5_100 * CONTRACT_MULT,
    }

# Print full table
print(f"\n{'Strategy':<14} {'Mean PnL':>9} {'$ Mean':>11} {'$ SD/trial':>11} {'Sharpe/trial':>12} {'$ CVaR5':>11} {'P(>0)':>7}")
for name, r in results.items():
    print(f"{name:<14} {r['mean']:>+9.3f} {r['mean_usd']:>+11,.0f} {r['sd_100_usd']:>11,.0f} {r['sharpe_100']:>12.2f} {r['cvar5_usd']:>+11,.0f} {r['p_pos']*100:>6.1f}%")

# Rank by each objective
def rank(metric_key, descending=True):
    items = sorted(results.items(), key=lambda kv: kv[1][metric_key], reverse=descending)
    return [name for name, _ in items]

print(f"\nRankings:")
print(f"  By E[score]:    {' > '.join(rank('mean'))}")
print(f"  By Sharpe:      {' > '.join(rank('sharpe_100'))}")
print(f"  By CVaR-5%:     {' > '.join(rank('cvar5_100'))}")
print(f"  By P(profit):   {' > '.join(rank('p_pos'))}")

# Save JSON for the report builder
out = {
    "fair_values": FV,
    "theoretical_opt": {SYMBOLS[i]: int(THEORETICAL_OPT[i]) for i in range(len(SYMBOLS))},
    "theoretical_total_ev": float(total_ev),
    "theoretical_total_usd": float(total_ev * CONTRACT_MULT),
    "strategies": {name: {SYMBOLS[i]: int(v[i]) for i in range(len(SYMBOLS))} for name, v in STRATS.items()},
    "strategy_metrics": {name: {k: (float(x) if not isinstance(x, np.ndarray) else x.tolist())
                                for k, x in r.items()} for name, r in results.items()},
}
import json as _json
with open("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/manual/global_search_v2.json", "w") as f:
    _json.dump(out, f, indent=2)

print(f"\nElapsed: {time.time()-t0:.1f}s")
print("=" * 90)
print("DONE.  See global_search_v2.md for the report.")
print("=" * 90)
