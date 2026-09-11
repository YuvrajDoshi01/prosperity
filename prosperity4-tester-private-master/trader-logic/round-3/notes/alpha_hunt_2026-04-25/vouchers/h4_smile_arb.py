"""H4: Static no-arb violations: vertical spread, butterfly, monotonicity.
Test on day 2 first 1k ticks.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

for d in [0,1,2]:
    mid = pivot_mid(d)
    if d==2:
        mid = mid[mid.index<100000]
    print(f"\n=== Day {d} (n={len(mid)}) ===")
    # Monotonicity: C(K1) >= C(K2) for K1<K2
    pairs = [(STRIKES[i], STRIKES[i+1]) for i in range(len(STRIKES)-1)]
    print("Monotonicity violations C(K1) < C(K2):")
    for k1,k2 in pairs:
        v1,v2 = f"VEV_{k1}", f"VEV_{k2}"
        if v1 not in mid.columns or v2 not in mid.columns: continue
        viol = (mid[v1] < mid[v2]).sum()
        if viol>0:
            print(f"  {v1}<{v2}: {viol} ticks (out of {len(mid)})")
    # Vertical spread bound: C(K1) - C(K2) <= K2 - K1   (upper bound)
    # And C(K1) - C(K2) >= max(0, ...) lower
    print("Vertical spread upper bound violations C(K1)-C(K2) > K2-K1:")
    for k1,k2 in pairs:
        v1,v2 = f"VEV_{k1}", f"VEV_{k2}"
        if v1 not in mid.columns or v2 not in mid.columns: continue
        diff = mid[v1] - mid[v2]
        bound = k2 - k1
        viol = (diff > bound).sum()
        if viol>0:
            mean_excess = (diff[diff>bound] - bound).mean()
            print(f"  {v1}-{v2} > {bound}: {viol} ticks, mean excess={mean_excess:.2f}")
    # Butterfly: C(K1) - 2*C(K2) + C(K3) >= 0   (convexity)
    print("Butterfly convexity violations:")
    for i in range(len(STRIKES)-2):
        k1,k2,k3 = STRIKES[i], STRIKES[i+1], STRIKES[i+2]
        v1,v2,v3 = f"VEV_{k1}",f"VEV_{k2}",f"VEV_{k3}"
        if any(v not in mid.columns for v in [v1,v2,v3]): continue
        bf = mid[v1] - 2*mid[v2] + mid[v3]
        viol = (bf<0).sum()
        if viol>0:
            mean_bf = bf[bf<0].mean()
            print(f"  bf({k1},{k2},{k3}): {viol} ticks neg, mean={mean_bf:.2f} (max viol={bf.min():.2f})")
        else:
            print(f"  bf({k1},{k2},{k3}): clean (min={bf.min():.2f}, mean={bf.mean():.2f})")
