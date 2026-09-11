"""manual_r3_solver.py — Round 3 "Celestial Gardeners' Guild" two-bid auction.

Rules (from brief + UI):
  - Each counterparty has a reserve r uniform on {670, 675, ..., 915, 920} (51 values).
  - Submit two integer bids: b1 (lower) <= b2 (upper), both in [670, 920].
  - Sell price next day = 920.
  - If r < b1: both bids exceed → trade at LOWER bid b1, profit = 920 - b1.
  - Elif r < b2: only b2 exceeds → trade at b2, subject to global mean check:
      * If b2 > mean_b2 across all players: profit = 920 - b2.
      * Elif b2 <= mean_b2: profit = (920 - mean_b2)**3 / (920 - b2)**2 (penalty).
  - Else (r >= b2): no trade.

mean_b2 is endogenous. Solve via Nash fixed-point iteration.
"""
from __future__ import annotations

SELL = 920
RESERVES = tuple(range(670, 925, 5))  # 51 discrete values
NUM_RESERVES = len(RESERVES)


def profit_one(b1: int, b2: int, r: int, mu: float) -> float:
    if r < b1:
        return SELL - b1
    if r < b2:
        if b2 > mu:
            return SELL - b2
        # penalty branch: effective profit = (SELL - mu)**3 / (SELL - b2)**2
        denom = (SELL - b2)
        if denom <= 0:
            return 0.0
        return (SELL - mu) ** 3 / (denom * denom)
    return 0.0


def EV(b1: int, b2: int, mu: float) -> float:
    return sum(profit_one(b1, b2, r, mu) for r in RESERVES) / NUM_RESERVES


def best_response(mu: float) -> tuple[int, int, float]:
    """Grid search (b1, b2) integer pair in [670, 920] with b1 <= b2, maximizing EV."""
    best = (0, 0, -1.0)
    for b1 in range(670, 921):
        for b2 in range(b1, 921):
            ev = EV(b1, b2, mu)
            if ev > best[2]:
                best = (b1, b2, ev)
    return best


def solve_nash(mu_init: float = 850.0, tol: float = 0.25, max_iter: int = 50, damping: float = 0.5):
    """Fixed-point iteration: update mu to best-response b2 (symmetric equilibrium).

    Cycle-detection: if the same (b1, b2) pair is produced twice, the iteration
    has entered an integer oscillation and won't converge below tol. Return the
    highest-EV pair seen so far.
    """
    mu = mu_init
    history = [(mu, None)]
    seen_pairs = {}  # (b1, b2) -> ev
    best_global = (0, 0, -1.0)
    for it in range(max_iter):
        b1, b2, ev = best_response(mu)
        history.append((float(b2), (b1, b2, ev)))
        if ev > best_global[2]:
            best_global = (b1, b2, ev)
        pair = (b1, b2)
        if pair in seen_pairs:
            # Integer oscillation detected — return best seen
            return best_global, mu, it + 1, history
        seen_pairs[pair] = ev
        mu_new = float(b2)
        if abs(mu_new - mu) < tol:
            return (b1, b2, ev), mu, it + 1, history
        mu = damping * mu + (1 - damping) * mu_new
    return best_global, mu, max_iter, history


def sensitivity(b1: int, b2: int, mu_star: float, mu_range: range | list) -> list:
    """How does EV vary as mu deviates from mu_star?"""
    return [(m, EV(b1, b2, m)) for m in mu_range]


def robust_grid(mu_star: float, mu_std: float = 10.0) -> tuple[int, int, float]:
    """Robust optimum: maximize EV averaged over mu sampled from N(mu_star, mu_std)."""
    import math
    # 7-point Gauss-Hermite-ish grid for N(mu_star, mu_std^2)
    offsets = [-2.5, -1.5, -0.75, 0.0, 0.75, 1.5, 2.5]
    weights = [0.025, 0.15, 0.2, 0.25, 0.2, 0.15, 0.025]
    mus = [mu_star + o * mu_std for o in offsets]
    best = (0, 0, -1.0)
    for b1 in range(670, 921):
        for b2 in range(b1, 921):
            ev_avg = sum(w * EV(b1, b2, m) for w, m in zip(weights, mus))
            if ev_avg > best[2]:
                best = (b1, b2, ev_avg)
    return best


if __name__ == "__main__":
    print("=" * 60)
    print("R3 Manual Challenge — Two-Bid Auction Solver")
    print("=" * 60)

    print("\n[1] Nash fixed-point iteration from mu=850.0:")
    (b1, b2, ev), mu_star, iters, hist = solve_nash()
    print(f"  Converged in {iters} iter(s).")
    print(f"  Best-response: b1={b1}, b2={b2}, EV={ev:.3f}, mu* = {mu_star:.2f}")
    print("\n  History (mu → best_response):")
    for i, (m, br) in enumerate(hist[:8]):
        if br:
            print(f"    iter {i}: mu={m:.2f} → (b1={br[0]}, b2={br[1]}, EV={br[2]:.3f})")
        else:
            print(f"    iter {i}: mu={m:.2f} (seed)")

    print("\n[2] Alternate seeds (check for multiple equilibria):")
    for seed in [800.0, 870.0, 890.0, 910.0]:
        (b1s, b2s, evs), mus, its, _ = solve_nash(mu_init=seed)
        print(f"  seed={seed:.0f}: → b1={b1s}, b2={b2s}, EV={evs:.3f}, mu*={mus:.2f}, iter={its}")

    print(f"\n[3] Sensitivity around mu* = {mu_star:.2f} (keeping b1={b1}, b2={b2}):")
    for m in range(int(mu_star) - 20, int(mu_star) + 21, 5):
        ev_m = EV(b1, b2, m)
        marker = "  *" if m == int(mu_star) else ""
        print(f"  mu={m:>4}: EV = {ev_m:.3f}{marker}")

    print("\n[4] Robust optimum over varying mu uncertainty:")
    for mu_std in [5.0, 10.0, 20.0]:
        rb1, rb2, rev = robust_grid(mu_star, mu_std=mu_std)
        print(f"  mu_std={mu_std:>4}: b1={rb1}, b2={rb2}, EV_avg={rev:.3f}")

    print("\n[4b] Robust optimum centered at 860 (in case competitors overshoot):")
    rb1, rb2, rev = robust_grid(860.0, mu_std=15.0)
    print(f"  center=860, mu_std=15: b1={rb1}, b2={rb2}, EV_avg={rev:.3f}")

    print("\n[4c] Candidate pair comparison across mu scenarios:")
    candidates = [
        ("Nash(mu=850)", 756, 851),
        ("UI default",   761, 856),
        ("Robust(850,10)", 766, 866),
        ("Safe high",    770, 871),
        ("Nash(mu=836)", 751, 836),
    ]
    scenarios = [830, 840, 850, 855, 860, 865, 870, 880]
    header = "  pair".ljust(22) + "".join(f"mu={m:<4}".rjust(10) for m in scenarios)
    print(header)
    for name, b1c, b2c in candidates:
        row = f"  {name} ({b1c},{b2c})".ljust(22)
        for m in scenarios:
            row += f"{EV(b1c, b2c, m):>9.2f} "
        print(row)

    print("\n[5] Comparison: UI default (761, 856):")
    ui_ev = EV(761, 856, mu_star)
    print(f"  EV at mu*={mu_star:.2f}: {ui_ev:.3f}")
    print(f"  vs. Nash best ({b1}, {b2}): {ev:.3f}")
    print(f"  Nash improvement: +{ev - ui_ev:.3f} per counterparty ({100*(ev-ui_ev)/ui_ev:+.1f}%)")

    print("\n" + "=" * 60)
    print(f"SUBMIT: b1={b1}, b2={b2}  (Nash, EV={ev:.2f})")
    print(f"ROBUST: b1={rb1}, b2={rb2} (EV_avg={rev:.2f})")
    print("=" * 60)
