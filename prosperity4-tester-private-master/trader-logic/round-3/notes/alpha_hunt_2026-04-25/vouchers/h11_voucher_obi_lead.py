"""H11: Does voucher OBI lead VFE?
For each voucher, compute OBI_t = (bid_vol1 - ask_vol1)/(bid_vol1+ask_vol1).
Test correlation with VFE return at horizons 1, 5, 10, 50 ticks.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

for d in [2]:
    df = load_prices(d)
    df = df[df["timestamp"]<100000]
    bv = df.pivot(index="timestamp", columns="product", values="bid_volume_1")
    av = df.pivot(index="timestamp", columns="product", values="ask_volume_1")
    mid = df.pivot(index="timestamp", columns="product", values="mid_price")
    obi = (bv - av) / (bv + av)
    vfe_ret = mid[UND].diff().shift(-1)  # next-tick return
    print(f"Day {d} 1k-tick: voucher OBI -> next-tick VFE return correlation")
    for v in VOUCHERS + [UND]:
        if v not in obi.columns: continue
        c = np.corrcoef(obi[v].values[:-1], vfe_ret.values[:-1])[0,1]
        # Also h=5
        h5 = (mid[UND].shift(-5) - mid[UND]).iloc[:-5]
        c5 = np.corrcoef(obi[v].values[:-5], h5.values)[0,1]
        h20 = (mid[UND].shift(-20) - mid[UND]).iloc[:-20]
        c20 = np.corrcoef(obi[v].values[:-20], h20.values)[0,1]
        print(f"  {v}: corr(obi, dVFE_t+1)={c:+.3f}  h=5: {c5:+.3f}  h=20: {c20:+.3f}")
    # Also: does VEV mid lead VFE? compute VEV-derived implied S vs VFE itself
    print("\nVEV mid 'implied S' lead test")
    # For ATM strikes: implied S = K + C - P (no put). Can't use parity.
    # But signed deviation: VEV change should track VFE change * delta. Excess = info?
    # Compute residual: dVEV - delta * dVFE. Lag corr with future dVFE.
    K_test = [5000, 5100, 5200, 5300]
    for k in K_test:
        v = f"VEV_{k}"
        delta_emp = ((mid[v] - mid[v].shift(1)) / (mid[UND] - mid[UND].shift(1)).replace(0,np.nan)).rolling(50).median()
        delta_emp = delta_emp.fillna(0.5)
        residual = mid[v].diff() - delta_emp * mid[UND].diff()
        h5 = (mid[UND].shift(-5) - mid[UND])
        valid = (~residual.isna()) & (~h5.isna())
        c = np.corrcoef(residual[valid].values, h5[valid].values)[0,1]
        print(f"  K={k}: corr(VEV residual_t, dVFE_t+5) = {c:+.3f}")
