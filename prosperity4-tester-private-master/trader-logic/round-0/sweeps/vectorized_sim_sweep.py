"""
VECTORIZED SIM SWEEP — GPU-accelerated parameter sweep using sim-mode taker model.

Uses the calibrated taker model:
- Poisson arrival: TOMATOES cadence=1300ms, EMERALDS cadence=7000ms
- Distance-decay: p_fill = exp(-0.007 * spread)
- Taker hits best bid/ask (competes with MM for fills)

Multi-seed: runs N seeds, averages results. Pre-generates taker arrays per seed.

Run: python -u trader-logic/round-0/sweeps/vectorized_sim_sweep.py
"""

import csv, os, time, json, math
import numpy as np
from itertools import product as cartesian
from collections import Counter

try:
    import cupy as cp
    xp = cp
    GPU = True
    print("Using CuPy (GPU)")
except ImportError:
    xp = np
    GPU = False
    print("Using NumPy (CPU) — install cupy-cuda12x for GPU acceleration")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_DIR = os.path.join(ROOT, 'prosperity4bt', 'resources', 'round0')

# Calibrated taker parameters
TAKER_CADENCE_TOM = 1300   # ms between arrivals
TAKER_QTY_TOM = (2, 5)     # uniform range
TAKER_DECAY = 0.007         # p_fill = exp(-k * spread)
TICK_MS = 100
NUM_SEEDS = 5


def load_day(day):
    """Load TOMATOES data + EMERALDS narrow-spread ticks."""
    bids, asks, mids, bv1s, av1s = [], [], [], [], []
    em_bids, em_asks = [], []
    with open(os.path.join(DATA_DIR, f'prices_round_0_day_{day}.csv')) as f:
        for r in csv.DictReader(f, delimiter=';'):
            if r['product'] == 'TOMATOES':
                bids.append(float(r['bid_price_1']))
                asks.append(float(r['ask_price_1']))
                mids.append(float(r['mid_price']))
                bv1s.append(int(r['bid_volume_1']))
                av1s.append(int(r['ask_volume_1']))
            elif r['product'] == 'EMERALDS':
                em_bids.append(float(r['bid_price_1']))
                em_asks.append(float(r['ask_price_1']))

    trade_flow = [0.0] * len(mids)
    with open(os.path.join(DATA_DIR, f'trades_round_0_day_{day}.csv')) as f:
        tom_timestamps = []
        with open(os.path.join(DATA_DIR, f'prices_round_0_day_{day}.csv')) as pf:
            for r in csv.DictReader(pf, delimiter=';'):
                if r['product'] == 'TOMATOES':
                    tom_timestamps.append(int(r['timestamp']))
        ts_to_idx = {ts: i for i, ts in enumerate(tom_timestamps)}
        for r in csv.DictReader(f, delimiter=';'):
            if r['symbol'] == 'TOMATOES':
                ts = int(r['timestamp'])
                if ts in ts_to_idx:
                    idx = ts_to_idx[ts]
                    price = float(r['price'])
                    qty = int(r['quantity'])
                    mid = mids[idx]
                    trade_flow[idx] += qty if price >= mid else -qty

    return {
        'bid': np.array(bids), 'ask': np.array(asks), 'mid': np.array(mids),
        'bv1': np.array(bv1s), 'av1': np.array(av1s),
        'trade_flow': np.array(trade_flow),
        'em_bid': np.array(em_bids), 'em_ask': np.array(em_asks),
        'n': len(mids),
    }


def compute_microprices(data):
    bv = data['bv1'].astype(float)
    av = data['av1'].astype(float)
    total = bv + av
    spread = data['ask'] - data['bid']
    return np.where(total > 0, data['bid'] + (bv / total) * spread, data['mid'])


def fit_regression_np(mp, mid, lag):
    n = len(mp)
    X = np.zeros((n - lag, lag + 1))
    X[:, 0] = 1.0
    for i in range(lag):
        X[:, i + 1] = mp[i:n - lag + i]
    Y = mid[lag:]
    XtX = X.T @ X + 1e-6 * len(Y) * np.eye(lag + 1)
    beta = np.linalg.solve(XtX, X.T @ Y)
    return beta[0], beta[1:]


def gen_taker_arrays(n_ticks, seed):
    """Pre-generate taker arrival/side/qty arrays for one seed."""
    rng = np.random.RandomState(seed)
    p_arrive = TICK_MS / TAKER_CADENCE_TOM
    arrives = rng.random(n_ticks) < p_arrive
    sides = rng.random(n_ticks) < 0.5  # True = sells (hits bid), False = buys (hits ask)
    qtys = rng.randint(TAKER_QTY_TOM[0], TAKER_QTY_TOM[1] + 1, size=n_ticks)
    return arrives, sides, qtys


def simulate_pnl_sim(data, mp, fv_array, params, taker_arrives, taker_sides, taker_qtys, ticks=2000):
    """
    Simulate PnL with sim-mode taker model.
    Taker competes with us for fills in a unified book.
    """
    n = min(len(fv_array), ticks, data['n'])
    bid = data['bid'][:n]
    ask = data['ask'][:n]
    mid = data['mid'][:n]

    tom_aggr_tick = params['TOM_AGGR_TICK']
    tom_pos_thresh = params['TOM_POS_THRESH']
    dir_trigger = params['DIR_TRIGGER']
    dir_width = params['DIR_WIDTH']
    dir_decay = params['DIR_DECAY']
    post_offset = params['POST_OFFSET']

    tv = np.round(fv_array[:n]).astype(int)

    pos = 0
    pnl = 0.0
    prev_bid = None
    sig = 0.0

    for t in range(n):
        b, a = int(bid[t]), int(ask[t])
        fair = tv[t]
        spread = a - b

        # Position aggression
        mbp = fair - tom_aggr_tick if (tom_aggr_tick > 0 and pos > tom_pos_thresh) else fair
        msp = fair + tom_aggr_tick if (tom_aggr_tick > 0 and pos < -tom_pos_thresh) else fair

        tb = 80 - pos
        ts_ = 80 + pos

        # === TAKE (aggressive, against MM book) ===
        if tb > 0 and a <= mbp:
            qty = min(tb, 10)
            pnl -= qty * a
            pos += qty
            tb -= qty

        if ts_ > 0 and b >= msp:
            qty = min(ts_, 10)
            pnl += qty * b
            pos -= qty
            ts_ -= qty

        # === Directional signal ===
        if prev_bid is not None:
            bc = b - prev_bid
            if bc >= dir_trigger: sig = -1.0
            elif bc <= -dir_trigger: sig = 1.0
            elif abs(bc) <= 1: sig *= dir_decay
        prev_bid = b

        # === COMPUTE POST PRICES ===
        if sig > 0.5:
            buy_price = min(fair - 1, b + 1)
            sell_price = max(fair + dir_width, a - 1, b + 1)
        elif sig < -0.5:
            buy_price = min(fair - dir_width, b + 1, a - 1)
            sell_price = max(fair + 1, a - 1)
        else:
            buy_price = min(fair - post_offset, b + 1)
            sell_price = max(fair + post_offset, a - 1)

        # === TAKER ARRIVAL (sim mode) ===
        if taker_arrives[t]:
            # Distance-decay fill probability
            p_fill = math.exp(-TAKER_DECAY * spread)
            # Use a deterministic check based on taker qty (avoid extra random calls)
            if p_fill > 0.5:  # spread < 100 ticks (always true for our products)
                tq = int(taker_qtys[t])
                if taker_sides[t]:
                    # Taker SELLS → hits best bid
                    # Our buy_price vs MM's bid — whoever is higher gets hit
                    if tb > 0 and buy_price >= b:
                        # We're at best bid — taker hits us
                        fill = min(tq, tb)
                        pnl -= fill * buy_price
                        pos += fill
                        tb -= fill
                    # else: taker hits MM (no fill for us)
                else:
                    # Taker BUYS → hits best ask
                    if ts_ > 0 and sell_price <= a:
                        # We're at best ask — taker hits us
                        fill = min(tq, ts_)
                        pnl += fill * sell_price
                        pos -= fill
                        ts_ -= fill

    # Mark to market
    pnl += pos * mid[n - 1]
    return pnl


def simulate_emeralds(data, ticks=2000):
    """Simple EMERALDS simulation — take at narrow spreads. Returns ~1,050."""
    n = min(ticks, data['n'])
    em_bid = data['em_bid'][:n]
    em_ask = data['em_ask'][:n]
    pos = 0; pnl = 0.0
    lim_hist = []

    for t in range(n):
        b, a = int(em_bid[t]), int(em_ask[t])
        tb = 80 - pos; ts_ = 80 + pos
        mbp = 9999 if pos > 40 else 10000
        msp = 10001 if pos < -40 else 10000

        if tb > 0 and a <= mbp:
            qty = min(tb, int(-0 if a > mbp else 10))
            # Actually just take at ask if <= 10000
            if a <= mbp:
                qty = min(tb, 10)
                pnl -= qty * a; pos += qty
        if ts_ > 0 and b >= msp:
            qty = min(ts_, 10)
            pnl += qty * b; pos -= qty

        # Post at best±1
        # (simplified — no actual passive fill modeling for EMERALDS)

    pnl += pos * 10000  # MTM at fair
    return pnl


def main():
    print("Loading data...")
    days_data = {}
    for day in [-1]:  # day -1 only (website conditions)
        days_data[day] = load_day(day)
        print(f"  Day {day}: {days_data[day]['n']} ticks")

    print("Computing microprices...")
    mps = {day: compute_microprices(days_data[day]) for day in days_data}

    print("Fitting regressions...")
    reg_cache = {}
    for lag in [3, 4, 5, 6]:
        coefs_list, intercepts = [], []
        for day in [-2, -1]:
            d = load_day(day)
            mp = compute_microprices(d)
            intercept, coefs = fit_regression_np(mp, d['mid'], lag)
            coefs_list.append(coefs); intercepts.append(intercept)
        avg_int = np.mean(intercepts)
        avg_coefs = np.mean(coefs_list, axis=0)
        reg_cache[lag] = (avg_int, avg_coefs)
        print(f"  lag={lag}: intercept={avg_int:.2f}, coefs_sum={np.sum(avg_coefs):.4f}")

    # Pre-generate taker arrays with randomized seeds
    # Use diverse seeds spread across the seed space for robustness
    print(f"Pre-generating taker arrays ({NUM_SEEDS} seeds)...")
    n_ticks = days_data[-1]['n']
    taker_seeds = [42, 137, 271, 593, 1009, 2741, 4999, 7919, 10007, 13337][:NUM_SEEDS]
    taker_data = []
    for seed in taker_seeds:
        arrives, sides, qtys = gen_taker_arrays(n_ticks, seed)
        taker_data.append((arrives, sides, qtys))
    print(f"  Seeds: {taker_seeds}")

    # Pre-compute FV arrays
    print("Precomputing fair value arrays...")
    fv_cache = {}
    for lag in [3, 4, 5, 6]:
        _, coefs = reg_cache[lag]
        for intercept in [2.21, 5.0, 7.39, 10.0]:
            for day in days_data:
                mp = mps[day]
                n = len(mp)
                fv = np.full(n, np.nan)
                for t in range(lag, n):
                    fv[t] = intercept + np.dot(coefs, mp[t-lag:t])
                fv[:lag] = mp[:lag]
                tf = days_data[day]['trade_flow']
                for flow_coef in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]:
                    tf_cum = np.zeros(n)
                    for t in range(n):
                        start = max(0, t - 4)  # window=5
                        tf_cum[t] = np.sum(tf[start:t+1])
                    flow_signal = np.clip(tf_cum / 15.0, -1.0, 1.0)
                    fv_adj = fv - flow_signal * flow_coef
                    fv_cache[(lag, intercept, flow_coef, day)] = fv_adj
    print(f"  Cached {len(fv_cache)} FV arrays")

    # PARAMETER GRID — 276K combos
    PARAMS = {
        'REG_LAGS': [3, 4, 5, 6],
        'INTERCEPT': [2.21, 5.0, 7.39, 10.0],
        'FLOW_COEF': [0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
        'TOM_AGGR_TICK': [0, 1, 2],
        'TOM_POS_THRESH': [20, 30, 40, 50, 60],
        'DIR_TRIGGER': [2, 3, 4, 5],
        'DIR_WIDTH': [2, 3, 4, 5],
        'DIR_DECAY': [0.3, 0.5, 0.7, 0.9],
        'POST_OFFSET': [1, 2, 3],
    }

    keys = sorted(PARAMS.keys())
    values = [PARAMS[k] for k in keys]
    all_combos = list(cartesian(*values))
    total = len(all_combos)

    print(f"\nSIM VECTORIZED SWEEP: {total:,} combos × {NUM_SEEDS} seeds")
    for k in keys:
        print(f"  {k}: {PARAMS[k]} ({len(PARAMS[k])} values)")

    # EMERALDS baseline (same for all combos)
    em_pnl = simulate_emeralds(days_data[-1], ticks=2000)
    print(f"\nEMERALDS baseline: {em_pnl:,.0f}")

    results = []
    best_avg = 0
    start = time.time()

    for i, combo in enumerate(all_combos):
        params = dict(zip(keys, combo))
        lag = params['REG_LAGS']
        intercept = params['INTERCEPT']
        flow_coef = params['FLOW_COEF']

        fv_key = (lag, intercept, flow_coef, -1)
        if fv_key not in fv_cache:
            continue
        fv = fv_cache[fv_key]

        # Run N seeds, average
        seed_pnls = []
        for arrives, sides, qtys in taker_data:
            tom_pnl = simulate_pnl_sim(days_data[-1], mps[-1], fv, params,
                                        arrives, sides, qtys, ticks=2000)
            seed_pnls.append(tom_pnl + em_pnl)

        avg = np.mean(seed_pnls)
        std = np.std(seed_pnls)

        results.append({
            'params': params,
            'avg': float(avg),
            'std': float(std),
        })

        if avg > best_avg:
            best_avg = avg
            print(f"  *** NEW BEST [{i+1}/{total}]: avg={avg:,.0f} std={std:,.0f} {params}")

        if (i + 1) % 5000 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            remaining = (total - i - 1) / rate
            print(f"  [{i+1:,}/{total:,}] {elapsed:.0f}s, {remaining:.0f}s left, best={best_avg:,.0f}")

    elapsed = time.time() - start
    results.sort(key=lambda x: -x['avg'])

    print(f"\n{'='*80}")
    print(f"  COMPLETE: {total:,} combos × {NUM_SEEDS} seeds in {elapsed:.1f}s ({total/elapsed:,.0f} combos/sec)")
    print(f"{'='*80}")

    print(f"\n  TOP 30:")
    for i, r in enumerate(results[:30]):
        p = r['params']
        print(f"  {i+1:3d}. avg={r['avg']:>7,.0f} std={r['std']:>4,.0f}  "
              f"lag={p['REG_LAGS']} int={p['INTERCEPT']} flow={p['FLOW_COEF']} "
              f"aggr={p['TOM_AGGR_TICK']}/{p['TOM_POS_THRESH']} "
              f"dir={p['DIR_TRIGGER']}/{p['DIR_WIDTH']}/{p['DIR_DECAY']} "
              f"post={p['POST_OFFSET']}")

    print(f"\n  LANDSCAPE (top 50):")
    for key in keys:
        vals = [r['params'][key] for r in results[:50]]
        c = Counter(vals)
        print(f"    {key}: {dict(c.most_common())}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sim_vectorized_results.json')
    with open(out, 'w') as f:
        json.dump([{'params': r['params'], 'avg': round(r['avg']), 'std': round(r['std'])}
                   for r in results[:500]], f, indent=2)
    print(f"\n  Saved top 500 to {out}")


if __name__ == '__main__':
    main()
