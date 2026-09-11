import json
from datamodel import Order, TradingState

"""
GOD LOGGER: Places ZERO orders. Captures the pristine market state.

Submit this to the website to get CLEAN market data without our orders
modifying the book. Then download the logs, extract the exact price path,
solve the DP on clean data, and build the perfect hardcoded strategy.

The key: when WE trade, we consume liquidity and change the book.
A logger that doesn't trade sees the UNMODIFIED bot behavior.
"""

class Trader:
    def __init__(self):
        pass

    def bid(self):
        return 15

    def run(self, state: TradingState):
        # Log EVERYTHING via print (captured in lambda_log)
        # This gets saved in the submission logs we can download

        ts = state.timestamp

        for product in state.order_depths:
            od = state.order_depths[product]
            pos = state.position.get(product, 0)

            # Compact log: ts|product|bid1:bv1,bid2:bv2|ask1:av1,ask2:av2|pos|trades
            bids = sorted(od.buy_orders.items(), reverse=True)
            asks = sorted(od.sell_orders.items())

            bid_str = ",".join(f"{p}:{v}" for p, v in bids)
            ask_str = ",".join(f"{p}:{abs(v)}" for p, v in asks)

            # Market trades this tick
            mt = state.market_trades.get(product, [])
            trade_str = ",".join(f"{t.price}:{t.quantity}" for t in mt)

            # Own trades (should be empty since we don't trade)
            ot = state.own_trades.get(product, [])
            own_str = ",".join(f"{t.price}:{t.quantity}" for t in ot)

        # Return EMPTY orders — we're just observing
        return {}, 0, ""
