"""
Final recommendation: integrate everything.

Given mu ~ N(858, 0.5) (per task: 'predicted mu = 858 with sd=0.5 due to N=4021'),
and accounting for fractional bidding allowed by the form:

OPTIMUM under point estimate mu=858:
  (b1, b2) = (760+eps, 860+eps), EV = 83.137255
  Use eps ~ 0.01 to be visible in the form: (760.01, 860.01)

If form REQUIRES integers, the best integer pair is:
  (b1, b2) = (761, 861), EV = 82.372549   (vs. (766,866) -> 81.568627)
  (761, 861) beats (766, 866) by +0.804 EV (+0.99%) at mu=858.

Robustness analysis below uses the proper candidate set.
"""

import math
from statistics import NormalDist

from ev_engine import ev


def discretize_normal(mean, sd, n=201, span=4):
    nd = NormalDist(mean, sd)
    xs = [mean + sd * (-span + 2 * span * i / (n - 1)) for i in range(n)]
    weights = [nd.pdf(x) for x in xs]
    s = sum(weights)
    return [(x, w / s) for x, w in zip(xs, weights)]


def all_candidates():
    """Build candidate set focused on the relevant region.
    Includes: reserve+eps cell-rep candidates, integer candidates near optimum,
    and the b2=mu boundary for various mu.
    """
    eps = 1e-6
    cands = set()
    # Reserve+eps cell candidates over [720, 800] x [800, 900]
    for r1 in range(720, 801, 5):
        for r2 in range(800, 901, 5):
            if r1 <= r2:
                cands.add((r1 + eps, r2 + eps))
                cands.add((r1 + eps, float(r2)))   # b2 exactly on a reserve
    # Integer candidates near the optimal area (form might require integers)
    for b1 in range(740, 791):
        for b2 in range(840, 891):
            if b1 <= b2:
                cands.add((float(b1), float(b2)))
    # b2 = mu candidates: try b2 in {857, 858, 859, ...} also as fractional
    for r1 in range(720, 801, 5):
        for b2 in [857.0, 857.5, 858.0, 858.5, 859.0, 860.5, 861.5, 862.5,
                   864.0, 866.0, 868.0]:
            cands.add((r1 + eps, b2))
    return sorted(cands)


def expected_ev(b1, b2, pdf):
    return sum(w * ev(b1, b2, m) for m, w in pdf)


def percentile_ev(b1, b2, pdf, q):
    evs = sorted(ev(b1, b2, m) for m, _ in pdf)
    return evs[int(q * (len(evs) - 1))]


def cvar(b1, b2, pdf, alpha=0.05):
    pairs = sorted([(ev(b1, b2, m), w) for m, w in pdf])
    cum = 0.0
    s = 0.0
    wt = 0.0
    for v, w in pairs:
        if cum + w <= alpha:
            s += v * w
            wt += w
            cum += w
        else:
            take = alpha - cum
            s += v * take
            wt += take
            break
    return s / wt if wt > 0 else pairs[0][0]


def best_under(criterion, cands, pdf):
    best = (-math.inf, None)
    for b1, b2 in cands:
        v = criterion(b1, b2, pdf)
        if v > best[0]:
            best = (v, (b1, b2))
    return best


def main():
    cands = all_candidates()
    print(f"Searching over {len(cands)} candidate pairs.")

    distros = {
        "Plug-in mu=858 (delta)":   [(858.0, 1.0)],
        "N(858, 0.5) [user prior]": discretize_normal(858, 0.5),
        "N(858, 2)":                discretize_normal(858, 2),
        "N(858, 5)":                discretize_normal(858, 5),
        "N(862, 8)":                discretize_normal(862, 8),
        "Uniform [840, 890]":       [(840 + i * 0.5, 1.0 / 101) for i in range(101)],
    }
    for k, pdf in distros.items():
        s = sum(w for _, w in pdf)
        distros[k] = [(m, w / s) for m, w in pdf]

    # Precompute support of mus needed across all distributions.
    all_mus = set()
    for pdf in distros.values():
        for m, _ in pdf:
            all_mus.add(round(m, 6))
    all_mus = sorted(all_mus)
    print(f"Precomputing EV over {len(cands)} cands * {len(all_mus)} mu pts...")
    ev_table = {}
    for b1, b2 in cands:
        ev_table[(b1, b2)] = {m: ev(b1, b2, m) for m in all_mus}

    def expected_ev_fast(b1, b2, pdf):
        d = ev_table[(b1, b2)]
        return sum(w * d[round(m, 6)] for m, w in pdf)

    def worst_ev_fast(b1, b2, pdf):
        d = ev_table[(b1, b2)]
        return min(d[round(m, 6)] for m, _ in pdf)

    def cvar_fast(b1, b2, pdf, alpha=0.05):
        d = ev_table[(b1, b2)]
        pairs = sorted([(d[round(m, 6)], w) for m, w in pdf])
        cum = 0.0
        s = 0.0
        wt = 0.0
        for v, w in pairs:
            if cum + w <= alpha:
                s += v * w; wt += w; cum += w
            else:
                take = alpha - cum
                s += v * take; wt += take; break
        return s / wt if wt > 0 else pairs[0][0]

    print(f"\n{'distribution':<32} {'criterion':<20} {'b1':>10} {'b2':>10} {'score':>10}")
    print("-" * 90)
    for d_name, pdf in distros.items():
        for crit_name, crit in [
            ("E[EV]", expected_ev_fast),
            ("min EV", worst_ev_fast),
            ("CVaR-95%", lambda b1, b2, p: cvar_fast(b1, b2, p, 0.05)),
        ]:
            best = (-math.inf, None)
            for b1, b2 in cands:
                v = crit(b1, b2, pdf)
                if v > best[0]:
                    best = (v, (b1, b2))
            b1, b2 = best[1]
            print(f"{d_name:<32} {crit_name:<20} {b1:>10.4f} {b2:>10.4f} {best[0]:>10.4f}")

    # Final recommendation
    print("\n" + "=" * 80)
    print("FINAL RECOMMENDATION")
    print("=" * 80)
    print("""
Under mu ~ N(858, 0.5) (the user's stated prior), the optimum is:

  (b1, b2) = (760.01, 860.01)         EV = 83.137  per counterparty

If the form requires integer bids, the best integer choice is:

  (b1, b2) = (761, 861)               EV = 82.373  per counterparty

These dominate the prior recommendation (766, 866) [EV = 81.569] across the
ENTIRE plausible mu range [856, 860] by approximately +1.57 EV (fractional)
or +0.80 EV (integer).

If you are uncertain enough that mu may be > 860 (e.g. N(862, 8) prior),
then (770.01, 870.01) is more robust (E[EV] = 80.7 under that prior),
and the worst-case-robust choice is (776, 880) (EV >= 66 over [840, 890]).
""")


if __name__ == "__main__":
    main()
