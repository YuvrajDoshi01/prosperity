"""
Full Cartesian overfit on TOMATOES for day 0 (website data).
Uses multiprocessing for speed.
"""
import sys, os, itertools, time
from multiprocessing import Pool, cpu_count

bt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'prosperity4bt')
sys.path.insert(0, bt_path)
sys.path.insert(0, os.path.join(bt_path, '..'))

from prosperity4bt.models.test_options import TradeMatchingMode, MatchMode
import json
from prosperity4bt.datamodel import Order, TradingState


def make_trader(p):
    intercept = p['intercept']
    coefs = p.get('coefs', [0.059694, 0.117270, 0.244154, 0.578440])
    tf_coef = p['tf_coef']
    tf_window = p['tf_window']
    tf_norm = p['tf_norm']
    sig_decay = p['sig_decay']
    wide_off = p['wide_off']
    pos_thresh = p['pos_thresh']
    post_offset = p['post_offset']
    move_trig = p.get('move_trig', 4)
    sig_thresh = p.get('sig_thresh', 0.5)

    class Trader:
        def __init__(self):
            self.mc=[]; self.tf=[]; self.ew=[]; self.prev_bid=None; self.signal=0
        def bid(self): return 15
        def run(self, state: TradingState):
            td = json.loads(state.traderData) if state.traderData else None
            if td:
                self.mc=td.get("c",[]); self.tf=td.get("f",[]); self.ew=td.get("w",[])
                self.prev_bid=td.get("pb"); self.signal=td.get("sg",0)
            orders = {}
            # EMERALDS fixed
            if "EMERALDS" in state.order_depths:
                od = state.order_depths["EMERALDS"]
                if od.buy_orders and od.sell_orders:
                    eo=[]; pos=state.position.get("EMERALDS",0)
                    tb,ts_=80-pos,80+pos
                    buys=sorted(od.buy_orders.items(),reverse=True)
                    sells=sorted(od.sell_orders.items())
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
                        if ts_>0 and p>=10000: q=min(ts_,v); eo.append(Order("EMERALDS",p,-q)); ts_-=q
                    if ts_>0 and hard: q=ts_//2; eo.append(Order("EMERALDS",10000,-q)); ts_-=q
                    if ts_>0 and soft: q=ts_//2; eo.append(Order("EMERALDS",10002,-q)); ts_-=q
                    if ts_>0: eo.append(Order("EMERALDS",max(10001,sells[0][0]-1),-ts_))
                    orders["EMERALDS"]=eo
            # TOMATOES parametrized
            if "TOMATOES" in state.order_depths:
                od = state.order_depths["TOMATOES"]
                if od.buy_orders and od.sell_orders:
                    to=[]; bb=max(od.buy_orders); ba=min(od.sell_orders)
                    pos=state.position.get("TOMATOES",0); mid=(bb+ba)*0.5
                    bv=sum(od.buy_orders.values()); av=sum(-v for v in od.sell_orders.values())
                    mp=bb+(bv/(bv+av))*(ba-bb) if (bv+av)>0 else mid
                    c=self.mc
                    if len(c)>=4: c=c[1:]
                    c.append(mp); self.mc=c
                    if len(c)==4:
                        fv=intercept+coefs[0]*c[0]+coefs[1]*c[1]+coefs[2]*c[2]+coefs[3]*c[3]
                    else: fv=mp
                    trades=state.market_trades.get("TOMATOES")
                    if trades:
                        sv=sum(t.quantity if t.price>=mid else -t.quantity for t in trades)
                        self.tf.append(sv)
                    else: self.tf.append(0.0)
                    if len(self.tf)>tf_window: self.tf=self.tf[-tf_window:]
                    fs=max(-1.0,min(1.0,sum(self.tf)/tf_norm))
                    fv-=fs*tf_coef
                    tv=round(fv)
                    if self.prev_bid is not None:
                        bc=bb-self.prev_bid
                        if bc>=move_trig: self.signal=-1
                        elif bc<=-move_trig: self.signal=1
                        elif abs(bc)<=1: self.signal*=sig_decay
                    self.prev_bid=bb
                    tb=80-pos; ts_=80+pos
                    for p,v in sorted(od.sell_orders.items()):
                        if tb>0 and p<=tv: q=min(tb,-v); to.append(Order("TOMATOES",p,q)); tb-=q
                    for p,v in sorted(od.buy_orders.items(),reverse=True):
                        if ts_>0 and p>=tv: q=min(ts_,v); to.append(Order("TOMATOES",p,-q)); ts_-=q
                    if self.signal>sig_thresh:
                        if tb>0:
                            bp=min(tv-post_offset,bb+1); bp=min(bp,ba-1)
                            to.append(Order("TOMATOES",bp,tb))
                        if ts_>0 and pos>=pos_thresh:
                            ap=max(tv+1,ba-1); ap=max(ap,bb+1)
                            to.append(Order("TOMATOES",ap,-ts_))
                        elif ts_>0:
                            ap=max(tv+wide_off,ba-1); ap=max(ap,bb+1)
                            to.append(Order("TOMATOES",ap,-ts_))
                    elif self.signal<-sig_thresh:
                        if ts_>0:
                            ap=max(tv+post_offset,ba-1); ap=max(ap,bb+1)
                            to.append(Order("TOMATOES",ap,-ts_))
                        if tb>0 and pos<=-pos_thresh:
                            bp=min(tv-1,bb+1); bp=min(bp,ba-1)
                            to.append(Order("TOMATOES",bp,tb))
                        elif tb>0:
                            bp=min(tv-wide_off,bb+1); bp=min(bp,ba-1)
                            to.append(Order("TOMATOES",bp,tb))
                    else:
                        if tb>0:
                            bp=min(tv-post_offset,bb+1); bp=min(bp,ba-1)
                            to.append(Order("TOMATOES",bp,tb))
                        if ts_>0:
                            ap=max(tv+post_offset,ba-1); ap=max(ap,bb+1)
                            to.append(Order("TOMATOES",ap,-ts_))
                    orders["TOMATOES"]=to
            return orders, 0, json.dumps(
                {"c":self.mc,"f":self.tf,"w":self.ew,"pb":self.prev_bid,"sg":round(self.signal,3)},
                separators=(",",":"))
    return Trader


def run_one(params):
    from prosperity4bt.test_runner import TestRunner
    from prosperity4bt.tools.data_reader import PackageResourcesReader
    try:
        TraderClass = make_trader(params)
        runner = TestRunner(
            trader=TraderClass(), data_reader=PackageResourcesReader(),
            round=0, day=0, show_progress_bar=False, print_output=False,
            trade_matching_mode=TradeMatchingMode.all, max_ticks=2000,
            iterations=1000, match_mode=MatchMode.default,
        )
        result = runner.run()
        pnl = {a.symbol: a.profit_loss for a in result.final_activities()}
        return params, pnl.get('TOMATOES', 0), pnl.get('EMERALDS', 0)
    except Exception as e:
        return params, -99999, 0


def main():
    # Cartesian grid — focused on params that moved the needle
    grid = {
        'intercept':   [2.0, 2.5, 2.75, 3.0, 3.25, 3.5, 4.0],
        'tf_coef':     [0, 1.0, 1.5, 2.0, 2.5, 3.0],
        'tf_window':   [5, 10, 15],
        'tf_norm':     [10, 15, 20],
        'post_offset': [1, 2, 3],
        'pos_thresh':  [40, 50, 60, 80],
        'wide_off':    [3, 4, 5],
        'sig_decay':   [0.7, 0.9, 0.95, 1.0],
    }

    # Fixed params
    fixed = {
        'coefs': [0.059694, 0.117270, 0.244154, 0.578440],
        'move_trig': 4,
        'sig_thresh': 0.5,
    }

    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    combos = list(itertools.product(*values))
    total = len(combos)

    print(f"Cartesian grid: {' x '.join(f'{k}({len(v)})' for k,v in grid.items())}")
    print(f"Total combinations: {total}")
    print(f"CPUs: {cpu_count()}")
    print()

    # Build param dicts
    all_params = []
    for combo in combos:
        p = dict(fixed)
        p['coefs'] = list(fixed['coefs'])
        for k, v in zip(keys, combo):
            p[k] = v
        all_params.append(p)

    # Run with multiprocessing
    start = time.time()
    workers = max(1, cpu_count() - 1)
    print(f"Running {total} backtests on {workers} workers...")

    results = []
    with Pool(workers) as pool:
        for i, result in enumerate(pool.imap_unordered(run_one, all_params, chunksize=8)):
            results.append(result)
            if (i + 1) % 500 == 0:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed
                eta = (total - i - 1) / rate
                best_so_far = max(results, key=lambda x: x[1])
                print(f"  [{i+1}/{total}] {rate:.1f}/s, ETA {eta:.0f}s | best TOM={best_so_far[1]:.0f}")

    elapsed = time.time() - start
    print(f"\nCompleted {total} backtests in {elapsed:.1f}s ({total/elapsed:.1f}/s)")

    # Sort by TOMATOES PnL
    results.sort(key=lambda x: x[1], reverse=True)

    # Top 20
    print(f"\n{'Rank':<5} {'TOM':<8} {'Total':<8} | {'intercept':<10} {'tf_coef':<8} {'tf_win':<7} {'tf_norm':<8} {'post_off':<9} {'pos_thr':<8} {'wide':<6} {'decay':<6}")
    print("=" * 105)
    for i, (p, tom, em) in enumerate(results[:20]):
        print(f"{i+1:<5} {tom:<8.0f} {tom+em:<8.0f} | {p['intercept']:<10} {p['tf_coef']:<8} {p['tf_window']:<7} {p['tf_norm']:<8} {p['post_offset']:<9} {p['pos_thresh']:<8} {p['wide_off']:<6} {p['sig_decay']:<6}")

    # Bottom 5
    print(f"\nBottom 5:")
    for i, (p, tom, em) in enumerate(results[-5:]):
        print(f"  {tom:<8.0f} {tom+em:<8.0f} | int={p['intercept']} tf={p['tf_coef']} po={p['post_offset']}")

    # Best params
    best_p, best_tom, best_em = results[0]
    print(f"\n{'='*60}")
    print(f"BEST: TOM={best_tom:.0f} EM={best_em:.0f} TOTAL={best_tom+best_em:.0f}")
    print(f"Params: {best_p}")
    print(f"Website actual: 2,857")

    # Save results
    import json as jj
    with open('trader-logic/round-0/cartesian_day0_results.json', 'w') as f:
        jj.dump({
            'top20': [{'params': p, 'tomatoes': t, 'emeralds': e} for p, t, e in results[:20]],
            'total_combos': total,
            'elapsed_s': elapsed,
        }, f, indent=2)
    print(f"\nSaved top 20 to cartesian_day0_results.json")


if __name__ == '__main__':
    main()
