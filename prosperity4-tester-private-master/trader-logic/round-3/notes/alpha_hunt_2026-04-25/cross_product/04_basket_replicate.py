"""H3+H13: Static portfolio replication. Build basket of vouchers w_k * C(K_k) ~ S.
Solve for weights via OLS over day 0 (training). Test PnL on day 1, day 2.
Also: with vfe drift +28 on day 2, what basket maximizes drift exposure within 300/voucher limit?"""
import pickle, numpy as np, pandas as pd, os
from numpy.linalg import lstsq

OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"
with open(os.path.join(OUT, "data.pkl"), "rb") as f:
    D = pickle.load(f)

mids = D["mids"]
VOUCHERS = D["vouchers"]

# Use returns to fit beta (delta proxy)
print("=== Per-day per-voucher delta proxy (beta of dC/dS) ===")
betas_per_day = {}
for day in [0,1,2]:
    m = mids[day]
    rs = m["VELVETFRUIT_EXTRACT"].diff().fillna(0)
    rec = {}
    for k in VOUCHERS:
        col = f"VEV_{k}"
        if col not in m: continue
        rc = m[col].diff().fillna(0)
        if rs.std()<1e-6: continue
        beta = np.cov(rs, rc)[0,1] / np.var(rs)
        rec[k] = beta
    betas_per_day[day] = rec
    print(f"  Day {day}: {rec}")

# Day-2 1k-tick test: long basket with delta=1 vs short VFE 1
m2 = mids[2].iloc[:1000]
S2 = m2["VELVETFRUIT_EXTRACT"]

# Strategy A: long N units of VEV_4000 (highest delta, ~1.0) -> hedged short S?
# But goal is CROSS alpha: replication PnL = drift on basket - drift on VFE = should be near 0 if delta-1 perfect.
# More interesting: which voucher has BEST delta/cost ratio for capturing drift?
print("\n=== Day-2 1k-tick: long 300 units of voucher K, no hedge: $ PnL from drift only ===")
for k in VOUCHERS:
    col = f"VEV_{k}"
    if col not in m2: continue
    drift_per_contract = m2[col].iloc[-1] - m2[col].iloc[0]
    print(f"  VEV_{k}: drift_per_contract={drift_per_contract:+.2f}, full_size_PnL=${drift_per_contract*300:+.0f}")

# Compare to VFE long 200 (limit 200)
drift_vfe = m2["VELVETFRUIT_EXTRACT"].iloc[-1] - m2["VELVETFRUIT_EXTRACT"].iloc[0]
print(f"  VFE long 200: drift={drift_vfe:+.2f}, full_size_PnL=${drift_vfe*200:+.0f}")

# Capital efficiency: drift_per_contract / abs(mid)
print("\n=== Drift % per contract (signal/cost) day 2 1k ===")
for k in VOUCHERS:
    col = f"VEV_{k}"
    if col not in m2: continue
    o = m2[col].iloc[0]; cl = m2[col].iloc[-1]
    if o == 0: continue
    pct = (cl-o)/o * 100
    print(f"  VEV_{k}: {o:.1f} -> {cl:.1f} ({pct:+.2f}%) limit300={pct*300:.1f}%-units")

o=m2["VELVETFRUIT_EXTRACT"].iloc[0]; cl=m2["VELVETFRUIT_EXTRACT"].iloc[-1]
print(f"  VFE: {o:.1f} -> {cl:.1f} ({(cl-o)/o*100:+.3f}%) limit200")

# Key: for ATM-OTM voucher, leverage = S/C ~ 5260/100 = 50x for VEV_5200. Drift X% in S -> X*delta*S/C in C
# Delta-weighted long basket vs short VFE: PnL = drift_VFE * (sum w_k * delta_k - 1) but w_k is in shares of C
# Long vouchers w_k contracts each, total delta exposure D = sum w_k * delta_k
# Cost = sum w_k * C_k. To replicate 200 VFE long (delta exposure = 200), need sum w_k * delta_k = 200.

print("\n=== Direction-robust check: same long-VEV_4000 basket on day 0 (down -6) ===")
for day in [0,1,2]:
    m = mids[day]
    if day==2: m=m.iloc[:1000]
    drift_4000 = m["VEV_4000"].iloc[-1] - m["VEV_4000"].iloc[0]
    drift_5000 = m["VEV_5000"].iloc[-1] - m["VEV_5000"].iloc[0] if "VEV_5000" in m else 0
    drift_5300 = m["VEV_5300"].iloc[-1] - m["VEV_5300"].iloc[0] if "VEV_5300" in m else 0
    print(f"  Day {day}: VEV_4000 drift {drift_4000:+.1f} | VEV_5000 {drift_5000:+.1f} | VEV_5300 {drift_5300:+.1f}")

# Cross-asset: short VFE long VEV_4000 (long synthetic put = K - cash + something)
# Actually: short S, long C(K) = long P(K) + K (deferred). On day 2, drift_S = +28, drift_C = +27.5 -> net +28-27.5 = +0.5/unit. Tiny.
print("\n=== Pair: long VEV_K short delta*VFE (per-day drift residual) ===")
for day in [0,1,2]:
    m = mids[day]
    if day==2: m=m.iloc[:1000]
    s = m["VELVETFRUIT_EXTRACT"]
    rs = s.diff().fillna(0)
    print(f"  Day {day} (drift VFE={s.iloc[-1]-s.iloc[0]:+.1f}):")
    for k in [4000, 5000, 5100, 5200, 5300]:
        col=f"VEV_{k}";
        if col not in m: continue
        c = m[col]
        beta = np.cov(rs, c.diff().fillna(0))[0,1]/np.var(rs) if rs.var()>0 else 0
        # PnL of LONG 300 voucher SHORT (300*beta) VFE
        dvfe = s.iloc[-1]-s.iloc[0]; dc = c.iloc[-1]-c.iloc[0]
        pnl_per_300_voucher = 300*dc - 300*beta*dvfe
        print(f"    K={k} beta={beta:.3f} dC={dc:+.2f} hedged_PnL=${pnl_per_300_voucher:+.0f}")
