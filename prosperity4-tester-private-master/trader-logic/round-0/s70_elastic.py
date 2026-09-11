import json
from datamodel import Order, TradingState

"""
s69_taker_leash_450 — s36 base + selective directional book takes + 450-tick Leash
"""

# --- TOMATOES fair value regression ---
REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4

# --- Trade flow signal ---
TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0

# --- L1/L2 OBI shift ---
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
TOMATO_POST_SKEW_THRESHOLD = 40
TERMINAL_TIMESTAMP = 900000
TERMINAL_POSITION_THRESHOLD = 28

# --- Liquidation ---
LIQUIDATION_WINDOW = 10

# === Directional take parameters ===
TAKE_EMA_ALPHA = 0.01        
TAKE_THRESHOLD = 8.0          
TAKE_QTY = 3                  
TAKE_COOLDOWN = 5             
POSITION_LEASH_TICKS = 500    # Extended from 350 to give mean-reversion more room


class Trader:
    def __init__(self):
        self.microprice_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0
        self.ema_mid = None
        self.last_take_tick = -999
        
        # Leash state
        self.pos_start_tick = None
        self.last_pos = 0

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
            self.ema_mid = saved.get("em")
            self.last_take_tick = saved.get("lt", -999)
            self.pos_start_tick = saved.get("pst")
            self.last_pos = saved.get("lp", 0)

        result = {}
        conversions = 0
        tick_num = state.timestamp // 100  

        # ═══════════════════════════════════════════════════
        # EMERALDS 
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
        # TOMATOES
        # ═══════════════════════════════════════════════════
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5
                
                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos

                # --- Update Position Age ---
                if pos == 0:
                    self.pos_start_tick = None
                elif self.last_pos == 0 and pos != 0:
                    self.pos_start_tick = tick_num
                elif (self.last_pos > 0 and pos < 0) or (self.last_pos < 0 and pos > 0):
                    self.pos_start_tick = tick_num
                
                self.last_pos = pos

                # Check if we've held the bag too long
                force_flatten = False
                if self.pos_start_tick is not None and (tick_num - self.pos_start_tick) > POSITION_LEASH_TICKS:
                    force_flatten = True

                if force_flatten:
                    # Execute market order to puke inventory and skip normal operations
                    if pos > 0 and sell_capacity > 0:
                        qty = min(sell_capacity, pos)
                        tom_orders.append(Order("TOMATOES", best_bid, -qty))
                    elif pos < 0 and buy_capacity > 0:
                        qty = min(buy_capacity, -pos)
                        tom_orders.append(Order("TOMATOES", best_ask, qty))
                    
                    self.pos_start_tick = None
                else:
                    # --- Normal Operations ---
                    
                    # Update EMA
                    if self.ema_mid is None:
                        self.ema_mid = mid
                    else:
                        self.ema_mid += TAKE_EMA_ALPHA * (mid - self.ema_mid)

                    # Fair value: microprice regression
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

                    # Trade flow adjustment
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

                    # L1/L2 OBI shift
                    obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
                           if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                    fair_value += obi * OBI_FV_SHIFT

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

                    # Selective directional take
                    ema_dev = mid - self.ema_mid
                    can_take = (tick_num - self.last_take_tick) >= TAKE_COOLDOWN

                    if can_take and abs(ema_dev) > TAKE_THRESHOLD:
                        if ema_dev < -TAKE_THRESHOLD and buy_capacity > 0:
                            take_qty = min(TAKE_QTY, buy_capacity)
                            if take_qty > 0:
                                tom_orders.append(Order("TOMATOES", best_ask, take_qty))
                                buy_capacity -= take_qty
                                self.last_take_tick = tick_num
                        elif ema_dev > TAKE_THRESHOLD and sell_capacity > 0:
                            take_qty = min(TAKE_QTY, sell_capacity)
                            if take_qty > 0:
                                tom_orders.append(Order("TOMATOES", best_bid, -take_qty))
                                sell_capacity -= take_qty
                                self.last_take_tick = tick_num

                    # Phase 1: Take at fair value
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

                    # Terminal flatten
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

                    # Phase 2: Directional posting
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
             "em": round(self.ema_mid, 2) if self.ema_mid is not None else None,
             "lt": self.last_take_tick,
             "pst": self.pos_start_tick,
             "lp": self.last_pos},
            separators=(",", ":")
        )