import json
from datamodel import Order, TradingState

"""
s62_mid_reg_l2 — Mid-based AR(4) regression + L2 lead signal

KEY DIFFERENCE from s58: FV computed from mid (pure price), NOT microprice.
This removes ALL volume dependency from the regression input.

Cross-validated AR(4) on mid (trained on d-2 + d-1):
  intercept = 3.7874
  coefs = [0.456765, 0.253373, 0.165972, 0.123131]
  OOS RMSE = 1.126 (same as IS, no overfit)

The microprice regression in s36 uses:
  microprice = bid1 + (bid_vol / (bid_vol + ask_vol)) * spread
which depends on VOLUMES that differ 98.5% between CSV and website.

The mid-based regression uses:
  mid = (bid1 + ask1) / 2
which is PURE PRICE — guaranteed identical on website.
"""

# --- Mid-based AR(4) regression (cross-validated on d-2 + d-1) ---
REGRESSION_COEFS = [0.456765, 0.253373, 0.165972, 0.123131]
REGRESSION_INTERCEPT = 3.7874
REGRESSION_LAGS = 4

# --- Same s36 parameters ---
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

# L2 lead signal (from s58)
L2_FV_SHIFT = 1.0


class Trader:
    def __init__(self):
        self.mid_history = []       # mid instead of microprice
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0
        self.prev_bid1 = None
        self.prev_ask1 = None
        self.prev_bid2 = None
        self.prev_ask2 = None
        self.l2_signal = 0.0

    def bid(self):
        return 15

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.mid_history = saved.get("mh", [])
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
        # TOMATOES — Mid-based regression + L2 lead
        # ═══════════════════════════════════════════════════
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5

                sorted_bids = sorted(book.buy_orders.keys(), reverse=True)
                sorted_asks = sorted(book.sell_orders.keys())
                bid2 = sorted_bids[1] if len(sorted_bids) > 1 else None
                ask2 = sorted_asks[1] if len(sorted_asks) > 1 else None

                # L2 lead signal (lagged)
                l2_shift = self.l2_signal
                self.l2_signal = 0.0
                if self.prev_bid1 is not None and self.prev_bid2 is not None and bid2 is not None:
                    dbid1 = best_bid - self.prev_bid1
                    dbid2 = bid2 - self.prev_bid2
                    if dbid1 == 0 and dbid2 >= 1:
                        self.l2_signal += -0.5
                    elif dbid1 == 0 and dbid2 <= -1:
                        self.l2_signal += -0.5
                if self.prev_ask1 is not None and self.prev_ask2 is not None and ask2 is not None:
                    dask1 = best_ask - self.prev_ask1
                    dask2 = ask2 - self.prev_ask2
                    if dask1 == 0 and dask2 <= -1:
                        self.l2_signal += +0.5
                self.prev_bid1 = best_bid
                self.prev_ask1 = best_ask
                self.prev_bid2 = bid2
                self.prev_ask2 = ask2

                # --- FV: mid-based AR(4) regression ---
                hist = self.mid_history
                if len(hist) >= REGRESSION_LAGS:
                    hist = hist[1:]
                hist.append(mid)
                self.mid_history = hist

                if len(hist) == REGRESSION_LAGS:
                    fair_value = REGRESSION_INTERCEPT + sum(
                        c * x for c, x in zip(REGRESSION_COEFS, hist))
                else:
                    fair_value = mid

                # --- Trade flow (same as s36) ---
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

                # --- OBI shift (same as s36) ---
                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())
                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fair_value += obi * OBI_FV_SHIFT

                # --- L2 lead shift ---
                if abs(l2_shift) > 0.1:
                    fair_value += (1.0 if l2_shift > 0 else -1.0) * L2_FV_SHIFT

                fair_value_int = round(fair_value)

                # Carry signal
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

                if self.carry_signal > CARRY_THRESHOLD:
                    if buy_capacity > 0:
                        bp = min(fair_value_int - 1, best_bid + 1, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bp, buy_capacity))
                    if sell_capacity > 0:
                        ap = max(fair_value_int + 1, best_ask - 1) if pos >= TOMATO_POST_SKEW_THRESHOLD else max(fair_value_int + CARRY_WIDE_OFFSET, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", max(ap, best_bid + 1), -sell_capacity))
                elif self.carry_signal < -CARRY_THRESHOLD:
                    if sell_capacity > 0:
                        ap = max(fair_value_int + 1, best_ask - 1, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ap, -sell_capacity))
                    if buy_capacity > 0:
                        bp = min(fair_value_int - 1, best_bid + 1) if pos <= -TOMATO_POST_SKEW_THRESHOLD else min(fair_value_int - CARRY_WIDE_OFFSET, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", min(bp, best_ask - 1), buy_capacity))
                else:
                    if buy_capacity > 0:
                        bp = min(fair_value_int - 1, best_bid + 1, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bp, buy_capacity))
                    if sell_capacity > 0:
                        ap = max(fair_value_int + 1, best_ask - 1, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ap, -sell_capacity))

                result["TOMATOES"] = tom_orders

        return result, conversions, json.dumps(
            {"mh": self.mid_history,
             "tf": self.trade_flow_history,
             "el": self.emerald_limit_history,
             "bb": self.prev_best_bid,
             "cs": round(self.carry_signal, 3),
             "pb1": self.prev_bid1, "pa1": self.prev_ask1,
             "pb2": self.prev_bid2, "pa2": self.prev_ask2,
             "l2s": round(self.l2_signal, 2)},
            separators=(",", ":")
        )
