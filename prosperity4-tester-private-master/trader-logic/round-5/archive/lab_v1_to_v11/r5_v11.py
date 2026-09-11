"""r5_v11.py -- IMC Prosperity 4 Round 5: Tiered penny MM.

v8/v10 baseline: $600k default 3-day, $33k 1k d4.

v11: Same penny MM core but with product-specific tuning.
  - ROBOT_DISHES (AC1=-0.23): Aggressive size, tight spread capture
  - ROBOT_IRONING (AC1=-0.13): Above-average size
  - OXYGEN_SHAKE_EVENING_BREATH/CHOCOLATE: Slightly above average
  - SNACKPACK: Wider spreads (15-18) = more profit per fill, larger size
  - Everything else: Standard penny MM

Also: proper all-or-nothing limit check to avoid order rejection.
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

# Per-product config: (base_size_mult, soft_pos, hard_pos, emergency)
PRODUCT_CONFIG = {}

# Mean-reverting products: aggressive
for p in ['ROBOT_DISHES']:
    PRODUCT_CONFIG[p] = (2.5, 25, 50, 65)
for p in ['ROBOT_IRONING']:
    PRODUCT_CONFIG[p] = (2.0, 25, 45, 60)
for p in ['OXYGEN_SHAKE_EVENING_BREATH', 'OXYGEN_SHAKE_CHOCOLATE']:
    PRODUCT_CONFIG[p] = (1.5, 20, 40, 55)

# Wide-spread products (SNACKPACK): more profit per fill
for p in ['SNACKPACK_CHOCOLATE', 'SNACKPACK_PISTACHIO', 'SNACKPACK_RASPBERRY',
          'SNACKPACK_STRAWBERRY', 'SNACKPACK_VANILLA']:
    PRODUCT_CONFIG[p] = (1.5, 20, 35, 50)

# PEBBLES: standard (basket doesn't help for passive MM)
# Everything else: standard
DEFAULT_CONFIG = (1.0, 20, 40, 55)


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

            size_mult, soft_pos, hard_pos, emergency = PRODUCT_CONFIG.get(product, DEFAULT_CONFIG)
            orders = []

            # Emergency flatten
            if pos > emergency:
                sell_qty = min(10, LIMIT + pos)
                if sell_qty > 0:
                    orders.append(Order(product, best_bid, -sell_qty))
                    pos -= sell_qty
            elif pos < -emergency:
                buy_qty = min(10, LIMIT - pos)
                if buy_qty > 0:
                    orders.append(Order(product, best_ask, buy_qty))
                    pos += buy_qty

            if spread >= 3:
                base_size = max(3, min(10, spread // 2))
                base_size = int(base_size * size_mult)

                bid_price = best_bid + 1
                ask_price = best_ask - 1

                bid_qty = base_size
                ask_qty = base_size

                if pos > hard_pos:
                    bid_qty = 0
                    ask_qty = base_size * 3
                elif pos > soft_pos:
                    fade = (pos - soft_pos) / (hard_pos - soft_pos)
                    bid_qty = max(1, int(base_size * (1 - fade)))
                    ask_qty = base_size + int(base_size * fade)

                if pos < -hard_pos:
                    ask_qty = 0
                    bid_qty = base_size * 3
                elif pos < -soft_pos:
                    fade = (-pos - soft_pos) / (hard_pos - soft_pos)
                    ask_qty = max(1, int(base_size * (1 - fade)))
                    bid_qty = base_size + int(base_size * fade)

                # All-or-nothing limit check
                # Total buy orders must not exceed LIMIT - pos
                # Total sell orders must not exceed LIMIT + pos
                total_buy = bid_qty
                total_sell = ask_qty
                if total_buy + pos > LIMIT:
                    bid_qty = max(0, LIMIT - pos)
                if total_sell - pos > LIMIT:
                    ask_qty = max(0, LIMIT + pos)

                if bid_qty > 0:
                    orders.append(Order(product, bid_price, bid_qty))
                if ask_qty > 0:
                    orders.append(Order(product, ask_price, -ask_qty))

            elif spread == 2:
                base_size = max(2, int(3 * size_mult))
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
