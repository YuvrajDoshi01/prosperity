import json
from datamodel import Order, TradingState

"""
s28_inside_mm: Inside Market-Making for TOMATOES + Proven Taking

Posts INSIDE the MM bot's 13-14 tick spread to intercept taker flow.
Earns spread instead of paying it. Combines with proven taking from s25.

Key insight: MM bot quotes at ±7 from mid. Taker is 100% price-insensitive
(hits best bid/ask). Post 1 tick inside MM → intercept ALL taker flow.
"""

# === TOMATOES MM Parameters ===
OFFSET = 7           # At MM's half-spread boundary; tighter adds inside alpha
BUFFER = 0           # Full capacity for both takes and posts
SKEW_FACTOR = 0.0    # No inventory skew (taker uninformed, skew hurts -62)
MAX_SKEW = 0         # Disabled

# === TOMATOES Regression (cross-validated from s25) ===
INTERCEPT = 7.388073
COEFS = [0.059509, 0.117116, 0.243910, 0.577988]
FLOW_COEF = 0.0      # Trade flow irrelevant for MM posting (sweep: F0 = F0.5 = F1.0)
FLOW_WINDOW = 5


class Trader:
    def __init__(self):
        self.tc = []      # microprice lag buffer
        self.tf = []      # trade flow buffer
        self.ew = []      # EMERALDS limit flags

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])
            self.ew = td.get("ew", [])

        orders = {}

        # ═══════════════════════════════════════════════════════════════
        # EMERALDS — Proven liquidation logic from s25 (unchanged)
        # ═══════════════════════════════════════════════════════════════
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

        # ═══════════════════════════════════════════════════════════════
        # TOMATOES — Inside MM + Taking
        # ═══════════════════════════════════════════════════════════════
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb = max(od.buy_orders)
                ba = min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)

                # --- Step 1: Compute Fair Value (FIRST, before any orders) ---
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) * 0.5

                c = self.tc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.tc = c

                if len(c) == 4:
                    fv = INTERCEPT + sum(co * lag for co, lag in zip(COEFS, c))
                else:
                    fv = mp

                # Trade flow adjustment
                trades = state.market_trades.get("TOMATOES")
                if trades:
                    mid = (bb + ba) * 0.5
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > FLOW_WINDOW: self.tf = self.tf[-FLOW_WINDOW:]
                fs = max(-1.0, min(1.0, sum(self.tf) / 15.0))
                fv -= fs * FLOW_COEF

                tv = round(fv)

                # --- Step 2: Aggressive Takes FIRST (full capacity, proven from s25) ---
                tb = 80 - pos  # total buy capacity
                ts = 80 + pos  # total sell capacity

                # Position aggression on takes (from s25)
                take_bid = tv - 1 if pos > 40 else tv
                take_ask = tv + 1 if pos < -40 else tv

                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= take_bid:
                        q = min(tb, -v)
                        to.append(Order("TOMATOES", p, q))
                        tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= take_ask:
                        q = min(ts, v)
                        to.append(Order("TOMATOES", p, -q))
                        ts -= q

                # --- Step 3: Inside MM Posting with REMAINING capacity ---
                skew = max(-MAX_SKEW, min(MAX_SKEW, -pos * SKEW_FACTOR))
                skewed_mid = round(fv + skew)

                # Post with whatever capacity is left after taking
                bid_size = tb  # already reduced by takes above
                ask_size = ts

                # Post inside the MM spread
                bid_price = max(skewed_mid - OFFSET, bb + 1)
                ask_price = min(skewed_mid + OFFSET, ba - 1)

                # Ensure we don't cross ourselves
                if bid_price >= ask_price:
                    mid_point = (bid_price + ask_price) // 2
                    bid_price = mid_point - 1
                    ask_price = mid_point + 1

                if bid_size > 0:
                    to.append(Order("TOMATOES", int(bid_price), bid_size))
                if ask_size > 0:
                    to.append(Order("TOMATOES", int(ask_price), -ask_size))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({"c": self.tc, "f": self.tf, "ew": self.ew}, separators=(",", ":"))
