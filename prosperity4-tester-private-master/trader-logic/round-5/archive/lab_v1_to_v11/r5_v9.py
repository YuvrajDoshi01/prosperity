"""r5_v9.py -- IMC Prosperity 4 Round 5: Multi-level penny MM.

v8 baseline: $600k default / $33k 1k d4 / $0 imc.

v9: Post at MULTIPLE levels inside the spread to capture more fills.
  Level 1: best+1 / best-1 (tightest, first to fill)
  Level 2: best+2 / best-2 (wider, catches bigger moves)

Also try the LU approach: take+clear+make pipeline.
"""

from datamodel import TradingState, Order, OrderDepth, Symbol

LIMIT = 80

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

SOFT_POS = 20
HARD_POS = 40
EMERGENCY = 55


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
            mid = (best_bid + best_ask) / 2.0
            mid_int = int(round(mid))
            orders = []

            # Emergency flatten
            if pos > EMERGENCY:
                sell_qty = min(10, LIMIT + pos)
                if sell_qty > 0:
                    orders.append(Order(product, best_bid, -sell_qty))
                    pos -= sell_qty
            elif pos < -EMERGENCY:
                buy_qty = min(10, LIMIT - pos)
                if buy_qty > 0:
                    orders.append(Order(product, best_ask, buy_qty))
                    pos += buy_qty

            # CLEAR: if we have inventory and can flatten at mid, do it
            if pos > 0 and best_bid >= mid_int:
                clear_qty = min(pos, 3)
                orders.append(Order(product, mid_int, -clear_qty))
                pos -= clear_qty
            elif pos < 0 and best_ask <= mid_int:
                clear_qty = min(-pos, 3)
                orders.append(Order(product, mid_int, clear_qty))
                pos += clear_qty

            if spread >= 4:
                # Multi-level posting
                # Level 1: penny (tight)
                l1_size = min(5, max(2, spread // 3))
                # Level 2: wider
                l2_size = min(3, max(1, spread // 4))

                l1_bid = best_bid + 1
                l1_ask = best_ask - 1
                l2_bid = best_bid + 2 if spread >= 6 else best_bid + 1
                l2_ask = best_ask - 2 if spread >= 6 else best_ask - 1

                # Position-adjusted sizing
                bid_mult = 1.0
                ask_mult = 1.0
                if pos > HARD_POS:
                    bid_mult = 0.0
                    ask_mult = 2.0
                elif pos > SOFT_POS:
                    fade = (pos - SOFT_POS) / (HARD_POS - SOFT_POS)
                    bid_mult = 1 - fade
                    ask_mult = 1 + fade
                if pos < -HARD_POS:
                    ask_mult = 0.0
                    bid_mult = 2.0
                elif pos < -SOFT_POS:
                    fade = (-pos - SOFT_POS) / (HARD_POS - SOFT_POS)
                    ask_mult = 1 - fade
                    bid_mult = 1 + fade

                # Level 1
                l1_bq = max(0, min(int(l1_size * bid_mult), LIMIT - pos))
                l1_aq = max(0, min(int(l1_size * ask_mult), LIMIT + pos))
                if l1_bq > 0:
                    orders.append(Order(product, l1_bid, l1_bq))
                    pos += l1_bq
                if l1_aq > 0:
                    orders.append(Order(product, l1_ask, -l1_aq))
                    pos -= l1_aq

                # Level 2 (only if spread wide enough and still have room)
                if spread >= 6:
                    l2_bq = max(0, min(int(l2_size * bid_mult), LIMIT - pos))
                    l2_aq = max(0, min(int(l2_size * ask_mult), LIMIT + pos))
                    if l2_bq > 0:
                        orders.append(Order(product, l2_bid, l2_bq))
                    if l2_aq > 0:
                        orders.append(Order(product, l2_ask, -l2_aq))

            elif spread == 3:
                l1_size = 3
                bid_qty = min(l1_size, LIMIT - pos) if pos < HARD_POS else 0
                ask_qty = min(l1_size, LIMIT + pos) if pos > -HARD_POS else 0

                if bid_qty > 0:
                    orders.append(Order(product, best_bid + 1, bid_qty))
                if ask_qty > 0:
                    orders.append(Order(product, best_ask - 1, -ask_qty))

            elif spread == 2:
                size = 2
                if pos <= 0:
                    bq = min(size, LIMIT - pos)
                    if bq > 0:
                        orders.append(Order(product, best_bid, bq))
                if pos >= 0:
                    aq = min(size, LIMIT + pos)
                    if aq > 0:
                        orders.append(Order(product, best_ask, -aq))

            result[product] = orders

        return result, conversions, ""
