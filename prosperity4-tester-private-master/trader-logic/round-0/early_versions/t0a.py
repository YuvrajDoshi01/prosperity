import json
import math
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict, Any

"""
v11.1: The Final Competition Build
EMERALDS: Solved Passive MM (Target PnL: 1050)
TOMATOES: Hybrid Aggressive Mean Reversion (Target PnL: 2700+)
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

        tv = 10000 # Fixed fair value for Emeralds
        pos = state.position.get(self.symbol, 0)
        to_buy = self.limit - pos
        to_sell = self.limit + pos

        # 1. Take any sells at or below 10,000
        for price, vol in sells:
            if to_buy > 0 and price <= tv:
                qty = min(to_buy, -vol)
                self.buy(price, qty)
                to_buy -= qty

        # 2. Post passive buy at best_bid + 1 (capped at 9999)
        if to_buy > 0:
            bid_price = min(tv - 1, buys[0][0] + 1)
            self.buy(bid_price, to_buy)

        # 3. Take any bids at or above 10,000
        for price, vol in buys:
            if to_sell > 0 and price >= tv:
                qty = min(to_sell, vol)
                self.sell(price, qty)
                to_sell -= qty

        # 4. Post passive sell at best_ask - 1 (floored at 10001)
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

        # Use the Weighted Microprice from your winning v8
        # This captures the 'internal' book pressure better
        bb, ba = buys[0][0], sells[0][0]
        bv, av = sum(od.buy_orders.values()), sum(abs(v) for v in od.sell_orders.values())
        microprice = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) / 2.0
        
        self.price_history.append(microprice)
        if len(self.price_history) > self.window_size: self.price_history.pop(0)
        
        # Calculate Reversion Signal
        ma_5 = sum(self.price_history) / len(self.price_history)
        ma_diff = microprice - ma_5
        
        # HYBRID FAIR VALUE: 
        # Base fv on microprice + 2.21 drift + mean reversion correction
        fv = microprice + 2.21 - (0.43 * ma_diff)
        
        pos = state.position.get(self.symbol, 0)
        to_buy = self.limit - pos
        to_sell = self.limit + pos

        # LAYER 1: AGGRESSIVE TAKER (Higher Threshold)
        # Increased buffer to 2.5 to ensure we only take 'guaranteed' profit
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

        # LAYER 2: PASSIVE MM (Aggressive Skew)
        # Increased skew to 0.35 to keep inventory more active
        skew = pos * 0.35 
        fv_skew = fv - skew

        if to_buy > 0:
            # We target a price that is 1 tick better than the best bid, but capped by our fv_skew
            target_bid = min(int(round(fv_skew - 1)), buys[0][0] + 1)
            # Safety: don't cross spread in passive layer
            self.buy(min(target_bid, sells[0][0] - 1), to_buy)

        if to_sell > 0:
            target_ask = max(int(round(fv_skew + 1)), sells[0][0] - 1)
            # Safety: don't cross spread in passive layer
            self.sell(max(target_ask, buys[0][0] + 1), to_sell)
    def save(self): return self.price_history
    def load(self, data):
        if data is not None: self.price_history = data

class Trader:
    def __init__(self):
        self.strategies = {
            "EMERALDS": EmeraldsStrategy("EMERALDS", 80),
            "TOMATOES": TomatoesStrategy("TOMATOES", 80),
        }
    
    def run(self, state: TradingState):
        old_td = json.loads(state.traderData) if state.traderData != "" else {}
        new_td, orders = {}, {}
        for sym, strat in self.strategies.items():
            if sym in old_td: strat.load(old_td.get(sym))
            if sym in state.order_depths:
                orders[sym] = strat.run(state)
            new_td[sym] = strat.save()
        return orders, 0, json.dumps(new_td, separators=(",", ":"))