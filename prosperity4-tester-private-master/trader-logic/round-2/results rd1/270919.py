# Strategy 1: Combined
# Pepper from 228959 (Nancy's trend-following, original params/bugs) + Osmium from 145452
#
# Osmium uses 145452 (structurally proven, no overfit to 3-day sample):
#   - FV=10000 is the true mean (verified: zero drift across all days)
#   - Multi-level sweep, inclusive taking at FV, liquidation mechanism
#   - No directional model on a driftless product = no spurious bets
#
# Pepper is unmodified 228959 — serves as baseline to isolate pepper fix impact
# when compared against strategy_improved.py

from datamodel import OrderDepth, TradingState, Order
import numpy as np
import math
import json

## ═══ POSITION LIMITS ═══
POS_LIMITS = {
    "ASH_COATED_OSMIUM": 80,
    "INTARIAN_PEPPER_ROOT": 80
}

## ═══ OSMIUM PARAMS (145452 — structurally proven) ═══
ACO_FV = 10000
ACO_AGGRESSION_THRESHOLD = 40
ACO_LIQUIDATION_WINDOW = 10

## ═══ PEPPER PARAMS (from 228959 — original, unfixed) ═══
PEPPER_PARAMS = {
    "spread_gradient": 0.0010586880760,
    "spread_intercept": 0.8694130152902
}


class Trader:

    def bid(self):
        return 2000

    ## ═══ REGRESSION SLOPE ═══
    def regression_slope(self, prices):
        x = np.arange(len(prices))
        y = np.array(prices)
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        denom = np.sum((x - x_mean) ** 2)
        if denom == 0:
            return 0.0
        slope = np.sum((x - x_mean) * (y - y_mean)) / denom
        return slope

    ## ═══ WALL-MID ═══
    def get_wall_mid(self, order_depth: OrderDepth):
        best_vol = 0
        deep_bid = 0
        for bid in order_depth.buy_orders:
            if order_depth.buy_orders[bid] > best_vol:
                best_vol = order_depth.buy_orders[bid]
                deep_bid = bid

        best_vol = 0
        deep_ask = 0
        for ask in order_depth.sell_orders:
            if order_depth.sell_orders[ask] < best_vol:
                best_vol = order_depth.sell_orders[ask]
                deep_ask = ask

        return (deep_bid + deep_ask) / 2

    ## ═══ ASH_COATED_OSMIUM — 145452 architecture ═══
    def _trade_osmium(self, product, order_depth, pos, limit, aco_liq):
        orders = []
        book = order_depth
        has_bids = bool(book.buy_orders)
        has_asks = bool(book.sell_orders)

        if not (has_bids or has_asks):
            return orders, aco_liq

        buy_cap = limit - pos
        sell_cap = limit + pos
        fv_int = ACO_FV

        best_bid = max(book.buy_orders) if has_bids else None
        best_ask = min(book.sell_orders) if has_asks else None

        # Liquidation tracking
        aco_liq.append(abs(pos) == limit)
        if len(aco_liq) > ACO_LIQUIDATION_WINDOW:
            aco_liq = aco_liq[-ACO_LIQUIDATION_WINDOW:]
        soft = (len(aco_liq) == ACO_LIQUIDATION_WINDOW
                and sum(aco_liq) >= 5 and aco_liq[-1])
        hard = (len(aco_liq) == ACO_LIQUIDATION_WINDOW
                and all(aco_liq))

        # Position-aware aggression (inclusive at FV when inventory is low)
        max_buy = fv_int if pos <= ACO_AGGRESSION_THRESHOLD else fv_int - 1
        min_sell = fv_int if pos >= -ACO_AGGRESSION_THRESHOLD else fv_int + 1

        # Multi-level sweep: take all asks ≤ max_buy
        if has_asks:
            for price, vol in sorted(book.sell_orders.items()):
                if buy_cap > 0 and price <= max_buy:
                    qty = min(buy_cap, -vol)
                    orders.append(Order(product, price, qty))
                    buy_cap -= qty

        # Multi-level sweep: take all bids ≥ min_sell
        if has_bids:
            for price, vol in sorted(book.buy_orders.items(), reverse=True):
                if sell_cap > 0 and price >= min_sell:
                    qty = min(sell_cap, vol)
                    orders.append(Order(product, price, -qty))
                    sell_cap -= qty

        # Liquidation: hard = at FV, soft = near FV
        if buy_cap > 0 and hard:
            orders.append(Order(product, fv_int, buy_cap // 2))
            buy_cap -= buy_cap // 2
        if buy_cap > 0 and soft:
            orders.append(Order(product, fv_int - 2, buy_cap // 2))
            buy_cap -= buy_cap // 2
        if sell_cap > 0 and hard:
            orders.append(Order(product, fv_int, -(sell_cap // 2)))
            sell_cap -= sell_cap // 2
        if sell_cap > 0 and soft:
            orders.append(Order(product, fv_int + 2, -(sell_cap // 2)))
            sell_cap -= sell_cap // 2

        # Market making around FV
        if has_bids and has_asks:
            if buy_cap > 0:
                bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                orders.append(Order(product, bp, buy_cap))
            if sell_cap > 0:
                ap = max(fv_int + 1, best_ask - 1, best_bid + 1)
                orders.append(Order(product, ap, -sell_cap))
        elif has_bids:
            if buy_cap > 0:
                orders.append(Order(product, min(fv_int - 1, best_bid + 1), buy_cap))
            if sell_cap > 0:
                orders.append(Order(product, fv_int + 1, -sell_cap))
        elif has_asks:
            if sell_cap > 0:
                orders.append(Order(product, max(fv_int + 1, best_ask - 1), -sell_cap))
            if buy_cap > 0:
                orders.append(Order(product, fv_int - 1, buy_cap))

        return orders, aco_liq

    ## ═══ INTARIAN_PEPPER_ROOT — 228959's trend-following (original, unfixed) ═══
    def _trade_pepper(self, product, order_depth, pos, limit, prev_mids, slope, directions):
        orders = []

        wall_mid = prev_mids[-1] + slope if prev_mids is not None else 10000
        best_ask = best_bid = None

        if order_depth.buy_orders and order_depth.sell_orders:
            wall_mid = self.get_wall_mid(order_depth)
            best_ask, ask_quantity = list(order_depth.sell_orders.items())[0]
            best_bid, bid_quantity = list(order_depth.buy_orders.items())[0]
        elif order_depth.sell_orders:
            best_ask, ask_quantity = list(order_depth.sell_orders.items())[0]
        elif order_depth.buy_orders:
            best_bid, bid_quantity = list(order_depth.buy_orders.items())[0]

        prev_mids = [wall_mid] if prev_mids is None else prev_mids + [wall_mid]
        if len(prev_mids) > 5:
            prev_mids.pop(0)
            slope = self.regression_slope(prev_mids)
        else:
            slope = 0

        trend = 1 if slope >= 0 else -1
        directions = [trend] if directions is None else directions + [trend]
        if len(directions) > 20:
            directions.pop(0)
        indicator = directions.count(1) / len(directions)

        buy_cap = limit - pos
        sell_cap = limit + pos

        m = PEPPER_PARAMS.get("spread_gradient")
        c = PEPPER_PARAMS.get("spread_intercept")
        mid_spread = (m * wall_mid + c) / 2

        if indicator >= 0.5:
            target = 80

            if pos <= 0.9 * target and len(prev_mids) == 5:
                fair_purchase = math.floor(wall_mid + mid_spread)
                best_ask = min(best_ask, fair_purchase) if best_ask else fair_purchase
                orders.append(Order(product, best_ask, buy_cap))

            elif pos < target:
                if best_ask and best_ask <= wall_mid:
                    buy_quantity = min(buy_cap, -ask_quantity)
                    orders.append(Order(product, best_ask, buy_quantity))
                    buy_cap -= buy_quantity
                if best_bid and best_bid < wall_mid - mid_spread / 2:
                    orders.append(Order(product, best_bid + 1, buy_cap))

            elif best_ask and best_ask > wall_mid + mid_spread / 2:
                orders.append(Order(product, best_ask - 1, -sell_cap))

        else:
            target = -80

            if pos >= 0.9 * target and len(prev_mids) == 10:
                if best_bid:
                    orders.append(Order(product, best_bid, -sell_cap))
                else:
                    orders.append(Order(product, math.floor(wall_mid - mid_spread), -sell_cap))

            elif pos > target:
                if best_bid and best_bid >= wall_mid:
                    sell_quantity = min(sell_cap, bid_quantity)
                    orders.append(Order(product, best_bid, -sell_quantity))
                    sell_cap -= sell_quantity
                if best_ask and best_ask > wall_mid + mid_spread / 2:
                    orders.append(Order(product, best_ask - 1, -sell_cap))

            elif best_bid and best_bid < wall_mid - mid_spread / 2:
                orders.append(Order(product, best_bid + 1, buy_cap))

        return orders, prev_mids, slope, directions

    ## ═══ RUN ═══
    def run(self, state: TradingState):
        result = {}

        pstate: dict = {}
        if state.traderData:
            try:
                pstate = json.loads(state.traderData)
            except Exception:
                pstate = {}

        for product, order_depth in state.order_depths.items():
            position = state.position.get(product, 0)
            limit = POS_LIMITS.get(product, 20)

            if product == "ASH_COATED_OSMIUM":
                aco_liq = pstate.get("ACO_LIQ", [])
                orders, aco_liq = self._trade_osmium(product, order_depth, position, limit, aco_liq)
                pstate["ACO_LIQ"] = aco_liq

            elif product == "INTARIAN_PEPPER_ROOT":
                prev_mids = pstate.get("PREV_PEPPER_MIDS")
                prev_slope = pstate.get("PEPPER_SLOPE")
                prev_directions = pstate.get("PEPPER_DIRECTIONS")
                orders, pepper_mids, slope, directions = self._trade_pepper(
                    product, order_depth, position, limit, prev_mids, prev_slope, prev_directions
                )
                pstate["PREV_PEPPER_MIDS"] = pepper_mids
                pstate["PEPPER_SLOPE"] = slope
                pstate["PEPPER_DIRECTIONS"] = directions

            else:
                orders = []

            result[product] = orders

        conversions = 0
        return result, conversions, json.dumps(pstate)