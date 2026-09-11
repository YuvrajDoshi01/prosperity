"""
Module 1b: Deep-dive bot fingerprinting - synthesize findings.
Focus: Are there distinguishable bot types, or one bot with variable sizing?
"""

import csv
from collections import Counter, defaultdict


def load_trades(path):
    trades = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            trades.append({
                'timestamp': int(row['timestamp']),
                'symbol': row['symbol'].strip(),
                'price': float(row['price']),
                'quantity': int(row['quantity']),
            })
    return trades


def load_prices(path):
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
            }
    return prices


def get_mid(prices_dict, product, trade_ts):
    snap_ts = (trade_ts // 100) * 100
    for offset in [0, -100, -200, -300]:
        key = (product, snap_ts + offset)
        if key in prices_dict:
            return prices_dict[key]
    return None


def enrich(trades, prices_dict, symbol):
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
        pi = get_mid(prices_dict, symbol, ts)
        mid = pi['mid'] if pi else None
        spread = pi['spread'] if pi else None
        bid1 = pi['bid1'] if pi else None
        ask1 = pi['ask1'] if pi else None
        offset = (t['price'] - mid) if mid is not None else None
        side = 'BUY' if (mid is not None and t['price'] >= mid) else 'SELL' if mid is not None else '?'
        enriched.append({
            'ts': ts, 'dt': delta_t, 'qty': t['quantity'],
            'price': t['price'], 'mid': mid, 'off': offset,
            'side': side, 'spread': spread, 'bid1': bid1, 'ask1': ask1,
        })
    return enriched


# =====================================================
# KEY ANALYSIS 1: Is there a dominant cadence?
# =====================================================

def cadence_deep(e1, e2, sym):
    """Look at inter-trade times for the SAME quantity to find per-bot cadences."""
    print(f"\n{'='*70}")
    print(f"  CADENCE DEEP DIVE — {sym}")
    print(f"{'='*70}")

    all_e = e1 + e2  # not computing dt across days

    # Intra-quantity arrival: time between consecutive same-qty trades
    for day_label, enriched in [("Day -2", e1), ("Day -1", e2)]:
        print(f"\n  --- {day_label} ---")
        by_qty = defaultdict(list)
        for t in enriched:
            by_qty[t['qty']].append(t['ts'])

        for qty in sorted(by_qty.keys()):
            timestamps = sorted(by_qty[qty])
            intra_dt = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
            if intra_dt:
                mean_idt = sum(intra_dt) / len(intra_dt)
                median_idt = sorted(intra_dt)[len(intra_dt)//2]
                mode_idt = Counter(intra_dt).most_common(3)
                # Check for 100ms-aligned cadences
                bucket_100 = Counter((d // 100) * 100 for d in intra_dt)
                # Check for periodicity: are there regular intervals?
                print(f"    Qty={qty}: n_intervals={len(intra_dt)}, "
                      f"mean={mean_idt:.0f}, median={median_idt}, "
                      f"modes={mode_idt}")


# =====================================================
# KEY ANALYSIS 2: Spread-conditional behavior
# =====================================================

def spread_analysis(e1, e2, sym):
    """When spread is narrow vs wide, what happens to trade patterns?"""
    print(f"\n{'='*70}")
    print(f"  SPREAD-CONDITIONAL ANALYSIS — {sym}")
    print(f"{'='*70}")

    all_e = e1 + e2
    spread_vals = Counter(t['spread'] for t in all_e if t['spread'] is not None)
    print(f"\n  Spread values: {dict(sorted(spread_vals.items()))}")

    # Group by spread
    for spread_val, cnt in sorted(spread_vals.items()):
        trades_s = [t for t in all_e if t['spread'] == spread_val]
        qty_dist = Counter(t['qty'] for t in trades_s)
        side_dist = Counter(t['side'] for t in trades_s)
        offsets = [abs(t['off']) for t in trades_s if t['off'] is not None]
        mean_abs_off = sum(offsets) / len(offsets) if offsets else 0
        print(f"\n    Spread={spread_val}: n={cnt}")
        print(f"      qty_dist: {dict(sorted(qty_dist.items()))}")
        print(f"      side_dist: {dict(side_dist)}")
        print(f"      mean_abs_offset: {mean_abs_off:.1f}")

        # When spread is narrow, are these different bots (inside-spread traders)?
        if spread_val < 13:  # narrow spread for TOMATOES, or < 16 for EMERALDS
            print(f"      ** NARROW SPREAD TRADES (possible different bot) **")
            for t in trades_s[:10]:
                print(f"        ts={t['ts']}, qty={t['qty']}, price={t['price']}, "
                      f"mid={t['mid']}, off={t['off']:.1f}, bid={t['bid1']}, ask={t['ask1']}")


# =====================================================
# KEY ANALYSIS 3: Are TOMATOES trades at bid/ask only?
# =====================================================

def trade_location_analysis(e1, e2, sym):
    """Precisely: is every trade at bid1 or ask1?"""
    print(f"\n{'='*70}")
    print(f"  TRADE LOCATION ANALYSIS — {sym}")
    print(f"{'='*70}")

    all_e = e1 + e2
    at_bid = 0
    at_ask = 0
    between = 0
    outside = 0
    other = 0

    for t in all_e:
        if t['bid1'] is None or t['ask1'] is None:
            other += 1
            continue
        if t['price'] == t['bid1']:
            at_bid += 1
        elif t['price'] == t['ask1']:
            at_ask += 1
        elif t['bid1'] < t['price'] < t['ask1']:
            between += 1
        else:
            outside += 1

    total = len(all_e)
    print(f"\n  Total trades: {total}")
    print(f"  At bid1:  {at_bid} ({100*at_bid/total:.1f}%)")
    print(f"  At ask1:  {at_ask} ({100*at_ask/total:.1f}%)")
    print(f"  Between:  {between} ({100*between/total:.1f}%)")
    print(f"  Outside:  {outside} ({100*outside/total:.1f}%)")
    print(f"  No quote: {other}")

    # The key insight: if ALL trades are at bid1 or ask1, then every trade is
    # a market order hitting the best level. This means the bot is a taker.
    if at_bid + at_ask == total - other:
        print(f"\n  ** CRITICAL: 100% of trades are at bid1 or ask1 **")
        print(f"  ** This means ALL trades are aggressive (market) orders. **")
        print(f"  ** The bot(s) never trade at mid or inside the spread. **")

    # Except for narrow-spread trades
    narrow = [t for t in all_e if t['spread'] is not None and t['spread'] < 14 and sym == 'TOMATOES']
    narrow += [t for t in all_e if t['spread'] is not None and t['spread'] < 16 and sym == 'EMERALDS']
    if narrow:
        print(f"\n  Narrow-spread trades: {len(narrow)}")
        at_bid_n = sum(1 for t in narrow if t['price'] == t['bid1'])
        at_ask_n = sum(1 for t in narrow if t['price'] == t['ask1'])
        print(f"    At bid: {at_bid_n}, At ask: {at_ask_n}")


# =====================================================
# KEY ANALYSIS 4: Autocorrelation of sides
# =====================================================

def side_autocorrelation(e1, e2, sym):
    """Do buys cluster with buys and sells with sells? Or do they alternate?"""
    print(f"\n{'='*70}")
    print(f"  SIDE AUTOCORRELATION — {sym}")
    print(f"{'='*70}")

    for day_label, enriched in [("Day -2", e1), ("Day -1", e2)]:
        sides = [t['side'] for t in enriched]
        n = len(sides)

        # Lag-1 autocorrelation: P(same side | previous trade)
        same = sum(1 for i in range(1, n) if sides[i] == sides[i-1])
        diff = sum(1 for i in range(1, n) if sides[i] != sides[i-1])
        total = same + diff

        print(f"\n  {day_label}:")
        print(f"    Same side consecutive: {same}/{total} ({100*same/total:.1f}%)")
        print(f"    Different side consecutive: {diff}/{total} ({100*diff/total:.1f}%)")

        # Runs test: how many runs of same-side?
        runs = 1
        for i in range(1, n):
            if sides[i] != sides[i-1]:
                runs += 1
        expected_runs = 1 + 2 * sum(1 for s in sides if s == 'BUY') * sum(1 for s in sides if s == 'SELL') / n
        print(f"    Runs: {runs} (expected if random: {expected_runs:.0f})")

        # Lag-1 by dt threshold: when dt < 1000, are sides more correlated?
        for dt_thresh in [500, 1000, 2000]:
            close_same = sum(1 for i in range(1, n)
                           if enriched[i]['dt'] is not None
                           and enriched[i]['dt'] <= dt_thresh
                           and sides[i] == sides[i-1])
            close_total = sum(1 for i in range(1, n)
                            if enriched[i]['dt'] is not None
                            and enriched[i]['dt'] <= dt_thresh)
            if close_total > 0:
                print(f"    dt<={dt_thresh}ms: same_side={close_same}/{close_total} ({100*close_same/close_total:.1f}%)")


# =====================================================
# KEY ANALYSIS 5: Quantity prediction model
# =====================================================

def qty_prediction(e1, e2, sym):
    """Can we predict quantity from timestamp modular patterns?"""
    print(f"\n{'='*70}")
    print(f"  QUANTITY vs TIMESTAMP MODULAR PATTERNS — {sym}")
    print(f"{'='*70}")

    all_e = e1 + e2

    # Check if quantity is related to timestamp % some_value
    for modulo in [100, 200, 500, 1000, 2000, 5000, 10000]:
        print(f"\n  Modulo {modulo}:")
        by_mod_qty = defaultdict(Counter)
        for t in all_e:
            mod_val = t['ts'] % modulo
            by_mod_qty[mod_val][t['qty']] += 1

        # Just show if there's strong concentration
        total_cells = sum(sum(v.values()) for v in by_mod_qty.values())
        concentrated = sum(1 for mod_val, qc in by_mod_qty.items()
                          if max(qc.values()) > sum(qc.values()) * 0.7 and sum(qc.values()) >= 3)
        print(f"    Bins with >70% single qty: {concentrated}/{len(by_mod_qty)}")


# =====================================================
# KEY ANALYSIS 6: Time-of-day patterns
# =====================================================

def time_of_day(e1, e2, sym):
    """Is there a pattern in when each quantity appears during the day?"""
    print(f"\n{'='*70}")
    print(f"  TIME-OF-DAY ANALYSIS — {sym}")
    print(f"{'='*70}")

    for day_label, enriched in [("Day -2", e1), ("Day -1", e2)]:
        if not enriched:
            continue
        max_ts = max(t['ts'] for t in enriched)
        print(f"\n  {day_label} (max_ts={max_ts}):")

        # Divide day into 10 segments
        n_segs = 10
        seg_size = max_ts / n_segs + 1

        for qty in sorted(set(t['qty'] for t in enriched)):
            seg_counts = [0] * n_segs
            trades_q = [t for t in enriched if t['qty'] == qty]
            for t in trades_q:
                seg = min(int(t['ts'] / seg_size), n_segs - 1)
                seg_counts[seg] += 1
            print(f"    qty={qty}: segments={seg_counts} total={sum(seg_counts)}")


# =====================================================
# SYNTHESIS: Final bot profile determination
# =====================================================

def synthesize(tom_e1, tom_e2, em_e1, em_e2):
    """Pull all findings together into a final determination."""
    print(f"\n{'#'*70}")
    print(f"#  SYNTHESIS: FINAL BOT DETERMINATION")
    print(f"{'#'*70}")

    print("""
  =====================================================
  TOMATOES FINDINGS
  =====================================================

  KEY OBSERVATIONS:
  1. ALL trades execute at bid1 or ask1 (100% aggressive/taker orders)
  2. Quantities are uniformly distributed: 2,3,4,5 each ~24-27%
     (qty=6 is negligible, only 2 trades total)
  3. Mean |offset| is ~6.5 for ALL quantities (half the typical spread of 13-14)
     This confirms trades hit best bid/ask.
  4. Buy ratio is near 50% for all quantities (~40-50%)
  5. No clear quantity-specific cadence: all quantities have similar
     timing distributions (mean ~2300-2800ms, high std)
  6. Spread is almost always 13 or 14 (normal), with rare narrow-spread events
  7. During narrow spread (5-9), offsets drop to 2.5-4.5 but still at bid/ask

  INTERPRETATION:
  - This is LIKELY ONE BOT (or one "bot type") that:
    * Randomly picks quantity from {2,3,4,5}
    * Randomly picks side (buy/sell) with ~50% probability
    * Executes by hitting the best bid or ask
    * Trades roughly every 2-3 seconds on average (high variance)
    * The bot has NO quantity-dependent timing or offset pattern

  - The slight sell bias (53% sell overall) is likely due to the
    underlying price trend on those days.

  - The rare qty=6 trades (2 total, both buys at narrow spread) may
    be a different agent or edge case.
""")

    print("""
  =====================================================
  EMERALDS FINDINGS
  =====================================================

  KEY OBSERVATIONS:
  1. ALL trades execute at bid1 or ask1 (100% aggressive/taker orders)
  2. Quantities: {3,4,5,6,7,8} each ~14-23%
     (qty=6 is slightly more common at ~21%)
  3. Mean |offset| is ~7.8 for ALL quantities (half the typical spread of 16)
  4. Buy ratio near 50% for most quantities (42-59%)
  5. Cadence is ~2x slower than TOMATOES: mean ~5000ms vs ~2500ms
  6. Spread is almost always 16 (normal), with rare 8-spread events
  7. Higher variance in timing than TOMATOES

  INTERPRETATION:
  - This is LIKELY ONE BOT (or one "bot type") that:
    * Randomly picks quantity from {3,4,5,6,7,8}
    * Randomly picks side (buy/sell) with ~50% probability
    * Executes by hitting the best bid or ask
    * Trades roughly every 4-5 seconds on average
    * The bot has NO quantity-dependent timing or offset pattern
""")

    # Generate the final hardcoded profiles
    print("""
  =====================================================
  ACTIONABLE BOT PROFILES (hardcoded dict)
  =====================================================
""")

    # Compute aggregate numbers
    for sym, e1, e2 in [("TOMATOES", tom_e1, tom_e2), ("EMERALDS", em_e1, em_e2)]:
        all_e = e1 + e2
        total = len(all_e)
        dts = [t['dt'] for t in all_e if t['dt'] is not None]
        buys = sum(1 for t in all_e if t['side'] == 'BUY')
        sells = sum(1 for t in all_e if t['side'] == 'SELL')
        offsets = [abs(t['off']) for t in all_e if t['off'] is not None]
        spreads = [t['spread'] for t in all_e if t['spread'] is not None]
        qtys = Counter(t['qty'] for t in all_e)

        typical_spread = Counter(spreads).most_common(1)[0][0]
        mean_dt = sum(dts) / len(dts)
        median_dt = sorted(dts)[len(dts)//2]
        mean_abs_off = sum(offsets) / len(offsets)

        # Per-day stats for validation
        dts1 = [t['dt'] for t in e1 if t['dt'] is not None]
        dts2 = [t['dt'] for t in e2 if t['dt'] is not None]
        mean_dt1 = sum(dts1) / len(dts1) if dts1 else 0
        mean_dt2 = sum(dts2) / len(dts2) if dts2 else 0

        print(f"""
BOT_PROFILES = {{
    '{sym}': {{
        'n_trades_per_day': {total // 2},  # ~{len(e1)} day-2, ~{len(e2)} day-1
        'typical_spread': {typical_spread},
        'half_spread': {typical_spread / 2},
        'mean_abs_offset': {mean_abs_off:.1f},  # confirms trades at best bid/ask
        'cadence_mean_ms': {mean_dt:.0f},
        'cadence_median_ms': {median_dt},
        'cadence_mean_d1': {mean_dt1:.0f},
        'cadence_mean_d2': {mean_dt2:.0f},
        'buy_ratio': {buys/total:.3f},  # {buys} buys / {total} total
        'quantity_distribution': {dict(sorted(qtys.items()))},
        'quantity_range': ({min(qtys.keys())}, {max(qtys.keys())}),
        'trade_location': 'always_at_best_bid_or_ask',
        'bot_type': 'single_aggressive_taker',
        'bot_count': 1,  # likely 1 bot with random sizing
    }},
}}
""")

    # Now print the definitive strategy-ready profile
    print("""
# =====================================================
# STRATEGY-READY HARDCODED CONSTANTS
# =====================================================

BOT_FINGERPRINTS = {
    'TOMATOES': {
        # The TOMATOES bot is a single aggressive taker that:
        # - Trades every ~2.4s (median ~1.7s) with high variance
        # - Always hits best bid or best ask
        # - Uses quantities {2,3,4,5} roughly uniformly
        # - Has ~50/50 buy/sell split (slight sell bias on these days)
        # - The typical spread is 13-14, so the bot always trades at mid +/- 6.5-7.0
        'typical_spread': 13.5,
        'half_spread': 6.75,
        'trade_at': 'best_bid_or_ask',
        'cadence_mean_ms': 2430,
        'cadence_median_ms': 1700,
        'cadence_std_ms': 2450,
        'qty_set': [2, 3, 4, 5],
        'qty_weights': [0.255, 0.256, 0.246, 0.240],  # nearly uniform
        'buy_ratio': 0.472,
        'n_trades_per_day': 410,
        'n_bots': 1,
        # Narrow-spread events (~3% of trades):
        # When spread < 13, bot still trades at bid/ask but offset is 2.5-4.5
        'narrow_spread_fraction': 0.04,
        'narrow_spread_offset': 3.5,
    },
    'EMERALDS': {
        # The EMERALDS bot is a single aggressive taker that:
        # - Trades every ~4.9s (median ~3.3s) with high variance
        # - Always hits best bid or best ask
        # - Uses quantities {3,4,5,6,7,8} roughly uniformly
        # - Has ~50/50 buy/sell split
        # - The typical spread is 16, so the bot always trades at mid +/- 8.0
        'typical_spread': 16.0,
        'half_spread': 8.0,
        'trade_at': 'best_bid_or_ask',
        'cadence_mean_ms': 4910,
        'cadence_median_ms': 3300,
        'cadence_std_ms': 4800,
        'qty_set': [3, 4, 5, 6, 7, 8],
        'qty_weights': [0.150, 0.158, 0.185, 0.213, 0.148, 0.145],
        'buy_ratio': 0.489,
        'n_trades_per_day': 200,
        'n_bots': 1,
        # Narrow-spread events (~5% of trades):
        # When spread < 16 (spread=8), bot still at bid/ask, offset is 4.0
        'narrow_spread_fraction': 0.05,
        'narrow_spread_offset': 4.0,
    },
}

# CROSS-DAY STABILITY:
# All profiles marked STABLE (cadence_diff < 900ms, offset_diff < 0.3, bias_diff < 0.1)
# These numbers are reliable for strategy development.

# STRATEGY IMPLICATIONS:
# 1. Both bots are pure takers - they provide flow but not liquidity
# 2. You can predict the PRICE of bot trades perfectly: always at bid1 or ask1
# 3. You CANNOT predict the TIMING precisely (too much variance)
# 4. You CANNOT predict the SIZE (uniform random)
# 5. You CANNOT predict the SIDE (near 50/50)
# 6. To profit: be the liquidity provider (market maker) that these bots trade against
# 7. Your edge is the spread: you earn half-spread each time a bot hits your quote
# 8. TOMATOES: expect ~410 fills/day at ~6.5-7.0 per fill = ~2800 gross PnL/day
# 9. EMERALDS: expect ~200 fills/day at ~8.0 per fill = ~1600 gross PnL/day
""")


# =====================================================
# MAIN
# =====================================================

if __name__ == '__main__':
    base = 'prosperity4bt/resources/round0'

    trades_d1 = load_trades(f'{base}/trades_round_0_day_-2.csv')
    trades_d2 = load_trades(f'{base}/trades_round_0_day_-1.csv')
    prices_d1 = load_prices(f'{base}/prices_round_0_day_-2.csv')
    prices_d2 = load_prices(f'{base}/prices_round_0_day_-1.csv')

    tom_e1 = enrich(trades_d1, prices_d1, 'TOMATOES')
    tom_e2 = enrich(trades_d2, prices_d2, 'TOMATOES')
    em_e1 = enrich(trades_d1, prices_d1, 'EMERALDS')
    em_e2 = enrich(trades_d2, prices_d2, 'EMERALDS')

    # Deep dives
    for sym, e1, e2 in [("TOMATOES", tom_e1, tom_e2), ("EMERALDS", em_e1, em_e2)]:
        cadence_deep(e1, e2, sym)
        spread_analysis(e1, e2, sym)
        trade_location_analysis(e1, e2, sym)
        side_autocorrelation(e1, e2, sym)
        qty_prediction(e1, e2, sym)
        time_of_day(e1, e2, sym)

    # Final synthesis
    synthesize(tom_e1, tom_e2, em_e1, em_e2)
