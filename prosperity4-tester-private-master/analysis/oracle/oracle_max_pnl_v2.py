"""
Oracle Maximum PnL Calculator v2 - More careful modeling.

Key insight from CLAUDE.md: The website order book IS the CSV order book for day 0
(100% match confirmed). BUT our orders do NOT change the book (static replay).
This means:
1. We CAN take from the book - the volume is there
2. Taking does NOT deplete volume for future ticks (book resets each tick from CSV)
3. Taker bot arrives independently - we intercept by being at best bid/ask

This changes everything: at each tick, taking from the book and intercepting the taker
are INDEPENDENT events. We can do BOTH:
- Take up to the full book volume (buy at ask or sell at bid)
- AND intercept the taker if one arrives
- AND have resting orders fill from MM quote changes

The position limit (80) is the ONLY constraint.

Also critical: the website shows ~12 MORE taker fills than the CSV for inside-spread MM
strategies. These extra fills are takers that only trade when our best+/-1 order provides
a better price. The CSV doesn't record these because they don't happen without our orders.
"""

import time
from collections import defaultdict

def load_data(prices_file, trades_file):
    prices = defaultdict(list)
    with open(prices_file) as f:
        for line in f.read().splitlines()[1:]:
            cols = line.split(';')
            ts = int(cols[1])
            product = cols[2]

            bid_prices, bid_volumes = [], []
            for idx in [3, 5, 7]:
                if cols[idx] == '': break
                bid_prices.append(int(cols[idx]))
                bid_volumes.append(int(cols[idx + 1]))

            ask_prices, ask_volumes = [], []
            for idx in [9, 11, 13]:
                if cols[idx] == '': break
                ask_prices.append(int(cols[idx]))
                ask_volumes.append(int(cols[idx + 1]))

            mid = float(cols[15])
            prices[product].append({
                'ts': ts, 'mid': mid,
                'bid_prices': bid_prices, 'bid_volumes': bid_volumes,
                'ask_prices': ask_prices, 'ask_volumes': ask_volumes,
            })

    for p in prices:
        prices[p].sort(key=lambda x: x['ts'])

    trades = defaultdict(list)
    with open(trades_file) as f:
        for line in f.read().splitlines()[1:]:
            cols = line.split(';')
            ts = int(cols[0])
            sym = cols[3]
            price = int(float(cols[5]))
            qty = int(cols[6])
            trades[sym].append({'ts': ts, 'price': price, 'qty': qty})

    return prices, trades


def classify_trades(prices, trades):
    """Classify each trade as taker buy or sell."""
    classified = {}
    for product in trades:
        ts_to_mid = {t['ts']: t['mid'] for t in prices[product]}
        classified[product] = []
        for t in trades[product]:
            mid = ts_to_mid.get(t['ts'])
            if mid is None: continue
            is_buy = t['price'] >= mid
            classified[product].append({**t, 'is_buy': is_buy, 'mid': mid})
    return classified


def dp_max_pnl(ticks, trades_classified, product, pos_limit=80, verbose=True):
    """
    DP over position states with FULL action enumeration per tick.

    At each tick we can:
    1. Take from MM book: buy at ask levels, sell at bid levels
       - Volume limited by what's shown in the book
       - Book resets each tick (our takes don't persist)
    2. Intercept taker: if taker arrives, we can fill at bid or ask
       - Independent of book takes
    3. Resting fill: post order that fills when MM quotes move next tick
       - Independent of takes and taker

    All three can happen simultaneously! Position limit is the only constraint.

    State: position at start of tick
    For each state, enumerate all possible (position_change, cash_flow) tuples.
    """
    N = len(ticks)

    # Build trade index
    trades_at = defaultdict(list)
    for t in trades_classified:
        ts_idx = None
        for i, tick in enumerate(ticks):
            if tick['ts'] == t['ts']:
                ts_idx = i
                break
        if ts_idx is not None:
            trades_at[ts_idx].append(t)

    final_mid = ticks[N-1]['mid']

    # DP backward
    # dp[pos] = max total PnL (cash + final MTM) achievable from this tick onward
    dp_next = {pos: pos * final_mid for pos in range(-pos_limit, pos_limit + 1)}

    # For trajectory reconstruction
    best_actions = [{} for _ in range(N)]

    t0 = time.time()

    for i in range(N - 1, -1, -1):
        tick = ticks[i]
        bb = tick['bid_prices'][0] if tick['bid_prices'] else None
        ba = tick['ask_prices'][0] if tick['ask_prices'] else None

        if i % 500 == 0 and verbose:
            print(f"  Tick {i}/{N} ({time.time()-t0:.1f}s)")

        dp_curr = {}

        for pos in range(-pos_limit, pos_limit + 1):
            best_val = dp_next[pos]
            best_act = 'hold'

            if bb is None or ba is None:
                dp_curr[pos] = best_val
                best_actions[i][pos] = best_act
                continue

            # === Build list of independent fill sources ===
            # Source 1: Take from book (buy at ask levels)
            book_buys = []  # (price, max_qty) - buying from asks
            for lvl in range(len(tick['ask_prices'])):
                book_buys.append((tick['ask_prices'][lvl], tick['ask_volumes'][lvl]))

            # Source 2: Take from book (sell at bid levels)
            book_sells = []  # (price, max_qty) - selling to bids
            for lvl in range(len(tick['bid_prices'])):
                book_sells.append((tick['bid_prices'][lvl], tick['bid_volumes'][lvl]))

            # Source 3: Taker interception
            taker_buys_from_us = []  # We sell to taker (taker is buying)
            taker_sells_to_us = []   # We buy from taker (taker is selling)
            for td in trades_at.get(i, []):
                if td['is_buy']:
                    # Taker buys: we can sell at ask or ask-1
                    taker_buys_from_us.append((ba, td['qty']))  # sell at ask
                    if ba - 1 > bb:
                        taker_buys_from_us.append((ba - 1, td['qty']))  # inside
                else:
                    # Taker sells: we can buy at bid or bid+1
                    taker_sells_to_us.append((bb, td['qty']))
                    if bb + 1 < ba:
                        taker_sells_to_us.append((bb + 1, td['qty']))

            # Source 4: Resting fills (from quote changes)
            resting_buys = []  # We buy via resting order
            resting_sells = []  # We sell via resting order
            if i + 1 < N:
                nt = ticks[i + 1]
                nba = nt['ask_prices'][0] if nt['ask_prices'] else None
                nbb = nt['bid_prices'][0] if nt['bid_prices'] else None

                # Resting buy at bid+1: fills if next ask <= bid+1
                rbp = bb + 1
                if nba is not None and nba <= rbp:
                    vol = sum(nt['ask_volumes'][l] for l in range(len(nt['ask_prices']))
                              if nt['ask_prices'][l] <= rbp)
                    if vol > 0:
                        resting_buys.append((rbp, min(vol, 80)))

                # Resting sell at ask-1: fills if next bid >= ask-1
                rsp = ba - 1
                if nbb is not None and nbb >= rsp:
                    vol = sum(nt['bid_volumes'][l] for l in range(len(nt['bid_prices']))
                              if nt['bid_prices'][l] >= rsp)
                    if vol > 0:
                        resting_sells.append((rsp, min(vol, 80)))

            # === Enumerate actions ===
            # Single actions first (fast path for most ticks)

            # Buy from book
            cum_q, cum_cost = 0, 0
            for ap, av in book_buys:
                for q in range(1, min(av, pos_limit - pos - cum_q) + 1):
                    nq = cum_q + q
                    nc = cum_cost + ap * q
                    new_pos = pos + nq
                    if new_pos <= pos_limit:
                        val = -nc + dp_next[new_pos]
                        if val > best_val:
                            best_val = val
                            best_act = f'book_buy_{nq}'
                cum_q += min(av, pos_limit - pos - cum_q)
                cum_cost += ap * min(av, max(0, pos_limit - pos - (cum_q - min(av, pos_limit - pos - (cum_q - av)))))
                if cum_q >= pos_limit - pos:
                    break

            # Actually let me simplify: just try buying total of Q units walking up ask levels
            max_buy_from_book = min(sum(av for _, av in book_buys), pos_limit - pos)
            if max_buy_from_book > 0:
                # Walk through ask levels
                for total_buy_q in range(1, max_buy_from_book + 1):
                    # Cost: fill from best ask up
                    cost = 0
                    remaining = total_buy_q
                    for ap, av in book_buys:
                        fill = min(remaining, av)
                        cost += ap * fill
                        remaining -= fill
                        if remaining <= 0:
                            break
                    new_pos = pos + total_buy_q
                    val = -cost + dp_next[new_pos]
                    if val > best_val:
                        best_val = val
                        best_act = f'book_buy_{total_buy_q}@avg{cost/total_buy_q:.0f}'

            # Sell to book
            max_sell_from_book = min(sum(bv for _, bv in book_sells), pos_limit + pos)
            if max_sell_from_book > 0:
                for total_sell_q in range(1, max_sell_from_book + 1):
                    revenue = 0
                    remaining = total_sell_q
                    for bp, bv in book_sells:
                        fill = min(remaining, bv)
                        revenue += bp * fill
                        remaining -= fill
                        if remaining <= 0:
                            break
                    new_pos = pos - total_sell_q
                    val = revenue + dp_next[new_pos]
                    if val > best_val:
                        best_val = val
                        best_act = f'book_sell_{total_sell_q}@avg{revenue/total_sell_q:.0f}'

            # Taker interception (sell to buying taker)
            for tp, tq in taker_buys_from_us:
                for q in range(1, min(tq, pos_limit + pos) + 1):
                    new_pos = pos - q
                    val = tp * q + dp_next[new_pos]
                    if val > best_val:
                        best_val = val
                        best_act = f'taker_sell_{q}@{tp}'

            # Taker interception (buy from selling taker)
            for tp, tq in taker_sells_to_us:
                for q in range(1, min(tq, pos_limit - pos) + 1):
                    new_pos = pos + q
                    val = -tp * q + dp_next[new_pos]
                    if val > best_val:
                        best_val = val
                        best_act = f'taker_buy_{q}@{tp}'

            # Resting buys
            for rp, rq in resting_buys:
                for q in range(1, min(rq, pos_limit - pos) + 1):
                    new_pos = pos + q
                    val = -rp * q + dp_next[new_pos]
                    if val > best_val:
                        best_val = val
                        best_act = f'rest_buy_{q}@{rp}'

            # Resting sells
            for rp, rq in resting_sells:
                for q in range(1, min(rq, pos_limit + pos) + 1):
                    new_pos = pos - q
                    val = rp * q + dp_next[new_pos]
                    if val > best_val:
                        best_val = val
                        best_act = f'rest_sell_{q}@{rp}'

            # === COMBOS: book_take + taker_intercept ===
            # These are independent: we take from MM book AND intercept taker

            # Book buy + taker sell (both buys for us from different sources)
            for bp_price, bp_qty in book_buys[:1]:  # best ask only for speed
                for tp, tq in taker_buys_from_us[:1]:
                    max_book = min(bp_qty, pos_limit - pos)
                    for bq in range(0, max_book + 1):
                        max_taker = min(tq, pos_limit + pos + bq)  # after book buy, before taker sell
                        # Wait - book buy increases pos, taker sell decreases pos
                        # Net: pos + bq - sq
                        for sq in range(0, max_taker + 1):
                            if bq == 0 and sq == 0: continue
                            net_pos = pos + bq - sq
                            if -pos_limit <= net_pos <= pos_limit:
                                # Check intermediate: pos+bq <= pos_limit
                                if pos + bq <= pos_limit:
                                    cash = -bp_price * bq + tp * sq
                                    val = cash + dp_next[net_pos]
                                    if val > best_val:
                                        best_val = val
                                        best_act = f'combo_bbuy{bq}+tsell{sq}'

            # Book sell + taker buy (both fills for different sources)
            for sp_price, sp_qty in book_sells[:1]:
                for tp, tq in taker_sells_to_us[:1]:
                    max_book_sell = min(sp_qty, pos_limit + pos)
                    for sq in range(0, max_book_sell + 1):
                        max_taker_buy = min(tq, pos_limit - pos + sq)
                        for bq in range(0, max_taker_buy + 1):
                            if bq == 0 and sq == 0: continue
                            net_pos = pos - sq + bq
                            if -pos_limit <= net_pos <= pos_limit:
                                if pos - sq >= -pos_limit:
                                    cash = sp_price * sq - tp * bq
                                    val = cash + dp_next[net_pos]
                                    if val > best_val:
                                        best_val = val
                                        best_act = f'combo_bsell{sq}+tbuy{bq}'

            # Book buy + taker buy (both increase position)
            for bp_price, bp_qty in book_buys[:1]:
                for tp, tq in taker_sells_to_us[:1]:
                    for bq in range(0, min(bp_qty, pos_limit - pos) + 1):
                        for tbq in range(0, min(tq, pos_limit - pos - bq) + 1):
                            if bq == 0 and tbq == 0: continue
                            net_pos = pos + bq + tbq
                            if net_pos <= pos_limit:
                                cash = -bp_price * bq - tp * tbq
                                val = cash + dp_next[net_pos]
                                if val > best_val:
                                    best_val = val
                                    best_act = f'combo_bbuy{bq}+tbuy{tbq}'

            # Book sell + taker sell (both decrease position)
            for sp_price, sp_qty in book_sells[:1]:
                for tp, tq in taker_buys_from_us[:1]:
                    for sq in range(0, min(sp_qty, pos_limit + pos) + 1):
                        for tsq in range(0, min(tq, pos_limit + pos - sq) + 1):
                            if sq == 0 and tsq == 0: continue
                            net_pos = pos - sq - tsq
                            if net_pos >= -pos_limit:
                                cash = sp_price * sq + tp * tsq
                                val = cash + dp_next[net_pos]
                                if val > best_val:
                                    best_val = val
                                    best_act = f'combo_bsell{sq}+tsell{tsq}'

            # Resting + taker combos
            for rp, rq in resting_buys[:1]:
                for tp, tq in taker_buys_from_us[:1]:
                    for rbq in range(0, min(rq, pos_limit - pos) + 1):
                        for tsq in range(0, min(tq, pos_limit + pos + rbq) + 1):
                            if rbq == 0 and tsq == 0: continue
                            net_pos = pos + rbq - tsq
                            if -pos_limit <= net_pos <= pos_limit and pos + rbq <= pos_limit:
                                cash = -rp * rbq + tp * tsq
                                val = cash + dp_next[net_pos]
                                if val > best_val:
                                    best_val = val
                                    best_act = f'combo_rbuy{rbq}+tsell{tsq}'

            for rp, rq in resting_sells[:1]:
                for tp, tq in taker_sells_to_us[:1]:
                    for rsq in range(0, min(rq, pos_limit + pos) + 1):
                        for tbq in range(0, min(tq, pos_limit - pos + rsq) + 1):
                            if rsq == 0 and tbq == 0: continue
                            net_pos = pos - rsq + tbq
                            if -pos_limit <= net_pos <= pos_limit and pos - rsq >= -pos_limit:
                                cash = rp * rsq - tp * tbq
                                val = cash + dp_next[net_pos]
                                if val > best_val:
                                    best_val = val
                                    best_act = f'combo_rsell{rsq}+tbuy{tbq}'

            # Resting + book combos
            for rp, rq in resting_buys[:1]:
                for bp, bq_max in book_sells[:1]:
                    for rbq in range(0, min(rq, pos_limit - pos) + 1):
                        for bsq in range(0, min(bq_max, pos_limit + pos + rbq) + 1):
                            if rbq == 0 and bsq == 0: continue
                            # Actually these happen at different times
                            # Resting buy fills on next tick, book sell fills now
                            # But position constraint applies: after book sell, pos-bsq must be >= -limit
                            # After resting buy fills later, but we're only tracking NET effect for DP
                            # THIS IS WRONG - we can't combine across ticks in a single DP state
                            # Skip this - resting fills happen on a different tick
                            pass

            dp_curr[pos] = best_val
            best_actions[i][pos] = best_act

        dp_next = dp_curr

    optimal_pnl = dp_curr[0]

    # Reconstruct trajectory
    pos = 0
    cash = 0
    trajectory = []
    trade_counts = defaultdict(int)
    trade_cash = defaultdict(float)
    trade_qty = defaultdict(int)

    for i in range(N):
        act = best_actions[i][pos]
        if act == 'hold':
            continue

        tick = ticks[i]
        bb = tick['bid_prices'][0] if tick['bid_prices'] else 0
        ba = tick['ask_prices'][0] if tick['ask_prices'] else 0

        # Parse action to get new position and cash
        # This is tricky with combos; let's re-derive from action string
        # Instead, let's just track the position change
        old_pos = pos

        # Simple actions
        if act.startswith('book_buy_'):
            parts = act.split('_')
            qty_part = parts[2].split('@')[0]
            q = int(qty_part)
            # Compute cost
            cost = 0
            remaining = q
            for ap, av in zip(tick['ask_prices'], tick['ask_volumes']):
                fill = min(remaining, av)
                cost += ap * fill
                remaining -= fill
                if remaining <= 0: break
            cash -= cost
            pos += q
            source = 'take'
        elif act.startswith('book_sell_'):
            parts = act.split('_')
            qty_part = parts[2].split('@')[0]
            q = int(qty_part)
            revenue = 0
            remaining = q
            for bp, bv in zip(tick['bid_prices'], tick['bid_volumes']):
                fill = min(remaining, bv)
                revenue += bp * fill
                remaining -= fill
                if remaining <= 0: break
            cash += revenue
            pos -= q
            source = 'take'
        elif act.startswith('taker_sell_'):
            parts = act.split('_')
            q = int(parts[2].split('@')[0])
            p = int(parts[2].split('@')[1])
            cash += p * q
            pos -= q
            source = 'taker_intercept'
        elif act.startswith('taker_buy_'):
            parts = act.split('_')
            q = int(parts[2].split('@')[0])
            p = int(parts[2].split('@')[1])
            cash -= p * q
            pos += q
            source = 'taker_intercept'
        elif act.startswith('rest_buy_'):
            parts = act.split('_')
            q = int(parts[2].split('@')[0])
            p = int(parts[2].split('@')[1])
            cash -= p * q
            pos += q
            source = 'resting'
        elif act.startswith('rest_sell_'):
            parts = act.split('_')
            q = int(parts[2].split('@')[0])
            p = int(parts[2].split('@')[1])
            cash += p * q
            pos -= q
            source = 'resting'
        elif act.startswith('combo_'):
            # Parse combo actions
            # Format: combo_bbuy3+tsell5, combo_bsell4+tbuy2, etc.
            inner = act[6:]  # remove 'combo_'
            parts = inner.split('+')
            source = 'combo'
            for part in parts:
                if part.startswith('bbuy'):
                    q = int(part[4:])
                    if q > 0:
                        cost = tick['ask_prices'][0] * q  # simplified
                        cash -= cost
                        pos += q
                elif part.startswith('bsell'):
                    q = int(part[5:])
                    if q > 0:
                        rev = tick['bid_prices'][0] * q
                        cash += rev
                        pos -= q
                elif part.startswith('tsell'):
                    q = int(part[5:])
                    if q > 0:
                        rev = ba * q  # sell to buying taker at ask
                        cash += rev
                        pos -= q
                elif part.startswith('tbuy'):
                    q = int(part[4:])
                    if q > 0:
                        cost = bb * q  # buy from selling taker at bid
                        cash -= cost
                        pos += q
                elif part.startswith('rbuy'):
                    q = int(part[4:])
                    if q > 0:
                        rbp = bb + 1
                        cash -= rbp * q
                        pos += q
                elif part.startswith('rsell'):
                    q = int(part[5:])
                    if q > 0:
                        rsp = ba - 1
                        cash += rsp * q
                        pos -= q
        else:
            source = 'unknown'

        delta_pos = pos - old_pos
        trade_counts[source] += 1
        trade_qty[source] += abs(delta_pos)

        trajectory.append({
            'tick': i, 'ts': tick['ts'], 'action': act,
            'pos_before': old_pos, 'pos_after': pos,
            'mid': tick['mid'],
        })

    mtm = pos * final_mid

    elapsed = time.time() - t0
    if verbose:
        print(f"\n  DP completed in {elapsed:.1f}s")
        print(f"  Optimal total PnL: {optimal_pnl:.2f}")
        print(f"  Cash: {cash:.2f}, MTM: {mtm:.2f}, Check: {cash + mtm:.2f}")
        print(f"  Final position: {pos}")
        print(f"  Actions: {len(trajectory)}")
        print(f"\n  By source:")
        for s in sorted(trade_counts.keys()):
            print(f"    {s}: {trade_counts[s]} actions, {trade_qty[s]} units")

    return optimal_pnl, cash, mtm, pos, trajectory


def main():
    prices_file = 'prosperity4bt/resources/round0/prices_round_0_day_0.csv'
    trades_file = 'prosperity4bt/resources/round0/trades_round_0_day_0.csv'

    print("=" * 70)
    print("  ORACLE MAXIMUM PnL CALCULATOR v2")
    print("  IMC Prosperity 4 - Round 0, Day 0 (2000 ticks)")
    print("  Static book model (our orders don't change the book)")
    print("=" * 70)

    prices, trades = load_data(prices_file, trades_file)
    classified = classify_trades(prices, trades)

    # Summary
    for product in sorted(prices.keys()):
        ticks = prices[product]
        tc = classified[product]
        buys = sum(1 for t in tc if t['is_buy'])
        sells = len(tc) - buys
        total_qty = sum(t['qty'] for t in tc)
        first_mid = ticks[0]['mid']
        last_mid = ticks[-1]['mid']
        avg_spread = sum(t['ask_prices'][0] - t['bid_prices'][0] for t in ticks
                        if t['ask_prices'] and t['bid_prices']) / len(ticks)
        print(f"\n  {product}: {len(ticks)} ticks")
        print(f"    Mid: {first_mid} -> {last_mid} ({last_mid - first_mid:+.1f})")
        print(f"    Avg spread: {avg_spread:.1f}")
        print(f"    Taker trades: {len(tc)} ({buys} buys, {sells} sells), {total_qty} total units")

    # === Run DP for each product ===
    total_pnl = 0
    results = {}

    for product in sorted(prices.keys()):
        print(f"\n{'='*70}")
        print(f"  Running DP for {product}...")
        print(f"{'='*70}")

        pnl, cash, mtm, final_pos, trajectory = dp_max_pnl(
            prices[product], classified[product], product, pos_limit=80
        )

        results[product] = {'pnl': pnl, 'cash': cash, 'mtm': mtm,
                           'final_pos': final_pos, 'trajectory': trajectory}
        total_pnl += pnl

        # Show key trades
        if trajectory:
            print(f"\n  First 15 actions:")
            for t in trajectory[:15]:
                print(f"    t={t['ts']:>6} {t['action']:<45} pos:{t['pos_before']:>4}->{t['pos_after']:>4} mid={t['mid']}")
            if len(trajectory) > 25:
                print(f"    ... ({len(trajectory)-25} more) ...")
            print(f"  Last 10 actions:")
            for t in trajectory[-10:]:
                print(f"    t={t['ts']:>6} {t['action']:<45} pos:{t['pos_before']:>4}->{t['pos_after']:>4} mid={t['mid']}")

    # === ALSO: Compute theoretical bounds ===
    print(f"\n{'='*70}")
    print(f"  THEORETICAL BOUNDS ANALYSIS")
    print(f"{'='*70}")

    for product in sorted(prices.keys()):
        ticks = prices[product]
        tc = classified[product]
        N = len(ticks)

        # Bound 1: Pure taker interception (no book takes, no MTM)
        # Buy from taker sells at bid, sell to taker buys at ask
        taker_pnl_raw = 0
        for t in tc:
            tick_data = None
            for td in ticks:
                if td['ts'] == t['ts']:
                    tick_data = td
                    break
            if tick_data is None: continue
            bb = tick_data['bid_prices'][0]
            ba = tick_data['ask_prices'][0]
            spread = ba - bb
            half_spread = spread / 2
            taker_pnl_raw += half_spread * t['qty']

        # Bound 2: Maximum from book takes (mid changes)
        # If we could buy at ask when price is about to go up, sell at bid when about to go down
        mid_changes = []
        for j in range(1, N):
            dm = ticks[j]['mid'] - ticks[j-1]['mid']
            if dm != 0:
                mid_changes.append((j-1, dm, ticks[j-1]))

        # Maximum from directional book takes at each mid change
        dir_pnl = 0
        for idx, dm, td in mid_changes:
            if dm > 0:
                # Price going up: buy at ask, gain dm per unit
                max_q = min(sum(td['ask_volumes']), 80)
                edge = dm - (td['ask_prices'][0] - td['mid'])  # edge = dm - half_spread
                if edge > 0:
                    dir_pnl += edge * max_q
            else:
                max_q = min(sum(td['bid_volumes']), 80)
                edge = abs(dm) - (td['mid'] - td['bid_prices'][0])
                if edge > 0:
                    dir_pnl += edge * max_q

        print(f"\n  {product}:")
        print(f"    Taker interception (half-spread * qty, no pos limit): {taker_pnl_raw:.0f}")
        print(f"    Directional book takes (edge per mid change):        {dir_pnl:.0f}")
        print(f"    DP optimal (with position limits + combos):          {results[product]['pnl']:.0f}")

    # === Final Summary ===
    print(f"\n{'='*70}")
    print(f"  FINAL RESULTS")
    print(f"{'='*70}")

    for product in sorted(results.keys()):
        r = results[product]
        print(f"  {product}:")
        print(f"    Total PnL:       {r['pnl']:>10,.2f}")
        print(f"    Cash PnL:        {r['cash']:>10,.2f}")
        print(f"    MTM:             {r['mtm']:>10,.2f}")
        print(f"    Final position:  {r['final_pos']:>10}")

    print(f"\n  {'TOTAL PnL':>20}: {total_pnl:>10,.2f}")
    print(f"  {'Our best (s36)':>20}: {2896:>10,}")
    print(f"  {'Top team':>20}: {4949:>10,}")
    print(f"  {'Oracle max':>20}: {total_pnl:>10,.0f}")
    print(f"  {'Oracle - top':>20}: {total_pnl - 4949:>+10,.0f}")
    print(f"  {'Efficiency (ours)':>20}: {2896/total_pnl*100:>9.1f}%")
    print(f"  {'Efficiency (top)':>20}: {4949/total_pnl*100:>9.1f}%")

    # Also compute what's achievable without any book takes (taker only + MTM)
    print(f"\n  --- Achievability Analysis ---")
    print(f"  NOTE: Website has ~12 more TOMATOES taker fills than CSV")
    print(f"  NOTE: EMERALDS mid = 10000 (flat), so EM PnL is pure spread capture")
    print(f"  NOTE: TOMATOES mid drops 9.5 over 2000 ticks")

    # What if we add 12 extra TOMATOES fills?
    # Average TOMATOES half-spread = 6.55, average taker qty = 3.4
    extra_fills = 12
    avg_half_spread_tom = 6.55
    avg_taker_qty = 240 / 70  # from data
    extra_pnl = extra_fills * avg_half_spread_tom * avg_taker_qty
    print(f"\n  Extra PnL from ~12 additional TOMATOES taker fills: ~{extra_pnl:.0f}")
    print(f"  Adjusted total: {total_pnl + extra_pnl:.0f}")

    print(f"\n{'='*70}")


if __name__ == '__main__':
    main()
