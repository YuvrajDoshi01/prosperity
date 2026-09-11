"""r5_v8.py -- IMC Prosperity 4 Round 5: Optimized penny MM.

v6 baseline: $571k default 3-day, $31k 1k d4.
v8 tweaks: larger quote sizes, tighter position management, join-best strategy.

Key insight: on 50 drifting products, PnL = fill_rate * spread_captured - inventory_risk.
  - fill_rate: proportional to our volume at best levels
  - spread_captured: 1 tick per fill for penny quotes (best+1 / best-1)
  - inventory_risk: mean-zero across products (diversification)

We want to maximize fill_rate (larger quotes) while controlling inventory (fast flatten).
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

# Position management
SOFT_POS = 20       # Start reducing one side
HARD_POS = 40       # Stop one side, increase other
EMERGENCY = 55      # Cross spread to flatten


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

            if spread >= 3:
                # Size scales with spread: wider = more profit, so bigger is OK
                base_size = min(10, max(3, spread // 2))

                # Penny: post one tick inside the spread
                bid_price = best_bid + 1
                ask_price = best_ask - 1

                # Compute quantities with position management
                bid_qty = base_size
                ask_qty = base_size

                if pos > HARD_POS:
                    bid_qty = 0
                    ask_qty = base_size * 3  # Aggressively flatten
                elif pos > SOFT_POS:
                    fade = (pos - SOFT_POS) / (HARD_POS - SOFT_POS)
                    bid_qty = max(1, int(base_size * (1 - fade)))
                    ask_qty = base_size + int(base_size * fade)

                if pos < -HARD_POS:
                    ask_qty = 0
                    bid_qty = base_size * 3
                elif pos < -SOFT_POS:
                    fade = (-pos - SOFT_POS) / (HARD_POS - SOFT_POS)
                    ask_qty = max(1, int(base_size * (1 - fade)))
                    bid_qty = base_size + int(base_size * fade)

                # Enforce limits
                bid_qty = min(bid_qty, LIMIT - pos)
                ask_qty = min(ask_qty, LIMIT + pos)

                if bid_qty > 0:
                    orders.append(Order(product, bid_price, bid_qty))
                if ask_qty > 0:
                    orders.append(Order(product, ask_price, -ask_qty))

            elif spread == 2:
                # Can't penny inside spread=2 (penny = cross).
                # Join the best level with small size on the side we want.
                base_size = 3
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
