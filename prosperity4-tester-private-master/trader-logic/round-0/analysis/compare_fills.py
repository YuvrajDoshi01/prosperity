"""Compare fill patterns between s36 and s38 to understand WHERE +71 PnL comes from."""
import json, sys

def parse_log(path):
    with open(path) as f:
        data = json.load(f)

    activities = data.get('activitiesLog', '')
    pnl_by_tick = {}

    for line in activities.strip().split('\n'):
        if not line.strip():
            continue
        parts = line.split(';')
        if len(parts) < 16:
            continue
        # Skip header line
        try:
            ts = int(parts[1])
        except ValueError:
            continue

        product = parts[2]
        pnl = float(parts[-1]) if parts[-1] else 0
        pnl_by_tick[(product, ts)] = pnl

    return pnl_by_tick

# Compare two logs
log1 = 'backtests/2026-03-22_13-30-45.log'  # s36
log2 = 'backtests/2026-03-22_13-24-57.log'  # s38

p1 = parse_log(log1)
p2 = parse_log(log2)

# Find ticks where PnL differs for TOMATOES
tom_diff = {}
all_ts = sorted(set(ts for (prod, ts) in p1 if prod == 'TOMATOES') |
                set(ts for (prod, ts) in p2 if prod == 'TOMATOES'))

for ts in all_ts:
    pnl1 = p1.get(('TOMATOES', ts), 0)
    pnl2 = p2.get(('TOMATOES', ts), 0)
    if pnl1 != pnl2:
        tom_diff[ts] = (pnl1, pnl2, pnl2 - pnl1)

print(f"TOMATOES ticks where PnL differs: {len(tom_diff)} / {len(all_ts)}")
print(f"\nTotal TOMATOES PnL: s36={p1.get(('TOMATOES', all_ts[-1]), 0):.1f}, "
      f"s38={p2.get(('TOMATOES', all_ts[-1]), 0):.1f}")

# Show biggest differences
if tom_diff:
    print(f"\nTop 20 divergence ticks (by |delta|):")
    sorted_diff = sorted(tom_diff.items(), key=lambda x: abs(x[1][2]), reverse=True)
    for ts, (p1v, p2v, delta) in sorted_diff[:20]:
        print(f"  ts={ts:>8}: s36={p1v:>8.1f}, s38={p2v:>8.1f}, delta={delta:>+7.1f}")

    # Find the FIRST tick where they diverge
    first_diff = sorted(tom_diff.keys())[0]
    print(f"\nFirst divergence at ts={first_diff}")

    # Cumulative divergence
    cum_delta = 0
    print(f"\nCumulative divergence over time:")
    check_points = [ts for ts in all_ts if ts % 20000 == 0]
    for cp in check_points:
        pnl1 = p1.get(('TOMATOES', cp), 0)
        pnl2 = p2.get(('TOMATOES', cp), 0)
        print(f"  ts={cp:>8}: s36={pnl1:>8.1f}, s38={pnl2:>8.1f}, gap={pnl2-pnl1:>+7.1f}")

# Also check EMERALDS
em_final_1 = max((p1.get(('EMERALDS', ts), 0) for ts in all_ts), default=0)
em_final_2 = max((p2.get(('EMERALDS', ts), 0) for ts in all_ts), default=0)
print(f"\nEMERALDS: s36={em_final_1:.1f}, s38={em_final_2:.1f}")
