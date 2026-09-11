import json
from datamodel import Order, TradingState

"""
r1_chess_fader_v2 — "Forced Sequence" Strategy (Improved)

Improved from r1_chess_fader based on advisor hint analysis:

  Chess Engine: "Easier to follow, once you commit to the pattern."
  Orin: "Slow-growing goods reveal their direction gradually...
         easier to reason about in the near future, AND FURTHER AHEAD."

CHANGES FROM r1_chess_fader:
  1. REPLACED: Fixed IPR_DRIFT_BIAS=5.0 with rolling drift estimate
     - "Recalculate" = update the drift, not a constant guess
     - Drift changes across the session as IPR trends (+1000/day)
     - Volume-independent: uses only mid price levels

  2. ADDED: 4-lag fixed regression as base FV (before applying fade)
     - Coefs [0.2474, 0.2529, 0.2412, 0.2585] cross-validated across 3 days
     - "Commit to the pattern" = lock in structural parameters
     - Provides a smoother FV than raw microprice + drift

  3. ADDED: Trade flow signal (coef=1.5, window=5) from r1_medallion
     - Proven +207 PnL in Round 0 from diffuse posting shifts

  4. TUNED: DRIFT_HORIZON from implicit 1 to explicit 5
     - Orin says "further ahead" — 5-tick projection captures more of the trend
     - Safe: drift_rate is ~0.1/tick, 5-tick horizon adds ~0.5 to FV

  5. KEPT: The fade logic (unique differentiator vs r1_medallion)
     - AC(1)=-0.50 mean reversion after large cumulative moves
     - "Forced sequence" = chess engine sees the mandatory reversal
     - Applied AFTER regression FV (fade adjusts posting, not FV)

  The improved version: r1_medallion + explicit AC(1) fade signal.
  If the fade captures something the carry signal doesn't, this wins.
"""

# === INTARIAN_PEPPER_ROOT CONFIG ===
IPR = "INTARIAN_PEPPER_ROOT"
IPR_LIMIT = 80
IPR_LAGS = 4

# Fixed cross-validated regression coefficients
IPR_FIXED_COEFS = [0.2474, 0.2529, 0.2412, 0.2585]
IPR_FIXED_INTERCEPT = 0.2078

# Rolling drift estimation (replaces fixed IPR_DRIFT_BIAS=5.0)
IPR_DRIFT_WINDOW = 50
IPR_DRIFT_HORIZON = 5         # "Further ahead" per Orin

# Forced-sequence (mean-reversion) parameters
IPR_FADE_WINDOW = 10          # Cumulative move measurement window
IPR_FADE_TRIGGER = 6          # |cum_move| > this = forced reversion detected
IPR_FADE_TIGHT = 1            # Tighter posting offset when fading
IPR_FADE_WIDE = 3             # Wider posting offset on faded side

# OBI shift
IPR_OBI_SHIFT = 0.5

# Trade flow signal
IPR_TF_COEF = 1.5
IPR_TF_WINDOW = 5
IPR_TF_NORM = 15.0

# Order placement
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3
IPR_AGGRESSION_THRESHOLD = 40

# === ASH_COATED_OSMIUM CONFIG ===
ACO = "ASH_COATED_OSMIUM"
ACO_LIMIT = 80
ACO_FV = 10000
ACO_AGGRESSION_THRESHOLD = 40
ACO_LIQUIDATION_WINDOW = 10


class Trader:
    def __init__(self):
        self.ipr_mp_hist = []    # Microprice history (regression lags)
        self.ipr_mids = []       # Mid history (drift + fade detection)
        self.ipr_tf_hist = []    # Trade flow history
        self.aco_liq = []

    def bid(self):
        return 15

    def _estimate_drift(self):
        """
        Rolling drift rate from pure mid prices.
        The ONLY "recalculate" — volume-independent, safe for website.
        Replaces the fixed IPR_DRIFT_BIAS=5.0 that couldn't adapt.
        """
        mid = self.ipr_mids
        if len(mid) < IPR_DRIFT_WINDOW:
            return 0.1  # Default: ~+1000/10000 ticks
        recent = mid[-IPR_DRIFT_WINDOW:]
        return (recent[-1] - recent[0]) / len(recent)

    def _compute_trade_flow(self, state):
        """Trade flow signal from recent market trades."""
        trades = state.market_trades.get(IPR, [])
        signed = 0.0
        for t in trades:
            signed += t.quantity
        self.ipr_tf_hist.append(signed)
        if len(self.ipr_tf_hist) > IPR_TF_WINDOW:
            self.ipr_tf_hist = self.ipr_tf_hist[-IPR_TF_WINDOW:]

        if not self.ipr_tf_hist:
            return 0.0
        return IPR_TF_COEF * sum(self.ipr_tf_hist) / IPR_TF_NORM

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.ipr_mp_hist = saved.get("mp", [])
            self.ipr_mids = saved.get("m", [])
            self.ipr_tf_hist = saved.get("tf", [])
            self.aco_liq = saved.get("l", [])

        result = {}
        conversions = 0

        # ====================================================
        # ASH_COATED_OSMIUM — identical to r1_medallion (proven)
        # ====================================================
        if ACO in state.order_depths:
            book = state.order_depths[ACO]
            has_bids = bool(book.buy_orders)
            has_asks = bool(book.sell_orders)

            if has_bids or has_asks:
                orders = []
                pos = state.position.get(ACO, 0)
                buy_cap = ACO_LIMIT - pos
                sell_cap = ACO_LIMIT + pos
                fv_int = ACO_FV

                best_bid = max(book.buy_orders) if has_bids else None
                best_ask = min(book.sell_orders) if has_asks else None

                self.aco_liq.append(abs(pos) == ACO_LIMIT)
                if len(self.aco_liq) > ACO_LIQUIDATION_WINDOW:
                    self.aco_liq = self.aco_liq[-ACO_LIQUIDATION_WINDOW:]
                soft = (len(self.aco_liq) == ACO_LIQUIDATION_WINDOW
                        and sum(self.aco_liq) >= 5 and self.aco_liq[-1])
                hard = (len(self.aco_liq) == ACO_LIQUIDATION_WINDOW
                        and all(self.aco_liq))

                max_buy = fv_int if pos <= ACO_AGGRESSION_THRESHOLD else fv_int - 1
                min_sell = fv_int if pos >= -ACO_AGGRESSION_THRESHOLD else fv_int + 1

                if has_asks:
                    for price, vol in sorted(book.sell_orders.items()):
                        if buy_cap > 0 and price <= max_buy:
                            qty = min(buy_cap, -vol)
                            orders.append(Order(ACO, price, qty))
                            buy_cap -= qty

                if has_bids:
                    for price, vol in sorted(book.buy_orders.items(), reverse=True):
                        if sell_cap > 0 and price >= min_sell:
                            qty = min(sell_cap, vol)
                            orders.append(Order(ACO, price, -qty))
                            sell_cap -= qty

                if buy_cap > 0 and hard:
                    orders.append(Order(ACO, fv_int, buy_cap // 2))
                    buy_cap -= buy_cap // 2
                if buy_cap > 0 and soft:
                    orders.append(Order(ACO, fv_int - 2, buy_cap // 2))
                    buy_cap -= buy_cap // 2
                if sell_cap > 0 and hard:
                    orders.append(Order(ACO, fv_int, -(sell_cap // 2)))
                    sell_cap -= sell_cap // 2
                if sell_cap > 0 and soft:
                    orders.append(Order(ACO, fv_int + 2, -(sell_cap // 2)))
                    sell_cap -= sell_cap // 2

                if has_bids and has_asks:
                    if buy_cap > 0:
                        bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                        orders.append(Order(ACO, bp, buy_cap))
                    if sell_cap > 0:
                        ap = max(fv_int + 1, best_ask - 1, best_bid + 1)
                        orders.append(Order(ACO, ap, -sell_cap))
                elif has_bids:
                    if buy_cap > 0:
                        orders.append(Order(ACO, min(fv_int - 1, best_bid + 1), buy_cap))
                    if sell_cap > 0:
                        orders.append(Order(ACO, fv_int + 1, -sell_cap))
                elif has_asks:
                    if sell_cap > 0:
                        orders.append(Order(ACO, max(fv_int + 1, best_ask - 1), -sell_cap))
                    if buy_cap > 0:
                        orders.append(Order(ACO, fv_int - 1, buy_cap))

                result[ACO] = orders

        # ====================================================
        # INTARIAN_PEPPER_ROOT — "Forced Sequence" Fader v2
        # Fixed regression base + rolling drift + AC(1) fade
        # ====================================================
        if IPR in state.order_depths:
            book = state.order_depths[IPR]
            has_bids = bool(book.buy_orders)
            has_asks = bool(book.sell_orders)

            if has_bids or has_asks:
                orders = []
                pos = state.position.get(IPR, 0)
                buy_cap = IPR_LIMIT - pos
                sell_cap = IPR_LIMIT + pos

                best_bid = max(book.buy_orders) if has_bids else None
                best_ask = min(book.sell_orders) if has_asks else None

                if has_bids and has_asks:
                    mid = (best_bid + best_ask) * 0.5

                    # -- Compute microprice + OBI --
                    total_bv = sum(book.buy_orders.values())
                    total_av = sum(-v for v in book.sell_orders.values())
                    if total_bv + total_av > 0:
                        mp = best_bid + (total_bv / (total_bv + total_av)) * (best_ask - best_bid)
                        obi = (total_bv - total_av) / (total_bv + total_av)
                    else:
                        mp = mid
                        obi = 0.0

                    # -- Update rolling histories --
                    self.ipr_mp_hist.append(mp)
                    self.ipr_mids.append(mid)
                    max_keep = max(IPR_DRIFT_WINDOW, IPR_FADE_WINDOW, IPR_LAGS) + 10
                    if len(self.ipr_mp_hist) > max_keep:
                        self.ipr_mp_hist = self.ipr_mp_hist[-max_keep:]
                    if len(self.ipr_mids) > max_keep:
                        self.ipr_mids = self.ipr_mids[-max_keep:]

                    # -- Base FV: fixed 4-lag regression (NEW — was raw microprice) --
                    # "Commit to the pattern" — structural coefs, never refitted
                    if len(self.ipr_mp_hist) >= IPR_LAGS:
                        lags = self.ipr_mp_hist[-IPR_LAGS:]
                        fv = IPR_FIXED_INTERCEPT
                        for i, lag_val in enumerate(lags):
                            fv += IPR_FIXED_COEFS[i] * lag_val
                    else:
                        fv = mp  # Warmup fallback

                    # -- Rolling drift (NEW — replaces fixed IPR_DRIFT_BIAS=5.0) --
                    # "Recalculate" the drift as the game unfolds
                    drift_rate = self._estimate_drift()
                    fv += drift_rate * IPR_DRIFT_HORIZON

                    # -- OBI nudge --
                    fv += obi * IPR_OBI_SHIFT

                    # -- Trade flow signal (NEW — from r1_medallion) --
                    tf_signal = self._compute_trade_flow(state)
                    fv += tf_signal

                    fv_int = round(fv)

                    # -- Forced Sequence Detection --
                    # "Every large price move is a forced sequence — the board MUST revert."
                    # Track cumulative move over fade window
                    if len(self.ipr_mids) >= 2:
                        window_start = max(0, len(self.ipr_mids) - IPR_FADE_WINDOW - 1)
                        cum_move = self.ipr_mids[-1] - self.ipr_mids[window_start]
                    else:
                        cum_move = 0.0

                    rally_detected = cum_move > IPR_FADE_TRIGGER
                    dip_detected = cum_move < -IPR_FADE_TRIGGER

                    # -- Asymmetric takes (position-aware, long-biased) --
                    if pos > IPR_AGGRESSION_THRESHOLD:
                        buy_thresh = fv_int + 1
                        sell_thresh = fv_int + 2
                    elif pos < -IPR_AGGRESSION_THRESHOLD:
                        buy_thresh = fv_int + IPR_BUY_SLACK
                        sell_thresh = fv_int + IPR_SELL_SLACK + 1
                    else:
                        buy_thresh = fv_int + IPR_BUY_SLACK
                        sell_thresh = fv_int + IPR_SELL_SLACK

                    for price, vol in sorted(book.sell_orders.items()):
                        if buy_cap > 0 and price <= buy_thresh:
                            qty = min(buy_cap, -vol)
                            orders.append(Order(IPR, price, qty))
                            buy_cap -= qty

                    for price, vol in sorted(book.buy_orders.items(), reverse=True):
                        if sell_cap > 0 and price >= sell_thresh:
                            qty = min(sell_cap, vol)
                            orders.append(Order(IPR, price, -qty))
                            sell_cap -= qty

                    # -- Posting: fade logic applied on top of regression FV --
                    if rally_detected:
                        # Forced reversion DOWN expected after strong rally
                        # Tight asks (sell into rally), wide bids (catch reversion)
                        if sell_cap > 0:
                            ap = max(fv_int + IPR_FADE_TIGHT, best_bid + 1)
                            ap = min(ap, best_ask)
                            orders.append(Order(IPR, ap, -sell_cap))
                        if buy_cap > 0:
                            bp = min(fv_int - IPR_FADE_WIDE, best_bid)
                            bp = max(bp, best_bid - IPR_FADE_WIDE)
                            orders.append(Order(IPR, bp, buy_cap))

                    elif dip_detected:
                        # Forced reversion UP expected after strong dip
                        # Tight bids (buy the dip), wide asks (wait for reversion)
                        if buy_cap > 0:
                            bp = min(fv_int - IPR_FADE_TIGHT, best_ask - 1)
                            bp = max(bp, best_bid)
                            orders.append(Order(IPR, bp, buy_cap))
                        if sell_cap > 0:
                            ap = max(fv_int + IPR_FADE_WIDE, best_ask)
                            ap = min(ap, best_ask + IPR_FADE_WIDE)
                            orders.append(Order(IPR, ap, -sell_cap))

                    else:
                        # No forced sequence — standard long-biased posting
                        if buy_cap > 0:
                            bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                            orders.append(Order(IPR, bp, buy_cap))
                        if sell_cap > 0:
                            ap = max(fv_int + 2, best_ask - 1, best_bid + 1)
                            orders.append(Order(IPR, ap, -sell_cap))

                else:
                    # One-sided book handling
                    if has_bids and not has_asks:
                        if buy_cap > 0:
                            orders.append(Order(IPR, best_bid + 1, buy_cap))
                        if sell_cap > 0:
                            orders.append(Order(IPR, best_bid + 14, -sell_cap))
                    elif has_asks and not has_bids:
                        if buy_cap > 0:
                            orders.append(Order(IPR, best_ask - 14, buy_cap))
                        if sell_cap > 0:
                            orders.append(Order(IPR, best_ask - 1, -sell_cap))

                result[IPR] = orders

        return result, conversions, json.dumps(
            {
                "mp": self.ipr_mp_hist[-60:],
                "m": self.ipr_mids[-60:],
                "tf": self.ipr_tf_hist,
                "l": self.aco_liq
            },
            separators=(",", ":")
        )
