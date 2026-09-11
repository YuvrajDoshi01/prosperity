"""
s36_medallion exhaustive hyperparameter sweep.

Sweeps ALL tunable parameters across ALL 3 days simultaneously.
Reports: day0, day-1, day-2, total. Ranks by total (cross-day stability).

Parameters swept:
  1. OBI_FV_SHIFT: [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
  2. TRADE_FLOW_COEF: [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
  3. TRADE_FLOW_WINDOW: [3, 5, 7, 10]
  4. CARRY_TRIGGER: [3, 4, 5, 6]
  5. CARRY_DECAY: [0.5, 0.6, 0.7, 0.8, 0.9]
  6. CARRY_WIDE_OFFSET: [1, 2, 3, 4, 5]
  7. TERMINAL_POSITION_THRESHOLD: [5, 10, 15, 20, 30]
  8. EMERALD_AGGRESSION_THRESHOLD: [30, 40, 50, 60, 999]
  9. REGRESSION_INTERCEPT: [1.5, 2.0, 2.208667, 2.5, 2.75, 3.0]
 10. TOMATO_POST_SKEW_THRESHOLD: [20, 30, 40, 50, 60]

Full cartesian = 7*6*4*4*5*5*5*5*6*5 = 63M combos. Way too many.
Strategy: sweep each dimension independently (hold others at current best),
then do pairwise interactions for the top 3 most sensitive params.
"""

import sys
import os
import importlib.util
import json
import itertools
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import defaultdict

_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
sys.path.insert(0, os.path.join(_root, 'prosperity4bt'))
os.chdir(_root)

TEMPLATE = os.path.join(os.path.dirname(__file__), '..', 's36_medallion.py')

# Current best values
DEFAULTS = {
    'OBI_FV_SHIFT': 0.5,
    'TRADE_FLOW_COEF': 1.5,
    'TRADE_FLOW_WINDOW': 5,
    'TRADE_FLOW_NORM': 15.0,
    'CARRY_TRIGGER': 4,
    'CARRY_DECAY': 0.7,
    'CARRY_WIDE_OFFSET': 3,
    'CARRY_THRESHOLD': 0.5,
    'TERMINAL_TIMESTAMP': 900000,
    'TERMINAL_POSITION_THRESHOLD': 10,
    'EMERALD_AGGRESSION_THRESHOLD': 40,
    'REGRESSION_INTERCEPT': 2.208667,
    'TOMATO_POST_SKEW_THRESHOLD': 40,
}

SWEEPS = {
    'OBI_FV_SHIFT':                [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0],
    'TRADE_FLOW_COEF':             [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
    'TRADE_FLOW_WINDOW':           [3, 5, 7, 10, 15],
    'TRADE_FLOW_NORM':             [5.0, 10.0, 15.0, 20.0, 30.0],
    'CARRY_TRIGGER':               [2, 3, 4, 5, 6, 8],
    'CARRY_DECAY':                 [0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    'CARRY_WIDE_OFFSET':           [1, 2, 3, 4, 5, 6],
    'CARRY_THRESHOLD':             [0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
    'TERMINAL_TIMESTAMP':          [800000, 850000, 900000, 950000],
    'TERMINAL_POSITION_THRESHOLD': [5, 10, 15, 20, 30, 50],
    'EMERALD_AGGRESSION_THRESHOLD':[20, 30, 40, 50, 60, 999],
    'REGRESSION_INTERCEPT':        [1.0, 1.5, 2.0, 2.208667, 2.5, 2.75, 3.0, 3.5],
    'TOMATO_POST_SKEW_THRESHOLD':  [20, 30, 40, 50, 60, 80],
}


def make_source(overrides):
    with open(TEMPLATE, encoding='utf-8') as f:
        src = f.read()
    for key, val in overrides.items():
        if isinstance(val, float):
            # Match the line: KEY = <number>
            import re
            src = re.sub(rf'^({key}\s*=\s*)[\d.]+', rf'\g<1>{val}', src, flags=re.MULTILINE)
        elif isinstance(val, int):
            import re
            src = re.sub(rf'^({key}\s*=\s*)[\d]+', rf'\g<1>{val}', src, flags=re.MULTILINE)
    return src


def run_config(overrides):
    """Run a single config across all 3 days, return {day: pnl}."""
    from prosperity4bt.tools.data_reader import PackageResourcesReader
    from prosperity4bt.test_runner import TestRunner
    from prosperity4bt.models.test_options import TradeMatchingMode

    src = make_source(overrides)
    # Compile and exec
    mod_code = compile(src, 's36_sweep', 'exec')
    import types
    mod = types.ModuleType('s36_sweep')
    exec(mod_code, mod.__dict__)

    reader = PackageResourcesReader()
    results = {}
    for day in [0, -1, -2]:
        trader = mod.Trader()
        data = reader.read_from_file(0, day)
        ticks = 2000 if day == 0 else None
        runner = TestRunner(trader, reader, round=0, day=day,
                            trade_matching_mode=TradeMatchingMode.all,
                            max_ticks=ticks)
        result = runner.run()
        # Sum PnL
        pnl = sum(data.profit_loss.values())
        results[day] = pnl

    results['total'] = sum(results.values())
    return overrides, results


def sweep_dimension(param_name, values):
    """Sweep one dimension, keeping all others at defaults."""
    configs = []
    for val in values:
        overrides = {param_name: val}
        configs.append(overrides)
    return configs


if __name__ == '__main__':
    import time
    start = time.time()

    print("s36_medallion Exhaustive Hyperparameter Sweep")
    print("=" * 80)
    print(f"Sweeping {len(SWEEPS)} dimensions independently")
    print()

    all_results = {}

    # Phase 1: Independent sweeps
    for param, values in SWEEPS.items():
        print(f"\n--- {param} ({len(values)} values) ---")
        print(f"{'Value':>15} {'Day0':>7} {'Day-1':>7} {'Day-2':>7} {'Total':>8}")

        best_total = -999999
        best_val = None
        dim_results = []

        for val in values:
            overrides = {param: val}
            _, res = run_config(overrides)
            dim_results.append((val, res))
            marker = " <-- current" if val == DEFAULTS[param] else ""
            if res['total'] > best_total:
                best_total = res['total']
                best_val = val
                if val != DEFAULTS[param]:
                    marker = " <-- BEST"
            print(f"{str(val):>15} {res[0]:>7.0f} {res[-1]:>7.0f} {res[-2]:>7.0f} {res['total']:>8.0f}{marker}")

        all_results[param] = {
            'best_val': best_val,
            'best_total': best_total,
            'default_val': DEFAULTS[param],
            'results': dim_results,
        }

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY: Optimal values per dimension")
    print(f"{'Parameter':>35} {'Default':>10} {'Optimal':>10} {'Delta':>8}")
    print("-" * 70)

    optimal = dict(DEFAULTS)
    for param in SWEEPS:
        r = all_results[param]
        default_total = next((res['total'] for val, res in r['results']
                              if val == r['default_val']), 0)
        delta = r['best_total'] - default_total
        marker = " ***" if delta > 100 else ""
        print(f"{param:>35} {str(r['default_val']):>10} {str(r['best_val']):>10} {delta:>+8.0f}{marker}")
        optimal[param] = r['best_val']

    # Phase 2: Run with ALL optimal values combined
    print("\n" + "=" * 80)
    print("COMBINED OPTIMAL:")
    _, combined = run_config(optimal)
    print(f"Day0={combined[0]:.0f} Day-1={combined[-1]:.0f} Day-2={combined[-2]:.0f} Total={combined['total']:.0f}")

    # Compare to defaults
    _, defaults_res = run_config({})
    print(f"\nDefaults: Total={defaults_res['total']:.0f}")
    print(f"Optimal:  Total={combined['total']:.0f}")
    print(f"Delta:    {combined['total'] - defaults_res['total']:+.0f}")

    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.0f}s")

    # Save results
    out_path = os.path.join(os.path.dirname(__file__), 's36_hypersweep_results.json')
    with open(out_path, 'w') as f:
        json.dump({
            'optimal': {k: v for k, v in optimal.items()},
            'defaults': DEFAULTS,
            'per_dimension': {
                param: {
                    'best_val': r['best_val'],
                    'best_total': r['best_total'],
                    'values': [(v, {str(k): rv for k, rv in res.items()})
                               for v, res in r['results']]
                }
                for param, r in all_results.items()
            }
        }, f, indent=2)
    print(f"Results saved to {out_path}")
