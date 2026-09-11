import json
from datamodel import Order, TradingState

"""
s3_carry.py — Maximum Mean-Reversion Carry Strategy

EXPLOIT: TOMATOES mid has -0.44 lag-1 autocorrelation (confirmed both days).
After a large bid UP (>=+4 ticks), the next 5 ticks give -5.72 mean reversion.
This is MASSIVE alpha if we can build position in the right direction.

DESIGN:
- Track recent price moves
- After large UP move: go maximally SHORT (post only asks, pull bids)
- After large DOWN move: go maximally LONG (post only bids, pull asks)
- Normal market: standard MM at best±1
- Position unwinding: when signal flips, aggressively take to reverse

The theoretical carry PnL is 25,190 per full day at 20-lot sizing.
Even at 5 lots it's 6,298. Our current 2,851 total might be beatable
just from carry alone if we size it right.

RISK: Carry PnL assumes we can reposition instantly. On the website,
we can only reposition via fills. So actual PnL will be lower.
But the DIRECTION is free alpha that we're currently leaving on the table.
"""


class Trader:
    def __init__(self):
        self.mc = []
        self.tf = []
        self.ew = []
        self.prev_bid = None
        self.signal = 0  # -1 = expect down, +1 = expect up, 0 = neutral

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
        conversions = 0

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

        # ═══ TOMATOES — CARRY-MAXIMIZING MM ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb = max(od.buy_orders)
                ba = min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (bb + ba) * 0.5

                # Fair value (same regression)
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

                # ─── DETECT LARGE MOVES (update directional signal) ───
                if self.prev_bid is not None:
                    bid_change = bb - self.prev_bid
                    if bid_change >= 4:
                        # Large UP move -> expect DOWN -> go SHORT
                        self.signal = -1
                    elif bid_change <= -4:
                        # Large DOWN move -> expect UP -> go LONG
                        self.signal = 1
                    elif abs(bid_change) <= 1:
                        # No big move -> decay signal toward neutral
                        self.signal = self.signal * 0.7
                self.prev_bid = bb

                tb = 80 - pos
                ts_ = 80 + pos

                # ─── PHASE 1: TAKE at fair (same as before) ───
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= tv:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts_ > 0 and p >= tv:
                        q = min(ts_, v); to.append(Order("TOMATOES", p, -q)); ts_ -= q

                # ─── PHASE 2: DIRECTIONAL POSTING ───
                # When signal is strong, post ONE-SIDED to build position
                # When signal is neutral, post BOTH SIDES normally

                signal_strength = abs(self.signal)

                if self.signal > 0.5:
                    # Expect UP -> want to be LONG -> post bids aggressively, minimal asks
                    if tb > 0:
                        # Aggressive bid: tight posting
                        bid_price = min(tv - 1, bb + 1)
                        bid_price = min(bid_price, ba - 1)
                        to.append(Order("TOMATOES", bid_price, tb))
                    # Post minimal ask (still need some to avoid getting stuck at limit)
                    if ts_ > 0 and pos >= 40:
                        ask_price = max(tv + 1, ba - 1)
                        ask_price = max(ask_price, bb + 1)
                        to.append(Order("TOMATOES", ask_price, -ts_))
                    elif ts_ > 0:
                        # Post ask at wider level (less likely to be hit)
                        ask_price = max(tv + 3, ba - 1)
                        ask_price = max(ask_price, bb + 1)
                        to.append(Order("TOMATOES", ask_price, -ts_))

                elif self.signal < -0.5:
                    # Expect DOWN -> want to be SHORT -> post asks aggressively, minimal bids
                    if ts_ > 0:
                        ask_price = max(tv + 1, ba - 1)
                        ask_price = max(ask_price, bb + 1)
                        to.append(Order("TOMATOES", ask_price, -ts_))
                    if tb > 0 and pos <= -40:
                        bid_price = min(tv - 1, bb + 1)
                        bid_price = min(bid_price, ba - 1)
                        to.append(Order("TOMATOES", bid_price, tb))
                    elif tb > 0:
                        bid_price = min(tv - 3, bb + 1)
                        bid_price = min(bid_price, ba - 1)
                        to.append(Order("TOMATOES", bid_price, tb))

                else:
                    # Neutral: standard MM at best±1
                    if tb > 0:
                        bid_price = min(tv - 1, bb + 1)
                        bid_price = min(bid_price, ba - 1)
                        to.append(Order("TOMATOES", bid_price, tb))
                    if ts_ > 0:
                        ask_price = max(tv + 1, ba - 1)
                        ask_price = max(ask_price, bb + 1)
                        to.append(Order("TOMATOES", ask_price, -ts_))

                orders["TOMATOES"] = to

        return orders, conversions, json.dumps(
            {"c": self.mc, "f": self.tf, "w": self.ew, "pb": self.prev_bid, "sg": round(self.signal, 3)},
            separators=(",", ":")
        )
