"""Multi-level: post simultaneously at best+1, best+2, best+3 (and mirror on ask).

Tests if L2/L3 posts capture additional flow. SIZE=3 per level per side.
Total per-side commit = 9 (so per-product two-side commit 18; well under HP/VFE 200 and voucher 300).
"""
from datamodel import Order, TradingState

LIMITS = {"HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200}
VOUCHER_LIMIT = 300

class Trader:
    def bid(self): return 15

    def run(self, state: TradingState):
        orders = {}
        SIZE = 3
        for product, od in state.order_depths.items():
            if not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            if best_ask - best_bid < 6:  # need spread≥6 for 3 levels each side
                continue
            limit = LIMITS.get(product, VOUCHER_LIMIT)
            pos = state.position.get(product, 0)
            buy_total = SIZE * 3
            sell_total = SIZE * 3
            buy_room = limit - pos
            sell_room = limit + pos
            if buy_total > buy_room: buy_total = max(0, buy_room)
            if sell_total > sell_room: sell_total = max(0, sell_room)
            o = []
            for k in range(1, 4):
                if buy_total >= SIZE:
                    o.append(Order(product, best_bid + k, SIZE))
                    buy_total -= SIZE
                if sell_total >= SIZE:
                    o.append(Order(product, best_ask - k, -SIZE))
                    sell_total -= SIZE
            if o:
                orders[product] = o
        return orders, 0, ""
