"""L1 (best+1) + L2 (best+2) simultaneous, both SIZE=15. Tests stacking benefit."""
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
            buy_room = limit - pos; sell_room = limit + pos
            o = []
            for k in (1, 2):
                if buy_room >= SIZE:
                    o.append(Order(product, bb + k, SIZE)); buy_room -= SIZE
                if sell_room >= SIZE:
                    o.append(Order(product, ba - k, -SIZE)); sell_room -= SIZE
            if o: orders[product] = o
        return orders, 0, ""
