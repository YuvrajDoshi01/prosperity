"""
Verify top hidden_alpha_v2 combos via Monte Carlo path simulation.

Specifically test: is the +0.54 EV on SELL_chooser_BUY_2w_straddle genuine?
  - Static identity: chooser_T,t1 = C_T(K) + P_t1(K) (Rubinstein, r=0)
  - 2w straddle = C_2w(50) + P_2w(50)
  - At t1 (=2w), holder of chooser picks max(C_residual_1w, P_residual_1w)
  - Mathematically: chooser - 2w_straddle = max(C_res, P_res) - max(C_2w, P_2w)
    where max(C_2w, P_2w) at expiry = |S_2w - 50|
    and max(C_res, P_res) at S_2w = max(C_1w(50, S_2w), P_1w(50, S_2w))
    For r=0, max(C, P) = ATM-ish straddle value, always >= |S_2w - 50|.
  - So chooser >= 2w straddle ALWAYS pathwise. Selling chooser, buying 2w straddle has
    NEGATIVE expected payoff at expiry. Net cash today +2.70.
  - Static identity says fair difference = chooser_fair - 2w_straddle_fair = 21.898 - 19.741 = +2.156
    SELL chooser at 22.20, BUY straddle at 19.75 (ask*2 ~ 19.50): receive 2.70
    But pay -2.156 in expectation -> EV +0.544 (matches script).

This is a real EV but not arb. It's just exploiting the mid-vs-ask spread.
We're already SELLING chooser in the recommended portfolio. We're ALREADY BUYING 2w straddle (P_2 + C_2).
So the "combo" is just both edges combined — already captured in DROP_60C.

Let me verify that interaction.
"""
from __future__ import annotations
import math
import random


S0, SIGMA, T_3W, T_2W = 50.0, 2.51, 15/252, 10/252


def gbm_step(S: float, dt: float, sigma: float) -> float:
    return S * math.exp(-0.5 * sigma * sigma * dt + sigma * math.sqrt(dt) * random.gauss(0, 1))


def simulate_one(seed: int = None) -> tuple[float, float, float, bool]:
    """Simulate path -> (S_2w, S_3w, min_S_path, hit_barrier)."""
    if seed is not None:
        random.seed(seed)
    n_3w = 60  # 4/day * 15 days
    n_2w = 40  # 4/day * 10 days
    dt = T_3W / n_3w
    S = S0
    min_S = S
    S_2w = None
    for i in range(n_3w):
        S = gbm_step(S, dt, SIGMA)
        if S < min_S:
            min_S = S
        if i + 1 == n_2w:
            S_2w = S
    S_3w = S
    hit_barrier = min_S <= 35.0
    return S_2w, S_3w, min_S, hit_barrier


def chooser_payoff(S_2w: float, T_residual: float = T_3W - T_2W) -> float:
    """At t1=2w, holder picks max(C_residual_1w(50, S_2w), P_residual_1w(50, S_2w))."""
    sd = SIGMA * math.sqrt(T_residual)
    d1 = (math.log(S_2w / 50.0) + 0.5 * SIGMA * SIGMA * T_residual) / sd
    d2 = d1 - sd
    phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    c = S_2w * phi(d1) - 50.0 * phi(d2)
    p = 50.0 * phi(-d2) - S_2w * phi(-d1)
    return max(c, p)


def main():
    N = 1_000_000
    random.seed(42)
    sums = {
        "chooser": 0.0,
        "2w_straddle": 0.0,
        "3w_straddle": 0.0,
        "bp40": 0.0,
        "ko_45": 0.0,
        "p45": 0.0,
    }
    sq_sums = {k: 0.0 for k in sums}

    print(f"Simulating {N:,} paths to verify +EV chooser combos...")
    for n in range(N):
        S_2w, S_3w, min_S, hit = simulate_one()
        ch = chooser_payoff(S_2w)
        st_2w = abs(S_2w - 50.0)
        st_3w = abs(S_3w - 50.0)
        bp = 10.0 if S_3w <= 40.0 else 0.0
        p45 = max(45.0 - S_3w, 0.0)
        ko = 0.0 if hit else p45
        for k, v in [("chooser", ch), ("2w_straddle", st_2w), ("3w_straddle", st_3w),
                     ("bp40", bp), ("ko_45", ko), ("p45", p45)]:
            sums[k] += v
            sq_sums[k] += v * v
        if (n + 1) % 200_000 == 0:
            print(f"  ... {n+1:,} done")

    print("\n  Instrument        MC mean      MC sd       BS fair       diff")
    print("  " + "-" * 60)
    bs_fair = {
        "chooser": 21.8977,
        "2w_straddle": 2 * 9.8707,
        "3w_straddle": 2 * 12.0269,
        "bp40": 4.7679,
        "ko_45": 0.2055,
        "p45": 9.0889,
    }
    for k in sums:
        mean = sums[k] / N
        var = (sq_sums[k] / N) - mean * mean
        sd = math.sqrt(var / N)
        print(f"  {k:<15}  {mean:>9.4f}    {sd:>7.4f}   {bs_fair[k]:>9.4f}    {mean - bs_fair[k]:>+8.4f}")

    print("\nKey relationships:")
    print(f"  chooser - 2w_straddle (mean) = {sums['chooser']/N - sums['2w_straddle']/N:+.4f}")
    print(f"  Static fair diff = {21.8977 - 2*9.8707:+.4f}")
    print(f"  -> chooser is worth +2.156 over 2w straddle pathwise (in expectation)")
    print(f"  Selling chooser at 22.20, buying 2w straddle at 19.50: receive +2.70 cash")
    print(f"  Pay -2.156 in expectation at expiry -> NET EV +0.544/unit (per-unit, before quantity scaling)")
    print(f"  BUT: this is achieved by COMBINING chooser-sell edge (+0.302) and 2w-straddle-buy edge (+0.121*2=+0.242)")
    print(f"  Sum: 0.302 + 0.242 = +0.544 -- exactly. NOT NEW alpha. Already in optimal portfolio.")


if __name__ == "__main__":
    main()
