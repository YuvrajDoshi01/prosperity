"""Mark 55 reverse-engineering for R4 v6.

Hypotheses:
  H1. Mark 55 net flow (rolling) predicts VFE mid drift.
  H2. Mark 55 sells with qty>=8 → SHORT 20 for 50 ticks.
  H3. Mark 55 buys with qty>=8 → SHORT 20 for 50 ticks (fade — he loses).
  H4. Aggregated VFE counterparty signal (Mark 55 + 49 + 14 + 01 net flow).
  H5. Predictability of Mark 55 timing from Marks 14/01.

Outputs:
  - Per-tick predictive correlations.
  - Backtest of trigger-based short strategies.
  - Best signal config (size, lookback, threshold) → r4_v6_m55.py.
"""
from __future__ import annotations

import csv
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
RES = ROOT / "prosperity4bt/resources/round4"

MARKS = ["Mark 55", "Mark 49", "Mark 14", "Mark 01", "Mark 67", "Mark 22"]


def load_day(day):
    """Returns (prices_by_ts_product, trades_list)."""
    pf = RES / f"prices_round_4_day_{day}.csv"
    tf = RES / f"trades_round_4_day_{day}.csv"
    prices = {}
    with pf.open() as f:
        rd = csv.DictReader(f, delimiter=";")
        for r in rd:
            ts = int(r["timestamp"])
            prod = r["product"]
            try:
                mid = float(r["mid_price"])
            except (TypeError, ValueError):
                continue
            prices[(ts, prod)] = mid
    trades = []
    with tf.open() as f:
        rd = csv.DictReader(f, delimiter=";")
        for r in rd:
            trades.append({
                "ts": int(r["timestamp"]),
                "buyer": r["buyer"],
                "seller": r["seller"],
                "symbol": r["symbol"],
                "price": float(r["price"]),
                "qty": int(r["quantity"]),
            })
    return prices, trades


def vfe_mid_series(prices, day_max_ts):
    out = []
    for ts in range(0, day_max_ts + 100, 100):
        m = prices.get((ts, "VELVETFRUIT_EXTRACT"))
        if m is not None:
            out.append((ts, m))
    return out


def mark_flow(trades, mark, product="VELVETFRUIT_EXTRACT"):
    """Returns dict ts -> net_flow (buy_qty - sell_qty for `mark`)."""
    flow = defaultdict(int)
    bvol = defaultdict(int)
    svol = defaultdict(int)
    sells_bigqty = defaultdict(list)  # ts -> list[(qty, price)] of sells with qty>=N
    buys_bigqty = defaultdict(list)
    for t in trades:
        if t["symbol"] != product:
            continue
        if t["buyer"] == mark:
            flow[t["ts"]] += t["qty"]
            bvol[t["ts"]] += t["qty"]
            buys_bigqty[t["ts"]].append((t["qty"], t["price"]))
        elif t["seller"] == mark:
            flow[t["ts"]] -= t["qty"]
            svol[t["ts"]] += t["qty"]
            sells_bigqty[t["ts"]].append((t["qty"], t["price"]))
    return flow, bvol, svol


def rolling_signal(flow_dict, ts_list, window):
    """Cumulative net flow over last `window` ticks (in steps of 100)."""
    out = {}
    buf = []
    for ts in ts_list:
        v = flow_dict.get(ts, 0)
        buf.append(v)
        if len(buf) > window:
            buf.pop(0)
        out[ts] = sum(buf)
    return out


def _safe_corr(xs, ys):
    if len(xs) < 30:
        return 0.0, 0.0, 0
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0, 0.0, len(xs)
    r = num / (dx * dy)
    # t-stat
    n = len(xs)
    if abs(r) >= 1:
        return r, float("inf"), n
    t = r * ((n - 2) / max(1 - r * r, 1e-12)) ** 0.5
    return r, t, n


def correlate_flow_to_drift(flow_signal, mid_ts, horizon):
    """Correlate flow_signal[t] with mid[t+h] - mid[t]."""
    xs, ys = [], []
    mid_dict = dict(mid_ts)
    for ts, mid in mid_ts:
        future_ts = ts + horizon
        future_mid = mid_dict.get(future_ts)
        if future_mid is None:
            continue
        sig = flow_signal.get(ts)
        if sig is None:
            continue
        xs.append(sig)
        ys.append(future_mid - mid)
    return _safe_corr(xs, ys)


def event_study(events_by_ts, mid_ts, horizons=(10, 25, 50, 100)):
    """events_by_ts: dict ts -> bool/qty. Returns mean fwd return per horizon."""
    mid_dict = dict(mid_ts)
    results = {}
    for h in horizons:
        rets = []
        for ts, m in mid_ts:
            if not events_by_ts.get(ts):
                continue
            future = mid_dict.get(ts + h * 100)
            if future is None:
                continue
            rets.append(future - m)
        if rets:
            mu = sum(rets) / len(rets)
            sd = statistics.pstdev(rets) if len(rets) > 1 else 0
            t = mu / (sd / len(rets) ** 0.5) if sd > 0 else 0
            results[h] = (mu, t, len(rets))
        else:
            results[h] = (0, 0, 0)
    return results


def simulate_trigger_strategy(events, mid_ts, side, hold_ticks, size, fee_per_share=0.0):
    """Simple sim: when event fires, take `side` (+1 long / -1 short) at mid, hold N, exit at mid."""
    mid_dict = dict(mid_ts)
    pnl = 0.0
    n_trades = 0
    for ts, m in mid_ts:
        if not events.get(ts):
            continue
        exit_ts = ts + hold_ticks * 100
        exit_m = mid_dict.get(exit_ts)
        if exit_m is None:
            continue
        # PnL = side * (exit - entry) * size
        pnl += side * (exit_m - m) * size - fee_per_share * size
        n_trades += 1
    return pnl, n_trades


def run_day(day):
    print(f"\n=========== DAY {day} ===========")
    prices, trades = load_day(day)
    day_max_ts = max(ts for (ts, _) in prices.keys())
    mid_ts = vfe_mid_series(prices, day_max_ts)
    if len(mid_ts) < 100:
        print(f"  short series: {len(mid_ts)}")
        return None
    print(f"  series len={len(mid_ts)} ts max={day_max_ts}")

    # Build flow series for each Mark on VFE
    flows = {}
    bvols = {}
    svols = {}
    for m in MARKS:
        flows[m], bvols[m], svols[m] = mark_flow(trades, m, "VELVETFRUIT_EXTRACT")

    ts_list = [ts for ts, _ in mid_ts]

    # === H1: Mark 55 net flow rolling vs forward drift ===
    print("\n[H1] Mark 55 rolling net flow → VFE forward drift")
    print(f"  {'window':>6} {'h':>4}  {'r':>7}  {'t':>7}  n")
    for window in (10, 25, 50, 100, 200):
        sig = rolling_signal(flows["Mark 55"], ts_list, window)
        for h in (10, 25, 50, 100, 200, 500):
            r, t, n = correlate_flow_to_drift(sig, mid_ts, h * 100)
            if abs(t) > 2.0:
                print(f"  w={window:>4} h={h:>4}  r={r:+.4f}  t={t:+.2f}  n={n}")

    # === H2: Mark 55 SELL trigger (qty>=N) → forward drop ===
    print("\n[H2] Mark 55 SELL events (qty>=N aggregate per tick) → VFE forward drift")
    for QMIN in (5, 8, 12, 20):
        events = {ts: q for ts, q in svols["Mark 55"].items() if q >= QMIN}
        if not events:
            continue
        ev_dict = {ts: True for ts in events}
        es = event_study(ev_dict, mid_ts)
        n_events = len(events)
        print(f"  qty>={QMIN}: {n_events} events")
        for h, (mu, t, n) in es.items():
            if abs(t) > 1.5:
                print(f"    h={h:>4}  mean Δmid={mu:+.3f}  t={t:+.2f}  n={n}")

    # === H3: Mark 55 BUY trigger (qty>=N) → forward drift ===
    print("\n[H3] Mark 55 BUY events (qty>=N) → VFE forward drift")
    for QMIN in (5, 8, 12, 20):
        events = {ts: q for ts, q in bvols["Mark 55"].items() if q >= QMIN}
        if not events:
            continue
        ev_dict = {ts: True for ts in events}
        es = event_study(ev_dict, mid_ts)
        n_events = len(events)
        print(f"  qty>={QMIN}: {n_events} events")
        for h, (mu, t, n) in es.items():
            if abs(t) > 1.5:
                print(f"    h={h:>4}  mean Δmid={mu:+.3f}  t={t:+.2f}  n={n}")

    # === H4: Aggregate VFE flow ===
    print("\n[H4] AGGREGATE flow (M55+M49+M14+M01) rolling → forward drift")
    agg_flow = defaultdict(int)
    for m in ("Mark 55", "Mark 49", "Mark 14", "Mark 01"):
        for ts, q in flows[m].items():
            agg_flow[ts] += q
    for window in (10, 25, 50, 100):
        sig = rolling_signal(agg_flow, ts_list, window)
        for h in (10, 25, 50, 100, 200):
            r, t, n = correlate_flow_to_drift(sig, mid_ts, h * 100)
            if abs(t) > 2.0:
                print(f"  w={window:>4} h={h:>4}  r={r:+.4f}  t={t:+.2f}  n={n}")

    # === SIM: trigger strategies ===
    print("\n[SIM] Trigger strategies on Mark 55 events")
    print(f"  {'side':>4} {'qmin':>4} {'hold':>4} {'size':>4}  {'PnL':>10}  trades")
    for QMIN in (5, 8, 12):
        for hold in (10, 25, 50, 100):
            for size in (10, 20, 40):
                # Fade SELL: he sells → mid drops → we SHORT (side=-1)
                events = {ts: True for ts, q in svols["Mark 55"].items() if q >= QMIN}
                if events:
                    pnl, n = simulate_trigger_strategy(events, mid_ts, side=-1, hold_ticks=hold, size=size)
                    if abs(pnl) > 500:
                        print(f"  SELL>=qmin={QMIN} hold={hold} size={size} side=SHORT: pnl={pnl:+.0f} n={n}")
                # Fade BUY: he buys → contrarian → SHORT
                events = {ts: True for ts, q in bvols["Mark 55"].items() if q >= QMIN}
                if events:
                    pnl, n = simulate_trigger_strategy(events, mid_ts, side=-1, hold_ticks=hold, size=size)
                    if abs(pnl) > 500:
                        print(f"  BUY>=qmin={QMIN} hold={hold} size={size} side=SHORT: pnl={pnl:+.0f} n={n}")
                # Follow SELL: SHORT alongside him
                events = {ts: True for ts, q in svols["Mark 55"].items() if q >= QMIN}
                if events:
                    pnl_long, n = simulate_trigger_strategy(events, mid_ts, side=+1, hold_ticks=hold, size=size)
                    if abs(pnl_long) > 500:
                        print(f"  SELL>=qmin={QMIN} hold={hold} size={size} side=LONG: pnl={pnl_long:+.0f} n={n}")

    # === Mark 55 NET-FLOW threshold strategy ===
    print("\n[NET] Rolling-window net flow threshold short")
    for window in (10, 25, 50, 100):
        sig = rolling_signal(flows["Mark 55"], ts_list, window)
        for thr in (-20, -50, -100, -200):
            events = {ts: True for ts, v in sig.items() if v <= thr}
            if not events:
                continue
            for hold in (25, 50, 100):
                for size in (20, 40):
                    pnl, n = simulate_trigger_strategy(events, mid_ts, side=-1, hold_ticks=hold, size=size)
                    if abs(pnl) > 500 and n < len(mid_ts) // 2:  # not always-on
                        print(f"  w={window} thr={thr} hold={hold} size={size} side=SHORT: pnl={pnl:+.0f} n={n}")
        for thr in (20, 50, 100, 200):
            events = {ts: True for ts, v in sig.items() if v >= thr}
            if not events:
                continue
            for hold in (25, 50, 100):
                for size in (20, 40):
                    pnl, n = simulate_trigger_strategy(events, mid_ts, side=+1, hold_ticks=hold, size=size)
                    if abs(pnl) > 500 and n < len(mid_ts) // 2:
                        print(f"  w={window} thr={thr} hold={hold} side=LONG: pnl={pnl:+.0f} n={n}")

    # === H5: M55 timing predictable from M14/M01? ===
    print("\n[H5] Lead-lag: does M14/M01 activity predict M55?")
    # Bin: tick has M55 trade -> 1, else 0. Test M14 sum_lag predicts.
    m55_mask = {ts: (1 if (bvols["Mark 55"].get(ts, 0) + svols["Mark 55"].get(ts, 0)) > 0 else 0) for ts in ts_list}
    for partner in ("Mark 14", "Mark 01"):
        for lead_ticks in (1, 5, 10, 25):
            xs, ys = [], []
            for i, ts in enumerate(ts_list):
                lookback_idx = i - lead_ticks
                if lookback_idx < 0:
                    continue
                past_ts = ts_list[lookback_idx]
                xs.append(bvols[partner].get(past_ts, 0) + svols[partner].get(past_ts, 0))
                ys.append(m55_mask[ts])
            r, t, n = _safe_corr(xs, ys)
            if abs(t) > 2.0:
                print(f"  {partner} lead={lead_ticks}: r={r:+.4f} t={t:+.2f} n={n}")

    return {
        "flows": flows, "bvols": bvols, "svols": svols, "mid_ts": mid_ts,
    }


if __name__ == "__main__":
    days = [1, 2, 3]
    if len(sys.argv) > 1:
        days = [int(x) for x in sys.argv[1:]]
    for d in days:
        run_day(d)
