import json
from datamodel import Order, TradingState

"""
anchored_quoting_asymmetric — Asymmetric Move Classifier + L1 Regression

NOVEL IDEA: Not all mid-price changes are equally informative.
The MM bot's book reveals that asymmetric moves (only bid OR only ask moves)
carry 5x more predictive signal than symmetric moves:

  bid UP only   → next dmid = -0.55  (strong reversal DOWN)
  ask DOWN only → next dmid = +0.57  (strong reversal UP)
  bid DOWN only → next dmid ≈  0.00  (noise)
  ask UP only   → next dmid ≈  0.00  (noise)
  both moved    → next dmid ≈  0.00  (noise)
  neither moved → next dmid ≈  0.00  (noise)

These are stable across all 3 days (day 0 correlation: -0.51 for asymmetric,
-0.10 for symmetric). The mechanism: "bid UP only" = exit from a DOWN narrow
spread episode (spread=5/7), which always fully reverts.

IMPLEMENTATION: Track prev_best_bid and prev_best_ask. Classify the move type.
On "strong reversal" ticks, shift FV by ±0.5 to improve integer boundary.
On "noise" ticks, keep FV unmodified.

This is ORTHOGONAL to the microprice regression — microprice captures the
volume-weighted level, but misses the structural reversal signal when volumes
happen to be balanced (50/50 bid/ask vol → microprice barely shifts, but
reversal is still -0.55).

Base: L1 microprice regression (s36-proven coefficients) + original carry.
"""

# --- L1 Regression (s36-proven, website 2,896) ---
REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4

TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0

OBI_FV_SHIFT = 0.5

# --- Asymmetric move classifier ---
ASYM_FV_SHIFT = 0.5   # FV shift on strong reversal ticks

# --- Original carry signal ---
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

LIQUIDATION_WINDOW = 10


class Trader:
    def __init__(self):
        self.microprice_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.prev_best_ask = None
        self.carry_signal = 0.0

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.microprice_history = saved.get("mp", [])
            self.trade_flow_history = saved.get("tf", [])
            self.emerald_limit_history = saved.get("el", [])
            self.prev_best_bid = saved.get("bb")
            self.prev_best_ask = saved.get("ba")
            self.carry_signal = saved.get("cs", 0.0)

        orders = {}
        conversions = 0

        # ──────────────────────────────────────────────────────────────────────
        # EMERALDS: Fixed FV + liquidation (identical to anchored_quoting.py)
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
                    em_orders.append(Order("EMERALDS", min(EMERALD_FV - 1, bids[0][0] + 1), buy_cap))

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
                    em_orders.append(Order("EMERALDS", max(EMERALD_FV + 1, asks[0][0] - 1), -sell_cap))

                orders["EMERALDS"] = em_orders

        # ──────────────────────────────────────────────────────────────────────
        # TOMATOES: L1 Regression + Asymmetric Move Classifier + Original Carry
        # ──────────────────────────────────────────────────────────────────────
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5

                # --- L1 microprice regression (s36-proven) ---
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

                # --- Trade flow ---
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

                # --- OBI shift ---
                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fv += obi * OBI_FV_SHIFT

                # --- NOVEL: Asymmetric move classifier ---
                # Classify the move that just happened based on which side moved
                asym_shift = 0.0
                if self.prev_best_bid is not None and self.prev_best_ask is not None:
                    bid_moved = (best_bid != self.prev_best_bid)
                    ask_moved = (best_ask != self.prev_best_ask)
                    bid_delta = best_bid - self.prev_best_bid
                    ask_delta = best_ask - self.prev_best_ask

                    if bid_moved and not ask_moved:
                        # Only bid moved
                        if bid_delta > 0:
                            # Bid UP only → strong DOWN reversal expected
                            asym_shift = -ASYM_FV_SHIFT
                        # bid DOWN only → noise, no shift
                    elif ask_moved and not bid_moved:
                        # Only ask moved
                        if ask_delta < 0:
                            # Ask DOWN only → strong UP reversal expected
                            asym_shift = +ASYM_FV_SHIFT
                        # ask UP only → noise, no shift
                    # Both moved or neither → noise, no shift

                fv += asym_shift

                self.prev_best_ask = best_ask

                fv_int = round(fv)

                # --- Original carry signal ---
                if self.prev_best_bid is not None:
                    bd = best_bid - self.prev_best_bid
                    if bd >= CARRY_TRIGGER:
                        self.carry_signal = -1.0
                    elif bd <= -CARRY_TRIGGER:
                        self.carry_signal = 1.0
                    elif abs(bd) <= 1:
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

                # --- Directional posting (original carry) ---
                if self.carry_signal > CARRY_THRESHOLD:
                    if buy_cap > 0:
                        bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bp, buy_cap))
                    if sell_cap > 0:
                        ap = max(fv_int + CARRY_WIDE_OFFSET, best_ask - 1, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ap, -sell_cap))
                elif self.carry_signal < -CARRY_THRESHOLD:
                    if sell_cap > 0:
                        ap = max(fv_int + 1, best_ask - 1, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ap, -sell_cap))
                    if buy_cap > 0:
                        bp = min(fv_int - CARRY_WIDE_OFFSET, best_bid + 1, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bp, buy_cap))
                else:
                    if buy_cap > 0:
                        bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bp, buy_cap))
                    if sell_cap > 0:
                        ap = max(fv_int + 1, best_ask - 1, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ap, -sell_cap))

                orders["TOMATOES"] = tom_orders

        return orders, conversions, json.dumps(
            {"mp": self.microprice_history,
             "tf": self.trade_flow_history,
             "el": self.emerald_limit_history,
             "bb": self.prev_best_bid,
             "ba": self.prev_best_ask,
             "cs": round(self.carry_signal, 3)},
            separators=(",", ":")
        )
