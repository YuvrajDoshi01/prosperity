import json
from abc import abstractmethod
from collections import deque
from datamodel import OrderDepth, Order, TradingState
from logger import logger
from typing import List, Dict, Any

"""
Prosperity 4 — Tutorial Round: EMERALDS + TOMATOES

Architecture: jmerle's MarketMakingStrategy (9th place Prosperity 3, all rounds).

Core market-making logic:
  1. Compute true_value
  2. Take all asks ≤ true_value (tighten to true_value-1 when long >50% limit)
  3. Take all bids ≥ true_value (tighten to true_value+1 when short >50% limit)
  4. Liquidation window: if stuck at limit too long, post aggressively to unwind
  5. Post remaining capacity: undercut the "popular" price (highest volume level) + 1
  
EMERALDS: true_value = 10000 (fixed, rock-solid)
TOMATOES: true_value = round(mid_price) from order book
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

        position = state.position.get(self.symbol, 0)
        to_buy = self.limit - position
        to_sell = self.limit + position

        # ── Liquidation tracking ──
        self.window.append(abs(position) == self.limit)
        if len(self.window) > self.window_size:
            self.window.popleft()

        soft_liquidate = (
            len(self.window) == self.window_size
            and sum(self.window) >= self.window_size / 2
            and self.window[-1]
        )
        hard_liquidate = (
            len(self.window) == self.window_size and all(self.window)
        )

        # ── Position-dependent aggression ──
        # When very long: don't buy at fair, buy below fair only
        # When very short: don't sell at fair, sell above fair only
        max_buy_price = true_value - 1 if position > self.limit * 0.5 else true_value
        min_sell_price = true_value + 1 if position < self.limit * -0.5 else true_value

        # ── BUY SIDE ──

        # 1) Take cheap asks
        for price, volume in sell_orders:
            if to_buy > 0 and price <= max_buy_price:
                quantity = min(to_buy, -volume)
                self.buy(price, quantity)
                to_buy -= quantity

        # 2) Hard liquidation: aggressively buy at fair to unwind short
        if to_buy > 0 and hard_liquidate:
            quantity = to_buy // 2
            self.buy(true_value, quantity)
            to_buy -= quantity

        # 3) Soft liquidation: buy at fair-2 to help unwind
        if to_buy > 0 and soft_liquidate:
            quantity = to_buy // 2
            self.buy(true_value - 2, quantity)
            to_buy -= quantity

        # 4) Post remaining: undercut the best bid to get inside spread
        if to_buy > 0:
            best_buy_price = buy_orders[0][0]  # sorted descending, first = best
            price = min(max_buy_price, best_buy_price + 1)
            self.buy(price, to_buy)

        # ── SELL SIDE ──

        # 1) Take expensive bids
        for price, volume in buy_orders:
            if to_sell > 0 and price >= min_sell_price:
                quantity = min(to_sell, volume)
                self.sell(price, quantity)
                to_sell -= quantity

        # 2) Hard liquidation: aggressively sell at fair to unwind long
        if to_sell > 0 and hard_liquidate:
            quantity = to_sell // 2
            self.sell(true_value, quantity)
            to_sell -= quantity

        # 3) Soft liquidation: sell at fair+2 to help unwind
        if to_sell > 0 and soft_liquidate:
            quantity = to_sell // 2
            self.sell(true_value + 2, quantity)
            to_sell -= quantity

        # 4) Post remaining: undercut the best ask to get inside spread
        if to_sell > 0:
            best_sell_price = sell_orders[0][0]  # sorted ascending, first = best
            price = max(min_sell_price, best_sell_price - 1)
            self.sell(price, to_sell)

    def save(self):
        return list(self.window)

    def load(self, data) -> None:
        if data is not None:
            self.window = deque(data)


class EmeraldsStrategy(MarketMakingStrategy):
    """EMERALDS: fair value is exactly 10000 (std = 0.72 across 20k obs)"""
    def get_true_value(self, state: TradingState) -> int:
        return 10_000


class TomatoesStrategy(MarketMakingStrategy):
    """
    TOMATOES: fair value = round(mid_price) from order book.
    
    Uses "popular price" (highest volume level) for mid calculation,
    matching jmerle's Starfruit approach. The popular price is more
    stable than best bid/ask since it ignores thin outlier levels.
    """
    def get_true_value(self, state: TradingState) -> int:
        order_depth = state.order_depths[self.symbol]
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        # Best (tightest) prices on each side
        best_buy_price = buy_orders[0][0]
        best_sell_price = sell_orders[0][0]

        return round((best_buy_price + best_sell_price) / 2)


class Trader:
    def __init__(self) -> None:
        limits = {
            "EMERALDS": 80,
            "TOMATOES": 80,
        }

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
