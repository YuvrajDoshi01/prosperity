import json
from datamodel import Order, TradingState

"""
s65_dynamic_inv — s58 base + returns-based FV + dynamic inventory management

Core changes from s58:
1. FV = EMA(mid) + predicted_dmid (NOT AR(4) on levels)
   - EMA tracks the market wherever it goes (no stale intercept)
   - dmid regression predicts the CHANGE, which is stationary
   - If market trends permanently, EMA follows → no one-sided fills

2. Dynamic position scaling:
   - max_position shrinks when |predicted_dmid| is small (low conviction)
   - max_position shrinks when already inventoried against the signal
   - Prevents sitting at 80 in a trending market

3. Circuit breaker:
   - Tracks consecutive adverse fills (bought then price dropped)
   - After N adverse fills, slashes capacity on that side
   - Resets when price moves favorably

Everything else (L2 lead, carry, posting, EMERALDS) identical to s58.
"""

# === FV Engine: EMA + dmid regression ===
# dmid AR(4) coefficients (cross-validated, from session analysis)
# dmid[t] = sum(coef[i] * dmid[t-i]) + intercept
# These are STATIONARY — predict changes, not levels
DMID_COEFS = [-0.551536, -0.309438, -0.160757, -0.068804]
DMID_INTERCEPT = -0.004619  # near-zero (expected for stationary process)
DMID_LAGS = 4

# EMA smoothing for mid price anchor
EMA_ALPHA = 0.15  # higher = more responsive to trends, lower = smoother
# Blend: how much of the dmid prediction to use vs just EMA
DMID_BLEND = 1.0  # full predicted shift applied to EMA

# === Dynamic inventory management ===
POSITION_LIMIT = 80            # hard cap (exchange-enforced)
SOFT_POSITION_LIMIT = 80       # starting max before scaling
# Scale down max position when FV deviation from mid is small
# i.e., low conviction → don't hold big positions
FV_DEVIATION_SCALE = True
FV_DEV_THRESHOLD = 1.5         # if |FV - mid| < this, scale position down
FV_DEV_MIN_POSITION = 40       # minimum position even at zero conviction

# Scale down when inventoried against the predicted direction
INVENTORY_DIRECTION_SCALE = True
INV_SCALE_FACTOR = 0.5         # multiply capacity by this when inventory opposes signal

# === Circuit breaker ===
CIRCUIT_BREAKER_ENABLED = True
ADVERSE_FILL_WINDOW = 10       # look at last N ticks
ADVERSE_FILL_THRESHOLD = 4     # if N of last window ticks had adverse fills
CIRCUIT_BREAKER_FRACTION = 0.25  # slash capacity to this fraction

# === Same as s58 ===
TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0
OBI_FV_SHIFT = 0.5
CARRY_TRIGGER = 4
CARRY_DECAY = 0.7
CARRY_THRESHOLD = 0.5
CARRY_WIDE_OFFSET = 3
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40
TOMATO_POST_SKEW_THRESHOLD = 40
TERMINAL_TIMESTAMP = 900000
TERMINAL_POSITION_THRESHOLD = 28
LIQUIDATION_WINDOW = 10

# L2 lead (from s58)
L2_LEAD_THRESHOLD = 1
L2_STRONG_THRESHOLD = 2
L2_FV_SHIFT_WEAK = 1.0
L2_FV_SHIFT_STRONG = 0.0


class Trader:
    def __init__(self):
        self.mid_ema = None
        self.dmid_history = []        # last N dmid values for regression
        self.prev_mid = None
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
        # Circuit breaker tracking
        self.adverse_fills = []  # list of booleans: was the last fill adverse?
        self.last_fill_side = 0  # +1 = bought, -1 = sold
        self.last_fill_price = None

    def bid(self):
        return 15

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.mid_ema = saved.get("ema")
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
            self.adverse_fills = saved.get("af", [])
            self.last_fill_side = saved.get("lfs", 0)
            self.last_fill_price = saved.get("lfp")

        result = {}
        conversions = 0

        # ═══════════════════════════════════════════════════
        # EMERALDS — Identical to s58/s36
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
        # TOMATOES — EMA + dmid regression + dynamic inventory
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

                # === NEW: EMA-anchored FV with dmid prediction ===
                # Update EMA
                if self.mid_ema is None:
                    self.mid_ema = mid
                else:
                    self.mid_ema = EMA_ALPHA * mid + (1 - EMA_ALPHA) * self.mid_ema

                # Compute dmid and update history
                if self.prev_mid is not None:
                    dmid = mid - self.prev_mid
                else:
                    dmid = 0.0
                self.prev_mid = mid

                hist = self.dmid_history
                hist.append(dmid)
                if len(hist) > DMID_LAGS:
                    hist = hist[-DMID_LAGS:]
                self.dmid_history = hist

                # Predict next dmid from dmid history
                predicted_dmid = 0.0
                if len(hist) == DMID_LAGS:
                    predicted_dmid = DMID_INTERCEPT + sum(
                        c * x for c, x in zip(DMID_COEFS, hist))

                # FV = EMA + predicted change
                fair_value = self.mid_ema + predicted_dmid * DMID_BLEND

                # --- Trade flow adjustment (same as s58/s36) ---
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

                # --- OBI shift (same as s58/s36) ---
                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())
                obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                       if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                fair_value += obi * OBI_FV_SHIFT

                # --- L2 lead FV shift (from s58) ---
                if abs(l2_shift) >= 1.0:
                    fair_value += l2_shift * L2_FV_SHIFT_STRONG
                elif abs(l2_shift) > 0:
                    fair_value += (1.0 if l2_shift > 0 else -1.0) * L2_FV_SHIFT_WEAK

                fair_value_int = round(fair_value)

                # --- Carry signal (same as s58/s36) ---
                if self.prev_best_bid is not None:
                    bid_delta = best_bid - self.prev_best_bid
                    if bid_delta >= CARRY_TRIGGER:
                        self.carry_signal = -1.0
                    elif bid_delta <= -CARRY_TRIGGER:
                        self.carry_signal = 1.0
                    elif abs(bid_delta) <= 1:
                        self.carry_signal *= CARRY_DECAY
                self.prev_best_bid = best_bid

                # === NEW: Dynamic position sizing ===
                effective_limit = SOFT_POSITION_LIMIT

                # Scale down when low conviction (FV close to mid)
                if FV_DEVIATION_SCALE:
                    fv_dev = abs(fair_value - mid)
                    if fv_dev < FV_DEV_THRESHOLD:
                        # Linear scale: at fv_dev=0, use min; at threshold, use full
                        scale = FV_DEV_MIN_POSITION + (
                            (SOFT_POSITION_LIMIT - FV_DEV_MIN_POSITION)
                            * fv_dev / FV_DEV_THRESHOLD)
                        effective_limit = min(effective_limit, scale)

                # Scale down when inventory opposes predicted direction
                if INVENTORY_DIRECTION_SCALE and predicted_dmid != 0:
                    # pos > 0 and predicted DOWN, or pos < 0 and predicted UP
                    if (pos > 0 and predicted_dmid < 0) or (pos < 0 and predicted_dmid > 0):
                        effective_limit = effective_limit * INV_SCALE_FACTOR

                effective_limit = max(10, int(effective_limit))  # floor at 10

                # === NEW: Circuit breaker ===
                # Check if last tick had adverse fill
                if self.last_fill_price is not None:
                    if self.last_fill_side > 0:
                        # Bought last tick — adverse if mid dropped
                        adverse = mid < self.last_fill_price - 0.5
                    elif self.last_fill_side < 0:
                        adverse = mid > self.last_fill_price + 0.5
                    else:
                        adverse = False
                    self.adverse_fills.append(adverse)
                    if len(self.adverse_fills) > ADVERSE_FILL_WINDOW:
                        self.adverse_fills = self.adverse_fills[-ADVERSE_FILL_WINDOW:]

                circuit_break_buy = False
                circuit_break_sell = False
                if CIRCUIT_BREAKER_ENABLED and len(self.adverse_fills) >= ADVERSE_FILL_WINDOW:
                    recent_adverse = sum(self.adverse_fills[-ADVERSE_FILL_WINDOW:])
                    if recent_adverse >= ADVERSE_FILL_THRESHOLD:
                        # Which side is bleeding? Look at position
                        if pos > 20:
                            circuit_break_buy = True  # stop buying, we're long and bleeding
                        elif pos < -20:
                            circuit_break_sell = True

                # Apply effective limit to capacities
                buy_capacity = min(POSITION_LIMIT - pos, effective_limit - pos)
                sell_capacity = min(POSITION_LIMIT + pos, effective_limit + pos)
                buy_capacity = max(0, buy_capacity)
                sell_capacity = max(0, sell_capacity)

                # Apply circuit breaker
                if circuit_break_buy:
                    buy_capacity = int(buy_capacity * CIRCUIT_BREAKER_FRACTION)
                if circuit_break_sell:
                    sell_capacity = int(sell_capacity * CIRCUIT_BREAKER_FRACTION)

                # Track fills for circuit breaker (will be set after takes)
                self.last_fill_side = 0
                self.last_fill_price = None

                # --- Phase 1: Takes at fair value ---
                for price, vol in sorted(book.sell_orders.items()):
                    if buy_capacity > 0 and price <= fair_value_int:
                        qty = min(buy_capacity, -vol)
                        tom_orders.append(Order("TOMATOES", price, qty))
                        buy_capacity -= qty
                        self.last_fill_side = 1
                        self.last_fill_price = price

                for price, vol in sorted(book.buy_orders.items(), reverse=True):
                    if sell_capacity > 0 and price >= fair_value_int:
                        qty = min(sell_capacity, vol)
                        tom_orders.append(Order("TOMATOES", price, -qty))
                        sell_capacity -= qty
                        self.last_fill_side = -1
                        self.last_fill_price = price

                # --- Terminal flatten (same as s58/s36) ---
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

                # --- Phase 2: Posting (same as s58/s36) ---
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
            {"ema": round(self.mid_ema, 2) if self.mid_ema else None,
             "dh": [round(d, 3) for d in self.dmid_history],
             "pm": self.prev_mid,
             "tf": self.trade_flow_history,
             "el": self.emerald_limit_history,
             "bb": self.prev_best_bid,
             "cs": round(self.carry_signal, 3),
             "pb1": self.prev_bid1, "pa1": self.prev_ask1,
             "pb2": self.prev_bid2, "pa2": self.prev_ask2,
             "l2s": round(self.l2_signal, 2),
             "af": self.adverse_fills[-ADVERSE_FILL_WINDOW:],
             "lfs": self.last_fill_side,
             "lfp": self.last_fill_price},
            separators=(",", ":")
        )
