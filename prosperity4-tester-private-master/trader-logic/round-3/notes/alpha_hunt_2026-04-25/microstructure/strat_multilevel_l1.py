"""Baseline: post L1 only at best+1 / best-1 with size 5 per side per product.

Tests on HP, VFE, all vouchers. No trader_data state. Default mode.
"""
import json
from datamodel import Order, TradingState

LIMITS = {"HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200}
VOUCHER_LIMIT = 300

class Trader:
    def bid(self):
        return 15

    def run(self, state: TradingState):
        orders = {}
        SIZE = 5
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            if best_ask - best_bid < 2:
                continue
            limit = LIMITS.get(product, VOUCHER_LIMIT)
            pos = state.position.get(product, 0)
            buy_room = limit - pos
            sell_room = limit + pos
            o = []
            if buy_room > 0:
                o.append(Order(product, best_bid + 1, min(SIZE, buy_room)))
            if sell_room > 0:
                o.append(Order(product, best_ask - 1, -min(SIZE, sell_room)))
            if o:
                orders[product] = o
        return orders, 0, ""
