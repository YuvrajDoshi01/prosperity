import json
from datamodel import Order, TradingState

"""
s23_take_only: Take Only — ZERO making/passive posting.

Uses microprice regression + trade flow for fair value (proven from s2_tradeflow).
But instead of posting at best±1, ONLY takes everything at/below fair.
NO passive posting at all.
"""

class Trader:
    def __init__(self):
        self.tc = []    # TOMATOES microprice cache (max 4)
        self.tf = []    # TOMATOES trade flow history (max 5)
        self.ew = []    # EMERALDS liquidation window (max 10)

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])
            self.ew = td.get("ew", [])

        orders = {}

        # ═══ EMERALDS (standard take at 10000, post at best±1, liquidation tracking) ═══
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

        # ═══ TOMATOES (take only — ZERO passive posting) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, ts = 80 - pos, 80 + pos
                mid = (bb + ba) * 0.5

                # Microprice
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else mid

                # Cache
                c = self.tc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.tc = c

                # Fair value from regression
                if len(c) == 4:
                    fv = 2.208667 + 0.059694*c[0] + 0.117270*c[1] + 0.244154*c[2] + 0.578440*c[3]
                else:
                    fv = mp

                # Trade flow
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

                # Take everything at/below fair (buy side)
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= tv:
                        q = min(tb, -v)
                        to.append(Order("TOMATOES", p, q)); tb -= q

                # Take everything at/above fair (sell side)
                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= tv:
                        q = min(ts, v)
                        to.append(Order("TOMATOES", p, -q)); ts -= q

                # NO passive posting at all

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({"c": self.tc, "f": self.tf, "ew": self.ew}, separators=(",", ":"))
