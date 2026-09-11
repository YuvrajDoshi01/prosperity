"""
Module 4: Quote Timing Optimizer

Decides WHAT to leave on the book between run() calls.
Uses bot phases (Module 2) and toxicity rates (Module 3) to:
  - Widen spread when toxic bot is about to act
  - Tighten spread when benign bot is about to act
  - Adjust reservation price based on inventory + time

Implements Avellaneda-Stoikov with discrete bot timing adjustments.
"""

import math
from datamodel import Order, TradingState

# Default toxicity rates (from Module 3 offline analysis)
# Update these per round from adverse_selection.py output
DEFAULT_TOXICITY = {
    'TOMATOES_TAKER': 0.45,  # ~45% of fills are adverse at 500ms horizon
    'EMERALDS_TAKER': 0.40,
}

# A-S parameters (tune per product)
DEFAULT_PARAMS = {
    'TOMATOES': {
        'gamma': 0.05,           # risk aversion
        'sigma_sq': 1.80,        # variance per tick (std=1.34)
        'k': 0.04,              # order arrival rate (trades per tick)
        'default_half_spread': 1, # base half-spread in ticks
    },
    'EMERALDS': {
        'gamma': 0.01,
        'sigma_sq': 0.5,
        'k': 0.02,
        'default_half_spread': 1,
    },
}


class QuoteTimingOptimizer:
    def __init__(self, bot_tracker, toxicity_rates=None, params=None):
        self.bot_tracker = bot_tracker
        self.toxicity = toxicity_rates or DEFAULT_TOXICITY
        self.params = params or DEFAULT_PARAMS

    def compute_quotes(self, state: TradingState, fair_values: dict,
                       danger_window_ms: float = 300,
                       danger_threshold: float = 0.8,
                       spread_multiplier: float = 1.5) -> dict:
        """
        Compute optimal quotes for all products.

        Args:
            state: current TradingState
            fair_values: dict[product -> float] estimated fair prices
            danger_window_ms: how far ahead to look for incoming toxic flow
            danger_threshold: above this danger level, pull quotes entirely
            spread_multiplier: how much to widen per unit of danger

        Returns:
            dict[product -> list[Order]]
        """
        orders = {}
        current_ts = state.timestamp
        # Approximate time remaining (fraction of day)
        T_MAX = 999900  # last timestamp of a full day
        time_remaining = max(0.01, (T_MAX - current_ts) / T_MAX)

        for product in state.order_depths:
            od = state.order_depths[product]
            if not od.buy_orders or not od.sell_orders:
                continue

            position = state.position.get(product, 0)
            fv = fair_values.get(product)
            if fv is None:
                continue

            p = self.params.get(product, DEFAULT_PARAMS.get('TOMATOES'))

            # Compute danger level from bot phases
            danger = self._compute_danger(product, current_ts, danger_window_ms)

            if danger > danger_threshold:
                # High danger: pull quotes entirely
                orders[product] = []
                continue

            # A-S reservation price: shift fair value based on inventory + time
            reservation = fv - position * p['gamma'] * p['sigma_sq'] * time_remaining

            # A-S optimal spread (modified for bot timing)
            base_spread = (p['gamma'] * p['sigma_sq'] * time_remaining +
                          (2 / max(p['gamma'], 0.001)) * math.log(1 + p['gamma'] / max(p['k'], 0.001)))

            # Adjust spread for danger level
            adjusted_spread = max(p['default_half_spread'],
                                 base_spread * (1 + spread_multiplier * danger))

            bid_price = round(reservation - adjusted_spread)
            ask_price = round(reservation + adjusted_spread)

            # Clamp to not cross the spread
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            bid_price = min(bid_price, best_ask - 1)
            ask_price = max(ask_price, best_bid + 1)

            product_orders = []

            # Compute position-aware sizes
            limit = 80  # default, override per product
            max_buy = limit - position
            max_sell = limit + position

            if max_buy > 0:
                product_orders.append(Order(product, int(bid_price), max_buy))
            if max_sell > 0:
                product_orders.append(Order(product, int(ask_price), -max_sell))

            orders[product] = product_orders

        return orders

    def _compute_danger(self, product: str, current_ts: int,
                        danger_window_ms: float) -> float:
        """
        Aggregate danger level from all bots that trade this product.
        High danger = toxic bot about to act = widen spread or pull quotes.
        """
        danger = 0.0
        for bot_id, tox_rate in self.toxicity.items():
            profile = self.bot_tracker.profiles.get(bot_id)
            if not profile or product not in profile.active_products:
                continue

            urgency = self.bot_tracker.urgency(bot_id, current_ts, danger_window_ms)
            danger += tox_rate * urgency

        return min(1.0, danger)

    def compute_taking_orders(self, state: TradingState, fair_values: dict) -> dict:
        """
        Separate taking logic: aggressively take from the book when mispriced.
        This runs BEFORE passive quoting.
        """
        orders = {}
        for product in state.order_depths:
            od = state.order_depths[product]
            if not od.buy_orders or not od.sell_orders:
                continue

            fv = fair_values.get(product)
            if fv is None:
                continue

            position = state.position.get(product, 0)
            limit = 80
            to_buy = limit - position
            to_sell = limit + position

            product_orders = []

            # Take sells at/below fair
            for price in sorted(od.sell_orders.keys()):
                if to_buy <= 0 or price > fv:
                    break
                vol = min(to_buy, abs(od.sell_orders[price]))
                product_orders.append(Order(product, price, vol))
                to_buy -= vol

            # Take bids at/above fair
            for price in sorted(od.buy_orders.keys(), reverse=True):
                if to_sell <= 0 or price < fv:
                    break
                vol = min(to_sell, od.buy_orders[price])
                product_orders.append(Order(product, price, -vol))
                to_sell -= vol

            orders[product] = product_orders

        return orders
