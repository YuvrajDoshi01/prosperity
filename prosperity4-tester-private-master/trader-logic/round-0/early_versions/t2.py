import json
import math
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict, Any

"""
v12: The Sniper (Refined Alpha)
- EMERALDS: Solved (1050 target)
- TOMATOES: Weighted Microprice + EMA Reversion + Sniper Taker Layer
- Re-integrating the 6913.py coefficients as a secondary 'Nudge' signal.
"""

class Strategy:
    def __init__(self, symbol: str, limit: int):
        self.symbol = symbol
        self.limit = limit
        
    def act(self, state: TradingState): raise NotImplementedError()
        
    def run(self, state: TradingState) -> List[Order]:
        self.orders = []
        self.act(state)
        return self.orders
        
    def buy(self, price: int, qty: int): self.orders.append(Order(self.symbol, price, qty))
    def sell(self, price, qty: int): self.orders.append(Order(self.symbol, price, -qty))
    def save(self) -> Any: return None
    def load(self, data: Any): pass

class EmeraldsStrategy(Strategy):
    def act(self, state: TradingState):
        od = state.order_depths[self.symbol]
        buys = sorted(od.buy_orders.items(), reverse=True)
        sells = sorted(od.sell_orders.items())
        if not buys or not sells: return

        tv = 10000 
        pos = state.position.get(self.symbol, 0)
        to_buy, to_sell = self.limit - pos, self.limit + pos

        for p, v in sells:
            if to_buy > 0 and p <= tv:
                q = min(to_buy, -v)
                self.buy(p, q); to_buy -= q

        if to_buy > 0:
            self.buy(min(tv - 1, buys[0][0] + 1), to_buy)

        for p, v in buys:
            if to_sell > 0 and p >= tv:
                q = min(to_sell, v)
                self.sell(p, q); to_sell -= q

        if to_sell > 0:
            self.sell(max(tv + 1, sells[0][0] - 1), to_sell)

class TomatoesStrategy(Strategy):
    def __init__(self, symbol: str, limit: int):
        super().__init__(symbol, limit)
        self.ema = None
        self.alpha = 0.4 # Smoothing factor for EMA
        self.cache = []

    def act(self, state: TradingState):
        od = state.order_depths[self.symbol]
        buys = sorted(od.buy_orders.items(), reverse=True)
        sells = sorted(od.sell_orders.items())
        if not buys or not sells: return

        # 1. Weighted Microprice (The core signal)
        bb, ba = buys[0][0], sells[0][0]
        bv, av = sum(od.buy_orders.values()), sum(abs(v) for v in od.sell_orders.values())
        mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) / 2.0
        
        # 2. Update EMA (Faster reaction to trend changes)
        if self.ema is None: self.ema = mp
        else: self.ema = (self.alpha * mp) + (1 - self.alpha) * self.ema
        
        # 3. Microprice Lag Prediction (The 6913.py coefficients)
        self.cache.append(mp)
        if len(self.cache) > 4: self.cache.pop(0)
        
        lag_pred = 0
        if len(self.cache) == 4:
            coefs = [0.06, 0.12, 0.24, 0.58] # Simplified 6913.py weights
            for i, v in enumerate(self.cache): lag_pred += v * coefs[i]
            lag_pred += 2.21 # The Drift Intercept
        else:
            lag_pred = mp

        # 4. Final Fair Value (Blend of EMA and Lag-Regression)
        fv = (0.7 * lag_pred) + (0.3 * self.ema)
        
        pos = state.position.get(self.symbol, 0)
        to_buy, to_sell = self.limit - pos, self.limit + pos

        # --- LAYER 1: SNIPER TAKER (Strict threshold) ---
        # Only take if profit > half spread + 5.0 tick buffer
        for p, v in sells:
            if to_buy > 0 and (fv - p) > 11.5:
                q = min(to_buy, -v)
                self.buy(p, q); to_buy -= q
        
        for p, v in buys:
            if to_sell > 0 and (p - fv) > 11.5:
                q = min(to_sell, v)
                self.sell(p, q); to_sell -= q

        # --- LAYER 2: PASSIVE MARKET MAKING ---
        # Inventory Skew: 0.2 ticks per lot (Balanced)
        skew = pos * 0.2 
        fv_skew = fv - skew

        if to_buy > 0:
            target_bid = min(int(round(fv_skew - 1)), buys[0][0] + 1)
            self.buy(min(target_bid, sells[0][0] - 1), to_buy)

        if to_sell > 0:
            target_ask = max(int(round(fv_skew + 1)), sells[0][0] - 1)
            self.sell(max(target_ask, buys[0][0] + 1), to_sell)

    def save(self) -> Any: return {"ema": self.ema, "cache": self.cache}
    def load(self, data: Any):
        if data:
            self.ema = data.get("ema")
            self.cache = data.get("cache", [])

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
            if sym in state.order_depths: orders[sym] = strat.run(state)
            new_td[sym] = strat.save()
        return orders, 0, json.dumps(new_td, separators=(",", ":"))