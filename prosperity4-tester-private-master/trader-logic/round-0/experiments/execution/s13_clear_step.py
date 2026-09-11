import json
from datamodel import Order, TradingState

"""
s13_clear_step: s2_tradeflow + proper CLEAR step from Prosperity Fundamentals PDF

The PDF says every top team uses Take → Clear → Make:
  Take: buy below FV, sell above FV (guaranteed profit)
  Clear: flatten position AT fair value (zero PnL, frees capacity for next take)
  Make: post passive orders at best±1 (speculative)

Our current strategy skips Clear entirely. This adds it.
"""

class Trader:
    def __init__(self):
        self.tc = []
        self.tf = []
        self.tw = []
        self.ew = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])
            self.tw = td.get("tw", [])
            self.ew = td.get("ew", [])

        orders = {}

        # ═══ EMERALDS ═══
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

                # TAKE
                for p, v in sells:
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v); eo.append(Order("EMERALDS", p, q)); tb -= q
                for p, v in buys:
                    if ts > 0 and p >= msp:
                        q = min(ts, v); eo.append(Order("EMERALDS", p, -q)); ts -= q

                # CLEAR at fair value
                filled_buy = (80 - state.position.get("EMERALDS", 0)) - tb
                filled_sell = (80 + state.position.get("EMERALDS", 0)) - ts
                eff_pos = state.position.get("EMERALDS", 0) + filled_buy - filled_sell
                if eff_pos > 0 and ts > 0:
                    cq = min(eff_pos, ts)
                    eo.append(Order("EMERALDS", tv, -cq)); ts -= cq
                elif eff_pos < 0 and tb > 0:
                    cq = min(abs(eff_pos), tb)
                    eo.append(Order("EMERALDS", tv, cq)); tb -= cq

                # MAKE
                if tb > 0 and hard:
                    q = tb // 2; eo.append(Order("EMERALDS", tv, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; eo.append(Order("EMERALDS", tv - 2, q)); tb -= q
                if tb > 0:
                    eo.append(Order("EMERALDS", min(mbp, buys[0][0] + 1), tb))
                if ts > 0 and hard:
                    q = ts // 2; eo.append(Order("EMERALDS", tv, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; eo.append(Order("EMERALDS", tv + 2, -q)); ts -= q
                if ts > 0:
                    eo.append(Order("EMERALDS", max(msp, sells[0][0] - 1), -ts))

                orders["EMERALDS"] = eo

        # ═══ TOMATOES ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, ts = 80 - pos, 80 + pos

                # Microprice + regression
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
                tv = round(fv)

                self.tw.append(abs(pos) == 80)
                if len(self.tw) > 10: self.tw = self.tw[-10:]
                soft = len(self.tw) == 10 and sum(self.tw) >= 5 and self.tw[-1]
                hard = len(self.tw) == 10 and all(self.tw)
                mbp = tv - 1 if pos > 40 else tv
                msp = tv + 1 if pos < -40 else tv

                # STEP 1: TAKE
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= msp:
                        q = min(ts, v); to.append(Order("TOMATOES", p, -q)); ts -= q

                # STEP 2: CLEAR — flatten position at fair value
                filled_buy = (80 - pos) - tb
                filled_sell = (80 + pos) - ts
                eff_pos = pos + filled_buy - filled_sell
                if eff_pos > 0 and ts > 0:
                    cq = min(eff_pos, ts)
                    to.append(Order("TOMATOES", tv, -cq)); ts -= cq
                elif eff_pos < 0 and tb > 0:
                    cq = min(abs(eff_pos), tb)
                    to.append(Order("TOMATOES", tv, cq)); tb -= cq

                # STEP 3: MAKE at best±1
                if tb > 0 and hard:
                    q = tb // 2; to.append(Order("TOMATOES", tv, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; to.append(Order("TOMATOES", tv - 2, q)); tb -= q
                if tb > 0:
                    to.append(Order("TOMATOES", min(mbp, bb + 1), tb))
                if ts > 0 and hard:
                    q = ts // 2; to.append(Order("TOMATOES", tv, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; to.append(Order("TOMATOES", tv + 2, -q)); ts -= q
                if ts > 0:
                    to.append(Order("TOMATOES", max(msp, ba - 1), -ts))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({"c":self.tc,"f":self.tf,"tw":self.tw,"ew":self.ew}, separators=(",",":"))
