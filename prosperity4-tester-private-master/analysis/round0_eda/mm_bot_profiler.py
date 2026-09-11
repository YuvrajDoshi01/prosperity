"""
mm_bot_profiler.py — Market Maker Bot Behavior Analysis
Run from: c:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/
Usage: python mm_bot_profiler.py
"""

import csv
import json
import os
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

DATA_DIR = "prosperity4bt/resources/round0"
ROUND = 0
DAYS = [-2, -1]
PRODUCTS = ["TOMATOES", "EMERALDS"]

@dataclass
class BookSnapshot:
    timestamp: int
    product: str
    bid_prices: list
    bid_volumes: list
    ask_prices: list
    ask_volumes: list
    mid: float
    spread: float
    microprice: float
    best_bid: float
    best_ask: float
    total_bid_vol: int
    total_ask_vol: int

@dataclass
class Trade:
    timestamp: int
    product: str
    price: float
    quantity: int
    side: str

def load_prices(round_num, day):
    fname = os.path.join(DATA_DIR, f"prices_round_{round_num}_day_{day}.csv")
    snapshots = defaultdict(list)
    with open(fname, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            product = row['product']
            ts = int(row['timestamp'])
            bid_prices, bid_volumes, ask_prices, ask_volumes = [], [], [], []
            for i in range(1, 4):
                bp = row.get(f'bid_price_{i}', '')
                bv = row.get(f'bid_volume_{i}', '')
                ap = row.get(f'ask_price_{i}', '')
                av = row.get(f'ask_volume_{i}', '')
                if bp and bp != '':
                    bid_prices.append(float(bp)); bid_volumes.append(int(bv))
                if ap and ap != '':
                    ask_prices.append(float(ap)); ask_volumes.append(int(av))
            if not bid_prices or not ask_prices:
                continue
            bb = max(bid_prices); ba = min(ask_prices)
            mid = (bb + ba) / 2.0; spread = ba - bb
            tbv = sum(bid_volumes); tav = sum(ask_volumes)
            mp = bb + (tbv / (tbv + tav)) * (ba - bb) if (tbv + tav) > 0 else mid
            snapshots[product].append(BookSnapshot(
                ts, product, sorted(bid_prices, reverse=True), bid_volumes,
                sorted(ask_prices), ask_volumes, mid, spread, mp, bb, ba, tbv, tav))
    for p in snapshots:
        snapshots[p].sort(key=lambda s: s.timestamp)
    return snapshots

def load_trades(round_num, day):
    fname = os.path.join(DATA_DIR, f"trades_round_{round_num}_day_{day}.csv")
    trades = defaultdict(list)
    if not os.path.exists(fname):
        return trades
    with open(fname, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            product = row['symbol']
            ts = int(row['timestamp'])
            price = float(row['price'])
            qty = int(row['quantity'])
            trades[product].append(Trade(ts, product, price, qty, ''))
    for p in trades:
        trades[p].sort(key=lambda t: t.timestamp)
    return trades

# ============================================================
# ANALYSIS 1: QUOTE UPDATE PATTERNS
# ============================================================
def analyze_quote_updates(snapshots, product):
    snaps = snapshots[product]
    if len(snaps) < 2: return
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 1: MM QUOTE UPDATE PATTERNS — {product}")
    print(f"{'='*70}")
    bid_only = ask_only = both = neither = symmetric = 0
    bid_deltas = []; ask_deltas = []; asymmetric_cases = []
    for i in range(1, len(snaps)):
        bd = snaps[i].best_bid - snaps[i-1].best_bid
        ad = snaps[i].best_ask - snaps[i-1].best_ask
        bc = bd != 0; ac = ad != 0
        if bc and ac: both += 1
        elif bc: bid_only += 1
        elif ac: ask_only += 1
        else: neither += 1
        if bc: bid_deltas.append(bd)
        if ac: ask_deltas.append(ad)
        if (bc or ac) and bd != ad:
            asymmetric_cases.append((snaps[i].timestamp, bd, ad, snaps[i].spread))
    total = len(snaps) - 1
    total_moves = both + bid_only + ask_only
    print(f"  Both moved: {both} ({100*both/total:.1f}%), Bid only: {bid_only} ({100*bid_only/total:.1f}%)")
    print(f"  Ask only: {ask_only} ({100*ask_only/total:.1f}%), Neither: {neither} ({100*neither/total:.1f}%)")
    sym = sum(1 for ts, bd, ad, sp in asymmetric_cases if False) if not asymmetric_cases else 0
    sym_count = total_moves - len(asymmetric_cases)
    print(f"  Symmetric (bid_delta==ask_delta): {sym_count}/{total_moves} ({100*sym_count/max(1,total_moves):.1f}%)")
    print(f"  Asymmetric: {len(asymmetric_cases)}/{total_moves} ({100*len(asymmetric_cases)/max(1,total_moves):.1f}%)")
    if asymmetric_cases[:5]:
        print(f"  First 5 asymmetric: (ts, bid_d, ask_d, spread)")
        for ts, bd, ad, sp in asymmetric_cases[:5]:
            print(f"    {ts}: bid_d={bd:+.1f}, ask_d={ad:+.1f}, spread={sp:.0f}")
    if bid_deltas:
        bd_hist = defaultdict(int)
        for d in bid_deltas: bd_hist[d] += 1
        top = sorted(bd_hist.items(), key=lambda x: -x[1])[:8]
        print(f"  Bid delta distribution: {dict(top)}")
    if ask_deltas:
        ad_hist = defaultdict(int)
        for d in ask_deltas: ad_hist[d] += 1
        top = sorted(ad_hist.items(), key=lambda x: -x[1])[:8]
        print(f"  Ask delta distribution: {dict(top)}")

# ============================================================
# ANALYSIS 2: POST-FILL RESPONSE (THE BIG ONE)
# ============================================================
def analyze_post_fill(snapshots, trades_by_ts, product):
    snaps = snapshots[product]
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 2: MM RESPONSE TO TAKER FILLS — {product}")
    print(f"{'='*70}")
    ts_to_idx = {s.timestamp: i for i, s in enumerate(snaps)}
    widen = tighten = same = 0
    mid_after_buy = {1:[], 2:[], 3:[], 5:[], 10:[]}
    mid_after_sell = {1:[], 2:[], 3:[], 5:[], 10:[]}
    bid_after_buy = {1:[], 2:[], 3:[], 5:[]}
    ask_after_buy = {1:[], 2:[], 3:[], 5:[]}
    ask_after_sell = {1:[], 2:[], 3:[], 5:[]}
    bid_after_sell = {1:[], 2:[], 3:[], 5:[]}
    n_events = 0
    for trade_ts, trade_list in sorted(trades_by_ts.items()):
        if trade_ts not in ts_to_idx: continue
        idx = ts_to_idx[trade_ts]
        if idx < 1 or idx + 10 >= len(snaps): continue
        at = snaps[idx]; pre = snaps[idx-1]
        price = trade_list[0].price
        is_buy = price >= at.mid
        n_events += 1
        if idx+1 < len(snaps):
            post1 = snaps[idx+1]
            if post1.spread > at.spread: widen += 1
            elif post1.spread < at.spread: tighten += 1
            else: same += 1
        for off in [1,2,3,5,10]:
            if idx+off >= len(snaps): continue
            post = snaps[idx+off]
            shift = post.mid - at.mid
            if is_buy:
                mid_after_buy[off].append(shift)
            else:
                mid_after_sell[off].append(shift)
        for off in [1,2,3,5]:
            if idx+off >= len(snaps): continue
            post = snaps[idx+off]
            if is_buy:
                bid_after_buy[off].append(post.best_bid - at.best_bid)
                ask_after_buy[off].append(post.best_ask - at.best_ask)
            else:
                bid_after_sell[off].append(post.best_bid - at.best_bid)
                ask_after_sell[off].append(post.best_ask - at.best_ask)
    print(f"  Fill events: {n_events}")
    print(f"  Spread 1 tick after: widen={widen} ({100*widen/max(1,n_events):.1f}%), "
          f"tighten={tighten} ({100*tighten/max(1,n_events):.1f}%), "
          f"same={same} ({100*same/max(1,n_events):.1f}%)")
    print(f"\n  Mid shift after BUY fill (taker bought):")
    for off in sorted(mid_after_buy):
        s = mid_after_buy[off]
        if s: print(f"    +{off}: mean={sum(s)/len(s):+.4f}, n={len(s)}, up={sum(1 for x in s if x>0)}/{len(s)}")
    print(f"\n  Mid shift after SELL fill (taker sold):")
    for off in sorted(mid_after_sell):
        s = mid_after_sell[off]
        if s: print(f"    +{off}: mean={sum(s)/len(s):+.4f}, n={len(s)}, up={sum(1 for x in s if x>0)}/{len(s)}")
    print(f"\n  Quote adjustment after BUY fill:")
    for off in sorted(bid_after_buy):
        b = bid_after_buy[off]; a = ask_after_buy[off]
        if b: print(f"    +{off}: bid={sum(b)/len(b):+.4f}, ask={sum(a)/len(a):+.4f}")
    print(f"\n  Quote adjustment after SELL fill:")
    for off in sorted(bid_after_sell):
        b = bid_after_sell[off]; a = ask_after_sell[off]
        if b: print(f"    +{off}: bid={sum(b)/len(b):+.4f}, ask={sum(a)/len(a):+.4f}")

# ============================================================
# ANALYSIS 3: NARROW SPREAD CAUSES
# ============================================================
def analyze_narrow_spreads(snapshots, trades_by_ts, product):
    snaps = snapshots[product]
    typical = 13.5 if product == "TOMATOES" else 16.0
    thresh = typical * 0.75
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 3: NARROW SPREAD CAUSES — {product} (thresh={thresh:.1f})")
    print(f"{'='*70}")
    events = []
    in_narrow = False; start = 0; min_sp = 999
    for i, s in enumerate(snaps):
        if s.spread < thresh:
            if not in_narrow: start = i; min_sp = s.spread; in_narrow = True
            min_sp = min(min_sp, s.spread)
        else:
            if in_narrow: events.append((start, i-1, min_sp)); in_narrow = False
    if in_narrow: events.append((start, len(snaps)-1, min_sp))
    print(f"  Narrow events: {len(events)}")
    if not events: return
    durs = [e-s+1 for s,e,_ in events]
    print(f"  Duration: mean={sum(durs)/len(durs):.1f}, median={sorted(durs)[len(durs)//2]}, max={max(durs)}")
    pre_moves = []; pre_trades = []
    for si, ei, _ in events:
        if si < 10: continue
        pre_moves.append(abs(snaps[si].mid - snaps[si-10].mid))
        n = sum(len(trades_by_ts.get(snaps[j].timestamp, [])) for j in range(si-10, si))
        pre_trades.append(n)
    if pre_moves:
        print(f"  |Mid move| in 10 ticks before: mean={sum(pre_moves)/len(pre_moves):.2f}")
        print(f"  Trades in 10 ticks before: mean={sum(pre_trades)/len(pre_trades):.1f}")
    spread_hist = defaultdict(int)
    for s in snaps: spread_hist[s.spread] += 1
    print(f"  Spread distribution:")
    for sp in sorted(spread_hist): print(f"    {sp:5.0f}: {spread_hist[sp]:5d} ({100*spread_hist[sp]/len(snaps):.1f}%)")

# ============================================================
# ANALYSIS 4: MICROPRICE LEADS MM MID?
# ============================================================
def analyze_mm_lag(snapshots, product):
    snaps = snapshots[product]
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 4: MICROPRICE vs MM MID LAG — {product}")
    print(f"{'='*70}")
    mp_minus_mid = [s.microprice - s.mid for s in snaps]
    abs_vals = [abs(x) for x in mp_minus_mid]
    print(f"  Microprice - Mid: mean={sum(mp_minus_mid)/len(mp_minus_mid):+.4f}, "
          f"mean_abs={sum(abs_vals)/len(abs_vals):.4f}")
    print(f"\n  Microprice predicts future mid:")
    for h in [1, 2, 3, 5, 10, 20]:
        if len(snaps) <= h: continue
        correct = total = 0; profits = []
        for i in range(len(snaps)-h):
            sig = snaps[i].microprice - snaps[i].mid
            if abs(sig) < 0.1: continue
            fm = snaps[i+h].mid - snaps[i].mid
            if (sig > 0 and fm > 0) or (sig < 0 and fm < 0): correct += 1
            total += 1
            profits.append(fm if sig > 0 else -fm)
        if total > 0:
            print(f"    +{h:2d}: hit={100*correct/total:.1f}%, pnl={sum(profits)/len(profits):+.4f}, n={total}")
    print(f"\n  Return autocorrelation:")
    for lag in [1,2,3,5,10]:
        if len(snaps) <= lag+1: continue
        rn = []; rf = []
        for i in range(1, len(snaps)-lag):
            r = snaps[i].mid - snaps[i-1].mid
            if r != 0:
                rn.append(r); rf.append(snaps[i+lag].mid - snaps[i].mid)
        if len(rn) > 10:
            mn = sum(rn)/len(rn); mf = sum(rf)/len(rf)
            cov = sum((a-mn)*(b-mf) for a,b in zip(rn,rf))/len(rn)
            vn = sum((a-mn)**2 for a in rn)/len(rn); vf = sum((b-mf)**2 for b in rf)/len(rf)
            if vn>0 and vf>0:
                print(f"    lag={lag}: corr={cov/math.sqrt(vn*vf):+.4f}")

# ============================================================
# ANALYSIS 5: CROSS-PRODUCT LEAD-LAG
# ============================================================
def analyze_cross_product(snapshots):
    if "TOMATOES" not in snapshots or "EMERALDS" not in snapshots: return
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 5: CROSS-PRODUCT LEAD-LAG")
    print(f"{'='*70}")
    tom = {s.timestamp: s for s in snapshots["TOMATOES"]}
    em = {s.timestamp: s for s in snapshots["EMERALDS"]}
    cts = sorted(set(tom) & set(em))
    if len(cts) < 100: print("  Not enough common timestamps"); return
    tr = [tom[cts[i]].mid - tom[cts[i-1]].mid for i in range(1, len(cts))]
    er = [em[cts[i]].mid - em[cts[i-1]].mid for i in range(1, len(cts))]
    print(f"  Common timestamps: {len(cts)}")
    print(f"  EMERALDS ret std: {math.sqrt(sum(x**2 for x in er)/len(er)):.4f}")
    for lag in [-5,-3,-1,0,1,3,5]:
        if lag == 0: pairs = list(zip(er, tr))
        elif lag > 0: pairs = list(zip(er[:-lag], tr[lag:]))
        else: pairs = list(zip(er[-lag:], tr[:lag]))
        if len(pairs) < 10: continue
        ea, ta = zip(*pairs)
        me=sum(ea)/len(ea); mt=sum(ta)/len(ta)
        cov=sum((a-me)*(b-mt) for a,b in pairs)/len(pairs)
        ve=sum((a-me)**2 for a in ea)/len(ea); vt=sum((b-mt)**2 for b in ta)/len(ta)
        if ve>0 and vt>0:
            lbl = f"EM[t{lag:+d}]->TOM[t]" if lag != 0 else "EM[t]↔TOM[t]"
            print(f"    {lbl}: corr={cov/math.sqrt(ve*vt):+.4f}")

# ============================================================
# ANALYSIS 6: INTRADAY DRIFT
# ============================================================
def analyze_intraday(snapshots, product):
    snaps = snapshots[product]
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 6: INTRADAY PATTERNS — {product}")
    print(f"{'='*70}")
    segs = defaultdict(list)
    seg_size = snaps[-1].timestamp // 10
    for s in snaps: segs[min(9, s.timestamp // max(1,seg_size))].append(s)
    for seg in range(10):
        if seg not in segs: continue
        ss = segs[seg]
        chg = ss[-1].mid - ss[0].mid
        vol = math.sqrt(sum((ss[i].mid-ss[i-1].mid)**2 for i in range(1,len(ss)))/max(1,len(ss)-1))
        print(f"    Seg {seg}: change={chg:+.1f}, vol={vol:.3f}, n={len(ss)}")
    print(f"  Total drift: {snaps[-1].mid - snaps[0].mid:+.1f}")

# ============================================================
# ANALYSIS 7: BOOK DEPTH
# ============================================================
def analyze_book_depth(snapshots, product):
    snaps = snapshots[product]
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 7: BOOK DEPTH — {product}")
    print(f"{'='*70}")
    bv1 = [s.bid_volumes[0] for s in snaps if s.bid_volumes]
    av1 = [s.ask_volumes[0] for s in snaps if s.ask_volumes]
    print(f"  L1 bid vol: mean={sum(bv1)/len(bv1):.1f}, range=[{min(bv1)},{max(bv1)}]")
    print(f"  L1 ask vol: mean={sum(av1)/len(av1):.1f}, range=[{min(av1)},{max(av1)}]")
    print(f"\n  Volume imbalance predicts mid:")
    for h in [1,2,5]:
        correct=total=0
        for i in range(len(snaps)-h):
            imb = (snaps[i].total_bid_vol - snaps[i].total_ask_vol) / max(1, snaps[i].total_bid_vol + snaps[i].total_ask_vol)
            if abs(imb) < 0.1: continue
            fm = snaps[i+h].mid - snaps[i].mid
            if (imb>0 and fm>0) or (imb<0 and fm<0): correct += 1
            total += 1
        if total>0: print(f"    +{h}: hit={100*correct/total:.1f}%, n={total}")

# ============================================================
# ANALYSIS 8: ORDER-OF-OPERATIONS
# ============================================================
def analyze_order_ops(snapshots, trades_by_ts, product):
    snaps = snapshots[product]
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 8: ORDER-OF-OPERATIONS — {product}")
    print(f"{'='*70}")
    ts_map = {s.timestamp: s for s in snaps}
    curr_match = prev_match = neither = total = 0
    for ts, tlist in sorted(trades_by_ts.items()):
        if ts not in ts_map: continue
        c = ts_map[ts]; prev_ts = ts - 100
        if prev_ts not in ts_map: continue
        p = ts_map[prev_ts]
        for t in tlist:
            total += 1
            at_c = abs(t.price - c.best_bid) < 0.01 or abs(t.price - c.best_ask) < 0.01
            at_p = abs(t.price - p.best_bid) < 0.01 or abs(t.price - p.best_ask) < 0.01
            if at_c: curr_match += 1
            elif at_p: prev_match += 1
            else: neither += 1
    print(f"  Matches CURRENT tick: {curr_match}/{total} ({100*curr_match/max(1,total):.1f}%)")
    print(f"  Matches PREVIOUS tick: {prev_match}/{total} ({100*prev_match/max(1,total):.1f}%)")
    print(f"  Neither: {neither}/{total} ({100*neither/max(1,total):.1f}%)")
    if curr_match > prev_match:
        print(f"  -> MM updates BEFORE trades match (trades see fresh quotes)")
    else:
        print(f"  -> Trades match BEFORE MM updates (trades see stale quotes)")

# ============================================================
# MAIN
# ============================================================
def main():
    for day in DAYS:
        print(f"\n{'#'*70}")
        print(f"#  DAY {day}")
        print(f"{'#'*70}")
        snapshots = load_prices(ROUND, day)
        raw_trades = load_trades(ROUND, day)
        for product in PRODUCTS:
            if product not in snapshots: continue
            print(f"\n  {product}: {len(snapshots[product])} snapshots")
            tbt = defaultdict(list)
            for t in raw_trades.get(product, []): tbt[t.timestamp].append(t)
            print(f"  {product}: {sum(len(v) for v in tbt.values())} trades")
            analyze_quote_updates(snapshots, product)
            analyze_post_fill(snapshots, tbt, product)
            analyze_narrow_spreads(snapshots, tbt, product)
            analyze_mm_lag(snapshots, product)
            analyze_book_depth(snapshots, product)
            analyze_order_ops(snapshots, tbt, product)
        analyze_cross_product(snapshots)
        for product in PRODUCTS:
            if product in snapshots: analyze_intraday(snapshots, product)
    print(f"\n{'#'*70}\n#  DONE\n{'#'*70}")

if __name__ == "__main__":
    main()
