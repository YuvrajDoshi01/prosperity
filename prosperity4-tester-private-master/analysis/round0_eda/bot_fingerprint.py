"""
Module 1: Bot Fingerprinting for IMC Prosperity 4 — TOMATOES & EMERALDS
Analyzes historical trade data to identify bot behaviors from trade characteristics.
"""

import csv
import math
from collections import Counter, defaultdict

# ─────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────

def load_trades(path):
    """Load trades CSV (semicolon-delimited)."""
    trades = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            trades.append({
                'timestamp': int(row['timestamp']),
                'buyer': row['buyer'].strip(),
                'seller': row['seller'].strip(),
                'symbol': row['symbol'].strip(),
                'price': float(row['price']),
                'quantity': int(row['quantity']),
            })
    return trades


def load_prices(path):
    """Load prices CSV (semicolon-delimited). Returns dict: (product, timestamp) -> row."""
    prices = {}
    with open(path, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            product = row['product'].strip()
            ts = int(row['timestamp'])
            bid1 = float(row['bid_price_1']) if row['bid_price_1'] else None
            ask1 = float(row['ask_price_1']) if row['ask_price_1'] else None
            mid = float(row['mid_price']) if row['mid_price'] else None
            spread = (ask1 - bid1) if (bid1 is not None and ask1 is not None) else None
            prices[(product, ts)] = {
                'bid1': bid1, 'ask1': ask1, 'mid': mid, 'spread': spread,
                'timestamp': ts, 'product': product,
            }
    return prices


def get_mid_at_timestamp(prices_dict, product, trade_ts):
    """Find mid price at or just before trade timestamp using price snapshots at 100ms intervals."""
    # Price snapshots are at 100ms intervals; find the most recent one <= trade_ts
    snap_ts = (trade_ts // 100) * 100
    for offset in [0, -100, -200, -300]:
        key = (product, snap_ts + offset)
        if key in prices_dict:
            return prices_dict[key]
    return None


# ─────────────────────────────────────────────────────
# STEP 1: Enrich trades with features
# ─────────────────────────────────────────────────────

def enrich_trades(trades, prices_dict, symbol):
    """Filter by symbol, compute inter-trade times, offsets, side, spread."""
    sym_trades = sorted(
        [t for t in trades if t['symbol'] == symbol],
        key=lambda t: t['timestamp']
    )
    enriched = []
    prev_ts = None
    for t in sym_trades:
        ts = t['timestamp']
        delta_t = (ts - prev_ts) if prev_ts is not None else None
        prev_ts = ts

        price_info = get_mid_at_timestamp(prices_dict, symbol, ts)
        mid = price_info['mid'] if price_info else None
        spread = price_info['spread'] if price_info else None
        bid1 = price_info['bid1'] if price_info else None
        ask1 = price_info['ask1'] if price_info else None

        offset = (t['price'] - mid) if mid is not None else None
        # Side: buy-initiated if price >= mid, sell-initiated if < mid
        if mid is not None:
            side = 'BUY' if t['price'] >= mid else 'SELL'
        else:
            side = 'UNKNOWN'

        enriched.append({
            'timestamp': ts,
            'delta_t': delta_t,
            'quantity': t['quantity'],
            'price': t['price'],
            'mid': mid,
            'offset': offset,
            'side': side,
            'spread': spread,
            'bid1': bid1,
            'ask1': ask1,
        })
    return enriched


# ─────────────────────────────────────────────────────
# STEP 2: Inter-trade arrival time analysis
# ─────────────────────────────────────────────────────

def analyze_arrival_times(enriched, label=""):
    """Histogram & mode analysis of delta_t."""
    deltas = [t['delta_t'] for t in enriched if t['delta_t'] is not None]
    if not deltas:
        print(f"  [{label}] No delta_t data.")
        return

    print(f"\n{'='*70}")
    print(f"  INTER-TRADE ARRIVAL TIME ANALYSIS — {label}")
    print(f"{'='*70}")
    print(f"  Total trades: {len(enriched)}, Deltas: {len(deltas)}")
    print(f"  Min delta_t: {min(deltas)} ms")
    print(f"  Max delta_t: {max(deltas)} ms")
    print(f"  Mean delta_t: {sum(deltas)/len(deltas):.1f} ms")
    median_val = sorted(deltas)[len(deltas)//2]
    print(f"  Median delta_t: {median_val} ms")

    # Histogram with bins
    bins = [0, 100, 200, 300, 500, 700, 1000, 1500, 2000, 3000, 5000, 10000, 20000, 50000, 100000, 999999999]
    bin_labels = []
    for i in range(len(bins)-1):
        bin_labels.append(f"{bins[i]:>6}-{bins[i+1]:<6}")
    counts_by_bin = [0] * (len(bins) - 1)
    for d in deltas:
        for i in range(len(bins)-1):
            if bins[i] <= d < bins[i+1]:
                counts_by_bin[i] += 1
                break

    print(f"\n  Delta_t Histogram:")
    for i, (lbl, cnt) in enumerate(zip(bin_labels, counts_by_bin)):
        bar = '#' * min(cnt, 80)
        if cnt > 0:
            print(f"    {lbl} ms: {cnt:>4}  {bar}")

    # Exact value mode analysis
    delta_counter = Counter(deltas)
    print(f"\n  Top 20 exact delta_t values (mode analysis):")
    for val, cnt in delta_counter.most_common(20):
        print(f"    delta_t={val:>6} ms: count={cnt:>3}")

    # Bucketed mode (100ms buckets)
    bucket_counter = Counter((d // 100) * 100 for d in deltas)
    print(f"\n  Top 15 delta_t buckets (100ms resolution):")
    for val, cnt in bucket_counter.most_common(15):
        print(f"    bucket={val:>6} ms: count={cnt:>3}")

    return deltas


# ─────────────────────────────────────────────────────
# STEP 3: Cluster trades by (delta_t, quantity, offset)
# ─────────────────────────────────────────────────────

def cluster_trades(enriched, label=""):
    """Group trades by quantity and delta_t ranges to find clusters."""
    print(f"\n{'='*70}")
    print(f"  TRADE CLUSTERING — {label}")
    print(f"{'='*70}")

    # Group by quantity
    by_qty = defaultdict(list)
    for t in enriched:
        by_qty[t['quantity']].append(t)

    print(f"\n  Trades grouped by QUANTITY:")
    for qty in sorted(by_qty.keys()):
        trades_q = by_qty[qty]
        deltas = [t['delta_t'] for t in trades_q if t['delta_t'] is not None]
        offsets = [t['offset'] for t in trades_q if t['offset'] is not None]
        sides = [t['side'] for t in trades_q]
        side_counter = Counter(sides)

        if deltas:
            mean_dt = sum(deltas) / len(deltas)
            median_dt = sorted(deltas)[len(deltas)//2]
            min_dt = min(deltas)
            max_dt = max(deltas)
        else:
            mean_dt = median_dt = min_dt = max_dt = 0

        if offsets:
            mean_off = sum(offsets) / len(offsets)
            abs_offs = [abs(o) for o in offsets]
            mean_abs_off = sum(abs_offs) / len(abs_offs)
        else:
            mean_off = mean_abs_off = 0

        print(f"\n    Qty={qty}: count={len(trades_q)}, "
              f"delta_t(mean={mean_dt:.0f}, median={median_dt}, min={min_dt}, max={max_dt}), "
              f"offset(mean={mean_off:.1f}, abs_mean={mean_abs_off:.1f}), "
              f"sides={dict(side_counter)}")

        # Show delta_t distribution for this quantity
        if deltas:
            dt_counter = Counter(deltas)
            top5 = dt_counter.most_common(5)
            print(f"      Top delta_t values: {top5}")

    # Joint (quantity, delta_t_bucket) clustering
    print(f"\n  Joint (quantity, delta_t_bucket_1000ms) clusters:")
    joint = Counter()
    for t in enriched:
        if t['delta_t'] is not None:
            dt_bucket = (t['delta_t'] // 1000) * 1000
            joint[(t['quantity'], dt_bucket)] += 1

    for (qty, dt_b), cnt in joint.most_common(30):
        print(f"    (qty={qty}, dt_bucket={dt_b}ms): {cnt}")

    return by_qty


# ─────────────────────────────────────────────────────
# STEP 4: Quantity distribution
# ─────────────────────────────────────────────────────

def analyze_quantities(enriched, label=""):
    """Detailed quantity analysis."""
    print(f"\n{'='*70}")
    print(f"  QUANTITY DISTRIBUTION — {label}")
    print(f"{'='*70}")

    qty_counter = Counter(t['quantity'] for t in enriched)
    total = len(enriched)
    print(f"\n  Quantity distribution:")
    for qty in sorted(qty_counter.keys()):
        cnt = qty_counter[qty]
        pct = 100.0 * cnt / total
        bar = '#' * int(pct)
        print(f"    qty={qty}: count={cnt:>4} ({pct:5.1f}%)  {bar}")

    # Quantity x Side cross-tab
    print(f"\n  Quantity x Side cross-tab:")
    qty_side = defaultdict(Counter)
    for t in enriched:
        qty_side[t['quantity']][t['side']] += 1
    for qty in sorted(qty_side.keys()):
        buys = qty_side[qty].get('BUY', 0)
        sells = qty_side[qty].get('SELL', 0)
        total_qs = buys + sells
        buy_pct = 100.0 * buys / total_qs if total_qs > 0 else 0
        print(f"    qty={qty}: BUY={buys}, SELL={sells}, buy_ratio={buy_pct:.1f}%")


# ─────────────────────────────────────────────────────
# STEP 5: Price offset patterns
# ─────────────────────────────────────────────────────

def analyze_offsets(enriched, label=""):
    """Analyze price offset from mid."""
    print(f"\n{'='*70}")
    print(f"  PRICE OFFSET ANALYSIS — {label}")
    print(f"{'='*70}")

    offsets_data = [(t['offset'], t['side'], t['quantity'], t['delta_t'], t['price'], t['mid'])
                    for t in enriched if t['offset'] is not None]

    # Offset distribution
    offset_counter = Counter(round(o[0], 1) for o in offsets_data)
    print(f"\n  Offset distribution (trade_price - mid_price):")
    for off in sorted(offset_counter.keys()):
        cnt = offset_counter[off]
        bar = '#' * min(cnt, 60)
        print(f"    offset={off:>7.1f}: count={cnt:>3}  {bar}")

    # Group by (side, abs_offset_bucket) and check timing
    print(f"\n  Timing patterns by (side, offset_magnitude):")
    groups = defaultdict(list)
    for t in enriched:
        if t['offset'] is not None:
            abs_off = abs(t['offset'])
            # Bucket: 0-4, 4-8, 8-12, 12-16, 16+
            if abs_off < 4:
                bucket = '0-4'
            elif abs_off < 8:
                bucket = '4-8'
            elif abs_off < 12:
                bucket = '8-12'
            elif abs_off < 16:
                bucket = '12-16'
            else:
                bucket = '16+'
            groups[(t['side'], bucket)].append(t)

    for (side, bucket), trades_g in sorted(groups.items()):
        deltas = [t['delta_t'] for t in trades_g if t['delta_t'] is not None]
        qtys = [t['quantity'] for t in trades_g]
        qty_counter = Counter(qtys)
        if deltas:
            mean_dt = sum(deltas) / len(deltas)
            median_dt = sorted(deltas)[len(deltas)//2]
        else:
            mean_dt = median_dt = 0
        print(f"    ({side}, |offset|={bucket}): n={len(trades_g)}, "
              f"delta_t(mean={mean_dt:.0f}, median={median_dt}), "
              f"qty_dist={dict(qty_counter)}")

    # Specific: trades at bid vs ask vs between
    print(f"\n  Trade location relative to quotes:")
    at_bid = [t for t in enriched if t['bid1'] is not None and t['price'] == t['bid1']]
    at_ask = [t for t in enriched if t['ask1'] is not None and t['price'] == t['ask1']]
    below_bid = [t for t in enriched if t['bid1'] is not None and t['price'] < t['bid1']]
    above_ask = [t for t in enriched if t['ask1'] is not None and t['price'] > t['ask1']]
    between = [t for t in enriched if t['bid1'] is not None and t['ask1'] is not None
               and t['bid1'] < t['price'] < t['ask1']]
    print(f"    At bid:     {len(at_bid)}")
    print(f"    At ask:     {len(at_ask)}")
    print(f"    Below bid:  {len(below_bid)}")
    print(f"    Above ask:  {len(above_ask)}")
    print(f"    Between:    {len(between)}")


# ─────────────────────────────────────────────────────
# STEP 6: Build bot profiles via clustering
# ─────────────────────────────────────────────────────

def build_bot_profiles(enriched, label=""):
    """Attempt to identify distinct bot profiles."""
    print(f"\n{'='*70}")
    print(f"  BOT PROFILE CONSTRUCTION — {label}")
    print(f"{'='*70}")

    # Strategy: cluster by (quantity, side) pairs since buyer/seller is empty
    # Then validate with timing patterns
    profiles = {}

    # First, let's look at consecutive trade patterns (sequences)
    print(f"\n  Consecutive trade sequence analysis:")
    for i in range(1, len(enriched)):
        pass  # We'll do this in the sequence section

    # Cluster by quantity groups
    # Small: 1-2, Medium: 3-4, Large: 5+
    size_groups = {
        'small(1-2)': [t for t in enriched if t['quantity'] <= 2],
        'medium(3-4)': [t for t in enriched if 3 <= t['quantity'] <= 4],
        'large(5+)': [t for t in enriched if t['quantity'] >= 5],
    }

    for group_name, trades_g in size_groups.items():
        if not trades_g:
            continue
        deltas = [t['delta_t'] for t in trades_g if t['delta_t'] is not None]
        offsets = [t['offset'] for t in trades_g if t['offset'] is not None]
        sides = Counter(t['side'] for t in trades_g)
        qtys = Counter(t['quantity'] for t in trades_g)

        if deltas:
            mean_dt = sum(deltas) / len(deltas)
            std_dt = (sum((d - mean_dt)**2 for d in deltas) / len(deltas)) ** 0.5
            median_dt = sorted(deltas)[len(deltas)//2]
        else:
            mean_dt = std_dt = median_dt = 0

        if offsets:
            mean_off = sum(offsets) / len(offsets)
            abs_offs = [abs(o) for o in offsets]
            mean_abs_off = sum(abs_offs) / len(abs_offs)
        else:
            mean_off = mean_abs_off = 0

        buy_count = sides.get('BUY', 0)
        sell_count = sides.get('SELL', 0)
        total_s = buy_count + sell_count
        buy_ratio = buy_count / total_s if total_s > 0 else 0

        # Activity over time: split into 4 quarters
        timestamps = [t['timestamp'] for t in trades_g]
        min_ts = min(timestamps)
        max_ts = max(timestamps)
        range_ts = max_ts - min_ts if max_ts > min_ts else 1
        quarters = [0, 0, 0, 0]
        for ts in timestamps:
            q = min(int((ts - min_ts) / range_ts * 4), 3)
            quarters[q] += 1

        profile = {
            'count': len(trades_g),
            'cadence_ms': round(mean_dt),
            'cadence_std': round(std_dt),
            'cadence_median': median_dt,
            'size_distribution': dict(qtys),
            'typical_offset': round(mean_abs_off, 1),
            'mean_offset': round(mean_off, 1),
            'side_bias': round(buy_ratio, 3),
            'buy_count': buy_count,
            'sell_count': sell_count,
            'activity_quarters': quarters,
        }
        profiles[group_name] = profile

        print(f"\n  Profile: {group_name}")
        for k, v in profile.items():
            print(f"    {k}: {v}")

    # Now try a more refined approach: cluster by (quantity, side) specifically
    print(f"\n  Refined profiles by (quantity, side):")
    refined = defaultdict(list)
    for t in enriched:
        refined[(t['quantity'], t['side'])].append(t)

    for (qty, side), trades_g in sorted(refined.items()):
        if len(trades_g) < 3:
            continue
        deltas = [t['delta_t'] for t in trades_g if t['delta_t'] is not None]
        offsets = [t['offset'] for t in trades_g if t['offset'] is not None]

        if deltas:
            mean_dt = sum(deltas) / len(deltas)
            std_dt = (sum((d - mean_dt)**2 for d in deltas) / len(deltas)) ** 0.5
            median_dt = sorted(deltas)[len(deltas)//2]
        else:
            mean_dt = std_dt = median_dt = 0

        if offsets:
            mean_off = sum(offsets) / len(offsets)
            mean_abs_off = sum(abs(o) for o in offsets) / len(offsets)
            offset_vals = Counter(round(o, 1) for o in offsets)
        else:
            mean_off = mean_abs_off = 0
            offset_vals = Counter()

        print(f"\n    (qty={qty}, side={side}): n={len(trades_g)}")
        print(f"      delta_t: mean={mean_dt:.0f}, std={std_dt:.0f}, median={median_dt}")
        if deltas:
            print(f"      delta_t top values: {Counter(deltas).most_common(5)}")
        print(f"      offset: mean={mean_off:.1f}, abs_mean={mean_abs_off:.1f}")
        print(f"      offset values: {offset_vals.most_common(10)}")

    return profiles


# ─────────────────────────────────────────────────────
# STEP 6b: Advanced sequence-based fingerprinting
# ─────────────────────────────────────────────────────

def sequence_analysis(enriched, label=""):
    """Look at sequences of consecutive trades to identify bot patterns."""
    print(f"\n{'='*70}")
    print(f"  SEQUENCE ANALYSIS — {label}")
    print(f"{'='*70}")

    # Find bursts: groups of trades within 2000ms of each other
    bursts = []
    current_burst = [enriched[0]] if enriched else []
    for i in range(1, len(enriched)):
        if enriched[i]['delta_t'] is not None and enriched[i]['delta_t'] <= 2000:
            current_burst.append(enriched[i])
        else:
            if len(current_burst) >= 1:
                bursts.append(current_burst)
            current_burst = [enriched[i]]
    if current_burst:
        bursts.append(current_burst)

    burst_sizes = Counter(len(b) for b in bursts)
    print(f"\n  Trade bursts (gap <= 2000ms):")
    print(f"    Total bursts: {len(bursts)}")
    print(f"    Burst size distribution: {dict(burst_sizes)}")

    # Analyze bursts of size 2+
    multi_bursts = [b for b in bursts if len(b) >= 2]
    print(f"    Multi-trade bursts: {len(multi_bursts)}")

    for i, burst in enumerate(multi_bursts[:15]):
        details = [(t['timestamp'], t['quantity'], t['side'],
                    f"off={t['offset']:.1f}" if t['offset'] is not None else "off=?",
                    f"dt={t['delta_t']}" if t['delta_t'] is not None else "")
                   for t in burst]
        print(f"    Burst {i}: {details}")

    # Look for repeating patterns in (qty, side) sequences
    print(f"\n  Repeating (qty, side) bigrams:")
    bigrams = []
    for i in range(len(enriched) - 1):
        if enriched[i+1]['delta_t'] is not None and enriched[i+1]['delta_t'] <= 5000:
            bg = ((enriched[i]['quantity'], enriched[i]['side']),
                  (enriched[i+1]['quantity'], enriched[i+1]['side']))
            bigrams.append(bg)
    bigram_counter = Counter(bigrams)
    for bg, cnt in bigram_counter.most_common(15):
        print(f"    {bg}: {cnt}")


# ─────────────────────────────────────────────────────
# STEP 7: Cross-day validation
# ─────────────────────────────────────────────────────

def cross_day_validation(profiles_d1, profiles_d2):
    """Compare profiles across days."""
    print(f"\n{'='*70}")
    print(f"  CROSS-DAY VALIDATION")
    print(f"{'='*70}")

    all_keys = set(profiles_d1.keys()) | set(profiles_d2.keys())
    for key in sorted(all_keys):
        p1 = profiles_d1.get(key)
        p2 = profiles_d2.get(key)
        print(f"\n  Profile: {key}")
        if p1 and p2:
            print(f"    Day -2: count={p1['count']}, cadence={p1['cadence_ms']}ms (std={p1['cadence_std']}), "
                  f"offset={p1['typical_offset']}, buy_ratio={p1['side_bias']}")
            print(f"    Day -1: count={p2['count']}, cadence={p2['cadence_ms']}ms (std={p2['cadence_std']}), "
                  f"offset={p2['typical_offset']}, buy_ratio={p2['side_bias']}")
            # Stability check
            cad_diff = abs(p1['cadence_ms'] - p2['cadence_ms'])
            off_diff = abs(p1['typical_offset'] - p2['typical_offset'])
            bias_diff = abs(p1['side_bias'] - p2['side_bias'])
            print(f"    STABILITY: cadence_diff={cad_diff}ms, offset_diff={off_diff:.1f}, bias_diff={bias_diff:.3f}")
            if cad_diff < 2000 and off_diff < 3 and bias_diff < 0.15:
                print(f"    --> STABLE across days (TRUSTED)")
            else:
                print(f"    --> UNSTABLE across days (check further)")
        elif p1:
            print(f"    Day -2 only: count={p1['count']}")
        elif p2:
            print(f"    Day -1 only: count={p2['count']}")


# ─────────────────────────────────────────────────────
# EMERALDS ANALYSIS (same steps)
# ─────────────────────────────────────────────────────

def run_full_analysis(symbol, trades_d1, prices_d1, trades_d2, prices_d2):
    """Run full fingerprinting for one symbol."""
    print(f"\n{'#'*70}")
    print(f"#  FINGERPRINTING: {symbol}")
    print(f"{'#'*70}")

    enriched_d1 = enrich_trades(trades_d1, prices_d1, symbol)
    enriched_d2 = enrich_trades(trades_d2, prices_d2, symbol)

    print(f"\n  Day -2: {len(enriched_d1)} trades")
    print(f"  Day -1: {len(enriched_d2)} trades")

    # Print first 10 enriched trades for inspection
    print(f"\n  Sample enriched trades (Day -2, first 10):")
    for t in enriched_d1[:10]:
        off_str = f"{t['offset']:.1f}" if t['offset'] is not None else '?'
        print(f"    ts={t['timestamp']:>7}, qty={t['quantity']}, price={t['price']}, "
              f"mid={t['mid']}, off={off_str:>6}, "
              f"side={t['side']}, dt={t['delta_t']}, spread={t['spread']}")

    # Step 2
    analyze_arrival_times(enriched_d1, f"{symbol} Day -2")
    analyze_arrival_times(enriched_d2, f"{symbol} Day -1")

    # Step 3
    cluster_trades(enriched_d1, f"{symbol} Day -2")
    cluster_trades(enriched_d2, f"{symbol} Day -1")

    # Step 4
    analyze_quantities(enriched_d1, f"{symbol} Day -2")
    analyze_quantities(enriched_d2, f"{symbol} Day -1")

    # Step 5
    analyze_offsets(enriched_d1, f"{symbol} Day -2")
    analyze_offsets(enriched_d2, f"{symbol} Day -1")

    # Step 6
    profiles_d1 = build_bot_profiles(enriched_d1, f"{symbol} Day -2")
    profiles_d2 = build_bot_profiles(enriched_d2, f"{symbol} Day -1")

    # Step 6b
    sequence_analysis(enriched_d1, f"{symbol} Day -2")
    sequence_analysis(enriched_d2, f"{symbol} Day -1")

    # Step 7
    cross_day_validation(profiles_d1, profiles_d2)

    return enriched_d1, enriched_d2, profiles_d1, profiles_d2


# ─────────────────────────────────────────────────────
# FINAL: Hardcoded bot profile dict generation
# ─────────────────────────────────────────────────────

def generate_hardcoded_profiles(tom_e1, tom_e2, em_e1, em_e2):
    """Generate the final hardcoded Python dict from the analysis."""
    print(f"\n{'#'*70}")
    print(f"#  FINAL: HARDCODED BOT PROFILES")
    print(f"{'#'*70}")

    # For TOMATOES: compute aggregate stats
    for symbol, e1, e2 in [("TOMATOES", tom_e1, tom_e2), ("EMERALDS", em_e1, em_e2)]:
        all_trades = e1 + e2
        print(f"\n  === {symbol} AGGREGATE STATS ===")
        print(f"  Total trades across both days: {len(all_trades)}")

        # Quantity distribution
        qty_c = Counter(t['quantity'] for t in all_trades)
        print(f"  Quantity distribution: {dict(sorted(qty_c.items()))}")

        # Side distribution
        side_c = Counter(t['side'] for t in all_trades)
        print(f"  Side distribution: {dict(side_c)}")

        # Offset distribution by quantity
        print(f"  Mean |offset| by quantity:")
        for qty in sorted(qty_c.keys()):
            offs = [abs(t['offset']) for t in all_trades if t['quantity'] == qty and t['offset'] is not None]
            if offs:
                print(f"    qty={qty}: mean_abs_offset={sum(offs)/len(offs):.1f}, n={len(offs)}")

        # Timing by quantity
        print(f"  Mean delta_t by quantity:")
        for qty in sorted(qty_c.keys()):
            dts = [t['delta_t'] for t in all_trades if t['quantity'] == qty and t['delta_t'] is not None]
            if dts:
                print(f"    qty={qty}: mean_dt={sum(dts)/len(dts):.0f}, median_dt={sorted(dts)[len(dts)//2]}, n={len(dts)}")

        # Side by quantity
        print(f"  Buy ratio by quantity:")
        for qty in sorted(qty_c.keys()):
            sides = [t['side'] for t in all_trades if t['quantity'] == qty]
            buys = sum(1 for s in sides if s == 'BUY')
            total = len(sides)
            print(f"    qty={qty}: buy_ratio={buys/total:.3f} ({buys}/{total})")

        # Spread analysis
        spreads = [t['spread'] for t in all_trades if t['spread'] is not None]
        if spreads:
            spread_c = Counter(spreads)
            print(f"  Spread distribution: {dict(sorted(spread_c.items()))}")

    # Generate the dict
    print(f"\n\n  ====== HARDCODED PYTHON DICT ======")
    print(f"  (Copy this into your strategy file)\n")

    # We need to compute this from the actual data
    # Let's compute the key parameters for each identified cluster

    for symbol, e1, e2 in [("TOMATOES", tom_e1, tom_e2), ("EMERALDS", em_e1, em_e2)]:
        all_t = e1 + e2
        print(f"\n# {symbol} bot profiles")
        print(f"{symbol}_BOT_PROFILES = {{")

        # Group by quantity
        by_qty = defaultdict(list)
        for t in all_t:
            by_qty[t['quantity']].append(t)

        for qty in sorted(by_qty.keys()):
            trades_q = by_qty[qty]
            deltas = [t['delta_t'] for t in trades_q if t['delta_t'] is not None]
            offsets = [t['offset'] for t in trades_q if t['offset'] is not None]
            sides = Counter(t['side'] for t in trades_q)
            buy_ratio = sides.get('BUY', 0) / len(trades_q)

            mean_dt = sum(deltas) / len(deltas) if deltas else 0
            std_dt = (sum((d - mean_dt)**2 for d in deltas) / len(deltas)) ** 0.5 if deltas else 0
            median_dt = sorted(deltas)[len(deltas)//2] if deltas else 0
            mean_abs_off = sum(abs(o) for o in offsets) / len(offsets) if offsets else 0
            mean_off = sum(offsets) / len(offsets) if offsets else 0

            # Offset for buy vs sell
            buy_offs = [t['offset'] for t in trades_q if t['side'] == 'BUY' and t['offset'] is not None]
            sell_offs = [t['offset'] for t in trades_q if t['side'] == 'SELL' and t['offset'] is not None]
            mean_buy_off = sum(buy_offs) / len(buy_offs) if buy_offs else 0
            mean_sell_off = sum(sell_offs) / len(sell_offs) if sell_offs else 0

            print(f"    {qty}: {{")
            print(f"        'count': {len(trades_q)},")
            print(f"        'cadence_mean_ms': {mean_dt:.0f},")
            print(f"        'cadence_std_ms': {std_dt:.0f},")
            print(f"        'cadence_median_ms': {median_dt},")
            print(f"        'mean_abs_offset': {mean_abs_off:.1f},")
            print(f"        'mean_offset': {mean_off:.1f},")
            print(f"        'mean_buy_offset': {mean_buy_off:.1f},")
            print(f"        'mean_sell_offset': {mean_sell_off:.1f},")
            print(f"        'buy_ratio': {buy_ratio:.3f},")
            print(f"        'buy_count': {sides.get('BUY', 0)},")
            print(f"        'sell_count': {sides.get('SELL', 0)},")
            print(f"    }},")

        print(f"}}")


# ─────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────

if __name__ == '__main__':
    base = 'prosperity4bt/resources/round0'

    print("Loading data...")
    trades_d1 = load_trades(f'{base}/trades_round_0_day_-2.csv')
    trades_d2 = load_trades(f'{base}/trades_round_0_day_-1.csv')
    prices_d1 = load_prices(f'{base}/prices_round_0_day_-2.csv')
    prices_d2 = load_prices(f'{base}/prices_round_0_day_-1.csv')

    print(f"Trades day -2: {len(trades_d1)}")
    print(f"Trades day -1: {len(trades_d2)}")
    print(f"Price snapshots day -2: {len(prices_d1)}")
    print(f"Price snapshots day -1: {len(prices_d2)}")

    # Run for TOMATOES
    tom_e1, tom_e2, tom_p1, tom_p2 = run_full_analysis(
        'TOMATOES', trades_d1, prices_d1, trades_d2, prices_d2)

    # Run for EMERALDS
    em_e1, em_e2, em_p1, em_p2 = run_full_analysis(
        'EMERALDS', trades_d1, prices_d1, trades_d2, prices_d2)

    # Generate final profiles
    generate_hardcoded_profiles(tom_e1, tom_e2, em_e1, em_e2)

    print("\n\nDone. Bot fingerprinting complete.")
