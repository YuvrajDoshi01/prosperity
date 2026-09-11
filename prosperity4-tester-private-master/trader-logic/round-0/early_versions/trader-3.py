import json
from abc import abstractmethod
from collections import deque
from datamodel import OrderDepth, Order, TradingState
from logger import logger
from typing import List, Dict

"""
Prosperity 4 — Tutorial Round: EMERALDS + TOMATOES — v5

Combined approach:
1. jmerle's MarketMakingStrategy (liquidation window, position-dependent aggression)
2. Order book imbalance signal (0.59 corr with next return) shifts true_value
3. Regression-based fair for TOMATOES (v2 scored 2621 > v4's 2518)
4. Fixed fair 10000 for EMERALDS
"""


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
    def __init__(self, symbol: str, limit: int, imbalance_k: float = 0) -> None:
        super().__init__(symbol, limit)
        self.window = deque()
        self.window_size = 10
        self.imbalance_k = imbalance_k

    @abstractmethod
    def get_base_true_value(self, state: TradingState) -> int:
        raise NotImplementedError()

    def compute_imbalance(self, order_depth: OrderDepth) -> float:
        bid_vol = sum(abs(v) for v in order_depth.buy_orders.values())
        ask_vol = sum(abs(v) for v in order_depth.sell_orders.values())
        total = bid_vol + ask_vol
        if total == 0:
            return 0.5
        return bid_vol / total

    def act(self, state: TradingState) -> None:
        order_depth = state.order_depths[self.symbol]
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        if not buy_orders or not sell_orders:
            return

        base_value = self.get_base_true_value(state)
        imbalance = self.compute_imbalance(order_depth)
        imb_shift = round(self.imbalance_k * (imbalance - 0.5))
        true_value = base_value + imb_shift

        position = state.position.get(self.symbol, 0)
        to_buy = self.limit - position
        to_sell = self.limit + position

        self.window.append(abs(position) == self.limit)
        if len(self.window) > self.window_size:
            self.window.popleft()

        soft_liquidate = (
            len(self.window) == self.window_size
            and sum(self.window) >= self.window_size / 2
            and self.window[-1]
        )
        hard_liquidate = (
            len(self.window) == self.window_size
            and all(self.window)
        )

        max_buy_price = true_value - 1 if position > self.limit * 0.5 else true_value
        min_sell_price = true_value + 1 if position < self.limit * -0.5 else true_value

        # ── BUY SIDE ──
        for price, volume in sell_orders:
            if to_buy > 0 and price <= max_buy_price:
                quantity = min(to_buy, -volume)
                self.buy(price, quantity)
                to_buy -= quantity

        if to_buy > 0 and hard_liquidate:
            quantity = to_buy // 2
            self.buy(true_value, quantity)
            to_buy -= quantity

        if to_buy > 0 and soft_liquidate:
            quantity = to_buy // 2
            self.buy(true_value - 2, quantity)
            to_buy -= quantity

        if to_buy > 0:
            best_bid = buy_orders[0][0]
            price = min(max_buy_price, best_bid + 1)
            self.buy(price, to_buy)

        # ── SELL SIDE ──
        for price, volume in buy_orders:
            if to_sell > 0 and price >= min_sell_price:
                quantity = min(to_sell, volume)
                self.sell(price, quantity)
                to_sell -= quantity

        if to_sell > 0 and hard_liquidate:
            quantity = to_sell // 2
            self.sell(true_value, quantity)
            to_sell -= quantity

        if to_sell > 0 and soft_liquidate:
            quantity = to_sell // 2
            self.sell(true_value + 2, quantity)
            to_sell -= quantity

        if to_sell > 0:
            best_ask = sell_orders[0][0]
            price = max(min_sell_price, best_ask - 1)
            self.sell(price, to_sell)

    def save(self):
        return list(self.window)

    def load(self, data) -> None:
        if data is not None:
            self.window = deque(data)


class EmeraldsStrategy(MarketMakingStrategy):
    """EMERALDS: fair=10000, imbalance k=20 (corr=0.63)"""
    def __init__(self, symbol: str, limit: int) -> None:
        super().__init__(symbol, limit, imbalance_k=20)

    def get_base_true_value(self, state: TradingState) -> int:
        return 10_000


class TomatoesStrategy(MarketMakingStrategy):
    """TOMATOES: regression fair + imbalance k=12 (corr=0.59)"""
    def __init__(self, symbol: str, limit: int) -> None:
        super().__init__(symbol, limit, imbalance_k=12)
        self.cache = []
        self.cache_dim = 4

    def get_base_true_value(self, state: TradingState) -> int:
        order_depth = state.order_depths[self.symbol]
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        current_mid = (best_bid + best_ask) / 2

        if len(self.cache) == self.cache_dim:
            self.cache.pop(0)
        self.cache.append(current_mid)

        if len(self.cache) == self.cache_dim:
            return self._predict_next()

        return round(current_mid)

    def _predict_next(self) -> int:
        coef = [0.123131, 0.165972, 0.253373, 0.456765]
        intercept = 3.787356
        pred = intercept
        for i, val in enumerate(self.cache):
            pred += val * coef[i]
        return round(pred)

    def save(self):
        return {"window": list(self.window), "cache": self.cache}

    def load(self, data) -> None:
        if data is not None:
            self.window = deque(data.get("window", []))
            self.cache = data.get("cache", [])


class Trader:
    def __init__(self) -> None:
        limits = {"EMERALDS": 80, "TOMATOES": 80}
        self.strategies: Dict[str, Strategy] = {
            "EMERALDS": EmeraldsStrategy("EMERALDS", limits["EMERALDS"]),
            "TOMATOES": TomatoesStrategy("TOMATOES", limits["TOMATOES"]),
        }

    def bid(self):
        return 15

    def run(self, state: TradingState):
        conversions = 0
        old_trader_data = json.loads(state.traderData) if state.traderData != "" else {}
        new_trader_data = {}

        orders = {}
        for symbol, strategy in self.strategies.items():
            if symbol in old_trader_data:
                strategy.load(old_trader_data.get(symbol, None))
            if symbol in state.order_depths:
                orders[symbol] = strategy.run(state)
            new_trader_data[symbol] = strategy.save()

        trader_data = json.dumps(new_trader_data, separators=(",", ":"))
        logger.flush(state, orders, conversions, trader_data)
        return orders, conversions, trader_data
