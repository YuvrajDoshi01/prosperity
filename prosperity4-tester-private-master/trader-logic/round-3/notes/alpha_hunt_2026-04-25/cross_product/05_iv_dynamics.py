"""H7+H9: Volatility transmission and sticky-strike vs sticky-delta.
- Roll IV per voucher (BS, r=0, T=6/250 day 2).
- Does VFE move predict IV change next tick?
- Does HP vol spike predict VFE vol spike?"""
import pickle, numpy as np, pandas as pd, os
from scipy.stats import norm
from scipy.optimize import brentq

OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"
with open(os.path.join(OUT, "data.pkl"), "rb") as f:
    D = pickle.load(f)

mids = D["mids"]
VOUCHERS = D["vouchers"]
T_DAYS = {0: 8/250, 1: 7/250, 2: 6/250}

def bs_call(S,K,T,sig):
    if sig<=0 or T<=0: return max(S-K,0)
    d1 = (np.log(S/K) + 0.5*sig*sig*T)/(sig*np.sqrt(T))
    d2 = d1 - sig*np.sqrt(T)
    return S*norm.cdf(d1) - K*norm.cdf(d2)

def implied_vol(c,S,K,T):
    if c <= max(S-K,0)+1e-3: return np.nan
    if c >= S: return np.nan
    try:
        return brentq(lambda s: bs_call(S,K,T,s)-c, 1e-4, 5.0, maxiter=50)
    except: return np.nan

# Compute IV time series for ATM-ish strikes day 2 1k
day = 2; T = T_DAYS[day]
m2 = mids[day].iloc[:1000]
S2 = m2["VELVETFRUIT_EXTRACT"].values

iv_data = {}
print(f"=== IV time series day 2, T={T:.4f} ===")
for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500]:
    col = f"VEV_{k}"
    if col not in m2: continue
    C = m2[col].values
    ivs = np.array([implied_vol(C[i], S2[i], k, T) for i in range(len(C))])
    valid = ~np.isnan(ivs)
    if valid.sum()<100: continue
    iv_data[k] = ivs
    print(f"  K={k}: IV mean={np.nanmean(ivs):.3f} std={np.nanstd(ivs):.3f} valid={valid.sum()}/{len(ivs)}")

# Sticky-strike vs sticky-delta: does dIV correlate with dS at SAME strike?
print("\n=== dIV[K] vs dS regression (sticky-strike if beta=0; sticky-delta if dIV moves with S) ===")
dS = np.diff(S2)
for k, ivs in iv_data.items():
    div = np.diff(ivs)
    mask = ~np.isnan(div)
    if mask.sum()<50: continue
    r = np.corrcoef(dS[mask], div[mask])[0,1]
    beta = np.cov(dS[mask], div[mask])[0,1] / np.var(dS[mask])
    print(f"  K={k}: corr(dS,dIV)={r:+.3f} beta={beta:+.5f}")

# HP vol -> VFE vol transmission. Use realized vol over rolling 20-tick windows.
print("\n=== HP rolling vol -> VFE rolling vol next-window correlation ===")
for day in [0,1,2]:
    m = mids[day].iloc[:1000] if day==2 else mids[day]
    rh = m["HYDROGEL_PACK"].diff()
    rv = m["VELVETFRUIT_EXTRACT"].diff()
    vh = rh.rolling(20).std()
    vv = rv.rolling(20).std()
    # Same-tick
    same = vh.corr(vv)
    # Lead: HP_vol[t] vs VFE_vol[t+5]
    lead5 = vh.iloc[:-5].corr(vv.iloc[5:].reset_index(drop=True))
    lead1 = vh.shift(1).corr(vv)
    print(f"  Day {day}: same-tick rho={same:+.3f} | HP_vol lead VFE_vol by 1: {lead1:+.3f} by 5: {lead5:+.3f}")

# Cross-strike IV smile: when ATM IV moves, do wing IVs move (parallel) or stay?
print("\n=== IV smile rigidity: corr(dIV_K1, dIV_K2) within day 2 ===")
keys = sorted(iv_data.keys())
mat = pd.DataFrame({k: pd.Series(iv_data[k]).diff() for k in keys})
print(mat.corr().round(2).to_string())
