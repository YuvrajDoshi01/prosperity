"""mark22_alpha.py — DEDICATED Mark 22 reverse-engineering for R4 v6.

Mark 22 profile: 1,584 trades, 96% seller. Paired with Mark 01 on VEV_5200..6500.
Mining mandate (5 axes):
  1. HP fade — when Mark 22 sells HP, mid drops -3.66 in 2 ticks (n=19, t=-7.27)
     Is it implementable after spread cost (HP spread ~16, half=8)?
  2. VFE fade — Mark 22 sells VFE → -1.27 in 1 tick (n=126).
     Already captured by passive WM MM?
  3. Mark 22 → Mark 55 sequence: post passive bid INSIDE spread for 100 ticks.
  4. VEV_6000/6500 free 0.5/share — already in v5 deep-OTM bid=0.
  5. Mark 22 daily clustering — time-of-day pattern?
"""
import os, csv, math
from collections import defaultdict, deque, Counter
from statistics import mean, pstdev, stdev

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "prosperity4bt", "resources", "round4")
TICK = 100  # ms per tick


def load_all():
    trades, mids, books = [], defaultdict(dict), defaultdict(dict)
    for d in (1, 2, 3):
        ts_off = (d - 1) * 1_000_000
        with open(os.path.join(DATA, f"trades_round_4_day_{d}.csv"),
                  encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter=";"):
                sym = r["symbol"]
                sym = "VELVETFRUIT_EXTRACT" if sym == "VFE" else (
                      "HYDROGEL_PACK" if sym == "HP" else sym)
                trades.append({
                    "ts": int(r["timestamp"]) + ts_off,
                    "ts_intra": int(r["timestamp"]),
                    "day": d,
                    "buyer": r["buyer"],
                    "seller": r["seller"],
                    "symbol": sym,
                    "price": float(r["price"]),
                    "qty": int(r["quantity"]),
                })
        with open(os.path.join(DATA, f"prices_round_4_day_{d}.csv"),
                  encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter=";"):
                sym = r["product"]
                ts = int(r["timestamp"]) + ts_off
                try:
                    mids[sym][ts] = float(r["mid_price"])
                    books[sym][ts] = {
                        "bid": float(r["bid_price_1"] or 0),
                        "ask": float(r["ask_price_1"] or 0),
                        "bid_v": int(r["bid_volume_1"] or 0),
                        "ask_v": int(r["ask_volume_1"] or 0),
                    }
                except ValueError:
                    pass
    trades.sort(key=lambda x: x["ts"])
    return trades, mids, books


def fwd_mid(mids_p, ts, h_ms):
    target = ts + h_ms
    keys = sorted(mids_p.keys())
    lo, hi = 0, len(keys)
    while lo < hi:
        m = (lo + hi) // 2
        if keys[m] < target: lo = m + 1
        else: hi = m
    return mids_p[keys[lo]] if lo < len(keys) else None


def t_stat(xs):
    if len(xs) < 3: return 0.0
    m = mean(xs); sd = pstdev(xs)
    return 0.0 if sd == 0 else m / (sd / math.sqrt(len(xs)))


def main():
    trades, mids, books = load_all()
    print(f"Total trades: {len(trades)}")

    # Mark 22 trade subset
    m22 = [t for t in trades if t["seller"] == "Mark 22" or t["buyer"] == "Mark 22"]
    print(f"Mark 22 total trades: {len(m22)}")

    # ---- AXIS 1: HP fade by qty bucket -----------------------------------
    print("\n=== AXIS 1: Mark 22 SELLS HP — mid forward by qty bucket ===")
    hp_sells = [t for t in m22 if t["symbol"] == "HYDROGEL_PACK" and t["seller"] == "Mark 22"]
    print(f"HP sells (Mark 22): n={len(hp_sells)}")
    # qty distribution
    qty_dist = Counter(t["qty"] for t in hp_sells)
    print(f"qty distribution: {dict(qty_dist)}")
    # forward mid moves at horizons {1, 2, 5, 10, 20, 50, 100}
    horizons = [1, 2, 5, 10, 20, 50, 100]
    for h in horizons:
        h_ms = h * TICK
        deltas = []
        for t in hp_sells:
            m_now = mids["HYDROGEL_PACK"].get(t["ts"])
            m_fwd = fwd_mid(mids["HYDROGEL_PACK"], t["ts"], h_ms)
            if m_now is None or m_fwd is None: continue
            deltas.append(m_fwd - m_now)
        if deltas:
            ts = t_stat(deltas)
            print(f"  h={h:>3}t  n={len(deltas):>3}  mean Δmid={mean(deltas):+7.3f}  t={ts:+6.2f}")

    # qty bucket
    print("\nQty filter: HP sells with qty≥5")
    big = [t for t in hp_sells if t["qty"] >= 5]
    print(f"  n={len(big)}")
    for h in [1, 2, 5, 10]:
        h_ms = h * TICK
        deltas = []
        for t in big:
            m_now = mids["HYDROGEL_PACK"].get(t["ts"])
            m_fwd = fwd_mid(mids["HYDROGEL_PACK"], t["ts"], h_ms)
            if m_now is None or m_fwd is None: continue
            deltas.append(m_fwd - m_now)
        if deltas:
            ts = t_stat(deltas)
            print(f"  h={h:>3}t  n={len(deltas):>3}  mean Δmid={mean(deltas):+7.3f}  t={ts:+6.2f}")

    # spread context — what is the typical HP spread when Mark 22 sells?
    print("\nHP book context at Mark 22 sell time:")
    spreads = []
    for t in hp_sells:
        b = books["HYDROGEL_PACK"].get(t["ts"])
        if b: spreads.append(b["ask"] - b["bid"])
    if spreads:
        print(f"  n={len(spreads)}  mean spread={mean(spreads):.2f}  "
              f"p25={sorted(spreads)[len(spreads)//4]:.0f}  "
              f"median={sorted(spreads)[len(spreads)//2]:.0f}  "
              f"p75={sorted(spreads)[3*len(spreads)//4]:.0f}")

    # IMPLEMENTABILITY: net edge after spread cost.
    # If we want to FADE Mark 22's sell (price goes down), we SHORT — sell at best_bid.
    # Cost = (mid - best_bid) ≈ spread/2. Edge = -mean Δmid - spread/2.
    print("\n[Implementability] FADE = WE SELL when Mark 22 sells")
    for h in [1, 2, 5]:
        h_ms = h * TICK
        net = []
        for t in hp_sells:
            b = books["HYDROGEL_PACK"].get(t["ts"])
            m_now = mids["HYDROGEL_PACK"].get(t["ts"])
            m_fwd = fwd_mid(mids["HYDROGEL_PACK"], t["ts"], h_ms)
            if not (b and m_now and m_fwd): continue
            # we sell at best_bid (cross spread), exit at m_fwd
            entry = b["bid"]
            pnl = entry - m_fwd  # short pnl
            net.append(pnl)
        if net:
            print(f"  h={h:>2}t  n={len(net)}  mean PnL/share={mean(net):+6.3f}  "
                  f"t={t_stat(net):+5.2f}  total={sum(net):+7.1f}")

    # PASSIVE entry: post a sell at best_ask-1 (penny ask), maybe-fill
    print("\n[Passive ask] post sell at best_ask-1 — assumes fill if mid moves down")
    for h in [1, 2, 5]:
        h_ms = h * TICK
        net = []
        for t in hp_sells:
            b = books["HYDROGEL_PACK"].get(t["ts"])
            m_fwd = fwd_mid(mids["HYDROGEL_PACK"], t["ts"], h_ms)
            if not (b and m_fwd): continue
            entry = b["ask"] - 1
            pnl = entry - m_fwd
            net.append(pnl)
        if net:
            print(f"  h={h:>2}t  n={len(net)}  mean PnL/share={mean(net):+6.3f}  "
                  f"t={t_stat(net):+5.2f}  total={sum(net):+7.1f}")

    # ---- AXIS 2: VFE fade ------------------------------------------------
    print("\n=== AXIS 2: Mark 22 SELLS VFE — mid forward ===")
    vfe_sells = [t for t in m22 if t["symbol"] == "VELVETFRUIT_EXTRACT"
                 and t["seller"] == "Mark 22"]
    print(f"VFE sells (Mark 22): n={len(vfe_sells)}")
    for h in horizons:
        h_ms = h * TICK
        deltas = []
        for t in vfe_sells:
            m_now = mids["VELVETFRUIT_EXTRACT"].get(t["ts"])
            m_fwd = fwd_mid(mids["VELVETFRUIT_EXTRACT"], t["ts"], h_ms)
            if m_now is None or m_fwd is None: continue
            deltas.append(m_fwd - m_now)
        if deltas:
            ts = t_stat(deltas)
            print(f"  h={h:>3}t  n={len(deltas):>3}  mean Δmid={mean(deltas):+7.3f}  t={ts:+6.2f}")

    # ---- AXIS 3: Mark 22 → Mark 55 sequence -------------------------------
    print("\n=== AXIS 3: Mark 22 SELL VFE → Mark 55 SELL VFE within window ===")
    # forward mid measured AT Mark 22's trade time, looking forward
    # pattern: M22S then M55S → fwd should rise (we should LONG)
    for window_ticks in [10, 50, 100, 500]:
        window_ms = window_ticks * TICK
        m22_sells_ts = [t["ts"] for t in trades if t["seller"] == "Mark 22"
                        and t["symbol"] == "VELVETFRUIT_EXTRACT"]
        m55_sells_ts = [t["ts"] for t in trades if t["seller"] == "Mark 55"
                        and t["symbol"] == "VELVETFRUIT_EXTRACT"]
        m55_set = sorted(m55_sells_ts)
        # for each M22 sell, look for M55 sell within window forward
        triggers = []
        for ts22 in m22_sells_ts:
            # binary search for first M55 sell >= ts22
            lo, hi = 0, len(m55_set)
            while lo < hi:
                mid = (lo + hi) // 2
                if m55_set[mid] < ts22: lo = mid + 1
                else: hi = mid
            for j in range(lo, len(m55_set)):
                if m55_set[j] - ts22 > window_ms: break
                if m55_set[j] > ts22:
                    triggers.append(m55_set[j])
                    break
        # fwd return at h=10, 100, 500 ticks from second event
        for h in [10, 50, 100]:
            h_ms = h * TICK
            deltas = []
            for ts in triggers:
                m_now = mids["VELVETFRUIT_EXTRACT"].get(ts)
                m_fwd = fwd_mid(mids["VELVETFRUIT_EXTRACT"], ts, h_ms)
                if m_now is None or m_fwd is None: continue
                deltas.append(m_fwd - m_now)
            if deltas and len(deltas) >= 5:
                ts_t = t_stat(deltas)
                print(f"  win={window_ticks:>3}t  h={h:>3}t  n={len(deltas):>3}  "
                      f"mean Δmid={mean(deltas):+7.3f}  t={ts_t:+6.2f}")

    # passive bid camping: we post bid at best_bid+1 for 100 ticks after Mark 22 SELL VFE
    print("\n[Passive BID camp] After Mark 22 sells VFE, post bid at best_bid+1 for N ticks")
    for hold_ticks in [10, 50, 100]:
        hold_ms = hold_ticks * TICK
        # entry = best_bid+1; exit = mid at ts+hold_ms
        net, n_filled = [], 0
        for t in vfe_sells:
            b = books["VELVETFRUIT_EXTRACT"].get(t["ts"])
            m_fwd = fwd_mid(mids["VELVETFRUIT_EXTRACT"], t["ts"], hold_ms)
            if not (b and m_fwd): continue
            # ASSUME passive bid+1 fills only if mid drops below entry within window
            # Conservative: only fill if any mid in [ts, ts+hold] <= entry
            entry = b["bid"] + 1
            keys = sorted(mids["VELVETFRUIT_EXTRACT"].keys())
            # find keys in window
            filled = False
            lo, hi = 0, len(keys)
            while lo < hi:
                mid_i = (lo + hi) // 2
                if keys[mid_i] < t["ts"]: lo = mid_i + 1
                else: hi = mid_i
            for j in range(lo, len(keys)):
                if keys[j] > t["ts"] + hold_ms: break
                if mids["VELVETFRUIT_EXTRACT"][keys[j]] <= entry:
                    filled = True; break
            if filled:
                n_filled += 1
                pnl = m_fwd - entry  # long pnl
                net.append(pnl)
        if net:
            print(f"  hold={hold_ticks:>3}t  fills={n_filled}/{len(vfe_sells)}  "
                  f"mean PnL/share={mean(net):+6.3f}  t={t_stat(net):+5.2f}  "
                  f"total={sum(net):+7.1f}")

    # ---- AXIS 4: VEV_6000/6500 free 0.5/share extraction ------------------
    print("\n=== AXIS 4: VEV_6000/6500 — already 0.5/share captured? ===")
    for sym in ("VEV_6000", "VEV_6500"):
        sells_22 = [t for t in trades if t["seller"] == "Mark 22" and t["symbol"] == sym]
        buys_01 = [t for t in trades if t["buyer"] == "Mark 01" and t["symbol"] == sym]
        print(f"\n{sym}: Mark 22 sells={len(sells_22)} (avg qty={mean(t['qty'] for t in sells_22) if sells_22 else 0:.1f})  "
              f"Mark 01 buys={len(buys_01)}")
        prices_22 = [t["price"] for t in sells_22]
        if prices_22:
            print(f"  M22 sell price distribution: min={min(prices_22)} max={max(prices_22)} "
                  f"mean={mean(prices_22):.2f}")
        # Are there any ticks where mid is HIGHER than 0.5? If so, we could front-run.
        elevated = sum(1 for ts, m in mids[sym].items() if m > 0.5)
        total_ticks = len(mids[sym])
        print(f"  ticks with mid>0.5: {elevated}/{total_ticks} ({100*elevated/total_ticks:.1f}%)")

    # ---- AXIS 5: time-of-day clustering -----------------------------------
    print("\n=== AXIS 5: Mark 22 daily timing pattern ===")
    # bucket intra-day timestamp into deciles
    for product in ("HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", "VEV_5200", "VEV_6000"):
        sells = [t for t in m22 if t["symbol"] == product and t["seller"] == "Mark 22"]
        if not sells: continue
        buckets = Counter()
        for t in sells:
            buckets[t["ts_intra"] // 100_000] += 1  # 10 buckets per day
        print(f"\n{product} (n={len(sells)})  decile counts:")
        for d in sorted(buckets):
            print(f"  decile {d}: {buckets[d]}")

    # daily counts by date
    print("\nMark 22 SELL counts per (day, product):")
    by_dp = Counter()
    for t in m22:
        if t["seller"] == "Mark 22":
            by_dp[(t["day"], t["symbol"])] += 1
    rows = sorted(by_dp.items())
    for (d, p), c in rows:
        print(f"  day {d}  {p:<25}  {c}")

    # ---- BONUS: HP fade with directional gating --------------------------
    # The mandate cited n=19, t=-7.27. Let's find what filter gives that.
    print("\n=== BONUS: HP fade — try different filters to find the n=19, t=-7.27 cell ===")
    # try qty thresholds × horizons
    for qty_min in [1, 3, 5, 8, 10]:
        for h in [1, 2, 3, 5]:
            h_ms = h * TICK
            sub = [t for t in hp_sells if t["qty"] >= qty_min]
            deltas = []
            for t in sub:
                m_now = mids["HYDROGEL_PACK"].get(t["ts"])
                m_fwd = fwd_mid(mids["HYDROGEL_PACK"], t["ts"], h_ms)
                if m_now is None or m_fwd is None: continue
                deltas.append(m_fwd - m_now)
            if deltas:
                ts_v = t_stat(deltas)
                if abs(ts_v) >= 3 or len(deltas) <= 30:
                    print(f"  qty≥{qty_min}  h={h}t  n={len(deltas):>3}  "
                          f"mean={mean(deltas):+6.3f}  t={ts_v:+6.2f}")


if __name__ == "__main__":
    main()
