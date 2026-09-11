"""
Q4: Boundary cases and Q7: sensitivity to mu uncertainty.
"""

import math
from statistics import NormalDist

from ev_engine import ev, RESERVES, SELL


# =============================================================================
# Q4: Boundary cases
# =============================================================================

def boundary_cases():
    print("\n=== Q4: BOUNDARY CASES ===")

    cases = [
        ("(670, 670)  -- single-bid at minimum",   670, 670),
        ("(670, 670+eps) -- min with vanishing 2nd", 670, 670 + 1e-6),
        ("(670, 920) -- spread the full range",    670, 920),
        ("(670, 919.99) -- almost-no-trade ceiling", 670, 919.99),
        ("(920, 920) -- both at max",              920, 920),
        ("(919, 920) -- single-bid at max",        919, 920),
        ("(b1=b2=860) -- midpoint single-bid",     860, 860),
        ("(860, 860+eps) -- midpoint with vanish", 860, 860 + 1e-6),
        ("(670+eps, 920) -- min+eps wide",         670 + 1e-6, 920),
    ]
    mu = 858
    for name, b1, b2 in cases:
        v = ev(b1, b2, mu)
        print(f"  {name:50s}  EV={v:.4f}")

    print("\nKey observation: at b1=b2=B, the 'between' bracket is empty (b1<=r<b2 is empty).")
    print("So profit per reserve is (920-B) if r<B else 0.")
    print("EV = (count of r<B) * (920-B) / 51.")
    print("For B in {670,675,...,920}, count(r<B) = (B-670)/5  (the integer part).")
    print()
    print("Sweep b1=b2 across reserve grid:")
    best = (-1, None)
    for B in RESERVES:
        n_below = sum(1 for r in RESERVES if r < B)
        per = (SELL - B)
        v = n_below * per / len(RESERVES)
        if v > best[0]:
            best = (v, B)
        if v > 75:
            print(f"  B={B}: n_below={n_below}, per={per}, EV={v:.4f}")
    print(f"  best single-bid (b1=b2 grid): EV={best[0]:.4f} at B={best[1]}")

    # Single-bid CONTINUOUS optimum: maximize n*(920-B) where n = # reserves < B
    # n is step function: n=0 for B<=670, n=1 for 670<B<=675, ..., n=k for 670+5(k-1) < B <= 670+5k
    # Within a step, EV increases as B decreases (more 920-B). So optimum at B = 670+5(k-1)+eps.
    print("\nSingle-bid CONTINUOUS optimum (B = 670 + 5(k-1) + eps):")
    best = (-1, None, None)
    for k in range(0, 51):
        B_inf = 670 + 5 * (k - 1) + 1e-6 if k >= 1 else 670 + 1e-6
        n = k
        per = SELL - B_inf
        v = n * per / 51
        if v > best[0]:
            best = (v, B_inf, k)
    print(f"  best continuous single-bid: EV={best[0]:.4f} at B={best[1]:.6f} (k={best[2]} reserves below)")

    # b1=b2 with SPLIT: b1=k_th-reserve+eps, b2=B for some B>b1
    # As b2 -> b1, "between" empties -- single-bid limit.

    # The single-bid optimum is a decent baseline. Compare with two-bid optimum.
    print("\nFor reference, two-bid optimum at mu=858 from prior runs: ~83.14 EV.")
    print("Single-bid achievable optimum:", best[0])


# =============================================================================
# Q7: Sensitivity analysis
# =============================================================================

def sweep_candidates():
    """Returns a curated list of strong candidates spanning the search space."""
    cands = set()
    # Integer optima we found earlier
    for b1 in range(750, 781):
        for b2 in range(850, 881):
            cands.add((float(b1), float(b2)))
    # Fractional cell-rep candidates: (r1+eps, r2+eps) for r1, r2 in reserves nearby
    eps = 1e-6
    for r1 in range(750, 785, 5):
        for r2 in range(850, 880, 5):
            if r1 <= r2:
                cands.add((r1 + eps, r2 + eps))
                cands.add((r1 + eps, float(r2)))
                cands.add((float(r1), r2 + eps))
    # Some integer "+eps" types
    for r1 in [765, 766]:
        for r2 in [860, 861, 865, 866]:
            cands.add((float(r1), float(r2)))
    return sorted(cands)


def expected_ev_under_distribution(b1, b2, mu_pdf):
    """mu_pdf is a list of (mu, weight) pairs (already normalized)."""
    return sum(w * ev(b1, b2, m) for m, w in mu_pdf)


def cvar(b1, b2, mu_pdf, alpha=0.05):
    """Worst alpha-quantile EV (Conditional Value at Risk on the left tail)."""
    evs = sorted([(ev(b1, b2, m), w) for m, w in mu_pdf])
    cum = 0.0
    total = 0.0
    weight_acc = 0.0
    for v, w in evs:
        if cum + w <= alpha:
            total += v * w
            weight_acc += w
            cum += w
        else:
            take = alpha - cum
            total += v * take
            weight_acc += take
            break
    if weight_acc == 0:
        return evs[0][0]
    return total / weight_acc


def worst_case(b1, b2, mu_pdf):
    return min(ev(b1, b2, m) for m, _ in mu_pdf)


def log_utility(b1, b2, mu_pdf):
    """E[log(EV)] -- needs EV>0. Skip if any EV <= 0."""
    s = 0.0
    for m, w in mu_pdf:
        v = ev(b1, b2, m)
        if v <= 0:
            return -math.inf
        s += w * math.log(v)
    return s


def discretize_normal(mean, sd, n=121, span=4):
    """Returns weighted list of (mu, w) approximating N(mean, sd)."""
    nd = NormalDist(mean, sd)
    xs = [mean + sd * (-span + 2 * span * i / (n - 1)) for i in range(n)]
    weights = [nd.pdf(x) for x in xs]
    s = sum(weights)
    return [(x, w / s) for x, w in zip(xs, weights)]


def sensitivity_table():
    print("\n=== Q7: SENSITIVITY ANALYSIS ===")
    cands = sweep_candidates()
    print(f"Candidate set: {len(cands)} pairs")

    distros = {
        "N(858, 5)":   discretize_normal(858, 5),
        "N(862, 8)":   discretize_normal(862, 8),
        "N(858, 0.5)": discretize_normal(858, 0.5),
        "Mixture: 0.5*N(858,5)+0.5*N(862,8)": (
            [(m, 0.5 * w) for m, w in discretize_normal(858, 5)] +
            [(m, 0.5 * w) for m, w in discretize_normal(862, 8)]
        ),
        "Uniform [840,890]": [(840 + i * 0.5, 1.0) for i in range(101)],
    }
    # Normalize uniform
    for k, v in list(distros.items()):
        s = sum(w for _, w in v)
        distros[k] = [(m, w / s) for m, w in v]

    criteria = ["E[EV]", "Worst case EV", "CVaR-95%", "log(EV) (Kelly)"]

    print()
    for d_name, pdf in distros.items():
        print(f"\n--- distribution: {d_name} ---")
        for crit in criteria:
            best = (-math.inf, None)
            for b1, b2 in cands:
                if crit == "E[EV]":
                    v = expected_ev_under_distribution(b1, b2, pdf)
                elif crit == "Worst case EV":
                    v = worst_case(b1, b2, pdf)
                elif crit == "CVaR-95%":
                    v = cvar(b1, b2, pdf, alpha=0.05)
                elif crit == "log(EV) (Kelly)":
                    v = log_utility(b1, b2, pdf)
                if v > best[0]:
                    best = (v, (b1, b2))
            b1, b2 = best[1]
            print(f"  {crit:18s}  best=({b1:9.6f}, {b2:9.6f})  score={best[0]:.4f}")

    # Wald minimax: maximize over (b1,b2) the minimum EV over mu in [840, 890]
    print("\n--- Wald minimax: max over bids of min EV over mu in [840, 890] ---")
    pdf = [(840 + i * 1.0, 1.0) for i in range(51)]
    best = (-math.inf, None)
    for b1, b2 in cands:
        v = worst_case(b1, b2, pdf)
        if v > best[0]:
            best = (v, (b1, b2))
    print(f"  best=({best[1][0]:.6f},{best[1][1]:.6f})  worst-case EV={best[0]:.4f}")


def main():
    boundary_cases()
    sensitivity_table()


if __name__ == "__main__":
    main()
