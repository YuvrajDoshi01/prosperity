"""
Module 6: Position Limit Manager

Allocates order sizes respecting per-side worst-case limits.
Priority: most aggressive orders get allocated first (highest fill probability).

The exchange checks buys and sells INDEPENDENTLY for worst-case:
  max_buy_volume = position_limit - current_position
  max_sell_volume = position_limit + current_position
If EITHER side exceeds, ALL orders for that product are rejected.
"""

from datamodel import Order

# Default limits — update per round as new products are added
POSITION_LIMITS = {
    "TOMATOES": 80,
    "EMERALDS": 80,
}


class PositionLimitManager:
    def __init__(self, limits: dict = None):
        self.limits = limits or POSITION_LIMITS

    def headroom(self, product: str, position: int) -> tuple:
        """Returns (buy_headroom, sell_headroom)."""
        limit = self.limits.get(product, 80)
        return limit - position, limit + position

    def allocate(self, product: str, position: int,
                 desired_bids: list, desired_asks: list) -> tuple:
        """
        Trim orders to fit within position limits.
        Bids sorted by price descending (most aggressive first).
        Asks sorted by price ascending (most aggressive first).
        Returns (allocated_bids, allocated_asks).
        """
        limit = self.limits.get(product, 80)
        max_buy = limit - position
        max_sell = limit + position

        # Sort: most aggressive bids first (highest price)
        sorted_bids = sorted(desired_bids, key=lambda o: o.price, reverse=True)
        # Sort: most aggressive asks first (lowest price)
        sorted_asks = sorted(desired_asks, key=lambda o: abs(o.price))

        allocated_bids = []
        remaining_buy = max_buy
        for order in sorted_bids:
            if remaining_buy <= 0:
                break
            size = min(order.quantity, remaining_buy)
            if size > 0:
                allocated_bids.append(Order(product, order.price, size))
                remaining_buy -= size

        allocated_asks = []
        remaining_sell = max_sell
        for order in sorted_asks:
            qty = abs(order.quantity)
            if remaining_sell <= 0:
                break
            size = min(qty, remaining_sell)
            if size > 0:
                allocated_asks.append(Order(product, order.price, -size))
                remaining_sell -= size

        return allocated_bids, allocated_asks

    def validate(self, product: str, position: int, orders: list) -> bool:
        """Check if a set of orders would pass the exchange's limit check."""
        limit = self.limits.get(product, 80)
        total_buy = sum(o.quantity for o in orders if o.quantity > 0)
        total_sell = sum(abs(o.quantity) for o in orders if o.quantity < 0)
        return (position + total_buy <= limit and
                position - total_sell >= -limit)
