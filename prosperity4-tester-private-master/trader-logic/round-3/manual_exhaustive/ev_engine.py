"""
Independent reimplementation of R3 manual auction EV.

Rules (from user payoff spec):
- 51 reserves r in {670, 675, ..., 920}, uniform.
- Submit (b1, b2) with b1 <= b2, both in [670, 920].
- For each reserve r:
    if r < b1:           profit = 920 - b1                   (trade at b1)
    elif b1 <= r < b2:   profit = 920 - b2                  if b2 >  mu     (trade at b2)
                         profit = (920 - mu)**3 / (920 - b2)**2 if b2 <= mu (penalty branch)
    else (r >= b2):      profit = 0                          (no trade)
- Average profit across the 51 reserves = EV per counterparty.

This file is intentionally independent of trader-logic/round-3/manual_r3_solver.py.
"""

from __future__ import annotations

import math
from typing import Iterable

RESERVES = tuple(670 + 5 * k for k in range(51))   # 670, 675, ..., 920
N_RES = len(RESERVES)                              # 51
SELL = 920


def per_reserve_profit(b1: float, b2: float, mu: float, r: float) -> float:
    """Profit from one counterparty with reserve r."""
    if r < b1:
        return SELL - b1
    if r < b2:
        if b2 > mu:
            return SELL - b2
        # penalty branch (b2 <= mu)
        if b2 >= SELL:
            # (920 - b2) = 0 -> infinite. Means we never trade because b2=920 >= every r,
            # but the rule says b1<=r<b2, and r<=920. If b2=920 and r=920 not strict-less,
            # so this branch only fires for b2<920 here. Guard anyway.
            return 0.0
        return (SELL - mu) ** 3 / (SELL - b2) ** 2
    return 0.0


def ev(b1: float, b2: float, mu: float, reserves: Iterable[float] = RESERVES) -> float:
    """Expected profit per counterparty (uniform over reserves)."""
    total = 0.0
    n = 0
    for r in reserves:
        total += per_reserve_profit(b1, b2, mu, r)
        n += 1
    return total / n


def ev_breakdown(b1: float, b2: float, mu: float):
    """Diagnostic: returns (n_below_b1, n_between, n_above, contrib_b1, contrib_b2_branch)."""
    n_below = sum(1 for r in RESERVES if r < b1)
    n_between = sum(1 for r in RESERVES if b1 <= r < b2)
    n_above = sum(1 for r in RESERVES if r >= b2)
    contrib_b1 = n_below * (SELL - b1)
    if b2 > mu:
        contrib_b2 = n_between * (SELL - b2)
    elif b2 >= SELL:
        contrib_b2 = 0.0
    else:
        contrib_b2 = n_between * (SELL - mu) ** 3 / (SELL - b2) ** 2
    return n_below, n_between, n_above, contrib_b1, contrib_b2, (contrib_b1 + contrib_b2) / N_RES


if __name__ == "__main__":
    # Sanity vs prior recommendation (766, 866) at mu=858
    for pair in [(766, 866), (771, 871), (771, 866), (766, 871), (766, 868)]:
        b1, b2 = pair
        print(f"({b1},{b2}) mu=858  EV={ev(b1,b2,858):.6f}  "
              f"breakdown={ev_breakdown(b1,b2,858)}")
