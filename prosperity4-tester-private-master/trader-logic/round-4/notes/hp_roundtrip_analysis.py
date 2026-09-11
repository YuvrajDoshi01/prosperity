"""Analyze HP intraday oscillation for round-trip MM opportunities."""
import csv
from pathlib import Path

BASE = Path(r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round4")

def load_prices(day):
    rows = []
    with open(BASE / f"prices_round_4_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows.append(r)
    return rows

for day in [1, 2, 3]:
    print(f"\n{'='*60}")
    print(f"DAY {day} HP ROUND-TRIP ANALYSIS")
    print(f"{'='*60}")

    rows = load_prices(day)
    hp = [(int(r["timestamp"]), float(r["mid_price"]),
           int(r["ask_price_1"]) - int(r["bid_price_1"]) if r["bid_price_1"] and r["ask_price_1"] else None,
           int(r["bid_price_1"]) if r["bid_price_1"] else None,
           int(r["ask_price_1"]) if r["ask_price_1"] else None)
          for r in rows if r["product"] == "HYDROGEL_PACK"]

    mids = [m for _, m, _, _, _ in hp]

    # 1. Range statistics
    print(f"  Range: {min(mids):.1f} - {max(mids):.1f} = {max(mids)-min(mids):.1f}")
    print(f"  Drift: {mids[-1]-mids[0]:+.1f}")

    # 2. Mean reversion structure: when mid > 10020, how often does it come back to 10000?
    # and vice versa
    above_thresh = 10020
    below_thresh = 9990
    above_runs = []
    current_run = 0
    for mid in mids:
        if mid >= above_thresh:
            current_run += 1
        else:
            if current_run > 0:
                above_runs.append(current_run)
            current_run = 0

    below_runs = []
    current_run = 0
    for mid in mids:
        if mid <= below_thresh:
            current_run += 1
        else:
            if current_run > 0:
                below_runs.append(current_run)
            current_run = 0

    if above_runs:
        print(f"  Runs above {above_thresh}: {len(above_runs)} episodes, avg={sum(above_runs)/len(above_runs):.1f} ticks")
    if below_runs:
        print(f"  Runs below {below_thresh}: {len(below_runs)} episodes, avg={sum(below_runs)/len(below_runs):.1f} ticks")

    # 3. Perfect-foresight round-trips (oracle analysis)
    # If we could buy at local minima and sell at local maxima with 200 units...
    # Use simple 50-tick rolling min/max
    WINDOW = 50
    local_mins = []
    local_maxs = []
    for i in range(WINDOW, len(mids) - WINDOW):
        window = mids[i-WINDOW:i+WINDOW+1]
        if mids[i] == min(window):
            local_mins.append((i, mids[i]))
        if mids[i] == max(window):
            local_maxs.append((i, mids[i]))

    # Compute max theoretical PnL from round-trips
    # Alternate: buy at local min, sell at next local max (or vice versa)
    events = sorted(
        [(i, mid, "min") for i, mid in local_mins] +
        [(i, mid, "max") for i, mid in local_maxs],
        key=lambda x: x[0]
    )

    theoretical_pnl = 0
    pos = 0  # -1 (short), 0, +1 (long)
    entry_price = 0
    trades = 0
    for i, mid, kind in events:
        if kind == "min" and pos <= 0:
            if pos == -1:  # close short
                theoretical_pnl += (entry_price - mid) * 200
                trades += 1
            pos = 1
            entry_price = mid
        elif kind == "max" and pos >= 0:
            if pos == 1:  # close long
                theoretical_pnl += (mid - entry_price) * 200
                trades += 1
            pos = -1
            entry_price = mid

    print(f"  Oracle 50-tick: {trades} round-trips, PnL={theoretical_pnl:.0f}")
    print(f"    Avg per trip: {theoretical_pnl/trades:.0f}" if trades else "")

    # 4. Spread-based signal analysis
    # When spread narrows to 7-9 (tight), what happens next?
    tight_spread_next = []
    for i in range(len(hp) - 50):
        ts, mid, spread, bp, ap = hp[i]
        if spread is not None and spread <= 9:
            future_mid = hp[i+50][1]
            tight_spread_next.append(future_mid - mid)

    if tight_spread_next:
        avg = sum(tight_spread_next) / len(tight_spread_next)
        print(f"  Tight spread (<=9) future 50-tick return: avg={avg:.2f}, n={len(tight_spread_next)}")

    # When spread widens to 17, what's the 50-tick return?
    wide_spread_next = []
    for i in range(len(hp) - 50):
        ts, mid, spread, bp, ap = hp[i]
        if spread == 17 and mid > 10010:
            future_mid = hp[i+50][1]
            wide_spread_next.append(future_mid - mid)

    if wide_spread_next:
        avg = sum(wide_spread_next) / len(wide_spread_next)
        neg_pct = sum(1 for x in wide_spread_next if x < 0) / len(wide_spread_next) * 100
        print(f"  Spread=17 (mid>10010) 50-tick return: avg={avg:.2f}, {neg_pct:.0f}% negative, n={len(wide_spread_next)}")

    # 5. z-score mean reversion signal
    # When z-score of last 200 mids > 2, short. When < -2, buy.
    ZBUF = 200
    if len(mids) > ZBUF:
        z_signals = []
        for i in range(ZBUF, len(mids) - 100):
            window = mids[i-ZBUF:i]
            mu = sum(window) / len(window)
            sd = (sum((x-mu)**2 for x in window) / len(window))**0.5
            if sd > 0:
                z = (mids[i] - mu) / sd
                if abs(z) > 1.5:
                    future_ret = mids[i+100] - mids[i]
                    z_signals.append((z, future_ret))

        if z_signals:
            high_z = [(z, r) for z, r in z_signals if z > 1.5]
            low_z = [(z, r) for z, r in z_signals if z < -1.5]
            if high_z:
                avg_ret = sum(r for _, r in high_z) / len(high_z)
                print(f"  z>1.5 (short signal) 100-tick return: avg={avg_ret:.2f}, n={len(high_z)}")
            if low_z:
                avg_ret = sum(r for _, r in low_z) / len(low_z)
                print(f"  z<-1.5 (buy signal) 100-tick return: avg={avg_ret:.2f}, n={len(low_z)}")
