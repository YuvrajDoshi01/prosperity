"""H1: How many S17 + S7-FLIP cycles fire on day 2 full 10k?
Each cycle should net ~$2-4k. If 5+ events => $10-20k achievable.

Replicate the S17+S7+FLIP backbone exactly:
  - Enter SHORT to -200 when spread==17 AND mid > 10010
  - Cover when spread==7 AND mid <= 8th-percentile of last 500-tick window
  - On cover: FLIP LONG to +200
  - Exit FLIP when mid >= mid_target (mean reversion exit) — what's the rule?
"""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_hp(day):
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "HYDROGEL_PACK"].reset_index(drop=True)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    return p

# Print stats and event sequence per day
for day in [0, 1, 2]:
    p = load_hp(day)
    n = len(p)
    s17_mask = (p["spread"] == 17) & (p["mid_price"] > 10010)
    s7_mask = (p["spread"] == 7)
    s17_idx = list(p.index[s17_mask])
    s7_idx = list(p.index[s7_mask])

    # 8th percentile of last 500 mids
    p["mid_p8"] = p["mid_price"].rolling(500, min_periods=50).quantile(0.08)
    s7_low_mask = (p["spread"] == 7) & (p["mid_price"] <= p["mid_p8"])
    s7_low_idx = list(p.index[s7_low_mask])

    # Mid > 9990 (FV reversion target)
    p["mid_p70"] = p["mid_price"].rolling(500, min_periods=50).quantile(0.70)

    print(f"\n=== DAY {day} ({n} rows) ===")
    print(f"  spread=17 raw events:       {(p['spread']==17).sum()}")
    print(f"  spread=17 & mid>10010:      {s17_mask.sum()}  (S17 entry trigger)")
    print(f"  spread=7 raw events:        {s7_mask.sum()}")
    print(f"  spread=7 & mid<=p8(500):    {s7_low_mask.sum()}  (S7 cover+flip trigger)")

    # Simulate the S17/S7/FLIP cycle
    pos = 0
    cash = 0
    cycles = []
    cur_entry_price = None
    cur_entry_idx = None
    state = "FLAT"  # FLAT, SHORT, LONG
    flip_target_mid = None

    LIMIT = 200
    EXIT_MID = 9998  # standard cover threshold
    FLIP_EXIT_MID = 9990  # FV - flip exits when mean-reverted to FV

    for i in range(len(p)):
        mid = p.loc[i, "mid_price"]
        ask = p.loc[i, "ask_price_1"]
        bid = p.loc[i, "bid_price_1"]
        spr = p.loc[i, "spread"]
        p8 = p.loc[i, "mid_p8"]

        if state == "FLAT" and spr == 17 and mid > 10010:
            # Enter short at bid (sell)
            cur_entry_price = bid
            cur_entry_idx = i
            pos = -LIMIT
            cash += LIMIT * bid
            state = "SHORT"
            continue

        if state == "SHORT":
            # Cover via S7 low OR mid<EXIT_MID
            if (spr == 7 and not pd.isna(p8) and mid <= p8) or mid <= EXIT_MID:
                # Cover at ask
                cash -= LIMIT * ask
                pnl = cash
                # Flip long
                pos = LIMIT
                cash -= LIMIT * ask  # buy 200 more at ask
                cycles.append({
                    "type": "S17_short",
                    "entry_idx": cur_entry_idx,
                    "exit_idx": i,
                    "entry_px": cur_entry_price,
                    "exit_px": ask,
                    "pnl": (cur_entry_price - ask) * LIMIT,
                    "duration": i - cur_entry_idx,
                })
                cur_entry_price = ask
                cur_entry_idx = i
                state = "LONG"
                continue

        if state == "LONG":
            # Exit flip at mid > FV
            if mid >= FLIP_EXIT_MID + 5:  # exit when above FV (a bit past mean)
                cash += LIMIT * bid  # sell at bid
                cycles.append({
                    "type": "FLIP_long",
                    "entry_idx": cur_entry_idx,
                    "exit_idx": i,
                    "entry_px": cur_entry_price,
                    "exit_px": bid,
                    "pnl": (bid - cur_entry_price) * LIMIT,
                    "duration": i - cur_entry_idx,
                })
                pos = 0
                state = "FLAT"
                continue

    # Close any open position at last mid
    if state == "SHORT":
        cash -= LIMIT * p.iloc[-1]["ask_price_1"]
        pos = 0
    elif state == "LONG":
        cash += LIMIT * p.iloc[-1]["bid_price_1"]
        pos = 0

    short_cycles = [c for c in cycles if c["type"] == "S17_short"]
    long_cycles = [c for c in cycles if c["type"] == "FLIP_long"]

    print(f"\n  Cycles: {len(short_cycles)} short, {len(long_cycles)} flip")
    print(f"  Short PnL total: ${sum(c['pnl'] for c in short_cycles):+,.0f}")
    print(f"  Flip PnL total:  ${sum(c['pnl'] for c in long_cycles):+,.0f}")
    print(f"  Combined: ${sum(c['pnl'] for c in cycles):+,.0f}")
    print(f"  Final cash position: ${cash:+,.0f} (residual pos={pos})")

    print(f"\n  Cycle detail:")
    for c in cycles:
        print(f"    {c['type']:12s} t=[{c['entry_idx']:4d}->{c['exit_idx']:4d}] "
              f"px={c['entry_px']:.0f}->{c['exit_px']:.0f}  "
              f"dur={c['duration']:4d}t  pnl=${c['pnl']:+,.0f}")
