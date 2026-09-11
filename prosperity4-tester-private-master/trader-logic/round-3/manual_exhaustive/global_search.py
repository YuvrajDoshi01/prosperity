"""
Global search: characterize the EV landscape over the FULL legal domain.

Key observation: for fixed mu, EV(b1, b2) is piecewise constant on rectangles
whose vertices are at:
   b1-grid: {670, 675, ..., 920} (the reserves) plus their "+epsilon" duals
   b2-grid: {670, 675, ..., 920} plus mu (penalty switch)
EV is right-continuous in b1 (just-above-r jumps UP because that reserve falls
into the lower-payoff bracket... wait, just-above r means we now PAY less for
that reserve since 920 - b1 increases with smaller b1. Actually reserves below
b1 give profit 920-b1, so smaller b1 -> larger profit per reserve, but fewer
reserves below.) Need to enumerate all rectangle representatives.

So the full optimum over R is found by sampling (b1, b2) at every cell-rep of
the form (r_i + 1e-6, r_j + 1e-6) for r_i, r_j in {670, 675, ..., 920} with
r_i <= r_j, plus also (r_i, r_j) and (r_i, r_j + 1e-6) and (r_i + 1e-6, r_j),
to cover every closed-vs-open boundary case.
"""

from ev_engine import ev, RESERVES, SELL


EPS = 1e-6


def all_cell_reps(mu: float):
    """Yield (b1, b2) sample points covering every piecewise-constant cell.

    For b1 we pick:
      - r exactly  (r in (b1, b2)? r > b1?  r < b1?  At b1=r exactly, r is in
        upper bracket since condition is r < b1. So r=b1 puts r in [b1,b2).)
      - r + EPS    (now r < b1 strictly, r is in lower bracket)
    Similarly for b2:
      - r exactly  (r=b2: condition r >= b2 -> "no trade")
      - r + EPS    (r < b2: trade at b2)
      - mu, mu + EPS (penalty switch)
    """
    b1_pts = []
    for r in RESERVES:
        b1_pts.append(r)
        b1_pts.append(r + EPS)
    b2_pts = []
    for r in RESERVES:
        b2_pts.append(r)
        b2_pts.append(r + EPS)
    b2_pts.append(mu)
    b2_pts.append(mu + EPS)
    b2_pts.append(mu - EPS)
    for b1 in b1_pts:
        if b1 < 670 or b1 > 920:
            continue
        for b2 in b2_pts:
            if b2 < b1 or b2 < 670 or b2 > 920:
                continue
            yield b1, b2


def search(mu: float, top_k: int = 20):
    results = []
    for b1, b2 in all_cell_reps(mu):
        v = ev(b1, b2, mu)
        results.append((v, b1, b2))
    results.sort(reverse=True)
    return results[:top_k]


def integer_search(mu: float, top_k: int = 20):
    results = []
    for b1 in range(670, 921):
        for b2 in range(b1, 921):
            v = ev(b1, b2, mu)
            results.append((v, b1, b2))
    results.sort(reverse=True)
    return results[:top_k]


def reserve_only_search(mu: float, top_k: int = 20):
    """Restrict bids to multiples of 5 (the reserve grid itself)."""
    results = []
    for b1 in RESERVES:
        for b2 in RESERVES:
            if b2 < b1:
                continue
            v = ev(b1, b2, mu)
            results.append((v, b1, b2))
    results.sort(reverse=True)
    return results[:top_k]


def main():
    for mu in [855.0, 857.0, 858.0, 859.0, 860.0, 862.0, 865.0]:
        print(f"\n========== mu = {mu} ==========")

        print("Top 10 integer:")
        for v, b1, b2 in integer_search(mu, 10):
            print(f"  ({b1:6.2f},{b2:6.2f})  EV={v:.6f}")

        print("Top 10 reserve-grid (multiples of 5):")
        for v, b1, b2 in reserve_only_search(mu, 10):
            print(f"  ({b1:6.2f},{b2:6.2f})  EV={v:.6f}")

        print("Top 10 fractional (cell reps):")
        for v, b1, b2 in search(mu, 10):
            print(f"  ({b1:9.6f},{b2:9.6f})  EV={v:.6f}")


if __name__ == "__main__":
    main()
