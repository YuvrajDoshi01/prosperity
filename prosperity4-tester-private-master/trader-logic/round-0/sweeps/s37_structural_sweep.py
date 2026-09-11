"""
s37 Structural Sweep — Testing position-dependent FV shifts and EMERALDS OBI.

Attack vectors:
  V1: A-S-Lite — fair_value -= GAMMA_POS * pos (after OBI shift, before rounding)
  V2: EMERALDS OBI — em_fv = round(10000 + em_obi * EM_OBI_SHIFT)
  V3: Time-gated gamma — A-S-Lite only after GAMMA_START_TS

Extracts PnL from result.final_activities() (correct method).
Reports day 0 only for ranking (day 0 CSV = website data).
Cross-validates top configs on day -1.
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


def inject_as_lite(src, gamma_pos, gamma_start_ts=0):
    """Inject A-S-Lite position-dependent FV shift into TOMATOES section."""
    if gamma_pos == 0.0:
        return src

    # Add constant at top (after OBI_FV_SHIFT line)
    src = src.replace(
        'OBI_FV_SHIFT = 0.5',
        f'OBI_FV_SHIFT = 0.5\nGAMMA_POS = {gamma_pos}\nGAMMA_START_TS = {gamma_start_ts}'
    )

    # Inject the FV shift after OBI application, before rounding
    old = '                fair_value += obi * OBI_FV_SHIFT\n\n                fair_value_int = round(fair_value)'
    if gamma_start_ts == 0:
        new = ('                fair_value += obi * OBI_FV_SHIFT\n'
               '                fair_value -= GAMMA_POS * pos\n\n'
               '                fair_value_int = round(fair_value)')
    else:
        new = ('                fair_value += obi * OBI_FV_SHIFT\n'
               '                if state.timestamp >= GAMMA_START_TS:\n'
               '                    fair_value -= GAMMA_POS * pos\n\n'
               '                fair_value_int = round(fair_value)')
    src = src.replace(old, new)
    return src


def inject_em_obi(src, em_obi_shift):
    """Inject EMERALDS OBI dynamic FV."""
    if em_obi_shift == 0.0:
        return src

    # Add constant
    src = src.replace(
        'EMERALD_FV = 10000',
        f'EMERALD_FV = 10000\nEM_OBI_SHIFT = {em_obi_shift}'
    )

    # Inject OBI computation before position-dependent take aggression
    old_block = ('                # Position-dependent take aggression\n'
                 '                max_buy_price = EMERALD_FV if pos <= EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV - 1\n'
                 '                min_sell_price = EMERALD_FV if pos >= -EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV + 1')
    new_block = ('                # EMERALDS OBI dynamic FV\n'
                 '                em_bv = sum(book.buy_orders.values())\n'
                 '                em_av = sum(-v for v in book.sell_orders.values())\n'
                 '                em_obi = (em_bv - em_av) / (em_bv + em_av) if (em_bv + em_av) > 0 else 0.0\n'
                 '                em_fv = round(EMERALD_FV + em_obi * EM_OBI_SHIFT)\n'
                 '\n'
                 '                # Position-dependent take aggression\n'
                 '                max_buy_price = em_fv if pos <= EMERALD_AGGRESSION_THRESHOLD else em_fv - 1\n'
                 '                min_sell_price = em_fv if pos >= -EMERALD_AGGRESSION_THRESHOLD else em_fv + 1')
    src = src.replace(old_block, new_block)

    # Replace remaining EMERALD_FV usages in body (liquidation + posting)
    # These are all inside the run() method, not the constant def
    # Liquidation hard buy: Order("EMERALDS", EMERALD_FV, qty)
    src = src.replace('Order("EMERALDS", EMERALD_FV, qty)', 'Order("EMERALDS", em_fv, qty)')
    src = src.replace('Order("EMERALDS", EMERALD_FV, -qty)', 'Order("EMERALDS", em_fv, -qty)')
    # Liquidation soft: EMERALD_FV - 2, EMERALD_FV + 2
    src = src.replace('Order("EMERALDS", EMERALD_FV - 2, qty)', 'Order("EMERALDS", em_fv - 2, qty)')
    src = src.replace('Order("EMERALDS", EMERALD_FV + 2, -qty)', 'Order("EMERALDS", em_fv + 2, -qty)')
    # Post: EMERALD_FV - 1, EMERALD_FV + 1
    src = src.replace('bid_price = min(EMERALD_FV - 1,', 'bid_price = min(em_fv - 1,')
    src = src.replace('ask_price = max(EMERALD_FV + 1,', 'ask_price = max(em_fv + 1,')

    return src


def make_source(gamma_pos=0.0, gamma_start_ts=0, em_obi_shift=0.0):
    """Build modified s36 source with injected structural mechanisms."""
    src = BASE_SOURCE
    src = inject_as_lite(src, gamma_pos, gamma_start_ts)
    src = inject_em_obi(src, em_obi_shift)
    return src


def run_config(config, day=0):
    """Run a single config on one day, return PnL."""
    from prosperity4bt.tools.data_reader import PackageResourcesReader
    from prosperity4bt.test_runner import TestRunner
    from prosperity4bt.models.test_options import TradeMatchingMode

    src = make_source(**config)
    mod_code = compile(src, 's37_sweep', 'exec')
    mod = types.ModuleType('s37_sweep')
    exec(mod_code, mod.__dict__)

    reader = PackageResourcesReader()
    trader = mod.Trader()
    ticks = 2000 if day == 0 else None
    runner = TestRunner(trader, reader, round=0, day=day,
                        trade_matching_mode=TradeMatchingMode.all,
                        max_ticks=ticks)
    result = runner.run()

    # Extract PnL from final activity logs (correct: includes cash + MTM)
    pnl = sum(a.profit_loss for a in result.final_activities())
    return pnl


def run_sweep(name, configs, days=None):
    """Run a sweep and return sorted results."""
    if days is None:
        days = [0]
    print(f"\n{'='*80}")
    print(f"SWEEP: {name} ({len(configs)} configs × {len(days)} days)")
    print(f"{'='*80}")

    results = []
    for i, config in enumerate(configs):
        pnls = {}
        for day in days:
            pnl = run_config(config, day)
            pnls[day] = pnl
        pnls['avg'] = sum(pnls.values()) / len(pnls)
        results.append((config, pnls))
        label = ', '.join(f'{k}={v}' for k, v in config.items() if v != 0.0)
        if not label:
            label = 'BASELINE'
        day_str = '  '.join(f'd{d}={pnls[d]:>7.0f}' for d in days)
        print(f"  [{i+1:>2}/{len(configs)}] {label:<45} {day_str}  avg={pnls['avg']:>7.0f}")
        results.sort(key=lambda x: -x[1]['avg'])

    print(f"\n  TOP 5:")
    for rank, (config, pnls) in enumerate(results[:5], 1):
        label = ', '.join(f'{k}={v}' for k, v in config.items() if v != 0.0) or 'BASELINE'
        print(f"  #{rank}: {label:<45} avg={pnls['avg']:>7.0f}")

    return results


if __name__ == '__main__':
    start = time.time()

    # ═══════════════════════════════════════════════
    # SWEEP V1: A-S-Lite (position-dependent FV shift)
    # ═══════════════════════════════════════════════
    v1_configs = [{'gamma_pos': g} for g in
                  [0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]]
    v1_results = run_sweep("V1: A-S-Lite (GAMMA_POS)", v1_configs)

    # ═══════════════════════════════════════════════
    # SWEEP V2: EMERALDS OBI dynamic FV
    # ═══════════════════════════════════════════════
    v2_configs = [{'em_obi_shift': s} for s in
                  [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0]]
    v2_results = run_sweep("V2: EMERALDS OBI", v2_configs)

    # ═══════════════════════════════════════════════
    # SWEEP V3: Time-gated gamma (pre-terminal only)
    # ═══════════════════════════════════════════════
    v3_configs = []
    for g in [0.05, 0.10, 0.15, 0.20]:
        for ts in [500000, 700000]:
            v3_configs.append({'gamma_pos': g, 'gamma_start_ts': ts})
    v3_results = run_sweep("V3: Time-gated gamma", v3_configs)

    # ═══════════════════════════════════════════════
    # COMBINATION SWEEP: best from each vector
    # ═══════════════════════════════════════════════
    # Extract best non-baseline from each
    best_v1 = None
    baseline_pnl = v1_results[0][1]['avg'] if v1_results[0][0].get('gamma_pos', 0) == 0 else None
    for config, pnls in v1_results:
        if config.get('gamma_pos', 0) > 0:
            if baseline_pnl is None or pnls['avg'] > baseline_pnl:
                best_v1 = config
                break

    # Find baseline from v1 or v2
    if baseline_pnl is None:
        for config, pnls in v1_results:
            if config.get('gamma_pos', 0) == 0:
                baseline_pnl = pnls['avg']
                break

    best_v2 = None
    for config, pnls in v2_results:
        if config.get('em_obi_shift', 0) > 0:
            if pnls['avg'] > baseline_pnl:
                best_v2 = config
                break

    best_v3 = None
    for config, pnls in v3_results:
        if pnls['avg'] > baseline_pnl:
            best_v3 = config
            break

    combo_configs = []
    winners = [c for c in [best_v1, best_v2, best_v3] if c is not None]

    print(f"\n{'='*80}")
    print(f"WINNERS (beat baseline {baseline_pnl:.0f}):")
    for w in winners:
        print(f"  {w}")

    if len(winners) >= 2:
        # Pairwise combinations
        from itertools import combinations
        for combo in combinations(winners, 2):
            merged = {}
            for c in combo:
                merged.update(c)
            combo_configs.append(merged)
        # Triple combination
        if len(winners) == 3:
            merged = {}
            for c in winners:
                merged.update(c)
            combo_configs.append(merged)

    if combo_configs:
        combo_results = run_sweep("COMBINATIONS", combo_configs, days=[0, -1])

    # Cross-validate top 3 overall on day -1
    all_results = v1_results + v2_results + v3_results
    all_results.sort(key=lambda x: -x[1]['avg'])
    top3 = [r for r in all_results[:5] if r[0] != {'gamma_pos': 0.0} and r[0] != {}][:3]

    if top3:
        print(f"\n{'='*80}")
        print("CROSS-VALIDATION: Top 3 on day -1")
        print(f"{'='*80}")
        for config, day0_pnls in top3:
            pnl_d1 = run_config(config, day=-1)
            label = ', '.join(f'{k}={v}' for k, v in config.items())
            print(f"  {label:<45} d0={day0_pnls[0]:>7.0f}  d-1={pnl_d1:>7.0f}")

    elapsed = time.time() - start
    print(f"\nTotal time: {elapsed:.1f}s")
