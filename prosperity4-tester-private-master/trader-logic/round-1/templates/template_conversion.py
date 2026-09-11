import json
from datamodel import Order, TradingState

"""
template_conversion.py — Cross-exchange conversion arbitrage.

Strategy:
  - Each tick, compute implied bid/ask from conversion observations
  - If local ask < implied ask: buy locally, convert (export) next tick
  - If local bid > implied bid: sell locally, convert (import) next tick
  - Hidden taker bot detection: if sell orders at int(obs.bidPrice + 0.5) get
    filled consistently, exploit that pattern
  - Volume trigger: if best_bid_vol > 9, guaranteed fill on ask-side orders

Conversions return an integer: positive = import, negative = export.

UPDATE CHECKLIST when Round 1 data drops:
  1. Set PRODUCT to the actual symbol
  2. Set CONVERSION_LIMIT from the spec
  3. Set LIMIT from the spec
  4. Verify fee/tariff field names match the actual datamodel
  5. Tune EDGE_THRESHOLD (minimum profit per unit to trade)
"""

# ═══ CONFIG — UPDATE THESE ═══
PRODUCT = "MAGNIFICENT_MACARONS"  # UPDATE: product symbol
CONVERSION_LIMIT = 10             # UPDATE: max units per tick for conversions
LIMIT = 75                        # UPDATE: position limit

# Minimum edge (in price units) to trigger a conversion trade
EDGE_THRESHOLD = 0.5  # UPDATE: may need tuning based on fee structure

# Hidden taker bot detection
BOT_FILL_WINDOW = 10   # Ticks to track for pattern detection
BOT_FILL_THRESHOLD = 7  # Out of BOT_FILL_WINDOW ticks, how many fills needed


class Trader:
    def __init__(self):
        self.pending_conversion = 0   # conversion to submit this tick
        self.bot_fills = []           # tracking hidden taker bot fills

    def bid(self):
        return 15

    def run(self, state: TradingState):
        # ── Restore state ──
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.pending_conversion = td.get("pc", 0)
            self.bot_fills = td.get("bf", [])

        orders = {}
        conversions = 0

        # ── Submit pending conversion from last tick ──
        # Positive = import (buy from foreign, sell locally)
        # Negative = export (buy locally, sell to foreign)
        if self.pending_conversion != 0:
            conversions = self.pending_conversion
            self.pending_conversion = 0

        # ── Check conversion observations ──
        obs = None
        if hasattr(state, 'observations') and state.observations:
            conv_obs = getattr(state.observations, 'conversionObservations', None)
            if conv_obs and PRODUCT in conv_obs:
                obs = conv_obs[PRODUCT]

        if PRODUCT not in state.order_depths or obs is None:
            return orders, conversions, json.dumps({
                "pc": self.pending_conversion,
                "bf": self.bot_fills,
            }, separators=(",", ":"))

        od = state.order_depths[PRODUCT]
        if not od.buy_orders or not od.sell_orders:
            return orders, conversions, json.dumps({
                "pc": self.pending_conversion,
                "bf": self.bot_fills,
            }, separators=(",", ":"))

        pos = state.position.get(PRODUCT, 0)
        bb = max(od.buy_orders)
        ba = min(od.sell_orders)

        # ── Compute implied prices from foreign exchange ──
        # implied_bid = what we'd get selling to the foreign exchange (after fees)
        implied_bid = obs.bidPrice - obs.exportTariff - obs.transportFees
        # implied_ask = what we'd pay buying from the foreign exchange (after fees)
        implied_ask = obs.askPrice + obs.importTariff + obs.transportFees

        result = []
        next_conversion = 0

        # ── Strategy 1: Local buy + export (sell to foreign) ──
        # Buy locally at local ask, export next tick at implied_bid
        # Profit = implied_bid - local_ask
        if ba < implied_bid - EDGE_THRESHOLD:
            # How many can we export?
            export_qty = min(CONVERSION_LIMIT, LIMIT - pos)
            if export_qty > 0:
                # Buy locally
                for p, v in sorted(od.sell_orders.items()):
                    if export_qty <= 0:
                        break
                    if p < implied_bid - EDGE_THRESHOLD:
                        take = min(export_qty, -v)
                        result.append(Order(PRODUCT, p, take))
                        export_qty -= take
                # Schedule export for next tick (negative = export)
                bought = min(CONVERSION_LIMIT, LIMIT - pos) - export_qty
                if bought > 0:
                    next_conversion = -bought

        # ── Strategy 2: Import (buy from foreign) + local sell ──
        # Import at implied_ask, sell locally at local bid
        # Profit = local_bid - implied_ask
        if bb > implied_ask + EDGE_THRESHOLD:
            import_qty = min(CONVERSION_LIMIT, LIMIT + pos)
            if import_qty > 0:
                # Sell locally
                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if import_qty <= 0:
                        break
                    if p > implied_ask + EDGE_THRESHOLD:
                        take = min(import_qty, v)
                        result.append(Order(PRODUCT, p, -take))
                        import_qty -= take
                # Schedule import for next tick (positive = import)
                sold = min(CONVERSION_LIMIT, LIMIT + pos) - import_qty
                if sold > 0:
                    next_conversion = sold

        # ── Hidden taker bot detection ──
        # If there's a bot that consistently takes at int(obs.bidPrice + 0.5),
        # we can post sell orders there to get filled
        bot_target_price = int(obs.bidPrice + 0.5)
        filled = False
        if state.own_trades and PRODUCT in state.own_trades:
            for t in state.own_trades[PRODUCT]:
                if t.price == bot_target_price and t.quantity < 0:
                    filled = True
                    break
        self.bot_fills.append(1 if filled else 0)
        if len(self.bot_fills) > BOT_FILL_WINDOW:
            self.bot_fills = self.bot_fills[-BOT_FILL_WINDOW:]

        bot_detected = (
            len(self.bot_fills) == BOT_FILL_WINDOW
            and sum(self.bot_fills) >= BOT_FILL_THRESHOLD
        )

        if bot_detected:
            # Post sell order at the bot's target price
            ts = LIMIT + pos
            if ts > 0:
                result.append(Order(PRODUCT, bot_target_price, -min(ts, CONVERSION_LIMIT)))

        # ── Volume trigger: if best_bid_vol > 9, guaranteed fill on ask-side ──
        best_bid_vol = od.buy_orders.get(bb, 0)
        if best_bid_vol > 9:
            ts = LIMIT + pos
            if ts > 0 and not any(o.quantity < 0 and o.price == ba - 1 for o in result):
                result.append(Order(PRODUCT, ba - 1, -min(ts, 5)))

        self.pending_conversion = next_conversion

        if result:
            orders[PRODUCT] = result

        return orders, conversions, json.dumps({
            "pc": self.pending_conversion,
            "bf": self.bot_fills,
        }, separators=(",", ":"))
