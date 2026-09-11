import json
from datamodel import Order, TradingState

"""
r2_v4 — Round 2 submission: r1_v4 structure + fast adaptive ACO FV.

Context (2026-04-20):
  r2_v2 (submission 274128) scored 8,412 on R2 day 1 website (IPR 7,386 +
  ACO 1,026). Root cause: website R2 day 1 ACO FV ≈ 10004 (median 10004,
  mode 10002), NOT 10000. Position ended at -76 (stuck short).

  r2_v3 tried median-of-first-50 bootstrap but regressed on local CSV because
  the CSV realization differs from website (CSV ACO mean 9983 vs website 9994
  with median 10004). CSV is not reliable ground truth.

Fix (this file): median-of-first-10 ticks → FV frozen.
  - First 10 ticks: use provisional FV = 10000 (same as v2).
  - At tick 10: FV = round(median of first 10 mids), frozen for rest of day.
  - Fast enough to engage by tick 10 (~1% of day).
  - 10-sample median is robust to one-off tick anomalies.
  - Handles FV shifts of any size (10000, 10004, 10007, 14000, etc.).

Why N=10 not 50? Faster engagement. On R2 day 1 website, the first 50 mids
had median 10009 (closer to tick-0 value of 10007). First 10 mids would
plausibly median to ~10006, still close to true median of 10004 but engages
4× sooner. Trade-off: higher variance, but acceptable for a small N.

Everything else is byte-identical to r2_v2 (= r1_v4 + bid()=20000).

Keeps IPR simple mid + drift_bias=5 unchanged (R2 data diff showed IPR
structure identical to R1, just +1000 level shift).
"""

MAF_BID = 20000

LIMIT = 80
SOFT_LIMIT = 40
BOOTSTRAP_WINDOW = 10

IPR = "INTARIAN_PEPPER_ROOT"
IPR_DRIFT_BIAS = 5.0
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3

ACO = "ASH_COATED_OSMIUM"
ACO_FV_PROVISIONAL = 10000
ACO_TAKE_WIDTH = 1
ACO_CLEAR_WIDTH = 0
ACO_DISREGARD_EDGE = 1
ACO_JOIN_EDGE = 2
ACO_DEFAULT_EDGE = 4
ACO_ADVERSE_VOL = 15


def _median(values):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


class Trader:
    def __init__(self):
        self.aco_mids = []
        self.aco_fv = None

    def bid(self):
        return MAF_BID

    def _current_fv(self, book):
        if self.aco_fv is not None:
            return self.aco_fv
        if book.buy_orders and book.sell_orders:
            mid = (max(book.buy_orders) + min(book.sell_orders)) * 0.5
            self.aco_mids.append(mid)
            if len(self.aco_mids) >= BOOTSTRAP_WINDOW:
                self.aco_fv = round(_median(self.aco_mids))
                return self.aco_fv
        return ACO_FV_PROVISIONAL

    def _aco(self, state):
        book = state.order_depths[ACO]
        if not (book.buy_orders or book.sell_orders):
            return []

        pos = state.position.get(ACO, 0)
        fv = self._current_fv(book)
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
            fv_int = round(mid + IPR_DRIFT_BIAS)

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
            self.aco_mids = saved.get("m", [])
            self.aco_fv = saved.get("fv", None)

        result = {}
        if ACO in state.order_depths:
            result[ACO] = self._aco(state)
        if IPR in state.order_depths:
            result[IPR] = self._ipr(state)

        return result, 0, json.dumps(
            {"m": self.aco_mids, "fv": self.aco_fv},
            separators=(",", ":")
        )
