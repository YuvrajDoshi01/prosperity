"""Analyze drawdowns from a backtest log file (JSON format)."""
import json, sys

LOG_PATH = 'backtests/12635.txt'

with open(LOG_PATH) as f:
    data = json.load(f)

activities = data.get('activitiesLog', '')
lines = activities.strip().split('\n')

# Parse PnL time series per product
pnl_series = {}  # product -> [(ts, pnl)]
for line in lines:
    if not line.strip():
        continue
    parts = line.split(';')
    if len(parts) < 16:
        continue
    try:
        ts = int(parts[1])
    except ValueError:
        continue
    product = parts[2]
    pnl = float(parts[-1]) if parts[-1] else 0.0

    # Also extract book data for context
    mid = float(parts[14]) if parts[14] else 0.0

    if product not in pnl_series:
        pnl_series[product] = []
    pnl_series[product].append((ts, pnl, mid))

print(f"Products found: {list(pnl_series.keys())}")
print(f"Log file: {LOG_PATH}\n")

for product in sorted(pnl_series.keys()):
    series = pnl_series[product]
    print(f"{'='*70}")
    print(f"  {product}: {len(series)} ticks")
    print(f"  Final PnL: {series[-1][1]:.1f}")
    print(f"{'='*70}")

    # Compute drawdown from running peak
    peak_pnl = 0.0
    drawdowns = []  # (start_ts, trough_ts, end_ts, peak_val, trough_val, dd_amount)
    in_dd = False
    dd_start_ts = 0
    dd_peak_val = 0.0
    dd_trough_val = 0.0
    dd_trough_ts = 0

    for ts, pnl, mid in series:
        if pnl >= peak_pnl:
            if in_dd and (peak_pnl - dd_trough_val) >= 20:
                # Drawdown ended — record it
                drawdowns.append({
                    'start_ts': dd_start_ts,
                    'trough_ts': dd_trough_ts,
                    'end_ts': ts,
                    'peak_val': dd_peak_val,
                    'trough_val': dd_trough_val,
                    'dd_amount': dd_peak_val - dd_trough_val,
                    'duration': ts - dd_start_ts,
                })
            peak_pnl = pnl
            in_dd = False
        else:
            if not in_dd:
                in_dd = True
                dd_start_ts = ts
                dd_peak_val = peak_pnl
                dd_trough_val = pnl
                dd_trough_ts = ts
            if pnl < dd_trough_val:
                dd_trough_val = pnl
                dd_trough_ts = ts

    # Capture final drawdown if still in one
    if in_dd and (peak_pnl - dd_trough_val) >= 20:
        drawdowns.append({
            'start_ts': dd_start_ts,
            'trough_ts': dd_trough_ts,
            'end_ts': series[-1][0],
            'peak_val': dd_peak_val,
            'trough_val': dd_trough_val,
            'dd_amount': dd_peak_val - dd_trough_val,
            'duration': series[-1][0] - dd_start_ts,
            'recovered': False,
        })

    if not drawdowns:
        print("  No drawdowns >= 20 PnL found.\n")
        continue

    # Sort by severity
    drawdowns.sort(key=lambda x: -x['dd_amount'])

    print(f"\n  Total drawdown events (≥20 PnL): {len(drawdowns)}")
    max_dd = max(d['dd_amount'] for d in drawdowns)
    print(f"  Max drawdown: {max_dd:.1f}")
    print(f"  Final PnL / Max DD ratio: {abs(series[-1][1] / max_dd):.2f}")

    # Show all drawdowns sorted by severity
    print(f"\n  {'Rank':>4} {'Start_ts':>10} {'Trough_ts':>10} {'End_ts':>10} {'Peak':>8} {'Trough':>8} {'DD':>8} {'Duration':>10}")
    print(f"  {'-'*4} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")

    for i, d in enumerate(drawdowns):
        print(f"  {i+1:>4} {d['start_ts']:>10} {d['trough_ts']:>10} {d['end_ts']:>10} "
              f"{d['peak_val']:>8.1f} {d['trough_val']:>8.1f} {d['dd_amount']:>8.1f} "
              f"{d['duration']:>10}")

    # Detail the top 5 drawdowns — show what happened tick by tick
    print(f"\n  ── Top 5 Drawdowns Detail ──")
    for rank, d in enumerate(drawdowns[:5], 1):
        print(f"\n  #{rank}: DD={d['dd_amount']:.1f} from ts={d['start_ts']} to trough={d['trough_ts']}")

        # Get ticks in this drawdown window (with context before/after)
        context_before = 3
        context_after = 3
        window_start = d['start_ts'] - context_before * 100
        window_end = d['trough_ts'] + context_after * 100

        print(f"  {'ts':>10} {'PnL':>8} {'dPnL':>8} {'Mid':>10} {'dMid':>8} {'Note':>10}")
        prev_pnl = None
        prev_mid = None
        for ts, pnl, mid in series:
            if ts < window_start or ts > window_end:
                continue
            dpnl = f"{pnl - prev_pnl:>+8.1f}" if prev_pnl is not None else "     ---"
            dmid = f"{mid - prev_mid:>+8.1f}" if prev_mid is not None else "     ---"
            note = ""
            if ts == d['start_ts']:
                note = " ← DD START"
            elif ts == d['trough_ts']:
                note = " ← TROUGH"
            print(f"  {ts:>10} {pnl:>8.1f} {dpnl} {mid:>10.1f} {dmid}{note}")
            prev_pnl = pnl
            prev_mid = mid

    # Analyze drawdown CAUSES
    print(f"\n  ── Drawdown Cause Analysis ──")
    # For each drawdown, check: was it from mid moving against position, or from a bad fill?
    # Build position estimate from PnL changes and mid changes
    ts_to_data = {ts: (pnl, mid) for ts, pnl, mid in series}
    ts_list = [ts for ts, _, _ in series]

    for rank, d in enumerate(drawdowns[:5], 1):
        # Get PnL trajectory during drawdown
        dd_ticks = [(ts, pnl, mid) for ts, pnl, mid in series
                    if d['start_ts'] <= ts <= d['trough_ts']]

        if len(dd_ticks) < 2:
            print(f"  #{rank}: Too few ticks to analyze")
            continue

        # Decompose: how much PnL was lost, and was mid moving in one direction?
        total_mid_move = dd_ticks[-1][2] - dd_ticks[0][2]
        total_pnl_loss = dd_ticks[-1][1] - dd_ticks[0][1]
        n_ticks = len(dd_ticks)

        # Count ticks where PnL dropped
        drop_ticks = sum(1 for i in range(1, len(dd_ticks))
                        if dd_ticks[i][1] < dd_ticks[i-1][1])
        rise_ticks = sum(1 for i in range(1, len(dd_ticks))
                        if dd_ticks[i][1] > dd_ticks[i-1][1])

        # Biggest single-tick PnL drops
        worst_drops = []
        for i in range(1, len(dd_ticks)):
            dpnl = dd_ticks[i][1] - dd_ticks[i-1][1]
            dmid = dd_ticks[i][2] - dd_ticks[i-1][2]
            if dpnl < 0:
                worst_drops.append((dd_ticks[i][0], dpnl, dmid))
        worst_drops.sort(key=lambda x: x[1])

        print(f"  #{rank}: DD={d['dd_amount']:.1f}, {n_ticks} ticks, "
              f"mid moved {total_mid_move:+.1f}, PnL lost {total_pnl_loss:+.1f}")
        print(f"       {drop_ticks} drop ticks, {rise_ticks} rise ticks")
        if worst_drops:
            print(f"       Worst single-tick drops:")
            for ts, dpnl, dmid in worst_drops[:3]:
                print(f"         ts={ts}: dPnL={dpnl:+.1f}, dMid={dmid:+.1f}")

    print()
