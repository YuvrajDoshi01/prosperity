import json
from datamodel import Order, TradingState

"""
s1_zero_risk: s2_tradeflow logic + ishaanthenerd's hints

Changes from s2_tradeflow (2,851):
1. "0 risk aversion": REMOVE position-dependent aggression
   (was: buy at tv-1 when pos>40, sell at tv+1 when pos<-40)
2. "miss mid less": use CONTINUOUS fair value for taking decisions
   (was: round(fv) then compare — misses when fv is near .5)
3. Remove liquidation tracking (clean execution, no dead code paths)

Post prices still use integer (Order requirement).
"""

class Trader:
    def __init__(self):
        self.tc = []
        self.tf = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])

        orders = {}

        # ═══ EMERALDS — no position aggression, no liquidation ═══
        if "EMERALDS" in state.order_depths:
            od = state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo = []
                pos = state.position.get("EMERALDS", 0)
                tb, ts = 80 - pos, 80 + pos
                buys = sorted(od.buy_orders.items(), reverse=True)
                sells = sorted(od.sell_orders.items())

                # Take at fair — NO position restriction
                for p, v in sells:
                    if tb > 0 and p <= 10000:
                        q = min(tb, -v); eo.append(Order("EMERALDS", p, q)); tb -= q
                if tb > 0:
                    eo.append(Order("EMERALDS", min(9999, buys[0][0] + 1), tb))

                for p, v in buys:
                    if ts > 0 and p >= 10000:
                        q = min(ts, v); eo.append(Order("EMERALDS", p, -q)); ts -= q
                if ts > 0:
                    eo.append(Order("EMERALDS", max(10001, sells[0][0] - 1), -ts))

                orders["EMERALDS"] = eo

        # ═══ TOMATOES — continuous fv, no position aggression ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, ts = 80 - pos, 80 + pos

                # Microprice
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) * 0.5

                c = self.tc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.tc = c

                if len(c) == 4:
                    fv = 2.208667 + 0.059694*c[0] + 0.117270*c[1] + 0.244154*c[2] + 0.578440*c[3]
                else:
                    fv = mp

                # Trade flow
                trades = state.market_trades.get("TOMATOES")
                if trades:
                    mid = (bb + ba) * 0.5
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > 5: self.tf = self.tf[-5:]
                fs = max(-1.0, min(1.0, sum(self.tf) / 15.0))
                fv -= fs * 1.5

                # "miss mid less": use CONTINUOUS fv for taking, integer for posting
                tv_int = round(fv)  # for posting only

                # Take buys: compare price to CONTINUOUS fv (not rounded)
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= fv:  # continuous comparison!
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                if tb > 0:
                    to.append(Order("TOMATOES", min(tv_int, bb + 1), tb))

                # Take sells: compare price to CONTINUOUS fv
                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= fv:  # continuous comparison!
                        q = min(ts, v); to.append(Order("TOMATOES", p, -q)); ts -= q
                if ts > 0:
                    to.append(Order("TOMATOES", max(tv_int, ba - 1), -ts))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({"c": self.tc, "f": self.tf}, separators=(",", ":"))
