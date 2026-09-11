"""r5_v6.py -- IMC Prosperity 4 Round 5: Enhanced penny MM.

v5 proved penny MM works ($448k 3-day). Now optimize:
  - Increase quote sizes where spread is wide (more profit per fill)
  - Use basket-implied FV for PEBBLES penny placement
  - Spread-aware sizing: wider spread = larger quotes
  - Add gentle mean-reversion lean for high-AC1 products
  - Tighter position management
"""

import json
from datamodel import TradingState, Order, OrderDepth, Symbol

LIMIT = 80

PEBBLES = ['PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL']
PEBBLES_BASKET_SUM = 50000

HIGH_AC1 = {
    'ROBOT_DISHES': -0.232,
    'ROBOT_IRONING': -0.125,
    'OXYGEN_SHAKE_EVENING_BREATH': -0.123,
    'OXYGEN_SHAKE_CHOCOLATE': -0.089,
}

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
FLATTEN_POS = 25          # Start flattening (was 20)
MAX_POS = 40              # Hard cap one-sided quoting (was 30)
EMERGENCY_POS = 55        # Cross the spread (was 50)


def get_mid(od: OrderDepth) -> float:
    if not od.buy_orders or not od.sell_orders:
        return 0
    return (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2


def quote_size_for_spread(spread: int) -> int:
    """Wider spread = more profit per fill = larger size is safe."""
    if spread <= 4:
        return 2
    elif spread <= 8:
        return 4
    elif spread <= 12:
        return 5
    elif spread <= 16:
        return 6
    else:
        return 8  # SNACKPACK-wide spreads


class Trader:

    def run(self, state: TradingState):
        result = {}
        conversions = 0

        # Compute PEBBLES basket FVs
        peb_basket_fvs = {}
        peb_mids = {}
        for p in PEBBLES:
            if p in state.order_depths:
                peb_mids[p] = get_mid(state.order_depths[p])

        if len(peb_mids) == 5:
            total_mid = sum(peb_mids.values())
            for p in PEBBLES:
                other_sum = total_mid - peb_mids[p]
                peb_basket_fvs[p] = PEBBLES_BASKET_SUM - other_sum

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

            # Determine fair value
            if product in peb_basket_fvs:
                fv = peb_basket_fvs[product]
            elif product in HIGH_AC1:
                # Mean-reversion: pull FV slightly toward wall-mid
                # (wall = highest-volume level, acts as mean-reversion anchor)
                max_bv, wall_b = 0, best_bid
                for p, v in od.buy_orders.items():
                    if v > max_bv:
                        max_bv, wall_b = v, p
                max_av, wall_a = 0, best_ask
                for p, v in od.sell_orders.items():
                    if abs(v) > max_av:
                        max_av, wall_a = abs(v), p
                wall_mid = (wall_b + wall_a) / 2.0
                # Blend: 80% mid + 20% wall_mid
                fv = 0.8 * mid + 0.2 * wall_mid
            else:
                fv = mid

            fv_int = int(round(fv))
            base_size = quote_size_for_spread(spread)

            # Emergency flatten
            if abs(pos) >= EMERGENCY_POS:
                if pos > 0:
                    sell_qty = min(base_size * 3, LIMIT + pos)
                    if sell_qty > 0:
                        orders.append(Order(product, best_bid, -sell_qty))
                else:
                    buy_qty = min(base_size * 3, LIMIT - pos)
                    if buy_qty > 0:
                        orders.append(Order(product, best_ask, buy_qty))

            if spread > 2:
                # Penny inside the spread
                bid_price = best_bid + 1
                ask_price = best_ask - 1

                # For PEBBLES: place relative to basket FV if it's inside the spread
                if product in peb_basket_fvs:
                    if best_bid < fv_int < best_ask:
                        bid_price = fv_int - 1
                        ask_price = fv_int + 1
                    elif fv_int <= best_bid:
                        # FV below best bid -- want to sell
                        bid_price = best_bid  # Join bid
                        ask_price = best_bid + 1  # Tight ask
                    elif fv_int >= best_ask:
                        # FV above best ask -- want to buy
                        bid_price = best_ask - 1  # Tight bid
                        ask_price = best_ask  # Join ask

                # Position-aware sizing
                bid_qty = base_size
                ask_qty = base_size

                if pos > FLATTEN_POS:
                    bid_qty = 0
                    ask_qty = base_size * 2
                elif pos > 0:
                    ratio = 1.0 - (pos / FLATTEN_POS) * 0.5
                    bid_qty = max(1, int(base_size * ratio))

                if pos < -FLATTEN_POS:
                    ask_qty = 0
                    bid_qty = base_size * 2
                elif pos < 0:
                    ratio = 1.0 - (-pos / FLATTEN_POS) * 0.5
                    ask_qty = max(1, int(base_size * ratio))

                bid_qty = min(bid_qty, LIMIT - pos)
                ask_qty = min(ask_qty, LIMIT + pos)

                if bid_qty > 0 and pos < MAX_POS:
                    orders.append(Order(product, bid_price, bid_qty))
                if ask_qty > 0 and pos > -MAX_POS:
                    orders.append(Order(product, ask_price, -ask_qty))

            elif spread == 2:
                bid_qty = min(base_size, LIMIT - pos)
                ask_qty = min(base_size, LIMIT + pos)
                if pos <= 0 and bid_qty > 0:
                    orders.append(Order(product, best_bid, bid_qty))
                if pos >= 0 and ask_qty > 0:
                    orders.append(Order(product, best_ask, -ask_qty))

            result[product] = orders

        return result, conversions, ""
