"""Final confirmation:
1. Underlying VELVETFRUIT_EXTRACT drift across 3 days
2. Strategy backtest: post 1-tick-inside on HYDROGEL_PACK (high-spread MM)
3. Voucher carry: long ITM voucher (VEV_4000/4500) collects underlying drift directly
   because they are delta~0.65-0.73 — drift = 28 over 1k ticks => +0.028/tick
4. Underlying VFE itself drifts +28 over 1k ticks => long 200 VFE = +5,600/day = $5.6/tick
   Buy and hold across all delta-1 vouchers => ~80k.
"""
import os
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester"
DATA_DIR = os.path.join(ROOT, "prosperity4bt", "resources", "round3")


def load_day(d):
    p = pd.read_csv(os.path.join(DATA_DIR, f"prices_round_3_day_{d}.csv"), sep=";")
    return p


def buy_and_hold_pnl(prices, prod, size):
    df = prices[prices["product"] == prod].sort_values("timestamp")
    if df.empty:
        return None, None
    open_ = df.iloc[0]["mid_price"]
    close_ = df.iloc[-1]["mid_price"]
    pnl = size * (close_ - open_)
    return open_, close_, pnl


def main():
    print("=" * 80)
    print("BUY-AND-HOLD PNL across all 3 days, by product")
    print("=" * 80)
    LIMITS = {
        "HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300, "VEV_5100": 300,
        "VEV_5200": 300, "VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300,
        "VEV_6000": 300, "VEV_6500": 300,
    }
    for d in [0, 1, 2]:
        try:
            p = load_day(d)
        except FileNotFoundError:
            continue
        print(f"\n--- Day {d} ---")
        rows = []
        for prod, lim in LIMITS.items():
            r = buy_and_hold_pnl(p, prod, lim)
            if r is None:
                continue
            o, c, pnl = r
            rows.append({
                "product": prod,
                "open": o,
                "close": c,
                "drift": c - o,
                "size": lim,
                "buy_and_hold_pnl": pnl,
            })
        df = pd.DataFrame(rows).sort_values("buy_and_hold_pnl", ascending=False)
        print(df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
        print(f"  Total long-everything-at-open PnL day {d}: {df['buy_and_hold_pnl'].sum():,.0f}")
        # OTM short:
        otm = df[df["product"].isin(["VEV_5300", "VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500"])]
        print(f"  OTM short (sell @ open): { -otm['buy_and_hold_pnl'].sum():,.0f}")

    # Now -- assume underlying drifts +28 / 10k ticks (= +2.8 / 1k ticks).
    # Day 2: drift 28 on VELVETFRUIT_EXTRACT, 27.5 on VEV_4000, 28.5 on VEV_4500.
    # Long 300 VEV_4000 -> +8,250.
    # Long 300 VEV_4500 -> +8,550.
    # Long 200 VELVETFRUIT_EXTRACT -> +5,600.
    # Long 300 VEV_5000 -> +7,950.
    # Long 300 VEV_5100 -> +6,750.
    # Long 300 VEV_5200 -> +4,500.
    # Sum of "delta~1" longs: ~$41k from drift alone.
    # Plus shorting OTM premia (VEV_5400/5500/6000/6500) at avg, decays 0 -> further +5-10k.

    print("\n" + "=" * 80)
    print("STRATEGY 1: BUY-AND-HOLD ALL DELTA-1 LONGS at OPEN, day 2")
    print("=" * 80)
    p = load_day(2)
    longs = ["VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", "VEV_5200", "VELVETFRUIT_EXTRACT"]
    total = 0
    for prod in longs:
        r = buy_and_hold_pnl(p, prod, LIMITS[prod])
        if r:
            o, c, pnl = r
            print(f"  long {LIMITS[prod]} {prod} from {o} to {c}: {pnl:,.0f}")
            total += pnl
    print(f"  TOTAL: {total:,.0f}")

    # Strategy 2: short OTM at avg
    print("\nSTRATEGY 2: short OTM vouchers (open ALL with size limits, sell to taker bids)")
    print("Assumption: each OTM seller-only flow lets us short at the bid, voucher decays to 0.")
    shorts = {"VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300, "VEV_6500": 300}
    total2 = 0
    for prod, sz in shorts.items():
        df = p[p["product"] == prod]
        if df.empty:
            continue
        avg_mid = df["mid_price"].mean()
        # close mid is ~0 for OTM
        close_mid = df.sort_values("timestamp").iloc[-1]["mid_price"]
        # Short at avg, cover at close (or at expiry payoff = max(0, U-K))
        pnl = sz * (avg_mid - close_mid)
        print(f"  short {sz} {prod} from avg {avg_mid:.2f} to close {close_mid:.2f}: {pnl:,.0f}")
        total2 += pnl
    print(f"  TOTAL: {total2:,.0f}")

    print("\nGRAND TOTAL: long-delta-1 + short-OTM = ${:,.0f}".format(total + total2))


if __name__ == "__main__":
    main()
