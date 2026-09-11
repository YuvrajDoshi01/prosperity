import json
from datamodel import Order, TradingState

"""
r1_v5 — Round 1 Strategy (r1_v4 + IPR Trend-Reversal Guardrail)

Adds risk management on top of r1_v4 (website 10,624.84):
- Rolling regression slope over last SLOPE_WINDOW mids
- Direction history tally over last DIR_WINDOW signs-of-slope
- Dynamic drift_bias: +5 default (uptrend), 0 neutral, -5 confirmed downtrend

Asymmetric thresholds (0.55 / 0.35) give defensive protection:
- p=0.55 upper threshold has ~33% chance by chance under random-walk null
- p=0.35 lower threshold has ~13% chance by chance under random-walk null
- We require stronger evidence (13%-tail) to flip SHORT than to flip LONG

If the guardrail stays quiet on uptrend days → behaviorally identical to r1_v4.
If drift reverses (Round 2+ or unseen day) → strategy adapts instead of bleeding.

ACO: unchanged from r1_v4 (Linear Utility framework).
"""

# ═══ SHARED ═══
LIMIT = 80
SOFT_LIMIT = 40

# ═══ IPR (r1_v4 base + guardrail) ═══
IPR = "INTARIAN_PEPPER_ROOT"
IPR_DRIFT_BIAS = 5.0        # default magnitude; sign controlled by guardrail
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3

# Guardrail params (structural, not backtest-tuned)
SLOPE_WINDOW = 5            # min stable-slope window
DIR_WINDOW = 20             # direction history length (~2% of tutorial)
MIN_HISTORY = 10            # wait for ≥10 direction samples before flipping
UPTREND_THRESHOLD = 0.55    # ≥55% upward slopes → confirmed uptrend
DOWNTREND_THRESHOLD = 0.35  # ≤35% upward slopes → confirmed downtrend

# ═══ ACO (Linear Utility AMETHYSTS port — unchanged) ═══
ACO = "ASH_COATED_OSMIUM"
ACO_FV = 10000
ACO_TAKE_WIDTH = 1
ACO_CLEAR_WIDTH = 0
ACO_DISREGARD_EDGE = 1
ACO_JOIN_EDGE = 2
ACO_DEFAULT_EDGE = 4
ACO_ADVERSE_VOL = 15


def _regression_slope(prices):
    """OLS slope of prices against their indices. Returns 0 for <2 points or zero-variance x."""
    n = len(prices)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(prices) / n
    num = sum((i - x_mean) * (prices[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den > 0 else 0.0


class Trader:
    def __init__(self):
        self.ipr_mids = []
        self.ipr_directions = []

    def bid(self):
        return 15

    # ═══════════════════════════════════════════════════════════
    # ACO: Linear Utility framework (unchanged from r1_v4)
    # ═══════════════════════════════════════════════════════════

    def _aco(self, state):
        book = state.order_depths[ACO]
        if not (book.buy_orders or book.sell_orders):
            return []

        pos = state.position.get(ACO, 0)
        fv = ACO_FV
        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos
        bought = sold = 0
        orders = []

        # Take
        for price, vol in sorted(book.sell_orders.items()):
            if buy_cap <= 0 or price > fv - ACO_TAKE_WIDTH:
                break
            if abs(vol) >= ACO_ADVERSE_VOL:
                continue
            qty = min(buy_cap, -vol)
            orders.append(Order(ACO, price, qty))
            buy_cap -= qty
            bought += qty

        for price, vol in sorted(book.buy_orders.items(), reverse=True):
            if sell_cap <= 0 or price < fv + ACO_TAKE_WIDTH:
                break
            if vol >= ACO_ADVERSE_VOL:
                continue
            qty = min(sell_cap, vol)
            orders.append(Order(ACO, price, -qty))
            sell_cap -= qty
            sold += qty

        # Clear at FV
        pos_after = pos + bought - sold
        if pos_after > 0 and sell_cap > 0:
            fair_for_ask = round(fv + ACO_CLEAR_WIDTH)
            clearable = sum(v for p, v in book.buy_orders.items() if p >= fair_for_ask)
            qty = min(pos_after, clearable, sell_cap)
            if qty > 0:
                orders.append(Order(ACO, fair_for_ask, -qty))
                sell_cap -= qty
                sold += qty
        elif pos_after < 0 and buy_cap > 0:
            fair_for_bid = round(fv - ACO_CLEAR_WIDTH)
            clearable = sum(-v for p, v in book.sell_orders.items() if p <= fair_for_bid)
            qty = min(-pos_after, clearable, buy_cap)
            if qty > 0:
                orders.append(Order(ACO, fair_for_bid, qty))
                buy_cap -= qty
                bought += qty

        # Make
        asks_above = [p for p in book.sell_orders if p > fv + ACO_DISREGARD_EDGE]
        bids_below = [p for p in book.buy_orders if p < fv - ACO_DISREGARD_EDGE]

        if asks_above:
            ref = min(asks_above)
            ask_price = ref if (ref - fv) <= ACO_JOIN_EDGE else ref - 1
        else:
            ask_price = round(fv + ACO_DEFAULT_EDGE)

        if bids_below:
            ref = max(bids_below)
            bid_price = ref if (fv - ref) <= ACO_JOIN_EDGE else ref + 1
        else:
            bid_price = round(fv - ACO_DEFAULT_EDGE)

        if pos > SOFT_LIMIT:
            ask_price -= 1
        elif pos < -SOFT_LIMIT:
            bid_price += 1
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        if buy_cap > 0:
            orders.append(Order(ACO, bid_price, buy_cap))
        if sell_cap > 0:
            orders.append(Order(ACO, ask_price, -sell_cap))

        return orders

    # ═══════════════════════════════════════════════════════════
    # IPR: r1_v4 base + guardrail
    # ═══════════════════════════════════════════════════════════

    def _ipr_drift(self):
        """Return signed drift_bias based on current trend state.
        Default +5 during warmup and confirmed uptrend, 0 during unclear,
        -5 during confirmed downtrend."""
        n = len(self.ipr_directions)
        if n < MIN_HISTORY:
            return IPR_DRIFT_BIAS  # warmup: assume default uptrend

        indicator = sum(1 for d in self.ipr_directions if d == 1) / n
        if indicator >= UPTREND_THRESHOLD:
            return IPR_DRIFT_BIAS
        if indicator <= DOWNTREND_THRESHOLD:
            return -IPR_DRIFT_BIAS
        return 0.0

    def _update_trend_state(self, mid):
        """Update rolling mids + direction history."""
        self.ipr_mids.append(mid)
        if len(self.ipr_mids) > SLOPE_WINDOW:
            self.ipr_mids = self.ipr_mids[-SLOPE_WINDOW:]

        if len(self.ipr_mids) == SLOPE_WINDOW:
            slope = _regression_slope(self.ipr_mids)
            self.ipr_directions.append(1 if slope >= 0 else -1)
            if len(self.ipr_directions) > DIR_WINDOW:
                self.ipr_directions = self.ipr_directions[-DIR_WINDOW:]

    def _ipr(self, state):
        book = state.order_depths[IPR]
        has_bids = bool(book.buy_orders)
        has_asks = bool(book.sell_orders)

        if not (has_bids or has_asks):
            return []

        best_bid = max(book.buy_orders) if has_bids else None
        best_ask = min(book.sell_orders) if has_asks else None
        pos = state.position.get(IPR, 0)
        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos
        orders = []

        if has_bids and has_asks:
            mid = (best_bid + best_ask) * 0.5
            self._update_trend_state(mid)
            drift = self._ipr_drift()
            fv_int = round(mid + drift)

            # Asymmetric takes
            for price, vol in sorted(book.sell_orders.items()):
                if buy_cap > 0 and price <= fv_int + IPR_BUY_SLACK:
                    qty = min(buy_cap, -vol)
                    orders.append(Order(IPR, price, qty))
                    buy_cap -= qty

            for price, vol in sorted(book.buy_orders.items(), reverse=True):
                if sell_cap > 0 and price >= fv_int + IPR_SELL_SLACK:
                    qty = min(sell_cap, vol)
                    orders.append(Order(IPR, price, -qty))
                    sell_cap -= qty

            # Post: aggressive bid, defensive ask
            if buy_cap > 0:
                orders.append(Order(IPR, min(fv_int - 1, best_bid + 1, best_ask - 1), buy_cap))
            if sell_cap > 0:
                orders.append(Order(IPR, max(fv_int + 2, best_ask - 1, best_bid + 1), -sell_cap))

        else:
            # One-sided book (no trend update — unreliable mid)
            if has_bids and not has_asks:
                if buy_cap > 0:
                    orders.append(Order(IPR, best_bid + 1, buy_cap))
                if sell_cap > 0:
                    orders.append(Order(IPR, best_bid + 14, -sell_cap))
            elif has_asks and not has_bids:
                if buy_cap > 0:
                    orders.append(Order(IPR, best_ask - 14, buy_cap))
                if sell_cap > 0:
                    orders.append(Order(IPR, best_ask - 1, -sell_cap))

        return orders

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.ipr_mids = saved.get("m", [])
            self.ipr_directions = saved.get("d", [])

        result = {}
        if ACO in state.order_depths:
            result[ACO] = self._aco(state)
        if IPR in state.order_depths:
            result[IPR] = self._ipr(state)

        return result, 0, json.dumps(
            {"m": self.ipr_mids, "d": self.ipr_directions},
            separators=(",", ":")
        )
