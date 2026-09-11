import json
from datamodel import Order, TradingState

"""
s64_pure_mid_l2 — Pure mid as FV + L2 lead signal (NO regression)

The most volume-independent strategy possible:
  FV = mid = (bid1 + ask1) / 2

No regression, no microprice, no volume inputs to FV.
Only additions: trade flow (price-based), OBI shift (kept for now), L2 lead.

If this scores well, the regression adds nothing on the website.
If it scores badly, the regression's FV improvement is real.

Reference: s52_mid_fv (pure mid without L2) scored 2,496 on BT d0.
s36 (microprice regression without L2) scored 2,626.
So regression is worth +130 on BT d0.
"""

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
L2_FV_SHIFT = 1.0


class Trader:
    def __init__(self):
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
                bc = POSITION_LIMIT - pos
                sc = POSITION_LIMIT + pos
                bids = sorted(book.buy_orders.items(), reverse=True)
                asks = sorted(book.sell_orders.items())
                self.emerald_limit_history.append(abs(pos) == POSITION_LIMIT)
                if len(self.emerald_limit_history) > LIQUIDATION_WINDOW:
                    self.emerald_limit_history = self.emerald_limit_history[-LIQUIDATION_WINDOW:]
                als = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW and sum(self.emerald_limit_history) >= 5 and self.emerald_limit_history[-1])
                alh = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW and all(self.emerald_limit_history))
                mbp = EMERALD_FV if pos <= EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV - 1
                msp = EMERALD_FV if pos >= -EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV + 1
                for p, v in asks:
                    if bc > 0 and p <= mbp: q = min(bc, -v); em_orders.append(Order("EMERALDS", p, q)); bc -= q
                if bc > 0 and alh: q = bc // 2; em_orders.append(Order("EMERALDS", EMERALD_FV, q)); bc -= q
                if bc > 0 and als: q = bc // 2; em_orders.append(Order("EMERALDS", EMERALD_FV - 2, q)); bc -= q
                if bc > 0: em_orders.append(Order("EMERALDS", min(EMERALD_FV - 1, bids[0][0] + 1), bc))
                for p, v in bids:
                    if sc > 0 and p >= msp: q = min(sc, v); em_orders.append(Order("EMERALDS", p, -q)); sc -= q
                if sc > 0 and alh: q = sc // 2; em_orders.append(Order("EMERALDS", EMERALD_FV, -q)); sc -= q
                if sc > 0 and als: q = sc // 2; em_orders.append(Order("EMERALDS", EMERALD_FV + 2, -q)); sc -= q
                if sc > 0: em_orders.append(Order("EMERALDS", max(EMERALD_FV + 1, asks[0][0] - 1), -sc))
                result["EMERALDS"] = em_orders

        # TOMATOES — pure mid FV + L2 lead
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

                # L2 lead (lagged)
                l2_shift = self.l2_signal
                self.l2_signal = 0.0
                if self.prev_bid1 is not None and self.prev_bid2 is not None and bid2 is not None:
                    if best_bid == self.prev_bid1 and bid2 != self.prev_bid2:
                        self.l2_signal += -0.5
                if self.prev_ask1 is not None and self.prev_ask2 is not None and ask2 is not None:
                    if best_ask == self.prev_ask1 and ask2 < self.prev_ask2:
                        self.l2_signal += 0.5
                self.prev_bid1 = best_bid
                self.prev_ask1 = best_ask
                self.prev_bid2 = bid2
                self.prev_ask2 = ask2

                # FV = mid (pure price, zero volume dependency)
                fair_value = mid

                # Trade flow
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

                bc = POSITION_LIMIT - pos
                sc = POSITION_LIMIT + pos

                for p, v in sorted(book.sell_orders.items()):
                    if bc > 0 and p <= fair_value_int: q = min(bc, -v); tom_orders.append(Order("TOMATOES", p, q)); bc -= q
                for p, v in sorted(book.buy_orders.items(), reverse=True):
                    if sc > 0 and p >= fair_value_int: q = min(sc, v); tom_orders.append(Order("TOMATOES", p, -q)); sc -= q

                if state.timestamp > TERMINAL_TIMESTAMP and abs(pos) > TERMINAL_POSITION_THRESHOLD:
                    if pos > 0 and sc > 0:
                        for p, v in sorted(book.buy_orders.items(), reverse=True):
                            if sc > 0 and pos > 0: q = min(sc, v, pos); tom_orders.append(Order("TOMATOES", p, -q)); sc -= q; pos -= q
                    elif pos < 0 and bc > 0:
                        for p, v in sorted(book.sell_orders.items()):
                            if bc > 0 and pos < 0: q = min(bc, -v, -pos); tom_orders.append(Order("TOMATOES", p, q)); bc -= q; pos += q

                if self.carry_signal > CARRY_THRESHOLD:
                    if bc > 0: tom_orders.append(Order("TOMATOES", min(fair_value_int - 1, best_bid + 1, best_ask - 1), bc))
                    if sc > 0:
                        ap = max(fair_value_int + 1, best_ask - 1) if pos >= TOMATO_POST_SKEW_THRESHOLD else max(fair_value_int + CARRY_WIDE_OFFSET, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", max(ap, best_bid + 1), -sc))
                elif self.carry_signal < -CARRY_THRESHOLD:
                    if sc > 0: tom_orders.append(Order("TOMATOES", max(fair_value_int + 1, best_ask - 1, best_bid + 1), -sc))
                    if bc > 0:
                        bp = min(fair_value_int - 1, best_bid + 1) if pos <= -TOMATO_POST_SKEW_THRESHOLD else min(fair_value_int - CARRY_WIDE_OFFSET, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", min(bp, best_ask - 1), bc))
                else:
                    if bc > 0: tom_orders.append(Order("TOMATOES", min(fair_value_int - 1, best_bid + 1, best_ask - 1), bc))
                    if sc > 0: tom_orders.append(Order("TOMATOES", max(fair_value_int + 1, best_ask - 1, best_bid + 1), -sc))

                result["TOMATOES"] = tom_orders

        return result, conversions, json.dumps(
            {"tf": self.trade_flow_history, "el": self.emerald_limit_history,
             "bb": self.prev_best_bid, "cs": round(self.carry_signal, 3),
             "pb1": self.prev_bid1, "pa1": self.prev_ask1,
             "pb2": self.prev_bid2, "pa2": self.prev_ask2,
             "l2s": round(self.l2_signal, 2)},
            separators=(",", ":")
        )
