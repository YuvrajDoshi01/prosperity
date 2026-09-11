import json
from abc import abstractmethod
from collections import deque
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict

class Strategy:
    def __init__(self, symbol, limit):
        self.symbol = symbol
        self.limit = limit
    def act(self, state): raise NotImplementedError()
    def run(self, state):
        self.orders = []
        self.act(state)
        return self.orders
    def buy(self, price, quantity): self.orders.append(Order(self.symbol, price, quantity))
    def sell(self, price, quantity): self.orders.append(Order(self.symbol, price, -quantity))
    def save(self): return None
    def load(self, data): pass

class MarketMakingStrategy(Strategy):
    def __init__(self, symbol, limit, depth_shift=0):
        super().__init__(symbol, limit)
        self.window = deque()
        self.window_size = 10
        self.depth_shift = depth_shift

    def get_base_true_value(self, state): raise NotImplementedError()

    def compute_depth_signal(self, od):
        n_bid = len(od.buy_orders)
        n_ask = len(od.sell_orders)
        level_diff = n_bid - n_ask
        return round(-self.depth_shift * level_diff)

    def act(self, state):
        od = state.order_depths[self.symbol]
        buys = sorted(od.buy_orders.items(), reverse=True)
        sells = sorted(od.sell_orders.items())
        if not buys or not sells: return

        base = self.get_base_true_value(state)
        tv = base + self.compute_depth_signal(od)

        pos = state.position.get(self.symbol, 0)
        to_buy = self.limit - pos
        to_sell = self.limit + pos

        self.window.append(abs(pos) == self.limit)
        if len(self.window) > self.window_size: self.window.popleft()

        soft_liq = len(self.window) == self.window_size and sum(self.window) >= self.window_size / 2 and self.window[-1]
        hard_liq = len(self.window) == self.window_size and all(self.window)

        max_buy = tv - 1 if pos > self.limit * 0.5 else tv
        min_sell = tv + 1 if pos < self.limit * -0.5 else tv

        for price, vol in sells:
            if to_buy > 0 and price <= max_buy:
                qty = min(to_buy, -vol)
                self.buy(price, qty)
                to_buy -= qty

        if to_buy > 0 and hard_liq:
            qty = to_buy // 2
            self.buy(tv, qty); to_buy -= qty
        if to_buy > 0 and soft_liq:
            qty = to_buy // 2
            self.buy(tv - 2, qty); to_buy -= qty
        if to_buy > 0:
            self.buy(min(max_buy, buys[0][0] + 1), to_buy)

        for price, vol in buys:
            if to_sell > 0 and price >= min_sell:
                qty = min(to_sell, vol)
                self.sell(price, qty)
                to_sell -= qty

        if to_sell > 0 and hard_liq:
            qty = to_sell // 2
            self.sell(tv, qty); to_sell -= qty
        if to_sell > 0 and soft_liq:
            qty = to_sell // 2
            self.sell(tv + 2, qty); to_sell -= qty
        if to_sell > 0:
            self.sell(max(min_sell, sells[0][0] - 1), to_sell)

    def save(self): return list(self.window)
    def load(self, data):
        if data is not None: self.window = deque(data)

class EmeraldsStrategy(MarketMakingStrategy):
    def __init__(self, symbol, limit):
        super().__init__(symbol, limit, depth_shift=4)
    def get_base_true_value(self, state): return 10000

class TomatoesStrategy(MarketMakingStrategy):
    def __init__(self, symbol, limit):
        super().__init__(symbol, limit, depth_shift=3)
        self.cache = []
        self.cache_dim = 4

    def compute_microprice(self, od):
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        bv = sum(abs(v) for v in od.buy_orders.values())
        av = sum(abs(v) for v in od.sell_orders.values())
        t = bv + av
        if t == 0: return (bb + ba) / 2
        return bb + (bv / t) * (ba - bb)

    def get_base_true_value(self, state):
        od = state.order_depths[self.symbol]
        mp = self.compute_microprice(od)
        if len(self.cache) == self.cache_dim: self.cache.pop(0)
        self.cache.append(mp)
        if len(self.cache) == self.cache_dim: return self._predict()
        return round(mp)

    def _predict(self):
        coef = [0.059694, 0.117270, 0.244154, 0.578440]
        intercept = 2.208667
        p = intercept
        for i, v in enumerate(self.cache): p += v * coef[i]
        return round(p)

    def save(self): return {"w": list(self.window), "c": self.cache}
    def load(self, data):
        if data is not None:
            self.window = deque(data.get("w", []))
            self.cache = data.get("c", [])

class Trader:
    def __init__(self):
        self.strategies = {
            "EMERALDS": EmeraldsStrategy("EMERALDS", 80),
            "TOMATOES": TomatoesStrategy("TOMATOES", 80),
        }
    def bid(self): return 15
    def run(self, state):
        conversions = 0
        old_td = json.loads(state.traderData) if state.traderData != "" else {}
        new_td = {}
        orders = {}
        for sym, strat in self.strategies.items():
            if sym in old_td: strat.load(old_td.get(sym))
            if sym in state.order_depths: orders[sym] = strat.run(state)
            new_td[sym] = strat.save()
        return orders, conversions, json.dumps(new_td, separators=(",",":"))
