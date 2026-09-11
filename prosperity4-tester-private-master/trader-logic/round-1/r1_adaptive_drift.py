import json
from datamodel import Order, TradingState

"""
r1_adaptive_drift — "Analyze. Calculate. Reanalyze. Recalculate." (Fixed)

Improved from r1_adaptive_regression based on advisor hint analysis:

  The mentor says "Recalculate" — but WHAT to recalculate matters.
  - Online OLS refitting the INTERCEPT is CATASTROPHIC on the website
    (s15_adaptive_reg: 2,495; s42_refit: ~2,400 — inverted BT gap)
  - The intercept encodes CSV volume distribution via microprice, which
    differs 98.5% from website volumes in Round 1

  The correct interpretation of "Recalculate":
    - FIXED structural coefficients (cross-validated, stable across 3 days)
    - ROLLING drift rate estimation (pure price-level arithmetic, volume-independent)
    - "Commit to the pattern" (mentor hint) = lock in the structural parameters
    - "Reanalyze. Recalculate." = update WHERE you are on the board (drift), not the board's rules (coefs)

CHANGES FROM r1_adaptive_regression:
  1. REMOVED: _solve_ols(), _refit_regression() — the poison
  2. KEPT: _estimate_drift() — volume-independent, safe
  3. ADDED: Fixed cross-validated coefs from r1_medallion [0.2474, 0.2529, 0.2412, 0.2585]
  4. ADDED: Trade flow signal (coef=1.5, window=5, norm=15) — proven in r1_medallion
  5. ADDED: Position-dependent aggression at |pos| > 40
  6. FV = fixed_intercept + sum(coef_i * mp[t-i]) + drift_rate * HORIZON + OBI + trade_flow

  The "adaptive" part is now ONLY the drift rate — the one thing the mentor
  actually wants you to recalculate as the game unfolds.
"""

# === INTARIAN_PEPPER_ROOT CONFIG ===
IPR = "INTARIAN_PEPPER_ROOT"
IPR_LIMIT = 80
IPR_LAGS = 4

# Fixed cross-validated coefficients (stable across all 3 CSV days)
# Coef sum ~1.0 -> FV ~ average of last 4 microprice values + intercept
IPR_FIXED_COEFS = [0.2474, 0.2529, 0.2412, 0.2585]
IPR_FIXED_INTERCEPT = 0.2078

# Drift estimation (the ONLY adaptive component — volume-independent)
IPR_DRIFT_WINDOW = 50         # Estimate drift from last 50 mids
IPR_DRIFT_HORIZON = 5         # "Further ahead" per Orin's hint (was 1, now 5)

# OBI shift
IPR_OBI_SHIFT = 0.5

# Trade flow signal (from r1_medallion, proven)
IPR_TF_COEF = 1.5
IPR_TF_WINDOW = 5
IPR_TF_NORM = 15.0

# Order placement
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3
IPR_AGGRESSION_THRESHOLD = 40  # Position aggression threshold

# === ASH_COATED_OSMIUM CONFIG ===
ACO = "ASH_COATED_OSMIUM"
ACO_LIMIT = 80
ACO_FV = 10000
ACO_AGGRESSION_THRESHOLD = 40
ACO_LIQUIDATION_WINDOW = 10


class Trader:
    def __init__(self):
        self.ipr_mp_hist = []     # Microprice history (for lag features)
        self.ipr_mid_hist = []    # Mid history (for drift estimation)
        self.ipr_tf_hist = []     # Trade flow: signed trade sizes
        self.aco_liq = []

    def bid(self):
        return 15

    def _estimate_drift(self):
        """
        The ONLY "recalculate" — rolling drift rate from pure mid prices.
        Volume-independent. Safe for website.
        """
        mid = self.ipr_mid_hist
        if len(mid) < IPR_DRIFT_WINDOW:
            return 0.1  # Default: ~+1000/10000 ticks
        recent = mid[-IPR_DRIFT_WINDOW:]
        return (recent[-1] - recent[0]) / len(recent)

    def _compute_trade_flow(self, state):
        """
        Trade flow signal from recent market trades.
        Positive = net buying pressure, negative = net selling.
        """
        trades = state.market_trades.get(IPR, [])
        signed = 0.0
        for t in trades:
            # Buyer-initiated = positive, seller-initiated = negative
            signed += t.quantity  # Already signed by convention
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
            self.ipr_mid_hist = saved.get("md", [])
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
        # INTARIAN_PEPPER_ROOT — Fixed Regression + Rolling Drift
        # "Commit to the pattern. Recalculate the position."
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

                    # -- Update rolling history --
                    self.ipr_mp_hist.append(mp)
                    self.ipr_mid_hist.append(mid)
                    max_keep = IPR_DRIFT_WINDOW + IPR_LAGS + 10
                    if len(self.ipr_mp_hist) > max_keep:
                        self.ipr_mp_hist = self.ipr_mp_hist[-max_keep:]
                        self.ipr_mid_hist = self.ipr_mid_hist[-max_keep:]

                    # -- FIXED regression FV (cross-validated coefs, NEVER refitted) --
                    if len(self.ipr_mp_hist) >= IPR_LAGS:
                        lags = self.ipr_mp_hist[-IPR_LAGS:]
                        fv = IPR_FIXED_INTERCEPT
                        for i, lag_val in enumerate(lags):
                            fv += IPR_FIXED_COEFS[i] * lag_val
                    else:
                        fv = mp  # Warmup fallback

                    # -- Rolling drift: the ONLY "recalculate" --
                    # "Slow-growing goods reveal their direction gradually...
                    #  easier to reason about in the near future, and further ahead."
                    drift_rate = self._estimate_drift()
                    fv += drift_rate * IPR_DRIFT_HORIZON

                    # -- OBI nudge --
                    fv += obi * IPR_OBI_SHIFT

                    # -- Trade flow signal (proven in r1_medallion) --
                    tf_signal = self._compute_trade_flow(state)
                    fv += tf_signal

                    fv_int = round(fv)

                    # -- Position-dependent aggression --
                    if pos > IPR_AGGRESSION_THRESHOLD:
                        # Long and heavy: tighter sells, wider buys
                        buy_thresh = fv_int + 1
                        sell_thresh = fv_int + 2
                    elif pos < -IPR_AGGRESSION_THRESHOLD:
                        # Short and heavy: tighter buys, wider sells
                        buy_thresh = fv_int + IPR_BUY_SLACK
                        sell_thresh = fv_int + IPR_SELL_SLACK + 1
                    else:
                        buy_thresh = fv_int + IPR_BUY_SLACK
                        sell_thresh = fv_int + IPR_SELL_SLACK

                    # -- Asymmetric takes (long-biased) --
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

                    # -- Posting: long-biased --
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
                "md": self.ipr_mid_hist[-60:],
                "tf": self.ipr_tf_hist,
                "l": self.aco_liq
            },
            separators=(",", ":")
        )
