import json
import math
import statistics
from datamodel import Order, TradingState

"""
r2_v6 — r1_v18 EXACTLY with MAF_BID=0 for Round 2.

r1_v18 base rationale (four robustness fixes for the 272466 ACO leak):

Context: r1_v17_bootstrap_only scored 89,861 on Round 1 day 1. Post-mortem
(see POST_MORTEM_272466.md) showed ~1,743 PnL lost to crash_mode flicker:
bootstrap anchor snapped to 10,008 (banker-rounded from asymmetric tick-0
mid 10,007), so the crash window [9,993, 10,023] triggered on normal dips
to 9,990-9,992. 512 spurious crash ticks, take/clear disabled, per-tick
PnL -1.263 vs +1.228 normal.

v18 fixes:

  1. Rolling median for ACO avg_mid (was 5-tick simple mean, window=5).
     - New window=21, uses statistics.median.
     - Outlier spikes no longer shift the mid used for crash-mode repricing.

  2. Adaptive crash threshold via MAD (was hardcoded 15 forever).
     - threshold_eff = max(ACO_CRASH_FLOOR, K * MAD(aco_mids))
     - On 272466 day 1: MAD(mids) ~ 3 -> 6*MAD ~ 18, absorbing the 8-tick
       anchor bias that caused 512 flickers. Would recover ~1,743 ACO PnL.
     - On a real gradient crash, |cur_mid - median| grows faster than MAD
       widens (MAD uses the full window including stale low-vol samples),
       so crash_mode still triggers with ~1-2 tick delay.

  3. Bootstrap from median of first 20 symmetric mids (was first-tick snap).
     - Eliminates single-tick-asymmetry bias at open.
     - Cost: 20 ticks using ACO_FV=10000 fallback during warmup (~40 PnL).
     - On 272466: anchor would land at median(first 20 mids) ~ 10,007 or
       10,006, then snap to 10,006 or 10,008 - small remaining jitter, but
       combined with fix #2 the adaptive threshold absorbs it.

  4. Hysteresis on crash trigger (was 1-tick flicker oscillation).
     - Enter crash_mode when |dev| > threshold_eff.
     - Stay in crash_mode until |dev| < 0.7 * threshold_eff.
     - Prevents single-tick flickers from disabling take/clear for 1 tick
       and re-enabling it. 200 flicker-episodes in v17 -> expected ~10-20
       real episodes in v18 (only when crash is actually sustained).

IPR is unchanged. IPR uses trend detection (rolling slope + direction
history), not a crash threshold, so per-product threshold separation is
naturally achieved by ACO_CRASH_FLOOR being ACO-specific. If we ever add
a circuit breaker to IPR, IPR_CRASH_FLOOR would be its own constant.

Expected vs v17:
  - Real day 1 (272466 replay): ~+1,700 ACO PnL (91,600 total vs 89,861).
  - Synthetic baseline regimes: neutral to slight positive.
  - Synthetic ACO_CRASH: ~1-2 tick slower to trigger, ~200-400 PnL cost.
  - Synthetic ACO_FLASH / PERMANENT / CRASH_DEEP: unchanged (large deviations
    trigger immediately regardless of MAD).
"""

LIMIT = 80

# R2 Market Access Fee. 0 = do not bid (structural + community + empirical
# arguments all point to trap). See trader-logic/round-2/R2_SUBMISSION_SUMMARY.md.
MAF_BID = 0

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

ACO_MAX_CONCESSION = 4.0          # v12 sweep-optimal ((4,15) > (8,25) by +9,280 on 25-seed bench)
ACO_MID_WINDOW = 21               # Fix #1: odd, larger for outlier-robust median (was 5)

# Fix #2: per-day adaptive crash threshold via frozen MAD (was hardcoded 15).
# MAD(|mid - anchor|) is computed from the first ACO_MAD_WARMUP ticks, then
# FROZEN. Updating it live would let a real crash widen the threshold as
# mids drift far from anchor, creating the same self-disarm failure mode
# that killed v15/v16. Freezing after warmup keeps per-day calibration
# (each day's noise level is different) without the disarm risk.
ACO_CRASH_FLOOR = 15              # minimum threshold (matches v17's hardcoded)
ACO_CRASH_K_MAD = 4.0             # frozen_threshold = max(FLOOR, K * MAD_frozen)
ACO_MAD_WARMUP = 50               # collect this many mids, compute MAD once, freeze

# Fix #3: median-bootstrap (was first-tick snap)
ACO_BOOTSTRAP_SAMPLES = 20        # collect this many mids, then snap(median) as anchor

# Fix #4: hysteresis exit ratio (was no hysteresis)
ACO_CRASH_EXIT_RATIO = 0.7        # stay in crash until |dev| < EXIT_RATIO * threshold_eff

ACO_ACCUM_SUPPRESS_POS = 60       # crash_mode + |pos|>=this -> skip quote on accumulation side
ACO_CRASH_JOIN_EDGE_BONUS = 4
ACO_CRASH_DEFAULT_EDGE_BONUS = 8


def _half_up(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def _wall_mid(book, fallback):
    if not (book.buy_orders and book.sell_orders):
        return fallback
    deep_bid = max(book.buy_orders, key=lambda p: (book.buy_orders[p], p))
    deep_ask = max(book.sell_orders, key=lambda p: (abs(book.sell_orders[p]), -p))
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


def _aco_skew(pos):
    return ACO_MAX_CONCESSION * (pos / LIMIT) ** 3


def _snap_anchor(x):
    # Snap to nearest even tick so the anchor lands on the MM bot's grid.
    # Uses half-up (not banker's) to avoid the 10007->10008 drift we saw in v17.
    return 2 * _half_up(x / 2)


def _mad(samples, median_val):
    # Median absolute deviation; robust scale estimator.
    return statistics.median([abs(s - median_val) for s in samples])


class Trader:
    def __init__(self):
        self.ipr_mids = []
        self.ipr_directions = []
        self.ipr_spreads = []
        self.aco_mids = []
        self.aco_bootstrap_samples = []   # v18: median-bootstrap accumulator
        self.aco_anchor = None
        self.aco_in_crash = False          # v18: hysteresis state
        self.aco_mad_samples = []          # v18: first ACO_MAD_WARMUP mids for MAD freeze
        self.aco_mad_frozen = None         # v18: frozen MAD, computed once after warmup

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
            cur_mid = (max(book.buy_orders) + min(book.sell_orders)) * 0.5
            # Fix #3: median-bootstrap. Accumulate first ACO_BOOTSTRAP_SAMPLES mids,
            # then snap the median. Robust to single-tick book asymmetry at open.
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
            # Book broke one-sided: fall back to last known mid to keep the
            # crash detection math meaningful (not reset to anchor).
            cur_mid = self.aco_mids[-1]
        else:
            cur_mid = ACO_FV

        # Anchor: bootstrapped median if ready, else provisional ACO_FV.
        anchor = self.aco_anchor if self.aco_anchor is not None else ACO_FV

        # Fix #1: median (not mean) of rolling window. Used as base_fv during
        # crash_mode to reprice toward market reality.
        if self.aco_mids:
            med_mid = statistics.median(self.aco_mids)
        else:
            med_mid = ACO_FV

        # Fix #2: per-day adaptive threshold via FROZEN MAD from anchor.
        # Collect first ACO_MAD_WARMUP mids into aco_mad_samples, then
        # compute MAD once and freeze. This gives per-day calibration
        # (absorbs anchor bias + observed noise level) while preventing
        # the self-disarm failure mode that happens if MAD widens during
        # a crash as mids drift far from anchor.
        if self.aco_mad_frozen is None and self.aco_anchor is not None:
            # Accumulate any new valid mid into the MAD sample buffer.
            if self.aco_mids:
                self.aco_mad_samples.append(self.aco_mids[-1])
            if len(self.aco_mad_samples) >= ACO_MAD_WARMUP:
                mad = _mad(self.aco_mad_samples, self.aco_anchor)
                self.aco_mad_frozen = mad
                # Free the buffer; we'll use the scalar from now on.
                self.aco_mad_samples = []

        if self.aco_mad_frozen is not None:
            threshold_eff = max(ACO_CRASH_FLOOR, ACO_CRASH_K_MAD * self.aco_mad_frozen)
        else:
            threshold_eff = ACO_CRASH_FLOOR

        # Fix #4: hysteresis. Enter at threshold_eff, exit at EXIT_RATIO * threshold_eff.
        dev = abs(cur_mid - anchor)
        if self.aco_in_crash:
            if dev < ACO_CRASH_EXIT_RATIO * threshold_eff:
                self.aco_in_crash = False
        else:
            if dev > threshold_eff:
                self.aco_in_crash = True
        crash_mode = self.aco_in_crash

        # Asymmetric quoting when trapped in sustained crash + high inventory.
        if crash_mode:
            if pos >= ACO_ACCUM_SUPPRESS_POS:
                buy_cap = 0
            elif pos <= -ACO_ACCUM_SUPPRESS_POS:
                sell_cap = 0

        # During crash: anchor to market median + widen edges.
        # Normal: use the frozen bootstrap anchor.
        if crash_mode:
            base_fv = med_mid
            active_default_edge = ACO_DEFAULT_EDGE + ACO_CRASH_DEFAULT_EDGE_BONUS
            active_join_edge = ACO_JOIN_EDGE + ACO_CRASH_JOIN_EDGE_BONUS
        else:
            base_fv = anchor
            active_default_edge = ACO_DEFAULT_EDGE
            active_join_edge = ACO_JOIN_EDGE

        fv_eff = base_fv - _aco_skew(pos)

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
            self.aco_bootstrap_samples = saved.get("abs", [])
            self.aco_in_crash = saved.get("aic", False)
            self.aco_mad_samples = saved.get("ams", [])
            self.aco_mad_frozen = saved.get("amf", None)

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
                "abs": self.aco_bootstrap_samples,
                "aic": self.aco_in_crash,
                "ams": self.aco_mad_samples,
                "amf": self.aco_mad_frozen,
            },
            separators=(",", ":")
        )
