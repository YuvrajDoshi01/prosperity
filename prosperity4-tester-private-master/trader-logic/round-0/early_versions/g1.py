import json
import math
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict, Any

"""
v9: Dynamic Stochastic Expectation Model (Ornstein-Uhlenbeck) + Dual Layer Execution
- Replaced static microprice regression with dynamic mean-reverting expectations.
- Maintains dual-layer volume splitting for optimal queue priority and spread capture.
- Includes self-trading protection and strict edge requirements for taking volume.
"""

class Strategy:
    def __init__(self, symbol: str, limit: int):
        self.symbol = symbol
        self.limit = limit
        
    def act(self, state: TradingState): 
        raise NotImplementedError()
    
    def run(self, state: TradingState) -> List[Order]:
        self.orders = []
        self.act(state)
        return self.orders
        
    def buy(self, price: int, qty: int): 
        self.orders.append(Order(self.symbol, price, qty))
    
    def sell(self, price: int, qty: int): 
        self.orders.append(Order(self.symbol, price, -qty))
    
    def save(self) -> Any:
        return None
        
    def load(self, data: Any):
        pass

class MarketMakingStrategy(Strategy):
    def get_true_value(self, state: TradingState) -> float: 
        raise NotImplementedError()

    def act(self, state: TradingState):
        od = state.order_depths[self.symbol]
        buys = sorted(od.buy_orders.items(), reverse=True)
        sells = sorted(od.sell_orders.items())
        if not buys or not sells: return

        best_bid = buys[0][0]
        best_ask = sells[0][0]

        tv = self.get_true_value(state)
        pos = state.position.get(self.symbol, 0)
        to_buy = self.limit - pos
        to_sell = self.limit + pos

        target_bid = min(int(tv), best_bid + 1)
        target_ask = max(int(tv), best_ask - 1)

        # CRITICAL: Prevent self-trading
        if target_bid >= target_ask:
            target_bid = int(tv) - 1
            target_ask = int(tv) + 1

        # Take mispriced asks (Require at least 1 tick of edge vs fair value)
        for price, vol in sells:
            if to_buy > 0 and price < tv:
                qty = min(to_buy, -vol)
                self.buy(price, qty)
                to_buy -= qty

        # Take mispriced bids (Require at least 1 tick of edge vs fair value)
        for price, vol in buys:
            if to_sell > 0 and price > tv:
                qty = min(to_sell, vol)
                self.sell(price, qty)
                to_sell -= qty

        # Post remaining inventory in dual-layer quotes.
        if to_buy > 0:
            tier1_qty = to_buy // 2
            tier2_qty = to_buy - tier1_qty
            if tier1_qty > 0: self.buy(target_bid, tier1_qty)
            if tier2_qty > 0: self.buy(target_bid - 1, tier2_qty)

        if to_sell > 0:
            tier1_qty = to_sell // 2
            tier2_qty = to_sell - tier1_qty
            if tier1_qty > 0: self.sell(target_ask, tier1_qty)
            if tier2_qty > 0: self.sell(target_ask + 1, tier2_qty)


class EmeraldsStrategy(MarketMakingStrategy):
    def get_true_value(self, state: TradingState) -> float: 
        return 10000.0


class TomatoesStrategy(MarketMakingStrategy):
    def __init__(self, symbol: str, limit: int):
        super().__init__(symbol, limit)
        self.price_history = []
        self.window_size = 20  # Lookback window for long-term mean
        self.theta = 0.1       # Speed of mean reversion (dynamically updated)
        self.dt = 1.0          # 1 tick forward

    def compute_microprice(self, od: OrderDepth) -> float:
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        bv = sum(abs(v) for v in od.buy_orders.values())
        av = sum(abs(v) for v in od.sell_orders.values())
        t = bv + av
        if t == 0: return (bb + ba) / 2.0
        return bb + (bv / t) * (ba - bb)

    def calculate_mu(self) -> float:
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
        
        # Guard against zero variance dividing by zero
        if variance > 0:
            covariance = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x)))
            slope = covariance / variance
            # Bound theta to prevent erratic behaviors from sudden spikes
            self.theta = max(0.01, min(-slope, 0.5))

    def get_true_value(self, state: TradingState) -> float:
        od = state.order_depths[self.symbol]
        mp = self.compute_microprice(od)
        
        # Update history
        self.price_history.append(mp)
        if len(self.price_history) > self.window_size:
            self.price_history.pop(0)

        # Need at least 2 points to start doing basic math
        if len(self.price_history) < 2:
            return float(round(mp))
            
        # Calculate dynamic parameters
        mu = self.calculate_mu()
        self.estimate_theta()
        
        # Apply closed-form expectation (Feynman-Kac expectation of OU process)
        decay_factor = math.exp(-self.theta * self.dt)
        expected_value = (mp * decay_factor) + (mu * (1 - decay_factor))
        
        return float(round(expected_value))

    def save(self) -> Any: 
        return self.price_history
        
    def load(self, data: Any):
        if data is not None: 
            self.price_history = data


class Trader:
    def __init__(self):
        self.strategies = {
            "EMERALDS": EmeraldsStrategy("EMERALDS", 80), # Adjust limit to 20 if standard rules apply
            "TOMATOES": TomatoesStrategy("TOMATOES", 80), # Adjust limit to 20 if standard rules apply
        }
    
    def run(self, state: TradingState):
        conversions = 0
        old_td = json.loads(state.traderData) if state.traderData != "" else {}
        new_td = {}
        orders = {}
        
        for sym, strat in self.strategies.items():
            if sym in old_td: 
                strat.load(old_td.get(sym))
            if sym in state.order_depths: 
                orders[sym] = strat.run(state)
            new_td[sym] = strat.save()
            
        return orders, conversions, json.dumps(new_td, separators=(",",":"))