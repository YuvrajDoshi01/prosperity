import json
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict, Any

"""
s3_wallmid_regime: Wall Mid + Spread-Regime Adaptive

Hypothesis: Tight spread windows (5-9 ticks, 7.2% of time) are opportunities.
Taker tax drops from ~6.5 to ~3 ticks → taking becomes profitable.
Normal spread: standard MM. Tight spread: more aggressive posting.

Fair value: Wall Mid (zero params)
Spread threshold: 10 (structural — half normal spread of 13)
"""


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

        # Wall Mid
        wall_bid = max(od.buy_orders.items(), key=lambda x: x[1])[0]
        wall_ask = max(od.sell_orders.items(), key=lambda x: abs(x[1]))[0]
        tv = round((wall_bid + wall_ask) / 2)

        best_bid, best_ask = buys[0][0], sells[0][0]
        spread = best_ask - best_bid
        pos = state.position.get(self.symbol, 0)
        to_buy = self.limit - pos
        to_sell = self.limit + pos

        # TAKE at/below fair (same in both regimes)
        for p, v in sells:
            if to_buy > 0 and p <= tv:
                q = min(to_buy, -v)
                self.buy(p, q)
                to_buy -= q

        for p, v in buys:
            if to_sell > 0 and p >= tv:
                q = min(to_sell, v)
                self.sell(p, q)
                to_sell -= q

        # MAKE: regime-dependent posting
        if spread < 10:
            # TIGHT REGIME: taker tax is low, be more aggressive
            # Post at fair±1 (tighter than best±1) to maximize fill rate
            # when the spread is narrow
            bid_price = tv - 1
            ask_price = tv + 1
            # But never cross the spread
            bid_price = min(bid_price, best_ask - 1)
            ask_price = max(ask_price, best_bid + 1)
        else:
            # NORMAL REGIME: standard best±1 posting
            bid_price = min(tv - 1, best_bid + 1)
            bid_price = min(bid_price, best_ask - 1)
            ask_price = max(tv + 1, best_ask - 1)
            ask_price = max(ask_price, best_bid + 1)

        if to_buy > 0:
            self.buy(int(bid_price), to_buy)

        if to_sell > 0:
            self.sell(int(ask_price), to_sell)


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
