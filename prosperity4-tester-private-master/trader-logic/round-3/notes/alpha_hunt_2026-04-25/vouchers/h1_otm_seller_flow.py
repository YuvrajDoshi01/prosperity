"""H1: OTM seller-only flow exploitation
H2: Voucher decays to 0 — collect penny bids
H5: Static no-arb — vertical/butterfly
H13: Round-end fair value: last day-2 mid vs zero?
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

print("="*70)
print("H1: OTM seller flow + H13 round-end payoff")
print("="*70)

# For each strike, look at price trajectory across days, plus terminal mid.
for d in [0,1,2]:
    mid = pivot_mid(d)
    last_mid = mid.iloc[-1]
    first_mid = mid.iloc[0]
    last_und = last_mid[UND]
    print(f"\nDay {d}: last VFE mid = {last_und:.1f}, first VFE = {first_mid[UND]:.1f}")
    rows = []
    for k in STRIKES:
        v = f"VEV_{k}"
        if v not in mid.columns: continue
        intrinsic = max(0, last_und - k)
        rows.append({
            "strike": k,
            "first_mid": first_mid[v],
            "last_mid": last_mid[v],
            "intrinsic_at_close": intrinsic,
            "last_minus_intrinsic": last_mid[v] - intrinsic,
        })
    print(pd.DataFrame(rows).to_string(index=False))

# Trades on OTM strikes — buyer/seller direction
print("\n" + "="*70)
print("OTM strike trade flow (5300/5400/5500/6000/6500)")
print("="*70)
for d in [0,1,2]:
    tr = load_trades(d)
    for k in [5300,5400,5500,6000,6500]:
        v = f"VEV_{k}"
        sub = tr[tr["symbol"]==v]
        if len(sub)==0:
            print(f"day{d} {v}: 0 trades"); continue
        # buyer="" => external/MM-bot; seller="" => external too
        # In Prosperity convention: empty = anonymous; "SUBMISSION" = us
        n_buy_anon = (sub["buyer"]=="").sum() if "buyer" in sub else 0
        avg_p = sub["price"].mean()
        n = len(sub)
        # Empirically all trades show buyer/seller blanks; we infer from price
        print(f"day{d} {v}: n={n}, avg_px={avg_p:.2f}, min={sub['price'].min()}, max={sub['price'].max()}, qty_sum={sub['quantity'].sum()}")
