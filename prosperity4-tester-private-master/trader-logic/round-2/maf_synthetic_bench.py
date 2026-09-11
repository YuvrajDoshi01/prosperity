"""MAF synthetic bench — defensible Market Access Fee decision under regime uncertainty.

Runs r2_v5 and r2_v6 across the 14 round99 synthetic regimes + round98 real R2 day 1,
under three --extra-flow modes (none, scale, interp). The bid decision is post-hoc
arithmetic: winning MAF costs X; under the brief's mechanic, winners trade against
interp-book, losers trade against none-book.

Design doc: docs/superpowers/specs/2026-04-18-maf-synthetic-bench-design.md

Usage:
    python trader-logic/round-2/maf_synthetic_bench.py                  # 25 seeds
    SEEDS=3 python trader-logic/round-2/maf_synthetic_bench.py          # smoke test
    RESUME=1 python trader-logic/round-2/maf_synthetic_bench.py         # continue from last checkpoint

Outputs:
    trader-logic/round-2/maf_synthetic_results.json   (raw seed matrix)
    trader-logic/round-2/maf_synthetic_results.md     (human-readable summary)
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from statistics import mean, median, stdev

REPO = Path(__file__).resolve().parents[2]
PYTHONPATH = str(REPO / "prosperity4bt")
GENERATOR = REPO / "trader-logic" / "round-1" / "experiments" / "synthetic" / "generate.py"
RESULTS_JSON = REPO / "trader-logic" / "round-2" / "maf_synthetic_results.json"
RESULTS_MD = REPO / "trader-logic" / "round-2" / "maf_synthetic_results.md"

STRATEGIES = {
    "r2_v5": str(REPO / "trader-logic" / "round-2" / "r2_v5.py"),
    "r2_v6": str(REPO / "trader-logic" / "round-2" / "r2_v6.py"),
}
FLOW_MODES = ["none", "scale", "interp"]
MATCH_MODE = os.environ.get("MATCH_MODE", "imc")  # imc → R2-calibrated (extra_rate=0.038); default → CSV replay

# round99 regimes (index matches day number)
REGIMES = [
    "UPTREND", "FLAT", "DOWNTREND", "REVERSAL",
    "ACO_CRASH", "ACO_FLASH", "PERMANENT", "CRASH_DEEP",
    "ALT_FV_HIGH", "ALT_FV_LOW", "MID_SHIFT", "DEFENSE_BOT", "VOLUME_BURST",
    "ASYM_OPEN",
]

SEED_COUNT = int(os.environ.get("SEEDS", "25"))
SEEDS = [42 + 73 * i for i in range(SEED_COUNT)]
TICKS = 10_000
RESUME = os.environ.get("RESUME", "0") == "1"

# t-critical values (two-tailed 0.05) for small-sample CIs. Normal approx (1.96) used beyond n=50.
T_CRIT = {2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 9: 2.262, 14: 2.145, 19: 2.093, 24: 2.064, 29: 2.045, 49: 2.010}

DAY_RE = re.compile(r"Round (\d+) day (-?\d+): ([-\d,]+)")
TOTAL_RE = re.compile(r"Total profit:\s*([-\d,]+)")

# Bid grid and P(win) grid for the decision table
BID_GRID = [0, 1000, 5000, 10000, 15000, 20000, 25000, 30000]
P_WIN_GRID = [0.1, 0.3, 0.5, 0.7, 0.9]

# Core regimes = "R2 live is one normal day" — closest synthetic equivalent.
# Stress regimes (everything else) are tail-risk probes.
CORE_REGIMES = ["UPTREND", "FLAT", "DOWNTREND", "REVERSAL"]


# =========================================================================
# Runner
# =========================================================================

def regenerate(seed: int) -> None:
    """Regenerate round99 CSVs for the given seed."""
    subprocess.run(
        [sys.executable, str(GENERATOR), str(seed)],
        cwd=REPO, check=True, capture_output=True,
    )


def run_bt(strategy_path: str, dataset: str, flow_mode: str) -> dict[int, int]:
    """Run one BT and return {day: pnl}. Empty dict on failure."""
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    cmd = [
        sys.executable, "-m", "prosperity4bt",
        strategy_path, dataset,
        "--ticks", str(TICKS), "--no-out", "--no-progress",
        "--match-mode", MATCH_MODE,
        "--extra-flow", flow_mode,
    ]
    try:
        result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {}
    out = result.stdout + result.stderr
    pnl_by_day: dict[int, int] = {}
    # Multi-day runs emit "Round X day Y: N" under "Profit summary:"
    for m in DAY_RE.finditer(out):
        day = int(m.group(2))
        pnl = int(m.group(3).replace(",", ""))
        pnl_by_day[day] = pnl
    # Single-day runs (e.g. round 98) have no Profit summary block — fall back to Total profit.
    if not pnl_by_day:
        m = TOTAL_RE.search(out)
        if m:
            pnl_by_day[0] = int(m.group(1).replace(",", ""))
    return pnl_by_day


def cell_key(strategy: str, flow_mode: str, dataset_label: str, regime_or_day: str) -> str:
    return f"{strategy}|{flow_mode}|{dataset_label}|{regime_or_day}"


def load_checkpoint() -> dict:
    if RESULTS_JSON.exists() and RESUME:
        with open(RESULTS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Handle both shapes: incremental {seeds_done, data} or final {state: {...}, aggregate: {...}}.
        if "seeds_done" in data:
            return data
        if "state" in data and isinstance(data["state"], dict):
            return data["state"]
    return {"seeds_done": [], "data": {}}


def save_checkpoint(state: dict) -> None:
    with open(RESULTS_JSON, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def bench() -> dict:
    """Run the full matrix and return the accumulated result state."""
    state = load_checkpoint()
    done_seeds = set(state["seeds_done"])
    data = state["data"]  # data[cell_key] = [pnl_seed1, pnl_seed2, ...]

    total_seeds = len(SEEDS)
    for seed_idx, seed in enumerate(SEEDS, start=1):
        if seed in done_seeds:
            print(f"[{seed_idx}/{total_seeds}] seed {seed}: SKIP (already in checkpoint)")
            continue

        print(f"[{seed_idx}/{total_seeds}] seed {seed}: regenerating round99...")
        regenerate(seed)

        for strat_name, strat_path in STRATEGIES.items():
            for flow in FLOW_MODES:
                # round99: 14 regimes in one run
                pnl99 = run_bt(strat_path, "99", flow)
                for day, regime_label in enumerate(REGIMES):
                    key = cell_key(strat_name, flow, "round99", regime_label)
                    data.setdefault(key, []).append(pnl99.get(day, 0))

                # round98: single day
                pnl98 = run_bt(strat_path, "98", flow)
                key98 = cell_key(strat_name, flow, "round98", "day0")
                data.setdefault(key98, []).append(pnl98.get(0, 0))

                print(f"    {strat_name} flow={flow}: round99 total={sum(pnl99.values()):>9,}  round98={pnl98.get(0, 0):>6,}")

        state["seeds_done"].append(seed)
        save_checkpoint(state)

    return state


# =========================================================================
# Aggregator
# =========================================================================

def t_critical(n: int) -> float:
    if n < 2:
        return 0.0
    df = n - 1
    if df in T_CRIT:
        return T_CRIT[df]
    if df > 49:
        return 1.96
    keys = sorted(T_CRIT.keys())
    for k in keys:
        if df <= k:
            return T_CRIT[k]
    return 1.96


def stats(vals: list[int]) -> dict:
    if not vals:
        return {"n": 0, "mean": 0.0, "median": 0.0, "stdev": 0.0, "ci": 0.0, "min": 0, "max": 0}
    n = len(vals)
    m = mean(vals)
    sd = stdev(vals) if n >= 2 else 0.0
    se = sd / math.sqrt(n) if n >= 2 else 0.0
    ci = t_critical(n) * se
    return {
        "n": n,
        "mean": m,
        "median": median(vals),
        "stdev": sd,
        "ci": ci,
        "min": min(vals),
        "max": max(vals),
    }


def aggregate(state: dict) -> dict:
    """Compute per-cell stats + deltas + decision curves."""
    data = state["data"]
    per_cell: dict[str, dict] = {}
    for key, vals in data.items():
        per_cell[key] = stats(vals)

    # Winner-minus-loser deltas per (strategy, regime, dataset)
    deltas: dict[str, dict[str, dict[str, float]]] = {}
    for strat in STRATEGIES:
        deltas[strat] = {"round99": {}, "round98": {}}
        for regime in REGIMES:
            none_key = cell_key(strat, "none", "round99", regime)
            for winner_mode in ("scale", "interp"):
                win_key = cell_key(strat, winner_mode, "round99", regime)
                if none_key in per_cell and win_key in per_cell:
                    deltas[strat]["round99"].setdefault(regime, {})[winner_mode] = (
                        per_cell[win_key]["mean"] - per_cell[none_key]["mean"]
                    )
        # round98 single-day deltas
        none_98 = cell_key(strat, "none", "round98", "day0")
        for winner_mode in ("scale", "interp"):
            win_98 = cell_key(strat, winner_mode, "round98", "day0")
            if none_98 in per_cell and win_98 in per_cell:
                deltas[strat]["round98"].setdefault("day0", {})[winner_mode] = (
                    per_cell[win_98]["mean"] - per_cell[none_98]["mean"]
                )

    # Per-strategy delta_mean = mean across regimes of (interp - none).
    # Use interp as the brief-literal winner-side proxy.
    # Compute both across ALL regimes (pessimistic — includes tail-stress) and CORE only
    # (optimistic — single normal day, closer to R2 live conditions).
    delta_mean_per_strategy: dict[str, float] = {}
    delta_mean_core_per_strategy: dict[str, float] = {}
    for strat in STRATEGIES:
        regime_deltas_all = [
            deltas[strat]["round99"][r]["interp"]
            for r in REGIMES
            if r in deltas[strat]["round99"] and "interp" in deltas[strat]["round99"][r]
        ]
        delta_mean_per_strategy[strat] = mean(regime_deltas_all) if regime_deltas_all else 0.0
        regime_deltas_core = [
            deltas[strat]["round99"][r]["interp"]
            for r in CORE_REGIMES
            if r in deltas[strat]["round99"] and "interp" in deltas[strat]["round99"][r]
        ]
        delta_mean_core_per_strategy[strat] = mean(regime_deltas_core) if regime_deltas_core else 0.0

    # Baseline mean(none) per strategy = mean across regimes of none-mode PnL.
    # This is the strategy's typical no-MAF PnL per regime.
    baseline_none_per_strategy: dict[str, float] = {}
    for strat in STRATEGIES:
        vals = [
            per_cell[cell_key(strat, "none", "round99", r)]["mean"]
            for r in REGIMES
            if cell_key(strat, "none", "round99", r) in per_cell
        ]
        baseline_none_per_strategy[strat] = mean(vals) if vals else 0.0

    # Decision curve: E[net | bid=X, P_win] = baseline_none + P_win * (delta_mean - X)
    # Pair of curves: all-regime (pessimistic) + core-regime (optimistic).
    def build_curve(dmean: float) -> dict[float, dict[int, float]]:
        curve: dict[float, dict[int, float]] = {}
        for p_win in P_WIN_GRID:
            curve[p_win] = {}
            for X in BID_GRID:
                curve[p_win][X] = p_win * (dmean - X)  # E[net delta vs not bidding]
        return curve

    decision_curves_all: dict[str, dict[float, dict[int, float]]] = {
        strat: build_curve(delta_mean_per_strategy[strat]) for strat in STRATEGIES
    }
    decision_curves_core: dict[str, dict[float, dict[int, float]]] = {
        strat: build_curve(delta_mean_core_per_strategy[strat]) for strat in STRATEGIES
    }

    # Break-even bid per strategy = delta_mean (both views)
    break_even_bid = delta_mean_per_strategy
    break_even_bid_core = delta_mean_core_per_strategy

    # MAF model cross-check: |interp - scale| per (strategy, regime)
    model_divergence: dict[str, dict[str, float]] = {}
    for strat in STRATEGIES:
        model_divergence[strat] = {}
        for regime in REGIMES:
            interp_key = cell_key(strat, "interp", "round99", regime)
            scale_key = cell_key(strat, "scale", "round99", regime)
            if interp_key in per_cell and scale_key in per_cell:
                model_divergence[strat][regime] = abs(per_cell[interp_key]["mean"] - per_cell[scale_key]["mean"])

    return {
        "per_cell": per_cell,
        "deltas": deltas,
        "delta_mean_per_strategy": delta_mean_per_strategy,
        "delta_mean_core_per_strategy": delta_mean_core_per_strategy,
        "baseline_none_per_strategy": baseline_none_per_strategy,
        "decision_curves_all": decision_curves_all,
        "decision_curves_core": decision_curves_core,
        "break_even_bid": break_even_bid,
        "break_even_bid_core": break_even_bid_core,
        "model_divergence": model_divergence,
    }


# =========================================================================
# Markdown writer
# =========================================================================

def fmt_num(x: float, width: int = 10) -> str:
    return f"{x:>{width},.0f}"


def write_markdown(agg: dict, seed_count: int) -> None:
    lines: list[str] = []
    lines.append("# MAF Synthetic Bench — R2 Market Access Fee Decision\n")
    lines.append(f"Seeds: **{seed_count}** (canonical 42 + 73·i pattern). Ticks/day: 10,000. Strategies: {', '.join(STRATEGIES.keys())}.\n")
    lines.append("Assumes MAF winners trade against `interp`-book (brief-literal inject-midpoint mechanic); losers trade against `none`-book (base 80% flow). `scale` (×1.25 all volumes) shown as pragmatic cross-check.\n")

    # Top-line conclusion
    lines.append("## Top-line conclusion\n")
    for strat in STRATEGIES:
        be_all = agg["break_even_bid"][strat]
        be_core = agg["break_even_bid_core"][strat]
        base = agg["baseline_none_per_strategy"][strat]
        lines.append(
            f"- **{strat}**: break-even bid ≈ {fmt_num(be_all, 1)} (all 14 regimes) / {fmt_num(be_core, 1)} (4 core regimes only). "
            f"Baseline (no-MAF) mean PnL per regime = {fmt_num(base, 1)}. "
            f"`E[net delta | bid=X, P_win] = P_win · (delta_mean − X)`.\n"
        )
    lines.append("\nIf break-even is negative or zero, no positive bid is +EV — MAF_BID=0 wins under any P_win belief. If positive, bid up to break-even yields positive expected return scaled by P_win.\n")
    lines.append("\n")

    # Per-cell PnL table (the big one, per strategy)
    lines.append("## Per-cell PnL (mean ± 95% CI across seeds, round99 synthetic)\n")
    for strat in STRATEGIES:
        lines.append(f"### {strat}\n")
        lines.append("| Regime | none | scale | interp |")
        lines.append("|--------|-----:|------:|-------:|")
        for regime in REGIMES:
            row_cells = [regime]
            for flow in FLOW_MODES:
                key = cell_key(strat, flow, "round99", regime)
                s = agg["per_cell"].get(key)
                if s and s["n"] > 0:
                    row_cells.append(f"{s['mean']:>9,.0f} ± {s['ci']:>6,.0f}")
                else:
                    row_cells.append("—")
            lines.append("| " + " | ".join(row_cells) + " |")
        lines.append("")

    # Winner-minus-loser deltas
    lines.append("## Value of winning MAF per regime (PnL[winner] − PnL[loser])\n")
    for strat in STRATEGIES:
        lines.append(f"### {strat}\n")
        lines.append("| Regime | delta (interp) | delta (scale) |")
        lines.append("|--------|---------------:|--------------:|")
        for regime in REGIMES:
            d = agg["deltas"][strat]["round99"].get(regime, {})
            lines.append(f"| {regime} | {d.get('interp', 0):>+11,.0f} | {d.get('scale', 0):>+11,.0f} |")
        lines.append("")

    # MAF model cross-check
    lines.append("## MAF model cross-check (|mean(interp) − mean(scale)| per regime)\n")
    lines.append("Large values indicate synthetic conclusions are sensitive to the MAF approximation choice. Flag threshold: 5,000 PnL.\n")
    for strat in STRATEGIES:
        lines.append(f"### {strat}\n")
        lines.append("| Regime | |interp − scale| | Flag |")
        lines.append("|--------|------------------:|:-----|")
        for regime in REGIMES:
            v = agg["model_divergence"][strat].get(regime, 0)
            flag = "**HIGH**" if v > 5000 else "ok"
            lines.append(f"| {regime} | {v:>13,.0f} | {flag} |")
        lines.append("")

    # Decision curve — ALL regimes (pessimistic, tail-stress weighted)
    lines.append("## Decision curve — E[net PnL delta vs not bidding], ALL 14 regimes\n")
    lines.append("Formula: `E[net delta | bid=X, P_win] = P_win · (delta_mean − X)` where `delta_mean = mean(PnL[interp] − PnL[none])` across all 14 regimes (includes stress regimes like CRASH_DEEP).\n")
    lines.append("Positive values → bidding beats not bidding. Break-even bid = `delta_mean`.\n")
    for strat in STRATEGIES:
        dmean = agg["delta_mean_per_strategy"][strat]
        lines.append(f"### {strat} (delta_mean_all = {dmean:>,.0f})\n")
        header_cells = ["bid"] + [f"P={p}" for p in P_WIN_GRID]
        lines.append("| " + " | ".join(header_cells) + " |")
        lines.append("|" + "|".join(["---:"] * len(header_cells)) + "|")
        for X in BID_GRID:
            cells = [f"{X:,}"]
            for p in P_WIN_GRID:
                v = agg["decision_curves_all"][strat][p][X]
                cells.append(f"{v:>+9,.0f}")
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    # Decision curve — CORE regimes only (optimistic, normal-day weighted)
    lines.append("## Decision curve — E[net PnL delta vs not bidding], CORE 4 regimes\n")
    lines.append(f"Core regimes = {CORE_REGIMES}. Closer to R2 live (one normal day, no crash/flash/asym-open).\n")
    for strat in STRATEGIES:
        dmean = agg["delta_mean_core_per_strategy"][strat]
        lines.append(f"### {strat} (delta_mean_core = {dmean:>,.0f})\n")
        header_cells = ["bid"] + [f"P={p}" for p in P_WIN_GRID]
        lines.append("| " + " | ".join(header_cells) + " |")
        lines.append("|" + "|".join(["---:"] * len(header_cells)) + "|")
        for X in BID_GRID:
            cells = [f"{X:,}"]
            for p in P_WIN_GRID:
                v = agg["decision_curves_core"][strat][p][X]
                cells.append(f"{v:>+9,.0f}")
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    # Round98 anchor check
    lines.append("## Round98 anchor check (real R2 day 1 data, submission 274128)\n")
    lines.append("Methodology validator. round98 CSV = r2_v2 submission 274128's book data (100% match). That submission WAS in the bottom 50% of bids, so its real book was the 80% flow. Reported numbers are for r2_v5/v6 (not r2_v2) — so absolute numbers differ from 8,407 (r2_v2's imc-calibrated PnL). Use the `interp - none` delta to gauge whether MAF would have flipped the sign vs r2_v2's actual 8,412 website score.\n")
    lines.append("| Strategy | none | scale | interp |")
    lines.append("|----------|-----:|------:|-------:|")
    for strat in STRATEGIES:
        cells = [strat]
        for flow in FLOW_MODES:
            key = cell_key(strat, flow, "round98", "day0")
            s = agg["per_cell"].get(key)
            if s and s["n"] > 0:
                cells.append(f"{s['mean']:>8,.0f} ± {s['ci']:>5,.0f}")
            else:
                cells.append("—")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("\n---\n")
    lines.append("Generated by `trader-logic/round-2/maf_synthetic_bench.py`. Design: `docs/superpowers/specs/2026-04-18-maf-synthetic-bench-design.md`.\n")

    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote summary -> {RESULTS_MD.relative_to(REPO)}")


# =========================================================================
# Main
# =========================================================================

def main() -> None:
    print(f"MAF synthetic bench - {SEED_COUNT} seeds x {len(STRATEGIES)} strategies x {len(FLOW_MODES)} flow modes")
    print(f"Match mode: {MATCH_MODE}")
    print(f"Total BT invocations: {SEED_COUNT * len(STRATEGIES) * len(FLOW_MODES) * 2}  (round99 batch + round98 single-day)")
    print(f"Checkpoint: {RESULTS_JSON.relative_to(REPO)}")
    print(f"Resume mode: {RESUME}")
    print()

    state = bench()
    agg = aggregate(state)

    # Dump aggregate to JSON alongside the raw matrix. Keep the incremental shape at
    # the root (seeds_done, data) so RESUME works across final+incremental runs.
    final = {"seeds_done": state["seeds_done"], "data": state["data"], "aggregate": agg}
    RESULTS_JSON.write_text(json.dumps(final, indent=2), encoding="utf-8")
    write_markdown(agg, seed_count=len(state["seeds_done"]))


if __name__ == "__main__":
    main()
