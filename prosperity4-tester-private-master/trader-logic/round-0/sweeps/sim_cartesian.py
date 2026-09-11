"""
SIM CARTESIAN SWEEP: Full parameter grid on sim mode with multi-seed averaging.

Uses parallel workers for speed. Each combo runs N seeds on day -1.

Run: python -u trader-logic/round-0/sweeps/sim_cartesian.py
  env SWEEP_WORKERS=10 for 10 parallel workers (default: 8)
  env SWEEP_SEEDS=5 for 5 seeds (default: 5)
"""

import subprocess, re, json, os, sys, time, itertools, csv, statistics
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(BASE_DIR)))
ROUND_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(ROOT_DIR, 'prosperity4bt', 'resources', 'round0')

NUM_WORKERS = int(os.environ.get('SWEEP_WORKERS', '14'))
NUM_SEEDS = int(os.environ.get('SWEEP_SEEDS', '5'))
SEEDS = list(range(42, 42 + NUM_SEEDS))

# ============================================================
# FULL PARAMETER GRID
# ============================================================
PARAMS = {
    'INTERCEPT': [5.0, 7.39],
    'REG_LAGS': [4, 5, 6],
    'FLOW_COEF': [0.0, 0.5, 1.0, 1.5, 2.0],
    'TOM_AGGR_TICK': [0, 1],
    'TOM_POS_THRESH': [30, 40, 50],
    'DIR_TRIGGER': [2, 3, 4],
    'DIR_WIDTH': [3, 4, 5],
    'DIR_DECAY': [0.5, 0.7, 0.9],
    'EM_AGGRESSION': [0, 1],
    'POST_OFFSET': [1, 2],
}


def fit_regression(day, dim):
    mps, mids = [], []
    fname = os.path.join(DATA_DIR, f'prices_round_0_day_{day}.csv')
    with open(fname) as f:
        for r in csv.DictReader(f, delimiter=';'):
            if r['product'] == 'TOMATOES':
                bb = float(r['bid_price_1']); ba = float(r['ask_price_1'])
                bv = float(r['bid_volume_1']); av = float(r['ask_volume_1'])
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) / 2
                mps.append(mp); mids.append((bb + ba) / 2)
    import numpy as np
    X = []; Y = []
    for i in range(dim, len(mps)):
        X.append([mps[i - j - 1] for j in range(dim)])
        Y.append(mids[i])
    X = np.array(X); Y = np.array(Y)
    Xa = np.column_stack([np.ones(len(X)), X])
    coefs = np.linalg.lstsq(Xa, Y, rcond=None)[0]
    return coefs[0], coefs[1:].tolist()


def build_strategy(params, reg_cache):
    lag = params['REG_LAGS']
    reg_int, reg_coefs = reg_cache[lag]
    intercept = params['INTERCEPT']
    coef_expr = "+".join(f"{reg_coefs[i]}*c[{i}]" for i in range(lag))
    reg_line = f"fv={intercept}+{coef_expr}"

    code = f'''import json, random
from datamodel import Order, TradingState
class Trader:
    def __init__(self):
        self.tc=[];self.tf=[];self.ew=[];self.tw=[];self.pb=None;self.sig=0
    def bid(self): return 15
    def run(self, state):
        td=json.loads(state.traderData) if state.traderData else None
        if td: self.tc=td.get("c",[]);self.tf=td.get("f",[]);self.ew=td.get("w",[]);self.tw=td.get("tw",[]);self.pb=td.get("pb");self.sig=td.get("sg",0)
        orders={{}}
        if "EMERALDS" in state.order_depths:
            od=state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo=[];pos=state.position.get("EMERALDS",0);tb=80-pos;ts=80+pos
                buys=sorted(od.buy_orders.items(),reverse=True);sells=sorted(od.sell_orders.items())
                self.ew.append(abs(pos)==80)
                if len(self.ew)>10: self.ew=self.ew[-10:]
                soft=len(self.ew)==10 and sum(self.ew)>=5 and self.ew[-1]
                hard=len(self.ew)==10 and all(self.ew)
                embp=10000-{params['EM_AGGRESSION']} if pos>40 else 10000
                emsp=10000+{params['EM_AGGRESSION']} if pos<-40 else 10000
                for p,v in sells:
                    if tb>0 and p<=embp: q=min(tb,-v);eo.append(Order("EMERALDS",p,q));tb-=q
                if tb>0 and hard: q=tb//2;eo.append(Order("EMERALDS",10000,q));tb-=q
                if tb>0 and soft: q=tb//2;eo.append(Order("EMERALDS",9998,q));tb-=q
                if tb>0: eo.append(Order("EMERALDS",min(embp,buys[0][0]+1),tb))
                for p,v in buys:
                    if ts>0 and p>=emsp: q=min(ts,v);eo.append(Order("EMERALDS",p,-q));ts-=q
                if ts>0 and hard: q=ts//2;eo.append(Order("EMERALDS",10000,-q));ts-=q
                if ts>0 and soft: q=ts//2;eo.append(Order("EMERALDS",10002,-q));ts-=q
                if ts>0: eo.append(Order("EMERALDS",max(emsp,sells[0][0]-1),-ts))
                orders["EMERALDS"]=eo
        if "TOMATOES" in state.order_depths:
            od=state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to=[];bb,ba=max(od.buy_orders),min(od.sell_orders);pos=state.position.get("TOMATOES",0);mid=(bb+ba)*0.5
                bv=sum(od.buy_orders.values());av=sum(-v for v in od.sell_orders.values())
                mp=bb+(bv/(bv+av))*(ba-bb) if (bv+av)>0 else mid
                c=self.tc
                if len(c)>={lag}: c=c[1:]
                c.append(mp);self.tc=c
                if len(c)=={lag}: {reg_line}
                else: fv=mp
                trades=state.market_trades.get("TOMATOES")
                if trades: sv=sum(t.quantity if t.price>=mid else -t.quantity for t in trades);self.tf.append(sv)
                else: self.tf.append(0.0)
                if len(self.tf)>5: self.tf=self.tf[-5:]
                fs=max(-1.0,min(1.0,sum(self.tf)/15.0))
                fv-=fs*{params['FLOW_COEF']}
                tv=round(fv)
                if self.pb is not None:
                    bc=bb-self.pb
                    if bc>={params['DIR_TRIGGER']}: self.sig=-1
                    elif bc<=-{params['DIR_TRIGGER']}: self.sig=1
                    elif abs(bc)<=1: self.sig*={params['DIR_DECAY']}
                self.pb=bb
                self.tw.append(abs(pos)==80)
                if len(self.tw)>10: self.tw=self.tw[-10:]
                tsoft=len(self.tw)==10 and sum(self.tw)>=5 and self.tw[-1]
                thard=len(self.tw)==10 and all(self.tw)
                tb=80-pos;ts=80+pos
                mbp=tv-{params['TOM_AGGR_TICK']} if pos>{params['TOM_POS_THRESH']} else tv
                msp=tv+{params['TOM_AGGR_TICK']} if pos<-{params['TOM_POS_THRESH']} else tv
                for p,v in sorted(od.sell_orders.items()):
                    if tb>0 and p<=mbp: q=min(tb,-v);to.append(Order("TOMATOES",p,q));tb-=q
                if tb>0 and thard: q=tb//2;to.append(Order("TOMATOES",tv,q));tb-=q
                if tb>0 and tsoft: q=tb//2;to.append(Order("TOMATOES",tv-2,q));tb-=q
                for p,v in sorted(od.buy_orders.items(),reverse=True):
                    if ts>0 and p>=msp: q=min(ts,v);to.append(Order("TOMATOES",p,-q));ts-=q
                if ts>0 and thard: q=ts//2;to.append(Order("TOMATOES",tv,-q));ts-=q
                if ts>0 and tsoft: q=ts//2;to.append(Order("TOMATOES",tv+2,-q));ts-=q
                if self.sig>0.5:
                    if tb>0: to.append(Order("TOMATOES",min(tv-1,bb+1),tb))
                    if ts>0: to.append(Order("TOMATOES",max(tv+{params['DIR_WIDTH']},ba-1,bb+1),-ts))
                elif self.sig<-0.5:
                    if ts>0: to.append(Order("TOMATOES",max(tv+1,ba-1),-ts))
                    if tb>0: to.append(Order("TOMATOES",min(tv-{params['DIR_WIDTH']},bb+1,ba-1),tb))
                else:
                    if tb>0: to.append(Order("TOMATOES",min(tv-{params['POST_OFFSET']},bb+1),tb))
                    if ts>0: to.append(Order("TOMATOES",max(tv+{params['POST_OFFSET']},ba-1),-ts))
                orders["TOMATOES"]=to
        return orders,0,json.dumps({{"c":self.tc,"f":self.tf,"w":self.ew,"tw":self.tw,"pb":self.pb,"sg":round(self.sig,3)}},separators=(",",":"))
'''
    return code


def run_single(args):
    """Run one combo + one seed. Called by worker pool."""
    combo_idx, params, code, seed = args
    # Write to a unique temp file per worker to avoid collisions
    tmp = os.path.join(ROUND_DIR, f'_sim_tmp_{os.getpid()}.py')
    try:
        # Inject seed into code
        seeded_code = code.replace('import json, random', f'import json, random\nrandom.seed({seed})')
        with open(tmp, 'w') as f:
            f.write(seeded_code)

        cmd = [sys.executable, '-m', 'prosperity4bt', tmp, '0--1',
               '--no-out', '--no-progress', '--ticks', '2000',
               '--iterations', '1000', '--match-mode', 'sim']
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT_DIR, timeout=30)
        m = re.search(r'Total profit: ([\d,.-]+)', r.stdout)
        if m:
            return combo_idx, seed, int(m.group(1).replace(',', ''))
        return combo_idx, seed, 0
    except Exception as e:
        return combo_idx, seed, 0
    finally:
        try:
            os.remove(tmp)
        except:
            pass


def main():
    keys = sorted(PARAMS.keys())
    values = [PARAMS[k] for k in keys]
    all_combos = list(itertools.product(*values))

    # Pre-fit regressions
    print("Pre-fitting regressions...")
    reg_cache = {}
    for lag in PARAMS['REG_LAGS']:
        coefs_list = []; intercepts = []
        for day in [-2, -1]:
            intercept, coefs = fit_regression(day, lag)
            coefs_list.append(coefs); intercepts.append(intercept)
        avg_int = sum(intercepts) / 2
        avg_coefs = [sum(coefs_list[d][i] for d in range(2)) / 2 for i in range(lag)]
        reg_cache[lag] = (avg_int, avg_coefs)
        print(f"  lag={lag}: intercept={avg_int:.2f}, coefs_sum={sum(avg_coefs):.4f}")

    # Build all strategy codes
    codes = {}
    for combo in all_combos:
        params = dict(zip(keys, combo))
        codes[combo] = build_strategy(params, reg_cache)

    total_combos = len(all_combos)
    total_runs = total_combos * NUM_SEEDS
    est_hours = total_runs * 0.6 / 3600 / NUM_WORKERS

    print(f"\nSIM CARTESIAN SWEEP")
    print(f"Parameters: {len(keys)}")
    for k in keys:
        print(f"  {k}: {PARAMS[k]} ({len(PARAMS[k])} values)")
    print(f"Total combos: {total_combos:,}")
    print(f"Seeds per combo: {NUM_SEEDS} ({SEEDS})")
    print(f"Total runs: {total_runs:,}")
    print(f"Workers: {NUM_WORKERS}")
    print(f"Estimated time: {est_hours:.1f} hours")
    print()

    # Build work items: (combo_idx, params, code, seed)
    work = []
    for i, combo in enumerate(all_combos):
        for seed in SEEDS:
            work.append((i, dict(zip(keys, combo)), codes[combo], seed))

    # Run in parallel
    raw_results = {}  # combo_idx -> list of scores
    start = time.time()
    completed = 0

    with ProcessPoolExecutor(max_workers=NUM_WORKERS) as pool:
        futures = {pool.submit(run_single, w): w for w in work}
        for future in as_completed(futures):
            combo_idx, seed, score = future.result()
            raw_results.setdefault(combo_idx, []).append(score)
            completed += 1

            if completed % (NUM_SEEDS * 100) == 0 or completed == total_runs:
                elapsed = time.time() - start
                rate = completed / elapsed
                remaining = (total_runs - completed) / rate if rate > 0 else 0
                combos_done = completed // NUM_SEEDS
                print(f"  [{combos_done:,}/{total_combos:,} combos] "
                      f"({elapsed/60:.1f}m elapsed, {remaining/60:.1f}m remaining)")

    # Aggregate results
    results = []
    for i, combo in enumerate(all_combos):
        params = dict(zip(keys, combo))
        scores = raw_results.get(i, [0])
        avg = statistics.mean(scores)
        std = statistics.stdev(scores) if len(scores) > 1 else 0
        results.append({
            'params': params,
            'avg': round(avg),
            'std': round(std),
            'scores': scores,
        })

    results.sort(key=lambda x: -x['avg'])

    elapsed = time.time() - start
    print(f"\n{'='*80}")
    print(f"  COMPLETE — {total_combos:,} combos × {NUM_SEEDS} seeds = {total_runs:,} runs in {elapsed/60:.1f} min")
    print(f"{'='*80}")

    print(f"\n  TOP 30:")
    for i, r in enumerate(results[:30]):
        p = r['params']
        print(f"  {i+1:3d}. avg={r['avg']:>6,} std={r['std']:>4,}  "
              f"lag={p['REG_LAGS']} int={p['INTERCEPT']} flow={p['FLOW_COEF']} "
              f"aggr={p['TOM_AGGR_TICK']}/{p['TOM_POS_THRESH']} "
              f"dir={p['DIR_TRIGGER']}/{p['DIR_WIDTH']}/{p['DIR_DECAY']} "
              f"em={p['EM_AGGRESSION']} post={p['POST_OFFSET']}")

    print(f"\n  LANDSCAPE (top 50 param frequency):")
    for key in keys:
        vals = [r['params'][key] for r in results[:50]]
        c = Counter(vals)
        print(f"    {key}: {dict(c.most_common())}")

    out = os.path.join(BASE_DIR, 'sim_cartesian_results.json')
    with open(out, 'w') as f:
        json.dump(results[:500], f, indent=2)
    print(f"\n  Saved top 500 to {out}")


if __name__ == '__main__':
    main()
