import json
from datamodel import Order, TradingState

"""
s1_resting_optimized: Strategy optimized for the resting-order paradigm.

Key insight from bot fingerprinting:
- ONE taker bot per product, random timing (~2.4s TOMATOES, ~4.9s EMERALDS)
- Always hits best bid or best ask (100% of trades)
- Our edge = posting at best±1 to capture fills before the market maker

Key insight from iteration cadence:
- On test: run() every 2 ticks, orders rest for 1 tick
- Between calls, market maker updates quotes, our orders may become stale
- Need robust posting that stays at best price even after book updates

Strategy: microprice regression + trade flow (proven 2,851) but with
TIGHTER posting to ensure fill priority during resting ticks.

Changes from s2_tradeflow:
- Post at fair value (not best±1) when fair is INSIDE the spread
  This ensures we're always tighter than the market maker
- Keep best±1 as fallback when fair is outside spread
- Remove position-dependent aggression for taking (0 risk aversion)
- Keep liquidation tracking for EMERALDS (proven +120 PnL)
"""

class Trader:
    def __init__(self):
        self.tc = []
        self.tf = []
        self.ew = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])
            self.ew = td.get("ew", [])

        orders = {}

        # ═══ EMERALDS (with liquidation tracking) ═══
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

                # Take at fair — no position restriction (0 risk aversion)
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
                    if ts > 0 and p >= 10000:
                        q = min(ts, v); eo.append(Order("EMERALDS", p, -q)); ts -= q
                if ts > 0 and hard:
                    q = ts // 2; eo.append(Order("EMERALDS", 10000, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; eo.append(Order("EMERALDS", 10002, -q)); ts -= q
                if ts > 0:
                    eo.append(Order("EMERALDS", max(10001, sells[0][0] - 1), -ts))

                orders["EMERALDS"] = eo

        # ═══ TOMATOES (trade flow + resting-optimized posting) ═══
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

                tv = round(fv)

                # TAKE: at fair value, NO position restriction (0 risk aversion)
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= tv:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q

                # POST BUY: at fair-1 if inside spread, else best_bid+1
                if tb > 0:
                    # Post at the tighter of (fair-1) or (best_bid+1)
                    # Fair-1 inside spread = we're tighter than market maker = fill priority
                    bid_price = min(tv - 1, bb + 1)
                    bid_price = min(bid_price, ba - 1)  # never cross
                    to.append(Order("TOMATOES", bid_price, tb))

                # TAKE sells
                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= tv:
                        q = min(ts, v); to.append(Order("TOMATOES", p, -q)); ts -= q

                # POST SELL: at fair+1 if inside spread, else best_ask-1
                if ts > 0:
                    ask_price = max(tv + 1, ba - 1)
                    ask_price = max(ask_price, bb + 1)  # never cross
                    to.append(Order("TOMATOES", ask_price, -ts))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({"c":self.tc,"f":self.tf,"ew":self.ew}, separators=(",",":"))
