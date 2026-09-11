"""H5/H6: Cross-product lead/lag. For each pair (HP,VFE), (VFE,VEV_K), (HP,VEV_K),
compute corr(ret_X[t], ret_Y[t+k]) for k in -10..10. Significant non-zero k = predictive."""
import pickle, numpy as np, pandas as pd, os
from scipy.stats import pearsonr

OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"
with open(os.path.join(OUT, "data.pkl"), "rb") as f:
    D = pickle.load(f)

mids = D["mids"]; obi = D["obi"]
PRODS = D["products"]

def returns(s): return s.diff()

print("=== MID-RETURN LEAD/LAG (Pearson r) ===")
print("Positive lag k = X leads Y by k ticks (X[t] predicts Y[t+k])")
print()

day_results = {}
for day in [0,1,2]:
    m = mids[day]
    if day==2: m = m.iloc[:1000]
    rets = m.diff()
    rec = []
    pairs = [("HYDROGEL_PACK","VELVETFRUIT_EXTRACT")] + \
            [("VELVETFRUIT_EXTRACT", f"VEV_{k}") for k in [4000,4500,5000,5100,5200,5300]] + \
            [("HYDROGEL_PACK", f"VEV_{k}") for k in [4000,5000,5300]]
    for x,y in pairs:
        if x not in rets or y not in rets: continue
        rx = rets[x].fillna(0).values
        ry = rets[y].fillna(0).values
        best_k, best_r = 0, 0
        for k in range(-5, 6):
            if k==0:
                r = np.corrcoef(rx, ry)[0,1]
            elif k>0:
                r = np.corrcoef(rx[:-k], ry[k:])[0,1]
            else:
                r = np.corrcoef(rx[-k:], ry[:k])[0,1]
            if abs(r) > abs(best_r):
                best_r, best_k = r, k
        # also lag-1 specifically
        r1 = np.corrcoef(rx[:-1], ry[1:])[0,1]
        rm1 = np.corrcoef(rx[1:], ry[:-1])[0,1]
        rec.append((f"{x[:6]}->{y[:8]}", best_k, best_r, r1, rm1))
    df = pd.DataFrame(rec, columns=["pair","best_lag","best_r","r_lag+1","r_lag-1"])
    print(f"--- Day {day} ---")
    print(df.to_string(index=False))
    day_results[day] = df

print("\n\n=== OBI[X,t] -> Mid[Y, t+1] regression (does X's OBI predict Y's next-tick mid)? ===")
for day in [2]:
    m = mids[day].iloc[:1000]
    o = obi[day].iloc[:1000]
    rets = m.diff().shift(-1)  # next tick return
    rec = []
    targets = ["VELVETFRUIT_EXTRACT","VEV_4000","VEV_5000","VEV_5300","HYDROGEL_PACK"]
    leaders = ["VELVETFRUIT_EXTRACT","HYDROGEL_PACK","VEV_4000"]
    for src in leaders:
        for tgt in targets:
            if src==tgt: continue
            x = o.get(src); y = rets.get(tgt)
            if x is None or y is None: continue
            mask = x.notna() & y.notna()
            if mask.sum()<100: continue
            r = np.corrcoef(x[mask], y[mask])[0,1]
            # beta scaled
            beta = np.cov(x[mask], y[mask])[0,1] / np.var(x[mask])
            rec.append((src, tgt, r, beta, int(mask.sum())))
    df = pd.DataFrame(rec, columns=["leader","laggard","corr","beta","n"]).sort_values("corr", key=abs, ascending=False)
    print(df.to_string(index=False))

# Same-tick contemporaneous beta (HP vs VFE) - useful as instantaneous beta for hedging
print("\n=== Same-tick beta (instantaneous co-movement, |VFE return| ~ |HP return|) ===")
for day in [0,1,2]:
    m = mids[day]
    if day==2: m=m.iloc[:1000]
    r_hp = m["HYDROGEL_PACK"].diff().fillna(0)
    r_vfe = m["VELVETFRUIT_EXTRACT"].diff().fillna(0)
    if r_hp.std() > 0:
        beta = np.cov(r_hp, r_vfe)[0,1] / np.var(r_hp)
        rho = np.corrcoef(r_hp, r_vfe)[0,1]
        print(f"  Day {day}: rho={rho:.4f} beta_VFE_per_HP={beta:.4f} std_HP={r_hp.std():.2f} std_VFE={r_vfe.std():.2f}")
