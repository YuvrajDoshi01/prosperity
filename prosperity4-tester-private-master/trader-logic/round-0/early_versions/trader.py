from datamodel import OrderDepth, UserId, TradingState, Order
from logger import logger
from typing import List, Dict
import json
import math

class Trader:
    """
    Prosperity 4 — Tutorial Round: EMERALDS + TOMATOES
    
    EMERALDS: Stable fair value ~10000. Bots quote 9992/10008 (spread=16).
              We market-make inside the spread with inventory skew.
    
    TOMATOES: Drifting fair value, strongly mean-reverting (autocorr ~ -0.43).
              We track fair via mid-price, market-make around it, skew on position.
    """

    POSITION_LIMITS = {"EMERALDS": 80, "TOMATOES": 80}

    # ── EMERALDS params ──
    EM_FAIR = 10000
    EM_MM_EDGE = 2          # quote 9998 / 10002 → spread = 4
    EM_TAKE_EDGE = 1        # take anything ≥1 inside fair
    EM_SKEW_PER_LOT = 0.05  # tilt fair by 0.05 per unit of position

    # ── TOMATOES params ──
    TOM_MM_EDGE = 2         # quote fair-2 / fair+2
    TOM_TAKE_EDGE = 1       # aggress if price is 1+ inside fair
    TOM_SKEW_PER_LOT = 0.08 # heavier skew — more volatile product

    def bid(self):
        return 15

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        
        # Restore state
        trader_data = {}
        if state.traderData and state.traderData != "":
            try:
                trader_data = json.loads(state.traderData)
            except:
                trader_data = {}

        # ─────────────── EMERALDS ───────────────
        if "EMERALDS" in state.order_depths:
            result["EMERALDS"] = self._trade_emeralds(state)

        # ─────────────── TOMATOES ───────────────
        if "TOMATOES" in state.order_depths:
            orders, trader_data = self._trade_tomatoes(state, trader_data)
            result["TOMATOES"] = orders

        conversions = 0
        trader_data_str = json.dumps(trader_data)
        logger.flush(state, result, conversions, trader_data_str)
        return result, conversions, trader_data_str

    # ═══════════════════════════════════════════════
    #  EMERALDS: tight market-making around 10000
    # ═══════════════════════════════════════════════
    def _trade_emeralds(self, state: TradingState) -> List[Order]:
        product = "EMERALDS"
        orders: List[Order] = []
        od: OrderDepth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.POSITION_LIMITS[product]

        # Skewed fair — push fair down when long, up when short
        fair = self.EM_FAIR - self.EM_SKEW_PER_LOT * pos

        buy_budget = limit - pos    # max we can buy
        sell_budget = limit + pos   # max we can sell

        # ── 1) TAKE mispriced asks (buy cheap) ──
        sorted_asks = sorted(od.sell_orders.items())  # ascending price
        for ask_price, ask_vol in sorted_asks:
            if ask_price < fair - self.EM_TAKE_EDGE and buy_budget > 0:
                qty = min(-ask_vol, buy_budget)
                orders.append(Order(product, ask_price, qty))
                buy_budget -= qty
                pos += qty

        # ── 2) TAKE mispriced bids (sell high) ──
        sorted_bids = sorted(od.buy_orders.items(), reverse=True)  # descending price
        for bid_price, bid_vol in sorted_bids:
            if bid_price > fair + self.EM_TAKE_EDGE and sell_budget > 0:
                qty = min(bid_vol, sell_budget)
                orders.append(Order(product, bid_price, -qty))
                sell_budget -= qty
                pos -= qty

        # ── 3) MAKE — post resting orders inside the bot spread ──
        # Recalculate fair with updated pos
        fair = self.EM_FAIR - self.EM_SKEW_PER_LOT * pos
        
        buy_price = int(round(fair - self.EM_MM_EDGE))
        sell_price = int(round(fair + self.EM_MM_EDGE))

        if buy_budget > 0:
            orders.append(Order(product, buy_price, buy_budget))
        if sell_budget > 0:
            orders.append(Order(product, sell_price, -sell_budget))

        return orders

    # ═══════════════════════════════════════════════
    #  TOMATOES: EMA fair + market-making + mean-reversion
    # ═══════════════════════════════════════════════
    def _trade_tomatoes(self, state: TradingState, trader_data: dict):
        product = "TOMATOES"
        orders: List[Order] = []
        od: OrderDepth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.POSITION_LIMITS[product]

        # Compute current mid from order book
        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None

        if best_bid is not None and best_ask is not None:
            current_mid = (best_bid + best_ask) / 2
        elif best_bid is not None:
            current_mid = best_bid
        elif best_ask is not None:
            current_mid = best_ask
        else:
            return orders, trader_data

        # EMA fair value tracking (alpha = 0.3 — responsive to changes)
        alpha = 0.3
        prev_ema = trader_data.get("tom_ema", current_mid)
        fair = alpha * current_mid + (1 - alpha) * prev_ema
        trader_data["tom_ema"] = fair

        # Inventory skew
        skewed_fair = fair - self.TOM_SKEW_PER_LOT * pos

        buy_budget = limit - pos
        sell_budget = limit + pos

        # ── 1) TAKE mispriced asks ──
        sorted_asks = sorted(od.sell_orders.items())
        for ask_price, ask_vol in sorted_asks:
            if ask_price < skewed_fair - self.TOM_TAKE_EDGE and buy_budget > 0:
                qty = min(-ask_vol, buy_budget)
                orders.append(Order(product, ask_price, qty))
                buy_budget -= qty
                pos += qty

        # ── 2) TAKE mispriced bids ──
        sorted_bids = sorted(od.buy_orders.items(), reverse=True)
        for bid_price, bid_vol in sorted_bids:
            if bid_price > skewed_fair + self.TOM_TAKE_EDGE and sell_budget > 0:
                qty = min(bid_vol, sell_budget)
                orders.append(Order(product, bid_price, -qty))
                sell_budget -= qty
                pos -= qty

        # ── 3) MAKE — post resting orders ──
        skewed_fair = fair - self.TOM_SKEW_PER_LOT * pos  # recalc after takes
        
        buy_price = int(math.floor(skewed_fair - self.TOM_MM_EDGE))
        sell_price = int(math.ceil(skewed_fair + self.TOM_MM_EDGE))

        if buy_budget > 0:
            orders.append(Order(product, buy_price, buy_budget))
        if sell_budget > 0:
            orders.append(Order(product, sell_price, -sell_budget))

        return orders, trader_data
