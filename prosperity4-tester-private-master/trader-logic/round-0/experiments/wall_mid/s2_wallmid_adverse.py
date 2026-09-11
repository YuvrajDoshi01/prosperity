import json
from datamodel import OrderDepth, Order, TradingState
from typing import List, Dict, Any

"""
s2_wallmid_split: Wall Mid + Split-Level Quoting

Hypothesis: Real HFT firms don't post all capacity at one price.
Split passive orders across two levels:
  - Aggressive: 40% at best±1 (higher fill rate, thinner edge)
  - Passive: 60% at wall±1 (thicker edge, lower fill rate)

This captures fills from BOTH bot types and market conditions.
Zero fitted parameters. Fair value = Wall Mid.
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
        if qty > 0:
            self.orders.append(Order(self.symbol, price, qty))

    def sell(self, price: int, qty: int):
        if qty > 0:
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

        if to_buy > 0:
            self.buy(min(tv - 1, buys[0][0] + 1), to_buy)

        for p, v in buys:
            if to_sell > 0 and p >= tv:
                q = min(to_sell, v)
                self.sell(p, q)
                to_sell -= q

        if to_sell > 0:
            self.sell(max(tv + 1, sells[0][0] - 1), to_sell)


class TomatoesStrategy(Strategy):
    def act(self, state: TradingState):
        od = state.order_depths[self.symbol]
        buys = sorted(od.buy_orders.items(), reverse=True)
        sells = sorted(od.sell_orders.items())
        if not buys or not sells:
            return

        # Wall Mid: midpoint of highest-volume levels
        wall_bid = max(od.buy_orders.items(), key=lambda x: x[1])[0]
        wall_ask = max(od.sell_orders.items(), key=lambda x: abs(x[1]))[0]
        tv = round((wall_bid + wall_ask) / 2)

        best_bid, best_ask = buys[0][0], sells[0][0]
        pos = state.position.get(self.symbol, 0)
        to_buy = self.limit - pos
        to_sell = self.limit + pos

        # === TAKE at/below fair ===
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

        # === MAKE: Split across two levels ===
        # Level 1 (aggressive): 40% at best±1
        # Level 2 (passive): 60% at wall_bid+1 / wall_ask-1
        if to_buy > 0:
            aggressive_qty = max(1, int(to_buy * 0.4))
            passive_qty = to_buy - aggressive_qty

            agg_bid = min(tv - 1, best_bid + 1)
            agg_bid = min(agg_bid, best_ask - 1)
            self.buy(int(agg_bid), aggressive_qty)

            pas_bid = min(tv - 1, wall_bid + 1)
            pas_bid = min(pas_bid, best_ask - 1)
            if pas_bid < agg_bid and passive_qty > 0:
                self.buy(int(pas_bid), passive_qty)
            elif passive_qty > 0:
                # Wall is at same level as L1, post everything aggressive
                self.buy(int(agg_bid), passive_qty)

        if to_sell > 0:
            aggressive_qty = max(1, int(to_sell * 0.4))
            passive_qty = to_sell - aggressive_qty

            agg_ask = max(tv + 1, best_ask - 1)
            agg_ask = max(agg_ask, best_bid + 1)
            self.sell(int(agg_ask), aggressive_qty)

            pas_ask = max(tv + 1, wall_ask - 1)
            pas_ask = max(pas_ask, best_bid + 1)
            if pas_ask > agg_ask and passive_qty > 0:
                self.sell(int(pas_ask), passive_qty)
            elif passive_qty > 0:
                self.sell(int(agg_ask), passive_qty)


class Trader:
    def __init__(self):
        self.strategies = {
            "EMERALDS": EmeraldsStrategy("EMERALDS", 80),
            "TOMATOES": TomatoesStrategy("TOMATOES", 80),
        }

    def bid(self):
        return 15

    def run(self, state: TradingState):
        old_td = json.loads(state.traderData) if state.traderData != "" else {}
        new_td, orders = {}, {}
        for sym, strat in self.strategies.items():
            if sym in old_td:
                strat.load(old_td.get(sym))
            if sym in state.order_depths:
                orders[sym] = strat.run(state)
            new_td[sym] = strat.save()
        return orders, 0, json.dumps(new_td, separators=(",", ":"))
