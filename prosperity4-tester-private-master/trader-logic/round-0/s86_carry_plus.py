import json
from datamodel import Order, TradingState

"""
s86_carry_plus — s74 base + proportional carry + adaptive decay + position-aware amp

Three layered carry improvements on top of s74's EMA amplification:
  1. Proportional carry (s82): bigger bid_delta → stronger carry magnitude
  2. Adaptive decay (s83): EMA-aligned carry decays slower, misaligned decays faster
  3. Position-aware amp (s85): amplify harder when position needs unwinding

All volume-independent. No spread crossing. Each mechanism is independently
motivated and targets a different aspect of carry signal quality.
"""

# --- s36 params (identical) ---
REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4
TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0
OBI_FV_SHIFT = 0.5
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

# === EMA carry amplification (from s74 v2) ===
EMA_ALPHA = 0.01
EMA_AMP_THRESHOLD = 4.0
EMA_AMP_FACTOR = 0.3
EMA_AMP_CAP = 2.0
EMA_INJECT_THRESHOLD = 6.0
EMA_INJECT_STRENGTH = 0.7
EMA_DAMPEN_FACTOR = 0.5

# === Proportional carry (from s82) ===
CARRY_SCALE = 5.0
CARRY_MAG_CAP = 2.0

# === Adaptive decay (from s83) ===
SLOW_DECAY = 0.85
FAST_DECAY = 0.5

# === Position-aware amp (from s85) ===
POS_AMP_THRESHOLD = 25
POS_AMP_BOOST = 2.0
POS_DAMPEN_EXTRA = 0.3


class Trader:
    def __init__(self):
        self.microprice_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0
        self.ema_mid = None

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
            self.ema_mid = saved.get("em")

        result = {}
        conversions = 0

        # EMERALDS — Identical to s36
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

        # TOMATOES — s74 + proportional carry + adaptive decay + position-aware amp
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5

                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos

                # Update EMA
                if self.ema_mid is None:
                    self.ema_mid = mid
                else:
                    self.ema_mid += EMA_ALPHA * (mid - self.ema_mid)

                # Fair value: microprice regression
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

                # Trade flow
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

                # L1/L2 OBI shift
                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fair_value += obi * OBI_FV_SHIFT

                fair_value_int = round(fair_value)

                # Compute EMA direction first (needed for adaptive decay + amplification)
                ema_dev = mid - self.ema_mid
                ema_direction = -1.0 if ema_dev > 0 else (1.0 if ema_dev < 0 else 0.0)

                # === PROPORTIONAL carry with ADAPTIVE decay ===
                if self.prev_best_bid is not None:
                    bid_delta = best_bid - self.prev_best_bid
                    abs_delta = abs(bid_delta)
                    if abs_delta >= CARRY_TRIGGER:
                        # Proportional magnitude (from s82)
                        magnitude = min(CARRY_MAG_CAP, abs_delta / CARRY_SCALE)
                        self.carry_signal = -magnitude if bid_delta > 0 else magnitude
                    elif abs_delta <= 1:
                        # Adaptive decay (from s83)
                        if self.carry_signal != 0 and ema_direction != 0:
                            same_dir = ((self.carry_signal > 0 and ema_direction > 0) or
                                        (self.carry_signal < 0 and ema_direction < 0))
                            decay = SLOW_DECAY if same_dir else FAST_DECAY
                        else:
                            decay = CARRY_DECAY
                        self.carry_signal *= decay
                self.prev_best_bid = best_bid

                # === Position-aware EMA amplification (from s85) ===
                carry_effective = self.carry_signal

                pos_aligns_ema = (abs(pos) > POS_AMP_THRESHOLD and
                                  ((ema_direction < 0 and pos > 0) or
                                   (ema_direction > 0 and pos < 0)))
                pos_contradicts_ema = (abs(pos) > POS_AMP_THRESHOLD and
                                       ((ema_direction > 0 and pos > 0) or
                                        (ema_direction < 0 and pos < 0)))

                if abs(ema_dev) > EMA_AMP_THRESHOLD:
                    excess = abs(ema_dev) - EMA_AMP_THRESHOLD
                    effective_factor = EMA_AMP_FACTOR * POS_AMP_BOOST if pos_aligns_ema else EMA_AMP_FACTOR
                    amp = excess * effective_factor

                    if (carry_effective > 0 and ema_direction > 0) or (carry_effective < 0 and ema_direction < 0):
                        carry_effective += ema_direction * amp
                        carry_effective = max(-EMA_AMP_CAP, min(EMA_AMP_CAP, carry_effective))
                    elif carry_effective != 0 and ema_direction != 0:
                        dampen = EMA_DAMPEN_FACTOR * POS_DAMPEN_EXTRA if pos_contradicts_ema else EMA_DAMPEN_FACTOR
                        carry_effective *= dampen
                    elif abs(carry_effective) < CARRY_THRESHOLD and abs(ema_dev) > EMA_INJECT_THRESHOLD:
                        inject = EMA_INJECT_STRENGTH * 1.5 if pos_aligns_ema else EMA_INJECT_STRENGTH
                        carry_effective = ema_direction * min(inject, EMA_AMP_CAP)

                # Phase 1: Take at fair value
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

                # Terminal flatten
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

                # Phase 2: Directional posting (magnitude-sensitive)
                carry_mag = abs(carry_effective)
                wide_scale = max(1.0, carry_mag)
                scaled_wide = int(round(CARRY_WIDE_OFFSET * wide_scale))

                if carry_effective > CARRY_THRESHOLD:
                    if buy_capacity > 0:
                        bid_price = min(fair_value_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))
                    if sell_capacity > 0:
                        if state.position.get("TOMATOES", 0) >= TOMATO_POST_SKEW_THRESHOLD:
                            ask_price = max(fair_value_int + 1, best_ask - 1)
                        else:
                            ask_price = max(fair_value_int + scaled_wide, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))

                elif carry_effective < -CARRY_THRESHOLD:
                    if sell_capacity > 0:
                        ask_price = max(fair_value_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))
                    if buy_capacity > 0:
                        if state.position.get("TOMATOES", 0) <= -TOMATO_POST_SKEW_THRESHOLD:
                            bid_price = min(fair_value_int - 1, best_bid + 1)
                        else:
                            bid_price = min(fair_value_int - scaled_wide, best_bid + 1)
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
             "cs": round(self.carry_signal, 4),
             "em": round(self.ema_mid, 2) if self.ema_mid is not None else None},
            separators=(",", ":")
        )
