"""Per-tick PnL extractor for post-mortem analysis (Phase 3.3).

Extracts PnL time series from a BacktestResult or a saved .log JSON file.
Eliminates the manual log-parsing dance done for R2/R3 post-mortems.

Usage:

    # From a BacktestResult (in-process)
    from prosperity4bt.back_tester import BackTester
    from prosperity4bt.tools.per_tick_pnl import extract_pnl_series
    bt = BackTester(...)
    results = bt.run()
    series = extract_pnl_series(results[0])
    # {'HYDROGEL_PACK': [(0, 0.0), (100, 0.0), (200, 5.5), ...], ...}

    # From a saved .log file (post-hoc on a website submission)
    from prosperity4bt.tools.per_tick_pnl import extract_pnl_from_log
    series = extract_pnl_from_log("run-logs/round-3/402350/402350.log")

    # Per-decile aggregation
    from prosperity4bt.tools.per_tick_pnl import per_decile_breakdown
    deciles = per_decile_breakdown(series)
    # {'HYDROGEL_PACK': [2132, 1756, ...], ...}

The extracted series is the cumulative PnL per product over the day, sampled
at every activity-log row (one per tick per product).
"""

from typing import Dict, List, Tuple, Any
import json
import os


def extract_pnl_series(backtest_result) -> Dict[str, List[Tuple[int, float]]]:
    """Extract per-product PnL time series from a BacktestResult.

    Args:
        backtest_result: a BacktestResult instance from prosperity4bt

    Returns:
        Dict mapping product symbol to list of (timestamp, cumulative_pnl).
        Sorted by timestamp ascending.
    """
    series: Dict[str, List[Tuple[int, float]]] = {}
    for row in backtest_result.activity_logs:
        ts = row.timestamp
        sym = row.symbol
        pnl = float(row.profit_loss) if row.profit_loss != "" else 0.0
        series.setdefault(sym, []).append((ts, pnl))
    for sym in series:
        series[sym].sort(key=lambda t: t[0])
    return series


def extract_pnl_from_log(log_path: str) -> Dict[str, List[Tuple[int, float]]]:
    """Extract per-product PnL series from a saved .log JSON (website or BT output).

    Handles both formats:
      - Website submission .log (JSON with activitiesLog as ;-delimited string)
      - BT --out .log (newline-delimited activity rows + sandbox logs)
    """
    with open(log_path, "r", encoding="utf-8") as f:
        text = f.read()

    # Try JSON-wrapped (website format) first
    try:
        data = json.loads(text)
        log_str = data.get("activitiesLog", "")
        return _parse_activity_string(log_str)
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: bare text format
    return _parse_activity_string(text)


def _parse_activity_string(log_str: str) -> Dict[str, List[Tuple[int, float]]]:
    """Parse a ;-delimited activitiesLog string into per-product PnL series."""
    series: Dict[str, List[Tuple[int, float]]] = {}
    lines = log_str.strip().split("\n")
    for line in lines[1:]:  # skip header
        parts = line.split(";")
        if len(parts) < 17:
            continue
        try:
            ts = int(parts[1])
            sym = parts[2]
            pnl = float(parts[16]) if parts[16] else 0.0
        except (ValueError, IndexError):
            continue
        series.setdefault(sym, []).append((ts, pnl))
    for sym in series:
        series[sym].sort(key=lambda t: t[0])
    return series


def per_decile_breakdown(
    series: Dict[str, List[Tuple[int, float]]],
    deciles: int = 10,
) -> Dict[str, List[float]]:
    """Per-decile incremental PnL gain.

    Splits each product's series into `deciles` equal time buckets and returns
    the cumulative-PnL gain within each bucket. Useful for spotting regime
    transitions and unbalanced PnL contribution.

    Returns:
        Dict mapping product symbol to list of `deciles` floats (PnL gained per bucket).
    """
    result: Dict[str, List[float]] = {}
    for sym, ts_pnl in series.items():
        if not ts_pnl:
            result[sym] = [0.0] * deciles
            continue
        ts_min = ts_pnl[0][0]
        ts_max = ts_pnl[-1][0]
        bucket_size = max(1, (ts_max - ts_min) / deciles)

        buckets = []
        prev_pnl = ts_pnl[0][1]
        cur_bucket = 0
        last_bucket_end_pnl = prev_pnl
        for ts, pnl in ts_pnl:
            bucket_idx = min(deciles - 1, int((ts - ts_min) / bucket_size))
            while cur_bucket < bucket_idx:
                buckets.append(prev_pnl - last_bucket_end_pnl)
                last_bucket_end_pnl = prev_pnl
                cur_bucket += 1
            prev_pnl = pnl
        # Final bucket
        while cur_bucket < deciles:
            buckets.append(prev_pnl - last_bucket_end_pnl)
            last_bucket_end_pnl = prev_pnl
            cur_bucket += 1

        result[sym] = buckets
    return result


def summary_table(series: Dict[str, List[Tuple[int, float]]]) -> str:
    """Human-readable summary string for printing.

    Returns a multi-line string with per-product final PnL and
    max drawdown.
    """
    lines = ["product".ljust(28) + "  final".rjust(12) + "  peak".rjust(12) + "  max_dd".rjust(12)]
    for sym in sorted(series.keys()):
        ts_pnl = series[sym]
        if not ts_pnl:
            continue
        finals = [p for _, p in ts_pnl]
        peak = -1e18
        max_dd = 0.0
        for p in finals:
            if p > peak:
                peak = p
            dd = peak - p
            if dd > max_dd:
                max_dd = dd
        lines.append(
            sym.ljust(28)
            + f"  {finals[-1]:>10,.2f}"
            + f"  {peak:>10,.2f}"
            + f"  {max_dd:>10,.2f}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print(
            "Usage: python -m prosperity4bt.tools.per_tick_pnl <log_path> [--deciles]"
        )
        sys.exit(1)

    log_path = sys.argv[1]
    if not os.path.exists(log_path):
        print(f"Error: file not found: {log_path}")
        sys.exit(1)

    series = extract_pnl_from_log(log_path)
    print(summary_table(series))

    if "--deciles" in sys.argv:
        print()
        deciles = per_decile_breakdown(series)
        print("Per-decile PnL gain:")
        for sym in sorted(deciles.keys()):
            buckets = deciles[sym]
            row = sym.ljust(28) + " | " + " ".join(f"{b:>+8.0f}" for b in buckets)
            print(row)
