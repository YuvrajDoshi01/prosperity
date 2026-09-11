import json
from datamodel import Order, TradingState

"""
s29_sim_optimal: GPU sim sweep winner (276K combos × 5 seeds)

WARNING: These params are at grid edges (INTERCEPT=10.0, FLOW=2.5).
May be overfitting to sim model. Submit as experiment, not as main strategy.

Optimal params from sim sweep:
  lag=3, intercept=10.0, flow=2.5, aggr=2/30, post=3
  DIR params don't matter (all score identical)
"""

# Cross-validated regression for lag=3 (averaged from both training days)
INTERCEPT = 10.0
COEFS_LAG3 = None  # computed at runtime from training data
FLOW_COEF = 2.5
FLOW_WINDOW = 5
TOM_AGGR_TICK = 2
TOM_POS_THRESH = 30
DIR_TRIGGER = 4
DIR_WIDTH = 5
DIR_DECAY = 0.7
POST_OFFSET = 3


class Trader:
    def __init__(self):
        self.tc = []
        self.tf = []
        self.ew = []
        self.tw = []
        self.pb = None
        self.sig = 0
        # Lag-3 regression coefficients (pre-fitted, averaged from both days)
        # Day -2: intercept=13.78, coefs=[0.112, 0.240, 0.646]
        # Day -1: intercept=6.15, coefs=[0.117, 0.244, 0.638]
        # Average: coefs=[0.115, 0.242, 0.642] (sum=0.999)
        self.coefs = [0.114537, 0.242047, 0.642072]

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])
            self.ew = td.get("w", [])
            self.tw = td.get("tw", [])
            self.pb = td.get("pb")
            self.sig = td.get("sg", 0)

        orders = {}

        # ═══ EMERALDS (proven, unchanged from s25) ═══
        if "EMERALDS" in state.order_depths:
            od = state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo = []
                pos = state.position.get("EMERALDS", 0)
                tb, ts = 80 - pos, 80 + pos
                buys = sorted(od.buy_orders.items(), reverse=True)
                sells = sorted(od.sell_orders.items())
                tv = 10000
                self.ew.append(abs(pos) == 80)
                if len(self.ew) > 10: self.ew = self.ew[-10:]
                soft = len(self.ew) == 10 and sum(self.ew) >= 5 and self.ew[-1]
                hard = len(self.ew) == 10 and all(self.ew)
                mbp = tv - 1 if pos > 40 else tv
                msp = tv + 1 if pos < -40 else tv
                for p, v in sells:
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v); eo.append(Order("EMERALDS", p, q)); tb -= q
                if tb > 0 and hard:
                    q = tb // 2; eo.append(Order("EMERALDS", tv, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; eo.append(Order("EMERALDS", tv - 2, q)); tb -= q
                if tb > 0:
                    eo.append(Order("EMERALDS", min(mbp, buys[0][0] + 1), tb))
                for p, v in buys:
                    if ts > 0 and p >= msp:
                        q = min(ts, v); eo.append(Order("EMERALDS", p, -q)); ts -= q
                if ts > 0 and hard:
                    q = ts // 2; eo.append(Order("EMERALDS", tv, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; eo.append(Order("EMERALDS", tv + 2, -q)); ts -= q
                if ts > 0:
                    eo.append(Order("EMERALDS", max(msp, sells[0][0] - 1), -ts))
                orders["EMERALDS"] = eo

        # ═══ TOMATOES (sim sweep optimal) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (bb + ba) * 0.5

                # Microprice
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else mid

                c = self.tc
                if len(c) >= 3: c = c[1:]
                c.append(mp)
                self.tc = c

                if len(c) == 3:
                    fv = INTERCEPT + sum(co * lag for co, lag in zip(self.coefs, c))
                else:
                    fv = mp

                # Trade flow
                trades = state.market_trades.get("TOMATOES")
                if trades:
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > FLOW_WINDOW: self.tf = self.tf[-FLOW_WINDOW:]
                fs = max(-1.0, min(1.0, sum(self.tf) / 15.0))
                fv -= fs * FLOW_COEF

                tv = round(fv)

                # Directional signal
                if self.pb is not None:
                    bc = bb - self.pb
                    if bc >= DIR_TRIGGER: self.sig = -1
                    elif bc <= -DIR_TRIGGER: self.sig = 1
                    elif abs(bc) <= 1: self.sig *= DIR_DECAY
                self.pb = bb

                # Liquidation tracking
                self.tw.append(abs(pos) == 80)
                if len(self.tw) > 10: self.tw = self.tw[-10:]
                tsoft = len(self.tw) == 10 and sum(self.tw) >= 5 and self.tw[-1]
                thard = len(self.tw) == 10 and all(self.tw)

                tb = 80 - pos
                ts = 80 + pos

                # Take with aggression=2 at threshold=30
                mbp = tv - TOM_AGGR_TICK if pos > TOM_POS_THRESH else tv
                msp = tv + TOM_AGGR_TICK if pos < -TOM_POS_THRESH else tv

                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                if tb > 0 and thard:
                    q = tb // 2; to.append(Order("TOMATOES", tv, q)); tb -= q
                if tb > 0 and tsoft:
                    q = tb // 2; to.append(Order("TOMATOES", tv - 2, q)); tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= msp:
                        q = min(ts, v); to.append(Order("TOMATOES", p, -q)); ts -= q
                if ts > 0 and thard:
                    q = ts // 2; to.append(Order("TOMATOES", tv, -q)); ts -= q
                if ts > 0 and tsoft:
                    q = ts // 2; to.append(Order("TOMATOES", tv + 2, -q)); ts -= q

                # Post with directional signal
                if self.sig > 0.5:
                    if tb > 0: to.append(Order("TOMATOES", min(tv - 1, bb + 1), tb))
                    if ts > 0: to.append(Order("TOMATOES", max(tv + DIR_WIDTH, ba - 1, bb + 1), -ts))
                elif self.sig < -0.5:
                    if ts > 0: to.append(Order("TOMATOES", max(tv + 1, ba - 1), -ts))
                    if tb > 0: to.append(Order("TOMATOES", min(tv - DIR_WIDTH, bb + 1, ba - 1), tb))
                else:
                    if tb > 0: to.append(Order("TOMATOES", min(tv - POST_OFFSET, bb + 1), tb))
                    if ts > 0: to.append(Order("TOMATOES", max(tv + POST_OFFSET, ba - 1), -ts))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({"c": self.tc, "f": self.tf, "w": self.ew, "tw": self.tw, "pb": self.pb, "sg": round(self.sig, 3)}, separators=(",", ":"))
