"""Test the L1 momentum / L2-L3 contrarian decomposition.

Key hypothesis: OBI_full (L1+L2+L3) has IC=-0.37 at h=1; OBI_L1 has IC=+0.28.
Net signal = OBI_L1 - OBI_full_or_deep should be very strong predictor.
"""
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load(day):
    p = pd.read_csv(f"{ROOT}/prices_round_3_day_{day}.csv", sep=";")
    return p[p["product"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)

def ic(s, r):
    s = pd.Series(s).fillna(0); r = pd.Series(r).fillna(0)
    if s.std() == 0 or r.std() == 0: return 0.0
    return s.corr(r)

print(f"{'Day':>4} {'Window':>10} {'Signal':>20} {'IC_h1':>8} {'IC_h5':>8} {'IC_h20':>8}")
for day in [0, 1, 2]:
    p = load(day)
    bv1 = p["bid_volume_1"].fillna(0).values
    bv2 = p["bid_volume_2"].fillna(0).values
    bv3 = p["bid_volume_3"].fillna(0).values
    av1 = p["ask_volume_1"].fillna(0).values
    av2 = p["ask_volume_2"].fillna(0).values
    av3 = p["ask_volume_3"].fillna(0).values
    mid = p["mid_price"].values

    obi_l1 = (bv1 - av1) / np.maximum(bv1 + av1, 1)
    obi_l2 = (bv2 - av2) / np.maximum(bv2 + av2, 1)
    obi_l3 = (bv3 - av3) / np.maximum(bv3 + av3, 1)
    obi_deep = (bv2+bv3 - av2-av3) / np.maximum(bv2+bv3+av2+av3, 1)
    obi_full = (bv1+bv2+bv3 - av1-av2-av3) / np.maximum(bv1+bv2+bv3+av1+av2+av3, 1)
    combined = obi_l1 - obi_deep  # bet on L1 push, fade deep imbalance
    combined2 = obi_l1 - 0.5 * obi_deep

    fwd1 = np.zeros_like(mid); fwd1[:-1] = mid[1:] - mid[:-1]
    fwd5 = np.zeros_like(mid); fwd5[:-5] = mid[5:] - mid[:-5]
    fwd20 = np.zeros_like(mid); fwd20[:-20] = mid[20:] - mid[:-20]

    for win_name, sl in [("full", slice(None, -20)), ("first1k", slice(0, 980))]:
        for sname, sig in [("OBI_L1", obi_l1), ("OBI_L2", obi_l2), ("OBI_L3", obi_l3),
                           ("OBI_deep", obi_deep), ("OBI_full", obi_full),
                           ("L1-deep", combined), ("L1-0.5deep", combined2)]:
            print(f"{day:>4} {win_name:>10} {sname:>20} "
                  f"{ic(sig[sl], fwd1[sl]):>+8.4f} "
                  f"{ic(sig[sl], fwd5[sl]):>+8.4f} "
                  f"{ic(sig[sl], fwd20[sl]):>+8.4f}")
        print()

# What about L2 specifically? Often the "wall" sits at L2.
print("\n=== Where does mass sit? L1 vs L2 vs L3 volume distribution ===")
for day in [0, 1, 2]:
    p = load(day)
    bv1 = p["bid_volume_1"].fillna(0).values
    bv2 = p["bid_volume_2"].fillna(0).values
    bv3 = p["bid_volume_3"].fillna(0).values
    av1 = p["ask_volume_1"].fillna(0).values
    av2 = p["ask_volume_2"].fillna(0).values
    av3 = p["ask_volume_3"].fillna(0).values
    print(f"Day {day} avg bid vol L1/L2/L3: {bv1.mean():.1f}/{bv2.mean():.1f}/{bv3.mean():.1f}")
    print(f"Day {day} avg ask vol L1/L2/L3: {av1.mean():.1f}/{av2.mean():.1f}/{av3.mean():.1f}")
