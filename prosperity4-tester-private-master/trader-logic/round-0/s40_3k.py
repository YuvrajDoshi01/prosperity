import json
from datamodel import Order, TradingState

"""
s40_3k — Maximum-ceiling strategy, targeting 3.0-3.3k on website

All changes are ORTHOGONAL and individually motivated:

1. SEPARATE take-FV and post-FV (from s38_microstructure architecture):
   - Take FV: conservative (bad take costs 13 ticks)
   - Post FV: aggressive (bad post costs 0, just misses a fill)
   L2 OBI and narrow-spread signals only affect POSTING, not takes.

2. CONDITIONAL L2 OBI (threshold-gated):
   - L2 OBI fires on 7% of ticks with 97-99% accuracy
   - On the other 93%, it's noise that can push FV past integer boundaries
   - Gate: only apply when |l2_obi| > 0.25 (strong signal regime)
   - For takes: use total OBI at conservative 0.5 (proven in s36)
   - For posts: use L2 OBI at 0.8 when strong, total OBI otherwise

3. AR(2) DIRECTIONAL CORRECTION (R²=0.225, OOS-validated):
   - dmid_pred = -0.526 * dmid[t-1] - 0.220 * dmid[t-2]
   - Applied to post-FV only (small 0.3 coefficient)
   - Captures mean-reversion signal the microprice regression doesn't directly encode

4. POSITION SKEW gamma=0.01 (from s39, zero-cost on 2k ticks):
   - Applied to BOTH take and post FV (shifts which side of integer boundary we land on)
   - At |pos|=80, shifts FV by only 0.8 — never causes a bad take alone

5. NARROW SPREAD DIRECTIONAL POSTING (from s38_final, posting only):
   - Spread 5→UP 96%, 7→UP 82%, 6→DOWN 73%, 8→DOWN 74%, 9→DOWN 94%
   - Only fires on 7% of ticks when spread is narrow

6. NO TERMINAL FLATTEN (from s39):
   - On 2k ticks, never fires anyway (max ts = 199,900 < 900,000)
   - Position skew handles inventory instead

WHY THIS COULD REACH 3.3k:
- Separate FV architecture prevents L2 OBI noise from causing bad takes (~30-60 PnL saved)
- Conditional OBI threshold eliminates 93% of noise applications
- AR(2) adds directional information for posting (orthogonal to microprice regression)
- All three effects are INVISIBLE to backtester (they improve taker-fill positioning,
  which only matters on the website where taker hits our inside-spread orders)
- Expected backtester score: ~2,680-2,700 (comparable to s38/s39)
- Expected website score: 2,950-3,300 (depending on directional accuracy transfer)
"""

# ── Microprice regression (proven, from s36) ──
REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4

# ── Trade flow (proven, from s36) ──
TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0

# ── OBI configuration ──
TOTAL_OBI_SHIFT = 0.5        # Conservative total OBI for take-FV (proven in s36)
L2_OBI_SHIFT = 0.8           # Aggressive L2 OBI for post-FV (proven in s38)
L2_OBI_THRESHOLD = 0.25      # Only apply L2 when signal is strong

# ── AR(2) directional correction (posting only) ──
AR2_COEF_1 = -0.526          # Lag-1 coefficient (stable across all days)
AR2_COEF_2 = -0.220          # Lag-2 coefficient (stable across all days)
AR2_POST_WEIGHT = 0.3        # Small weight — just a nudge to posting direction

# ── Position skew (from s39, applies to both take and post FV) ──
SKEW_GAMMA = 0.01

# ── Carry signal ──
CARRY_TRIGGER = 4
CARRY_DECAY = 0.7
CARRY_THRESHOLD = 0.5
CARRY_WIDE_OFFSET = 3

# ── Position management ──
POSITION_LIMIT = 80
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40
TOMATO_POST_SKEW_THRESHOLD = 40

# ── EMERALDS liquidation ──
LIQUIDATION_WINDOW = 10

# ── Narrow spread direction map (posting only) ──
SPREAD_DIRECTION = {5: +1, 6: -1, 7: +1, 8: -1, 9: -1}


class Trader:
    def __init__(self):
        self.microprice_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0
        self.mid_history = []  # For AR(2) dmid computation

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
        # EMERALDS — Identical to s36 (proven optimal)
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
        # TOMATOES — Dual-FV architecture
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

                # ── Book data extraction ──
                sorted_bids = sorted(book.buy_orders.items(), reverse=True)
                sorted_asks = sorted(book.sell_orders.items())
                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())

                # ── Microprice regression (base FV, identical to s36) ──
                microprice = (best_bid + (total_bid_vol / (total_bid_vol + total_ask_vol))
                              * (best_ask - best_bid)
                              if (total_bid_vol + total_ask_vol) > 0 else mid)

                hist = self.microprice_history
                if len(hist) >= REGRESSION_LAGS:
                    hist = hist[1:]
                hist.append(microprice)
                self.microprice_history = hist

                if len(hist) == REGRESSION_LAGS:
                    base_fv = REGRESSION_INTERCEPT + sum(
                        c * x for c, x in zip(REGRESSION_COEFS, hist))
                else:
                    base_fv = microprice

                # ── Trade flow (identical to s36) ──
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
                base_fv -= flow_signal * TRADE_FLOW_COEF

                # ── OBI computation ──
                # Total OBI (for take-FV, conservative)
                total_obi = ((total_bid_vol - total_ask_vol) /
                             (total_bid_vol + total_ask_vol)
                             if (total_bid_vol + total_ask_vol) > 0 else 0.0)

                # L2 OBI (for post-FV, aggressive)
                bv2 = sorted_bids[1][1] if len(sorted_bids) > 1 else 0
                av2 = -sorted_asks[1][1] if len(sorted_asks) > 1 else 0
                l2_obi = (bv2 - av2) / (bv2 + av2) if (bv2 + av2) > 0 else 0.0
                l2_strong = abs(l2_obi) > L2_OBI_THRESHOLD

                # ── AR(2) directional prediction ──
                self.mid_history.append(mid)
                if len(self.mid_history) > 3:
                    self.mid_history = self.mid_history[-3:]
                ar2_correction = 0.0
                if len(self.mid_history) >= 3:
                    dmid_1 = self.mid_history[-1] - self.mid_history[-2]
                    dmid_2 = self.mid_history[-2] - self.mid_history[-3]
                    ar2_correction = AR2_COEF_1 * dmid_1 + AR2_COEF_2 * dmid_2

                # ══════════════════════════════════════════════
                # TAKE FV: conservative — only proven signals
                # ══════════════════════════════════════════════
                take_fv = base_fv
                take_fv += total_obi * TOTAL_OBI_SHIFT  # s36's proven OBI
                take_fv -= pos * SKEW_GAMMA              # Position skew (< 1 tick)
                take_fv_int = round(take_fv)

                # ══════════════════════════════════════════════
                # POST FV: aggressive — add speculative signals
                # ══════════════════════════════════════════════
                post_fv = base_fv
                # L2 OBI: conditional on signal strength
                if l2_strong:
                    post_fv += l2_obi * L2_OBI_SHIFT     # Strong L2 signal
                else:
                    post_fv += total_obi * TOTAL_OBI_SHIFT  # Fallback to total OBI
                post_fv -= pos * SKEW_GAMMA              # Position skew
                post_fv += ar2_correction * AR2_POST_WEIGHT  # AR(2) directional nudge
                post_fv_int = round(post_fv)

                # ── Carry signal (identical to s36) ──
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

                # ── Phase 1: Take at CONSERVATIVE fair value ──
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

                # ── Phase 2: Post at AGGRESSIVE fair value ──
                # Determine posting signal: carry + narrow spread override
                posting_signal = self.carry_signal

                # Narrow spread directional posting
                spread_int = int(spread)
                if spread_int in SPREAD_DIRECTION:
                    narrow_dir = SPREAD_DIRECTION[spread_int]
                    posting_signal += narrow_dir * 0.8

                if posting_signal > CARRY_THRESHOLD:
                    # Expect UP: tight bid, wide ask
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
                    # Expect DOWN: wide bid, tight ask
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
                    # Neutral: symmetric best±1
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
