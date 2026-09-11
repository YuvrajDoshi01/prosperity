"""KO put fair value: monitoring frequency verification + Bayesian decision.

R4 manual challenge: AC_45_KO is a down-and-out put with K=45, B=35, T=15td,
S0=50, sigma=2.51 annualized, drift=-sigma^2/2 (martingale GBM, IMC convention).

Tasks:
  1. High-precision MC at 4/day (5 seeds x 5M paths = 25M total) -> confirm 0.207
  2. Sweep monitoring frequency: 1/day .. 1000/day -> verify continuous limit
     converges to Reiner-Rubinstein closed form (~0.123)
  3. Broadie-Glasserman-Kou (BGK) adjusted-barrier approximation
     B* = B * exp(-0.5826 * sigma * sqrt(dt)) under continuous formula
  4. Implied monitoring frequency from market mid 0.1625
  5. Bayesian decision under monitoring uncertainty
  6. Minimax-regret optimal KO size

Vectorized numpy. ~5-10 min total.
"""
from __future__ import annotations

import json
import math
import time
from statistics import NormalDist

import numpy as np

# -- Inputs (per CLAUDE.md / brief) ------------------------------------------
S0 = 50.0
SIGMA = 2.51
TRADING_DAYS_YEAR = 252
T_DAYS = 15
T_YEARS = T_DAYS / TRADING_DAYS_YEAR
K = 45.0
B = 35.0

# Quotes
KO_BID = 0.150
KO_ASK = 0.175
KO_MID = 0.5 * (KO_BID + KO_ASK)
KO_VOL_CAP = 500
MULTIPLIER = 3000

# ---------------------------------------------------------------------------
# 1) Reiner-Rubinstein closed form (continuous monitoring) for down-and-out put
# ---------------------------------------------------------------------------
# Reference: Haug "Complete Guide to Option Pricing Formulas", down-and-out put.
# We have r=0, q=0, drift = -0.5 sigma^2 (so under risk-neutral measure r=0).
# Standard formulas (Reiner-Rubinstein 1991): with eta=1 (down barrier),
# phi=-1 (put). H = barrier B, K = strike, S = spot, T = time, vol = sigma.
#
#   mu = (r - q) / sigma^2 - 0.5
#   lambda_ = sqrt(mu^2 + 2*r/sigma^2)   (with r=0 -> lambda = |mu|)
#   x1 = ln(S/K)/(s*sqrt(T)) + (1+mu)*s*sqrt(T)
#   x2 = ln(S/H)/(s*sqrt(T)) + (1+mu)*s*sqrt(T)
#   y1 = ln(H^2/(S*K))/(s*sqrt(T)) + (1+mu)*s*sqrt(T)
#   y2 = ln(H/S)/(s*sqrt(T)) + (1+mu)*s*sqrt(T)
#
# Down-and-out put (K > H, i.e. K=45 > B=35):
#   P_di (down-and-in) =
#       phi*S*N(phi*x1) - phi*K*exp(-rT)*N(phi*x1 - phi*s*sqrt(T))
#       - phi*S*(H/S)^(2*(mu+1))*N(eta*y1) + phi*K*exp(-rT)*(H/S)^(2*mu)*N(eta*y1 - eta*s*sqrt(T))   when K > H
#   But we want P_do = P_vanilla - P_di
#
# Simpler: use the standard "down-and-out put" formula directly
# (case K > H, equivalent to A - B + C - D in Haug notation):
# Let phi=-1, eta=+1 (down barrier, meaning H below S0).
N = NormalDist().cdf

def reiner_rubinstein_do_put(S, K_, H, T, sigma, r=0.0, q=0.0):
    """Closed-form Reiner-Rubinstein down-and-out put with continuous monitoring."""
    if H >= S:
        # Already "knocked out" or at barrier
        return 0.0
    s_sqrt_T = sigma * math.sqrt(T)
    mu = (r - q) / (sigma * sigma) - 0.5
    lam = math.sqrt(mu * mu + 2.0 * r / (sigma * sigma)) if sigma > 0 else 0.0

    x1 = math.log(S / K_) / s_sqrt_T + (1.0 + mu) * s_sqrt_T
    x2 = math.log(S / H) / s_sqrt_T + (1.0 + mu) * s_sqrt_T
    y1 = math.log((H * H) / (S * K_)) / s_sqrt_T + (1.0 + mu) * s_sqrt_T
    y2 = math.log(H / S) / s_sqrt_T + (1.0 + mu) * s_sqrt_T

    phi = -1.0  # put
    eta = +1.0  # down barrier (eta = sign(S - H))

    A = phi * S * math.exp(-q * T) * N(phi * x1) - phi * K_ * math.exp(-r * T) * N(phi * x1 - phi * s_sqrt_T)
    B_term = phi * S * math.exp(-q * T) * N(phi * x2) - phi * K_ * math.exp(-r * T) * N(phi * x2 - phi * s_sqrt_T)
    C = phi * S * math.exp(-q * T) * (H / S) ** (2.0 * (mu + 1.0)) * N(eta * y1) \
        - phi * K_ * math.exp(-r * T) * (H / S) ** (2.0 * mu) * N(eta * y1 - eta * s_sqrt_T)
    D = phi * S * math.exp(-q * T) * (H / S) ** (2.0 * (mu + 1.0)) * N(eta * y2) \
        - phi * K_ * math.exp(-r * T) * (H / S) ** (2.0 * mu) * N(eta * y2 - eta * s_sqrt_T)

    # Down-and-out put with K > H (our case: K=45 > H=35):
    # P_do = A - B + C - D    (Haug Table 4-12, "down-and-out put", K > H)
    return A - B_term + C - D


# ---------------------------------------------------------------------------
# 2) Discrete-monitoring Monte Carlo (vectorized)
# ---------------------------------------------------------------------------
def ko_mc_vectorized(n_paths: int, n_steps: int, seed: int,
                     S0: float = S0, sigma: float = SIGMA, T: float = T_YEARS,
                     K_: float = K, H: float = B,
                     return_se: bool = True):
    """Run vectorized GBM with discrete barrier monitoring at n_steps points.

    Steps are evenly spaced over T. Barrier checked AFTER each step.
    drift = -0.5 sigma^2 (martingale).
    """
    rng = np.random.default_rng(seed)
    dt = T / n_steps
    drift = -0.5 * sigma * sigma * dt
    vol = sigma * math.sqrt(dt)

    # Process in chunks to control memory; here single shot fine if n_paths*n_steps <= 5M*60 = 300M floats
    # We keep min_S running -> O(n_paths) memory.
    log_S = np.full(n_paths, math.log(S0), dtype=np.float64)
    breached = np.zeros(n_paths, dtype=bool)
    log_B = math.log(H)

    # Generate noise in column-major chunks if memory is a concern.
    # Trade memory for speed: do 1M paths at a time if n_paths*n_steps > 60M.
    BATCH = max(1, min(n_paths, max(1, 60_000_000 // max(1, n_steps))))

    payoffs = np.empty(n_paths, dtype=np.float64)

    idx = 0
    while idx < n_paths:
        end = min(idx + BATCH, n_paths)
        n_batch = end - idx
        # Generate full noise matrix (n_batch x n_steps) -- log-returns
        z = rng.standard_normal((n_batch, n_steps))
        log_returns = drift + vol * z          # shape (n_batch, n_steps)
        log_paths = math.log(S0) + np.cumsum(log_returns, axis=1)   # (n_batch, n_steps)
        # Min over the path (post each step). Initial S0 is NOT a monitoring point
        # since at t=0 the option exists by construction (S0=50 > B=35).
        log_min = log_paths.min(axis=1)
        breached_batch = log_min <= log_B
        S_T = np.exp(log_paths[:, -1])
        payoff = np.where(breached_batch, 0.0, np.maximum(K_ - S_T, 0.0))
        payoffs[idx:end] = payoff
        idx = end

    mean = float(payoffs.mean())
    if return_se:
        sd = float(payoffs.std(ddof=1))
        se = sd / math.sqrt(n_paths)
        return mean, se
    return mean


# ---------------------------------------------------------------------------
# 3) Broadie-Glasserman-Kou adjusted-barrier formula
# ---------------------------------------------------------------------------
# For discretely monitored down-barrier with monitoring step dt:
#   B*  = B * exp(-beta * sigma * sqrt(dt))     (down barrier shifted DOWN)
# where beta = -zeta(1/2)/sqrt(2pi) = 0.5826 (Broadie, Glasserman, Kou 1997).
# Apply continuous-monitoring formula with B*. Note: this lowers the effective
# barrier, so price is HIGHER than continuous (closer to vanilla) -- correct
# direction, since discrete monitoring breaches less often.
BGK_BETA = 0.5826


def bgk_do_put(S, K_, H, T, sigma, n_steps_per_year_mon: float):
    """Broadie-Glasserman-Kou: continuous formula with adjusted barrier B*.

    n_steps_per_year_mon: total monitoring points scaled to 1 year (so dt = 1 / n)
    """
    dt = 1.0 / n_steps_per_year_mon
    H_star = H * math.exp(-BGK_BETA * sigma * math.sqrt(dt))
    return reiner_rubinstein_do_put(S, K_, H_star, T, sigma)


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------
def main():
    out_lines = []
    log = lambda *a: (print(*a), out_lines.append(" ".join(str(x) for x in a)))

    log("=" * 80)
    log(f"KO PUT FAIR VALUE -- MONITORING FREQUENCY VERIFICATION")
    log(f"S0={S0}, sigma={SIGMA}, T={T_DAYS}td={T_YEARS:.6f}y, K={K}, B={B}")
    log(f"drift = -0.5*sigma^2 = {-0.5*SIGMA*SIGMA:.4f}/year (martingale)")
    log("=" * 80)

    # --- Continuous-monitoring closed form -----------------------------------
    cont = reiner_rubinstein_do_put(S0, K, B, T_YEARS, SIGMA)
    log(f"\n[Reiner-Rubinstein continuous-monitoring closed form]")
    log(f"  fair_continuous = {cont:.6f}")

    # --- Task 1: High-precision MC at 4/day (5 seeds x 5M paths) -------------
    log(f"\n{'='*80}")
    log(f"TASK 1: HIGH-PRECISION MC AT 4/day (5 seeds x 5M paths = 25M total)")
    log(f"{'='*80}")

    n_steps_4day = T_DAYS * 4   # 60
    seeds = [101, 202, 303, 404, 505]
    NP = 5_000_000

    estimates_4day = []
    ses_4day = []
    t0 = time.time()
    for s in seeds:
        ts = time.time()
        m, se = ko_mc_vectorized(NP, n_steps_4day, s)
        estimates_4day.append(m)
        ses_4day.append(se)
        log(f"  Seed {s}: fair = {m:.6f}  SE = {se:.6f}  ({time.time()-ts:.1f}s)")
    avg_4day = float(np.mean(estimates_4day))
    spread = float(np.max(estimates_4day) - np.min(estimates_4day))
    # Combined SE assuming independence
    combined_se = float(np.sqrt(np.mean(np.array(ses_4day) ** 2)) / math.sqrt(len(seeds)))
    log(f"\n  Pooled 4/day estimate over {len(seeds)} seeds, {len(seeds)*NP:,} paths:")
    log(f"    fair_4day       = {avg_4day:.6f}")
    log(f"    spread (max-min)= {spread:.6f}")
    log(f"    combined SE     = {combined_se:.6f}")
    log(f"    99% CI          = [{avg_4day - 2.576*combined_se:.6f}, {avg_4day + 2.576*combined_se:.6f}]")
    log(f"  Total time: {time.time()-t0:.1f}s")

    # --- Task 2: Frequency sweep --------------------------------------------
    log(f"\n{'='*80}")
    log(f"TASK 2: MONITORING FREQUENCY SWEEP (per-day)")
    log(f"{'='*80}")
    log(f"  Each row: 2M paths, single seed (seed=7).")

    # n_obs/day to test
    freqs = [1, 2, 4, 8, 16, 32, 96, 1000]
    NP_SWEEP = 2_000_000
    sweep = []
    log(f"  {'obs/day':>8} {'n_steps':>9} {'MC fair':>10} {'SE':>9}  {'BGK fair':>10}  {'continuous':>11}")
    for f in freqs:
        n_steps = T_DAYS * f
        # MC
        ts = time.time()
        m, se = ko_mc_vectorized(NP_SWEEP, n_steps, seed=7)
        # BGK: dt corresponds to 1 monitoring tick = 1/(252*f) year
        bgk = bgk_do_put(S0, K, B, T_YEARS, SIGMA, n_steps_per_year_mon=TRADING_DAYS_YEAR * f)
        sweep.append({"obs_per_day": f, "n_steps": n_steps, "mc": m, "se": se, "bgk": bgk})
        log(f"  {f:>8} {n_steps:>9} {m:>10.6f} {se:>9.6f}  {bgk:>10.6f}  {cont:>11.6f}  ({time.time()-ts:.1f}s)")

    # 1000/day "near-continuous" + BGK convergence
    log(f"\n  Continuous closed-form: {cont:.6f}")
    log(f"  As n_obs/day -> infty, MC and BGK -> continuous limit.")

    # --- Task 3: BGK accuracy at 4/day --------------------------------------
    log(f"\n{'='*80}")
    log(f"TASK 3: BGK ACCURACY AT 4/day")
    log(f"{'='*80}")
    bgk_4 = bgk_do_put(S0, K, B, T_YEARS, SIGMA, n_steps_per_year_mon=TRADING_DAYS_YEAR * 4)
    log(f"  4/day MC fair (high-precision): {avg_4day:.6f} +/- {combined_se:.6f}")
    log(f"  4/day BGK approximation:        {bgk_4:.6f}")
    log(f"  BGK error vs MC:                {bgk_4 - avg_4day:+.6f} ({(bgk_4-avg_4day)/avg_4day*100:+.2f}%)")
    log(f"  Continuous closed form:         {cont:.6f}")
    log(f"  MC discrete vs continuous:      {avg_4day - cont:+.6f} ({(avg_4day-cont)/cont*100:+.2f}%)")

    # --- Task 4: Implied monitoring frequency -------------------------------
    log(f"\n{'='*80}")
    log(f"TASK 4: IMPLIED MONITORING FREQUENCY FROM MARKET MID {KO_MID}")
    log(f"{'='*80}")
    log(f"  Market: bid {KO_BID} / ask {KO_ASK} / mid {KO_MID}")
    log(f"  Find n* such that fair(n*) = {KO_MID}.")
    log(f"  Using BGK + bisection (consistent with continuous limit).")

    # Bisect on log(n_obs/day) with BGK as the smooth surrogate
    def bgk_for_per_day(n_per_day):
        return bgk_do_put(S0, K, B, T_YEARS, SIGMA, n_steps_per_year_mon=TRADING_DAYS_YEAR * n_per_day)

    # Sanity: BGK at very high n should equal continuous; at low n equals 4/day BGK
    # We want bgk_for_per_day(n) = KO_MID = 0.1625
    # cont (n=inf) = 0.123, so 0.1625 > cont always... so n must be FINITE.
    # bgk(n=1) > bgk(n=4) > bgk(n=inf) -- monotone decreasing in n.
    # Find n where bgk = 0.1625.
    target = KO_MID
    # Use logspace bisection
    lo, hi = 1.0, 10000.0
    if bgk_for_per_day(lo) < target or bgk_for_per_day(hi) > target:
        log(f"  Warning: target {target} outside BGK range [{bgk_for_per_day(hi):.4f}, {bgk_for_per_day(lo):.4f}]")
    for _ in range(80):
        mid = math.sqrt(lo * hi)
        if bgk_for_per_day(mid) > target:
            lo = mid
        else:
            hi = mid
    n_star = math.sqrt(lo * hi)
    log(f"  Implied n* (BGK) = {n_star:.2f} obs/day")
    log(f"    (4/day -> {bgk_for_per_day(4):.4f}, 8/day -> {bgk_for_per_day(8):.4f}, "
        f"16/day -> {bgk_for_per_day(16):.4f}, 96/day -> {bgk_for_per_day(96):.4f})")

    # --- Task 5: Edge / EV under different monitoring assumptions -----------
    log(f"\n{'='*80}")
    log(f"TASK 5: EDGE & EV UNDER MONITORING ASSUMPTIONS")
    log(f"{'='*80}")

    fair_by_freq = {row["obs_per_day"]: row["mc"] for row in sweep}
    fair_by_freq[4] = avg_4day  # use high-precision
    fair_by_freq["continuous"] = cont

    log(f"  Using BUY price = ASK = {KO_ASK}, SELL price = BID = {KO_BID}.")
    log(f"  EV per unit (BUY) = fair - ASK; (SELL) = BID - fair.")
    log(f"  At v contracts and multiplier x{MULTIPLIER}, total EV = v * edge_per_unit * {MULTIPLIER}.")
    log("")
    log(f"  {'freq':>12} {'fair':>9} {'BUY edge':>10} {'SELL edge':>10}  {'BUY 500 EV':>13} {'SELL 500 EV':>13}")
    scenarios = [(1, fair_by_freq[1]), (2, fair_by_freq[2]), (4, fair_by_freq[4]), (8, fair_by_freq[8]),
                 (16, fair_by_freq[16]), (32, fair_by_freq[32]), (96, fair_by_freq[96]),
                 ("continuous", cont)]
    for label, f in scenarios:
        buy_edge = f - KO_ASK
        sell_edge = KO_BID - f
        buy_ev_500 = 500 * buy_edge * MULTIPLIER
        sell_ev_500 = 500 * sell_edge * MULTIPLIER
        log(f"  {str(label):>12} {f:>9.4f} {buy_edge:>+10.4f} {sell_edge:>+10.4f}  ${buy_ev_500:>+12,.0f} ${sell_ev_500:>+12,.0f}")

    # --- Task 6: Bayesian decision ------------------------------------------
    log(f"\n{'='*80}")
    log(f"TASK 6: BAYESIAN DECISION  (P(4/d)=0.7, P(8/d)=0.2, P(16/d)=0.1)")
    log(f"{'='*80}")
    P_4 = 0.7
    P_8 = 0.2
    P_16 = 0.1
    fair_4 = avg_4day
    fair_8 = fair_by_freq[8]
    fair_16 = fair_by_freq[16]
    log(f"  fair_4  = {fair_4:.4f}")
    log(f"  fair_8  = {fair_8:.4f}")
    log(f"  fair_16 = {fair_16:.4f}")

    # E[fair] under prior
    E_fair = P_4 * fair_4 + P_8 * fair_8 + P_16 * fair_16
    log(f"  E[fair] = {E_fair:.4f}")
    log(f"  E[BUY edge]  = E[fair] - ASK  = {E_fair - KO_ASK:+.4f}")
    log(f"  E[SELL edge] = BID - E[fair]  = {KO_BID - E_fair:+.4f}")

    # Position sign chosen by sign of E[edge]; size by Kelly-style (pure linear here).
    # For the manual challenge, payoff is LINEAR in v, so optimal v is at the cap
    # in whichever direction has positive E[edge]. There is NO Kelly fractional
    # because the EV function is linear (no quadratic risk penalty UNLESS we add one).
    # Since rules cap at 500 either side, choose sign of E[edge].
    if (E_fair - KO_ASK) > 0:
        bayes_dir = "BUY"
        bayes_edge = E_fair - KO_ASK
    else:
        bayes_dir = "SELL"
        bayes_edge = KO_BID - E_fair
    log(f"  Bayes-optimal direction (point EV): {bayes_dir} at edge {bayes_edge:+.4f}")
    log(f"  Bayes-optimal full size: {bayes_dir} 500  (linear payoff -> bang-bang)")
    log(f"  Bayes EV at 500: ${500 * bayes_edge * MULTIPLIER:+,.0f}")

    # Mean-variance trade-off: variance of EV across scenarios (model risk)
    EVs = {
        "BUY 500":  500 * MULTIPLIER * (np.array([fair_4, fair_8, fair_16, cont]) - KO_ASK),
        "SHORT 500": 500 * MULTIPLIER * (KO_BID - np.array([fair_4, fair_8, fair_16, cont])),
        "BUY 100":  100 * MULTIPLIER * (np.array([fair_4, fair_8, fair_16, cont]) - KO_ASK),
        "SHORT 100": 100 * MULTIPLIER * (KO_BID - np.array([fair_4, fair_8, fair_16, cont])),
        "ZERO":     np.zeros(4),
    }
    log(f"\n  Per-scenario EV (4/d, 8/d, 16/d, continuous):")
    for name, vec in EVs.items():
        log(f"    {name:>10}: 4d=${vec[0]:>+10,.0f}  8d=${vec[1]:>+10,.0f}  16d=${vec[2]:>+10,.0f}  cont=${vec[3]:>+10,.0f}")

    # Posterior-weighted EV (continuous excluded since prior doesn't include it)
    prior4 = np.array([P_4, P_8, P_16])
    fairs3 = np.array([fair_4, fair_8, fair_16])

    log(f"\n  Posterior-weighted EV (3-scenario prior):")
    sizes = [-500, -300, -100, 0, 100, 300, 500]
    best = None
    for v in sizes:
        if v >= 0:
            ev_per_scen = v * MULTIPLIER * (fairs3 - KO_ASK)
        else:
            ev_per_scen = -v * MULTIPLIER * (KO_BID - fairs3)
        bayes_ev = float(np.sum(prior4 * ev_per_scen))
        worst = float(np.min(ev_per_scen))
        log(f"    v={v:>+5d}: BayesEV=${bayes_ev:>+11,.0f}  worst=${worst:>+11,.0f}")
        if best is None or bayes_ev > best[1]:
            best = (v, bayes_ev)
    log(f"  Bayes-best size: {best[0]:+d}  with EV ${best[1]:+,.0f}")

    # --- Task 7: Minimax regret ---------------------------------------------
    log(f"\n{'='*80}")
    log(f"TASK 7: MINIMAX REGRET ACROSS MONITORING ASSUMPTIONS")
    log(f"{'='*80}")
    # Scenario set: 4/d, 8/d, 16/d, continuous
    scenarios_for_regret = [("4/d", fair_4), ("8/d", fair_8), ("16/d", fair_16), ("cont", cont)]
    log(f"  Scenario set: 4/d, 8/d, 16/d, continuous")
    log(f"  Action set:  v in [-500, +500] (sign+size).")

    candidate_actions = list(range(-500, 501, 25))
    # For each scenario, compute best EV achievable by ANY action
    scenario_best = {}
    for name, f in scenarios_for_regret:
        best_a, best_ev = None, -1e18
        for a in candidate_actions:
            if a >= 0:
                ev = a * MULTIPLIER * (f - KO_ASK)
            else:
                ev = -a * MULTIPLIER * (KO_BID - f)
            if ev > best_ev:
                best_ev, best_a = ev, a
        scenario_best[name] = (best_a, best_ev)
        log(f"  Scenario {name}: best action = {best_a:+d}, best EV = ${best_ev:+,.0f}")

    # Minimax regret
    log(f"\n  Regret = best_EV_in_scenario - EV_of_chosen_action_in_that_scenario")
    log(f"  Choose action that MINIMIZES the MAXIMUM regret across scenarios.")
    log("")
    minimax = None
    log(f"  {'v':>5} {'reg(4/d)':>12} {'reg(8/d)':>12} {'reg(16/d)':>12} {'reg(cont)':>12} {'max_regret':>12} {'BayesEV':>12}")
    for a in candidate_actions:
        regrets = []
        evs = []
        for name, f in scenarios_for_regret:
            if a >= 0:
                ev = a * MULTIPLIER * (f - KO_ASK)
            else:
                ev = -a * MULTIPLIER * (KO_BID - f)
            evs.append(ev)
            regrets.append(scenario_best[name][1] - ev)
        max_regret = max(regrets)
        bayes_ev_3 = sum(prior4[i] * evs[i] for i in range(3))  # 3-scenario prior
        if minimax is None or max_regret < minimax[1]:
            minimax = (a, max_regret, bayes_ev_3)
        # Print only key rows to keep log manageable
        if a in [-500, -300, -100, -50, -25, 0, 25, 50, 100, 300, 500]:
            log(f"  {a:>+5d} ${regrets[0]:>+11,.0f} ${regrets[1]:>+11,.0f} ${regrets[2]:>+11,.0f} ${regrets[3]:>+11,.0f} "
                f"${max_regret:>+11,.0f} ${bayes_ev_3:>+11,.0f}")

    log(f"\n  *** MINIMAX-REGRET OPTIMAL: v = {minimax[0]:+d} (max_regret = ${minimax[1]:+,.0f}, BayesEV = ${minimax[2]:+,.0f})")

    # --- Decision summary ---------------------------------------------------
    log(f"\n{'='*80}")
    log(f"DECISION SUMMARY")
    log(f"{'='*80}")
    log(f"  4/day fair (HP MC)        = {avg_4day:.4f}  +/- {combined_se:.4f}")
    log(f"  Continuous fair (RR)      = {cont:.4f}")
    log(f"  BGK at 4/day              = {bgk_4:.4f}  (BGK error {(bgk_4-avg_4day)*100:+.2f}c vs MC)")
    log(f"  Market mid                = {KO_MID:.4f}")
    log(f"  Implied monitoring (BGK)  = {n_star:.1f} obs/day")
    log(f"  E[fair | prior]           = {E_fair:.4f}")
    log(f"  Bayes-best size           = {best[0]:+d}  (EV ${best[1]:+,.0f})")
    log(f"  Minimax-regret size       = {minimax[0]:+d}  (max regret ${minimax[1]:+,.0f})")
    log(f"")
    if minimax[0] > 0:
        log(f"  SHIP CALL: BUY {minimax[0]} AC_45_KO @ {KO_ASK}")
    elif minimax[0] < 0:
        log(f"  SHIP CALL: SELL {-minimax[0]} AC_45_KO @ {KO_BID}")
    else:
        log(f"  SHIP CALL: ZERO position in AC_45_KO")

    # --- JSON dump ---
    out = {
        "inputs": {
            "S0": S0, "sigma": SIGMA, "T_days": T_DAYS, "K": K, "B": B,
            "ko_bid": KO_BID, "ko_ask": KO_ASK, "ko_mid": KO_MID,
            "vol_cap": KO_VOL_CAP, "multiplier": MULTIPLIER,
        },
        "fair_value": {
            "continuous_RR": cont,
            "mc_4_per_day_pooled": avg_4day,
            "mc_4_per_day_combined_se": combined_se,
            "mc_4_per_day_seed_estimates": dict(zip([str(s) for s in seeds], estimates_4day)),
            "bgk_4_per_day": bgk_4,
        },
        "frequency_sweep": sweep,
        "implied_monitoring_per_day_BGK": n_star,
        "edges": {
            str(label): {"fair": f, "buy_edge": f - KO_ASK, "sell_edge": KO_BID - f,
                         "buy_500_EV": 500*(f-KO_ASK)*MULTIPLIER, "sell_500_EV": 500*(KO_BID-f)*MULTIPLIER}
            for label, f in scenarios
        },
        "bayes": {
            "prior": {"4/d": P_4, "8/d": P_8, "16/d": P_16},
            "E_fair": E_fair,
            "bayes_best_size": best[0],
            "bayes_best_EV": best[1],
        },
        "minimax_regret": {
            "size": minimax[0],
            "max_regret_USD": minimax[1],
            "bayes_ev_USD": minimax[2],
            "scenario_best": {k: {"action": v[0], "ev": v[1]} for k, v in scenario_best.items()},
        },
    }
    with open("trader-logic/round-4/manual/ko_monitoring_v2_results.json", "w") as f:
        json.dump(out, f, indent=2)
    with open("trader-logic/round-4/manual/ko_monitoring_v2_output.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))
    log(f"\nJSON saved -> ko_monitoring_v2_results.json")


if __name__ == "__main__":
    main()
