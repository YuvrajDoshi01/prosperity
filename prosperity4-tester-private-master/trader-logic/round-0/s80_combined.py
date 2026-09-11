import json
from datamodel import Order, TradingState

"""
s80_combined — s36 base + ALL 5 spread exploitation mechanisms

Combines:
  1. Asymmetric SIZE: post more on signal-favored side (UNFAVORED_RATIO=0.5)
  2. Multi-level: split orders across 2 price levels (FRONT_RATIO=0.6)
  3. Pull losing side: stop posting on increasing side at |pos|>60
  4. Spread skip: no posting during tight spreads (<=9)
  5. Time-decay: widen posting as day progresses + position grows

All mechanisms are volume-independent (safe for website).
EMERALDS identical to s36. Takes at FV always happen regardless.
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

# === Combined params ===
UNFAVORED_RATIO = 0.5         # #1: Asymmetric size
FRONT_RATIO = 0.6             # #2: Multi-level split
PULL_THRESHOLD = 60           # #3: Pull losing side
TIGHT_SPREAD_THRESHOLD = 9   # #4: Spread skip
RAMP_START = 500000           # #5: Time-decay start
TIME_MAX_WIDEN = 2            # #5: Max extra offset
POS_SCALE_THRESHOLD = 30      # #5: Only widen when |pos| > this


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
        # TOMATOES — s36 core + all 5 mechanisms
        # ═══════════════════════════════════════════════════
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                spread = best_ask - best_bid
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5

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

                market_trades = state.market_trades.get("TOMATOES")
                if market_trades:
                    net_flow = sum(t.quantity if t.price >= mid else -t.quantity for t in market_trades)
                    self.trade_flow_history.append(net_flow)
                else:
                    self.trade_flow_history.append(0.0)
                if len(self.trade_flow_history) > TRADE_FLOW_WINDOW:
                    self.trade_flow_history = self.trade_flow_history[-TRADE_FLOW_WINDOW:]

                flow_signal = max(-1.0, min(1.0, sum(self.trade_flow_history) / TRADE_FLOW_NORM))
                fair_value -= flow_signal * TRADE_FLOW_COEF

                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fair_value += obi * OBI_FV_SHIFT
                fair_value_int = round(fair_value)

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

                # Phase 1: Take at fair value (ALWAYS)
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

                # Terminal flatten (identical to s36)
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

                # === MECHANISM #4: Spread skip — no posting during tight spreads ===
                if spread <= TIGHT_SPREAD_THRESHOLD:
                    result["TOMATOES"] = tom_orders
                    return result, conversions, json.dumps(
                        {"mp": self.microprice_history, "tf": self.trade_flow_history,
                         "el": self.emerald_limit_history, "bb": self.prev_best_bid,
                         "cs": round(self.carry_signal, 3)},
                        separators=(",", ":"))

                # === MECHANISM #3: Pull losing side ===
                allow_buy_post = pos < PULL_THRESHOLD
                allow_sell_post = pos > -PULL_THRESHOLD

                # === MECHANISM #5: Time-decay widen ===
                time_widen = 0
                if state.timestamp > RAMP_START and abs(pos) > POS_SCALE_THRESHOLD:
                    progress = min(1.0, (state.timestamp - RAMP_START) / (TERMINAL_TIMESTAMP - RAMP_START))
                    pos_scale = min(1.0, (abs(pos) - POS_SCALE_THRESHOLD) / (POSITION_LIMIT - POS_SCALE_THRESHOLD))
                    time_widen = int(round(TIME_MAX_WIDEN * progress * pos_scale))

                # === MECHANISM #1: Asymmetric size ===
                # === MECHANISM #2: Multi-level posting ===
                def post_buy(capacity, price):
                    """Post buy with multi-level split"""
                    if capacity <= 0:
                        return
                    front = max(1, int(capacity * FRONT_RATIO))
                    back = capacity - front
                    tom_orders.append(Order("TOMATOES", price, front))
                    deeper = min(price, best_bid)
                    if back > 0 and deeper != price:
                        tom_orders.append(Order("TOMATOES", deeper, back))
                    elif back > 0:
                        tom_orders.append(Order("TOMATOES", price, back))

                def post_sell(capacity, price):
                    """Post sell with multi-level split"""
                    if capacity <= 0:
                        return
                    front = max(1, int(capacity * FRONT_RATIO))
                    back = capacity - front
                    tom_orders.append(Order("TOMATOES", price, -front))
                    deeper = max(price, best_ask)
                    if back > 0 and deeper != price:
                        tom_orders.append(Order("TOMATOES", deeper, -back))
                    elif back > 0:
                        tom_orders.append(Order("TOMATOES", price, -back))

                # Phase 2: Directional posting with ALL mechanisms
                if self.carry_signal > CARRY_THRESHOLD:
                    # Expect UP: full buy, reduced sell (#1), with pull (#3)
                    if allow_buy_post and buy_capacity > 0:
                        bid_price = min(fair_value_int - 1, best_bid + 1, best_ask - 1)
                        post_buy(buy_capacity, bid_price)
                    if allow_sell_post and sell_capacity > 0:
                        post_sell_qty = max(1, int(sell_capacity * UNFAVORED_RATIO))
                        if pos >= TOMATO_POST_SKEW_THRESHOLD:
                            ask_price = max(fair_value_int + 1, best_ask - 1)
                        else:
                            ask_price = max(fair_value_int + CARRY_WIDE_OFFSET + time_widen, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        post_sell(post_sell_qty, ask_price)

                elif self.carry_signal < -CARRY_THRESHOLD:
                    # Expect DOWN: full sell, reduced buy (#1), with pull (#3)
                    if allow_sell_post and sell_capacity > 0:
                        ask_price = max(fair_value_int + 1, best_ask - 1, best_bid + 1)
                        post_sell(sell_capacity, ask_price)
                    if allow_buy_post and buy_capacity > 0:
                        post_buy_qty = max(1, int(buy_capacity * UNFAVORED_RATIO))
                        if pos <= -TOMATO_POST_SKEW_THRESHOLD:
                            bid_price = min(fair_value_int - 1, best_bid + 1)
                        else:
                            bid_price = min(fair_value_int - CARRY_WIDE_OFFSET - time_widen, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        post_buy(post_buy_qty, bid_price)

                else:
                    # Neutral: symmetric with pull (#3) and time-decay on loaded side (#5)
                    if allow_buy_post and buy_capacity > 0:
                        bid_offset = time_widen if pos > POS_SCALE_THRESHOLD else 0
                        bid_price = min(fair_value_int - 1 - bid_offset, best_bid + 1, best_ask - 1)
                        post_buy(buy_capacity, bid_price)
                    if allow_sell_post and sell_capacity > 0:
                        ask_offset = time_widen if pos < -POS_SCALE_THRESHOLD else 0
                        ask_price = max(fair_value_int + 1 + ask_offset, best_ask - 1, best_bid + 1)
                        post_sell(sell_capacity, ask_price)

                result["TOMATOES"] = tom_orders

        return result, conversions, json.dumps(
            {"mp": self.microprice_history, "tf": self.trade_flow_history,
             "el": self.emerald_limit_history, "bb": self.prev_best_bid,
             "cs": round(self.carry_signal, 3)},
            separators=(",", ":"))
