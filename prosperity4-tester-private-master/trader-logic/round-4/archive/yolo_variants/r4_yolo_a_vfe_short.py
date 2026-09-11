"""r4_yolo_a_vfe_short.py — Candidate A: VFE max short, no TP.
Hold -200 VFE entire 1k probe. Theoretical ceiling +$8,400."""
import json
from typing import Any
from datamodel import Order, ProsperityEncoder, TradingState

class Logger:
    def __init__(self): self.logs = ""
    def print(self, *o, sep=" ", end="\n"): self.logs += sep.join(map(str, o)) + end
    def flush(self, state, orders, conv, td):
        print(json.dumps([self._cs(state), [[o.symbol, o.price, o.quantity] for a in orders.values() for o in a],
                          conv, td, self.logs], cls=ProsperityEncoder, separators=(",", ":")))
        self.logs = ""
    def _cs(self, s): return [s.timestamp, s.traderData,
        [[l.symbol, l.product, l.denomination] for l in s.listings.values()],
        {sy: [od.buy_orders, od.sell_orders] for sy, od in s.order_depths.items()},
        self._ct(s.own_trades), self._ct(s.market_trades), s.position, [{}, {}]]
    def _ct(self, t): return [[x.symbol, x.price, x.quantity, x.buyer, x.seller, x.timestamp]
                              for a in t.values() for x in a]
logger = Logger()

class Trader:
    def bid(self): return 15
    def run(self, state: TradingState):
        orders = {}
        VFE = "VELVETFRUIT_EXTRACT"
        pos = state.position.get(VFE, 0)
        od = state.order_depths.get(VFE)
        if od and od.buy_orders:
            best_bid = max(od.buy_orders.keys())
            target = -200
            qty = pos - target  # how many to sell (positive)
            if qty > 0:
                # Aggressive: sell at best_bid (cross), walk down levels
                sell_levels = sorted(od.buy_orders.keys(), reverse=True)
                ords = []
                rem = qty
                for px in sell_levels:
                    if rem <= 0: break
                    avail = od.buy_orders[px]
                    take = min(rem, avail)
                    if take > 0:
                        ords.append(Order(VFE, px, -take))
                        rem -= take
                # Also rest at best_bid for any remaining
                if rem > 0:
                    ords.append(Order(VFE, best_bid, -rem))
                if ords:
                    orders[VFE] = ords
        logger.flush(state, orders, 0, "")
        return orders, 0, ""
