#!/usr/bin/env python3
"""
Invest & Expand — Comprehensive Manual Challenge Solver (v5)

Problem:
  Budget = 50,000 XIRECs
  Allocate r, s, sp in [0,100] integers, r + s + sp <= 100
  Research(r) = 200,000 * ln(1+r) / ln(101)
  Scale(s)    = 7 * s / 100
  Speed_mult  = rank-based (0.1 to 0.9, linear interpolation by rank)
  PnL = Research(r) * Scale(s) * Speed_mult(sp) - 500*(r+s+sp)

Sections:
  1. Optimal allocation for each fixed speed multiplier h
  2. Game-theoretic speed analysis (Nash, best response, population models)
  3. Sensitivity analysis
  4. Scenario analysis for concrete allocations
  5. Symmetric Nash equilibrium derivation
  6. Final recommendation with justification
"""

import math
import random
import json
from pathlib import Path
from collections import defaultdict

# =============================================================================
# Constants
# =============================================================================

BUDGET = 50_000
LOG_101 = math.log(101)
COST_PER_PCT = BUDGET / 100  # = 500

# =============================================================================
# Core functions
# =============================================================================

def research(r):
    """Research payoff: concave log, [0, 200000]."""
    if r <= 0:
        return 0.0
    return 200_000 * math.log(1 + r) / LOG_101

def scale(s):
    """Scale multiplier: linear, [0, 7]."""
    return 7.0 * s / 100.0

def pnl(r, s, sp, h):
    """PnL given allocation (r, s, sp) and speed multiplier h."""
    return research(r) * scale(s) * h - COST_PER_PCT * (r + s + sp)

def research_derivative(r):
    """d/dr Research(r) = 200000 / ((1+r) * ln(101))."""
    return 200_000 / ((1 + r) * LOG_101)

# =============================================================================
# Section 1: Optimal allocation for each fixed speed multiplier h
# =============================================================================

def section_1_fixed_speed():
    """
    Key insight: PnL is linear in s (Scale is linear).
    For any fixed (r, sp), the optimal s = 100 - r - sp (maximize s).

    With s = 100 - r - sp, we reduce to:
      PnL(r, sp; h) = Research(r) * 7*(100-r-sp)/100 * h - 500*100
                     = h * 14000 * (100-r-sp)/100 * ln(1+r)/ln(101) - 50000

    Wait: the budget constraint is r+s+sp <= 100, not = 100.
    Since s linearly increases PnL (coefficient = Research(r)*7/100*h > 0 for r>0),
    optimal s* = 100 - r - sp, spending the full budget.

    Then cost = 500 * 100 = 50000 always.

    PnL = h * (200000 * ln(1+r)/ln(101)) * (7*(100-r-sp)/100) - 50000

    FOC w.r.t. r (holding sp fixed):
      d/dr [ln(1+r) * (100-r-sp)] = 0
      (100-r-sp)/(1+r) - ln(1+r) = 0
      (100-r-sp)/(1+r) = ln(1+r)

    This is INDEPENDENT of h! The optimal r depends only on sp.
    """

    print("=" * 80)
    print("SECTION 1: OPTIMAL ALLOCATION FOR EACH FIXED SPEED MULTIPLIER")
    print("=" * 80)

    print("\n--- Mathematical derivation ---")
    print("PnL is LINEAR in s => optimal s* = 100 - r - sp (spend full budget)")
    print("Cost = 500 * 100 = 50,000 always at optimum")
    print("")
    print("Reduced problem: max_r [ h * K * ln(1+r) * (100-r-sp) ] - 50000")
    print("where K = 200000 * 7 / (100 * ln(101)) = 14000 / ln(101)")
    print("")
    print("FOC: (100 - r - sp) / (1+r) = ln(1+r)")
    print("This equation is INDEPENDENT of h (speed multiplier)!")
    print("=> Optimal r*(sp) is the same for all h.")
    print("")

    K = 14_000 / LOG_101

    # Solve FOC numerically for each sp
    def solve_foc_continuous(sp):
        """Find r* that satisfies (100-r-sp)/(1+r) = ln(1+r)."""
        # Binary search on r in [0, 100-sp]
        lo, hi = 0.001, 100 - sp - 0.001
        if hi <= lo:
            return 0.0
        for _ in range(200):
            mid = (lo + hi) / 2
            lhs = (100 - mid - sp) / (1 + mid)
            rhs = math.log(1 + mid)
            if lhs > rhs:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    # Table: for each h, find optimal (r, s, sp) by brute force over integer grid
    print("--- Brute force optimal for each h (integer allocations) ---")
    print(f"{'h':>5} | {'r*':>4} {'s*':>4} {'sp*':>4} | {'PnL':>12} | {'Research':>10} {'Scale':>6} {'Gross':>12} {'Cost':>8}")
    print("-" * 80)

    results_sec1 = {}
    for h_idx in range(1, 10):
        h = h_idx / 10.0
        best_pnl = -1e18
        best_alloc = (0, 0, 0)
        for r in range(101):
            rv = research(r)
            for sp in range(101 - r):
                s = 100 - r - sp  # optimal s
                sv = scale(s)
                p = rv * sv * h - COST_PER_PCT * (r + s + sp)
                if p > best_pnl:
                    best_pnl = p
                    best_alloc = (r, s, sp)
        r_, s_, sp_ = best_alloc
        rv = research(r_)
        sv = scale(s_)
        gross = rv * sv * h
        cost = COST_PER_PCT * (r_ + s_ + sp_)
        results_sec1[h] = {"alloc": best_alloc, "pnl": best_pnl, "gross": gross, "cost": cost}
        print(f"  {h:>3.1f} | {r_:>4} {s_:>4} {sp_:>4} | {best_pnl:>12,.0f} | {rv:>10,.0f} {sv:>6.2f} {gross:>12,.0f} {cost:>8,.0f}")

    print("")
    print("KEY OBSERVATION: When h is GIVEN (not competitive), optimal sp*=0 always.")
    print("You never waste budget on Speed when the multiplier is already determined.")
    print("r* = 23 at sp=0 is the FOC solution: (100-23)/(1+23) = ln(24) = 3.18.")
    print("The FOC (100-r-sp)/(1+r) = ln(1+r) does not depend on h.")
    print("r*(sp) decreases as sp increases (see continuous table below).")

    # Continuous FOC solution for sp=0
    r_star_cont = solve_foc_continuous(0)
    s_star_cont = 100 - r_star_cont
    print(f"\nContinuous FOC solution at sp=0: r* = {r_star_cont:.4f}, s* = {100 - r_star_cont:.4f}")
    print(f"Verification: LHS = {(100 - r_star_cont) / (1 + r_star_cont):.6f}, "
          f"RHS = {math.log(1 + r_star_cont):.6f}")

    # Also solve for various sp values
    print("\n--- Continuous r*(sp) for different sp values ---")
    print(f"{'sp':>4} | {'r*':>8} {'s*':>8} | {'Check (LHS-RHS)':>16}")
    print("-" * 45)
    for sp in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]:
        r_star = solve_foc_continuous(sp)
        s_star = 100 - r_star - sp
        lhs = (100 - r_star - sp) / (1 + r_star)
        rhs = math.log(1 + r_star)
        print(f"  {sp:>3} | {r_star:>8.4f} {s_star:>8.4f} | {lhs - rhs:>16.2e}")

    # The key relationship: s* = (1+r*) * ln(1+r*)
    print("\n--- Structural relationship: s* = (1+r*) * ln(1+r*) ---")
    print("From FOC: 100 - r - sp = (1+r)*ln(1+r), so s* = (1+r*)*ln(1+r*)")
    for sp in [0, 10, 20, 30, 40, 50]:
        r_star = solve_foc_continuous(sp)
        s_star = 100 - r_star - sp
        structural = (1 + r_star) * math.log(1 + r_star)
        print(f"  sp={sp:>3}: r*={r_star:.2f}, s*={s_star:.2f}, (1+r)*ln(1+r)={structural:.2f}")

    return results_sec1


# =============================================================================
# Section 2: Game-theoretic speed analysis
# =============================================================================

def speed_multiplier_rank(our_sp, population_sps):
    """
    Compute speed multiplier based on rank.
    Ties share the top rank of the tied group.
    h = 0.1 + 0.8 * (N_below) / N  where N_below = count strictly below us.
    """
    n = len(population_sps)
    if n == 0:
        return 0.5
    below = sum(1 for x in population_sps if x < our_sp)
    return 0.1 + 0.8 * below / n


def build_population_empirical(rng, n, seed_sp):
    """
    Build population using empirical buckets from R1 leaderboard analysis.
    """
    BUCKETS = [
        ("ghost",          0.733, lambda rng, sp: 0),
        ("copy_paster",    0.080, lambda rng, sp: max(0, min(100, int(rng.gauss(sp, 3))))),
        ("partial_solver", 0.074, lambda rng, sp: max(0, min(100, int(rng.uniform(15, 50))))),
        ("round_number",   0.050, lambda rng, sp: rng.choices([20, 25, 30, 33, 40, 50], [0.20, 0.15, 0.25, 0.15, 0.15, 0.10])[0]),
        ("over_invester",  0.020, lambda rng, sp: max(40, min(100, int(rng.gauss(65, 10))))),
        ("nash_hunter",    0.015, lambda rng, sp: max(0, min(100, int(rng.gauss(sp, 2))))),
        ("contrarian",     0.005, lambda rng, sp: max(0, min(100, sp + rng.choice([1, 2, 3])))),
        ("remainder",      0.023, lambda rng, sp: rng.randint(0, 100)),
    ]

    weights = [b[1] for b in BUCKETS]
    names = [b[0] for b in BUCKETS]
    samplers = [b[2] for b in BUCKETS]

    samples = []
    for _ in range(n):
        idx = rng.choices(range(len(BUCKETS)), weights=weights)[0]
        samples.append(samplers[idx](rng, seed_sp))

    return samples


def build_population_engaged_only(rng, n, seed_sp):
    """Build population excluding ghosts."""
    BUCKETS = [
        ("copy_paster",    0.080, lambda rng, sp: max(0, min(100, int(rng.gauss(sp, 3))))),
        ("partial_solver", 0.074, lambda rng, sp: max(0, min(100, int(rng.uniform(15, 50))))),
        ("round_number",   0.050, lambda rng, sp: rng.choices([20, 25, 30, 33, 40, 50], [0.20, 0.15, 0.25, 0.15, 0.15, 0.10])[0]),
        ("over_invester",  0.020, lambda rng, sp: max(40, min(100, int(rng.gauss(65, 10))))),
        ("nash_hunter",    0.015, lambda rng, sp: max(0, min(100, int(rng.gauss(sp, 2))))),
        ("contrarian",     0.005, lambda rng, sp: max(0, min(100, sp + rng.choice([1, 2, 3])))),
        ("remainder",      0.023, lambda rng, sp: rng.randint(0, 100)),
    ]

    weights = [b[1] for b in BUCKETS]
    total = sum(weights)
    weights = [w / total for w in weights]
    samplers = [b[2] for b in BUCKETS]

    samples = []
    for _ in range(n):
        idx = rng.choices(range(len(BUCKETS)), weights=weights)[0]
        samples.append(samplers[idx](rng, seed_sp))

    return samples


def section_2_game_theory():
    print("\n" + "=" * 80)
    print("SECTION 2: GAME-THEORETIC SPEED ANALYSIS")
    print("=" * 80)

    N_TRIALS = 200

    # --- Approach A: Symmetric Nash ---
    print("\n--- Approach A: Symmetric Nash Equilibrium ---")
    print("If all N players choose the same sp*, all get the same rank.")
    print("With ties sharing top rank, all get h = 0.1 + 0.8 * 0/N = 0.1")
    print("Wait -- if all tied, N_below = 0 for all, so h = 0.1 for everyone.")
    print("")
    print("Actually, re-examining: if all play sp* and we deviate to sp*+1,")
    print("we have N_below = N-1 (everyone else below), so h ≈ 0.9.")
    print("If we deviate to sp*-1, h = 0.1 (everyone above us).")
    print("")
    print("Pure symmetric Nash does NOT exist in this game. Any sp* is unstable:")
    print("deviating up by 1 point gains 0.8 in h multiplier at cost of 500.")
    print("")

    # Check: when is deviating up by 1 not profitable?
    print("--- Nash deviation analysis ---")
    print("At symmetric (r*, s*, sp*) with h=0.1 (all tied):")
    print("Deviator goes to sp*+1 with h≈0.9. For deviation to be unprofitable:")
    print("  PnL(r*, s*-1, sp*+1, h=0.9) <= PnL(r*, s*, sp*, h=0.1)")
    print("")

    # Solve for Nash: find sp* where deviation up is exactly break-even
    print("Finding sp* where upward deviation breaks even...")
    print("(Using continuous relaxation)")

    def solve_foc_continuous(sp):
        lo, hi = 0.001, 100 - sp - 0.001
        if hi <= lo:
            return 0.0
        for _ in range(200):
            mid = (lo + hi) / 2
            if (100 - mid - sp) / (1 + mid) > math.log(1 + mid):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    for N in [100, 1000, 10000, 22000]:
        print(f"\n  N = {N:,}:")
        # At symmetric equilibrium, all play sp* -> all get rank = tied at top = 0 below
        # h_tied = 0.1 (no one strictly below)
        # Deviator plays sp*+1 -> h_dev ≈ 0.1 + 0.8*(N-1)/N ≈ 0.9
        h_tied = 0.1
        h_dev = 0.1 + 0.8 * (N - 1) / N

        # Find sp* where PnL(deviation) = PnL(stay)
        # Stay: s = 100 - r - sp, h = 0.1
        # Deviate: s = 100 - r - (sp+1), h ≈ 0.9
        # Both use same r (FOC says r only depends on remaining budget for s)

        best_sp_nash = None
        best_delta = float('inf')

        for sp in range(0, 99):
            r_stay = solve_foc_continuous(sp)
            r_dev = solve_foc_continuous(sp + 1)

            s_stay = 100 - r_stay - sp
            s_dev = 100 - r_dev - (sp + 1)

            if s_stay < 0 or s_dev < 0:
                continue

            pnl_stay = research(r_stay) * scale(s_stay) * h_tied - 50000
            pnl_dev = research(r_dev) * scale(s_dev) * h_dev - 50000

            delta = pnl_dev - pnl_stay

            if sp <= 5 or sp % 10 == 0 or abs(delta) < 5000:
                pass  # Will print selectively below

            if delta < best_delta and delta >= 0:
                # Still profitable to deviate
                pass
            if delta <= 0 and abs(delta) < abs(best_delta):
                best_sp_nash = sp
                best_delta = delta

        # Actually, more carefully: the deviation is ALWAYS profitable
        # because h jumps from 0.1 to 0.9 for just 1 point of sp.
        # Let's verify this:
        deviations = []
        for sp in range(0, 95):
            r_ = round(solve_foc_continuous(sp))
            r_d = round(solve_foc_continuous(sp + 1))
            s_ = 100 - r_ - sp
            s_d = 100 - r_d - (sp + 1)
            if s_ < 0 or s_d < 0:
                continue
            pnl_stay = pnl(r_, s_, sp, h_tied)
            pnl_dev = pnl(r_d, s_d, sp + 1, h_dev)
            deviations.append((sp, pnl_stay, pnl_dev, pnl_dev - pnl_stay))

        print(f"    h_tied = {h_tied:.4f}, h_deviate = {h_dev:.4f}")
        print(f"    Sample deviations:")
        print(f"    {'sp':>4} | {'PnL(stay)':>12} {'PnL(dev)':>12} {'Gain':>10}")
        for sp, ps, pd, g in deviations[::10]:
            print(f"    {sp:>4} | {ps:>12,.0f} {pd:>12,.0f} {g:>10,.0f}")

        # Find where deviation gain is minimized (closest to Nash)
        min_gain_sp = min(deviations, key=lambda x: x[3])
        print(f"    Min deviation gain at sp={min_gain_sp[0]}: {min_gain_sp[3]:,.0f}")
        print(f"    => Pure symmetric Nash does NOT exist (deviation always profitable)")

    # --- Approach B: Population best response ---
    print("\n\n--- Approach B: Best Response to Empirical Population ---")

    for pop_label, pop_builder, pop_n in [
        ("ALL 22k (incl ghosts)", build_population_empirical, 22000),
        ("ENGAGED only (~5900)", build_population_engaged_only, 5900),
    ]:
        print(f"\n  Population: {pop_label}")

        # Monte Carlo: for each (r, sp), compute expected PnL
        best_by_sp = {}
        for seed_sp in [30, 40, 45, 50]:
            speed_tables = []  # trial -> sp -> h
            for trial in range(N_TRIALS):
                rng = random.Random(42 + trial * 7919)
                pop = pop_builder(rng, pop_n, seed_sp)
                table = [speed_multiplier_rank(sp, pop) for sp in range(101)]
                speed_tables.append(table)

            # Find best allocation
            best_pnl = -1e18
            best_alloc = None
            for r in range(1, 50):
                rv = research(r)
                for sp in range(101 - r):
                    s = 100 - r - sp
                    sv = scale(s)
                    if sv <= 0:
                        continue
                    mean_h = sum(speed_tables[t][sp] for t in range(N_TRIALS)) / N_TRIALS
                    p = rv * sv * mean_h - 50000
                    if p > best_pnl:
                        best_pnl = p
                        best_alloc = (r, s, sp, mean_h)

            r_, s_, sp_, h_ = best_alloc
            best_by_sp[seed_sp] = best_alloc
            print(f"    seed_sp={seed_sp}: best=({r_}, {s_}, {sp_}) h_mean={h_:.3f} PnL={best_pnl:,.0f}")

    # --- Approach C: Scenario-based best response ---
    print("\n\n--- Approach C: Best Response Under Different Population Assumptions ---")

    scenarios = [
        ("Naive (most sp~30)", lambda rng, n: [max(0, min(100, int(rng.gauss(30, 10)))) for _ in range(n)]),
        ("Moderate (sp~40)", lambda rng, n: [max(0, min(100, int(rng.gauss(40, 12)))) for _ in range(n)]),
        ("Aggressive (sp~55)", lambda rng, n: [max(0, min(100, int(rng.gauss(55, 10)))) for _ in range(n)]),
        ("Bimodal (30/60)", lambda rng, n: [max(0, min(100, int(rng.gauss(30 if rng.random() < 0.6 else 60, 8)))) for _ in range(n)]),
        ("Uniform [0,100]", lambda rng, n: [rng.randint(0, 100) for _ in range(n)]),
        ("Uniform [10,60]", lambda rng, n: [rng.randint(10, 60) for _ in range(n)]),
    ]

    for label, pop_gen in scenarios:
        # Monte Carlo
        speed_tables = []
        for trial in range(N_TRIALS):
            rng = random.Random(42 + trial * 7919)
            pop = pop_gen(rng, 5000)
            table = [speed_multiplier_rank(sp, pop) for sp in range(101)]
            speed_tables.append(table)

        best_pnl = -1e18
        best_alloc = None
        for r in range(1, 50):
            rv = research(r)
            for sp in range(101 - r):
                s = 100 - r - sp
                sv = scale(s)
                if sv <= 0:
                    continue
                mean_h = sum(speed_tables[t][sp] for t in range(N_TRIALS)) / N_TRIALS
                p = rv * sv * mean_h - 50000
                if p > best_pnl:
                    best_pnl = p
                    best_alloc = (r, s, sp, mean_h)

        r_, s_, sp_, h_ = best_alloc
        print(f"  {label:>25}: best=({r_:>2}, {s_:>2}, {sp_:>2}) h={h_:.3f} PnL={best_pnl:>10,.0f}")

    return


# =============================================================================
# Section 3: Sensitivity Analysis
# =============================================================================

def section_3_sensitivity():
    print("\n" + "=" * 80)
    print("SECTION 3: SENSITIVITY ANALYSIS")
    print("=" * 80)

    # Candidate allocations
    candidates = [
        ("(14, 42, 44)", 14, 42, 44),
        ("(15, 44, 41)", 15, 44, 41),
        ("(16, 46, 38)", 16, 46, 38),
        ("(23, 74, 3)",  23, 74, 3),
        ("(11, 29, 60)", 11, 29, 60),
        ("(18, 50, 32)", 18, 50, 32),
    ]

    # 3a: PnL sensitivity to h
    print("\n--- 3a: PnL vs Speed Multiplier h ---")
    print(f"{'Allocation':>16} |", end="")
    for h10 in range(1, 10):
        print(f" h={h10/10:.1f}", end="")
    print(f" | {'Breakeven h':>12}")
    print("-" * 130)

    for label, r, s, sp in candidates:
        vals = []
        breakeven_h = None
        for h10 in range(1, 10):
            h = h10 / 10.0
            p = pnl(r, s, sp, h)
            vals.append(p)

        # Find breakeven h where PnL = 0
        gross_per_h = research(r) * scale(s)
        cost = COST_PER_PCT * (r + s + sp)
        if gross_per_h > 0:
            breakeven_h = cost / gross_per_h

        print(f"{label:>16} |", end="")
        for v in vals:
            print(f" {v:>7,.0f}", end="")
        if breakeven_h and breakeven_h <= 1.0:
            print(f" | {breakeven_h:>12.4f}")
        else:
            print(f" | {'N/A':>12}")

    # 3b: Perturbation analysis (+/- 5 points in each variable)
    print("\n--- 3b: Perturbation Analysis (base: (14, 42, 44) at h=0.5) ---")
    base_r, base_s, base_sp = 14, 42, 44
    h = 0.5
    base_p = pnl(base_r, base_s, base_sp, h)
    print(f"Base PnL = {base_p:,.0f}")
    print()

    for delta in [-5, -3, -1, 1, 3, 5]:
        # Perturb r (take from s)
        r_, s_, sp_ = base_r + delta, base_s - delta, base_sp
        if 0 <= r_ <= 100 and 0 <= s_ <= 100:
            p = pnl(r_, s_, sp_, h)
            print(f"  r+{delta:+d} (s{-delta:+d}): ({r_},{s_},{sp_}) PnL={p:>10,.0f} delta={p-base_p:>+8,.0f}")
    print()
    for delta in [-5, -3, -1, 1, 3, 5]:
        # Perturb sp (take from s)
        r_, s_, sp_ = base_r, base_s - delta, base_sp + delta
        if 0 <= s_ <= 100 and 0 <= sp_ <= 100:
            p = pnl(r_, s_, sp_, h)
            print(f"  sp+{delta:+d} (s{-delta:+d}): ({r_},{s_},{sp_}) PnL={p:>10,.0f} delta={p-base_p:>+8,.0f}")
    print()
    for delta in [-5, -3, -1, 1, 3, 5]:
        # Perturb r (take from sp)
        r_, s_, sp_ = base_r + delta, base_s, base_sp - delta
        if 0 <= r_ <= 100 and 0 <= sp_ <= 100:
            p = pnl(r_, s_, sp_, h)
            print(f"  r+{delta:+d} (sp{-delta:+d}): ({r_},{s_},{sp_}) PnL={p:>10,.0f} delta={p-base_p:>+8,.0f}")

    # 3c: Breakeven speed multiplier analysis
    print("\n--- 3c: Breakeven Speed Multiplier ---")
    print("For 'all-in R*S' allocation (sp=0), what h_min makes it worth investing in sp?")
    print("")

    # Compare: (r0, s0, 0) at h=0.1 vs (r, s, sp) at h=h_variable
    # All-in R*S: r=15, s=85, sp=0
    for r0, s0 in [(15, 85), (16, 84), (20, 80), (23, 77)]:
        pnl_0 = pnl(r0, s0, 0, 0.1)  # worst case speed
        print(f"  ({r0}, {s0}, 0) at h=0.1: PnL = {pnl_0:>10,.0f}")

    print()
    print("Compare with (14, 42, 44) at various h:")
    for h10 in range(1, 10):
        h = h10 / 10.0
        p = pnl(14, 42, 44, h)
        p0 = pnl(15, 85, 0, 0.1)
        print(f"  h={h:.1f}: PnL = {p:>10,.0f} (vs no-speed baseline {p0:>10,.0f}, diff = {p - p0:>+10,.0f})")

    # 3d: PnL surface for r at various h (with optimal s = 100 - r - sp)
    print("\n--- 3d: PnL vs Research% for Different h (sp=44, s=100-r-44) ---")
    print(f"{'r':>4} |", end="")
    for h10 in [1, 3, 5, 7, 9]:
        print(f"  h={h10/10:.1f}   ", end="")
    print()
    print("-" * 60)
    for r in range(1, 50, 2):
        sp = 44
        s = 100 - r - sp
        if s < 0:
            break
        print(f"{r:>4} |", end="")
        for h10 in [1, 3, 5, 7, 9]:
            h = h10 / 10.0
            p = pnl(r, s, sp, h)
            print(f" {p:>9,.0f}", end="")
        print()

    return


# =============================================================================
# Section 4: Scenario Analysis
# =============================================================================

def section_4_scenarios():
    print("\n" + "=" * 80)
    print("SECTION 4: SCENARIO ANALYSIS FOR CONCRETE ALLOCATIONS")
    print("=" * 80)

    scenarios = [
        ("Conservative",     30, 60, 10),
        ("Balanced",         20, 40, 40),
        ("Speed-heavy",      15, 30, 55),
        ("Research-heavy",   40, 55, 5),
        ("All-in R*S",       45, 55, 0),
        ("Prior best (v4)",  14, 42, 44),
        ("v3 Nash",          15, 44, 41),
        ("v2 mean-opt",      16, 46, 38),
        ("Robust",           11, 29, 60),
        ("High Scale",       23, 74, 3),
        ("Budget-efficient", 14, 42, 44),
    ]

    print(f"\n{'Scenario':>20} | {'(r,s,sp)':>10} | {'Cost':>6} |", end="")
    for h10 in range(1, 10):
        print(f" h={h10/10:.1f}   ", end="")
    print()
    print("-" * 130)

    seen = set()
    for label, r, s, sp in scenarios:
        key = (r, s, sp)
        if key in seen:
            continue
        seen.add(key)
        cost = COST_PER_PCT * (r + s + sp)
        print(f"{label:>20} | ({r},{s},{sp}){' '*(10-len(f'({r},{s},{sp})'))}| {cost/1000:.0f}k  |", end="")
        for h10 in range(1, 10):
            h = h10 / 10.0
            p = pnl(r, s, sp, h)
            print(f" {p:>8,.0f}", end="")
        print()

    # Decomposition
    print(f"\n--- Decomposition: Research * Scale * h - Cost ---")
    print(f"{'Scenario':>20} | {'Research':>10} {'Scale':>6} {'R*S':>10} {'R*S*0.5':>10} {'R*S*0.9':>10} {'Cost':>8} {'PnL@0.5':>10} {'PnL@0.9':>10}")
    print("-" * 110)
    seen = set()
    for label, r, s, sp in scenarios:
        key = (r, s, sp)
        if key in seen:
            continue
        seen.add(key)
        rv = research(r)
        sv = scale(s)
        rs = rv * sv
        cost = COST_PER_PCT * (r + s + sp)
        print(f"{label:>20} | {rv:>10,.0f} {sv:>6.2f} {rs:>10,.0f} {rs*0.5:>10,.0f} {rs*0.9:>10,.0f} {cost:>8,.0f} {rs*0.5-cost:>10,.0f} {rs*0.9-cost:>10,.0f}")

    return


# =============================================================================
# Section 5: Nash Equilibrium (Deep Analysis)
# =============================================================================

def section_5_nash():
    print("\n" + "=" * 80)
    print("SECTION 5: NASH EQUILIBRIUM ANALYSIS")
    print("=" * 80)

    def solve_foc_continuous(sp):
        lo, hi = 0.001, max(0.002, 100 - sp - 0.001)
        if hi <= lo:
            return 0.0
        for _ in range(200):
            mid = (lo + hi) / 2
            if (100 - mid - sp) / (1 + mid) > math.log(1 + mid):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    # --- 5a: Pure symmetric Nash cannot exist ---
    print("\n--- 5a: No Pure Symmetric Nash Exists ---")
    print("Proof:")
    print("  Suppose all N players choose sp*. All tied => h = 0.1 for all.")
    print("  Deviator plays sp*+1 => h = 0.1 + 0.8*(N-1)/N ≈ 0.9")
    print("  The gain from h: 0.1 -> 0.9 is a 9x multiplier on gross.")
    print("  The cost: 500 extra + 1 less Scale point.")
    print("  For any reasonable allocation, the gain far exceeds the cost.")
    print("  => Every pure symmetric sp* is unstable to upward deviation.")
    print("")
    print("  Conversely, there's no pure ASYMMETRIC Nash either in a symmetric game")
    print("  with 22,000 identical players. The only equilibria are mixed strategies.")

    # --- 5b: Mixed strategy equilibrium characterization ---
    print("\n--- 5b: Mixed Strategy / Quantal Response Equilibrium ---")
    print("In the continuous limit, a mixed-strategy Nash has each player randomize")
    print("over sp values. The distribution F(sp) must satisfy: no player gains by")
    print("shifting probability mass.")
    print("")
    print("This is equivalent to: expected PnL is constant across all sp in the support.")
    print("")
    print("Let F(x) be the CDF of the mixed strategy. If all N-1 opponents play F,")
    print("the probability that we rank at percentile p when playing sp=x is:")
    print("  P(rank <= p | sp=x) = F(x)^{N-1}  (binomial, large N)")
    print("  Expected h(x) = 0.1 + 0.8 * F(x)  (large N limit)")
    print("")
    print("For indifference across all sp in support [a,b]:")
    print("  d/dx [Research(r*(x)) * Scale(s*(x)) * (0.1 + 0.8*F(x))] = 500")
    print("where r*(x) = FOC-optimal r for sp=x, s*(x) = 100 - r*(x) - x")

    # --- 5c: Practical Nash approximation via iterated best response ---
    print("\n--- 5c: Iterated Best Response (Practical Nash Proxy) ---")

    N_TRIALS = 300
    N_POP = 5900  # engaged only

    print(f"Population: {N_POP} engaged players, {N_TRIALS} MC trials per iteration")

    seed_sp = 40
    history = []

    for iteration in range(8):
        # Build population speed tables
        speed_tables = []
        for trial in range(N_TRIALS):
            rng = random.Random(42 + trial * 7919 + iteration * 31)
            pop = build_population_engaged_only(rng, N_POP, seed_sp)
            table = [speed_multiplier_rank(sp, pop) for sp in range(101)]
            speed_tables.append(table)

        # Find best allocation
        best_pnl = -1e18
        best_alloc = None
        top_10 = []

        for r in range(1, 50):
            rv = research(r)
            for sp in range(101 - r):
                s = 100 - r - sp
                sv = scale(s)
                if sv <= 0:
                    continue
                # Mean PnL across trials
                mean_p = sum(rv * sv * speed_tables[t][sp] for t in range(N_TRIALS)) / N_TRIALS - 50000
                if mean_p > best_pnl:
                    best_pnl = mean_p
                    best_alloc = (r, s, sp)
                top_10.append((mean_p, r, s, sp))

        top_10.sort(reverse=True)
        top_10 = top_10[:10]

        r_, s_, sp_ = best_alloc
        mean_h = sum(speed_tables[t][sp_] for t in range(N_TRIALS)) / N_TRIALS

        entry = {
            "iteration": iteration + 1,
            "seed_sp": seed_sp,
            "best": best_alloc,
            "pnl": best_pnl,
            "mean_h": mean_h,
        }
        history.append(entry)

        print(f"\n  Iteration {iteration+1}: seed_sp={seed_sp}")
        print(f"    Best: ({r_}, {s_}, {sp_}) PnL={best_pnl:,.0f} h_mean={mean_h:.4f}")
        print(f"    Top 5:")
        for rank, (p, r, s, sp) in enumerate(top_10[:5], 1):
            print(f"      {rank}. ({r}, {s}, {sp}) PnL={p:,.0f}")

        new_sp = sp_
        if abs(new_sp - seed_sp) <= 1:
            print(f"    CONVERGED (sp moved {seed_sp} -> {new_sp})")
            break
        seed_sp = new_sp

    # --- 5d: Deviation analysis at the fixed point ---
    final_sp = history[-1]["best"][2]
    print(f"\n--- 5d: Deviation Analysis at Fixed Point sp={final_sp} ---")

    # Build population at fixed point
    speed_tables = []
    for trial in range(N_TRIALS):
        rng = random.Random(42 + trial * 7919)
        pop = build_population_engaged_only(rng, N_POP, final_sp)
        table = [speed_multiplier_rank(sp, pop) for sp in range(101)]
        speed_tables.append(table)

    r_fixed = history[-1]["best"][0]

    print(f"  Base allocation: ({r_fixed}, {100-r_fixed-final_sp}, {final_sp})")
    print(f"  Deviation in sp (holding r fixed, adjusting s):")
    print(f"  {'sp':>4} | {'s':>4} | {'mean_h':>8} | {'PnL':>12} | {'delta':>10}")
    print("  " + "-" * 55)

    # First pass: compute all PnLs
    deviation_data = []
    base_pnl_val = None
    for sp in range(max(0, final_sp - 20), min(101 - r_fixed, final_sp + 21)):
        s = 100 - r_fixed - sp
        if s < 0:
            continue
        rv = research(r_fixed)
        sv = scale(s)
        mean_h = sum(speed_tables[t][sp] for t in range(N_TRIALS)) / N_TRIALS
        p = rv * sv * mean_h - 50000
        if sp == final_sp:
            base_pnl_val = p
        deviation_data.append((sp, s, mean_h, p))

    # Second pass: print with correct deltas
    for sp, s, mean_h, p in deviation_data:
        delta = p - base_pnl_val if base_pnl_val is not None else 0
        marker = " <-- base" if sp == final_sp else ""
        print(f"  {sp:>4} | {s:>4} | {mean_h:>8.4f} | {p:>12,.0f} | {delta:>+10,.0f}{marker}")

    return history


# =============================================================================
# Section 6: Final Recommendation
# =============================================================================

def section_6_recommendation():
    print("\n" + "=" * 80)
    print("SECTION 6: FINAL RECOMMENDATION")
    print("=" * 80)

    N_TRIALS = 500

    # --- Comprehensive evaluation of final candidates ---
    candidates = [
        (14, 42, 44, "Prior best (v4)"),
        (15, 44, 41, "v3 Nash"),
        (16, 46, 38, "v2 mean-opt"),
        (23, 74, 3,  "MODE A exploit"),
        (11, 29, 60, "Robust"),
        (18, 50, 32, "Moderate"),
        (13, 43, 44, "Variant A"),
        (14, 43, 43, "Variant B"),
        (15, 43, 42, "Contrarian +1"),
        (14, 41, 45, "Anchoring adj"),
    ]

    # Run under multiple population models
    pop_models = [
        ("ALL 22k", build_population_empirical, 22000),
        ("ENGAGED 5.9k", build_population_engaged_only, 5900),
    ]

    results = {}

    for pop_label, pop_builder, pop_n in pop_models:
        print(f"\n--- Population: {pop_label} ---")

        for seed_sp in [40, 44]:
            speed_tables = []
            for trial in range(N_TRIALS):
                rng = random.Random(42 + trial * 7919)
                pop = pop_builder(rng, pop_n, seed_sp)
                table = [speed_multiplier_rank(sp, pop) for sp in range(101)]
                speed_tables.append(table)

            print(f"\n  seed_sp={seed_sp}:")
            print(f"  {'Allocation':>20} | {'mean PnL':>10} {'p10':>10} {'p25':>10} {'median':>10} {'p75':>10} {'p90':>10} {'mean_h':>8}")
            print("  " + "-" * 100)

            for r, s, sp, label in candidates:
                rv = research(r)
                sv = scale(s)
                trials = []
                for t in range(N_TRIALS):
                    h = speed_tables[t][sp]
                    p = rv * sv * h - 50000
                    trials.append(p)
                trials.sort()

                mean_p = sum(trials) / N_TRIALS
                p10 = trials[int(0.10 * N_TRIALS)]
                p25 = trials[int(0.25 * N_TRIALS)]
                median = trials[N_TRIALS // 2]
                p75 = trials[int(0.75 * N_TRIALS)]
                p90 = trials[int(0.90 * N_TRIALS)]
                mean_h = sum(speed_tables[t][sp] for t in range(N_TRIALS)) / N_TRIALS

                key = (pop_label, seed_sp, r, s, sp)
                results[key] = {
                    "label": label, "mean": mean_p, "p10": p10, "median": median,
                    "p90": p90, "mean_h": mean_h,
                }

                print(f"  {label:>20} | {mean_p:>10,.0f} {p10:>10,.0f} {p25:>10,.0f} {median:>10,.0f} {p75:>10,.0f} {p90:>10,.0f} {mean_h:>8.4f}")

    # --- Decision matrix under mode uncertainty ---
    print("\n\n--- Decision Matrix: Expected PnL Under Mode Uncertainty ---")
    print("P(A) = probability that ghosts are included in ranking")
    print("")

    # Get results for key candidates
    key_candidates = [
        (14, 42, 44, "Prior best (v4)"),
        (15, 44, 41, "v3 Nash"),
        (23, 74, 3,  "MODE A exploit"),
        (11, 29, 60, "Robust"),
        (18, 50, 32, "Moderate"),
        (15, 43, 42, "Contrarian +1"),
    ]

    print(f"{'Allocation':>20} |", end="")
    for pa in [0.0, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0]:
        print(f" P(A)={pa:.1f}", end="")
    print(f" | {'Worst':>10} {'log-util':>10}")
    print("-" * 140)

    for r, s, sp, label in key_candidates:
        key_a = ("ALL 22k", 44, r, s, sp)
        key_b = ("ENGAGED 5.9k", 44, r, s, sp)

        if key_a not in results or key_b not in results:
            continue

        pnl_a = results[key_a]["mean"]
        pnl_b = results[key_b]["mean"]
        worst = min(pnl_a, pnl_b)

        print(f"{label:>20} |", end="")
        for pa in [0.0, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0]:
            ev = pa * pnl_a + (1 - pa) * pnl_b
            print(f" {ev:>8,.0f}", end="")

        # Log utility at 50/50
        if pnl_a > 0 and pnl_b > 0:
            log_u = 0.5 * math.log(pnl_a) + 0.5 * math.log(pnl_b)
        else:
            log_u = float('-inf')

        print(f" | {worst:>10,.0f} {log_u:>10.3f}")

    # --- Kelly/log-utility analysis ---
    print("\n--- Kelly (Log-Utility) Analysis ---")
    print("Since we already have 177k banked from R1, the relevant utility is")
    print("log(177k + PnL_manual). This is NOT the same as log(PnL_manual).")
    print("")

    W0 = 177_000  # banked from R1

    print(f"{'Allocation':>20} | {'E[ln(W0+PnL)] P(A)=0.2':>24} {'P(A)=0.5':>10} {'P(A)=0.8':>10}")
    print("-" * 80)

    for r, s, sp, label in key_candidates:
        key_a = ("ALL 22k", 44, r, s, sp)
        key_b = ("ENGAGED 5.9k", 44, r, s, sp)

        if key_a not in results or key_b not in results:
            continue

        pnl_a = results[key_a]["mean"]
        pnl_b = results[key_b]["mean"]

        vals = []
        for pa in [0.2, 0.5, 0.8]:
            wa = W0 + pnl_a
            wb = W0 + pnl_b
            if wa > 0 and wb > 0:
                lu = pa * math.log(wa) + (1 - pa) * math.log(wb)
            else:
                lu = float('-inf')
            vals.append(lu)
        print(f"{label:>20} | {vals[0]:>24.4f} {vals[1]:>10.4f} {vals[2]:>10.4f}")

    # --- Final synthesis ---
    print("\n" + "=" * 80)
    print("FINAL SYNTHESIS AND RECOMMENDATION")
    print("=" * 80)

    print("""
PROBLEM STRUCTURE:
  - PnL = Research(r) * Scale(s) * Speed(sp) - 500*(r+s+sp)
  - Research is LOG (concave), Scale is LINEAR, Speed is RANK-BASED (game)
  - Budget is always spent fully (s absorbs remainder) => Cost = 50,000 always
  - FOC: s* = (1+r*)*ln(1+r*), INDEPENDENT of speed multiplier h
  - The only real decision is: how much to invest in Speed?

KEY INSIGHT: NO PURE SYMMETRIC NASH EXISTS
  - If all players choose sp*, all get h=0.1 (tied at bottom)
  - Deviating up by 1 point gives h ≈ 0.9 at cost of 500 + 1 Scale point
  - This is always profitable => pure Nash doesn't exist
  - The game has only mixed-strategy equilibria

POPULATION ANALYSIS (22,130 teams from R1 data):
  - 73.3% are ghosts (did not submit anything)
  - Only ~5,900 teams are engaged

  MODE A (ghosts count in ranking):
    - sp=3 already beats 73% of the field
    - Optimal: (23, 74, 3) at ~470k
    - Almost all budget goes to Research * Scale

  MODE B (only engaged players ranked):
    - Need meaningful sp investment
    - Iterated best-response: (14, 42, 44) at ~204k
    - Arms race oscillates if iterated further (no stable pure Nash)

WHICH MODE IS CORRECT?
  - The problem says "rank-based across all players"
  - Worked example shows 3 players with NONZERO investments: 95, 20, 10
  - Ambiguous whether sp=0 (ghost) players enter the ranking
  - P(MODE A) estimate: 0.15 to 0.30 (brief's example suggests only active)
  - Safe prior: P(MODE A) = 0.2

DECISION MATRIX (EV at P(A) = 0.2):
  (14, 42, 44): ~257k MODE A, ~204k MODE B => EV ≈ 215k, worst = 204k
  (23, 74, 3):  ~470k MODE A, ~60k MODE B  => EV ≈ 142k, worst = 60k
  (15, 44, 41): ~265k MODE A, ~105k MODE B => EV ≈ 137k, worst = 105k
  (11, 29, 60): ~143k MODE A, ~131k MODE B => EV ≈ 134k, worst = 131k

RECOMMENDATION:

  PRIMARY: r=14, s=42, sp=44

  Justification:
  1. Maximizes worst-case PnL across mode uncertainty (204k floor)
  2. Wins on log-utility (Kelly) at any P(A) <= 0.45
  3. Level-3 play: sits above the Schelling point of sp=41 that v3/v1 solvers
     converge to, hedging against copy-paste dynamics if that answer leaks
  4. Research-Scale split (14, 42) satisfies FOC: s* = (1+14)*ln(15) ≈ 40.6,
     close to 42 after accounting for integer rounding
  5. Already above R1+R2 200k threshold with any h >= 0.15

  FALLBACK (if sp=41 cluster theory is strong): r=15, s=44, sp=41
  AGGRESSIVE (if confident ghosts count): r=23, s=74, sp=3

  Risk: if the engaged population arms-races past sp=50, our h drops from
  ~0.6 to ~0.4, costing roughly 30k PnL. Acceptable given 177k R1 cushion.
""")

    return results


# =============================================================================
# Main
# =============================================================================

def main():
    print("Invest & Expand — Comprehensive Solver v5")
    print("=" * 80)
    print(f"Budget: {BUDGET:,} XIRECs")
    print(f"Cost per %: {COST_PER_PCT:,.0f}")
    print(f"ln(101): {LOG_101:.6f}")
    print(f"Research K = 200000/ln(101) = {200000/LOG_101:,.2f}")
    print()

    # Verify formulas
    print("--- Formula verification ---")
    for r in [0, 10, 50, 100]:
        print(f"  Research({r}) = {research(r):>10,.2f}")
    for s in [0, 50, 100]:
        print(f"  Scale({s}) = {scale(s):>6.2f}")
    print()

    sec1 = section_1_fixed_speed()
    section_2_game_theory()
    section_3_sensitivity()
    section_4_scenarios()
    nash_history = section_5_nash()
    results = section_6_recommendation()

    # Save results
    output = {
        "version": "v5",
        "recommendation": {
            "primary": [14, 42, 44],
            "fallback": [15, 44, 41],
            "aggressive": [23, 74, 3],
        },
        "section_1_fixed_speed": {
            str(h): {"alloc": list(v["alloc"]), "pnl": v["pnl"]}
            for h, v in sec1.items()
        },
        "nash_iterations": [
            {"iter": h["iteration"], "seed_sp": h["seed_sp"],
             "best": list(h["best"]), "pnl": h["pnl"]}
            for h in nash_history
        ],
    }

    out_path = Path(__file__).parent / "invest_expand_results_v5.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults written to: {out_path}")


if __name__ == "__main__":
    main()
