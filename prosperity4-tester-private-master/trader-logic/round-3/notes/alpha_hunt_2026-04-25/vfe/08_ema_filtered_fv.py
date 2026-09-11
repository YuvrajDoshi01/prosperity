"""EMA-filtered fair value vs Wall Mid IC; spread-conditional signals."""
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

def ema(x, alpha):
    out = np.zeros_like(x, dtype=float)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1-alpha) * out[i-1]
    return out

# Test EMA(mid) - mid as a signal
print("=== EMA-mid deviation as predictor (first 1k) ===")
print(f"{'Day':>4} {'alpha':>6} {'IC_h1':>8} {'IC_h5':>8} {'IC_h20':>8}")
for day in [0, 1, 2]:
    p = load(day)
    mid = p["mid_price"].values
    fwd1 = np.zeros_like(mid); fwd1[:-1] = mid[1:] - mid[:-1]
    fwd5 = np.zeros_like(mid); fwd5[:-5] = mid[5:] - mid[:-5]
    fwd20 = np.zeros_like(mid); fwd20[:-20] = mid[20:] - mid[:-20]
    for alpha in [0.05, 0.1, 0.2, 0.3]:
        e = ema(mid, alpha)
        # Sign convention: if mid > ema, recent up-move; predicts next direction
        sig = mid - e
        sl = slice(0, 1000)
        print(f"{day:>4} {alpha:>6.2f} {ic(sig[sl], fwd1[sl]):>+8.4f} {ic(sig[sl], fwd5[sl]):>+8.4f} {ic(sig[sl], fwd20[sl]):>+8.4f}")
    print()

# Spread state conditional analysis
print("\n=== Spread-conditional next-tick return mean & std (full day) ===")
print(f"{'Day':>4} {'Spread':>7} {'N':>6} {'Mean_r1':>10} {'Std_r1':>8}")
for day in [0, 1, 2]:
    p = load(day)
    mid = p["mid_price"].values
    bp1 = p["bid_price_1"].values; ap1 = p["ask_price_1"].values
    spread = ap1 - bp1
    fwd1 = np.zeros_like(mid); fwd1[:-1] = mid[1:] - mid[:-1]
    for s in [2, 3, 4, 5, 6, 7, 8, 10]:
        mask = spread[:-1] == s
        if mask.sum() < 5: continue
        r = fwd1[:-1][mask]
        print(f"{day:>4} {s:>7} {mask.sum():>6} {r.mean():>+10.4f} {r.std():>8.3f}")
    print()

# Wall_mid - mid: gap forecasts gap closure?
print("\n=== Wall-mid gap mean-reversion check ===")
for day in [0, 1, 2]:
    p = load(day)
    bp1 = p["bid_price_1"].values; bv1 = p["bid_volume_1"].fillna(0).values
    bp2 = p["bid_price_2"].fillna(0).values; bv2 = p["bid_volume_2"].fillna(0).values
    bp3 = p["bid_price_3"].fillna(0).values; bv3 = p["bid_volume_3"].fillna(0).values
    ap1 = p["ask_price_1"].values; av1 = p["ask_volume_1"].fillna(0).values
    ap2 = p["ask_price_2"].fillna(0).values; av2 = p["ask_volume_2"].fillna(0).values
    ap3 = p["ask_price_3"].fillna(0).values; av3 = p["ask_volume_3"].fillna(0).values
    mid = p["mid_price"].values
    bv_arr = np.column_stack([bv1, bv2, bv3])
    bp_arr = np.column_stack([bp1, bp2, bp3])
    av_arr = np.column_stack([av1, av2, av3])
    ap_arr = np.column_stack([ap1, ap2, ap3])
    wall_b = bp_arr[np.arange(len(bv1)), np.argmax(bv_arr, axis=1)]
    wall_a = ap_arr[np.arange(len(av1)), np.argmax(av_arr, axis=1)]
    wall_mid = (wall_b + wall_a) / 2
    gap = wall_mid - mid
    fwd5 = np.zeros_like(mid); fwd5[:-5] = mid[5:] - mid[:-5]
    fwd20 = np.zeros_like(mid); fwd20[:-20] = mid[20:] - mid[:-20]
    fwd100 = np.zeros_like(mid); fwd100[:-100] = mid[100:] - mid[:-100]
    sl = slice(0, 1000)
    print(f"Day {day} (first 1k): IC(gap, h5)={ic(gap[sl], fwd5[sl]):+.4f}, h20={ic(gap[sl], fwd20[sl]):+.4f}, h100={ic(gap[sl], fwd100[sl]):+.4f}")

# Microprice deeper
print("\n=== Microprice with L2/L3 weights ===")
print(f"{'Day':>4} {'Variant':>20} {'IC_h1':>8} {'IC_h5':>8} {'IC_h20':>8}")
for day in [0, 1, 2]:
    p = load(day)
    bp1 = p["bid_price_1"].values; bv1 = p["bid_volume_1"].fillna(0).values
    bp2 = p["bid_price_2"].fillna(0).values; bv2 = p["bid_volume_2"].fillna(0).values
    ap1 = p["ask_price_1"].values; av1 = p["ask_volume_1"].fillna(0).values
    ap2 = p["ask_price_2"].fillna(0).values; av2 = p["ask_volume_2"].fillna(0).values
    mid = p["mid_price"].values
    fwd1 = np.zeros_like(mid); fwd1[:-1] = mid[1:] - mid[:-1]
    fwd5 = np.zeros_like(mid); fwd5[:-5] = mid[5:] - mid[:-5]
    fwd20 = np.zeros_like(mid); fwd20[:-20] = mid[20:] - mid[:-20]

    # micro_l1 (already tested)
    m1 = (bp1*av1 + ap1*bv1) / np.maximum(av1+bv1, 1) - mid
    # micro_l1+l2
    m12 = ((bp1*av1 + bp2*av2) + (ap1*bv1 + ap2*bv2)) / np.maximum(av1+av2+bv1+bv2, 1) - mid
    # micro l1+l2+l3
    bp3v = p["bid_price_3"].fillna(0).values; bv3 = p["bid_volume_3"].fillna(0).values
    ap3v = p["ask_price_3"].fillna(0).values; av3 = p["ask_volume_3"].fillna(0).values
    m123 = ((bp1*av1 + bp2*av2 + bp3v*av3) + (ap1*bv1 + ap2*bv2 + ap3v*bv3)) / np.maximum(av1+av2+av3+bv1+bv2+bv3, 1) - mid
    sl = slice(0, 1000)
    for nm, sg in [("micro_L1", m1), ("micro_L1+L2", m12), ("micro_L1+L2+L3", m123)]:
        print(f"{day:>4} {nm:>20} {ic(sg[sl], fwd1[sl]):>+8.4f} {ic(sg[sl], fwd5[sl]):>+8.4f} {ic(sg[sl], fwd20[sl]):>+8.4f}")
    print()
