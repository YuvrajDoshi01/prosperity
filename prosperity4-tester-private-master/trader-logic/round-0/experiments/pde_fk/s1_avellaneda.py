import json
from abc import abstractmethod
from collections import deque
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict

"""
s1_avellaneda: Microprice Regression + Avellaneda-Stoikov Time-Dependent Inventory Skew

Base: 6913.py microprice regression (2,644 on website)
NEW: A-S reservation price — inventory skew DECREASES over time.
  Early: large skew (aggressively rebalance)
  Late: small skew (accept position, capture mark-to-market)

The HJB solution says: reservation = fair - q * gamma * sigma^2 * (T-t)
"""

GAMMA = 0.05       # Risk aversion parameter
SIGMA_SQ = 1.80    # Empirical variance per tick (std=1.34, both days)
T_MAX = 199900     # Last timestamp


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

    def get_reservation_price(self, true_value: int, position: int, timestamp: int) -> int:
        """A-S reservation price: skew fair value based on inventory + time remaining."""
        return true_value  # default: no skew (overridden in TomatoesStrategy)

    def act(self, state: TradingState) -> None:
        true_value = self.get_true_value(state)
        position = state.position.get(self.symbol, 0)
        reservation = self.get_reservation_price(true_value, position, state.timestamp)

        order_depth = state.order_depths[self.symbol]
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        if not buy_orders or not sell_orders:
            return

        to_buy = self.limit - position
        to_sell = self.limit + position

        # Liquidation tracking
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

        # Use reservation price for taking decisions
        max_buy_price = reservation - 1 if position > self.limit * 0.5 else reservation
        min_sell_price = reservation + 1 if position < self.limit * -0.5 else reservation

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
            price = min(int(max_buy_price), best_bid + 1)
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
            price = max(int(min_sell_price), best_ask - 1)
            self.sell(price, to_sell)

    def save(self):
        return list(self.window)

    def load(self, data) -> None:
        if data is not None:
            self.window = deque(data)


class EmeraldsStrategy(MarketMakingStrategy):
    def get_true_value(self, state: TradingState) -> int:
        return 10_000


class TomatoesStrategy(MarketMakingStrategy):
    def __init__(self, symbol: str, limit: int) -> None:
        super().__init__(symbol, limit)
        self.cache = []
        self.cache_dim = 4

    def compute_microprice(self, order_depth: OrderDepth) -> float:
        """Microprice = bid + (bid_vol / total_vol) * spread (L1 imbalance weighted)."""
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_vol = sum(order_depth.buy_orders.values())
        ask_vol = sum(abs(v) for v in order_depth.sell_orders.values())
        total_vol = bid_vol + ask_vol
        if total_vol > 0:
            return best_bid + (bid_vol / total_vol) * (best_ask - best_bid)
        return (best_bid + best_ask) / 2

    def get_true_value(self, state: TradingState) -> int:
        order_depth = state.order_depths[self.symbol]
        microprice = self.compute_microprice(order_depth)

        if len(self.cache) == self.cache_dim:
            self.cache.pop(0)
        self.cache.append(microprice)

        if len(self.cache) == self.cache_dim:
            return self._predict_next()
        return round(microprice)

    def _predict_next(self) -> int:
        """Regression on last 4 microprices."""
        coef = [0.059694, 0.117270, 0.244154, 0.578440]
        intercept = 2.208667
        pred = intercept
        for i, val in enumerate(self.cache):
            pred += val * coef[i]
        return round(pred)

    def get_reservation_price(self, true_value: int, position: int, timestamp: int) -> int:
        """A-S reservation price: time-dependent inventory skew."""
        time_remaining = max(0, (T_MAX - timestamp) / T_MAX)  # 1.0 → 0.0
        skew = position * GAMMA * SIGMA_SQ * time_remaining
        return round(true_value - skew)

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
        old_trader_data = json.loads(state.traderData) if state.traderData != "" else {}
        new_trader_data = {}
        orders = {}
        for symbol, strategy in self.strategies.items():
            if symbol in old_trader_data:
                strategy.load(old_trader_data.get(symbol, None))
            if symbol in state.order_depths:
                orders[symbol] = strategy.run(state)
            new_trader_data[symbol] = strategy.save()
        return orders, 0, json.dumps(new_trader_data, separators=(",", ":"))
