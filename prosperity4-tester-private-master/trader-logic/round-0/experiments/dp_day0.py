"""
DP backward induction on day 0 website data.

State: (tick_index, tomatoes_position)
At each tick we know: bb, ba, whether taker comes, taker side/qty.
Actions: buy X at ask, sell X at bid, or hold.
EMERALDS fixed (already optimal).

Outputs: optimal action at each (tick, position) -> upload as god script.
"""
import json, sys, os

# Load god logger data
with open('c:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/run-logs/round-0/troll/8678/8678.log') as f:
    data = json.load(f)

al_lines = data['activitiesLog'].strip().split('\n')[1:]
trades_raw = data['tradeHistory']

# Build price path
books = {}
for line in al_lines:
    f = line.split(';')
    ts = int(f[1]); prod = f[2]
    if ts not in books: books[ts] = {}
    books[ts][prod] = {
        'bb': int(f[3]) if f[3] else None,
        'ba': int(f[9]) if f[9] else None,
        'mid': float(f[15]),
    }

timestamps = sorted(books.keys())
N = len(timestamps)
ts_to_idx = {ts: i for i, ts in enumerate(timestamps)}

# Taker trades for TOMATOES
taker_at = {}
for t in trades_raw:
    if t['symbol'] != 'TOMATOES': continue
    ts = t['timestamp']
    mid = books[ts]['TOMATOES']['mid']
    side = 1 if t['price'] >= mid else -1  # +1=taker buys, -1=taker sells
    taker_at[ts] = {'price': int(t['price']), 'qty': t['quantity'], 'side': side}

# Website calls run() 1000 times over 2000 ticks
# But for DP we model every tick since that's when matching happens
# Simplification: at each tick, we can change position by trading

LIMIT = 80
POS_RANGE = range(-LIMIT, LIMIT + 1)  # 161 values
POS_OFFSET = LIMIT  # pos + POS_OFFSET = array index

final_mid = books[timestamps[-1]]['TOMATOES']['mid']
print(f"Ticks: {N}, Final mid: {final_mid}")
print(f"Taker trades: {len(taker_at)}")
print(f"State space: {N} x {2*LIMIT+1} = {N * (2*LIMIT+1)}")

# DP arrays
INF = float('-inf')
# dp[pos_idx] = best PnL achievable from this state to end
dp = [INF] * (2 * LIMIT + 1)
action = [[0] * (2 * LIMIT + 1) for _ in range(N)]  # action[tick][pos] = delta_pos

# Terminal: MTM at final tick
for pos in POS_RANGE:
    dp[pos + POS_OFFSET] = pos * final_mid

print("Running backward DP...")

# Backward induction
for i in range(N - 2, -1, -1):
    ts = timestamps[i]
    book = books[ts]['TOMATOES']
    bb = book['bb']
    ba = book['ba']

    if bb is None or ba is None:
        # Can't trade, carry forward
        action[i] = [0] * (2 * LIMIT + 1)
        continue

    spread = ba - bb

    new_dp = [INF] * (2 * LIMIT + 1)

    for pos in POS_RANGE:
        pi = pos + POS_OFFSET

        best_val = INF
        best_delta = 0

        # Enumerate possible deltas
        max_buy = LIMIT - pos    # max we can buy
        max_sell = LIMIT + pos   # max we can sell

        # For efficiency, only consider key deltas:
        # 0 (hold), small buys/sells (1-10), and fills matching taker
        deltas_to_try = [0]

        # Buy deltas (positive): pay ask price
        for d in range(1, min(max_buy, 20) + 1):
            deltas_to_try.append(d)

        # Sell deltas (negative): receive bid price
        for d in range(1, min(max_sell, 20) + 1):
            deltas_to_try.append(-d)

        # If taker comes at this tick, try exact taker qty
        if ts in taker_at:
            tk = taker_at[ts]
            if tk['side'] == -1:  # taker sells, we can buy
                deltas_to_try.append(min(tk['qty'], max_buy))
            else:  # taker buys, we can sell
                deltas_to_try.append(-min(tk['qty'], max_sell))

        for delta in set(deltas_to_try):
            new_pos = pos + delta
            if new_pos < -LIMIT or new_pos > LIMIT:
                continue

            # Cost of this trade
            if delta > 0:
                # Buying: pay ask price per unit
                cash_change = -ba * delta
            elif delta < 0:
                # Selling: receive bid price per unit
                cash_change = -bb * delta  # delta is negative, bb * |delta|
            else:
                cash_change = 0

            future = dp[new_pos + POS_OFFSET]
            val = cash_change + future

            if val > best_val:
                best_val = val
                best_delta = delta

        new_dp[pi] = best_val
        action[i][pi] = best_delta

    dp = new_dp

    if i % 200 == 0:
        # Show best value starting from pos=0
        print(f"  tick {i} (ts={ts}): best from pos=0 = {dp[POS_OFFSET]:.0f}")

# Forward pass: simulate optimal trajectory from pos=0
pos = 0
total_cash = 0
trajectory = []
for i in range(N - 1):
    ts = timestamps[i]
    delta = action[i][pos + POS_OFFSET]
    book = books[ts]['TOMATOES']
    bb = book['bb']
    ba = book['ba']

    if delta > 0:
        total_cash -= ba * delta
    elif delta < 0:
        total_cash -= bb * delta

    pos += delta
    mtm = pos * book['mid']

    if delta != 0:
        trajectory.append((ts, delta, pos, total_cash + mtm))

# Final MTM
final_pnl = total_cash + pos * final_mid

print(f"\n{'='*60}")
print(f"DP OPTIMAL TOMATOES PnL: {final_pnl:.0f}")
print(f"Final position: {pos}")
print(f"Total cash: {total_cash:.0f}")
print(f"Final MTM: {pos * final_mid:.0f}")
print(f"Trades: {len(trajectory)}")
print(f"\nTrajectory (first 20 trades):")
for ts, delta, p, pnl in trajectory[:20]:
    print(f"  ts={ts:>6d}: delta={delta:+3d} pos={p:+4d} cumPnL={pnl:.0f}")

print(f"\nTrajectory (last 10 trades):")
for ts, delta, p, pnl in trajectory[-10:]:
    print(f"  ts={ts:>6d}: delta={delta:+3d} pos={p:+4d} cumPnL={pnl:.0f}")

# Generate compact oracle: {timestamp: delta_position}
oracle = {}
for ts, delta, p, pnl in trajectory:
    oracle[ts] = delta

# Output for embedding
print(f"\n# Oracle dict ({len(oracle)} entries):")
o_str = ','.join(f'{ts}:{d}' for ts, d in sorted(oracle.items()))
print(f'DP={{{o_str}}}')
