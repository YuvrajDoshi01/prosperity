"""Validate the spread=2/ap_dn signal SPECIFICALLY in first 1k ticks per day."""
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load(day):
    p = pd.read_csv(f"{ROOT}/prices_round_3_day_{day}.csv", sep=";")
    return p[p["product"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)

print("=== First 1k tick spread-state breakdown ===")
print(f"{'Day':>4} {'condition':>30} {'N':>5} {'mean_h1':>8} {'std':>8}")
for day in [0, 1, 2]:
    p = load(day)
    mid = p["mid_price"].values[:1001]
    bp1 = p["bid_price_1"].values[:1001]
    ap1 = p["ask_price_1"].values[:1001]
    spread = ap1 - bp1
    bp_diff = np.diff(bp1, prepend=bp1[0])
    ap_diff = np.diff(ap1, prepend=ap1[0])
    fwd1 = np.diff(mid, append=mid[-1])
    for label, mask in [
        ("spread=2 all", spread == 2),
        ("spread=2 ap_dn", (spread == 2) & (ap_diff < 0)),
        ("spread=2 bp_up", (spread == 2) & (bp_diff > 0)),
        ("spread=3 all", spread == 3),
        ("spread=3 ap_up", (spread == 3) & (ap_diff > 0)),
        ("spread=3 bp_dn", (spread == 3) & (bp_diff < 0)),
    ]:
        if mask.sum() == 0: continue
        m = fwd1[mask].mean(); s = fwd1[mask].std()
        print(f"{day:>4} {label:>30} {mask.sum():>5} {m:>+8.3f} {s:>8.3f}")
    print()

print("\n=== Signal persistence: fwd return at h=1,3,5,10,20 (first 1k mask) ===")
for day in [0, 1, 2]:
    p = load(day)
    mid = p["mid_price"].values
    bp1 = p["bid_price_1"].values
    ap1 = p["ask_price_1"].values
    spread = ap1 - bp1
    ap_diff = np.diff(ap1, prepend=ap1[0])
    masks = {
        "s=2 ap_dn": (spread == 2) & (ap_diff < 0),
        "s=3 ap_up": (spread == 3) & (ap_diff > 0),
    }
    for lbl, m in masks.items():
        m_1k = m.copy(); m_1k[1000:] = False
        if m_1k.sum() < 3: continue
        rets = []
        for h in [1, 3, 5, 10, 20]:
            mh = m_1k.copy(); mh[len(mid)-h:] = False
            fwd = np.zeros_like(mid, dtype=float)
            fwd[:-h] = mid[h:] - mid[:-h]
            rets.append(fwd[mh].mean() if mh.sum() else 0)
        print(f"Day {day} {lbl} N={m_1k.sum():>3}: " + " ".join(f"h{h}={r:+.2f}" for h, r in zip([1,3,5,10,20], rets)))

# Lift strategy: cross spread by 1 in signal direction (more likely to fill before bot adjusts)
print("\n=== One-tick aggressive lift at ap1-1 (BUY) / bp1+1 (SELL) on signal ===")
def lift(day, ticks=1000, qty=20):
    p = load(day)
    mid = p["mid_price"].values; bp1 = p["bid_price_1"].values; ap1 = p["ask_price_1"].values
    spread = ap1 - bp1
    ap_diff = np.diff(ap1, prepend=ap1[0])
    pos, cash = 0, 0.0; LIMIT = 200
    n = min(ticks, len(mid)-2)
    fills = 0
    for i in range(n):
        bull = (spread[i] == 2 and ap_diff[i] < 0)
        bear = (spread[i] == 3 and ap_diff[i] > 0)
        if bull and pos < LIMIT:
            q = min(qty, LIMIT - pos)
            cash -= q * (ap1[i] - 1); pos += q; fills += q
        elif bear and pos > -LIMIT:
            q = min(qty, LIMIT + pos)
            cash += q * (bp1[i] + 1); pos -= q; fills += q
    pnl = cash + pos * mid[n]
    return pnl, fills

for q in [10, 20, 50]:
    results = [lift(d, qty=q) for d in [0, 1, 2]]
    print(f"qty={q}: d0=pnl{results[0][0]:+.1f}/f{results[0][1]} d1=pnl{results[1][0]:+.1f}/f{results[1][1]} d2=pnl{results[2][0]:+.1f}/f{results[2][1]} sum={sum(r[0] for r in results):+.1f}")
