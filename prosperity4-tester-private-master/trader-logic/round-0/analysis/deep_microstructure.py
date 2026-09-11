#!/usr/bin/env python3
"""
DEEP MICROSTRUCTURE ANALYSIS — Finding the Hidden Edge
=====================================================
Goes beyond simple statistics into the actual generative model:
- How does the MM bot ACTUALLY update quotes?
- What PRECEDES profitable vs unprofitable ticks?
- Where does the PnL come from tick-by-tick?
- What information exists in the ORDER BOOK that we're ignoring?
- Is there a SEQUENCE pattern in quote changes?
"""

import csv
import numpy as np
from collections import defaultdict, Counter
import json

DATA_DIR = '/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0'

def load_prices(day):
    rows = []
    with open(f'{DATA_DIR}/prices_round_0_day_{day}.csv') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] == 'TOMATOES':
                r = {}
                for k, v in row.items():
                    if v == '':
                        r[k] = None
                    else:
                        try:
                            r[k] = float(v)
                        except:
                            r[k] = v
                rows.append(r)
    return rows

def load_trades(day):
    rows = []
    with open(f'{DATA_DIR}/trades_round_0_day_{day}.csv') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['symbol'] == 'TOMATOES':
                rows.append({
                    'timestamp': float(row['timestamp']),
                    'price': float(row['price']),
                    'quantity': int(float(row['quantity'])),
                })
    return rows

def extract_features(rows):
    """Extract ALL microstructure features from price rows."""
    n = len(rows)
    d = {
        'timestamp': np.array([r['timestamp'] for r in rows]),
        'bid1': np.array([r['bid_price_1'] for r in rows]),
        'ask1': np.array([r['ask_price_1'] for r in rows]),
        'bv1': np.array([r['bid_volume_1'] for r in rows]),
        'av1': np.array([r['ask_volume_1'] for r in rows]),
        'bid2': np.array([r.get('bid_price_2') or 0 for r in rows]),
        'ask2': np.array([r.get('ask_price_2') or 0 for r in rows]),
        'bv2': np.array([r.get('bid_volume_2') or 0 for r in rows]),
        'av2': np.array([r.get('ask_volume_2') or 0 for r in rows]),
        'bid3': np.array([r.get('bid_price_3') or 0 for r in rows]),
        'ask3': np.array([r.get('ask_price_3') or 0 for r in rows]),
        'bv3': np.array([r.get('bid_volume_3') or 0 for r in rows]),
        'av3': np.array([r.get('ask_volume_3') or 0 for r in rows]),
    }
    d['mid'] = (d['bid1'] + d['ask1']) / 2
    d['spread'] = d['ask1'] - d['bid1']
    d['dmid'] = np.diff(d['mid'], prepend=d['mid'][0])
    d['microprice'] = d['bid1'] + d['bv1'] / (d['bv1'] + d['av1']) * (d['ask1'] - d['bid1'])

    # L2 features
    mask_l2 = d['bid2'] > 0
    d['l2_mid'] = np.where(mask_l2, (d['bid2'] + d['ask2']) / 2, d['mid'])
    d['l2_spread'] = np.where(mask_l2, d['ask2'] - d['bid2'], d['spread'])
    d['l1_l2_gap_bid'] = d['bid1'] - d['bid2']
    d['l1_l2_gap_ask'] = d['ask2'] - d['ask1']

    # Book shape
    d['total_bid_vol'] = d['bv1'] + d['bv2'] + d['bv3']
    d['total_ask_vol'] = d['av1'] + d['av2'] + d['av3']
    d['obi'] = (d['total_bid_vol'] - d['total_ask_vol']) / np.maximum(d['total_bid_vol'] + d['total_ask_vol'], 1)
    d['l1_obi'] = (d['bv1'] - d['av1']) / np.maximum(d['bv1'] + d['av1'], 1)
    d['vol_ratio'] = d['bv1'] / np.maximum(d['av1'], 1)

    return d, n

def analyze_day(day_label, rows, trades):
    d, n = extract_features(rows)
    print(f"\n{'#'*100}")
    print(f"# DAY {day_label}: {n} ticks, {len(trades)} trades")
    print(f"{'#'*100}")

    # ═══════════════════════════════════════════════════════════════
    # 1. QUOTE UPDATE MECHANICS — How does the MM bot ACTUALLY move?
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("1. MM BOT QUOTE UPDATE MECHANICS")
    print(f"{'='*80}")

    dbid = np.diff(d['bid1'])
    dask = np.diff(d['ask1'])
    dmid = d['dmid'][1:]

    # Bid and ask move INDEPENDENTLY or together?
    both_move = (dbid != 0) & (dask != 0)
    bid_only = (dbid != 0) & (dask == 0)
    ask_only = (dbid == 0) & (dask != 0)
    neither = (dbid == 0) & (dask == 0)
    same_dir = both_move & (np.sign(dbid) == np.sign(dask))
    opp_dir = both_move & (np.sign(dbid) != np.sign(dask))

    print(f"  Both move (same dir):  {same_dir.sum():5d} ({100*same_dir.mean():.1f}%)")
    print(f"  Both move (opp dir):   {opp_dir.sum():5d} ({100*opp_dir.mean():.1f}%)")
    print(f"  Bid only:              {bid_only.sum():5d} ({100*bid_only.mean():.1f}%)")
    print(f"  Ask only:              {ask_only.sum():5d} ({100*ask_only.mean():.1f}%)")
    print(f"  Neither:               {neither.sum():5d} ({100*neither.mean():.1f}%)")

    # When bid moves alone, what happens to mid NEXT tick?
    print(f"\n  --- PREDICTIVE VALUE of asymmetric moves ---")
    for label, mask in [("Bid UP only", bid_only & (dbid > 0)),
                         ("Bid DOWN only", bid_only & (dbid < 0)),
                         ("Ask UP only", ask_only & (dask > 0)),
                         ("Ask DOWN only", ask_only & (dask < 0)),
                         ("Both UP", same_dir & (dbid > 0)),
                         ("Both DOWN", same_dir & (dbid < 0)),
                         ("Spread WIDEN (bid dn, ask up)", opp_dir & (dbid < 0)),
                         ("Spread NARROW (bid up, ask dn)", opp_dir & (dbid > 0))]:
        idx = np.where(mask)[0]
        if len(idx) > 0 and idx[-1] < len(dmid) - 1:
            next_dmid = dmid[idx[idx < len(dmid) - 1] + 1]  # dmid at t+2
            if len(next_dmid) > 5:
                print(f"    {label:35s}: n={len(next_dmid):4d}, E[dmid_next]={next_dmid.mean():+.3f}, "
                      f"P(up)={100*(next_dmid>0).mean():.0f}% P(dn)={100*(next_dmid<0).mean():.0f}%")

    # ═══════════════════════════════════════════════════════════════
    # 2. SPREAD STATE MACHINE — Transitions between spread states
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("2. SPREAD STATE MACHINE")
    print(f"{'='*80}")

    spreads = d['spread']
    spread_vals = sorted(set(spreads.astype(int)))
    print(f"  Spread values: {spread_vals}")
    spread_counts = Counter(spreads.astype(int))
    for s in spread_vals:
        print(f"    Spread {s:2d}: {spread_counts[s]:5d} ({100*spread_counts[s]/n:.1f}%)")

    # Transition matrix
    print(f"\n  Spread transition matrix:")
    transitions = defaultdict(lambda: defaultdict(int))
    for i in range(n - 1):
        s1 = int(spreads[i])
        s2 = int(spreads[i + 1])
        transitions[s1][s2] += 1

    print(f"    {'From\\To':>8}", end='')
    for s in spread_vals:
        print(f"  {s:5d}", end='')
    print()
    for s1 in spread_vals:
        total = sum(transitions[s1].values())
        if total == 0:
            continue
        print(f"    {s1:8d}", end='')
        for s2 in spread_vals:
            pct = 100 * transitions[s1][s2] / total if total > 0 else 0
            print(f"  {pct:5.1f}", end='')
        print(f"  (n={total})")

    # What predicts spread NARROWING?
    print(f"\n  --- What precedes spread narrowing (going to <=9)? ---")
    narrow_entries = []
    for i in range(2, n):
        if spreads[i] <= 9 and spreads[i-1] >= 13:
            narrow_entries.append(i)
    print(f"  Narrow entry events: {len(narrow_entries)}")
    if narrow_entries:
        # What happened in the 3 ticks before?
        dmid_before_narrow = []
        spread_before_narrow = []
        vol_asym_before_narrow = []
        for i in narrow_entries:
            if i >= 3:
                dmid_before_narrow.append(d['dmid'][i-1])
                spread_before_narrow.append(d['spread'][i-2])
                vol_asym_before_narrow.append(d['l1_obi'][i-1])
        if dmid_before_narrow:
            arr = np.array(dmid_before_narrow)
            print(f"  dmid at t-1: mean={arr.mean():+.2f}, |mean|={np.abs(arr).mean():.2f}, "
                  f"P(>0)={100*(arr>0).mean():.0f}%")
            varr = np.array(vol_asym_before_narrow)
            print(f"  L1 OBI at t-1: mean={varr.mean():+.3f}")

    # ═══════════════════════════════════════════════════════════════
    # 3. VOLUME PATTERNS — The REAL information in the book
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("3. VOLUME PATTERNS & BOOK SHAPE")
    print(f"{'='*80}")

    # L1 volume distribution
    print(f"  L1 bid vol: mean={d['bv1'].mean():.1f}, std={d['bv1'].std():.1f}, "
          f"min={d['bv1'].min():.0f}, max={d['bv1'].max():.0f}")
    print(f"  L1 ask vol: mean={d['av1'].mean():.1f}, std={d['av1'].std():.1f}, "
          f"min={d['av1'].min():.0f}, max={d['av1'].max():.0f}")

    # Volume CHANGE predicts price?
    dbv1 = np.diff(d['bv1'])
    dav1 = np.diff(d['av1'])
    next_dm = dmid

    print(f"\n  --- Volume CHANGE → next mid move ---")
    for label, feat in [("dBidVol1", dbv1), ("dAskVol1", dav1),
                          ("dBidVol1 - dAskVol1", dbv1 - dav1)]:
        # Bin by quintile
        pcts = np.percentile(feat, [20, 40, 60, 80])
        for lo, hi, lbl in [(feat.min()-1, pcts[0], "Q1 (lowest)"),
                             (pcts[0], pcts[1], "Q2"),
                             (pcts[1], pcts[2], "Q3 (middle)"),
                             (pcts[2], pcts[3], "Q4"),
                             (pcts[3], feat.max()+1, "Q5 (highest)")]:
            mask = (feat >= lo) & (feat < hi)
            valid = mask[:len(next_dm)]
            if valid.sum() > 10:
                nm = next_dm[valid]
                print(f"    {label:25s} {lbl:15s}: n={valid.sum():4d}, "
                      f"E[dmid_next]={nm.mean():+.4f}, dir_acc={100*((nm>0).mean() if nm.mean()>0 else (nm<0).mean()):.0f}%")

    # ═══════════════════════════════════════════════════════════════
    # 4. L3 APPEARANCES — When does L3 show up?
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("4. L3 BOOK DEPTH APPEARANCES")
    print(f"{'='*80}")

    has_l3 = d['bid3'] > 0
    print(f"  Ticks with L3 data: {has_l3.sum()} ({100*has_l3.mean():.1f}%)")

    # Are L3 ticks special?
    if has_l3.sum() > 10:
        # What spread state during L3?
        l3_spreads = Counter(d['spread'][has_l3].astype(int))
        print(f"  Spread during L3: {dict(l3_spreads)}")

        # Price at L3 ticks
        l3_idx = np.where(has_l3)[0]
        l3_dmid_after = []
        for i in l3_idx:
            if i + 1 < n:
                l3_dmid_after.append(d['dmid'][i+1])
        if l3_dmid_after:
            arr = np.array(l3_dmid_after)
            print(f"  dmid AFTER L3 tick: mean={arr.mean():+.3f}, |mean|={np.abs(arr).mean():.3f}")
            print(f"  (vs overall |dmid|={np.abs(d['dmid'][1:]).mean():.3f})")

        # What's the L3 price relationship?
        l3_gap_bid = d['bid1'][has_l3] - d['bid3'][has_l3]
        l3_gap_ask = d['ask3'][has_l3] - d['ask1'][has_l3]
        print(f"  L3 bid gap (bid1-bid3): mean={l3_gap_bid.mean():.1f}")
        print(f"  L3 ask gap (ask3-ask1): mean={l3_gap_ask.mean():.1f}")

        # L3 is our OWN orders! Check if L3 prices cluster at best±1
        l3_bid_prices = d['bid3'][has_l3]
        l3_ask_prices = d['ask3'][has_l3]
        l3_bid1 = d['bid1'][has_l3]
        l3_ask1 = d['ask1'][has_l3]
        bid_offset = l3_bid1 - l3_bid_prices
        ask_offset = l3_ask_prices - l3_ask1
        print(f"  L3 bid offset from L1 (bid1-bid3): {Counter(bid_offset.astype(int))}")
        print(f"  L3 ask offset from L1 (ask3-ask1): {Counter(ask_offset.astype(int))}")

    # ═══════════════════════════════════════════════════════════════
    # 5. TRADE ARRIVAL PATTERNS — Taker bot forensics
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("5. TAKER BOT FORENSICS")
    print(f"{'='*80}")

    if trades:
        trade_ts = np.array([t['timestamp'] for t in trades])
        trade_px = np.array([t['price'] for t in trades])
        trade_qty = np.array([t['quantity'] for t in trades])

        # Inter-arrival times
        iat = np.diff(trade_ts)
        print(f"  Trades: {len(trades)}")
        print(f"  Inter-arrival: mean={iat.mean():.0f}ms, median={np.median(iat):.0f}ms, "
              f"std={iat.std():.0f}ms")

        # Trade side inference
        sides = []
        for t in trades:
            ts = int(t['timestamp'])
            # Find matching price row
            idx = -1
            for j, r in enumerate(rows):
                if r['timestamp'] == ts:
                    idx = j
                    break
            if idx >= 0:
                if t['price'] >= d['ask1'][idx]:
                    sides.append('buy')
                elif t['price'] <= d['bid1'][idx]:
                    sides.append('sell')
                else:
                    sides.append('mid')
            else:
                sides.append('unknown')

        side_counts = Counter(sides)
        print(f"  Trade sides: {dict(side_counts)}")

        # Do trades CLUSTER at certain timestamps?
        ts_mod = trade_ts % 1000  # position within second
        print(f"\n  Trade timing within second (mod 1000):")
        for lo, hi, lbl in [(0, 200, "0-200ms"), (200, 400, "200-400ms"),
                             (400, 600, "400-600ms"), (600, 800, "600-800ms"),
                             (800, 1000, "800-1000ms")]:
            cnt = ((ts_mod >= lo) & (ts_mod < hi)).sum()
            print(f"    {lbl}: {cnt} ({100*cnt/len(trade_ts):.1f}%)")

        # Trade price vs mid at time of trade
        trade_mid = []
        for t in trades:
            ts = int(t['timestamp'])
            for j, r in enumerate(rows):
                if r['timestamp'] == ts:
                    trade_mid.append(d['mid'][j])
                    break
        if trade_mid:
            arr = np.array(trade_mid)
            dev = trade_px - arr
            print(f"\n  Trade price - mid: mean={dev.mean():+.2f}, all buys above mid: {(dev > 0).sum()}, "
                  f"all sells below: {(dev < 0).sum()}")

        # CRITICAL: What happens to mid AFTER a trade?
        print(f"\n  --- Mid movement AFTER trade (adverse selection) ---")
        for horizon in [1, 2, 3, 5, 10]:
            impacts = []
            for t in trades:
                ts = int(t['timestamp'])
                for j, r in enumerate(rows):
                    if r['timestamp'] == ts and j + horizon < n:
                        side = 1 if t['price'] >= d['ask1'][j] else -1
                        future_dmid = d['mid'][j + horizon] - d['mid'][j]
                        impacts.append(side * future_dmid)  # positive = adverse
                        break
            if impacts:
                arr = np.array(impacts)
                print(f"    t+{horizon:2d}: E[adverse]={arr.mean():+.3f}, "
                      f"P(adverse)={100*(arr>0).mean():.0f}%")

    # ═══════════════════════════════════════════════════════════════
    # 6. THE BIG ONE: CONDITIONAL BOOK STATE → FUTURE MID
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("6. BOOK STATE → FUTURE MID (THE HIDDEN EDGE)")
    print(f"{'='*80}")

    # Create composite features and test each for prediction
    features = {}

    # Feature 1: Volume imbalance at DIFFERENT levels
    features['l1_obi'] = d['l1_obi']
    features['total_obi'] = d['obi']
    features['l2_obi'] = np.where(d['bv2'] + d['av2'] > 0,
                                    (d['bv2'] - d['av2']) / (d['bv2'] + d['av2']), 0)

    # Feature 2: Spread state
    features['spread'] = d['spread']

    # Feature 3: Volume levels (not ratio)
    features['bv1'] = d['bv1']
    features['av1'] = d['av1']
    features['bv1_minus_av1'] = d['bv1'] - d['av1']

    # Feature 4: Price position relative to L2
    features['bid1_minus_bid2'] = d['bid1'] - d['bid2']
    features['ask2_minus_ask1'] = d['ask2'] - d['ask1']
    features['l1_l2_gap_asymmetry'] = features['bid1_minus_bid2'] - features['ask2_minus_ask1']

    # Feature 5: Recent momentum
    for lag in [1, 2, 3]:
        features[f'dmid_lag{lag}'] = np.roll(d['dmid'], lag)
        features[f'dmid_lag{lag}'][:lag] = 0

    # Feature 6: Volume at specific PRICE levels (not just L1/L2)
    # How far is bid1 from mid? (asymmetric quotes)
    features['bid1_from_mid'] = d['mid'] - d['bid1']
    features['ask1_from_mid'] = d['ask1'] - d['mid']
    features['quote_asymmetry'] = features['ask1_from_mid'] - features['bid1_from_mid']

    # Feature 7: INTERACTION features
    features['obi_x_spread'] = d['obi'] * d['spread']
    features['obi_x_dmid_lag1'] = d['obi'] * np.roll(d['dmid'], 1)

    # Feature 8: Volume clustering (was there a big volume change?)
    features['dbv1'] = np.diff(d['bv1'], prepend=d['bv1'][0])
    features['dav1'] = np.diff(d['av1'], prepend=d['av1'][0])
    features['dvol_imb'] = features['dbv1'] - features['dav1']

    # Feature 9: Total book depth change
    features['dtotal_bid'] = np.diff(d['total_bid_vol'], prepend=d['total_bid_vol'][0])
    features['dtotal_ask'] = np.diff(d['total_ask_vol'], prepend=d['total_ask_vol'][0])

    # Feature 10: Microprice deviation from mid
    features['microprice_dev'] = d['microprice'] - d['mid']

    # Target: next mid change
    target = np.roll(d['dmid'], -1)
    target[-1] = 0

    print(f"\n  Feature → next dmid correlation (Pearson r):")
    results = []
    for name, feat in sorted(features.items()):
        valid = ~(np.isnan(feat) | np.isinf(feat))
        if valid.sum() < 100:
            continue
        r = np.corrcoef(feat[valid], target[valid])[0, 1]
        results.append((abs(r), r, name))

    results.sort(reverse=True)
    for _, r, name in results[:25]:
        direction = "↑" if r > 0 else "↓"
        strength = "███" if abs(r) > 0.3 else "██" if abs(r) > 0.1 else "█" if abs(r) > 0.05 else "·"
        print(f"    {name:30s}: r={r:+.4f} {direction} {strength}")

    # ═══════════════════════════════════════════════════════════════
    # 7. CONDITIONAL ANALYSIS — When is each feature STRONGEST?
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("7. CONDITIONAL EDGE: WHEN DOES THE BOOK TELL THE TRUTH?")
    print(f"{'='*80}")

    # Split by spread state
    for spread_val in [5, 6, 7, 8, 9, 13, 14]:
        mask = d['spread'] == spread_val
        cnt = mask.sum()
        if cnt < 20:
            continue
        target_here = target[mask]
        print(f"\n  Spread = {spread_val} ({cnt} ticks, {100*cnt/n:.1f}%):")
        print(f"    E[dmid_next] = {target_here.mean():+.4f}")
        print(f"    |dmid_next| = {np.abs(target_here).mean():.4f}")
        print(f"    P(up) = {100*(target_here>0).mean():.1f}%, P(dn) = {100*(target_here<0).mean():.1f}%")

        # Best feature within this spread state
        best_r = 0
        best_feat = ""
        for name, feat in features.items():
            valid = mask & ~(np.isnan(feat) | np.isinf(feat))
            if valid.sum() < 20:
                continue
            r = np.corrcoef(feat[valid], target[valid])[0, 1]
            if abs(r) > abs(best_r):
                best_r = r
                best_feat = name
        print(f"    Best predictor: {best_feat} (r={best_r:+.4f})")

    # ═══════════════════════════════════════════════════════════════
    # 8. SEQUENCE MINING — Are there quote update PATTERNS?
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("8. QUOTE UPDATE SEQUENCE PATTERNS")
    print(f"{'='*80}")

    # Encode each tick as a letter based on what happened
    codes = []
    for i in range(1, n):
        db = d['bid1'][i] - d['bid1'][i-1]
        da = d['ask1'][i] - d['ask1'][i-1]
        if db > 0 and da > 0:
            codes.append('U')  # Both up
        elif db < 0 and da < 0:
            codes.append('D')  # Both down
        elif db > 0 and da == 0:
            codes.append('b')  # Bid up only (spread narrows)
        elif db < 0 and da == 0:
            codes.append('B')  # Bid down only (spread widens)
        elif da > 0 and db == 0:
            codes.append('A')  # Ask up only (spread widens)
        elif da < 0 and db == 0:
            codes.append('a')  # Ask down only (spread narrows)
        elif db > 0 and da < 0:
            codes.append('N')  # Narrow (bid up, ask down)
        elif db < 0 and da > 0:
            codes.append('W')  # Widen (bid down, ask up)
        else:
            codes.append('.')  # No change

    code_counts = Counter(codes)
    print(f"  Quote update types:")
    for c, label in [('U', 'Both UP'), ('D', 'Both DOWN'), ('b', 'Bid UP only'),
                      ('B', 'Bid DOWN only'), ('A', 'Ask UP only'), ('a', 'Ask DOWN only'),
                      ('N', 'NARROW (bid↑ ask↓)'), ('W', 'WIDEN (bid↓ ask↑)'), ('.', 'No change')]:
        print(f"    {c} ({label:20s}): {code_counts[c]:5d} ({100*code_counts[c]/len(codes):.1f}%)")

    # Bigram analysis: what follows what?
    print(f"\n  Bigram patterns (current → next, with prediction):")
    bigrams = defaultdict(lambda: {'count': 0, 'next_dmid': []})
    for i in range(len(codes) - 1):
        bg = codes[i] + codes[i+1]
        bigrams[bg]['count'] += 1
        if i + 2 < len(d['dmid']):
            bigrams[bg]['next_dmid'].append(d['dmid'][i+2])

    # Show top bigrams by prediction strength
    bg_results = []
    for bg, data in bigrams.items():
        if data['count'] >= 10 and data['next_dmid']:
            arr = np.array(data['next_dmid'])
            bg_results.append((abs(arr.mean()), arr.mean(), bg, data['count']))
    bg_results.sort(reverse=True)

    for _, mean_dm, bg, cnt in bg_results[:20]:
        print(f"    {bg}: n={cnt:4d}, E[dmid_t+2]={mean_dm:+.4f}")

    # ═══════════════════════════════════════════════════════════════
    # 9. THE MONEY QUESTION: Tick-by-tick P&L attribution
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("9. WHERE DOES THE MONEY COME FROM? (simulated best±1 MM)")
    print(f"{'='*80}")

    # Simulate a simple best±1 market maker
    pos = 0
    pnl = 0.0
    fills = []

    for i in range(n):
        # We post at best_bid+1 and best_ask-1
        our_bid = d['bid1'][i] + 1
        our_ask = d['ask1'][i] - 1

        if our_bid >= our_ask:
            continue  # Spread too tight to improve

        # Check if a trade happened at this tick
        tick_ts = d['timestamp'][i]
        for t in trades:
            if t['timestamp'] == tick_ts:
                if t['price'] <= our_bid and pos < 80:
                    # Taker sells to us
                    qty = min(t['quantity'], 80 - pos)
                    pos += qty
                    pnl -= our_bid * qty
                    fills.append({'tick': i, 'side': 'buy', 'price': our_bid, 'qty': qty,
                                  'mid': d['mid'][i], 'spread': d['spread'][i],
                                  'dmid_next': d['dmid'][i+1] if i+1 < n else 0,
                                  'obi': d['obi'][i]})
                elif t['price'] >= our_ask and pos > -80:
                    qty = min(t['quantity'], 80 + pos)
                    pos -= qty
                    pnl += our_ask * qty
                    fills.append({'tick': i, 'side': 'sell', 'price': our_ask, 'qty': qty,
                                  'mid': d['mid'][i], 'spread': d['spread'][i],
                                  'dmid_next': d['dmid'][i+1] if i+1 < n else 0,
                                  'obi': d['obi'][i]})

    # Mark-to-market
    final_mtm = pnl + pos * d['mid'][-1]
    print(f"  Fills: {len(fills)}, Final pos: {pos}, PnL: {final_mtm:.1f}")

    if fills:
        # Classify fills by book state at time of fill
        buy_fills = [f for f in fills if f['side'] == 'buy']
        sell_fills = [f for f in fills if f['side'] == 'sell']
        print(f"  Buy fills: {len(buy_fills)}, Sell fills: {len(sell_fills)}")

        # Was the fill ADVERSE? (mid moves against us after fill)
        adverse_buys = [f for f in buy_fills if f['dmid_next'] < 0]
        adverse_sells = [f for f in sell_fills if f['dmid_next'] > 0]
        print(f"  Adverse buys (mid drops after): {len(adverse_buys)}/{len(buy_fills)} "
              f"({100*len(adverse_buys)/max(len(buy_fills),1):.0f}%)")
        print(f"  Adverse sells (mid rises after): {len(adverse_sells)}/{len(sell_fills)} "
              f"({100*len(adverse_sells)/max(len(sell_fills),1):.0f}%)")

        # The key: WHICH fills are profitable vs unprofitable?
        print(f"\n  --- Fill context analysis ---")
        for label, subset in [("All fills", fills), ("Buy fills", buy_fills), ("Sell fills", sell_fills)]:
            if not subset:
                continue
            obi_vals = [f['obi'] for f in subset]
            spread_vals_f = [f['spread'] for f in subset]
            next_dm = [f['dmid_next'] for f in subset]
            print(f"    {label}: n={len(subset)}")
            print(f"      Mean OBI at fill: {np.mean(obi_vals):+.4f}")
            print(f"      Mean spread at fill: {np.mean(spread_vals_f):.1f}")
            print(f"      Mean dmid_next: {np.mean(next_dm):+.4f}")

    # ═══════════════════════════════════════════════════════════════
    # 10. VOLUME FINGERPRINT — The MM bot's volume generation model
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("10. MM BOT VOLUME GENERATION MODEL")
    print(f"{'='*80}")

    # L1 vol when symmetric vs asymmetric
    sym_mask = d['bv1'] == d['av1']
    print(f"  L1 symmetric (bv1==av1): {sym_mask.sum()} ({100*sym_mask.mean():.1f}%)")
    print(f"  L1 asymmetric: {(~sym_mask).sum()} ({100*(~sym_mask).mean():.1f}%)")

    # During asymmetric: who has more volume?
    asym_mask = ~sym_mask
    if asym_mask.sum() > 0:
        bid_heavy = (d['bv1'][asym_mask] > d['av1'][asym_mask]).sum()
        ask_heavy = (d['bv1'][asym_mask] < d['av1'][asym_mask]).sum()
        print(f"    Bid heavier: {bid_heavy}, Ask heavier: {ask_heavy}")

        # Asymmetric volume → next mid
        asym_obi = d['l1_obi'][asym_mask]
        asym_next = target[asym_mask]
        r = np.corrcoef(asym_obi, asym_next)[0, 1]
        print(f"    Asymmetric OBI → dmid_next: r={r:+.4f}")

        # EXTREME asymmetry
        extreme_bid = asym_mask & (d['bv1'] > d['av1'] * 2)
        extreme_ask = asym_mask & (d['av1'] > d['bv1'] * 2)
        if extreme_bid.sum() > 5:
            print(f"    Extreme bid heavy (bv1 > 2*av1): n={extreme_bid.sum()}, "
                  f"E[dmid_next]={target[extreme_bid].mean():+.4f}")
        if extreme_ask.sum() > 5:
            print(f"    Extreme ask heavy (av1 > 2*bv1): n={extreme_ask.sum()}, "
                  f"E[dmid_next]={target[extreme_ask].mean():+.4f}")

    # L2 vol pattern
    l2_present = d['bv2'] > 0
    print(f"\n  L2 volume pattern:")
    print(f"    L2 present: {l2_present.sum()} ({100*l2_present.mean():.1f}%)")
    if l2_present.sum() > 0:
        l2_ratio = d['bv2'][l2_present] / d['bv1'][l2_present]
        print(f"    L2/L1 bid vol ratio: mean={l2_ratio.mean():.2f}, std={l2_ratio.std():.2f}")

    # L1 volume as PREDICTOR — does the MM bot set volume based on where price will go?
    print(f"\n  --- L1 volume as prediction of NEXT spread state ---")
    wide_next = d['spread'][1:] >= 13
    for vol_thresh in [4, 6, 8, 10]:
        low_vol = d['bv1'][:-1] <= vol_thresh
        high_vol = d['bv1'][:-1] > vol_thresh
        if low_vol.sum() > 10 and high_vol.sum() > 10:
            print(f"    bv1 <= {vol_thresh}: P(wide_next)={100*wide_next[low_vol].mean():.1f}%, "
                  f"bv1 > {vol_thresh}: P(wide_next)={100*wide_next[high_vol].mean():.1f}%")


def main():
    for day in [-1, -2, 0]:
        rows = load_prices(day)
        trades = load_trades(day)
        analyze_day(day, rows, trades)

if __name__ == '__main__':
    main()
