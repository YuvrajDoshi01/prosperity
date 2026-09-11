"""Quick debug script to count signal activations from s37."""
import json, csv

# Read day 0 CSV data
data_file = '/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0/prices_round_0_day_0.csv'

rows = []
with open(data_file) as f:
    reader = csv.DictReader(f, delimiter=';')
    for row in reader:
        if row.get('product') == 'TOMATOES':
            rows.append(row)

# Extract mids
mids = []
for r in rows:
    bb = float(r['bid_price_1'])
    ba = float(r['ask_price_1'])
    mids.append((bb + ba) / 2)

# Compute dmid
dmids = [0.0] + [mids[i] - mids[i-1] for i in range(1, len(mids))]

VOL_WINDOW = 5
VOL_HIGH_THRESHOLD = 1.5
BURST_MOVE_THRESHOLD = 2.0
BURST_COUNT_TRIGGER = 2

high_vol_count = 0
burst_up_count = 0
burst_down_count = 0
carry_trigger_count = 0

for i in range(len(dmids)):
    # Rolling vol
    start = max(0, i - VOL_WINDOW + 1)
    window = [abs(d) for d in dmids[start:i+1]]
    rolling_vol = sum(window) / len(window) if window else 0

    if rolling_vol > VOL_HIGH_THRESHOLD:
        high_vol_count += 1

    # Burst detection
    if i >= BURST_COUNT_TRIGGER - 1:
        recent = dmids[i - BURST_COUNT_TRIGGER + 1:i + 1]
        if all(d >= BURST_MOVE_THRESHOLD for d in recent):
            burst_up_count += 1
        elif all(d <= -BURST_MOVE_THRESHOLD for d in recent):
            burst_down_count += 1

    # Carry trigger (bid change >= 4)
    if i > 0:
        bid_prev = float(rows[i-1]['bid_price_1'])
        bid_curr = float(rows[i]['bid_price_1'])
        if abs(bid_curr - bid_prev) >= 4:
            carry_trigger_count += 1

n = len(mids)
print(f"Day 0 TOMATOES: {n} ticks (first {min(n, 2000)} for website)")
print(f"  High-vol regime ticks: {high_vol_count} ({100*high_vol_count/n:.1f}%)")
print(f"  Burst UP detections: {burst_up_count}")
print(f"  Burst DOWN detections: {burst_down_count}")
print(f"  Carry trigger (bid change >=4): {carry_trigger_count}")
print(f"  Total dmid > 2: {sum(1 for d in dmids if abs(d) >= 2)}")
print(f"  Total dmid > 3: {sum(1 for d in dmids if abs(d) >= 3)}")

# How many ticks have pos > 30 during high vol?
# Can't know without running strategy, but show distribution of big moves
print(f"\n  Consecutive same-dir big moves:")
streak = 0
direction = None
streak_counts = {1: 0, 2: 0, 3: 0, 4: 0}
for d in dmids:
    if d >= BURST_MOVE_THRESHOLD:
        if direction == 'up':
            streak += 1
        else:
            if streak > 0 and direction:
                streak_counts[min(streak, 4)] = streak_counts.get(min(streak, 4), 0) + 1
            direction = 'up'
            streak = 1
    elif d <= -BURST_MOVE_THRESHOLD:
        if direction == 'down':
            streak += 1
        else:
            if streak > 0 and direction:
                streak_counts[min(streak, 4)] = streak_counts.get(min(streak, 4), 0) + 1
            direction = 'down'
            streak = 1
    else:
        if streak > 0 and direction:
            streak_counts[min(streak, 4)] = streak_counts.get(min(streak, 4), 0) + 1
        streak = 0
        direction = None

for k, v in sorted(streak_counts.items()):
    print(f"    Length {k}: {v}")
