"""
Deep log-level analysis of raw CSV data for TOMATOES and EMERALDS.
Looking for ANY exploitable patterns at the granular level.
"""
import csv
import os
from collections import Counter, defaultdict
import math

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "prosperity4bt", "resources", "round0")


def load_prices(day):
    path = os.path.join(DATA_DIR, f"prices_round_0_day_{day}.csv")
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows


def load_trades(day):
    path = os.path.join(DATA_DIR, f"trades_round_0_day_{day}.csv")
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows


def analyze_prices(day, product, max_ticks=2000):
    prices = load_prices(day)
    product_rows = [r for r in prices if r['product'] == product]
    if max_ticks:
        product_rows = product_rows[:max_ticks]

    print(f"\n{'='*80}")
    print(f"  PRICES ANALYSIS: {product} day={day} ({len(product_rows)} rows)")
    print(f"{'='*80}")

    # --- L1 prices ---
    bid1_prices = Counter()
    ask1_prices = Counter()
    bid1_vols = []
    ask1_vols = []
    bid2_vols = []
    ask2_vols = []
    spreads = Counter()
    l2_spreads = Counter()  # ask2 - bid2
    bid1_endings = Counter()
    ask1_endings = Counter()
    vol_combos = Counter()
    bid_vol_ratio = []  # L2/L1
    ask_vol_ratio = []
    mids = []
    dmids = []
    prev_mid = None

    # L1+L2 combined analysis
    bid_total_vols = []
    ask_total_vols = []
    bid_asymmetry = []  # bid1_vol != ask1_vol
    level_count_bid = Counter()
    level_count_ask = Counter()

    for r in product_rows:
        b1 = int(r['bid_price_1']) if r['bid_price_1'] else None
        a1 = int(r['ask_price_1']) if r['ask_price_1'] else None
        bv1 = int(r['bid_volume_1']) if r['bid_volume_1'] else 0
        av1 = int(r['ask_volume_1']) if r['ask_volume_1'] else 0
        b2 = int(r['bid_price_2']) if r['bid_price_2'] else None
        a2 = int(r['ask_price_2']) if r['ask_price_2'] else None
        bv2 = int(r['bid_volume_2']) if r['bid_volume_2'] else 0
        av2 = int(r['ask_volume_2']) if r['ask_volume_2'] else 0
        b3 = int(r['bid_price_3']) if r['bid_price_3'] else None
        a3 = int(r['ask_price_3']) if r['ask_price_3'] else None
        bv3 = int(r['bid_volume_3']) if r['bid_volume_3'] else 0
        av3 = int(r['ask_volume_3']) if r['ask_volume_3'] else 0

        mid = float(r['mid_price'])
        mids.append(mid)
        if prev_mid is not None:
            dmids.append(mid - prev_mid)
        prev_mid = mid

        if b1: bid1_prices[b1] += 1
        if a1: ask1_prices[a1] += 1
        bid1_vols.append(bv1)
        ask1_vols.append(av1)
        bid2_vols.append(bv2)
        ask2_vols.append(av2)

        if b1 and a1:
            spd = a1 - b1
            spreads[spd] += 1
            bid1_endings[b1 % 10] += 1
            ask1_endings[a1 % 10] += 1

        if b2 and a2:
            l2spd = a2 - b2
            l2_spreads[l2spd] += 1

        # Volume ratios
        if bv1 > 0 and bv2 > 0:
            bid_vol_ratio.append(bv2 / bv1)
        if av1 > 0 and av2 > 0:
            ask_vol_ratio.append(av2 / av1)

        # Total volumes per side
        btotal = bv1 + bv2 + bv3
        atotal = av1 + av2 + av3
        bid_total_vols.append(btotal)
        ask_total_vols.append(atotal)

        # Asymmetry
        bid_asymmetry.append(bv1 != av1)

        # Level counts
        n_bid = (1 if bv1 else 0) + (1 if bv2 else 0) + (1 if bv3 else 0)
        n_ask = (1 if av1 else 0) + (1 if av2 else 0) + (1 if av3 else 0)
        level_count_bid[n_bid] += 1
        level_count_ask[n_ask] += 1

        # Volume combo (L1 bid vol, L1 ask vol)
        vol_combos[(bv1, av1)] += 1

    # --- Print results ---
    print(f"\n--- L1 SPREAD DISTRIBUTION ---")
    for spd in sorted(spreads):
        pct = spreads[spd] / len(product_rows) * 100
        print(f"  spread={spd:>3}: {spreads[spd]:>5} ({pct:>5.1f}%)")

    print(f"\n--- L2 SPREAD (ask2-bid2) DISTRIBUTION ---")
    for spd in sorted(l2_spreads):
        pct = l2_spreads[spd] / len([x for x in l2_spreads.values()]) * 100
        print(f"  l2_spread={spd:>3}: {l2_spreads[spd]:>5}")

    print(f"\n--- BOOK DEPTH (# levels per side) ---")
    for n in sorted(level_count_bid):
        print(f"  bid levels={n}: {level_count_bid[n]:>5}  |  ask levels={n}: {level_count_ask.get(n,0):>5}")

    print(f"\n--- L1 BID PRICES (top 15) ---")
    for p, c in bid1_prices.most_common(15):
        print(f"  bid1={p}: {c:>5} ({c/len(product_rows)*100:.1f}%)")

    print(f"\n--- L1 ASK PRICES (top 15) ---")
    for p, c in ask1_prices.most_common(15):
        print(f"  ask1={p}: {c:>5} ({c/len(product_rows)*100:.1f}%)")

    print(f"\n--- PRICE DIGIT ENDINGS ---")
    print(f"  Bid1 last digit: {dict(sorted(bid1_endings.items()))}")
    print(f"  Ask1 last digit: {dict(sorted(ask1_endings.items()))}")

    print(f"\n--- VOLUME STATISTICS ---")
    for name, vals in [("L1 bid", bid1_vols), ("L1 ask", ask1_vols),
                        ("L2 bid", bid2_vols), ("L2 ask", ask2_vols)]:
        if vals and any(v > 0 for v in vals):
            nonzero = [v for v in vals if v > 0]
            print(f"  {name}: min={min(nonzero)} max={max(nonzero)} mean={sum(nonzero)/len(nonzero):.1f} "
                  f"median={sorted(nonzero)[len(nonzero)//2]}")

    print(f"\n--- L2/L1 VOLUME RATIO ---")
    if bid_vol_ratio:
        print(f"  Bid L2/L1: mean={sum(bid_vol_ratio)/len(bid_vol_ratio):.3f} "
              f"min={min(bid_vol_ratio):.2f} max={max(bid_vol_ratio):.2f}")
    if ask_vol_ratio:
        print(f"  Ask L2/L1: mean={sum(ask_vol_ratio)/len(ask_vol_ratio):.3f} "
              f"min={min(ask_vol_ratio):.2f} max={max(ask_vol_ratio):.2f}")

    print(f"\n--- L1 VOLUME ASYMMETRY (bid_vol != ask_vol) ---")
    asym_count = sum(1 for a in bid_asymmetry if a)
    print(f"  Asymmetric: {asym_count}/{len(bid_asymmetry)} ({asym_count/len(bid_asymmetry)*100:.1f}%)")

    # Volume distribution (histogram)
    print(f"\n--- L1 BID VOLUME DISTRIBUTION ---")
    vol_hist = Counter(bid1_vols)
    for v in sorted(vol_hist):
        if v > 0:
            bar = '#' * min(50, vol_hist[v])
            print(f"  vol={v:>3}: {vol_hist[v]:>5} {bar}")

    print(f"\n--- L1 ASK VOLUME DISTRIBUTION ---")
    vol_hist = Counter(ask1_vols)
    for v in sorted(vol_hist):
        if v > 0:
            bar = '#' * min(50, vol_hist[v])
            print(f"  vol={v:>3}: {vol_hist[v]:>5} {bar}")

    # Top volume combos
    print(f"\n--- TOP 20 (L1_bid_vol, L1_ask_vol) COMBOS ---")
    for combo, c in vol_combos.most_common(20):
        pct = c / len(product_rows) * 100
        sym = "SYM" if combo[0] == combo[1] else "ASY"
        print(f"  ({combo[0]:>3}, {combo[1]:>3}): {c:>5} ({pct:>4.1f}%) [{sym}]")

    # Mid price analysis
    print(f"\n--- MID PRICE ---")
    print(f"  Range: {min(mids):.1f} - {max(mids):.1f}")
    print(f"  Mean: {sum(mids)/len(mids):.2f}")

    if dmids:
        print(f"\n--- MID CHANGES (dmid) ---")
        dmid_counter = Counter(dmids)
        for d in sorted(dmid_counter):
            if dmid_counter[d] >= 3:
                print(f"  dmid={d:>+6.1f}: {dmid_counter[d]:>5}")

    # Spread → next mid change
    print(f"\n--- SPREAD STATE → NEXT MID CHANGE ---")
    for i in range(len(product_rows) - 1):
        pass  # Computed below

    spd_dmid = defaultdict(list)
    for i in range(min(len(product_rows), len(dmids))):
        r = product_rows[i]
        b1 = int(r['bid_price_1']) if r['bid_price_1'] else None
        a1 = int(r['ask_price_1']) if r['ask_price_1'] else None
        if b1 and a1 and i < len(dmids):
            spd = a1 - b1
            spd_dmid[spd].append(dmids[i])

    for spd in sorted(spd_dmid):
        vals = spd_dmid[spd]
        if len(vals) >= 5:
            mean_dm = sum(vals) / len(vals)
            up = sum(1 for v in vals if v > 0)
            dn = sum(1 for v in vals if v < 0)
            flat = sum(1 for v in vals if v == 0)
            print(f"  spread={spd:>3}: n={len(vals):>5}  mean_dmid={mean_dm:>+6.3f}  "
                  f"up={up} dn={dn} flat={flat}")

    return product_rows


def analyze_trades(day, product):
    trades = load_trades(day)
    product_trades = [t for t in trades if t['symbol'] == product]

    print(f"\n{'='*80}")
    print(f"  TRADES ANALYSIS: {product} day={day} ({len(product_trades)} trades)")
    print(f"{'='*80}")

    if not product_trades:
        print("  No trades found.")
        return

    prices = [float(t['price']) for t in product_trades]
    qtys = [int(t['quantity']) for t in product_trades]
    timestamps = [int(t['timestamp']) for t in product_trades]

    print(f"\n--- TRADE PRICES ---")
    price_counter = Counter(prices)
    for p in sorted(price_counter):
        print(f"  price={p:>8.0f}: {price_counter[p]:>4} trades, "
              f"total_qty={sum(int(t['quantity']) for t in product_trades if float(t['price'])==p)}")

    print(f"\n--- TRADE QUANTITIES ---")
    qty_counter = Counter(qtys)
    for q in sorted(qty_counter):
        print(f"  qty={q:>3}: {qty_counter[q]:>4} trades")

    print(f"\n--- TRADE TIMING ---")
    # Inter-arrival times
    inter_arrivals = []
    for i in range(1, len(timestamps)):
        inter_arrivals.append(timestamps[i] - timestamps[i-1])
    if inter_arrivals:
        print(f"  Inter-arrival: min={min(inter_arrivals)} max={max(inter_arrivals)} "
              f"mean={sum(inter_arrivals)/len(inter_arrivals):.0f} "
              f"median={sorted(inter_arrivals)[len(inter_arrivals)//2]}")

    # Inter-arrival distribution
    ia_hist = Counter()
    for ia in inter_arrivals:
        bucket = (ia // 500) * 500  # 500ms buckets
        ia_hist[bucket] += 1
    print(f"\n  Inter-arrival histogram (500ms buckets):")
    for b in sorted(ia_hist):
        bar = '#' * min(40, ia_hist[b])
        print(f"    {b:>6}-{b+499:>6}ms: {ia_hist[b]:>4} {bar}")

    # Trade at which book level?
    print(f"\n--- TRADE PRICE vs BOOK ---")
    prices_data = load_prices(day)
    product_prices = {int(r['timestamp']): r for r in prices_data if r['product'] == product}

    at_bid1 = 0
    at_ask1 = 0
    at_bid2 = 0
    at_ask2 = 0
    at_other = 0
    buy_trades = 0
    sell_trades = 0

    for t in product_trades:
        ts = int(t['timestamp'])
        tp = float(t['price'])
        # Find closest price tick at or before this trade
        closest_ts = max((k for k in product_prices if k <= ts), default=None)
        if closest_ts is not None:
            book = product_prices[closest_ts]
            b1 = int(book['bid_price_1']) if book['bid_price_1'] else None
            a1 = int(book['ask_price_1']) if book['ask_price_1'] else None
            b2 = int(book['bid_price_2']) if book['bid_price_2'] else None
            a2 = int(book['ask_price_2']) if book['ask_price_2'] else None

            if tp == a1:
                at_ask1 += 1
                buy_trades += 1
            elif tp == b1:
                at_bid1 += 1
                sell_trades += 1
            elif a2 and tp == a2:
                at_ask2 += 1
                buy_trades += 1
            elif b2 and tp == b2:
                at_bid2 += 1
                sell_trades += 1
            else:
                at_other += 1
                # Print oddities
                print(f"  UNUSUAL: t={ts} price={tp} book=({b1}/{a1}) L2=({b2}/{a2})")

    print(f"  At best_ask (L1): {at_ask1} (buys)")
    print(f"  At best_bid (L1): {at_bid1} (sells)")
    print(f"  At L2 ask: {at_ask2}")
    print(f"  At L2 bid: {at_bid2}")
    print(f"  Other: {at_other}")
    print(f"  Buy/Sell ratio: {buy_trades}/{sell_trades}")

    # Price relative to mid
    print(f"\n--- TRADE PRICE vs MID ---")
    above_mid = 0
    below_mid = 0
    for t in product_trades:
        ts = int(t['timestamp'])
        tp = float(t['price'])
        closest_ts = max((k for k in product_prices if k <= ts), default=None)
        if closest_ts is not None:
            mid = float(product_prices[closest_ts]['mid_price'])
            if tp > mid:
                above_mid += 1
            elif tp < mid:
                below_mid += 1
    print(f"  Above mid (buyer-initiated): {above_mid}")
    print(f"  Below mid (seller-initiated): {below_mid}")

    # Sequential patterns
    print(f"\n--- SEQUENTIAL TRADE PATTERNS ---")
    sides = []
    for t in product_trades:
        ts = int(t['timestamp'])
        tp = float(t['price'])
        closest_ts = max((k for k in product_prices if k <= ts), default=None)
        if closest_ts is not None:
            mid = float(product_prices[closest_ts]['mid_price'])
            sides.append('B' if tp > mid else 'S')

    # Autocorrelation of trade direction
    same_dir = 0
    diff_dir = 0
    for i in range(1, len(sides)):
        if sides[i] == sides[i-1]:
            same_dir += 1
        else:
            diff_dir += 1
    if same_dir + diff_dir > 0:
        print(f"  Same direction: {same_dir} ({same_dir/(same_dir+diff_dir)*100:.1f}%)")
        print(f"  Flip direction: {diff_dir} ({diff_dir/(same_dir+diff_dir)*100:.1f}%)")

    # Runs
    runs = []
    current_run = 1
    for i in range(1, len(sides)):
        if sides[i] == sides[i-1]:
            current_run += 1
        else:
            runs.append(current_run)
            current_run = 1
    runs.append(current_run)
    run_counter = Counter(runs)
    print(f"  Run lengths: {dict(sorted(run_counter.items()))}")

    # Quantity → direction
    print(f"\n--- QUANTITY → DIRECTION ---")
    qty_dir = defaultdict(lambda: {'B': 0, 'S': 0})
    for i, t in enumerate(product_trades):
        q = int(t['quantity'])
        if i < len(sides):
            qty_dir[q][sides[i]] += 1
    for q in sorted(qty_dir):
        b = qty_dir[q]['B']
        s = qty_dir[q]['S']
        total = b + s
        pct_b = b / total * 100 if total > 0 else 0
        print(f"  qty={q}: buy={b} sell={s} ({pct_b:.0f}% buy)")


if __name__ == "__main__":
    for day in [0]:  # Day 0 = website-matching data
        for product in ["TOMATOES", "EMERALDS"]:
            analyze_prices(day, product, max_ticks=2000)
            analyze_trades(day, product)
