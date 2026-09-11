import json
from datamodel import Order, TradingState

"""
s87_narrow_gap — s74 base + narrow-spread gap_asymmetry exploitation

KEY INSIGHT: During narrow spread ticks (spread < 10, ~7% of ticks),
gap_asymmetry predicts dmid(t+1) with r = -0.95 across ALL 3 days.
This is the highest non-trivial predictive correlation in the data.

Mechanism:
  gap_asym = (bid1 - bid2) - (ask2 - ask1)
  When spread narrows, gap_asym tells us which direction the MM bot
  is about to move mid with near-certainty (95%).

  gap_asym < 0 → price going UP   → shift FV up, buy aggressively
  gap_asym > 0 → price going DOWN → shift FV down, sell aggressively

  During WIDE spread (~93% of ticks): no change from s74.
  During NARROW spread (~7% of ticks): aggressive FV shift from gap_asym.

This is fundamentally different from previous L2 attempts:
  - s36's OBI shift uses L2 on ALL ticks (volume-dependent, marginal)
  - s40_v2 used L2 OBI for takes on ALL ticks → CATASTROPHIC (-352 vs s36)
  - s87 uses gap_asym ONLY during narrow spread — the signal is 0.95 here
  - Spread state (narrow vs wide) is PRICE-based, not volume-based → safe

Risk assessment:
  - gap_asym uses L2 PRICES (bid2, ask2), not volumes → more likely to transfer
  - Spread < 10 is a price condition → volume-independent
  - But L2 price gaps might differ between CSV and website (untested)
  - Conservative: shift FV by 1-2 ticks only, don't cross spread
"""

# --- TOMATOES fair value regression (identical to s74/s36) ---
REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4

# --- Trade flow signal (identical to s74/s36) ---
TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0

# --- L1/L2 OBI shift (identical to s74/s36) ---
OBI_FV_SHIFT = 0.5

# --- Mean-reversion carry signal (identical to s74/s36) ---
CARRY_TRIGGER = 4
CARRY_DECAY = 0.7
CARRY_THRESHOLD = 0.5
CARRY_WIDE_OFFSET = 3

# --- Position management (identical to s74/s36) ---
POSITION_LIMIT = 80
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40
TOMATO_POST_SKEW_THRESHOLD = 40
TERMINAL_TIMESTAMP = 900000
TERMINAL_POSITION_THRESHOLD = 28

# --- Liquidation (identical to s74/s36) ---
LIQUIDATION_WINDOW = 10

# === EMA carry amplification (identical to s74) ===
EMA_ALPHA = 0.01
EMA_AMP_THRESHOLD = 4.0
EMA_AMP_FACTOR = 0.3
EMA_AMP_CAP = 2.0
EMA_INJECT_THRESHOLD = 6.0
EMA_INJECT_STRENGTH = 0.7
EMA_DAMPEN_FACTOR = 0.5

# === NEW: Narrow-spread gap_asym exploitation ===
NARROW_SPREAD_THRESHOLD = 10    # spread < 10 = narrow (spread states 5,6,7,8,9)
GAP_ASYM_FV_SHIFT = 2.0        # Max FV shift from gap_asym during narrow spread
GAP_ASYM_TAKE_EXTRA = 1        # Extra ticks to take through during narrow (cheap spread)


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

        # ═══════════════════════════════════════════════════
        # EMERALDS — Identical to s74/s36
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
        # TOMATOES — s74 core + narrow-spread gap_asym
        # ═══════════════════════════════════════════════════
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5
                spread = best_ask - best_bid

                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos

                # --- Update EMA (identical to s74) ---
                if self.ema_mid is None:
                    self.ema_mid = mid
                else:
                    self.ema_mid += EMA_ALPHA * (mid - self.ema_mid)

                # --- Fair value: microprice regression (identical to s74/s36) ---
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

                # Trade flow adjustment
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

                # ============================================
                # NEW: Narrow-spread gap_asym FV shift
                # ============================================
                # gap_asym = (bid1 - bid2) - (ask2 - ask1)
                # Uses L2 PRICES (not volumes) — more likely to transfer
                # Only fires when spread < 10 (~7% of ticks)
                # r = -0.95 with dmid(t+1) during narrow spread
                narrow_spread_active = False
                gap_asym_shift = 0.0

                if spread < NARROW_SPREAD_THRESHOLD:
                    narrow_spread_active = True
                    # Get L2 prices
                    sorted_bids = sorted(book.buy_orders.keys(), reverse=True)
                    sorted_asks = sorted(book.sell_orders.keys())

                    if len(sorted_bids) >= 2 and len(sorted_asks) >= 2:
                        bid1, bid2 = sorted_bids[0], sorted_bids[1]
                        ask1, ask2 = sorted_asks[0], sorted_asks[1]
                        gap_asym = (bid1 - bid2) - (ask2 - ask1)

                        # gap_asym > 0 → bid gap tight, ask gap wide → price going DOWN
                        # gap_asym < 0 → bid gap wide, ask gap tight → price going UP
                        # Negative correlation: shift FV OPPOSITE to gap_asym sign
                        # Normalize: gap_asym typically in [-6, +6] range during narrow
                        # Shift by up to GAP_ASYM_FV_SHIFT ticks
                        normalized = max(-1.0, min(1.0, gap_asym / 6.0))
                        gap_asym_shift = -normalized * GAP_ASYM_FV_SHIFT
                        fair_value += gap_asym_shift

                fair_value_int = round(fair_value)

                # During narrow spread, extend take range by GAP_ASYM_TAKE_EXTRA
                # The spread cost is only 2.5-4.5 instead of 6.5-7, so we can afford
                # to take more aggressively in the predicted direction
                take_buy_price = fair_value_int
                take_sell_price = fair_value_int

                if narrow_spread_active and abs(gap_asym_shift) > 0.5:
                    if gap_asym_shift > 0:
                        # FV shifted UP → buy more aggressively
                        take_buy_price = fair_value_int + GAP_ASYM_TAKE_EXTRA
                    else:
                        # FV shifted DOWN → sell more aggressively
                        take_sell_price = fair_value_int - GAP_ASYM_TAKE_EXTRA

                # Carry signal (identical to s74/s36)
                if self.prev_best_bid is not None:
                    bid_delta = best_bid - self.prev_best_bid
                    if bid_delta >= CARRY_TRIGGER:
                        self.carry_signal = -1.0
                    elif bid_delta <= -CARRY_TRIGGER:
                        self.carry_signal = 1.0
                    elif abs(bid_delta) <= 1:
                        self.carry_signal *= CARRY_DECAY
                self.prev_best_bid = best_bid

                # --- EMA carry amplification v2 (identical to s74) ---
                carry_effective = self.carry_signal
                ema_dev = mid - self.ema_mid
                ema_direction = -1.0 if ema_dev > 0 else (1.0 if ema_dev < 0 else 0.0)

                if abs(ema_dev) > EMA_AMP_THRESHOLD:
                    excess = abs(ema_dev) - EMA_AMP_THRESHOLD
                    amp = excess * EMA_AMP_FACTOR

                    if (carry_effective > 0 and ema_direction > 0) or (carry_effective < 0 and ema_direction < 0):
                        carry_effective += ema_direction * amp
                        carry_effective = max(-EMA_AMP_CAP, min(EMA_AMP_CAP, carry_effective))
                    elif carry_effective != 0 and ema_direction != 0:
                        carry_effective *= EMA_DAMPEN_FACTOR
                    elif abs(carry_effective) < CARRY_THRESHOLD and abs(ema_dev) > EMA_INJECT_THRESHOLD:
                        carry_effective = ema_direction * EMA_INJECT_STRENGTH

                # Phase 1: Take at fair value (with narrow-spread extension)
                for price, vol in sorted(book.sell_orders.items()):
                    if buy_capacity > 0 and price <= take_buy_price:
                        qty = min(buy_capacity, -vol)
                        tom_orders.append(Order("TOMATOES", price, qty))
                        buy_capacity -= qty

                for price, vol in sorted(book.buy_orders.items(), reverse=True):
                    if sell_capacity > 0 and price >= take_sell_price:
                        qty = min(sell_capacity, vol)
                        tom_orders.append(Order("TOMATOES", price, -qty))
                        sell_capacity -= qty

                # Terminal flatten (identical to s74/s36)
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

                # Phase 2: Directional posting (magnitude-sensitive carry, identical to s74)
                carry_mag = abs(carry_effective)
                wide_scale = max(1.0, carry_mag)
                scaled_wide = int(round(CARRY_WIDE_OFFSET * wide_scale))

                if carry_effective > CARRY_THRESHOLD:
                    if buy_capacity > 0:
                        bid_price = min(fair_value_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))
                    if sell_capacity > 0:
                        if pos >= TOMATO_POST_SKEW_THRESHOLD:
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
                        if pos <= -TOMATO_POST_SKEW_THRESHOLD:
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
             "cs": round(self.carry_signal, 3),
             "em": round(self.ema_mid, 2) if self.ema_mid is not None else None},
            separators=(",", ":")
        )
