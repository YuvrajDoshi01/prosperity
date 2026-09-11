import json
from datamodel import Order, TradingState

"""
s20_directional_only: s2_tradeflow + ONLY the directional posting from s3_carry

Isolates JUST the directional signal/posting change:
- After bid_change >= +4: expect down, widen bid to tv-3 (less buying on continuation)
- After bid_change <= -4: expect up, widen ask to tv+3 (less selling on continuation)
- Decay signal by 0.7 each tick

KEEPS: liquidation tracking, position-dependent aggression (both proven to help)
This tests if the directional posting alone adds the +6.
"""

class Trader:
    def __init__(self):
        self.tc = []
        self.tf = []
        self.tw = []
        self.ew = []
        self.prev_bid = None
        self.signal = 0

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])
            self.tw = td.get("tw", [])
            self.ew = td.get("ew", [])
            self.prev_bid = td.get("pb")
            self.signal = td.get("sg", 0)

        orders = {}

        # ═══ EMERALDS (standard with liquidation + pos aggression) ═══
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

        # ═══ TOMATOES (tradeflow + directional posting + KEEP liquidation + pos aggression) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, ts = 80 - pos, 80 + pos
                mid = (bb + ba) * 0.5

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

                # Directional signal from s3_carry
                if self.prev_bid is not None:
                    bid_change = bb - self.prev_bid
                    if bid_change >= 4:
                        self.signal = -1
                    elif bid_change <= -4:
                        self.signal = 1
                    elif abs(bid_change) <= 1:
                        self.signal *= 0.7
                self.prev_bid = bb

                # Liquidation tracking (KEPT from s2_tradeflow)
                self.tw.append(abs(pos) == 80)
                if len(self.tw) > 10: self.tw = self.tw[-10:]
                soft = len(self.tw) == 10 and sum(self.tw) >= 5 and self.tw[-1]
                hard = len(self.tw) == 10 and all(self.tw)

                # Position aggression (KEPT)
                mbp = tv - 1 if pos > 40 else tv
                msp = tv + 1 if pos < -40 else tv

                # TAKE (standard with pos aggression)
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

                # POST: directional (wider on continuation side when biased)
                if self.signal > 0.5:
                    # Expect UP → tight bid, wider ask
                    if tb > 0:
                        to.append(Order("TOMATOES", min(mbp, bb + 1), tb))
                    if ts > 0:
                        ask_price = max(tv + 3, ba - 1)
                        ask_price = max(ask_price, bb + 1)
                        to.append(Order("TOMATOES", ask_price, -ts))
                elif self.signal < -0.5:
                    # Expect DOWN → wider bid, tight ask
                    if tb > 0:
                        bid_price = min(tv - 3, bb + 1)
                        bid_price = min(bid_price, ba - 1)
                        to.append(Order("TOMATOES", bid_price, tb))
                    if ts > 0:
                        to.append(Order("TOMATOES", max(msp, ba - 1), -ts))
                else:
                    # Neutral: standard best±1
                    if tb > 0:
                        to.append(Order("TOMATOES", min(mbp, bb + 1), tb))
                    if ts > 0:
                        to.append(Order("TOMATOES", max(msp, ba - 1), -ts))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({
            "c": self.tc, "f": self.tf, "tw": self.tw, "ew": self.ew,
            "pb": self.prev_bid, "sg": round(self.signal, 3)
        }, separators=(",", ":"))
