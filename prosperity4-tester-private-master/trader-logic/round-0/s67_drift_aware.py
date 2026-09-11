import json
from datamodel import Order, TradingState

"""
s67_drift_aware — s58 base + drift-aware position management

The problem: price can drift 49 points over 10k ticks while still being
mean-reverting tick-to-tick (AC(1) = -0.44). AR(4) regression always predicts
reversion, so we accumulate inventory in the wrong direction during slow drifts.

Solution: TWO timescale FV
- SHORT-term FV: microprice regression (proven, captures tick-level reversion)
- LONG-term anchor: EMA of mid (tracks slow drift)
- When they disagree (regression says up, EMA says drift is down), REDUCE position

The drift detector isn't a circuit breaker — it's a continuous scaling signal:
- drift_signal = (mid - EMA) / normalization
- When drift_signal opposes our position, scale down capacity
- When aligned, keep full capacity

This handles the day -1 scenario: 49-point downtrend means mid << EMA (lagged),
so drift_signal = negative. If we're long, buy_capacity gets scaled down.
"""

# === Proven FV engine from s58 ===
REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4
TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0
OBI_FV_SHIFT = 0.5
L2_LEAD_THRESHOLD = 1
L2_STRONG_THRESHOLD = 2
L2_FV_SHIFT_WEAK = 1.0
L2_FV_SHIFT_STRONG = 0.0

# === Same as s58 ===
CARRY_TRIGGER = 4
CARRY_DECAY = 0.7
CARRY_THRESHOLD = 0.5
CARRY_WIDE_OFFSET = 3
POSITION_LIMIT = 80
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40
TOMATO_POST_SKEW_THRESHOLD = 40
TERMINAL_TIMESTAMP = 900000
TERMINAL_POSITION_THRESHOLD = 28
LIQUIDATION_WINDOW = 10

# === NEW: Drift-aware position management ===
# Slow EMA for drift detection
DRIFT_EMA_ALPHA = 0.01        # very slow — tracks 100-tick drift
DRIFT_NORM = 10.0             # normalize drift: 10-point deviation = full signal
DRIFT_MAX_SCALE = 0.3         # when drift fully opposes position, scale to this
# Only apply drift scaling when position is significant
DRIFT_POS_THRESHOLD = 20      # don't bother below this position
# Scale is: 1.0 when aligned, DRIFT_MAX_SCALE when fully opposed
# Linear interpolation between


class Trader:
    def __init__(self):
        self.microprice_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0
        # L2 lead tracking
        self.prev_bid1 = None
        self.prev_ask1 = None
        self.prev_bid2 = None
        self.prev_ask2 = None
        self.l2_signal = 0.0
        # Drift tracking
        self.drift_ema = None

    def bid(self):
        return 15

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.microprice_history = saved.get("mp", [])
            self.trade_flow_history = saved.get("tf", [])
            self.emerald_limit_history = saved.get("el", [])
            self.prev_best_bid = saved.get("bb")
            self.carry_signal = saved.get("cs", 0.0)
            self.prev_bid1 = saved.get("pb1")
            self.prev_ask1 = saved.get("pa1")
            self.prev_bid2 = saved.get("pb2")
            self.prev_ask2 = saved.get("pa2")
            self.l2_signal = saved.get("l2s", 0.0)
            self.drift_ema = saved.get("de")

        result = {}
        conversions = 0

        # ═══════════════════════════════════════════════════
        # EMERALDS — Identical to s58
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
                    bid_price = min(EMERALD_FV - 1, bids[0][0] + 1)
                    em_orders.append(Order("EMERALDS", bid_price, buy_capacity))

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
                    ask_price = max(EMERALD_FV + 1, asks[0][0] - 1)
                    em_orders.append(Order("EMERALDS", ask_price, -sell_capacity))

                result["EMERALDS"] = em_orders

        # ═══════════════════════════════════════════════════
        # TOMATOES — s58 FV + drift-aware inventory
        # ═══════════════════════════════════════════════════
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5

                # Get L2 prices
                sorted_bids = sorted(book.buy_orders.keys(), reverse=True)
                sorted_asks = sorted(book.sell_orders.keys())
                bid2 = sorted_bids[1] if len(sorted_bids) > 1 else None
                ask2 = sorted_asks[1] if len(sorted_asks) > 1 else None

                # --- L2 lead signal (from s58) ---
                l2_shift = self.l2_signal
                self.l2_signal = 0.0
                if (self.prev_bid1 is not None and self.prev_bid2 is not None
                        and bid2 is not None):
                    dbid1 = best_bid - self.prev_bid1
                    dbid2 = bid2 - self.prev_bid2
                    if dbid1 == 0 and dbid2 >= L2_STRONG_THRESHOLD:
                        self.l2_signal = -1.0
                    elif dbid1 == 0 and dbid2 >= L2_LEAD_THRESHOLD:
                        self.l2_signal += -0.5
                    elif dbid1 == 0 and dbid2 <= -L2_STRONG_THRESHOLD:
                        self.l2_signal = -1.0
                    elif dbid1 == 0 and dbid2 <= -L2_LEAD_THRESHOLD:
                        self.l2_signal += -0.5

                if (self.prev_ask1 is not None and self.prev_ask2 is not None
                        and ask2 is not None):
                    dask1 = best_ask - self.prev_ask1
                    dask2 = ask2 - self.prev_ask2
                    if dask1 == 0 and dask2 <= -L2_STRONG_THRESHOLD:
                        self.l2_signal = +1.0
                    elif dask1 == 0 and dask2 <= -L2_LEAD_THRESHOLD:
                        self.l2_signal += +0.5

                self.prev_bid1 = best_bid
                self.prev_ask1 = best_ask
                self.prev_bid2 = bid2
                self.prev_ask2 = ask2

                # --- Fair value: microprice regression (PROVEN, from s58) ---
                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())
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

                # --- Trade flow (same as s58) ---
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

                # --- OBI shift (same as s58) ---
                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fair_value += obi * OBI_FV_SHIFT

                # --- L2 lead FV shift (from s58) ---
                if abs(l2_shift) >= 1.0:
                    fair_value += l2_shift * L2_FV_SHIFT_STRONG
                elif abs(l2_shift) > 0:
                    fair_value += (1.0 if l2_shift > 0 else -1.0) * L2_FV_SHIFT_WEAK

                fair_value_int = round(fair_value)

                # --- Carry signal (same as s58) ---
                if self.prev_best_bid is not None:
                    bid_delta = best_bid - self.prev_best_bid
                    if bid_delta >= CARRY_TRIGGER:
                        self.carry_signal = -1.0
                    elif bid_delta <= -CARRY_TRIGGER:
                        self.carry_signal = 1.0
                    elif abs(bid_delta) <= 1:
                        self.carry_signal *= CARRY_DECAY
                self.prev_best_bid = best_bid

                # === NEW: Drift detection ===
                if self.drift_ema is None:
                    self.drift_ema = mid
                else:
                    self.drift_ema = DRIFT_EMA_ALPHA * mid + (1 - DRIFT_EMA_ALPHA) * self.drift_ema

                # drift_signal: positive = price above EMA (uptrend), negative = below (downtrend)
                drift_signal = (mid - self.drift_ema) / DRIFT_NORM
                drift_signal = max(-1.0, min(1.0, drift_signal))  # clamp to [-1, 1]

                # Compute capacity scaling based on drift vs position
                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos

                if abs(pos) > DRIFT_POS_THRESHOLD:
                    # When pos > 0 (long) and drift < 0 (price falling): scale down buying
                    # When pos < 0 (short) and drift > 0 (price rising): scale down selling
                    if pos > 0 and drift_signal < 0:
                        # How opposed? drift_signal = -1 is worst
                        oppose_strength = abs(drift_signal)  # 0 to 1
                        scale = 1.0 - oppose_strength * (1.0 - DRIFT_MAX_SCALE)
                        buy_capacity = int(buy_capacity * scale)
                    elif pos < 0 and drift_signal > 0:
                        oppose_strength = abs(drift_signal)
                        scale = 1.0 - oppose_strength * (1.0 - DRIFT_MAX_SCALE)
                        sell_capacity = int(sell_capacity * scale)

                buy_capacity = max(0, buy_capacity)
                sell_capacity = max(0, sell_capacity)

                # --- Phase 1: Takes at fair value ---
                for price, vol in sorted(book.sell_orders.items()):
                    if buy_capacity > 0 and price <= fair_value_int:
                        qty = min(buy_capacity, -vol)
                        tom_orders.append(Order("TOMATOES", price, qty))
                        buy_capacity -= qty

                for price, vol in sorted(book.buy_orders.items(), reverse=True):
                    if sell_capacity > 0 and price >= fair_value_int:
                        qty = min(sell_capacity, vol)
                        tom_orders.append(Order("TOMATOES", price, -qty))
                        sell_capacity -= qty

                # --- Terminal flatten (same as s58) ---
                if state.timestamp > TERMINAL_TIMESTAMP and abs(pos) > TERMINAL_POSITION_THRESHOLD:
                    if pos > 0 and sell_capacity > 0:
                        for price, vol in sorted(book.buy_orders.items(), reverse=True):
                            if sell_capacity > 0 and pos > 0:
                                qty = min(sell_capacity, vol, pos)
                                tom_orders.append(Order("TOMATOES", price, -qty))
                                sell_capacity -= qty
                                pos -= qty
                    elif pos < 0 and buy_capacity > 0:
                        for price, vol in sorted(book.sell_orders.items()):
                            if buy_capacity > 0 and pos < 0:
                                qty = min(buy_capacity, -vol, -pos)
                                tom_orders.append(Order("TOMATOES", price, qty))
                                buy_capacity -= qty
                                pos += qty

                # --- Phase 2: Posting (same as s58) ---
                if self.carry_signal > CARRY_THRESHOLD:
                    if buy_capacity > 0:
                        bid_price = min(fair_value_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))
                    if sell_capacity > 0:
                        if pos >= TOMATO_POST_SKEW_THRESHOLD:
                            ask_price = max(fair_value_int + 1, best_ask - 1)
                        else:
                            ask_price = max(fair_value_int + CARRY_WIDE_OFFSET, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))

                elif self.carry_signal < -CARRY_THRESHOLD:
                    if sell_capacity > 0:
                        ask_price = max(fair_value_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))
                    if buy_capacity > 0:
                        if pos <= -TOMATO_POST_SKEW_THRESHOLD:
                            bid_price = min(fair_value_int - 1, best_bid + 1)
                        else:
                            bid_price = min(fair_value_int - CARRY_WIDE_OFFSET, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))

                else:
                    if buy_capacity > 0:
                        bid_price = min(fair_value_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))
                    if sell_capacity > 0:
                        ask_price = max(fair_value_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))

                result["TOMATOES"] = tom_orders

        return result, conversions, json.dumps(
            {"mp": self.microprice_history,
             "tf": self.trade_flow_history,
             "el": self.emerald_limit_history,
             "bb": self.prev_best_bid,
             "cs": round(self.carry_signal, 3),
             "pb1": self.prev_bid1, "pa1": self.prev_ask1,
             "pb2": self.prev_bid2, "pa2": self.prev_ask2,
             "l2s": round(self.l2_signal, 2),
             "de": round(self.drift_ema, 2) if self.drift_ema else None},
            separators=(",", ":")
        )
