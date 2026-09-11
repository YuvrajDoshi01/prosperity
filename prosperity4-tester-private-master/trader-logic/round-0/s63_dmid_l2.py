import json
from datamodel import Order, TradingState

"""
s63_dmid_l2 — dmid AR(4) prediction + L2 lead signal

Instead of predicting mid LEVEL (which requires intercept calibration),
predict the CHANGE in mid. FV = mid + predicted_dmid.

Cross-validated dmid AR(4) (trained on d-2 + d-1):
  intercept = -0.004619 (≈ 0, no level dependence!)
  coefs = [-0.551536, -0.309438, -0.160757, -0.068804]
  All negative = pure mean reversion, decaying weights

This is the most volume-independent approach:
  - Input: dmid = (bid1 + ask1)/2 changes (pure price)
  - No microprice, no volumes
  - Near-zero intercept (no level to miscalibrate)
  - Coefficients directly encode mean-reversion strength
"""

# --- dmid AR(4) regression (cross-validated on d-2 + d-1) ---
DMID_COEFS = [-0.551536, -0.309438, -0.160757, -0.068804]
DMID_INTERCEPT = -0.004619
DMID_LAGS = 4

# --- s36 parameters ---
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

# L2 lead signal
L2_FV_SHIFT = 1.0


class Trader:
    def __init__(self):
        self.dmid_history = []
        self.prev_mid = None
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
            self.dmid_history = saved.get("dh", [])
            self.prev_mid = saved.get("pm")
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

        # EMERALDS — identical to s36
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
                at_limit_soft = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW
                                 and sum(self.emerald_limit_history) >= 5
                                 and self.emerald_limit_history[-1])
                at_limit_hard = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW
                                 and all(self.emerald_limit_history))
                mbp = EMERALD_FV if pos <= EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV - 1
                msp = EMERALD_FV if pos >= -EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV + 1
                for p, v in asks:
                    if buy_cap > 0 and p <= mbp:
                        q = min(buy_cap, -v); em_orders.append(Order("EMERALDS", p, q)); buy_cap -= q
                if buy_cap > 0 and at_limit_hard:
                    q = buy_cap // 2; em_orders.append(Order("EMERALDS", EMERALD_FV, q)); buy_cap -= q
                if buy_cap > 0 and at_limit_soft:
                    q = buy_cap // 2; em_orders.append(Order("EMERALDS", EMERALD_FV - 2, q)); buy_cap -= q
                if buy_cap > 0:
                    em_orders.append(Order("EMERALDS", min(EMERALD_FV - 1, bids[0][0] + 1), buy_cap))
                for p, v in bids:
                    if sell_cap > 0 and p >= msp:
                        q = min(sell_cap, v); em_orders.append(Order("EMERALDS", p, -q)); sell_cap -= q
                if sell_cap > 0 and at_limit_hard:
                    q = sell_cap // 2; em_orders.append(Order("EMERALDS", EMERALD_FV, -q)); sell_cap -= q
                if sell_cap > 0 and at_limit_soft:
                    q = sell_cap // 2; em_orders.append(Order("EMERALDS", EMERALD_FV + 2, -q)); sell_cap -= q
                if sell_cap > 0:
                    em_orders.append(Order("EMERALDS", max(EMERALD_FV + 1, asks[0][0] - 1), -sell_cap))
                result["EMERALDS"] = em_orders

        # TOMATOES — dmid prediction + L2 lead
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
                    if best_bid == self.prev_bid1 and bid2 != self.prev_bid2:
                        self.l2_signal += -0.5
                if self.prev_ask1 is not None and self.prev_ask2 is not None and ask2 is not None:
                    if best_ask == self.prev_ask1 and ask2 != self.prev_ask2:
                        if ask2 < self.prev_ask2:
                            self.l2_signal += 0.5
                self.prev_bid1 = best_bid
                self.prev_ask1 = best_ask
                self.prev_bid2 = bid2
                self.prev_ask2 = ask2

                # --- FV: mid + predicted dmid ---
                dmid = mid - self.prev_mid if self.prev_mid is not None else 0.0
                self.prev_mid = mid

                hist = self.dmid_history
                if len(hist) >= DMID_LAGS:
                    hist = hist[1:]
                hist.append(dmid)
                self.dmid_history = hist

                if len(hist) == DMID_LAGS:
                    predicted_dmid = DMID_INTERCEPT + sum(
                        c * x for c, x in zip(DMID_COEFS, hist))
                    fair_value = mid + predicted_dmid
                else:
                    fair_value = mid

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

                # OBI shift
                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())
                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fair_value += obi * OBI_FV_SHIFT

                # L2 lead
                if abs(l2_shift) > 0.1:
                    fair_value += (1.0 if l2_shift > 0 else -1.0) * L2_FV_SHIFT

                fair_value_int = round(fair_value)

                # Carry
                if self.prev_best_bid is not None:
                    bd = best_bid - self.prev_best_bid
                    if bd >= CARRY_TRIGGER: self.carry_signal = -1.0
                    elif bd <= -CARRY_TRIGGER: self.carry_signal = 1.0
                    elif abs(bd) <= 1: self.carry_signal *= CARRY_DECAY
                self.prev_best_bid = best_bid

                buy_cap = POSITION_LIMIT - pos
                sell_cap = POSITION_LIMIT + pos

                # Takes
                for p, v in sorted(book.sell_orders.items()):
                    if buy_cap > 0 and p <= fair_value_int:
                        q = min(buy_cap, -v); tom_orders.append(Order("TOMATOES", p, q)); buy_cap -= q
                for p, v in sorted(book.buy_orders.items(), reverse=True):
                    if sell_cap > 0 and p >= fair_value_int:
                        q = min(sell_cap, v); tom_orders.append(Order("TOMATOES", p, -q)); sell_cap -= q

                # Terminal flatten
                if state.timestamp > TERMINAL_TIMESTAMP and abs(pos) > TERMINAL_POSITION_THRESHOLD:
                    if pos > 0 and sell_cap > 0:
                        for p, v in sorted(book.buy_orders.items(), reverse=True):
                            if sell_cap > 0 and pos > 0:
                                q = min(sell_cap, v, pos); tom_orders.append(Order("TOMATOES", p, -q)); sell_cap -= q; pos -= q
                    elif pos < 0 and buy_cap > 0:
                        for p, v in sorted(book.sell_orders.items()):
                            if buy_cap > 0 and pos < 0:
                                q = min(buy_cap, -v, -pos); tom_orders.append(Order("TOMATOES", p, q)); buy_cap -= q; pos += q

                # Posting
                if self.carry_signal > CARRY_THRESHOLD:
                    if buy_cap > 0:
                        bp = min(fair_value_int - 1, best_bid + 1, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bp, buy_cap))
                    if sell_cap > 0:
                        ap = max(fair_value_int + 1, best_ask - 1) if pos >= TOMATO_POST_SKEW_THRESHOLD else max(fair_value_int + CARRY_WIDE_OFFSET, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", max(ap, best_bid + 1), -sell_cap))
                elif self.carry_signal < -CARRY_THRESHOLD:
                    if sell_cap > 0:
                        ap = max(fair_value_int + 1, best_ask - 1, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ap, -sell_cap))
                    if buy_cap > 0:
                        bp = min(fair_value_int - 1, best_bid + 1) if pos <= -TOMATO_POST_SKEW_THRESHOLD else min(fair_value_int - CARRY_WIDE_OFFSET, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", min(bp, best_ask - 1), buy_cap))
                else:
                    if buy_cap > 0:
                        tom_orders.append(Order("TOMATOES", min(fair_value_int - 1, best_bid + 1, best_ask - 1), buy_cap))
                    if sell_cap > 0:
                        tom_orders.append(Order("TOMATOES", max(fair_value_int + 1, best_ask - 1, best_bid + 1), -sell_cap))

                result["TOMATOES"] = tom_orders

        return result, conversions, json.dumps(
            {"dh": self.dmid_history, "pm": self.prev_mid,
             "tf": self.trade_flow_history,
             "el": self.emerald_limit_history,
             "bb": self.prev_best_bid,
             "cs": round(self.carry_signal, 3),
             "pb1": self.prev_bid1, "pa1": self.prev_ask1,
             "pb2": self.prev_bid2, "pa2": self.prev_ask2,
             "l2s": round(self.l2_signal, 2)},
            separators=(",", ":")
        )
