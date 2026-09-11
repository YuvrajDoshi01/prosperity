import json
from datamodel import Order, TradingState

"""
template_olivia.py — Olivia detection module.

Olivia is a high-value bot that trades in signature quantities (abs(qty) == 15).
She buys at daily lows (bullish signal) and sells at daily highs (bearish signal).

Usage as standalone: runs as a Trader, prints Olivia signals via traderData.
Usage as import: copy OliviaTracker class into another template and call
  tracker.update(mid, market_trades) each tick.

Signal interpretation:
  +1 = bullish (Olivia buying at lows)
  -1 = bearish (Olivia selling at highs)
   0 = neutral (no recent signal or invalidated)

Invalidation: signal resets to 0 if price moves 5 ticks against the signal
direction after the signal was set.

UPDATE CHECKLIST:
  1. Set PRODUCTS to the symbols you want to track Olivia on
  2. Tune OLIVIA_QTY if the signature quantity changes
  3. Tune INVALIDATION_TICKS based on product volatility
"""

# ═══ CONFIG ═══
PRODUCTS = ["KELP", "RAINFOREST_RESIN"]  # UPDATE: products to track
OLIVIA_QTY = 15           # Olivia's signature trade quantity
INVALIDATION_TICKS = 5    # Price move against signal to invalidate


class OliviaTracker:
    """Tracks Olivia's activity on a single product."""

    def __init__(self):
        self.daily_min = float('inf')
        self.daily_max = float('-inf')
        self.signal = 0        # +1 = bullish, -1 = bearish, 0 = neutral
        self.signal_price = 0  # mid price when signal was set

    def update(self, mid, market_trades):
        """Call each tick with current mid price and market trades list."""
        self.daily_min = min(self.daily_min, mid)
        self.daily_max = max(self.daily_max, mid)

        for trade in market_trades:
            if abs(trade.quantity) == OLIVIA_QTY:  # Olivia's signature
                if trade.price <= self.daily_min:
                    self.signal = 1   # buying at low = bullish
                    self.signal_price = mid
                elif trade.price >= self.daily_max:
                    self.signal = -1  # selling at high = bearish
                    self.signal_price = mid

        # Invalidation: if new extreme contradicts signal
        if self.signal == 1 and mid < self.signal_price - INVALIDATION_TICKS:
            self.signal = 0
        elif self.signal == -1 and mid > self.signal_price + INVALIDATION_TICKS:
            self.signal = 0

    def save(self):
        """Serialize to dict for traderData."""
        return {
            "mn": self.daily_min,
            "mx": self.daily_max,
            "sg": self.signal,
            "sp": self.signal_price,
        }

    def load(self, d):
        """Restore from dict loaded from traderData."""
        if d:
            self.daily_min = d.get("mn", float('inf'))
            self.daily_max = d.get("mx", float('-inf'))
            self.signal = d.get("sg", 0)
            self.signal_price = d.get("sp", 0)


class Trader:
    """Standalone Trader that tracks Olivia signals across all configured products.
    Signals are stored in traderData and can be read by other templates."""

    def __init__(self):
        self.trackers = {p: OliviaTracker() for p in PRODUCTS}

    def bid(self):
        return 15

    def run(self, state: TradingState):
        # ── Restore state ──
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            for product in PRODUCTS:
                key = f"ol_{product}"
                if key in td:
                    self.trackers[product].load(td[key])

        orders = {}

        # ── Update trackers ──
        for product in PRODUCTS:
            if product in state.order_depths:
                od = state.order_depths[product]
                if od.buy_orders and od.sell_orders:
                    mid = (max(od.buy_orders) + min(od.sell_orders)) / 2
                    trades = state.market_trades.get(product, [])
                    self.trackers[product].update(mid, trades)

        # ── Save state ──
        save_data = {}
        for product in PRODUCTS:
            save_data[f"ol_{product}"] = self.trackers[product].save()

        # No orders — this template is purely for signal tracking.
        # To act on signals, integrate OliviaTracker into another template
        # and use tracker.signal to adjust thresholds/positions.

        return orders, 0, json.dumps(save_data, separators=(",", ":"))
