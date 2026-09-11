import json
from datamodel import Order, TradingState

"""
MAX LOSS: Deliberately crosses the spread at maximum size every tick.

Buy at best ask (overpay) and sell at best bid (undersell) with full position capacity.
Flips position every tick to maximize spread-crossing cost.

Purpose: calibration — compare website loss vs backtester loss to validate matching model.
Expected: -50K to -100K per day.
"""


class Trader:
    def bid(self):
        return 15

    def run(self, state: TradingState):
        orders = {}

        for product in state.order_depths:
            od = state.order_depths[product]
            if not od.buy_orders or not od.sell_orders:
                continue

            pos = state.position.get(product, 0)
            limit = 80
            bb = max(od.buy_orders)
            ba = min(od.sell_orders)
            o = []

            # BUY at worst price (best ask) — overpay
            buy_cap = limit - pos
            if buy_cap > 0:
                for p, v in sorted(od.sell_orders.items()):
                    if buy_cap > 0:
                        q = min(buy_cap, -v)
                        o.append(Order(product, p, q))
                        buy_cap -= q

            # SELL at worst price (best bid) — undersell
            sell_cap = limit + pos
            if sell_cap > 0:
                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if sell_cap > 0:
                        q = min(sell_cap, v)
                        o.append(Order(product, p, -q))
                        sell_cap -= q

            orders[product] = o

        return orders, 0, ""
