"""H3: For OTM strikes 5300-6500, all trade flow is SELLS hitting the bid.
If we are the BID at best+1, we pay best_bid+1 and the option expires at intrinsic.
EV per fill = intrinsic_at_expiry - fill_price.
Compute: across 3 days, if we had aggressively sold to ourselves at best_bid every tick,
what's actual EV?
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from h_load import *
import pandas as pd, numpy as np

# Day 2 VFE end mid was 5295.5 -> intrinsic for 5300/5400/5500/6000/6500 is 0.
# For 5200, intrinsic = 95.5
# But round-end isn't day 2 close — it's day 5 (3 more days). Underlying at submission has TTE=5/250.
# IMC convention: positions liquidate at hidden FV at end of round. Best estimate: use last day-2 mid.

# Look at: terminal mid (day 2 last tick) per voucher.
# Compare to: what we'd pay if we BOUGHT at best_ask each tick or POSTED bid at best_bid.

print("Posting bid at best_bid and getting filled by external sellers — EV analysis")
print("Assumption: round-end fair = last day-2 mid (BT convention)")
for d in [0,1,2]:
    df = load_prices(d)
    if d==2:
        df1k = df[df["timestamp"]<100000]
    else:
        df1k = df
    last_und = df[df["product"]==UND]["mid_price"].iloc[-1]
    print(f"\n--- Day {d}, terminal VFE mid = {last_und} ---")
    for k in [5200,5300,5400,5500,6000,6500]:
        v = f"VEV_{k}"
        sub = df1k[df1k["product"]==v]
        last_voucher_mid = df[df["product"]==v]["mid_price"].iloc[-1]
        avg_bb = sub["bid_price_1"].mean()
        avg_aa = sub["ask_price_1"].mean()
        # If we post bid at best_bid+1, fill is uncertain. But "invisible takers" hit our quotes.
        # Approx EV per filled contract = round_end_voucher_mid - (best_bid+1)
        # Use last_voucher_mid as proxy for round-end FV.
        ev_post_bid_plus1 = last_voucher_mid - (avg_bb+1)
        ev_buy_ask = last_voucher_mid - avg_aa
        ev_sell_bid = avg_bb - last_voucher_mid
        # Sell at ask: EV = best_ask - last_mid
        ev_sell_ask = avg_aa - last_voucher_mid
        # Sell at best_ask-1 (post inside)
        ev_sell_ask_m1 = (avg_aa-1) - last_voucher_mid
        print(f"  {v}: bb={avg_bb:.2f} aa={avg_aa:.2f} last={last_voucher_mid:.1f}  "
              f"buy@ask EV={ev_buy_ask:+.2f}  sell@bid EV={ev_sell_bid:+.2f}  "
              f"sell@ask-1 EV={ev_sell_ask_m1:+.2f}")
