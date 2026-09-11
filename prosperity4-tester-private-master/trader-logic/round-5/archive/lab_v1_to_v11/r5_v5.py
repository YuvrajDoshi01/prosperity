"""r5_v5.py -- IMC Prosperity 4 Round 5: Pure penny MM on all 50 products.

Core insight: with 50 drifting products, the only reliable PnL source is
spread capture from passive fills. Taker bot hits our quotes ~2.4% per tick.
With 50 products, that's ~1.2 fills per tick across the universe.

Strategy: post penny quotes (best+1 / best-1) with tiny size on ALL products.
Position management via asymmetric quoting (stop quoting the long side when
inventory builds up, aggressively flatten via crossing the spread at high pos).

No basket arb, no pair trading -- just harvest the bid-ask spread at scale.
"""

import json
from datamodel import TradingState, Order, OrderDepth, Symbol

LIMIT = 80

# All 50 products
ALL_PRODUCTS = [
    'GALAXY_SOUNDS_BLACK_HOLES', 'GALAXY_SOUNDS_DARK_MATTER',
    'GALAXY_SOUNDS_PLANETARY_RINGS', 'GALAXY_SOUNDS_SOLAR_FLAMES',
    'GALAXY_SOUNDS_SOLAR_WINDS',
    'MICROCHIP_CIRCLE', 'MICROCHIP_OVAL', 'MICROCHIP_RECTANGLE',
    'MICROCHIP_SQUARE', 'MICROCHIP_TRIANGLE',
    'OXYGEN_SHAKE_CHOCOLATE', 'OXYGEN_SHAKE_EVENING_BREATH',
    'OXYGEN_SHAKE_GARLIC', 'OXYGEN_SHAKE_MINT', 'OXYGEN_SHAKE_MORNING_BREATH',
    'PANEL_1X2', 'PANEL_1X4', 'PANEL_2X2', 'PANEL_2X4', 'PANEL_4X4',
    'PEBBLES_L', 'PEBBLES_M', 'PEBBLES_S', 'PEBBLES_XL', 'PEBBLES_XS',
    'ROBOT_DISHES', 'ROBOT_IRONING', 'ROBOT_LAUNDRY', 'ROBOT_MOPPING', 'ROBOT_VACUUMING',
    'SLEEP_POD_COTTON', 'SLEEP_POD_LAMB_WOOL', 'SLEEP_POD_NYLON',
    'SLEEP_POD_POLYESTER', 'SLEEP_POD_SUEDE',
    'SNACKPACK_CHOCOLATE', 'SNACKPACK_PISTACHIO', 'SNACKPACK_RASPBERRY',
    'SNACKPACK_STRAWBERRY', 'SNACKPACK_VANILLA',
    'TRANSLATOR_ASTRO_BLACK', 'TRANSLATOR_ECLIPSE_CHARCOAL',
    'TRANSLATOR_GRAPHITE_MIST', 'TRANSLATOR_SPACE_GRAY', 'TRANSLATOR_VOID_BLUE',
    'UV_VISOR_AMBER', 'UV_VISOR_MAGENTA', 'UV_VISOR_ORANGE',
    'UV_VISOR_RED', 'UV_VISOR_YELLOW',
]

QUOTE_SIZE = 3            # Very small to limit inventory risk
MAX_POS = 30              # Hard cap -- stop one-sided quoting
FLATTEN_POS = 20          # Start flattening aggressively
EMERGENCY_POS = 50        # Cross the spread to flatten


def get_mid(od: OrderDepth) -> float:
    if not od.buy_orders or not od.sell_orders:
        return 0
    return (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2


class Trader:

    def run(self, state: TradingState):
        result = {}
        conversions = 0

        for product in ALL_PRODUCTS:
            od = state.order_depths.get(product)
            if not od or not od.buy_orders or not od.sell_orders:
                continue

            pos = state.position.get(product, 0)
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            spread = best_ask - best_bid
            mid = (best_bid + best_ask) / 2
            orders = []

            # Emergency flatten: cross the spread to reduce position
            if abs(pos) >= EMERGENCY_POS:
                if pos > 0:
                    # Need to sell -- hit the bid
                    sell_qty = min(QUOTE_SIZE * 2, pos, LIMIT + pos)
                    if sell_qty > 0:
                        orders.append(Order(product, best_bid, -sell_qty))
                else:
                    # Need to buy -- lift the ask
                    buy_qty = min(QUOTE_SIZE * 2, -pos, LIMIT - pos)
                    if buy_qty > 0:
                        orders.append(Order(product, best_ask, buy_qty))

            # Only penny inside the spread if spread > 2 (room for profit)
            if spread > 2:
                # Bid: post at best_bid + 1 (penny)
                bid_price = best_bid + 1
                # Ask: post at best_ask - 1 (penny)
                ask_price = best_ask - 1

                # Position-aware sizing and skipping
                bid_qty = QUOTE_SIZE
                ask_qty = QUOTE_SIZE

                if pos > FLATTEN_POS:
                    bid_qty = 0  # Stop buying
                    ask_qty = QUOTE_SIZE * 2  # Sell harder
                elif pos > MAX_POS:
                    bid_qty = 0
                    ask_qty = QUOTE_SIZE * 3
                elif pos > 0:
                    # Reduce bid size proportionally
                    ratio = 1.0 - (pos / FLATTEN_POS) * 0.5
                    bid_qty = max(1, int(QUOTE_SIZE * ratio))

                if pos < -FLATTEN_POS:
                    ask_qty = 0
                    bid_qty = QUOTE_SIZE * 2
                elif pos < -MAX_POS:
                    ask_qty = 0
                    bid_qty = QUOTE_SIZE * 3
                elif pos < 0:
                    ratio = 1.0 - (-pos / FLATTEN_POS) * 0.5
                    ask_qty = max(1, int(QUOTE_SIZE * ratio))

                # Enforce position limits
                bid_qty = min(bid_qty, LIMIT - pos)
                ask_qty = min(ask_qty, LIMIT + pos)

                if bid_qty > 0:
                    orders.append(Order(product, bid_price, bid_qty))
                if ask_qty > 0:
                    orders.append(Order(product, ask_price, -ask_qty))

            elif spread == 2:
                # Spread = 2: can only post at mid (best+1 = best_ask)
                # Very tight -- just join the best level
                mid_int = int(round(mid))
                bid_qty = min(QUOTE_SIZE, LIMIT - pos)
                ask_qty = min(QUOTE_SIZE, LIMIT + pos)

                if pos <= 0 and bid_qty > 0:
                    orders.append(Order(product, best_bid, bid_qty))
                if pos >= 0 and ask_qty > 0:
                    orders.append(Order(product, best_ask, -ask_qty))

            result[product] = orders

        return result, conversions, ""
