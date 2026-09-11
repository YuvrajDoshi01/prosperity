"""H9: Passive MM on OTM strikes — POST inside MM bot's spread.
On 5400/5500: spread is 1-2 wide, all flow is sells.
If we POST a bid at best_bid+1 (penny inside), we attract the seller flow.
Then mid moves and we exit at FAIR.

But wait: trades on 5400 day 2 had n=80 with avg price 12.86, range 7-19.
The ENTIRE day 2 (10k ticks) had 80 sell trades. Per 1k-tick = 8 trades = 8 contracts.
Mean price 12.86 vs day-2 last mid 20.0 = +$7 per contract -> $56 total.

But we'd need to BE THE TOP BID. We can capture 8 contracts max for 1k-tick.

Better: trade flow on 5500 = 94/day = 9.4/1k = 9 contracts.
Trade flow on 5300 = 45/day = 4.5/1k = 4 contracts.
Trade flow on 5400 = 80/day = 8/1k = 8 contracts.

Total max passive sale flow ~21 contracts/1k. Edge per contract = (round-end mid - bid_price).

Compute by stepping through trades and assuming if we post at bid+1, we steal the trade.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

for d in [0,1,2]:
    pr = load_prices(d)
    tr = load_trades(d)
    if d==2:
        tr = tr[tr["timestamp"]<100000]
        pr = pr[pr["timestamp"]<100000]
    # Last day-2 mid is the round-end approximation
    # For estimate of EV: use VEV mid at final tick of FULL day 2 as fair value.
    pr_full = load_prices(d)
    last_mid = pr_full[pr_full["product"]==UND]["mid_price"].iloc[-1]

    print(f"\n=== Day {d}: terminal VFE = {last_mid} ===")
    total_pnl_est = 0
    total_qty = 0
    for k in [5200,5300,5400,5500,6000,6500]:
        v = f"VEV_{k}"
        # Last mid of voucher
        vlast = pr_full[pr_full["product"]==v]["mid_price"].iloc[-1]
        intrinsic = max(0, last_mid-k)
        # Trades — these are seller trades hitting some bid
        sub = tr[tr["symbol"]==v]
        n = len(sub)
        qty = sub["quantity"].sum()
        avg_p = sub["price"].mean() if n>0 else 0
        # If we had been the top bid by 1, we'd pay avg_p+1 and get vlast at end
        ev_per = vlast - (avg_p + 1)
        pnl_est = qty * ev_per
        # Cap by 300 limit
        capped_qty = min(qty, 300)
        capped_pnl = capped_qty * ev_per
        print(f"  {v}: n_trades={n} qty_total={qty} avg_px={avg_p:.2f} | "
              f"vlast={vlast:.1f} intrinsic={intrinsic:.1f} | "
              f"EV/contract={ev_per:+.2f} TotalPnL=${pnl_est:+.0f} (capped@300=${capped_pnl:+.0f})")
        total_pnl_est += capped_pnl
        total_qty += capped_qty
    print(f"  TOTAL across OTM strikes: ${total_pnl_est:+.0f} on {total_qty} contracts")
