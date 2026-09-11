import json
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict, Any

"""
s2_fastflip: Wall Mid + Soft Position Limit

Hypothesis: Smaller effective limit = faster inventory turnover = more round-trips.
valentinz scored 2.6k with effective limit 15-20.
TOMATOES mean-reverts (autocorr -0.43) → large positions are risky, fast flipping is optimal.

Fair value: Wall Mid (zero params)
Soft limit: 25 (only maintain positions up to ±25, not ±80)
Take at fair, post at best±1. Zero skew, zero fitted params.
"""

SOFT_LIMIT = 25  # Effective position cap (hard limit is still 80)


class Strategy:
    def __init__(self, symbol: str, limit: int):
        self.symbol = symbol
        self.limit = limit

    def act(self, state: TradingState):
        raise NotImplementedError()

    def run(self, state: TradingState) -> List[Order]:
        self.orders = []
        self.act(state)
        return self.orders

    def buy(self, price: int, qty: int):
        if qty > 0:
            self.orders.append(Order(self.symbol, price, qty))

    def sell(self, price: int, qty: int):
        if qty > 0:
            self.orders.append(Order(self.symbol, price, -qty))

    def save(self) -> Any:
        return None

    def load(self, data: Any):
        pass


class EmeraldsStrategy(Strategy):
    def act(self, state: TradingState):
        od = state.order_depths[self.symbol]
        buys = sorted(od.buy_orders.items(), reverse=True)
        sells = sorted(od.sell_orders.items())
        if not buys or not sells:
            return

        tv = 10000
        pos = state.position.get(self.symbol, 0)
        to_buy = self.limit - pos
        to_sell = self.limit + pos

        for p, v in sells:
            if to_buy > 0 and p <= tv:
                q = min(to_buy, -v)
                self.buy(p, q)
                to_buy -= q

        if to_buy > 0:
            self.buy(min(tv - 1, buys[0][0] + 1), to_buy)

        for p, v in buys:
            if to_sell > 0 and p >= tv:
                q = min(to_sell, v)
                self.sell(p, q)
                to_sell -= q

        if to_sell > 0:
            self.sell(max(tv + 1, sells[0][0] - 1), to_sell)


class TomatoesStrategy(Strategy):
    def act(self, state: TradingState):
        od = state.order_depths[self.symbol]
        buys = sorted(od.buy_orders.items(), reverse=True)
        sells = sorted(od.sell_orders.items())
        if not buys or not sells:
            return

        # Wall Mid: midpoint of highest-volume bid and ask
        wall_bid = max(od.buy_orders.items(), key=lambda x: x[1])[0]
        wall_ask = max(od.sell_orders.items(), key=lambda x: abs(x[1]))[0]
        tv = round((wall_bid + wall_ask) / 2)

        pos = state.position.get(self.symbol, 0)

        # Soft limit: only use capacity up to ±SOFT_LIMIT
        # But still respect the hard limit for order validation
        to_buy = min(SOFT_LIMIT - pos, self.limit - pos)
        to_sell = min(SOFT_LIMIT + pos, self.limit + pos)
        to_buy = max(0, to_buy)
        to_sell = max(0, to_sell)

        # TAKE at/below fair
        for p, v in sells:
            if to_buy > 0 and p <= tv:
                q = min(to_buy, -v)
                self.buy(p, q)
                to_buy -= q

        if to_buy > 0:
            self.buy(min(tv - 1, buys[0][0] + 1), to_buy)

        for p, v in buys:
            if to_sell > 0 and p >= tv:
                q = min(to_sell, v)
                self.sell(p, q)
                to_sell -= q

        if to_sell > 0:
            self.sell(max(tv + 1, sells[0][0] - 1), to_sell)


class Trader:
    def __init__(self):
        self.strategies = {
            "EMERALDS": EmeraldsStrategy("EMERALDS", 80),
            "TOMATOES": TomatoesStrategy("TOMATOES", 80),
        }

    def bid(self):
        return 15

    def run(self, state: TradingState):
        old_td = json.loads(state.traderData) if state.traderData != "" else {}
        new_td, orders = {}, {}
        for sym, strat in self.strategies.items():
            if sym in old_td:
                strat.load(old_td.get(sym))
            if sym in state.order_depths:
                orders[sym] = strat.run(state)
            new_td[sym] = strat.save()
        return orders, 0, json.dumps(new_td, separators=(",", ":"))
