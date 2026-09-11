import json
import math
import statistics
from datamodel import Order, TradingState

"""
r2_v6_aco_l2

ACO strategy upgraded from L1-only to use L2 order book signals.

L1-only (current baseline):
    cur_mid = (best_bid + best_ask) / 2     ← ignores all volume info
    adverse = vol_at_best >= 15              ← absolute threshold

L2 additions in this file:
  1. Microprice instead of simple mid
     microprice = (best_ask * bid_vol_at_best + best_bid * ask_vol_at_best)
                / (bid_vol_at_best + ask_vol_at_best)
     Pulls FV toward the side with less volume (the side price will cross next).
     When 30 units bid / 5 units ask at best → microprice is closer to ask → bullish.

  2. L2 depth imbalance overlay on FV
     bid_depth  = sum of all bid volumes across the whole book
     ask_depth  = sum of all ask volumes across the whole book
     imbalance  = (bid_depth - ask_depth) / (bid_depth + ask_depth)  ∈ [-1, 1]
     fv_l2      = fv_eff + imbalance * L2_IMBALANCE_SCALE
     Heavy bid side → FV shifts up → we quote ask higher, bid more aggressively.

  3. Relative adverse selection
     Current: skip level if its vol >= ACO_ADVERSE_VOL (absolute 15 units)
     New: skip level if vol >= ACO_ADVERSE_REL_FRAC * total_book_depth  (relative)
     More meaningful when book is thick vs thin.
     Falls back to absolute filter when book is very thin.

Knobs to tune:
    L2_IMBALANCE_SCALE   — how many ticks to shift FV per unit of imbalance (0 = off)
    ACO_ADVERSE_REL_FRAC — fraction of total book depth that triggers adverse skip
"""

LIMIT = 80
MAF_BID = 0

ACO = "ASH_COATED_OSMIUM"
ACO_FV = 10000
ACO_TAKE_WIDTH = 1
ACO_CLEAR_WIDTH = 0
ACO_DISREGARD_EDGE = 1
ACO_JOIN_EDGE = 2
ACO_DEFAULT_EDGE = 4
ACO_ADVERSE_VOL = 15          # absolute fallback (used when book is thin)

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

# ── L2 knobs ─────────────────────────────────────────────────────────────────
# How many ticks to shift FV per unit of imbalance (imbalance ∈ [-1, 1]).
# 0 = disabled (pure L1 behaviour); try 1.0 → 4.0
L2_IMBALANCE_SCALE = 2.0

# Skip a level for adverse selection if its volume is >= this fraction of
# total book depth.  0.0 = always skip (not useful); 1.0 = never skip.
# Typical good range: 0.10 → 0.30
ACO_ADVERSE_REL_FRAC = 0.20


def _half_up(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def _aco_skew(pos):
    return ACO_MAX_CONCESSION * (pos / LIMIT) ** 3


def _snap_anchor(x):
    return 2 * _half_up(x / 2)


def _mad(samples, median_val):
    return statistics.median([abs(s - median_val) for s in samples])


# ── L2 helpers ────────────────────────────────────────────────────────────────

def _microprice(book) -> float:
    """
    Volume-weighted mid at the best bid/ask.
    Pulls toward whichever side has LESS volume — the side price will cross next.
    Falls back to simple mid if volumes are zero.
    """
    best_bid = max(book.buy_orders)
    best_ask = min(book.sell_orders)
    bid_vol = book.buy_orders[best_bid]         # positive
    ask_vol = abs(book.sell_orders[best_ask])   # positive
    total = bid_vol + ask_vol
    if total == 0:
        return (best_bid + best_ask) * 0.5
    return (best_ask * bid_vol + best_bid * ask_vol) / total


def _l2_imbalance(book) -> float:
    """
    Signed depth imbalance across the whole visible book: ∈ [-1, 1].
    Positive  → more bids than asks → buy pressure → FV should drift up.
    Negative  → more asks than bids → sell pressure → FV should drift down.
    """
    bid_depth = sum(book.buy_orders.values())
    ask_depth = sum(abs(v) for v in book.sell_orders.values())
    total = bid_depth + ask_depth
    if total == 0:
        return 0.0
    return (bid_depth - ask_depth) / total


def _total_book_depth(book) -> int:
    return sum(book.buy_orders.values()) + sum(abs(v) for v in book.sell_orders.values())


def _is_adverse_relative(level_vol: int, total_depth: int) -> bool:
    """
    True if level_vol is an outsized fraction of the book (informed-trader proxy).
    Falls back to absolute filter when book is thin.
    """
    if total_depth > 0 and (level_vol / total_depth) >= ACO_ADVERSE_REL_FRAC:
        return True
    return level_vol >= ACO_ADVERSE_VOL


class Trader:
    def __init__(self):
        self.aco_mids = []
        self.aco_bootstrap_samples = []
        self.aco_anchor = None
        self.aco_in_crash = False
        self.aco_mad_samples = []
        self.aco_mad_frozen = None

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

        has_both = bool(book.buy_orders) and bool(book.sell_orders)

        if has_both:
            # ── L2: use microprice as cur_mid (better FV estimate) ────────────
            cur_mid = _microprice(book)

            if self.aco_anchor is None:
                self.aco_bootstrap_samples.append(cur_mid)
                if len(self.aco_bootstrap_samples) >= ACO_BOOTSTRAP_SAMPLES:
                    self.aco_anchor = _snap_anchor(statistics.median(self.aco_bootstrap_samples))
            self.aco_mids.append(cur_mid)
            if len(self.aco_mids) > ACO_MID_WINDOW:
                self.aco_mids = self.aco_mids[-ACO_MID_WINDOW:]
        elif self.aco_mids:
            cur_mid = self.aco_mids[-1]
        else:
            cur_mid = ACO_FV

        anchor = self.aco_anchor if self.aco_anchor is not None else ACO_FV
        med_mid = statistics.median(self.aco_mids) if self.aco_mids else ACO_FV

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

        # ── L2: depth imbalance shifts FV in direction of book pressure ───────
        imbalance = _l2_imbalance(book) if has_both else 0.0
        imbalance_adj = imbalance * L2_IMBALANCE_SCALE

        fv_eff = base_fv - _aco_skew(pos) + imbalance_adj

        # ── L2: relative adverse selection ────────────────────────────────────
        total_depth = _total_book_depth(book) if has_both else 0

        if not crash_mode:
            for price, vol in sorted(book.sell_orders.items()):
                if buy_cap <= 0 or price > fv_eff - ACO_TAKE_WIDTH:
                    break
                if _is_adverse_relative(abs(vol), total_depth):
                    continue
                qty = min(buy_cap, -vol)
                orders.append(Order(ACO, price, qty))
                buy_cap -= qty
                bought += qty

            for price, vol in sorted(book.buy_orders.items(), reverse=True):
                if sell_cap <= 0 or price < fv_eff + ACO_TAKE_WIDTH:
                    break
                if _is_adverse_relative(vol, total_depth):
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

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.aco_mids = saved.get("a", [])
            self.aco_anchor = saved.get("aa", None)
            self.aco_bootstrap_samples = saved.get("abs", [])
            self.aco_in_crash = saved.get("aic", False)
            self.aco_mad_samples = saved.get("ams", [])
            self.aco_mad_frozen = saved.get("amf", None)

        result = {}
        if ACO in state.order_depths:
            result[ACO] = self._aco(state)

        return result, 0, json.dumps(
            {
                "a": self.aco_mids,
                "aa": self.aco_anchor,
                "abs": self.aco_bootstrap_samples,
                "aic": self.aco_in_crash,
                "ams": self.aco_mad_samples,
                "amf": self.aco_mad_frozen,
            },
            separators=(",", ":"),
        )