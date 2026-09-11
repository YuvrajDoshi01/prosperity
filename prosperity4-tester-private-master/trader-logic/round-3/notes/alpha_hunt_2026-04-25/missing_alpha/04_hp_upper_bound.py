"""H1d: Upper bound for HP under S17 + FLIP-with-mid-target backbone.

Combines short P&L (already $11,200 day-2) + flip P&L with optimal exit target.
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

# Multi-day expected PnL for the FULL S17+FLIP cycle with optimal exit
# Re-running with state machine FLAT->SHORT->LONG->FLAT
print("S17 short + FLIP long with mid-target exit (all aggressive prints):")
print(f"{'day':>4} {'tgt':>6} {'cycles':>7} {'short_pnl':>10} {'flip_pnl':>10} {'total':>10}")

for day in [0, 1, 2]:
    p = load_hp(day)
    p["mid_p8"] = p["mid_price"].rolling(500, min_periods=50).quantile(0.08)

    for flip_target_mid in [10010, 10015, 10020, 10025]:
        state = "FLAT"
        short_pnl = 0
        flip_pnl = 0
        cycles_s = 0
        cycles_f = 0
        s_entry_px = None
        l_entry_px = None
        cover_idx = None
        for i in range(len(p)):
            mid = p.loc[i, "mid_price"]
            spr = p.loc[i, "spread"]
            ba = p.loc[i, "ask_price_1"]
            bb = p.loc[i, "bid_price_1"]
            p8 = p.loc[i, "mid_p8"]

            if state == "FLAT" and spr == 17 and mid > 10010:
                # SHORT 200 at bid
                s_entry_px = bb
                state = "SHORT"
                continue

            if state == "SHORT":
                # Cover at ask when S7-low or mid<9998
                if (spr == 7 and not pd.isna(p8) and mid <= p8) or mid <= 9998:
                    cover_px = ba
                    short_pnl += (s_entry_px - cover_px) * LIMIT
                    cycles_s += 1
                    # Flip long at ask immediately (but need to model FLIP entry separately for clarity)
                    l_entry_px = ba
                    state = "LONG"
                    cover_idx = i
                    continue

            if state == "LONG":
                if mid >= flip_target_mid:
                    sell_px = bb
                    flip_pnl += (sell_px - l_entry_px) * LIMIT
                    cycles_f += 1
                    state = "FLAT"
                    continue

        # Close residual
        if state == "SHORT":
            cover_px = p.iloc[-1]["ask_price_1"]
            short_pnl += (s_entry_px - cover_px) * LIMIT
            cycles_s += 1
        elif state == "LONG":
            sell_px = p.iloc[-1]["bid_price_1"]
            flip_pnl += (sell_px - l_entry_px) * LIMIT
            cycles_f += 1

        total = short_pnl + flip_pnl
        print(f"{day:>4} {flip_target_mid:>6} {cycles_s:>3}/{cycles_f:>3} ${short_pnl:>+9,.0f} ${flip_pnl:>+9,.0f} ${total:>+9,.0f}")

print()
print("NOTE: above is aggressive entry/exit (worst-case spread cost). Passive layer adds bonus.")
print()
print("Compare current r3_v20 results (HP only):")
print("  Day 0: ~$21,786")
print("  Day 1: ~$26,212")
print("  Day 2: ~$22,915")
print()
print("Compare teammate's:")
print("  Day 0: $41,437")
print("  Day 1: $26,415")
print("  Day 2: $33,633")
