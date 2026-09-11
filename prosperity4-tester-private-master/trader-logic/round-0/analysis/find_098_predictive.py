#!/usr/bin/env python3
"""
find_098_predictive.py — TOMATOES-only exhaustive predictive correlation search
================================================================================

Goal: Find feature(t) that correlates 0.98+ with something at t+k (k=1,2,3,...).
Only actionable pairs (can become a strategy).

Tests:
  - Every L1/L2/L3 price and volume feature
  - Log volumes, ratios, imbalances, gaps
  - Cumulative sums, rolling means, EMAs
  - All vs: mid(t+k), dmid(t+k), bid(t+k), ask(t+k), spread(t+k), vol(t+k)
  - Lags k = 1, 2, 3, 5, 10, 20, 50
"""

import csv
import os
import math

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "prosperity4bt", "resources", "round0")


def load_tomatoes(day):
    fname = os.path.join(DATA_DIR, f"prices_round_0_day_{day}.csv")
    rows = []
    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["product"] != "TOMATOES":
                continue
            def p(k):
                return int(row[k]) if row.get(k) and row[k] != "" else None
            def v(k):
                return int(row[k]) if row.get(k) and row[k] != "" else 0
            rows.append({
                "ts": int(row["timestamp"]),
                "bid1": p("bid_price_1"), "bv1": v("bid_volume_1"),
                "bid2": p("bid_price_2"), "bv2": v("bid_volume_2"),
                "bid3": p("bid_price_3"), "bv3": v("bid_volume_3"),
                "ask1": p("ask_price_1"), "av1": v("ask_volume_1"),
                "ask2": p("ask_price_2"), "av2": v("ask_volume_2"),
                "ask3": p("ask_price_3"), "av3": v("ask_volume_3"),
                "mid": float(row["mid_price"]),
            })
    return rows


def corr(x, y):
    n = len(x)
    if n < 10:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    sx = math.sqrt(max(0, sum((xi - mx) ** 2 for xi in x) / n))
    sy = math.sqrt(max(0, sum((yi - my) ** 2 for yi in y) / n))
    if sx < 1e-12 or sy < 1e-12:
        return 0.0
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / n
    return cov / (sx * sy)


def safe_log(x):
    return math.log(x) if x > 0 else 0.0


def rolling_mean(series, window):
    out = []
    for i in range(len(series)):
        start = max(0, i - window + 1)
        out.append(sum(series[start:i+1]) / (i - start + 1))
    return out


def ema(series, alpha):
    out = [series[0]]
    for i in range(1, len(series)):
        out.append(out[-1] + alpha * (series[i] - out[-1]))
    return out


def cumsum(series):
    out = []
    s = 0
    for x in series:
        s += x
        out.append(s)
    return out


def main():
    for day in [-2, -1, 0]:
        print(f"\n{'='*80}")
        print(f"  DAY {day} — TOMATOES ONLY — PREDICTIVE CORRELATIONS")
        print(f"{'='*80}")

        rows = load_tomatoes(day)
        n = len(rows)
        print(f"  Ticks: {n}")

        # ── Extract raw series ──
        mid = [r["mid"] for r in rows]
        bid1 = [r["bid1"] or 0 for r in rows]
        ask1 = [r["ask1"] or 0 for r in rows]
        bv1 = [r["bv1"] for r in rows]
        av1 = [r["av1"] for r in rows]
        bv2 = [r["bv2"] for r in rows]
        av2 = [r["av2"] for r in rows]
        bv3 = [r["bv3"] for r in rows]
        av3 = [r["av3"] for r in rows]
        bid2 = [r["bid2"] or 0 for r in rows]
        ask2 = [r["ask2"] or 0 for r in rows]
        bid3 = [r["bid3"] or 0 for r in rows]
        ask3 = [r["ask3"] or 0 for r in rows]
        spread = [a - b for a, b in zip(ask1, bid1)]

        # ── Derived features ──
        dmid = [0] + [mid[i] - mid[i-1] for i in range(1, n)]
        dbid = [0] + [bid1[i] - bid1[i-1] for i in range(1, n)]
        dask = [0] + [ask1[i] - ask1[i-1] for i in range(1, n)]

        total_bv = [bv1[i] + bv2[i] + bv3[i] for i in range(n)]
        total_av = [av1[i] + av2[i] + av3[i] for i in range(n)]

        # Log volumes
        log_bv1 = [safe_log(x) for x in bv1]
        log_av1 = [safe_log(x) for x in av1]
        log_bv2 = [safe_log(x) for x in bv2]
        log_av2 = [safe_log(x) for x in av2]
        log_total_bv = [safe_log(x) for x in total_bv]
        log_total_av = [safe_log(x) for x in total_av]

        # Volume imbalances
        obi_l1 = [(bv1[i] - av1[i]) / (bv1[i] + av1[i]) if (bv1[i] + av1[i]) > 0 else 0 for i in range(n)]
        obi_l2 = [(bv2[i] - av2[i]) / (bv2[i] + av2[i]) if (bv2[i] + av2[i]) > 0 else 0 for i in range(n)]
        obi_total = [(total_bv[i] - total_av[i]) / (total_bv[i] + total_av[i]) if (total_bv[i] + total_av[i]) > 0 else 0 for i in range(n)]

        # Ratios
        l2l1_bid = [bv2[i] / bv1[i] if bv1[i] > 0 else 0 for i in range(n)]
        l2l1_ask = [av2[i] / av1[i] if av1[i] > 0 else 0 for i in range(n)]
        l3l1_bid = [bv3[i] / bv1[i] if bv1[i] > 0 else 0 for i in range(n)]
        l3l1_ask = [av3[i] / av1[i] if av1[i] > 0 else 0 for i in range(n)]

        # Microprice
        mp = [bid1[i] + bv1[i] / (bv1[i] + av1[i]) * (ask1[i] - bid1[i])
              if (bv1[i] + av1[i]) > 0 else mid[i] for i in range(n)]
        mp_dev = [mp[i] - mid[i] for i in range(n)]

        # L2 microprice
        mp_l2 = [bid2[i] + bv2[i] / (bv2[i] + av2[i]) * (ask2[i] - bid2[i])
                  if (bv2[i] + av2[i]) > 0 and bid2[i] > 0 else mid[i] for i in range(n)]
        mp_l2_dev = [mp_l2[i] - mid[i] for i in range(n)]

        # Gap asymmetry
        gap_asym = [(bid1[i] - bid2[i]) - (ask2[i] - ask1[i]) if bid2[i] > 0 else 0 for i in range(n)]

        # Dist-weighted OBI
        dw_obi = []
        for i in range(n):
            m = mid[i]
            num = 0
            den = 0
            for bp, bvol in [(bid1[i], bv1[i]), (bid2[i], bv2[i]), (bid3[i], bv3[i])]:
                if bp > 0 and bvol > 0:
                    d = max(1, m - bp)
                    num += bvol / d
                    den += bvol / d
            for ap, avol in [(ask1[i], av1[i]), (ask2[i], av2[i]), (ask3[i], av3[i])]:
                if ap > 0 and avol > 0:
                    d = max(1, ap - m)
                    num -= avol / d
                    den += avol / d
            dw_obi.append(num / den if den > 0 else 0)

        # EMAs of mid
        ema_5 = ema(mid, 2 / 6)
        ema_10 = ema(mid, 2 / 11)
        ema_20 = ema(mid, 2 / 21)
        ema_50 = ema(mid, 2 / 51)
        ema_100 = ema(mid, 0.01)

        ema_dev_5 = [mid[i] - ema_5[i] for i in range(n)]
        ema_dev_10 = [mid[i] - ema_10[i] for i in range(n)]
        ema_dev_20 = [mid[i] - ema_20[i] for i in range(n)]
        ema_dev_50 = [mid[i] - ema_50[i] for i in range(n)]
        ema_dev_100 = [mid[i] - ema_100[i] for i in range(n)]

        # Rolling mean of dmid
        rm_dmid_5 = rolling_mean(dmid, 5)
        rm_dmid_10 = rolling_mean(dmid, 10)
        rm_dmid_20 = rolling_mean(dmid, 20)

        # Cumulative dmid
        cum_dmid = cumsum(dmid)

        # Rolling vol
        rvol_10 = []
        for i in range(n):
            start = max(0, i - 9)
            window = dmid[start:i+1]
            m = sum(window) / len(window)
            rvol_10.append(math.sqrt(sum((x - m) ** 2 for x in window) / len(window)))

        # Log volume differences
        log_bv1_av1 = [log_bv1[i] - log_av1[i] for i in range(n)]
        log_bv2_av2 = [log_bv2[i] - log_av2[i] for i in range(n)]
        log_total_diff = [log_total_bv[i] - log_total_av[i] for i in range(n)]

        # Volume sums
        vol_sum_l1 = [bv1[i] + av1[i] for i in range(n)]
        vol_sum_total = [total_bv[i] + total_av[i] for i in range(n)]

        # ── Build feature dictionary ──
        features = {
            # Prices
            "mid": mid, "bid1": bid1, "ask1": ask1, "bid2": bid2, "ask2": ask2,
            "bid3": bid3, "ask3": ask3, "spread": spread,
            # Price changes
            "dmid": dmid, "dbid": dbid, "dask": dask,
            # Volumes raw
            "bv1": bv1, "av1": av1, "bv2": bv2, "av2": av2, "bv3": bv3, "av3": av3,
            "total_bv": total_bv, "total_av": total_av,
            # Log volumes
            "log_bv1": log_bv1, "log_av1": log_av1, "log_bv2": log_bv2, "log_av2": log_av2,
            "log_total_bv": log_total_bv, "log_total_av": log_total_av,
            # Imbalances
            "obi_l1": obi_l1, "obi_l2": obi_l2, "obi_total": obi_total,
            "dw_obi": dw_obi, "gap_asym": gap_asym,
            # Ratios
            "l2l1_bid": l2l1_bid, "l2l1_ask": l2l1_ask,
            "l3l1_bid": l3l1_bid, "l3l1_ask": l3l1_ask,
            # Microprice
            "microprice": mp, "mp_dev": mp_dev,
            "mp_l2": mp_l2, "mp_l2_dev": mp_l2_dev,
            # EMAs
            "ema_dev_5": ema_dev_5, "ema_dev_10": ema_dev_10,
            "ema_dev_20": ema_dev_20, "ema_dev_50": ema_dev_50,
            "ema_dev_100": ema_dev_100,
            # Rolling
            "rm_dmid_5": rm_dmid_5, "rm_dmid_10": rm_dmid_10, "rm_dmid_20": rm_dmid_20,
            "cum_dmid": cum_dmid, "rvol_10": rvol_10,
            # Log vol diffs
            "log_bv1-av1": log_bv1_av1, "log_bv2-av2": log_bv2_av2,
            "log_total_diff": log_total_diff,
            # Vol sums
            "vol_sum_l1": vol_sum_l1, "vol_sum_total": vol_sum_total,
        }

        # ── Targets: future values at lag k ──
        targets = {
            "mid": mid, "dmid": dmid, "bid1": bid1, "ask1": ask1,
            "spread": spread, "microprice": mp, "mp_dev": mp_dev,
            "bv1": bv1, "av1": av1, "total_bv": total_bv, "total_av": total_av,
            "obi_l1": obi_l1, "obi_total": obi_total,
            "bv2": bv2, "av2": av2, "vol_sum_l1": vol_sum_l1,
            "log_bv1": log_bv1, "log_av1": log_av1,
            "log_total_bv": log_total_bv, "log_total_av": log_total_av,
        }

        lags = [1, 2, 3, 5, 10, 20, 50]

        all_results = []
        tested = 0

        for fname, fvals in features.items():
            for tname, tvals in targets.items():
                for lag in lags:
                    if lag >= n - 10:
                        continue
                    # feature(t) vs target(t+lag)
                    x = fvals[:n - lag]
                    y = tvals[lag:]
                    r = corr(x, y)
                    tested += 1

                    # Skip trivial self-correlations at lag 0 equivalent
                    # (mid(t) vs mid(t+1) = 0.999 is known trivial)
                    # But we still record them for completeness
                    all_results.append((abs(r), r, lag, fname, tname, len(x)))

        all_results.sort(reverse=True)

        print(f"  Tested {tested} pairs")
        print(f"\n  TOP 50 (|r| > 0.90):")
        print(f"  {'Feature(t)':<25s}   {'Target(t+k)':<25s} {'lag':>4s} {'r':>9s} {'|r|':>8s}")
        print(f"  {'-'*25}   {'-'*25} {'-'*4} {'-'*9} {'-'*8}")

        shown = 0
        seen = set()
        for abs_r, r, lag, fname, tname, cnt in all_results:
            if abs_r < 0.90:
                break
            # De-duplicate trivial variants (mid→mid at different lags)
            key = f"{fname}→{tname}"
            if key in seen and abs_r < 0.98:
                continue
            seen.add(key)

            trivial = ""
            # Mark trivially high (price level autocorrelation)
            if fname in ("mid", "bid1", "ask1", "bid2", "ask2", "microprice", "mp_l2",
                         "cum_dmid", "ema_dev_5", "ema_dev_10", "ema_dev_20") and \
               tname in ("mid", "bid1", "ask1", "bid2", "ask2", "microprice", "mp_l2"):
                trivial = " (price→price, trivial)"

            marker = " <<<" if abs_r >= 0.98 else ""
            print(f"  {fname:<25s} → {tname:<25s} {lag:>4d} {r:>+9.5f} {abs_r:>8.5f}{trivial}{marker}")
            shown += 1
            if shown >= 50:
                break

        # ── SPECIFICALLY look for volume-based predictors of future price ──
        print(f"\n  VOLUME → FUTURE PRICE (non-trivial, |r| > 0.5):")
        print(f"  {'Feature(t)':<25s} → {'Target(t+k)':<25s} {'lag':>4s} {'r':>9s}")
        print(f"  {'-'*25}   {'-'*25} {'-'*4} {'-'*9}")

        vol_features = ["bv1", "av1", "bv2", "av2", "bv3", "av3",
                        "total_bv", "total_av", "obi_l1", "obi_l2", "obi_total",
                        "dw_obi", "gap_asym", "l2l1_bid", "l2l1_ask",
                        "log_bv1", "log_av1", "log_bv2", "log_av2",
                        "log_total_bv", "log_total_av",
                        "log_bv1-av1", "log_bv2-av2", "log_total_diff",
                        "mp_dev", "mp_l2_dev", "vol_sum_l1", "vol_sum_total",
                        "l3l1_bid", "l3l1_ask"]
        price_targets = ["mid", "dmid", "bid1", "ask1", "spread", "microprice", "mp_dev"]

        vol_price = [(abs_r, r, lag, fname, tname, cnt) for abs_r, r, lag, fname, tname, cnt in all_results
                     if fname in vol_features and tname in price_targets and abs_r > 0.5]
        vol_price.sort(reverse=True)
        for abs_r, r, lag, fname, tname, cnt in vol_price[:30]:
            print(f"  {fname:<25s} → {tname:<25s} {lag:>4d} {r:>+9.5f}")

        # ── VOLUME → FUTURE VOLUME ──
        print(f"\n  VOLUME → FUTURE VOLUME (|r| > 0.85):")
        print(f"  {'Feature(t)':<25s} → {'Target(t+k)':<25s} {'lag':>4s} {'r':>9s}")
        print(f"  {'-'*25}   {'-'*25} {'-'*4} {'-'*9}")

        vol_vol = [(abs_r, r, lag, fname, tname, cnt) for abs_r, r, lag, fname, tname, cnt in all_results
                   if fname in vol_features and tname in ["bv1", "av1", "bv2", "av2",
                   "total_bv", "total_av", "obi_l1", "obi_total", "vol_sum_l1",
                   "log_bv1", "log_av1", "log_total_bv", "log_total_av"]
                   and abs_r > 0.85 and fname != tname]
        vol_vol.sort(reverse=True)
        seen2 = set()
        for abs_r, r, lag, fname, tname, cnt in vol_vol[:30]:
            key = f"{fname}→{tname}"
            if key in seen2:
                continue
            seen2.add(key)
            marker = " <<<" if abs_r >= 0.98 else ""
            print(f"  {fname:<25s} → {tname:<25s} {lag:>4d} {r:>+9.5f}{marker}")


if __name__ == "__main__":
    main()
