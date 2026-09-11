from typing import List
from sortedcontainers import SortedKeyList
from datamodel import OrderDepth, Order, Trade


class OrderBook:
    def __init__(self, symbol) -> None:
        self.symbol = symbol
        self.buy_orders: SortedKeyList = SortedKeyList([], lambda order: -order.price)
        self.sell_orders: SortedKeyList = SortedKeyList([], lambda order: order.price)
        self.order_depth = OrderDepth()

    def add(self, orders: List[Order]):
        for o in orders:
            if o.quantity > 0:
                self.buy_orders.add(o)
                self.order_depth.buy_orders.setdefault(o.price, 0)
                self.order_depth.buy_orders[o.price] += o.quantity
            else:
                self.sell_orders.add(o)
                self.order_depth.sell_orders.setdefault(o.price, 0)
                self.order_depth.sell_orders[o.price] += o.quantity

        best_bid: Order
        best_ask: Order
        trades = []

        while len(self.buy_orders) > 0 \
                and len(self.sell_orders) > 0 \
                and self.buy_orders[0].price == self.sell_orders[0].price:
            best_bid = self.buy_orders[0]
            best_ask = self.sell_orders[0]
            price = best_bid.price
            trade_quantity = min(best_bid.quantity, -best_ask.quantity)

            trades.append(Trade(self.symbol, price, trade_quantity, best_bid.user_id, best_ask.user_id))

            best_bid.quantity -= trade_quantity
            best_ask.quantity += trade_quantity
            self.order_depth.buy_orders[price] -= trade_quantity
            self.order_depth.sell_orders[price] += trade_quantity

            if self.order_depth.buy_orders[price] == 0:
                self.order_depth.buy_orders.pop(price)
            if self.order_depth.sell_orders[price] == 0:
                self.order_depth.sell_orders.pop(price)

            if best_bid.quantity == 0:
                self.buy_orders.pop(0)
            if best_ask.quantity == 0:
                self.sell_orders.pop(0)

        return trades
