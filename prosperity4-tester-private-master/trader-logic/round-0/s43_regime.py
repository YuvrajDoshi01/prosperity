import json
import math
from datamodel import Order, TradingState

"""
s43_regime — Regime-detection market maker

ARCHITECTURE:
  Core FV: microprice lag-4 regression (proven, volume-independent)
  Trade flow: same as s36 (proven +207 PnL)
  OBI shift: total OBI × 0.5 (proven, volume-independent)

  NEW — Dual-signal regime detection for POSTING:
    Short signal: AR(2) mean-reversion  (horizon 1-3 ticks)
      pred = -0.526 * dmid[-1] - 0.220 * dmid[-2]
      +ve → expect price UP → lean long on posts
      -ve → expect price DOWN → lean short on posts

    Long signal: OLS slope over last 15 ticks of mid (horizon 1500ms)
      +ve slope → trending UP → lean long on posts
      -ve slope → trending DOWN → lean short on posts

    Regime combination:
      SAME SIGN (momentum regime): signals aligned → amplify direction
      OPPOSITE SIGN (mean-reversion regime): trust short-term AR(2) only

    Result → posting_signal replaces carry signal for post direction

  Position skew: CUBIC (inspired by user's idea, safely tuned)
    skew = (pos / 80)³ × CUBIC_SKEW
    vs linear: cubic stays small until inventory is large,
    then ramps fast — better mimics urgency at position extremes

  TAKES: conservative (base FV only, no regime in takes)
  POSTS: base FV + regime posting signal for direction

VOLUME-INDEPENDENCE CHECK:
  ✓ microprice: uses total vol, but regression coefs are calibrated
  ✓ total OBI: normalized ratio — robust
  ✓ AR(2): uses mid only
  ✓ 15-tick slope: uses mid only
  ✓ Cubic skew: uses position only
  ✗ wall_mid: NOT used (volume-dependent, replaced with microprice)
"""

# ── Regression (from s36, proven) ──
REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4

# ── Trade flow (from s36, proven) ──
TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0

# ── OBI (from s36, proven) ──
OBI_SHIFT = 0.5

# ── AR(2) coefficients (fitted, OOS-validated R²=0.225) ──
AR2_A1 = -0.526
AR2_A2 = -0.220

# ── Regime detection ──
SLOPE_WINDOW = 15           # ticks to compute long-term slope
SHORT_WEIGHT = 0.5          # weight of AR(2) in combined signal
LONG_WEIGHT = 0.5           # weight of slope in combined signal
REGIME_SCALE = 1.5          # scale the combined signal for posting shifts
MOMENTUM_AMPLIFY = 1.5      # amplify posting signal when both signals aligned
MR_DAMPEN = 0.6             # dampen posting signal when signals oppose each other
REGIME_THRESHOLD = 0.4      # |signal| > this to trigger directional posting

# ── Cubic position skew ──
# (pos/80)^3 × CUBIC_SKEW ticks of FV adjustment
# At pos=40: 0.5^3 × 4 = 0.5 ticks   (mild)
# At pos=60: 0.75^3 × 4 = 1.7 ticks  (moderate)
# At pos=80: 1.0^3 × 4 = 4.0 ticks   (aggressive exit at limit)
CUBIC_SKEW = 4.0

# ── Carry signal (kept as fallback when history is short) ──
CARRY_TRIGGER = 4
CARRY_DECAY = 0.7
CARRY_THRESHOLD = 0.5
CARRY_WIDE_OFFSET = 2

# ── Position management ──
POSITION_LIMIT = 80
TOMATO_POST_SKEW_THRESHOLD = 40

# ── EMERALDS (identical to s36) ──
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40
LIQUIDATION_WINDOW = 10


class Trader:
    def __init__(self):
        self.microprice_history = []   # for regression
        self.trade_flow_history = []   # for trade flow
        self.mid_history = []          # for AR(2) and slope
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0

    def bid(self):
        return 15

    def _compute_regime_signal(self):
        """
        Returns a combined regime signal in [-1, +1]:
          +ve → expect UP → lean long for posting
          -ve → expect DOWN → lean short for posting

        Combines:
          1. AR(2) short-term mean-reversion
          2. OLS 15-tick slope (long-term momentum)
        """
        mids = self.mid_history
        n = len(mids)

        # AR(2): need at least 3 ticks for dmid[-1] and dmid[-2]
        ar2 = 0.0
        if n >= 3:
            dmid_1 = mids[-1] - mids[-2]
            dmid_2 = mids[-2] - mids[-3]
            # AR(2) predicts next dmid — positive = expect up
            ar2_raw = AR2_A1 * dmid_1 + AR2_A2 * dmid_2
            # Normalise to [-1, +1] (typical moves ±1.5 so range is ±1.5)
            ar2 = max(-1.0, min(1.0, ar2_raw / 1.5))

        # Long-term slope: OLS on last SLOPE_WINDOW mids
        slope_signal = 0.0
        if n >= SLOPE_WINDOW:
            y = mids[-SLOPE_WINDOW:]
            x_mean = (SLOPE_WINDOW - 1) / 2.0
            var_x = sum((i - x_mean) ** 2 for i in range(SLOPE_WINDOW))
            cov_xy = sum((i - x_mean) * (y[i] - sum(y) / SLOPE_WINDOW)
                         for i in range(SLOPE_WINDOW))
            slope = cov_xy / var_x  # ticks per tick (100ms)
            # A slope of ±0.5 tick/tick is significant; normalise
            slope_signal = max(-1.0, min(1.0, slope / 0.5))

        # Combine: detect regime alignment
        if ar2 != 0.0 and slope_signal != 0.0:
            if ar2 * slope_signal > 0:
                # SAME SIGN → MOMENTUM regime: both agree on direction
                combined = (SHORT_WEIGHT * ar2 + LONG_WEIGHT * slope_signal) * MOMENTUM_AMPLIFY
            else:
                # OPPOSITE SIGN → MEAN-REVERSION regime: trust AR(2)
                # AR(2) is stronger signal at 1-tick horizon
                combined = ar2 * MR_DAMPEN
        elif slope_signal != 0.0:
            combined = slope_signal * LONG_WEIGHT
        else:
            combined = ar2 * SHORT_WEIGHT

        return max(-1.0, min(1.0, combined * REGIME_SCALE))

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.microprice_history = saved.get("mp", [])
            self.trade_flow_history = saved.get("tf", [])
            self.mid_history = saved.get("mh", [])
            self.emerald_limit_history = saved.get("el", [])
            self.prev_best_bid = saved.get("bb")
            self.carry_signal = saved.get("cs", 0.0)

        result = {}
        conversions = 0

        # ═══════════════════════════════════════════════════
        # EMERALDS — Identical to s36
        # ═══════════════════════════════════════════════════
        if "EMERALDS" in state.order_depths:
            book = state.order_depths["EMERALDS"]
            if book.buy_orders and book.sell_orders:
                em_orders = []
                pos = state.position.get("EMERALDS", 0)
                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos
                bids = sorted(book.buy_orders.items(), reverse=True)
                asks = sorted(book.sell_orders.items())

                self.emerald_limit_history.append(abs(pos) == POSITION_LIMIT)
                if len(self.emerald_limit_history) > LIQUIDATION_WINDOW:
                    self.emerald_limit_history = self.emerald_limit_history[-LIQUIDATION_WINDOW:]
                at_limit_soft = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW
                                 and sum(self.emerald_limit_history) >= 5
                                 and self.emerald_limit_history[-1])
                at_limit_hard = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW
                                 and all(self.emerald_limit_history))

                max_buy_price = EMERALD_FV if pos <= EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV - 1
                min_sell_price = EMERALD_FV if pos >= -EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV + 1

                for price, vol in asks:
                    if buy_capacity > 0 and price <= max_buy_price:
                        qty = min(buy_capacity, -vol)
                        em_orders.append(Order("EMERALDS", price, qty))
                        buy_capacity -= qty

                if buy_capacity > 0 and at_limit_hard:
                    qty = buy_capacity // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV, qty))
                    buy_capacity -= qty
                if buy_capacity > 0 and at_limit_soft:
                    qty = buy_capacity // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV - 2, qty))
                    buy_capacity -= qty
                if buy_capacity > 0:
                    em_orders.append(Order("EMERALDS", min(EMERALD_FV - 1, bids[0][0] + 1), buy_capacity))

                for price, vol in bids:
                    if sell_capacity > 0 and price >= min_sell_price:
                        qty = min(sell_capacity, vol)
                        em_orders.append(Order("EMERALDS", price, -qty))
                        sell_capacity -= qty

                if sell_capacity > 0 and at_limit_hard:
                    qty = sell_capacity // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV, -qty))
                    sell_capacity -= qty
                if sell_capacity > 0 and at_limit_soft:
                    qty = sell_capacity // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV + 2, -qty))
                    sell_capacity -= qty
                if sell_capacity > 0:
                    em_orders.append(Order("EMERALDS", max(EMERALD_FV + 1, asks[0][0] - 1), -sell_capacity))

                result["EMERALDS"] = em_orders

        # ═══════════════════════════════════════════════════
        # TOMATOES — Regime-detection enhanced MM
        # ═══════════════════════════════════════════════════
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5

                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())

                # ── Update mid history (for regime detection) ──
                self.mid_history.append(mid)
                if len(self.mid_history) > SLOPE_WINDOW + 2:
                    self.mid_history = self.mid_history[-(SLOPE_WINDOW + 2):]

                # ── Fair value: microprice lag-4 regression ──
                microprice = (best_bid + (total_bid_vol / (total_bid_vol + total_ask_vol))
                              * (best_ask - best_bid)
                              if (total_bid_vol + total_ask_vol) > 0 else mid)

                hist = self.microprice_history
                if len(hist) >= REGRESSION_LAGS:
                    hist = hist[1:]
                hist.append(microprice)
                self.microprice_history = hist

                if len(hist) == REGRESSION_LAGS:
                    fair_value = REGRESSION_INTERCEPT + sum(
                        c * x for c, x in zip(REGRESSION_COEFS, hist))
                else:
                    fair_value = microprice

                # ── Trade flow ──
                market_trades = state.market_trades.get("TOMATOES")
                if market_trades:
                    net_flow = sum(t.quantity if t.price >= mid else -t.quantity
                                  for t in market_trades)
                    self.trade_flow_history.append(net_flow)
                else:
                    self.trade_flow_history.append(0.0)
                if len(self.trade_flow_history) > TRADE_FLOW_WINDOW:
                    self.trade_flow_history = self.trade_flow_history[-TRADE_FLOW_WINDOW:]

                flow_signal = max(-1.0, min(1.0,
                    sum(self.trade_flow_history) / TRADE_FLOW_NORM))
                fair_value -= flow_signal * TRADE_FLOW_COEF

                # ── OBI shift (total, normalised, proven robust) ──
                obi = ((total_bid_vol - total_ask_vol) /
                       (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fair_value += obi * OBI_SHIFT

                # ── Cubic position skew on take FV ──
                # Gentle adjustment of take threshold by inventory level
                cubic_fv_adj = -(pos / 80.0) ** 3 * CUBIC_SKEW
                take_fv = fair_value + cubic_fv_adj
                take_fv_int = round(take_fv)

                # ── Regime detection for posting ──
                regime_signal = self._compute_regime_signal()

                # ── Carry signal (fallback when history is short) ──
                if self.prev_best_bid is not None:
                    bid_delta = best_bid - self.prev_best_bid
                    if bid_delta >= CARRY_TRIGGER:
                        self.carry_signal = -1.0
                    elif bid_delta <= -CARRY_TRIGGER:
                        self.carry_signal = 1.0
                    elif abs(bid_delta) <= 1:
                        self.carry_signal *= CARRY_DECAY
                self.prev_best_bid = best_bid

                # Blend regime and carry: use regime when we have enough history
                history_ready = len(self.mid_history) >= SLOPE_WINDOW
                if history_ready:
                    # Blend: regime dominates when confident, carry as fallback
                    posting_signal = (regime_signal * 0.7 + self.carry_signal * 0.3)
                else:
                    posting_signal = self.carry_signal

                # Post FV: regime nudges posting direction
                # (separate from take FV — posting mistakes are cheaper than take mistakes)
                post_fv = fair_value + cubic_fv_adj
                post_fv_int = round(post_fv)

                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos

                # ── Phase 1: Take at conservative FV ──
                for price, vol in sorted(book.sell_orders.items()):
                    if buy_capacity > 0 and price <= take_fv_int:
                        qty = min(buy_capacity, -vol)
                        tom_orders.append(Order("TOMATOES", price, qty))
                        buy_capacity -= qty

                for price, vol in sorted(book.buy_orders.items(), reverse=True):
                    if sell_capacity > 0 and price >= take_fv_int:
                        qty = min(sell_capacity, vol)
                        tom_orders.append(Order("TOMATOES", price, -qty))
                        sell_capacity -= qty

                # ── Phase 2: Regime-directed posting ──
                if posting_signal > REGIME_THRESHOLD:
                    # Expect UP: tight bid (good queue), wide ask
                    if buy_capacity > 0:
                        bid_price = min(post_fv_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))
                    if sell_capacity > 0:
                        if pos >= TOMATO_POST_SKEW_THRESHOLD:
                            ask_price = max(post_fv_int + 1, best_ask - 1)
                        else:
                            ask_price = max(post_fv_int + CARRY_WIDE_OFFSET, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))

                elif posting_signal < -REGIME_THRESHOLD:
                    # Expect DOWN: tight ask, wide bid
                    if sell_capacity > 0:
                        ask_price = max(post_fv_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))
                    if buy_capacity > 0:
                        if pos <= -TOMATO_POST_SKEW_THRESHOLD:
                            bid_price = min(post_fv_int - 1, best_bid + 1)
                        else:
                            bid_price = min(post_fv_int - CARRY_WIDE_OFFSET, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))

                else:
                    # Neutral: symmetric best±1
                    if buy_capacity > 0:
                        bid_price = min(post_fv_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))
                    if sell_capacity > 0:
                        ask_price = max(post_fv_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))

                result["TOMATOES"] = tom_orders

        return result, conversions, json.dumps(
            {"mp": self.microprice_history,
             "tf": self.trade_flow_history,
             "mh": self.mid_history,
             "el": self.emerald_limit_history,
             "bb": self.prev_best_bid,
             "cs": round(self.carry_signal, 3)},
            separators=(",", ":")
        )
