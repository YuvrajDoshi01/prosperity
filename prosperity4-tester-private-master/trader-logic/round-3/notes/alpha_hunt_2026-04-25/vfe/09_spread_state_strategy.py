"""Spread=2 long, spread=3 short — execute via aggressive cross-spread.

Spread=2 cells: ~3.4% of all ticks, mean fwd ret = +1.07
Spread=3 cells: ~3.4% of all ticks, mean fwd ret = -0.85

Sample size: 320-350 per day → not noise.
EV per signal trigger: $1 mid-cents × 200 = $2 per share but limited by liquidity at L1 ~38 contracts.

Strategy: when spread=2, BUY 38 at ask. Hold 1 tick, sell at next mid. Reverse for spread=3.
"""
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load(day):
    p = pd.read_csv(f"{ROOT}/prices_round_3_day_{day}.csv", sep=";")
    return p[p["product"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)

def simulate(day, hold=1, ticks=1000, qty_per_trigger=20):
    """Spread=2 → BUY qty at ask; close after 'hold' ticks at bid.
       Spread=3 → SELL qty at bid; close at ask after hold."""
    p = load(day)
    mid = p["mid_price"].values
    bp1 = p["bid_price_1"].values; ap1 = p["ask_price_1"].values
    bv1 = p["bid_volume_1"].fillna(0).values; av1 = p["ask_volume_1"].fillna(0).values
    spread = ap1 - bp1
    pos = 0; cash = 0.0; LIMIT = 200
    pending_close = []  # (close_tick, qty_signed)
    fills = 0
    n = min(ticks, len(mid)-hold-1)
    for i in range(n):
        # Close any positions
        new_pending = []
        for ct, q in pending_close:
            if ct == i:
                if q > 0:  # sell at bid
                    cash += q * bp1[i]; pos -= q
                else:
                    cash += q * ap1[i]; pos -= q
            else:
                new_pending.append((ct, q))
        pending_close = new_pending
        # New triggers
        if spread[i] == 2:
            q = min(qty_per_trigger, int(av1[i]), LIMIT - pos)
            if q > 0:
                cash -= q * ap1[i]; pos += q; fills += q
                pending_close.append((i+hold, q))
        elif spread[i] == 3:
            q = min(qty_per_trigger, int(bv1[i]), LIMIT + pos)
            if q > 0:
                cash += q * bp1[i]; pos -= q; fills += q
                pending_close.append((i+hold, -q))
    pnl = cash + pos * mid[n]
    return pnl, pos, fills

print("=== Spread-state strategy (long spread=2 / short spread=3) ===")
print(f"{'qty/trig':>9} {'hold':>5} {'PnL_d0':>10} {'PnL_d1':>10} {'PnL_d2':>10} {'Sum':>10}")
for qty in [10, 20, 38, 100, 200]:
    for hold in [1, 3, 5]:
        results = []
        for day in [0, 1, 2]:
            pnl, _, _ = simulate(day, hold=hold, ticks=1000, qty_per_trigger=qty)
            results.append(pnl)
        print(f"{qty:>9} {hold:>5} {results[0]:>+10.1f} {results[1]:>+10.1f} {results[2]:>+10.1f} {sum(results):>+10.1f}")

# What if we also act on the L1 ask volume / bid volume directly?
# Spread=2 means one side raised by 1; check WHICH side.
# spread=2 with bp1 raised vs ap1 lowered should differ
print("\n=== Decompose spread=2 by L1 volume change ===")
for day in [0, 1, 2]:
    p = load(day)
    mid = p["mid_price"].values
    bp1 = p["bid_price_1"].values; ap1 = p["ask_price_1"].values
    bv1 = p["bid_volume_1"].fillna(0).values; av1 = p["ask_volume_1"].fillna(0).values
    spread = ap1 - bp1
    fwd1 = np.zeros_like(mid); fwd1[:-1] = mid[1:] - mid[:-1]
    # For spread=2, classify by who moved: bp1 went up or ap1 went down vs prev tick
    bp_diff = np.diff(bp1, prepend=bp1[0])
    ap_diff = np.diff(ap1, prepend=ap1[0])
    mask_s2 = spread == 2
    bp_up = mask_s2 & (bp_diff > 0)
    ap_dn = mask_s2 & (ap_diff < 0)
    print(f"Day {day} (full): spread=2 N={mask_s2.sum()}, bp_up_only N={bp_up.sum()} mean_fwd1={fwd1[bp_up].mean():+.3f}, ap_dn_only N={ap_dn.sum()} mean_fwd1={fwd1[ap_dn].mean():+.3f}")
    mask_s3 = spread == 3
    bp_dn = mask_s3 & (bp_diff < 0)
    ap_up = mask_s3 & (ap_diff > 0)
    print(f"Day {day} (full): spread=3 N={mask_s3.sum()}, bp_dn_only N={bp_dn.sum()} mean_fwd1={fwd1[bp_dn].mean():+.3f}, ap_up_only N={ap_up.sum()} mean_fwd1={fwd1[ap_up].mean():+.3f}")

# Hold longer — when spread=2 fires, it's actually preceded by mean-reversion. Best hold?
print("\n=== Mean fwd return at h=1,2,3,5,10 after spread=2 trigger ===")
for day in [0, 1, 2]:
    p = load(day)
    mid = p["mid_price"].values
    bp1 = p["bid_price_1"].values; ap1 = p["ask_price_1"].values
    spread = ap1 - bp1
    for s_val in [2, 3]:
        mask = spread == s_val
        rets = []
        for h in [1, 2, 3, 5, 10]:
            fwd = np.zeros_like(mid)
            fwd[:-h] = mid[h:] - mid[:-h]
            rets.append(fwd[mask[:-h]].mean() if mask[:-h].sum() else 0)
        print(f"Day {day} spread={s_val}: " + " ".join(f"h{h}={r:+.3f}" for h, r in zip([1,2,3,5,10], rets)))
