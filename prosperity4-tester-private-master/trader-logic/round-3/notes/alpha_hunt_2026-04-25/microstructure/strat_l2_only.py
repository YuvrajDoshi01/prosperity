"""L2 only: post at best+2 / best-2 SIZE=15 per side. Isolates L2 fills to verify they exist.
"""
from datamodel import Order, TradingState
LIMITS = {"HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200}
VOUCHER_LIMIT = 300
class Trader:
    def bid(self): return 15
    def run(self, state):
        orders = {}; SIZE = 15
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders: continue
            bb = max(od.buy_orders.keys()); ba = min(od.sell_orders.keys())
            if ba - bb < 4: continue
            limit = LIMITS.get(product, VOUCHER_LIMIT)
            pos = state.position.get(product, 0)
            o = []
            if limit - pos > 0: o.append(Order(product, bb + 2, min(SIZE, limit - pos)))
            if limit + pos > 0: o.append(Order(product, ba - 2, -min(SIZE, limit + pos)))
            if o: orders[product] = o
        return orders, 0, ""
