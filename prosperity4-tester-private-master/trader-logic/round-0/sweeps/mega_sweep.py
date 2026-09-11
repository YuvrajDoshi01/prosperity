"""
MEGA SWEEP: Exhaustive parameter optimization across 6 independent dimensions.
Each sweep holds other params at proven defaults and varies one dimension.

Sweeps:
  S1: Regression (intercept, lag-4 coefficient)         — 16 combos
  S2: Trade Flow (coefficient, window, normalization)    — 72 combos
  S3: Position Management (threshold, aggression, liq)   — 72 combos
  S4: Directional Posting (trigger, width, decay)        — 100 combos
  S5: EMERALDS (pos threshold, aggression, liquidation)  — 144 combos
  S6: Posting & EMA (offset, EMA smoothing)              — 72 combos
  Total: ~476 combos × 2 days × ~1.5s = ~24 minutes

Run: python -u trader-logic/round-0/sweeps/mega_sweep.py
"""

import subprocess, re, json, os, sys, time, itertools, math
from collections import Counter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(BASE_DIR)))
TMP = os.path.join(BASE_DIR, '_sweep_tmp.py')

DEFAULTS = {
    'INTERCEPT': 7.388073, 'C0': 0.059509, 'C1': 0.117116, 'C2': 0.243910, 'C3': 0.577988,
    'FLOW_COEF': 1.5, 'FLOW_WINDOW': 5, 'FLOW_NORM': 15.0,
    'USE_EMA': 0, 'EMA_ALPHA': 0.4, 'EMA_BLEND': 0.7,
    'DIR_TRIGGER': 4, 'DIR_WIDTH': 3, 'DIR_DECAY': 0.7,
    'TOM_POS_THRESH': 40, 'TOM_AGGR_TICK': 1, 'TOM_LIQ_WINDOW': 10, 'TOM_LIQ_SOFT': 5,
    'EM_POS_THRESH': 40, 'EM_AGGRESSION': 1, 'EM_LIQ_WINDOW': 10, 'EM_LIQ_SOFT': 5,
    'POST_OFFSET': 1,
}

SWEEPS = {
    'S0_lag_size': {
        'REG_LAGS': [2, 3, 4, 5, 6, 8],
    },
    'S1_regression': {
        'INTERCEPT': [0.0, 2.21, 5.0, 7.39],
        'C3': [0.55, 0.578, 0.60, 0.62],
    },
    'S2_trade_flow': {
        'FLOW_COEF': [0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
        'FLOW_WINDOW': [3, 5, 7, 10],
        'FLOW_NORM': [10, 15, 20],
    },
    'S3_position_mgmt': {
        'TOM_POS_THRESH': [20, 30, 40, 50, 60, 70],
        'TOM_AGGR_TICK': [0, 1, 2],
        'TOM_LIQ_WINDOW': [5, 10, 15, 20],
    },
    'S4_directional': {
        'DIR_TRIGGER': [2, 3, 4, 5, 6],
        'DIR_WIDTH': [1, 2, 3, 4, 5],
        'DIR_DECAY': [0.3, 0.5, 0.7, 0.9],
    },
    'S5_emeralds': {
        'EM_POS_THRESH': [20, 40, 60, 80],
        'EM_AGGRESSION': [0, 1, 2],
        'EM_LIQ_WINDOW': [5, 10, 15],
        'EM_LIQ_SOFT': [3, 5, 7],
    },
    'S6_posting': {
        'POST_OFFSET': [0, 1, 2, 3],
        'USE_EMA': [0, 1],
        'EMA_ALPHA': [0.3, 0.5, 0.7],
        'EMA_BLEND': [0.5, 0.7, 0.9],
    },
}

STRATEGY_TEMPLATE = r'''import json
from datamodel import Order, TradingState

class Trader:
    def __init__(self):
        self.tc=[]; self.tf=[]; self.ew=[]; self.tw=[]; self.pb=None; self.sig=0; self.ema=None
    def bid(self): return 15
    def run(self, state):
        td=json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc=td.get("c",[]);self.tf=td.get("f",[]);self.ew=td.get("w",[])
            self.tw=td.get("tw",[]);self.pb=td.get("pb");self.sig=td.get("sg",0)
            self.ema=td.get("em")
        orders={}
        if "EMERALDS" in state.order_depths:
            od=state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo=[];pos=state.position.get("EMERALDS",0);tb,ts=80-pos,80+pos
                buys=sorted(od.buy_orders.items(),reverse=True);sells=sorted(od.sell_orders.items())
                self.ew.append(abs(pos)==80)
                if len(self.ew)>$$EM_LIQ_WINDOW$$: self.ew=self.ew[-$$EM_LIQ_WINDOW$$:]
                soft=len(self.ew)==$$EM_LIQ_WINDOW$$ and sum(self.ew)>=$$EM_LIQ_SOFT$$ and self.ew[-1]
                hard=len(self.ew)==$$EM_LIQ_WINDOW$$ and all(self.ew)
                embp=10000-$$EM_AGGRESSION$$ if pos>$$EM_POS_THRESH$$ else 10000
                emsp=10000+$$EM_AGGRESSION$$ if pos<-$$EM_POS_THRESH$$ else 10000
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
                to=[];bb,ba=max(od.buy_orders),min(od.sell_orders)
                pos=state.position.get("TOMATOES",0);mid=(bb+ba)*0.5
                bv=sum(od.buy_orders.values());av=sum(-v for v in od.sell_orders.values())
                mp=bb+(bv/(bv+av))*(ba-bb) if (bv+av)>0 else mid
                c=self.tc
                if len(c)>=4: c=c[1:]
                c.append(mp);self.tc=c
                if len(c)==4:
                    fv=$$INTERCEPT$$+$$C0$$*c[0]+$$C1$$*c[1]+$$C2$$*c[2]+$$C3$$*c[3]
                else: fv=mp
                trades=state.market_trades.get("TOMATOES")
                if trades:
                    sv=sum(t.quantity if t.price>=mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else: self.tf.append(0.0)
                if len(self.tf)>$$FLOW_WINDOW$$: self.tf=self.tf[-$$FLOW_WINDOW$$:]
                fs=max(-1.0,min(1.0,sum(self.tf)/$$FLOW_NORM$$))
                fv-=fs*$$FLOW_COEF$$
                if $$USE_EMA$$:
                    if self.ema is None: self.ema=fv
                    else: self.ema=$$EMA_ALPHA$$*fv+(1-$$EMA_ALPHA$$)*self.ema
                    fv=$$EMA_BLEND$$*fv+(1-$$EMA_BLEND$$)*self.ema
                tv=round(fv)
                if self.pb is not None:
                    bc=bb-self.pb
                    if bc>=$$DIR_TRIGGER$$: self.sig=-1
                    elif bc<=-$$DIR_TRIGGER$$: self.sig=1
                    elif abs(bc)<=1: self.sig*=$$DIR_DECAY$$
                self.pb=bb
                self.tw.append(abs(pos)==80)
                if len(self.tw)>$$TOM_LIQ_WINDOW$$: self.tw=self.tw[-$$TOM_LIQ_WINDOW$$:]
                tsoft=len(self.tw)==$$TOM_LIQ_WINDOW$$ and sum(self.tw)>=$$TOM_LIQ_SOFT$$ and self.tw[-1]
                thard=len(self.tw)==$$TOM_LIQ_WINDOW$$ and all(self.tw)
                tb=80-pos;ts=80+pos
                mbp=tv-$$TOM_AGGR_TICK$$ if pos>$$TOM_POS_THRESH$$ else tv
                msp=tv+$$TOM_AGGR_TICK$$ if pos<-$$TOM_POS_THRESH$$ else tv
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
                    if ts>0: to.append(Order("TOMATOES",max(tv+$$DIR_WIDTH$$,ba-1,bb+1),-ts))
                elif self.sig<-0.5:
                    if ts>0: to.append(Order("TOMATOES",max(tv+1,ba-1),-ts))
                    if tb>0: to.append(Order("TOMATOES",min(tv-$$DIR_WIDTH$$,bb+1,ba-1),tb))
                else:
                    if tb>0: to.append(Order("TOMATOES",min(tv-$$POST_OFFSET$$,bb+1),tb))
                    if ts>0: to.append(Order("TOMATOES",max(tv+$$POST_OFFSET$$,ba-1),-ts))
                orders["TOMATOES"]=to
        return orders,0,json.dumps({"c":self.tc,"f":self.tf,"w":self.ew,"tw":self.tw,"pb":self.pb,"sg":round(self.sig,3),"em":self.ema},separators=(",",":"))
'''


def write_strategy(params):
    code = STRATEGY_TEMPLATE
    for k, v in params.items():
        code = code.replace('$$' + k + '$$', str(v))
    with open(TMP, 'w') as f:
        f.write(code)


def run_backtest(day):
    cmd = f'python -m prosperity4bt "{TMP}" 0-{day} --no-out --no-progress --ticks 2000 --iterations 1000'
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True, cwd=ROOT_DIR)
    m = re.search(r'Total profit: ([\d,]+)', r.stdout)
    return int(m.group(1).replace(',', '')) if m else 0


def run_lag_sweep():
    """Special sweep: test different regression lag sizes (2-8)."""
    print(f"\n{'='*70}")
    print(f"  SWEEP S0_lag_size: Testing lag sizes 2-8")
    print(f"{'='*70}")

    # For each lag size, we need to refit the regression from training data
    # Use day -1 data to fit, test on both days
    import csv
    data_dir = os.path.join(ROOT_DIR, 'prosperity4bt', 'resources', 'round0')

    def load_microprices(day):
        mps, mids = [], []
        fname = os.path.join(data_dir, f'prices_round_0_day_{day}.csv')
        with open(fname) as f:
            for r in csv.DictReader(f, delimiter=';'):
                if r['product'] == 'TOMATOES':
                    bb = float(r['bid_price_1']); ba = float(r['ask_price_1'])
                    bv = int(r['bid_volume_1']); av = int(r['ask_volume_1'])
                    if r.get('bid_volume_2') and r['bid_volume_2']: bv += int(r['bid_volume_2'])
                    if r.get('ask_volume_2') and r['ask_volume_2']: av += int(r['ask_volume_2'])
                    mp = bb + (bv/(bv+av))*(ba-bb) if (bv+av) > 0 else (bb+ba)/2
                    mps.append(mp); mids.append(float(r['mid_price']))
        return mps, mids

    def fit_regression(mps, mids, dim):
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
            mr = max(range(col,m), key=lambda r: abs(aug[r][col]))
            aug[col], aug[mr] = aug[mr], aug[col]
            for row in range(m):
                if row==col: continue
                fc = aug[row][col]/aug[col][col]
                for j in range(m+1): aug[row][j] -= fc*aug[col][j]
        beta = [aug[j][m]/aug[j][j] for j in range(m)]
        return beta[0], beta[1:]

    # Fit on averaged day -2 + day -1 data
    results = []
    for lag in [2, 3, 4, 5, 6, 8]:
        # Fit on both days, average coefficients
        coefs_list = []
        intercepts = []
        for day in [-2, -1]:
            mps, mids = load_microprices(day)
            intercept, coefs = fit_regression(mps, mids, lag)
            coefs_list.append(coefs)
            intercepts.append(intercept)

        avg_intercept = sum(intercepts) / 2
        avg_coefs = [sum(coefs_list[d][i] for d in range(2)) / 2 for i in range(lag)]

        # Build a strategy with this lag size
        coef_lines = []
        for i in range(lag):
            coef_lines.append(f"{avg_coefs[i]}*c[{i}]")
        reg_expr = f"{avg_intercept}+" + "+".join(coef_lines)

        lag_strategy = f'''import json
from datamodel import Order, TradingState

class Trader:
    def __init__(self):
        self.tc=[]; self.tf=[]; self.ew=[]; self.tw=[]; self.pb=None; self.sig=0
    def bid(self): return 15
    def run(self, state):
        td=json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc=td.get("c",[]);self.tf=td.get("f",[]);self.ew=td.get("w",[])
            self.tw=td.get("tw",[]);self.pb=td.get("pb");self.sig=td.get("sg",0)
        orders={{}}
        if "EMERALDS" in state.order_depths:
            od=state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo=[];pos=state.position.get("EMERALDS",0);tb,ts=80-pos,80+pos
                buys=sorted(od.buy_orders.items(),reverse=True);sells=sorted(od.sell_orders.items())
                self.ew.append(abs(pos)==80)
                if len(self.ew)>10: self.ew=self.ew[-10:]
                soft=len(self.ew)==10 and sum(self.ew)>=5 and self.ew[-1]
                hard=len(self.ew)==10 and all(self.ew)
                for p,v in sells:
                    if tb>0 and p<=10000: q=min(tb,-v);eo.append(Order("EMERALDS",p,q));tb-=q
                if tb>0 and hard: q=tb//2;eo.append(Order("EMERALDS",10000,q));tb-=q
                if tb>0 and soft: q=tb//2;eo.append(Order("EMERALDS",9998,q));tb-=q
                if tb>0: eo.append(Order("EMERALDS",min(9999,buys[0][0]+1),tb))
                for p,v in buys:
                    if ts>0 and p>=10000: q=min(ts,v);eo.append(Order("EMERALDS",p,-q));ts-=q
                if ts>0 and hard: q=ts//2;eo.append(Order("EMERALDS",10000,-q));ts-=q
                if ts>0 and soft: q=ts//2;eo.append(Order("EMERALDS",10002,-q));ts-=q
                if ts>0: eo.append(Order("EMERALDS",max(10001,sells[0][0]-1),-ts))
                orders["EMERALDS"]=eo
        if "TOMATOES" in state.order_depths:
            od=state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to=[];bb,ba=max(od.buy_orders),min(od.sell_orders)
                pos=state.position.get("TOMATOES",0);mid=(bb+ba)*0.5
                bv=sum(od.buy_orders.values());av=sum(-v for v in od.sell_orders.values())
                mp=bb+(bv/(bv+av))*(ba-bb) if (bv+av)>0 else mid
                c=self.tc
                if len(c)>={lag}: c=c[1:]
                c.append(mp);self.tc=c
                if len(c)=={lag}: fv={reg_expr}
                else: fv=mp
                trades=state.market_trades.get("TOMATOES")
                if trades:
                    sv=sum(t.quantity if t.price>=mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else: self.tf.append(0.0)
                if len(self.tf)>5: self.tf=self.tf[-5:]
                fs=max(-1.0,min(1.0,sum(self.tf)/15.0))
                fv-=fs*1.5
                tv=round(fv)
                if self.pb is not None:
                    bc=bb-self.pb
                    if bc>=4: self.sig=-1
                    elif bc<=-4: self.sig=1
                    elif abs(bc)<=1: self.sig*=0.7
                self.pb=bb
                self.tw.append(abs(pos)==80)
                if len(self.tw)>10: self.tw=self.tw[-10:]
                tb=80-pos;ts=80+pos
                mbp=tv-1 if pos>40 else tv;msp=tv+1 if pos<-40 else tv
                for p,v in sorted(od.sell_orders.items()):
                    if tb>0 and p<=mbp: q=min(tb,-v);to.append(Order("TOMATOES",p,q));tb-=q
                for p,v in sorted(od.buy_orders.items(),reverse=True):
                    if ts>0 and p>=msp: q=min(ts,v);to.append(Order("TOMATOES",p,-q));ts-=q
                if self.sig>0.5:
                    if tb>0: to.append(Order("TOMATOES",min(tv-1,bb+1),tb))
                    if ts>0: to.append(Order("TOMATOES",max(tv+3,ba-1,bb+1),-ts))
                elif self.sig<-0.5:
                    if ts>0: to.append(Order("TOMATOES",max(tv+1,ba-1),-ts))
                    if tb>0: to.append(Order("TOMATOES",min(tv-3,bb+1,ba-1),tb))
                else:
                    if tb>0: to.append(Order("TOMATOES",min(tv-1,bb+1),tb))
                    if ts>0: to.append(Order("TOMATOES",max(tv+1,ba-1),-ts))
                orders["TOMATOES"]=to
        return orders,0,json.dumps({{"c":self.tc,"f":self.tf,"w":self.ew,"tw":self.tw,"pb":self.pb,"sg":round(self.sig,3)}},separators=(",",":"))
'''
        with open(TMP, 'w') as f:
            f.write(lag_strategy)

        d2 = run_backtest(-2)
        d1 = run_backtest(-1)
        avg = (d2 + d1) / 2
        spread = abs(d2 - d1)

        coef_sum = sum(avg_coefs)
        print(f"  lag={lag}: d-2={d2:,} d-1={d1:,} avg={avg:,.0f} spread={spread:,} "
              f"coef_sum={coef_sum:.4f} intercept={avg_intercept:.2f}")

        results.append({
            'combo': {'REG_LAGS': lag},
            'd2': d2, 'd1': d1, 'avg': avg, 'spread': spread,
            'coefs': avg_coefs, 'intercept': avg_intercept, 'coef_sum': coef_sum,
        })

    results.sort(key=lambda x: (-x['avg'], x['spread']))
    print(f"\n  BEST LAG SIZE: {results[0]['combo']['REG_LAGS']} (avg={results[0]['avg']:,.0f})")
    return results


def run_sweep(name, sweep_params):
    keys = sorted(sweep_params.keys())
    values = [sweep_params[k] for k in keys]
    combos = list(itertools.product(*values))

    print(f"\n{'='*70}")
    print(f"  SWEEP {name}: {len(combos)} combinations ({', '.join(keys)})")
    print(f"{'='*70}")

    results = []
    for i, combo in enumerate(combos):
        params = dict(DEFAULTS)
        for k, v in zip(keys, combo):
            params[k] = v

        write_strategy(params)
        d2 = run_backtest(-2)
        d1 = run_backtest(-1)
        avg = (d2 + d1) / 2
        spread = abs(d2 - d1)

        results.append({
            'combo': dict(zip(keys, combo)),
            'd2': d2, 'd1': d1, 'avg': avg, 'spread': spread
        })

        if (i + 1) % 20 == 0:
            best = max(results, key=lambda x: x['avg'])
            print(f"  [{i+1}/{len(combos)}] Best: avg={best['avg']:.0f} {best['combo']}")

    results.sort(key=lambda x: (-x['avg'], x['spread']))

    print(f"\n  TOP 5 for {name}:")
    for i, r in enumerate(results[:5]):
        print(f"    {i+1}. avg={r['avg']:,.0f} d-2={r['d2']:,} d-1={r['d1']:,} spread={r['spread']:,} {r['combo']}")

    print(f"\n  LANDSCAPE (params in top 10):")
    for key in keys:
        vals = [r['combo'][key] for r in results[:10]]
        c = Counter(vals)
        print(f"    {key}: {dict(c.most_common())}")

    return results


def main():
    total_combos = sum(
        len(list(itertools.product(*s.values()))) for s in SWEEPS.values()
    )
    print(f"MEGA PARAMETER SWEEP: {total_combos} combinations across 6 dimensions")
    print(f"Estimated time: {total_combos * 3 / 60:.0f} minutes")

    write_strategy(DEFAULTS)
    base_d2 = run_backtest(-2)
    base_d1 = run_backtest(-1)
    print(f"\nBaseline: d-2={base_d2:,} d-1={base_d1:,} avg={(base_d2+base_d1)/2:,.0f}")

    all_results = {}
    start = time.time()

    # S0: Lag size sweep (special — needs regression refitting)
    if 'S0_lag_size' in SWEEPS:
        all_results['S0_lag_size'] = run_lag_sweep()
        del SWEEPS['S0_lag_size']

    # All other sweeps
    for name, sweep_params in SWEEPS.items():
        all_results[name] = run_sweep(name, sweep_params)

    elapsed = time.time() - start
    print(f"\n{'='*70}")
    print(f"  COMPLETE in {elapsed/60:.1f} minutes")
    print(f"{'='*70}")

    print(f"\n  GLOBAL TOP 10:")
    all_flat = []
    for name, results in all_results.items():
        for r in results:
            r['sweep'] = name
            all_flat.append(r)
    all_flat.sort(key=lambda x: (-x['avg'], x['spread']))
    for i, r in enumerate(all_flat[:10]):
        print(f"    {i+1}. [{r['sweep']}] avg={r['avg']:,.0f} spread={r['spread']:,} {r['combo']}")

    out = os.path.join(BASE_DIR, 'mega_sweep_results.json')
    with open(out, 'w') as f:
        json.dump({name: results[:20] for name, results in all_results.items()}, f, indent=2)
    print(f"\n  Saved to {out}")

    if os.path.exists(TMP):
        os.remove(TMP)


if __name__ == '__main__':
    main()
