import json
import math
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict, Any  # Added Any here

"""
v9: Dynamic Stochastic Expectation Model (Ornstein-Uhlenbeck)
Replaced static microprice regression with dynamic mean-reverting expectations.
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
    
    def save(self) -> Any:  # Type hint added here
        return None
        
    def load(self, data: Any):  # Type hint added here
        pass

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
        self.price_history = []
        self.window_size = 20  # Lookback window for long-term mean
        self.theta = 0.1       # Speed of mean reversion (dynamically updated)
        self.dt = 1.0          # 1 tick forward

    def compute_microprice(self, od):
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        bv = sum(abs(v) for v in od.buy_orders.values())
        av = sum(abs(v) for v in od.sell_orders.values())
        t = bv + av
        if t == 0: return (bb + ba) / 2
        return bb + (bv / t) * (ba - bb)

    def calculate_mu(self):
        if not self.price_history:
            return 0.0
        return sum(self.price_history) / len(self.price_history)

    def estimate_theta(self):
        # Dynamically estimate theta based on recent price action
        if len(self.price_history) < 10:
            return
            
        x = self.price_history[:-1]
        y = [self.price_history[i] - self.price_history[i-1] for i in range(1, len(self.price_history))]
        
        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)
        
        variance = sum((xi - mean_x) ** 2 for xi in x)
        if variance > 0:
            covariance = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x)))
            slope = covariance / variance
            # Bound theta to prevent erratic behaviors from sudden spikes
            self.theta = max(0.01, min(-slope, 0.5))

    def get_true_value(self, state):
        od = state.order_depths[self.symbol]
        mp = self.compute_microprice(od)
        
        # Update history
        self.price_history.append(mp)
        if len(self.price_history) > self.window_size:
            self.price_history.pop(0)

        # Need at least 2 points to start doing basic math
        if len(self.price_history) < 2:
            return round(mp)
            
        # Calculate dynamic parameters
        mu = self.calculate_mu()
        self.estimate_theta()
        
        # Apply closed-form expectation (Feynman-Kac expectation of OU process)
        decay_factor = math.exp(-self.theta * self.dt)
        expected_value = (mp * decay_factor) + (mu * (1 - decay_factor))
        
        return round(expected_value)

    def save(self): 
        return self.price_history
        
    def load(self, data):
        if data is not None: 
            self.price_history = data

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