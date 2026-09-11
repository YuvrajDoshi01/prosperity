"""Deep drawdown analysis — properly parse log format and extract book state."""
import json

LOG_PATH = 'backtests/12635.txt'

with open(LOG_PATH) as f:
    data = json.load(f)

activities = data.get('activitiesLog', '')
lines = activities.strip().split('\n')

# First, figure out the header
header_line = None
data_lines = []
for line in lines:
    parts = line.split(';')
    if parts[0] == 'day':
        header_line = parts
        continue
    if len(parts) >= 16:
        data_lines.append(parts)

if header_line:
    print(f"Header ({len(header_line)} cols): {header_line}")
else:
    print("No header found, using positional parsing")
    # From CLAUDE.MD: day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;
    # bid_price_3;bid_volume_3;ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;
    # ask_price_3;ask_volume_3;mid_price;profit_and_loss

print(f"\nSample data line ({len(data_lines[5])} cols): {data_lines[5][:20]}")

# Parse all TOMATOES ticks with full book state
tomato_ticks = []
for parts in data_lines:
    try:
        day = int(parts[0])
        ts = int(parts[1])
        product = parts[2]
    except (ValueError, IndexError):
        continue

    if product != 'TOMATOES':
        continue

    # Parse book: bp1, bv1, bp2, bv2, bp3, bv3, ap1, av1, ap2, av2, ap3, av3, mid, pnl
    try:
        bp1 = float(parts[3]) if parts[3] else 0
        bv1 = float(parts[4]) if parts[4] else 0
        bp2 = float(parts[5]) if parts[5] else 0
        bv2 = float(parts[6]) if parts[6] else 0
        bp3 = float(parts[7]) if parts[7] else 0
        bv3 = float(parts[8]) if parts[8] else 0
        ap1 = float(parts[9]) if parts[9] else 0
        av1 = float(parts[10]) if parts[10] else 0
        ap2 = float(parts[11]) if parts[11] else 0
        av2 = float(parts[12]) if parts[12] else 0
        ap3 = float(parts[13]) if parts[13] else 0
        av3 = float(parts[14]) if parts[14] else 0
        mid = float(parts[15]) if parts[15] else 0
        pnl = float(parts[16]) if len(parts) > 16 and parts[16] else 0
    except (ValueError, IndexError):
        continue

    tomato_ticks.append({
        'ts': ts, 'bp1': bp1, 'bv1': bv1, 'bp2': bp2, 'bv2': bv2,
        'ap1': ap1, 'av1': av1, 'ap2': ap2, 'av2': av2,
        'mid': mid, 'pnl': pnl,
        'spread': ap1 - bp1 if ap1 > 0 and bp1 > 0 else 0,
    })

print(f"\nTOMATOES ticks parsed: {len(tomato_ticks)}")
print(f"Sample tick: {tomato_ticks[10]}")

# Compute drawdowns with full context
print(f"\n{'='*80}")
print(f"TOMATOES DRAWDOWN ANALYSIS (with book state)")
print(f"{'='*80}")

peak_pnl = 0.0
drawdowns = []
in_dd = False
dd_start_idx = 0
dd_peak_val = 0.0
dd_trough_val = 0.0
dd_trough_idx = 0

for i, t in enumerate(tomato_ticks):
    if t['pnl'] >= peak_pnl:
        if in_dd and (dd_peak_val - dd_trough_val) >= 50:
            drawdowns.append({
                'start_idx': dd_start_idx,
                'trough_idx': dd_trough_idx,
                'end_idx': i,
                'dd_amount': dd_peak_val - dd_trough_val,
            })
        peak_pnl = t['pnl']
        in_dd = False
    else:
        if not in_dd:
            in_dd = True
            dd_start_idx = i
            dd_peak_val = peak_pnl
            dd_trough_val = t['pnl']
            dd_trough_idx = i
        if t['pnl'] < dd_trough_val:
            dd_trough_val = t['pnl']
            dd_trough_idx = i

if in_dd and (peak_pnl - dd_trough_val) >= 50:
    drawdowns.append({
        'start_idx': dd_start_idx,
        'trough_idx': dd_trough_idx,
        'end_idx': len(tomato_ticks) - 1,
        'dd_amount': dd_peak_val - dd_trough_val,
    })

drawdowns.sort(key=lambda x: -x['dd_amount'])
print(f"\nDrawdowns ≥ 50 PnL: {len(drawdowns)}")

for rank, dd in enumerate(drawdowns[:5], 1):
    si = dd['start_idx']
    ti = dd['trough_idx']
    ei = dd['end_idx']
    start_ts = tomato_ticks[si]['ts']
    trough_ts = tomato_ticks[ti]['ts']

    print(f"\n{'─'*80}")
    print(f"  DRAWDOWN #{rank}: DD={dd['dd_amount']:.1f}, "
          f"ts {start_ts} → {trough_ts} ({trough_ts - start_ts}ms, {ti - si + 1} ticks)")
    print(f"{'─'*80}")

    # Show full context: 3 ticks before DD start to 3 ticks after trough
    ctx_start = max(0, si - 3)
    ctx_end = min(len(tomato_ticks) - 1, ti + 3)

    # Compute position estimate from PnL changes and mid changes
    prev_pnl = None
    prev_mid = None

    print(f"  {'ts':>8} {'PnL':>8} {'dPnL':>7} {'Mid':>8} {'dMid':>6} {'Spread':>6} "
          f"{'BP1':>6} {'BV1':>4} {'AP1':>6} {'AV1':>4} {'BP2':>6} {'BV2':>4} {'AP2':>6} {'AV2':>4}")

    for idx in range(ctx_start, ctx_end + 1):
        t = tomato_ticks[idx]
        dpnl = f"{t['pnl'] - prev_pnl:>+7.1f}" if prev_pnl is not None else "    ---"
        dmid = f"{t['mid'] - prev_mid:>+6.1f}" if prev_mid is not None and t['mid'] > 0 and prev_mid > 0 else "   ---"
        note = ""
        if idx == si:
            note = " ← START"
        elif idx == ti:
            note = " ← TROUGH"

        print(f"  {t['ts']:>8} {t['pnl']:>8.1f} {dpnl} {t['mid']:>8.1f} {dmid} "
              f"{t['spread']:>6.0f} {t['bp1']:>6.0f} {t['bv1']:>4.0f} "
              f"{t['ap1']:>6.0f} {t['av1']:>4.0f} {t['bp2']:>6.0f} {t['bv2']:>4.0f} "
              f"{t['ap2']:>6.0f} {t['av2']:>4.0f}{note}")

        prev_pnl = t['pnl']
        prev_mid = t['mid'] if t['mid'] > 0 else prev_mid

    # Analyze: spread distribution during drawdown
    dd_ticks = tomato_ticks[si:ti+1]
    spreads = [t['spread'] for t in dd_ticks if t['spread'] > 0]
    narrow = sum(1 for s in spreads if s <= 9)
    wide = sum(1 for s in spreads if s > 9)

    # Mid movement
    mids = [t['mid'] for t in dd_ticks if t['mid'] > 0]
    if len(mids) >= 2:
        mid_change = mids[-1] - mids[0]
        mid_max = max(mids)
        mid_min = min(mids)
        mid_range = mid_max - mid_min
    else:
        mid_change = 0
        mid_range = 0

    # Count single-tick PnL drops > 40
    big_drops = [(tomato_ticks[j]['ts'],
                  tomato_ticks[j]['pnl'] - tomato_ticks[j-1]['pnl'],
                  tomato_ticks[j]['mid'] - tomato_ticks[j-1]['mid'] if tomato_ticks[j]['mid'] > 0 and tomato_ticks[j-1]['mid'] > 0 else 0)
                 for j in range(si+1, ti+1)
                 if tomato_ticks[j]['pnl'] - tomato_ticks[j-1]['pnl'] < -30]

    print(f"\n  Analysis:")
    print(f"    Narrow spreads: {narrow}/{len(spreads)} ({100*narrow/max(1,len(spreads)):.0f}%)")
    print(f"    Mid change: {mid_change:+.1f}, range: {mid_range:.1f}")
    print(f"    Big single-tick drops (>30 PnL):")
    for ts, dpnl, dmid in sorted(big_drops, key=lambda x: x[1]):
        print(f"      ts={ts}: dPnL={dpnl:+.1f}, dMid={dmid:+.1f}")

# Overall stats
print(f"\n{'='*80}")
print(f"SUMMARY")
print(f"{'='*80}")
final_pnl = tomato_ticks[-1]['pnl']
max_dd = drawdowns[0]['dd_amount'] if drawdowns else 0
print(f"Final TOMATOES PnL: {final_pnl:.1f}")
print(f"Max drawdown: {max_dd:.1f}")
print(f"PnL/MaxDD ratio: {final_pnl/max_dd:.2f}" if max_dd > 0 else "N/A")

# Count total exposure to narrow spreads
all_narrow = sum(1 for t in tomato_ticks if 0 < t['spread'] <= 9)
print(f"Narrow spread ticks: {all_narrow}/{len(tomato_ticks)} ({100*all_narrow/len(tomato_ticks):.1f}%)")
