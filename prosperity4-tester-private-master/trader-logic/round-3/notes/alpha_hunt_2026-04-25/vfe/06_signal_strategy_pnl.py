"""Convert top signals into actual $ PnL via realistic simulator.

Strategy: per-tick target = sign(signal) * LIMIT, walk toward target with edge=2 limit.
Compare h=1 vwmid_dev, wall_mid_dev, OBI_L1, OBI_L1-deep, against buy-and-hold.

We assume entry at ask (cross spread), exit at bid (cross spread). MM bot replenishes 20/tick.
"""
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load(day):
    p = pd.read_csv(f"{ROOT}/prices_round_3_day_{day}.csv", sep=";")
    return p[p["product"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)

def gen_signals(p):
    bp1 = p["bid_price_1"].values; bv1 = p["bid_volume_1"].fillna(0).values
    bp2 = p["bid_price_2"].fillna(0).values; bv2 = p["bid_volume_2"].fillna(0).values
    bp3 = p["bid_price_3"].fillna(0).values; bv3 = p["bid_volume_3"].fillna(0).values
    ap1 = p["ask_price_1"].values; av1 = p["ask_volume_1"].fillna(0).values
    ap2 = p["ask_price_2"].fillna(0).values; av2 = p["ask_volume_2"].fillna(0).values
    ap3 = p["ask_price_3"].fillna(0).values; av3 = p["ask_volume_3"].fillna(0).values
    mid = p["mid_price"].values

    obi_l1 = (bv1 - av1) / np.maximum(bv1 + av1, 1)
    obi_deep = (bv2+bv3 - av2-av3) / np.maximum(bv2+bv3+av2+av3, 1)
    combined = obi_l1 - obi_deep

    bv_arr = np.column_stack([bv1, bv2, bv3])
    bp_arr = np.column_stack([bp1, bp2, bp3])
    av_arr = np.column_stack([av1, av2, av3])
    ap_arr = np.column_stack([ap1, ap2, ap3])
    wall_b = bp_arr[np.arange(len(bv1)), np.argmax(bv_arr, axis=1)]
    wall_a = ap_arr[np.arange(len(av1)), np.argmax(av_arr, axis=1)]
    wall_mid = (wall_b + wall_a) / 2 - mid

    bv_tot = bv1+bv2+bv3; av_tot = av1+av2+av3
    num = bp1*bv1 + bp2*bv2 + bp3*bv3 + ap1*av1 + ap2*av2 + ap3*av3
    den = bv_tot + av_tot
    vwmid_dev = np.where(den > 0, num/np.maximum(den, 1), mid) - mid

    return {
        "OBI_L1": obi_l1, "OBI_L1-deep": combined,
        "wall_mid_dev": wall_mid, "vwmid_dev": vwmid_dev,
    }, bp1, ap1, mid

def simulate(p, sig_arr, threshold, rate=20, ticks=1000):
    """Trade against signal: target=+200 if sig>threshold, -200 if sig<-threshold."""
    sigs, bp1, ap1, mid = gen_signals(p)
    sig = sig_arr
    pos, cash = 0, 0.0
    LIMIT = 200
    n = min(ticks, len(mid)-1)
    for i in range(n):
        if sig[i] > threshold: target = LIMIT
        elif sig[i] < -threshold: target = -LIMIT
        else: target = 0
        diff = target - pos
        q = max(-rate, min(rate, diff))
        if q > 0:
            cash -= q * ap1[i]; pos += q
        elif q < 0:
            cash -= q * bp1[i]; pos += q
    pnl = cash + pos * mid[n]
    return pnl, pos

print("=== Day 2 first 1k tick PnL by signal (rate=20/tick) ===")
print(f"{'Signal':>16} {'Threshold':>10} {'PnL_d0':>10} {'PnL_d1':>10} {'PnL_d2':>10} {'Sum':>10}")
for sname in ["OBI_L1", "OBI_L1-deep", "wall_mid_dev", "vwmid_dev"]:
    for thresh_pct in [0.0, 0.1, 0.2, 0.3, 0.5]:
        # Need to set threshold relative to signal scale; use percentile
        results = []
        for day in [0, 1, 2]:
            p = load(day)
            sigs, _, _, _ = gen_signals(p)
            sig = sigs[sname]
            # Use absolute std-based threshold
            thresh = thresh_pct * np.std(sig[:1000])
            pnl, _ = simulate(p, sig, thresh, rate=20, ticks=1000)
            results.append(pnl)
        print(f"{sname:>16} {thresh_pct:>10.2f} {results[0]:>+10.1f} {results[1]:>+10.1f} {results[2]:>+10.1f} {sum(results):>+10.1f}")

# Try aggressive cross-spread rates
print("\n=== Same but higher trade rate (rate=200/tick = unlimited target seek) ===")
for sname in ["OBI_L1", "OBI_L1-deep", "wall_mid_dev", "vwmid_dev"]:
    for thresh_pct in [0.5, 1.0]:
        results = []
        for day in [0, 1, 2]:
            p = load(day)
            sigs, _, _, _ = gen_signals(p)
            sig = sigs[sname]
            thresh = thresh_pct * np.std(sig[:1000])
            pnl, _ = simulate(p, sig, thresh, rate=200, ticks=1000)
            results.append(pnl)
        print(f"{sname:>16} {thresh_pct:>10.2f} {results[0]:>+10.1f} {results[1]:>+10.1f} {results[2]:>+10.1f} {sum(results):>+10.1f}")

# Passive MM with signal-based skew (place inside spread aggressively in signal direction)
print("\n=== Passive MM: post bid+1/ask-1 skewed by signal sign ===")
def simulate_mm(p, sig_arr, ticks=1000, skew_thresh=0.5):
    """Post passive 200@bid+1, 200@ask-1; if sig strong, drop opposite side."""
    sigs, bp1, ap1, mid = gen_signals(p)
    bp1_arr = bp1; ap1_arr = ap1
    bv1 = p["bid_volume_1"].fillna(0).values
    av1 = p["ask_volume_1"].fillna(0).values
    pos, cash = 0, 0.0
    LIMIT = 200
    fills = 0
    sig_std = np.std(sig_arr[:ticks])
    for i in range(min(ticks, len(mid)-1)):
        s = sig_arr[i]
        # post bid at bp1+1 (penny), ask at ap1-1
        bid_qty = min(20, LIMIT - pos)  # passive buy size capped
        ask_qty = min(20, LIMIT + pos)
        # Asymmetry by signal
        if s > skew_thresh * sig_std:
            ask_qty = 0  # skip selling, ride up
        elif s < -skew_thresh * sig_std:
            bid_qty = 0
        # Estimate fill: probability ~ taker arrival hits inside spread (~30% from R1)
        # Use a simple: prob(fill on each side) = 0.3
        if bid_qty > 0:
            f = int(0.3 * bid_qty)  # heuristic
            cash -= f * (bp1_arr[i] + 1); pos += f; fills += f
        if ask_qty > 0:
            f = int(0.3 * ask_qty)
            cash += f * (ap1_arr[i] - 1); pos -= f; fills += f
    pnl = cash + pos * mid[min(ticks, len(mid)-1)]
    return pnl, pos, fills

for sname in ["OBI_L1", "OBI_L1-deep", "wall_mid_dev", "vwmid_dev"]:
    results = []
    for day in [0, 1, 2]:
        p = load(day)
        sigs, _, _, _ = gen_signals(p)
        pnl, pos, fills = simulate_mm(p, sigs[sname], ticks=1000, skew_thresh=0.5)
        results.append(pnl)
    print(f"{sname:>16}    PnL: d0={results[0]:>+8.1f} d1={results[1]:>+8.1f} d2={results[2]:>+8.1f} sum={sum(results):>+8.1f}")
