import json
from datamodel import Order, TradingState

"""
template_stable.py — Market making for a stable/pegged product.
Proven EMERALDS logic from s25_training_only.

Strategy:
  - Take at/below fair value, post at best +/- 1
  - Liquidation tracking (10-tick window): soft = 5/10 ticks at limit,
    hard = 10/10 ticks at limit -> increasingly aggressive quotes to unwind
  - Position aggression: widen by 1 when pos > LIMIT * 0.5

UPDATE CHECKLIST when Round 1 data drops:
  1. Change PRODUCT to the actual symbol name
  2. Change FAIR_VALUE to the peg value visible in sample data
  3. Change LIMIT to the position limit from the spec
  4. Verify take/post offsets still make sense at the new price scale
"""

# ═══ CONFIG — UPDATE THESE ═══
PRODUCT = "RAINFOREST_RESIN"  # UPDATE: actual product symbol
FAIR_VALUE = 10000             # UPDATE: check the peg value from sample data
LIMIT = 80                     # UPDATE: check position limit


class Trader:
    def __init__(self):
        # ew = "at-limit" window for liquidation tracking
        self.ew = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        # ── Restore state ──
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.ew = td.get("w", [])

        orders = {}

        if PRODUCT in state.order_depths:
            od = state.order_depths[PRODUCT]
            if od.buy_orders and od.sell_orders:
                result = []
                pos = state.position.get(PRODUCT, 0)

                # Room to buy / sell before hitting limit
                tb = LIMIT - pos   # total buy capacity
                ts = LIMIT + pos   # total sell capacity

                buys = sorted(od.buy_orders.items(), reverse=True)
                sells = sorted(od.sell_orders.items())

                # ── Liquidation tracking (10-tick window) ──
                # Tracks whether we are stuck at the position limit
                self.ew.append(abs(pos) == LIMIT)
                if len(self.ew) > 10:
                    self.ew = self.ew[-10:]

                # soft: at limit >= 5 of last 10 ticks AND currently at limit
                soft = len(self.ew) == 10 and sum(self.ew) >= 5 and self.ew[-1]
                # hard: at limit every single tick for the last 10 ticks
                hard = len(self.ew) == 10 and all(self.ew)

                # ── BUY SIDE ──
                # 1) Take any asks at or below fair value
                for p, v in sells:
                    if tb > 0 and p <= FAIR_VALUE:
                        q = min(tb, -v)
                        result.append(Order(PRODUCT, p, q))
                        tb -= q

                # 2) Hard liquidation: quote AT fair to unwind faster
                if tb > 0 and hard:
                    q = tb // 2
                    result.append(Order(PRODUCT, FAIR_VALUE, q))
                    tb -= q

                # 3) Soft liquidation: quote 2 below fair
                if tb > 0 and soft:
                    q = tb // 2
                    result.append(Order(PRODUCT, FAIR_VALUE - 2, q))
                    tb -= q

                # 4) Passive post: best bid + 1, but never above fair - 1
                if tb > 0:
                    post_price = min(FAIR_VALUE - 1, buys[0][0] + 1)
                    result.append(Order(PRODUCT, post_price, tb))

                # ── SELL SIDE ──
                # 1) Take any bids at or above fair value
                for p, v in buys:
                    if ts > 0 and p >= FAIR_VALUE:
                        q = min(ts, v)
                        result.append(Order(PRODUCT, p, -q))
                        ts -= q

                # 2) Hard liquidation: quote AT fair to unwind faster
                if ts > 0 and hard:
                    q = ts // 2
                    result.append(Order(PRODUCT, FAIR_VALUE, -q))
                    ts -= q

                # 3) Soft liquidation: quote 2 above fair
                if ts > 0 and soft:
                    q = ts // 2
                    result.append(Order(PRODUCT, FAIR_VALUE + 2, -q))
                    ts -= q

                # 4) Passive post: best ask - 1, but never below fair + 1
                if ts > 0:
                    post_price = max(FAIR_VALUE + 1, sells[0][0] - 1)
                    result.append(Order(PRODUCT, post_price, -ts))

                orders[PRODUCT] = result

        return orders, 0, json.dumps({
            "w": self.ew,
        }, separators=(",", ":"))
