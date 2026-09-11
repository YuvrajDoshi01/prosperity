"""IC (forward-return correlation) of candidate VFE signals across days 0/1/2."""
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_vfe(day):
    p = pd.read_csv(f"{ROOT}/prices_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    return p

def signals(p):
    bp1 = p["bid_price_1"].values; bv1 = p["bid_volume_1"].fillna(0).values
    bp2 = p["bid_price_2"].fillna(0).values; bv2 = p["bid_volume_2"].fillna(0).values
    bp3 = p["bid_price_3"].fillna(0).values; bv3 = p["bid_volume_3"].fillna(0).values
    ap1 = p["ask_price_1"].values; av1 = p["ask_volume_1"].fillna(0).values
    ap2 = p["ask_price_2"].fillna(0).values; av2 = p["ask_volume_2"].fillna(0).values
    ap3 = p["ask_price_3"].fillna(0).values; av3 = p["ask_volume_3"].fillna(0).values
    mid = p["mid_price"].values

    # OBI (L1)
    obi_l1 = (bv1 - av1) / np.maximum(bv1 + av1, 1)
    # OBI (L1+L2+L3)
    bv_tot = bv1 + bv2 + bv3
    av_tot = av1 + av2 + av3
    obi_full = (bv_tot - av_tot) / np.maximum(bv_tot + av_tot, 1)
    # Microprice L1
    micro_l1 = (bp1 * av1 + ap1 * bv1) / np.maximum(av1 + bv1, 1) - mid
    # VWMid full book
    num = bp1*bv1 + bp2*bv2 + bp3*bv3 + ap1*av1 + ap2*av2 + ap3*av3
    den = bv_tot + av_tot
    vwmid = np.where(den > 0, num / np.maximum(den, 1), mid) - mid
    # Spread
    spread = ap1 - bp1
    # L1 ask thinning (negative diff = ask volume falling = buying pressure)
    ask_thin = -np.diff(av1, prepend=av1[0])
    bid_thin = -np.diff(bv1, prepend=bv1[0])
    # L1 ask price climbing
    ask_climb = np.diff(ap1, prepend=ap1[0])
    bid_climb = np.diff(bp1, prepend=bp1[0])
    # Wall mid
    bv_arr = np.column_stack([bv1, bv2, bv3])
    bp_arr = np.column_stack([bp1, bp2, bp3])
    av_arr = np.column_stack([av1, av2, av3])
    ap_arr = np.column_stack([ap1, ap2, ap3])
    wall_b = bp_arr[np.arange(len(bv1)), np.argmax(bv_arr, axis=1)]
    wall_a = ap_arr[np.arange(len(av1)), np.argmax(av_arr, axis=1)]
    wall_mid = (wall_b + wall_a) / 2 - mid

    return {
        "obi_l1": obi_l1, "obi_full": obi_full,
        "micro_l1": micro_l1, "vwmid_dev": vwmid,
        "spread": spread, "ask_thin": ask_thin, "bid_thin": bid_thin,
        "ask_climb": ask_climb, "bid_climb": bid_climb,
        "wall_mid_dev": wall_mid,
    }

def ic_for_horizon(sig, fwd_ret, mask=None):
    if mask is not None:
        sig = sig[mask]; fwd_ret = fwd_ret[mask]
    if len(sig) < 50: return np.nan
    s = pd.Series(sig).fillna(0)
    r = pd.Series(fwd_ret).fillna(0)
    if s.std() == 0 or r.std() == 0: return 0.0
    return s.corr(r)

print("=== IC of signals vs forward mid-return (h=1, 5, 20, 100 ticks) — full day ===")
print(f"{'Day':>4} {'Signal':>16} {'IC_h1':>8} {'IC_h5':>8} {'IC_h20':>8} {'IC_h100':>8}")
for day in [0, 1, 2]:
    p = load_vfe(day)
    mid = p["mid_price"].values
    sigs = signals(p)
    for name, sig in sigs.items():
        row = [day, name]
        for h in [1, 5, 20, 100]:
            fwd = np.zeros_like(mid)
            fwd[:-h] = mid[h:] - mid[:-h]
            ic = ic_for_horizon(sig[:-h], fwd[:-h])
            row.append(ic)
        print(f"{row[0]:>4} {row[1]:>16} {row[2]:>+8.4f} {row[3]:>+8.4f} {row[4]:>+8.4f} {row[5]:>+8.4f}")
    print()

print("\n=== IC restricted to first 1000 ticks (website BT window) ===")
print(f"{'Day':>4} {'Signal':>16} {'IC_h1':>8} {'IC_h5':>8} {'IC_h20':>8} {'IC_h100':>8}")
for day in [0, 1, 2]:
    p = load_vfe(day)
    mid = p["mid_price"].values
    sigs = signals(p)
    for name, sig in sigs.items():
        row = [day, name]
        for h in [1, 5, 20, 100]:
            fwd = np.zeros_like(mid)
            fwd[:-h] = mid[h:] - mid[:-h]
            mask = np.zeros_like(fwd, dtype=bool)
            mask[:1000-h] = True
            ic = ic_for_horizon(sig[:-h], fwd[:-h], mask=mask[:-h])
            row.append(ic)
        print(f"{row[0]:>4} {row[1]:>16} {row[2]:>+8.4f} {row[3]:>+8.4f} {row[4]:>+8.4f} {row[5]:>+8.4f}")
    print()
