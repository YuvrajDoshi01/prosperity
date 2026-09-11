"""Analyze taker bot timing patterns from backtest log and correlate with book state."""
import json
import math

LOG_PATH = 'backtests/12635.txt'

with open(LOG_PATH) as f:
    data = json.load(f)

activities = data.get('activitiesLog', '')
lines = activities.strip().split('\n')

# Parse ALL ticks for both products
ticks = {}  # (product, ts) -> {bp1, bv1, ap1, av1, ..., mid, pnl}
header = None
for line in lines:
    parts = line.split(';')
    if parts[0] == 'day':
        header = parts
        continue
    if len(parts) < 17:
        continue
    try:
        ts = int(parts[1])
    except ValueError:
        continue

    product = parts[2]
    try:
        tick = {
            'ts': ts, 'product': product,
            'bp1': float(parts[3]) if parts[3] else 0,
            'bv1': float(parts[4]) if parts[4] else 0,
            'bp2': float(parts[5]) if parts[5] else 0,
            'bv2': float(parts[6]) if parts[6] else 0,
            'bp3': float(parts[7]) if parts[7] else 0,
            'bv3': float(parts[8]) if parts[8] else 0,
            'ap1': float(parts[9]) if parts[9] else 0,
            'av1': float(parts[10]) if parts[10] else 0,
            'ap2': float(parts[11]) if parts[11] else 0,
            'av2': float(parts[12]) if parts[12] else 0,
            'ap3': float(parts[13]) if parts[13] else 0,
            'av3': float(parts[14]) if parts[14] else 0,
            'mid': float(parts[15]) if parts[15] else 0,
            'pnl': float(parts[16]) if parts[16] else 0,
        }
        tick['spread'] = tick['ap1'] - tick['bp1'] if tick['ap1'] > 0 and tick['bp1'] > 0 else 0
        ticks[(product, ts)] = tick
    except (ValueError, IndexError):
        continue

# Now read the TRADES CSV to get actual taker bot fills
import csv
trades_path = 'prosperity4bt/resources/round0/trades_round_0_day_0.csv'
trades = []
with open(trades_path) as f:
    reader = csv.DictReader(f, delimiter=';')
    for row in reader:
        if row.get('symbol', row.get('product', '')) == 'TOMATOES':
            trades.append({
                'ts': int(row['timestamp']),
                'price': float(row['price']),
                'qty': int(row['quantity']),
                'buyer': row.get('buyer', ''),
                'seller': row.get('seller', ''),
            })

print(f"TOMATOES trades from CSV: {len(trades)}")
print(f"TOMATOES ticks from log: {sum(1 for k in ticks if k[0] == 'TOMATOES')}")

# Get TOMATOES tick series
tom_ticks = sorted([(ts, t) for (prod, ts), t in ticks.items() if prod == 'TOMATOES'], key=lambda x: x[0])
ts_list = [ts for ts, _ in tom_ticks]

print(f"\n{'='*80}")
print(f"1. TAKER BOT TIMING ANALYSIS")
print(f"{'='*80}")

# Inter-arrival times
if len(trades) >= 2:
    arrivals = [trades[i+1]['ts'] - trades[i]['ts'] for i in range(len(trades)-1)]
    print(f"\nInter-arrival times (ms):")
    print(f"  Mean: {sum(arrivals)/len(arrivals):.0f}")
    print(f"  Median: {sorted(arrivals)[len(arrivals)//2]:.0f}")
    print(f"  Min: {min(arrivals)}, Max: {max(arrivals)}")
    print(f"  Std: {(sum((a - sum(arrivals)/len(arrivals))**2 for a in arrivals)/len(arrivals))**0.5:.0f}")

    # Distribution of inter-arrival times
    buckets = [0, 500, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 7000, 10000, 99999]
    print(f"\n  Inter-arrival distribution:")
    for i in range(len(buckets)-1):
        count = sum(1 for a in arrivals if buckets[i] <= a < buckets[i+1])
        pct = 100 * count / len(arrivals)
        bar = '█' * int(pct/2)
        print(f"    {buckets[i]:>5}-{buckets[i+1]:>5}ms: {count:>3} ({pct:>5.1f}%) {bar}")

# Trade timing within the 100ms tick
print(f"\n  Trade timestamp modulo 100ms (within tick):")
for mod in [100, 200, 400, 500, 1000]:
    within = [t['ts'] % mod for t in trades]
    from collections import Counter
    counts = Counter(within)
    print(f"\n  mod {mod}ms:")
    for k in sorted(counts.keys()):
        pct = 100 * counts[k] / len(trades)
        print(f"    {k:>4}ms: {counts[k]:>3} ({pct:>5.1f}%)")

# Trade side analysis
print(f"\n  Trade sides:")
buys = sum(1 for t in trades if t.get('buyer', '') == '' or 'SUBMISSION' in t.get('buyer', ''))
sells = sum(1 for t in trades if t.get('seller', '') == '' or 'SUBMISSION' in t.get('seller', ''))
print(f"    Buyer=SUBMISSION (we bought): {buys}")
print(f"    Seller=SUBMISSION (we sold): {sells}")

# Price analysis
print(f"\n  Trade prices:")
for t in trades[:10]:
    print(f"    ts={t['ts']:>8}, price={t['price']}, qty={t['qty']}, buyer={t.get('buyer','')}, seller={t.get('seller','')}")

print(f"\n{'='*80}")
print(f"2. TAKER TIMING vs BOOK STATE")
print(f"{'='*80}")

# For each trade, what was the book state at that tick?
for t in trades:
    ts = t['ts']
    tick = ticks.get(('TOMATOES', ts))
    if tick:
        spread = tick['spread']
        # Was the trade at best bid or best ask?
        at_bid = t['price'] == tick['bp1']
        at_ask = t['price'] == tick['ap1']
        t['spread'] = spread
        t['at_bid'] = at_bid
        t['at_ask'] = at_ask
        t['mid'] = tick['mid']
        t['bv1'] = tick['bv1']
        t['av1'] = tick['av1']
        t['bp1'] = tick['bp1']
        t['ap1'] = tick['ap1']

# Trades during narrow vs wide spreads
narrow_trades = [t for t in trades if t.get('spread', 0) <= 9 and t.get('spread', 0) > 0]
wide_trades = [t for t in trades if t.get('spread', 0) > 9]
print(f"\n  Trades during narrow spread (≤9): {len(narrow_trades)}")
print(f"  Trades during wide spread (>9):   {len(wide_trades)}")

if narrow_trades:
    print(f"\n  Narrow spread trades detail:")
    for t in narrow_trades:
        print(f"    ts={t['ts']:>8}, price={t['price']}, spread={t.get('spread',0):.0f}, "
              f"at_bid={t.get('at_bid')}, at_ask={t.get('at_ask')}, "
              f"bp1={t.get('bp1',0):.0f}, ap1={t.get('ap1',0):.0f}")

# Do trades cluster at specific times relative to spread changes?
print(f"\n{'='*80}")
print(f"3. TAKER TIMING vs SPREAD TRANSITIONS")
print(f"{'='*80}")

# Find spread transitions (wide→narrow, narrow→wide)
transitions = []
for i in range(1, len(tom_ticks)):
    ts_prev, t_prev = tom_ticks[i-1]
    ts_curr, t_curr = tom_ticks[i]
    spread_prev = t_prev['spread']
    spread_curr = t_curr['spread']

    if spread_prev > 9 and spread_curr <= 9:
        transitions.append(('wide→narrow', ts_curr, spread_curr))
    elif spread_prev <= 9 and spread_curr > 9:
        transitions.append(('narrow→wide', ts_curr, spread_curr))

print(f"\n  Spread transitions: {len(transitions)}")
for trans_type, ts, spread in transitions[:20]:
    # Find nearest trade
    nearest_trade = min(trades, key=lambda t: abs(t['ts'] - ts)) if trades else None
    trade_dist = abs(nearest_trade['ts'] - ts) if nearest_trade else 9999
    print(f"    {trans_type:15s} at ts={ts:>8} (spread={spread:.0f}), "
          f"nearest trade: ts={nearest_trade['ts']:>8} (dist={trade_dist}ms)")

# Does taker bot arrive MORE often right after narrow spreads?
print(f"\n{'='*80}")
print(f"4. TAKER TIMING RELATIVE TO NARROW SPREADS")
print(f"{'='*80}")

# For each narrow spread tick, how soon does the next trade arrive?
narrow_ticks = [(ts, t) for ts, t in tom_ticks if t['spread'] <= 9 and t['spread'] > 0]
print(f"\n  Narrow spread ticks: {len(narrow_ticks)}")

if narrow_ticks and trades:
    trade_ts_set = sorted(set(t['ts'] for t in trades))

    for ts, t in narrow_ticks:
        # Find next trade after this tick
        next_trades = [tts for tts in trade_ts_set if tts >= ts]
        if next_trades:
            dist = next_trades[0] - ts
            print(f"    Narrow ts={ts:>8} (spread={t['spread']:.0f}), "
                  f"next trade at +{dist}ms (ts={next_trades[0]})")

# Average distance to next trade from narrow vs wide ticks
if trades:
    trade_ts_sorted = sorted(t['ts'] for t in trades)

    def dist_to_next_trade(ts):
        for tts in trade_ts_sorted:
            if tts >= ts:
                return tts - ts
        return 999999

    narrow_dists = [dist_to_next_trade(ts) for ts, t in tom_ticks if t['spread'] <= 9 and t['spread'] > 0]
    wide_dists = [dist_to_next_trade(ts) for ts, t in tom_ticks if t['spread'] > 9]

    if narrow_dists:
        print(f"\n  Avg time to next trade from NARROW tick: {sum(narrow_dists)/len(narrow_dists):.0f}ms")
    if wide_dists:
        print(f"  Avg time to next trade from WIDE tick:   {sum(wide_dists)/len(wide_dists):.0f}ms")

print(f"\n{'='*80}")
print(f"5. TAKER BOT PRICE SELECTION RELATIVE TO OUR QUOTES")
print(f"{'='*80}")

# Check: does the taker bot trade at OUR price or the MM bot's price?
# Our orders are at best±1. MM bot is at best. If trade is at best+1/best-1,
# it's hitting OUR order. If at best, it's hitting the MM bot.
for t in trades:
    tick = ticks.get(('TOMATOES', t['ts']))
    if not tick:
        continue
    # Our bid would be at bp1+1 (if bp1+1 < ap1), our ask at ap1-1 (if ap1-1 > bp1)
    our_bid = tick['bp1'] + 1 if tick['bp1'] + 1 < tick['ap1'] else tick['bp1']
    our_ask = tick['ap1'] - 1 if tick['ap1'] - 1 > tick['bp1'] else tick['ap1']

    if t['price'] == our_bid or t['price'] == our_ask:
        t['hit_us'] = True
    elif t['price'] == tick['bp1'] or t['price'] == tick['ap1']:
        t['hit_mm'] = True
    else:
        t['hit_other'] = True

hit_us = sum(1 for t in trades if t.get('hit_us'))
hit_mm = sum(1 for t in trades if t.get('hit_mm'))
hit_other = sum(1 for t in trades if t.get('hit_other'))
unknown = len(trades) - hit_us - hit_mm - hit_other
print(f"\n  Trades hitting OUR price (best±1): {hit_us} ({100*hit_us/len(trades):.1f}%)")
print(f"  Trades hitting MM price (best):    {hit_mm} ({100*hit_mm/len(trades):.1f}%)")
print(f"  Trades at other prices:            {hit_other} ({100*hit_other/len(trades):.1f}%)")
print(f"  Unclassified:                      {unknown}")

print(f"\n  Detail of trades hitting OUR price:")
for t in trades:
    if t.get('hit_us'):
        tick = ticks.get(('TOMATOES', t['ts']))
        our_bid = tick['bp1'] + 1
        our_ask = tick['ap1'] - 1
        side = "BUY@our_ask" if t['price'] == our_ask else "SELL@our_bid"
        print(f"    ts={t['ts']:>8}, price={t['price']}, qty={t['qty']}, {side}, "
              f"book=[{tick['bp1']:.0f}/{tick['ap1']:.0f}] spread={tick['spread']:.0f}")

print(f"\n  Detail of trades hitting MM price:")
for t in trades:
    if t.get('hit_mm'):
        tick = ticks.get(('TOMATOES', t['ts']))
        side = "BUY@mm_ask" if t['price'] == tick['ap1'] else "SELL@mm_bid"
        print(f"    ts={t['ts']:>8}, price={t['price']}, qty={t['qty']}, {side}, "
              f"book=[{tick['bp1']:.0f}/{tick['ap1']:.0f}] spread={tick['spread']:.0f}")

print(f"\n{'='*80}")
print(f"6. TAKER BOT PERIODICITY (FFT / autocorrelation)")
print(f"{'='*80}")

# Create binary arrival signal: 1 if trade at this tick, 0 otherwise
all_ts = sorted(set(ts for ts, _ in tom_ticks))
trade_ts_counts = {}
for t in trades:
    trade_ts_counts[t['ts']] = trade_ts_counts.get(t['ts'], 0) + 1

arrival = [trade_ts_counts.get(ts, 0) for ts in all_ts]
n = len(arrival)
mean_arr = sum(arrival) / n

# Autocorrelation of arrival signal
print(f"\n  Autocorrelation of taker arrival signal:")
for lag in [1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 40, 50]:
    if lag >= n:
        break
    cov = sum((arrival[i] - mean_arr) * (arrival[i+lag] - mean_arr) for i in range(n - lag)) / (n - lag)
    var = sum((a - mean_arr)**2 for a in arrival) / n
    ac = cov / var if var > 0 else 0
    print(f"    lag={lag:>3}: r={ac:+.4f}")

# Check if there's a pattern in which SECOND of each 1000ms the trade arrives
print(f"\n  Trade timing within each second (mod 1000ms):")
from collections import Counter
within_second = Counter(t['ts'] % 1000 for t in trades)
for ms in sorted(within_second.keys()):
    pct = 100 * within_second[ms] / len(trades)
    bar = '█' * int(pct)
    print(f"    {ms:>4}ms: {within_second[ms]:>3} ({pct:>5.1f}%) {bar}")
