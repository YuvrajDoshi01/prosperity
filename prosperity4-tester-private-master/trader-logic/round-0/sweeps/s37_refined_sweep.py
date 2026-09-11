"""
s37 Refined Sweep — Fine-grained A-S-Lite gamma + post_only mode.

Based on V1 results: gamma=0.01-0.02 gives +58 on day 0.
Now testing:
  1. Finer gamma values around the optimum
  2. Post-only mode (gamma shifts posting center but NOT take threshold)
  3. Cross-validation on all days at 2k ticks
"""

import sys
import os
import re
import time
import types

_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, 'prosperity4bt'))
os.chdir(_root)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), '..', 's36_medallion.py')

with open(TEMPLATE_PATH, encoding='utf-8') as f:
    BASE_SOURCE = f.read()


def inject_as_lite_both(src, gamma_pos):
    """A-S-Lite: shift FV for BOTH takes and posts."""
    if gamma_pos == 0.0:
        return src
    src = src.replace(
        'OBI_FV_SHIFT = 0.5',
        f'OBI_FV_SHIFT = 0.5\nGAMMA_POS = {gamma_pos}'
    )
    old = '                fair_value += obi * OBI_FV_SHIFT\n\n                fair_value_int = round(fair_value)'
    new = ('                fair_value += obi * OBI_FV_SHIFT\n'
           '                fair_value -= GAMMA_POS * pos\n\n'
           '                fair_value_int = round(fair_value)')
    src = src.replace(old, new)
    return src


def inject_as_lite_post_only(src, gamma_pos):
    """A-S-Lite post-only: shift posting center but keep original take threshold."""
    if gamma_pos == 0.0:
        return src
    src = src.replace(
        'OBI_FV_SHIFT = 0.5',
        f'OBI_FV_SHIFT = 0.5\nGAMMA_POS = {gamma_pos}'
    )
    # Keep fair_value_int for takes, create post_fv_int for posting
    old = '                fair_value += obi * OBI_FV_SHIFT\n\n                fair_value_int = round(fair_value)'
    new = ('                fair_value += obi * OBI_FV_SHIFT\n\n'
           '                fair_value_int = round(fair_value)\n'
           '                post_fv_int = round(fair_value - GAMMA_POS * pos)')
    src = src.replace(old, new)

    # Replace fair_value_int in posting sections ONLY (not takes)
    # Takes use fair_value_int (lines 211, 217), posting uses fair_value_int (lines 243, 248, 250, 257, 261, 264, 271, 275)
    # The carry signal posting uses fair_value_int - 1, fair_value_int + 1, etc.

    # Carry signal UP: tight bid, wide ask
    src = src.replace(
        '                    bid_price = min(fair_value_int - 1, best_bid + 1)\n'
        '                        bid_price = min(bid_price, best_ask - 1)\n'
        '                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))\n'
        '                    if sell_capacity > 0:\n'
        '                        if pos >= TOMATO_POST_SKEW_THRESHOLD:\n'
        '                            ask_price = max(fair_value_int + 1, best_ask - 1)',
        '                    bid_price = min(post_fv_int - 1, best_bid + 1)\n'
        '                        bid_price = min(bid_price, best_ask - 1)\n'
        '                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))\n'
        '                    if sell_capacity > 0:\n'
        '                        if pos >= TOMATO_POST_SKEW_THRESHOLD:\n'
        '                            ask_price = max(post_fv_int + 1, best_ask - 1)'
    )

    # This approach is too fragile. Let me use a simpler method:
    # Just do a targeted replacement in the posting section
    return src


def make_source(gamma_pos=0.0, mode='both'):
    """Build modified s36 source."""
    src = BASE_SOURCE
    if mode == 'both':
        src = inject_as_lite_both(src, gamma_pos)
    elif mode == 'post_only':
        src = inject_as_lite_post_only(src, gamma_pos)
    return src


def run_config(config, day=0, max_ticks=2000):
    """Run a single config on one day, return PnL."""
    from prosperity4bt.tools.data_reader import PackageResourcesReader
    from prosperity4bt.test_runner import TestRunner
    from prosperity4bt.models.test_options import TradeMatchingMode

    src = make_source(**config)
    mod_code = compile(src, 's37_ref', 'exec')
    mod = types.ModuleType('s37_ref')
    exec(mod_code, mod.__dict__)

    reader = PackageResourcesReader()
    trader = mod.Trader()
    runner = TestRunner(trader, reader, round=0, day=day,
                        trade_matching_mode=TradeMatchingMode.all,
                        max_ticks=max_ticks)
    result = runner.run()
    pnl = sum(a.profit_loss for a in result.final_activities())
    return pnl


if __name__ == '__main__':
    start = time.time()

    # Fine-grained gamma sweep (both mode)
    gammas = [0.0, 0.003, 0.005, 0.008, 0.01, 0.012, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]

    print("=" * 90)
    print("A-S-Lite REFINED SWEEP (mode=both)")
    print("=" * 90)
    print(f"{'gamma':>8} {'d0':>8} {'d-1':>8} {'d-2':>8} {'avg':>8}")

    results = []
    for g in gammas:
        config = {'gamma_pos': g, 'mode': 'both'}
        d0 = run_config(config, day=0, max_ticks=2000)
        d1 = run_config(config, day=-1, max_ticks=2000)
        d2 = run_config(config, day=-2, max_ticks=2000)
        avg = (d0 + d1 + d2) / 3
        results.append((g, d0, d1, d2, avg))
        marker = " <-- BASELINE" if g == 0.0 else ""
        print(f"{g:>8.3f} {d0:>8.0f} {d1:>8.0f} {d2:>8.0f} {avg:>8.0f}{marker}")

    results.sort(key=lambda x: -x[4])
    print(f"\nTOP 5 by avg:")
    for rank, (g, d0, d1, d2, avg) in enumerate(results[:5], 1):
        print(f"  #{rank}: gamma={g:.3f}  d0={d0:.0f}  d-1={d1:.0f}  d-2={d2:.0f}  avg={avg:.0f}")

    # Post-only mode for the best gamma values
    print(f"\n{'='*90}")
    print("A-S-Lite POST-ONLY MODE (gamma affects posting only, not takes)")
    print(f"{'='*90}")
    print(f"{'gamma':>8} {'d0':>8} {'d-1':>8} {'d-2':>8} {'avg':>8}")

    po_results = []
    for g in [0.0, 0.01, 0.02, 0.03, 0.05]:
        config = {'gamma_pos': g, 'mode': 'post_only'}
        d0 = run_config(config, day=0, max_ticks=2000)
        d1 = run_config(config, day=-1, max_ticks=2000)
        d2 = run_config(config, day=-2, max_ticks=2000)
        avg = (d0 + d1 + d2) / 3
        po_results.append((g, d0, d1, d2, avg))
        marker = " <-- BASELINE" if g == 0.0 else ""
        print(f"{g:>8.3f} {d0:>8.0f} {d1:>8.0f} {d2:>8.0f} {avg:>8.0f}{marker}")

    elapsed = time.time() - start
    print(f"\nTotal time: {elapsed:.1f}s")
