"""H4: Delta-hedged voucher PnL = gamma scalp - theta. Simulate per-tick delta-hedge over 1k ticks day 2."""
import pickle, numpy as np, pandas as pd, os
from scipy.stats import norm

OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"
with open(os.path.join(OUT, "data.pkl"), "rb") as f:
    D = pickle.load(f)

mids = D["mids"]
T = 6/250

def bs_delta(S,K,T,sig):
    if sig<=0 or T<=0: return 1.0 if S>K else 0.0
    d1 = (np.log(S/K) + 0.5*sig*sig*T)/(sig*np.sqrt(T))
    return norm.cdf(d1)

def bs_gamma(S,K,T,sig):
    if sig<=0 or T<=0: return 0.0
    d1 = (np.log(S/K) + 0.5*sig*sig*T)/(sig*np.sqrt(T))
    return norm.pdf(d1)/(S*sig*np.sqrt(T))

def bs_theta_per_tick(S,K,T,sig,n_ticks=1000):
    if sig<=0 or T<=0: return 0.0
    d1 = (np.log(S/K) + 0.5*sig*sig*T)/(sig*np.sqrt(T))
    th = -S*norm.pdf(d1)*sig/(2*np.sqrt(T))
    return th * (1/250) / n_ticks  # theta per tick (1k ticks = 1 day)

# Use actual market sigma per strike from start of day 2
m2 = mids[2].iloc[:1000]
S = m2["VELVETFRUIT_EXTRACT"].values
print(f"=== Delta-hedged long N=300 voucher: 1k-tick day 2 PnL ===")
print(f"S0={S[0]:.1f} Send={S[-1]:.1f} drift={S[-1]-S[0]:+.1f}")
realized_var = np.var(np.diff(S)) * 1000  # per-day variance
realized_sig = np.sqrt(realized_var/S[0]**2 * 250)
print(f"Day-2 1k realized sigma (annualized): {realized_sig:.3f}\n")

for k in [4500, 5000, 5100, 5200, 5300, 5400]:
    col=f"VEV_{k}"
    if col not in m2: continue
    C = m2[col].values
    if C[0]<=0: continue
    # back out implied sigma at t=0
    from scipy.optimize import brentq
    def bs_call(s,sig):
        if sig<=0: return max(s-k,0)
        d1=(np.log(s/k)+0.5*sig*sig*T)/(sig*np.sqrt(T)); d2=d1-sig*np.sqrt(T)
        return s*norm.cdf(d1)-k*norm.cdf(d2)
    try:
        iv0 = brentq(lambda s: bs_call(S[0], s)-C[0], 1e-3, 3.0)
    except:
        continue

    # Simulate delta hedge: long 300 voucher, hedge with -delta*300 VFE every tick
    pos_v = 300
    pnl = 0.0
    cash = -300 * C[0]  # paid for vouchers
    s_pos = -bs_delta(S[0],k,T,iv0)*300
    cash -= s_pos * S[0]  # cost of hedge (negative s_pos = short = receive cash)
    for i in range(1, len(S)):
        new_d = bs_delta(S[i],k,T - i/250000,iv0)  # decay T
        new_s_pos = -new_d * 300
        d_s = new_s_pos - s_pos
        cash -= d_s * S[i]
        s_pos = new_s_pos
    # Liquidate at end
    cash += pos_v * C[-1]
    cash += s_pos * S[-1]
    print(f"  K={k} iv0={iv0:.3f}: delta-hedged 1k PnL = ${cash:+.0f}")

# Naive long 300 vouchers no hedge
print("\n=== Naive long 300 voucher, no hedge, 1k-tick day 2 ===")
for k in [4500, 5000, 5100, 5200, 5300, 5400]:
    col=f"VEV_{k}"
    if col not in m2: continue
    C = m2[col].values
    pnl = 300*(C[-1]-C[0])
    print(f"  K={k}: ${pnl:+.0f}")

# Cross-day robustness: long 300 VEV_4000 + short equivalent VFE delta
print("\n=== Cross-day: long 300 VEV_4000 hedged by short delta*300 VFE ===")
for day in [0,1,2]:
    m = mids[day].iloc[:1000] if day==2 else mids[day]
    s = m["VELVETFRUIT_EXTRACT"].values
    if "VEV_4000" not in m: continue
    c = m["VEV_4000"].values
    # delta of 4000 ~ 1 always (deep ITM)
    delta = 1.0
    pnl = 300*(c[-1]-c[0]) - 300*delta*(s[-1]-s[0])
    print(f"  Day {day} (drift VFE {s[-1]-s[0]:+.1f}, drift C {c[-1]-c[0]:+.1f}): hedged_PnL=${pnl:+.0f}")
