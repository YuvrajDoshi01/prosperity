"""
FULL CARTESIAN: Every combination of every tunable parameter.
This is the brute-force "try everything" approach.

Run: python -u trader-logic/round-0/sweeps/full_cartesian.py
"""

import subprocess, re, json, os, sys, time, itertools, csv, math
from collections import Counter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(BASE_DIR)))
ROUND_DIR = os.path.dirname(BASE_DIR)  # trader-logic/round-0/ where datamodel.py lives
TMP = os.path.join(ROUND_DIR, '_cart_tmp.py')

# ============================================================
# FULL PARAMETER GRID — everything × everything
# ============================================================
PARAMS = {
    # Most impactful from mega_sweep (only params that moved the needle)
    'INTERCEPT': [5.0, 7.39],          # S1: 5.0 was #1 winner
    'REG_LAGS': [4, 5, 6],             # S0: untested, include 4 (current) + neighbors
    'FLOW_COEF': [1.0, 1.5, 2.0],     # S2: 2.0 won, 1.0-1.5 close
    'FLOW_WINDOW': [3, 5],             # S2: 3 and 5 both in top
    'TOM_AGGR_TICK': [0, 1],           # S3: 0 was universal winner
    'DIR_TRIGGER': [2, 3, 4],          # S4: 2 won, 3-4 close
    'DIR_WIDTH': [3, 4, 5],            # S4: 5 dominated, include 3-4
    'DIR_DECAY': [0.5, 0.7],           # S4: both in top
    'EM_AGGRESSION': [0, 1],           # S5: 0 was #1 winner
    'EM_LIQ_SOFT': [3, 5],            # S5: 3 won
    'POST_OFFSET': [1, 2],            # S6: 2 slightly better
}
# = 2 × 3 × 3 × 2 × 2 × 3 × 3 × 2 × 2 × 2 × 2 = 10,368 combos
# ~10,368 × 3s = 8.6 hours — still long. Fix some more:
# Fix FLOW_WINDOW=5 (no effect), EM_LIQ_SOFT=3 (clear winner), DIR_DECAY=0.7 (landscape stable)
PARAMS = {
    'INTERCEPT': [5.0, 7.39],          # 2
    'REG_LAGS': [4, 5, 6],             # 3
    'FLOW_COEF': [1.0, 1.5, 2.0],     # 3
    'TOM_AGGR_TICK': [0, 1],           # 2
    'DIR_TRIGGER': [2, 3, 4],          # 3
    'DIR_WIDTH': [3, 4, 5],            # 3
    'EM_AGGRESSION': [0, 1],           # 2
    'POST_OFFSET': [1, 2],            # 2
}
# Fixed: FLOW_WINDOW=5, FLOW_NORM=15, DIR_DECAY=0.7, EM_LIQ_SOFT=3,
#        TOM_POS_THRESH=40, TOM_LIQ_WINDOW=10
# = 2×3×3×2×3×3×2×2 = 1,296 combos × 3s = ~65 minutes

DATA_DIR = os.path.join(ROOT_DIR, 'prosperity4bt', 'resources', 'round0')


def fit_regression(day, dim):
    """Fit microprice regression for given lag dimension."""
    mps, mids = [], []
    fname = os.path.join(DATA_DIR, f'prices_round_0_day_{day}.csv')
    with open(fname) as f:
        for r in csv.DictReader(f, delimiter=';'):
            if r['product'] == 'TOMATOES':
                bb = float(r['bid_price_1']); ba = float(r['ask_price_1'])
                bv = int(r['bid_volume_1']); av = int(r['ask_volume_1'])
                if r.get('bid_volume_2') and r['bid_volume_2']: bv += int(r['bid_volume_2'])
                if r.get('ask_volume_2') and r['ask_volume_2']: av += int(r['ask_volume_2'])
                mp = bb + (bv/(bv+av))*(ba-bb) if (bv+av) > 0 else (bb+ba)/2
                mps.append(mp); mids.append(float(r['mid_price']))

    n = len(mps); X = []; Y = []
    for i in range(dim, n):
        X.append(mps[i-dim:i]); Y.append(mids[i])
    k = dim
    XtX = [[0]*(k+1) for _ in range(k+1)]; XtY = [0]*(k+1)
    for i in range(len(X)):
        row = [1.0] + X[i]
        for j in range(k+1):
            XtY[j] += row[j]*Y[i]
            for l in range(k+1): XtX[j][l] += row[j]*row[l]
    for j in range(k+1): XtX[j][j] += 1e-6*len(X)
    aug = [XtX[j][:]+[XtY[j]] for j in range(k+1)]
    m = k+1
    for col in range(m):
        mr = max(range(col, m), key=lambda r: abs(aug[r][col]))
        aug[col], aug[mr] = aug[mr], aug[col]
        for row in range(m):
            if row == col: continue
            fc = aug[row][col] / aug[col][col]
            for j in range(m+1): aug[row][j] -= fc * aug[col][j]
    beta = [aug[j][m]/aug[j][j] for j in range(m)]
    return beta[0], beta[1:]


# Pre-compute regression coefficients for each lag size
print("Pre-fitting regressions for each lag size...")
REG_CACHE = {}
for lag in PARAMS['REG_LAGS']:
    coefs_list = []; intercepts = []
    for day in [-2, -1]:
        intercept, coefs = fit_regression(day, lag)
        coefs_list.append(coefs); intercepts.append(intercept)
    avg_int = sum(intercepts) / 2
    avg_coefs = [sum(coefs_list[d][i] for d in range(2)) / 2 for i in range(lag)]
    REG_CACHE[lag] = (avg_int, avg_coefs)
    print(f"  lag={lag}: intercept={avg_int:.2f}, coefs_sum={sum(avg_coefs):.4f}")


def build_strategy(params):
    """Generate strategy code for given parameter combination."""
    lag = params['REG_LAGS']
    reg_int, reg_coefs = REG_CACHE[lag]

    # Override intercept if specified (the grid intercept is an OFFSET, not replacement)
    # Actually: use the grid intercept directly
    intercept = params['INTERCEPT']

    coef_expr = "+".join(f"{reg_coefs[i]}*c[{i}]" for i in range(lag))
    reg_line = f"fv={intercept}+{coef_expr}"

    code = f'''import json, random
random.seed(42)  # deterministic sim mode
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
                eo=[];pos=state.position.get("EMERALDS",0);tb,ts=80-pos,80+pos
                buys=sorted(od.buy_orders.items(),reverse=True);sells=sorted(od.sell_orders.items())
                self.ew.append(abs(pos)==80)
                if len(self.ew)>10: self.ew=self.ew[-10:]
                soft=len(self.ew)==10 and sum(self.ew)>=3 and self.ew[-1]
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
                    elif abs(bc)<=1: self.sig*=0.7
                self.pb=bb
                self.tw.append(abs(pos)==80)
                if len(self.tw)>10: self.tw=self.tw[-10:]
                tsoft=len(self.tw)==10 and sum(self.tw)>=5 and self.tw[-1]
                thard=len(self.tw)==10 and all(self.tw)
                tb=80-pos;ts=80+pos
                mbp=tv-{params['TOM_AGGR_TICK']} if pos>40 else tv
                msp=tv+{params['TOM_AGGR_TICK']} if pos<-40 else tv
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


MATCH_MODE = os.environ.get('SWEEP_MATCH_MODE', 'default')  # set SWEEP_MATCH_MODE=sim to use sim mode

def run_backtest(day, verbose=False):
    cmd = f'python -m prosperity4bt "{TMP}" 0-{day} --no-out --no-progress --ticks 2000 --iterations 1000 --match-mode {MATCH_MODE}'
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True, cwd=ROOT_DIR)
    m = re.search(r'Total profit: ([\d,]+)', r.stdout)
    if m:
        return int(m.group(1).replace(',', ''))
    if verbose or r.returncode != 0:
        print(f"  BACKTEST FAILED (day {day}, exit={r.returncode})")
        if r.stderr:
            print(f"  stderr: {r.stderr[:300]}")
        if r.stdout:
            print(f"  stdout: {r.stdout[:300]}")
    return 0


def main():
    keys = sorted(PARAMS.keys())
    values = [PARAMS[k] for k in keys]
    all_combos = list(itertools.product(*values))

    print(f"FULL CARTESIAN SWEEP")
    print(f"Parameters: {len(keys)}")
    for k in keys:
        print(f"  {k}: {PARAMS[k]} ({len(PARAMS[k])} values)")
    print(f"Total combinations: {len(all_combos):,}")
    print(f"Estimated time: {len(all_combos) * 3 / 60:.0f} min = {len(all_combos) * 3 / 3600:.1f} hours")
    print()

    results = []
    best_avg = 0
    best_params = None
    start = time.time()

    for i, combo in enumerate(all_combos):
        params = dict(zip(keys, combo))

        code = build_strategy(params)
        with open(TMP, 'w') as f:
            f.write(code)

        verbose = (i == 0)  # show errors on first combo to catch issues early
        d2 = run_backtest(-2, verbose=verbose)
        d1 = run_backtest(-1, verbose=verbose)
        avg = (d2 + d1) / 2
        spread = abs(d2 - d1)

        results.append({
            'params': params,
            'd2': d2, 'd1': d1, 'avg': avg, 'spread': spread,
        })

        if avg > best_avg:
            best_avg = avg
            best_params = params
            print(f"  *** NEW BEST at [{i+1}/{len(all_combos)}]: avg={avg:,.0f} d-2={d2:,} d-1={d1:,} spread={spread:,}")
            print(f"      {params}")

        elif (i + 1) % 100 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            remaining = (len(all_combos) - i - 1) / rate
            print(f"  [{i+1}/{len(all_combos)}] ({elapsed/60:.1f}m elapsed, {remaining/60:.1f}m remaining) "
                  f"Best: avg={best_avg:,.0f}")

    elapsed = time.time() - start

    # Sort results
    results.sort(key=lambda x: (-x['avg'], x['spread']))

    print(f"\n{'='*80}")
    print(f"  COMPLETE — {len(all_combos):,} combinations in {elapsed/60:.1f} minutes")
    print(f"{'='*80}")

    print(f"\n  TOP 20:")
    for i, r in enumerate(results[:20]):
        print(f"    {i+1:3d}. avg={r['avg']:,.0f} d-2={r['d2']:,} d-1={r['d1']:,} spread={r['spread']:,}")
        p = r['params']
        print(f"         lag={p['REG_LAGS']} int={p['INTERCEPT']} flow={p['FLOW_COEF']} "
              f"aggr={p['TOM_AGGR_TICK']} dir={p['DIR_TRIGGER']}/{p['DIR_WIDTH']} "
              f"em={p['EM_AGGRESSION']} post={p['POST_OFFSET']}")

    print(f"\n  LANDSCAPE (top 50 parameter frequency):")
    for key in keys:
        vals = [r['params'][key] for r in results[:50]]
        c = Counter(vals)
        print(f"    {key}: {dict(c.most_common())}")

    out = os.path.join(BASE_DIR, 'full_cartesian_results.json')
    with open(out, 'w') as f:
        json.dump(results[:200], f, indent=2)
    print(f"\n  Saved top 200 to {out}")

    if os.path.exists(TMP):
        os.remove(TMP)


if __name__ == '__main__':
    main()
