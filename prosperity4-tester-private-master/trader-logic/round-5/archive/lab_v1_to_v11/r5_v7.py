"""r5_v7.py -- IMC Prosperity 4 Round 5: Aggressive penny MM + basket takes.

imc mode shows v6 at ~$0 (passive fills don't happen often enough).
default mode shows $571k (overpredicts fills).

Strategy adjustment:
  - More aggressive posting: tighter to mid, larger sizes
  - Add aggressive takes on ALL products when price crosses outside the spread
  - Use PEBBLES basket FV for take decisions (structural edge)
  - For non-basket products, take when bid > mid + threshold (overpriced)
  - Position management: faster flatten via market orders
"""

import json
from datamodel import TradingState, Order, OrderDepth, Symbol

LIMIT = 80

PEBBLES = ['PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL']
PEBBLES_BASKET_SUM = 50000

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

# Position management
FLATTEN_POS = 30
MAX_POS = 50
EMERGENCY_POS = 60


def get_mid(od: OrderDepth) -> float:
    if not od.buy_orders or not od.sell_orders:
        return 0
    return (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2


class Trader:

    def run(self, state: TradingState):
        result = {}
        conversions = 0

        # Compute PEBBLES basket FVs
        peb_fvs = {}
        peb_mids = {}
        for p in PEBBLES:
            if p in state.order_depths:
                peb_mids[p] = get_mid(state.order_depths[p])
        if len(peb_mids) == 5:
            total = sum(peb_mids.values())
            for p in PEBBLES:
                peb_fvs[p] = PEBBLES_BASKET_SUM - (total - peb_mids[p])

        for product in ALL_PRODUCTS:
            od = state.order_depths.get(product)
            if not od or not od.buy_orders or not od.sell_orders:
                continue

            pos = state.position.get(product, 0)
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            spread = best_ask - best_bid
            mid = (best_bid + best_ask) / 2.0
            orders = []

            # Fair value
            if product in peb_fvs:
                fv = peb_fvs[product]
            else:
                fv = mid

            fv_int = int(round(fv))

            # === TAKE: aggressive crossing when the book is mispriced vs FV ===
            # Buy asks that are below FV
            for ask_price in sorted(od.sell_orders.keys()):
                if ask_price >= fv_int:
                    break
                ask_vol = abs(od.sell_orders[ask_price])
                buy_qty = min(ask_vol, LIMIT - pos)
                if buy_qty > 0:
                    orders.append(Order(product, ask_price, buy_qty))
                    pos += buy_qty

            # Sell bids that are above FV
            for bid_price in sorted(od.buy_orders.keys(), reverse=True):
                if bid_price <= fv_int:
                    break
                bid_vol = od.buy_orders[bid_price]
                sell_qty = min(bid_vol, LIMIT + pos)
                if sell_qty > 0:
                    orders.append(Order(product, bid_price, -sell_qty))
                    pos -= sell_qty

            # === FLATTEN: position reduction ===
            if pos > EMERGENCY_POS:
                sell_qty = min(5, LIMIT + pos)
                if sell_qty > 0:
                    orders.append(Order(product, best_bid, -sell_qty))
                    pos -= sell_qty
            elif pos < -EMERGENCY_POS:
                buy_qty = min(5, LIMIT - pos)
                if buy_qty > 0:
                    orders.append(Order(product, best_ask, buy_qty))
                    pos += buy_qty

            # === MAKE: penny quotes ===
            if spread > 2:
                # Quote size: proportional to spread (more profit per fill when wide)
                base_size = max(2, min(8, spread // 2))

                bid_price = best_bid + 1
                ask_price = best_ask - 1

                # For PEBBLES with basket FV: center quotes on FV
                if product in peb_fvs and best_bid < fv_int < best_ask:
                    bid_price = max(best_bid + 1, fv_int - 1)
                    ask_price = min(best_ask - 1, fv_int + 1)

                bid_qty = base_size
                ask_qty = base_size

                # Position skew
                if pos > FLATTEN_POS:
                    bid_qty = 0
                    ask_qty = base_size * 2
                elif pos > 0:
                    bid_qty = max(1, int(base_size * (1.0 - pos / FLATTEN_POS * 0.5)))

                if pos < -FLATTEN_POS:
                    ask_qty = 0
                    bid_qty = base_size * 2
                elif pos < 0:
                    ask_qty = max(1, int(base_size * (1.0 - (-pos) / FLATTEN_POS * 0.5)))

                bid_qty = min(bid_qty, LIMIT - pos)
                ask_qty = min(ask_qty, LIMIT + pos)

                if bid_qty > 0 and pos < MAX_POS:
                    orders.append(Order(product, bid_price, bid_qty))
                if ask_qty > 0 and pos > -MAX_POS:
                    orders.append(Order(product, ask_price, -ask_qty))

            elif spread == 2:
                base_size = 2
                if pos <= 0:
                    bid_qty = min(base_size, LIMIT - pos)
                    if bid_qty > 0:
                        orders.append(Order(product, best_bid, bid_qty))
                if pos >= 0:
                    ask_qty = min(base_size, LIMIT + pos)
                    if ask_qty > 0:
                        orders.append(Order(product, best_ask, -ask_qty))

            result[product] = orders

        return result, conversions, ""
