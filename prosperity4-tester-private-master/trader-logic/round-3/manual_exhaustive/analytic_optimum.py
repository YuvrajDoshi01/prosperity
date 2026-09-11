"""
Analytic global optimum.

Claim: the global optimum sets b2 = mu (or mu+eps, equivalently as EV is
continuous there) and b1 = r* + eps where r* maximizes
   F(r1) = n_below(r1) * (920 - r1) + n_between(r1, mu) * (920 - mu)
over r1 in {670, 675, ..., 920}.

Here n_below(r1) = #{r in reserves : r < r1+eps} and
     n_between(r1, mu) = #{r : r1+eps <= r < mu+eps}.

For r1 = 670 + 5k (k=0..50):
  n_below = k         (reserves 670, 675, ..., 670+5(k-1))
  n_between = #{r : 670+5k <= r < mu+eps} = floor((mu - 670 - 5k)/5) + 1 if applicable.

Actually with b1 = (670+5k) + eps, reserves in [b1, b2=mu+eps) are those r with
  670+5k+eps <= r < mu+eps, equivalently 670+5(k+1) <= r <= floor_to_grid(mu).
For mu in {670+5j} (lying on grid), reserves in [b1, b2) include r=mu since
mu < mu+eps. So n_between = j - k = (mu-670)/5 - k.

For mu NOT on grid, e.g. mu=858: floor((858-670)/5) = 37 -> r=670+5*37=855.
Reserves in [b1, b2=858+eps): r in {670+5(k+1), ..., 855} -> count = 37-k.
(Assuming k+1 <= 37, i.e. k <= 36.)

F(k) = k * (920 - 670 - 5k) + (J - k) * (920 - mu)
where J = floor((mu-670)/5) [or with +1 if mu lies exactly on grid].

= k*(250 - 5k) + (J - k)*(920 - mu)
= 250k - 5k^2 + (920-mu)*J - (920-mu)*k

dF/dk = 250 - 10k - (920 - mu) = (250 - 920 + mu) - 10k = (mu - 670) - 10k
Setting = 0: k* = (mu - 670) / 10

For mu = 858: k* = 18.8 -> k in {18, 19} candidates.
  k=18: b1 = 670 + 90 = 760+eps  (reserve 760)
  k=19: b1 = 670 + 95 = 765+eps  (reserve 765)

F(18) = 18 * (250 - 90) + (37-18) * 62 = 18*160 + 19*62 = 2880 + 1178 = 4058
F(19) = 19 * (250 - 95) + (37-19) * 62 = 19*155 + 18*62 = 2945 + 1116 = 4061

Max at k=19? But our sweep said (760+eps, 860+eps) wins... let me check.

Oh wait, I had b2=860+eps not b2=mu+eps. With b2=860+eps and mu=858, b2>mu so
no-penalty branch. n_between counted reserves in [760+eps, 860+eps) = {765,...,860}.

Actually 860+eps vs mu+eps=858+eps: at b2=860+eps, between-count = 20 (includes 860).
At b2=858+eps, between-count = 19.

So I was solving the wrong thing -- the optimum isn't necessarily at b2=mu+eps.

Let me redo: among ALL b2 = r2+eps for r2 in reserves, with b2 > mu enforcing
no-penalty branch, the EV is
   F(k1, k2) = k1 * (920 - 670 - 5*k1) + (k2 - k1) * (920 - 670 - 5*k2)
where r1 = 670+5*k1, r2 = 670+5*k2, k1 < k2, AND 670+5*k2 >= mu (so b2>mu).

For penalty-branch cells, b2 just-above-mu gives EV continuous = (920-mu).
But if mu falls strictly inside a cell (r2 < mu < r2_next), then b2 = mu+eps
chops the b2 contribution to (920-mu) instead of (920-r2_next).
"""

from ev_engine import ev, RESERVES, SELL


def F_no_penalty(k1, k2):
    """EV when both bids just-above reserve grid; b2 > mu (no penalty)."""
    r1 = 670 + 5 * k1
    r2 = 670 + 5 * k2
    n_below = k1                                 # reserves {670, ..., r1-5}
    n_between = k2 - k1                          # reserves {r1, ..., r2-5}? Wait.
    # b1 = r1+eps -> reserves <b1 are {670, ..., r1} when r1 itself <r1+eps... yes r1<r1+eps.
    # So n_below = k1 + 1.
    # Reserves in [b1, b2) = [r1+eps, r2+eps): {r1+5, r1+10, ..., r2}, count = k2 - k1.
    return (k1 + 1) * (SELL - r1) + (k2 - k1) * (SELL - r2)


def F_penalty(k1, mu):
    """EV when b2 = mu (boundary, both branches agree)."""
    r1 = 670 + 5 * k1
    n_below = k1 + 1
    # reserves in [r1+eps, mu+eps): need r in {r1+5, r1+10, ..., r <= mu}
    n_between = sum(1 for r in RESERVES if r1 + 1e-9 <= r <= mu + 1e-9)
    n_between -= 1 if (r1 in RESERVES and r1 <= mu) else 0  # exclude r1 itself
    n_between = max(0, n_between)
    # actually count reserves r with r1+eps <= r < mu+eps, i.e. r1 < r <= mu (since r is on grid and mu may not be)
    n_between = sum(1 for r in RESERVES if r > r1 and r <= mu)
    return (k1 + 1) * (SELL - r1) + n_between * (SELL - mu)


def find_global_optimum_analytic(mu):
    best = (-1.0, None, None, None)
    # No-penalty (b2 strictly above mu): pick r2 = smallest reserve > mu, or any reserve > mu.
    for k1 in range(0, 51):
        for k2 in range(k1, 51):
            r2 = 670 + 5 * k2
            if r2 + 1e-9 <= mu:
                continue  # b2 = r2+eps would still be < mu -> penalty cell, handle below
            ev_val = F_no_penalty(k1, k2) / 51
            if ev_val > best[0]:
                best = (ev_val, k1, k2, "no-penalty (b2=r2+eps>mu)")
    # Penalty boundary: b2 = mu (limit), profit = 920-mu in between bracket
    for k1 in range(0, 51):
        ev_val = F_penalty(k1, mu) / 51
        if ev_val > best[0]:
            best = (ev_val, k1, None, f"b2=mu={mu}")
    return best


def main():
    print(f"{'mu':>8}  {'k1*':>4}  {'b1*':>10}  {'b2*':>10}  {'EV':>10}  {'branch':>30}")
    for mu in [840, 850, 855, 857, 858, 859, 860, 861, 862, 863, 864, 865, 866, 870, 880, 890]:
        best_v, k1, k2, branch = find_global_optimum_analytic(mu)
        b1 = 670 + 5 * k1 + 1e-7 if k1 is not None else None
        if k2 is not None:
            b2 = 670 + 5 * k2 + 1e-7
        else:
            b2 = mu
        # Cross-check with engine
        v_check = ev(b1, b2, mu)
        print(f"{mu:>8.2f}  {k1:>4}  {b1:>10.4f}  {b2:>10.4f}  {best_v:>10.4f}  {branch:>30}  (eng: {v_check:.4f})")

    # The "Q8" question: at b2=mu exactly, the formula matches no-penalty value 920-mu.
    # CAN WE actually 'ride the mean'? If mu were known precisely, yes, b2=mu maximizes
    # the no-penalty branch (no-penalty: 920-b2 decreases with b2, so smaller b2 is better,
    # but b2 must > mu in penalty rule. At limit b2=mu, value = 920-mu.)
    print("\n--- Q8: 'ride the mean' check ---")
    print("At b2 = mu exactly: profit per between-reserve = 920 - mu (matches no-penalty branch).")
    print("This IS a valid maximum of the no-penalty branch (limit from above).")
    print("Numerically EV is continuous at b2=mu (penalty -> M, no-penalty -> M).")
    for mu in [858.0, 862.0]:
        print(f"  mu={mu}:")
        for delta in [-0.01, -0.001, 0.0, 0.001, 0.01]:
            b2 = mu + delta
            print(f"    b2={b2:.4f}  EV={ev(760.0001, b2, mu):.6f}")


if __name__ == "__main__":
    main()
