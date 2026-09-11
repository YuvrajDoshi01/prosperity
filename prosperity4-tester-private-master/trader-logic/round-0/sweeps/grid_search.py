"""
Grid Search: Sweep all tunable parameters across both training days.
Pick parameters that are best on BOTH days (landscape stability).

Run: python -u trader-logic/round-0/sweeps/grid_search.py
"""

import subprocess
import re
import json
import os
import itertools
import tempfile

BACKTESTER = "python -m prosperity4bt"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(BASE_DIR)))

# Parameter grid
PARAMS = {
    'intercept': [2.21, 7.39],            # 2: regression intercept (cross-val extremes)
    'flow_coef': [0.0, 1.0, 1.5, 2.0],   # 4: trade flow coefficient
    'flow_window': [3, 5],                 # 2: trade flow window
    'pos_threshold': [30, 40, 50],         # 3: position aggression threshold
    'dir_trigger': [3, 4, 5],             # 3: directional posting trigger
    'dir_width': [2, 3, 4],              # 3: directional posting width
    'dir_decay': [0.5, 0.7],             # 2: directional signal decay
}
# 864 combinations, ~43 minutes

TEMPLATE = '''import json
from datamodel import Order, TradingState

class Trader:
    def __init__(self):
        self.tc=[]; self.tf=[]; self.ew=[]; self.pb=None; self.sig=0
    def bid(self): return 15
    def run(self, state):
        td=json.loads(state.traderData) if state.traderData else None
        if td: self.tc=td.get("c",[]); self.tf=td.get("f",[]); self.ew=td.get("w",[]); self.pb=td.get("pb"); self.sig=td.get("sg",0)
        orders={}
        if "EMERALDS" in state.order_depths:
            od=state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo=[]; pos=state.position.get("EMERALDS",0); tb,ts=80-pos,80+pos
                buys=sorted(od.buy_orders.items(),reverse=True); sells=sorted(od.sell_orders.items())
                self.ew.append(abs(pos)==80)
                if len(self.ew)>10: self.ew=self.ew[-10:]
                soft=len(self.ew)==10 and sum(self.ew)>=5 and self.ew[-1]
                hard=len(self.ew)==10 and all(self.ew)
                for p,v in sells:
                    if tb>0 and p<=10000: q=min(tb,-v); eo.append(Order("EMERALDS",p,q)); tb-=q
                if tb>0 and hard: q=tb//2; eo.append(Order("EMERALDS",10000,q)); tb-=q
                if tb>0 and soft: q=tb//2; eo.append(Order("EMERALDS",9998,q)); tb-=q
                if tb>0: eo.append(Order("EMERALDS",min(9999,buys[0][0]+1),tb))
                for p,v in buys:
                    if ts>0 and p>=10000: q=min(ts,v); eo.append(Order("EMERALDS",p,-q)); ts-=q
                if ts>0 and hard: q=ts//2; eo.append(Order("EMERALDS",10000,-q)); ts-=q
                if ts>0 and soft: q=ts//2; eo.append(Order("EMERALDS",10002,-q)); ts-=q
                if ts>0: eo.append(Order("EMERALDS",max(10001,sells[0][0]-1),-ts))
                orders["EMERALDS"]=eo
        if "TOMATOES" in state.order_depths:
            od=state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to=[]; bb,ba=max(od.buy_orders),min(od.sell_orders); pos=state.position.get("TOMATOES",0)
                mid=(bb+ba)*0.5
                bv=sum(od.buy_orders.values()); av=sum(-v for v in od.sell_orders.values())
                mp=bb+(bv/(bv+av))*(ba-bb) if (bv+av)>0 else mid
                c=self.tc
                if len(c)>=4: c=c[1:]
                c.append(mp); self.tc=c
                if len(c)==4: fv={INTERCEPT}+0.059509*c[0]+0.117116*c[1]+0.243910*c[2]+0.577988*c[3]
                else: fv=mp
                trades=state.market_trades.get("TOMATOES")
                if trades:
                    sv=sum(t.quantity if t.price>=mid else -t.quantity for t in trades); self.tf.append(sv)
                else: self.tf.append(0.0)
                if len(self.tf)>{FLOW_WINDOW}: self.tf=self.tf[-{FLOW_WINDOW}:]
                fs=max(-1.0,min(1.0,sum(self.tf)/15.0))
                fv-=fs*{FLOW_COEF}
                tv=round(fv)
                if self.pb is not None:
                    bc=bb-self.pb
                    if bc>={DIR_TRIGGER}: self.sig=-1
                    elif bc<=-{DIR_TRIGGER}: self.sig=1
                    elif abs(bc)<=1: self.sig*={DIR_DECAY}
                self.pb=bb
                tb=80-pos; ts=80+pos
                mbp=tv-1 if pos>{POS_THRESH} else tv; msp=tv+1 if pos<-{POS_THRESH} else tv
                for p,v in sorted(od.sell_orders.items()):
                    if tb>0 and p<=mbp: q=min(tb,-v); to.append(Order("TOMATOES",p,q)); tb-=q
                for p,v in sorted(od.buy_orders.items(),reverse=True):
                    if ts>0 and p>=msp: q=min(ts,v); to.append(Order("TOMATOES",p,-q)); ts-=q
                if self.sig>0.5:
                    if tb>0: to.append(Order("TOMATOES",min(tv-1,bb+1),tb))
                    if ts>0: to.append(Order("TOMATOES",max(tv+{DIR_WIDTH},ba-1,bb+1),-ts))
                elif self.sig<-0.5:
                    if ts>0: to.append(Order("TOMATOES",max(tv+1,ba-1),-ts))
                    if tb>0: to.append(Order("TOMATOES",min(tv-{DIR_WIDTH},bb+1,ba-1),tb))
                else:
                    if tb>0: to.append(Order("TOMATOES",min(tv-1,bb+1),tb))
                    if ts>0: to.append(Order("TOMATOES",max(tv+1,ba-1),-ts))
                orders["TOMATOES"]=to
        return orders,0,json.dumps({{"c":self.tc,"f":self.tf,"w":self.ew,"pb":self.pb,"sg":round(self.sig,3)}},separators=(",",":"))
'''


def run_backtest(strategy_path, day):
    """Run backtester and return total PnL."""
    cmd = f'python -m prosperity4bt "{strategy_path}" 0-{day} --no-out --no-progress --ticks 2000 --iterations 1000'
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True,
                      cwd=ROOT_DIR)
    m = re.search(r'Total profit: ([\d,]+)', r.stdout)
    if m:
        return int(m.group(1).replace(',', ''))
    return 0


def generate_strategy(params):
    """Generate strategy file with given parameters."""
    code = TEMPLATE.replace('{INTERCEPT}', str(params['intercept']))
    code = code.replace('{FLOW_COEF}', str(params['flow_coef']))
    code = code.replace('{FLOW_WINDOW}', str(params['flow_window']))
    code = code.replace('{POS_THRESH}', str(params['pos_threshold']))
    code = code.replace('{DIR_TRIGGER}', str(params['dir_trigger']))
    code = code.replace('{DIR_WIDTH}', str(params['dir_width']))
    code = code.replace('{DIR_DECAY}', str(params['dir_decay']))
    return code


def main():
    # Generate all parameter combinations
    keys = sorted(PARAMS.keys())
    values = [PARAMS[k] for k in keys]
    all_combos = list(itertools.product(*values))

    print(f"Grid search: {len(all_combos)} combinations across {len(keys)} parameters")
    print(f"Parameters: {keys}")
    print(f"Estimated time: {len(all_combos) * 2 * 3 / 60:.0f} minutes")
    print()

    # Use temp file for strategy
    tmp_path = os.path.join(BASE_DIR, '_grid_tmp.py')

    results = []
    best_avg = 0
    best_params = None

    for i, combo in enumerate(all_combos):
        params = dict(zip(keys, combo))

        # Generate and write strategy
        code = generate_strategy(params)
        with open(tmp_path, 'w') as f:
            f.write(code)

        # Run on both days
        pnl_d2 = run_backtest(tmp_path, -2)
        pnl_d1 = run_backtest(tmp_path, -1)

        avg = (pnl_d2 + pnl_d1) / 2
        spread = abs(pnl_d2 - pnl_d1)

        results.append({
            'params': params,
            'day_m2': pnl_d2,
            'day_m1': pnl_d1,
            'avg': avg,
            'spread': spread,
        })

        if avg > best_avg:
            best_avg = avg
            best_params = params

        if (i + 1) % 10 == 0 or i == 0:
            print(f"[{i+1}/{len(all_combos)}] Current: avg={avg:.0f} spread={spread:.0f} | "
                  f"Best: avg={best_avg:.0f} params={best_params}")

    # Clean up
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    # Sort by average, then by lowest spread
    results.sort(key=lambda x: (-x['avg'], x['spread']))

    print(f"\n{'='*80}")
    print(f"TOP 20 RESULTS (sorted by avg PnL, then consistency)")
    print(f"{'='*80}")
    for i, r in enumerate(results[:20]):
        p = r['params']
        print(f"{i+1:3d}. avg={r['avg']:,.0f} d-2={r['day_m2']:,} d-1={r['day_m1']:,} spread={r['spread']:,}")
        print(f"     int={p['intercept']} flow={p['flow_coef']}/{p['flow_window']} "
              f"pos={p['pos_threshold']} dir={p['dir_trigger']}/±{p['dir_width']}/decay={p['dir_decay']}")

    print(f"\n{'='*80}")
    print(f"LANDSCAPE ANALYSIS: Parameters that appear in top 20")
    print(f"{'='*80}")
    for key in keys:
        vals = [r['params'][key] for r in results[:20]]
        from collections import Counter
        c = Counter(vals)
        print(f"  {key}: {dict(c.most_common())}")

    # Save full results
    out_path = os.path.join(BASE_DIR, 'grid_results.json')
    with open(out_path, 'w') as f:
        json.dump(results[:100], f, indent=2)
    print(f"\nFull results saved to {out_path}")


if __name__ == '__main__':
    main()
