import json
import math
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict, Any

"""
v11.2: The Optimized Hybrid Build
- EMERALDS: Solved Passive MM (Target: 1050)
- TOMATOES: Weighted Microprice + Aggressive MR + High-Threshold Taker
- Fixed Pylance IncompatibleMethodOverride via -> Any
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

class EmeraldsStrategy(Strategy):
    def act(self, state: TradingState):
        od = state.order_depths[self.symbol]
        buys = sorted(od.buy_orders.items(), reverse=True)
        sells = sorted(od.sell_orders.items())
        if not buys or not sells: return

        tv = 10000 
        pos = state.position.get(self.symbol, 0)
        to_buy = self.limit - pos
        to_sell = self.limit + pos

        # 1. Aggressive: Take any sells at or below fair value
        for price, vol in sells:
            if to_buy > 0 and price <= tv:
                qty = min(to_buy, -vol)
                self.buy(price, qty)
                to_buy -= qty

        # 2. Passive: Post buy at best_bid + 1, capped to never cross fair
        if to_buy > 0:
            bid_price = min(tv - 1, buys[0][0] + 1)
            self.buy(bid_price, to_buy)

        # 3. Aggressive: Take any bids at or above fair value
        for price, vol in buys:
            if to_sell > 0 and price >= tv:
                qty = min(to_sell, vol)
                self.sell(price, qty)
                to_sell -= qty

        # 4. Passive: Post sell at best_ask - 1, floored to never cross fair
        if to_sell > 0:
            ask_price = max(tv + 1, sells[0][0] - 1)
            self.sell(ask_price, to_sell)

class TomatoesStrategy(Strategy):
    def __init__(self, symbol: str, limit: int):
        super().__init__(symbol, limit)
        self.price_history = []
        self.window_size = 5
        self.half_spread_cost = 6.5

    def act(self, state: TradingState):
        od = state.order_depths[self.symbol]
        buys = sorted(od.buy_orders.items(), reverse=True)
        sells = sorted(od.sell_orders.items())
        if not buys or not sells: return

        # Weighted Microprice (The v8 Secret Sauce)
        bb, ba = buys[0][0], sells[0][0]
        bv = sum(od.buy_orders.values())
        av = sum(abs(v) for v in od.sell_orders.values())
        microprice = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) / 2.0
        
        self.price_history.append(microprice)
        if len(self.price_history) > self.window_size: 
            self.price_history.pop(0)
        
        # Mean Reversion Signal
        ma_5 = sum(self.price_history) / len(self.price_history)
        ma_diff = microprice - ma_5
        
        # Fair Value Prediction (v8 Drift + MR Correction)
        fv = microprice + 2.21 - (0.43 * ma_diff)
        
        pos = state.position.get(self.symbol, 0)
        to_buy = self.limit - pos
        to_sell = self.limit + pos

        # LAYER 1: AGGRESSIVE TAKER (Higher Threshold to avoid 'Taker Tax')
        # Buffer increased to 2.5 ticks
        for price, vol in sells:
            if to_buy > 0 and (fv - price) > (self.half_spread_cost + 2.5):
                qty = min(to_buy, -vol)
                self.buy(price, qty)
                to_buy -= qty
        
        for price, vol in buys:
            if to_sell > 0 and (price - fv) > (self.half_spread_cost + 2.5):
                qty = min(to_sell, vol)
                self.sell(price, qty)
                to_sell -= qty

        # LAYER 2: PASSIVE MM (Aggressive Inventory Skew)
        # Shift fair value by 0.35 ticks per lot of inventory
        skew = pos * 0.35 
        fv_skew = fv - skew

        if to_buy > 0:
            target_bid = min(int(round(fv_skew - 1)), buys[0][0] + 1)
            # Safety: don't cross spread passively
            self.buy(min(target_bid, sells[0][0] - 1), to_buy)

        if to_sell > 0:
            target_ask = max(int(round(fv_skew + 1)), sells[0][0] - 1)
            # Safety: don't cross spread passively
            self.sell(max(target_ask, buys[0][0] + 1), to_sell)

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
    
    def run(self, state: TradingState):
        # Handle TraderData Persistence
        old_td = json.loads(state.traderData) if state.traderData != "" else {}
        new_td = {}
        orders = {}
        
        for sym, strat in self.strategies.items():
            if sym in old_td: 
                strat.load(old_td.get(sym))
            if sym in state.order_depths:
                orders[sym] = strat.run(state)
            new_td[sym] = strat.save()
            
        return orders, 0, json.dumps(new_td, separators=(",", ":"))