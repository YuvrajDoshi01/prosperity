"""
log_analysis3.py — Deep dive into L1/L2 price levels, changes, ratios, distributions.

Analyses:
  1. L1/L2 price level distributions (bid1, ask1, bid2, ask2)
  2. L1/L2 volume distributions
  3. log(price) distributions and log-returns
  4. L1 change (dbid1, dask1) distributions and joint distribution
  5. L2 change (dbid2, dask2) distributions and joint distribution
  6. L1 vs L2 change correlation (does L2 move predict L1?)
  7. L2-L1 gap analysis (bid1-bid2, ask2-ask1) — gap distributions + changes
  8. L2/L1 volume ratio distributions + changes
  9. Conditional analysis: L2 change → next L1 change
  10. Asymmetric move analysis: bid moves vs ask moves independently
  11. L2 gap BEFORE narrow spreads vs normal ticks
  12. Joint distribution of all changes: does any combination predict next mid?
"""

import csv
import os
import math
from collections import Counter, defaultdict

DATA_DIR = os.path.join("prosperity4bt", "resources", "round0")

for day in [-2, -1, 0]:
    fname = f"prices_round_0_day_{day}.csv"
    fpath = os.path.join(DATA_DIR, fname)
    if not os.path.exists(fpath):
        continue

    ticks = []
    with open(fpath) as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            if r["product"] != "TOMATOES":
                continue
            bp1 = r["bid_price_1"]
            ap1 = r["ask_price_1"]
            bp2 = r["bid_price_2"]
            ap2 = r["ask_price_2"]
            bv1 = r["bid_volume_1"]
            av1 = r["ask_volume_1"]
            bv2 = r["bid_volume_2"]
            av2 = r["ask_volume_2"]
            bp3 = r.get("bid_price_3", "")
            ap3 = r.get("ask_price_3", "")
            bv3 = r.get("bid_volume_3", "")
            av3 = r.get("ask_volume_3", "")

            if not bp1 or not ap1:
                continue

            t = {
                "bid1": int(bp1), "ask1": int(ap1),
                "bv1": int(bv1) if bv1 else 0, "av1": int(av1) if av1 else 0,
                "bid2": int(bp2) if bp2 else None, "ask2": int(ap2) if ap2 else None,
                "bv2": int(bv2) if bv2 else 0, "av2": int(av2) if av2 else 0,
                "bid3": int(bp3) if bp3 else None, "ask3": int(ap3) if ap3 else None,
                "bv3": int(bv3) if bv3 else 0, "av3": int(av3) if av3 else 0,
            }
            t["mid"] = (t["bid1"] + t["ask1"]) / 2
            t["spread"] = t["ask1"] - t["bid1"]
            if t["bid2"] is not None:
                t["bid_gap"] = t["bid1"] - t["bid2"]  # gap between L1 and L2 bid
            else:
                t["bid_gap"] = None
            if t["ask2"] is not None:
                t["ask_gap"] = t["ask2"] - t["ask1"]  # gap between L1 and L2 ask
            else:
                t["ask_gap"] = None
            ticks.append(t)

    n = len(ticks)
    print(f"\n{'='*70}")
    print(f"DAY {day} — {n} ticks")
    print(f"{'='*70}")

    # ── 1. L1 PRICE LEVEL DISTRIBUTIONS ──
    print(f"\n── 1. L1 Price Level Summary ──")
    bids1 = [t["bid1"] for t in ticks]
    asks1 = [t["ask1"] for t in ticks]
    mids = [t["mid"] for t in ticks]
    print(f"  bid1: min={min(bids1)} max={max(bids1)} mean={sum(bids1)/n:.1f} range={max(bids1)-min(bids1)}")
    print(f"  ask1: min={min(asks1)} max={max(asks1)} mean={sum(asks1)/n:.1f} range={max(asks1)-min(asks1)}")
    print(f"  mid:  min={min(mids):.1f} max={max(mids):.1f} mean={sum(mids)/n:.1f}")

    # ── 2. L2 PRICE LEVEL DISTRIBUTIONS ──
    print(f"\n── 2. L2 Price Level Summary ──")
    bids2 = [t["bid2"] for t in ticks if t["bid2"] is not None]
    asks2 = [t["ask2"] for t in ticks if t["ask2"] is not None]
    print(f"  bid2: n={len(bids2)} min={min(bids2)} max={max(bids2)} mean={sum(bids2)/len(bids2):.1f}")
    print(f"  ask2: n={len(asks2)} min={min(asks2)} max={max(asks2)} mean={sum(asks2)/len(asks2):.1f}")
    no_l2 = sum(1 for t in ticks if t["bid2"] is None or t["ask2"] is None)
    print(f"  ticks missing L2: {no_l2} ({100*no_l2/n:.1f}%)")

    # ── 3. L3 PRESENCE ──
    has_l3_bid = sum(1 for t in ticks if t["bid3"] is not None)
    has_l3_ask = sum(1 for t in ticks if t["ask3"] is not None)
    print(f"\n── 3. L3 Presence ──")
    print(f"  bid3 present: {has_l3_bid} ({100*has_l3_bid/n:.1f}%)")
    print(f"  ask3 present: {has_l3_ask} ({100*has_l3_ask/n:.1f}%)")

    # ── 4. VOLUME DISTRIBUTIONS ──
    print(f"\n── 4. Volume Distributions ──")
    for label, key in [("bv1", "bv1"), ("av1", "av1"), ("bv2", "bv2"), ("av2", "av2")]:
        vals = [t[key] for t in ticks if t[key] > 0]
        if vals:
            c = Counter(vals)
            top5 = c.most_common(10)
            print(f"  {label}: n={len(vals)} min={min(vals)} max={max(vals)} mean={sum(vals)/len(vals):.2f}")
            print(f"         dist: {sorted(top5)}")

    # ── 5. L1-L2 GAP DISTRIBUTIONS ──
    print(f"\n── 5. L1-L2 Gap (bid1-bid2, ask2-ask1) ──")
    bid_gaps = [t["bid_gap"] for t in ticks if t["bid_gap"] is not None]
    ask_gaps = [t["ask_gap"] for t in ticks if t["ask_gap"] is not None]
    if bid_gaps:
        c_bg = Counter(bid_gaps)
        print(f"  bid_gap: min={min(bid_gaps)} max={max(bid_gaps)} mean={sum(bid_gaps)/len(bid_gaps):.2f}")
        print(f"           dist: {sorted(c_bg.most_common(15))}")
    if ask_gaps:
        c_ag = Counter(ask_gaps)
        print(f"  ask_gap: min={min(ask_gaps)} max={max(ask_gaps)} mean={sum(ask_gaps)/len(ask_gaps):.2f}")
        print(f"           dist: {sorted(c_ag.most_common(15))}")

    # ── 6. SPREAD DISTRIBUTION (detailed) ──
    print(f"\n── 6. Spread Distribution ──")
    spread_counts = Counter(t["spread"] for t in ticks)
    for s in sorted(spread_counts):
        pct = 100 * spread_counts[s] / n
        print(f"  spread={s:>2}: {spread_counts[s]:>5} ({pct:>5.1f}%)")

    # ── 7. L1 CHANGES ──
    print(f"\n── 7. L1 Changes (tick-to-tick) ──")
    dbid1 = [ticks[i]["bid1"] - ticks[i-1]["bid1"] for i in range(1, n)]
    dask1 = [ticks[i]["ask1"] - ticks[i-1]["ask1"] for i in range(1, n)]
    dmid = [ticks[i]["mid"] - ticks[i-1]["mid"] for i in range(1, n)]

    for label, vals in [("dbid1", dbid1), ("dask1", dask1), ("dmid", dmid)]:
        c = Counter(vals)
        nonzero = sum(1 for v in vals if v != 0)
        print(f"  {label}: nonzero={nonzero} ({100*nonzero/len(vals):.1f}%) mean={sum(vals)/len(vals):+.3f}")
        top = sorted(c.most_common(20), key=lambda x: x[0])
        print(f"         dist: {[(k, v) for k, v in top]}")

    # ── 8. L2 CHANGES ──
    print(f"\n── 8. L2 Changes (tick-to-tick) ──")
    dbid2 = []
    dask2 = []
    for i in range(1, n):
        if ticks[i]["bid2"] is not None and ticks[i-1]["bid2"] is not None:
            dbid2.append(ticks[i]["bid2"] - ticks[i-1]["bid2"])
        if ticks[i]["ask2"] is not None and ticks[i-1]["ask2"] is not None:
            dask2.append(ticks[i]["ask2"] - ticks[i-1]["ask2"])

    for label, vals in [("dbid2", dbid2), ("dask2", dask2)]:
        if not vals:
            continue
        c = Counter(vals)
        nonzero = sum(1 for v in vals if v != 0)
        print(f"  {label}: n={len(vals)} nonzero={nonzero} ({100*nonzero/len(vals):.1f}%)")
        top = sorted(c.most_common(20), key=lambda x: x[0])
        print(f"         dist: {[(k, v) for k, v in top]}")

    # ── 9. JOINT L1 CHANGE: dbid1 vs dask1 ──
    print(f"\n── 9. Joint L1: (dbid1, dask1) ──")
    joint_l1 = Counter()
    for i in range(1, n):
        db = ticks[i]["bid1"] - ticks[i-1]["bid1"]
        da = ticks[i]["ask1"] - ticks[i-1]["ask1"]
        joint_l1[(db, da)] += 1
    # Show top patterns
    for (db, da), cnt in sorted(joint_l1.most_common(25), key=lambda x: (-x[1])):
        pct = 100 * cnt / (n - 1)
        move_type = "SYMMETRIC" if db == da else "ASYM_BID" if db != 0 and da == 0 else "ASYM_ASK" if db == 0 and da != 0 else "MIXED"
        print(f"  (db={db:+d}, da={da:+d}): {cnt:>5} ({pct:>5.1f}%) [{move_type}]")

    # ── 10. L1 vs L2 CHANGE CORRELATION ──
    print(f"\n── 10. L2 Change → Next L1 Change ──")
    # Does dbid2[t] predict dbid1[t+1]?
    pairs_b = []
    pairs_a = []
    for i in range(1, n - 1):
        if ticks[i]["bid2"] is not None and ticks[i-1]["bid2"] is not None:
            db2 = ticks[i]["bid2"] - ticks[i-1]["bid2"]
            db1_next = ticks[i+1]["bid1"] - ticks[i]["bid1"]
            pairs_b.append((db2, db1_next))
        if ticks[i]["ask2"] is not None and ticks[i-1]["ask2"] is not None:
            da2 = ticks[i]["ask2"] - ticks[i-1]["ask2"]
            da1_next = ticks[i+1]["ask1"] - ticks[i]["ask1"]
            pairs_a.append((da2, da1_next))

    if pairs_b:
        # Correlation
        n_p = len(pairs_b)
        mx = sum(p[0] for p in pairs_b) / n_p
        my = sum(p[1] for p in pairs_b) / n_p
        cov = sum((p[0]-mx)*(p[1]-my) for p in pairs_b) / n_p
        sx = (sum((p[0]-mx)**2 for p in pairs_b) / n_p) ** 0.5
        sy = (sum((p[1]-my)**2 for p in pairs_b) / n_p) ** 0.5
        r = cov / (sx * sy) if sx > 0 and sy > 0 else 0
        print(f"  dbid2[t] → dbid1[t+1]: r={r:+.4f} (n={n_p})")

        # Conditional means: when L2 bid moved, what happens to L1 bid next?
        db2_buckets = defaultdict(list)
        for x, y in pairs_b:
            if x != 0:
                db2_buckets[x].append(y)
        for k in sorted(db2_buckets):
            vs = db2_buckets[k]
            if len(vs) >= 3:
                print(f"    dbid2={k:+d}: n={len(vs)} → mean dbid1_next={sum(vs)/len(vs):+.3f}")

    if pairs_a:
        n_p = len(pairs_a)
        mx = sum(p[0] for p in pairs_a) / n_p
        my = sum(p[1] for p in pairs_a) / n_p
        cov = sum((p[0]-mx)*(p[1]-my) for p in pairs_a) / n_p
        sx = (sum((p[0]-mx)**2 for p in pairs_a) / n_p) ** 0.5
        sy = (sum((p[1]-my)**2 for p in pairs_a) / n_p) ** 0.5
        r = cov / (sx * sy) if sx > 0 and sy > 0 else 0
        print(f"  dask2[t] → dask1[t+1]: r={r:+.4f} (n={n_p})")

        da2_buckets = defaultdict(list)
        for x, y in pairs_a:
            if x != 0:
                da2_buckets[x].append(y)
        for k in sorted(da2_buckets):
            vs = da2_buckets[k]
            if len(vs) >= 3:
                print(f"    dask2={k:+d}: n={len(vs)} → mean dask1_next={sum(vs)/len(vs):+.3f}")

    # ── 11. L2 GAP CHANGES ──
    print(f"\n── 11. L2 Gap Changes ──")
    dgap_bid = []
    dgap_ask = []
    for i in range(1, n):
        if ticks[i]["bid_gap"] is not None and ticks[i-1]["bid_gap"] is not None:
            dgap_bid.append(ticks[i]["bid_gap"] - ticks[i-1]["bid_gap"])
        if ticks[i]["ask_gap"] is not None and ticks[i-1]["ask_gap"] is not None:
            dgap_ask.append(ticks[i]["ask_gap"] - ticks[i-1]["ask_gap"])

    for label, vals in [("d_bid_gap", dgap_bid), ("d_ask_gap", dgap_ask)]:
        if not vals:
            continue
        c = Counter(vals)
        nonzero = sum(1 for v in vals if v != 0)
        print(f"  {label}: n={len(vals)} nonzero={nonzero} ({100*nonzero/len(vals):.1f}%)")
        top = sorted(c.most_common(15), key=lambda x: x[0])
        print(f"         dist: {[(k, v) for k, v in top]}")

    # ── 12. GAP ASYMMETRY → NEXT MID ──
    print(f"\n── 12. Gap Asymmetry (bid_gap - ask_gap) → Next dmid ──")
    gap_asym_next = []
    for i in range(n - 1):
        if ticks[i]["bid_gap"] is not None and ticks[i]["ask_gap"] is not None:
            asym = ticks[i]["bid_gap"] - ticks[i]["ask_gap"]
            dm = ticks[i+1]["mid"] - ticks[i]["mid"]
            gap_asym_next.append((asym, dm))

    if gap_asym_next:
        asym_buckets = defaultdict(list)
        for a, dm in gap_asym_next:
            asym_buckets[a].append(dm)
        for k in sorted(asym_buckets):
            vs = asym_buckets[k]
            if len(vs) >= 5:
                mean_dm = sum(vs) / len(vs)
                up = sum(1 for v in vs if v > 0)
                dn = sum(1 for v in vs if v < 0)
                print(f"  gap_asym={k:+d}: n={len(vs):>4} mean_dm={mean_dm:+.3f} up={up} dn={dn}")

    # ── 13. VOLUME CHANGES ──
    print(f"\n── 13. Volume Changes (tick-to-tick) ──")
    dbv1 = [ticks[i]["bv1"] - ticks[i-1]["bv1"] for i in range(1, n)]
    dav1 = [ticks[i]["av1"] - ticks[i-1]["av1"] for i in range(1, n)]
    for label, vals in [("dbv1", dbv1), ("dav1", dav1)]:
        c = Counter(vals)
        nonzero = sum(1 for v in vals if v != 0)
        print(f"  {label}: nonzero={nonzero} ({100*nonzero/len(vals):.1f}%)")
        top = sorted(c.most_common(20), key=lambda x: x[0])
        print(f"         dist: {[(k, v) for k, v in top]}")

    # ── 14. VOLUME CHANGE → NEXT MID ──
    print(f"\n── 14. L1 Volume Change → Next dmid ──")
    # Does volume increasing on bid side predict UP?
    vol_imb_change = []
    for i in range(1, n - 1):
        dv = (ticks[i]["bv1"] - ticks[i-1]["bv1"]) - (ticks[i]["av1"] - ticks[i-1]["av1"])
        dm = ticks[i+1]["mid"] - ticks[i]["mid"]
        vol_imb_change.append((dv, dm))

    buckets = defaultdict(list)
    for dv, dm in vol_imb_change:
        # bucket into ranges
        if dv <= -5:
            b = "≤-5"
        elif dv <= -2:
            b = "-4 to -2"
        elif dv <= -1:
            b = "-1"
        elif dv == 0:
            b = "0"
        elif dv <= 1:
            b = "+1"
        elif dv <= 4:
            b = "+2 to +4"
        else:
            b = "≥+5"
        buckets[b].append(dm)

    for b in ["≤-5", "-4 to -2", "-1", "0", "+1", "+2 to +4", "≥+5"]:
        vs = buckets.get(b, [])
        if vs:
            mean_dm = sum(vs) / len(vs)
            print(f"  vol_imb_change {b:>10}: n={len(vs):>4} mean_dm={mean_dm:+.4f}")

    # ── 15. LOG-RETURNS ──
    print(f"\n── 15. Log-Returns ──")
    log_rets = [math.log(ticks[i]["mid"] / ticks[i-1]["mid"]) for i in range(1, n) if ticks[i-1]["mid"] > 0]
    if log_rets:
        mean_lr = sum(log_rets) / len(log_rets)
        var_lr = sum((x - mean_lr)**2 for x in log_rets) / len(log_rets)
        std_lr = var_lr ** 0.5
        skew_lr = sum((x - mean_lr)**3 for x in log_rets) / (len(log_rets) * std_lr**3) if std_lr > 0 else 0
        kurt_lr = sum((x - mean_lr)**4 for x in log_rets) / (len(log_rets) * std_lr**4) - 3 if std_lr > 0 else 0
        print(f"  mean={mean_lr:+.8f} std={std_lr:.8f}")
        print(f"  skew={skew_lr:+.4f} excess_kurt={kurt_lr:+.4f}")
        # Autocorrelation of log returns
        if len(log_rets) > 5:
            for lag in [1, 2, 3, 4, 5]:
                c = sum((log_rets[i] - mean_lr) * (log_rets[i-lag] - mean_lr) for i in range(lag, len(log_rets)))
                c /= sum((x - mean_lr)**2 for x in log_rets)
                print(f"  AC(log_ret, lag={lag}): {c:+.4f}")

    # ── 16. ASYMMETRIC L1 MOVES ──
    print(f"\n── 16. Asymmetric L1 Moves (bid moves ≠ ask moves) ──")
    asym_types = Counter()
    for i in range(1, n):
        db = ticks[i]["bid1"] - ticks[i-1]["bid1"]
        da = ticks[i]["ask1"] - ticks[i-1]["ask1"]
        if db == 0 and da == 0:
            asym_types["NO_MOVE"] += 1
        elif db == da:
            asym_types["SYMMETRIC"] += 1
        elif db != 0 and da == 0:
            asym_types["BID_ONLY"] += 1
        elif db == 0 and da != 0:
            asym_types["ASK_ONLY"] += 1
        else:
            if (db > 0) == (da > 0):
                asym_types["SAME_DIR_DIFF_MAG"] += 1
            else:
                asym_types["OPPOSITE_DIR"] += 1

    total_moves = n - 1
    for k in ["NO_MOVE", "SYMMETRIC", "BID_ONLY", "ASK_ONLY", "SAME_DIR_DIFF_MAG", "OPPOSITE_DIR"]:
        cnt = asym_types.get(k, 0)
        print(f"  {k:>20}: {cnt:>5} ({100*cnt/total_moves:>5.1f}%)")

    # Conditional: after asymmetric moves, what happens next?
    print(f"\n  After BID_ONLY moves → next dmid:")
    after_bid_only = []
    for i in range(1, n - 1):
        db = ticks[i]["bid1"] - ticks[i-1]["bid1"]
        da = ticks[i]["ask1"] - ticks[i-1]["ask1"]
        if db != 0 and da == 0:
            dm_next = ticks[i+1]["mid"] - ticks[i]["mid"]
            after_bid_only.append((db, dm_next))

    bid_only_buckets = defaultdict(list)
    for db, dm in after_bid_only:
        bid_only_buckets[db].append(dm)
    for k in sorted(bid_only_buckets):
        vs = bid_only_buckets[k]
        if len(vs) >= 3:
            print(f"    dbid={k:+d}: n={len(vs)} → mean next_dm={sum(vs)/len(vs):+.3f}")

    print(f"\n  After ASK_ONLY moves → next dmid:")
    after_ask_only = []
    for i in range(1, n - 1):
        db = ticks[i]["bid1"] - ticks[i-1]["bid1"]
        da = ticks[i]["ask1"] - ticks[i-1]["ask1"]
        if db == 0 and da != 0:
            dm_next = ticks[i+1]["mid"] - ticks[i]["mid"]
            after_ask_only.append((da, dm_next))

    ask_only_buckets = defaultdict(list)
    for da, dm in after_ask_only:
        ask_only_buckets[da].append(dm)
    for k in sorted(ask_only_buckets):
        vs = ask_only_buckets[k]
        if len(vs) >= 3:
            print(f"    dask={k:+d}: n={len(vs)} → mean next_dm={sum(vs)/len(vs):+.3f}")

    # ── 17. L2 LEADS L1? ──
    print(f"\n── 17. L2 Moves Before L1 (lead-lag) ──")
    # When L2 bid changes but L1 bid doesn't, does L1 bid follow next tick?
    l2_lead_bid = []
    for i in range(1, n - 1):
        if ticks[i]["bid2"] is not None and ticks[i-1]["bid2"] is not None:
            db2 = ticks[i]["bid2"] - ticks[i-1]["bid2"]
            db1 = ticks[i]["bid1"] - ticks[i-1]["bid1"]
            if db2 != 0 and db1 == 0:
                # L2 moved, L1 didn't — does L1 follow?
                db1_next = ticks[i+1]["bid1"] - ticks[i]["bid1"]
                l2_lead_bid.append((db2, db1_next))

    if l2_lead_bid:
        print(f"  Cases where L2 bid moved but L1 bid didn't: {len(l2_lead_bid)}")
        lead_buckets = defaultdict(list)
        for db2, db1n in l2_lead_bid:
            lead_buckets["UP" if db2 > 0 else "DOWN"].append(db1n)
        for k in ["UP", "DOWN"]:
            vs = lead_buckets.get(k, [])
            if vs:
                followed = sum(1 for v in vs if (v > 0) == (k == "UP")) / len(vs) * 100
                print(f"    L2 bid {k}: n={len(vs)} → L1 followed={followed:.1f}% mean_next_db1={sum(vs)/len(vs):+.3f}")

    l2_lead_ask = []
    for i in range(1, n - 1):
        if ticks[i]["ask2"] is not None and ticks[i-1]["ask2"] is not None:
            da2 = ticks[i]["ask2"] - ticks[i-1]["ask2"]
            da1 = ticks[i]["ask1"] - ticks[i-1]["ask1"]
            if da2 != 0 and da1 == 0:
                da1_next = ticks[i+1]["ask1"] - ticks[i]["ask1"]
                l2_lead_ask.append((da2, da1_next))

    if l2_lead_ask:
        print(f"  Cases where L2 ask moved but L1 ask didn't: {len(l2_lead_ask)}")
        lead_buckets = defaultdict(list)
        for da2, da1n in l2_lead_ask:
            lead_buckets["UP" if da2 > 0 else "DOWN"].append(da1n)
        for k in ["UP", "DOWN"]:
            vs = lead_buckets.get(k, [])
            if vs:
                followed = sum(1 for v in vs if (v > 0) == (k == "UP")) / len(vs) * 100
                print(f"    L2 ask {k}: n={len(vs)} → L1 followed={followed:.1f}% mean_next_da1={sum(vs)/len(vs):+.3f}")

    # ── 18. VOLUME RATIO L2/L1 DISTRIBUTIONS ──
    print(f"\n── 18. Volume Ratio L2/L1 ──")
    vol_ratio_bid = [t["bv2"] / t["bv1"] for t in ticks if t["bv1"] > 0 and t["bv2"] is not None and t["bv2"] > 0]
    vol_ratio_ask = [t["av2"] / t["av1"] for t in ticks if t["av1"] > 0 and t["av2"] is not None and t["av2"] > 0]
    if vol_ratio_bid:
        mean_r = sum(vol_ratio_bid) / len(vol_ratio_bid)
        std_r = (sum((x-mean_r)**2 for x in vol_ratio_bid) / len(vol_ratio_bid)) ** 0.5
        vals_rounded = Counter(round(v, 1) for v in vol_ratio_bid)
        print(f"  bv2/bv1: n={len(vol_ratio_bid)} mean={mean_r:.3f} std={std_r:.3f}")
        print(f"           dist (rounded): {sorted(vals_rounded.most_common(10))}")
    if vol_ratio_ask:
        mean_r = sum(vol_ratio_ask) / len(vol_ratio_ask)
        std_r = (sum((x-mean_r)**2 for x in vol_ratio_ask) / len(vol_ratio_ask)) ** 0.5
        vals_rounded = Counter(round(v, 1) for v in vol_ratio_ask)
        print(f"  av2/av1: n={len(vol_ratio_ask)} mean={mean_r:.3f} std={std_r:.3f}")
        print(f"           dist (rounded): {sorted(vals_rounded.most_common(10))}")

    # ── 19. BID/ASK VOLUME SYMMETRY AT EACH LEVEL ──
    print(f"\n── 19. Volume Symmetry (bv == av at each level) ──")
    sym_l1 = sum(1 for t in ticks if t["bv1"] == t["av1"])
    sym_l2 = sum(1 for t in ticks if t["bv2"] is not None and t["av2"] is not None and t["bv2"] == t["av2"])
    n_l2 = sum(1 for t in ticks if t["bv2"] is not None and t["av2"] is not None)
    print(f"  L1 symmetric: {sym_l1}/{n} ({100*sym_l1/n:.1f}%)")
    print(f"  L2 symmetric: {sym_l2}/{n_l2} ({100*sym_l2/n_l2:.1f}%)" if n_l2 > 0 else "  L2: N/A")

    # When L1 is ASYMMETRIC, which side is heavier?
    asym_l1_bid_heavy = sum(1 for t in ticks if t["bv1"] > t["av1"])
    asym_l1_ask_heavy = sum(1 for t in ticks if t["bv1"] < t["av1"])
    print(f"  L1 bid-heavy: {asym_l1_bid_heavy} ({100*asym_l1_bid_heavy/n:.1f}%)")
    print(f"  L1 ask-heavy: {asym_l1_ask_heavy} ({100*asym_l1_ask_heavy/n:.1f}%)")

    # ── 20. CONSECUTIVE MOVE PATTERNS ──
    print(f"\n── 20. Consecutive Mid Move Patterns ──")
    move_pairs = Counter()
    for i in range(2, n):
        prev = ticks[i-1]["mid"] - ticks[i-2]["mid"]
        curr = ticks[i]["mid"] - ticks[i-1]["mid"]
        p = "+" if prev > 0 else ("-" if prev < 0 else "0")
        c = "+" if curr > 0 else ("-" if curr < 0 else "0")
        move_pairs[(p, c)] += 1

    for (p, c) in sorted(move_pairs, key=lambda x: -move_pairs[x]):
        cnt = move_pairs[(p, c)]
        print(f"  {p} → {c}: {cnt:>5} ({100*cnt/(n-2):>5.1f}%)")
