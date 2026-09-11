"""H12: HP spread=17 regime -> voucher mispricing? Also HP-vol regime -> VFE/voucher action."""
import pickle, numpy as np, pandas as pd, os

OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"
with open(os.path.join(OUT, "data.pkl"), "rb") as f:
    D = pickle.load(f)

mids = D["mids"]; spreads = D["spreads"]

print("=== HP spread distribution by day (1k-tick subset) ===")
for day in [0,1,2]:
    s = spreads[day]["HYDROGEL_PACK"]
    if day==2: s=s.iloc[:1000]
    print(f"  Day {day}: counts {s.value_counts().head(5).to_dict()}")

# When HP spread == 17, what happens to VFE and vouchers next 10 ticks?
print("\n=== HP spread=17 trigger: VFE & voucher 10-tick forward returns ===")
for day in [0,1,2]:
    sp = spreads[day]["HYDROGEL_PACK"]
    m = mids[day]
    if day==2: sp=sp.iloc[:1000]; m=m.iloc[:1000]
    trig = sp[sp==17].index
    if len(trig)==0:
        print(f"  Day {day}: NO spread=17 ticks"); continue
    print(f"  Day {day}: {len(trig)} spread=17 ticks")
    for col in ["VELVETFRUIT_EXTRACT","VEV_4000","VEV_5000","VEV_5300"]:
        if col not in m: continue
        c = m[col]
        future_ret = []
        for t in trig:
            try:
                idx = c.index.get_loc(t)
                if idx+10 < len(c):
                    future_ret.append(c.iloc[idx+10] - c.iloc[idx])
            except: pass
        if future_ret:
            print(f"    {col} 10-tick fwd ret after HP_spread=17: mean={np.mean(future_ret):+.2f} n={len(future_ret)}")

# HP at extreme mid (>10010 or <9990) - does that predict VFE move?
print("\n=== HP extreme mid -> VFE 50-tick fwd return ===")
for day in [0,1,2]:
    m = mids[day]
    if day==2: m=m.iloc[:1000]
    hp = m["HYDROGEL_PACK"]
    vfe = m["VELVETFRUIT_EXTRACT"]
    # When HP > 10010
    high = hp>10010
    low = hp<9990
    if high.sum()>10:
        idx_h = hp[high].index
        rets = []
        for t in idx_h:
            i = vfe.index.get_loc(t)
            if i+50 < len(vfe): rets.append(vfe.iloc[i+50]-vfe.iloc[i])
        print(f"  Day {day} HP>10010 ({high.sum()} ticks): VFE fwd-50 mean={np.mean(rets) if rets else 0:+.2f}")
    if low.sum()>10:
        idx_l = hp[low].index
        rets = []
        for t in idx_l:
            i = vfe.index.get_loc(t)
            if i+50 < len(vfe): rets.append(vfe.iloc[i+50]-vfe.iloc[i])
        print(f"  Day {day} HP<9990 ({low.sum()} ticks): VFE fwd-50 mean={np.mean(rets) if rets else 0:+.2f}")
