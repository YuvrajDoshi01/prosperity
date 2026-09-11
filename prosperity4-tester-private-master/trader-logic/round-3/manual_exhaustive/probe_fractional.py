"""
Q1: Does fractional bidding strictly beat the integer optimum?

Strategy: take μ ∈ {857, 858, 859} and sweep b1, b2 on a fine grid (step 0.01)
in a neighborhood of the integer optimum.

Key insight: for fixed (b1, b2) and uniform discrete reserves, EV is piecewise
constant in (b1, b2): it changes only when b1 crosses a reserve point (multiple
of 5) or when b2 crosses a reserve point or crosses μ.

So we only need to evaluate at:
  - half-open interval midpoints between consecutive reserves
  - just-above-μ for the penalty boundary

We confirm that and find where fractional differs from integer.
"""

from ev_engine import ev, RESERVES, SELL


def fine_sweep(mu: float, step: float = 0.01):
    best = (-1, None, None)
    # b1 in [720, 800], b2 in [800, 900], step
    b1 = 720.0
    while b1 <= 800.0 + 1e-9:
        b2 = max(b1, 800.0)
        while b2 <= 900.0 + 1e-9:
            v = ev(b1, b2, mu)
            if v > best[0] + 1e-12:
                best = (v, b1, b2)
            b2 += step
        b1 += step
    return best


def piecewise_check(mu: float):
    """
    EV is piecewise constant in b1 (changes at multiples of 5 in (670,920]) and
    in b2 (changes at multiples of 5, plus the breakpoint b2 = mu).
    Sample at integer + epsilon, integer, integer - epsilon to characterize jumps.
    """
    print(f"\n--- piecewise check, mu={mu} ---")
    # Sweep b1 along multiples-of-5 boundaries
    print("b1 boundary behavior at b2=866:")
    for r in [765, 766, 767, 770, 771, 772, 775, 776]:
        for delta in [-0.01, 0.0, 0.01]:
            b1 = r + delta
            if b1 < 670 or b1 > 920:
                continue
            print(f"  b1={b1:.2f}  EV={ev(b1, 866, mu):.6f}")
    print("b2 boundary at b1=766:")
    for r in [865, 866, 867, 870, 871]:
        for delta in [-0.01, 0.0, 0.01]:
            b2 = r + delta
            print(f"  b2={b2:.2f}  EV={ev(766, b2, mu):.6f}")
    # Critical: b2 just-above-mu vs at-mu vs just-below
    print(f"b2 at mu boundary (mu={mu}), b1=766:")
    for delta in [-0.01, -0.001, 0.0, 0.001, 0.01]:
        b2 = mu + delta
        print(f"  b2={b2:.4f}  EV={ev(766, b2, mu):.6f}")


def main():
    for mu in [857.0, 858.0, 859.0]:
        print(f"\n=========== mu = {mu} ===========")
        piecewise_check(mu)

    # Targeted: is there a fractional b2 just above mu that beats integer?
    # If mu = 858.0, integer b2 candidates 866 and 868 give EV 81.57 / 80.78. What
    # about b2 = 858.001? It's > mu, so contribution = 920-858.001 = 61.999 per reserve.
    print("\n--- 'just above mu' exploit check (b1=766) ---")
    for mu in [857.0, 858.0, 859.0]:
        for delta in [0.001, 0.01, 0.5, 1.0, 2.0, 5.0, 7.0, 8.0, 10.0]:
            b2 = mu + delta
            v = ev(766, b2, mu)
            print(f"  mu={mu}  b2={b2:.4f}  EV={v:.6f}")

    # Wide grid sanity (coarse): 1.0 step, mu=858
    print("\n--- coarse 1-unit sweep at mu=858, b1 in [720,800], b2 in [800,900] ---")
    best = (-1, None, None)
    for b1 in range(720, 801):
        for b2 in range(max(b1, 800), 901):
            v = ev(b1, b2, 858)
            if v > best[0]:
                best = (v, b1, b2)
    print(f"  best integer: EV={best[0]:.6f}  (b1,b2)={best[1],best[2]}")

    # Same with 0.5 steps
    print("\n--- half-unit sweep at mu=858 ---")
    best = (-1, None, None)
    b1 = 720.0
    while b1 <= 800.0:
        b2 = max(b1, 800.0)
        while b2 <= 900.0:
            v = ev(b1, b2, 858)
            if v > best[0]:
                best = (v, b1, b2)
            b2 += 0.5
        b1 += 0.5
    print(f"  best half-integer: EV={best[0]:.6f}  (b1,b2)={best[1],best[2]}")


if __name__ == "__main__":
    main()
