"""
TOMATOES-only overfit on day 0 (website data).
Fine grid on intercept + coefficient sweeps + combo search.
"""
import sys, os
bt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'prosperity4bt')
sys.path.insert(0, bt_path)
sys.path.insert(0, os.path.join(bt_path, '..'))

from prosperity4bt.models.test_options import TradeMatchingMode, MatchMode
import json
from prosperity4bt.datamodel import Order, TradingState


def make_trader(p):
    intercept = p.get('intercept', 2.208667)
    coefs = p.get('coefs', [0.059694, 0.117270, 0.244154, 0.578440])
    tf_coef = p.get('tf_coef', 1.5)
    tf_window = p.get('tf_window', 5)
    tf_norm = p.get('tf_norm', 15.0)
    sig_thresh = p.get('sig_thresh', 0.5)
    sig_decay = p.get('sig_decay', 0.7)
    move_trig = p.get('move_trig', 4)
    wide_off = p.get('wide_off', 3)
    pos_thresh = p.get('pos_thresh', 40)
    take_offset = p.get('take_offset', 0)  # extra aggression on takes
    post_offset = p.get('post_offset', 1)  # distance from tv for posting

    class Trader:
        def __init__(self):
            self.mc = []; self.tf = []; self.ew = []; self.prev_bid = None; self.signal = 0
        def bid(self): return 15
        def run(self, state: TradingState):
            td = json.loads(state.traderData) if state.traderData else None
            if td:
                self.mc=td.get("c",[]); self.tf=td.get("f",[]); self.ew=td.get("w",[])
                self.prev_bid=td.get("pb"); self.signal=td.get("sg",0)
            orders = {}
            # EMERALDS — fixed best
            if "EMERALDS" in state.order_depths:
                od = state.order_depths["EMERALDS"]
                if od.buy_orders and od.sell_orders:
                    eo = []; pos = state.position.get("EMERALDS", 0)
                    tb, ts_ = 80-pos, 80+pos
                    buys = sorted(od.buy_orders.items(), reverse=True)
                    sells = sorted(od.sell_orders.items())
                    self.ew.append(abs(pos)==80)
                    if len(self.ew)>10: self.ew=self.ew[-10:]
                    soft = len(self.ew)==10 and sum(self.ew)>=5 and self.ew[-1]
                    hard = len(self.ew)==10 and all(self.ew)
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
                    orders["EMERALDS"] = eo
            # TOMATOES — parametrized
            if "TOMATOES" in state.order_depths:
                od = state.order_depths["TOMATOES"]
                if od.buy_orders and od.sell_orders:
                    to = []; bb=max(od.buy_orders); ba=min(od.sell_orders)
                    pos = state.position.get("TOMATOES", 0); mid=(bb+ba)*0.5
                    bv=sum(od.buy_orders.values()); av=sum(-v for v in od.sell_orders.values())
                    mp = bb+(bv/(bv+av))*(ba-bb) if (bv+av)>0 else mid
                    c=self.mc
                    if len(c)>=4: c=c[1:]
                    c.append(mp); self.mc=c
                    if len(c)==4:
                        fv = intercept + coefs[0]*c[0]+coefs[1]*c[1]+coefs[2]*c[2]+coefs[3]*c[3]
                    else: fv = mp
                    trades = state.market_trades.get("TOMATOES")
                    if trades:
                        sv=sum(t.quantity if t.price>=mid else -t.quantity for t in trades)
                        self.tf.append(sv)
                    else: self.tf.append(0.0)
                    if len(self.tf)>tf_window: self.tf=self.tf[-tf_window:]
                    fs = max(-1.0, min(1.0, sum(self.tf)/tf_norm))
                    fv -= fs * tf_coef
                    tv = round(fv)
                    if self.prev_bid is not None:
                        bc = bb-self.prev_bid
                        if bc>=move_trig: self.signal=-1
                        elif bc<=-move_trig: self.signal=1
                        elif abs(bc)<=1: self.signal *= sig_decay
                    self.prev_bid = bb
                    tb=80-pos; ts_=80+pos
                    # Takes
                    for p,v in sorted(od.sell_orders.items()):
                        if tb>0 and p<=tv+take_offset:
                            q=min(tb,-v); to.append(Order("TOMATOES",p,q)); tb-=q
                    for p,v in sorted(od.buy_orders.items(), reverse=True):
                        if ts_>0 and p>=tv-take_offset:
                            q=min(ts_,v); to.append(Order("TOMATOES",p,-q)); ts_-=q
                    # Posts
                    if self.signal > sig_thresh:
                        if tb>0:
                            bp=min(tv-post_offset,bb+1); bp=min(bp,ba-1)
                            to.append(Order("TOMATOES",bp,tb))
                        if ts_>0 and pos>=pos_thresh:
                            ap=max(tv+1,ba-1); ap=max(ap,bb+1)
                            to.append(Order("TOMATOES",ap,-ts_))
                        elif ts_>0:
                            ap=max(tv+wide_off,ba-1); ap=max(ap,bb+1)
                            to.append(Order("TOMATOES",ap,-ts_))
                    elif self.signal < -sig_thresh:
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
                    orders["TOMATOES"] = to
            return orders, 0, json.dumps(
                {"c":self.mc,"f":self.tf,"w":self.ew,"pb":self.prev_bid,"sg":round(self.signal,3)},
                separators=(",",":"))
    return Trader


def run_one(params):
    from prosperity4bt.test_runner import TestRunner
    from prosperity4bt.tools.data_reader import PackageResourcesReader
    TraderClass = make_trader(params)
    runner = TestRunner(
        trader=TraderClass(), data_reader=PackageResourcesReader(),
        round=0, day=0, show_progress_bar=False, print_output=False,
        trade_matching_mode=TradeMatchingMode.all, max_ticks=2000,
        iterations=1000, match_mode=MatchMode.default,
    )
    result = runner.run()
    pnl = {a.symbol: a.profit_loss for a in result.final_activities()}
    return pnl.get('TOMATOES', 0), pnl.get('EMERALDS', 0)


if __name__ == '__main__':
    base = {
        'intercept': 2.208667,
        'coefs': [0.059694, 0.117270, 0.244154, 0.578440],
        'tf_coef': 1.5, 'tf_window': 5, 'tf_norm': 15.0,
        'sig_thresh': 0.5, 'sig_decay': 0.7, 'move_trig': 4,
        'wide_off': 3, 'pos_thresh': 40, 'take_offset': 0, 'post_offset': 1,
    }

    print(f"{'Sweep':<25} {'Value':<15} {'TOM':<10} {'Total':<10}")
    print("=" * 60)
    t, e = run_one(base)
    print(f"{'BASELINE':<25} {'—':<15} {t:<10.0f} {t+e:<10.0f}")
    print("-" * 60)

    best_params = dict(base)
    best_params['coefs'] = list(base['coefs'])
    best_tom = t

    sweeps = [
        # Fine intercept grid
        ('intercept', [i * 0.25 for i in range(0, 25)]),  # 0 to 6 in 0.25 steps
        # Individual coefficient sweeps
        ('coef_0', [x * 0.02 for x in range(-5, 15)]),
        ('coef_1', [x * 0.02 for x in range(-5, 15)]),
        ('coef_2', [x * 0.05 for x in range(0, 15)]),
        ('coef_3', [x * 0.05 for x in range(5, 20)]),
        # Trade flow
        ('tf_coef', [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]),
        ('tf_window', [2, 3, 4, 5, 7, 10, 15]),
        ('tf_norm', [3, 5, 8, 10, 15, 20, 30]),
        # Directional
        ('sig_thresh', [0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 999]),
        ('sig_decay', [0.0, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0]),
        ('move_trig', [1, 2, 3, 4, 5, 6, 7, 8]),
        ('wide_off', [1, 2, 3, 4, 5, 6, 7]),
        # Position + takes
        ('pos_thresh', [10, 20, 30, 40, 50, 60, 70, 80]),
        ('take_offset', [-2, -1, 0, 1, 2, 3]),
        ('post_offset', [0, 1, 2, 3]),
    ]

    for dim, values in sweeps:
        best_dim_val = None
        best_dim_tom = -999999
        for val in values:
            p = dict(best_params)
            p['coefs'] = list(best_params['coefs'])
            if dim.startswith('coef_'):
                idx = int(dim[-1])
                p['coefs'][idx] = val
            else:
                p[dim] = val
            t, e = run_one(p)
            marker = " *" if t > best_dim_tom else ""
            print(f"{dim:<25} {val:<15.4f} {t:<10.0f} {t+e:<10.0f}{marker}")
            if t > best_dim_tom:
                best_dim_tom = t
                best_dim_val = val

        # Apply best to running params (greedy)
        if best_dim_tom > best_tom:
            if dim.startswith('coef_'):
                best_params['coefs'][int(dim[-1])] = best_dim_val
            else:
                best_params[dim] = best_dim_val
            best_tom = best_dim_tom
        print(f"  >> Best {dim}: {best_dim_val} (TOM={best_dim_tom:.0f})")
        print()

    # Final combined
    print("=" * 60)
    print("GREEDY-COMBINED BEST PARAMS:")
    for k, v in best_params.items():
        print(f"  {k}: {v}")
    t, e = run_one(best_params)
    print(f"\n{'COMBINED':<25} {'—':<15} {t:<10.0f} {t+e:<10.0f}")
    print(f"Website actual: 2,857 (TOM ~1,828)")
