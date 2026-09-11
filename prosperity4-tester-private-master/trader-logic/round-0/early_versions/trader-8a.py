import json
from abc import abstractmethod
from collections import deque
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict

"""
Prosperity 4 — Tutorial Round v6

Key intel from Discord:
  - fabiantum (4k): "test all common signals" → microprice is the alpha
  - valentinz (2.6k): "mid_wall and limit around 15-20" 
  - advoltex (2.6k): "tighten spread", confirmed 2.6k is possible without overfit
  - ishaanthenerd: "miss the correct mid price" → microprice fixes this

Core change from v5: 
  Microprice = bid + (bid_vol / (bid_vol + ask_vol)) * spread
  - Better predictor of next mid than simple mid (MAE 0.70 vs 0.79)
  - Regression on microprice: RMSE 1.11 vs 1.18 on simple mid
  - Naturally incorporates order book imbalance — no separate k parameter needed
  
EMERALDS: fair = 10000 (microprice ≈ 10000 anyway, std=0.51)
TOMATOES: fair = regression on last 4 microprices
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

        if not buy_orders or not sell_orders:
            return

        position = state.position.get(self.symbol, 0)
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

        # Position-dependent aggression
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
            price = max_buy_price - 1 if max_buy_price == true_value else max_buy_price
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
            price = min_sell_price + 1 if min_sell_price == true_value else min_sell_price
            self.sell(price, to_sell)

    def save(self):
        return list(self.window)

    def load(self, data) -> None:
        if data is not None:
            self.window = deque(data)


class EmeraldsStrategy(MarketMakingStrategy):
    """EMERALDS: fair = 10000"""
    def get_true_value(self, state: TradingState) -> int:
        return 10_000


class TomatoesStrategy(MarketMakingStrategy):
    """
    TOMATOES: regression on last 4 microprices.
    
    Microprice = bid1 + imbalance * spread
    where imbalance = bid_vol_total / (bid_vol_total + ask_vol_total)
    
    This naturally shifts fair toward the side with more volume,
    capturing order flow information that simple mid ignores.
    RMSE improvement: 1.11 vs 1.18 (6% better prediction).
    """
    def __init__(self, symbol: str, limit: int) -> None:
        super().__init__(symbol, limit)
        self.cache = []
        self.cache_dim = 4

    def compute_microprice(self, order_depth: OrderDepth) -> float:
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        
        bid_vol = sum(abs(v) for v in order_depth.buy_orders.values())
        ask_vol = sum(abs(v) for v in order_depth.sell_orders.values())
        total = bid_vol + ask_vol
        
        if total == 0:
            return (best_bid + best_ask) / 2
        
        imb = bid_vol / total
        return best_bid + imb * (best_ask - best_bid)

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
        """Regression on last 4 microprices → predict next mid."""
        coef = [0.059694, 0.117270, 0.244154, 0.578440]
        intercept = 2.208667
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
        return orders, conversions, trader_data
