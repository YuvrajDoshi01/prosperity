"""r5_v1.py -- IMC Prosperity 4 Round 5 baseline strategy.

50 products in 10 groups of 5. Position limit = 80 (default).

EDA findings:
  PEBBLES: Perfect basket (sum = 50000, std=2.8). Basket-implied FV for MM.
  SNACKPACK: Strong negative pairs (CHOC-VAN rho=-0.92, RASP-STRAW rho=-0.92).
    Pairs sum is ~constant with some drift; tight enough for pair-arb MM.
  ROBOT_DISHES: AC(1) = -0.23 (strongly mean-reverting). ROBOT_IRONING: AC(1) = -0.13.
  OXYGEN_SHAKE_EVENING_BREATH: AC(1) = -0.12. OXYGEN_SHAKE_CHOCOLATE: AC(1) = -0.09.
  All other groups: near-zero intra-group correlation, random-walk individual products.

Strategy:
  Tier 1 - PEBBLES basket arb: use basket-implied FV for tight MM + aggressive takes.
  Tier 2 - SNACKPACK pair trading: pair-implied FV for MM on high-corr pairs.
  Tier 3 - High-AC(1) mean-reversion MM: ROBOT_DISHES, ROBOT_IRONING, OXYGEN_SHAKE*.
  Tier 4 - Wall-Mid MM on everything else (50 products).

All MM uses Wall-Mid (highest-volume level midpoint) as fair value fallback.
"""

import json
import math
from datamodel import TradingState, Order, OrderDepth, Symbol

# ==================== CONSTANTS ====================
LIMIT = 80  # Default position limit for all R5 products

# Product groups
PEBBLES = ['PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL']
PEBBLES_BASKET_SUM = 50000  # Exact sum constraint

SNACKPACK = ['SNACKPACK_CHOCOLATE', 'SNACKPACK_PISTACHIO', 'SNACKPACK_RASPBERRY',
             'SNACKPACK_STRAWBERRY', 'SNACKPACK_VANILLA']
# High-correlation pairs: (p1, p2, avg_sum) — these pairs move inversely
SNACK_PAIRS = [
    ('SNACKPACK_CHOCOLATE', 'SNACKPACK_VANILLA'),      # rho = -0.92
    ('SNACKPACK_RASPBERRY', 'SNACKPACK_STRAWBERRY'),    # rho = -0.92
    ('SNACKPACK_PISTACHIO', 'SNACKPACK_RASPBERRY'),     # rho = -0.83
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

# MM parameters
PEBBLES_QUOTE_SIZE = 15       # Basket arb posting size
PEBBLES_EDGE = 1              # Minimum edge from basket FV before aggressive take
PEBBLES_MM_OFFSET = 2         # Offset from FV for passive quotes
PEBBLES_TAKE_OFFSET = 0       # Take at FV or better

SNACK_PAIR_WINDOW = 100       # Rolling window for pair sum mean
SNACK_PAIR_THRESHOLD = 40     # Z-score entry threshold for pair divergence
SNACK_QUOTE_SIZE = 15

MR_QUOTE_SIZE = 10            # Size for mean-reverting products
MR_REVERSION_BETA = 0.15     # How aggressively to lean into mean reversion

MM_QUOTE_SIZE = 10            # Default MM size
MM_OFFSET = 2                 # Default MM offset from FV
SOFT_LIMIT = 60               # Start skewing at this position level


# ==================== HELPER FUNCTIONS ====================

def get_mid(order_depth: OrderDepth) -> float:
    """Simple midpoint of best bid/ask."""
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return 0
    best_bid = max(order_depth.buy_orders.keys())
    best_ask = min(order_depth.sell_orders.keys())
    return (best_bid + best_ask) / 2


def get_wall_mid(order_depth: OrderDepth) -> float:
    """Wall Mid: midpoint of the highest-volume bid and ask levels.
    This is the institutional anchor price -- proven superior to simple mid in R3."""
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return get_mid(order_depth)

    # Find the bid level with maximum volume
    max_bid_vol = 0
    wall_bid = max(order_depth.buy_orders.keys())
    for price, vol in order_depth.buy_orders.items():
        if vol > max_bid_vol:
            max_bid_vol = vol
            wall_bid = price

    # Find the ask level with minimum volume (most negative = most volume)
    max_ask_vol = 0
    wall_ask = min(order_depth.sell_orders.keys())
    for price, vol in order_depth.sell_orders.items():
        if abs(vol) > max_ask_vol:
            max_ask_vol = abs(vol)
            wall_ask = price

    return (wall_bid + wall_ask) / 2


def get_spread(order_depth: OrderDepth) -> int:
    """Current bid-ask spread."""
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return 999
    return min(order_depth.sell_orders.keys()) - max(order_depth.buy_orders.keys())


def position_skew(pos: int, limit: int, soft: int) -> float:
    """Returns a skew factor [-1, 1] based on position.
    Positive position -> negative skew (lean toward selling).
    Returns 0 within soft limit."""
    if abs(pos) <= soft:
        return 0
    excess = abs(pos) - soft
    max_excess = limit - soft
    raw = excess / max_excess if max_excess > 0 else 0
    return -raw if pos > 0 else raw


class Trader:

    def __init__(self):
        self.snack_pair_sums = {}  # (p1, p2) -> list of recent sums

    def run(self, state: TradingState):
        result = {}
        conversions = 0

        # Parse trader data
        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except:
                td = {}

        # Restore snack pair sums
        self.snack_pair_sums = {}
        for key_str, vals in td.get('sp', {}).items():
            self.snack_pair_sums[key_str] = vals

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

                # Basket-implied FV: this product's FV = BASKET_SUM - sum(other 4 mids)
                other_sum = total_mid - pebbles_mids[p]
                basket_fv = PEBBLES_BASKET_SUM - other_sum

                pos = state.position.get(p, 0)
                orders = []
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())

                # Aggressive takes: take mispriced levels
                # Buy at ask if ask < basket_fv (underpriced)
                for ask_price in sorted(od.sell_orders.keys()):
                    ask_vol = abs(od.sell_orders[ask_price])
                    if ask_price < basket_fv - PEBBLES_TAKE_OFFSET:
                        buy_qty = min(ask_vol, LIMIT - pos)
                        if buy_qty > 0:
                            orders.append(Order(p, ask_price, buy_qty))
                            pos += buy_qty

                # Sell at bid if bid > basket_fv (overpriced)
                for bid_price in sorted(od.buy_orders.keys(), reverse=True):
                    bid_vol = od.buy_orders[bid_price]
                    if bid_price > basket_fv + PEBBLES_TAKE_OFFSET:
                        sell_qty = min(bid_vol, LIMIT + pos)
                        if sell_qty > 0:
                            orders.append(Order(p, bid_price, -sell_qty))
                            pos -= sell_qty

                # Passive MM around basket FV with position skew
                skew = position_skew(pos, LIMIT, SOFT_LIMIT)
                fv_int = int(round(basket_fv))

                # Bid
                bid_offset = PEBBLES_MM_OFFSET
                if skew < 0:
                    bid_offset += 1  # Widen bid when long
                bid_price = fv_int - bid_offset
                bid_qty = min(PEBBLES_QUOTE_SIZE, LIMIT - pos)
                if bid_qty > 0:
                    # Penny: if our bid < best_bid, step up to best_bid
                    if bid_price < best_bid and best_bid < fv_int:
                        bid_price = best_bid
                    orders.append(Order(p, bid_price, bid_qty))

                # Ask
                ask_offset = PEBBLES_MM_OFFSET
                if skew > 0:
                    ask_offset += 1  # Widen ask when short
                ask_price = fv_int + ask_offset
                ask_qty = min(PEBBLES_QUOTE_SIZE, LIMIT + pos)
                if ask_qty > 0:
                    if ask_price > best_ask and best_ask > fv_int:
                        ask_price = best_ask
                    orders.append(Order(p, ask_price, -ask_qty))

                result[p] = orders
        else:
            # Fallback: MM with simple mid
            for p in PEBBLES:
                if p in state.order_depths:
                    result[p] = self._wall_mid_mm(p, state, MM_QUOTE_SIZE, MM_OFFSET)

        # ==================== TIER 2: SNACKPACK PAIRS ====================
        snack_mids = {}
        for p in SNACKPACK:
            if p in state.order_depths:
                snack_mids[p] = get_mid(state.order_depths[p])

        # Update pair sum rolling windows
        for p1, p2 in SNACK_PAIRS:
            key = f"{p1}_{p2}"
            if p1 in snack_mids and p2 in snack_mids:
                pair_sum = snack_mids[p1] + snack_mids[p2]
                if key not in self.snack_pair_sums:
                    self.snack_pair_sums[key] = []
                self.snack_pair_sums[key].append(pair_sum)
                # Keep only last WINDOW values
                if len(self.snack_pair_sums[key]) > SNACK_PAIR_WINDOW:
                    self.snack_pair_sums[key] = self.snack_pair_sums[key][-SNACK_PAIR_WINDOW:]

        # For each SNACKPACK product, compute FV using pair relationship
        snack_fvs = {}
        for p1, p2 in SNACK_PAIRS:
            key = f"{p1}_{p2}"
            if key in self.snack_pair_sums and len(self.snack_pair_sums[key]) >= 20:
                mean_sum = sum(self.snack_pair_sums[key]) / len(self.snack_pair_sums[key])

                # p1's FV implied by p2 and pair sum
                if p2 in snack_mids:
                    fv_p1 = mean_sum - snack_mids[p2]
                    if p1 not in snack_fvs:
                        snack_fvs[p1] = []
                    snack_fvs[p1].append(fv_p1)

                # p2's FV implied by p1 and pair sum
                if p1 in snack_mids:
                    fv_p2 = mean_sum - snack_mids[p1]
                    if p2 not in snack_fvs:
                        snack_fvs[p2] = []
                    snack_fvs[p2].append(fv_p2)

        for p in SNACKPACK:
            if p in state.order_depths:
                od = state.order_depths[p]
                if not od.buy_orders or not od.sell_orders:
                    continue

                # Use average of pair-implied FVs if available, else Wall Mid
                if p in snack_fvs and snack_fvs[p]:
                    fv = sum(snack_fvs[p]) / len(snack_fvs[p])
                else:
                    fv = get_wall_mid(od)

                result[p] = self._fv_mm(p, state, fv, SNACK_QUOTE_SIZE, 3)

        # ==================== TIER 3: MEAN-REVERTING PRODUCTS ====================
        for p, ac1 in HIGH_AC1.items():
            if p in state.order_depths:
                od = state.order_depths[p]
                if not od.buy_orders or not od.sell_orders:
                    continue

                # Wall Mid MM with mean-reversion adjustment
                wm = get_wall_mid(od)
                mid = get_mid(od)

                # Mean-reversion: when mid is above wall-mid, price likely to revert down
                # Lean our FV toward the wall-mid (away from current mid)
                reversion_signal = wm - mid  # positive = mid below wall, expect up
                fv = mid + MR_REVERSION_BETA * reversion_signal

                result[p] = self._fv_mm(p, state, fv, MR_QUOTE_SIZE, 1)

        # ==================== TIER 4: WALL-MID MM ON EVERYTHING ELSE ====================
        for p in ALL_PRODUCTS:
            if p not in result and p in state.order_depths:
                result[p] = self._wall_mid_mm(p, state, MM_QUOTE_SIZE, MM_OFFSET)

        # Save trader data
        new_td = {
            'sp': self.snack_pair_sums,
        }

        try:
            trader_data = json.dumps(new_td)
            if len(trader_data) > 49000:
                # Truncate pair sums if too large
                for key in self.snack_pair_sums:
                    self.snack_pair_sums[key] = self.snack_pair_sums[key][-50:]
                trader_data = json.dumps({'sp': self.snack_pair_sums})
        except:
            trader_data = ""

        return result, conversions, trader_data

    def _wall_mid_mm(self, product: str, state: TradingState,
                     quote_size: int, offset: int) -> list:
        """Generic Wall-Mid market making."""
        od = state.order_depths.get(product)
        if not od or not od.buy_orders or not od.sell_orders:
            return []

        fv = get_wall_mid(od)
        return self._fv_mm(product, state, fv, quote_size, offset)

    def _fv_mm(self, product: str, state: TradingState, fv: float,
               quote_size: int, offset: int) -> list:
        """Market making around a given fair value.

        Take: lift mispriced asks / hit mispriced bids vs FV.
        Make: post bid/ask around FV with position-aware skew.
        """
        od = state.order_depths.get(product)
        if not od or not od.buy_orders or not od.sell_orders:
            return []

        pos = state.position.get(product, 0)
        orders = []
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        fv_int = int(round(fv))

        # === TAKE: aggressive crossing when mispriced ===
        # Buy underpriced asks (ask <= fv - 1)
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price > fv_int - 1:
                break
            ask_vol = abs(od.sell_orders[ask_price])
            buy_qty = min(ask_vol, LIMIT - pos)
            if buy_qty > 0:
                orders.append(Order(product, ask_price, buy_qty))
                pos += buy_qty

        # Sell overpriced bids (bid >= fv + 1)
        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price < fv_int + 1:
                break
            bid_vol = od.buy_orders[bid_price]
            sell_qty = min(bid_vol, LIMIT + pos)
            if sell_qty > 0:
                orders.append(Order(product, bid_price, -sell_qty))
                pos -= sell_qty

        # === MAKE: passive quotes around FV ===
        skew = position_skew(pos, LIMIT, SOFT_LIMIT)

        # Bid
        bid_offset = offset
        if pos > SOFT_LIMIT:
            bid_offset += 1
        bid_price = fv_int - bid_offset
        bid_qty = min(quote_size, LIMIT - pos)
        if bid_qty > 0:
            # Penny: improve if we can
            if bid_price < best_bid and best_bid < fv_int:
                bid_price = best_bid
            orders.append(Order(product, bid_price, bid_qty))

        # Ask
        ask_offset = offset
        if pos < -SOFT_LIMIT:
            ask_offset += 1
        ask_price = fv_int + ask_offset
        ask_qty = min(quote_size, LIMIT + pos)
        if ask_qty > 0:
            if ask_price > best_ask and best_ask > fv_int:
                ask_price = best_ask
            orders.append(Order(product, ask_price, -ask_qty))

        return orders
