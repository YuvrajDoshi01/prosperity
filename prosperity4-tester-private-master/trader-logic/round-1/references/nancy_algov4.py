# Round 1, Algorithm v4 - Getting Osmium right. Peppers locked in.
# Nancy's Discord submission — website score ~10,700
# Source: teammate shared in Discord 2026-04-17

## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##
from datamodel import OrderDepth, UserId, TradingState, Order
import numpy as np
import math
import json

## GENERAL ##  ## GENERAL ##  ## GENERAL ##  ## GENERAL ##  ## GENERAL ##
POS_LIMITS = {
    "ASH_COATED_OSMIUM": 80,
    "INTARIAN_PEPPER_ROOT": 80
}

OSMIUM_PARAMS = {
    "alpha": 0.0294,
    "beta": 1.145,
    "gamma": 10000,
    "ask_factor": 1.0007,
    "bid_factor": 0.9993,
    "edge": 1,
    "spread": 16,
    "skew": 0.5,
    "z_threshold": 0.6
}

PEPPER_PARAMS = {
    "spread_gradient": 0.0010586880760,
    "spread_intercept": 0.8694130152902
}

class Trader:

    ## REGRESSION SLOPE ##     ## REGRESSION SLOPE ##
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

    ## WALL-MID ##     ## WALL-MID ##
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

    ## ASH COATED OSMIUM ##     ## ASH COATED OSMIUM ##
    def _trade_osmium(self, product, order_depth, pos, limit, prev_wall_mid):
        orders = []

        # Obtain metrics
        alpha = OSMIUM_PARAMS.get("alpha")
        beta = OSMIUM_PARAMS.get("beta")
        mean = OSMIUM_PARAMS.get("gamma")
        ask_fac = OSMIUM_PARAMS.get("ask_factor")
        bid_fac = OSMIUM_PARAMS.get("bid_factor")
        edge = OSMIUM_PARAMS.get("edge")
        mid_spread = OSMIUM_PARAMS.get("spread")/2
        skew = OSMIUM_PARAMS.get("skew")
        z_thresh = OSMIUM_PARAMS.get("z_threshold")

        # Obtain the fair value using wall-mid
        wall_mid = mean if prev_wall_mid is None else mean + alpha*(prev_wall_mid - mean) # Initialisation and arbitrary value for protection

        best_ask = best_bid = None
        if order_depth.buy_orders and order_depth.sell_orders:
            wall_mid = self.get_wall_mid(order_depth)
            best_ask, ask_quantity = list(order_depth.sell_orders.items())[0]
            best_bid, bid_quantity = list(order_depth.buy_orders.items())[0]
        elif len(order_depth.sell_orders) != 0:
            best_ask, ask_quantity = list(order_depth.sell_orders.items())[0]
        elif len(order_depth.buy_orders) != 0:
            best_bid, bid_quantity = list(order_depth.buy_orders.items())[0]

        # Set our maximum order quantities
        buy_cap = limit - pos
        sell_cap = limit + pos

        # Find sensible buy / sell prices
        sensible_buy = math.floor(wall_mid * bid_fac)
        sensible_sell = math.ceil(wall_mid * ask_fac)

        # Find our z-score
        std = beta/math.sqrt(2*alpha)
        z = (wall_mid - mean)/std
        deviation = math.ceil(abs(z)*skew)

        ## Snatch up anything above / below fair value
        if best_bid and best_bid > mean:
            sell_quantity = min(sell_cap, bid_quantity)
            orders.append(Order(product, best_bid, -sell_quantity))
            sell_cap -= sell_quantity
        elif best_ask and best_ask < mean:
            buy_quantity = min(buy_cap, -ask_quantity)
            orders.append(Order(product, best_ask, buy_quantity))
            buy_cap -= buy_quantity

        ## Positive z-score strategy - SHORT
        if z > z_thresh:
            # Aggressive selling
            if best_bid >= wall_mid - deviation:
                sale_quantity = min(sell_cap, bid_quantity)
                orders.append(Order(product, best_bid, -sale_quantity))
                sell_cap -= sale_quantity
                best_bid = sensible_buy
            else:
                best_bid = best_bid+edge

            best_ask -= (deviation + edge)
            best_bid = min(best_bid, mean - 1)

            # Market Make
            orders.append(Order(product, best_ask-edge-deviation, -sell_cap))
            orders.append(Order(product, best_bid+edge-deviation, buy_cap))


        ## Negative z-score strategy - LONG
        elif z < -z_thresh:
            # Aggressive buying
            if best_ask <= wall_mid + deviation:
                buy_quantity = min(buy_cap, -ask_quantity)
                orders.append(Order(product, best_ask, buy_quantity))
                buy_cap -= buy_quantity
                best_ask = sensible_sell
            else:
                best_ask = best_ask-edge

            # Market Make
            orders.append(Order(product, best_ask-edge+deviation, -sell_cap))
            orders.append(Order(product, best_bid+edge+deviation, buy_cap))


        ## Skewed Market Making
        else:
            # Buying
            if best_bid and best_bid < wall_mid:
                orders.append(Order(product, best_bid+1, buy_cap))
            else:
                orders.append(Order(product, sensible_buy, buy_cap))

            # Selling
            if best_ask and best_ask > wall_mid:
                orders.append(Order(product, best_ask-1, -sell_cap))
            else:
                orders.append(Order(product, sensible_sell, -sell_cap))

        return orders, wall_mid


    ## INTARIAN PEPPER ROOT ##     ## INTARIAN PEPPER ROOT ##
    def _trade_pepper(self, product, order_depth, pos, limit, prev_mids, slope, directions):
        orders = []

        # Obtain the fair value using wall-mid
        wall_mid = prev_mids[-1] + slope if prev_mids is not None else 10000 # Initialisation and arbitrary value for protection
        best_ask = best_bid = None

        if order_depth.buy_orders and order_depth.sell_orders:
            wall_mid = self.get_wall_mid(order_depth)
            best_ask, ask_quantity = list(order_depth.sell_orders.items())[0]
            best_bid, bid_quantity = list(order_depth.buy_orders.items())[0]
        elif order_depth.sell_orders:
            best_ask, ask_quantity = list(order_depth.sell_orders.items())[0]
        elif order_depth.buy_orders:
            best_bid, bid_quantity = list(order_depth.buy_orders.items())[0]

        # Perform a regression to find the slope
        prev_mids = [wall_mid] if prev_mids is None else prev_mids + [wall_mid] # Initialisation or addition
        if len(prev_mids) > 5:
            prev_mids.pop(0)
            slope = self.regression_slope(prev_mids)
        else:
            slope = 0

        # Robust check for a positive or negative trend
        trend = 1 if slope >=0 else -1
        directions = [trend] if directions is None else directions + [trend]    # Initialisation or addition
        if len(directions) > 20:
            directions.pop(0)
        indicator = directions.count(1) / len(directions)

        # Set our maximum order quantities
        buy_cap = limit - pos
        sell_cap = limit + pos

        # Calculate the spread from the price
        m = PEPPER_PARAMS.get("spread_gradient")
        c = PEPPER_PARAMS.get("spread_intercept")
        mid_spread = (m*wall_mid + c)/2

        # Build inventory if the trend is positive
        if indicator >= 0.5:
            target = 80

            # Aggressively take if we are under target and we have sufficent data
            if pos <= 0.9*target and len(prev_mids) == 5:
                fair_purchase = math.floor(wall_mid+mid_spread)
                best_ask = min(best_ask, fair_purchase) if best_ask else fair_purchase
                orders.append(Order(product, best_ask, buy_cap))

            # Dealing with small fluctuations from market making
            elif pos < target:
                if best_ask and best_ask <= wall_mid:
                    buy_quantity = min(buy_cap, -ask_quantity)
                    orders.append(Order(product, best_ask, buy_quantity))
                    buy_cap -= buy_quantity
                if best_bid and best_bid < wall_mid - mid_spread/2:
                    orders.append(Order(product, best_bid+1, buy_cap))

            # Market make if our position is full
            elif best_ask and best_ask > wall_mid + mid_spread/2:
                orders.append(Order(product, best_ask-1, -sell_cap))

        # Short inventory if the trend is negative
        else:
            target = -80

            # Aggressively short if we are under target and we have sufficent data
            if pos >= 0.9*target and len(prev_mids) == 10:
                if best_bid:
                    orders.append(Order(product, best_bid, -sell_cap))
                else:
                    orders.append(Order(product, math.floor(wall_mid-mid_spread), -sell_cap))

            # Dealing with small fluctuations from market making
            elif pos > target:
                if best_bid and best_bid >= wall_mid:
                    sell_quantity = min(sell_cap, bid_quantity)
                    orders.append(Order(product, best_bid, -sell_quantity))
                    sell_cap -= sell_quantity
                if best_ask and best_ask > wall_mid + mid_spread/2:
                    orders.append(Order(product, best_ask-1, -sell_cap))

            # Market make if our position is full
            elif best_bid and best_bid < wall_mid - mid_spread/2:
                orders.append(Order(product, best_bid+1, buy_cap))

        return orders, prev_mids, slope, directions


    ## RUN ALGORITHMS ##     ## RUN ALGORITHMS ##
    def run(self, state: TradingState):
        result = {}

        # Load previous data
        pstate: dict = {}
        if state.traderData:
            try:
                pstate = json.loads(state.traderData)
            except Exception:
                pstate = {}

        # Run algorithms for all products
        for product, order_depth in state.order_depths.items():
            position = state.position.get(product, 0)
            limit    = POS_LIMITS.get(product, 20)

            if product == "ASH_COATED_OSMIUM":
                prev_wall_mid = pstate.get("PREV_OSMIUM_WALL_MID")
                orders, osmium_wall_mid = self._trade_osmium(product, order_depth, position, limit, prev_wall_mid)
                pstate["PREV_OSMIUM_WALL_MID"] = osmium_wall_mid

            elif product == "INTARIAN_PEPPER_ROOT":
                prev_mids = pstate.get("PREV_PEPPER_MIDS")
                prev_slope = pstate.get("PEPPER_SLOPE")
                prev_directions = pstate.get("PEPPER_DIRECTIONS")
                orders, pepper_mids, slope, directions = self._trade_pepper(product, order_depth, position, limit, prev_mids, prev_slope, prev_directions)
                pstate["PREV_PEPPER_MIDS"] = pepper_mids
                pstate["PEPPER_SLOPE"] = slope
                pstate["PEPPER_DIRECTIONS"] = directions

            else:
                orders = []

            result[product] = orders

        # Return results
        conversions = 0
        return result, conversions, json.dumps(pstate)
