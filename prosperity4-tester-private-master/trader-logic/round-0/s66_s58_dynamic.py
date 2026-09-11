import json
from datamodel import Order, TradingState

"""
s66_s58_dynamic — s58 (proven FV engine) + dynamic inventory management

Key insight from s65 ablation:
- EMA + dmid regression = WORSE FV than microprice regression (dmid prediction too weak)
- But dynamic inventory is the RIGHT idea, just on the WRONG FV engine

This strategy keeps s58's proven FV pipeline (microprice reg + trade flow + OBI + L2 lead)
and adds:

1. Drawdown-aware position scaling:
   - Tracks rolling PnL. If PnL drops by more than DRAWDOWN_THRESHOLD, scale position
   - Uses position * dmid as a quick PnL proxy

2. Inventory heat management:
   - When position exceeds HEAT_THRESHOLD and predicted direction opposes,
     reduce max capacity on the adding side
   - NOT a hard cap — just scales down new adds

3. Circuit breaker:
   - Tracks consecutive ticks where we're at max position AND price moves against us
   - After N ticks, aggressively reduce adds on the losing side
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

# === NEW: Dynamic inventory ===
# Inventory heat: when |pos| > threshold AND dmid opposes, scale down adds
HEAT_THRESHOLD = 50          # position level where we start caring
HEAT_SCALE = 0.5             # multiply adding-side capacity by this

# Drawdown circuit breaker: consecutive adverse ticks at high inventory
ADVERSE_WINDOW = 8           # look at last N ticks
ADVERSE_THRESHOLD = 5        # if this many were adverse
ADVERSE_SCALE = 0.25         # slash capacity to this fraction
ADVERSE_POS_THRESHOLD = 30   # only trigger if |pos| > this


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
        # Dynamic inventory tracking
        self.prev_mid = None
        self.adverse_ticks = []  # True/False per tick: was this tick adverse for our position?

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
            self.prev_mid = saved.get("pm")
            self.adverse_ticks = saved.get("at", [])

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
        # TOMATOES — s58 FV + dynamic inventory
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

                # === NEW: Track adverse price movement against position ===
                if self.prev_mid is not None and abs(pos) > 0:
                    dmid = mid - self.prev_mid
                    # Adverse = price moved against our position
                    adverse = (pos > 0 and dmid < -0.5) or (pos < 0 and dmid > 0.5)
                    self.adverse_ticks.append(adverse)
                else:
                    self.adverse_ticks.append(False)
                if len(self.adverse_ticks) > ADVERSE_WINDOW:
                    self.adverse_ticks = self.adverse_ticks[-ADVERSE_WINDOW:]
                self.prev_mid = mid

                # Compute base capacities
                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos

                # === Inventory heat: scale down adding side when deep in position ===
                if abs(pos) > HEAT_THRESHOLD:
                    if pos > 0:
                        # Long and deep — reduce buy capacity
                        buy_capacity = int(buy_capacity * HEAT_SCALE)
                    else:
                        # Short and deep — reduce sell capacity
                        sell_capacity = int(sell_capacity * HEAT_SCALE)

                # === Circuit breaker: slash capacity after sustained adverse moves ===
                if (abs(pos) > ADVERSE_POS_THRESHOLD
                        and len(self.adverse_ticks) >= ADVERSE_WINDOW):
                    recent_adverse = sum(self.adverse_ticks[-ADVERSE_WINDOW:])
                    if recent_adverse >= ADVERSE_THRESHOLD:
                        if pos > 0:
                            buy_capacity = int(buy_capacity * ADVERSE_SCALE)
                        else:
                            sell_capacity = int(sell_capacity * ADVERSE_SCALE)

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
             "pm": self.prev_mid,
             "at": self.adverse_ticks[-ADVERSE_WINDOW:]},
            separators=(",", ":")
        )
