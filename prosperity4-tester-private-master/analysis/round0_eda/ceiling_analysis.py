#!/usr/bin/env python3
"""
Theoretical PnL Ceiling Analysis for IMC Prosperity 4 Tutorial Round
=====================================================================
Computes upper bounds on achievable PnL given:
- CSV order book data (2000 ticks, day 0)
- CSV trade data (taker bot trades)
- Position limits: 80 for both TOMATOES and EMERALDS
- Inside-spread posting (best +/- 1 tick improvement)
"""

import csv
import math
from collections import defaultdict

# ============================================================
# LOAD DATA
# ============================================================
PRICES_FILE = "prosperity4bt/resources/round0/prices_round_0_day_0.csv"
TRADES_FILE = "prosperity4bt/resources/round0/trades_round_0_day_0.csv"

POS_LIMIT = 80

def load_prices(filepath):
    """Load order book snapshots, keyed by (timestamp, product)."""
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
    """Load taker bot trades."""
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

# Get sorted unique timestamps
all_timestamps = sorted(set(ts for (ts, _) in book.keys()))

# Separate trades by product
tom_trades = [t for t in trades if t['symbol'] == 'TOMATOES']
em_trades = [t for t in trades if t['symbol'] == 'EMERALDS']

# Determine trade side (buy or sell) from price vs book
def classify_trade_side(trade, book):
    """Determine if the taker was buying or selling."""
    ts = trade['timestamp']
    prod = trade['symbol']
    key = (ts, prod)
    if key not in book:
        # Find closest previous timestamp
        candidates = sorted([t for (t, p) in book if p == prod and t <= ts])
        if candidates:
            key = (candidates[-1], prod)
        else:
            return 'unknown'

    entry = book[key]
    price = trade['price']

    if entry['ask1'] is not None and price >= entry['ask1']:
        return 'buy'  # taker is buying (lifting the ask)
    elif entry['bid1'] is not None and price <= entry['bid1']:
        return 'sell'  # taker is selling (hitting the bid)
    else:
        # Trade inside the spread — classify by proximity
        mid = entry['mid']
        if price > mid:
            return 'buy'
        else:
            return 'sell'

for t in trades:
    t['side'] = classify_trade_side(t, book)

print("=" * 80)
print("THEORETICAL PnL CEILING ANALYSIS — IMC Prosperity 4 Tutorial Round")
print("=" * 80)
print(f"\nData: {len(all_timestamps)} ticks, {len(trades)} total trades")
print(f"  TOMATOES: {len(tom_trades)} trades, {sum(t['quantity'] for t in tom_trades)} total qty")
print(f"  EMERALDS: {len(em_trades)} trades, {sum(t['quantity'] for t in em_trades)} total qty")

# ============================================================
# ANALYSIS 1: SPREAD CAPTURE CEILING
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 1: SPREAD CAPTURE CEILING")
print("=" * 80)
print("\nAssumption: We post at best +/- 1 (inside the MM spread).")
print("When taker hits our order, we earn (spread/2 - 1) per unit.")
print("Position limit constrains: can't buy if pos >= 80 or sell if pos <= -80.\n")

def spread_capture_ceiling(trade_list, product, book, pos_limit=80):
    """
    Compute max spread capture assuming:
    - We ALWAYS have an order at best +/- 1 on the correct side
    - We capture EVERY taker trade (get filled on all of them)
    - Position limit constrains us

    For each trade:
      If taker buys (lifts ask), they'd hit OUR ask at ask1 - 1 (we improve by 1 tick)
        Our PnL per unit = (ask1 - 1) - mid  (roughly spread/2 - 1)
        Actually: we SELL at (ask1 - 1), so our "spread capture" is (ask1 - 1 - fair_value)
        But fair_value is debatable. Let's use TWO metrics:
        a) PnL relative to mid: (our_sell_price - mid) per unit
        b) Half-spread capture: our sell is 1 tick inside ask, so improvement = 1 tick
           Net edge = (ask1 - 1) - mid_at_time_of_fill

      If taker sells (hits bid), they'd hit OUR bid at bid1 + 1
        Our PnL per unit = mid - (bid1 + 1) = (mid - bid1 - 1)
    """
    position = 0
    total_pnl = 0
    total_units = 0
    fills = []
    rejected_units = 0

    for trade in trade_list:
        ts = trade['timestamp']
        key = (ts, product)
        if key not in book:
            candidates = sorted([t for (t, p) in book if p == product and t <= ts])
            if candidates:
                key = (candidates[-1], product)
            else:
                continue

        entry = book[key]
        qty = trade['quantity']
        side = trade['side']

        if side == 'buy':
            # Taker is buying -> they lift our ask
            # We sell at ask1 - 1 (inside spread improvement)
            our_price = entry['ask1'] - 1
            # How much can we sell? Limited by position
            max_sell = position + pos_limit  # position - qty >= -pos_limit => qty <= position + pos_limit
            actual_qty = min(qty, max_sell)
            if actual_qty <= 0:
                rejected_units += qty
                continue
            rejected_units += (qty - actual_qty)

            edge_per_unit = our_price - entry['mid']
            pnl = actual_qty * edge_per_unit
            position -= actual_qty
            total_pnl += pnl
            total_units += actual_qty
            fills.append({
                'ts': ts, 'side': 'sell', 'price': our_price, 'qty': actual_qty,
                'mid': entry['mid'], 'spread': entry['spread'], 'edge': edge_per_unit,
                'pos_after': position
            })

        elif side == 'sell':
            # Taker is selling -> they hit our bid
            # We buy at bid1 + 1
            our_price = entry['bid1'] + 1
            max_buy = pos_limit - position  # position + qty <= pos_limit => qty <= pos_limit - position
            actual_qty = min(qty, max_buy)
            if actual_qty <= 0:
                rejected_units += qty
                continue
            rejected_units += (qty - actual_qty)

            edge_per_unit = entry['mid'] - our_price
            pnl = actual_qty * edge_per_unit
            position += actual_qty
            total_pnl += pnl
            total_units += actual_qty
            fills.append({
                'ts': ts, 'side': 'buy', 'price': our_price, 'qty': actual_qty,
                'mid': entry['mid'], 'spread': entry['spread'], 'edge': edge_per_unit,
                'pos_after': position
            })

    # Terminal PnL: mark position to final mid
    final_mid = book[(all_timestamps[-1], product)]['mid'] if (all_timestamps[-1], product) in book else None
    terminal_mtm = 0
    if final_mid and position != 0:
        # Unrealized PnL from inventory
        # We need to compute cost basis
        # Actually, let's compute it properly:
        # Total PnL from spread capture already counted
        # Plus terminal value of position = position * final_mid - cost_of_position
        # But we already have spread_pnl which is sum of (edge * qty)
        # The total realized PnL if we could close at mid would be:
        # spread_pnl + position * final_mid - sum(buy_price * buy_qty) + sum(sell_price * sell_qty)
        # Actually spread_pnl IS the mark-to-mid PnL at time of each trade.
        # Terminal MTM = position * (final_mid - mid_at_last_relevant_trade)?
        # No. Let's think clearly.
        #
        # For each buy at price p, qty q: cash -= p*q, inventory += q
        # For each sell at price p, qty q: cash += p*q, inventory -= q
        # Total PnL = cash + inventory * final_mid
        #
        # We computed edge_per_unit = mid_at_trade - our_buy_price (for buys)
        #                           = our_sell_price - mid_at_trade (for sells)
        # total_pnl = sum(edge * qty) = sum((mid - buy_price) * qty) for buys
        #                              + sum((sell_price - mid) * qty) for sells
        #
        # The TRUE PnL = cash + pos * final_mid
        # = sum(sell_price * qty) - sum(buy_price * qty) + pos * final_mid
        # = sum((sell_price - mid_at_trade) * qty) + sum((mid_at_trade - buy_price) * qty)
        #   + sum(mid_at_trade * qty_sold) - sum(mid_at_trade * qty_bought) + pos * final_mid
        #
        # This is getting complex. Let me just compute cash + position * final_mid directly.
        pass

    # Recompute properly
    position2 = 0
    cash = 0
    for fill in fills:
        if fill['side'] == 'buy':
            cash -= fill['price'] * fill['qty']
            position2 += fill['qty']
        else:
            cash += fill['price'] * fill['qty']
            position2 -= fill['qty']

    assert position2 == position
    terminal_pnl = cash + position * final_mid if final_mid else cash

    return {
        'spread_pnl': total_pnl,  # Mark-to-mid at time of trade
        'total_units': total_units,
        'rejected_units': rejected_units,
        'final_position': position,
        'terminal_pnl': terminal_pnl,  # Mark-to-final-mid
        'cash': cash,
        'final_mid': final_mid,
        'fills': fills,
    }


for product, trade_list in [('TOMATOES', tom_trades), ('EMERALDS', em_trades)]:
    result = spread_capture_ceiling(trade_list, product, book)

    print(f"\n--- {product} ---")
    print(f"Taker trades: {len(trade_list)}")
    buys = [t for t in trade_list if t['side'] == 'buy']
    sells = [t for t in trade_list if t['side'] == 'sell']
    print(f"  Taker buys (we sell): {len(buys)} trades, {sum(t['quantity'] for t in buys)} qty")
    print(f"  Taker sells (we buy): {len(sells)} trades, {sum(t['quantity'] for t in sells)} qty")
    print(f"Total fills: {result['total_units']} units ({result['rejected_units']} rejected by pos limit)")
    print(f"Final position: {result['final_position']}")
    print(f"Spread capture PnL (mark-to-mid at trade time): {result['spread_pnl']:.1f}")
    print(f"Terminal PnL (mark to final mid {result['final_mid']}): {result['terminal_pnl']:.1f}")
    print(f"Cash component: {result['cash']:.1f}")

    # Spread statistics
    spreads = [f['spread'] for f in result['fills'] if f['spread']]
    edges = [f['edge'] for f in result['fills']]
    if spreads:
        print(f"\nSpread at fill times: min={min(spreads):.0f}, max={max(spreads):.0f}, "
              f"mean={sum(spreads)/len(spreads):.1f}")
        print(f"Edge per unit: min={min(edges):.1f}, max={max(edges):.1f}, "
              f"mean={sum(edges)/len(edges):.1f}")

# ============================================================
# ANALYSIS 2: DIRECTIONAL PnL CEILING (PERFECT PREDICTION)
# ============================================================
print("\n\n" + "=" * 80)
print("ANALYSIS 2: DIRECTIONAL PnL CEILING (PERFECT PREDICTION)")
print("=" * 80)
print("\nAssumption: We know mid[t+1] at each tick.")
print("We post ONLY on the profitable side (or both if spread capture > direction cost).")
print("Constrained by: fills only when taker bot trades, and position limits.\n")

def directional_ceiling(trade_list, product, book, all_ts, pos_limit=80):
    """
    Perfect directional prediction + capturing every taker trade.

    At each taker trade, we know the future direction of mid.
    We only take the trade if it's in the profitable direction.
    We post inside spread (best +/- 1) and capture the fill.

    Strategy:
    - If mid is going UP, we want to BUY -> only accept taker sells
    - If mid is going DOWN, we want to SELL -> only accept taker buys
    - If mid is flat, take any trade for spread capture

    Additionally: with perfect prediction, we'd also know WHEN to unwind
    inventory for maximum MTM.
    """
    # Build mid price series for product
    mid_series = {}
    for ts in all_ts:
        key = (ts, product)
        if key in book:
            mid_series[ts] = book[key]['mid']

    ts_list = sorted(mid_series.keys())

    # For each trade, find direction of next mid change
    position = 0
    cash = 0
    fills = []
    rejected_direction = 0
    rejected_position = 0

    for trade in trade_list:
        ts = trade['timestamp']
        side = trade['side']
        qty = trade['quantity']

        # Find book at this timestamp
        key = (ts, product)
        if key not in book:
            candidates = sorted([t for t in ts_list if t <= ts])
            if candidates:
                key = (candidates[-1], product)
            else:
                continue
        entry = book[key]

        # Find future mid (next tick where mid changes, or end of day)
        future_mids = [(t, mid_series[t]) for t in ts_list if t > ts]
        current_mid = entry['mid']

        # Use final mid for terminal value
        final_mid = mid_series[ts_list[-1]]

        # Direction: positive = mid going up
        if future_mids:
            # Look ahead to find the mid a few ticks later
            next_mid = future_mids[0][1]
            direction = next_mid - current_mid
        else:
            direction = 0

        # Determine if we want this trade
        if side == 'sell':
            # Taker sells -> we buy at bid1+1
            our_price = entry['bid1'] + 1
            edge = current_mid - our_price  # immediate spread edge

            # We want to buy if mid is going up (direction > 0) or if spread edge is enough
            want = True  # With perfect prediction, ALWAYS take profitable side

            if direction < 0 and edge + direction < 0:
                # Even spread capture can't offset adverse move
                # But actually, we should think longer term...
                # For ceiling, let's be optimistic and use max future mid
                max_future_mid = max(m for _, m in future_mids) if future_mids else current_mid
                if max_future_mid - our_price <= 0:
                    rejected_direction += qty
                    continue

            max_buy = pos_limit - position
            actual_qty = min(qty, max_buy)
            if actual_qty <= 0:
                rejected_position += qty
                continue
            rejected_position += (qty - actual_qty)

            cash -= our_price * actual_qty
            position += actual_qty
            fills.append({'ts': ts, 'side': 'buy', 'price': our_price, 'qty': actual_qty,
                         'mid': current_mid, 'pos_after': position})

        elif side == 'buy':
            # Taker buys -> we sell at ask1-1
            our_price = entry['ask1'] - 1
            edge = our_price - current_mid

            if direction > 0 and edge - direction < 0:
                min_future_mid = min(m for _, m in future_mids) if future_mids else current_mid
                if our_price - min_future_mid <= 0:
                    rejected_direction += qty
                    continue

            max_sell = position + pos_limit
            actual_qty = min(qty, max_sell)
            if actual_qty <= 0:
                rejected_position += qty
                continue
            rejected_position += (qty - actual_qty)

            cash += our_price * actual_qty
            position -= actual_qty
            fills.append({'ts': ts, 'side': 'sell', 'price': our_price, 'qty': actual_qty,
                         'mid': current_mid, 'pos_after': position})

    final_mid = mid_series[ts_list[-1]]
    terminal_pnl = cash + position * final_mid

    return {
        'terminal_pnl': terminal_pnl,
        'final_position': position,
        'total_fills': sum(f['qty'] for f in fills),
        'rejected_direction': rejected_direction,
        'rejected_position': rejected_position,
        'fills': fills,
        'final_mid': final_mid,
        'cash': cash,
    }


# More sophisticated: perfect oracle that chooses direction AND can reject trades
def perfect_oracle_dp(trade_list, product, book, all_ts, pos_limit=80):
    """
    Dynamic programming approach:
    For each taker trade, decide: TAKE or SKIP.
    If TAKE, we get filled at inside-spread price.
    Terminal value = cash + position * final_mid.

    State: (trade_index, position)
    This is small enough to solve exactly.
    """
    # Get mid at each trade timestamp
    ts_list = sorted(set(ts for (ts, p) in book.keys() if p == product))
    mid_at = {}
    for ts in ts_list:
        mid_at[ts] = book[(ts, product)]['mid']

    final_mid = mid_at[ts_list[-1]]

    # Precompute trade info
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
            # Taker sells -> we buy at bid1+1
            our_price = entry['bid1'] + 1
            delta_pos = trade['quantity']  # we buy
            delta_cash = -our_price * trade['quantity']
        elif trade['side'] == 'buy':
            # Taker buys -> we sell at ask1-1
            our_price = entry['ask1'] - 1
            delta_pos = -trade['quantity']  # we sell
            delta_cash = our_price * trade['quantity']
        else:
            continue

        trade_info.append({
            'delta_pos': delta_pos,
            'delta_cash': delta_cash,
            'qty': trade['quantity'],
            'ts': ts,
        })

    n = len(trade_info)

    # DP: dp[pos] = max cash achievable at this state
    # Position range: [-pos_limit, +pos_limit]
    # After processing all trades, terminal PnL = cash + pos * final_mid

    INF = float('-inf')

    # Current DP table: pos -> max_cash
    dp = {0: 0.0}  # Start at position 0, cash 0

    for i in range(n):
        ti = trade_info[i]
        new_dp = {}

        for pos, cash in dp.items():
            # Option 1: SKIP this trade
            if pos not in new_dp or cash > new_dp[pos]:
                new_dp[pos] = cash

            # Option 2: TAKE this trade (full quantity)
            new_pos = pos + ti['delta_pos']
            if -pos_limit <= new_pos <= pos_limit:
                new_cash = cash + ti['delta_cash']
                if new_pos not in new_dp or new_cash > new_dp[new_pos]:
                    new_dp[new_pos] = new_cash

            # Option 3: TAKE partial (if full quantity would breach limit)
            if not (-pos_limit <= new_pos <= pos_limit):
                if ti['delta_pos'] > 0:
                    # Buying: max we can buy = pos_limit - pos
                    partial = pos_limit - pos
                else:
                    # Selling: max we can sell = pos + pos_limit
                    partial = pos + pos_limit

                if partial > 0:
                    fraction = partial / ti['qty']
                    partial_cash = ti['delta_cash'] * fraction
                    partial_pos = pos + (ti['delta_pos'] // abs(ti['delta_pos'])) * partial

                    if -pos_limit <= partial_pos <= pos_limit:
                        new_cash2 = cash + partial_cash
                        if partial_pos not in new_dp or new_cash2 > new_dp[partial_pos]:
                            new_dp[partial_pos] = new_cash2

        dp = new_dp

    # Find best terminal PnL
    best_pnl = INF
    best_pos = 0
    for pos, cash in dp.items():
        pnl = cash + pos * final_mid
        if pnl > best_pnl:
            best_pnl = pnl
            best_pos = pos

    return {
        'optimal_pnl': best_pnl,
        'optimal_final_pos': best_pos,
        'optimal_cash': dp[best_pos],
        'final_mid': final_mid,
        'n_trades': n,
        'n_states': len(dp),
    }


# Run both analyses
for product, trade_list in [('TOMATOES', tom_trades), ('EMERALDS', em_trades)]:
    print(f"\n--- {product} (Greedy Perfect Direction) ---")
    result = directional_ceiling(trade_list, product, book, all_timestamps)
    print(f"Total fills: {result['total_fills']}")
    print(f"Rejected (direction): {result['rejected_direction']}")
    print(f"Rejected (position): {result['rejected_position']}")
    print(f"Final position: {result['final_position']}")
    print(f"Terminal PnL: {result['terminal_pnl']:.1f}")

    print(f"\n--- {product} (DP Optimal — exact solution) ---")
    dp_result = perfect_oracle_dp(trade_list, product, book, all_timestamps)
    print(f"Optimal PnL: {dp_result['optimal_pnl']:.1f}")
    print(f"Optimal final position: {dp_result['optimal_final_pos']}")
    print(f"Final mid: {dp_result['final_mid']}")
    print(f"States explored: {dp_result['n_states']}")


# ============================================================
# ANALYSIS 3: PnL vs DIRECTIONAL ACCURACY
# ============================================================
print("\n\n" + "=" * 80)
print("ANALYSIS 3: PnL vs DIRECTIONAL ACCURACY")
print("=" * 80)
print("\nModel: At each taker trade, we predict direction of next mid move.")
print("With probability p, we're correct (take profitable side only).")
print("With probability (1-p), we're wrong (take the losing side).")
print("At 50%, we take every trade regardless (no directional info).\n")

def expected_pnl_at_accuracy(tom_trades_data, em_trades_data, product_book, all_ts, accuracy):
    """
    For a given directional accuracy, compute expected PnL.

    This is an approximation:
    - With prob=accuracy, we take the RIGHT side of the trade
    - With prob=(1-accuracy), we take the WRONG side
    - At 50%, we take all trades (both sides, no filter)

    More precisely: at each taker event, we must decide whether to be on
    the trade or not. The taker randomly buys or sells.

    Model:
    - Taker arrives with random side (buy/sell)
    - If we predict direction correctly:
      - If taker side aligns with our desired side, we get a fill at inside-spread
      - If taker side opposes our desired side, we DON'T get filled (no counterparty)
    - If we predict direction incorrectly:
      - Same logic but mirrored

    Actually, let's think about this differently. The taker's side is RANDOM.
    Our strategy: at each tick we choose whether to post bid, ask, or both.

    With perfect accuracy: post only the profitable side.
      - Fill when taker side matches our posted side
      - Expected fill rate = 50% of trades (taker is 50/50)

    With 50% accuracy: post both sides (or randomly pick).
      - Fill on every trade at inside spread
      - But half the fills are directionally wrong

    So the tradeoff: higher accuracy -> fewer fills but better direction.
    At 50% (no info), fill all trades, spread capture only.
    At 100% (perfect), fill ~50% of trades, spread + direction capture.

    Let me compute this properly.
    """
    total_pnl = 0

    for product, trade_list in [('TOMATOES', tom_trades_data), ('EMERALDS', em_trades_data)]:
        ts_list = sorted(set(ts for (ts, p) in product_book.keys() if p == product))
        mid_at = {}
        for ts in ts_list:
            if (ts, product) in product_book:
                mid_at[ts] = product_book[(ts, product)]['mid']

        final_mid = mid_at[ts_list[-1]]

        # For each trade, compute:
        # 1. spread_edge: PnL from just capturing the spread (agnostic to direction)
        # 2. directional_edge: additional PnL from being on the right side

        position_sim_spread = 0
        cash_spread_only = 0  # 50% accuracy: take all trades

        for trade in trade_list:
            ts = trade['timestamp']
            key = (ts, product)
            if key not in product_book:
                candidates = sorted([t for t in ts_list if t <= ts])
                if candidates:
                    key = (candidates[-1], product)
                else:
                    continue
            entry = product_book[key]
            qty = trade['quantity']
            side = trade['side']

            if side == 'sell':
                our_price = entry['bid1'] + 1
                max_buy = POS_LIMIT - position_sim_spread
                actual = min(qty, max_buy)
                if actual > 0:
                    cash_spread_only -= our_price * actual
                    position_sim_spread += actual
            elif side == 'buy':
                our_price = entry['ask1'] - 1
                max_sell = position_sim_spread + POS_LIMIT
                actual = min(qty, max_sell)
                if actual > 0:
                    cash_spread_only += our_price * actual
                    position_sim_spread -= actual

        pnl_all = cash_spread_only + position_sim_spread * final_mid
        total_pnl += pnl_all

    return total_pnl


# First, compute the EXACT spread-only PnL (all trades, both products)
print("Computing PnL at different directional accuracy levels...")
print("(Using Monte Carlo simulation with 1000 trials for stochastic accuracies)\n")

import random
random.seed(42)

def simulate_accuracy(product, trade_list, product_book, all_ts, accuracy, n_trials=1000):
    """
    Monte Carlo simulation of trading with given directional accuracy.

    Strategy: For each taker trade:
    1. Observe taker side (buy/sell)
    2. We predict direction with given accuracy
    3. If our prediction says "go with this trade" (direction aligns), we take it
    4. If prediction says "oppose this trade", we skip it

    More precisely:
    - If taker sells, we'd buy. Good if mid going up.
    - If taker buys, we'd sell. Good if mid going down.
    - "Correct prediction" = we correctly identify whether the trade is directionally good
    """
    ts_list = sorted(set(ts for (ts, p) in product_book.keys() if p == product))
    mid_at = {}
    for ts in ts_list:
        if (ts, product) in product_book:
            mid_at[ts] = product_book[(ts, product)]['mid']
    final_mid = mid_at[ts_list[-1]]

    # Precompute trade details
    trade_details = []
    for trade in trade_list:
        ts = trade['timestamp']
        key = (ts, product)
        if key not in product_book:
            candidates = sorted([t for t in ts_list if t <= ts])
            if candidates:
                key = (candidates[-1], product)
            else:
                continue
        entry = product_book[key]

        # Find next mid
        future_ts = [t for t in ts_list if t > ts]
        if future_ts:
            next_mid = mid_at[future_ts[0]]
        else:
            next_mid = mid_at[ts]

        direction = next_mid - entry['mid']

        if trade['side'] == 'sell':
            our_price = entry['bid1'] + 1
            is_good = direction >= 0  # buying is good if mid going up or flat (spread capture)
            pos_delta = trade['quantity']
            cash_delta = -our_price * trade['quantity']
        elif trade['side'] == 'buy':
            our_price = entry['ask1'] - 1
            is_good = direction <= 0  # selling is good if mid going down or flat
            pos_delta = -trade['quantity']
            cash_delta = our_price * trade['quantity']
        else:
            continue

        trade_details.append({
            'is_good': is_good,
            'pos_delta': pos_delta,
            'cash_delta': cash_delta,
            'qty': trade['quantity'],
        })

    # Special cases
    if accuracy >= 1.0:
        # Perfect: take only good trades
        pos = 0
        cash = 0
        for td in trade_details:
            if td['is_good']:
                new_pos = pos + td['pos_delta']
                if -POS_LIMIT <= new_pos <= POS_LIMIT:
                    pos = new_pos
                    cash += td['cash_delta']
                else:
                    # Partial fill
                    if td['pos_delta'] > 0:
                        partial = POS_LIMIT - pos
                    else:
                        partial = pos + POS_LIMIT
                    if partial > 0:
                        frac = partial / td['qty']
                        cash += td['cash_delta'] * frac
                        pos += (1 if td['pos_delta'] > 0 else -1) * partial
        return cash + pos * final_mid

    if accuracy <= 0.5:
        # No info: take all trades
        pos = 0
        cash = 0
        for td in trade_details:
            new_pos = pos + td['pos_delta']
            if -POS_LIMIT <= new_pos <= POS_LIMIT:
                pos = new_pos
                cash += td['cash_delta']
            else:
                if td['pos_delta'] > 0:
                    partial = POS_LIMIT - pos
                else:
                    partial = pos + POS_LIMIT
                if partial > 0:
                    frac = partial / td['qty']
                    cash += td['cash_delta'] * frac
                    pos += (1 if td['pos_delta'] > 0 else -1) * partial
        return cash + pos * final_mid

    # Stochastic: run Monte Carlo
    pnls = []
    for _ in range(n_trials):
        pos = 0
        cash = 0
        for td in trade_details:
            # With prob=accuracy, we correctly identify if trade is good/bad
            # If we think it's good, we take it; if bad, we skip
            correct = random.random() < accuracy
            if correct:
                take = td['is_good']
            else:
                take = not td['is_good']

            if take:
                new_pos = pos + td['pos_delta']
                if -POS_LIMIT <= new_pos <= POS_LIMIT:
                    pos = new_pos
                    cash += td['cash_delta']
                else:
                    if td['pos_delta'] > 0:
                        partial = POS_LIMIT - pos
                    else:
                        partial = pos + POS_LIMIT
                    if partial > 0:
                        frac = partial / td['qty']
                        cash += td['cash_delta'] * frac
                        pos += (1 if td['pos_delta'] > 0 else -1) * partial

        pnls.append(cash + pos * final_mid)

    return sum(pnls) / len(pnls)


accuracies = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00]

print(f"{'Accuracy':>10} {'TOMATOES':>12} {'EMERALDS':>12} {'COMBINED':>12}")
print("-" * 50)

combined_results = {}
for acc in accuracies:
    tom_pnl = simulate_accuracy('TOMATOES', tom_trades, book, all_timestamps, acc)
    em_pnl = simulate_accuracy('EMERALDS', em_trades, book, all_timestamps, acc)
    combined = tom_pnl + em_pnl
    combined_results[acc] = combined
    print(f"{acc:>10.0%} {tom_pnl:>12.1f} {em_pnl:>12.1f} {combined:>12.1f}")


# ============================================================
# ANALYSIS 4: EMERALDS CEILING (DETAILED)
# ============================================================
print("\n\n" + "=" * 80)
print("ANALYSIS 4: EMERALDS DETAILED CEILING")
print("=" * 80)

# EMERALDS specifics
print(f"\nEMERALDS taker trades: {len(em_trades)}")
em_buys = [t for t in em_trades if t['side'] == 'buy']
em_sells = [t for t in em_trades if t['side'] == 'sell']
print(f"  Taker buys (we sell): {len(em_buys)}, qty={sum(t['quantity'] for t in em_buys)}")
print(f"  Taker sells (we buy): {len(em_sells)}, qty={sum(t['quantity'] for t in em_sells)}")

# EMERALDS spread analysis
em_spreads = []
for ts in all_timestamps:
    key = (ts, 'EMERALDS')
    if key in book:
        em_spreads.append(book[key]['spread'])

from collections import Counter
spread_counts = Counter(em_spreads)
print(f"\nEMERALDS spread distribution:")
for s in sorted(spread_counts.keys()):
    print(f"  Spread {s:.0f}: {spread_counts[s]} ticks ({spread_counts[s]/len(em_spreads)*100:.1f}%)")

# For EMERALDS: also compute ceiling from narrow-spread windows
narrow_ticks = [(ts, book[(ts, 'EMERALDS')]) for ts in all_timestamps
                if (ts, 'EMERALDS') in book and book[(ts, 'EMERALDS')]['spread'] and book[(ts, 'EMERALDS')]['spread'] < 16]
print(f"\nNarrow spread (<16) ticks: {len([t for t in em_spreads if t and t < 16])}")

# EMERALDS: what if we could also take from the book during narrow spreads?
# During narrow spread windows (spread <= 5-9), we can BUY at ask1 and SELL at bid1
# with small cost, capturing the liquidation
print("\nEMERALDS narrow-spread take opportunities:")
for spread_thresh in [5, 6, 7, 8, 9, 10]:
    narrow = [ts for ts in all_timestamps if (ts, 'EMERALDS') in book
              and book[(ts, 'EMERALDS')]['spread'] and book[(ts, 'EMERALDS')]['spread'] <= spread_thresh]
    if narrow:
        total_vol = sum(book[(ts, 'EMERALDS')]['ask1_vol'] for ts in narrow)
        avg_spread = sum(book[(ts, 'EMERALDS')]['spread'] for ts in narrow) / len(narrow)
        print(f"  Spread <= {spread_thresh}: {len(narrow)} ticks, avg_spread={avg_spread:.1f}, "
              f"total L1 ask vol={total_vol}")


# ============================================================
# ANALYSIS 5: COMBINED CEILING + TARGET THRESHOLDS
# ============================================================
print("\n\n" + "=" * 80)
print("ANALYSIS 5: COMBINED CEILING + TARGET THRESHOLDS")
print("=" * 80)

# Compute precise ceilings
tom_spread = spread_capture_ceiling(tom_trades, 'TOMATOES', book)
em_spread = spread_capture_ceiling(em_trades, 'EMERALDS', book)

tom_dp = perfect_oracle_dp(tom_trades, 'TOMATOES', book, all_timestamps)
em_dp = perfect_oracle_dp(em_trades, 'EMERALDS', book, all_timestamps)

print(f"\n{'':>30} {'TOMATOES':>12} {'EMERALDS':>12} {'COMBINED':>12}")
print("-" * 68)
print(f"{'Spread capture (all fills)':>30} {tom_spread['terminal_pnl']:>12.1f} {em_spread['terminal_pnl']:>12.1f} "
      f"{tom_spread['terminal_pnl']+em_spread['terminal_pnl']:>12.1f}")
print(f"{'DP optimal (oracle)':>30} {tom_dp['optimal_pnl']:>12.1f} {em_dp['optimal_pnl']:>12.1f} "
      f"{tom_dp['optimal_pnl']+em_dp['optimal_pnl']:>12.1f}")

combined_dp = tom_dp['optimal_pnl'] + em_dp['optimal_pnl']
combined_spread = tom_spread['terminal_pnl'] + em_spread['terminal_pnl']

print(f"\n--- Target Analysis ---")
targets = [2896, 3000, 3300, 3500, 4000, 4950]
for target in targets:
    pct_of_dp = target / combined_dp * 100 if combined_dp > 0 else float('inf')
    pct_of_spread = target / combined_spread * 100 if combined_spread > 0 else float('inf')
    print(f"  {target}: {pct_of_dp:.1f}% of DP ceiling, {pct_of_spread:.1f}% of spread capture")

# Find accuracy where combined hits each target
print(f"\n--- Required Directional Accuracy for Targets ---")
for target in [2896, 3000, 3300]:
    # Binary search
    lo, hi = 0.50, 1.00
    for _ in range(30):
        mid_acc = (lo + hi) / 2
        tom_pnl = simulate_accuracy('TOMATOES', tom_trades, book, all_timestamps, mid_acc, n_trials=2000)
        em_pnl = simulate_accuracy('EMERALDS', em_trades, book, all_timestamps, mid_acc, n_trials=2000)
        if tom_pnl + em_pnl < target:
            lo = mid_acc
        else:
            hi = mid_acc
    print(f"  Target {target}: requires ~{(lo+hi)/2:.1%} directional accuracy")


# ============================================================
# ADDITIONAL ANALYSIS: BOOK-TAKING CEILING
# ============================================================
print("\n\n" + "=" * 80)
print("ADDITIONAL: AGGRESSIVE BOOK-TAKING CEILING")
print("=" * 80)
print("\nWhat if we could also CROSS the spread (take from the book)?")
print("At each tick, with perfect direction prediction, we take L1 volume")
print("when spread is tight enough that directional gain exceeds spread cost.\n")

def aggressive_oracle(product, product_book, all_ts, pos_limit=80):
    """
    Perfect oracle that can ALSO take from the book.
    At each tick: predict mid[t+1].
    If |mid[t+1] - mid[t]| > spread/2, cross the spread and take L1.
    Also capture taker fills as before.
    """
    ts_list = sorted(set(ts for (ts, p) in product_book.keys() if p == product))
    mid_at = {}
    for ts in ts_list:
        if (ts, product) in product_book:
            mid_at[ts] = product_book[(ts, product)]['mid']

    final_mid = mid_at[ts_list[-1]]

    position = 0
    cash = 0
    take_count = 0
    take_pnl_gross = 0

    for i, ts in enumerate(ts_list[:-1]):
        entry = product_book[(ts, product)]
        next_mid = mid_at[ts_list[i+1]]
        current_mid = entry['mid']
        delta = next_mid - current_mid

        if delta > 0:
            # Mid going up -> want to buy
            # Cost to buy: ask1
            ask = entry['ask1']
            if ask is not None and next_mid > ask:
                # Profitable to cross spread
                max_buy = pos_limit - position
                take_qty = min(entry['ask1_vol'], max_buy)
                if take_qty > 0:
                    pnl_per_unit = next_mid - ask
                    cash -= ask * take_qty
                    position += take_qty
                    take_count += 1
                    take_pnl_gross += pnl_per_unit * take_qty

        elif delta < 0:
            # Mid going down -> want to sell
            bid = entry['bid1']
            if bid is not None and next_mid < bid:
                max_sell = position + pos_limit
                take_qty = min(entry['bid1_vol'], max_sell)
                if take_qty > 0:
                    pnl_per_unit = bid - next_mid
                    cash += bid * take_qty
                    position -= take_qty
                    take_count += 1
                    take_pnl_gross += pnl_per_unit * take_qty

    terminal_pnl = cash + position * final_mid

    return {
        'terminal_pnl': terminal_pnl,
        'final_position': position,
        'take_count': take_count,
        'take_pnl_gross': take_pnl_gross,
        'final_mid': final_mid,
    }


for product in ['TOMATOES', 'EMERALDS']:
    result = aggressive_oracle(product, book, all_timestamps)
    print(f"\n--- {product} (Aggressive Oracle — cross spread when profitable) ---")
    print(f"Spread-crossing takes: {result['take_count']}")
    print(f"Final position: {result['final_position']}")
    print(f"Terminal PnL: {result['terminal_pnl']:.1f}")
    print(f"Gross take PnL (before inventory): {result['take_pnl_gross']:.1f}")


# ============================================================
# ULTIMATE CEILING: DP on ALL opportunities (taker + book-taking)
# ============================================================
print("\n\n" + "=" * 80)
print("ULTIMATE CEILING: DP over ALL opportunities (taker fills + book takes)")
print("=" * 80)
print("\nThis combines taker interception AND spread crossing at every tick.")
print("At each tick, choose: post_bid, post_ask, take_ask, take_bid, or nothing.")
print("Solved via forward DP over (tick, position) state space.\n")

def ultimate_dp(product, trade_list, product_book, all_ts, pos_limit=80):
    """
    Forward DP at every tick.
    Actions at each tick:
      1. Do nothing
      2. If taker arrives: intercept (buy or sell at inside spread)
      3. Take from book: buy at ask1 or sell at bid1

    We process ticks sequentially. At each tick, for each position state,
    we try all available actions and keep the best cash.
    """
    ts_list = sorted(set(ts for (ts, p) in product_book.keys() if p == product))
    mid_at = {}
    entries_at = {}
    for ts in ts_list:
        if (ts, product) in product_book:
            mid_at[ts] = product_book[(ts, product)]['mid']
            entries_at[ts] = product_book[(ts, product)]

    final_mid = mid_at[ts_list[-1]]

    # Build trade lookup: timestamp -> trade
    trade_at = {}
    for t in trade_list:
        trade_at[t['timestamp']] = t

    # DP state: position -> max_cash
    dp = {0: 0.0}

    for ts in ts_list:
        entry = entries_at.get(ts)
        if entry is None:
            continue

        new_dp = {}

        # Copy current states (do nothing)
        for pos, cash in dp.items():
            if pos not in new_dp or cash > new_dp[pos]:
                new_dp[pos] = cash

        for pos, cash in dp.items():
            # Option: Take from book — BUY at ask1
            if entry['ask1'] is not None:
                ask = entry['ask1']
                avail = entry['ask1_vol']
                max_buy = pos_limit - pos
                qty = min(avail, max_buy)
                if qty > 0:
                    new_pos = pos + qty
                    new_cash = cash - ask * qty
                    if new_pos not in new_dp or new_cash > new_dp[new_pos]:
                        new_dp[new_pos] = new_cash

            # Option: Take from book — SELL at bid1
            if entry['bid1'] is not None:
                bid = entry['bid1']
                avail = entry['bid1_vol']
                max_sell = pos + pos_limit
                qty = min(avail, max_sell)
                if qty > 0:
                    new_pos = pos - qty
                    new_cash = cash + bid * qty
                    if new_pos not in new_dp or new_cash > new_dp[new_pos]:
                        new_dp[new_pos] = new_cash

            # Option: Intercept taker trade (if one happens at this tick)
            if ts in trade_at:
                trade = trade_at[ts]
                qty = trade['quantity']

                if trade['side'] == 'sell':
                    # Taker sells -> we buy at bid1+1
                    our_price = entry['bid1'] + 1
                    max_buy = pos_limit - pos
                    actual = min(qty, max_buy)
                    if actual > 0:
                        new_pos = pos + actual
                        new_cash = cash - our_price * actual
                        if new_pos not in new_dp or new_cash > new_dp[new_pos]:
                            new_dp[new_pos] = new_cash

                elif trade['side'] == 'buy':
                    # Taker buys -> we sell at ask1-1
                    our_price = entry['ask1'] - 1
                    max_sell = pos + pos_limit
                    actual = min(qty, max_sell)
                    if actual > 0:
                        new_pos = pos - actual
                        new_cash = cash + our_price * actual
                        if new_pos not in new_dp or new_cash > new_dp[new_pos]:
                            new_dp[new_pos] = new_cash

        dp = new_dp

    # Best terminal PnL
    best_pnl = float('-inf')
    best_pos = 0
    for pos, cash in dp.items():
        pnl = cash + pos * final_mid
        if pnl > best_pnl:
            best_pnl = pnl
            best_pos = pos

    return {
        'optimal_pnl': best_pnl,
        'optimal_pos': best_pos,
        'optimal_cash': dp[best_pos],
        'final_mid': final_mid,
        'n_states': len(dp),
    }


for product, trade_list in [('TOMATOES', tom_trades), ('EMERALDS', em_trades)]:
    result = ultimate_dp(product, trade_list, book, all_timestamps)
    print(f"\n--- {product} ---")
    print(f"Optimal PnL (taker + book): {result['optimal_pnl']:.1f}")
    print(f"Optimal final position: {result['optimal_pos']}")
    print(f"Final mid: {result['final_mid']}")
    print(f"DP states at terminal: {result['n_states']}")

tom_ult = ultimate_dp('TOMATOES', tom_trades, book, all_timestamps)
em_ult = ultimate_dp('EMERALDS', em_trades, book, all_timestamps)
print(f"\nULTIMATE COMBINED CEILING: {tom_ult['optimal_pnl'] + em_ult['optimal_pnl']:.1f}")


# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n\n" + "=" * 80)
print("FINAL SUMMARY")
print("=" * 80)

print(f"""
Data: 2000 ticks, position limit 80 per product

TOMATOES: 70 taker trades (240 total qty), final mid = {tom_spread['final_mid']}
EMERALDS: 29 taker trades (150 total qty), final mid = {em_spread['final_mid']}

                                          TOMATOES    EMERALDS    COMBINED
----------------------------------------------------------------------
Spread capture (all taker fills)       {tom_spread['terminal_pnl']:>10.1f}  {em_spread['terminal_pnl']:>10.1f}  {tom_spread['terminal_pnl']+em_spread['terminal_pnl']:>10.1f}
DP optimal (taker only, oracle)        {tom_dp['optimal_pnl']:>10.1f}  {em_dp['optimal_pnl']:>10.1f}  {tom_dp['optimal_pnl']+em_dp['optimal_pnl']:>10.1f}
Ultimate DP (taker + book takes)       {tom_ult['optimal_pnl']:>10.1f}  {em_ult['optimal_pnl']:>10.1f}  {tom_ult['optimal_pnl']+em_ult['optimal_pnl']:>10.1f}

Your best score (s36_medallion):                                   2,896.0
Implied efficiency vs spread ceiling: {2896/(tom_spread['terminal_pnl']+em_spread['terminal_pnl'])*100:.1f}%
Implied efficiency vs DP oracle:      {2896/(tom_dp['optimal_pnl']+em_dp['optimal_pnl'])*100:.1f}%
Implied efficiency vs ultimate DP:    {2896/(tom_ult['optimal_pnl']+em_ult['optimal_pnl'])*100:.1f}%

KEY INSIGHT: The gap between your 2,896 and the DP oracle ceiling
tells you how much room for improvement exists from better trade
selection alone (no new information sources needed).

The gap between DP oracle and ultimate ceiling tells you the value
of ALSO being able to cross the spread profitably.
""")

# Additional: mid price trajectory analysis
print("=" * 80)
print("MID PRICE TRAJECTORY ANALYSIS")
print("=" * 80)

for product in ['TOMATOES', 'EMERALDS']:
    mids = []
    for ts in all_timestamps:
        key = (ts, product)
        if key in book:
            mids.append(book[key]['mid'])

    if mids:
        first = mids[0]
        last = mids[-1]
        high = max(mids)
        low = min(mids)
        drift = last - first

        # Count direction changes
        up_moves = sum(1 for i in range(1, len(mids)) if mids[i] > mids[i-1])
        down_moves = sum(1 for i in range(1, len(mids)) if mids[i] < mids[i-1])
        flat = sum(1 for i in range(1, len(mids)) if mids[i] == mids[i-1])

        # Max position PnL from drift
        max_drift_pnl = POS_LIMIT * abs(drift)

        print(f"\n{product}:")
        print(f"  First mid: {first}, Last mid: {last}, Drift: {drift:+.1f}")
        print(f"  High: {high}, Low: {low}, Range: {high-low:.1f}")
        print(f"  Up moves: {up_moves}, Down moves: {down_moves}, Flat: {flat}")
        print(f"  Max PnL from drift alone (80 units): {max_drift_pnl:.1f}")
        print(f"  Max PnL from range (buy low, sell high, 80 units): {POS_LIMIT * (high - low):.1f}")
