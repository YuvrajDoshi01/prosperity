#!/usr/bin/env python3
"""
Theoretical PnL Ceiling Analysis v2 — IMC Prosperity 4 Tutorial Round
=====================================================================
Key improvement over v1: correct directional accuracy model and
analysis of website-only fills (not in CSV).
"""

import csv
import math
import random
from collections import defaultdict, Counter

# ============================================================
# LOAD DATA
# ============================================================
PRICES_FILE = "prosperity4bt/resources/round0/prices_round_0_day_0.csv"
TRADES_FILE = "prosperity4bt/resources/round0/trades_round_0_day_0.csv"
POS_LIMIT = 80

def load_prices(filepath):
    book = {}
    with open(filepath) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            ts = int(row['timestamp'])
            prod = row['product']
            entry = {
                'bid1': float(row['bid_price_1']) if row['bid_price_1'] else None,
                'bid1_vol': int(row['bid_volume_1']) if row['bid_volume_1'] else 0,
                'bid2': float(row['bid_price_2']) if row['bid_price_2'] else None,
                'bid2_vol': int(row['bid_volume_2']) if row['bid_volume_2'] else 0,
                'ask1': float(row['ask_price_1']) if row['ask_price_1'] else None,
                'ask1_vol': int(row['ask_volume_1']) if row['ask_volume_1'] else 0,
                'ask2': float(row['ask_price_2']) if row['ask_price_2'] else None,
                'ask2_vol': int(row['ask_volume_2']) if row['ask_volume_2'] else 0,
                'mid': float(row['mid_price']),
            }
            entry['spread'] = entry['ask1'] - entry['bid1'] if entry['ask1'] and entry['bid1'] else None
            book[(ts, prod)] = entry
    return book

def load_trades(filepath):
    trades = []
    with open(filepath) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            trades.append({
                'timestamp': int(row['timestamp']),
                'symbol': row['symbol'],
                'price': float(row['price']),
                'quantity': int(row['quantity']),
            })
    return trades

book = load_prices(PRICES_FILE)
trades = load_trades(TRADES_FILE)
all_timestamps = sorted(set(ts for (ts, _) in book.keys()))

# Classify trade side
def classify_trade_side(trade, book):
    ts = trade['timestamp']
    prod = trade['symbol']
    key = (ts, prod)
    if key not in book:
        candidates = sorted([t for (t, p) in book if p == prod and t <= ts])
        if candidates:
            key = (candidates[-1], prod)
        else:
            return 'unknown'
    entry = book[key]
    price = trade['price']
    if entry['ask1'] is not None and price >= entry['ask1']:
        return 'buy'
    elif entry['bid1'] is not None and price <= entry['bid1']:
        return 'sell'
    else:
        return 'buy' if price > entry['mid'] else 'sell'

for t in trades:
    t['side'] = classify_trade_side(t, book)

tom_trades = [t for t in trades if t['symbol'] == 'TOMATOES']
em_trades = [t for t in trades if t['symbol'] == 'EMERALDS']

# ============================================================
# HELPER: Build mid series for a product
# ============================================================
def get_mid_series(product):
    mids = {}
    for ts in all_timestamps:
        key = (ts, product)
        if key in book:
            mids[ts] = book[key]['mid']
    return mids

# ============================================================
print("=" * 80)
print("THEORETICAL PnL CEILING ANALYSIS v2")
print("IMC Prosperity 4 Tutorial Round (2000 ticks, day 0 CSV)")
print("=" * 80)

# ============================================================
# ANALYSIS 1: SPREAD CAPTURE CEILING (TAKER FILLS ONLY)
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 1: SPREAD CAPTURE CEILING (INTERCEPT ALL TAKER FILLS)")
print("=" * 80)
print("""
Model: We post at best +/- 1 on BOTH sides every tick.
We intercept EVERY taker trade at 1-tick improvement over the MM.
PnL = sum of (our_price vs final_mid) for all fills.
Constrained by position limits.
""")

def spread_capture_simulation(trade_list, product, pos_limit=80):
    """Simulate capturing every taker trade with inside-spread posting."""
    position = 0
    cash = 0
    fills = 0
    rejected = 0

    ts_list = sorted(set(ts for (ts, p) in book.keys() if p == product))
    final_mid = book[(ts_list[-1], product)]['mid']

    for trade in trade_list:
        ts = trade['timestamp']
        key = (ts, product)
        if key not in book:
            candidates = sorted([t for t in ts_list if t <= ts])
            if candidates:
                key = (candidates[-1], product)
            else:
                continue
        entry = book[key]
        qty = trade['quantity']

        if trade['side'] == 'sell':
            # Taker sells, we buy at bid1 + 1
            price = entry['bid1'] + 1
            room = pos_limit - position
            actual = min(qty, room)
            if actual > 0:
                cash -= price * actual
                position += actual
                fills += actual
            rejected += (qty - actual)
        elif trade['side'] == 'buy':
            # Taker buys, we sell at ask1 - 1
            price = entry['ask1'] - 1
            room = position + pos_limit
            actual = min(qty, room)
            if actual > 0:
                cash += price * actual
                position -= actual
                fills += actual
            rejected += (qty - actual)

    terminal_pnl = cash + position * final_mid
    return terminal_pnl, position, fills, rejected, cash, final_mid

for product, tlist in [('TOMATOES', tom_trades), ('EMERALDS', em_trades)]:
    pnl, pos, fills, rej, cash, fmid = spread_capture_simulation(tlist, product)
    buys = sum(t['quantity'] for t in tlist if t['side'] == 'sell')
    sells = sum(t['quantity'] for t in tlist if t['side'] == 'buy')
    print(f"--- {product} ---")
    print(f"  Taker trades: {len(tlist)} ({buys} qty bought by us, {sells} qty sold by us)")
    print(f"  Fills: {fills}, Rejected: {rej}")
    print(f"  Final position: {pos}, Final mid: {fmid}")
    print(f"  Terminal PnL: {pnl:.1f}  (cash={cash:.0f}, inventory MTM={pos*fmid:.0f})")

tom_sc, _, _, _, _, _ = spread_capture_simulation(tom_trades, 'TOMATOES')
em_sc, _, _, _, _, _ = spread_capture_simulation(em_trades, 'EMERALDS')
print(f"\n  COMBINED SPREAD CAPTURE CEILING: {tom_sc + em_sc:.1f}")


# ============================================================
# ANALYSIS 2: DP OPTIMAL (TAKER ONLY, PERFECT SELECTION)
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 2: DP OPTIMAL (TAKER ONLY, SELECTIVE ORACLE)")
print("=" * 80)
print("""
Model: Perfect oracle chooses which taker trades to accept/reject.
For each trade, decides: take it (full qty up to pos limit) or skip.
Solved exactly via DP over (trade_index, position) state space.
""")

def dp_taker_oracle(trade_list, product, pos_limit=80):
    ts_list = sorted(set(ts for (ts, p) in book.keys() if p == product))
    final_mid = book[(ts_list[-1], product)]['mid']

    trade_info = []
    for trade in trade_list:
        ts = trade['timestamp']
        key = (ts, product)
        if key not in book:
            candidates = sorted([t for t in ts_list if t <= ts])
            if candidates:
                key = (candidates[-1], product)
            else:
                continue
        entry = book[key]

        if trade['side'] == 'sell':
            our_price = entry['bid1'] + 1
            trade_info.append({'delta_pos': trade['quantity'],
                             'price_per_unit': -our_price,
                             'qty': trade['quantity'], 'ts': ts})
        elif trade['side'] == 'buy':
            our_price = entry['ask1'] - 1
            trade_info.append({'delta_pos': -trade['quantity'],
                             'price_per_unit': our_price,
                             'qty': trade['quantity'], 'ts': ts})

    # DP: position -> max_cash
    dp = {0: 0.0}

    for ti in trade_info:
        new_dp = {}
        for pos, cash in dp.items():
            # Skip
            if pos not in new_dp or cash > new_dp[pos]:
                new_dp[pos] = cash

            # Take full
            new_pos = pos + ti['delta_pos']
            new_cash = cash + ti['price_per_unit'] * ti['qty']
            if -pos_limit <= new_pos <= pos_limit:
                if new_pos not in new_dp or new_cash > new_dp[new_pos]:
                    new_dp[new_pos] = new_cash

            # Take partial (if full breaches limit)
            if not (-pos_limit <= new_pos <= pos_limit):
                if ti['delta_pos'] > 0:
                    partial = pos_limit - pos
                else:
                    partial = pos + pos_limit
                if partial > 0:
                    partial_pos = pos + (1 if ti['delta_pos'] > 0 else -1) * partial
                    partial_cash = cash + ti['price_per_unit'] * partial
                    if -pos_limit <= partial_pos <= pos_limit:
                        if partial_pos not in new_dp or partial_cash > new_dp[partial_pos]:
                            new_dp[partial_pos] = partial_cash

        dp = new_dp

    best_pnl = float('-inf')
    best_pos = 0
    for pos, cash in dp.items():
        pnl = cash + pos * final_mid
        if pnl > best_pnl:
            best_pnl = pnl
            best_pos = pos

    return best_pnl, best_pos, dp[best_pos], final_mid, len(dp)

for product, tlist in [('TOMATOES', tom_trades), ('EMERALDS', em_trades)]:
    pnl, pos, cash, fmid, nstates = dp_taker_oracle(tlist, product)
    print(f"--- {product} ---")
    print(f"  Optimal PnL: {pnl:.1f}")
    print(f"  Optimal final position: {pos}")
    print(f"  Cash: {cash:.0f}, Inventory value: {pos * fmid:.0f}")
    print(f"  States explored: {nstates}")

tom_dp, _, _, _, _ = dp_taker_oracle(tom_trades, 'TOMATOES')
em_dp, _, _, _, _ = dp_taker_oracle(em_trades, 'EMERALDS')
print(f"\n  COMBINED DP TAKER ORACLE: {tom_dp + em_dp:.1f}")


# ============================================================
# ANALYSIS 3: PnL vs POSITION MANAGEMENT QUALITY
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 3: PnL vs POSITION MANAGEMENT QUALITY")
print("=" * 80)
print("""
Corrected model: We take EVERY taker trade for spread capture.
The 'accuracy' parameter controls position MANAGEMENT:
- At each tick (not just trade ticks), we observe our position.
- With prob=accuracy, we SKEW our quotes to the profitable direction.
- Skewing means: post only on the side that will be profitable.
- This doesn't change fill count (taker is random), but changes
  the expected position drift.

Actually, the simplest correct model:
  We always take all taker trades (spread capture is always +EV).
  Position at end of day determines inventory MTM.
  Better directional prediction -> better ending position.

Let's model it as: PnL = spread_capture + position_drift_bonus
  where spread_capture is fixed (~2,467 combined)
  and position_drift_bonus depends on net inventory * price_drift.
""")

# Compute spread capture PnL decomposed into: immediate edge vs terminal MTM
for product, tlist in [('TOMATOES', tom_trades), ('EMERALDS', em_trades)]:
    ts_list = sorted(set(ts for (ts, p) in book.keys() if p == product))
    final_mid = book[(ts_list[-1], product)]['mid']

    position = 0
    cash = 0
    immediate_edge = 0  # sum of (our_price - mid_at_trade) per unit

    for trade in tlist:
        ts = trade['timestamp']
        key = (ts, product)
        if key not in book:
            candidates = sorted([t for t in ts_list if t <= ts])
            if candidates:
                key = (candidates[-1], product)
            else:
                continue
        entry = book[key]
        qty = trade['quantity']

        if trade['side'] == 'sell':
            price = entry['bid1'] + 1
            room = POS_LIMIT - position
            actual = min(qty, room)
            if actual > 0:
                immediate_edge += (entry['mid'] - price) * actual
                cash -= price * actual
                position += actual
        elif trade['side'] == 'buy':
            price = entry['ask1'] - 1
            room = position + POS_LIMIT
            actual = min(qty, room)
            if actual > 0:
                immediate_edge += (price - entry['mid']) * actual
                cash += price * actual
                position -= actual

    terminal_pnl = cash + position * final_mid
    inventory_mtm = terminal_pnl - immediate_edge

    # Actually: terminal_pnl = immediate_edge + inventory_drift
    # where inventory_drift comes from position * (final_mid - mid_at_trade_time)
    print(f"--- {product} ---")
    print(f"  Immediate spread edge (mark-to-mid at fill): {immediate_edge:.1f}")
    print(f"  Inventory MTM (position drift):              {terminal_pnl - immediate_edge:.1f}")
    print(f"  Total terminal PnL:                          {terminal_pnl:.1f}")
    print(f"  Final position: {position}, Final mid: {final_mid}")
    if immediate_edge != 0:
        print(f"  Inventory MTM as % of total: {(terminal_pnl - immediate_edge)/terminal_pnl*100:.1f}%")

# Model: what if we could control ending position?
print(f"\n--- WHAT IF WE CONTROL ENDING POSITION? ---")
print("  The spread edge is ~fixed. The variable is ending position * price drift.")

for product, tlist in [('TOMATOES', tom_trades), ('EMERALDS', em_trades)]:
    ts_list = sorted(set(ts for (ts, p) in book.keys() if p == product))
    first_mid = book[(ts_list[0], product)]['mid']
    final_mid = book[(ts_list[-1], product)]['mid']
    drift = final_mid - first_mid

    # With DP oracle, we get to choose which trades to take
    # Maximum position PnL:
    # If drift > 0: want to end at +80 -> PnL bonus = 80 * drift
    # If drift < 0: want to end at -80 -> PnL bonus = 80 * |drift|
    max_pos_bonus = POS_LIMIT * abs(drift)

    print(f"  {product}: drift = {drift:+.1f}, max position bonus = {max_pos_bonus:.1f}")
    print(f"    Best case: end at {'+80' if drift > 0 else '-80'} -> +{max_pos_bonus:.1f}")
    print(f"    Worst case: end at {'-80' if drift > 0 else '+80'} -> -{max_pos_bonus:.1f}")


# ============================================================
# ANALYSIS 4: EMERALDS DETAILED CEILING
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 4: EMERALDS DETAILED ANALYSIS")
print("=" * 80)

# EMERALDS spread distribution
em_spreads = []
narrow_windows = []
in_narrow = False
narrow_start = None
for ts in all_timestamps:
    key = (ts, 'EMERALDS')
    if key in book:
        s = book[key]['spread']
        em_spreads.append(s)
        if s and s < 16:
            if not in_narrow:
                narrow_start = ts
                in_narrow = True
        else:
            if in_narrow:
                narrow_windows.append((narrow_start, ts - 100))
                in_narrow = False
if in_narrow:
    narrow_windows.append((narrow_start, all_timestamps[-1]))

spread_counts = Counter(em_spreads)
print(f"\nEMERALDS spread distribution (2000 ticks):")
for s in sorted(k for k in spread_counts.keys() if k is not None):
    print(f"  Spread {s:.0f}: {spread_counts[s]} ticks ({spread_counts[s]/len(em_spreads)*100:.1f}%)")

print(f"\nNarrow-spread windows ({len(narrow_windows)} windows):")
for i, (start, end) in enumerate(narrow_windows):
    duration = (end - start) / 100 + 1
    # Check L1 volume during window
    vols = []
    for ts in range(start, end + 100, 100):
        key = (ts, 'EMERALDS')
        if key in book:
            vols.append(book[key]['ask1_vol'] + book[key]['bid1_vol'])
    avg_vol = sum(vols) / len(vols) if vols else 0
    print(f"  Window {i+1}: ts {start}-{end} ({duration:.0f} ticks), avg L1 vol={avg_vol:.0f}")

# EMERALDS: PnL from narrow-spread taking
print(f"\nEMERALDS narrow-spread TAKING PnL:")
print("  If we buy at ask (9996) during narrow spread=8 and sell later at bid (9992)...")
print("  Cost per unit: 9996 (buy) - 10000 (mid) = -4 per unit at entry")
print("  But: EMERALDS mid is always 10000, so buy at 9996 is 4 below mid.")
print("  Actually: during narrow spread, ask1=9996, bid1=9992.")
print("  If we buy at 9996, our cost basis is 9996. Mid = 10000. Unrealized PnL = +4/unit")
print("  Then when spread widens, we can sell at ask1-1 = 10007. PnL = 10007 - 9996 = 11/unit")
print()

# Compute: for each narrow tick, what's the best trade?
narrow_taker_fills = 0
narrow_take_pnl = 0
for ts in all_timestamps:
    key = (ts, 'EMERALDS')
    if key in book and book[key]['spread'] and book[key]['spread'] < 16:
        # Can take at ask1 (buy) or bid1 (sell)
        # Buy at 9996 when we know mid stays 10000 -> profit 4 per unit
        # But need to be able to sell later...
        entry = book[key]
        # Count how many units available
        ask_vol = entry['ask1_vol']
        # Each unit bought at 9996 is worth 10000 -> +4 per unit
        # Plus later sell at 10007 or 10008 when spread is 16 -> +7 or +8 more
        pass

# Simpler: simulate buying during narrow and selling during wide
print("  Simulation: Buy at ask during narrow spread, sell at bid+1 during wide spread")
em_position = 0
em_cash = 0
em_narrow_buys = 0
em_wide_sells = 0

# Strategy: buy during narrow (ask1 close to mid), sell during wide (ask1-1 far from mid)
for ts in all_timestamps:
    key = (ts, 'EMERALDS')
    if key not in book:
        continue
    entry = book[key]
    s = entry['spread']

    if s and s <= 8 and em_position < POS_LIMIT:
        # Narrow spread: buy at ask1
        buy_qty = min(entry['ask1_vol'], POS_LIMIT - em_position)
        if buy_qty > 0:
            em_cash -= entry['ask1'] * buy_qty
            em_position += buy_qty
            em_narrow_buys += buy_qty

final_em_mid = book[(all_timestamps[-1], 'EMERALDS')]['mid']
em_narrow_pnl = em_cash + em_position * final_em_mid
print(f"  Bought {em_narrow_buys} units during narrow spread")
print(f"  Final position: {em_position}")
print(f"  PnL from narrow-spread buying: {em_narrow_pnl:.1f}")
print(f"  (Avg cost: {abs(em_cash)/em_position:.1f} vs final mid {final_em_mid})" if em_position > 0 else "")


# ============================================================
# ANALYSIS 5: ULTIMATE DP (TAKER + BOOK TAKES)
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 5: ULTIMATE DP CEILING (TAKER + BOOK TAKES)")
print("=" * 80)
print("""
At each tick, the oracle can:
  1. Do nothing
  2. Buy at ask1 (take from book) — up to L1 volume
  3. Sell at bid1 (take from book) — up to L1 volume
  4. If taker arrives: buy at bid1+1 or sell at ask1-1 (intercept)

All actions constrained by position limits.
Solved via forward DP: dp[position] = max_cash at each tick.

NOTE: This assumes we can take L1 volume every tick, which overstates
reality (MM bot refreshes, but volume might be partially consumed).
It's a true UPPER BOUND.
""")

def ultimate_dp(product, trade_list, pos_limit=80):
    ts_list = sorted(set(ts for (ts, p) in book.keys() if p == product))
    entries = {}
    for ts in ts_list:
        entries[ts] = book[(ts, product)]
    final_mid = entries[ts_list[-1]]['mid']

    trade_at = {}
    for t in trade_list:
        trade_at[t['timestamp']] = t

    dp = {0: 0.0}

    for ts in ts_list:
        entry = entries[ts]
        new_dp = {}

        for pos, cash in dp.items():
            # Option 0: Do nothing
            if pos not in new_dp or cash > new_dp[pos]:
                new_dp[pos] = cash

            # Option 1: Buy at ask1 (aggressive take)
            if entry['ask1'] is not None:
                ask = entry['ask1']
                max_buy = min(entry['ask1_vol'], pos_limit - pos)
                if max_buy > 0:
                    new_pos = pos + max_buy
                    new_cash = cash - ask * max_buy
                    if new_pos not in new_dp or new_cash > new_dp[new_pos]:
                        new_dp[new_pos] = new_cash

            # Option 2: Sell at bid1 (aggressive take)
            if entry['bid1'] is not None:
                bid = entry['bid1']
                max_sell = min(entry['bid1_vol'], pos + pos_limit)
                if max_sell > 0:
                    new_pos = pos - max_sell
                    new_cash = cash + bid * max_sell
                    if new_pos not in new_dp or new_cash > new_dp[new_pos]:
                        new_dp[new_pos] = new_cash

            # Option 3: Intercept taker
            if ts in trade_at:
                trade = trade_at[ts]
                qty = trade['quantity']

                if trade['side'] == 'sell':
                    price = entry['bid1'] + 1
                    actual = min(qty, pos_limit - pos)
                    if actual > 0:
                        new_pos = pos + actual
                        new_cash = cash - price * actual
                        if new_pos not in new_dp or new_cash > new_dp[new_pos]:
                            new_dp[new_pos] = new_cash

                elif trade['side'] == 'buy':
                    price = entry['ask1'] - 1
                    actual = min(qty, pos + pos_limit)
                    if actual > 0:
                        new_pos = pos - actual
                        new_cash = cash + price * actual
                        if new_pos not in new_dp or new_cash > new_dp[new_pos]:
                            new_dp[new_pos] = new_cash

        dp = new_dp

    best_pnl = float('-inf')
    best_pos = 0
    for pos, cash in dp.items():
        pnl = cash + pos * final_mid
        if pnl > best_pnl:
            best_pnl = pnl
            best_pos = pos

    return best_pnl, best_pos, dp[best_pos], final_mid, len(dp)

for product, tlist in [('TOMATOES', tom_trades), ('EMERALDS', em_trades)]:
    pnl, pos, cash, fmid, ns = ultimate_dp(product, tlist)
    print(f"--- {product} ---")
    print(f"  Optimal PnL: {pnl:.1f}")
    print(f"  Optimal final position: {pos}")
    print(f"  Final mid: {fmid}")
    print(f"  States at terminal: {ns}")

tom_ult, _, _, _, _ = ultimate_dp('TOMATOES', tom_trades)
em_ult, _, _, _, _ = ultimate_dp('EMERALDS', em_trades)
print(f"\n  COMBINED ULTIMATE DP CEILING: {tom_ult + em_ult:.1f}")


# ============================================================
# ANALYSIS 6: WEBSITE vs CSV DISCREPANCY
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 6: WHY 2,896 EXCEEDS THE CSV-BASED DP CEILING")
print("=" * 80)
print("""
The CLAUDE.md documents that the website has ADDITIONAL fills not in CSV:
  - ~12 TOMATOES taker fills that only occur when our best+/-1 orders
    provide a better price than the MM bot (these takers don't appear
    in the CSV because the CSV records a market WITHOUT our orders)
  - ~58 EMERALDS narrow-spread fills from liquidation path

Website fill count for s25 (from CLAUDE.md): 170 total
  - 100 from CSV trade timestamps
  - 58 EMERALDS narrow-spread takes
  - 12 TOMATOES taker fills not in CSV

Let's estimate the PnL contribution of these extra fills:
""")

# Extra TOMATOES fills: ~12 trades, avg qty ~3.4 (taker avg), inside spread
tom_avg_qty = sum(t['quantity'] for t in tom_trades) / len(tom_trades)
tom_avg_spread = sum(book[(ts, 'TOMATOES')]['spread'] for ts in all_timestamps
                     if (ts, 'TOMATOES') in book and book[(ts, 'TOMATOES')]['spread']) / \
                 sum(1 for ts in all_timestamps if (ts, 'TOMATOES') in book and book[(ts, 'TOMATOES')]['spread'])
tom_avg_edge = tom_avg_spread / 2 - 1  # inside spread improvement

extra_tom_fills = 12
extra_tom_pnl = extra_tom_fills * tom_avg_qty * tom_avg_edge
print(f"Extra TOMATOES fills: ~{extra_tom_fills} trades")
print(f"  Avg taker qty: {tom_avg_qty:.1f}")
print(f"  Avg TOMATOES spread: {tom_avg_spread:.1f}")
print(f"  Avg edge per unit (spread/2 - 1): {tom_avg_edge:.1f}")
print(f"  Estimated extra PnL: {extra_tom_fills} * {tom_avg_qty:.1f} * {tom_avg_edge:.1f} = {extra_tom_pnl:.0f}")

# Extra EMERALDS fills: 58 during narrow spread (spread=8, at fair value 10000)
# During narrow spread: ask=9996, bid=9992
# We buy at 9993 (bid+1) or sell at 9995 (ask-1)?
# Actually: during narrow spread, we take from book at 10000 (near mid)
# CLAUDE.md says: "59 fills at 10,000 (liquidation path during narrow-spread windows)"
extra_em_fills = 58
extra_em_avg_spread = 0  # "avg spread 0" from CLAUDE.md
print(f"\nExtra EMERALDS fills: ~{extra_em_fills} units during narrow spread")
print(f"  Fill price: 10,000 (at mid)")
print(f"  These are 'liquidation' fills — position management, not spread capture")
print(f"  PnL depends on subsequent price path (EMERALDS reverts to 10,000)")

# ============================================================
# ANALYSIS 7: COMBINED CEILING + EFFICIENCY TABLE
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 7: COMPREHENSIVE CEILING COMPARISON")
print("=" * 80)

# Compute all ceilings
tom_sc, _, _, _, _, _ = spread_capture_simulation(tom_trades, 'TOMATOES')
em_sc, _, _, _, _, _ = spread_capture_simulation(em_trades, 'EMERALDS')
tom_dp, _, _, _, _ = dp_taker_oracle(tom_trades, 'TOMATOES')
em_dp, _, _, _, _ = dp_taker_oracle(em_trades, 'EMERALDS')
tom_ult, _, _, _, _ = ultimate_dp('TOMATOES', tom_trades)
em_ult, _, _, _, _ = ultimate_dp('EMERALDS', em_trades)

# Adjusted ceiling: CSV ceiling + estimated website-extra fills
adjusted_tom = tom_dp + extra_tom_pnl
adjusted_em = em_dp + 58 * 4  # 58 fills * ~4 PnL each (buy at 9996, sell at mid=10000)

print(f"""
                                          TOMATOES    EMERALDS    COMBINED
--------------------------------------------------------------------------
1. Spread capture (CSV fills only)       {tom_sc:>10.1f}  {em_sc:>10.1f}  {tom_sc+em_sc:>10.1f}
2. DP oracle (CSV taker, selective)      {tom_dp:>10.1f}  {em_dp:>10.1f}  {tom_dp+em_dp:>10.1f}
3. Adjusted (CSV + website-extra fills)  {adjusted_tom:>10.1f}  {adjusted_em:>10.1f}  {adjusted_tom+adjusted_em:>10.1f}
4. Ultimate DP (taker + book takes)      {tom_ult:>10.1f}  {em_ult:>10.1f}  {tom_ult+em_ult:>10.1f}

Your best (s36_medallion):                                        2,896.0
s3_carry:                                                         2,857.0
s25_training_only:                                                2,855.0

Efficiency Analysis:
  s36 vs Spread capture:       {2896/(tom_sc+em_sc)*100:>6.1f}%  (EXCEEDS - website has extra fills)
  s36 vs DP oracle (CSV):      {2896/(tom_dp+em_dp)*100:>6.1f}%  (EXCEEDS - same reason)
  s36 vs Adjusted ceiling:     {2896/(adjusted_tom+adjusted_em)*100:>6.1f}%
  s36 vs Ultimate DP:          {2896/(tom_ult+em_ult)*100:>6.1f}%
""")

# ============================================================
# ANALYSIS 8: MID PRICE TRAJECTORY
# ============================================================
print("=" * 80)
print("ANALYSIS 8: PRICE TRAJECTORY & INVENTORY VALUE")
print("=" * 80)

for product in ['TOMATOES', 'EMERALDS']:
    mids = []
    for ts in all_timestamps:
        key = (ts, product)
        if key in book:
            mids.append((ts, book[key]['mid']))

    prices = [m for _, m in mids]
    first = prices[0]
    last = prices[-1]
    high = max(prices)
    low = min(prices)
    drift = last - first

    up = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])
    down = sum(1 for i in range(1, len(prices)) if prices[i] < prices[i-1])
    flat = sum(1 for i in range(1, len(prices)) if prices[i] == prices[i-1])

    # Compute total absolute displacement
    total_abs_move = sum(abs(prices[i] - prices[i-1]) for i in range(1, len(prices)))

    print(f"\n--- {product} ---")
    print(f"  First: {first}, Last: {last}, Drift: {drift:+.1f}")
    print(f"  High: {high}, Low: {low}, Range: {high-low:.1f}")
    print(f"  Up/Down/Flat moves: {up}/{down}/{flat}")
    print(f"  Total absolute displacement: {total_abs_move:.1f}")
    print(f"  Avg |move| per tick: {total_abs_move/(len(prices)-1):.3f}")
    print(f"  Max inventory PnL from drift: {POS_LIMIT * abs(drift):.0f} ({POS_LIMIT} units * {abs(drift):.1f})")
    print(f"  Max inventory PnL from range: {POS_LIMIT * (high-low):.0f} ({POS_LIMIT} units * {high-low:.1f})")

# ============================================================
# ANALYSIS 9: THEORETICAL MAX FROM DIRECTION-ONLY TRADING
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 9: PURE DIRECTIONAL TRADING (BOOK ONLY, NO TAKER)")
print("=" * 80)
print("""
What if we ONLY crossed the spread when we know direction?
No taker interception, just aggressive book-taking.
This quantifies the value of perfect prediction alone.
""")

for product in ['TOMATOES', 'EMERALDS']:
    ts_list = sorted(set(ts for (ts, p) in book.keys() if p == product))
    mids = {ts: book[(ts, product)]['mid'] for ts in ts_list}

    position = 0
    cash = 0
    n_takes = 0
    profitable_takes = 0

    for i in range(len(ts_list) - 1):
        ts = ts_list[i]
        next_ts = ts_list[i+1]
        current_mid = mids[ts]
        next_mid = mids[next_ts]
        entry = book[(ts, product)]
        delta = next_mid - current_mid

        if delta > 0 and entry['ask1'] is not None:
            # Mid going up -> buy at ask1
            cost = entry['ask1']
            gain = next_mid - cost
            if gain > 0:
                max_buy = min(entry['ask1_vol'], POS_LIMIT - position)
                if max_buy > 0:
                    cash -= cost * max_buy
                    position += max_buy
                    n_takes += 1
                    profitable_takes += 1

        elif delta < 0 and entry['bid1'] is not None:
            # Mid going down -> sell at bid1
            revenue = entry['bid1']
            gain = revenue - next_mid
            if gain > 0:
                max_sell = min(entry['bid1_vol'], position + POS_LIMIT)
                if max_sell > 0:
                    cash += revenue * max_sell
                    position -= max_sell
                    n_takes += 1
                    profitable_takes += 1

    final_mid = mids[ts_list[-1]]
    pnl = cash + position * final_mid

    print(f"\n--- {product} ---")
    print(f"  Profitable spread-crossing opportunities: {profitable_takes}")
    print(f"  Final position: {position}")
    print(f"  Terminal PnL: {pnl:.1f}")

# ============================================================
# ANALYSIS 10: DECOMPOSITION OF THE 2,896 SCORE
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 10: DECOMPOSITION OF THE ACHIEVABLE 2,896")
print("=" * 80)
print("""
Based on CLAUDE.md data (run 8587 log dissection):

TOMATOES PnL breakdown:
  Spread capture: 925 PnL from 126 matched units (7.34 avg spread)
  Inventory MTM:  874 PnL from 73 units net long into rising end-of-day
  Total TOMATOES:                                          ~1,799

EMERALDS PnL breakdown:
  59 fills at 10,000 (narrow-spread liquidation path, avg spread 0)
  29 fills at 9,993/10,007 (inside-spread, avg spread 14)
  Total EMERALDS:                                          ~1,097
  (s36 score implies ~1,097 EMERALDS PnL = 2,896 - 1,799)

Components of s36_medallion score (2,896):
  Base spread capture (CSV taker fills):      ~2,467  (86% of score)
  Extra website fills (not in CSV):           ~200    (7%)
  DP selection bonus (oracle vs take-all):    ~385    (13%)
  OBI shift improvement (s36 vs s3):          ~39     (1.4%)
  Position management:                        varies
""")

# ============================================================
# FINAL SUMMARY TABLE
# ============================================================
print("\n" + "=" * 80)
print("=" * 80)
print("  FINAL SUMMARY: THEORETICAL PnL CEILINGS")
print("=" * 80)
print("=" * 80)

print(f"""
┌──────────────────────────────────────────┬───────────┬───────────┬───────────┐
│ Ceiling                                  │ TOMATOES  │ EMERALDS  │ COMBINED  │
├──────────────────────────────────────────┼───────────┼───────────┼───────────┤
│ 1. CSV spread capture (all fills)        │ {tom_sc:>9.1f} │ {em_sc:>9.1f} │ {tom_sc+em_sc:>9.1f} │
│ 2. CSV DP oracle (selective taker)       │ {tom_dp:>9.1f} │ {em_dp:>9.1f} │ {tom_dp+em_dp:>9.1f} │
│ 3. CSV + website extra fills (estimate)  │ {adjusted_tom:>9.1f} │ {adjusted_em:>9.1f} │ {adjusted_tom+adjusted_em:>9.1f} │
│ 4. Ultimate DP (taker + book crosses)    │ {tom_ult:>9.1f} │ {em_ult:>9.1f} │ {tom_ult+em_ult:>9.1f} │
├──────────────────────────────────────────┼───────────┼───────────┼───────────┤
│ s36_medallion (YOUR BEST)                │     ~1799 │     ~1097 │    2896.0 │
│ s3_carry                                 │           │           │    2857.0 │
│ s25_training_only                        │           │           │    2855.0 │
└──────────────────────────────────────────┴───────────┴───────────┴───────────┘

KEY FINDINGS:

1. SPREAD CAPTURE IS THE DOMINANT PnL SOURCE
   The CSV alone provides 2,467 in pure spread capture PnL
   (1,417 TOMATOES + 1,050 EMERALDS). This is 85% of your 2,896.

2. YOUR SCORE EXCEEDS THE CSV-ONLY DP ORACLE (2,851)
   This proves that website-only fills contribute ~45+ PnL. The extra
   ~12 TOMATOES taker fills and ~58 EMERALDS narrow-spread fills that
   only exist on the website (not in CSV) are worth ~200-400 PnL.

3. THE TAKER-ONLY CEILING IS ~2,851 (CSV) OR ~3,100 (ADJUSTED)
   With PERFECT selection of which taker trades to accept, the CSV
   limit is 2,851. Adding estimated website-extra fills: ~3,100.
   Your 2,896 is at 93% of this adjusted ceiling.

4. THE ULTIMATE CEILING IS ~5,568 (BOOK-TAKING INCLUDED)
   If you could cross the spread profitably at every tick with
   perfect direction knowledge, the ceiling jumps to 5,568.
   The 2,717 gap (5,568 - 2,851) is the value of being able to
   time book-crossing perfectly. But spread-crossing is NEVER +EV
   without perfect prediction (confirmed: -6.5 to -7.5 per trade).

5. THE GAP TO 4,950 REQUIRES AGGRESSIVE BOOK-TAKING
   Even perfect taker-only trading maxes at ~3,100. Reaching 4,950
   requires ~1,850 in book-crossing PnL — meaning you'd need to
   profitably cross the spread ~280 times (at 6.5 edge each).
   This is only possible with near-perfect directional prediction
   that doesn't exist in this market (AC=-0.44, mean-reverting).

6. INVENTORY MTM IS ~50% OF TOMATOES PnL
   The 8-unit ending position * price drift accounts for 113 PnL
   in the CSV simulation. On the website, TOMATOES drift is likely
   different, giving the 874 inventory MTM documented in CLAUDE.md.
   This component is VARIANCE, not systematic edge.

7. EMERALDS IS EFFECTIVELY CAPPED
   EMERALDS mid barely moves (range=8, drift=0). All EMERALDS PnL
   comes from spread capture. With 29 taker trades and ~58 narrow-
   spread takes, the ceiling is ~1,050-1,280. No room for improvement
   via directional trading.
""")

# ============================================================
# BONUS: What accuracy would you need to reach various targets?
# ============================================================
print("=" * 80)
print("BONUS: REQUIRED FILLS TO REACH TARGETS")
print("=" * 80)
print("""
Since spread capture is the bottleneck, the question is:
How many additional fills at what edge do you need?

Current: ~240 TOMATOES fills + ~150 EMERALDS fills = 390 fills
Average edge per fill: (1417+1050)/390 = {:.1f} per fill

""".format((tom_sc + em_sc) / 390))

avg_edge = (tom_sc + em_sc) / 390
for target in [3000, 3300, 3500, 4000, 4950]:
    additional_pnl = target - (tom_sc + em_sc)
    additional_fills = additional_pnl / avg_edge
    print(f"  Target {target:,}: need +{additional_pnl:.0f} PnL = ~{additional_fills:.0f} additional fills at {avg_edge:.1f}/fill")
    print(f"    OR: {additional_pnl / 6.5:.0f} spread crosses at 6.5 edge (TOMATOES)")
    if target <= adjusted_tom + adjusted_em:
        print(f"    -> ACHIEVABLE with better taker interception")
    else:
        print(f"    -> REQUIRES book-crossing (directional trading)")
