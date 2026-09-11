"""H10: Intrinsic-floor violations and put-call style: C(K) >= max(S-K, 0).
On the BOOK (executable): is best_ask of VEV_K below max(S - K, 0)?
This is the INTRINSIC TAKE that R3_v11 already does on 4000/4500.
Quantify: Day 2 1k-tick total $$ available.
Use S = best_bid of VFE (worst-case for arb, since to monetize buy voucher and SHORT VFE).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

for d in [0,1,2]:
    df = load_prices(d)
    if d==2:
        df = df[df["timestamp"]<100000]
    aa = df.pivot(index="timestamp", columns="product", values="ask_price_1")
    bb = df.pivot(index="timestamp", columns="product", values="bid_price_1")
    av = df.pivot(index="timestamp", columns="product", values="ask_volume_1")
    bv = df.pivot(index="timestamp", columns="product", values="bid_volume_1")
    print(f"\n=== Day {d} (n={len(df.timestamp.unique())}) Intrinsic-arb opportunities ===")
    for k in STRIKES:
        v = f"VEV_{k}"
        if v not in aa.columns: continue
        # buy voucher at best_ask, sell VFE at best_bid (locks intrinsic)
        # arb if ask_v + k < bid_VFE  =>  bid_VFE - ask_v > k
        # PnL per pair = bid_VFE - ask_v - k (always positive)
        pnl_per = bb[UND] - aa[v] - k
        mask = pnl_per > 0
        if mask.sum()>0:
            # cap by min volumes
            sz = np.minimum(av[v][mask].values, bv[UND][mask].values).clip(0, 300)
            total = (pnl_per[mask].values * sz).sum()
            print(f"  {v}: ask+K < bid_VFE in {mask.sum()} ticks, "
                  f"mean PnL/pair=${pnl_per[mask].mean():.2f}, total=${total:.0f}")
        # Reverse: bid_v + k > ask_VFE  =>  short voucher, long VFE
        rev = aa[UND] - bb[v] - k
        rev_mask = rev < 0  # short v get bid_v, buy VFE pay ask_VFE: NetCF = bid_v - ask_VFE.
        # Payoff at expiry: -max(S-K,0) + S = min(S, K). Always >= 0.
        # So short_v_long_VFE pays: bid_v - ask_VFE + min(S_T, K).
        # Floor scenario (S_T very high) = bid_v - ask_VFE + K.
        # So arb requires bid_v + K > ask_VFE  =>  bid_v - ask_VFE + K > 0.
        floor_pnl = bb[v] + k - aa[UND]
        # Worst case payoff at expiry if ITM: K paid. If OTM (S<K), get S, but premiums fixed.
        # Conservative: the deal has min payoff bid_v - (ask_VFE - K). If positive, free money.
        rev_mask2 = floor_pnl > 0
        if rev_mask2.sum()>0:
            sz = np.minimum(bv[v][rev_mask2].values, av[UND][rev_mask2].values).clip(0,300)
            total = (floor_pnl[rev_mask2].values * sz).sum()
            print(f"     reverse arb (sell v + buy VFE): {rev_mask2.sum()} ticks, mean=${floor_pnl[rev_mask2].mean():.2f}, total=${total:.0f}")
