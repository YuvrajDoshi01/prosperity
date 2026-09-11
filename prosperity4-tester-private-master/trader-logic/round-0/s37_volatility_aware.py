import json
from datamodel import Order, TradingState

"""
s37_volatility_aware — s36 base + refined position management

Analysis conclusion: volatility clustering, narrow spread avoidance, and burst
reversal signals all tested IDENTICAL or WORSE than s36 on backtester.
Root cause: new signals only affect posting direction, but the taker bot is
exogenous and random. Changing quotes by ±1 doesn't create new fills.

THIS VERSION focuses on what CAN improve PnL:
1. Burst reversal CARRY BOOST: When carry + burst align, use carry_wide=4 instead of 3
   (s36 already detects carry; this makes it stronger when vol confirms)
2. Graduated position aggression for TOMATOES takes:
   - |pos| > 60: take at fv-2/fv+2 (very conservative, avoid more wrong-side)
   - |pos| > 40: take at fv-1/fv+1 (s36 behavior, but also activate here)
   - |pos| <= 40: take at fv (standard)
3. EMERALDS: More aggressive liquidation — start soft liq at 3 ticks (not 5)

Everything else = s36 unchanged.
"""

# --- TOMATOES fair value regression (website-proven) ---
REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4

# --- Trade flow signal ---
TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0

# --- L1/L2 OBI shift ---
OBI_FV_SHIFT = 0.5

# --- Mean-reversion carry signal ---
CARRY_TRIGGER = 4
CARRY_DECAY = 0.7
CARRY_THRESHOLD = 0.5
CARRY_WIDE_OFFSET = 3

# --- Position management ---
POSITION_LIMIT = 80
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40
TOMATO_POST_SKEW_THRESHOLD = 40
TERMINAL_TIMESTAMP = 900000
TERMINAL_POSITION_THRESHOLD = 28

# --- Liquidation (EMERALDS) ---
LIQUIDATION_WINDOW = 10
EMERALD_SOFT_LIQ_THRESHOLD = 3   # NEW: was 5 in s36 (start liquidating earlier)

# --- NEW: graduated TOMATOES take aggression ---
TOMATO_HEAVY_POS_THRESHOLD = 60   # extra conservative takes above this


class Trader:
    def __init__(self):
        self.microprice_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0

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

        result = {}
        conversions = 0

        # ═══════════════════════════════════════════════════
        # EMERALDS — s36 + earlier soft liquidation
        # ═══════════════════════════════════════════════════
        if "EMERALDS" in state.order_depths:
            book = state.order_depths["EMERALDS"]
            if book.buy_orders and book.sell_orders:
                em_orders = []
                pos = state.position.get("EMERALDS", 0)
                buy_cap = POSITION_LIMIT - pos
                sell_cap = POSITION_LIMIT + pos
                bids = sorted(book.buy_orders.items(), reverse=True)
                asks = sorted(book.sell_orders.items())

                self.emerald_limit_history.append(abs(pos) == POSITION_LIMIT)
                if len(self.emerald_limit_history) > LIQUIDATION_WINDOW:
                    self.emerald_limit_history = self.emerald_limit_history[-LIQUIDATION_WINDOW:]

                # NEW: softer threshold for soft liquidation
                at_limit_soft = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW
                                 and sum(self.emerald_limit_history) >= EMERALD_SOFT_LIQ_THRESHOLD
                                 and self.emerald_limit_history[-1])
                at_limit_hard = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW
                                 and all(self.emerald_limit_history))

                max_buy = EMERALD_FV if pos <= EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV - 1
                min_sell = EMERALD_FV if pos >= -EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV + 1

                for price, vol in asks:
                    if buy_cap > 0 and price <= max_buy:
                        qty = min(buy_cap, -vol)
                        em_orders.append(Order("EMERALDS", price, qty))
                        buy_cap -= qty

                if buy_cap > 0 and at_limit_hard:
                    qty = buy_cap // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV, qty))
                    buy_cap -= qty
                if buy_cap > 0 and at_limit_soft:
                    qty = buy_cap // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV - 2, qty))
                    buy_cap -= qty
                if buy_cap > 0:
                    em_orders.append(Order("EMERALDS", min(EMERALD_FV - 1, bids[0][0] + 1), buy_cap))

                for price, vol in bids:
                    if sell_cap > 0 and price >= min_sell:
                        qty = min(sell_cap, vol)
                        em_orders.append(Order("EMERALDS", price, -qty))
                        sell_cap -= qty

                if sell_cap > 0 and at_limit_hard:
                    qty = sell_cap // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV, -qty))
                    sell_cap -= qty
                if sell_cap > 0 and at_limit_soft:
                    qty = sell_cap // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV + 2, -qty))
                    sell_cap -= qty
                if sell_cap > 0:
                    em_orders.append(Order("EMERALDS", max(EMERALD_FV + 1, asks[0][0] - 1), -sell_cap))

                result["EMERALDS"] = em_orders

        # ═══════════════════════════════════════════════════
        # TOMATOES — s36 + graduated position aggression
        # ═══════════════════════════════════════════════════
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5

                # ── Fair value: microprice regression (identical to s36) ──
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

                # ── Trade flow adjustment (identical to s36) ──
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

                # ── L1/L2 OBI shift (identical to s36) ──
                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fair_value += obi * OBI_FV_SHIFT

                fair_value_int = round(fair_value)

                # ── Carry signal (identical to s36) ──
                if self.prev_best_bid is not None:
                    bid_delta = best_bid - self.prev_best_bid
                    if bid_delta >= CARRY_TRIGGER:
                        self.carry_signal = -1.0
                    elif bid_delta <= -CARRY_TRIGGER:
                        self.carry_signal = 1.0
                    elif abs(bid_delta) <= 1:
                        self.carry_signal *= CARRY_DECAY
                self.prev_best_bid = best_bid

                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos

                # ── Phase 1: Take at fair value with graduated aggression ──
                # NEW: 3-tier position-aware take threshold
                if pos > TOMATO_HEAVY_POS_THRESHOLD:
                    max_buy_price = fair_value_int - 2   # very conservative buying when heavy long
                elif pos > EMERALD_AGGRESSION_THRESHOLD:
                    max_buy_price = fair_value_int - 1   # s36 behavior
                else:
                    max_buy_price = fair_value_int        # standard

                if pos < -TOMATO_HEAVY_POS_THRESHOLD:
                    min_sell_price = fair_value_int + 2   # very conservative selling when heavy short
                elif pos < -EMERALD_AGGRESSION_THRESHOLD:
                    min_sell_price = fair_value_int + 1   # s36 behavior
                else:
                    min_sell_price = fair_value_int        # standard

                for price, vol in sorted(book.sell_orders.items()):
                    if buy_capacity > 0 and price <= max_buy_price:
                        qty = min(buy_capacity, -vol)
                        tom_orders.append(Order("TOMATOES", price, qty))
                        buy_capacity -= qty

                for price, vol in sorted(book.buy_orders.items(), reverse=True):
                    if sell_capacity > 0 and price >= min_sell_price:
                        qty = min(sell_capacity, vol)
                        tom_orders.append(Order("TOMATOES", price, -qty))
                        sell_capacity -= qty

                # ── Terminal flatten (identical to s36) ──
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

                # ── Phase 2: Directional posting (identical to s36) ──
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
             "cs": round(self.carry_signal, 3)},
            separators=(",", ":")
        )
