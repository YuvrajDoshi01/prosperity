import json
from datamodel import Order, TradingState

"""
s3_tight_only.py — Pure Tight Posting Strategy

HYPOTHESIS TEST: If the taker bot's frequency increases when it sees a
tighter spread, posting at FV±1 should generate SIGNIFICANTLY more fills
on the website than in the backtester.

Expected backtester result: ~2,800 (same as current, fills capped by historical data)
If website result is >3,500: BOTS ARE REACTIVE to spread width
If website result is ~2,800: bots are NOT reactive, look elsewhere

DESIGN:
- Post at round(FV) ± 1 for TOMATOES
- Take aggressively at FV for both products
- Full position utilization (80 lot limit)
- No inventory skew (let position drift to maximize fills)
"""


class Trader:
    def __init__(self):
        self.mc = []
        self.tf = []
        self.ew = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.mc = td.get("c", [])
            self.tf = td.get("f", [])
            self.ew = td.get("w", [])

        orders = {}
        conversions = 0

        # ═══ EMERALDS (proven strategy, unchanged) ═══
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

        # ═══ TOMATOES — TIGHT POSTING AT FV±1 ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb = max(od.buy_orders)
                ba = min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (bb + ba) * 0.5

                # Microprice regression (same proven FV)
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else mid

                c = self.mc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.mc = c

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
                tb = 80 - pos
                ts_ = 80 + pos

                # TAKE: at fair value, no position restriction
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= tv:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts_ > 0 and p >= tv:
                        q = min(ts_, v); to.append(Order("TOMATOES", p, -q)); ts_ -= q

                # POST: TIGHT at FV ± 1
                # This is the key test: if bots react to tighter spread,
                # we should get significantly more fills on the website
                if tb > 0:
                    bid_price = tv - 1
                    bid_price = min(bid_price, ba - 1)  # don't cross
                    bid_price = max(bid_price, bb)  # at least at MM bid
                    to.append(Order("TOMATOES", bid_price, tb))

                if ts_ > 0:
                    ask_price = tv + 1
                    ask_price = max(ask_price, bb + 1)  # don't cross
                    ask_price = min(ask_price, ba)  # at most at MM ask
                    to.append(Order("TOMATOES", ask_price, -ts_))

                orders["TOMATOES"] = to

        return orders, conversions, json.dumps(
            {"c": self.mc, "f": self.tf, "w": self.ew},
            separators=(",", ":")
        )
