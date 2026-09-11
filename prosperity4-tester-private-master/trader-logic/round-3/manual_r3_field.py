"""manual_r3_field.py — Field-distribution stress test.

Hypothesis: real Prosperity field is heterogeneous. Some teams will L0/L1
think (mu ~ 850-865), some will overshoot to mu>880 chasing penalty escape.
Question: what's the *plausible* range of mu = mean of all teams' b2?

Strategy: simulate 4021 players with a realistic mixture:
  - 30% UI default (761, 856)
  - 20% naive round-numbers (756, 851), (761, 856), (766, 871), (771, 876)
  - 25% L1 best-respond to mu0=857 -> (761, 861) ish
  - 15% L2/Nash sf=1 -> (756, 851)
  - 10% sophisticated tournament-overshoot -> (771, 876) or (776, 881)

Then compute realized mu and EV of each candidate strategy.
"""
from __future__ import annotations
import numpy as np
from manual_r3_solver import EV, SELL, RESERVES, NUM_RESERVES

np.random.seed(42)


def simulate_field(N=4021, seed=42, weights=None):
    rng = np.random.default_rng(seed)
    # Player archetypes — (b1, b2, weight)
    archetypes = [
        ("UI default",       761, 856, 0.30),
        ("L1 BR(857)",       761, 861, 0.20),
        ("Nash sf=1",        756, 851, 0.15),
        ("Round num low",    760, 855, 0.10),
        ("Robust(850,10)",   766, 866, 0.10),
        ("Tournament safe",  771, 871, 0.08),
        ("Tournament high",  776, 881, 0.05),
        ("Overshoot",        781, 891, 0.02),
    ]
    if weights is not None:
        archetypes = [(name, b1, b2, w) for (name, b1, b2, _), w in zip(archetypes, weights)]
    names = [a[0] for a in archetypes]
    probs = np.array([a[3] for a in archetypes])
    probs /= probs.sum()
    b2_values = np.array([a[2] for a in archetypes])
    # Add small jitter sd=2 around each archetype (within-arch heterogeneity)
    choices = rng.choice(len(archetypes), size=N, p=probs)
    jitter = rng.normal(0, 2.0, size=N)
    realized_b2 = b2_values[choices] + jitter
    mu = float(realized_b2.mean())
    sd = float(realized_b2.std())
    return mu, sd, archetypes


def stress_test(n_sims=200):
    print("=" * 72)
    print("Field-distribution Monte Carlo (200 simulated populations)")
    print("=" * 72)
    mus = []
    for s in range(n_sims):
        mu, sd, _ = simulate_field(seed=s)
        mus.append(mu)
    mus = np.array(mus)
    print(f"  N=4021, 200 simulated populations")
    print(f"  mu    mean = {mus.mean():.2f}, sd = {mus.std():.3f}")
    print(f"  mu    quantiles: 5%={np.quantile(mus, 0.05):.2f}, "
          f"50%={np.quantile(mus, 0.5):.2f}, 95%={np.quantile(mus, 0.95):.2f}")
    return mus


def alt_distributions():
    """Vary the archetype mix to span our uncertainty."""
    print("\n" + "=" * 72)
    print("Alternative population mixes")
    print("=" * 72)

    # Case A: tournament-savvy field (most teams know mu chases up)
    weights_A = [0.10, 0.10, 0.10, 0.05, 0.20, 0.20, 0.15, 0.10]  # sums to 1
    # Case B: naive field (most teams stay low)
    weights_B = [0.40, 0.25, 0.20, 0.10, 0.03, 0.01, 0.005, 0.005]
    # Case C: balanced
    weights_C = [0.30, 0.20, 0.15, 0.10, 0.10, 0.08, 0.05, 0.02]

    for name, w in [("A_tournament", weights_A), ("B_naive", weights_B), ("C_balanced", weights_C)]:
        mus = []
        for s in range(200):
            mu, _, _ = simulate_field(seed=s, weights=w)
            mus.append(mu)
        mus = np.array(mus)
        print(f"  {name}: mu = {mus.mean():.2f} +- {mus.std():.3f} "
              f"(5%={np.quantile(mus, 0.05):.2f}, 95%={np.quantile(mus, 0.95):.2f})")

    return weights_A, weights_B, weights_C


def candidate_evaluation(mus_distribution, label):
    print(f"\n  Scenario: {label}")
    cands = [(756, 851), (761, 856), (762, 856),
             (766, 866), (771, 871), (771, 876), (776, 881), (781, 886)]
    print(f"    {'pair':<14} {'meanEV':>8} {'sd':>6} {'5%':>7} {'95%':>7}")
    for b1, b2 in cands:
        evs = np.array([EV(b1, b2, mu) for mu in mus_distribution])
        print(f"    ({b1},{b2})  {evs.mean():>8.3f} {evs.std():>6.3f} "
              f"{np.quantile(evs, 0.05):>7.3f} {np.quantile(evs, 0.95):>7.3f}")


if __name__ == "__main__":
    mus = stress_test()
    candidate_evaluation(mus, "Default mix (3:2:1.5:1:1:0.8:0.5:0.2)")

    wA, wB, wC = alt_distributions()

    # Run candidate eval on each
    for name, w in [("A_tournament_savvy", wA), ("B_naive", wB), ("C_balanced", wC)]:
        mus_v = np.array([simulate_field(seed=s, weights=w)[0] for s in range(200)])
        candidate_evaluation(mus_v, name)

    # Final summary: average over the 3 scenarios with equal weight (meta-uncertainty)
    print("\n" + "=" * 72)
    print("META-AVERAGE across A, B, C (equal prior over scenario)")
    print("=" * 72)
    all_mus = []
    for w in [wA, wB, wC]:
        for s in range(200):
            all_mus.append(simulate_field(seed=s, weights=w)[0])
    all_mus = np.array(all_mus)
    print(f"  All-mu pool: mean={all_mus.mean():.2f}, sd={all_mus.std():.2f}")
    print(f"  Quantiles 5/25/50/75/95: "
          f"{np.quantile(all_mus, [0.05, 0.25, 0.5, 0.75, 0.95])}")
    candidate_evaluation(all_mus, "META (A+B+C equal weight)")
