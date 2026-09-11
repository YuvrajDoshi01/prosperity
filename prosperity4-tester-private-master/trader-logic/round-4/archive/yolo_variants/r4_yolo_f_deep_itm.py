"""r4_yolo_f_deep_itm.py — Candidate F: short ONLY deep ITM (4000/4500/5100/5200).
Highest delta strikes capture VFE drop most directly. Theoretical ~$45k from these 4."""
import json
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

TARGETS = {"VEV_4000": -300, "VEV_4500": -300, "VEV_5100": -300, "VEV_5200": -300}

class Trader:
    def bid(self): return 15
    def run(self, state: TradingState):
        orders = {}
        for sym, target in TARGETS.items():
            pos = state.position.get(sym, 0)
            od = state.order_depths.get(sym)
            if not od or not od.buy_orders: continue
            qty = pos - target
            if qty <= 0: continue
            sell_levels = sorted(od.buy_orders.keys(), reverse=True)
            ords = []
            rem = qty
            for px in sell_levels:
                if rem <= 0: break
                take = min(rem, od.buy_orders[px])
                if take > 0:
                    ords.append(Order(sym, px, -take))
                    rem -= take
            if rem > 0 and sell_levels:
                ords.append(Order(sym, sell_levels[0], -rem))
            if ords: orders[sym] = ords
        logger.flush(state, orders, 0, "")
        return orders, 0, ""
