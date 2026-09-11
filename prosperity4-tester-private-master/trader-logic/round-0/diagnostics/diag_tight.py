import json
from datamodel import Order, TradingState

"""
diag_tight.py — DIAGNOSTIC: Post at mid±3 (tight, inside MM spread)
PURPOSE: Compare fill count on WEBSITE vs historical.
If fills > 84 per 2k ticks, bots react to our presence.
"""

class Trader:
    def __init__(self):
        self.fill_count = {"TOMATOES": 0, "EMERALDS": 0}

    def bid(self):
        return 15

    def run(self, state: TradingState):
        # Count fills
        for product in state.own_trades:
            self.fill_count[product] = self.fill_count.get(product, 0) + len(state.own_trades[product])

        orders = {}

        for product in state.order_depths:
            od = state.order_depths[product]
            if not od.buy_orders or not od.sell_orders:
                continue

            bb = max(od.buy_orders)
            ba = min(od.sell_orders)
            mid = (bb + ba) / 2.0
            pos = state.position.get(product, 0)

            if product == "TOMATOES":
                WIDTH = 3
                our_bid = round(mid) - WIDTH
                our_ask = round(mid) + WIDTH
                # Don't cross
                our_bid = min(our_bid, ba - 1)
                our_ask = max(our_ask, bb + 1)

                to = []
                tb = 80 - pos
                ts_ = 80 + pos

                # Take anything at or below fair
                tv = round(mid)
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= tv:
                        q = min(tb, -v); to.append(Order(product, p, q)); tb -= q

                if tb > 0:
                    to.append(Order(product, our_bid, tb))

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts_ > 0 and p >= tv:
                        q = min(ts_, v); to.append(Order(product, p, -q)); ts_ -= q

                if ts_ > 0:
                    to.append(Order(product, our_ask, -ts_))

                orders[product] = to

            elif product == "EMERALDS":
                eo = []
                tb = 80 - pos
                ts_ = 80 + pos
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= 10000:
                        q = min(tb, -v); eo.append(Order(product, p, q)); tb -= q
                if tb > 0:
                    eo.append(Order(product, min(9999, bb + 1), tb))
                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts_ > 0 and p >= 10000:
                        q = min(ts_, v); eo.append(Order(product, p, -q)); ts_ -= q
                if ts_ > 0:
                    eo.append(Order(product, max(10001, ba - 1), -ts_))
                orders[product] = eo

        # Print fill counts periodically
        if state.timestamp % 50000 == 0 and state.timestamp > 0:
            print(f"t={state.timestamp} fills={self.fill_count}")

        return orders, 0, ""
