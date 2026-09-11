"""r5_v2.py -- IMC Prosperity 4 Round 5 strategy v2.

Fixes from v1:
  - Remove aggressive takes on generic MM products (directional risk kills PnL on drifting products)
  - Keep takes ONLY on PEBBLES basket arb (structural edge, not directional)
  - Use simple mid for generic MM (Wall-Mid leans too hard into stale walls)
  - Reduce quote size and widen offsets for safety
  - Add position-aware inventory management
"""

import json
import math
from datamodel import TradingState, Order, OrderDepth, Symbol

# ==================== CONSTANTS ====================
LIMIT = 80

PEBBLES = ['PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL']
PEBBLES_BASKET_SUM = 50000

SNACKPACK = ['SNACKPACK_CHOCOLATE', 'SNACKPACK_PISTACHIO', 'SNACKPACK_RASPBERRY',
             'SNACKPACK_STRAWBERRY', 'SNACKPACK_VANILLA']
SNACK_PAIRS = [
    ('SNACKPACK_CHOCOLATE', 'SNACKPACK_VANILLA'),
    ('SNACKPACK_RASPBERRY', 'SNACKPACK_STRAWBERRY'),
]

HIGH_AC1 = {
    'ROBOT_DISHES': -0.232,
    'ROBOT_IRONING': -0.125,
    'OXYGEN_SHAKE_EVENING_BREATH': -0.123,
    'OXYGEN_SHAKE_CHOCOLATE': -0.089,
}

GALAXY_SOUNDS = ['GALAXY_SOUNDS_BLACK_HOLES', 'GALAXY_SOUNDS_DARK_MATTER',
                 'GALAXY_SOUNDS_PLANETARY_RINGS', 'GALAXY_SOUNDS_SOLAR_FLAMES',
                 'GALAXY_SOUNDS_SOLAR_WINDS']
MICROCHIP = ['MICROCHIP_CIRCLE', 'MICROCHIP_OVAL', 'MICROCHIP_RECTANGLE',
             'MICROCHIP_SQUARE', 'MICROCHIP_TRIANGLE']
OXYGEN_SHAKE = ['OXYGEN_SHAKE_CHOCOLATE', 'OXYGEN_SHAKE_EVENING_BREATH',
                'OXYGEN_SHAKE_GARLIC', 'OXYGEN_SHAKE_MINT', 'OXYGEN_SHAKE_MORNING_BREATH']
PANEL = ['PANEL_1X2', 'PANEL_1X4', 'PANEL_2X2', 'PANEL_2X4', 'PANEL_4X4']
ROBOT = ['ROBOT_DISHES', 'ROBOT_IRONING', 'ROBOT_LAUNDRY', 'ROBOT_MOPPING', 'ROBOT_VACUUMING']
SLEEP_POD = ['SLEEP_POD_COTTON', 'SLEEP_POD_LAMB_WOOL', 'SLEEP_POD_NYLON',
             'SLEEP_POD_POLYESTER', 'SLEEP_POD_SUEDE']
TRANSLATOR = ['TRANSLATOR_ASTRO_BLACK', 'TRANSLATOR_ECLIPSE_CHARCOAL',
              'TRANSLATOR_GRAPHITE_MIST', 'TRANSLATOR_SPACE_GRAY', 'TRANSLATOR_VOID_BLUE']
UV_VISOR = ['UV_VISOR_AMBER', 'UV_VISOR_MAGENTA', 'UV_VISOR_ORANGE',
            'UV_VISOR_RED', 'UV_VISOR_YELLOW']

ALL_PRODUCTS = (PEBBLES + SNACKPACK + GALAXY_SOUNDS + MICROCHIP + OXYGEN_SHAKE +
                PANEL + ROBOT + SLEEP_POD + TRANSLATOR + UV_VISOR)

# PEBBLES basket arb params
PEB_TAKE_EDGE = 2        # Min edge from basket FV for aggressive take
PEB_QUOTE_SIZE = 12
PEB_MM_OFFSET = 3        # Wider than v1's 2

# SNACKPACK pair params
SNACK_PAIR_WINDOW = 100
SNACK_QUOTE_SIZE = 8
SNACK_MM_OFFSET = 3

# High-AC(1) mean-reversion params
MR_QUOTE_SIZE = 8
MR_MM_OFFSET = 1         # Tight quotes, mean-reverting products

# Generic MM params
GEN_QUOTE_SIZE = 5        # Small to limit exposure
GEN_MM_OFFSET = 2

SOFT_LIMIT = 50           # Start skewing earlier (was 60)
HARD_LIMIT = 70           # Stop quoting one side

# ==================== HELPER FUNCTIONS ====================

def get_mid(od: OrderDepth) -> float:
    if not od.buy_orders or not od.sell_orders:
        return 0
    return (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2


def get_wall_mid(od: OrderDepth) -> float:
    if not od.buy_orders or not od.sell_orders:
        return get_mid(od)
    max_bv, wall_b = 0, max(od.buy_orders.keys())
    for p, v in od.buy_orders.items():
        if v > max_bv:
            max_bv, wall_b = v, p
    max_av, wall_a = 0, min(od.sell_orders.keys())
    for p, v in od.sell_orders.items():
        if abs(v) > max_av:
            max_av, wall_a = abs(v), p
    return (wall_b + wall_a) / 2


class Trader:

    def __init__(self):
        self.snack_pair_sums = {}

    def run(self, state: TradingState):
        result = {}
        conversions = 0

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except:
                td = {}

        self.snack_pair_sums = td.get('sp', {})

        # ==================== TIER 1: PEBBLES BASKET ARB ====================
        pebbles_mids = {}
        for p in PEBBLES:
            if p in state.order_depths:
                pebbles_mids[p] = get_mid(state.order_depths[p])

        if len(pebbles_mids) == 5:
            total_mid = sum(pebbles_mids.values())

            for p in PEBBLES:
                od = state.order_depths[p]
                if not od.buy_orders or not od.sell_orders:
                    continue

                other_sum = total_mid - pebbles_mids[p]
                basket_fv = PEBBLES_BASKET_SUM - other_sum

                pos = state.position.get(p, 0)
                orders = []
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())
                fv_int = int(round(basket_fv))

                # Aggressive takes only when basket edge > threshold
                for ask_price in sorted(od.sell_orders.keys()):
                    if ask_price > fv_int - PEB_TAKE_EDGE:
                        break
                    ask_vol = abs(od.sell_orders[ask_price])
                    buy_qty = min(ask_vol, LIMIT - pos)
                    if buy_qty > 0:
                        orders.append(Order(p, ask_price, buy_qty))
                        pos += buy_qty

                for bid_price in sorted(od.buy_orders.keys(), reverse=True):
                    if bid_price < fv_int + PEB_TAKE_EDGE:
                        break
                    bid_vol = od.buy_orders[bid_price]
                    sell_qty = min(bid_vol, LIMIT + pos)
                    if sell_qty > 0:
                        orders.append(Order(p, bid_price, -sell_qty))
                        pos -= sell_qty

                # Passive MM
                bid_offset = PEB_MM_OFFSET
                if pos > SOFT_LIMIT:
                    bid_offset += 2
                ask_offset = PEB_MM_OFFSET
                if pos < -SOFT_LIMIT:
                    ask_offset += 2

                bid_price = fv_int - bid_offset
                bid_qty = min(PEB_QUOTE_SIZE, LIMIT - pos)
                if bid_qty > 0 and pos < HARD_LIMIT:
                    orders.append(Order(p, bid_price, bid_qty))

                ask_price = fv_int + ask_offset
                ask_qty = min(PEB_QUOTE_SIZE, LIMIT + pos)
                if ask_qty > 0 and pos > -HARD_LIMIT:
                    orders.append(Order(p, ask_price, -ask_qty))

                result[p] = orders
        else:
            for p in PEBBLES:
                if p in state.order_depths:
                    result[p] = self._passive_mm(p, state, GEN_QUOTE_SIZE, GEN_MM_OFFSET)

        # ==================== TIER 2: SNACKPACK PAIRS ====================
        snack_mids = {}
        for p in SNACKPACK:
            if p in state.order_depths:
                snack_mids[p] = get_mid(state.order_depths[p])

        for p1, p2 in SNACK_PAIRS:
            key = f"{p1}_{p2}"
            if p1 in snack_mids and p2 in snack_mids:
                pair_sum = snack_mids[p1] + snack_mids[p2]
                if key not in self.snack_pair_sums:
                    self.snack_pair_sums[key] = []
                self.snack_pair_sums[key].append(pair_sum)
                if len(self.snack_pair_sums[key]) > SNACK_PAIR_WINDOW:
                    self.snack_pair_sums[key] = self.snack_pair_sums[key][-SNACK_PAIR_WINDOW:]

        snack_fvs = {}
        for p1, p2 in SNACK_PAIRS:
            key = f"{p1}_{p2}"
            if key in self.snack_pair_sums and len(self.snack_pair_sums[key]) >= 20:
                mean_sum = sum(self.snack_pair_sums[key]) / len(self.snack_pair_sums[key])
                if p2 in snack_mids:
                    snack_fvs.setdefault(p1, []).append(mean_sum - snack_mids[p2])
                if p1 in snack_mids:
                    snack_fvs.setdefault(p2, []).append(mean_sum - snack_mids[p1])

        for p in SNACKPACK:
            if p in state.order_depths and p not in result:
                od = state.order_depths[p]
                if not od.buy_orders or not od.sell_orders:
                    continue

                if p in snack_fvs and snack_fvs[p]:
                    fv = sum(snack_fvs[p]) / len(snack_fvs[p])
                    # Blend pair-implied FV with simple mid (avoid stale pair sums)
                    mid = get_mid(od)
                    fv = 0.5 * fv + 0.5 * mid
                else:
                    fv = get_mid(od)

                result[p] = self._passive_mm_fv(p, state, fv, SNACK_QUOTE_SIZE, SNACK_MM_OFFSET)

        # ==================== TIER 3: MEAN-REVERTING PRODUCTS ====================
        for p, ac1 in HIGH_AC1.items():
            if p in state.order_depths and p not in result:
                od = state.order_depths[p]
                if not od.buy_orders or not od.sell_orders:
                    continue

                wm = get_wall_mid(od)
                mid = get_mid(od)
                # Lean FV toward wall-mid for mean-reversion
                fv = 0.7 * mid + 0.3 * wm

                result[p] = self._passive_mm_fv(p, state, fv, MR_QUOTE_SIZE, MR_MM_OFFSET)

        # ==================== TIER 4: PASSIVE MM ON EVERYTHING ELSE ====================
        for p in ALL_PRODUCTS:
            if p not in result and p in state.order_depths:
                result[p] = self._passive_mm(p, state, GEN_QUOTE_SIZE, GEN_MM_OFFSET)

        # Save state
        new_td = {'sp': self.snack_pair_sums}
        try:
            trader_data = json.dumps(new_td)
            if len(trader_data) > 49000:
                for key in self.snack_pair_sums:
                    self.snack_pair_sums[key] = self.snack_pair_sums[key][-50:]
                trader_data = json.dumps({'sp': self.snack_pair_sums})
        except:
            trader_data = ""

        return result, conversions, trader_data

    def _passive_mm(self, product: str, state: TradingState,
                    quote_size: int, offset: int) -> list:
        """Pure passive MM with simple mid FV. NO taking."""
        od = state.order_depths.get(product)
        if not od or not od.buy_orders or not od.sell_orders:
            return []
        fv = get_mid(od)
        return self._passive_mm_fv(product, state, fv, quote_size, offset)

    def _passive_mm_fv(self, product: str, state: TradingState, fv: float,
                       quote_size: int, offset: int) -> list:
        """Passive MM around a fair value. No aggressive takes."""
        od = state.order_depths.get(product)
        if not od or not od.buy_orders or not od.sell_orders:
            return []

        pos = state.position.get(product, 0)
        orders = []
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        fv_int = int(round(fv))

        # Position-aware offsets
        bid_offset = offset
        ask_offset = offset
        if pos > SOFT_LIMIT:
            bid_offset += 2  # Widen bid when long
        elif pos > SOFT_LIMIT // 2:
            bid_offset += 1
        if pos < -SOFT_LIMIT:
            ask_offset += 2  # Widen ask when short
        elif pos < -SOFT_LIMIT // 2:
            ask_offset += 1

        # Bid
        bid_price = fv_int - bid_offset
        bid_qty = min(quote_size, LIMIT - pos)
        if bid_qty > 0 and pos < HARD_LIMIT:
            # Penny: improve toward best_bid if possible
            if bid_price < best_bid and best_bid < fv_int:
                bid_price = best_bid
            orders.append(Order(product, bid_price, bid_qty))

        # Ask
        ask_price = fv_int + ask_offset
        ask_qty = min(quote_size, LIMIT + pos)
        if ask_qty > 0 and pos > -HARD_LIMIT:
            if ask_price > best_ask and best_ask > fv_int:
                ask_price = best_ask
            orders.append(Order(product, ask_price, -ask_qty))

        return orders
