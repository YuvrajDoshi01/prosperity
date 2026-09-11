#!/usr/bin/env python3
"""Analyze TOMATOES drawdown regions from backtest logs."""

import json
import sys
import numpy as np

def parse_log(filepath):
    """Parse backtest log file, return TOMATOES rows."""
    with open(filepath, 'r') as f:
        data = json.loads(f.read())

    lines = data['activitiesLog'].split('\n')
    header = lines[0].split(';')

    tomatoes = []
    emeralds = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(';')
        row = {}
        for i, col in enumerate(header):
            if i < len(parts):
                val = parts[i]
                if val == '':
                    row[col] = None
                else:
                    try:
                        row[col] = float(val)
                    except ValueError:
                        row[col] = val

        if row.get('product') == 'TOMATOES':
            tomatoes.append(row)
        elif row.get('product') == 'EMERALDS':
            emeralds.append(row)

    return tomatoes, emeralds

def analyze_drawdowns(rows, product_name="TOMATOES"):
    """Full drawdown analysis."""
    timestamps = [r['timestamp'] for r in rows]
    pnl = [r['profit_and_loss'] for r in rows]
    mids = [r['mid_price'] for r in rows]

    # Extract spreads and volumes
    spreads = []
    l1_bid_vols = []
    l1_ask_vols = []
    for r in rows:
        b1 = r.get('bid_price_1')
        a1 = r.get('ask_price_1')
        if b1 is not None and a1 is not None:
            spreads.append(a1 - b1)
        else:
            spreads.append(None)
        l1_bid_vols.append(r.get('bid_volume_1', 0))
        l1_ask_vols.append(r.get('ask_volume_1', 0))

    n = len(pnl)

    print(f"\n{'='*80}")
    print(f"DRAWDOWN ANALYSIS: {product_name}")
    print(f"{'='*80}")
    print(f"Total ticks: {n}")
    print(f"Final PnL: {pnl[-1]:.1f}")
    print(f"Min PnL: {min(pnl):.1f} at tick {timestamps[pnl.index(min(pnl))]:.0f}")
    print(f"Max PnL: {max(pnl):.1f} at tick {timestamps[pnl.index(max(pnl))]:.0f}")

    # High-water mark and drawdown
    hwm = [0.0] * n
    dd = [0.0] * n
    hwm[0] = pnl[0]
    for i in range(1, n):
        hwm[i] = max(hwm[i-1], pnl[i])
        dd[i] = pnl[i] - hwm[i]

    max_dd = min(dd)
    max_dd_idx = dd.index(max_dd)

    print(f"\nMax drawdown: {max_dd:.1f} at tick {timestamps[max_dd_idx]:.0f}")
    print(f"PnL / Max DD ratio: {pnl[-1] / abs(max_dd):.2f}" if max_dd != 0 else "No drawdown")

    # Time in drawdown
    in_dd_count = sum(1 for d in dd if d < -1)
    print(f"Time in drawdown (>1): {in_dd_count}/{n} ({100*in_dd_count/n:.1f}%)")

    # Identify drawdown events (dd < -20)
    print(f"\n{'='*80}")
    print(f"DRAWDOWN EVENTS (depth > 20)")
    print(f"{'='*80}")

    events = []
    in_event = False
    event_start = 0
    event_bottom = 0
    event_bottom_dd = 0

    for i in range(n):
        if dd[i] < -20 and not in_event:
            # Start of drawdown event - find where HWM was
            in_event = True
            # Walk back to find where HWM was set
            event_start = i
            for j in range(i-1, -1, -1):
                if pnl[j] >= hwm[i]:
                    event_start = j
                    break
            event_bottom = i
            event_bottom_dd = dd[i]
        elif in_event and dd[i] < event_bottom_dd:
            event_bottom = i
            event_bottom_dd = dd[i]
        elif in_event and dd[i] >= -5:  # Recovery (within 5 of HWM)
            events.append({
                'start_idx': event_start,
                'bottom_idx': event_bottom,
                'end_idx': i,
                'start_ts': timestamps[event_start],
                'bottom_ts': timestamps[event_bottom],
                'end_ts': timestamps[i],
                'depth': event_bottom_dd,
                'duration_ticks': i - event_start,
                'hwm_pnl': hwm[event_start],
                'bottom_pnl': pnl[event_bottom],
                'mid_at_start': mids[event_start],
                'mid_at_bottom': mids[event_bottom],
                'mid_at_end': mids[i],
                'mid_move': mids[event_bottom] - mids[event_start],
                'spread_at_start': spreads[event_start],
                'spread_at_bottom': spreads[event_bottom],
            })
            in_event = False

    # Check if still in drawdown at end
    if in_event:
        events.append({
            'start_idx': event_start,
            'bottom_idx': event_bottom,
            'end_idx': n-1,
            'start_ts': timestamps[event_start],
            'bottom_ts': timestamps[event_bottom],
            'end_ts': timestamps[-1],
            'depth': event_bottom_dd,
            'duration_ticks': n - 1 - event_start,
            'hwm_pnl': hwm[event_start],
            'bottom_pnl': pnl[event_bottom],
            'mid_at_start': mids[event_start],
            'mid_at_bottom': mids[event_bottom],
            'mid_at_end': mids[-1],
            'mid_move': mids[event_bottom] - mids[event_start],
            'spread_at_start': spreads[event_start],
            'spread_at_bottom': spreads[event_bottom],
            'unrecovered': True,
        })

    print(f"Found {len(events)} drawdown events")

    for i, e in enumerate(events):
        recovered = "UNRECOVERED" if e.get('unrecovered') else "recovered"
        print(f"\n  Event {i+1}: [{recovered}]")
        print(f"    Start: t={e['start_ts']:.0f} (HWM PnL={e['hwm_pnl']:.1f})")
        print(f"    Bottom: t={e['bottom_ts']:.0f} (PnL={e['bottom_pnl']:.1f}, DD={e['depth']:.1f})")
        print(f"    End: t={e['end_ts']:.0f}")
        print(f"    Duration: {e['duration_ticks']} ticks ({e['duration_ticks']*0.1:.1f}s)")
        print(f"    Mid price: {e['mid_at_start']:.1f} -> {e['mid_at_bottom']:.1f} -> {e['mid_at_end']:.1f}")
        print(f"    Mid move to bottom: {e['mid_move']:+.1f}")
        print(f"    Spread at start: {e['spread_at_start']}")
        print(f"    Spread at bottom: {e['spread_at_bottom']}")

    # PnL trajectory (every 100th tick)
    print(f"\n{'='*80}")
    print(f"PnL TRAJECTORY (every 100 ticks)")
    print(f"{'='*80}")
    print(f"{'Tick':>8} {'Timestamp':>10} {'PnL':>8} {'HWM':>8} {'DD':>8} {'Mid':>8} {'Spread':>6}")
    for i in range(0, n, 100):
        sp = spreads[i] if spreads[i] is not None else '-'
        print(f"{i:8d} {timestamps[i]:10.0f} {pnl[i]:8.1f} {hwm[i]:8.1f} {dd[i]:8.1f} {mids[i]:8.1f} {sp!s:>6}")
    # Always show last tick
    i = n - 1
    sp = spreads[i] if spreads[i] is not None else '-'
    print(f"{i:8d} {timestamps[i]:10.0f} {pnl[i]:8.1f} {hwm[i]:8.1f} {dd[i]:8.1f} {mids[i]:8.1f} {sp!s:>6}")

    # PnL changes between fills
    print(f"\n{'='*80}")
    print(f"PnL CHANGE ANALYSIS")
    print(f"{'='*80}")

    dpnl = np.diff(pnl)
    nonzero_changes = dpnl[dpnl != 0]
    print(f"Total PnL changes (non-zero): {len(nonzero_changes)}")
    print(f"Positive changes: {(nonzero_changes > 0).sum()} (mean: {nonzero_changes[nonzero_changes > 0].mean():.2f})")
    print(f"Negative changes: {(nonzero_changes < 0).sum()} (mean: {nonzero_changes[nonzero_changes < 0].mean():.2f})")
    print(f"Largest positive change: {nonzero_changes.max():.1f}")
    print(f"Largest negative change: {nonzero_changes.min():.1f}")

    # When do negative PnL changes happen?
    print(f"\n--- Negative PnL changes context ---")
    neg_indices = np.where(dpnl < -5)[0]  # Changes > 5 negative
    for idx in neg_indices[:20]:
        ts = timestamps[idx]
        ts_next = timestamps[idx+1]
        mid_change = mids[idx+1] - mids[idx]
        sp = spreads[idx] if spreads[idx] is not None else -1
        sp_next = spreads[idx+1] if spreads[idx+1] is not None else -1
        print(f"  t={ts:.0f}->{ts_next:.0f}: dPnL={dpnl[idx]:+.1f}, "
              f"dMid={mid_change:+.1f}, spread={sp:.0f}->{sp_next:.0f}")

    # Narrow spread analysis during drawdowns
    print(f"\n{'='*80}")
    print(f"NARROW SPREAD WINDOWS AND DRAWDOWNS")
    print(f"{'='*80}")

    narrow_count = 0
    narrow_pnl_drops = []
    for i in range(1, n):
        sp = spreads[i]
        if sp is not None and sp <= 9:
            narrow_count += 1
            if dpnl[i-1] != 0:
                narrow_pnl_drops.append(dpnl[i-1])

    print(f"Narrow spread ticks (<=9): {narrow_count} ({100*narrow_count/n:.1f}%)")
    if narrow_pnl_drops:
        arr = np.array(narrow_pnl_drops)
        print(f"PnL changes on narrow spread ticks: {len(arr)}")
        print(f"  Mean: {arr.mean():+.2f}, Positive: {(arr>0).sum()}, Negative: {(arr<0).sum()}")

    # Wide spread analysis
    wide_pnl_drops = []
    for i in range(1, n):
        sp = spreads[i]
        if sp is not None and sp >= 13:
            if dpnl[i-1] != 0:
                wide_pnl_drops.append(dpnl[i-1])
    if wide_pnl_drops:
        arr = np.array(wide_pnl_drops)
        print(f"PnL changes on wide spread ticks (>=13): {len(arr)}")
        print(f"  Mean: {arr.mean():+.2f}, Positive: {(arr>0).sum()}, Negative: {(arr<0).sum()}")

    # Inventory MTM analysis
    print(f"\n{'='*80}")
    print(f"INVENTORY MTM DECOMPOSITION")
    print(f"{'='*80}")

    # Each PnL change = spread_captured + inventory_mtm
    # Without position data, approximate from PnL pattern
    # Positive PnL jump = fill (spread captured)
    # PnL drift without fill = inventory MTM from mid moving

    # Detect fills: PnL changes that look like fills
    fill_pnl = []
    mtm_pnl = []
    for i in range(len(dpnl)):
        if abs(dpnl[i]) >= 3:  # Likely a fill (spread capture ~6-7)
            fill_pnl.append(dpnl[i])
        elif dpnl[i] != 0:
            mtm_pnl.append(dpnl[i])

    print(f"Fill-like PnL changes (|d| >= 3): {len(fill_pnl)}")
    print(f"  Total: {sum(fill_pnl):.1f}")
    print(f"  Mean: {np.mean(fill_pnl):.2f}" if fill_pnl else "  (none)")
    print(f"MTM-like PnL changes (0 < |d| < 3): {len(mtm_pnl)}")
    print(f"  Total: {sum(mtm_pnl):.1f}")
    print(f"  Mean: {np.mean(mtm_pnl):.2f}" if mtm_pnl else "  (none)")

    return events, dd, pnl, hwm


def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else \
        '/Users/y0d046w/Desktop/prosperity4-tester-private/backtests/2026-03-22_00-34-37.txt'

    tomatoes, emeralds = parse_log(filepath)

    print(f"Parsed {len(tomatoes)} TOMATOES ticks, {len(emeralds)} EMERALDS ticks")

    if tomatoes:
        events_t, dd_t, pnl_t, hwm_t = analyze_drawdowns(tomatoes, "TOMATOES")

    if emeralds:
        events_e, dd_e, pnl_e, hwm_e = analyze_drawdowns(emeralds, "EMERALDS")

    # Combined analysis
    print(f"\n{'='*80}")
    print(f"COMBINED SUMMARY")
    print(f"{'='*80}")
    if tomatoes and emeralds:
        final_t = pnl_t[-1]
        final_e = pnl_e[-1]
        max_dd_t = min(dd_t)
        max_dd_e = min(dd_e)
        print(f"TOMATOES: PnL={final_t:.1f}, MaxDD={max_dd_t:.1f}, Ratio={final_t/abs(max_dd_t):.2f}" if max_dd_t != 0 else f"TOMATOES: PnL={final_t:.1f}, MaxDD=0")
        print(f"EMERALDS: PnL={final_e:.1f}, MaxDD={max_dd_e:.1f}, Ratio={final_e/abs(max_dd_e):.2f}" if max_dd_e != 0 else f"EMERALDS: PnL={final_e:.1f}, MaxDD=0")
        print(f"Total: PnL={final_t+final_e:.1f}")


if __name__ == '__main__':
    main()
