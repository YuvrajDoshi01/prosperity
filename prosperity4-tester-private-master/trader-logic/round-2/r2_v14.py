import json
import math
import statistics
import numpy as np
from datamodel import Order, OrderDepth, TradingState

"""
r2_v14 — Full submission: v13 ACO + v9 IPR

ACO (from v13): composite microprice+MR signal (IC=0.500) + spread-regime
  conditioning (tight spreads → wider takes, tighter makes) + crash mode +
  cubic skew. L2 imbalance removed (IC=-0.075). Absolute adverse_vol=15.

IPR (from v9): 228959 trend-following, no warmup gate.
  v9 beats v8/v11 by +174 BT / +174 IMC (warmup gate skips tick-0 lift).
"""

LIMIT = 80

# ── ACO Parameters ───────────────────────────────────────────────────────────
ACO = "ASH_COATED_OSMIUM"
ACO_FV = 10000

ACO_TAKE_WIDTH = 1
ACO_CLEAR_WIDTH = 0
ACO_DISREGARD_EDGE = 1
ACO_JOIN_EDGE = 2
ACO_DEFAULT_EDGE = 4
ACO_ADVERSE_VOL = 15

ACO_TIGHT_SPREAD_THRESHOLD = 14
ACO_TIGHT_TAKE_WIDTH = 2
ACO_TIGHT_JOIN_EDGE = 3
ACO_TIGHT_DEFAULT_EDGE = 3

ACO_MR_BETA = 0.10
ACO_MAX_CONCESSION = 4.0
ACO_MID_WINDOW = 21

ACO_CRASH_FLOOR = 15
ACO_CRASH_K_MAD = 4.0
ACO_MAD_WARMUP = 50
ACO_BOOTSTRAP_SAMPLES = 20
ACO_CRASH_EXIT_RATIO = 0.7
ACO_ACCUM_SUPPRESS_POS = 60
ACO_CRASH_JOIN_EDGE_BONUS = 4
ACO_CRASH_DEFAULT_EDGE_BONUS = 8

# ── IPR Parameters ───────────────────────────────────────────────────────────
IPR = "INTARIAN_PEPPER_ROOT"
PEPPER_SPREAD_GRADIENT = 0.0010586880760
PEPPER_SPREAD_INTERCEPT = 0.8694130152902


# ── ACO Helpers ──────────────────────────────────────────────────────────────

def _half_up(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def _cubic_skew(pos):
    return ACO_MAX_CONCESSION * (pos / LIMIT) ** 3


def _snap_anchor(x):
    return 2 * _half_up(x / 2)


def _mad(samples, center):
    return statistics.median(abs(s - center) for s in samples)


def _microprice(book: OrderDepth) -> float:
    best_bid = max(book.buy_orders)
    best_ask = min(book.sell_orders)
    bid_vol = book.buy_orders[best_bid]
    ask_vol = abs(book.sell_orders[best_ask])
    total = bid_vol + ask_vol
    if total == 0:
        return (best_bid + best_ask) * 0.5
    return (best_ask * bid_vol + best_bid * ask_vol) / total


class Trader:
    def __init__(self):
        self.aco_mids = []
        self.aco_bootstrap = []
        self.aco_anchor = None
        self.aco_in_crash = False
        self.aco_mad_samples = []
        self.aco_mad_frozen = None

    def bid(self):
        return 2000

    # ═══ ACO: v13 composite + regime + crash ═══

    def _aco(self, state):
        book = state.order_depths.get(ACO)
        if not book or not (book.buy_orders or book.sell_orders):
            return []

        pos = state.position.get(ACO, 0)
        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos
        bought = sold = 0
        orders = []

        has_both = bool(book.buy_orders) and bool(book.sell_orders)

        # ── Observe: microprice + anchor bootstrap ───────────────────────
        if has_both:
            cur_mid = _microprice(book)

            if self.aco_anchor is None:
                self.aco_bootstrap.append(cur_mid)
                if len(self.aco_bootstrap) >= ACO_BOOTSTRAP_SAMPLES:
                    self.aco_anchor = _snap_anchor(
                        statistics.median(self.aco_bootstrap)
                    )

            self.aco_mids.append(cur_mid)
            if len(self.aco_mids) > ACO_MID_WINDOW:
                self.aco_mids = self.aco_mids[-ACO_MID_WINDOW:]

            spread = min(book.sell_orders) - max(book.buy_orders)
        else:
            cur_mid = self.aco_mids[-1] if self.aco_mids else ACO_FV
            spread = 16

        anchor = self.aco_anchor if self.aco_anchor is not None else ACO_FV
        med_mid = statistics.median(self.aco_mids) if self.aco_mids else ACO_FV

        # ── MAD calibration ──────────────────────────────────────────────
        if self.aco_mad_frozen is None and self.aco_anchor is not None:
            if self.aco_mids:
                self.aco_mad_samples.append(self.aco_mids[-1])
            if len(self.aco_mad_samples) >= ACO_MAD_WARMUP:
                self.aco_mad_frozen = _mad(self.aco_mad_samples, self.aco_anchor)
                self.aco_mad_samples = []

        threshold = (
            max(ACO_CRASH_FLOOR, ACO_CRASH_K_MAD * self.aco_mad_frozen)
            if self.aco_mad_frozen is not None
            else ACO_CRASH_FLOOR
        )

        # ── Crash mode (hysteresis) ─────────────────────────────────────
        dev = abs(cur_mid - anchor)
        if self.aco_in_crash:
            if dev < ACO_CRASH_EXIT_RATIO * threshold:
                self.aco_in_crash = False
        else:
            if dev > threshold:
                self.aco_in_crash = True

        crash = self.aco_in_crash

        # ── Spread regime ────────────────────────────────────────────────
        tight = spread <= ACO_TIGHT_SPREAD_THRESHOLD and not crash

        if crash:
            take_width = ACO_TAKE_WIDTH
            join_edge = ACO_JOIN_EDGE + ACO_CRASH_JOIN_EDGE_BONUS
            default_edge = ACO_DEFAULT_EDGE + ACO_CRASH_DEFAULT_EDGE_BONUS
        elif tight:
            take_width = ACO_TIGHT_TAKE_WIDTH
            join_edge = ACO_TIGHT_JOIN_EDGE
            default_edge = ACO_TIGHT_DEFAULT_EDGE
        else:
            take_width = ACO_TAKE_WIDTH
            join_edge = ACO_JOIN_EDGE
            default_edge = ACO_DEFAULT_EDGE

        # ── Composite FV: microprice + mean-reversion blend ──────────────
        if crash:
            base_fv = med_mid
        else:
            base_fv = cur_mid - ACO_MR_BETA * (cur_mid - anchor)

        fv_eff = base_fv - _cubic_skew(pos)

        # ── Crash: suppress accumulation ─────────────────────────────────
        if crash:
            if pos >= ACO_ACCUM_SUPPRESS_POS:
                buy_cap = 0
            elif pos <= -ACO_ACCUM_SUPPRESS_POS:
                sell_cap = 0

        # ── 1. TAKE ─────────────────────────────────────────────────────
        if not crash:
            for price, vol in sorted(book.sell_orders.items()):
                if buy_cap <= 0 or price > fv_eff - take_width:
                    break
                if abs(vol) >= ACO_ADVERSE_VOL:
                    continue
                qty = min(buy_cap, -vol)
                orders.append(Order(ACO, price, qty))
                buy_cap -= qty
                bought += qty

            for price, vol in sorted(book.buy_orders.items(), reverse=True):
                if sell_cap <= 0 or price < fv_eff + take_width:
                    break
                if vol >= ACO_ADVERSE_VOL:
                    continue
                qty = min(sell_cap, vol)
                orders.append(Order(ACO, price, -qty))
                sell_cap -= qty
                sold += qty

            # ── 2. CLEAR ────────────────────────────────────────────────
            pos_after = pos + bought - sold
            if pos_after > 0 and sell_cap > 0:
                fair = _half_up(fv_eff + ACO_CLEAR_WIDTH)
                clearable = sum(
                    v for p, v in book.buy_orders.items() if p >= fair
                )
                qty = min(pos_after, clearable, sell_cap)
                if qty > 0:
                    orders.append(Order(ACO, fair, -qty))
                    sell_cap -= qty
                    sold += qty
            elif pos_after < 0 and buy_cap > 0:
                fair = _half_up(fv_eff - ACO_CLEAR_WIDTH)
                clearable = sum(
                    -v for p, v in book.sell_orders.items() if p <= fair
                )
                qty = min(-pos_after, clearable, buy_cap)
                if qty > 0:
                    orders.append(Order(ACO, fair, qty))
                    buy_cap -= qty
                    bought += qty

        # ── 3. MAKE ─────────────────────────────────────────────────────
        asks_above = [p for p in book.sell_orders if p > fv_eff + ACO_DISREGARD_EDGE]
        bids_below = [p for p in book.buy_orders if p < fv_eff - ACO_DISREGARD_EDGE]

        if asks_above:
            ref = min(asks_above)
            ask_price = ref if (ref - fv_eff) <= join_edge else ref - 1
        else:
            ask_price = _half_up(fv_eff + default_edge)

        if bids_below:
            ref = max(bids_below)
            bid_price = ref if (fv_eff - ref) <= join_edge else ref + 1
        else:
            bid_price = _half_up(fv_eff - default_edge)

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        if buy_cap > 0:
            orders.append(Order(ACO, bid_price, buy_cap))
        if sell_cap > 0:
            orders.append(Order(ACO, ask_price, -sell_cap))

        return orders

    # ═══ IPR: v9 228959 trend-following (no warmup gate) ═══

    @staticmethod
    def _regression_slope(prices):
        x = np.arange(len(prices))
        y = np.array(prices)
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        denom = np.sum((x - x_mean) ** 2)
        if denom == 0:
            return 0.0
        return float(np.sum((x - x_mean) * (y - y_mean)) / denom)

    @staticmethod
    def _wall_mid(book: OrderDepth):
        best_vol, deep_bid = 0, 0
        for price, vol in book.buy_orders.items():
            if vol > best_vol:
                best_vol = vol
                deep_bid = price

        best_vol, deep_ask = 0, 0
        for price, vol in book.sell_orders.items():
            if vol < best_vol:
                best_vol = vol
                deep_ask = price

        return (deep_bid + deep_ask) / 2

    def _ipr(self, book: OrderDepth, pos, prev_mids, slope, directions):
        orders = []

        wall_mid = prev_mids[-1] + slope if prev_mids else 10000
        best_ask = best_bid = None
        ask_quantity = bid_quantity = 0

        if book.buy_orders and book.sell_orders:
            wall_mid = self._wall_mid(book)
            best_ask = min(book.sell_orders)
            ask_quantity = book.sell_orders[best_ask]
            best_bid = max(book.buy_orders)
            bid_quantity = book.buy_orders[best_bid]
        elif book.sell_orders:
            best_ask = min(book.sell_orders)
            ask_quantity = book.sell_orders[best_ask]
        elif book.buy_orders:
            best_bid = max(book.buy_orders)
            bid_quantity = book.buy_orders[best_bid]

        prev_mids = [wall_mid] if prev_mids is None else prev_mids + [wall_mid]
        if len(prev_mids) > 5:
            prev_mids.pop(0)
            slope = self._regression_slope(prev_mids)
        else:
            slope = 0

        trend = 1 if slope >= 0 else -1
        directions = [trend] if directions is None else directions + [trend]
        if len(directions) > 20:
            directions.pop(0)
        indicator = directions.count(1) / len(directions)

        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos

        mid_spread = (PEPPER_SPREAD_GRADIENT * wall_mid + PEPPER_SPREAD_INTERCEPT) / 2

        if indicator >= 0.5:
            target = 80

            if pos <= 0.9 * target:
                fair_purchase = math.floor(wall_mid + mid_spread)
                best_ask = min(best_ask, fair_purchase) if best_ask else fair_purchase
                orders.append(Order(IPR, best_ask, buy_cap))

            elif pos < target:
                if best_ask and best_ask <= wall_mid:
                    buy_qty = min(buy_cap, -ask_quantity)
                    orders.append(Order(IPR, best_ask, buy_qty))
                    buy_cap -= buy_qty
                if best_bid and best_bid < wall_mid - mid_spread / 2:
                    orders.append(Order(IPR, best_bid + 1, buy_cap))

            elif best_ask and best_ask > wall_mid + mid_spread / 2:
                orders.append(Order(IPR, best_ask - 1, -sell_cap))

        else:
            target = -80

            # len(prev_mids)==10 never true (capped at 5) — intentional long-bias
            if pos >= 0.9 * target and len(prev_mids) == 10:
                if best_bid:
                    orders.append(Order(IPR, best_bid, -sell_cap))
                else:
                    orders.append(Order(IPR, math.floor(wall_mid - mid_spread), -sell_cap))

            elif pos > target:
                if best_bid and best_bid >= wall_mid:
                    sell_qty = min(sell_cap, bid_quantity)
                    orders.append(Order(IPR, best_bid, -sell_qty))
                    sell_cap -= sell_qty
                if best_ask and best_ask > wall_mid + mid_spread / 2:
                    orders.append(Order(IPR, best_ask - 1, -sell_cap))

            elif best_bid and best_bid < wall_mid - mid_spread / 2:
                orders.append(Order(IPR, best_bid + 1, buy_cap))

        return orders, prev_mids, slope, directions

    # ═══ Main ═══

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if isinstance(saved, dict):
            # ACO state
            self.aco_mids = saved.get("am", [])
            self.aco_anchor = saved.get("aa")
            self.aco_bootstrap = saved.get("ab", [])
            self.aco_in_crash = saved.get("ac", False)
            self.aco_mad_samples = saved.get("as", [])
            self.aco_mad_frozen = saved.get("af")
        else:
            saved = {}

        result = {}

        # ACO
        if ACO in state.order_depths:
            result[ACO] = self._aco(state)

        # IPR
        if IPR in state.order_depths:
            orders, mids, slope, dirs = self._ipr(
                state.order_depths[IPR],
                state.position.get(IPR, 0),
                saved.get("mids"),
                saved.get("slope", 0),
                saved.get("dirs"),
            )
            result[IPR] = orders
            saved["mids"] = mids
            saved["slope"] = slope
            saved["dirs"] = dirs

        # Persist ACO state
        saved["am"] = self.aco_mids
        saved["aa"] = self.aco_anchor
        saved["ab"] = self.aco_bootstrap
        saved["ac"] = self.aco_in_crash
        saved["as"] = self.aco_mad_samples
        saved["af"] = self.aco_mad_frozen

        return result, 0, json.dumps(saved, separators=(",", ":"))
