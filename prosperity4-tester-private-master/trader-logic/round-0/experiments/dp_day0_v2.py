"""
DP backward induction on day 0 — volume-constrained.
Uses actual L1+L2 volumes and prices from god logger.
Models price impact: L1 fills at ba, L2 fills at ba+1 (ask2).
"""
import json

with open('c:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/run-logs/round-0/troll/8678/8678.log') as f:
    data = json.load(f)

al_lines = data['activitiesLog'].strip().split('\n')[1:]

# Build full book: L1 + L2 prices and volumes
books = {}
for line in al_lines:
    f = line.split(';')
    ts = int(f[1]); prod = f[2]
    if ts not in books: books[ts] = {}
    books[ts][prod] = {
        'bp1': int(f[3]) if f[3] else None,
        'bv1': int(f[4]) if f[4] else 0,
        'bp2': int(f[5]) if f[5] else None,
        'bv2': int(f[6]) if f[6] else 0,
        'ap1': int(f[9]) if f[9] else None,
        'av1': int(f[10]) if f[10] else 0,
        'ap2': int(f[11]) if f[11] else None,
        'av2': int(f[12]) if f[12] else 0,
        'mid': float(f[15]),
    }

timestamps = sorted(books.keys())
N = len(timestamps)

LIMIT = 80
final_mid = books[timestamps[-1]]['TOMATOES']['mid']
print(f"Ticks: {N}, Final mid: {final_mid}")


def buy_cost(book, qty):
    """Cost to buy `qty` units, sweeping L1 then L2. Returns (cost, filled)."""
    if book['ap1'] is None:
        return 0, 0
    filled = 0; cost = 0
    # L1
    take_l1 = min(qty, book['av1'])
    cost += book['ap1'] * take_l1
    filled += take_l1
    qty -= take_l1
    # L2
    if qty > 0 and book['ap2'] is not None and book['av2'] > 0:
        take_l2 = min(qty, book['av2'])
        cost += book['ap2'] * take_l2
        filled += take_l2
    return cost, filled


def sell_revenue(book, qty):
    """Revenue from selling `qty` units, sweeping L1 then L2. Returns (revenue, filled)."""
    if book['bp1'] is None:
        return 0, 0
    filled = 0; rev = 0
    # L1
    take_l1 = min(qty, book['bv1'])
    rev += book['bp1'] * take_l1
    filled += take_l1
    qty -= take_l1
    # L2
    if qty > 0 and book['bp2'] is not None and book['bv2'] > 0:
        take_l2 = min(qty, book['bv2'])
        rev += book['bp2'] * take_l2
        filled += take_l2
    return rev, filled


# Precompute max fills and costs at each tick
max_buy = []  # (max_qty, avg_cost_per_unit) at each tick
max_sell = []
for ts in timestamps:
    b = books[ts]['TOMATOES']
    # Max buy = L1 + L2 ask volume
    mb = b['av1'] + b['av2']
    cost, filled = buy_cost(b, mb)
    max_buy.append((filled, cost))
    # Max sell = L1 + L2 bid volume
    ms = b['bv1'] + b['bv2']
    rev, filled = sell_revenue(b, ms)
    max_sell.append((filled, rev))

print(f"Avg max buy per tick: {sum(m[0] for m in max_buy)/N:.1f}")
print(f"Avg max sell per tick: {sum(m[0] for m in max_sell)/N:.1f}")

# DP
# State: position (-80 to +80)
# dp[pos_idx] = best cash + MTM from here to end
POS_OFF = LIMIT
dp = [float('-inf')] * (2 * LIMIT + 1)
action = [[0] * (2 * LIMIT + 1) for _ in range(N)]

# Terminal: MTM
for pos in range(-LIMIT, LIMIT + 1):
    dp[pos + POS_OFF] = pos * final_mid

print("Running backward DP with volume constraints...")

for i in range(N - 2, -1, -1):
    ts = timestamps[i]
    b = books[ts]['TOMATOES']
    new_dp = [float('-inf')] * (2 * LIMIT + 1)

    # Max fills this tick
    mb_qty, _ = max_buy[i]
    ms_qty, _ = max_sell[i]

    for pos in range(-LIMIT, LIMIT + 1):
        pi = pos + POS_OFF
        best_val = float('-inf')
        best_delta = 0

        # Possible buy deltas: 0 to min(max_buy, capacity)
        can_buy = min(mb_qty, LIMIT - pos)
        can_sell = min(ms_qty, LIMIT + pos)

        # Try key delta values (not all — too slow for 161 x 2000)
        # 0, and multiples of L1 volume up to max
        deltas = {0}
        for d in range(1, can_buy + 1):
            deltas.add(d)
            if d > 15: break  # cap enumeration
        for d in range(1, can_sell + 1):
            deltas.add(-d)
            if d > 15: break
        # Also try exact L1 volumes
        if b['av1'] > 0: deltas.add(min(b['av1'], can_buy))
        if b['bv1'] > 0: deltas.add(-min(b['bv1'], can_sell))
        # And max fills
        deltas.add(can_buy)
        deltas.add(-can_sell)

        for delta in deltas:
            new_pos = pos + delta
            if new_pos < -LIMIT or new_pos > LIMIT:
                continue

            if delta > 0:
                cost, filled = buy_cost(b, delta)
                if filled < delta:
                    continue  # can't fill this much
                cash_change = -cost
            elif delta < 0:
                rev, filled = sell_revenue(b, abs(delta))
                if filled < abs(delta):
                    continue
                cash_change = rev
            else:
                cash_change = 0

            val = cash_change + dp[new_pos + POS_OFF]
            if val > best_val:
                best_val = val
                best_delta = delta

        new_dp[pi] = best_val
        action[i][pi] = best_delta

    dp = new_dp

    if i % 200 == 0:
        print(f"  tick {i} (ts={ts}): best from pos=0 = {dp[POS_OFF]:.0f}")

# Forward pass
pos = 0
total_cash = 0
trajectory = []
for i in range(N - 1):
    ts = timestamps[i]
    delta = action[i][pos + POS_OFF]
    b = books[ts]['TOMATOES']

    if delta > 0:
        cost, _ = buy_cost(b, delta)
        total_cash -= cost
    elif delta < 0:
        rev, _ = sell_revenue(b, abs(delta))
        total_cash += rev

    pos += delta
    if delta != 0:
        trajectory.append((ts, delta, pos, total_cash + pos * b['mid']))

final_pnl = total_cash + pos * final_mid

print(f"\n{'='*60}")
print(f"DP OPTIMAL (volume-constrained) TOMATOES PnL: {final_pnl:.0f}")
print(f"Final position: {pos}")
print(f"Trades: {len(trajectory)}")
print(f"\nTrajectory (first 20):")
for ts, delta, p, pnl in trajectory[:20]:
    print(f"  ts={ts:>6d}: delta={delta:+3d} pos={p:+4d} cumPnL={pnl:.0f}")
print(f"\nTrajectory (last 10):")
for ts, delta, p, pnl in trajectory[-10:]:
    print(f"  ts={ts:>6d}: delta={delta:+3d} pos={p:+4d} cumPnL={pnl:.0f}")

# Generate oracle
oracle = {}
for ts, delta, p, pnl in trajectory:
    oracle[ts] = delta

o_str = ','.join(f'{ts}:{d}' for ts, d in sorted(oracle.items()))
print(f"\n# Oracle ({len(oracle)} entries):")
print(f'DP={{{o_str}}}')
