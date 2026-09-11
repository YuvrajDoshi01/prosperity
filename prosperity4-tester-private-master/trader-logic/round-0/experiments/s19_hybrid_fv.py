import json
from datamodel import Order, TradingState

"""
s19_hybrid_fv: Microprice regression for TAKING + Wall Mid for POSTING

Article insight: "PnL is marked against hidden fair value, not visible mid.
Wall Mid tracks hidden FV better."

Hypothesis: Use microprice regression (proven for taking at 2,644) for
take decisions, but use Wall Mid (tracks hidden FV) to cap posting prices.
This gets the best of both: accurate taking + PnL-aware posting.

Wall Mid = midpoint of highest-volume bid and ask levels.
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

        # ═══ EMERALDS (proven, unchanged) ═══
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

        # ═══ TOMATOES (hybrid: microprice for taking, Wall Mid for posting) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, ts = 80 - pos, 80 + pos

                # Microprice regression (for TAKING decisions)
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) * 0.5
                c = self.tc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.tc = c
                if len(c) == 4:
                    fv_take = 2.208667 + 0.059694*c[0] + 0.117270*c[1] + 0.244154*c[2] + 0.578440*c[3]
                else:
                    fv_take = mp

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
                fv_take -= fs * 1.5
                tv_take = round(fv_take)

                # Wall Mid (for POSTING anchor — tracks hidden FV)
                wall_bid = max(od.buy_orders.items(), key=lambda x: x[1])[0]
                wall_ask = max(od.sell_orders.items(), key=lambda x: abs(x[1]))[0]
                tv_post = round((wall_bid + wall_ask) / 2)

                self.tw.append(abs(pos) == 80)
                if len(self.tw) > 10: self.tw = self.tw[-10:]
                soft = len(self.tw) == 10 and sum(self.tw) >= 5 and self.tw[-1]
                hard = len(self.tw) == 10 and all(self.tw)

                # TAKE uses microprice regression FV (proven)
                mbp_take = tv_take - 1 if pos > 40 else tv_take
                msp_take = tv_take + 1 if pos < -40 else tv_take

                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= mbp_take:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                if tb > 0 and hard:
                    q = tb // 2; to.append(Order("TOMATOES", tv_take, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; to.append(Order("TOMATOES", tv_take - 2, q)); tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= msp_take:
                        q = min(ts, v); to.append(Order("TOMATOES", p, -q)); ts -= q
                if ts > 0 and hard:
                    q = ts // 2; to.append(Order("TOMATOES", tv_take, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; to.append(Order("TOMATOES", tv_take + 2, -q)); ts -= q

                # POST uses Wall Mid as cap (tracks hidden FV for PnL marking)
                mbp_post = min(tv_post, tv_take)  # whichever is lower
                msp_post = max(tv_post, tv_take)  # whichever is higher

                if tb > 0:
                    to.append(Order("TOMATOES", min(int(mbp_post), bb + 1), tb))
                if ts > 0:
                    to.append(Order("TOMATOES", max(int(msp_post), ba - 1), -ts))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({"c":self.tc,"f":self.tf,"tw":self.tw,"ew":self.ew}, separators=(",",":"))
