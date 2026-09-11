"""
BACKTESTER CALIBRATION — tune taker bot parameters against website ground truth.

Runs strategies with known website scores through the backtester and computes
correlation. Sweeps taker interval and qty parameters to maximize correlation.

Run: python -u trader-logic/round-0/sweeps/calibrate_backtester.py
"""

import subprocess, re, os, time, json
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(BASE_DIR)))
ROUND_DIR = os.path.dirname(BASE_DIR)

# Known website scores (day -1, 2k ticks, 1000 iterations)
GROUND_TRUTH = {
    "s3_carry.py": 2857,
    "s25_training_only.py": 2855,
    "s27_cartesian_optimal.py": 2407,
    "s26_sweep_optimal.py": None,  # untested — will predict
}

# Strategies in experiments/ and early_versions/ that need PYTHONPATH
NEEDS_PYTHONPATH = {
    "experiments/s19_hybrid_fv.py": 2676,
    "experiments/s18_partial_clear.py": 2648,
    "early_versions/s2_tradeflow.py": 2851,
}


def run_backtest(strategy_path, day=-1, taker_sim=False, match_trades="all"):
    """Run backtester and return total PnL and per-product PnL."""
    flags = f"--ticks 2000 --iterations 1000 --no-out --no-progress --match-trades {match_trades}"
    if taker_sim:
        flags += " --taker-sim"
    cmd = f'python -m prosperity4bt "{strategy_path}" 0-{day} {flags}'
    env = os.environ.copy()
    env['PYTHONPATH'] = os.path.join(ROOT_DIR, 'prosperity4bt')
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True, cwd=ROOT_DIR, env=env)

    result = {'total': 0, 'TOMATOES': 0, 'EMERALDS': 0}
    for line in r.stdout.split('\n'):
        m = re.search(r'TOMATOES:\s*([\d,]+)', line)
        if m:
            result['TOMATOES'] = int(m.group(1).replace(',', ''))
        m = re.search(r'EMERALDS:\s*([\d,]+)', line)
        if m:
            result['EMERALDS'] = int(m.group(1).replace(',', ''))
        m = re.search(r'Total profit:\s*([\d,]+)', line)
        if m:
            result['total'] = int(m.group(1).replace(',', ''))

    if result['total'] == 0 and r.returncode != 0:
        print(f"  ERROR: {r.stderr[:200]}")

    return result


def spearman_rank_corr(x, y):
    """Compute Spearman rank correlation."""
    n = len(x)
    rank_x = np.argsort(np.argsort(x)).astype(float)
    rank_y = np.argsort(np.argsort(y)).astype(float)
    d = rank_x - rank_y
    return 1 - (6 * np.sum(d ** 2)) / (n * (n ** 2 - 1))


def run_all_strategies(mode_name, taker_sim=False, match_trades="all"):
    """Run all strategies and compare with website scores."""
    print(f"\n{'='*60}")
    print(f"  MODE: {mode_name}")
    print(f"  taker_sim={taker_sim}, match_trades={match_trades}")
    print(f"{'='*60}")

    local_scores = []
    website_scores = []
    names = []

    # Main strategies in round-0/
    for strat, website_score in GROUND_TRUTH.items():
        if website_score is None:
            continue
        path = os.path.join(ROUND_DIR, strat)
        if not os.path.exists(path):
            print(f"  SKIP (not found): {strat}")
            continue
        r = run_backtest(path, taker_sim=taker_sim, match_trades=match_trades)
        print(f"  {strat:35s}  local={r['total']:,}  website={website_score:,}  "
              f"(TOM={r['TOMATOES']:,} EM={r['EMERALDS']:,})")
        local_scores.append(r['total'])
        website_scores.append(website_score)
        names.append(strat)

    # Strategies in subdirs
    for rel_path, website_score in NEEDS_PYTHONPATH.items():
        path = os.path.join(ROUND_DIR, rel_path)
        if not os.path.exists(path):
            print(f"  SKIP (not found): {rel_path}")
            continue
        r = run_backtest(path, taker_sim=taker_sim, match_trades=match_trades)
        print(f"  {rel_path:35s}  local={r['total']:,}  website={website_score:,}  "
              f"(TOM={r['TOMATOES']:,} EM={r['EMERALDS']:,})")
        local_scores.append(r['total'])
        website_scores.append(website_score)
        names.append(rel_path)

    if len(local_scores) < 3:
        print("  Not enough data for correlation")
        return {}

    x = np.array(local_scores, dtype=float)
    y = np.array(website_scores, dtype=float)

    # Pearson correlation
    pearson = np.corrcoef(x, y)[0, 1]
    # Spearman rank correlation
    spearman = spearman_rank_corr(x, y)
    # Linear fit
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    residuals = y - predicted
    rmse = np.sqrt(np.mean(residuals ** 2))

    print(f"\n  CORRELATION:")
    print(f"    Pearson r  = {pearson:.4f}")
    print(f"    Spearman r = {spearman:.4f}")
    print(f"    Linear fit: website = {slope:.3f} * local + {intercept:.0f}")
    print(f"    RMSE       = {rmse:.0f}")

    # Check ranking
    local_rank = np.argsort(np.argsort(-x))
    website_rank = np.argsort(np.argsort(-y))
    print(f"\n  RANKINGS (lower=better):")
    for i, name in enumerate(names):
        match = "OK" if local_rank[i] == website_rank[i] else "MISMATCH"
        print(f"    {name:35s}  local_rank={local_rank[i]+1}  website_rank={website_rank[i]+1}  {match}")

    return {
        'pearson': pearson, 'spearman': spearman,
        'slope': slope, 'intercept': intercept, 'rmse': rmse,
        'local': local_scores, 'website': website_scores, 'names': names,
    }


def main():
    print("BACKTESTER CALIBRATION")
    print(f"Root: {ROOT_DIR}")
    print(f"Strategies dir: {ROUND_DIR}")

    results = {}

    # Mode 1: Default (match-trades all, no taker sim)
    results['default'] = run_all_strategies("Default (match-trades=all)", taker_sim=False, match_trades="all")

    # Mode 2: match-trades worse
    results['worse'] = run_all_strategies("match-trades=worse", taker_sim=False, match_trades="worse")

    # Mode 3: Taker simulation
    results['taker_sim'] = run_all_strategies("Taker Simulation", taker_sim=True, match_trades="all")

    # Mode 4: Taker sim + match-trades worse (belt AND suspenders)
    results['taker_worse'] = run_all_strategies("Taker Sim + worse", taker_sim=True, match_trades="worse")

    # Summary
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  {'Mode':25s}  {'Pearson':>8s}  {'Spearman':>8s}  {'RMSE':>6s}")
    for mode, r in results.items():
        if r:
            print(f"  {mode:25s}  {r['pearson']:8.4f}  {r['spearman']:8.4f}  {r['rmse']:6.0f}")

    # Save
    out = os.path.join(BASE_DIR, 'calibration_results.json')
    with open(out, 'w') as f:
        json.dump({k: {kk: (vv if not isinstance(vv, np.floating) else float(vv))
                       for kk, vv in v.items()} for k, v in results.items() if v},
                  f, indent=2, default=lambda x: x.tolist() if hasattr(x, 'tolist') else str(x))
    print(f"\n  Saved to {out}")


if __name__ == '__main__':
    main()
