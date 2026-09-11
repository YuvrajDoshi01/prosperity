import json
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict, Any

"""
v10: OLS Multi-Variate Mean Reversion Model
Derived from historical data regression on Tomatoes.
Features: Order Book Imbalance (OBI), Price Momentum (1-tick), and 5-Tick Moving Average Reversion.
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
    def save(self) -> Any: return None
    def load(self, data: Any): pass

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
        self.window_size = 5  # Optimal window based on -0.47 correlation

    def get_true_value(self, state):
        od = state.order_depths[self.symbol]
        
        # Calculate Current Mid Price
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        mid_price = (best_bid + best_ask) / 2.0
        
        # Update History
        self.price_history.append(mid_price)
        if len(self.price_history) > self.window_size:
            self.price_history.pop(0)

        # We need at least 2 ticks to calculate momentum and MA
        if len(self.price_history) < 2:
            return round(mid_price)

        # 1. Feature: Order Book Imbalance (OBI)
        bid_vol = sum(abs(v) for v in od.buy_orders.values())
        ask_vol = sum(abs(v) for v in od.sell_orders.values())
        total_vol = bid_vol + ask_vol
        obi = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0

        # 2. Feature: 1-Tick Momentum
        prev_mid = self.price_history[-2]
        momentum = mid_price - prev_mid

        # 3. Feature: Moving Average Difference
        ma_5 = sum(self.price_history) / len(self.price_history)
        ma_diff = mid_price - ma_5

        # OLS Regression Coefficients (Derived from historical data)
        coef_obi = 2.6091
        coef_momentum = -0.1314
        coef_ma_diff = -0.4302

        # Predict next tick change
        expected_change = (coef_obi * obi) + (coef_momentum * momentum) + (coef_ma_diff * ma_diff)
        
        # Fair Value = Current Price + Expected Future Change
        fair_value = mid_price + expected_change
        
        return round(fair_value)

    def save(self) -> Any: 
        return self.price_history
        
    def load(self, data: Any):
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