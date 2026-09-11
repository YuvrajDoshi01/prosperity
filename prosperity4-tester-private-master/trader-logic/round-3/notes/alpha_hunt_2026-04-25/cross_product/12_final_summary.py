"""Final EV ranking. Each hypothesis: day-2 1k tick PnL at full position size, with cross-day check."""
import pickle, numpy as np, pandas as pd, os
from scipy.stats import norm

DATA = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"
OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"

def load_book(day):
    p = pd.read_csv(os.path.join(DATA, f"prices_round_3_day_{day}.csv"), sep=";")
    out = {}
    for col in ["bid_price_1","ask_price_1","bid_volume_1","ask_volume_1","mid_price"]:
        out[col] = p.pivot(index="timestamp", columns="product", values=col)
    return out

print("="*70)
print(" FINAL CROSS-PRODUCT ALPHA EV RANKING (day-2 1k-tick)")
print("="*70)

# --- H1: SHORT deep-OTM vouchers (VEV_5500, VEV_6000, VEV_6500) ---
# VEV_5500 day 2 1k: started 6.5 ended 7.0 (drift +0.5 hurt naked short -150).
# But: post ASK at 7 on every tick. If MM hits, we short at 7. Cover later when price drops.
# Theoretical fair value: ~0.13 with 5-day expiry. Expected gain ~$6/contract holding to expiry.
# But submission scored on 1k ticks day 2 only -> mark-to-market. Need MTM gain.
# VEV_5500: 6.5->7.0, naked short 300 = -$150
# VEV_6000: 0.5->0.5, naked short = $0 (can short at bid=0 only, no premium)
# VEV_6500: 0.5->0.5, naked short = $0
# But: we can EARN bid-ask spread by MM-ing them. Width = 1, captured = ~$1 per fill, ~10 fills/1k tick = $10.
print("\n[H1] SHORT deep-OTM vouchers + MM tail vouchers")
for day in [0,1,2]:
    p = load_book(day)
    if day==2:
        for k in p: p[k] = p[k].iloc[:1000]
    for K in [5500, 6000, 6500]:
        col = f"VEV_{K}"
        if col not in p["mid_price"]: continue
        m = p["mid_price"][col]
        drift = m.iloc[-1] - m.iloc[0]
        size = 300
        naked_short_pnl = -drift*size
        # MM ed: post bid - 1 + ask + 1 -> capture spread on each fill. Assume 5% take rate.
        spread = (p["ask_price_1"][col] - p["bid_price_1"][col]).mean()
        print(f"  Day {day} {col}: drift={drift:+.1f} naked_short_PnL=${naked_short_pnl:+.0f} spread={spread:.2f}")

# --- H2: Delta-hedged voucher long (gamma scalp) ---
# From 07: K=5200 +$713 1k day 2; K=5400 +$282; K=5100 +$279; K=5000 +$206.
# Sum of all = ~$1500 day 2. Cross-day: ?
print("\n[H2] Delta-hedged long voucher (continuous rehedge with VFE) — see 07_delta_hedge_pnl.py")

# Same for day 0 and 1
def bs_call(s,k,t,sig):
    if sig<=0: return max(s-k,0)
    d1 = (np.log(s/k) + 0.5*sig*sig*t)/(sig*np.sqrt(t)); d2 = d1 - sig*np.sqrt(t)
    return s*norm.cdf(d1)-k*norm.cdf(d2)
def bs_delta(s,k,t,sig):
    if sig<=0 or t<=0: return 1.0 if s>k else 0.0
    d1 = (np.log(s/k) + 0.5*sig*sig*t)/(sig*np.sqrt(t))
    return norm.cdf(d1)
from scipy.optimize import brentq

T_DAYS = {0: 8/250, 1: 7/250, 2: 6/250}
for day in [0,1,2]:
    p = load_book(day)
    if day==2:
        for k in p: p[k] = p[k].iloc[:1000]
    S = p["mid_price"]["VELVETFRUIT_EXTRACT"].values
    T = T_DAYS[day]
    sums = {}
    for K in [5000, 5100, 5200, 5300, 5400]:
        col = f"VEV_{K}"
        if col not in p["mid_price"]: continue
        C = p["mid_price"][col].values
        if C[0]<=0: continue
        try:
            iv0 = brentq(lambda s: bs_call(S[0], K, T, s)-C[0], 1e-3, 3.0)
        except: continue
        cash = -300*C[0]
        s_pos = -bs_delta(S[0],K,T,iv0)*300
        cash -= s_pos*S[0]
        for i in range(1,len(S)):
            new_d = bs_delta(S[i],K,T-i/(250*1000) if day==2 else T-i/(250*10000), iv0)
            new_s = -new_d*300
            cash -= (new_s-s_pos)*S[i]
            s_pos = new_s
        cash += 300*C[-1] + s_pos*S[-1]
        sums[K] = cash
    total = sum(sums.values())
    print(f"  Day {day} delta-hedged sum K=[5000-5400]: ${total:+.0f}  detail={ {k:int(v) for k,v in sums.items()} }")

# --- H3: HP spread=17 trigger spread between HP and VFE ---
print("\n[H3] HP spread=17 -> next 10 ticks HP/VFE move (already captured by single-asset HP strategy)")

# --- H4: VFE OBI -> VEV_4000 next-tick mid (lead/lag from 03) ---
# corr(VFE_OBI, VEV_4000_ret_t+1) = 0.129 day 2 1k. beta=0.465 per OBI unit.
# OBI ranges [-1, 1]. Per-tick edge = 0.465 * 0.5 * 1 = 0.23 per favorable tick.
# Voucher MM with VFE OBI as fair-value tilt: shift FV by sign(OBI) * 1 -> +1 per favorable side per fill.
# Estimate: 100 fills * $0.5 edge = $50/1k.
print("\n[H4] VFE OBI tilt voucher quotes — small +$50/1k tick edge")

# --- H5: VEV_4000 OBI -> VEV_5000 next-tick (corr 0.147 beta 1.86) ---
# That's the STRONGEST cross-product signal. VEV_4000 OBI predicts VEV_5000 NEXT tick by ~beta*OBI.
# OBI std=0.5, so prediction std = 0.93 per tick. Use to skew VEV_5000 quotes.
# Capacity: VEV_5000 has 0 trades in 1k day 2 trade list — but mid moves +$26 on day 2 full.
print("\n[H5] VEV_4000 OBI → VEV_5000 next-tick (corr=0.147) — best cross-voucher signal but VEV_5000 ZERO TRADES on day 2 1k")

# --- H6: Sticky-strike vol regime / ATM IV ---
# corr(dS, dIV) is NEGATIVE -0.4 to -0.5 -> when VFE goes up, IV goes DOWN. Sticky-strike pricing.
# Trade: long VFE + short ATM straddle (vega exposure). On day 2 +28 drift -> IV drops.
# Hard to size in 1k (tight), but as signal for re-pricing voucher quote: when VFE rises sharply, lower IV used in BS = lower fair value.
print("\n[H6] Sticky-strike vol: corr(dS,dIV)=-0.5. Adaptive IV for voucher quoting +$small")

# --- H7: Same-tick instantaneous "delta-hedged" of VEV_4000 with short VFE ---
# Day 0/1/2 hedged_PnL = $0 because beta drops C and S 1:1 perfectly. No gamma scalp at K=4000 (delta=1).
print("\n[H7] VEV_4000 (deep ITM) delta-hedge: $0/day - no gamma. Skip.")

# --- H8: Long VEV_5500 short delta*VFE - rises volatility play ---
# K=5500 day 2: drift +0.5 (slightly up). hedged for tiny delta=0.05: 300*0.5 - 300*0.05*(-3.5) = +150 + 53 = +203
# Day 0 K=5500: drift -1, beta=0.06, vfe drift -6. hedged = -300 + 0.06*300*6 = -300+108 = -192
# Day 1: drift -1, beta=0.05, vfe +20.5. hedged = -300 - 0.05*300*20.5 = -300 - 308 = -608
# NOT direction-robust. Skip.

# --- H9: Settlement drift exposure - long max-delta basket ---
# Limit 200 VFE long (200*0.066%*5260 = $7) vs limit 300 VEV_4000 long (drift VFE * delta=0.74 * 300 = -3.5*0.74*300 = -777)
# VEV_4000 alone gives 1.1x VFE exposure with limit 300 vs 200. But day 0 was negative.
# Direction-robust = NO.
print("\n[H9] Long-VEV_4000 settlement-drift exposure — fails day-0 robustness check")

# --- H10: Cross-product MM (VFE+vouchers simultaneously) ---
# Trivial: independent MM accounting. Already done for VFE in v11. Nets ~$1940 VFE + voucher pieces.
# Adding voucher MM with VFE-OBI tilt should add ~$300-500 from H4.
print("\n[H10] Add VFE-OBI-tilted voucher MM on top of v11: est +$300-500 incremental")
