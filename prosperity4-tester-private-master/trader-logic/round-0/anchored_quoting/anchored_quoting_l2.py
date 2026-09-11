import json
from datamodel import Order, TradingState

"""
anchored_quoting_l2 — L2-only microprice variant

Uses L2 microprice (second book level prices weighted by L2 volumes) as
regression input instead of L1 microprice. Coefficients recalibrated on
days -2/-1 training data (pooled fit).

L2 microprice has stronger negative autocorrelation (-0.42 vs -0.36 for L1)
and ANTI-correlates with concurrent mid moves (r=-0.60), making it a natural
contrarian/mean-reversion input. OOS R² = 0.9656 vs L1's 0.9631.

Everything else identical to anchored_quoting.py (carry signal, trade flow,
OBI, position aggression, liquidation, terminal flatten).
"""

# --- L2 Regression (pooled fit on days -2/-1, OOS R²=0.9656) ---
L2_REGRESSION_COEFS = [0.107151, 0.158261, 0.268849, 0.465272]
L2_REGRESSION_INTERCEPT = 2.313210
REGRESSION_LAGS = 4

TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0

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
TOMATO_AGGRESSION_THRESHOLD = 40
TERMINAL_TIMESTAMP = 900000
TERMINAL_POSITION_THRESHOLD = 28

# --- Liquidation ---
LIQUIDATION_WINDOW = 10


class Trader:
    def __init__(self):
        self.l2mp_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.l2mp_history = saved.get("l2", [])
            self.trade_flow_history = saved.get("tf", [])
            self.emerald_limit_history = saved.get("el", [])
            self.prev_best_bid = saved.get("bb")
            self.carry_signal = saved.get("cs", 0.0)

        orders = {}
        conversions = 0

        # ──────────────────────────────────────────────────────────────────────
        # EMERALDS: Fixed FV market making + liquidation tracking
        # (identical to anchored_quoting.py)
        # ──────────────────────────────────────────────────────────────────────
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

                max_buy_price = EMERALD_FV if pos <= EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV - 1
                min_sell_price = EMERALD_FV if pos >= -EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV + 1

                for price, vol in asks:
                    if buy_cap > 0 and price <= max_buy_price:
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
                    bid_price = min(EMERALD_FV - 1, bids[0][0] + 1)
                    em_orders.append(Order("EMERALDS", bid_price, buy_cap))

                for price, vol in bids:
                    if sell_cap > 0 and price >= min_sell_price:
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
                    ask_price = max(EMERALD_FV + 1, asks[0][0] - 1)
                    em_orders.append(Order("EMERALDS", ask_price, -sell_cap))

                orders["EMERALDS"] = em_orders

        # ──────────────────────────────────────────────────────────────────────
        # TOMATOES: L2 Microprice Regression FV + Carry Signal MM
        # ──────────────────────────────────────────────────────────────────────
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5

                # --- Fair value: L2 microprice regression ---
                # Extract L2 (second level) prices and volumes
                buy_prices = sorted(book.buy_orders.keys(), reverse=True)
                sell_prices = sorted(book.sell_orders.keys())

                if len(buy_prices) >= 2 and len(sell_prices) >= 2:
                    l2_bid_p = buy_prices[1]
                    l2_bid_v = book.buy_orders[l2_bid_p]
                    l2_ask_p = sell_prices[1]
                    l2_ask_v = abs(book.sell_orders[l2_ask_p])
                    l2_total = l2_bid_v + l2_ask_v
                    if l2_total > 0:
                        l2_microprice = (l2_bid_p * l2_ask_v + l2_ask_p * l2_bid_v) / l2_total
                    else:
                        l2_microprice = mid
                else:
                    l2_microprice = mid

                hist = self.l2mp_history
                if len(hist) >= REGRESSION_LAGS:
                    hist = hist[1:]
                hist.append(l2_microprice)
                self.l2mp_history = hist

                if len(hist) == REGRESSION_LAGS:
                    fv = L2_REGRESSION_INTERCEPT + sum(
                        c * x for c, x in zip(L2_REGRESSION_COEFS, hist))
                else:
                    fv = l2_microprice

                # --- Trade flow adjustment ---
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
                fv -= flow_signal * TRADE_FLOW_COEF

                # --- OBI shift (full book imbalance) ---
                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())
                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fv += obi * OBI_FV_SHIFT

                fv_int = round(fv)

                # --- Carry signal ---
                if self.prev_best_bid is not None:
                    bid_delta = best_bid - self.prev_best_bid
                    if bid_delta >= CARRY_TRIGGER:
                        self.carry_signal = -1.0
                    elif bid_delta <= -CARRY_TRIGGER:
                        self.carry_signal = 1.0
                    elif abs(bid_delta) <= 1:
                        self.carry_signal *= CARRY_DECAY
                self.prev_best_bid = best_bid

                buy_cap = POSITION_LIMIT - pos
                sell_cap = POSITION_LIMIT + pos

                # --- Take with position aggression ---
                max_buy_price = fv_int if pos <= TOMATO_AGGRESSION_THRESHOLD else fv_int - 1
                min_sell_price = fv_int if pos >= -TOMATO_AGGRESSION_THRESHOLD else fv_int + 1

                for price, vol in sorted(book.sell_orders.items()):
                    if buy_cap > 0 and price <= max_buy_price:
                        qty = min(buy_cap, -vol)
                        tom_orders.append(Order("TOMATOES", price, qty))
                        buy_cap -= qty

                for price, vol in sorted(book.buy_orders.items(), reverse=True):
                    if sell_cap > 0 and price >= min_sell_price:
                        qty = min(sell_cap, vol)
                        tom_orders.append(Order("TOMATOES", price, -qty))
                        sell_cap -= qty

                # --- Terminal flatten ---
                if state.timestamp > TERMINAL_TIMESTAMP and abs(pos) > TERMINAL_POSITION_THRESHOLD:
                    if pos > 0 and sell_cap > 0:
                        for price, vol in sorted(book.buy_orders.items(), reverse=True):
                            if sell_cap > 0 and pos > 0:
                                qty = min(sell_cap, vol, pos)
                                tom_orders.append(Order("TOMATOES", price, -qty))
                                sell_cap -= qty
                                pos -= qty
                    elif pos < 0 and buy_cap > 0:
                        for price, vol in sorted(book.sell_orders.items()):
                            if buy_cap > 0 and pos < 0:
                                qty = min(buy_cap, -vol, -pos)
                                tom_orders.append(Order("TOMATOES", price, qty))
                                buy_cap -= qty
                                pos += qty

                # --- Directional posting ---
                if self.carry_signal > CARRY_THRESHOLD:
                    if buy_cap > 0:
                        bid_price = min(fv_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_cap))
                    if sell_cap > 0:
                        ask_price = max(fv_int + CARRY_WIDE_OFFSET, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_cap))

                elif self.carry_signal < -CARRY_THRESHOLD:
                    if sell_cap > 0:
                        ask_price = max(fv_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_cap))
                    if buy_cap > 0:
                        bid_price = min(fv_int - CARRY_WIDE_OFFSET, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_cap))

                else:
                    if buy_cap > 0:
                        bid_price = min(fv_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_cap))
                    if sell_cap > 0:
                        ask_price = max(fv_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_cap))

                orders["TOMATOES"] = tom_orders

        return orders, conversions, json.dumps(
            {"l2": self.l2mp_history,
             "tf": self.trade_flow_history,
             "el": self.emerald_limit_history,
             "bb": self.prev_best_bid,
             "cs": round(self.carry_signal, 3)},
            separators=(",", ":")
        )
