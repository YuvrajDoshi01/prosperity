"""H13 settlement arb on deep OTM vouchers. VEV_6000/6500 trade at price 0-1; if they settle at 0 at expiry,
shorting them is risk-free (assuming VFE never reaches 6000)."""
import pickle, numpy as np, pandas as pd, os

OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"
with open(os.path.join(OUT, "data.pkl"), "rb") as f:
    D = pickle.load(f)

mids = D["mids"]; trades = D["trades"]

print("=== Deep-OTM voucher (K>=5500) bid/ask/trade prices across all 3 days ===")
import pandas as pd
DATA = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"
for day in [0,1,2]:
    p = pd.read_csv(os.path.join(DATA, f"prices_round_3_day_{day}.csv"), sep=";")
    for k in [5500, 6000, 6500]:
        sub = p[p["product"]==f"VEV_{k}"]
        if len(sub)==0: continue
        b = sub["bid_price_1"].dropna(); a = sub["ask_price_1"].dropna()
        m = sub["mid_price"].dropna()
        print(f"  Day {day} VEV_{k}: bid range [{b.min()},{b.max()}] mid range [{m.min()},{m.max()}] ask [{a.min()},{a.max()}]")

print("\n=== VFE max range per day ===")
for day in [0,1,2]:
    s = mids[day]["VELVETFRUIT_EXTRACT"]
    print(f"  Day {day}: min={s.min():.1f} max={s.max():.1f}")

# Trade volume in deep OTM
print("\n=== Trade volume in deep-OTM vouchers (1k window day 2) ===")
t2 = trades[2]
t2_1k = t2[t2["timestamp"]<=99900]
for k in [5500, 6000, 6500]:
    sub = t2_1k[t2_1k["symbol"]==f"VEV_{k}"]
    print(f"  VEV_{k}: n_trades={len(sub)} total_qty={sub['quantity'].sum()} prices={sub['price'].unique()[:5]}")

# Capacity for short:
# Limit 300, ask = 1 (we sell into ask=1 by being bid=1?... or sell into bid=0 means receive 0)
# Actually we sell at bid - if there's a buyer at bid=0, no profit. If we POST ask=1 and someone takes, +$1*N.
# But also: we can SELL at 1 if MM bot has bid=1 (rarely). Need to inspect actual bids.
print("\n=== Day 2 VEV_6000 1k bid/ask distribution ===")
p = pd.read_csv(os.path.join(DATA, f"prices_round_3_day_2.csv"), sep=";")
p1k = p[p["timestamp"]<=99900]
for k in [5500, 6000, 6500]:
    sub = p1k[p1k["product"]==f"VEV_{k}"]
    print(f"  VEV_{k}: bid_price_1.value_counts()={sub['bid_price_1'].value_counts().head(3).to_dict()} ask={sub['ask_price_1'].value_counts().head(3).to_dict()}")
    print(f"           bid_volume_1.sum={sub['bid_volume_1'].sum()} ask_volume_1.sum={sub['ask_volume_1'].sum()}")

# Most direct alpha: SHORT vouchers expected to expire OTM, and capture the time decay/premium.
# Day 2 VEV_5500: starts at 6.5, ends at 7.0. Day 0 8.5->7.5. Day 1 7.5->6.5. So mean reverts ~7.
# At expiry day 5: T=5/250 from submission, VFE~5260. P(VFE>5500) is what?
# Realized vol 0.11/yr. sigma over 5 days = 0.11*sqrt(5/250) = 0.0156, so std = 5260*0.0156 = ~82.
# Move to 5500 = 240 = 2.93 sigma. P=0.17%. Expected payoff = 0.0017*82*phi(2.93) ~ trivial.
# So VEV_5500 fair value ~0.5, market trades 6-8. SHORT IT.
# Position 300 short, cover at 0 -> +$6.5*300 = $1950 over 5 days. But submission only runs 1k ticks day 2.
# In 1k day 2 ticks: VEV_5500 starts 6.5 ends 7.0, drift +0.5*300 = -$150 if naked short.
# Theta decay over 100 ticks: theta = -BS_theta. At ATM=K-S=240, IV=0.20, very tiny.

# VEV_6000/6500: ALWAYS bid=0. We can't sell into bid=0 except if we accept $0. Need someone to BUY @1.
print("\n=== VEV_6000/6500 trades in 1k day2 — at what price? ===")
for k in [6000, 6500]:
    sub = t2_1k[t2_1k["symbol"]==f"VEV_{k}"]
    print(f"  VEV_{k}: trades at prices {sub['price'].unique()} qty_total={sub['quantity'].sum()} n_trades={len(sub)}")
    # Direction
    print(f"     buyer_NAs={sub['buyer'].isna().sum()} (we'd be on this side selling)")
    print(f"     seller_NAs={sub['seller'].isna().sum()}")
