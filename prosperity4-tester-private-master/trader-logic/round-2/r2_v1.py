import json
import math
from datamodel import Order, TradingState

"""
r2_v1 — Round 2 submission built on r1_v17 (bootstrap-only anchor).

Round 2 changes vs r1_v17:
  1. bid() returns MAF_BID (20000) — Market Access Fee for extra 25% flow.
  2. ACO FV uses _wall_mid() (volume-weighted) instead of simple mid. IPR
     already uses _wall_mid since v17. Matches Nancy's structural choice
     (rejected her OU calibration, kept wall-mid because it's stateless and
     volume-aware).
  3. OBI FV nudge on ACO: when book is extremely imbalanced and we are NOT
     in crash_mode, shift fv_eff by ±ACO_OBI_SHIFT. Gated behind OBI threshold
     to avoid interfering with normal mean-reversion logic. Sourced from
     Superduperbread's OBI reserve gate, simplified to a 0.5-tick FV bump.

Everything else identical to r1_v17. Keeping the defensive stack: cubic skew,
cur_mid crash trigger, accumulation suppression at |pos|>=60, bootstrap anchor.

Parameterization: all tunable constants are module-level so that a param_sweep
can override them for R2 tuning without editing method bodies.
"""

# ── Round 2 Market Access Fee ──────────────────────────────────────────────
# Single fixed integer; compared once at final R2 simulation, top-50% wins
# extra 25% order-book flow. First-price: pay your bid if you win.
# 20,000 = balanced: ~85% P(win) on our median-bid prior, captures ~85% of
# expected value (V≈87k across 3 days). See plan file for full math.
MAF_BID = 20000

LIMIT = 80

# ── IPR ────────────────────────────────────────────────────────────────────
IPR = "INTARIAN_PEPPER_ROOT"
IPR_DRIFT_BIAS = 5.0
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3

SLOPE_WINDOW = 5
DIR_WINDOW = 20
MIN_HISTORY = 10
UPTREND_THRESHOLD = 0.55
DOWNTREND_THRESHOLD = 0.35

IPR_SPREAD_WINDOW = 50
IPR_FALLBACK_EDGE = 14

# ── ACO ────────────────────────────────────────────────────────────────────
ACO = "ASH_COATED_OSMIUM"
ACO_FV = 10000
ACO_TAKE_WIDTH = 1
ACO_CLEAR_WIDTH = 0
ACO_DISREGARD_EDGE = 1
ACO_JOIN_EDGE = 2
ACO_DEFAULT_EDGE = 4
ACO_ADVERSE_VOL = 15

ACO_MAX_CONCESSION = 4.0
ACO_CRASH_THRESHOLD = 15
ACO_MID_WINDOW = 5
ACO_ACCUM_SUPPRESS_POS = 60
ACO_CRASH_JOIN_EDGE_BONUS = 4
ACO_CRASH_DEFAULT_EDGE_BONUS = 8

# R2 additions:
ACO_OBI_THRESHOLD = 0.25       # |imbalance| above this triggers FV shift
ACO_OBI_SHIFT = 0.5            # tick nudge in direction of imbalance


def _half_up(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def _wall_mid(book, fallback):
    if not (book.buy_orders and book.sell_orders):
        return fallback
    deep_bid = max(book.buy_orders, key=lambda p: (book.buy_orders[p], p))
    deep_ask = max(book.sell_orders, key=lambda p: (abs(book.sell_orders[p]), -p))
    return (deep_bid + deep_ask) / 2.0


def _obi(book):
    """Order-book imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol).
    Returns 0 if either side empty."""
    if not (book.buy_orders and book.sell_orders):
        return 0.0
    bb_vol = sum(book.buy_orders.values())
    ba_vol = sum(abs(v) for v in book.sell_orders.values())
    total = bb_vol + ba_vol
    return (bb_vol - ba_vol) / total if total > 0 else 0.0


def _regression_slope(prices):
    n = len(prices)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(prices) / n
    num = sum((i - x_mean) * (prices[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den > 0 else 0.0


def _aco_skew(pos):
    return ACO_MAX_CONCESSION * (pos / LIMIT) ** 3


def _snap_anchor(x):
    return 2 * round(x / 2)


class Trader:
    def __init__(self):
        self.ipr_mids = []
        self.ipr_directions = []
        self.ipr_spreads = []
        self.aco_mids = []
        self.aco_anchor = None

    def bid(self):
        return MAF_BID

    def _aco(self, state):
        book = state.order_depths[ACO]
        if not (book.buy_orders or book.sell_orders):
            return []

        pos = state.position.get(ACO, 0)
        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos
        bought = sold = 0
        orders = []

        if book.buy_orders and book.sell_orders:
            # R2: wall_mid instead of simple mid. Volume-weighted FV anchor.
            simple_mid = (max(book.buy_orders) + min(book.sell_orders)) * 0.5
            cur_mid = _wall_mid(book, simple_mid)
            if self.aco_anchor is None:
                self.aco_anchor = _snap_anchor(cur_mid)
            self.aco_mids.append(cur_mid)
            if len(self.aco_mids) > ACO_MID_WINDOW:
                self.aco_mids = self.aco_mids[-ACO_MID_WINDOW:]
            avg_mid = sum(self.aco_mids) / len(self.aco_mids)
        elif self.aco_mids:
            cur_mid = avg_mid = sum(self.aco_mids) / len(self.aco_mids)
        else:
            cur_mid = avg_mid = ACO_FV

        anchor = self.aco_anchor if self.aco_anchor is not None else ACO_FV
        crash_mode = abs(cur_mid - anchor) > ACO_CRASH_THRESHOLD

        if crash_mode:
            if pos >= ACO_ACCUM_SUPPRESS_POS:
                buy_cap = 0
            elif pos <= -ACO_ACCUM_SUPPRESS_POS:
                sell_cap = 0

        if crash_mode:
            base_fv = avg_mid
            active_default_edge = ACO_DEFAULT_EDGE + ACO_CRASH_DEFAULT_EDGE_BONUS
            active_join_edge = ACO_JOIN_EDGE + ACO_CRASH_JOIN_EDGE_BONUS
        else:
            base_fv = anchor
            active_default_edge = ACO_DEFAULT_EDGE
            active_join_edge = ACO_JOIN_EDGE

        fv_eff = base_fv - _aco_skew(pos)

        # R2: OBI nudge (normal mode only — crash mode already uses widened
        # logic and we don't want OBI to fight the recovery).
        if not crash_mode:
            imb = _obi(book)
            if imb > ACO_OBI_THRESHOLD:
                fv_eff += ACO_OBI_SHIFT
            elif imb < -ACO_OBI_THRESHOLD:
                fv_eff -= ACO_OBI_SHIFT

        if not crash_mode:
            for price, vol in sorted(book.sell_orders.items()):
                if buy_cap <= 0 or price > fv_eff - ACO_TAKE_WIDTH:
                    break
                if abs(vol) >= ACO_ADVERSE_VOL:
                    continue
                qty = min(buy_cap, -vol)
                orders.append(Order(ACO, price, qty))
                buy_cap -= qty
                bought += qty

            for price, vol in sorted(book.buy_orders.items(), reverse=True):
                if sell_cap <= 0 or price < fv_eff + ACO_TAKE_WIDTH:
                    break
                if vol >= ACO_ADVERSE_VOL:
                    continue
                qty = min(sell_cap, vol)
                orders.append(Order(ACO, price, -qty))
                sell_cap -= qty
                sold += qty

            pos_after = pos + bought - sold
            if pos_after > 0 and sell_cap > 0:
                fair_for_ask = _half_up(fv_eff + ACO_CLEAR_WIDTH)
                clearable = sum(v for p, v in book.buy_orders.items() if p >= fair_for_ask)
                qty = min(pos_after, clearable, sell_cap)
                if qty > 0:
                    orders.append(Order(ACO, fair_for_ask, -qty))
                    sell_cap -= qty
                    sold += qty
            elif pos_after < 0 and buy_cap > 0:
                fair_for_bid = _half_up(fv_eff - ACO_CLEAR_WIDTH)
                clearable = sum(-v for p, v in book.sell_orders.items() if p <= fair_for_bid)
                qty = min(-pos_after, clearable, buy_cap)
                if qty > 0:
                    orders.append(Order(ACO, fair_for_bid, qty))
                    buy_cap -= qty
                    bought += qty

        asks_above = [p for p in book.sell_orders if p > fv_eff + ACO_DISREGARD_EDGE]
        bids_below = [p for p in book.buy_orders if p < fv_eff - ACO_DISREGARD_EDGE]

        if asks_above:
            ref = min(asks_above)
            ask_price = ref if (ref - fv_eff) <= active_join_edge else ref - 1
        else:
            ask_price = _half_up(fv_eff + active_default_edge)

        if bids_below:
            ref = max(bids_below)
            bid_price = ref if (fv_eff - ref) <= active_join_edge else ref + 1
        else:
            bid_price = _half_up(fv_eff - active_default_edge)

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
            return 0.0
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

    def _ipr_one_sided_edge(self):
        if not self.ipr_spreads:
            return IPR_FALLBACK_EDGE
        return max(self.ipr_spreads)

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
            self.ipr_spreads.append(best_ask - best_bid)
            if len(self.ipr_spreads) > IPR_SPREAD_WINDOW:
                self.ipr_spreads = self.ipr_spreads[-IPR_SPREAD_WINDOW:]

            fv_base = _wall_mid(book, (best_bid + best_ask) * 0.5)
            self._update_trend_state(fv_base)
            drift = self._ipr_drift()
            fv_int = _half_up(fv_base + drift)

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
            edge = self._ipr_one_sided_edge()
            if has_bids and not has_asks:
                if sell_cap > 0:
                    orders.append(Order(IPR, best_bid + edge, -sell_cap))
            elif has_asks and not has_bids:
                if buy_cap > 0:
                    orders.append(Order(IPR, best_ask - edge, buy_cap))

        return orders

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.ipr_mids = saved.get("m", [])
            self.ipr_directions = saved.get("d", [])
            self.ipr_spreads = saved.get("s", [])
            self.aco_mids = saved.get("a", [])
            self.aco_anchor = saved.get("aa", None)

        result = {}
        if ACO in state.order_depths:
            result[ACO] = self._aco(state)
        if IPR in state.order_depths:
            result[IPR] = self._ipr(state)

        return result, 0, json.dumps(
            {
                "m": self.ipr_mids,
                "d": self.ipr_directions,
                "s": self.ipr_spreads,
                "a": self.aco_mids,
                "aa": self.aco_anchor,
            },
            separators=(",", ":")
        )
