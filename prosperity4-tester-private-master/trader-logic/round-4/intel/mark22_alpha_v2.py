"""mark22_alpha_v2.py — implementability of Mark 22 → Mark 55 VFE sequence (passive).

The previous v6 attempt with CROSS-SPREAD orders regressed imc -$23k.
This iteration tests PASSIVE BID CAMPING (post bid at best_bid+1 with N-tick lifetime,
no spread cost, only fills if mid temporarily dips to entry).
"""
import os, csv, math
from collections import defaultdict
from statistics import mean, pstdev

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "prosperity4bt", "resources", "round4")
TICK = 100


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
                trades.append({"ts": int(r["timestamp"]) + ts_off, "day": d,
                               "buyer": r["buyer"], "seller": r["seller"],
                               "symbol": sym, "price": float(r["price"]),
                               "qty": int(r["quantity"])})
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


def t_stat(xs):
    if len(xs) < 3: return 0.0
    m = mean(xs); sd = pstdev(xs)
    return 0.0 if sd == 0 else m / (sd / math.sqrt(len(xs)))


def main():
    trades, mids, books = load_all()
    sym = "VELVETFRUIT_EXTRACT"

    # Mark 22 SELL VFE events
    m22_sells = [t for t in trades if t["seller"] == "Mark 22" and t["symbol"] == sym]
    m55_sells = [t for t in trades if t["seller"] == "Mark 55" and t["symbol"] == sym]
    print(f"M22 VFE sells: n={len(m22_sells)}")
    print(f"M55 VFE sells: n={len(m55_sells)}")

    # Find M22S → M55S sequences (within window forward).
    # Then test forward returns and passive bid camping at the M55 trigger time.
    m55_ts = [t["ts"] for t in m55_sells]
    m55_set = sorted(m55_ts)

    # Build trigger list: for each M22S, find first M55S within window
    triggers = []  # (ts of M55S that triggered)
    for tr22 in m22_sells:
        ts22 = tr22["ts"]
        lo, hi = 0, len(m55_set)
        while lo < hi:
            md = (lo + hi) // 2
            if m55_set[md] <= ts22: lo = md + 1
            else: hi = md
        for j in range(lo, len(m55_set)):
            if m55_set[j] - ts22 > 10_000:  # 100 ticks = 10k ms
                break
            triggers.append((ts22, m55_set[j]))
            break  # only first one per m22

    print(f"\nM22S → M55S sequences (within 100 ticks): n={len(triggers)}")

    keys = sorted(mids[sym].keys())

    def fwd_mid(ts, h_ms):
        target = ts + h_ms
        lo, hi = 0, len(keys)
        while lo < hi:
            md = (lo + hi) // 2
            if keys[md] < target: lo = md + 1
            else: hi = md
        return mids[sym][keys[lo]] if lo < len(keys) else None

    # 1) Forward mid measured at M55 trigger time
    print("\n[Forward mid AT M55 trigger]")
    for h in [10, 50, 100, 200, 500]:
        h_ms = h * TICK
        deltas = []
        for ts22, ts55 in triggers:
            m_now = mids[sym].get(ts55)
            m_fwd = fwd_mid(ts55, h_ms)
            if m_now is None or m_fwd is None: continue
            deltas.append(m_fwd - m_now)
        if deltas:
            print(f"  h={h:>3}t  n={len(deltas):>3}  mean Δmid={mean(deltas):+6.3f}  t={t_stat(deltas):+5.2f}")

    # 2) Forward mid AT M22 entry (sooner = more capacity)
    print("\n[Forward mid AT M22 entry — earlier signal]")
    for h in [10, 50, 100, 200, 500]:
        h_ms = h * TICK
        deltas = []
        for ts22, ts55 in triggers:
            m_now = mids[sym].get(ts22)
            m_fwd = fwd_mid(ts22, h_ms)
            if m_now is None or m_fwd is None: continue
            deltas.append(m_fwd - m_now)
        if deltas:
            print(f"  h={h:>3}t  n={len(deltas):>3}  mean Δmid={mean(deltas):+6.3f}  t={t_stat(deltas):+5.2f}")

    # 3) PASSIVE BID at best_bid+1 with hold lifetime (only fill if mid <= entry).
    # Realistic fill model: the bid sits in the book; fill if any mid in window dipped <= entry.
    print("\n[Passive bid camp: post bid at best_bid+1 at M22 sell time, hold N ticks]")
    for hold_t in [10, 50, 100, 200]:
        hold_ms = hold_t * TICK
        net = []
        n_filled = 0
        for ts22, ts55 in triggers:
            b = books[sym].get(ts22)
            if not b: continue
            entry = b["bid"] + 1
            # filled if any mid in (ts22, ts22+hold] <= entry
            lo, hi = 0, len(keys)
            while lo < hi:
                md = (lo + hi) // 2
                if keys[md] < ts22: lo = md + 1
                else: hi = md
            filled = False
            for j in range(lo, len(keys)):
                if keys[j] > ts22 + hold_ms: break
                if mids[sym][keys[j]] <= entry:
                    filled = True; break
            if filled:
                exit_mid = fwd_mid(ts22, hold_ms)
                if exit_mid is None: continue
                pnl = exit_mid - entry  # long pnl
                net.append(pnl)
                n_filled += 1
        if net:
            print(f"  hold={hold_t:>3}t  fills={n_filled}/{len(triggers)}  "
                  f"mean PnL/share={mean(net):+5.2f}  t={t_stat(net):+5.2f}  total={sum(net):+7.1f}")

    # 4) Same as 3 but at M55 trigger (later signal, but cleaner)
    print("\n[Passive bid camp at M55 trigger, hold N ticks]")
    for hold_t in [10, 50, 100, 200]:
        hold_ms = hold_t * TICK
        net = []
        n_filled = 0
        for ts22, ts55 in triggers:
            b = books[sym].get(ts55)
            if not b: continue
            entry = b["bid"] + 1
            lo, hi = 0, len(keys)
            while lo < hi:
                md = (lo + hi) // 2
                if keys[md] < ts55: lo = md + 1
                else: hi = md
            filled = False
            for j in range(lo, len(keys)):
                if keys[j] > ts55 + hold_ms: break
                if mids[sym][keys[j]] <= entry:
                    filled = True; break
            if filled:
                exit_mid = fwd_mid(ts55, hold_ms)
                if exit_mid is None: continue
                pnl = exit_mid - entry
                net.append(pnl)
                n_filled += 1
        if net:
            print(f"  hold={hold_t:>3}t  fills={n_filled}/{len(triggers)}  "
                  f"mean PnL/share={mean(net):+5.2f}  t={t_stat(net):+5.2f}  total={sum(net):+7.1f}")

    # 5) Just Mark 22 alone (no M55 confirmation) — passive bid camp
    print("\n[BASELINE: Passive bid camp at M22 alone, N tick hold]")
    for hold_t in [10, 50, 100, 200]:
        hold_ms = hold_t * TICK
        net = []
        n_filled = 0
        for tr in m22_sells:
            ts22 = tr["ts"]
            b = books[sym].get(ts22)
            if not b: continue
            entry = b["bid"] + 1
            lo, hi = 0, len(keys)
            while lo < hi:
                md = (lo + hi) // 2
                if keys[md] < ts22: lo = md + 1
                else: hi = md
            filled = False
            for j in range(lo, len(keys)):
                if keys[j] > ts22 + hold_ms: break
                if mids[sym][keys[j]] <= entry:
                    filled = True; break
            if filled:
                exit_mid = fwd_mid(ts22, hold_ms)
                if exit_mid is None: continue
                pnl = exit_mid - entry
                net.append(pnl); n_filled += 1
        if net:
            print(f"  hold={hold_t:>3}t  fills={n_filled}/{len(m22_sells)}  "
                  f"mean PnL/share={mean(net):+5.2f}  t={t_stat(net):+5.2f}  total={sum(net):+7.1f}")

    # 6) Trade qty distribution
    qtys = [t["qty"] for t in m22_sells]
    print(f"\nM22 VFE sell qty: mean={mean(qtys):.1f} max={max(qtys)} median={sorted(qtys)[len(qtys)//2]}")

    # 7) DAYS analysis: per-day expected PnL
    print("\nPer-day breakdown (passive bid at M22, hold=10t):")
    by_day = defaultdict(list)
    hold_ms = 10 * TICK
    for tr in m22_sells:
        ts22 = tr["ts"]
        b = books[sym].get(ts22)
        if not b: continue
        entry = b["bid"] + 1
        lo, hi = 0, len(keys)
        while lo < hi:
            md = (lo + hi) // 2
            if keys[md] < ts22: lo = md + 1
            else: hi = md
        filled = False
        for j in range(lo, len(keys)):
            if keys[j] > ts22 + hold_ms: break
            if mids[sym][keys[j]] <= entry: filled = True; break
        if filled:
            exit_mid = fwd_mid(ts22, hold_ms)
            if exit_mid is None: continue
            by_day[tr["day"]].append((exit_mid - entry) * tr["qty"])
    for d in sorted(by_day):
        xs = by_day[d]
        print(f"  day {d}: n={len(xs)} total PnL={sum(xs):+7.1f} (per-trade: {sum(xs)/len(xs):+5.2f})")


if __name__ == "__main__":
    main()
