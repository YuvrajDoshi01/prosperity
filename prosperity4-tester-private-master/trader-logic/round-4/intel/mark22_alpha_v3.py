"""mark22_alpha_v3.py — Diagnose adverse selection: when Mark 22 prints,
is the v5 momentum-short layer already short? Then bidding HARDER fights
our own signal."""
import os, csv
from collections import defaultdict
from statistics import mean

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "prosperity4bt", "resources", "round4")


def main():
    # Reconstruct VFE mid sequence; for each Mark 22 SELL ts, compute
    # the 25-tick lookback velocity (mid - mid_25_ago). v5 momo fires when
    # velocity <= -3.
    trades, mids = [], {}
    for d in (1, 2, 3):
        ts_off = (d - 1) * 1_000_000
        with open(os.path.join(DATA, f"trades_round_4_day_{d}.csv"), encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter=";"):
                sym = r["symbol"]
                if sym not in ("VFE", "VELVETFRUIT_EXTRACT"): continue
                trades.append({"ts": int(r["timestamp"]) + ts_off, "day": d,
                               "buyer": r["buyer"], "seller": r["seller"],
                               "qty": int(r["quantity"]),
                               "price": float(r["price"])})
        with open(os.path.join(DATA, f"prices_round_4_day_{d}.csv"), encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r["product"] != "VELVETFRUIT_EXTRACT": continue
                ts = int(r["timestamp"]) + ts_off
                try:
                    mids[ts] = float(r["mid_price"])
                except ValueError:
                    pass

    keys = sorted(mids.keys())
    # build idx
    idx = {k: i for i, k in enumerate(keys)}

    m22 = [t for t in trades if t["seller"] == "Mark 22"]
    print(f"M22 VFE sells: {len(m22)}")

    # Velocity at trade time: lookback 25 ticks (2500 ms)
    velocity_dist = []
    momo_active = []  # 0/1
    for t in m22:
        ts = t["ts"]
        # round to nearest mid key (mids are at 100ms grid)
        ts_now = ts - (ts % 100)
        if ts_now not in idx: continue
        i = idx[ts_now]
        if i < 25: continue
        v = mids[keys[i]] - mids[keys[i - 25]]
        velocity_dist.append(v)
        momo_active.append(1 if v <= -3 else 0)
    if velocity_dist:
        v_sorted = sorted(velocity_dist)
        n = len(v_sorted)
        print(f"velocity (25-tick lookback) at M22 sell: n={n}")
        print(f"  mean={mean(velocity_dist):+.2f}  median={v_sorted[n//2]:+.2f}")
        print(f"  p10={v_sorted[n//10]:+.2f}  p90={v_sorted[9*n//10]:+.2f}")
        print(f"  velocity<=-3 (momo would fire): {sum(momo_active)}/{n} ({100*sum(momo_active)/n:.0f}%)")
        # what fraction of M22 prints happen during a momo-down regime?
        # also: net-mid-direction conditional on velocity bucket
    print()

    # Test 2: when M22 prints AND momo NOT active: forward mid
    # (this is where alpha is "free" — v5 isn't already short)
    deltas_no_momo = []
    deltas_momo = []
    for t in m22:
        ts = t["ts"]
        ts_now = ts - (ts % 100)
        if ts_now not in idx: continue
        i = idx[ts_now]
        if i < 25 or i + 1 >= len(keys): continue
        v = mids[keys[i]] - mids[keys[i - 25]]
        m_now = mids[keys[i]]
        m_fwd = mids[keys[i + 1]]
        d = m_fwd - m_now
        if v <= -3: deltas_momo.append(d)
        else: deltas_no_momo.append(d)
    if deltas_no_momo:
        print(f"M22 sell, momo NOT active (n={len(deltas_no_momo)}): "
              f"mean Δmid h=1 = {mean(deltas_no_momo):+.3f}")
    if deltas_momo:
        print(f"M22 sell, momo IS active (n={len(deltas_momo)}): "
              f"mean Δmid h=1 = {mean(deltas_momo):+.3f}")

    # Test 3: at a higher horizon (h=20)
    deltas_no_momo_20 = []
    deltas_momo_20 = []
    for t in m22:
        ts = t["ts"]
        ts_now = ts - (ts % 100)
        if ts_now not in idx: continue
        i = idx[ts_now]
        if i < 25 or i + 20 >= len(keys): continue
        v = mids[keys[i]] - mids[keys[i - 25]]
        m_now = mids[keys[i]]
        m_fwd = mids[keys[i + 20]]
        d = m_fwd - m_now
        if v <= -3: deltas_momo_20.append(d)
        else: deltas_no_momo_20.append(d)
    if deltas_no_momo_20:
        print(f"M22 sell, momo NOT active, h=20 (n={len(deltas_no_momo_20)}): "
              f"mean Δmid = {mean(deltas_no_momo_20):+.3f}")
    if deltas_momo_20:
        print(f"M22 sell, momo IS active, h=20 (n={len(deltas_momo_20)}): "
              f"mean Δmid = {mean(deltas_momo_20):+.3f}")


if __name__ == "__main__":
    main()
