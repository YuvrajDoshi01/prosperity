"""
Oracle Maximum PnL Calculator for IMC Prosperity 4 Round 0 Day 0 (2000 ticks).

Computes the TRUE theoretical maximum PnL with perfect future knowledge.

Approach: Forward-pass greedy with lookahead for each product independently.
Then DP over position states for exact optimum.

Key mechanics modeled:
1. TAKE: Cross the spread - buy at ask, sell at bid (instant fill)
2. MAKE/POST: Post resting orders inside the spread
   - Post buy at bid+1: filled if taker sells or if next tick's ask <= our price
   - Post sell at ask-1: filled if taker buys or if next tick's bid >= our price
3. TAKER INTERCEPTION: If we post at bid+1, we intercept taker sells before MM
4. Position limits: +/-80
5. End-of-day MTM: final_mid * final_position

The key insight for top scores: you need to both intercept taker flow AND
optimally manage inventory trajectory knowing future price moves.
"""

import sys
import os
from collections import defaultdict
from typing import NamedTuple
import time

# ============================================================================
# Data Loading
# ============================================================================

class TickData(NamedTuple):
    timestamp: int
    bid_prices: list  # [best_bid, bid2, bid3]
    bid_volumes: list  # [vol1, vol2, vol3]
    ask_prices: list  # [best_ask, ask2, ask3]
    ask_volumes: list
    mid_price: float

class TradeData(NamedTuple):
    timestamp: int
    price: int
    quantity: int
    is_taker_buy: bool  # True if taker bought (hit ask), False if taker sold (hit bid)

def load_data(prices_file, trades_file):
    """Load CSV data into structured format."""
    # Load prices
    prices_by_product = defaultdict(list)
    with open(prices_file) as f:
        for line in f.read().splitlines()[1:]:
            cols = line.split(';')
            ts = int(cols[1])
            product = cols[2]

            bid_prices = []
            bid_volumes = []
            for i, idx in enumerate([3, 5, 7]):
                if cols[idx] == '':
                    break
                bid_prices.append(int(cols[idx]))
                bid_volumes.append(int(cols[idx + 1]))

            ask_prices = []
            ask_volumes = []
            for i, idx in enumerate([9, 11, 13]):
                if cols[idx] == '':
                    break
                ask_prices.append(int(cols[idx]))
                ask_volumes.append(int(cols[idx + 1]))

            mid = float(cols[15])

            prices_by_product[product].append(TickData(
                timestamp=ts,
                bid_prices=bid_prices,
                bid_volumes=bid_volumes,
                ask_prices=ask_prices,
                ask_volumes=ask_volumes,
                mid_price=mid,
            ))

    # Sort by timestamp
    for product in prices_by_product:
        prices_by_product[product].sort(key=lambda x: x.timestamp)

    # Load trades
    trades_by_product = defaultdict(list)
    with open(trades_file) as f:
        for line in f.read().splitlines()[1:]:
            cols = line.split(';')
            ts = int(cols[0])
            symbol = cols[3]
            price = int(float(cols[5]))
            qty = int(cols[6])
            trades_by_product[symbol].append((ts, price, qty))

    return prices_by_product, trades_by_product


def classify_trades(prices_by_product, trades_by_product):
    """Classify each trade as taker buy or taker sell based on price vs mid."""
    classified = defaultdict(list)

    for product, trades in trades_by_product.items():
        ticks = prices_by_product[product]
        # Build timestamp -> tick index map
        ts_to_idx = {t.timestamp: i for i, t in enumerate(ticks)}

        for ts, price, qty in trades:
            if ts not in ts_to_idx:
                continue
            tick = ticks[ts_to_idx[ts]]
            mid = tick.mid_price

            # Taker buy if price >= mid (hit the ask), taker sell if price < mid (hit the bid)
            is_taker_buy = price >= mid

            classified[product].append(TradeData(
                timestamp=ts,
                price=price,
                quantity=qty,
                is_taker_buy=is_taker_buy,
            ))

    return classified


# ============================================================================
# Fill Opportunity Analysis
# ============================================================================

class FillOpportunity(NamedTuple):
    tick_idx: int        # When to place the order
    fill_price: int      # Price we trade at
    max_qty: int         # Maximum quantity available
    is_buy: bool         # True = we buy, False = we sell
    source: str          # 'take_ask', 'take_bid', 'taker_intercept_buy', 'taker_intercept_sell',
                         # 'resting_buy_filled', 'resting_sell_filled', 'mm_quote_sweep'
    pnl_per_unit: float  # Cash PnL per unit (negative for buys, positive for sells)
                         # Actual PnL depends on MTM at end

def find_all_opportunities(ticks, trades_classified, product):
    """Find ALL possible fill opportunities at every tick."""
    N = len(ticks)
    ts_to_idx = {t.timestamp: i for i, t in enumerate(ticks)}

    # Index trades by timestamp
    trades_at_tick = defaultdict(list)
    for td in trades_classified:
        if td.timestamp in ts_to_idx:
            trades_at_tick[ts_to_idx[td.timestamp]].append(td)

    opportunities = []

    for i in range(N):
        tick = ticks[i]
        best_bid = tick.bid_prices[0] if tick.bid_prices else None
        best_ask = tick.ask_prices[0] if tick.ask_prices else None

        if best_bid is None or best_ask is None:
            continue

        # === TAKE OPPORTUNITIES ===
        # Take the ask (buy at ask price) - instant fill against MM book
        for level_idx in range(len(tick.ask_prices)):
            ask_p = tick.ask_prices[level_idx]
            ask_v = tick.ask_volumes[level_idx]
            opportunities.append(FillOpportunity(
                tick_idx=i,
                fill_price=ask_p,
                max_qty=ask_v,
                is_buy=True,
                source=f'take_ask_L{level_idx+1}',
                pnl_per_unit=-ask_p,
            ))

        # Take the bid (sell at bid price) - instant fill against MM book
        for level_idx in range(len(tick.bid_prices)):
            bid_p = tick.bid_prices[level_idx]
            bid_v = tick.bid_volumes[level_idx]
            opportunities.append(FillOpportunity(
                tick_idx=i,
                fill_price=bid_p,
                max_qty=bid_v,
                is_buy=False,
                source=f'take_bid_L{level_idx+1}',
                pnl_per_unit=bid_p,
            ))

        # === TAKER INTERCEPTION (same tick) ===
        # If a taker arrives at this tick and we have a resting order at the best price,
        # we intercept the taker. In the default matching mode, our order at bid+1 gets
        # filled by taker sells at OUR price (which is better for the taker).
        # In IMC mode, taker hits best_bid which could be our resting order.

        for td in trades_at_tick.get(i, []):
            if td.is_taker_buy:
                # Taker buys at ask price. If we're posted at ask or ask-1, we fill.
                # If we post SELL at ask-1 (inside the spread), we're BETTER price for buyer
                # Taker would hit us first.
                post_price = best_ask  # Conservative: taker hits at current ask
                opportunities.append(FillOpportunity(
                    tick_idx=i,
                    fill_price=post_price,
                    max_qty=td.quantity,
                    is_buy=False,  # We sell to the taker
                    source='taker_intercept_sell_at_ask',
                    pnl_per_unit=post_price,
                ))
                # Can also post at ask-1 (better for taker, we're ahead of MM)
                inside_price = best_ask - 1
                if inside_price > best_bid:  # Must be valid (inside spread)
                    opportunities.append(FillOpportunity(
                        tick_idx=i,
                        fill_price=inside_price,
                        max_qty=td.quantity,
                        is_buy=False,
                        source='taker_intercept_sell_inside',
                        pnl_per_unit=inside_price,
                    ))
            else:
                # Taker sells at bid price. If we post BUY at bid or bid+1, we intercept.
                post_price = best_bid
                opportunities.append(FillOpportunity(
                    tick_idx=i,
                    fill_price=post_price,
                    max_qty=td.quantity,
                    is_buy=True,  # We buy from the taker
                    source='taker_intercept_buy_at_bid',
                    pnl_per_unit=-post_price,
                ))
                inside_price = best_bid + 1
                if inside_price < best_ask:
                    opportunities.append(FillOpportunity(
                        tick_idx=i,
                        fill_price=inside_price,
                        max_qty=td.quantity,
                        is_buy=True,
                        source='taker_intercept_buy_inside',
                        pnl_per_unit=-inside_price,
                    ))

        # === RESTING ORDER FILLS (post now, fills on future ticks) ===
        # Post buy at bid+1: fills if NEXT tick's MM ask moves down to our level
        # This happens when mid drops, causing ask to drop to <= bid+1
        if i + 1 < N:
            next_tick = ticks[i + 1]
            next_best_ask = next_tick.ask_prices[0] if next_tick.ask_prices else None
            next_best_bid = next_tick.bid_prices[0] if next_tick.bid_prices else None

            # Resting buy at bid+1: fills if next tick's ask <= bid+1
            # (MM updates quotes, new ask at or below our resting buy)
            resting_buy_price = best_bid + 1
            if next_best_ask is not None and next_best_ask <= resting_buy_price:
                # We get filled at our resting price (price improvement for us)
                # Volume: we can only get filled by the MM's new ask volume at that level
                fill_vol = 0
                for lvl in range(len(next_tick.ask_prices)):
                    if next_tick.ask_prices[lvl] <= resting_buy_price:
                        fill_vol += next_tick.ask_volumes[lvl]
                if fill_vol > 0:
                    opportunities.append(FillOpportunity(
                        tick_idx=i,
                        fill_price=resting_buy_price,
                        max_qty=min(fill_vol, 80),  # conservative
                        is_buy=True,
                        source='resting_buy_mm_sweep',
                        pnl_per_unit=-resting_buy_price,
                    ))

            # Resting sell at ask-1: fills if next tick's bid >= ask-1
            resting_sell_price = best_ask - 1
            if next_best_bid is not None and next_best_bid >= resting_sell_price:
                fill_vol = 0
                for lvl in range(len(next_tick.bid_prices)):
                    if next_tick.bid_prices[lvl] >= resting_sell_price:
                        fill_vol += next_tick.bid_volumes[lvl]
                if fill_vol > 0:
                    opportunities.append(FillOpportunity(
                        tick_idx=i,
                        fill_price=resting_sell_price,
                        max_qty=min(fill_vol, 80),
                        is_buy=False,
                        source='resting_sell_mm_sweep',
                        pnl_per_unit=resting_sell_price,
                    ))

    return opportunities


# ============================================================================
# Dynamic Programming: Optimal Position Trajectory
# ============================================================================

def dp_optimal_trajectory(ticks, trades_classified, product, pos_limit=80):
    """
    DP over (tick, position) states to find optimal PnL.

    At each tick, we can:
    1. Do nothing
    2. Take the ask (buy, multiple levels)
    3. Take the bid (sell, multiple levels)
    4. Intercept taker (if taker arrives at this tick)
    5. Post resting order that fills on next tick's MM quote change

    State: (tick_index, position)
    Value: maximum cash PnL achievable from this state onward

    Terminal value: position * final_mid_price
    """
    N = len(ticks)
    ts_to_idx = {t.timestamp: i for i, t in enumerate(ticks)}

    # Index trades by tick
    trades_at_tick = defaultdict(list)
    for td in trades_classified:
        if td.timestamp in ts_to_idx:
            trades_at_tick[ts_to_idx[td.timestamp]].append(td)

    # Position range: -pos_limit to +pos_limit
    POS_RANGE = range(-pos_limit, pos_limit + 1)

    # dp[pos] = max cash PnL from current state onward
    # We process backward from last tick

    final_mid = ticks[N - 1].mid_price

    # Initialize terminal values
    # At the end, cash_pnl + position * final_mid = total PnL
    # Since we want to maximize total, terminal value of position p = p * final_mid
    dp_next = {}
    for pos in POS_RANGE:
        dp_next[pos] = pos * final_mid

    # Track actions for reconstruction
    actions = [{} for _ in range(N)]  # actions[tick][pos] = (action_desc, new_pos, cash_delta)

    print(f"\n{'='*70}")
    print(f"  DP for {product}: {N} ticks, position range [{-pos_limit}, {pos_limit}]")
    print(f"  Final mid price: {final_mid}")
    print(f"  Taker trades: {len(trades_classified)}")
    print(f"{'='*70}")

    t0 = time.time()

    for i in range(N - 1, -1, -1):
        tick = ticks[i]
        best_bid = tick.bid_prices[0] if tick.bid_prices else None
        best_ask = tick.ask_prices[0] if tick.ask_prices else None

        dp_curr = {}

        if i % 200 == 0:
            elapsed = time.time() - t0
            print(f"  Tick {i}/{N} ({elapsed:.1f}s elapsed)...")

        for pos in POS_RANGE:
            best_val = dp_next[pos]  # Do nothing
            best_action = ('hold', pos, 0)

            if best_bid is None or best_ask is None:
                dp_curr[pos] = best_val
                actions[i][pos] = best_action
                continue

            # ---- Action 1: Take the ask (BUY) at various levels ----
            # We can buy up to (pos_limit - pos) units
            max_buy = pos_limit - pos
            if max_buy > 0:
                cumulative_cost = 0
                cumulative_qty = 0
                for lvl in range(len(tick.ask_prices)):
                    ask_p = tick.ask_prices[lvl]
                    ask_v = tick.ask_volumes[lvl]
                    can_buy = min(ask_v, max_buy - cumulative_qty)
                    if can_buy <= 0:
                        break
                    # Try buying 1..can_buy at this level
                    for q in range(1, can_buy + 1):
                        total_q = cumulative_qty + q
                        total_cost = cumulative_cost + ask_p * q
                        new_pos = pos + total_q
                        if new_pos in dp_next:
                            val = -total_cost + dp_next[new_pos]
                            if val > best_val:
                                best_val = val
                                best_action = (f'take_ask_{total_q}@{ask_p}', new_pos, -total_cost)
                    cumulative_cost += ask_p * can_buy
                    cumulative_qty += can_buy

            # ---- Action 2: Take the bid (SELL) at various levels ----
            max_sell = pos_limit + pos
            if max_sell > 0:
                cumulative_revenue = 0
                cumulative_qty = 0
                for lvl in range(len(tick.bid_prices)):
                    bid_p = tick.bid_prices[lvl]
                    bid_v = tick.bid_volumes[lvl]
                    can_sell = min(bid_v, max_sell - cumulative_qty)
                    if can_sell <= 0:
                        break
                    for q in range(1, can_sell + 1):
                        total_q = cumulative_qty + q
                        total_rev = cumulative_revenue + bid_p * q
                        new_pos = pos - total_q
                        if new_pos in dp_next:
                            val = total_rev + dp_next[new_pos]
                            if val > best_val:
                                best_val = val
                                best_action = (f'take_bid_{total_q}@{bid_p}', new_pos, total_rev)
                    cumulative_revenue += bid_p * can_sell
                    cumulative_qty += can_sell

            # ---- Action 3: Intercept taker (if one arrives this tick) ----
            for td in trades_at_tick.get(i, []):
                if td.is_taker_buy:
                    # Taker buys: we can SELL to them
                    # Option A: at current ask (we match MM, share fill)
                    # Option B: at ask-1 (we're better price, guaranteed fill)
                    for sell_price_label, sell_price in [('ask', best_ask), ('ask-1', best_ask - 1)]:
                        if sell_price <= best_bid:
                            continue
                        can_sell_to_taker = min(td.quantity, pos_limit + pos)
                        if can_sell_to_taker > 0:
                            for q in range(1, can_sell_to_taker + 1):
                                new_pos = pos - q
                                if new_pos in dp_next:
                                    cash = sell_price * q
                                    val = cash + dp_next[new_pos]
                                    if val > best_val:
                                        best_val = val
                                        best_action = (f'taker_sell_{q}@{sell_price}({sell_price_label})', new_pos, cash)
                else:
                    # Taker sells: we can BUY from them
                    for buy_price_label, buy_price in [('bid', best_bid), ('bid+1', best_bid + 1)]:
                        if buy_price >= best_ask:
                            continue
                        can_buy_from_taker = min(td.quantity, pos_limit - pos)
                        if can_buy_from_taker > 0:
                            for q in range(1, can_buy_from_taker + 1):
                                new_pos = pos + q
                                if new_pos in dp_next:
                                    cash = -buy_price * q
                                    val = cash + dp_next[new_pos]
                                    if val > best_val:
                                        best_val = val
                                        best_action = (f'taker_buy_{q}@{buy_price}({buy_price_label})', new_pos, cash)

            # ---- Action 4: Resting orders that fill on next tick ----
            if i + 1 < N:
                next_tick = ticks[i + 1]
                next_best_ask = next_tick.ask_prices[0] if next_tick.ask_prices else None
                next_best_bid = next_tick.bid_prices[0] if next_tick.bid_prices else None

                # Resting BUY at bid+1: fills if next MM ask <= bid+1
                resting_buy_price = best_bid + 1
                if next_best_ask is not None and next_best_ask <= resting_buy_price:
                    # How much volume can we get? Limited by next tick's sell volume at those levels
                    fill_vol = 0
                    for lvl in range(len(next_tick.ask_prices)):
                        if next_tick.ask_prices[lvl] <= resting_buy_price:
                            fill_vol += next_tick.ask_volumes[lvl]

                    can_buy = min(fill_vol, pos_limit - pos)
                    if can_buy > 0:
                        for q in range(1, can_buy + 1):
                            new_pos = pos + q
                            if new_pos in dp_next:
                                cash = -resting_buy_price * q
                                val = cash + dp_next[new_pos]
                                if val > best_val:
                                    best_val = val
                                    best_action = (f'resting_buy_{q}@{resting_buy_price}', new_pos, cash)

                # Resting SELL at ask-1: fills if next MM bid >= ask-1
                resting_sell_price = best_ask - 1
                if next_best_bid is not None and next_best_bid >= resting_sell_price:
                    fill_vol = 0
                    for lvl in range(len(next_tick.bid_prices)):
                        if next_tick.bid_prices[lvl] >= resting_sell_price:
                            fill_vol += next_tick.bid_volumes[lvl]

                    can_sell = min(fill_vol, pos_limit + pos)
                    if can_sell > 0:
                        for q in range(1, can_sell + 1):
                            new_pos = pos - q
                            if new_pos in dp_next:
                                cash = resting_sell_price * q
                                val = cash + dp_next[new_pos]
                                if val > best_val:
                                    best_val = val
                                    best_action = (f'resting_sell_{q}@{resting_sell_price}', new_pos, cash)

                # === COMBINED: Take + intercept taker in same tick ===
                # Can we take the ask AND intercept a taker sell (buying more)?
                # Or take the bid AND intercept a taker buy?
                for td in trades_at_tick.get(i, []):
                    if td.is_taker_buy:
                        # We can SELL via take_bid AND sell to taker
                        # First take bid for some qty, then sell to taker for some qty
                        for take_q in range(1, min(tick.bid_volumes[0], pos_limit + pos) + 1):
                            remaining_sell_cap = pos_limit + pos - take_q
                            if remaining_sell_cap <= 0:
                                break
                            take_cash = tick.bid_prices[0] * take_q
                            for taker_q in range(1, min(td.quantity, remaining_sell_cap) + 1):
                                sell_price = best_ask - 1 if (best_ask - 1) > best_bid else best_ask
                                taker_cash = sell_price * taker_q
                                total_q = take_q + taker_q
                                new_pos = pos - total_q
                                if new_pos in dp_next:
                                    val = take_cash + taker_cash + dp_next[new_pos]
                                    if val > best_val:
                                        best_val = val
                                        best_action = (f'combo_sell_take{take_q}+taker{taker_q}', new_pos, take_cash + taker_cash)
                    else:
                        # We can BUY via take_ask AND buy from taker
                        for take_q in range(1, min(tick.ask_volumes[0], pos_limit - pos) + 1):
                            remaining_buy_cap = pos_limit - pos - take_q
                            if remaining_buy_cap <= 0:
                                break
                            take_cash = -tick.ask_prices[0] * take_q
                            for taker_q in range(1, min(td.quantity, remaining_buy_cap) + 1):
                                buy_price = best_bid + 1 if (best_bid + 1) < best_ask else best_bid
                                taker_cash = -buy_price * taker_q
                                total_q = take_q + taker_q
                                new_pos = pos + total_q
                                if new_pos in dp_next:
                                    val = take_cash + taker_cash + dp_next[new_pos]
                                    if val > best_val:
                                        best_val = val
                                        best_action = (f'combo_buy_take{take_q}+taker{taker_q}', new_pos, take_cash + taker_cash)

            dp_curr[pos] = best_val
            actions[i][pos] = best_action

        dp_next = dp_curr

    # Optimal starts at position 0
    optimal_pnl = dp_curr[0]

    # Reconstruct trajectory
    trajectory = []
    pos = 0
    cash = 0
    for i in range(N):
        action_desc, new_pos, cash_delta = actions[i][pos]
        if action_desc != 'hold':
            trajectory.append({
                'tick': i,
                'timestamp': ticks[i].timestamp,
                'action': action_desc,
                'pos_before': pos,
                'pos_after': new_pos,
                'cash_delta': cash_delta,
                'mid': ticks[i].mid_price,
            })
        cash += cash_delta
        pos = new_pos

    mtm = pos * final_mid

    elapsed = time.time() - t0
    print(f"  DP completed in {elapsed:.1f}s")
    print(f"  Optimal PnL: {optimal_pnl:.2f} (cash: {cash:.2f}, MTM: {mtm:.2f})")
    print(f"  Final position: {pos}")
    print(f"  Number of trades: {len(trajectory)}")

    return optimal_pnl, cash, mtm, pos, trajectory


# ============================================================================
# Enhanced DP: Multiple fills per tick (take + intercept + resting simultaneously)
# ============================================================================

def dp_enhanced(ticks, trades_classified, product, pos_limit=80):
    """
    Enhanced DP that considers MULTIPLE SIMULTANEOUS actions per tick.

    At each tick, we can potentially:
    - Take from the book (buy at ask or sell at bid)
    - AND intercept a taker (if one arrives)
    - AND have a resting order fill from previous tick

    These are independent fill sources that can compound.

    To make this tractable, we enumerate possible (delta_position, cash_flow)
    pairs at each tick considering all combinations.
    """
    N = len(ticks)
    ts_to_idx = {t.timestamp: i for i, t in enumerate(ticks)}

    trades_at_tick = defaultdict(list)
    for td in trades_classified:
        if td.timestamp in ts_to_idx:
            trades_at_tick[ts_to_idx[td.timestamp]].append(td)

    POS_RANGE = range(-pos_limit, pos_limit + 1)
    final_mid = ticks[N - 1].mid_price

    # Terminal values
    dp_next = {pos: pos * final_mid for pos in POS_RANGE}

    actions = [{} for _ in range(N)]

    print(f"\n{'='*70}")
    print(f"  Enhanced DP for {product}: {N} ticks, pos range [{-pos_limit}, {pos_limit}]")
    print(f"  Final mid: {final_mid}")
    print(f"{'='*70}")

    t0 = time.time()

    for i in range(N - 1, -1, -1):
        tick = ticks[i]
        bb = tick.bid_prices[0] if tick.bid_prices else None
        ba = tick.ask_prices[0] if tick.ask_prices else None

        dp_curr = {}

        if i % 200 == 0:
            elapsed = time.time() - t0
            print(f"  Tick {i}/{N} ({elapsed:.1f}s)...")

        # Pre-compute available fills at this tick
        # Each fill is (is_buy, price, max_qty, source)
        available_fills = []

        if bb is not None and ba is not None:
            # Take ask (buy from MM book)
            for lvl in range(len(tick.ask_prices)):
                available_fills.append((True, tick.ask_prices[lvl], tick.ask_volumes[lvl], f'take_ask_L{lvl+1}'))

            # Take bid (sell to MM book)
            for lvl in range(len(tick.bid_prices)):
                available_fills.append((False, tick.bid_prices[lvl], tick.bid_volumes[lvl], f'take_bid_L{lvl+1}'))

            # Taker interception
            for td in trades_at_tick.get(i, []):
                if td.is_taker_buy:
                    # We can sell to taker at ask-1 (inside) or ask (at)
                    inside_p = ba - 1
                    if inside_p > bb:
                        available_fills.append((False, inside_p, td.quantity, 'taker_sell_inside'))
                    available_fills.append((False, ba, td.quantity, 'taker_sell_at_ask'))
                else:
                    inside_p = bb + 1
                    if inside_p < ba:
                        available_fills.append((True, inside_p, td.quantity, 'taker_buy_inside'))
                    available_fills.append((True, bb, td.quantity, 'taker_buy_at_bid'))

            # Resting fills (from this tick, filled by next tick's MM quote change)
            if i + 1 < N:
                next_tick = ticks[i + 1]
                nba = next_tick.ask_prices[0] if next_tick.ask_prices else None
                nbb = next_tick.bid_prices[0] if next_tick.bid_prices else None

                rest_buy_p = bb + 1
                if nba is not None and nba <= rest_buy_p:
                    vol = sum(next_tick.ask_volumes[lvl] for lvl in range(len(next_tick.ask_prices))
                              if next_tick.ask_prices[lvl] <= rest_buy_p)
                    if vol > 0:
                        available_fills.append((True, rest_buy_p, min(vol, 80), 'resting_buy'))

                rest_sell_p = ba - 1
                if nbb is not None and nbb >= rest_sell_p:
                    vol = sum(next_tick.bid_volumes[lvl] for lvl in range(len(next_tick.bid_prices))
                              if next_tick.bid_prices[lvl] >= rest_sell_p)
                    if vol > 0:
                        available_fills.append((False, rest_sell_p, min(vol, 80), 'resting_sell'))

        for pos in POS_RANGE:
            best_val = dp_next[pos]
            best_action = ('hold', pos, 0)

            # Try each individual fill
            for is_buy, price, max_qty, source in available_fills:
                if is_buy:
                    max_q = min(max_qty, pos_limit - pos)
                    for q in range(1, max_q + 1):
                        new_pos = pos + q
                        cash = -price * q
                        val = cash + dp_next[new_pos]
                        if val > best_val:
                            best_val = val
                            best_action = (f'{source}_{q}@{price}', new_pos, cash)
                else:
                    max_q = min(max_qty, pos_limit + pos)
                    for q in range(1, max_q + 1):
                        new_pos = pos - q
                        cash = price * q
                        val = cash + dp_next[new_pos]
                        if val > best_val:
                            best_val = val
                            best_action = (f'{source}_{q}@{price}', new_pos, cash)

            # Try COMBINATIONS of non-overlapping fills
            # Key insight: we can take from MM book AND intercept a taker simultaneously
            # But we can't take_ask AND taker_buy_inside from same taker

            # Group fills by compatibility
            take_buys = [(p, q, s) for is_buy, p, q, s in available_fills
                         if is_buy and s.startswith('take_ask')]
            take_sells = [(p, q, s) for is_buy, p, q, s in available_fills
                          if not is_buy and s.startswith('take_bid')]
            taker_buys = [(p, q, s) for is_buy, p, q, s in available_fills
                          if is_buy and s.startswith('taker_buy')]
            taker_sells = [(p, q, s) for is_buy, p, q, s in available_fills
                           if not is_buy and s.startswith('taker_sell')]
            resting_buys = [(p, q, s) for is_buy, p, q, s in available_fills
                            if is_buy and s.startswith('resting')]
            resting_sells = [(p, q, s) for is_buy, p, q, s in available_fills
                             if not is_buy and s.startswith('resting')]

            # Combo: take_sell + taker_sell (both sell directions, both fill from different sources)
            # Actually more useful: take_buy + taker_buy, take_sell + taker_sell (same direction)
            # Or: take_buy + taker_sell (buy from book + sell to taker)

            # Try: take from book + intercept taker (these are independent fill sources)
            # Buy from book + sell to taker
            if take_buys and taker_sells:
                for tb_p, tb_maxq, tb_s in take_buys[:1]:  # best ask level
                    for ts_p, ts_maxq, ts_s in taker_sells[:1]:  # best taker sell
                        for bq in range(1, min(tb_maxq, pos_limit - pos) + 1):
                            for sq in range(1, min(ts_maxq, pos_limit + pos + bq) + 1):
                                # But position limit applies to NET
                                # Buying bq and selling sq: net = pos + bq - sq
                                net_pos = pos + bq - sq
                                if -pos_limit <= net_pos <= pos_limit:
                                    # Also check intermediate: after buy, pos+bq must be <= pos_limit
                                    # After sell, pos+bq-sq >= -pos_limit
                                    if pos + bq <= pos_limit:
                                        cash = -tb_p * bq + ts_p * sq
                                        val = cash + dp_next[net_pos]
                                        if val > best_val:
                                            best_val = val
                                            best_action = (f'combo_{tb_s}_{bq}+{ts_s}_{sq}', net_pos, cash)

            # Sell to book + buy from taker
            if take_sells and taker_buys:
                for ts_p, ts_maxq, ts_s in take_sells[:1]:
                    for tb_p, tb_maxq, tb_s in taker_buys[:1]:
                        for sq in range(1, min(ts_maxq, pos_limit + pos) + 1):
                            for bq in range(1, min(tb_maxq, pos_limit - pos + sq) + 1):
                                net_pos = pos - sq + bq
                                if -pos_limit <= net_pos <= pos_limit:
                                    if pos - sq >= -pos_limit:
                                        cash = ts_p * sq - tb_p * bq
                                        val = cash + dp_next[net_pos]
                                        if val > best_val:
                                            best_val = val
                                            best_action = (f'combo_{ts_s}_{sq}+{tb_s}_{bq}', net_pos, cash)

            # Take + resting (these happen at different times, so always compatible)
            # Take now + resting fills later
            if take_buys and resting_sells:
                for tb_p, tb_maxq, tb_s in take_buys[:1]:
                    for rs_p, rs_maxq, rs_s in resting_sells[:1]:
                        for bq in range(1, min(tb_maxq, pos_limit - pos) + 1):
                            for sq in range(1, min(rs_maxq, pos_limit + pos + bq) + 1):
                                net_pos = pos + bq - sq
                                if -pos_limit <= net_pos <= pos_limit and pos + bq <= pos_limit:
                                    cash = -tb_p * bq + rs_p * sq
                                    val = cash + dp_next[net_pos]
                                    if val > best_val:
                                        best_val = val
                                        best_action = (f'combo_{tb_s}_{bq}+{rs_s}_{sq}', net_pos, cash)

            if take_sells and resting_buys:
                for ts_p, ts_maxq, ts_s in take_sells[:1]:
                    for rb_p, rb_maxq, rb_s in resting_buys[:1]:
                        for sq in range(1, min(ts_maxq, pos_limit + pos) + 1):
                            for bq in range(1, min(rb_maxq, pos_limit - pos + sq) + 1):
                                net_pos = pos - sq + bq
                                if -pos_limit <= net_pos <= pos_limit and pos - sq >= -pos_limit:
                                    cash = ts_p * sq - rb_p * bq
                                    val = cash + dp_next[net_pos]
                                    if val > best_val:
                                        best_val = val
                                        best_action = (f'combo_{ts_s}_{sq}+{rb_s}_{bq}', net_pos, cash)

            # Taker + resting (both passive)
            if taker_sells and resting_buys:
                for ts_p, ts_maxq, ts_s in taker_sells[:1]:
                    for rb_p, rb_maxq, rb_s in resting_buys[:1]:
                        for sq in range(1, min(ts_maxq, pos_limit + pos) + 1):
                            for bq in range(1, min(rb_maxq, pos_limit - pos + sq) + 1):
                                net_pos = pos - sq + bq
                                if -pos_limit <= net_pos <= pos_limit:
                                    cash = ts_p * sq - rb_p * bq
                                    val = cash + dp_next[net_pos]
                                    if val > best_val:
                                        best_val = val
                                        best_action = (f'combo_{ts_s}_{sq}+{rb_s}_{bq}', net_pos, cash)

            if taker_buys and resting_sells:
                for tb_p, tb_maxq, tb_s in taker_buys[:1]:
                    for rs_p, rs_maxq, rs_s in resting_sells[:1]:
                        for bq in range(1, min(tb_maxq, pos_limit - pos) + 1):
                            for sq in range(1, min(rs_maxq, pos_limit + pos + bq) + 1):
                                net_pos = pos + bq - sq
                                if -pos_limit <= net_pos <= pos_limit:
                                    cash = -tb_p * bq + rs_p * sq
                                    val = cash + dp_next[net_pos]
                                    if val > best_val:
                                        best_val = val
                                        best_action = (f'combo_{tb_s}_{bq}+{rs_s}_{sq}', net_pos, cash)

            dp_curr[pos] = best_val
            actions[i][pos] = best_action

        dp_next = dp_curr

    optimal_pnl = dp_curr[0]

    # Reconstruct
    trajectory = []
    pos = 0
    cash = 0
    for i in range(N):
        action_desc, new_pos, cash_delta = actions[i][pos]
        if action_desc != 'hold':
            trajectory.append({
                'tick': i,
                'timestamp': ticks[i].timestamp,
                'action': action_desc,
                'pos_before': pos,
                'pos_after': new_pos,
                'cash_delta': cash_delta,
                'mid': ticks[i].mid_price,
            })
        cash += cash_delta
        pos = new_pos

    mtm = pos * final_mid

    elapsed = time.time() - t0
    print(f"\n  Enhanced DP completed in {elapsed:.1f}s")
    print(f"  Optimal PnL: {optimal_pnl:.2f} (cash: {cash:.2f}, MTM: {mtm:.2f})")
    print(f"  Final position: {pos}")
    print(f"  Number of actions: {len(trajectory)}")

    return optimal_pnl, cash, mtm, pos, trajectory


# ============================================================================
# Analysis & Reporting
# ============================================================================

def analyze_trajectory(trajectory, product):
    """Break down the trajectory into PnL components."""
    take_pnl = 0
    take_count = 0
    taker_pnl = 0
    taker_count = 0
    resting_pnl = 0
    resting_count = 0
    combo_pnl = 0
    combo_count = 0

    for t in trajectory:
        action = t['action']
        cash = t['cash_delta']
        qty = abs(t['pos_after'] - t['pos_before'])

        if action.startswith('take_'):
            take_pnl += cash
            take_count += 1
        elif action.startswith('taker_'):
            taker_pnl += cash
            taker_count += 1
        elif action.startswith('resting_'):
            resting_pnl += cash
            resting_count += 1
        elif action.startswith('combo_'):
            combo_pnl += cash
            combo_count += 1
        # 'hold' excluded

    return {
        'take': (take_count, take_pnl),
        'taker': (taker_count, taker_pnl),
        'resting': (resting_count, resting_pnl),
        'combo': (combo_count, combo_pnl),
    }


def print_price_trajectory(ticks, product):
    """Print summary of price movement."""
    first_mid = ticks[0].mid_price
    last_mid = ticks[-1].mid_price
    min_mid = min(t.mid_price for t in ticks)
    max_mid = max(t.mid_price for t in ticks)
    avg_spread = sum(t.ask_prices[0] - t.bid_prices[0] for t in ticks if t.bid_prices and t.ask_prices) / len(ticks)

    print(f"\n  {product} Price Summary:")
    print(f"    First mid: {first_mid}, Last mid: {last_mid}, Move: {last_mid - first_mid:+.1f}")
    print(f"    Min mid: {min_mid}, Max mid: {max_mid}, Range: {max_mid - min_mid:.1f}")
    print(f"    Avg spread: {avg_spread:.1f}")


# ============================================================================
# Main
# ============================================================================

def main():
    prices_file = 'prosperity4bt/resources/round0/prices_round_0_day_0.csv'
    trades_file = 'prosperity4bt/resources/round0/trades_round_0_day_0.csv'

    print("=" * 70)
    print("  ORACLE MAXIMUM PnL CALCULATOR")
    print("  IMC Prosperity 4 - Round 0, Day 0 (2000 ticks)")
    print("=" * 70)

    # Load data
    print("\nLoading data...")
    prices_by_product, trades_by_product = load_data(prices_file, trades_file)
    trades_classified = classify_trades(prices_by_product, trades_by_product)

    for product in sorted(prices_by_product.keys()):
        ticks = prices_by_product[product]
        trades = trades_classified[product]
        print(f"\n{product}: {len(ticks)} ticks, {len(trades)} taker trades")

        taker_buys = sum(1 for t in trades if t.is_taker_buy)
        taker_sells = len(trades) - taker_buys
        print(f"  Taker buys: {taker_buys}, Taker sells: {taker_sells}")

        print_price_trajectory(ticks, product)

    # Run enhanced DP for each product
    total_pnl = 0
    total_cash = 0
    total_mtm = 0

    results = {}

    for product in sorted(prices_by_product.keys()):
        ticks = prices_by_product[product]
        trades = trades_classified[product]

        pnl, cash, mtm, final_pos, trajectory = dp_enhanced(
            ticks, trades, product, pos_limit=80
        )

        results[product] = {
            'pnl': pnl,
            'cash': cash,
            'mtm': mtm,
            'final_pos': final_pos,
            'trajectory': trajectory,
        }

        total_pnl += pnl
        total_cash += cash
        total_mtm += mtm

        # Analyze trajectory
        breakdown = analyze_trajectory(trajectory, product)

        print(f"\n  --- {product} Trajectory Breakdown ---")
        for source, (count, cash_flow) in breakdown.items():
            if count > 0:
                print(f"    {source}: {count} actions, cash flow: {cash_flow:,.0f}")

        # Show first 20 and last 10 actions
        print(f"\n  First 20 actions:")
        for t in trajectory[:20]:
            print(f"    t={t['timestamp']:>6} {t['action']:<40} pos: {t['pos_before']:>3} -> {t['pos_after']:>3}  cash: {t['cash_delta']:>10,.0f}  mid: {t['mid']}")
        if len(trajectory) > 30:
            print(f"    ... ({len(trajectory) - 30} more actions) ...")
        if len(trajectory) > 20:
            print(f"  Last 10 actions:")
            for t in trajectory[-10:]:
                print(f"    t={t['timestamp']:>6} {t['action']:<40} pos: {t['pos_before']:>3} -> {t['pos_after']:>3}  cash: {t['cash_delta']:>10,.0f}  mid: {t['mid']}")

    # Final summary
    print(f"\n{'='*70}")
    print(f"  FINAL RESULTS")
    print(f"{'='*70}")
    for product in sorted(results.keys()):
        r = results[product]
        print(f"  {product}:")
        print(f"    Total PnL:     {r['pnl']:>10,.2f}")
        print(f"    Cash PnL:      {r['cash']:>10,.2f}")
        print(f"    MTM (pos*mid): {r['mtm']:>10,.2f}")
        print(f"    Final pos:     {r['final_pos']:>10}")
        print(f"    Num actions:   {len(r['trajectory']):>10}")

    print(f"\n  TOTAL PnL:       {total_pnl:>10,.2f}")
    print(f"  Total Cash:      {total_cash:>10,.2f}")
    print(f"  Total MTM:       {total_mtm:>10,.2f}")
    print(f"\n  Our best score:  2,896")
    print(f"  Top team score:  4,949")
    print(f"  Oracle max:      {total_pnl:>,.0f}")
    print(f"  Gap to top:      {4949 - total_pnl:>+,.0f}")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()
