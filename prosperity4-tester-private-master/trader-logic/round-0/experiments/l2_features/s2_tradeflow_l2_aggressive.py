import json
from abc import abstractmethod
from collections import deque
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict

"""
s2_tradeflow_l2_aggressive: s2_tradeflow + L2 imbalance with FULL regression coefficient

Same as s1_tradeflow_l2 but with L2_COEF = 0.23 (full regression coefficient)
instead of 0.12 (conservative half).

Tests whether the full signal strength helps or hurts on day 0.
"""

L2_COEF = 0.23  # Full regression coefficient


class Strategy:
    def __init__(self, symbol: str, limit: int) -> None:
        self.symbol = symbol
        self.limit = limit

    @abstractmethod
    def act(self, state: TradingState) -> None:
        raise NotImplementedError()

    def run(self, state: TradingState) -> List[Order]:
        self.orders: List[Order] = []
        self.act(state)
        return self.orders

    def buy(self, price: int, quantity: int) -> None:
        self.orders.append(Order(self.symbol, price, quantity))

    def sell(self, price: int, quantity: int) -> None:
        self.orders.append(Order(self.symbol, price, -quantity))

    def save(self):
        return None

    def load(self, data) -> None:
        pass


class MarketMakingStrategy(Strategy):
    def __init__(self, symbol: str, limit: int) -> None:
        super().__init__(symbol, limit)
        self.window = deque()
        self.window_size = 10

    @abstractmethod
    def get_true_value(self, state: TradingState) -> int:
        raise NotImplementedError()

    def act(self, state: TradingState) -> None:
        true_value = self.get_true_value(state)
        order_depth = state.order_depths[self.symbol]
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())
        if not buy_orders or not sell_orders:
            return

        position = state.position.get(self.symbol, 0)
        to_buy = self.limit - position
        to_sell = self.limit + position

        self.window.append(abs(position) == self.limit)
        if len(self.window) > self.window_size:
            self.window.popleft()

        soft_liquidate = (len(self.window) == self.window_size
            and sum(self.window) >= self.window_size / 2 and self.window[-1])
        hard_liquidate = (len(self.window) == self.window_size and all(self.window))

        max_buy_price = true_value - 1 if position > self.limit * 0.5 else true_value
        min_sell_price = true_value + 1 if position < self.limit * -0.5 else true_value

        for price, volume in sell_orders:
            if to_buy > 0 and price <= max_buy_price:
                quantity = min(to_buy, -volume)
                self.buy(price, quantity)
                to_buy -= quantity

        if to_buy > 0 and hard_liquidate:
            quantity = to_buy // 2
            self.buy(true_value, quantity); to_buy -= quantity
        if to_buy > 0 and soft_liquidate:
            quantity = to_buy // 2
            self.buy(true_value - 2, quantity); to_buy -= quantity
        if to_buy > 0:
            self.buy(min(int(max_buy_price), buy_orders[0][0] + 1), to_buy)

        for price, volume in buy_orders:
            if to_sell > 0 and price >= min_sell_price:
                quantity = min(to_sell, volume)
                self.sell(price, quantity)
                to_sell -= quantity

        if to_sell > 0 and hard_liquidate:
            quantity = to_sell // 2
            self.sell(true_value, quantity); to_sell -= quantity
        if to_sell > 0 and soft_liquidate:
            quantity = to_sell // 2
            self.sell(true_value + 2, quantity); to_sell -= quantity
        if to_sell > 0:
            self.sell(max(int(min_sell_price), sell_orders[0][0] - 1), to_sell)

    def save(self): return list(self.window)
    def load(self, data):
        if data is not None: self.window = deque(data)


class EmeraldsStrategy(MarketMakingStrategy):
    def get_true_value(self, state): return 10_000


class TomatoesStrategy(MarketMakingStrategy):
    def __init__(self, symbol, limit):
        super().__init__(symbol, limit)
        self.cache = []
        self.cache_dim = 4
        self.flow_history = []

    def compute_microprice(self, od):
        bb = max(od.buy_orders.keys()); ba = min(od.sell_orders.keys())
        bv = sum(od.buy_orders.values()); av = sum(abs(v) for v in od.sell_orders.values())
        return bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) / 2

    def compute_trade_flow(self, state):
        trades = state.market_trades.get(self.symbol, [])
        if not trades:
            self.flow_history.append(0.0)
        else:
            od = state.order_depths[self.symbol]
            mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2
            sv = sum((1 if t.price >= mid else -1) * t.quantity for t in trades)
            self.flow_history.append(sv)
        if len(self.flow_history) > 5: self.flow_history.pop(0)
        return max(-1.0, min(1.0, sum(self.flow_history) / 15.0))

    def compute_l2_imbalance(self, od):
        bids = sorted(od.buy_orders.items(), reverse=True)
        asks = sorted(od.sell_orders.items())
        if len(bids) < 2 or len(asks) < 2: return 0.0
        return bids[1][1] - abs(asks[1][1])

    def get_true_value(self, state):
        od = state.order_depths[self.symbol]
        mp = self.compute_microprice(od)
        if len(self.cache) == self.cache_dim: self.cache.pop(0)
        self.cache.append(mp)

        if len(self.cache) == self.cache_dim:
            coef = [0.059694, 0.117270, 0.244154, 0.578440]
            fv = 2.208667 + sum(coef[i] * self.cache[i] for i in range(4))
        else:
            fv = mp

        fv -= self.compute_trade_flow(state) * 1.5
        fv += self.compute_l2_imbalance(od) * L2_COEF
        return round(fv)

    def save(self):
        return {"window": list(self.window), "cache": self.cache, "flow": self.flow_history}
    def load(self, data):
        if data:
            self.window = deque(data.get("window", []))
            self.cache = data.get("cache", [])
            self.flow_history = data.get("flow", [])


class Trader:
    def __init__(self):
        self.strategies = {
            "EMERALDS": EmeraldsStrategy("EMERALDS", 80),
            "TOMATOES": TomatoesStrategy("TOMATOES", 80),
        }
    def bid(self): return 15
    def run(self, state):
        old = json.loads(state.traderData) if state.traderData != "" else {}
        new_td, orders = {}, {}
        for sym, strat in self.strategies.items():
            if sym in old: strat.load(old.get(sym))
            if sym in state.order_depths: orders[sym] = strat.run(state)
            new_td[sym] = strat.save()
        return orders, 0, json.dumps(new_td, separators=(",", ":"))
