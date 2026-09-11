import json
from datamodel import Order, TradingState

"""
diag_conversions.py — DIAGNOSTIC: Test if conversions work for EMERALDS
PURPOSE: Return conversions=1 and see if PnL changes.
If EMERALDS has a conversion at 10000, buying at 9992 and converting = 8 profit/lot.
"""

class Trader:
    def __init__(self):
        pass

    def bid(self):
        return 15

    def run(self, state: TradingState):
        orders = {}
        conversions = 0

        for product in state.order_depths:
            od = state.order_depths[product]
            if not od.buy_orders or not od.sell_orders:
                continue

            pos = state.position.get(product, 0)
            bb = max(od.buy_orders)
            ba = min(od.sell_orders)

            if product == "EMERALDS":
                # Strategy: buy at MM's bid, convert at 10000, pocket the diff
                # Also try returning conversions > 0
                eo = []
                tb = 80 - pos
                ts_ = 80 + pos

                # Take anything below 10000
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p < 10000:
                        q = min(tb, -v)
                        eo.append(Order(product, p, q))
                        tb -= q

                # Post aggressive bid at 9999
                if tb > 0:
                    eo.append(Order(product, min(9999, bb + 1), tb))

                # Take anything above 10000
                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts_ > 0 and p > 10000:
                        q = min(ts_, v)
                        eo.append(Order(product, p, -q))
                        ts_ -= q

                # Post aggressive ask at 10001
                if ts_ > 0:
                    eo.append(Order(product, max(10001, ba - 1), -ts_))

                orders[product] = eo

                # TRY CONVERSION: positive = buy via conversion, negative = sell
                # If position > 0, try to convert (sell) to lock profit
                if pos > 0:
                    conversions = pos  # convert all long position

            elif product == "TOMATOES":
                # Simple MM for TOMATOES (don't optimize, just baseline)
                to = []
                tb = 80 - pos
                ts_ = 80 + pos
                mid = (bb + ba) / 2.0
                tv = round(mid)

                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= tv:
                        q = min(tb, -v); to.append(Order(product, p, q)); tb -= q
                if tb > 0:
                    to.append(Order(product, min(tv - 1, bb + 1), tb))

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts_ > 0 and p >= tv:
                        q = min(ts_, v); to.append(Order(product, p, -q)); ts_ -= q
                if ts_ > 0:
                    to.append(Order(product, max(tv + 1, ba - 1), -ts_))

                orders[product] = to

        return orders, conversions, ""
