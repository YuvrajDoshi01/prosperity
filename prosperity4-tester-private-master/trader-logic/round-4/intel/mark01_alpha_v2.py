"""Phase 2 Mark 01 forensics — refine actionable layer.

Findings from v1:
  - VFE h=1: BOTH sides +0.2 mean (t=+3.3 buy, +3.1 sell). This is not
    directional — it's time-bucket alpha. When Mark 01 trades VFE, mid drifts
    +0.2 next tick regardless of side. Mark 01 is passive (-2.6 agg).
  - VEV_5300 BUY h=1 = -0.12 (t=-3.26). Tiny magnitude, n=132.

Phase 2 questions:
  A. Is the VFE +0.2 a market-wide drift artifact (any trade) or Mark-01-specific?
  B. VEV_5300 fade signal: is the -0.12 actually about mid retracing the cross?
     If Mark 01 buys at ask-1 and tick mid is ask-0.5, fwd mid -0.12 would be
     half-spread retracing — pure noise.
  C. Does Mark 01 BUY tend to LEAD a mid-up move that we can ride passively?
     Specifically, post bid at mid for next 5 ticks after a Mark 01 trade.
"""
import csv
import os
from collections import defaultdict
from statistics import mean, stdev

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RES = os.path.join(ROOT, "prosperity4bt", "resources", "round4")

DAYS = [1, 2, 3]


def load_trades():
    trades = []
    for d in DAYS:
        with open(os.path.join(RES, f"trades_round_4_day_{d}.csv")) as f:
            for row in csv.DictReader(f, delimiter=";"):
                trades.append({
                    "day": d, "ts": int(row["timestamp"]),
                    "buyer": row["buyer"], "seller": row["seller"],
                    "symbol": row["symbol"], "price": float(row["price"]),
                    "qty": int(row["quantity"]),
                })
    return trades


def load_mids_indexed():
    """Returns {(day, product): {ts: mid}} sorted by ts."""
    out = defaultdict(dict)
    for d in DAYS:
        with open(os.path.join(RES, f"prices_round_4_day_{d}.csv")) as f:
            for row in csv.DictReader(f, delimiter=";"):
                if row["mid_price"]:
                    out[(d, row["product"])][int(row["timestamp"])] = float(row["mid_price"])
    return out


def main():
    trades = load_trades()
    mids = load_mids_indexed()

    # ---- A. Baseline market drift ----
    # For VFE: at random tick t, mid_{t+1} - mid_t. Compare to "Mark 01 trade" tick.
    print("=== A. BASELINE DRIFT vs MARK 01 SPECIFIC ===")
    for product in ["VELVETFRUIT_EXTRACT", "VEV_5300", "VEV_5400", "VEV_5500"]:
        all_drifts = []
        for d in DAYS:
            mid_map = mids.get((d, product), {})
            ts_sorted = sorted(mid_map.keys())
            for i in range(len(ts_sorted) - 1):
                ts = ts_sorted[i]
                ts_next = ts + 100
                if ts_next in mid_map:
                    all_drifts.append(mid_map[ts_next] - mid_map[ts])
        if not all_drifts:
            continue
        mu_all = mean(all_drifts)
        sd_all = stdev(all_drifts) if len(all_drifts) > 1 else 1.0
        t_all = mu_all / (sd_all / (len(all_drifts) ** 0.5)) if sd_all > 0 else 0.0

        # Mark 01 ticks only
        m01_buy_drifts = []
        m01_sell_drifts = []
        for t in trades:
            if t["symbol"] != product:
                continue
            if t["buyer"] != "Mark 01" and t["seller"] != "Mark 01":
                continue
            mid_now = mids.get((t["day"], product), {}).get(t["ts"])
            mid_fwd = mids.get((t["day"], product), {}).get(t["ts"] + 100)
            if mid_now is None or mid_fwd is None:
                continue
            d = mid_fwd - mid_now
            if t["buyer"] == "Mark 01":
                m01_buy_drifts.append(d)
            else:
                m01_sell_drifts.append(d)

        def fmt(label, arr):
            if not arr:
                return f"{label} n=0"
            mu = mean(arr)
            sd = stdev(arr) if len(arr) > 1 else 1.0
            tstat = mu / (sd / (len(arr) ** 0.5)) if sd > 0 else 0.0
            return f"{label} n={len(arr):>4} mu={mu:>+.4f} t={tstat:>+5.2f}"

        print(f"\n  {product}:")
        print(f"    BASE (any tick)         {fmt('', all_drifts)}")
        print(f"    Mark01-BUY  tick        {fmt('', m01_buy_drifts)}")
        print(f"    Mark01-SELL tick        {fmt('', m01_sell_drifts)}")

    # ---- B. VEV_5300 cross retracement vs alpha ----
    # When Mark 01 buys VEV_5300: at trade time, where was the mid relative to price?
    # If price > mid, fwd mid -0.12 just retraces the cross.
    print("\n=== B. VEV_5300 CROSS RETRACEMENT vs ALPHA ===")
    for product in ["VEV_5300", "VEV_5400", "VEV_5500"]:
        sub = [t for t in trades if t["symbol"] == product and t["buyer"] == "Mark 01"]
        agg_at_trade = []  # price - mid_now
        fwd_drifts = []
        for t in sub:
            mid_now = mids.get((t["day"], product), {}).get(t["ts"])
            mid_fwd = mids.get((t["day"], product), {}).get(t["ts"] + 100)
            if mid_now is None or mid_fwd is None:
                continue
            agg_at_trade.append(t["price"] - mid_now)
            fwd_drifts.append(mid_fwd - mid_now)
        if not agg_at_trade:
            continue
        print(f"\n  {product}: n={len(sub)}")
        print(f"    avg(price - mid_now)    = {mean(agg_at_trade):+.4f}")
        print(f"    avg(mid_fwd - mid_now)  = {mean(fwd_drifts):+.4f}")
        print(f"    -> retracement test: if -0.12 ~= -1*avg_agg, just cross retrace")

    # ---- C. Multi-tick lookahead, sided ----
    # When Mark 01 BUYS (any product), what's the avg max future mid in next 50 ticks?
    print("\n=== C. MAX FORWARD DRIFT WINDOW (Mark01 BUY VFE) ===")
    sub = [t for t in trades if t["symbol"] == "VELVETFRUIT_EXTRACT" and t["buyer"] == "Mark 01"]
    print(f"n={len(sub)}")
    windows = [(1, 5), (5, 20), (20, 100)]
    for lo, hi in windows:
        max_ups = []
        for t in sub:
            mid_now = mids.get((t["day"], "VELVETFRUIT_EXTRACT"), {}).get(t["ts"])
            if mid_now is None:
                continue
            future = []
            for h in range(lo, hi + 1):
                f = mids.get((t["day"], "VELVETFRUIT_EXTRACT"), {}).get(t["ts"] + h * 100)
                if f is not None:
                    future.append(f - mid_now)
            if future:
                max_ups.append(max(future))
        if max_ups:
            mu = mean(max_ups)
            print(f"  ticks [{lo:>2},{hi:>3}]  max_up_mean={mu:+.3f}  (n={len(max_ups)})")

    # ---- D. Time-since-last-Mark01 trade as feature ----
    # Quick check: cluster around time-of-day or burst events?
    print("\n=== D. BURST PATTERN: Mark 01 VFE consecutive trade gaps ===")
    sub = sorted([t for t in trades if t["symbol"] == "VELVETFRUIT_EXTRACT" and t["buyer"] == "Mark 01"],
                 key=lambda t: (t["day"], t["ts"]))
    bursts = 0
    for i in range(1, len(sub)):
        if sub[i]["day"] == sub[i-1]["day"] and sub[i]["ts"] - sub[i-1]["ts"] <= 500:
            bursts += 1
    print(f"  Within-500ms-of-prev: {bursts} of {len(sub)-1} ({bursts/(len(sub)-1)*100:.1f}%)")

    # ---- E. PROFITABILITY OF "MARK 01 VFE TRADE -> POST BID/ASK FOR 5 TICKS" ----
    # Simulate: when Mark 01 trades VFE, post a bid at mid for next 5 ticks.
    # Did mid go up by enough to capture passive fill at mid+1 sell?
    print("\n=== E. BACKTEST: 'Mark 01 VFE trades -> ride mid' (mid->mid+0 hold 5 ticks) ===")
    # For each Mark 01 VFE trade, score = (mid_{t+5} - mid_t) - costs
    # No spread cost since we're post-trade-arrival passive
    total = 0.0
    n_signals = 0
    for t in sub:
        mid_now = mids.get((t["day"], "VELVETFRUIT_EXTRACT"), {}).get(t["ts"])
        mid_fwd = mids.get((t["day"], "VELVETFRUIT_EXTRACT"), {}).get(t["ts"] + 500)
        if mid_now is None or mid_fwd is None:
            continue
        # Take 1 unit long for 5 ticks
        total += (mid_fwd - mid_now)
        n_signals += 1
    print(f"  LONG 1u for 5 ticks after Mark01 VFE BUY: total={total:+.1f} over {n_signals} signals")

    # Also try Mark 01 SELL (+0.21 t=3.10)
    sub_sell = sorted([t for t in trades if t["symbol"] == "VELVETFRUIT_EXTRACT" and t["seller"] == "Mark 01"],
                      key=lambda t: (t["day"], t["ts"]))
    total = 0.0
    n_signals = 0
    for t in sub_sell:
        mid_now = mids.get((t["day"], "VELVETFRUIT_EXTRACT"), {}).get(t["ts"])
        mid_fwd = mids.get((t["day"], "VELVETFRUIT_EXTRACT"), {}).get(t["ts"] + 500)
        if mid_now is None or mid_fwd is None:
            continue
        total += (mid_fwd - mid_now)
        n_signals += 1
    print(f"  LONG 1u for 5 ticks after Mark01 VFE SELL: total={total:+.1f} over {n_signals} signals")

    # Combined: any Mark 01 VFE trade
    sub_all = sorted([t for t in trades if t["symbol"] == "VELVETFRUIT_EXTRACT" and
                      (t["buyer"] == "Mark 01" or t["seller"] == "Mark 01")],
                     key=lambda t: (t["day"], t["ts"]))
    for hold in [1, 3, 5, 10, 20]:
        total = 0.0
        n_signals = 0
        for t in sub_all:
            mid_now = mids.get((t["day"], "VELVETFRUIT_EXTRACT"), {}).get(t["ts"])
            mid_fwd = mids.get((t["day"], "VELVETFRUIT_EXTRACT"), {}).get(t["ts"] + hold * 100)
            if mid_now is None or mid_fwd is None:
                continue
            total += (mid_fwd - mid_now)
            n_signals += 1
        print(f"  ANY Mark01 VFE trade -> LONG hold={hold:>3}t: total={total:+.1f} (n={n_signals})  per-signal={total/max(n_signals,1):+.3f}")

    # ---- F. PER-DAY breakout to confirm signal stability ----
    print("\n=== F. Per-day VFE 'any Mark01 trade -> long 5t' ===")
    for d in DAYS:
        total = 0.0
        n = 0
        for t in sub_all:
            if t["day"] != d:
                continue
            mid_now = mids.get((t["day"], "VELVETFRUIT_EXTRACT"), {}).get(t["ts"])
            mid_fwd = mids.get((t["day"], "VELVETFRUIT_EXTRACT"), {}).get(t["ts"] + 500)
            if mid_now is None or mid_fwd is None:
                continue
            total += (mid_fwd - mid_now)
            n += 1
        print(f"  day {d}: total={total:+.1f} n={n} per={total/max(n,1):+.3f}")

    # ---- G. Aggregate market-wide tick drift around Mark 01 events vs random ----
    # Maybe Mark 01 trades correlate with a moment when other counterparties are taking,
    # and the +0.2 is just net buy pressure at that moment.
    print("\n=== G. MARK 01 CO-OCCURRENCE: did anyone else buy VFE in same tick? ===")
    same_tick = 0
    co_buy = 0
    co_sell = 0
    for t in sub_all:
        same = [tt for tt in trades if tt["symbol"] == "VELVETFRUIT_EXTRACT" and
                tt["day"] == t["day"] and tt["ts"] == t["ts"] and tt is not t]
        if same:
            same_tick += 1
            for tt in same:
                if tt["buyer"] != "Mark 01" and tt["seller"] != "Mark 01":
                    if tt["price"] - mids.get((t["day"], "VELVETFRUIT_EXTRACT"), {}).get(t["ts"], 0) > 0.5:
                        co_buy += 1
                    else:
                        co_sell += 1
    print(f"  Mark 01 VFE trades with concurrent same-tick: {same_tick}/{len(sub_all)}")
    print(f"  Other-counterparty co-buys (above mid): {co_buy}, co-sells: {co_sell}")


if __name__ == "__main__":
    main()
