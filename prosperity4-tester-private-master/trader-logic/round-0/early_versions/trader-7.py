import json
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict

"""
v8: Microprice regression + NO liquidation.
Liquidation costs ~7/unit at EMERALDS (sell at 10000 vs normal 10007).
At 1000 iterations, being stuck at limit is rare and opportunity cost is low.
Removing liquidation should net improve PnL.
"""

class Strategy:
    def __init__(self, symbol, limit):
        self.symbol = symbol
        self.limit = limit
    def act(self, state): raise NotImplementedError()
    def run(self, state):
        self.orders = []
        self.act(state)
        return self.orders
    def buy(self, price, qty): self.orders.append(Order(self.symbol, price, qty))
    def sell(self, price, qty): self.orders.append(Order(self.symbol, price, -qty))
    def save(self): return None
    def load(self, data): pass

class MarketMakingStrategy(Strategy):
    def get_true_value(self, state): raise NotImplementedError()

    def act(self, state):
        od = state.order_depths[self.symbol]
        buys = sorted(od.buy_orders.items(), reverse=True)
        sells = sorted(od.sell_orders.items())
        if not buys or not sells: return

        tv = self.get_true_value(state)
        pos = state.position.get(self.symbol, 0)
        to_buy = self.limit - pos
        to_sell = self.limit + pos

        # Take mispriced asks (buy at/below fair)
        for price, vol in sells:
            if to_buy > 0 and price <= tv:
                qty = min(to_buy, -vol)
                self.buy(price, qty)
                to_buy -= qty

        # Post remaining buy: undercut best bid, capped at fair
        if to_buy > 0:
            self.buy(min(tv, buys[0][0] + 1), to_buy)

        # Take mispriced bids (sell at/above fair)
        for price, vol in buys:
            if to_sell > 0 and price >= tv:
                qty = min(to_sell, vol)
                self.sell(price, qty)
                to_sell -= qty

        # Post remaining sell: undercut best ask, floored at fair
        if to_sell > 0:
            self.sell(max(tv, sells[0][0] - 1), to_sell)

class EmeraldsStrategy(MarketMakingStrategy):
    def get_true_value(self, state): return 10_000

class TomatoesStrategy(MarketMakingStrategy):
    def __init__(self, symbol, limit):
        super().__init__(symbol, limit)
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

    def get_true_value(self, state):
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

    def save(self): return self.cache
    def load(self, data):
        if data is not None: self.cache = data

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
