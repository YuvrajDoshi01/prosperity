import json
from datamodel import Order, TradingState

"""
s58_l2_lead — s36 base + L2 price lead-lag signal

From log_analysis3.py Finding #3:
When L2 bid moves but L1 bid doesn't → 92% chance L1 bid follows DOWN next tick
When L2 ask moves but L1 ask doesn't → 85% chance L1 ask follows DOWN next tick

Key: This is PURELY PRICE-BASED (L2 price changes, not volumes).
Should be website-safe.

The mechanism: MM bot adjusts L2 before L1 as it restructures quotes.
L2 pulling away (widening gap) signals imminent L1 movement.

Implementation: Track prev L1/L2 prices. When L2 moved but L1 didn't,
apply a posting shift for the NEXT tick (lagged signal).
When dbid2 = +2 → next tick expect bid1 drops ~4.5 (strong DOWN)
When dask2 = -2 → next tick expect ask1 rises ~4.9 (strong UP)

We use this for POSTING DIRECTION (safer than take shifts).
"""

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

# s58: L2 lead-lag thresholds
# When |dbid2| >= threshold while dbid1 == 0, signal fires
L2_LEAD_THRESHOLD = 1       # minimum L2 price change to trigger
L2_STRONG_THRESHOLD = 2     # large L2 move → strong directional signal
L2_FV_SHIFT_WEAK = 1.0      # FV shift for weak L2 signal (dbid2/dask2 = ±1)
                             # Swept 0.0-1.4: d0 plateau +107 at 0.8-1.2, peak at 1.0
L2_FV_SHIFT_STRONG = 0.0    # Strong signal (|dbid2| >= 2): zero occurrences on d0


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
        self.l2_signal = 0.0  # +1 = expect UP, -1 = expect DOWN

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
        # TOMATOES — s36 + L2 lead-lag FV shift
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

                # --- s58: Compute L2 lead signal from previous tick ---
                # Read the lagged signal set last tick
                l2_shift = self.l2_signal  # this was set on prev tick

                # Now compute new signal for NEXT tick
                self.l2_signal = 0.0
                if (self.prev_bid1 is not None and self.prev_bid2 is not None
                        and bid2 is not None):
                    dbid1 = best_bid - self.prev_bid1
                    dbid2 = bid2 - self.prev_bid2
                    # L2 bid moved up but L1 didn't → expect L1 DOWN
                    if dbid1 == 0 and dbid2 >= L2_STRONG_THRESHOLD:
                        self.l2_signal = -1.0  # strong DOWN
                    elif dbid1 == 0 and dbid2 >= L2_LEAD_THRESHOLD:
                        self.l2_signal += -0.5  # weak DOWN
                    # L2 bid moved down but L1 didn't → L1 follows down (92%)
                    elif dbid1 == 0 and dbid2 <= -L2_STRONG_THRESHOLD:
                        self.l2_signal = -1.0  # strong DOWN (L2 pulling back)
                    elif dbid1 == 0 and dbid2 <= -L2_LEAD_THRESHOLD:
                        self.l2_signal += -0.5  # weak DOWN

                if (self.prev_ask1 is not None and self.prev_ask2 is not None
                        and ask2 is not None):
                    dask1 = best_ask - self.prev_ask1
                    dask2 = ask2 - self.prev_ask2
                    # L2 ask moved down but L1 didn't → expect L1 UP
                    if dask1 == 0 and dask2 <= -L2_STRONG_THRESHOLD:
                        self.l2_signal = +1.0  # strong UP
                    elif dask1 == 0 and dask2 <= -L2_LEAD_THRESHOLD:
                        self.l2_signal += +0.5
                    # L2 ask moved up but L1 didn't → weak (only 33-40%)
                    # Don't use this direction — too unreliable

                # Save current L1/L2 for next tick
                self.prev_bid1 = best_bid
                self.prev_ask1 = best_ask
                self.prev_bid2 = bid2
                self.prev_ask2 = ask2

                # --- Fair value: microprice regression (same as s36) ---
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

                # --- Trade flow adjustment (same as s36) ---
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

                # --- L1/L2 OBI shift (same as s36) ---
                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fair_value += obi * OBI_FV_SHIFT

                # --- s58: Apply L2 lead FV shift ---
                if abs(l2_shift) >= 1.0:
                    fair_value += l2_shift * L2_FV_SHIFT_STRONG
                elif abs(l2_shift) > 0:
                    fair_value += (1.0 if l2_shift > 0 else -1.0) * L2_FV_SHIFT_WEAK

                fair_value_int = round(fair_value)

                # --- Carry signal (same as s36) ---
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

                # --- Terminal flatten (same as s36) ---
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

                # --- Phase 2: Posting (same as s36) ---
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
             "l2s": round(self.l2_signal, 2)},
            separators=(",", ":")
        )
