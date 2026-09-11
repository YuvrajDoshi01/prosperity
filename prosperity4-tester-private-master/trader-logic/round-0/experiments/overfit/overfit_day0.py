"""
Overfit sweep on day 0 (website data) — find the ceiling.
Sweeps: regression intercept, lag coefficients, trade flow params,
directional posting params, position thresholds, EMERALDS params.
"""
import sys, os, itertools, importlib, copy
bt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'prosperity4bt')
sys.path.insert(0, bt_path)
# Also need the parent for prosperity4bt package imports
sys.path.insert(0, os.path.join(bt_path, '..'))

from prosperity4bt.back_tester import BackTester
from prosperity4bt.models.test_options import TestOptions, TradeMatchingMode, MatchMode

# We'll parametrize s3_carry inline
import json
from prosperity4bt.datamodel import Order, TradingState


def make_trader_class(params):
    """Create a Trader class with the given parameters."""
    intercept = params['intercept']
    coefs = params['coefs']
    tf_coef = params['tf_coef']
    tf_window = params['tf_window']
    tf_norm = params['tf_norm']
    signal_threshold = params['signal_threshold']
    signal_decay = params['signal_decay']
    move_trigger = params['move_trigger']
    wide_offset = params['wide_offset']
    pos_threshold = params['pos_threshold']
    em_soft_thresh = params['em_soft_thresh']
    em_hard_thresh = params['em_hard_thresh']

    class Trader:
        def __init__(self):
            self.mc = []
            self.tf = []
            self.ew = []
            self.prev_bid = None
            self.signal = 0

        def bid(self):
            return 15

        def run(self, state: TradingState):
            td = json.loads(state.traderData) if state.traderData else None
            if td:
                self.mc = td.get("c", [])
                self.tf = td.get("f", [])
                self.ew = td.get("w", [])
                self.prev_bid = td.get("pb")
                self.signal = td.get("sg", 0)

            orders = {}
            conversions = 0

            # EMERALDS
            if "EMERALDS" in state.order_depths:
                od = state.order_depths["EMERALDS"]
                if od.buy_orders and od.sell_orders:
                    eo = []
                    pos = state.position.get("EMERALDS", 0)
                    tb, ts_ = 80 - pos, 80 + pos
                    buys = sorted(od.buy_orders.items(), reverse=True)
                    sells = sorted(od.sell_orders.items())
                    self.ew.append(abs(pos) == 80)
                    if len(self.ew) > 10: self.ew = self.ew[-10:]
                    soft = len(self.ew) == 10 and sum(self.ew) >= em_soft_thresh and self.ew[-1]
                    hard = len(self.ew) == 10 and sum(self.ew) >= em_hard_thresh
                    for p, v in sells:
                        if tb > 0 and p <= 10000:
                            q = min(tb, -v); eo.append(Order("EMERALDS", p, q)); tb -= q
                    if tb > 0 and hard:
                        q = tb // 2; eo.append(Order("EMERALDS", 10000, q)); tb -= q
                    if tb > 0 and soft:
                        q = tb // 2; eo.append(Order("EMERALDS", 9998, q)); tb -= q
                    if tb > 0:
                        eo.append(Order("EMERALDS", min(9999, buys[0][0] + 1), tb))
                    for p, v in buys:
                        if ts_ > 0 and p >= 10000:
                            q = min(ts_, v); eo.append(Order("EMERALDS", p, -q)); ts_ -= q
                    if ts_ > 0 and hard:
                        q = ts_ // 2; eo.append(Order("EMERALDS", 10000, -q)); ts_ -= q
                    if ts_ > 0 and soft:
                        q = ts_ // 2; eo.append(Order("EMERALDS", 10002, -q)); ts_ -= q
                    if ts_ > 0:
                        eo.append(Order("EMERALDS", max(10001, sells[0][0] - 1), -ts_))
                    orders["EMERALDS"] = eo

            # TOMATOES
            if "TOMATOES" in state.order_depths:
                od = state.order_depths["TOMATOES"]
                if od.buy_orders and od.sell_orders:
                    to = []
                    bb = max(od.buy_orders)
                    ba = min(od.sell_orders)
                    pos = state.position.get("TOMATOES", 0)
                    mid = (bb + ba) * 0.5
                    bv = sum(od.buy_orders.values())
                    av = sum(-v for v in od.sell_orders.values())
                    mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else mid

                    c = self.mc
                    if len(c) >= 4: c = c[1:]
                    c.append(mp)
                    self.mc = c

                    if len(c) == 4:
                        fv = intercept + coefs[0]*c[0] + coefs[1]*c[1] + coefs[2]*c[2] + coefs[3]*c[3]
                    else:
                        fv = mp

                    trades = state.market_trades.get("TOMATOES")
                    if trades:
                        sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                        self.tf.append(sv)
                    else:
                        self.tf.append(0.0)
                    if len(self.tf) > tf_window: self.tf = self.tf[-tf_window:]
                    fs = max(-1.0, min(1.0, sum(self.tf) / tf_norm))
                    fv -= fs * tf_coef

                    tv = round(fv)

                    if self.prev_bid is not None:
                        bid_change = bb - self.prev_bid
                        if bid_change >= move_trigger:
                            self.signal = -1
                        elif bid_change <= -move_trigger:
                            self.signal = 1
                        elif abs(bid_change) <= 1:
                            self.signal = self.signal * signal_decay
                    self.prev_bid = bb

                    tb = 80 - pos
                    ts_ = 80 + pos

                    for p, v in sorted(od.sell_orders.items()):
                        if tb > 0 and p <= tv:
                            q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                    for p, v in sorted(od.buy_orders.items(), reverse=True):
                        if ts_ > 0 and p >= tv:
                            q = min(ts_, v); to.append(Order("TOMATOES", p, -q)); ts_ -= q

                    ss = abs(self.signal)

                    if self.signal > signal_threshold:
                        if tb > 0:
                            bp = min(tv - 1, bb + 1); bp = min(bp, ba - 1)
                            to.append(Order("TOMATOES", bp, tb))
                        if ts_ > 0 and pos >= pos_threshold:
                            ap = max(tv + 1, ba - 1); ap = max(ap, bb + 1)
                            to.append(Order("TOMATOES", ap, -ts_))
                        elif ts_ > 0:
                            ap = max(tv + wide_offset, ba - 1); ap = max(ap, bb + 1)
                            to.append(Order("TOMATOES", ap, -ts_))
                    elif self.signal < -signal_threshold:
                        if ts_ > 0:
                            ap = max(tv + 1, ba - 1); ap = max(ap, bb + 1)
                            to.append(Order("TOMATOES", ap, -ts_))
                        if tb > 0 and pos <= -pos_threshold:
                            bp = min(tv - 1, bb + 1); bp = min(bp, ba - 1)
                            to.append(Order("TOMATOES", bp, tb))
                        elif tb > 0:
                            bp = min(tv - wide_offset, bb + 1); bp = min(bp, ba - 1)
                            to.append(Order("TOMATOES", bp, tb))
                    else:
                        if tb > 0:
                            bp = min(tv - 1, bb + 1); bp = min(bp, ba - 1)
                            to.append(Order("TOMATOES", bp, tb))
                        if ts_ > 0:
                            ap = max(tv + 1, ba - 1); ap = max(ap, bb + 1)
                            to.append(Order("TOMATOES", ap, -ts_))

                    orders["TOMATOES"] = to

            return orders, conversions, json.dumps(
                {"c": self.mc, "f": self.tf, "w": self.ew, "pb": self.prev_bid, "sg": round(self.signal, 3)},
                separators=(",", ":")
            )

    return Trader


def run_backtest(trader_class, match_mode='default'):
    from prosperity4bt.test_runner import TestRunner
    from prosperity4bt.tools.data_reader import PackageResourcesReader

    trader = trader_class()
    data_reader = PackageResourcesReader()
    runner = TestRunner(
        trader=trader,
        data_reader=data_reader,
        round=0,
        day=0,
        show_progress_bar=False,
        print_output=False,
        trade_matching_mode=TradeMatchingMode.all,
        max_ticks=2000,
        iterations=1000,
        match_mode=MatchMode[match_mode],
    )
    return runner.run()


if __name__ == '__main__':
    # Baseline params (s3_carry)
    baseline = {
        'intercept': 2.208667,
        'coefs': [0.059694, 0.117270, 0.244154, 0.578440],
        'tf_coef': 1.5,
        'tf_window': 5,
        'tf_norm': 15.0,
        'signal_threshold': 0.5,
        'signal_decay': 0.7,
        'move_trigger': 4,
        'wide_offset': 3,
        'pos_threshold': 40,
        'em_soft_thresh': 5,
        'em_hard_thresh': 10,
    }

    # Define sweep dimensions
    sweeps = {
        'intercept': [0.0, 1.0, 2.208667, 3.0, 5.0, 8.0, 10.0],
        'tf_coef': [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0],
        'tf_window': [3, 5, 7, 10],
        'tf_norm': [5.0, 10.0, 15.0, 20.0, 30.0],
        'signal_threshold': [0.3, 0.5, 0.7, 1.0, 999],  # 999 = disable directional
        'signal_decay': [0.0, 0.3, 0.5, 0.7, 0.9],
        'move_trigger': [2, 3, 4, 5, 6],
        'wide_offset': [1, 2, 3, 4, 5],
        'pos_threshold': [20, 30, 40, 50, 60],
        'em_soft_thresh': [3, 5, 7],
        'em_hard_thresh': [8, 10],
    }

    print(f"{'Dimension':<20} {'Value':<12} {'TOMATOES':<12} {'EMERALDS':<12} {'Total':<12}")
    print("=" * 68)

    # Run baseline first
    TraderClass = make_trader_class(baseline)
    result = run_backtest(TraderClass)
    pnl = {a.symbol: a.profit_loss for a in result.final_activities()}
    tom = pnl.get('TOMATOES', 0)
    em = pnl.get('EMERALDS', 0)
    print(f"{'BASELINE':<20} {'—':<12} {tom:<12.0f} {em:<12.0f} {tom+em:<12.0f}")
    print("-" * 68)

    best_overall = {'params': baseline.copy(), 'total': tom + em}

    # Sweep each dimension independently
    for dim, values in sweeps.items():
        best_dim = {'value': baseline[dim], 'total': -999999}
        for val in values:
            params = baseline.copy()
            params['coefs'] = list(baseline['coefs'])  # deep copy
            params[dim] = val

            TraderClass = make_trader_class(params)
            result = run_backtest(TraderClass)
            pnl = {a.symbol: a.profit_loss for a in result.final_activities()}
            tom = pnl.get('TOMATOES', 0)
            em = pnl.get('EMERALDS', 0)
            total = tom + em
            marker = " *" if total > best_dim['total'] else ""
            print(f"{dim:<20} {str(val):<12} {tom:<12.0f} {em:<12.0f} {total:<12.0f}{marker}")

            if total > best_dim['total']:
                best_dim = {'value': val, 'total': total}

        if best_dim['total'] > best_overall['total']:
            best_overall['params'][dim] = best_dim['value']
            best_overall['total'] = best_dim['total']
        print(f"  >> Best {dim}: {best_dim['value']} ({best_dim['total']:.0f})")
        print()

    # Run with all best params combined
    print("=" * 68)
    print("COMBINED BEST:")
    print(best_overall['params'])
    TraderClass = make_trader_class(best_overall['params'])
    result = run_backtest(TraderClass)
    pnl = {a.symbol: a.profit_loss for a in result.final_activities()}
    tom = pnl.get('TOMATOES', 0)
    em = pnl.get('EMERALDS', 0)
    print(f"{'COMBINED':<20} {'—':<12} {tom:<12.0f} {em:<12.0f} {tom+em:<12.0f}")
    print(f"\nWebsite actual: 2,857")
