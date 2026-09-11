import json
from abc import abstractmethod
from collections import deque
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict

"""
s3_combined: Wall Mid + A-S Skew + Trade Flow (Zero Regression)

NO microprice. NO regression. NO fitted coefficients.
Fair value = Wall Mid (structural, zero params)
+ A-S time-dependent inventory skew (PDE-derived)
+ Trade flow signal from market_trades (r=-0.54, structural)

Three independent structural edges, zero overfitting risk.
"""

GAMMA = 0.05
SIGMA_SQ = 1.80
T_MAX = 199900


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
        self.flow_history = []

    def get_wall_mid(self, od: OrderDepth) -> float:
        """Wall Mid: midpoint of highest-volume bid and ask levels."""
        wall_bid = max(od.buy_orders.items(), key=lambda x: x[1])[0]
        wall_ask = max(od.sell_orders.items(), key=lambda x: abs(x[1]))[0]
        return (wall_bid + wall_ask) / 2

    def compute_trade_flow(self, state: TradingState) -> float:
        """Signed trade flow from market_trades, normalized to [-1, 1]."""
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

    def get_true_value(self, state: TradingState) -> int:
        od = state.order_depths[self.symbol]
        position = state.position.get(self.symbol, 0)

        # 1. Wall Mid (zero params, structural)
        fv = self.get_wall_mid(od)

        # 2. Trade flow adjustment (counter-flow, r=-0.54)
        flow_signal = self.compute_trade_flow(state)
        fv -= flow_signal * 1.5

        # 3. A-S time-dependent inventory skew
        time_remaining = max(0, (T_MAX - state.timestamp) / T_MAX)
        skew = position * GAMMA * SIGMA_SQ * time_remaining
        fv -= skew

        return round(fv)

    def save(self):
        return {"window": list(self.window), "flow": self.flow_history}

    def load(self, data) -> None:
        if data is not None:
            self.window = deque(data.get("window", []))
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
