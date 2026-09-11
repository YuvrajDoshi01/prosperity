"""H6: Long voucher + delta-hedged in VFE = gamma scalping.
Day 2 1k-tick: VFE moves 5267 -> 5295. Compute realized gamma PnL across strikes.
Use BS with rolling IV and r=0, compare PnL to theta cost.

Important: vouchers are 5/250 ~ 0.02 yr at submission. Day 2 is 6/250.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

# For each strike, compute realized gamma PnL = 0.5 * gamma * (dS)^2 summed
# vs theta cost = -theta * dt summed
# This estimates EV of long-vol play.

for d in [0,1,2]:
    mid = pivot_mid(d)
    if d==2:
        mid = mid[mid.index<100000]
    S = mid[UND].values
    n = len(S)
    T0 = TTE[d]
    # Daily TTE decreases. Within a 10k-tick day, dt = 1/250 yr.
    print(f"\n=== Day {d}, n={n}, S range [{S.min():.0f}, {S.max():.0f}], drift={S[-1]-S[0]:+.0f} ===")
    print(f"  realized vol annualized: {np.std(np.diff(np.log(S)))*np.sqrt(250*n):.4f} (over day)")
    rv_daily = np.std(np.diff(np.log(S)))*np.sqrt(n)  # daily
    print(f"  realized vol daily: {rv_daily:.4f}")
    # Implied vol: invert ATM mid
    for k in [5000,5100,5200,5300,5400,5500]:
        v = f"VEV_{k}"
        if v not in mid.columns: continue
        # Use first tick IV
        c0 = mid[v].iloc[0]
        s0 = S[0]
        iv = implied_vol(c0, s0, k, T0)
        # Final
        cN = mid[v].iloc[-1]
        sN = S[-1]
        ivN = implied_vol(cN, sN, k, T0 - n/250/n)  # approx final TTE
        # gamma scalp PnL estimate: 0.5 * realized_var - 0.5*iv^2 (annualized) integrated
        rv_ann = np.std(np.diff(np.log(S)))*np.sqrt(250*n)
        scalp_per_share = 0.5*(rv_ann**2 - iv**2)*T0 * s0**2  # for 1 share of underlying-equivalent (gamma_$)
        print(f"  {v}: IV0={iv:.3f} IVf={ivN:.3f} | C0={c0:.1f} Cf={cN:.1f} | "
              f"realised-implied vol gap = {rv_ann-iv:+.3f}")
