import json
from datamodel import Order, TradingState

"""
template_basket.py — Basket/ETF arbitrage.

Strategy:
  1. Compute synthetic = sum(weight * component_mid) for each component
  2. spread = basket_mid - synthetic
  3. rolling_std = std(spread, window=STD_WINDOW)
  4. z = (spread - SPREAD_MEAN) / rolling_std
  5. if z > ZSCORE_THRESHOLD: sell basket (spread too wide, will revert)
  6. if z < -ZSCORE_THRESHOLD: buy basket
  7. DO NOT hedge with components (reduces EV per playbook)
  8. Post at best +/- 1 on basket only

UPDATE CHECKLIST when Round 1 data drops:
  1. Set BASKET_PRODUCT and COMPONENTS from the round spec
  2. Compute SPREAD_MEAN from first day's data
  3. Tune ZSCORE_THRESHOLD (start with 7, lower if too few trades)
  4. Set LIMIT and TARGET_POSITION from the spec
  5. Check if Olivia signal helps (see template_olivia.py)
"""

# ═══ CONFIG — UPDATE THESE FROM SAMPLE DATA ANALYSIS ═══
BASKET_PRODUCT = "PICNIC_BASKET"                               # UPDATE: the basket symbol
COMPONENTS = {"CROISSANTS": 6, "JAMS": 3, "DJEMBES": 1}       # UPDATE: weight map
SPREAD_MEAN = 380.0      # UPDATE: hardcode from first day's data
ZSCORE_THRESHOLD = 7      # Linear Utility's proven threshold
STD_WINDOW = 45           # Rolling std window (small = sensitive to regime changes)
TARGET_POSITION = 58      # Near position limit for max edge
LIMIT = 60                # UPDATE: position limit

# Olivia cross-product adjustment (set to 0 to disable)
# If Olivia detected long on a component: shift ZSCORE_THRESHOLD for longs down
# (more eager to go long basket when Olivia is bullish on component)
OLIVIA_ZSCORE_SHIFT = 0.0  # UPDATE: tune from data, e.g., 0.5


class Trader:
    def __init__(self):
        self.spread_history = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        # ── Restore state ──
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.spread_history = td.get("sh", [])

        orders = {}

        # ── Compute component mids ──
        component_mids = {}
        all_available = True
        for product in COMPONENTS:
            if product in state.order_depths:
                od = state.order_depths[product]
                if od.buy_orders and od.sell_orders:
                    component_mids[product] = (max(od.buy_orders) + min(od.sell_orders)) / 2
                else:
                    all_available = False
                    break
            else:
                all_available = False
                break

        # ── Compute basket mid ──
        basket_available = False
        basket_mid = 0
        if BASKET_PRODUCT in state.order_depths:
            bod = state.order_depths[BASKET_PRODUCT]
            if bod.buy_orders and bod.sell_orders:
                basket_mid = (max(bod.buy_orders) + min(bod.sell_orders)) / 2
                basket_available = True

        if all_available and basket_available:
            # ── Synthetic price ──
            synthetic = sum(
                COMPONENTS[prod] * component_mids[prod]
                for prod in COMPONENTS
            )

            # ── Spread and z-score ──
            spread = basket_mid - synthetic
            self.spread_history.append(spread)
            if len(self.spread_history) > STD_WINDOW:
                self.spread_history = self.spread_history[-STD_WINDOW:]

            if len(self.spread_history) >= 2:
                mean_s = sum(self.spread_history) / len(self.spread_history)
                var_s = sum((x - mean_s) ** 2 for x in self.spread_history) / len(self.spread_history)
                std_s = var_s ** 0.5 if var_s > 0 else 1e-6

                z = (spread - SPREAD_MEAN) / std_s

                # ── Olivia adjustment placeholder ──
                # If Olivia is bullish on a component, lower the buy threshold
                # olivia_shift_buy = -OLIVIA_ZSCORE_SHIFT if olivia_bullish else 0
                # olivia_shift_sell = OLIVIA_ZSCORE_SHIFT if olivia_bearish else 0
                buy_threshold = -ZSCORE_THRESHOLD   # + olivia_shift_buy
                sell_threshold = ZSCORE_THRESHOLD    # + olivia_shift_sell

                pos = state.position.get(BASKET_PRODUCT, 0)
                bb = max(bod.buy_orders)
                ba = min(bod.sell_orders)
                result = []

                if z > sell_threshold:
                    # Spread too wide -> sell basket (expect reversion)
                    target = -TARGET_POSITION
                    qty = pos - target  # positive = we need to sell
                    if qty > 0:
                        # Take existing bids aggressively
                        remaining = qty
                        for p, v in sorted(bod.buy_orders.items(), reverse=True):
                            if remaining <= 0:
                                break
                            take = min(remaining, v)
                            result.append(Order(BASKET_PRODUCT, p, -take))
                            remaining -= take
                        # Post remainder at best ask - 1
                        if remaining > 0:
                            result.append(Order(BASKET_PRODUCT, ba - 1, -remaining))

                elif z < buy_threshold:
                    # Spread too narrow -> buy basket (expect reversion)
                    target = TARGET_POSITION
                    qty = target - pos  # positive = we need to buy
                    if qty > 0:
                        # Take existing asks aggressively
                        remaining = qty
                        for p, v in sorted(bod.sell_orders.items()):
                            if remaining <= 0:
                                break
                            take = min(remaining, -v)
                            result.append(Order(BASKET_PRODUCT, p, take))
                            remaining -= take
                        # Post remainder at best bid + 1
                        if remaining > 0:
                            result.append(Order(BASKET_PRODUCT, bb + 1, remaining))

                else:
                    # No strong signal: passive market making around basket
                    tb = LIMIT - pos
                    ts = LIMIT + pos
                    if tb > 0:
                        result.append(Order(BASKET_PRODUCT, bb + 1, min(tb, 5)))
                    if ts > 0:
                        result.append(Order(BASKET_PRODUCT, ba - 1, -min(ts, 5)))

                if result:
                    orders[BASKET_PRODUCT] = result

        return orders, 0, json.dumps({
            "sh": self.spread_history,
        }, separators=(",", ":"))
