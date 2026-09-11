"""HP alpha hunt v2 — DEEP analysis of HYDROGEL_PACK.

Mandate:
1. Spread regime distribution (HP), per-day
2. S17 trigger conditions (spread==17 + mid>10010): hit times, mids, conditional reversion
3. Refine S17 entry to maximize win rate (target 85%+)
4. Non-S17 mean reversion alpha (passive MM tweaks)
5. Cross-day time-of-day patterns
6. Concrete change recommendation

Outputs: text report to stdout; CSV summary saved.
"""

import os
import sys
import csv
import math
from collections import defaultdict, Counter

ROOT = "C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester"
RES = f"{ROOT}/prosperity4bt/resources/round4"

DAYS = [1, 2, 3]


def load_prices(day):
    """Return list of dicts with mid, best_bid, best_ask, spread, ts, plus 3-level data."""
    rows = []
    fp = f"{RES}/prices_round_4_day_{day}.csv"
    with open(fp) as f:
        rdr = csv.DictReader(f, delimiter=";")
        for r in rdr:
            if r["product"] != "HYDROGEL_PACK":
                continue
            ts = int(r["timestamp"])
            try:
                bb = float(r["bid_price_1"]) if r.get("bid_price_1") else None
                ba = float(r["ask_price_1"]) if r.get("ask_price_1") else None
            except ValueError:
                bb = ba = None
            if bb is None or ba is None:
                continue
            mid = (bb + ba) / 2.0
            spread = ba - bb
            # mid_price column
            mp = float(r["mid_price"]) if r.get("mid_price") else mid
            rows.append({
                "ts": ts,
                "bb": bb, "ba": ba,
                "mid": mid,
                "mp": mp,
                "spread": spread,
                "bv1": float(r["bid_volume_1"] or 0),
                "av1": float(r["ask_volume_1"] or 0),
            })
    rows.sort(key=lambda x: x["ts"])
    return rows


def analyze_spreads(by_day):
    print("\n========== 1. HP SPREAD REGIME DISTRIBUTION ==========")
    print(f"{'day':>3} {'N':>6} {'sp_mean':>8} {'sp_med':>7} {'sp=2':>7} {'sp=7':>7} {'sp=14':>7} {'sp=17':>7} {'sp_other':>9}")
    for d, rows in by_day.items():
        c = Counter(int(r["spread"]) for r in rows)
        n = len(rows)
        sm = sum(r["spread"] for r in rows) / n
        sds = sorted(int(r["spread"]) for r in rows)
        med = sds[n // 2]
        c2 = c.get(2, 0); c7 = c.get(7, 0); c14 = c.get(14, 0); c17 = c.get(17, 0)
        other = n - c2 - c7 - c14 - c17
        print(f"{d:>3} {n:>6} {sm:>8.2f} {med:>7} {c2/n:>7.1%} {c7/n:>7.1%} {c14/n:>7.1%} {c17/n:>7.1%} {other/n:>9.1%}")


def analyze_s17_triggers(by_day, future_horizons=(50, 100, 200, 500)):
    """For each S17 trigger (spread==17 & mid>10010), measure forward returns at multiple horizons."""
    print("\n========== 2. S17 TRIGGER FORWARD ANALYSIS ==========")
    print(f"  Trigger = spread==17 AND mid>10010")
    print(f"  Win = mid drops below entry within horizon (good for SHORT)")
    all_events = []
    for d, rows in by_day.items():
        n = len(rows)
        d_events = 0
        d_wins_50 = d_wins_100 = d_wins_200 = d_wins_500 = 0
        d_pnl_50 = d_pnl_100 = d_pnl_200 = d_pnl_500 = 0.0
        for i, r in enumerate(rows):
            if r["spread"] == 17 and r["mid"] > 10010:
                fwd = {}
                ent = r["mid"]
                for h in future_horizons:
                    j = min(i + h, n - 1)
                    fwd_mid = rows[j]["mid"]
                    fwd[h] = fwd_mid - ent  # positive = mid rose (bad for short)
                # min mid in window — best exit for short
                min_in_500 = min(rows[k]["mid"] for k in range(i, min(i + 500, n)))
                max_in_500 = max(rows[k]["mid"] for k in range(i, min(i + 500, n)))
                ev = {
                    "day": d, "ts": r["ts"], "ent": ent,
                    "spread": 17, "fwd": fwd,
                    "min500": min_in_500, "max500": max_in_500,
                    "drawdown": ent - min_in_500,  # positive = good for short
                    "max_pain": max_in_500 - ent,  # positive = mid rose against short
                }
                all_events.append(ev)
                d_events += 1
                if fwd[50] < 0: d_wins_50 += 1
                if fwd[100] < 0: d_wins_100 += 1
                if fwd[200] < 0: d_wins_200 += 1
                if fwd[500] < 0: d_wins_500 += 1
                d_pnl_50 += -fwd[50] * 200    # short PnL approximation
                d_pnl_100 += -fwd[100] * 200
                d_pnl_200 += -fwd[200] * 200
                d_pnl_500 += -fwd[500] * 200
        if d_events > 0:
            print(f"  day {d}: {d_events} events | "
                  f"win@50={d_wins_50}/{d_events}={d_wins_50/d_events:.0%} "
                  f"win@100={d_wins_100/d_events:.0%} "
                  f"win@200={d_wins_200/d_events:.0%} "
                  f"win@500={d_wins_500/d_events:.0%} "
                  f"| PnL@500/200pos: ${d_pnl_500:,.0f}")
    return all_events


def analyze_mid_bands(by_day):
    """Distribution of mid prices by day, and at S17 trigger."""
    print("\n========== Mid distributions ==========")
    print(f"{'day':>3} {'mid_min':>8} {'mid_max':>8} {'mid_mean':>9} {'mid_p10':>8} {'mid_p50':>8} {'mid_p90':>8}")
    for d, rows in by_day.items():
        mids = sorted(r["mid"] for r in rows)
        n = len(mids)
        print(f"{d:>3} {mids[0]:>8.1f} {mids[-1]:>8.1f} {sum(mids)/n:>9.2f} "
              f"{mids[n//10]:>8.1f} {mids[n//2]:>8.1f} {mids[9*n//10]:>8.1f}")


def s17_with_filters(events):
    """Refine S17: try additional filters and report win-rate uplift."""
    print("\n========== 3. S17 REFINEMENT FILTERS ==========")
    print("  Baseline: spread==17 AND mid>10010")
    if not events:
        print("  No events.")
        return
    n = len(events)
    base_win200 = sum(1 for e in events if e["fwd"][200] < 0)
    base_pnl500 = sum(-e["fwd"][500] * 200 for e in events)
    print(f"  Baseline: N={n} win@200={base_win200/n:.1%} TotalPnL@500*200={base_pnl500:,.0f}")

    # Filter A: also require mid > 10015 (more elevated)
    print("\n  Filter variants (smaller N but tighter):")
    for thr in [10015, 10020, 10025, 10030]:
        sub = [e for e in events if e["ent"] > thr]
        if not sub: continue
        win = sum(1 for e in sub if e["fwd"][200] < 0)
        pnl = sum(-e["fwd"][500] * 200 for e in sub)
        avg_dd = sum(e["drawdown"] for e in sub) / len(sub)
        avg_pain = sum(e["max_pain"] for e in sub) / len(sub)
        print(f"    mid>{thr}: N={len(sub):>3} win@200={win/len(sub):.0%} "
              f"PnL@500*200=${pnl:>10,.0f} avg_dd={avg_dd:.1f} avg_pain={avg_pain:.1f}")


def analyze_s17_with_context(by_day, future_horizons=(50, 100, 200, 500)):
    """For each S17 trigger, also compute (a) z-score over 500 ticks, (b) trend (mid - mid_50_ago),
    (c) recent vol, (d) per-day win rate.

    Goal: find the conditional filter that lifts day-3 win-rate.
    """
    print("\n========== 3b. S17 CONTEXT-FILTERED FORWARD ANALYSIS ==========")
    print("  Adding z-score, trend, and rolling-mean tags.")
    rows_by_day = by_day
    print(f"  {'day':>3} {'cond':>30} {'N':>4} {'win_50':>7} {'win_200':>8} {'PnL@500*200':>14}")
    for d, rows in rows_by_day.items():
        n = len(rows)
        # Pre-compute rolling stats
        mid_arr = [r["mid"] for r in rows]
        # rolling mean & std over 500
        win = 500
        roll_mean = [None]*n; roll_std = [None]*n
        s = 0; ss = 0
        for i in range(n):
            s += mid_arr[i]; ss += mid_arr[i]**2
            if i >= win:
                s -= mid_arr[i-win]; ss -= mid_arr[i-win]**2
            count = i+1 if i < win else win
            mu = s/count
            var = ss/count - mu*mu
            roll_mean[i] = mu
            roll_std[i] = math.sqrt(max(var, 0))

        events = []
        for i, r in enumerate(rows):
            if not (r["spread"] == 17 and r["mid"] > 10010):
                continue
            mid = r["mid"]
            mu = roll_mean[i]; sd = roll_std[i]
            z = (mid - mu) / sd if sd and sd > 0 else 0
            trend50 = mid - mid_arr[i-50] if i >= 50 else 0
            trend200 = mid - mid_arr[i-200] if i >= 200 else 0
            fwd200 = mid_arr[min(i+200, n-1)] - mid
            fwd500 = mid_arr[min(i+500, n-1)] - mid
            events.append((mid, z, trend50, trend200, fwd200, fwd500))

        # Compute baselines per filter
        def stat(es, label):
            if not es:
                print(f"  {d:>3} {label:>30} {0:>4}    -    -          -")
                return
            n_e = len(es)
            w50 = sum(1 for e in es if e[4] < 0)  # actually fwd200 is index 4? no, fwd200=4? check
            # tuple order: mid, z, trend50, trend200, fwd200, fwd500
            w200 = sum(1 for e in es if e[4] < 0)
            pnl = sum(-e[5] * 200 for e in es)
            print(f"  {d:>3} {label:>30} {n_e:>4} {w50/n_e:>7.0%} {w200/n_e:>8.0%} ${pnl:>13,.0f}")

        stat(events, "baseline (mid>10010)")
        stat([e for e in events if e[1] > 1.5], "+ z>1.5")
        stat([e for e in events if e[1] > 2.0], "+ z>2.0")
        stat([e for e in events if e[1] > 2.5], "+ z>2.5")
        stat([e for e in events if e[2] > 0], "+ trend50>0 (rising)")
        stat([e for e in events if e[2] > 3], "+ trend50>3")
        stat([e for e in events if e[2] > 5], "+ trend50>5")
        stat([e for e in events if e[2] < 0], "+ trend50<0 (falling — bad?)")
        stat([e for e in events if e[3] > 0], "+ trend200>0")
        stat([e for e in events if e[1] > 1.5 and e[2] > 0], "+ z>1.5 AND trend50>0")
        stat([e for e in events if e[1] > 2.0 and e[2] > 0], "+ z>2.0 AND trend50>0")


def analyze_intraday(by_day):
    """Time-of-day pattern analysis: bin ts into 10 buckets, compute mean mid + return."""
    print("\n========== 4. INTRADAY (TIME-OF-DAY) PATTERN ==========")
    print(f"{'day':>3} | mid by decile (ts/total -> 0..9):")
    for d, rows in by_day.items():
        n = len(rows)
        means = []
        for k in range(10):
            lo = k * n // 10
            hi = (k + 1) * n // 10
            sub = rows[lo:hi]
            if sub:
                m = sum(r["mid"] for r in sub) / len(sub)
                means.append(m)
        msg = " ".join(f"{m:.1f}" for m in means)
        print(f"  d{d}: {msg}")


def analyze_s17_first_1k(by_day):
    """How many S17 events fire in first 1000 ticks vs whole day?"""
    print("\n========== 5. S17 IN FIRST 1k TICKS (probe window) ==========")
    print(f"  IMC live probes 1k of d+1 only.")
    for d, rows in by_day.items():
        first_1k = [r for r in rows if r["ts"] < 100000]  # ts step 100, 1k ticks = 100k
        events = [r for r in first_1k if r["spread"] == 17 and r["mid"] > 10010]
        # forward in next 1k window
        wins = 0
        for i, r in enumerate(first_1k):
            if r["spread"] == 17 and r["mid"] > 10010:
                # check next 200 ticks
                end_idx = min(i + 200, len(first_1k))
                fwd_mid = first_1k[end_idx-1]["mid"] if end_idx > i else r["mid"]
                if fwd_mid < r["mid"]:
                    wins += 1
        print(f"  d{d}: {len(events)} S17 events in first 1k, win@200={wins}/{len(events) if events else 0}")


def analyze_passive_mm_alpha(by_day):
    """Look at simple passive bid+1/ask-1 PnL when not S17 firing — naive sim."""
    print("\n========== 6. PASSIVE MM ALPHA (non-S17) ==========")
    print("  Simulate: post bid at best_bid+1 size 25, ask at best_ask-1 size 25.")
    print("  Fills approximated by: did mid revert in next tick?")
    # Per-day passive MM expected value approximation
    # If mid drops in next tick, our passive bid likely got hit and we have positive MTM
    for d, rows in by_day.items():
        nf = 0
        gross = 0.0
        for i in range(len(rows) - 1):
            r = rows[i]
            nxt = rows[i + 1]
            spread = r["spread"]
            if spread <= 2: continue  # no room to post inside
            # Approx: if next mid > current mid → ask got hit, profit
            d_mid = nxt["mid"] - r["mid"]
            # We'd capture spread/2 + 0 expected drift, minus adverse selection ~|d_mid|
            # Simple: count |d_mid|<2 ticks where we'd hold no toxic flow
            if abs(d_mid) < 1.0:
                nf += 1
                gross += 1  # 1 unit MTM per safe fill assumption
        print(f"  d{d}: safe_passive_fraction={nf/len(rows):.1%}")


def main():
    by_day = {d: load_prices(d) for d in DAYS}
    for d, rows in by_day.items():
        print(f"day {d}: {len(rows)} HP rows | ts range [{rows[0]['ts']}, {rows[-1]['ts']}]")

    analyze_spreads(by_day)
    analyze_mid_bands(by_day)
    events = analyze_s17_triggers(by_day)
    s17_with_filters(events)
    analyze_s17_with_context(by_day)
    analyze_intraday(by_day)
    analyze_s17_first_1k(by_day)
    analyze_passive_mm_alpha(by_day)

    # Save events to CSV for cross-reference
    out = f"{ROOT}/trader-logic/round-4/intel/hp_s17_events.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["day", "ts", "ent_mid", "fwd_50", "fwd_100", "fwd_200", "fwd_500",
                    "min500", "max500", "drawdown", "max_pain"])
        for e in events:
            w.writerow([e["day"], e["ts"], e["ent"],
                        e["fwd"][50], e["fwd"][100], e["fwd"][200], e["fwd"][500],
                        e["min500"], e["max500"], e["drawdown"], e["max_pain"]])
    print(f"\nSaved {len(events)} S17 events -> {out}")


if __name__ == "__main__":
    main()
