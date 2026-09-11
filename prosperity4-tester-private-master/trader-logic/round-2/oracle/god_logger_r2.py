import json
from datamodel import Order, TradingState

"""
R2 GOD LOGGER — places zero orders, captures pristine market.

Submit with different bid() values to sample the 80% quote testing envelope.
Per R2 brief: testing always shows 80% regardless of bid(), so low/high bid
logs should be identical modulo per-submission randomization.

Each submission creates a different randomized 80% slice of the generated
data ("slightly randomized for every submission"). Run 3-5× to quantify
variance.

Bid strategy:
  - For low-bid probe: change bid() below to return 0
  - For high-bid probe: change bid() below to return 99999
  - Compare log files to verify testing is bid-insensitive.

Testing phase is free (brief: "ignored during testing, bids only compared
at final scoring"). Submit freely, but remember: the LAST submitted bid()
at end of round is what counts for the final auction.
"""

BID_VALUE = 0  # EDIT FOR EACH PROBE: 0 = low, 99999 = high


class Trader:
    def __init__(self):
        self.tick = 0

    def bid(self):
        return BID_VALUE

    def run(self, state: TradingState):
        # Compact state dump per tick: ts|product|bids|asks|mt|pos
        for product in state.order_depths:
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            bids = ",".join(f"{p}:{v}" for p, v in sorted(od.buy_orders.items(), reverse=True))
            asks = ",".join(f"{p}:{abs(v)}" for p, v in sorted(od.sell_orders.items()))
            mt = state.market_trades.get(product, [])
            mt_str = ",".join(f"{t.price}:{t.quantity}" for t in mt)
            print(f"GOD|{state.timestamp}|{product}|bid={bids}|ask={asks}|pos={pos}|mt={mt_str}")

        self.tick += 1
        return {}, 0, ""
