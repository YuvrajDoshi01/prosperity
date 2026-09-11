import json
from datamodel import Order, TradingState

"""
s38_microstructure — Deep Microstructure Edge Exploitation v2

KEY LESSON FROM v1: FV shifts cause bad takes at integer boundaries. The
microstructure signals are predictive but NOT reliable enough to shift the
TAKE threshold. They should ONLY affect POSTING (where we place quotes).

ARCHITECTURE:
  - Takes: IDENTICAL to s36 (same FV, same thresholds)
  - Posts: Enhanced with microstructure signals for BETTER QUEUE POSITION
    when a taker bot randomly arrives

SIGNALS USED (posting only):
  1. L2 OBI (r=+0.62): Stronger than total OBI for FV posting center
  2. Narrow spread determinism: During narrow spreads, skew posting
     aggressively in the predicted direction
  3. Extreme volume asymmetry: When bv1/av1 > 2, skew posting direction
  4. Bigram sequences: 2-tick lookahead from quote update patterns

The take phase uses s36's EXACT FV calculation (microprice regression +
trade flow + total OBI 0.5 shift). Only posting uses the enhanced signals.
"""

# --- TOMATOES fair value regression (UNCHANGED — for takes) ---
REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4

# --- Trade flow signal (UNCHANGED) ---
TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0

# --- OBI FV shift (UNCHANGED for takes) ---
OBI_FV_SHIFT = 0.5

# --- Mean-reversion carry signal (UNCHANGED) ---
CARRY_TRIGGER = 4
CARRY_DECAY = 0.7
CARRY_THRESHOLD = 0.5
CARRY_WIDE_OFFSET = 3

# --- Position management (UNCHANGED) ---
POSITION_LIMIT = 80
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40
TOMATO_POST_SKEW_THRESHOLD = 40
TERMINAL_TIMESTAMP = 900000
TERMINAL_POSITION_THRESHOLD = 28

# --- Liquidation (UNCHANGED) ---
LIQUIDATION_WINDOW = 10

# ═══════════════════════════════════════════════════
# NEW: Microstructure posting signals
# ═══════════════════════════════════════════════════

# Spread value → expected direction (+1 = UP, -1 = DOWN)
# Stable across 3 days: odd→UP, even→DOWN, 5→always UP, 9→always DOWN
SPREAD_DIRECTION = {5: +1, 6: -1, 7: +1, 8: -1, 9: -1}

# L2 OBI posting enhancement (on top of s36's total OBI for takes)
L2_OBI_POST_SHIFT = 0.5   # additional posting FV nudge from L2 OBI

# Extreme volume asymmetry threshold
EXTREME_VOL_RATIO = 2.0

# Bigram signal map (strongest patterns, stable across 3 days)
BIGRAM_SIGNALS = {
    'bD': -1.0, 'aU': +1.0, 'UD': -1.0, 'DU': +1.0,
    'DA': +0.5, 'AD': -0.5,
}


class Trader:
    def __init__(self):
        self.microprice_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0
        # Microstructure state
        self.prev_bid1 = None
        self.prev_ask1 = None
        self.last_quote_code = '.'
        self.bigram_signal = 0.0

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
            self.prev_bid1 = saved.get("pb")
            self.prev_ask1 = saved.get("pa")
            self.last_quote_code = saved.get("qc", ".")
            self.bigram_signal = saved.get("bs", 0.0)

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
        # TOMATOES — s36 takes + microstructure-enhanced posting
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

                # ── TAKE FV: Identical to s36 ──
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
                    take_fv = REGRESSION_INTERCEPT + sum(
                        c * x for c, x in zip(REGRESSION_COEFS, hist))
                else:
                    take_fv = microprice

                # Trade flow (identical to s36)
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
                take_fv -= flow_signal * TRADE_FLOW_COEF

                # Total OBI shift (identical to s36)
                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                take_fv += obi * OBI_FV_SHIFT

                take_fv_int = round(take_fv)

                # ══════════════════════════════════════════════
                # POST FV: s36 FV + microstructure enhancements
                # ══════════════════════════════════════════════
                post_fv = take_fv  # start from same base

                # Enhancement 1: L2 OBI posting nudge
                sorted_bids = sorted(book.buy_orders.items(), reverse=True)
                sorted_asks = sorted(book.sell_orders.items())
                bv2 = sorted_bids[1][1] if len(sorted_bids) > 1 else 0
                av2 = -sorted_asks[1][1] if len(sorted_asks) > 1 else 0

                if bv2 + av2 > 0:
                    l2_obi = (bv2 - av2) / (bv2 + av2)
                    post_fv += l2_obi * L2_OBI_POST_SHIFT

                # Enhancement 2: Narrow spread direction
                narrow_signal = 0.0
                if spread <= 9:
                    spread_int = int(spread)
                    if spread_int in SPREAD_DIRECTION:
                        narrow_signal = SPREAD_DIRECTION[spread_int]
                        # During narrow spread: shift posting FV by 1 in predicted direction
                        post_fv += narrow_signal * 1.0

                # Enhancement 3: Extreme volume asymmetry
                bv1 = sorted_bids[0][1] if sorted_bids else 0
                av1 = -sorted_asks[0][1] if sorted_asks else 0
                if av1 > 0 and bv1 / av1 > EXTREME_VOL_RATIO:
                    post_fv += 0.5   # bid heavy → expect UP → shift FV up
                elif bv1 > 0 and av1 / bv1 > EXTREME_VOL_RATIO:
                    post_fv -= 0.5   # ask heavy → expect DOWN → shift FV down

                # Enhancement 4: Bigram tracking
                current_code = '.'
                if self.prev_bid1 is not None and self.prev_ask1 is not None:
                    db = best_bid - self.prev_bid1
                    da = best_ask - self.prev_ask1
                    if db > 0 and da > 0:
                        current_code = 'U'
                    elif db < 0 and da < 0:
                        current_code = 'D'
                    elif db > 0 and da == 0:
                        current_code = 'b'
                    elif db < 0 and da == 0:
                        current_code = 'B'
                    elif da > 0 and db == 0:
                        current_code = 'A'
                    elif da < 0 and db == 0:
                        current_code = 'a'
                    elif db > 0 and da < 0:
                        current_code = 'N'
                    elif db < 0 and da > 0:
                        current_code = 'W'

                    bigram = self.last_quote_code + current_code
                    if bigram in BIGRAM_SIGNALS:
                        self.bigram_signal = BIGRAM_SIGNALS[bigram]
                    else:
                        self.bigram_signal *= 0.5

                self.prev_bid1 = best_bid
                self.prev_ask1 = best_ask
                self.last_quote_code = current_code

                if abs(self.bigram_signal) > 0.3:
                    post_fv += self.bigram_signal * 0.5

                post_fv_int = round(post_fv)

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

                # ── Phase 1: Take at s36's FV (UNCHANGED) ──
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

                # ── Phase 2: Directional posting (carry + microstructure) ──
                # Combine carry with narrow spread signal
                combined_signal = self.carry_signal

                # Narrow spread override when active (7% of ticks, 72-100% accuracy)
                if abs(narrow_signal) > 0 and spread <= 9:
                    # Weight narrow signal heavily — it's the strongest signal we have
                    combined_signal = narrow_signal * 1.2

                if combined_signal > CARRY_THRESHOLD:
                    # Expect UP: tight bid at post_fv, wide ask
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

                elif combined_signal < -CARRY_THRESHOLD:
                    # Expect DOWN: wide bid, tight ask at post_fv
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
                    # Neutral: symmetric posting around post_fv
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
             "el": self.emerald_limit_history,
             "bb": self.prev_best_bid,
             "cs": round(self.carry_signal, 3),
             "pb": self.prev_bid1,
             "pa": self.prev_ask1,
             "qc": self.last_quote_code,
             "bs": round(self.bigram_signal, 3)},
            separators=(",", ":")
        )
