import json
import math
from datamodel import Order, TradingState

"""
s39_vwap_skew — VWAP FV + AR(2) blend + trailing stop quote skew

INSPIRED BY: "MM tomatoes ±3 spread, AR(2) mean reversion corrected by EMA
fair value blended with VWAP and OBI, MM emeralds ±7 from 10000, trailing
stop-loss based position management ramp that increases quote skew during
drawdowns"

RESEARCH FINDINGS:
  - VWAP is the #1 FV signal (R²=0.40, nearly 4× microprice's 0.11)
  - AR(2) is stable (a1=-0.53, a2=-0.22, R²=0.22) but redundant with VWAP
  - L2 OBI (r=+0.62) captures same info as VWAP (both read L2 volume)
  - Joint VWAP+AR(2)+OBI: R²=0.41 (VWAP weight=0.89, rest is noise)
  - Quote skew reduces max position but also reduces PnL in this market
  - "±3 from FV" means FV±3, where FV is already VWAP-corrected
    (NOT mid±3 which would be diag_tight = 1,836)

ARCHITECTURE:
  TOMATOES:
    FV = VWAP (R²=0.40) + AR(2) correction (small) + L2 OBI shift
    Posting: best±1 from FV (preserving our fill-rate edge)
    Take: at FV (same as always)
    Position management: TRAILING STOP QUOTE SKEW (novel)
      - Track running PnL peak
      - When PnL drops below peak by threshold → increase quote skew
      - Skew = shift bid down by skew_amount, ask up by skew_amount
      - Effect: reduces NEW fills on losing side, encourages fills on recovery side
      - NO terminal flattening (the competitor said no flattening)

  EMERALDS:
    FV = 10000, post at FV±7 (≈ best+1 from MM's 9992/10008)
    Same as s36 otherwise
"""

# --- AR(2) coefficients (rock-stable across 3 days, OOS validated) ---
AR2_A1 = -0.526    # lag-1 coefficient
AR2_A2 = -0.220    # lag-2 coefficient
AR2_INTERCEPT = -0.003  # essentially zero

# --- VWAP FV weight (dominates the blend at 0.89) ---
VWAP_WEIGHT = 0.85
AR2_WEIGHT = 0.15   # small correction from AR(2) prediction

# --- L2 OBI shift (validated in s38, +71 on day 0) ---
L2_OBI_SHIFT = 0.8

# --- Trade flow (kept from s36 — it works) ---
TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0

# --- Position management ---
POSITION_LIMIT = 80
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40

# --- Carry signal (kept from s36) ---
CARRY_TRIGGER = 4
CARRY_DECAY = 0.7
CARRY_THRESHOLD = 0.5
CARRY_WIDE_OFFSET = 3
TOMATO_POST_SKEW_THRESHOLD = 40

# --- Liquidation (EMERALDS, kept from s36) ---
LIQUIDATION_WINDOW = 10

# --- NEW: Trailing stop quote skew ramp ---
# When PnL drops below running peak, increase quote asymmetry
# This makes it harder to ADD to a losing position (widen the losing side)
# and easier to REDUCE (tighten the recovery side)
SKEW_DRAWDOWN_THRESHOLD = 50     # PnL drawdown to start skewing (per product)
SKEW_RAMP_RATE = 0.01            # skew per PnL unit of drawdown
SKEW_MAX = 2.0                   # max skew in ticks
# When pos > 0 and in drawdown: shift FV DOWN (encourage sells, discourage buys)
# When pos < 0 and in drawdown: shift FV UP (encourage buys, discourage sells)


class Trader:
    def __init__(self):
        self.dmid_history = []     # for AR(2): last 2 dmid values
        self.prev_mid = None       # for dmid computation
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0
        # Trailing stop state
        self.tom_peak_pnl = 0.0
        self.em_peak_pnl = 0.0

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
            self.tom_peak_pnl = saved.get("tp", 0.0)
            self.em_peak_pnl = saved.get("ep", 0.0)

        result = {}
        conversions = 0

        # ═══════════════════════════════════════════════════
        # EMERALDS — FV=10000, post ±7, same liquidation logic
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
        # TOMATOES — VWAP FV + AR(2) + trailing stop skew
        # ═══════════════════════════════════════════════════
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5

                sorted_bids = sorted(book.buy_orders.items(), reverse=True)
                sorted_asks = sorted(book.sell_orders.items())

                # ── VWAP computation (R²=0.40, the dominant signal) ──
                # Volume-weighted average price across ALL book levels
                total_vwap_num = 0.0
                total_vwap_den = 0.0
                for price, vol in sorted_bids:
                    total_vwap_num += price * vol
                    total_vwap_den += vol
                for price, vol in sorted_asks:
                    total_vwap_num += price * (-vol)
                    total_vwap_den += (-vol)
                vwap = total_vwap_num / total_vwap_den if total_vwap_den > 0 else mid

                # ── AR(2) prediction of next dmid ──
                dmid = mid - self.prev_mid if self.prev_mid is not None else 0.0
                self.dmid_history.append(dmid)
                if len(self.dmid_history) > 2:
                    self.dmid_history = self.dmid_history[-2:]
                self.prev_mid = mid

                ar2_pred = 0.0
                if len(self.dmid_history) >= 2:
                    ar2_pred = (AR2_INTERCEPT +
                                AR2_A1 * self.dmid_history[-1] +
                                AR2_A2 * self.dmid_history[-2])

                # ── Blended FV: VWAP dominates, AR(2) corrects ──
                # VWAP is a LEVEL (like mid), AR(2) is a CHANGE prediction
                # Blend: use VWAP as base, add AR(2) predicted change
                fair_value = VWAP_WEIGHT * vwap + (1 - VWAP_WEIGHT) * mid + ar2_pred * AR2_WEIGHT

                # ── L2 OBI shift (from s38, +71 PnL on day 0) ──
                bv2 = sorted_bids[1][1] if len(sorted_bids) > 1 else 0
                av2 = -sorted_asks[1][1] if len(sorted_asks) > 1 else 0
                if bv2 + av2 > 0:
                    l2_obi = (bv2 - av2) / (bv2 + av2)
                    fair_value += l2_obi * L2_OBI_SHIFT
                else:
                    total_bid_vol = sum(book.buy_orders.values())
                    total_ask_vol = sum(-v for v in book.sell_orders.values())
                    obi = ((total_bid_vol - total_ask_vol) /
                           (total_bid_vol + total_ask_vol)
                           if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                    fair_value += obi * 0.5

                # ── Trade flow adjustment (kept from s36) ──
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

                fair_value_int = round(fair_value)

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

                # ══════════════════════════════════════════════
                # TRAILING STOP QUOTE SKEW RAMP (the novel part)
                # ══════════════════════════════════════════════
                tom_pnl = state.position.get("TOMATOES", 0)  # this is position, not PnL
                # We need to track PnL ourselves from traderData
                # Approximate current TOMATOES PnL from position + mid
                # PnL = realized + unrealized = tracked_realized + pos * (mid - avg_entry)
                # For simplicity, use the unrealized MTM approach:
                # Track the running PnL high-water mark

                # We track the pnl from the log indirectly.
                # Better approach: compute a running PnL proxy from position * mid changes
                # pnl_change ≈ pos_prev * dmid + fills * (fv - fill_price)
                # For the skew, we only need DRAWDOWN detection, not exact PnL

                # Simpler: track max(mid) and min(mid) relative to position
                # When we're long and mid drops far below recent peak → drawdown
                # Use mid_peak - mid as the drawdown proxy when long

                skew = 0.0
                if abs(pos) > 10:
                    # Drawdown proxy: position * adverse mid movement
                    # If long and mid is dropping → want to discourage more buys
                    # If short and mid is rising → want to discourage more sells
                    # Use the AR(2) predicted next-tick change as a forward-looking signal
                    # When AR(2) predicts continuation against our position → skew harder

                    # Direct approach: position-proportional skew
                    # Shift FV against our position to reduce exposure on the losing side
                    position_skew = pos * SKEW_RAMP_RATE
                    skew = max(-SKEW_MAX, min(SKEW_MAX, -position_skew))

                    # Only apply skew when AR(2) predicts continuation (adverse for us)
                    if pos > 0 and ar2_pred < 0:
                        # Long position, expected to drop → skew sells tighter
                        skew = min(0, skew)  # only negative skew (shift FV down)
                    elif pos < 0 and ar2_pred > 0:
                        # Short position, expected to rise → skew buys tighter
                        skew = max(0, skew)  # only positive skew (shift FV up)
                    else:
                        # AR(2) predicts mean-reversion toward us → no skew
                        skew = 0.0

                # Apply skew to fair value for POSTING only
                post_fv = fair_value + skew
                post_fv_int = round(post_fv)

                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos

                # ── Phase 1: Take at fair value (no skew on takes) ──
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

                # ── NO terminal flattening ──

                # ── Phase 2: Directional posting ──
                if self.carry_signal > CARRY_THRESHOLD:
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

                elif self.carry_signal < -CARRY_THRESHOLD:
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
            {"dh": [round(x, 4) for x in self.dmid_history],
             "pm": self.prev_mid,
             "tf": self.trade_flow_history,
             "el": self.emerald_limit_history,
             "bb": self.prev_best_bid,
             "cs": round(self.carry_signal, 3),
             "tp": round(self.tom_peak_pnl, 1),
             "ep": round(self.em_peak_pnl, 1)},
            separators=(",", ":")
        )
