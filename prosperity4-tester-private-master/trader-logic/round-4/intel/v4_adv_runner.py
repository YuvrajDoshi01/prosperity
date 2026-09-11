"""Adversarial Monte Carlo runner for R4 v3 robustness study.

For N_SEEDS x 14 batch slots = 50+ synthetic days:
  1. Regenerate round99 day {0..13} from seed S.
  2. Run strategy via backtester.
  3. Parse per-day PnL.
  4. Aggregate: distribution stats + tail diagnosis.

Optionally compare two strategies (v3 vs v4_robust).

Usage:
  python intel/v4_adv_runner.py --strategy trader-logic/round-4/r4_final_v3.py --seeds 4
  python intel/v4_adv_runner.py --strategy trader-logic/round-4/r4_v4_robust.py --seeds 4 --tag robust
"""

import argparse
import json
import os
import re
import subprocess
import sys
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GEN = REPO / "trader-logic" / "round-4" / "intel" / "v4_adv_generate.py"
DAY_RE = re.compile(r"Round 99 day (\d+): ([-\d,]+)")
PRODUCT_RE = re.compile(r"^([A-Z_0-9]+):\s+([-\d,]+)$")


def regen(seed, batch, **kwargs):
    cmd = [sys.executable, str(GEN), "--seed", str(seed), "--batch", str(batch)]
    for k, v in kwargs.items():
        if v is True:
            cmd.append(f"--{k.replace('_', '-')}")
        elif v not in (False, None, 0, 0.0):
            cmd.extend([f"--{k.replace('_', '-')}", str(v)])
    subprocess.run(cmd, cwd=REPO, check=True, capture_output=True)


def run_strategy(strategy_path, ticks=10000):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "prosperity4bt")
    cmd = [sys.executable, "-m", "prosperity4bt", strategy_path, "99",
           "--ticks", str(ticks), "--no-out", "--no-progress"]
    res = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=env)
    out = res.stdout + "\n" + res.stderr
    pnl = {}
    per_product = {}
    cur_day = None
    cur_prods = {}
    for line in out.splitlines():
        if "Backtesting" in line and "day:" in line:
            if cur_day is not None and cur_prods:
                per_product[cur_day] = cur_prods
            cur_prods = {}
            try:
                cur_day = int(line.rsplit("day:", 1)[1].strip())
            except Exception:
                cur_day = None
        m = DAY_RE.search(line)
        if m:
            d = int(m.group(1)); v = int(m.group(2).replace(",", ""))
            pnl[d] = v
            if cur_day == d and cur_prods:
                per_product[d] = cur_prods
                cur_prods = {}
        pm = PRODUCT_RE.match(line.strip())
        if pm and "Total" not in pm.group(1):
            try:
                cur_prods[pm.group(1)] = int(pm.group(2).replace(",", ""))
            except ValueError:
                pass
    return pnl, per_product


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--seeds", type=int, default=4)  # 4 seeds × 14 batches = 56 days
    ap.add_argument("--tag", default="v3")
    ap.add_argument("--out", default="C:/tmp/v4_adv")
    ap.add_argument("--adversarial-mix", action="store_true",
                    help="Cycle through adversarial perturbations across batches")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_pnls = []
    rows = []
    perturbations = [
        {},                             # 0: pure bootstrap
        {"vfe_shock": -50},             # 1: VFE -50 shock
        {"vfe_shock": +50},             # 2: VFE +50 shock
        {"hp_mute": True},              # 3: HP S17 thinned
        {"no_spread17": True},          # 4: no S17 events
        {"noise": 1.5},                 # 5: gaussian noise on mids
        {},                             # 6: bootstrap
        {"vfe_shock": -100},            # 7: VFE crash
        {"vfe_shock": +30, "noise": 1.0},
        {"hp_mute": True, "vfe_shock": -30},
        {"no_spread17": True, "vfe_shock": -50},
        {"noise": 2.5},
        {},
        {"vfe_shock": -200},            # 13: extreme VFE crash
    ]

    for seed in range(args.seeds):
        seed_val = 1000 + seed * 17
        for batch in range(14):
            kwargs = perturbations[batch] if args.adversarial_mix else {}
            regen(seed_val, batch, **kwargs)

        pnl, per_product = run_strategy(args.strategy)
        for batch in range(14):
            pnl_val = pnl.get(batch, 0)
            label = "+".join(f"{k}={v}" for k, v in (perturbations[batch] if args.adversarial_mix else {}).items()) or "boot"
            rows.append({
                "seed": seed_val,
                "batch": batch,
                "label": label,
                "pnl": pnl_val,
                "per_product": per_product.get(batch, {}),
            })
            all_pnls.append(pnl_val)
            print(f"seed={seed_val} batch={batch:2d} {label:30s} pnl={pnl_val:>10,}")

    # Aggregate
    p = sorted(all_pnls)
    n = len(p)
    pct = lambda q: p[max(0, min(n - 1, int(q * (n - 1))))]
    summary = {
        "tag": args.tag,
        "strategy": args.strategy,
        "n_days": n,
        "mean": statistics.mean(p),
        "median": statistics.median(p),
        "stdev": statistics.stdev(p) if n > 1 else 0,
        "min": min(p), "max": max(p),
        "p05": pct(0.05),
        "p25": pct(0.25),
        "p75": pct(0.75),
        "p95": pct(0.95),
        "n_loss_20k": sum(1 for x in all_pnls if x < -20_000),
        "n_loss_50k": sum(1 for x in all_pnls if x < -50_000),
    }
    with open(out_dir / f"{args.tag}_summary.json", "w") as f:
        json.dump({"summary": summary, "rows": rows}, f, indent=2)
    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\nWritten: {out_dir / f'{args.tag}_summary.json'}")

    # Tail analysis
    rows_sorted = sorted(rows, key=lambda r: r["pnl"])
    print("\n=== WORST 10 SCENARIOS ===")
    for r in rows_sorted[:10]:
        worst_prods = sorted(r["per_product"].items(), key=lambda kv: kv[1])[:3] if r["per_product"] else []
        wp_str = " ".join(f"{k}={v:,}" for k, v in worst_prods)
        print(f"  pnl={r['pnl']:>10,} seed={r['seed']} b={r['batch']:2d} {r['label']:30s} | worst: {wp_str}")


if __name__ == "__main__":
    main()
