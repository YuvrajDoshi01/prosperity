"""
DP v3: Models both aggressive takes AND passive resting fills.

Key insight: taker trades are FREE position changes that EARN spread.
Instead of paying 6.5/unit to cross, we can wait for a taker to hit our
resting order and EARN 6.5/unit.

State: (tick_index, position)
Transitions:
  1. TAKE: buy at ask / sell at bid (costs spread)
  2. RESTING FILL: if taker arrives, our post at best±1 fills (earns spread)
  3. HOLD: do nothing

The problem: decide at each tick whether to take aggressively or
wait for the next taker trade to get a free/profitable fill.

This is like weighted interval scheduling — each taker trade is an
"opportunity window" to change position profitably.

Complexity: O(N * P * max_delta) = O(2000 * 161 * 30) ≈ 10M — fast.
"""
import json

with open('c:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/run-logs/round-0/troll/8678/8678.log') as f:
    data = json.load(f)

al_lines = data['activitiesLog'].strip().split('\n')[1:]
trades_raw = data['tradeHistory']

# Build book data
books = {}
for line in al_lines:
    f = line.split(';')
    ts = int(f[1]); prod = f[2]
    if ts not in books: books[ts] = {}
    books[ts][prod] = {
        'bb': int(f[3]) if f[3] else None,
        'bv1': int(f[4]) if f[4] else 0,
        'ba': int(f[9]) if f[9] else None,
        'av1': int(f[10]) if f[10] else 0,
        'bp2': int(f[5]) if f[5] else None,
        'bv2': int(f[6]) if f[6] else 0,
        'ap2': int(f[11]) if f[11] else None,
        'av2': int(f[12]) if f[12] else 0,
        'mid': float(f[15]),
    }

timestamps = sorted(books.keys())
N = len(timestamps)
ts_to_idx = {ts: i for i, ts in enumerate(timestamps)}

# Taker trades
taker_at = {}  # idx -> (qty, side, price)
for t in trades_raw:
    if t['symbol'] != 'TOMATOES': continue
    ts = t['timestamp']
    if ts not in ts_to_idx: continue
    idx = ts_to_idx[ts]
    mid = books[ts]['TOMATOES']['mid']
    side = 1 if t['price'] >= mid else -1  # +1=buys(hits ask), -1=sells(hits bid)
    taker_at[idx] = {'qty': t['quantity'], 'side': side, 'price': int(t['price'])}

LIMIT = 80
POS_OFF = LIMIT
final_mid = books[timestamps[-1]]['TOMATOES']['mid']
print(f"Ticks: {N}, Final mid: {final_mid}, Taker events: {len(taker_at)}")

# DP arrays
dp = [float('-inf')] * (2 * LIMIT + 1)
action = [[None] * (2 * LIMIT + 1) for _ in range(N)]

# Terminal
for pos in range(-LIMIT, LIMIT + 1):
    dp[pos + POS_OFF] = pos * final_mid

print("Running DP v3 (takes + resting fills)...")

for i in range(N - 2, -1, -1):
    ts = timestamps[i]
    b = books[ts]['TOMATOES']
    bb = b['bb']; ba = b['ba']
    new_dp = [float('-inf')] * (2 * LIMIT + 1)

    if bb is None or ba is None:
        for pos in range(-LIMIT, LIMIT + 1):
            new_dp[pos + POS_OFF] = dp[pos + POS_OFF]
            action[i][pos + POS_OFF] = ('hold', 0)
        dp = new_dp
        continue

    has_taker = i in taker_at
    if has_taker:
        tk = taker_at[i]

    for pos in range(-LIMIT, LIMIT + 1):
        pi = pos + POS_OFF
        best_val = float('-inf')
        best_action = ('hold', 0)

        can_buy = LIMIT - pos
        can_sell = LIMIT + pos

        # --- Option 1: HOLD ---
        val = dp[pi]
        if val > best_val:
            best_val = val
            best_action = ('hold', 0)

        # --- Option 2: AGGRESSIVE TAKE ---
        # Buy at ask (L1 then L2)
        for d in range(1, min(can_buy, b['av1'] + b['av2']) + 1):
            if d > 20: break  # cap enumeration
            new_pos = pos + d
            # Cost: L1 at ba, overflow at ap2
            l1_fill = min(d, b['av1'])
            l2_fill = d - l1_fill
            if l2_fill > 0 and (b['ap2'] is None or l2_fill > b['av2']):
                break
            cost = ba * l1_fill
            if l2_fill > 0:
                cost += b['ap2'] * l2_fill
            val = -cost + dp[new_pos + POS_OFF]
            if val > best_val:
                best_val = val
                best_action = ('take_buy', d)

        # Sell at bid (L1 then L2)
        for d in range(1, min(can_sell, b['bv1'] + b['bv2']) + 1):
            if d > 20: break
            new_pos = pos - d
            l1_fill = min(d, b['bv1'])
            l2_fill = d - l1_fill
            if l2_fill > 0 and (b['bp2'] is None or l2_fill > b['bv2']):
                break
            rev = bb * l1_fill
            if l2_fill > 0:
                rev += b['bp2'] * l2_fill
            val = rev + dp[new_pos + POS_OFF]
            if val > best_val:
                best_val = val
                best_action = ('take_sell', d)

        # --- Option 3: RESTING FILL (only if taker arrives) ---
        if has_taker:
            tq = tk['qty']
            if tk['side'] == -1:
                # Taker SELLS → hits bid. We can post buy at bb+1 to intercept.
                # We buy at bb+1 (better than ba!), earning spread
                fill_price = bb + 1
                fill_qty = min(tq, can_buy)
                if fill_qty > 0:
                    new_pos = pos + fill_qty
                    cost = fill_price * fill_qty
                    val = -cost + dp[new_pos + POS_OFF]
                    if val > best_val:
                        best_val = val
                        best_action = ('rest_buy', fill_qty)

                    # Also try partial fills
                    for fq in range(1, fill_qty):
                        new_pos2 = pos + fq
                        cost2 = fill_price * fq
                        val2 = -cost2 + dp[new_pos2 + POS_OFF]
                        if val2 > best_val:
                            best_val = val2
                            best_action = ('rest_buy', fq)

            else:
                # Taker BUYS → hits ask. We can post sell at ba-1 to intercept.
                fill_price = ba - 1
                fill_qty = min(tq, can_sell)
                if fill_qty > 0:
                    new_pos = pos - fill_qty
                    rev = fill_price * fill_qty
                    val = rev + dp[new_pos + POS_OFF]
                    if val > best_val:
                        best_val = val
                        best_action = ('rest_sell', fill_qty)

                    for fq in range(1, fill_qty):
                        new_pos2 = pos - fq
                        rev2 = fill_price * fq
                        val2 = rev2 + dp[new_pos2 + POS_OFF]
                        if val2 > best_val:
                            best_val = val2
                            best_action = ('rest_sell', fq)

            # --- Option 4: TAKE + RESTING combo ---
            # Take some aggressively AND intercept taker on same tick
            if tk['side'] == -1:
                # Taker sells → we can both take asks AND rest-buy
                rest_qty = min(tq, can_buy)
                rest_price = bb + 1
                for rq in range(1, rest_qty + 1):
                    remaining_buy = can_buy - rq
                    # Also take some asks
                    for tq2 in range(1, min(remaining_buy, b['av1']) + 1):
                        if tq2 > 10: break
                        new_pos = pos + rq + tq2
                        if new_pos > LIMIT: break
                        cost = rest_price * rq + ba * tq2
                        val = -cost + dp[new_pos + POS_OFF]
                        if val > best_val:
                            best_val = val
                            best_action = ('combo_buy', rq, tq2)
            else:
                rest_qty = min(tq, can_sell)
                rest_price = ba - 1
                for rq in range(1, rest_qty + 1):
                    remaining_sell = can_sell - rq
                    for tq2 in range(1, min(remaining_sell, b['bv1']) + 1):
                        if tq2 > 10: break
                        new_pos = pos - rq - tq2
                        if new_pos < -LIMIT: break
                        rev = rest_price * rq + bb * tq2
                        val = rev + dp[new_pos + POS_OFF]
                        if val > best_val:
                            best_val = val
                            best_action = ('combo_sell', rq, tq2)

        new_dp[pi] = best_val
        action[i][pi] = best_action

    dp = new_dp
    if i % 200 == 0:
        print(f"  tick {i} (ts={ts}): best from pos=0 = {dp[POS_OFF]:.0f}")

# Forward pass
pos = 0
total_cash = 0
trajectory = []
take_cost = 0
rest_profit = 0

for i in range(N - 1):
    ts = timestamps[i]
    b = books[ts]['TOMATOES']
    bb = b['bb']; ba = b['ba']
    act = action[i][pos + POS_OFF]

    if act is None or act[0] == 'hold':
        continue

    atype = act[0]
    if atype == 'take_buy':
        d = act[1]
        l1 = min(d, b['av1']); l2 = d - l1
        cost = ba * l1 + (b['ap2'] or 0) * l2
        total_cash -= cost
        take_cost += cost - (b['mid'] * d)  # cost above mid
        pos += d
    elif atype == 'take_sell':
        d = act[1]
        l1 = min(d, b['bv1']); l2 = d - l1
        rev = bb * l1 + (b['bp2'] or 0) * l2
        total_cash += rev
        take_cost += (b['mid'] * d) - rev  # revenue below mid
        pos -= d
    elif atype == 'rest_buy':
        d = act[1]
        price = bb + 1
        total_cash -= price * d
        rest_profit += (b['mid'] - price) * d
        pos += d
    elif atype == 'rest_sell':
        d = act[1]
        price = ba - 1
        total_cash += price * d
        rest_profit += (price - b['mid']) * d
        pos -= d
    elif atype == 'combo_buy':
        rq, tq = act[1], act[2]
        total_cash -= (bb + 1) * rq + ba * tq
        rest_profit += (b['mid'] - (bb + 1)) * rq
        take_cost += (ba - b['mid']) * tq
        pos += rq + tq
    elif atype == 'combo_sell':
        rq, tq = act[1], act[2]
        total_cash += (ba - 1) * rq + bb * tq
        rest_profit += ((ba - 1) - b['mid']) * rq
        take_cost += (b['mid'] - bb) * tq
        pos -= rq + tq

    trajectory.append((ts, atype, pos, total_cash + pos * b['mid']))

final_pnl = total_cash + pos * final_mid

print(f"\n{'='*60}")
print(f"DP v3 OPTIMAL TOMATOES PnL: {final_pnl:.0f}")
print(f"  Take spread cost: {take_cost:.0f}")
print(f"  Rest spread earned: {rest_profit:.0f}")
print(f"  Net spread: {rest_profit - take_cost:.0f}")
print(f"Final position: {pos}")
print(f"Trades: {len(trajectory)}")

# Count action types
from collections import Counter
types = Counter(a[1] for a in trajectory)
print(f"Action breakdown: {dict(types)}")

print(f"\nTrajectory (first 20):")
for ts, atype, p, pnl in trajectory[:20]:
    print(f"  ts={ts:>6d}: {atype:<12s} pos={p:+4d} cumPnL={pnl:.0f}")
print(f"\nTrajectory (last 10):")
for ts, atype, p, pnl in trajectory[-10:]:
    print(f"  ts={ts:>6d}: {atype:<12s} pos={p:+4d} cumPnL={pnl:.0f}")

# Oracle for embedding
oracle_takes = {}
oracle_rests = {}
for i in range(N - 1):
    act = action[i][0 + POS_OFF]  # from pos=0 (only accurate for first trade)

# Better: output the full action table for the trajectory
print(f"\n# Full trajectory ({len(trajectory)} actions):")
for ts, atype, p, pnl in trajectory:
    print(f"#  {ts}: {atype} -> pos={p}")
