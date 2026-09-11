import json
import math
import statistics
import numpy as np
from datamodel import Order, OrderDepth, TradingState

"""
r2_v12 — Best-of-breed combination

ACO: from r2_v6_aco (microprice + crash mode + cubic skew)
  FIXES applied based on R2 data analysis:
    - L2_IMBALANCE_SCALE set to 0 (IC = -0.075, hurts PnL)
    - Reverted to absolute adverse_vol=15 (relative 20% triggers 97% of ticks)

IPR: from r2_v9 (228959 trend-following, no warmup gate)

Data evidence:
  - Microprice has IC=0.485 vs next-tick return (64.3% directional accuracy)
  - 33% of ticks have microprice deviating >0.5 from simple mid
  - v9-v11 use simple mid and miss this edge entirely
  - Crash mode + bootstrap anchor adds robustness on live exchange
"""

LIMIT = 80

# ── ACO Parameters (v6_aco base with data-driven fixes) ──────────────────────
ACO = "ASH_COATED_OSMIUM"
ACO_FV = 10000
ACO_TAKE_WIDTH = 1
ACO_CLEAR_WIDTH = 0
ACO_DISREGARD_EDGE = 1
ACO_JOIN_EDGE = 2
ACO_DEFAULT_EDGE = 4
ACO_ADVERSE_VOL = 15            # absolute filter (28% trigger rate — selective)

ACO_MAX_CONCESSION = 4.0        # cubic skew max
ACO_MID_WINDOW = 21

ACO_CRASH_FLOOR = 15
ACO_CRASH_K_MAD = 4.0
ACO_MAD_WARMUP = 50

ACO_BOOTSTRAP_SAMPLES = 20
ACO_CRASH_EXIT_RATIO = 0.7

ACO_ACCUM_SUPPRESS_POS = 60
ACO_CRASH_JOIN_EDGE_BONUS = 4
ACO_CRASH_DEFAULT_EDGE_BONUS = 8

# L2 imbalance DISABLED: IC = -0.075 on R2 data (wrong direction)
L2_IMBALANCE_SCALE = 0.0

# ── IPR Parameters (228959 trend-following from v9) ──────────────────────────
IPR = "INTARIAN_PEPPER_ROOT"
PEPPER_SPREAD_GRADIENT = 0.0010586880760
PEPPER_SPREAD_INTERCEPT = 0.8694130152902


# ── Helpers ──────────────────────────────────────────────────────────────────

def _half_up(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def _aco_skew(pos):
    return ACO_MAX_CONCESSION * (pos / LIMIT) ** 3


def _snap_anchor(x):
    return 2 * _half_up(x / 2)


def _mad(samples, median_val):
    return statistics.median([abs(s - median_val) for s in samples])


def _microprice(book) -> float:
    """
    Volume-weighted mid at the best bid/ask.
    IC = 0.485 vs next-tick return on R2 data (64.3% directional accuracy).
    """
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
        self.aco_bootstrap_samples = []
        self.aco_anchor = None
        self.aco_in_crash = False
        self.aco_mad_samples = []
        self.aco_mad_frozen = None

    def bid(self):
        return 0

    # ═══ ACO: Microprice + crash mode + cubic skew (v6_aco with fixes) ═══

    def _aco(self, state):
        book = state.order_depths[ACO]
        if not (book.buy_orders or book.sell_orders):
            return []

        pos = state.position.get(ACO, 0)
        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos
        bought = sold = 0
        orders = []

        has_both = bool(book.buy_orders) and bool(book.sell_orders)

        # ── FV estimation: microprice (IC=0.485) ────────────────────────
        if has_both:
            cur_mid = _microprice(book)

            if self.aco_anchor is None:
                self.aco_bootstrap_samples.append(cur_mid)
                if len(self.aco_bootstrap_samples) >= ACO_BOOTSTRAP_SAMPLES:
                    self.aco_anchor = _snap_anchor(
                        statistics.median(self.aco_bootstrap_samples)
                    )
            self.aco_mids.append(cur_mid)
            if len(self.aco_mids) > ACO_MID_WINDOW:
                self.aco_mids = self.aco_mids[-ACO_MID_WINDOW:]
        elif self.aco_mids:
            cur_mid = self.aco_mids[-1]
        else:
            cur_mid = ACO_FV

        anchor = self.aco_anchor if self.aco_anchor is not None else ACO_FV
        med_mid = statistics.median(self.aco_mids) if self.aco_mids else ACO_FV

        # ── MAD threshold calibration ────────────────────────────────────
        if self.aco_mad_frozen is None and self.aco_anchor is not None:
            if self.aco_mids:
                self.aco_mad_samples.append(self.aco_mids[-1])
            if len(self.aco_mad_samples) >= ACO_MAD_WARMUP:
                self.aco_mad_frozen = _mad(self.aco_mad_samples, self.aco_anchor)
                self.aco_mad_samples = []

        threshold_eff = (
            max(ACO_CRASH_FLOOR, ACO_CRASH_K_MAD * self.aco_mad_frozen)
            if self.aco_mad_frozen is not None
            else ACO_CRASH_FLOOR
        )

        # ── Crash mode detection ─────────────────────────────────────────
        dev = abs(cur_mid - anchor)
        if self.aco_in_crash:
            if dev < ACO_CRASH_EXIT_RATIO * threshold_eff:
                self.aco_in_crash = False
        else:
            if dev > threshold_eff:
                self.aco_in_crash = True
        crash_mode = self.aco_in_crash

        if crash_mode:
            if pos >= ACO_ACCUM_SUPPRESS_POS:
                buy_cap = 0
            elif pos <= -ACO_ACCUM_SUPPRESS_POS:
                sell_cap = 0

        if crash_mode:
            base_fv = med_mid
            active_default_edge = ACO_DEFAULT_EDGE + ACO_CRASH_DEFAULT_EDGE_BONUS
            active_join_edge = ACO_JOIN_EDGE + ACO_CRASH_JOIN_EDGE_BONUS
        else:
            base_fv = anchor
            active_default_edge = ACO_DEFAULT_EDGE
            active_join_edge = ACO_JOIN_EDGE

        fv_eff = base_fv - _aco_skew(pos)

        # ── 1. TAKE: aggressive fills at FV±1, absolute adverse filter ───
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

            # ── 2. CLEAR: flatten inventory at FV ────────────────────────
            pos_after = pos + bought - sold
            if pos_after > 0 and sell_cap > 0:
                fair_for_ask = _half_up(fv_eff + ACO_CLEAR_WIDTH)
                clearable = sum(
                    v for p, v in book.buy_orders.items() if p >= fair_for_ask
                )
                qty = min(pos_after, clearable, sell_cap)
                if qty > 0:
                    orders.append(Order(ACO, fair_for_ask, -qty))
                    sell_cap -= qty
                    sold += qty
            elif pos_after < 0 and buy_cap > 0:
                fair_for_bid = _half_up(fv_eff - ACO_CLEAR_WIDTH)
                clearable = sum(
                    -v for p, v in book.sell_orders.items() if p <= fair_for_bid
                )
                qty = min(-pos_after, clearable, buy_cap)
                if qty > 0:
                    orders.append(Order(ACO, fair_for_bid, qty))
                    buy_cap -= qty
                    bought += qty

        # ── 3. MAKE: passive quotes with penny/join/default ──────────────
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

    # ═══ IPR: 228959 trend-following (from v9, no warmup gate) ═══

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
        """Mid of the largest-volume bid and ask levels."""
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
            self.aco_mids = saved.get("a", [])
            self.aco_anchor = saved.get("aa", None)
            self.aco_bootstrap_samples = saved.get("abs", [])
            self.aco_in_crash = saved.get("aic", False)
            self.aco_mad_samples = saved.get("ams", [])
            self.aco_mad_frozen = saved.get("amf", None)
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

        # Persist both ACO and IPR state
        saved["a"] = self.aco_mids
        saved["aa"] = self.aco_anchor
        saved["abs"] = self.aco_bootstrap_samples
        saved["aic"] = self.aco_in_crash
        saved["ams"] = self.aco_mad_samples
        saved["amf"] = self.aco_mad_frozen

        return result, 0, json.dumps(saved, separators=(",", ":"))
