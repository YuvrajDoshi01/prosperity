import json
from datamodel import Order, TradingState

"""
r1_v7_fullwm — r1_v7_fixed + ACO wall-mid FV.

v7_fixed restored wall-mid on IPR with the correct deepest-ask logic. This
variant extends the fix to ACO: replaces constant FV=10000 with wall-mid,
falling back to 10000 on one-sided books. Tests whether the historical
r1_v6 rejection was driven by the same _wall_mid bug.
"""

LIMIT = 80
SOFT_LIMIT = 40

IPR = "INTARIAN_PEPPER_ROOT"
IPR_DRIFT_BIAS = 5.0
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3

SLOPE_WINDOW = 5
DIR_WINDOW = 20
MIN_HISTORY = 10
UPTREND_THRESHOLD = 0.55
DOWNTREND_THRESHOLD = 0.35

ACO = "ASH_COATED_OSMIUM"
ACO_FALLBACK_FV = 10000
ACO_TAKE_WIDTH = 1
ACO_CLEAR_WIDTH = 0
ACO_DISREGARD_EDGE = 1
ACO_JOIN_EDGE = 2
ACO_DEFAULT_EDGE = 4
ACO_ADVERSE_VOL = 15


def _wall_mid(book, fallback):
    """(deepest_bid + deepest_ask) / 2. Deepest = highest |volume|."""
    if not (book.buy_orders and book.sell_orders):
        return fallback
    deep_bid = max(book.buy_orders, key=lambda p: book.buy_orders[p])
    deep_ask = max(book.sell_orders, key=lambda p: abs(book.sell_orders[p]))
    return (deep_bid + deep_ask) / 2.0


def _regression_slope(prices):
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

    def _aco(self, state):
        book = state.order_depths[ACO]
        if not (book.buy_orders or book.sell_orders):
            return []

        pos = state.position.get(ACO, 0)
        fv = _wall_mid(book, ACO_FALLBACK_FV)
        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos
        bought = sold = 0
        orders = []

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

    def _ipr_drift(self):
        n = len(self.ipr_directions)
        if n < MIN_HISTORY:
            return IPR_DRIFT_BIAS
        indicator = sum(1 for d in self.ipr_directions if d == 1) / n
        if indicator >= UPTREND_THRESHOLD:
            return IPR_DRIFT_BIAS
        if indicator <= DOWNTREND_THRESHOLD:
            return -IPR_DRIFT_BIAS
        return 0.0

    def _update_trend_state(self, price):
        self.ipr_mids.append(price)
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
            fv_base = _wall_mid(book, (best_bid + best_ask) * 0.5)
            self._update_trend_state(fv_base)
            drift = self._ipr_drift()
            fv_int = round(fv_base + drift)

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

            if buy_cap > 0:
                orders.append(Order(IPR, min(fv_int - 1, best_bid + 1, best_ask - 1), buy_cap))
            if sell_cap > 0:
                orders.append(Order(IPR, max(fv_int + 2, best_ask - 1, best_bid + 1), -sell_cap))

        else:
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
