"""Auto post-mortem generator (Phase 5.4 of R4-prep roadmap).

Takes a website submission .log file (or .zip), parses the activitiesLog and
tradeHistory, and emits a markdown post-mortem with per-product breakdown.

Replaces the manual log-dissection done for R2/R3 post-mortems
(POST_MORTEM_363078*.md). Outputs decile breakdowns, position trajectories,
and trade attributions in a consistent format.

Usage:
    python trader-logic/oracle/auto_postmortem.py <log_or_zip_path> [--out report.md]

Examples:
    # Direct .log file
    python trader-logic/oracle/auto_postmortem.py run-logs/round-3/402350/402350.log

    # .zip extraction (will unzip to a tmp dir first)
    python trader-logic/oracle/auto_postmortem.py run-logs/round-3/402350.zip

    # Specify output file
    python trader-logic/oracle/auto_postmortem.py 363078.log --out POST_MORTEM_363078_AUTO.md
"""

import argparse
import json
import os
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from typing import Dict, List, Tuple


def _load_log_json(path: str) -> dict:
    """Load a .log file as JSON (website format) or raise ValueError."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_zip_to_tmp(zip_path: str) -> str:
    """Extract a single .log file from a zip to a tempdir; return the .log path."""
    tmp = tempfile.mkdtemp(prefix="auto_postmortem_")
    with zipfile.ZipFile(zip_path) as zf:
        log_names = [n for n in zf.namelist() if n.endswith(".log")]
        if not log_names:
            raise ValueError(f"No .log file found inside {zip_path}")
        zf.extract(log_names[0], tmp)
        return os.path.join(tmp, log_names[0])


def _parse_activities(log_str: str) -> Dict[str, List[Tuple[int, float]]]:
    """Parse ;-delimited activitiesLog into {product: [(ts, cum_pnl), ...]}."""
    series: Dict[str, List[Tuple[int, float]]] = {}
    for line in log_str.strip().split("\n")[1:]:
        parts = line.split(";")
        if len(parts) < 17:
            continue
        try:
            ts = int(parts[1]); sym = parts[2]
            pnl = float(parts[16]) if parts[16] else 0.0
        except (ValueError, IndexError):
            continue
        series.setdefault(sym, []).append((ts, pnl))
    for sym in series:
        series[sym].sort(key=lambda t: t[0])
    return series


def _per_decile(series: Dict[str, List[Tuple[int, float]]], n: int = 10) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    for sym, ts_pnl in series.items():
        if not ts_pnl:
            out[sym] = [0.0] * n
            continue
        ts_min, ts_max = ts_pnl[0][0], ts_pnl[-1][0]
        bsize = max(1, (ts_max - ts_min) / n)
        deciles = []
        cur_idx, last_pnl, prev_pnl = 0, ts_pnl[0][1], ts_pnl[0][1]
        for ts, pnl in ts_pnl:
            idx = min(n - 1, int((ts - ts_min) / bsize))
            while cur_idx < idx:
                deciles.append(prev_pnl - last_pnl); last_pnl = prev_pnl; cur_idx += 1
            prev_pnl = pnl
        while cur_idx < n:
            deciles.append(prev_pnl - last_pnl); last_pnl = prev_pnl; cur_idx += 1
        out[sym] = deciles
    return out


def _trade_summary(trade_history: List[dict]) -> Dict[str, Dict[str, int]]:
    """Per-product summary of submission trades."""
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: {"buy_n": 0, "buy_qty": 0, "sell_n": 0, "sell_qty": 0, "buy_cash": 0.0, "sell_cash": 0.0})
    for t in trade_history:
        sym = t.get("symbol", ""); buyer = t.get("buyer", ""); seller = t.get("seller", "")
        qty = t.get("quantity", 0); price = t.get("price", 0.0)
        if buyer == "SUBMISSION":
            out[sym]["buy_n"] += 1
            out[sym]["buy_qty"] += qty
            out[sym]["buy_cash"] += qty * price
        elif seller == "SUBMISSION":
            out[sym]["sell_n"] += 1
            out[sym]["sell_qty"] += qty
            out[sym]["sell_cash"] += qty * price
    return dict(out)


def _position_stats(logs: List[dict], product: str) -> Dict[str, float]:
    """Position trajectory stats from per-tick state."""
    positions = []
    for entry in logs:
        try:
            ll = json.loads(entry["lambdaLog"])
            pos = ll[0][6] if isinstance(ll[0][6], dict) else {}
            positions.append(pos.get(product, 0))
        except Exception:
            continue
    if not positions:
        return {}
    abs_mean = sum(abs(p) for p in positions) / len(positions)
    p_max, p_min = max(positions), min(positions)
    flat_pct = sum(1 for p in positions if abs(p) <= 5) / len(positions)
    pinned_pct = sum(1 for p in positions if abs(p) >= 0.95 * max(abs(p_max), abs(p_min) or 1)) / len(positions) if max(abs(p_max), abs(p_min)) > 0 else 0
    return {
        "abs_mean": abs_mean,
        "max": p_max, "min": p_min,
        "end": positions[-1],
        "flat_pct": flat_pct,
        "pinned_pct": pinned_pct,
        "n_ticks": len(positions),
    }


def generate_postmortem(log_path: str) -> str:
    """Generate full post-mortem markdown for a submission log."""
    data = _load_log_json(log_path)
    sub_id = data.get("submissionId", "unknown")
    activity_log = data.get("activitiesLog", "")
    trade_history = data.get("tradeHistory", [])
    logs = data.get("logs", [])

    series = _parse_activities(activity_log)
    deciles = _per_decile(series)
    trades = _trade_summary(trade_history)

    products = sorted(series.keys())
    total_pnl = sum(s[-1][1] for s in series.values() if s)

    md = []
    md.append(f"# Auto Post-Mortem: submission `{sub_id}`")
    md.append("")
    md.append(f"**Source log:** `{log_path}`")
    md.append(f"**Total PnL:** ${total_pnl:,.2f}")
    md.append(f"**Products traded:** {len(products)}")
    md.append("")

    # Per-product final PnL
    md.append("## Per-product summary")
    md.append("")
    md.append("| Product | Final PnL | Avg \\|pos\\| | End pos | Time flat | Buy/Sell trades | Avg buy | Avg sell | Spread captured |")
    md.append("|---|---:|---:|---:|---:|---|---:|---:|---:|")
    for sym in products:
        ts_pnl = series[sym]
        final_pnl = ts_pnl[-1][1] if ts_pnl else 0.0
        pos_st = _position_stats(logs, sym)
        tr = trades.get(sym, {})
        buy_n = tr.get("buy_n", 0); sell_n = tr.get("sell_n", 0)
        buy_qty = tr.get("buy_qty", 0); sell_qty = tr.get("sell_qty", 0)
        avg_buy = (tr.get("buy_cash", 0) / buy_qty) if buy_qty > 0 else 0
        avg_sell = (tr.get("sell_cash", 0) / sell_qty) if sell_qty > 0 else 0
        spread_cap = avg_sell - avg_buy if avg_buy and avg_sell else 0
        abs_mean = pos_st.get("abs_mean", 0)
        end_p = pos_st.get("end", 0)
        flat = pos_st.get("flat_pct", 0)
        md.append(
            f"| {sym} | {final_pnl:,.2f} | {abs_mean:.1f} | {end_p:+d} | {flat:.1%} | "
            f"{buy_n}/{sell_n} ({buy_qty}/{sell_qty}q) | {avg_buy:,.2f} | {avg_sell:,.2f} | {spread_cap:+.2f} |"
        )
    md.append("")

    # Per-decile PnL
    md.append("## Per-decile PnL gain")
    md.append("")
    md.append("| Product | D0 | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 |")
    md.append("|---|" + "|".join(["---:"] * 10) + "|")
    for sym in products:
        cells = " | ".join(f"{x:+,.0f}" for x in deciles.get(sym, [0] * 10))
        md.append(f"| {sym} | {cells} |")
    md.append("")

    # Trade summary
    md.append("## Trade activity")
    md.append("")
    md.append(f"- Total trades in log: {len(trade_history)}")
    submission_trades = sum(1 for t in trade_history if t.get("buyer") == "SUBMISSION" or t.get("seller") == "SUBMISSION")
    md.append(f"- Submission trades: {submission_trades}")
    md.append(f"- Market-only trades: {len(trade_history) - submission_trades}")
    md.append(f"- Per-tick log entries: {len(logs)}")
    md.append("")

    # Lessons / next steps placeholder
    md.append("## Notes")
    md.append("")
    md.append("This is an auto-generated skeleton. Add narrative analysis as needed:")
    md.append("- What went per expectation (Δ vs BT)?")
    md.append("- Which product is the dominant contributor / drag?")
    md.append("- Any decile transitions to investigate?")
    md.append("- Cross-reference per-product expectations from `R*_BACKTEST_COMMANDS.md` baselines.")
    md.append("")

    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log_path", help="Path to a .log file or .zip containing one")
    ap.add_argument("--out", default=None, help="Output markdown file (default: stdout)")
    args = ap.parse_args()

    path = args.log_path
    if path.endswith(".zip"):
        path = _extract_zip_to_tmp(path)

    md = generate_postmortem(path)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"Post-mortem written to {args.out}")
    else:
        print(md)


if __name__ == "__main__":
    main()
