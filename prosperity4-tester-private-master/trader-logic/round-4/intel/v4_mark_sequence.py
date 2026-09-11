"""v4_mark_sequence.py — n-gram detector for cross-Mark temporal sequences (R4).

Mines Mark trade sequences across {10, 100, 1000}-tick windows; tests forward
mid-return predictive power; Bonferroni-corrects across all tested patterns.

Outputs CSV with: pattern, window, n, mean_fwd, t_stat, sig_after_bonf.
"""
import os
import csv
import math
from collections import defaultdict, deque
from statistics import mean, pstdev

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "prosperity4bt", "resources", "round4")
PRODUCTS_OF_INTEREST = {"VELVETFRUIT_EXTRACT", "HYDROGEL_PACK",
                        "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
                        "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
                        "VEV_6000", "VEV_6500"}
# Map our CSV ticker abbreviations to canonical (R4 CSVs use VFE / VEV_K).
TICK = 100  # ms per tick step in CSVs


def load_day(day: int):
    trades = []
    with open(os.path.join(DATA, f"trades_round_4_day_{day}.csv"),
              encoding="utf-8") as f:
        rd = csv.DictReader(f, delimiter=";")
        for r in rd:
            sym = r["symbol"]
            sym_norm = ("VELVETFRUIT_EXTRACT" if sym == "VFE"
                        else "HYDROGEL_PACK" if sym == "HP"
                        else sym)
            trades.append({
                "ts": int(r["timestamp"]),
                "buyer": r["buyer"],
                "seller": r["seller"],
                "symbol": sym_norm,
                "price": float(r["price"]),
                "qty": int(r["quantity"]),
            })
    mids = defaultdict(dict)  # mids[product][ts] = mid
    with open(os.path.join(DATA, f"prices_round_4_day_{day}.csv"),
              encoding="utf-8") as f:
        rd = csv.DictReader(f, delimiter=";")
        for r in rd:
            sym = r["product"]
            try:
                mids[sym][int(r["timestamp"])] = float(r["mid_price"])
            except ValueError:
                pass
    return trades, mids


def fwd_mid(mids_p, ts, horizon_ts):
    target = ts + horizon_ts
    keys = sorted(mids_p.keys())
    # find first key >= target
    lo, hi = 0, len(keys)
    while lo < hi:
        m = (lo + hi) // 2
        if keys[m] < target:
            lo = m + 1
        else:
            hi = m
    if lo >= len(keys):
        return None
    return mids_p[keys[lo]]


def event_tokens(t):
    """Emit one token PER MARK PARTICIPANT in a trade. We use the AGGRESSOR
    convention: only the side that crossed the spread emits the action token,
    based on prior mining (Mark 38 always pays +8, Mark 22 always passive,
    etc.). Aggression heuristic: take side relative to mid would require
    prices; instead we use the prior mining table and emit the buyer token
    only if buyer is in AGGRESSORS, else the seller token, etc.
    """
    out = []
    # Conservative: emit BOTH sides as separate tokens, but tag with role.
    if t["buyer"].startswith("Mark"):
        out.append((t["buyer"], "B", t["symbol"]))
    if t["seller"].startswith("Mark"):
        out.append((t["seller"], "S", t["symbol"]))
    return out


def t_stat(xs):
    if len(xs) < 3:
        return 0.0
    m = mean(xs)
    sd = pstdev(xs)
    if sd == 0:
        return 0.0
    return m / (sd / math.sqrt(len(xs)))


def main():
    all_trades = []
    all_mids = defaultdict(dict)
    for d in (1, 2, 3):
        ts_off = (d - 1) * 1_000_000
        tr, m = load_day(d)
        for x in tr:
            x["ts"] += ts_off
            all_trades.append(x)
        for p, dmap in m.items():
            for ts, mid in dmap.items():
                all_mids[p][ts + ts_off] = mid

    all_trades.sort(key=lambda x: x["ts"])

    # Per-trade event tokens. We focus signals on VFE since prior mining
    # established mark-67/49 as VFE-only directional flow.
    sym_focus = "VELVETFRUIT_EXTRACT"
    horizon = 100  # 10000 ticks-ms = 100 engine ticks
    horizon_ts = horizon * TICK  # 10000 ms
    window_ms_list = [1000, 10_000, 100_000]  # 10/100/1000 ticks

    # Build pair patterns: (Mark_A side_A) -> (Mark_B side_B) within window,
    # measure fwd return on focus product evaluated at the SECOND event.
    marks = ["Mark 01", "Mark 14", "Mark 22", "Mark 38",
             "Mark 49", "Mark 55", "Mark 67"]
    sides = ["B", "S"]
    patterns = []
    for ma in marks:
        for sa in sides:
            for mb in marks:
                for sb in sides:
                    if (ma, sa) == (mb, sb):
                        continue
                    patterns.append(((ma, sa), (mb, sb)))

    rows = []
    for window_ms in window_ms_list:
        # for efficiency: for each pattern, walk trades; for every event A,
        # if within window we see B, record fwd return at B's ts.
        # use a deque of recent VFE-event tokens, index by mark.
        recent = deque()  # (ts, mark, side, symbol)
        # track all VFE-and-related events
        for pat in patterns:
            (ma, sa), (mb, sb) = pat
            samples = []
            recent.clear()
            for tr in all_trades:
                toks = event_tokens(tr)
                if not toks:
                    continue
                # purge old (relative to this trade's ts)
                while recent and recent[0][0] < tr["ts"] - window_ms:
                    recent.popleft()
                # check: any prior event matched A?
                for mk, sd, sym in toks:
                    if mk == mb and sd == sb and sym == sym_focus:
                        for (rts, rmk, rsd, rsym) in recent:
                            if rts >= tr["ts"]:
                                continue
                            if rmk == ma and rsd == sa and rsym == sym_focus:
                                mid_now = all_mids[sym_focus].get(tr["ts"])
                                mid_fwd = fwd_mid(all_mids[sym_focus],
                                                  tr["ts"], horizon_ts)
                                if mid_now is None or mid_fwd is None:
                                    continue
                                sgn = +1 if sb == "B" else -1
                                samples.append(sgn * (mid_fwd - mid_now))
                                break
                # append all tokens of this trade
                for mk, sd, sym in toks:
                    recent.append((tr["ts"], mk, sd, sym))
            n = len(samples)
            if n < 15:
                continue
            t = t_stat(samples)
            rows.append({
                "pattern": f"{ma}{sa} -> {mb}{sb}",
                "window_ms": window_ms,
                "n": n,
                "mean_fwd": round(mean(samples), 3),
                "t_stat": round(t, 2),
            })

    # Bonferroni: cutoff t for two-sided alpha=0.05 over len(rows) tests
    n_tests = len(rows)
    # approx z for alpha/(2n)
    if n_tests:
        alpha = 0.05 / n_tests
        # inverse of standard normal: use a simple approximation
        # via NormalDist
        from statistics import NormalDist
        z_cut = abs(NormalDist().inv_cdf(alpha / 2))
    else:
        z_cut = 4.0

    rows.sort(key=lambda r: -abs(r["t_stat"]))
    out_path = os.path.join(os.path.dirname(__file__),
                            "v4_mark_sequence.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["pattern", "window_ms",
                                          "n", "mean_fwd", "t_stat"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"n_tests={n_tests}  Bonferroni z_cut={z_cut:.2f}")
    print(f"\nTop 25 by |t_stat|:")
    print(f"{'pattern':<40} {'win':>6} {'n':>5} {'mean':>7} {'t':>6}")
    for r in rows[:25]:
        sig = "*" if abs(r["t_stat"]) >= z_cut else " "
        print(f"{r['pattern']:<40} {r['window_ms']:>6} {r['n']:>5} "
              f"{r['mean_fwd']:>7} {r['t_stat']:>6} {sig}")

    # Also: latency study of Mark 22 sell -> Mark 01 buy on VEV strikes.
    print("\n--- Mark22 SELL VEV* -> Mark01 BUY VEV* latency ---")
    deltas = []
    last22 = {}
    for tr in all_trades:
        sym = tr["symbol"]
        if not sym.startswith("VEV_"):
            continue
        if tr.get("seller") == "Mark 22":
            last22[sym] = tr["ts"]
        if tr.get("buyer") == "Mark 01" and sym in last22:
            dt = tr["ts"] - last22[sym]
            if 0 < dt <= 100_000:
                deltas.append(dt)
    if deltas:
        print(f"n={len(deltas)} mean dt={mean(deltas):.0f} ms "
              f"median={sorted(deltas)[len(deltas)//2]} ms")

    return rows, z_cut


if __name__ == "__main__":
    main()
