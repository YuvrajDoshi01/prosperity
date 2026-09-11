import json
from datamodel import Order, TradingState

"""
s2_asymmetric_gentle: s2_tradeflow (2,851) + Gentle Asymmetric Sizing

Same concept as s1_asymmetric but with gentler parameters:
- Threshold: 5 ticks (was 3) — only trigger on larger moves
- Light fraction: 0.5 (was 0.3) — still post half capacity on continuation side

Less aggressive = less risk of missing fills on the light side.
"""

MOVE_THRESHOLD = 5.0
LIGHT_FRACTION = 0.5


class Trader:
    def __init__(self):
        self.tc = []
        self.tf = []
        self.tw = []
        self.ew = []
        self.mid_history = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])
            self.tw = td.get("tw", [])
            self.ew = td.get("ew", [])
            self.mid_history = td.get("mh", [])

        orders = {}

        # ═══ EMERALDS (proven, don't change) ═══
        if "EMERALDS" in state.order_depths:
            od = state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo = []
                pos = state.position.get("EMERALDS", 0)
                tb, ts = 80 - pos, 80 + pos
                buys = sorted(od.buy_orders.items(), reverse=True)
                sells = sorted(od.sell_orders.items())

                self.ew.append(abs(pos) == 80)
                if len(self.ew) > 10: self.ew = self.ew[-10:]
                soft = len(self.ew) == 10 and sum(self.ew) >= 5 and self.ew[-1]
                hard = len(self.ew) == 10 and all(self.ew)

                mbp = 10000 - 1 if pos > 40 else 10000
                msp = 10000 + 1 if pos < -40 else 10000

                for p, v in sells:
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v); eo.append(Order("EMERALDS", p, q)); tb -= q
                if tb > 0 and hard:
                    q = tb // 2; eo.append(Order("EMERALDS", 10000, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; eo.append(Order("EMERALDS", 9998, q)); tb -= q
                if tb > 0:
                    eo.append(Order("EMERALDS", min(mbp, buys[0][0] + 1), tb))

                for p, v in buys:
                    if ts > 0 and p >= msp:
                        q = min(ts, v); eo.append(Order("EMERALDS", p, -q)); ts -= q
                if ts > 0 and hard:
                    q = ts // 2; eo.append(Order("EMERALDS", 10000, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; eo.append(Order("EMERALDS", 10002, -q)); ts -= q
                if ts > 0:
                    eo.append(Order("EMERALDS", max(msp, sells[0][0] - 1), -ts))

                orders["EMERALDS"] = eo

        # ═══ TOMATOES (trade flow + gentle asymmetric sizing) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, ts = 80 - pos, 80 + pos
                mid = (bb + ba) * 0.5

                self.mid_history.append(mid)
                if len(self.mid_history) > 10:
                    self.mid_history = self.mid_history[-10:]

                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else mid

                c = self.tc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.tc = c

                if len(c) == 4:
                    fv = 2.208667 + 0.059694*c[0] + 0.117270*c[1] + 0.244154*c[2] + 0.578440*c[3]
                else:
                    fv = mp

                trades = state.market_trades.get("TOMATOES")
                if trades:
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > 5: self.tf = self.tf[-5:]
                fs = max(-1.0, min(1.0, sum(self.tf) / 15.0))
                fv -= fs * 1.5
                tv = round(fv)

                self.tw.append(abs(pos) == 80)
                if len(self.tw) > 10: self.tw = self.tw[-10:]
                soft = len(self.tw) == 10 and sum(self.tw) >= 5 and self.tw[-1]
                hard = len(self.tw) == 10 and all(self.tw)

                mbp = tv - 1 if pos > 40 else tv
                msp = tv + 1 if pos < -40 else tv

                # TAKE
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                if tb > 0 and hard:
                    q = tb // 2; to.append(Order("TOMATOES", tv, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; to.append(Order("TOMATOES", tv - 2, q)); tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= msp:
                        q = min(ts, v); to.append(Order("TOMATOES", p, -q)); ts -= q
                if ts > 0 and hard:
                    q = ts // 2; to.append(Order("TOMATOES", tv, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; to.append(Order("TOMATOES", tv + 2, -q)); ts -= q

                # MAKE: gentle asymmetric sizing
                recent_move = 0.0
                if len(self.mid_history) >= 6:
                    recent_move = self.mid_history[-1] - self.mid_history[-6]

                if recent_move > MOVE_THRESHOLD:
                    buy_qty = max(1, int(tb * LIGHT_FRACTION))
                    sell_qty = ts
                elif recent_move < -MOVE_THRESHOLD:
                    buy_qty = tb
                    sell_qty = max(1, int(ts * LIGHT_FRACTION))
                else:
                    buy_qty = tb
                    sell_qty = ts

                if buy_qty > 0:
                    to.append(Order("TOMATOES", min(mbp, bb + 1), buy_qty))
                if sell_qty > 0:
                    to.append(Order("TOMATOES", max(msp, ba - 1), -sell_qty))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({
            "c": self.tc, "f": self.tf, "tw": self.tw, "ew": self.ew,
            "mh": self.mid_history
        }, separators=(",", ":"))
