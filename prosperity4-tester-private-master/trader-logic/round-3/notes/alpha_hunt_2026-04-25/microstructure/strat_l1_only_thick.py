"""Thick L1 only: post bid at best+1 and ask at best-1, SIZE=15 per side.
Tests fill rate at L1 with serious size to compare against multi-level distribution.
"""
from datamodel import Order, TradingState

LIMITS = {"HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200}
VOUCHER_LIMIT = 300

class Trader:
    def bid(self): return 15
    def run(self, state: TradingState):
        orders = {}
        SIZE = 15
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                continue
            bb = max(od.buy_orders.keys()); ba = min(od.sell_orders.keys())
            if ba - bb < 2: continue
            limit = LIMITS.get(product, VOUCHER_LIMIT)
            pos = state.position.get(product, 0)
            buy_room = limit - pos; sell_room = limit + pos
            o = []
            if buy_room > 0: o.append(Order(product, bb + 1, min(SIZE, buy_room)))
            if sell_room > 0: o.append(Order(product, ba - 1, -min(SIZE, sell_room)))
            if o: orders[product] = o
        return orders, 0, ""
