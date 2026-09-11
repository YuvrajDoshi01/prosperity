"""Mark 49 reverse-engineering for R4 voucher (VFE) anti-Olivia signal.

Goal: validate the 5 hypotheses passed in the brief and quantify edge.
1. Direct fade (Mark 49 sells VFE qty>=8 → SHORT for N ticks)
2. Pre-position (cluster detection of Mark 49 firings)
3. Mark 49 + Mark 55 sequence (combined → -1.13 fwd)
4. Mark 49 + Mark 14 BUY sequence (-1.41 fwd, t=-2.87)
5. Daily extrema concentration check.

Outputs ranking + chosen filter combo for r4_v6_m49.py.
"""
from __future__ import annotations
import csv, math, statistics
from pathlib import Path
from collections import defaultdict

ROOT = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4")
PRODUCT = "VELVETFRUIT_EXTRACT"

def load_trades(day):
    rows = []
    with open(ROOT / f"trades_round_4_day_{day}.csv") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            rows.append({
                "ts": int(row["timestamp"]),
                "buyer": row["buyer"],
                "seller": row["seller"],
                "sym": row["symbol"],
                "px": float(row["price"]),
                "qty": int(row["quantity"]),
            })
    return rows

def load_prices(day):
    """Returns dict timestamp -> dict[symbol] -> mid"""
    out = defaultdict(dict)
    with open(ROOT / f"prices_round_4_day_{day}.csv") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            try:
                ts = int(row["timestamp"])
                sym = row["product"]
                bb = row.get("bid_price_1") or ""
                ba = row.get("ask_price_1") or ""
                if bb and ba and bb != "" and ba != "":
                    mid = (float(bb) + float(ba)) / 2.0
                    out[ts][sym] = mid
            except Exception:
                pass
    return out

def main():
    all_trades = []
    all_mids = {}
    for d in (1, 2, 3):
        for t in load_trades(d):
            t["day"] = d
            all_trades.append(t)
        for ts, syms in load_prices(d).items():
            all_mids[(d, ts)] = syms

    # Restrict to VFE
    vfe_trades = [t for t in all_trades if t["sym"] == PRODUCT]

    def mid_at(day, ts):
        syms = all_mids.get((day, ts))
        if not syms: return None
        return syms.get(PRODUCT)

    def fwd_mid(day, ts, h_ts):
        return mid_at(day, ts + h_ts)

    # ---------- Mark 49 stats ----------
    m49_vfe = []  # (day, ts, side ['B'/'S'], qty, px)
    for t in vfe_trades:
        if t["seller"] == "Mark 49":
            m49_vfe.append((t["day"], t["ts"], "S", t["qty"], t["px"]))
        elif t["buyer"] == "Mark 49":
            m49_vfe.append((t["day"], t["ts"], "B", t["qty"], t["px"]))

    print(f"Mark 49 VFE trades total = {len(m49_vfe)}")
    s_count = sum(1 for x in m49_vfe if x[2] == "S")
    b_count = sum(1 for x in m49_vfe if x[2] == "B")
    print(f"  Sells: {s_count}, Buys: {b_count}")

    # Forward mid drop after Mark 49 sells, by horizon
    horizons = [1, 5, 10, 25, 50, 100, 200]
    print("\n=== Mark 49 SELL → mid change (all qty) ===")
    for H in horizons:
        diffs = []
        for d, ts, side, q, px in m49_vfe:
            if side != "S": continue
            now = mid_at(d, ts)
            fut = fwd_mid(d, ts, H * 100)  # ts step is 100
            if now is None or fut is None: continue
            diffs.append(fut - now)
        if diffs:
            mu = statistics.mean(diffs)
            sd = statistics.pstdev(diffs) if len(diffs) > 1 else 0
            t = mu / (sd / math.sqrt(len(diffs))) if sd > 0 else 0
            print(f"  H={H:3d}  n={len(diffs):4d}  mean={mu:+.2f}  sd={sd:.2f}  t={t:+.2f}")

    # By qty cutoffs
    print("\n=== Mark 49 SELL by qty ≥ X (H=10) ===")
    for cutoff in [1, 4, 8, 12, 16]:
        diffs = []
        for d, ts, side, q, px in m49_vfe:
            if side != "S" or q < cutoff: continue
            now = mid_at(d, ts)
            fut = fwd_mid(d, ts, 10 * 100)
            if now is None or fut is None: continue
            diffs.append(fut - now)
        if diffs:
            mu = statistics.mean(diffs)
            sd = statistics.pstdev(diffs) if len(diffs) > 1 else 0
            t = mu / (sd / math.sqrt(len(diffs))) if sd > 0 else 0
            print(f"  qty>={cutoff:2d}  n={len(diffs):4d}  mean={mu:+.2f}  sd={sd:.2f}  t={t:+.2f}")

    # ---------- Mark 49 + sequence ----------
    # For each Mark 49 SELL, look ahead 100 ticks for follow-on Mark 55 SELL or Mark 14 BUY.
    print("\n=== Mark 49 SELL → Mark 55 SELL within 100 ticks ===")
    # Build per-day index of vfe_trades sorted by ts
    by_day = defaultdict(list)
    for t in vfe_trades:
        by_day[t["day"]].append(t)
    for d in by_day:
        by_day[d].sort(key=lambda r: r["ts"])

    def sequence_signal(trigger_role_name, trigger_side,
                        followup_role, followup_side, window_ts=10000):
        """Yield (day, m49_ts) where Mark 49 SELLs and followup matches in window."""
        results = []
        for d, day_trades in by_day.items():
            # Filter day trades to Mark 49 sells and followups
            m49s = [t for t in day_trades
                    if t["seller"] == "Mark 49"]
            for t in m49s:
                ts0 = t["ts"]
                # Find any followup trade in (ts0, ts0+window_ts]
                for u in day_trades:
                    if u["ts"] <= ts0: continue
                    if u["ts"] > ts0 + window_ts: break
                    if followup_side == "S" and u["seller"] == followup_role:
                        results.append((d, ts0, u["ts"]))
                        break
                    if followup_side == "B" and u["buyer"] == followup_role:
                        results.append((d, ts0, u["ts"]))
                        break
        return results

    seq_55 = sequence_signal("Mark 49", "S", "Mark 55", "S", window_ts=10000)
    seq_14 = sequence_signal("Mark 49", "S", "Mark 14", "B", window_ts=10000)
    print(f"  Mark 49S → Mark 55S within 100 ticks: n={len(seq_55)}")
    print(f"  Mark 49S → Mark 14B within 100 ticks: n={len(seq_14)}")

    # Forward returns from m49 entry
    for label, seq in [("Mark 49S → Mark 55S", seq_55),
                       ("Mark 49S → Mark 14B", seq_14)]:
        for H in [10, 25, 50, 100]:
            diffs = []
            for d, ts0, _ in seq:
                now = mid_at(d, ts0)
                fut = fwd_mid(d, ts0, H * 100)
                if now is None or fut is None: continue
                diffs.append(fut - now)
            if diffs:
                mu = statistics.mean(diffs)
                sd = statistics.pstdev(diffs) if len(diffs) > 1 else 0
                t = mu / (sd / math.sqrt(len(diffs))) if sd > 0 else 0
                print(f"  {label} H={H:3d}  n={len(diffs):4d}  mean={mu:+.2f}  t={t:+.2f}")

    # ---------- Daily extrema check ----------
    print("\n=== Daily VFE mid range and Mark 49 placement ===")
    for d in (1, 2, 3):
        mids = [m for (dd, ts), syms in all_mids.items() if dd == d for sym, m in syms.items() if sym == PRODUCT]
        if not mids: continue
        mn = min(mids); mx = max(mids); rng = mx - mn
        if rng <= 0: continue
        # For each Mark 49 sell, what fraction of daily range is current mid?
        bucket = defaultdict(int)  # decile bucket
        for dd, ts, side, q, px in m49_vfe:
            if dd != d or side != "S": continue
            m = mid_at(d, ts)
            if m is None: continue
            pct = (m - mn) / rng
            bkt = min(9, int(pct * 10))
            bucket[bkt] += 1
        total = sum(bucket.values())
        print(f"  Day {d}: VFE range [{mn:.0f}, {mx:.0f}] (Δ={rng:.0f}). M49 SELL placement (decile of daily range):")
        for k in range(10):
            n = bucket.get(k, 0)
            star = "*" * (n * 30 // total) if total else ""
            print(f"    {k*10:3d}%-{(k+1)*10:3d}% : {n:3d}  {star}")

    # ---------- Trade simulation: direct fade only ----------
    print("\n=== SIMULATION: LONG-fade Mark 49 SELL qty>=X, hold N ticks ===")
    # SIGN FLIPPED — Mark 49 SELL precedes mid RISE in this dataset.
    # Strategy: when Mark 49 SELLs, BUY SIZE at ask; flatten after H ticks at bid.
    # MTM = (mid_tH - mid_t0) * SIZE (positive when mid rises).
    SIZE = 30
    for cutoff in [1, 4, 8, 12]:
        for H in [1, 5, 10, 25, 50]:
            pnls = []
            for d, ts, side, q, px in m49_vfe:
                if side != "S" or q < cutoff: continue
                now = mid_at(d, ts)
                fut = fwd_mid(d, ts, H * 100)
                if now is None or fut is None: continue
                pnls.append((fut - now) * SIZE)
            if pnls:
                tot = sum(pnls)
                hit = sum(1 for p in pnls if p > 0) / len(pnls)
                print(f"  qty>={cutoff:2d} H={H:3d}  n={len(pnls):3d}  total=${tot:+8.0f}  hit={hit:.0%}  avg=${tot/len(pnls):+.1f}")

    # Per-day breakdown for the best filter
    print("\n=== Per-day LONG-fade qty>=8 H=10 (SIZE=30) ===")
    for d in (1, 2, 3):
        pnls = []
        for dd, ts, side, q, px in m49_vfe:
            if dd != d or side != "S" or q < 8: continue
            now = mid_at(d, ts)
            fut = fwd_mid(d, ts, 10 * 100)
            if now is None or fut is None: continue
            pnls.append((fut - now) * SIZE)
        if pnls:
            tot = sum(pnls)
            print(f"  Day {d} n={len(pnls)} total=${tot:+8.0f}")

    # Test 1k probe day-3 window only (timestamps 0..99,900)
    print("\n=== 1k probe day-3 only (ts<=99900) LONG-fade qty>=8 H=10 ===")
    pnls = []
    for d, ts, side, q, px in m49_vfe:
        if d != 3 or ts > 99900 or side != "S" or q < 8: continue
        now = mid_at(d, ts)
        fut = fwd_mid(d, ts, 10 * 100)
        if now is None or fut is None: continue
        pnls.append((fut - now) * SIZE)
    if pnls:
        print(f"  n={len(pnls)} total=${sum(pnls):+.0f}")
    else:
        print("  no signals in 1k probe window")


if __name__ == "__main__":
    main()
