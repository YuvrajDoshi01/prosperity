"""R4 Manual Challenge: Aether Crystal options solver.

Underlying: Aether Crystal (S_0 = 50, GBM, sigma_annual = 2.51, r = 0).
Time grid: 4 steps per trading day, 252 trading days/year.
Convention: "T+21 Solvenarian Days" = 21 calendar days = 15 trading days = 3 weeks.
            "T+14 Solvenarian Days" = 14 calendar days = 10 trading days = 2 weeks.

12 tradeable instruments (bid/ask/size from the manual UI):

  AETHER_CRYSTAL  spot       49.975 / 50.025  size 200
  AC_50_P  3w put  K=50      12.00  / 12.05   size 50
  AC_50_C  3w call K=50      12.00  / 12.05   size 50
  AC_35_P  3w put  K=35      4.33   / 4.35    size 50
  AC_40_P  3w put  K=40      6.50   / 6.55    size 50
  AC_45_P  3w put  K=45      9.05   / 9.10    size 50
  AC_60_C  3w call K=60      8.80   / 8.85    size 50
  AC_50_P_2 2w put K=50      9.70   / 9.75    size 50
  AC_50_C_2 2w call K=50     9.70   / 9.75    size 50
  AC_50_CO chooser K=50, T1=2w, T=3w   22.20 / 22.30   size 50
  AC_40_BP binary put K=40, payoff=10  5.00 / 5.10     size 50
  AC_45_KO knock-out put K=45, B=35    0.15 / 0.175    size 500

Score = average PnL across 100 simulations of underlying.
"""
import math
from statistics import NormalDist

# ── Parameters ────────────────────────────────────────────────────────────────

S0 = 50.0                 # spot underlying mid
SIGMA = 2.51              # annualized vol
R = 0.0                   # zero risk-neutral drift
TRADING_DAYS_YEAR = 252
STEPS_PER_DAY = 4
T_3W_DAYS = 15            # 3 weeks = 15 trading days
T_2W_DAYS = 10            # 2 weeks = 10 trading days

T_3W = T_3W_DAYS / TRADING_DAYS_YEAR
T_2W = T_2W_DAYS / TRADING_DAYS_YEAR
DT = 1.0 / (TRADING_DAYS_YEAR * STEPS_PER_DAY)
N_3W_STEPS = T_3W_DAYS * STEPS_PER_DAY     # 60 steps
N_2W_STEPS = T_2W_DAYS * STEPS_PER_DAY     # 40 steps

ND = NormalDist()


# ── Black-Scholes helpers ─────────────────────────────────────────────────────

def bs_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * ND.cdf(d1) - K * ND.cdf(d2)


def bs_put(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * ND.cdf(-d2) - S * ND.cdf(-d1)


def bs_binary_put(S, K, T, sigma, payoff=10.0):
    """Cash-or-nothing put: pays `payoff` if S_T < K."""
    if T <= 0 or sigma <= 0:
        return payoff if S < K else 0.0
    d2 = (math.log(S / K) - 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return payoff * ND.cdf(-d2)


def bs_chooser(S, K, T_choice, T_expiry, sigma):
    """Standard chooser with r=0:
       V(0) = C_T(S, K) + P_T_choice(S, K)
       (when r=0 we have C-P = S-K so max(C,P) = C + max(0, K-S).)"""
    return bs_call(S, K, T_expiry, sigma) + bs_put(S, K, T_choice, sigma)


def bs_down_and_out_put(S, K, B, T, sigma):
    """Down-and-out put with continuous monitoring (r=0).
       Reiner-Rubinstein closed-form for K > B and S > B."""
    if T <= 0 or sigma <= 0:
        # Only pays if barrier never hit and S_T < K. Approximate at limit.
        if S <= B:
            return 0.0
        return max(K - S, 0.0)

    sqT = sigma * math.sqrt(T)
    mu = -0.5  # (r - sigma^2/2)/sigma^2 with r=0

    x1 = math.log(S / B) / sqT + (mu + 1) * sqT
    y = math.log(B * B / (S * K)) / sqT + (mu + 1) * sqT
    y1 = math.log(B / S) / sqT + (mu + 1) * sqT

    pow1 = (B / S) ** (2 * (mu + 1))   # = B/S when r=0
    pow2 = (B / S) ** (2 * mu)         # = S/B when r=0

    # P_DI for K > B (regular case)
    p_di = (
        -S * ND.cdf(-x1)
        + K * ND.cdf(-x1 + sqT)
        + S * pow1 * (ND.cdf(y) - ND.cdf(y1))
        - K * pow2 * (ND.cdf(y - sqT) - ND.cdf(y1 - sqT))
    )

    p_bs = bs_put(S, K, T, sigma)
    return p_bs - p_di


# ── Monte Carlo verification ──────────────────────────────────────────────────

def mc_paths(n_paths, n_steps, dt, sigma, S_init, seed=42):
    """Generate GBM paths with r=0, fixed sigma. Returns list of (S_T, min_S, S_at_T_choice) tuples.
       For chooser/KO we need the path; otherwise just S_T."""
    import random
    rng = random.Random(seed)
    paths = []
    drift_step = -0.5 * sigma * sigma * dt
    vol_step = sigma * math.sqrt(dt)
    for _ in range(n_paths):
        S = S_init
        min_S = S
        S_at_choice = None  # filled by caller as needed
        for k in range(n_steps):
            z = rng.gauss(0.0, 1.0)
            S = S * math.exp(drift_step + vol_step * z)
            if S < min_S:
                min_S = S
        paths.append((S, min_S, None))
    return paths


def mc_with_intermediate(n_paths, n_steps_total, n_steps_choice, dt, sigma, S_init, seed=42):
    """Generate paths and capture S at the intermediate choice timestep."""
    import random
    rng = random.Random(seed)
    paths = []
    drift_step = -0.5 * sigma * sigma * dt
    vol_step = sigma * math.sqrt(dt)
    for _ in range(n_paths):
        S = S_init
        min_S = S
        S_at_choice = None
        for k in range(n_steps_total):
            z = rng.gauss(0.0, 1.0)
            S = S * math.exp(drift_step + vol_step * z)
            if S < min_S:
                min_S = S
            if k + 1 == n_steps_choice:
                S_at_choice = S
        paths.append((S, min_S, S_at_choice))
    return paths


def verify_with_mc(n_paths=100_000):
    """Run MC and compare to closed-form for each instrument."""
    print(f"\n--- Monte Carlo verification ({n_paths:,} paths) ---")
    paths_3w = mc_paths(n_paths, N_3W_STEPS, DT, SIGMA, S0, seed=123)
    paths_2w = mc_paths(n_paths, N_2W_STEPS, DT, SIGMA, S0, seed=456)
    paths_chooser = mc_with_intermediate(
        n_paths, N_3W_STEPS, N_2W_STEPS, DT, SIGMA, S0, seed=789
    )

    # Helper for MC pricing
    def mc_call(paths, K):
        return sum(max(s - K, 0.0) for s, _, _ in paths) / len(paths)

    def mc_put(paths, K):
        return sum(max(K - s, 0.0) for s, _, _ in paths) / len(paths)

    def mc_binary_put(paths, K, payoff=10.0):
        return sum(payoff if s < K else 0.0 for s, _, _ in paths) / len(paths)

    def mc_ko_put(paths, K, B):
        # Down-and-out: pays max(K-S_T, 0) if min_S > B
        return sum(
            max(K - s, 0.0) if min_s > B else 0.0
            for s, min_s, _ in paths
        ) / len(paths)

    def mc_chooser(paths, K, sigma_remaining, dt, n_remaining):
        # At choice time, holder picks max(C_remaining, P_remaining)
        # = max value, which is then realized at expiry
        # MC this directly: payoff = max(C(S_choice), P(S_choice)) value at choice -> but
        # actually expected payoff at expiry = expected value at choice (martingale, r=0)
        T_remaining = n_remaining * dt
        out = 0.0
        for s_T, _, s_choice in paths:
            if s_choice is None:
                continue
            c = bs_call(s_choice, K, T_remaining, SIGMA)
            p = bs_put(s_choice, K, T_remaining, SIGMA)
            out += max(c, p)
        return out / len(paths)

    print(f"\n  3-week vanilla (T = {T_3W_DAYS} trading days):")
    for K in [35, 40, 45, 50, 60]:
        bs_c = bs_call(S0, K, T_3W, SIGMA)
        bs_p = bs_put(S0, K, T_3W, SIGMA)
        mc_c = mc_call(paths_3w, K)
        mc_p = mc_put(paths_3w, K)
        print(f"    K={K:3d}: BS C={bs_c:7.3f}  MC C={mc_c:7.3f} (diff {mc_c-bs_c:+.3f})"
              f"  |  BS P={bs_p:7.3f}  MC P={mc_p:7.3f} (diff {mc_p-bs_p:+.3f})")

    print(f"\n  2-week vanilla (T = {T_2W_DAYS} trading days):")
    for K in [50]:
        bs_c = bs_call(S0, K, T_2W, SIGMA)
        bs_p = bs_put(S0, K, T_2W, SIGMA)
        mc_c = mc_call(paths_2w, K)
        mc_p = mc_put(paths_2w, K)
        print(f"    K={K:3d}: BS C={bs_c:7.3f}  MC C={mc_c:7.3f} (diff {mc_c-bs_c:+.3f})"
              f"  |  BS P={bs_p:7.3f}  MC P={mc_p:7.3f} (diff {mc_p-bs_p:+.3f})")

    print(f"\n  Binary put K=40, T=3w, payoff=10:")
    bs_bp = bs_binary_put(S0, 40, T_3W, SIGMA, 10.0)
    mc_bp = mc_binary_put(paths_3w, 40, 10.0)
    print(f"    BS={bs_bp:.4f}  MC={mc_bp:.4f}  (diff {mc_bp-bs_bp:+.4f})")

    print(f"\n  Down-and-out put K=45, B=35, T=3w (continuous monitoring formula):")
    bs_ko = bs_down_and_out_put(S0, 45, 35, T_3W, SIGMA)
    mc_ko = mc_ko_put(paths_3w, 45, 35)
    print(f"    BS_continuous={bs_ko:.4f}  MC_discrete({STEPS_PER_DAY}/day, {N_3W_STEPS} steps)={mc_ko:.4f}")
    print(f"    Discrete monitoring should give HIGHER value (barrier hit less often).")

    print(f"\n  Chooser K=50, T_choice=2w, T_expiry=3w:")
    bs_ch = bs_chooser(S0, 50, T_2W, T_3W, SIGMA)
    mc_ch = mc_chooser(paths_chooser, 50, SIGMA, DT, N_3W_STEPS - N_2W_STEPS)
    print(f"    BS={bs_ch:.4f}  MC={mc_ch:.4f}  (diff {mc_ch-bs_ch:+.4f})")


# ── Solver ────────────────────────────────────────────────────────────────────

def solve():
    print("=" * 80)
    print("R4 MANUAL CHALLENGE: Aether Crystal options solver")
    print("=" * 80)
    print(f"\nUnderlying: S0 = {S0}, sigma = {SIGMA*100:.1f}% annual, r = {R}")
    print(f"Time grid: {STEPS_PER_DAY} steps/day, {TRADING_DAYS_YEAR} trading days/year")
    print(f"3 weeks = {T_3W_DAYS} trading days = T = {T_3W:.5f}")
    print(f"2 weeks = {T_2W_DAYS} trading days = T = {T_2W:.5f}")
    print(f"sigma * sqrt(T_3w) = {SIGMA * math.sqrt(T_3W):.4f}")
    print(f"sigma * sqrt(T_2w) = {SIGMA * math.sqrt(T_2W):.4f}")

    # Compute fair values (use MC for the KO put because discrete > continuous)
    print("\n" + "=" * 80)
    print("FAIR VALUES (Black-Scholes, r=0, sigma=2.51)")
    print("=" * 80)

    # Vanilla
    fv = {
        "AC_50_P":   bs_put(S0, 50, T_3W, SIGMA),
        "AC_50_C":   bs_call(S0, 50, T_3W, SIGMA),
        "AC_35_P":   bs_put(S0, 35, T_3W, SIGMA),
        "AC_40_P":   bs_put(S0, 40, T_3W, SIGMA),
        "AC_45_P":   bs_put(S0, 45, T_3W, SIGMA),
        "AC_60_C":   bs_call(S0, 60, T_3W, SIGMA),
        "AC_50_P_2": bs_put(S0, 50, T_2W, SIGMA),
        "AC_50_C_2": bs_call(S0, 50, T_2W, SIGMA),
        "AC_50_CO":  bs_chooser(S0, 50, T_2W, T_3W, SIGMA),
        "AC_40_BP":  bs_binary_put(S0, 40, T_3W, SIGMA, 10.0),
    }

    # KO put: closed-form (continuous), then MC adjustment for discrete monitoring
    ko_continuous = bs_down_and_out_put(S0, 45, 35, T_3W, SIGMA)
    # Run MC to get discrete-monitoring value
    paths_ko = mc_paths(200_000, N_3W_STEPS, DT, SIGMA, S0, seed=999)
    ko_discrete = sum(
        max(45 - s, 0.0) if min_s > 35 else 0.0
        for s, min_s, _ in paths_ko
    ) / len(paths_ko)
    fv["AC_45_KO"] = ko_discrete  # use discrete value for fair price

    # Quotes from manual UI
    quotes = {
        "AETHER":    (49.975, 50.025, 200),
        "AC_50_P":   (12.00, 12.05, 50),
        "AC_50_C":   (12.00, 12.05, 50),
        "AC_35_P":   (4.33,  4.35,  50),
        "AC_40_P":   (6.50,  6.55,  50),
        "AC_45_P":   (9.05,  9.10,  50),
        "AC_60_C":   (8.80,  8.85,  50),
        "AC_50_P_2": (9.70,  9.75,  50),
        "AC_50_C_2": (9.70,  9.75,  50),
        "AC_50_CO":  (22.20, 22.30, 50),
        "AC_40_BP":  (5.00,  5.10,  50),
        "AC_45_KO":  (0.15,  0.175, 500),
    }

    print(f"\n  Underlying: spot mid = {S0:.3f} (zero edge)")
    print(f"  KO put: continuous formula = {ko_continuous:.4f}, discrete MC = {ko_discrete:.4f}")
    print(f"\n  Per-instrument fair value:")
    for sym, val in fv.items():
        print(f"    {sym:12s}: {val:8.4f}")

    # ── Decision ────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("OPTIMAL POSITIONS")
    print("=" * 80)

    print(f"\n{'Instrument':<12} {'Bid':>8} {'Ask':>8} {'Fair':>8} {'BuyEdge':>8} {'SellEdge':>8} "
          f"{'Action':<6} {'Vol':>6} {'EV':>10}")
    print("-" * 90)

    decisions = []
    total_ev = 0.0
    for sym, (bid, ask, size) in quotes.items():
        if sym == "AETHER":
            fair = S0
        else:
            fair = fv[sym]
        buy_edge = fair - ask
        sell_edge = bid - fair
        if buy_edge > sell_edge and buy_edge > 0:
            action, vol, ev = "BUY", size, buy_edge * size
        elif sell_edge > 0:
            action, vol, ev = "SELL", size, sell_edge * size
        else:
            action, vol, ev = "SKIP", 0, 0.0
        decisions.append((sym, action, vol, ev))
        total_ev += ev
        print(f"{sym:<12} {bid:>8.3f} {ask:>8.3f} {fair:>8.4f} {buy_edge:>+8.4f} {sell_edge:>+8.4f} "
              f"{action:<6} {vol:>6d} {ev:>+10.3f}")

    print("-" * 90)
    print(f"{'TOTAL EV (per unit, no contract multiplier)':<70} {total_ev:>+18.3f}")

    # Risk analysis: compute portfolio variance under MC
    print("\n" + "=" * 80)
    print("MC RISK ANALYSIS: variance of portfolio PnL across simulations")
    print("=" * 80)

    n_sim = 100  # IMC scoring uses 100 sims
    n_paths_each = 1  # one path per simulation
    sim_pnls = []
    import random
    rng = random.Random(42)
    for sim_idx in range(n_sim):
        # Generate one path (3w horizon, 60 steps)
        S = S0
        min_S = S
        S_at_2w = None
        drift_step = -0.5 * SIGMA * SIGMA * DT
        vol_step = SIGMA * math.sqrt(DT)
        for k in range(N_3W_STEPS):
            z = rng.gauss(0.0, 1.0)
            S = S * math.exp(drift_step + vol_step * z)
            if S < min_S:
                min_S = S
            if k + 1 == N_2W_STEPS:
                S_at_2w = S
        S_T = S
        S_T_2w = S_at_2w  # for 2w options, S_at_2w is terminal

        # Compute PnL for each position
        pnl_sim = 0.0
        for sym, action, vol, _ in decisions:
            if vol == 0:
                continue
            bid, ask, _ = quotes[sym]
            if action == "BUY":
                cost = ask * vol
                payoff = _payoff(sym, S_T, S_T_2w, min_S) * vol
                pnl_sim += payoff - cost
            elif action == "SELL":
                proceeds = bid * vol
                payoff = _payoff(sym, S_T, S_T_2w, min_S) * vol
                pnl_sim += proceeds - payoff
        sim_pnls.append(pnl_sim)

    mean_pnl = sum(sim_pnls) / len(sim_pnls)
    var_pnl = sum((p - mean_pnl) ** 2 for p in sim_pnls) / (len(sim_pnls) - 1)
    sd_pnl = var_pnl ** 0.5
    se_mean = sd_pnl / (len(sim_pnls) ** 0.5)
    pct_pos = sum(1 for p in sim_pnls if p > 0) / len(sim_pnls) * 100

    print(f"\n  100-sim portfolio PnL:")
    print(f"    Mean   = {mean_pnl:+.3f} (theoretical EV = {total_ev:+.3f})")
    print(f"    SD     = {sd_pnl:.3f}")
    print(f"    SE/100 = {se_mean:.3f}")
    print(f"    Min    = {min(sim_pnls):+.3f}")
    print(f"    Max    = {max(sim_pnls):+.3f}")
    print(f"    P>0    = {pct_pos:.1f}% of sims")
    print(f"    95% CI on score = {mean_pnl - 1.96*se_mean:+.3f} to {mean_pnl + 1.96*se_mean:+.3f}")

    # Re-run with bigger N to estimate true score precision
    print(f"\n  Long-run mean (10,000 sims for low noise):")
    rng2 = random.Random(2024)
    long_pnls = []
    for sim_idx in range(10_000):
        S = S0
        min_S = S
        S_at_2w = None
        drift_step = -0.5 * SIGMA * SIGMA * DT
        vol_step = SIGMA * math.sqrt(DT)
        for k in range(N_3W_STEPS):
            z = rng2.gauss(0.0, 1.0)
            S = S * math.exp(drift_step + vol_step * z)
            if S < min_S:
                min_S = S
            if k + 1 == N_2W_STEPS:
                S_at_2w = S
        S_T = S
        S_T_2w = S_at_2w

        pnl_sim = 0.0
        for sym, action, vol, _ in decisions:
            if vol == 0:
                continue
            bid, ask, _ = quotes[sym]
            if action == "BUY":
                cost = ask * vol
                payoff = _payoff(sym, S_T, S_T_2w, min_S) * vol
                pnl_sim += payoff - cost
            elif action == "SELL":
                proceeds = bid * vol
                payoff = _payoff(sym, S_T, S_T_2w, min_S) * vol
                pnl_sim += proceeds - payoff
        long_pnls.append(pnl_sim)

    long_mean = sum(long_pnls) / len(long_pnls)
    long_sd = (sum((p - long_mean) ** 2 for p in long_pnls) / (len(long_pnls) - 1)) ** 0.5
    print(f"    Mean over 10k sims = {long_mean:+.3f}")
    print(f"    SE over 10k        = {long_sd / (len(long_pnls)**0.5):.3f}")
    print(f"    Implied 100-sim SE = {long_sd / 10:.3f}")


def _payoff(sym, S_T, S_T_2w, min_S):
    """Per-unit payoff at expiry for each instrument."""
    if sym == "AETHER":
        return S_T  # buy/sell at quote, value at expiry... actually for spot this is mark-to-end
    if sym == "AC_50_P":
        return max(50 - S_T, 0)
    if sym == "AC_50_C":
        return max(S_T - 50, 0)
    if sym == "AC_35_P":
        return max(35 - S_T, 0)
    if sym == "AC_40_P":
        return max(40 - S_T, 0)
    if sym == "AC_45_P":
        return max(45 - S_T, 0)
    if sym == "AC_60_C":
        return max(S_T - 60, 0)
    if sym == "AC_50_P_2":
        return max(50 - S_T_2w, 0) if S_T_2w is not None else 0
    if sym == "AC_50_C_2":
        return max(S_T_2w - 50, 0) if S_T_2w is not None else 0
    if sym == "AC_50_CO":
        # Chooser: at 2w, picks the side that's ITM. Payoff at 3w = chosen side
        if S_T_2w is None:
            return 0
        # Auto-choose at 2w based on intrinsic value at that time
        T_remaining = (N_3W_STEPS - N_2W_STEPS) * DT
        c_val = bs_call(S_T_2w, 50, T_remaining, SIGMA)
        p_val = bs_put(S_T_2w, 50, T_remaining, SIGMA)
        # Pick the side with higher BS value at 2w
        if c_val >= p_val:
            return max(S_T - 50, 0)
        else:
            return max(50 - S_T, 0)
    if sym == "AC_40_BP":
        return 10.0 if S_T < 40 else 0.0
    if sym == "AC_45_KO":
        if min_S <= 35:
            return 0.0
        return max(45 - S_T, 0)
    return 0.0


if __name__ == "__main__":
    solve()
    verify_with_mc(n_paths=200_000)
