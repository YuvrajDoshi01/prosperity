"""L1 SIZE=60. Saturation test."""
from datamodel import Order, TradingState
LIMITS = {"HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200}
VOUCHER_LIMIT = 300
class Trader:
    def bid(self): return 15
    def run(self, state):
        orders = {}; SIZE = 60
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders: continue
            bb = max(od.buy_orders.keys()); ba = min(od.sell_orders.keys())
            if ba - bb < 2: continue
            limit = LIMITS.get(product, VOUCHER_LIMIT)
            pos = state.position.get(product, 0)
            o = []; br = limit - pos; sr = limit + pos
            if br > 0: o.append(Order(product, bb + 1, min(SIZE, br)))
            if sr > 0: o.append(Order(product, ba - 1, -min(SIZE, sr)))
            if o: orders[product] = o
        return orders, 0, ""
