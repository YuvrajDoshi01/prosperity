import json
import math
import statistics
from datamodel import Order, OrderDepth, TradingState

"""
r2_v13 — ACO only: composite signal + spread-regime conditioning

Changes from v12 ACO:
  1. Composite FV: microprice blended with OU anchor via mean-reversion beta
     - microprice alone: IC = 0.468
     - composite (MP + MR): IC = 0.500, slowest decay (0.91x to 10-tick)
     - formula: fv = microprice - MR_BETA * (microprice - anchor)
  2. Spread-regime conditioning: tight spreads (≤14, 7% of ticks) amplify
     all signals by 60-80%. Use wider takes and tighter makes in that regime.
  3. L2 imbalance REMOVED (IC = -0.075, confirmed harmful)
  4. Absolute adverse_vol=15 (relative 20% triggers 97% of ticks)
"""

LIMIT = 80

ACO = "ASH_COATED_OSMIUM"
ACO_FV = 10000

# ── Take/Clear/Make widths (normal regime: spread ≥ 15) ──────────────────────
ACO_TAKE_WIDTH = 1
ACO_CLEAR_WIDTH = 0
ACO_DISREGARD_EDGE = 1
ACO_JOIN_EDGE = 2
ACO_DEFAULT_EDGE = 4
ACO_ADVERSE_VOL = 15

# ── Take/Clear/Make widths (tight regime: spread ≤ 14) ───────────────────────
# Signals are 60-80% stronger when spread is tight (bot repositioning).
# Wider takes capture more edge; tighter makes improve queue priority.
ACO_TIGHT_SPREAD_THRESHOLD = 14
ACO_TIGHT_TAKE_WIDTH = 2       # take at FV±2 (vs ±1 normal)
ACO_TIGHT_JOIN_EDGE = 3        # join within 3 of FV (vs 2 normal)
ACO_TIGHT_DEFAULT_EDGE = 3     # tighter default (vs 4 normal)

# ── Mean-reversion blend ─────────────────────────────────────────────────────
# Composite IC = 0.500: fv = microprice - MR_BETA * (microprice - anchor)
# Equivalent to: fv = (1 - MR_BETA) * microprice + MR_BETA * anchor
ACO_MR_BETA = 0.10

# ── Inventory management ─────────────────────────────────────────────────────
ACO_MAX_CONCESSION = 4.0        # cubic skew peak at ±LIMIT
ACO_MID_WINDOW = 21

# ── Crash mode ───────────────────────────────────────────────────────────────
ACO_CRASH_FLOOR = 15
ACO_CRASH_K_MAD = 4.0
ACO_MAD_WARMUP = 50
ACO_BOOTSTRAP_SAMPLES = 20
ACO_CRASH_EXIT_RATIO = 0.7
ACO_ACCUM_SUPPRESS_POS = 60
ACO_CRASH_JOIN_EDGE_BONUS = 4
ACO_CRASH_DEFAULT_EDGE_BONUS = 8


# ── Helpers ──────────────────────────────────────────────────────────────────

def _half_up(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def _cubic_skew(pos):
    """Cubic inventory skew: smooth, zero-crossing at pos=0."""
    return ACO_MAX_CONCESSION * (pos / LIMIT) ** 3


def _snap_anchor(x):
    """Snap to nearest even integer (reduces anchor flicker)."""
    return 2 * _half_up(x / 2)


def _mad(samples, center):
    return statistics.median(abs(s - center) for s in samples)


def _microprice(book: OrderDepth) -> float:
    """
    Volume-weighted mid at L1.
    IC = 0.468 vs next-tick return (64.3% directional, 30.7% coverage).
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
        self.mids = []
        self.bootstrap = []
        self.anchor = None
        self.in_crash = False
        self.mad_samples = []
        self.mad_frozen = None

    def bid(self):
        return 0

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

        # ── 0. Observe: microprice + anchor bootstrap ────────────────────
        if has_both:
            cur_mid = _microprice(book)

            # Bootstrap anchor from first N ticks
            if self.anchor is None:
                self.bootstrap.append(cur_mid)
                if len(self.bootstrap) >= ACO_BOOTSTRAP_SAMPLES:
                    self.anchor = _snap_anchor(statistics.median(self.bootstrap))

            self.mids.append(cur_mid)
            if len(self.mids) > ACO_MID_WINDOW:
                self.mids = self.mids[-ACO_MID_WINDOW:]

            spread = min(book.sell_orders) - max(book.buy_orders)
        else:
            cur_mid = self.mids[-1] if self.mids else ACO_FV
            spread = 16  # default to modal

        anchor = self.anchor if self.anchor is not None else ACO_FV
        med_mid = statistics.median(self.mids) if self.mids else ACO_FV

        # ── MAD calibration for crash threshold ──────────────────────────
        if self.mad_frozen is None and self.anchor is not None:
            if self.mids:
                self.mad_samples.append(self.mids[-1])
            if len(self.mad_samples) >= ACO_MAD_WARMUP:
                self.mad_frozen = _mad(self.mad_samples, self.anchor)
                self.mad_samples = []

        threshold = (
            max(ACO_CRASH_FLOOR, ACO_CRASH_K_MAD * self.mad_frozen)
            if self.mad_frozen is not None
            else ACO_CRASH_FLOOR
        )

        # ── Crash mode detection (hysteresis) ────────────────────────────
        dev = abs(cur_mid - anchor)
        if self.in_crash:
            if dev < ACO_CRASH_EXIT_RATIO * threshold:
                self.in_crash = False
        else:
            if dev > threshold:
                self.in_crash = True

        crash = self.in_crash

        # ── Spread regime detection ──────────────────────────────────────
        tight = spread <= ACO_TIGHT_SPREAD_THRESHOLD and not crash

        # Select regime-dependent parameters
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
        # fv = (1 - beta) * microprice + beta * anchor
        # IC = 0.500 (composite) vs 0.468 (microprice alone)
        if crash:
            base_fv = med_mid  # crash: trust recent median, not anchor
        else:
            base_fv = cur_mid - ACO_MR_BETA * (cur_mid - anchor)

        fv_eff = base_fv - _cubic_skew(pos)

        # ── Crash: suppress accumulation ─────────────────────────────────
        if crash:
            if pos >= ACO_ACCUM_SUPPRESS_POS:
                buy_cap = 0
            elif pos <= -ACO_ACCUM_SUPPRESS_POS:
                sell_cap = 0

        # ── 1. TAKE: aggressive fills at FV ± take_width ─────────────────
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

            # ── 2. CLEAR: flatten inventory at FV ────────────────────────
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

        # ── 3. MAKE: passive quotes (penny / join / default) ─────────────
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

    # ═══ Main ═══

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if isinstance(saved, dict):
            self.mids = saved.get("m", [])
            self.anchor = saved.get("a")
            self.bootstrap = saved.get("b", [])
            self.in_crash = saved.get("c", False)
            self.mad_samples = saved.get("ms", [])
            self.mad_frozen = saved.get("mf")
        else:
            saved = {}

        result = {}
        if ACO in state.order_depths:
            result[ACO] = self._aco(state)

        saved["m"] = self.mids
        saved["a"] = self.anchor
        saved["b"] = self.bootstrap
        saved["c"] = self.in_crash
        saved["ms"] = self.mad_samples
        saved["mf"] = self.mad_frozen

        return result, 0, json.dumps(saved, separators=(",", ":"))
