from datamodel import OrderDepth, UserId, TradingState, Order
from logger import logger
from typing import List, Dict
import json
import math
import collections

class Trader:
    """
    Prosperity 4 — Tutorial Round: EMERALDS + TOMATOES
    
    EMERALDS (fair = 10000, stable):
      - Bot spread 9992/10008 (16 wide)
      - Market-make inside spread with position-dependent aggression
      - Take mispriced orders; buy AT fair when short, sell AT fair when long
      - Undercut best bid/ask by 1 to steal priority
    
    TOMATOES (fair drifts, mean-reverting):
      - Regression on last 4 mids to predict next fair value
      - Same position-aware taking + undercutting logic
    """

    position = {"EMERALDS": 0, "TOMATOES": 0}
    POSITION_LIMIT = {"EMERALDS": 80, "TOMATOES": 80}
    
    tomatoes_cache = []
    tomatoes_dim = 4

    def bid(self):
        return 15

    def calc_next_price_tomatoes(self):
        """Linear regression: predict next mid from last 4 mids"""
        coef = [0.123131, 0.165972, 0.253373, 0.456765]
        intercept = 3.787356
        nxt_price = intercept
        for i, val in enumerate(self.tomatoes_cache):
            nxt_price += val * coef[i]
        return int(round(nxt_price))

    def compute_orders_emeralds(self, product, order_depth, acc_bid, acc_ask):
        """
        EMERALDS: stable fair value market-making.
        acc_bid = acc_ask = 10000 (the fair value).
        """
        orders: List[Order] = []
        LIMIT = self.POSITION_LIMIT[product]

        osell = collections.OrderedDict(sorted(order_depth.sell_orders.items()))
        obuy = collections.OrderedDict(sorted(order_depth.buy_orders.items(), reverse=True))

        # Proper best prices
        best_sell_pr = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else acc_ask + 5
        best_buy_pr = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else acc_bid - 5

        cpos = self.position[product]

        # ── BUY SIDE ──
        # 1) Take asks below fair. When short, also take AT fair (aggressive unwind)
        for ask, vol in osell.items():
            if ((ask < acc_bid) or ((self.position[product] < 0) and (ask == acc_bid))) and cpos < LIMIT:
                order_for = min(-vol, LIMIT - cpos)
                cpos += order_for
                orders.append(Order(product, ask, order_for))

        # 2) Post resting buy orders
        undercut_buy = best_buy_pr + 1
        undercut_sell = best_sell_pr - 1
        bid_pr = min(undercut_buy, acc_bid - 1)
        sell_pr = max(undercut_sell, acc_ask + 1)

        # When short → more aggressive (bid closer to fair)
        if (cpos < LIMIT) and (self.position[product] < 0):
            num = LIMIT - cpos
            orders.append(Order(product, min(undercut_buy + 1, acc_bid - 1), num))
            cpos += num

        # When very long → less aggressive (bid further from fair)
        if (cpos < LIMIT) and (self.position[product] > 15):
            num = LIMIT - cpos
            orders.append(Order(product, min(undercut_buy - 1, acc_bid - 1), num))
            cpos += num

        # Remaining capacity at standard undercut
        if cpos < LIMIT:
            num = LIMIT - cpos
            orders.append(Order(product, bid_pr, num))
            cpos += num

        # ── SELL SIDE ──
        cpos = self.position[product]

        # 1) Take bids above fair. When long, also take AT fair
        for bid, vol in obuy.items():
            if ((bid > acc_ask) or ((self.position[product] > 0) and (bid == acc_ask))) and cpos > -LIMIT:
                order_for = max(-vol, -LIMIT - cpos)
                cpos += order_for
                orders.append(Order(product, bid, order_for))

        # When long → more aggressive (ask closer to fair)
        if (cpos > -LIMIT) and (self.position[product] > 0):
            num = -LIMIT - cpos
            orders.append(Order(product, max(undercut_sell - 1, acc_ask + 1), num))
            cpos += num

        # When very short → less aggressive (ask further from fair)
        if (cpos > -LIMIT) and (self.position[product] < -15):
            num = -LIMIT - cpos
            orders.append(Order(product, max(undercut_sell + 1, acc_ask + 1), num))
            cpos += num

        # Remaining capacity at standard undercut
        if cpos > -LIMIT:
            num = -LIMIT - cpos
            orders.append(Order(product, sell_pr, num))
            cpos += num

        return orders

    def compute_orders_tomatoes(self, product, order_depth, acc_bid, acc_ask):
        """
        TOMATOES: regression-predicted fair value market-making.
        acc_bid / acc_ask = predicted_price ∓ 1
        """
        orders: List[Order] = []
        LIMIT = self.POSITION_LIMIT[product]

        osell = collections.OrderedDict(sorted(order_depth.sell_orders.items()))
        obuy = collections.OrderedDict(sorted(order_depth.buy_orders.items(), reverse=True))

        best_sell_pr = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else acc_ask + 5
        best_buy_pr = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else acc_bid - 5

        cpos = self.position[product]

        # ── BUY SIDE ──
        for ask, vol in osell.items():
            if ((ask <= acc_bid) or ((self.position[product] < 0) and (ask == acc_bid + 1))) and cpos < LIMIT:
                order_for = min(-vol, LIMIT - cpos)
                cpos += order_for
                orders.append(Order(product, ask, order_for))

        undercut_buy = best_buy_pr + 1
        undercut_sell = best_sell_pr - 1
        bid_pr = min(undercut_buy, acc_bid)
        sell_pr = max(undercut_sell, acc_ask)

        if cpos < LIMIT:
            num = LIMIT - cpos
            orders.append(Order(product, bid_pr, num))
            cpos += num

        # ── SELL SIDE ──
        cpos = self.position[product]

        for bid, vol in obuy.items():
            if ((bid >= acc_ask) or ((self.position[product] > 0) and (bid + 1 == acc_ask))) and cpos > -LIMIT:
                order_for = max(-vol, -LIMIT - cpos)
                cpos += order_for
                orders.append(Order(product, bid, order_for))

        if cpos > -LIMIT:
            num = -LIMIT - cpos
            orders.append(Order(product, sell_pr, num))
            cpos += num

        return orders

    def run(self, state: TradingState):
        result = {"EMERALDS": [], "TOMATOES": []}

        # Sync positions
        for key, val in state.position.items():
            self.position[key] = val

        # Restore state if class vars got wiped
        if state.traderData and state.traderData != "" and len(self.tomatoes_cache) == 0:
            try:
                td = json.loads(state.traderData)
                self.tomatoes_cache = td.get("tom_cache", [])
            except:
                pass

        # ═══ EMERALDS: fixed fair = 10000 ═══
        if "EMERALDS" in state.order_depths:
            result["EMERALDS"] = self.compute_orders_emeralds(
                "EMERALDS", state.order_depths["EMERALDS"],
                acc_bid=10000, acc_ask=10000
            )

        # ═══ TOMATOES: regression fair ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            
            best_bid = max(od.buy_orders.keys()) if od.buy_orders else 0
            best_ask = min(od.sell_orders.keys()) if od.sell_orders else 0
            tom_mid = (best_bid + best_ask) / 2

            if len(self.tomatoes_cache) == self.tomatoes_dim:
                self.tomatoes_cache.pop(0)
            self.tomatoes_cache.append(tom_mid)

            INF = int(1e9)
            tom_lb = -INF  # no signal yet → don't take
            tom_ub = INF

            if len(self.tomatoes_cache) == self.tomatoes_dim:
                predicted = self.calc_next_price_tomatoes()
                tom_lb = predicted - 1
                tom_ub = predicted + 1

            result["TOMATOES"] = self.compute_orders_tomatoes(
                "TOMATOES", state.order_depths["TOMATOES"],
                acc_bid=tom_lb, acc_ask=tom_ub
            )

        traderData = json.dumps({"tom_cache": self.tomatoes_cache})
        conversions = 0
        logger.flush(state, result, conversions, traderData)
        return result, conversions, traderData
