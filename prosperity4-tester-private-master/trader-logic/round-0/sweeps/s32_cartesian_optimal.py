import json
from datamodel import Order, TradingState


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

        # ═══ EMERALDS (unchanged) ═══
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
                soft = len(self.ew) == 10 and sum(self.ew) >= 5 and self.ew[-1]
                hard = len(self.ew) == 10 and all(self.ew)
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

        # ═══ TOMATOES (Cartesian-optimal params from day 0 sweep) ═══
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
                    fv = 2.75 + 0.059694*c[0] + 0.117270*c[1] + 0.244154*c[2] + 0.578440*c[3]
                else:
                    fv = mp

                trades = state.market_trades.get("TOMATOES")
                if trades:
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > 10: self.tf = self.tf[-10:]
                fs = max(-1.0, min(1.0, sum(self.tf) / 10.0))
                fv -= fs * 3.0

                tv = round(fv)

                if self.prev_bid is not None:
                    bid_change = bb - self.prev_bid
                    if bid_change >= 4:
                        self.signal = -1
                    elif bid_change <= -4:
                        self.signal = 1
                    elif abs(bid_change) <= 1:
                        self.signal = self.signal * 0.9
                self.prev_bid = bb

                tb = 80 - pos
                ts_ = 80 + pos

                # Takes at fair
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= tv:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts_ > 0 and p >= tv:
                        q = min(ts_, v); to.append(Order("TOMATOES", p, -q)); ts_ -= q

                # Directional posting
                if self.signal > 0.5:
                    if tb > 0:
                        bp = min(tv - 2, bb + 1); bp = min(bp, ba - 1)
                        to.append(Order("TOMATOES", bp, tb))
                    if ts_ > 0 and pos >= 40:
                        ap = max(tv + 1, ba - 1); ap = max(ap, bb + 1)
                        to.append(Order("TOMATOES", ap, -ts_))
                    elif ts_ > 0:
                        ap = max(tv + 5, ba - 1); ap = max(ap, bb + 1)
                        to.append(Order("TOMATOES", ap, -ts_))
                elif self.signal < -0.5:
                    if ts_ > 0:
                        ap = max(tv + 2, ba - 1); ap = max(ap, bb + 1)
                        to.append(Order("TOMATOES", ap, -ts_))
                    if tb > 0 and pos <= -40:
                        bp = min(tv - 1, bb + 1); bp = min(bp, ba - 1)
                        to.append(Order("TOMATOES", bp, tb))
                    elif tb > 0:
                        bp = min(tv - 5, bb + 1); bp = min(bp, ba - 1)
                        to.append(Order("TOMATOES", bp, tb))
                else:
                    if tb > 0:
                        bp = min(tv - 2, bb + 1); bp = min(bp, ba - 1)
                        to.append(Order("TOMATOES", bp, tb))
                    if ts_ > 0:
                        ap = max(tv + 2, ba - 1); ap = max(ap, bb + 1)
                        to.append(Order("TOMATOES", ap, -ts_))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps(
            {"c": self.mc, "f": self.tf, "w": self.ew, "pb": self.prev_bid, "sg": round(self.signal, 3)},
            separators=(",", ":")
        )
