import json
from abc import abstractmethod
from collections import deque
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict

"""
s3_tradeflow_l2_reversal: s2_tradeflow + L2 imbalance + Large Move Reversal

Three stacked signals on top of microprice regression:
1. Trade flow (proven +207 PnL on website, r=-0.54)
2. L2 volume imbalance (r=0.60, strongest signal in data)
3. Large move reversal: after |change| >= 3.0, reversal probability 66-67.5%

When a large move just happened, we shift fair value in the reversal direction.
Combined with L2 imbalance which fires during these same volatile moments.
"""

L2_COEF = 0.12  # Conservative L2 coefficient
REVERSAL_SHIFT = 1.0  # Ticks to shift after large move (conservative)


class Strategy:
    def __init__(self, symbol, limit):
        self.symbol = symbol
        self.limit = limit

    @abstractmethod
    def act(self, state): raise NotImplementedError()

    def run(self, state):
        self.orders = []
        self.act(state)
        return self.orders

    def buy(self, price, quantity):
        self.orders.append(Order(self.symbol, price, quantity))

    def sell(self, price, quantity):
        self.orders.append(Order(self.symbol, price, -quantity))

    def save(self): return None
    def load(self, data): pass


class MarketMakingStrategy(Strategy):
    def __init__(self, symbol, limit):
        super().__init__(symbol, limit)
        self.window = deque()
        self.window_size = 10

    @abstractmethod
    def get_true_value(self, state): raise NotImplementedError()

    def act(self, state):
        true_value = self.get_true_value(state)
        od = state.order_depths[self.symbol]
        buy_orders = sorted(od.buy_orders.items(), reverse=True)
        sell_orders = sorted(od.sell_orders.items())
        if not buy_orders or not sell_orders: return

        position = state.position.get(self.symbol, 0)
        to_buy = self.limit - position
        to_sell = self.limit + position

        self.window.append(abs(position) == self.limit)
        if len(self.window) > self.window_size: self.window.popleft()

        soft_liquidate = (len(self.window) == self.window_size
            and sum(self.window) >= self.window_size / 2 and self.window[-1])
        hard_liquidate = (len(self.window) == self.window_size and all(self.window))

        max_buy_price = true_value - 1 if position > self.limit * 0.5 else true_value
        min_sell_price = true_value + 1 if position < self.limit * -0.5 else true_value

        for price, volume in sell_orders:
            if to_buy > 0 and price <= max_buy_price:
                quantity = min(to_buy, -volume)
                self.buy(price, quantity); to_buy -= quantity

        if to_buy > 0 and hard_liquidate:
            q = to_buy // 2; self.buy(true_value, q); to_buy -= q
        if to_buy > 0 and soft_liquidate:
            q = to_buy // 2; self.buy(true_value - 2, q); to_buy -= q
        if to_buy > 0:
            self.buy(min(int(max_buy_price), buy_orders[0][0] + 1), to_buy)

        for price, volume in buy_orders:
            if to_sell > 0 and price >= min_sell_price:
                quantity = min(to_sell, volume)
                self.sell(price, quantity); to_sell -= quantity

        if to_sell > 0 and hard_liquidate:
            q = to_sell // 2; self.sell(true_value, q); to_sell -= q
        if to_sell > 0 and soft_liquidate:
            q = to_sell // 2; self.sell(true_value + 2, q); to_sell -= q
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
        self.prev_mid = None

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

    def compute_reversal_signal(self, od):
        """After large move (|Δ| >= 3.0), expect reversal (66-67.5% probability)."""
        mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2
        if self.prev_mid is None:
            self.prev_mid = mid
            return 0.0

        change = mid - self.prev_mid
        self.prev_mid = mid

        if abs(change) >= 3.0:
            # Large move detected → expect reversal
            # If price just went UP big, expect DOWN → shift fair value DOWN
            return -change / abs(change) * REVERSAL_SHIFT
        return 0.0

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

        # Signal 1: Trade flow
        fv -= self.compute_trade_flow(state) * 1.5
        # Signal 2: L2 imbalance
        fv += self.compute_l2_imbalance(od) * L2_COEF
        # Signal 3: Large move reversal
        fv += self.compute_reversal_signal(od)

        return round(fv)

    def save(self):
        return {"window": list(self.window), "cache": self.cache,
                "flow": self.flow_history, "prev_mid": self.prev_mid}
    def load(self, data):
        if data:
            self.window = deque(data.get("window", []))
            self.cache = data.get("cache", [])
            self.flow_history = data.get("flow", [])
            self.prev_mid = data.get("prev_mid")


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
