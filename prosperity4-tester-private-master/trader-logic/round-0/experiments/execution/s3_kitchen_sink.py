import json
from abc import abstractmethod
from collections import deque
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict

"""
s3_kitchen_sink: All improvements combined

TOMATOES: s2_tradeflow + L2 imbalance as quote skew (not fair value)
EMERALDS: dual-layer quoting
Both: gentle end-of-day position reduction

Targets: 3,000+ on website.
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
        if quantity > 0:
            self.orders.append(Order(self.symbol, price, quantity))

    def sell(self, price: int, quantity: int) -> None:
        if quantity > 0:
            self.orders.append(Order(self.symbol, price, -quantity))

    def save(self):
        return None

    def load(self, data) -> None:
        pass


class EmeraldsStrategy(Strategy):
    """Dual-layer EMERALDS quoting."""
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

        for p, v in buys:
            if to_sell > 0 and p >= tv:
                q = min(to_sell, v)
                self.sell(p, q)
                to_sell -= q

        if to_buy > 0:
            tight_qty = max(1, int(to_buy * 0.4))
            standard_qty = to_buy - tight_qty
            std_price = min(tv - 1, buys[0][0] + 1)
            self.buy(std_price, standard_qty)
            tight_price = min(tv - 2, buys[0][0] + 1)
            if tight_price < std_price and tight_qty > 0:
                self.buy(tight_price, tight_qty)
            elif tight_qty > 0:
                self.buy(std_price, tight_qty)

        if to_sell > 0:
            tight_qty = max(1, int(to_sell * 0.4))
            standard_qty = to_sell - tight_qty
            std_price = max(tv + 1, sells[0][0] - 1)
            self.sell(std_price, standard_qty)
            tight_price = max(tv + 2, sells[0][0] - 1)
            if tight_price > std_price and tight_qty > 0:
                self.sell(tight_price, tight_qty)
            elif tight_qty > 0:
                self.sell(std_price, tight_qty)


class TomatoesStrategy(Strategy):
    """s2_tradeflow + L2 quote skew + end-of-day position reduction."""
    def __init__(self, symbol: str, limit: int) -> None:
        super().__init__(symbol, limit)
        self.window = deque()
        self.window_size = 10
        self.cache = []
        self.cache_dim = 4
        self.flow_history = []

    def compute_microprice(self, od: OrderDepth) -> float:
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        bv = sum(od.buy_orders.values())
        av = sum(abs(v) for v in od.sell_orders.values())
        return bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) / 2

    def compute_trade_flow(self, state: TradingState) -> float:
        trades = state.market_trades.get(self.symbol, [])
        if not trades:
            self.flow_history.append(0.0)
        else:
            od = state.order_depths[self.symbol]
            mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2
            sv = sum((1 if t.price >= mid else -1) * t.quantity for t in trades)
            self.flow_history.append(sv)
        if len(self.flow_history) > 5:
            self.flow_history.pop(0)
        return max(-1.0, min(1.0, sum(self.flow_history) / 15.0))

    def get_l2_skew(self, od: OrderDepth) -> int:
        bids = sorted(od.buy_orders.items(), reverse=True)
        asks = sorted(od.sell_orders.items())
        if len(bids) < 2 or len(asks) < 2:
            return 0
        l2_imb = bids[1][1] - abs(asks[1][1])
        if abs(l2_imb) <= 5:
            return 0
        return 1 if l2_imb > 0 else -1

    def act(self, state: TradingState) -> None:
        od = state.order_depths[self.symbol]
        buy_orders = sorted(od.buy_orders.items(), reverse=True)
        sell_orders = sorted(od.sell_orders.items())
        if not buy_orders or not sell_orders:
            return

        # Fair value: microprice regression + trade flow (proven 2,851)
        microprice = self.compute_microprice(od)
        if len(self.cache) == self.cache_dim:
            self.cache.pop(0)
        self.cache.append(microprice)

        if len(self.cache) == self.cache_dim:
            coef = [0.059694, 0.117270, 0.244154, 0.578440]
            fv = 2.208667 + sum(coef[i] * self.cache[i] for i in range(4))
        else:
            fv = microprice

        fv -= self.compute_trade_flow(state) * 1.5
        true_value = round(fv)

        # L2 skew for posting
        l2_skew = self.get_l2_skew(od)

        position = state.position.get(self.symbol, 0)
        to_buy = self.limit - position
        to_sell = self.limit + position

        # End-of-day position reduction: last 10% of ticks
        # Reduce capacity on the side that increases |position|
        if state.timestamp >= 180000:
            if position > 40:
                to_buy = max(0, min(to_buy, 5))  # limit further buying
            elif position < -40:
                to_sell = max(0, min(to_sell, 5))  # limit further selling

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

        # TAKE
        for price, volume in sell_orders:
            if to_buy > 0 and price <= max_buy_price:
                quantity = min(to_buy, -volume)
                self.buy(price, quantity)
                to_buy -= quantity

        if to_buy > 0 and hard_liquidate:
            q = to_buy // 2
            self.buy(true_value, q)
            to_buy -= q
        if to_buy > 0 and soft_liquidate:
            q = to_buy // 2
            self.buy(true_value - 2, q)
            to_buy -= q

        # MAKE with L2 skew
        if to_buy > 0:
            skewed_cap = true_value + l2_skew
            price = min(int(skewed_cap), buy_orders[0][0] + 1)
            price = min(price, sell_orders[0][0] - 1)
            self.buy(price, to_buy)

        for price, volume in buy_orders:
            if to_sell > 0 and price >= min_sell_price:
                quantity = min(to_sell, volume)
                self.sell(price, quantity)
                to_sell -= quantity

        if to_sell > 0 and hard_liquidate:
            q = to_sell // 2
            self.sell(true_value, q)
            to_sell -= q
        if to_sell > 0 and soft_liquidate:
            q = to_sell // 2
            self.sell(true_value + 2, q)
            to_sell -= q

        if to_sell > 0:
            skewed_floor = true_value + l2_skew
            price = max(int(skewed_floor), sell_orders[0][0] - 1)
            price = max(price, buy_orders[0][0] + 1)
            self.sell(price, to_sell)

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
