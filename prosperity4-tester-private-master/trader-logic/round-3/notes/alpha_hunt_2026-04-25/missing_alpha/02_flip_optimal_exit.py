"""H1b: FLIP exit optimization.
After S7-low trigger covers SHORT and goes LONG +200, what's optimal exit?

The S7-bottom signal fires when price is depressed. Mean reversion target is FV~9990.
But after S7-low we're at p8(500), which is BELOW p50. Reversion target is HIGHER mids.

Test: Hold +200 LONG until mid reaches various targets.
"""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_hp(day):
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "HYDROGEL_PACK"].reset_index(drop=True)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    return p

LIMIT = 200

# Find S17->S7 cover events on each day, then test FLIP holds
for day in [0, 1, 2]:
    p = load_hp(day)
    p["mid_p8"] = p["mid_price"].rolling(500, min_periods=50).quantile(0.08)

    # Identify cover events (S17 entered, S7-low covered)
    state = "FLAT"
    cover_idxs = []
    s17_entry_idx = None
    for i in range(len(p)):
        mid = p.loc[i, "mid_price"]
        spr = p.loc[i, "spread"]
        p8 = p.loc[i, "mid_p8"]
        if state == "FLAT" and spr == 17 and mid > 10010:
            state = "SHORT"
            s17_entry_idx = i
            continue
        if state == "SHORT":
            if (spr == 7 and not pd.isna(p8) and mid <= p8) or mid <= 9998:
                cover_idxs.append(i)
                state = "FLAT"

    print(f"\n=== DAY {day}: {len(cover_idxs)} S7-low cover events ===")

    # Test holding +200 LONG from cover idx with various exit rules
    for hold_t in [1, 5, 10, 20, 50, 100, 200, 500, 1000]:
        pnls = []
        for ci in cover_idxs:
            if ci + hold_t >= len(p):
                continue
            entry_ask = p.loc[ci, "ask_price_1"]
            exit_bid = p.loc[ci + hold_t, "bid_price_1"]
            pnls.append((exit_bid - entry_ask) * LIMIT)
        if pnls:
            print(f"  hold={hold_t:5d}t: n={len(pnls):2d} avg=${np.mean(pnls):+,.0f} total=${sum(pnls):+,.0f}")

    # Test mid-target exit (exit when mid >= target)
    print("  --- Mid-target exits ---")
    for tgt in [9995, 10000, 10005, 10010, 10015, 10020]:
        pnls = []
        durs = []
        for ci in cover_idxs:
            entry_ask = p.loc[ci, "ask_price_1"]
            sliced = p.loc[ci+1:].reset_index(drop=True)
            hits = sliced.index[sliced["mid_price"] >= tgt]
            if len(hits) == 0:
                # exit at last bid
                exit_idx = ci + len(sliced) - 1
            else:
                exit_idx = ci + 1 + hits[0]
            exit_bid = p.loc[exit_idx, "bid_price_1"]
            pnls.append((exit_bid - entry_ask) * LIMIT)
            durs.append(exit_idx - ci)
        if pnls:
            print(f"  mid>={tgt}: n={len(pnls):2d} avg=${np.mean(pnls):+,.0f} total=${sum(pnls):+,.0f} avg_dur={np.mean(durs):.0f}t")
