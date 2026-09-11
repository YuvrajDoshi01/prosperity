"""r5_v3.py — IMC Prosperity 4 Round 5: 20-product strategy.

Builds on `sub_551355.py` (live $5,795 day-4-1k, imc BT $5,959, ratio 0.97).

BT 4-day imc: **$271,080 vs baseline $91,846 (+$179k / +195%)**
  Day 2: 70,887 (+17,818)
  Day 3:  -4,730 (+2,469)
  Day 4: 198,614 (+158,598)  ← ROBOT_DISHES jackpot day
  Day 5:   6,308 (+349, LIVE proxy)

Refactor vs v2:
  - STRATEGY_MAP -> module-level STRATEGY_CONFIG dict (per-product params)
  - generic_fair_value_and_width takes config dict (was strategy_type str)
  - reversion_coeff is per-product (was hardcoded -0.15)
  - risk_aversion is per-product (was hardcoded 1.0)
  - Two-pass run() loop (compute plan -> emit orders)
  - DISABLED_PRODUCTS set for ablation bisection
  - conversions = 0 (defensive; R5 has no conversion mechanism)

v3a additions (3 of 4 candidates passed per-product imc-BT gate):
  - ROBOT_DISHES (MEAN_REVERSION, coeff -0.10): +$151,152 4-day. d4=-0.29 dominant.
  - ROBOT_IRONING (MEAN_REVERSION, coeff -0.12): +$12,725 4-day.
  - PEBBLES_L (MOMENTUM):                         +$15,358 4-day.
  - PEBBLES_M dropped: -$24,633 (lost 3 of 4 days).

v3b (8 HIDDEN_LIQUIDITY tight-spread products) — REJECTED:
  HL width formula joins-not-pennies at spread<=8 (rounding interaction with
  default_edge=width+0.5). All 8 had ~$0 fills.

v3c (19 LIGHT MR wide-spread products) — REJECTED:
  All 19 negative on day-4 imc (-$11k to -$45k each). Random-walk products
  (AC(1) ≈ 0) generate adverse-selection on MR signal noise. -$600k 4-day total.

Final: 20 products active (17 v2 carryover + 3 v3a additions).
"""
import json
import jsonpickle
import numpy as np
import math
import copy
from typing import Any, List, Tuple, Dict

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        # We truncate state.traderData, trader_data, and self.logs to the same max. length to fit the log limit
        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])

        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]

        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )

        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        if observations:
            for product, observation in observations.conversionObservations.items():
                conversion_observations[product] = [
                    observation.bidPrice,
                    observation.askPrice,
                    observation.transportFees,
                    observation.exportTariff,
                    observation.importTariff,
                    observation.sugarPrice,
                    observation.sunlightIndex,
                ]

        return [observations.plainValueObservations if observations else {}, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])

        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if value is None:
            return ""
        lo, hi = 0, min(len(value), max_length)
        out = ""

        while lo <= hi:
            mid = (lo + hi) // 2

            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."

            encoded_candidate = json.dumps(candidate)

            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        return out


logger = Logger()


class Product:

    # Galaxy Sounds Recorders
    GALAXY_SOUNDS_DARK_MATTER = "GALAXY_SOUNDS_DARK_MATTER"
    GALAXY_SOUNDS_BLACK_HOLES = "GALAXY_SOUNDS_BLACK_HOLES"
    GALAXY_SOUNDS_PLANETARY_RINGS = "GALAXY_SOUNDS_PLANETARY_RINGS"
    GALAXY_SOUNDS_SOLAR_WINDS = "GALAXY_SOUNDS_SOLAR_WINDS"
    GALAXY_SOUNDS_SOLAR_FLAMES = "GALAXY_SOUNDS_SOLAR_FLAMES"

    # Vertical Sleeping Pods
    SLEEP_POD_SUEDE = "SLEEP_POD_SUEDE"
    SLEEP_POD_LAMB_WOOL = "SLEEP_POD_LAMB_WOOL"
    SLEEP_POD_POLYESTER = "SLEEP_POD_POLYESTER"
    SLEEP_POD_NYLON = "SLEEP_POD_NYLON"
    SLEEP_POD_COTTON = "SLEEP_POD_COTTON"

    # Organic Microchips
    MICROCHIP_CIRCLE = "MICROCHIP_CIRCLE"
    MICROCHIP_OVAL = "MICROCHIP_OVAL"
    MICROCHIP_SQUARE = "MICROCHIP_SQUARE"
    MICROCHIP_RECTANGLE = "MICROCHIP_RECTANGLE"
    MICROCHIP_TRIANGLE = "MICROCHIP_TRIANGLE"

    # Purification Pebbles
    PEBBLES_XS = "PEBBLES_XS"
    PEBBLES_S = "PEBBLES_S"
    PEBBLES_M = "PEBBLES_M"
    PEBBLES_L = "PEBBLES_L"
    PEBBLES_XL = "PEBBLES_XL"

    # Domestic Robots
    ROBOT_VACUUMING = "ROBOT_VACUUMING"
    ROBOT_MOPPING = "ROBOT_MOPPING"
    ROBOT_DISHES = "ROBOT_DISHES"
    ROBOT_LAUNDRY = "ROBOT_LAUNDRY"
    ROBOT_IRONING = "ROBOT_IRONING"

    # UV-Visors
    UV_VISOR_YELLOW = "UV_VISOR_YELLOW"
    UV_VISOR_AMBER = "UV_VISOR_AMBER"
    UV_VISOR_ORANGE = "UV_VISOR_ORANGE"
    UV_VISOR_RED = "UV_VISOR_RED"
    UV_VISOR_MAGENTA = "UV_VISOR_MAGENTA"

    # Instant Translators
    TRANSLATOR_SPACE_GRAY = "TRANSLATOR_SPACE_GRAY"
    TRANSLATOR_ASTRO_BLACK = "TRANSLATOR_ASTRO_BLACK"
    TRANSLATOR_ECLIPSE_CHARCOAL = "TRANSLATOR_ECLIPSE_CHARCOAL"
    TRANSLATOR_GRAPHITE_MIST = "TRANSLATOR_GRAPHITE_MIST"
    TRANSLATOR_VOID_BLUE = "TRANSLATOR_VOID_BLUE"

    # Construction Panels
    PANEL_1X2 = "PANEL_1X2"
    PANEL_2X2 = "PANEL_2X2"
    PANEL_1X4 = "PANEL_1X4"
    PANEL_2X4 = "PANEL_2X4"
    PANEL_4X4 = "PANEL_4X4"

    # Liquid Breath Oxygen Shakes
    OXYGEN_SHAKE_MORNING_BREATH = "OXYGEN_SHAKE_MORNING_BREATH"
    OXYGEN_SHAKE_EVENING_BREATH = "OXYGEN_SHAKE_EVENING_BREATH"
    OXYGEN_SHAKE_MINT = "OXYGEN_SHAKE_MINT"
    OXYGEN_SHAKE_CHOCOLATE = "OXYGEN_SHAKE_CHOCOLATE"
    OXYGEN_SHAKE_GARLIC = "OXYGEN_SHAKE_GARLIC"

    # Protein Snack Packs
    SNACKPACK_CHOCOLATE = "SNACKPACK_CHOCOLATE"
    SNACKPACK_VANILLA = "SNACKPACK_VANILLA"
    SNACKPACK_PISTACHIO = "SNACKPACK_PISTACHIO"
    SNACKPACK_STRAWBERRY = "SNACKPACK_STRAWBERRY"
    SNACKPACK_RASPBERRY = "SNACKPACK_RASPBERRY"




PARAMS = {

}


# ════════════════════════════════════════════════════════════════════
# r5_v3 STRATEGY_CONFIG — per-product strategy + params
#
# Phase = the ablation phase that introduced the entry. v3a/v3b/v3c.
# Config keys:
#   type            "MEAN_REVERSION" | "MOMENTUM" | "HIDDEN_LIQUIDITY"
#   reversion_coeff (MR only) lag-1 return regression coeff (negative).
#                   v2 default was -0.15 globally; v3 uses per-product
#                   = -clip(mean(|AC1_d2/3/4|), 0.05, 0.30) for new MR products.
#                   Carryover v2 products keep -0.15 to avoid regression risk.
#   risk_aversion   inventory penalty coefficient. 1.0 for proven products,
#                   2.0 for unproven (defensive default).
#
# DISABLED_PRODUCTS lets us bisect regressions without rebuilding versions.
# ════════════════════════════════════════════════════════════════════

STRATEGY_CONFIG = {
    # ───── v2 carryover (PROVEN) — keep original effective params ─────
    Product.OXYGEN_SHAKE_CHOCOLATE:      {"type": "MEAN_REVERSION", "reversion_coeff": -0.15, "risk_aversion": 1.0},
    Product.OXYGEN_SHAKE_EVENING_BREATH: {"type": "MEAN_REVERSION", "reversion_coeff": -0.15, "risk_aversion": 1.0},
    Product.OXYGEN_SHAKE_MINT:           {"type": "MEAN_REVERSION", "reversion_coeff": -0.15, "risk_aversion": 1.0},
    Product.OXYGEN_SHAKE_MORNING_BREATH: {"type": "MEAN_REVERSION", "reversion_coeff": -0.15, "risk_aversion": 1.0},
    Product.SNACKPACK_CHOCOLATE:         {"type": "MEAN_REVERSION", "reversion_coeff": -0.15, "risk_aversion": 1.0},
    Product.SNACKPACK_PISTACHIO:         {"type": "MEAN_REVERSION", "reversion_coeff": -0.15, "risk_aversion": 1.0},
    Product.SNACKPACK_RASPBERRY:         {"type": "MEAN_REVERSION", "reversion_coeff": -0.15, "risk_aversion": 1.0},
    Product.SNACKPACK_STRAWBERRY:        {"type": "MEAN_REVERSION", "reversion_coeff": -0.15, "risk_aversion": 1.0},
    Product.SNACKPACK_VANILLA:           {"type": "MEAN_REVERSION", "reversion_coeff": -0.15, "risk_aversion": 1.0},
    Product.PANEL_1X2:                   {"type": "MOMENTUM",       "risk_aversion": 1.0},
    Product.PANEL_1X4:                   {"type": "MOMENTUM",       "risk_aversion": 1.0},
    Product.PANEL_2X2:                   {"type": "MOMENTUM",       "risk_aversion": 1.0},
    Product.PANEL_2X4:                   {"type": "MOMENTUM",       "risk_aversion": 1.0},
    Product.PANEL_4X4:                   {"type": "MOMENTUM",       "risk_aversion": 1.0},
    Product.PEBBLES_S:                   {"type": "MOMENTUM",       "risk_aversion": 1.0},
    Product.PEBBLES_XL:                  {"type": "MOMENTUM",       "risk_aversion": 1.0},
    Product.PEBBLES_XS:                  {"type": "MOMENTUM",       "risk_aversion": 1.0},
    Product.ROBOT_LAUNDRY:               {"type": "HIDDEN_LIQUIDITY", "risk_aversion": 1.0},

    # ───── v3a additions (NEW alphas verified 2026-04-29) ─────
    # ROBOT_DISHES rho_d4=-0.29 is mostly a day-4 phenomenon (d2,d3 ≈ 0). Use 3-day avg -0.10.
    Product.ROBOT_DISHES:                {"type": "MEAN_REVERSION", "reversion_coeff": -0.10, "risk_aversion": 1.0},
    Product.ROBOT_IRONING:               {"type": "MEAN_REVERSION", "reversion_coeff": -0.12, "risk_aversion": 1.0},
    Product.PEBBLES_L:                   {"type": "MOMENTUM",       "risk_aversion": 1.0},
    # PEBBLES_M dropped: -$24,633 4-day, lost 3 of 4 days (architect's per-product gate)
    # v3b HIDDEN_LIQUIDITY additions for 8 tight-spread products dropped:
    # all had ~$0 fills (HL width formula joins-not-pennies at spread<=8 due to
    # rounding interaction with default_edge=width+0.5). Architect's +$500 d4 gate failed.
    # v3c LIGHT MR additions for 19 wide-spread products dropped:
    # ALL 19 negative on day 4 imc (-$11k to -$45k each). Random-walk products
    # (AC(1) ≈ 0) generate adverse-selection on MR signal noise. Architect prediction confirmed.
}

# Populated during ablation. Empty in shipping build.
DISABLED_PRODUCTS: set = set()


class Trader:
    def __init__(self, params=None):
        if params is None:
            params = PARAMS
        self.params = params

        self.LIMIT = {
            # Round 5 Products
            Product.GALAXY_SOUNDS_DARK_MATTER: 10,
            Product.GALAXY_SOUNDS_BLACK_HOLES: 10,
            Product.GALAXY_SOUNDS_PLANETARY_RINGS: 10,
            Product.GALAXY_SOUNDS_SOLAR_WINDS: 10,
            Product.GALAXY_SOUNDS_SOLAR_FLAMES: 10,
            Product.SLEEP_POD_SUEDE: 10,
            Product.SLEEP_POD_LAMB_WOOL: 10,
            Product.SLEEP_POD_POLYESTER: 10,
            Product.SLEEP_POD_NYLON: 10,
            Product.SLEEP_POD_COTTON: 10,
            Product.MICROCHIP_CIRCLE: 10,
            Product.MICROCHIP_OVAL: 10,
            Product.MICROCHIP_SQUARE: 10,
            Product.MICROCHIP_RECTANGLE: 10,
            Product.MICROCHIP_TRIANGLE: 10,
            Product.PEBBLES_XS: 10,
            Product.PEBBLES_S: 10,
            Product.PEBBLES_M: 10,
            Product.PEBBLES_L: 10,
            Product.PEBBLES_XL: 10,
            Product.ROBOT_VACUUMING: 10,
            Product.ROBOT_MOPPING: 10,
            Product.ROBOT_DISHES: 10,
            Product.ROBOT_LAUNDRY: 10,
            Product.ROBOT_IRONING: 10,
            Product.UV_VISOR_YELLOW: 10,
            Product.UV_VISOR_AMBER: 10,
            Product.UV_VISOR_ORANGE: 10,
            Product.UV_VISOR_RED: 10,
            Product.UV_VISOR_MAGENTA: 10,
            Product.TRANSLATOR_SPACE_GRAY: 10,
            Product.TRANSLATOR_ASTRO_BLACK: 10,
            Product.TRANSLATOR_ECLIPSE_CHARCOAL: 10,
            Product.TRANSLATOR_GRAPHITE_MIST: 10,
            Product.TRANSLATOR_VOID_BLUE: 10,
            Product.PANEL_1X2: 10,
            Product.PANEL_2X2: 10,
            Product.PANEL_1X4: 10,
            Product.PANEL_2X4: 10,
            Product.PANEL_4X4: 10,
            Product.OXYGEN_SHAKE_MORNING_BREATH: 10,
            Product.OXYGEN_SHAKE_EVENING_BREATH: 10,
            Product.OXYGEN_SHAKE_MINT: 10,
            Product.OXYGEN_SHAKE_CHOCOLATE: 10,
            Product.OXYGEN_SHAKE_GARLIC: 10,
            Product.SNACKPACK_CHOCOLATE: 10,
            Product.SNACKPACK_VANILLA: 10,
            Product.SNACKPACK_PISTACHIO: 10,
            Product.SNACKPACK_STRAWBERRY: 10,
            Product.SNACKPACK_RASPBERRY: 10,
        }

    def take_best_orders(
        self,
        product: str,
        fair_value: float,
        take_width: float,
        orders: List[Order],
        order_depth: OrderDepth,
        position: int,
        buy_order_volume: int,
        sell_order_volume: int,
        prevent_adverse: bool = False,
        adverse_volume: int = 0,
    ) -> Tuple[int, int]:
        position_limit = self.LIMIT[product]

        if len(order_depth.sell_orders) != 0:
            best_ask = min(order_depth.sell_orders.keys())
            best_ask_amount = -1 * order_depth.sell_orders[best_ask]

            if not prevent_adverse or abs(best_ask_amount) <= adverse_volume:
                if best_ask <= fair_value - take_width:
                    quantity = min(
                        best_ask_amount, position_limit - position
                    )  # max amt to buy
                    if quantity > 0:
                        orders.append(Order(product, best_ask, quantity))
                        buy_order_volume += quantity
                        order_depth.sell_orders[best_ask] += quantity
                        if order_depth.sell_orders[best_ask] == 0:
                            del order_depth.sell_orders[best_ask]

        if len(order_depth.buy_orders) != 0:
            best_bid = max(order_depth.buy_orders.keys())
            best_bid_amount = order_depth.buy_orders[best_bid]

            if not prevent_adverse or abs(best_bid_amount) <= adverse_volume:
                if best_bid >= fair_value + take_width:
                    quantity = min(
                        best_bid_amount, position_limit + position
                    )  # max amt to sell
                    if quantity > 0:
                        orders.append(Order(product, best_bid, -1 * quantity))
                        sell_order_volume += quantity
                        order_depth.buy_orders[best_bid] -= quantity
                        if order_depth.buy_orders[best_bid] == 0:
                            del order_depth.buy_orders[best_bid]

        return buy_order_volume, sell_order_volume

    def market_make(
        self,
        product: str,
        orders: List[Order],
        bid: int,
        ask: int,
        position: int,
        buy_order_volume: int,
        sell_order_volume: int,
    ) -> Tuple[int, int]:
        buy_quantity = self.LIMIT[product] - (position + buy_order_volume)
        if buy_quantity > 0:
            orders.append(Order(product, round(bid), buy_quantity))

        sell_quantity = self.LIMIT[product] + (position - sell_order_volume)
        if sell_quantity > 0:
            orders.append(Order(product, round(ask), -sell_quantity))
            
        return buy_order_volume, sell_order_volume

    def clear_position_order(
        self,
        product: str,
        fair_value: float,
        width: float,
        orders: List[Order],
        order_depth: OrderDepth,
        position: int,
        buy_order_volume: int,
        sell_order_volume: int,
    ) -> Tuple[int, int]:
        position_after_take = position + buy_order_volume - sell_order_volume
        fair_for_bid = round(fair_value - width)
        fair_for_ask = round(fair_value + width)

        buy_quantity = self.LIMIT[product] - (position + buy_order_volume)
        sell_quantity = self.LIMIT[product] + (position - sell_order_volume)

        if position_after_take > 0:
            clear_quantity = min(sell_quantity, position_after_take)
            sent_quantity = 0
            
            bids_sorted = sorted(list(order_depth.buy_orders.keys()), reverse=True)
            for bid_price in bids_sorted:
                if bid_price >= fair_for_ask:
                    vol = order_depth.buy_orders[bid_price]
                    taken = min(vol, clear_quantity - sent_quantity)
                    if taken > 0:
                        sent_quantity += taken
                        order_depth.buy_orders[bid_price] -= taken
                        if order_depth.buy_orders[bid_price] == 0:
                            del order_depth.buy_orders[bid_price]
                if sent_quantity >= clear_quantity:
                    break
                    
            if sent_quantity > 0:
                orders.append(Order(product, fair_for_ask, -abs(sent_quantity)))
                sell_order_volume += abs(sent_quantity)

        if position_after_take < 0:
            clear_quantity = min(buy_quantity, abs(position_after_take))
            sent_quantity = 0
            
            asks_sorted = sorted(list(order_depth.sell_orders.keys()))
            for ask_price in asks_sorted:
                if ask_price <= fair_for_bid:
                    vol = abs(order_depth.sell_orders[ask_price])
                    taken = min(vol, clear_quantity - sent_quantity)
                    if taken > 0:
                        sent_quantity += taken
                        order_depth.sell_orders[ask_price] += taken 
                        if order_depth.sell_orders[ask_price] == 0:
                            del order_depth.sell_orders[ask_price]
                if sent_quantity >= clear_quantity:
                    break
                    
            if sent_quantity > 0:
                orders.append(Order(product, fair_for_bid, abs(sent_quantity)))
                buy_order_volume += abs(sent_quantity)

        return buy_order_volume, sell_order_volume

    def take_orders(
        self,
        product: str,
        order_depth: OrderDepth,
        fair_value: float,
        take_width: float,
        position: int,
        prevent_adverse: bool = False,
        adverse_volume: int = 0,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        buy_order_volume = 0
        sell_order_volume = 0

        buy_order_volume, sell_order_volume = self.take_best_orders(
            product, fair_value, take_width, orders, order_depth, position, buy_order_volume, sell_order_volume, prevent_adverse, adverse_volume,
        )
        return orders, buy_order_volume, sell_order_volume

    def clear_orders(
        self,
        product: str,
        order_depth: OrderDepth,
        fair_value: float,
        clear_width: float,
        position: int,
        buy_order_volume: int,
        sell_order_volume: int,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        buy_order_volume, sell_order_volume = self.clear_position_order(
            product, fair_value, clear_width, orders, order_depth, position, buy_order_volume, sell_order_volume,
        )
        return orders, buy_order_volume, sell_order_volume

    def make_orders(
        self,
        product: str,
        order_depth: OrderDepth,
        fair_value: float,
        position: int,
        buy_order_volume: int,
        sell_order_volume: int,
        disregard_edge: float,  
        join_edge: float,  
        default_edge: float,  
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        asks_above_fair = [price for price in order_depth.sell_orders.keys() if price > fair_value + disregard_edge]
        bids_below_fair = [price for price in order_depth.buy_orders.keys() if price < fair_value - disregard_edge]

        best_ask_above_fair = min(asks_above_fair) if len(asks_above_fair) > 0 else None
        best_bid_below_fair = max(bids_below_fair) if len(bids_below_fair) > 0 else None

        ask = round(fair_value + default_edge)
        if best_ask_above_fair is not None:
            if abs(best_ask_above_fair - fair_value) <= join_edge:
                ask = best_ask_above_fair 
            else:
                ask = best_ask_above_fair - 1 

        bid = round(fair_value - default_edge)
        if best_bid_below_fair is not None:
            if abs(fair_value - best_bid_below_fair) <= join_edge:
                bid = best_bid_below_fair
            else:
                bid = best_bid_below_fair + 1
        
        buy_order_volume, sell_order_volume = self.market_make(
            product, orders, bid, ask, position, buy_order_volume, sell_order_volume,
        )

        return orders, buy_order_volume, sell_order_volume

    def generic_fair_value_and_width(
        self,
        product: str,
        state: TradingState,
        traderObject: Dict,
        position: int,
        config: dict,
    ) -> Tuple[float, float]:
        strategy_type = config["type"]
        reversion_coeff = config.get("reversion_coeff", -0.15)
        risk_aversion = config.get("risk_aversion", 1.0)

        order_depth = state.order_depths[product]
        
        has_asks = len(order_depth.sell_orders) > 0
        has_bids = len(order_depth.buy_orders) > 0

        best_ask = min(order_depth.sell_orders.keys()) if has_asks else None
        best_bid = max(order_depth.buy_orders.keys()) if has_bids else None

        if best_ask is not None and best_bid is not None:
            mid = (best_ask + best_bid) / 2.0
            spread = best_ask - best_bid
        elif best_ask is not None:
            mid = best_ask - 2.0
            spread = 4.0
        elif best_bid is not None:
            mid = best_bid + 2.0
            spread = 4.0
        else:
            mid = traderObject.get(f"{product}_prev_mid", 10000.0)
            spread = 4.0

        traderObject[f"{product}_prev_mid"] = mid

        # --- Daily Range Tracking ---
        day_min = traderObject.get(f"{product}_day_min", mid)
        day_max = traderObject.get(f"{product}_day_max", mid)
        day_min = min(day_min, mid)
        day_max = max(day_max, mid)
        traderObject[f"{product}_day_min"] = day_min
        traderObject[f"{product}_day_max"] = day_max

        range_mid = max(day_max - day_min, 1e-6)
        percentile = (mid - day_min) / range_mid

        # --- Tracking Returns History ---
        prev_mid = traderObject.get(f"{product}_last_mid", mid)
        last_ret = mid - prev_mid
        traderObject[f"{product}_last_mid"] = mid

        fair_value = mid
        inventory_adjustment = -position * risk_aversion
        dynamic_width = max(1.5, (spread / 2.0) + 0.5)

        if strategy_type == "MEAN_REVERSION":
            # reversion_coeff is per-product (negative); legacy v2 default is -0.15
            expected_mid = mid + reversion_coeff * last_ret
            if product == Product.SNACKPACK_CHOCOLATE:
                expected_mid -= (percentile - 0.60) * 5.0
            fair_value = expected_mid + inventory_adjustment

        elif strategy_type == "MOMENTUM":
            # Product: PEBBLES_XL
            # Whales buy at top, dump at bottom.
            # We skew our fair value towards the trend to avoid adverse selection
            expected_mid = mid + (percentile - 0.5) * 5.0
            fair_value = expected_mid + inventory_adjustment
            
            # Spread widens at the top
            dynamic_width = max(1.0, spread * (0.3 + 0.5 * percentile))

        elif strategy_type == "HIDDEN_LIQUIDITY":
            # Product: ROBOT_LAUNDRY
            # Penny the spread to capture hidden volume
            fair_value = mid + inventory_adjustment
            dynamic_width = max(1.0, (spread / 2.0) - 0.5) 

        return fair_value, dynamic_width


    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        original_order_depths = state.order_depths
        state.order_depths = copy.deepcopy(original_order_depths)

        traderObject = {}
        if state.traderData is not None and state.traderData != "":
            traderObject = jsonpickle.decode(state.traderData)

        result = {}

        # Pass 1 — compute (fair_value, width, config, position) per active product
        plan = {}
        for product, config in STRATEGY_CONFIG.items():
            if product in DISABLED_PRODUCTS:
                continue
            if product not in state.order_depths:
                continue
            position = state.position.get(product, 0)
            fv, w = self.generic_fair_value_and_width(
                product, state, traderObject, position, config
            )
            plan[product] = (fv, w, config, position)

        # Pass 2 — emit orders per product
        for product, (fair_value, dynamic_width, config, position) in plan.items():
            take_orders, buy_vol, sell_vol = self.take_orders(
                product, state.order_depths[product], fair_value, dynamic_width + 0.5, position
            )
            clear_width = dynamic_width + 1.0
            clear_orders, buy_vol, sell_vol = self.clear_orders(
                product, state.order_depths[product], fair_value, clear_width, position, buy_vol, sell_vol
            )
            make_orders, _, _ = self.make_orders(
                product, state.order_depths[product], fair_value, position, buy_vol, sell_vol,
                disregard_edge=0.0,
                join_edge=dynamic_width,
                default_edge=dynamic_width + 0.5,
            )
            result[product] = take_orders + clear_orders + make_orders

        conversions = 0
        trader_data = jsonpickle.encode(traderObject)

        logger.flush(state, result, conversions, trader_data)
        state.order_depths = original_order_depths
        return result, conversions, trader_data