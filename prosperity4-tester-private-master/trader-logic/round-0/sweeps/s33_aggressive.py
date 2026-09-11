import json
from datamodel import Order, TradingState

"""
s33_aggressive — Lessons from god mode applied to non-oracle strategy.

Key findings from god_mmtake (5,236) vs s3_carry (2,857):
1. god gets 2.5x more fill volume (825 vs 325 units)
2. s3 only takes 12 times aggressively; god takes 72 times
3. Spread per fill is identical (9.6 vs 10.0)
4. The volume gap IS the PnL gap

Changes from s3_carry:
- AGGRESSIVE TAKES: when FV deviates from mid by > threshold, take L1
- ONE-SIDED POSTING: when signal is strong, don't post on wrong side at all
  (current s3 always posts both sides, just at different widths)
- WIDER TAKE BAND: take at tv±1 instead of just at tv
- Cartesian-optimal params from day 0 sweep
"""


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

        # ═══ EMERALDS (unchanged — already optimal) ═══
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

        # ═══ TOMATOES (aggressive MM + take) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb = max(od.buy_orders)
                ba = min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (bb + ba) * 0.5

                # FV regression (Cartesian-optimal)
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

                # Trade flow
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

                # Directional signal
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

                # FV deviation from mid — this drives aggression
                fv_dev = fv - mid  # positive = FV above mid = want to buy

                # PHASE 1: AGGRESSIVE TAKES (the big change)
                # Take at tv±1 instead of just tv
                # When FV deviates, widen the take band further
                take_band = 1 if abs(fv_dev) > 1 else 0

                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= tv + take_band:
                        q = min(tb, -v)
                        to.append(Order("TOMATOES", p, q))
                        tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts_ > 0 and p >= tv - take_band:
                        q = min(ts_, v)
                        to.append(Order("TOMATOES", p, -q))
                        ts_ -= q

                # PHASE 2: POSTING — one-sided when directional
                if self.signal > 0.5:
                    # Expect UP → want LONG → tight bid, NO ask (unless pos high)
                    if tb > 0:
                        to.append(Order("TOMATOES", bb + 1, tb))
                    if pos >= 60 and ts_ > 0:
                        # Only post ask if we need to manage position
                        to.append(Order("TOMATOES", ba - 1, -ts_))
                    # else: NO ask posted — fully one-sided

                elif self.signal < -0.5:
                    # Expect DOWN → want SHORT → tight ask, NO bid
                    if ts_ > 0:
                        to.append(Order("TOMATOES", ba - 1, -ts_))
                    if pos <= -60 and tb > 0:
                        to.append(Order("TOMATOES", bb + 1, tb))
                    # else: NO bid posted — fully one-sided

                else:
                    # Neutral — standard MM at best±1
                    # But skew based on FV deviation
                    if fv_dev > 0.5:
                        # FV above mid — favor buying
                        if tb > 0:
                            to.append(Order("TOMATOES", bb + 1, tb))
                        if ts_ > 0:
                            to.append(Order("TOMATOES", max(ba, bb + 2), -ts_))
                    elif fv_dev < -0.5:
                        # FV below mid — favor selling
                        if ts_ > 0:
                            to.append(Order("TOMATOES", ba - 1, -ts_))
                        if tb > 0:
                            to.append(Order("TOMATOES", min(bb, ba - 2), tb))
                    else:
                        if tb > 0:
                            to.append(Order("TOMATOES", bb + 1, tb))
                        if ts_ > 0:
                            to.append(Order("TOMATOES", ba - 1, -ts_))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps(
            {"c": self.mc, "f": self.tf, "w": self.ew, "pb": self.prev_bid, "sg": round(self.signal, 3)},
            separators=(",", ":")
        )
