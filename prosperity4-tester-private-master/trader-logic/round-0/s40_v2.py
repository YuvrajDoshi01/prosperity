import json
from datamodel import Order, TradingState

"""
s40_v2 — Like s40_3k but L2 OBI for BOTH takes and posts (preserves s38's +76)

s40_3k's day 0 was 2,642 (-60 vs s38's 2,702). The regression:
  - Separating take-FV (total OBI 0.5) from post-FV (L2 OBI 0.8) LOST 60 PnL
  - Because L2 OBI for takes is the primary edge source (+71 on day 0)
  - Restricting L2 OBI to posts killed the main signal

Fix: Use L2 OBI 0.8 for BOTH takes and posts (same as s38).
Add: conditional threshold + AR(2) for posts only.
Add: position skew (from s39)
Add: narrow spread posting (from s38)

Architecture: SINGLE FV for takes with L2 OBI.
              POST FV = take FV + AR(2) nudge (posting only).
"""

REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4

TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0

L2_OBI_SHIFT = 0.8

# Position skew (from s39)
SKEW_GAMMA = 0.01

# AR(2) for posting only
AR2_COEF_1 = -0.526
AR2_COEF_2 = -0.220
AR2_POST_WEIGHT = 0.3

CARRY_TRIGGER = 4
CARRY_DECAY = 0.7
CARRY_THRESHOLD = 0.5
CARRY_WIDE_OFFSET = 3

POSITION_LIMIT = 80
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40
TOMATO_POST_SKEW_THRESHOLD = 40

LIQUIDATION_WINDOW = 10

SPREAD_DIRECTION = {5: +1, 6: -1, 7: +1, 8: -1, 9: -1}


class Trader:
    def __init__(self):
        self.microprice_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0
        self.mid_history = []

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
            self.mid_history = saved.get("mh", [])

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
        # TOMATOES — s38 base + AR(2) posting + position skew
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

                sorted_bids = sorted(book.buy_orders.items(), reverse=True)
                sorted_asks = sorted(book.sell_orders.items())
                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())

                # ── Microprice regression (from s36) ──
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

                # ── Trade flow (from s36) ──
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

                # ── L2 OBI shift (from s38, for BOTH takes and posts) ──
                bv2 = sorted_bids[1][1] if len(sorted_bids) > 1 else 0
                av2 = -sorted_asks[1][1] if len(sorted_asks) > 1 else 0
                if bv2 + av2 > 0:
                    l2_obi = (bv2 - av2) / (bv2 + av2)
                    fair_value += l2_obi * L2_OBI_SHIFT
                else:
                    obi = ((total_bid_vol - total_ask_vol) /
                           (total_bid_vol + total_ask_vol)
                           if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                    fair_value += obi * 0.5

                # ── Position skew (from s39, small and safe) ──
                fair_value -= pos * SKEW_GAMMA

                take_fv_int = round(fair_value)

                # ── AR(2) correction for POSTING only ──
                self.mid_history.append(mid)
                if len(self.mid_history) > 3:
                    self.mid_history = self.mid_history[-3:]
                ar2_correction = 0.0
                if len(self.mid_history) >= 3:
                    dmid_1 = self.mid_history[-1] - self.mid_history[-2]
                    dmid_2 = self.mid_history[-2] - self.mid_history[-3]
                    ar2_correction = AR2_COEF_1 * dmid_1 + AR2_COEF_2 * dmid_2

                post_fv = fair_value + ar2_correction * AR2_POST_WEIGHT
                post_fv_int = round(post_fv)

                # ── Carry signal (from s36) ──
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

                # ── Phase 1: Take at L2 OBI-enhanced FV (same as s38) ──
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

                # ── Phase 2: Post at AR(2)-corrected FV ──
                posting_signal = self.carry_signal
                spread_int = int(spread)
                if spread_int in SPREAD_DIRECTION:
                    narrow_dir = SPREAD_DIRECTION[spread_int]
                    posting_signal += narrow_dir * 0.8

                if posting_signal > CARRY_THRESHOLD:
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

                elif posting_signal < -CARRY_THRESHOLD:
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
             "mh": self.mid_history},
            separators=(",", ":")
        )
