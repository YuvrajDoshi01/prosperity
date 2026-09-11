import json
from datamodel import Order, TradingState

"""
r2_v3 — Round 2 submission: r1_v4 structure + ADAPTIVE ACO FV bootstrap.

Context (2026-04-20, after R2 tutorial submission 274128):
  r2_v2 scored 8,412 on R2 website day 1 (IPR 7,386 + ACO 1,026). ACO position
  ended at -76 (near limit short). Root cause: website R2 day 1 has ACO mid
  fluctuating around 10005-10007 (not 10000). Our v2's hardcoded FV=10000 was
  7 ticks low → asks got hit repeatedly (we sold at ~10015, FV ~10007 = +8
  edge, GREAT), but bids never caught fills (bid at 9999 vs market 9998 or
  higher) → accumulated short, got stuck at -76.

  v17's tick-0 bootstrap would have worked (10008 snap is close to actual
  ~10007), but it's noisy — on R2 day -1 CSV, tick-0 wall-mid was 9992
  (18 ticks off). Need a more robust bootstrap.

Fix (this file): ADAPTIVE ACO FV.
  - Track mids of first BOOTSTRAP_WINDOW (=50) two-sided ticks.
  - Once we have 50 samples, set ACO_FV = round(median) and freeze.
  - Before bootstrap: use 10000 as provisional FV (same as v2/v4 behavior).
  - Simple, robust, handles FV shifts up to ±50 ticks naturally.

Everything else is byte-identical to r2_v2 (= r1_v4 + bid()=20000).

Why not v17's full defensive stack? On R2 CSV data, v17 scored 276,431 vs
v4's 288,323 (-11.9k) because v17's crash_mode/cubic skew/accumulation
suppression all fired spuriously on the misaligned tick-0 anchor. With a
robust bootstrap (median of 50), the crash_mode machinery is unnecessary —
the FV is already correct.
"""

MAF_BID = 20000

LIMIT = 80
SOFT_LIMIT = 40
BOOTSTRAP_WINDOW = 50  # ticks of mid-price history before finalizing FV

IPR = "INTARIAN_PEPPER_ROOT"
IPR_DRIFT_BIAS = 5.0
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3

ACO = "ASH_COATED_OSMIUM"
ACO_FV_DEFAULT = 10000
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
        self.aco_fv = None  # None until bootstrap completes

    def bid(self):
        return MAF_BID

    def _current_fv(self, book):
        """Returns the current ACO FV — adaptive bootstrap from median of first
        BOOTSTRAP_WINDOW two-sided mids, else ACO_FV_DEFAULT."""
        if self.aco_fv is not None:
            return self.aco_fv

        if book.buy_orders and book.sell_orders:
            mid = (max(book.buy_orders) + min(book.sell_orders)) * 0.5
            self.aco_mids.append(mid)
            if len(self.aco_mids) >= BOOTSTRAP_WINDOW:
                self.aco_fv = round(_median(self.aco_mids))
                return self.aco_fv

        return ACO_FV_DEFAULT

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
