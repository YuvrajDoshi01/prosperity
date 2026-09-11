"""manual_r3_deep.py — Deep game-theoretic analysis of the R3 two-bid auction.

Builds on manual_r3_solver.py:
  1. Level-k thinking ladder (L0 = uniform / round-numbers / UI default)
  2. Logit Quantal Response Equilibrium (QRE) over symmetric mixed strategies
  3. Replicator dynamics on a discrete (b1, b2) action set
  4. Closed-form FOC for the symmetric pure-strategy interior optimum
  5. Head-to-head EV comparison for (766,866), (771,871), (771,876)
     under endogenous mu drawn from QRE distribution
  6. Coordination / focal-point analysis (UI default, Schelling clusters)
"""
from __future__ import annotations
import math
import numpy as np
from itertools import product

SELL = 920
RESERVES = tuple(range(670, 925, 5))
NUM_R = len(RESERVES)
N_PLAYERS = 4021


def profit_one(b1: int, b2: int, r: int, mu: float) -> float:
    if r < b1:
        return SELL - b1
    if r < b2:
        if b2 > mu:
            return SELL - b2
        denom = SELL - b2
        if denom <= 0:
            return 0.0
        return (SELL - mu) ** 3 / (denom * denom)
    return 0.0


def EV(b1: int, b2: int, mu: float) -> float:
    return sum(profit_one(b1, b2, r, mu) for r in RESERVES) / NUM_R


# Restrict the action set to a sensible neighborhood to keep QRE/replicator tractable.
# b1 in [740, 790], b2 in [840, 900], step=1, with b1 <= b2-50 enforced loosely.
B1_RANGE = list(range(740, 791))
B2_RANGE = list(range(840, 901))
ACTIONS = [(b1, b2) for b1 in B1_RANGE for b2 in B2_RANGE if b2 - b1 >= 50]


def best_response_mu(mu: float, actions=ACTIONS) -> tuple[int, int, float]:
    best = (0, 0, -1.0)
    for b1, b2 in actions:
        ev = EV(b1, b2, mu)
        if ev > best[2]:
            best = (b1, b2, ev)
    return best


# ---------------------------------------------------------------------------
# (1) Level-k ladder
# ---------------------------------------------------------------------------
def level_k_ladder():
    print("\n" + "=" * 72)
    print("[1] Level-k thinking ladder")
    print("=" * 72)

    # L0 candidates: (a) uniform random over actions, (b) round-numbers (b2 multiple of 50),
    # (c) UI default (761, 856), (d) myopic naive: bid = max reserve = 920 (degenerate).
    # We'll use a mixture: 1/3 uniform-random, 1/3 round-number-ish, 1/3 UI default.

    def l0_mu():
        # uniform over (b1, b2) action set: mean b2
        unif_b2 = np.mean([b2 for _, b2 in ACTIONS])
        round_b2 = 850.0  # naive round-number focal
        ui_b2 = 856.0
        return (unif_b2 + round_b2 + ui_b2) / 3.0

    mu0 = l0_mu()
    print(f"  L0 implied mu = {mu0:.2f} (mixture: uniform / round-50 / UI default)")

    history = [(0, None, None, mu0)]
    mu = mu0
    for k in range(1, 9):
        b1, b2, ev = best_response_mu(mu)
        history.append((k, (b1, b2), ev, mu))
        new_mu = float(b2)
        print(f"  L{k}: BR(mu={mu:.2f}) = ({b1},{b2}), EV={ev:.3f}  ->  mu_{k+1} = {new_mu:.2f}")
        if k >= 2 and history[-1][1] == history[-2][1]:
            print(f"  [converged at L{k}]")
            break
        mu = new_mu
    return history


# ---------------------------------------------------------------------------
# (2) Logit Quantal Response Equilibrium
# ---------------------------------------------------------------------------
def qre(lam: float, max_iter: int = 200, tol: float = 1e-4):
    """Symmetric logit QRE: pi(a) ∝ exp(lam * EV(a, mu(pi))).
    With N=4021, mu is essentially deterministic given pi: mu = sum_a pi(a) * b2(a).
    Iterate until pi converges.
    """
    actions = ACTIONS
    n = len(actions)
    b2_vec = np.array([b2 for _, b2 in actions], dtype=float)
    pi = np.ones(n) / n
    for it in range(max_iter):
        mu = float(pi @ b2_vec)
        ev_vec = np.array([EV(b1, b2, mu) for b1, b2 in actions])
        # logit response
        x = lam * ev_vec
        x -= x.max()
        new_pi = np.exp(x)
        new_pi /= new_pi.sum()
        if np.max(np.abs(new_pi - pi)) < tol:
            pi = new_pi
            break
        # damp for stability
        pi = 0.5 * pi + 0.5 * new_pi
    mu = float(pi @ b2_vec)
    # implied mu distribution: variance of b2 across pi
    var_b2 = float(pi @ (b2_vec - mu) ** 2)
    sd_b2 = math.sqrt(var_b2)
    # mode action
    mode_idx = int(np.argmax(pi))
    return pi, mu, sd_b2, actions[mode_idx], it


# ---------------------------------------------------------------------------
# (3) Replicator dynamics
# ---------------------------------------------------------------------------
def replicator(steps: int = 500, eta: float = 0.05):
    actions = ACTIONS
    n = len(actions)
    b2_vec = np.array([b2 for _, b2 in actions], dtype=float)
    pi = np.ones(n) / n
    history_mu = []
    for t in range(steps):
        mu = float(pi @ b2_vec)
        history_mu.append(mu)
        ev_vec = np.array([EV(b1, b2, mu) for b1, b2 in actions])
        avg_ev = float(pi @ ev_vec)
        # replicator: dpi/dt = pi * (ev - avg_ev)
        pi = pi * (1.0 + eta * (ev_vec - avg_ev))
        pi = np.maximum(pi, 0)
        pi /= pi.sum()
    mu = float(pi @ b2_vec)
    var_b2 = float(pi @ (b2_vec - mu) ** 2)
    sd_b2 = math.sqrt(var_b2)
    mode_idx = int(np.argmax(pi))
    return pi, mu, sd_b2, actions[mode_idx], history_mu


# ---------------------------------------------------------------------------
# (4) Closed-form FOC sketch (continuous relaxation)
# ---------------------------------------------------------------------------
def foc_analysis():
    """In the continuous relaxation with reserve r ~ Unif[670, 920]:
        F(r) = (r - 670)/250 for r in [670, 920].
        EV(b1, b2; mu) = (920 - b1) * F(b1) + integrand_{b1}^{b2} payoff(b2;mu) dF
                       = (920 - b1)(b1 - 670)/250 + payoff(b2;mu)*(b2 - b1)/250
      where payoff(b2;mu) = 920 - b2 if b2 > mu, else (920-mu)^3/(920-b2)^2.
    FOC wrt b1 (interior, fix b2): d/db1 [(920-b1)(b1-670)/250 - payoff(b2)*(b1)/250] = 0
      -> (920 - 2 b1 + 670)/250 - payoff(b2)/250 = 0
      -> b1* = (1590 - payoff(b2)) / 2
    For b2 ≈ mu+ ε, payoff(b2) = 920 - b2 ≈ 920 - mu, so:
      b1* ≈ (1590 - (920 - mu)) / 2 = (670 + mu) / 2
    With mu ≈ 855, b1* ≈ 762.5  -> b1 = 762 or 763.

    FOC wrt b2 (assuming we're in penalty branch b2 = mu - delta, delta small):
      payoff(b2) = (920-mu)^3/(920-b2)^2.
      d/db2 [payoff(b2)*(b2 - b1)/250]
        = [2(920-mu)^3/(920-b2)^3 * (b2-b1) + (920-mu)^3/(920-b2)^2] / 250
      Both terms positive => want b2 as large as possible in penalty branch.
      But at b2 = mu+: clean payoff (920 - b2), strictly LESS than penalty payoff for small delta.
      Discontinuous jump at b2 = mu: payoff jumps from (920-mu) [clean side] to (920-mu) [penalty
      side at the boundary, since (920-mu)^3/(920-mu)^2 = 920-mu] but the d/db2 has different signs.
      Right of mu: d/db2 payoff = -1 (linear decay).
      Left of mu (penalty side): d/db2 payoff = 2(920-mu)^3/(920-b2)^3 > 0 (penalty payoff INCREASES
      as b2 -> mu from below).
    => Optimal b2 sits exactly at mu+1 (just above mu) OR at penalty-side local max which is at
       b2 -> mu^- but bounded by integer step and risk of mu drift.
    """
    print("\n" + "=" * 72)
    print("[4] Closed-form FOC (continuous relaxation)")
    print("=" * 72)
    print("  b1* = (670 + mu) / 2   (assuming b2 just above mu)")
    print("  b2* = mu + 1            (smallest integer above mu, clean branch)")
    print()
    for mu in [840, 850, 855, 860, 865, 870]:
        b1c = (670 + mu) / 2
        b2c = mu + 1
        b1_int = int(round(b1c))
        b2_int = int(b2c)
        ev_int = EV(b1_int, b2_int, mu)
        print(f"  mu={mu}: continuous (b1*, b2*) = ({b1c:.1f}, {b2c}); "
              f"discrete ({b1_int}, {b2_int}), EV={ev_int:.3f}")


# ---------------------------------------------------------------------------
# (5) Head-to-head EV
# ---------------------------------------------------------------------------
def head_to_head(mu_dist):
    """mu_dist: list of (mu, weight)."""
    print("\n" + "=" * 72)
    print("[5] Head-to-head: (766,866) vs (771,871) vs (771,876) vs (756,851)")
    print("=" * 72)
    cands = [(766, 866), (771, 871), (771, 876), (756, 851), (762, 856), (761, 856)]
    print(f"  {'pair':<14}", end="")
    for mu, _ in mu_dist:
        print(f"  mu={mu:>4.0f}", end="")
    print(f"   {'wEV':>8}")
    for b1, b2 in cands:
        evs = []
        wsum = 0.0
        wev = 0.0
        for mu, w in mu_dist:
            e = EV(b1, b2, mu)
            evs.append(e)
            wev += w * e
            wsum += w
        wev /= wsum
        line = f"  ({b1},{b2})  "
        for e in evs:
            line += f"  {e:>6.2f}"
        line += f"   {wev:>8.3f}"
        print(line)


def breakeven_mu(pair_a, pair_b, mu_lo=820, mu_hi=900):
    """Find mu where EV(pair_a, mu) == EV(pair_b, mu)."""
    a1, a2 = pair_a
    b1, b2 = pair_b
    diffs = [(mu, EV(a1, a2, mu) - EV(b1, b2, mu)) for mu in range(mu_lo, mu_hi + 1)]
    # find sign change
    signs = [d for _, d in diffs]
    crossings = []
    for i in range(1, len(signs)):
        if signs[i - 1] * signs[i] < 0:
            mu_a = diffs[i - 1][0]
            mu_b = diffs[i][0]
            d_a = signs[i - 1]
            d_b = signs[i]
            mu_cross = mu_a - d_a * (mu_b - mu_a) / (d_b - d_a)
            crossings.append(mu_cross)
    return crossings


# ---------------------------------------------------------------------------
# (6) Sensitivity to behavioral fraction
# ---------------------------------------------------------------------------
def behavioral_fraction_sweep():
    """Mu = sf * Nash_mu + (1-sf) * naive_mu. naive_mu = 856 (UI default).
    Compute optimal pair as fn of sf.
    """
    print("\n" + "=" * 72)
    print("[6] Behavioral-fraction sensitivity")
    print("=" * 72)
    naive_mu = 856.0
    nash_mu = 851.0  # from previous sf=1 fixed point at seed 850
    print(f"  Mixing UI-default mu={naive_mu} with sophisticated mu={nash_mu}")
    print(f"  {'sf':>5} {'mu':>7} {'BR_b1':>6} {'BR_b2':>6} {'EV':>7}")
    for sf in [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0]:
        mu = sf * nash_mu + (1 - sf) * naive_mu
        b1, b2, ev = best_response_mu(mu)
        print(f"  {sf:>5.1f} {mu:>7.2f} {b1:>6} {b2:>6} {ev:>7.3f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 72)
    print("R3 Manual Challenge — DEEP analysis")
    print("=" * 72)
    print(f"Action grid: |B1|={len(B1_RANGE)}, |B2|={len(B2_RANGE)}, "
          f"|A|={len(ACTIONS)} (b2-b1>=50)")

    # 1. Level-k
    lk_history = level_k_ladder()

    # 4. FOC
    foc_analysis()

    # 2. QRE — sweep lambda
    print("\n" + "=" * 72)
    print("[2] Logit QRE — symmetric mixed equilibrium across lambda")
    print("=" * 72)
    print("  lambda corresponds to rationality. lambda=0 -> uniform. lambda=inf -> Nash pure.")
    print(f"  {'lambda':>8} {'mu*':>8} {'sd(b2)':>7} {'mode_action':>14} {'iters':>6}")
    qre_results = []
    for lam in [0.001, 0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0]:
        pi, mu, sd, mode_a, its = qre(lam)
        qre_results.append((lam, pi, mu, sd, mode_a))
        print(f"  {lam:>8.3f} {mu:>8.2f} {sd:>7.2f} {str(mode_a):>14} {its:>6}")

    # 3. Replicator
    print("\n" + "=" * 72)
    print("[3] Replicator dynamics (eta=0.05, 500 steps)")
    print("=" * 72)
    pi_r, mu_r, sd_r, mode_r, hist_mu = replicator()
    print(f"  Converged mu = {mu_r:.2f}, sd(b2) = {sd_r:.2f}, mode action = {mode_r}")
    print(f"  Mu trajectory (every 50 steps): "
          f"{[f'{hist_mu[i]:.1f}' for i in range(0, 500, 50)]}")
    # top-10 actions by replicator weight
    top_idx = np.argsort(pi_r)[-10:][::-1]
    print("  Top-10 actions by replicator weight:")
    for i in top_idx:
        b1, b2 = ACTIONS[i]
        print(f"    ({b1},{b2})  weight={pi_r[i]:.4f}  EV(at mu*={mu_r:.2f})="
              f"{EV(b1, b2, mu_r):.3f}")

    # 5. Head-to-head — use QRE-derived mu distribution
    # Use moderate-rationality QRE (lambda=0.5) as our "true" prior over mu
    _, mu_qre_low, _, _, _ = qre(0.05)
    _, mu_qre_mid, sd_qre_mid, mode_mid, _ = qre(0.5)
    _, mu_qre_high, _, _, _ = qre(2.0)
    print(f"\n  QRE mu range: lambda=0.05 -> mu={mu_qre_low}, "
          f"lambda=0.5 -> mu={mu_qre_mid:.2f}, lambda=2.0 -> mu={mu_qre_high:.2f}")

    # mu_dist: 5-pt distribution centered on QRE-mid with sd ~ qre sd
    mu_center = mu_qre_mid
    sd = max(sd_qre_mid, 5.0)
    mu_dist = [
        (mu_center - 2 * sd, 0.10),
        (mu_center - sd, 0.20),
        (mu_center, 0.40),
        (mu_center + sd, 0.20),
        (mu_center + 2 * sd, 0.10),
    ]
    print(f"\n  Using mu-distribution: center={mu_center:.2f}, sd={sd:.2f}")
    head_to_head(mu_dist)

    # 5b. Breakeven analysis
    print("\n  Breakeven mu where EV equals:")
    for a, b in [((766, 866), (771, 871)),
                 ((771, 871), (771, 876)),
                 ((766, 866), (771, 876)),
                 ((766, 866), (756, 851))]:
        cr = breakeven_mu(a, b)
        print(f"    {a} vs {b}: breakeven mu = {cr}")

    # 6. Behavioral fraction
    behavioral_fraction_sweep()

    # 7. Final recommendation
    print("\n" + "=" * 72)
    print("[7] FINAL EV-vs-mu under three plausible mu distributions")
    print("=" * 72)
    cands = [(756, 851), (761, 856), (762, 856), (766, 866), (771, 871),
             (771, 876), (776, 876)]
    scenarios = {
        "Pessimistic (Nash sf=1, mu=851)": [(845, 0.1), (850, 0.2), (855, 0.4), (860, 0.2), (865, 0.1)],
        "Realistic (QRE/mixed, mu~858)":   [(848, 0.1), (854, 0.2), (858, 0.4), (864, 0.2), (870, 0.1)],
        "Conservative (high sf, mu=865)":   [(855, 0.1), (860, 0.2), (865, 0.4), (870, 0.2), (875, 0.1)],
    }
    for name, dist in scenarios.items():
        print(f"\n  Scenario: {name}")
        print(f"    {'pair':<14} {'EV':>8} {'min':>8} {'max':>8}")
        for b1, b2 in cands:
            evs = [EV(b1, b2, mu) for mu, _ in dist]
            wev = sum(w * e for (mu, w), e in zip(dist, evs))
            print(f"    ({b1},{b2})  {wev:>8.3f} {min(evs):>8.3f} {max(evs):>8.3f}")
