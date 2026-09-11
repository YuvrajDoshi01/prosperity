import json
from datamodel import Order, TradingState

# --- Regression & Signal Constants ---
REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4

TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0

OBI_FV_SHIFT = 0.5

# --- Mean-reversion carry signal ---
CARRY_TRIGGER = 4       # bid change threshold to activate signal
CARRY_DECAY = 0.7       # signal decay per quiet tick
CARRY_THRESHOLD = 0.5   # signal strength to activate directional posting
CARRY_WIDE_OFFSET = 3   # wide-side posting offset during strong signal

# --- Position management ---
POSITION_LIMIT = 80
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40   # tighter EM takes above this
TOMATO_AGGRESSION_THRESHOLD = 40    # tighter TOM takes above this
TERMINAL_TIMESTAMP = 900000
TERMINAL_POSITION_THRESHOLD = 28    # only flatten when |pos| exceeds this

# --- Liquidation (EMERALDS stuck-at-limit detection) ---
LIQUIDATION_WINDOW = 10


class Trader:
    def __init__(self):
        self.microprice_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.microprice_history = saved.get("mp", [])
            self.trade_flow_history = saved.get("tf", [])
            self.emerald_limit_history = saved.get("el", [])
            self.prev_best_bid = saved.get("bb")
            self.carry_signal = saved.get("cs", 0.0)

        orders = {}
        conversions = 0

        # ──────────────────────────────────────────────────────────────────────
        # EMERALDS: Fixed FV market making + liquidation tracking
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

                # Liquidation: track how long we've been stuck at limit
                self.emerald_limit_history.append(abs(pos) == POSITION_LIMIT)
                if len(self.emerald_limit_history) > LIQUIDATION_WINDOW:
                    self.emerald_limit_history = self.emerald_limit_history[-LIQUIDATION_WINDOW:]
                at_limit_soft = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW
                                 and sum(self.emerald_limit_history) >= 5
                                 and self.emerald_limit_history[-1])
                at_limit_hard = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW
                                 and all(self.emerald_limit_history))

                # Position-dependent take aggression
                max_buy_price = EMERALD_FV if pos <= EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV - 1
                min_sell_price = EMERALD_FV if pos >= -EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV + 1

                # Take: buy at/below FV
                for price, vol in asks:
                    if buy_cap > 0 and price <= max_buy_price:
                        qty = min(buy_cap, -vol)
                        em_orders.append(Order("EMERALDS", price, qty))
                        buy_cap -= qty

                # Liquidation bids (stuck at short limit)
                if buy_cap > 0 and at_limit_hard:
                    qty = buy_cap // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV, qty))
                    buy_cap -= qty
                if buy_cap > 0 and at_limit_soft:
                    qty = buy_cap // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV - 2, qty))
                    buy_cap -= qty

                # Post: bid at best+1 (inside MM spread)
                if buy_cap > 0:
                    bid_price = min(EMERALD_FV - 1, bids[0][0] + 1)
                    em_orders.append(Order("EMERALDS", bid_price, buy_cap))

                # Take: sell at/above FV
                for price, vol in bids:
                    if sell_cap > 0 and price >= min_sell_price:
                        qty = min(sell_cap, vol)
                        em_orders.append(Order("EMERALDS", price, -qty))
                        sell_cap -= qty

                # Liquidation asks (stuck at long limit)
                if sell_cap > 0 and at_limit_hard:
                    qty = sell_cap // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV, -qty))
                    sell_cap -= qty
                if sell_cap > 0 and at_limit_soft:
                    qty = sell_cap // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV + 2, -qty))
                    sell_cap -= qty

                # Post: ask at best-1 (inside MM spread)
                if sell_cap > 0:
                    ask_price = max(EMERALD_FV + 1, asks[0][0] - 1)
                    em_orders.append(Order("EMERALDS", ask_price, -sell_cap))

                orders["EMERALDS"] = em_orders

        # ──────────────────────────────────────────────────────────────────────
        # TOMATOES: L1 Microprice Regression FV + Carry Signal MM
        # ──────────────────────────────────────────────────────────────────────
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5

                # --- Fair value: L1 microprice regression ---
                # [FIX 1] Use standard L1 microprice (total book volume weighted),
                # NOT L2 microprice. Regression was calibrated on L1 input.
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
                    fv = REGRESSION_INTERCEPT + sum(
                        c * x for c, x in zip(REGRESSION_COEFS, hist))
                else:
                    fv = microprice

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

                # --- L1/L2 OBI shift (full book imbalance) ---
                # [FIX 6] Use full book imbalance, not L2-only
                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fv += obi * OBI_FV_SHIFT

                fv_int = round(fv)

                # --- Carry signal: mean-reversion after large moves ---
                # [FIX 4] Added carry/directional signal
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

                # --- Phase 1: Take at fair value ---
                # [FIX 2] Take AT fair value (was fv_int±1, now fv_int)
                # [FIX 3] Position-dependent aggression: tighter takes at |pos|>40
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

                # --- Terminal flatten: reduce inventory in last 10% of full day ---
                # [FIX 7] Only flatten when |pos| > 28 (was > 0)
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

                # --- Phase 2: Post with carry-informed directional quoting ---
                # [FIX 6] Removed L2 anchoring & imbalance widening blocks entirely
                if self.carry_signal > CARRY_THRESHOLD:
                    # Expect UP: tight bid, wide ask
                    if buy_cap > 0:
                        bid_price = min(fv_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_cap))
                    if sell_cap > 0:
                        ask_price = max(fv_int + CARRY_WIDE_OFFSET, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_cap))

                elif self.carry_signal < -CARRY_THRESHOLD:
                    # Expect DOWN: wide bid, tight ask
                    if sell_cap > 0:
                        ask_price = max(fv_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_cap))
                    if buy_cap > 0:
                        bid_price = min(fv_int - CARRY_WIDE_OFFSET, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_cap))

                else:
                    # Neutral: symmetric best±1
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
            {"mp": self.microprice_history,
             "tf": self.trade_flow_history,
             "el": self.emerald_limit_history,
             "bb": self.prev_best_bid,
             "cs": round(self.carry_signal, 3)},
            separators=(",", ":")
        )
