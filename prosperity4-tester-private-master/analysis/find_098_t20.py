#!/usr/bin/env python3
"""
find_098_t20.py — EXHAUSTIVE search for 0.98+ correlations at t+20 horizon (TOMATOES)
=====================================================================================

Key insight: raw dmid(t) vs dmid(t+20) is ~0, but CUMULATIVE/INTEGRATED series
can trivially have 0.98+ correlations because integrated random walks are near-I(1).

This script tests:
  1. Cumulative features at t vs cumulative targets at t+20
  2. Rolling/smoothed features (EMA, rolling mean) vs future values
  3. Integrated/cumulative cross-feature correlations
  4. Price levels with offsets (known high, but which derived ones?)
  5. Cross-level correlations (L2 at t vs L1 at t+20)
  6. Ratio/normalized cumulative quantities
  7. Every combination with classification: TRIVIAL / INTERESTING / ACTIONABLE
"""

import csv
import os
import math
import sys

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prosperity4bt", "resources", "round0")

LAG = 20  # t+20 horizon


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
    """Pearson correlation between two equal-length lists."""
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


def cumsum(series):
    out = []
    s = 0.0
    for x in series:
        s += x
        out.append(s)
    return out


def ema(series, alpha):
    if not series:
        return []
    out = [series[0]]
    for i in range(1, len(series)):
        out.append(out[-1] + alpha * (series[i] - out[-1]))
    return out


def rolling_mean(series, window):
    out = []
    for i in range(len(series)):
        start = max(0, i - window + 1)
        out.append(sum(series[start:i+1]) / (i - start + 1))
    return out


def rolling_sum(series, window):
    out = []
    for i in range(len(series)):
        start = max(0, i - window + 1)
        out.append(sum(series[start:i+1]))
    return out


def classify_pair(fname, tname):
    """Classify a correlation pair as TRIVIAL, INTERESTING, or ACTIONABLE."""
    # TRIVIAL: price level -> price level (integrated series autocorrelation)
    price_level_features = {
        "mid", "bid1", "ask1", "bid2", "ask2", "bid3", "ask3",
        "microprice", "mp_l2", "vwap",
        "ema_mid_001", "ema_mid_002", "ema_mid_005", "ema_mid_01", "ema_mid_02",
        "rm_mid_5", "rm_mid_10", "rm_mid_20", "rm_mid_50", "rm_mid_100",
    }
    price_level_targets = {
        "mid", "bid1", "ask1", "bid2", "ask2",
        "microprice", "mp_l2",
    }

    # Cumulative of X at t vs cumulative of X at t+20 (same thing, integrated)
    if fname.startswith("cum_") and tname.startswith("cum_"):
        base_f = fname[4:]
        base_t = tname[4:]
        if base_f == base_t:
            return "TRIVIAL"

    # Price level to price level
    if fname in price_level_features and tname in price_level_targets:
        return "TRIVIAL"

    # EMA/rolling of mid -> future mid (smoothed version of price -> price)
    if ("ema_mid" in fname or "rm_mid" in fname) and tname in price_level_targets:
        return "TRIVIAL"

    # cum_dmid is just mid - mid[0], so cum_dmid -> mid is trivial
    if fname == "cum_dmid" and tname in price_level_targets:
        return "TRIVIAL"
    if tname == "cum_dmid" and fname in price_level_features:
        return "TRIVIAL"

    # ACTIONABLE: a feature at t predicts price CHANGE from t to t+20
    change_targets = {
        "fwd_return_20", "dmid", "fwd_mid_change",
    }
    if tname in change_targets:
        return "ACTIONABLE"

    # ACTIONABLE: volume/imbalance cumulative predicts future price level
    vol_cumulative = {f for f in ["cum_obi_l1", "cum_obi_l2", "cum_obi_total",
                                   "cum_dw_obi", "cum_vol_imb", "cum_bv_minus_av",
                                   "cum_mp_dev", "cum_gap_asym", "cum_signed_vol_change"]}
    if fname in vol_cumulative and tname in price_level_targets:
        return "INTERESTING"
    if fname in vol_cumulative and tname == "cum_dmid":
        return "INTERESTING"

    # Volume features predicting future price
    vol_features = {
        "obi_l1", "obi_l2", "obi_total", "dw_obi", "gap_asym",
        "mp_dev", "mp_l2_dev", "bv1", "av1", "bv2", "av2",
        "total_bv", "total_av", "vol_imb_raw",
    }
    if fname in vol_features and tname in price_level_targets:
        return "INTERESTING"

    # Cross-level (L2 price at t -> L1 price at t+20)
    if ("2" in fname and "1" in tname) or ("1" in fname and "2" in tname):
        if any(p in fname for p in ["bid", "ask"]) and any(p in tname for p in ["bid", "ask", "mid"]):
            return "INTERESTING"

    # Default
    return "INTERESTING"


def main():
    all_day_results = {}

    for day in [-2, -1, 0]:
        print(f"\n{'='*100}")
        print(f"  DAY {day} -- TOMATOES -- EXHAUSTIVE t+{LAG} CORRELATION SEARCH")
        print(f"{'='*100}")

        rows = load_tomatoes(day)
        n = len(rows)
        print(f"  Ticks: {n}")

        # ====================================================================
        # RAW SERIES
        # ====================================================================
        mid = [r["mid"] for r in rows]
        bid1 = [r["bid1"] or 0 for r in rows]
        ask1 = [r["ask1"] or 0 for r in rows]
        bid2 = [r["bid2"] or 0 for r in rows]
        ask2 = [r["ask2"] or 0 for r in rows]
        bid3 = [r["bid3"] or 0 for r in rows]
        ask3 = [r["ask3"] or 0 for r in rows]
        bv1 = [r["bv1"] for r in rows]
        av1 = [r["av1"] for r in rows]
        bv2 = [r["bv2"] for r in rows]
        av2 = [r["av2"] for r in rows]
        bv3 = [r["bv3"] for r in rows]
        av3 = [r["av3"] for r in rows]
        spread = [a - b for a, b in zip(ask1, bid1)]

        # ====================================================================
        # DERIVED RAW FEATURES
        # ====================================================================
        dmid = [0.0] + [mid[i] - mid[i-1] for i in range(1, n)]

        total_bv = [bv1[i] + bv2[i] + bv3[i] for i in range(n)]
        total_av = [av1[i] + av2[i] + av3[i] for i in range(n)]

        obi_l1 = [(bv1[i] - av1[i]) / max(1, bv1[i] + av1[i]) for i in range(n)]
        obi_l2 = [(bv2[i] - av2[i]) / max(1, bv2[i] + av2[i]) for i in range(n)]
        obi_total = [(total_bv[i] - total_av[i]) / max(1, total_bv[i] + total_av[i]) for i in range(n)]

        vol_imb_raw = [bv1[i] - av1[i] for i in range(n)]
        bv_minus_av = [total_bv[i] - total_av[i] for i in range(n)]

        # Microprice
        mp = [bid1[i] + bv1[i] / max(1, bv1[i] + av1[i]) * (ask1[i] - bid1[i]) for i in range(n)]
        mp_dev = [mp[i] - mid[i] for i in range(n)]

        # L2 microprice
        mp_l2 = [bid2[i] + bv2[i] / max(1, bv2[i] + av2[i]) * (ask2[i] - bid2[i])
                  if bid2[i] and ask2[i] else mid[i] for i in range(n)]
        mp_l2_dev = [mp_l2[i] - mid[i] for i in range(n)]

        # Gap asymmetry
        gap_asym = [(bid1[i] - bid2[i]) - (ask2[i] - ask1[i])
                     if bid2[i] and ask2[i] else 0 for i in range(n)]

        # Dist-weighted OBI
        dw_obi = []
        for i in range(n):
            m = mid[i]
            num = 0.0
            den = 0.0
            for bp, bvol in [(bid1[i], bv1[i]), (bid2[i], bv2[i]), (bid3[i], bv3[i])]:
                if bp and bp > 0 and bvol > 0:
                    d = max(1, m - bp)
                    num += bvol / d
                    den += bvol / d
            for ap, avol in [(ask1[i], av1[i]), (ask2[i], av2[i]), (ask3[i], av3[i])]:
                if ap and ap > 0 and avol > 0:
                    d = max(1, ap - m)
                    num -= avol / d
                    den += avol / d
            dw_obi.append(num / den if den > 0 else 0)

        # VWAP
        vwap = []
        for i in range(n):
            num = 0.0
            den = 0.0
            for bp, bvol in [(bid1[i], bv1[i]), (bid2[i], bv2[i]), (bid3[i], bv3[i])]:
                if bp and bp > 0 and bvol > 0:
                    num += bp * bvol
                    den += bvol
            for ap, avol in [(ask1[i], av1[i]), (ask2[i], av2[i]), (ask3[i], av3[i])]:
                if ap and ap > 0 and avol > 0:
                    num += ap * avol
                    den += avol
            vwap.append(num / den if den > 0 else mid[i])

        # Signed volume change proxy (change in total bid vol - change in total ask vol)
        signed_vol_change = [0.0] + [(total_bv[i] - total_bv[i-1]) - (total_av[i] - total_av[i-1])
                                      for i in range(1, n)]

        # L2/L1 ratios
        l2l1_bid = [bv2[i] / max(1, bv1[i]) for i in range(n)]
        l2l1_ask = [av2[i] / max(1, av1[i]) for i in range(n)]

        # ====================================================================
        # CUMULATIVE SERIES (INTEGRATED -- these WILL have high autocorrelation)
        # ====================================================================
        cum_dmid = cumsum(dmid)                    # = mid - mid[0] (trivially = mid shifted)
        cum_obi_l1 = cumsum(obi_l1)
        cum_obi_l2 = cumsum(obi_l2)
        cum_obi_total = cumsum(obi_total)
        cum_dw_obi = cumsum(dw_obi)
        cum_vol_imb = cumsum(vol_imb_raw)
        cum_bv_minus_av = cumsum(bv_minus_av)
        cum_mp_dev = cumsum(mp_dev)
        cum_gap_asym = cumsum(gap_asym)
        cum_signed_vol_change = cumsum(signed_vol_change)

        # ====================================================================
        # EMA SERIES (smoothed -- will track price closely)
        # ====================================================================
        ema_mid_001 = ema(mid, 0.01)
        ema_mid_002 = ema(mid, 0.02)
        ema_mid_005 = ema(mid, 0.05)
        ema_mid_01 = ema(mid, 0.1)
        ema_mid_02 = ema(mid, 0.2)

        ema_obi_005 = ema(obi_l1, 0.05)
        ema_obi_01 = ema(obi_l1, 0.1)
        ema_obi_total_005 = ema(obi_total, 0.05)
        ema_mp_dev_005 = ema(mp_dev, 0.05)
        ema_mp_dev_01 = ema(mp_dev, 0.1)
        ema_dw_obi_005 = ema(dw_obi, 0.05)
        ema_gap_asym_005 = ema(gap_asym, 0.05)
        ema_vol_imb_005 = ema(vol_imb_raw, 0.05)
        ema_bv1_005 = ema(bv1, 0.05)
        ema_av1_005 = ema(av1, 0.05)
        ema_signed_vol_005 = ema(signed_vol_change, 0.05)

        # ====================================================================
        # ROLLING MEAN SERIES
        # ====================================================================
        rm_mid_5 = rolling_mean(mid, 5)
        rm_mid_10 = rolling_mean(mid, 10)
        rm_mid_20 = rolling_mean(mid, 20)
        rm_mid_50 = rolling_mean(mid, 50)
        rm_mid_100 = rolling_mean(mid, 100)

        rm_dmid_5 = rolling_mean(dmid, 5)
        rm_dmid_10 = rolling_mean(dmid, 10)
        rm_dmid_20 = rolling_mean(dmid, 20)

        rm_obi_5 = rolling_mean(obi_l1, 5)
        rm_obi_10 = rolling_mean(obi_l1, 10)
        rm_obi_20 = rolling_mean(obi_l1, 20)

        rm_mp_dev_5 = rolling_mean(mp_dev, 5)
        rm_mp_dev_10 = rolling_mean(mp_dev, 10)
        rm_mp_dev_20 = rolling_mean(mp_dev, 20)

        rm_dw_obi_5 = rolling_mean(dw_obi, 5)
        rm_dw_obi_10 = rolling_mean(dw_obi, 10)
        rm_dw_obi_20 = rolling_mean(dw_obi, 20)

        # Rolling sum of dmid over past 20 ticks
        rsum_dmid_20 = rolling_sum(dmid, 20)

        # ====================================================================
        # FORWARD RETURN TARGET (the key actionable target)
        # ====================================================================
        fwd_return_20 = [mid[i + LAG] - mid[i] if i + LAG < n else 0.0 for i in range(n)]
        fwd_mid = [mid[i + LAG] if i + LAG < n else mid[-1] for i in range(n)]

        # ====================================================================
        # BUILD FEATURE AND TARGET DICTIONARIES
        # ====================================================================
        features = {}
        targets = {}

        # --- RAW PRICE LEVELS ---
        features["mid"] = mid
        features["bid1"] = bid1
        features["ask1"] = ask1
        features["bid2"] = bid2
        features["ask2"] = ask2
        features["bid3"] = bid3
        features["ask3"] = ask3
        features["microprice"] = mp
        features["mp_l2"] = mp_l2
        features["vwap"] = vwap
        features["spread"] = spread

        # --- RAW CHANGES ---
        features["dmid"] = dmid
        features["mp_dev"] = mp_dev
        features["mp_l2_dev"] = mp_l2_dev
        features["gap_asym"] = gap_asym

        # --- VOLUME RAW ---
        features["bv1"] = bv1
        features["av1"] = av1
        features["bv2"] = bv2
        features["av2"] = av2
        features["total_bv"] = total_bv
        features["total_av"] = total_av
        features["vol_imb_raw"] = vol_imb_raw
        features["bv_minus_av"] = bv_minus_av

        # --- IMBALANCES ---
        features["obi_l1"] = obi_l1
        features["obi_l2"] = obi_l2
        features["obi_total"] = obi_total
        features["dw_obi"] = dw_obi

        # --- VOLUME RATIOS ---
        features["l2l1_bid"] = l2l1_bid
        features["l2l1_ask"] = l2l1_ask

        # --- SIGNED VOL CHANGE ---
        features["signed_vol_change"] = signed_vol_change

        # --- CUMULATIVE SERIES ---
        features["cum_dmid"] = cum_dmid
        features["cum_obi_l1"] = cum_obi_l1
        features["cum_obi_l2"] = cum_obi_l2
        features["cum_obi_total"] = cum_obi_total
        features["cum_dw_obi"] = cum_dw_obi
        features["cum_vol_imb"] = cum_vol_imb
        features["cum_bv_minus_av"] = cum_bv_minus_av
        features["cum_mp_dev"] = cum_mp_dev
        features["cum_gap_asym"] = cum_gap_asym
        features["cum_signed_vol_change"] = cum_signed_vol_change

        # --- EMA OF MID ---
        features["ema_mid_001"] = ema_mid_001
        features["ema_mid_002"] = ema_mid_002
        features["ema_mid_005"] = ema_mid_005
        features["ema_mid_01"] = ema_mid_01
        features["ema_mid_02"] = ema_mid_02

        # --- EMA OF FEATURES ---
        features["ema_obi_005"] = ema_obi_005
        features["ema_obi_01"] = ema_obi_01
        features["ema_obi_total_005"] = ema_obi_total_005
        features["ema_mp_dev_005"] = ema_mp_dev_005
        features["ema_mp_dev_01"] = ema_mp_dev_01
        features["ema_dw_obi_005"] = ema_dw_obi_005
        features["ema_gap_asym_005"] = ema_gap_asym_005
        features["ema_vol_imb_005"] = ema_vol_imb_005
        features["ema_bv1_005"] = ema_bv1_005
        features["ema_av1_005"] = ema_av1_005
        features["ema_signed_vol_005"] = ema_signed_vol_005

        # --- ROLLING MEANS OF MID ---
        features["rm_mid_5"] = rm_mid_5
        features["rm_mid_10"] = rm_mid_10
        features["rm_mid_20"] = rm_mid_20
        features["rm_mid_50"] = rm_mid_50
        features["rm_mid_100"] = rm_mid_100

        # --- ROLLING MEANS OF FEATURES ---
        features["rm_dmid_5"] = rm_dmid_5
        features["rm_dmid_10"] = rm_dmid_10
        features["rm_dmid_20"] = rm_dmid_20
        features["rm_obi_5"] = rm_obi_5
        features["rm_obi_10"] = rm_obi_10
        features["rm_obi_20"] = rm_obi_20
        features["rm_mp_dev_5"] = rm_mp_dev_5
        features["rm_mp_dev_10"] = rm_mp_dev_10
        features["rm_mp_dev_20"] = rm_mp_dev_20
        features["rm_dw_obi_5"] = rm_dw_obi_5
        features["rm_dw_obi_10"] = rm_dw_obi_10
        features["rm_dw_obi_20"] = rm_dw_obi_20

        # --- ROLLING SUM ---
        features["rsum_dmid_20"] = rsum_dmid_20

        # --- NORMALIZED CUMULATIVE ---
        # cumsum(x) / sqrt(t) -- removes drift from growing variance
        cum_obi_normed = [cum_obi_l1[i] / math.sqrt(max(1, i)) for i in range(n)]
        cum_dmid_normed = [cum_dmid[i] / math.sqrt(max(1, i)) for i in range(n)]
        cum_dw_obi_normed = [cum_dw_obi[i] / math.sqrt(max(1, i)) for i in range(n)]
        cum_vol_imb_normed = [cum_vol_imb[i] / math.sqrt(max(1, i)) for i in range(n)]
        features["cum_obi_normed"] = cum_obi_normed
        features["cum_dmid_normed"] = cum_dmid_normed
        features["cum_dw_obi_normed"] = cum_dw_obi_normed
        features["cum_vol_imb_normed"] = cum_vol_imb_normed

        # ====================================================================
        # TARGETS at t+20
        # ====================================================================
        targets["mid"] = mid
        targets["bid1"] = bid1
        targets["ask1"] = ask1
        targets["bid2"] = bid2
        targets["ask2"] = ask2
        targets["microprice"] = mp
        targets["mp_l2"] = mp_l2
        targets["spread"] = spread
        targets["obi_l1"] = obi_l1
        targets["obi_total"] = obi_total
        targets["bv1"] = bv1
        targets["av1"] = av1
        targets["total_bv"] = total_bv
        targets["total_av"] = total_av
        targets["dmid"] = dmid
        targets["cum_dmid"] = cum_dmid
        targets["cum_obi_l1"] = cum_obi_l1
        targets["cum_obi_total"] = cum_obi_total
        targets["cum_dw_obi"] = cum_dw_obi
        targets["cum_vol_imb"] = cum_vol_imb
        targets["cum_bv_minus_av"] = cum_bv_minus_av
        targets["cum_mp_dev"] = cum_mp_dev
        targets["cum_gap_asym"] = cum_gap_asym
        targets["cum_signed_vol_change"] = cum_signed_vol_change
        targets["fwd_return_20"] = fwd_return_20  # mid(t+20) - mid(t), ALREADY shifted
        targets["cum_dmid_normed"] = cum_dmid_normed
        targets["cum_obi_normed"] = cum_obi_normed

        # ====================================================================
        # TEST ALL PAIRS at lag=20
        # ====================================================================
        print(f"\n  Testing {len(features)} features x {len(targets)} targets at lag={LAG}...")

        all_results = []
        tested = 0

        for fname, fvals in features.items():
            for tname, tvals in targets.items():
                # For fwd_return_20, it's already shifted -- use directly aligned
                if tname == "fwd_return_20":
                    # fwd_return_20[i] = mid[i+20] - mid[i], computed for i in range(n-LAG)
                    x = fvals[:n - LAG]
                    y = tvals[:n - LAG]
                else:
                    # Feature at t, target at t+LAG
                    x = fvals[:n - LAG]
                    y = tvals[LAG:]

                if len(x) < 50 or len(y) < 50:
                    continue

                mn = min(len(x), len(y))
                x = x[:mn]
                y = y[:mn]

                r = corr(x, y)
                tested += 1

                classification = classify_pair(fname, tname)
                all_results.append((abs(r), r, fname, tname, classification, mn))

        all_results.sort(reverse=True)

        print(f"  Tested {tested} pairs total")

        # ====================================================================
        # PRINT ALL WITH |r| >= 0.90
        # ====================================================================
        print(f"\n  ALL PAIRS with |r| >= 0.90 at t+{LAG}:")
        print(f"  {'Class':<12s} {'Feature(t)':<30s} {'Target(t+20)':<30s} {'r':>9s} {'|r|':>8s} {'n':>6s}")
        print(f"  {'-'*12} {'-'*30} {'-'*30} {'-'*9} {'-'*8} {'-'*6}")

        count_090 = 0
        for abs_r, r, fname, tname, cls, cnt in all_results:
            if abs_r < 0.90:
                break
            marker = " <<<" if abs_r >= 0.98 else (" **" if abs_r >= 0.95 else "")
            print(f"  {cls:<12s} {fname:<30s} {tname:<30s} {r:>+9.5f} {abs_r:>8.5f} {cnt:>6d}{marker}")
            count_090 += 1

        print(f"\n  Total pairs with |r| >= 0.90: {count_090}")

        # ====================================================================
        # SECTION 2: SPECIFICALLY cumsum(feature) vs mid(t+20) for all features
        # ====================================================================
        print(f"\n  --- SECTION 2: corr(cumsum(f)[t], mid[t+{LAG}]) for every base feature ---")
        print(f"  {'cumsum(feature)':<35s} {'r':>9s} {'|r|':>8s} {'class':>12s}")
        print(f"  {'-'*35} {'-'*9} {'-'*8} {'-'*12}")

        base_features_for_cumsum = {
            "dmid": dmid, "obi_l1": obi_l1, "obi_l2": obi_l2,
            "obi_total": obi_total, "dw_obi": dw_obi, "gap_asym": gap_asym,
            "mp_dev": mp_dev, "mp_l2_dev": mp_l2_dev,
            "vol_imb_raw": vol_imb_raw, "bv_minus_av": bv_minus_av,
            "signed_vol_change": signed_vol_change,
            "spread": spread,
            "l2l1_bid": l2l1_bid, "l2l1_ask": l2l1_ask,
        }

        cum_vs_mid = []
        for bname, bvals in base_features_for_cumsum.items():
            cs = cumsum(bvals)
            x = cs[:n - LAG]
            y = mid[LAG:]
            mn = min(len(x), len(y))
            r = corr(x[:mn], y[:mn])
            cls = "TRIVIAL" if bname == "dmid" else "INTERESTING"
            cum_vs_mid.append((abs(r), r, f"cumsum({bname})", cls))

        cum_vs_mid.sort(reverse=True)
        for abs_r, r, name, cls in cum_vs_mid:
            marker = " <<<" if abs_r >= 0.98 else (" **" if abs_r >= 0.95 else "")
            print(f"  {name:<35s} {r:>+9.5f} {abs_r:>8.5f} {cls:>12s}{marker}")

        # ====================================================================
        # SECTION 3: EMA(feature, 0.05)[t] vs mid(t+20) for all features
        # ====================================================================
        print(f"\n  --- SECTION 3: corr(EMA(f, 0.05)[t], mid[t+{LAG}]) for every base feature ---")
        print(f"  {'EMA(feature,0.05)':<35s} {'r':>9s} {'|r|':>8s} {'class':>12s}")
        print(f"  {'-'*35} {'-'*9} {'-'*8} {'-'*12}")

        ema_vs_mid = []
        all_base = {
            "mid": mid, "bid1": bid1, "ask1": ask1, "bid2": bid2, "ask2": ask2,
            "microprice": mp, "mp_l2": mp_l2, "vwap": vwap,
            "dmid": dmid, "obi_l1": obi_l1, "obi_l2": obi_l2,
            "obi_total": obi_total, "dw_obi": dw_obi, "gap_asym": gap_asym,
            "mp_dev": mp_dev, "mp_l2_dev": mp_l2_dev,
            "vol_imb_raw": vol_imb_raw, "bv_minus_av": bv_minus_av,
            "spread": spread, "signed_vol_change": signed_vol_change,
            "bv1": bv1, "av1": av1, "bv2": bv2, "av2": av2,
            "total_bv": total_bv, "total_av": total_av,
        }

        for bname, bvals in all_base.items():
            e = ema(bvals, 0.05)
            x = e[:n - LAG]
            y = mid[LAG:]
            mn = min(len(x), len(y))
            r = corr(x[:mn], y[:mn])
            cls = "TRIVIAL" if bname in ("mid", "bid1", "ask1", "bid2", "ask2",
                                          "microprice", "mp_l2", "vwap") else "INTERESTING"
            ema_vs_mid.append((abs(r), r, f"EMA({bname},0.05)", cls))

        ema_vs_mid.sort(reverse=True)
        for abs_r, r, name, cls in ema_vs_mid:
            marker = " <<<" if abs_r >= 0.98 else (" **" if abs_r >= 0.95 else "")
            print(f"  {name:<35s} {r:>+9.5f} {abs_r:>8.5f} {cls:>12s}{marker}")

        # ====================================================================
        # SECTION 4: cumsum(vol_feature) vs cumsum(dmid) at t+20
        # ====================================================================
        print(f"\n  --- SECTION 4: corr(cumsum(vol_feature)[t], cumsum(dmid)[t+{LAG}]) ---")
        print(f"  {'cumsum(vol_feature)':<35s} {'r':>9s} {'|r|':>8s}")
        print(f"  {'-'*35} {'-'*9} {'-'*8}")

        vol_features_for_cum = {
            "obi_l1": obi_l1, "obi_l2": obi_l2, "obi_total": obi_total,
            "dw_obi": dw_obi, "gap_asym": gap_asym,
            "mp_dev": mp_dev, "mp_l2_dev": mp_l2_dev,
            "vol_imb_raw": vol_imb_raw, "bv_minus_av": bv_minus_av,
            "signed_vol_change": signed_vol_change,
            "l2l1_bid": l2l1_bid, "l2l1_ask": l2l1_ask,
            "spread": spread,
        }

        cum_vol_vs_cum_dmid = []
        for bname, bvals in vol_features_for_cum.items():
            cs = cumsum(bvals)
            x = cs[:n - LAG]
            y = cum_dmid[LAG:]
            mn = min(len(x), len(y))
            r = corr(x[:mn], y[:mn])
            cum_vol_vs_cum_dmid.append((abs(r), r, f"cumsum({bname})"))

        cum_vol_vs_cum_dmid.sort(reverse=True)
        for abs_r, r, name in cum_vol_vs_cum_dmid:
            marker = " <<<" if abs_r >= 0.98 else (" **" if abs_r >= 0.95 else "")
            print(f"  {name:<35s} {r:>+9.5f} {abs_r:>8.5f}{marker}")

        # ====================================================================
        # SECTION 5: Cross-level correlations
        # ====================================================================
        print(f"\n  --- SECTION 5: Cross-level price correlations at t+{LAG} ---")
        print(f"  {'Feature(t)':<25s} {'Target(t+20)':<25s} {'r':>9s} {'|r|':>8s}")
        print(f"  {'-'*25} {'-'*25} {'-'*9} {'-'*8}")

        cross_level_pairs = [
            ("bid2", bid2, "bid1", bid1),
            ("ask2", ask2, "ask1", ask1),
            ("bid3", bid3, "bid1", bid1),
            ("ask3", ask3, "ask1", ask1),
            ("bid2", bid2, "mid", mid),
            ("ask2", ask2, "mid", mid),
            ("mp_l2", mp_l2, "mid", mid),
            ("mp_l2", mp_l2, "microprice", mp),
            ("bid1", bid1, "bid2", bid2),
            ("ask1", ask1, "ask2", ask2),
            ("mid", mid, "mp_l2", mp_l2),
            ("vwap", vwap, "mid", mid),
            ("vwap", vwap, "microprice", mp),
        ]

        for fname, fvals, tname, tvals in cross_level_pairs:
            x = fvals[:n - LAG]
            y = tvals[LAG:]
            mn = min(len(x), len(y))
            r = corr(x[:mn], y[:mn])
            marker = " <<<" if abs(r) >= 0.98 else ""
            print(f"  {fname:<25s} {tname:<25s} {r:>+9.5f} {abs(r):>8.5f}{marker}")

        # ====================================================================
        # SECTION 6: Running correlation between OBI and dmid (past 20 ticks)
        # ====================================================================
        print(f"\n  --- SECTION 6: Running correlation (window=20) between features ---")

        # rolling correlation obi vs dmid
        running_corr_obi_dmid = []
        for i in range(n):
            start = max(0, i - 19)
            if i - start < 5:
                running_corr_obi_dmid.append(0.0)
                continue
            x_win = obi_l1[start:i+1]
            y_win = dmid[start:i+1]
            running_corr_obi_dmid.append(corr(x_win, y_win))

        x = running_corr_obi_dmid[:n - LAG]
        y_fwd = fwd_return_20[:n - LAG]
        y_mid = mid[LAG:]
        mn = min(len(x), len(y_fwd), len(y_mid))
        r1 = corr(x[:mn], y_fwd[:mn])
        r2 = corr(x[:mn], y_mid[:mn])
        print(f"  running_corr(obi, dmid, 20)[t] vs fwd_return_20: r = {r1:+.5f}")
        print(f"  running_corr(obi, dmid, 20)[t] vs mid(t+20):     r = {r2:+.5f}")

        # running correlation mp_dev vs dmid
        running_corr_mpdev_dmid = []
        for i in range(n):
            start = max(0, i - 19)
            if i - start < 5:
                running_corr_mpdev_dmid.append(0.0)
                continue
            x_win = mp_dev[start:i+1]
            y_win = dmid[start:i+1]
            running_corr_mpdev_dmid.append(corr(x_win, y_win))

        x = running_corr_mpdev_dmid[:n - LAG]
        r1 = corr(x[:mn], y_fwd[:mn])
        r2 = corr(x[:mn], y_mid[:mn])
        print(f"  running_corr(mp_dev, dmid, 20)[t] vs fwd_return_20: r = {r1:+.5f}")
        print(f"  running_corr(mp_dev, dmid, 20)[t] vs mid(t+20):     r = {r2:+.5f}")

        # ====================================================================
        # SECTION 7: Additional creative features
        # ====================================================================
        print(f"\n  --- SECTION 7: Creative / non-obvious features vs mid(t+{LAG}) ---")
        print(f"  {'Feature(t)':<40s} {'r vs mid(t+20)':>15s} {'r vs fwd_ret':>15s} {'class':>12s}")
        print(f"  {'-'*40} {'-'*15} {'-'*15} {'-'*12}")

        creative_features = {}

        # Pressure: bid vol / (bid vol + ask vol) at each level
        pressure_l1 = [bv1[i] / max(1, bv1[i] + av1[i]) for i in range(n)]
        pressure_l2 = [bv2[i] / max(1, bv2[i] + av2[i]) for i in range(n)]
        pressure_total = [total_bv[i] / max(1, total_bv[i] + total_av[i]) for i in range(n)]
        creative_features["pressure_l1"] = pressure_l1
        creative_features["pressure_l2"] = pressure_l2
        creative_features["pressure_total"] = pressure_total
        creative_features["cum_pressure_l1"] = cumsum([p - 0.5 for p in pressure_l1])
        creative_features["cum_pressure_total"] = cumsum([p - 0.5 for p in pressure_total])

        # Spread-adjusted microprice deviation
        spread_adj_mp = [mp_dev[i] / max(1, spread[i]) for i in range(n)]
        creative_features["spread_adj_mp_dev"] = spread_adj_mp
        creative_features["cum_spread_adj_mp"] = cumsum(spread_adj_mp)

        # Log-volume weighted mid
        log_vol_mid = []
        for i in range(n):
            lb = safe_log(bv1[i])
            la = safe_log(av1[i])
            denom = lb + la
            if denom > 0:
                log_vol_mid.append(bid1[i] + lb / denom * (ask1[i] - bid1[i]))
            else:
                log_vol_mid.append(mid[i])
        creative_features["log_vol_mid"] = log_vol_mid

        # Rate of change of OBI
        d_obi = [0.0] + [obi_l1[i] - obi_l1[i-1] for i in range(1, n)]
        creative_features["d_obi"] = d_obi
        creative_features["cum_d_obi"] = cumsum(d_obi)

        # Momentum of mid over various windows
        mom_5 = [mid[i] - mid[max(0, i-5)] for i in range(n)]
        mom_10 = [mid[i] - mid[max(0, i-10)] for i in range(n)]
        mom_20 = [mid[i] - mid[max(0, i-20)] for i in range(n)]
        creative_features["momentum_5"] = mom_5
        creative_features["momentum_10"] = mom_10
        creative_features["momentum_20"] = mom_20
        creative_features["cum_momentum_5"] = cumsum(mom_5)
        creative_features["cum_momentum_10"] = cumsum(mom_10)

        # EMA crossover signals
        ema_cross_5_20 = [ema_mid_02[i] - ema_mid_005[i] for i in range(n)]  # fast - slow
        creative_features["ema_cross_5_20"] = ema_cross_5_20
        creative_features["cum_ema_cross"] = cumsum(ema_cross_5_20)

        # Weighted sum of all OBI levels
        weighted_obi = [0.6 * obi_l1[i] + 0.3 * obi_l2[i] +
                        0.1 * ((bv3[i] - av3[i]) / max(1, bv3[i] + av3[i])) for i in range(n)]
        creative_features["weighted_obi_all_levels"] = weighted_obi
        creative_features["cum_weighted_obi"] = cumsum(weighted_obi)

        # Running average of microprice
        rm_mp_10 = rolling_mean(mp, 10)
        rm_mp_20 = rolling_mean(mp, 20)
        creative_features["rm_microprice_10"] = rm_mp_10
        creative_features["rm_microprice_20"] = rm_mp_20

        # EMA of microprice
        ema_mp_005 = ema(mp, 0.05)
        ema_mp_01 = ema(mp, 0.1)
        ema_mp_001 = ema(mp, 0.01)
        creative_features["ema_microprice_001"] = ema_mp_001
        creative_features["ema_microprice_005"] = ema_mp_005
        creative_features["ema_microprice_01"] = ema_mp_01

        # Deviation of mid from EMA
        mid_ema_dev_001 = [mid[i] - ema_mid_001[i] for i in range(n)]
        mid_ema_dev_005 = [mid[i] - ema_mid_005[i] for i in range(n)]
        creative_features["mid_minus_ema001"] = mid_ema_dev_001
        creative_features["mid_minus_ema005"] = mid_ema_dev_005

        # Bollinger-style: (mid - rolling_mean) / rolling_std
        boll_z = []
        for i in range(n):
            start = max(0, i - 19)
            window = mid[start:i+1]
            m = sum(window) / len(window)
            std = math.sqrt(sum((x - m) ** 2 for x in window) / len(window)) if len(window) > 1 else 1.0
            boll_z.append((mid[i] - m) / max(0.01, std))
        creative_features["bollinger_z_20"] = boll_z

        # Regression residual: mid - linear_trend over past 20 ticks
        reg_residual = []
        for i in range(n):
            start = max(0, i - 19)
            window = mid[start:i+1]
            wn = len(window)
            if wn < 3:
                reg_residual.append(0.0)
                continue
            x_mean = (wn - 1) / 2.0
            y_mean = sum(window) / wn
            num = sum((j - x_mean) * (window[j] - y_mean) for j in range(wn))
            den = sum((j - x_mean) ** 2 for j in range(wn))
            slope = num / max(1e-10, den)
            intercept = y_mean - slope * x_mean
            predicted = slope * (wn - 1) + intercept
            reg_residual.append(mid[i] - predicted)
        creative_features["reg_residual_20"] = reg_residual

        # Now test all creative features
        creative_results = []
        for cname, cvals in creative_features.items():
            x_f = cvals[:n - LAG]
            y_m = mid[LAG:]
            y_r = fwd_return_20[:n - LAG]
            mn = min(len(x_f), len(y_m), len(y_r))

            r_mid = corr(x_f[:mn], y_m[:mn])
            r_fwd = corr(x_f[:mn], y_r[:mn])

            is_price_like = any(k in cname for k in ["microprice", "log_vol_mid", "rm_microprice", "ema_microprice"])
            cls = "TRIVIAL" if is_price_like and abs(r_mid) > 0.99 else ("ACTIONABLE" if abs(r_fwd) > 0.1 else "INTERESTING")

            creative_results.append((abs(r_mid), r_mid, r_fwd, cname, cls))

        creative_results.sort(reverse=True)
        for abs_r, r_mid, r_fwd, cname, cls in creative_results:
            marker = " <<<" if abs_r >= 0.98 else (" **" if abs_r >= 0.95 else "")
            fwd_marker = " [FWD!]" if abs(r_fwd) > 0.15 else ""
            print(f"  {cname:<40s} {r_mid:>+12.5f} {r_fwd:>+12.5f} {cls:>12s}{marker}{fwd_marker}")

        # ====================================================================
        # SECTION 8: Focus on ACTIONABLE -- what predicts fwd_return_20?
        # ====================================================================
        print(f"\n  --- SECTION 8: ALL features vs fwd_return_20 (mid[t+20]-mid[t]) ---")
        print(f"  {'Feature(t)':<40s} {'r vs fwd_ret_20':>15s} {'|r|':>8s}")
        print(f"  {'-'*40} {'-'*15} {'-'*8}")

        all_fwd_results = []
        combined_features = {**features, **creative_features}
        for fname, fvals in combined_features.items():
            x_f = fvals[:n - LAG]
            y_r = fwd_return_20[:n - LAG]
            mn = min(len(x_f), len(y_r))
            r = corr(x_f[:mn], y_r[:mn])
            all_fwd_results.append((abs(r), r, fname))

        all_fwd_results.sort(reverse=True)
        for abs_r, r, fname in all_fwd_results[:50]:
            marker = " <<<" if abs_r >= 0.20 else ""
            print(f"  {fname:<40s} {r:>+12.5f} {abs_r:>8.5f}{marker}")

        # Store for cross-day comparison
        all_day_results[day] = {
            "all_pairs": all_results,
            "cum_vs_mid": cum_vs_mid,
            "ema_vs_mid": ema_vs_mid,
            "cum_vol_vs_cum_dmid": cum_vol_vs_cum_dmid,
            "fwd_return": all_fwd_results,
            "creative": creative_results,
        }

    # ====================================================================
    # CROSS-DAY SUMMARY
    # ====================================================================
    print(f"\n\n{'='*100}")
    print(f"  CROSS-DAY SUMMARY")
    print(f"{'='*100}")

    # Find pairs that are >= 0.98 on ALL days
    print(f"\n  PAIRS with |r| >= 0.98 on ALL 3 days:")
    print(f"  {'Class':<12s} {'Feature(t)':<30s} {'Target(t+20)':<30s} {'Day-2':>8s} {'Day-1':>8s} {'Day0':>8s}")
    print(f"  {'-'*12} {'-'*30} {'-'*30} {'-'*8} {'-'*8} {'-'*8}")

    # Collect all pair names that hit 0.98 on any day
    pair_scores = {}  # (fname, tname) -> {day: r}
    for day in [-2, -1, 0]:
        for abs_r, r, fname, tname, cls, cnt in all_day_results[day]["all_pairs"]:
            if abs_r >= 0.90:
                key = (fname, tname, cls)
                if key not in pair_scores:
                    pair_scores[key] = {}
                pair_scores[key][day] = r

    for (fname, tname, cls), scores in sorted(pair_scores.items(), key=lambda x: min(abs(v) for v in x[1].values()), reverse=True):
        if all(abs(scores.get(d, 0)) >= 0.98 for d in [-2, -1, 0]):
            r2 = scores.get(-2, 0)
            r1 = scores.get(-1, 0)
            r0 = scores.get(0, 0)
            print(f"  {cls:<12s} {fname:<30s} {tname:<30s} {r2:>+8.5f} {r1:>+8.5f} {r0:>+8.5f}")

    print(f"\n  PAIRS with |r| >= 0.95 on ALL 3 days (not already in 0.98 set):")
    print(f"  {'Class':<12s} {'Feature(t)':<30s} {'Target(t+20)':<30s} {'Day-2':>8s} {'Day-1':>8s} {'Day0':>8s}")
    print(f"  {'-'*12} {'-'*30} {'-'*30} {'-'*8} {'-'*8} {'-'*8}")

    for (fname, tname, cls), scores in sorted(pair_scores.items(), key=lambda x: min(abs(v) for v in x[1].values()), reverse=True):
        if all(abs(scores.get(d, 0)) >= 0.95 for d in [-2, -1, 0]) and not all(abs(scores.get(d, 0)) >= 0.98 for d in [-2, -1, 0]):
            r2 = scores.get(-2, 0)
            r1 = scores.get(-1, 0)
            r0 = scores.get(0, 0)
            print(f"  {cls:<12s} {fname:<30s} {tname:<30s} {r2:>+8.5f} {r1:>+8.5f} {r0:>+8.5f}")

    # Cross-day stability of fwd_return predictions
    print(f"\n  TOP PREDICTORS of fwd_return_20 (stable across days):")
    print(f"  {'Feature(t)':<40s} {'Day-2':>10s} {'Day-1':>10s} {'Day0':>10s} {'Avg|r|':>10s}")
    print(f"  {'-'*40} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    fwd_by_name = {}
    for day in [-2, -1, 0]:
        for abs_r, r, fname in all_day_results[day]["fwd_return"]:
            if fname not in fwd_by_name:
                fwd_by_name[fname] = {}
            fwd_by_name[fname][day] = r

    fwd_ranked = []
    for fname, scores in fwd_by_name.items():
        if len(scores) == 3:
            avg_abs = sum(abs(scores[d]) for d in [-2, -1, 0]) / 3
            fwd_ranked.append((avg_abs, fname, scores))

    fwd_ranked.sort(reverse=True)
    for avg_abs, fname, scores in fwd_ranked[:40]:
        r2, r1, r0 = scores[-2], scores[-1], scores[0]
        marker = " <<<" if avg_abs >= 0.10 else ""
        print(f"  {fname:<40s} {r2:>+10.5f} {r1:>+10.5f} {r0:>+10.5f} {avg_abs:>10.5f}{marker}")

    # ====================================================================
    # FINAL DIAGNOSIS
    # ====================================================================
    print(f"\n\n{'='*100}")
    print(f"  DIAGNOSIS: Where is the 0.98 correlation at t+20?")
    print(f"{'='*100}")
    print(f"""
  The 0.98+ correlations at t+20 come from INTEGRATED (cumulative) series:

  1. cumsum(dmid)[t] vs mid[t+20]  -- This is TRIVIAL because cumsum(dmid) = mid - mid[0]
     So this is literally mid[t] vs mid[t+20], which is ~0.993+ (known price autocorrelation).

  2. cumsum(obi)[t] vs cumsum(dmid)[t+20]  -- This is INTERESTING if the correlation is
     significantly different from what you'd expect from two random walks with similar drift.

  3. EMA(mid, small_alpha)[t] vs mid[t+20] -- TRIVIAL. Slow EMA of price ~ price.

  The KEY QUESTION is whether any NON-PRICE cumulative feature (like cumsum(obi), cumsum(mp_dev),
  cumsum(gap_asym)) correlates with cum_dmid at t+20 at 0.98+. If yes, that feature's cumulative
  integral co-integrates with price, which means deviations are mean-reverting and ACTIONABLE.

  However: high correlation between integrated series is EXPECTED from spurious regression
  (Granger-Newbold, 1974). Two independent random walks will show ~0.85-0.95 spurious correlation
  when integrated. Only > 0.99 would be genuinely surprising.

  For STRATEGY purposes, what matters is:
  - corr(feature[t], mid[t+20] - mid[t]) -- i.e., does the feature predict the CHANGE?
  - This is the ACTIONABLE metric, and is shown in Section 8 above.
""")


if __name__ == "__main__":
    main()
