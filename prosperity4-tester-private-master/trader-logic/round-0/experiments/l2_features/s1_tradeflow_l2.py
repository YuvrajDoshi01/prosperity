import json
from abc import abstractmethod
from collections import deque
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict

"""
s1_tradeflow_l2: s2_tradeflow (2,851) + L2 Volume Imbalance Signal

L2 imbalance is the STRONGEST predictive signal found (r=0.60, both days):
  ret = 0.237 * (bid_vol_2 - ask_vol_2)

When L2 is asymmetric (~7% of ticks): expected return +3.3/-2.9 ticks
When L2 is symmetric (93%): no signal (no interference with base strategy)

This is CAUSAL, not the spread-value artifact that failed on day 0.
The direction comes from WHICH SIDE has more L2 volume, not the spread number.
"""

L2_COEF = 0.12  # Conservative: half the regression coefficient (0.237)


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
        self.flow_history = []

    def compute_microprice(self, order_depth: OrderDepth) -> float:
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_vol = sum(order_depth.buy_orders.values())
        ask_vol = sum(abs(v) for v in order_depth.sell_orders.values())
        total_vol = bid_vol + ask_vol
        if total_vol > 0:
            return best_bid + (bid_vol / total_vol) * (best_ask - best_bid)
        return (best_bid + best_ask) / 2

    def compute_trade_flow(self, state: TradingState) -> float:
        trades = state.market_trades.get(self.symbol, [])
        if not trades:
            self.flow_history.append(0.0)
        else:
            od = state.order_depths[self.symbol]
            mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2
            signed_vol = 0.0
            for trade in trades:
                direction = 1 if trade.price >= mid else -1
                signed_vol += direction * trade.quantity
            self.flow_history.append(signed_vol)

        if len(self.flow_history) > 5:
            self.flow_history.pop(0)

        total_flow = sum(self.flow_history)
        return max(-1.0, min(1.0, total_flow / 15.0))

    def compute_l2_imbalance(self, order_depth: OrderDepth) -> float:
        """L2 volume imbalance: bid_vol_2 - ask_vol_2. Zero when symmetric."""
        # Bids: sorted descending by price → [0]=L1 (best), [1]=L2
        bids = sorted(order_depth.buy_orders.items(), reverse=True)
        # Asks: sorted ascending by price → [0]=L1 (best), [1]=L2
        asks = sorted(order_depth.sell_orders.items())

        if len(bids) < 2 or len(asks) < 2:
            return 0.0

        bid_vol_2 = bids[1][1]        # L2 bid volume (positive)
        ask_vol_2 = abs(asks[1][1])    # L2 ask volume (was negative)

        return bid_vol_2 - ask_vol_2

    def get_true_value(self, state: TradingState) -> int:
        order_depth = state.order_depths[self.symbol]
        microprice = self.compute_microprice(order_depth)

        if len(self.cache) == self.cache_dim:
            self.cache.pop(0)
        self.cache.append(microprice)

        # Base: microprice regression (proven 2,644)
        if len(self.cache) == self.cache_dim:
            coef = [0.059694, 0.117270, 0.244154, 0.578440]
            intercept = 2.208667
            fv = intercept
            for i, val in enumerate(self.cache):
                fv += val * coef[i]
        else:
            fv = microprice

        # Signal 1: Trade flow (proven +207, r=-0.54)
        flow_signal = self.compute_trade_flow(state)
        fv -= flow_signal * 1.5

        # Signal 2: L2 volume imbalance (r=0.60, strongest signal)
        # Only fires ~7% of ticks when L2 is asymmetric
        # When L2_imb=0 (93% of ticks), adds nothing — no interference
        l2_imb = self.compute_l2_imbalance(order_depth)
        fv += l2_imb * L2_COEF

        return round(fv)

    def save(self):
        return {"window": list(self.window), "cache": self.cache, "flow": self.flow_history}

    def load(self, data) -> None:
        if data is not None:
            self.window = deque(data.get("window", []))
            self.cache = data.get("cache", [])
            self.flow_history = data.get("flow", [])


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
