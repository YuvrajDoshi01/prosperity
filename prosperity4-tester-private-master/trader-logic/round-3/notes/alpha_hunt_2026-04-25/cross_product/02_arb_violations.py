"""H2/H3: Vertical spread, butterfly, intrinsic, deep-ITM call ~ underlying parity violations.
Enumerate every tick on day 2 (and 0/1 for robustness). Convert each violation into
$ EV at full size given limits + 1k-tick day 2 only."""
import pickle, numpy as np, pandas as pd, os

OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"
with open(os.path.join(OUT, "data.pkl"), "rb") as f:
    D = pickle.load(f)

VOUCHERS = D["vouchers"]
mids = D["mids"]

def vouch(d, k): return mids[d].get(f"VEV_{k}")

results = {}
for day in [0,1,2]:
    m = mids[day].iloc[:1000].copy() if day == 2 else mids[day].copy()
    S = m["VELVETFRUIT_EXTRACT"]
    rec = []
    # Vertical: C(K1) - C(K2) <= K2-K1, also >= max(0, K2-K1 - small theta drag); lower bound C(K1)>=C(K2)
    for i,k1 in enumerate(VOUCHERS):
        for k2 in VOUCHERS[i+1:]:
            c1 = vouch(day,k1); c2 = vouch(day,k2)
            if c1 is None or c2 is None: continue
            diff = c1 - c2
            # Upper bound violation: c1-c2 > k2-k1 -> sell c1, buy c2, lock K2-K1
            up_viol = (diff - (k2-k1)).clip(lower=0)
            # Monotonicity: c1 < c2 -> sell c2, buy c1
            mono_viol = (c2 - c1).clip(lower=0)
            if up_viol.sum() > 0 or mono_viol.sum() > 0:
                rec.append((f"vert_{k1}_{k2}", up_viol.gt(0).sum(), up_viol.mean(),
                            mono_viol.gt(0).sum(), mono_viol.mean()))
    # Butterfly: C(k1)-2C(k2)+C(k3) >= 0
    for i,k1 in enumerate(VOUCHERS):
        for j,k2 in enumerate(VOUCHERS[i+1:], i+1):
            for k3 in VOUCHERS[j+1:]:
                c1=vouch(day,k1); c2=vouch(day,k2); c3=vouch(day,k3)
                if c1 is None or c2 is None or c3 is None: continue
                bf = c1 - 2*c2 + c3
                neg = (-bf).clip(lower=0)
                if neg.gt(0).sum()>0:
                    rec.append((f"bfly_{k1}_{k2}_{k3}", neg.gt(0).sum(), neg.mean(), 0, 0))
    # Deep-ITM parity: K=4000, S~5260 -> C(4000) >= S - 4000
    for k in [4000, 4500]:
        c = vouch(day,k)
        if c is None: continue
        intrinsic = (S - k).clip(lower=0)
        viol = (intrinsic - c).clip(lower=0)  # C < intrinsic -> buy C, short S, exercise
        rec.append((f"intrinsic_{k}", viol.gt(0).sum(), viol.mean(), 0, 0))
    # Synthetic forward: 4000-5000 spread should track S-4500-ish? Check S - C(4000) vs -K + (low TV)
    # Actually compute: F_synthetic = K + (C(K_low) - C(K_high)) ... if both ITM
    # For 4000-6500: at expiry payoff(4000)-payoff(6500) = max(S-4000,0)-max(S-6500,0)
    # If S in [4000,6500]: = S - 4000. So C(4000)-C(6500) ~ S - 4000 - tv.
    c40 = vouch(day,4000); c65 = vouch(day,6500)
    if c40 is not None and c65 is not None:
        synth_S = (c40 - c65) + 4000
        gap = synth_S - S  # positive = synth too high vs spot
        rec.append((f"synthF_4000-6500", (gap.abs()>5).sum(), gap.mean(), 0, gap.std()))

    df = pd.DataFrame(rec, columns=["pair","n_viol","mean_viol_or_gap","n_mono","mono_mean"])
    df = df.sort_values("mean_viol_or_gap", ascending=False)
    print(f"\n=== Day {day} (1k ticks if day2) ===")
    print(df.head(15).to_string(index=False))
    results[day] = df

# Day-2 EV: top vertical violation in $ * size
print("\n--- Day 2 1k-tick top vertical/butterfly EV at full size ---")
df2 = results[2]
for _, row in df2.head(8).iterrows():
    name = row["pair"]; mean = row["mean_viol_or_gap"]; n = row["n_viol"]
    # voucher limit 300; can short 300 of high-K, long 300 of low-K
    # Per-tick EV if violation realized: mean_viol * 300 contracts (if we hold to expiry+slip)
    # But violation is mid-vs-mid; to capture need crossing book. Conservative: half the gap * size
    ev_full = mean * 300
    ev_partial = mean * 0.5 * 300
    print(f"  {name}: n={n}/1000 mean={mean:.2f} | full_size_EV=${ev_full:.0f} half-cap=${ev_partial:.0f}")
