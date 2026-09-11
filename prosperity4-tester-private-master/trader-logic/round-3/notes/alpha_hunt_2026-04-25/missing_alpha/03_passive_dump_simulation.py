"""H1c: Quantify how the passive MM fallback unwinds +200 long after FLIP.

Reality: after FLIP completes (pos=+200), passive MM posts ask at best_ask-1 size 25.
When taker hits, 25 lots offload at best_ask-1.

Estimate: how fast does passive MM dump? At what avg price?
"""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_hp(day):
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "HYDROGEL_PACK"].reset_index(drop=True)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    return p

# Read trades file to understand taker arrival rate
def load_hp_trades(day):
    t = pd.read_csv(f"{BASE}/trades_round_3_day_{day}.csv", sep=";")
    t = t[t["symbol"] == "HYDROGEL_PACK"].reset_index(drop=True)
    return t

LIMIT = 200
QUOTE_SIZE = 25

for day in [0, 1, 2]:
    p = load_hp(day)
    p["mid_p8"] = p["mid_price"].rolling(500, min_periods=50).quantile(0.08)
    t = load_hp_trades(day)

    # Find S7-low cover events
    state = "FLAT"
    cover_idxs = []
    for i in range(len(p)):
        mid = p.loc[i, "mid_price"]
        spr = p.loc[i, "spread"]
        p8 = p.loc[i, "mid_p8"]
        if state == "FLAT" and spr == 17 and mid > 10010:
            state = "SHORT"
            continue
        if state == "SHORT":
            if (spr == 7 and not pd.isna(p8) and mid <= p8) or mid <= 9998:
                cover_idxs.append(i)
                state = "FLAT"

    print(f"\n=== DAY {day}: simulating FLIP+passive MM dump from {len(cover_idxs)} covers ===")

    # Simulate: enter +200 at ask, then unwind via passive ask=best_ask-1 size 25 each tick
    # Conservative: each tick a buyer takes our ask if mid_t+1 > our_ask. Then we sell 25 lots at our_ask.
    pnls_passive = []
    pnls_hold_until_target = {tgt: [] for tgt in [10005, 10010, 10015, 10020, 10025]}
    pnls_hold_for_t = {h: [] for h in [50, 100, 200, 500, 1000, 2000]}

    for ci in cover_idxs:
        # Entry at ask
        entry_ask = p.loc[ci, "ask_price_1"]
        cost = LIMIT * entry_ask
        # Unwind: each subsequent tick, post ask=best_ask-1 size 25.
        # Assume fill if next mid < our_ask (taker buyer flow).
        # Actually simpler: assume passive sells QUOTE_SIZE per tick until pos=0.
        # Track avg sell price.
        pos = LIMIT
        proceeds = 0
        sells = []
        for j in range(ci+1, min(ci + 500, len(p))):
            ba = p.loc[j, "ask_price_1"]
            bb = p.loc[j, "bid_price_1"]
            our_ask = ba - 1
            # If our_ask > best_bid (else would be aggressive), it's posted.
            # Heuristic fill: if mid moves up to >= our_ask in next tick, assume filled.
            # More conservative: half-fill rate
            mid_now = p.loc[j, "mid_price"]
            # Fill if reached: assume filled at our_ask
            sell_qty = min(QUOTE_SIZE, pos)
            proceeds += sell_qty * our_ask
            sells.append(our_ask)
            pos -= sell_qty
            if pos <= 0:
                break
        if pos > 0:
            # Hit by remaining bid
            proceeds += pos * p.loc[min(ci + 500, len(p) - 1), "bid_price_1"]
        pnls_passive.append(proceeds - cost)

        # Compare: hold for fixed t, exit at bid
        for h in pnls_hold_for_t:
            if ci + h < len(p):
                pnls_hold_for_t[h].append((p.loc[ci + h, "bid_price_1"] - entry_ask) * LIMIT)

        # Compare: hold until mid >= target
        for tgt in pnls_hold_until_target:
            sliced = p.loc[ci+1:].reset_index(drop=True)
            hits = sliced.index[sliced["mid_price"] >= tgt]
            if len(hits) == 0:
                ei = ci + len(sliced) - 1
            else:
                ei = ci + 1 + hits[0]
            pnls_hold_until_target[tgt].append((p.loc[ei, "bid_price_1"] - entry_ask) * LIMIT)

    print(f"  Passive-MM dump (heuristic each-tick fill): n={len(pnls_passive)} avg=${np.mean(pnls_passive):+,.0f} total=${sum(pnls_passive):+,.0f}")
    print(f"  Hold-fixed-t exits:")
    for h, pnls in pnls_hold_for_t.items():
        if pnls:
            print(f"    hold={h:5d}t: total=${sum(pnls):+,.0f}")
    print(f"  Hold-until-target exits:")
    for tgt, pnls in pnls_hold_until_target.items():
        if pnls:
            print(f"    mid>={tgt}: total=${sum(pnls):+,.0f}")
