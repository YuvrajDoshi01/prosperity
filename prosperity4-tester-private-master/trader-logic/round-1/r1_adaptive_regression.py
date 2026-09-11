import json
from datamodel import Order, TradingState

"""
r1_adaptive_regression — "Analyze. Calculate. Reanalyze. Recalculate." Strategy

Inspired by the mentor's chess engine metaphor:
  "Every data point is like a move on a chessboard."
  "Track those steps, analyze them over and over again."
  "Analyze. Calculate. Reanalyze. Recalculate. That is my favorite loop."

CORE INSIGHT:
  r1_medallion uses FIXED regression coefficients fitted OFFLINE on historical CSV.
  But the mentor explicitly says to RE-CALCULATE using AVAILABLE data.

  This strategy implements a ROLLING ONLINE REGRESSION that refits every tick:
  - Maintains a sliding window of (microprice, next_mid) pairs
  - Refits OLS coefficients on the live data every tick
  - Also tracks realized drift over the rolling window → explicit drift component

  The regression adapts to:
  1. Intraday regime shifts (price level changes with drift)
  2. Volatility clustering
  3. Any structural changes the mentor would "recalculate" for

STRATEGY:
  FV = adaptive_intercept + Σ(adaptive_coef_i × microprice_lag_i) + drift_rate × horizon

  Where adaptive_coef_i are refitted every tick on the last WINDOW_SIZE observations.

  IPR: Rolling regression FV + OBI shift + adaptive drift bias
  ACO: Identical to r1_medallion (stable, proven)

Why this differs from r1_medallion:
  - r1_medallion: fixed coefs [0.2474, 0.2529, 0.2412, 0.2585] from offline calibration
  - This: coefs refit ONLINE every tick from last 100 ticks of live data
  - Intercept adapts to current price level (automatically tracks drift)
  - Explicit drift rate estimation: measures ticks/price over rolling window
  - No trade flow signal (reduces feedback loop risk)

MATH:
  Online OLS using normal equations on window of size W:
    X = [[1, mp[t-4], mp[t-3], mp[t-2], mp[t-1]] for t in window]
    y = [mid[t] for t in window]
    coefs = (X^T X)^-1 X^T y

  Using incremental Gram matrix update for efficiency:
    XTX += x_new @ x_new.T - x_old @ x_old.T  (rank-2 update)

  Drift rate estimation:
    drift_per_tick = (mid[-1] - mid[-DRIFT_WINDOW]) / DRIFT_WINDOW
    FV += drift_per_tick * DRIFT_HORIZON
"""

# ═══ INTARIAN_PEPPER_ROOT CONFIG ═══
IPR = "INTARIAN_PEPPER_ROOT"
IPR_LIMIT = 80
IPR_LAGS = 4
IPR_REG_WINDOW = 100          # Refit regression on last 100 observations
IPR_REG_WARMUP = 20           # Minimum ticks before using regression (fallback to microprice)
IPR_OBI_SHIFT = 0.5
IPR_DRIFT_WINDOW = 50         # Estimate drift rate from last 50 ticks
IPR_DRIFT_HORIZON = 1         # Predict 1 tick ahead with drift
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3
IPR_AGGRESSION_THRESHOLD = 60
IPR_FALLBACK_DRIFT_BIAS = 5.0  # Fallback before regression warms up

# ═══ ASH_COATED_OSMIUM CONFIG ═══
ACO = "ASH_COATED_OSMIUM"
ACO_LIMIT = 80
ACO_FV = 10000
ACO_AGGRESSION_THRESHOLD = 40
ACO_LIQUIDATION_WINDOW = 10


def _solve_ols(X, y):
    """
    Solve OLS: coefs = (X^T X)^-1 X^T y
    X: list of row vectors (each row = [1, lag1, lag2, lag3, lag4])
    y: list of target values
    Returns coefficient vector or None if singular.
    """
    n = len(X[0])
    # Accumulate X^T X and X^T y
    XTX = [[0.0] * n for _ in range(n)]
    XTy = [0.0] * n
    for row, target in zip(X, y):
        for i in range(n):
            XTy[i] += row[i] * target
            for j in range(n):
                XTX[i][j] += row[i] * row[j]

    # Gaussian elimination with partial pivoting
    aug = [XTX[i][:] + [XTy[i]] for i in range(n)]
    for col in range(n):
        # Find pivot
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        if abs(aug[col][col]) < 1e-10:
            return None
        # Eliminate
        for row in range(n):
            if row != col:
                factor = aug[row][col] / aug[col][col]
                for k in range(n + 1):
                    aug[row][k] -= factor * aug[col][k]
    coefs = [aug[i][n] / aug[i][i] for i in range(n)]
    return coefs


class Trader:
    def __init__(self):
        # Rolling data for regression
        self.ipr_mp_hist = []     # Microprice history (for lag features)
        self.ipr_mid_hist = []    # Mid history (for regression targets + drift)
        self.ipr_reg_coefs = None # Current fitted coefficients [intercept, c1, c2, c3, c4]
        self.aco_liq = []

    def bid(self):
        return 15

    def _refit_regression(self):
        """
        Refit OLS on the rolling window.
        Feature: [1, mp[t-4], mp[t-3], mp[t-2], mp[t-1]]
        Target: mid[t]
        """
        mp = self.ipr_mp_hist
        mid = self.ipr_mid_hist
        n_lags = IPR_LAGS

        # Need at least warmup + lags observations
        if len(mp) < IPR_REG_WARMUP + n_lags:
            return None

        # Build dataset from rolling window
        window_end = len(mid)
        window_start = max(n_lags, window_end - IPR_REG_WINDOW)

        X_rows = []
        y_vals = []
        for t in range(window_start, window_end):
            if t < n_lags:
                continue
            # Feature: [1, mp[t-4], mp[t-3], mp[t-2], mp[t-1]]
            row = [1.0] + [mp[t - n_lags + lag] for lag in range(n_lags)]
            X_rows.append(row)
            y_vals.append(mid[t])

        if len(X_rows) < IPR_REG_WARMUP:
            return None

        return _solve_ols(X_rows, y_vals)

    def _estimate_drift(self):
        """
        Estimate current drift rate (price change per tick) over recent window.
        Returns drift per tick.
        """
        mid = self.ipr_mid_hist
        if len(mid) < IPR_DRIFT_WINDOW:
            return 0.1  # Default: ~+100/1000 ticks
        recent = mid[-IPR_DRIFT_WINDOW:]
        drift_total = recent[-1] - recent[0]
        return drift_total / len(recent)

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.ipr_mp_hist = saved.get("mp", [])
            self.ipr_mid_hist = saved.get("md", [])
            self.ipr_reg_coefs = saved.get("rc")
            self.aco_liq = saved.get("l", [])

        result = {}
        conversions = 0

        # ═══════════════════════════════════════════════════
        # ASH_COATED_OSMIUM — identical to r1_medallion (proven)
        # ═══════════════════════════════════════════════════
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

        # ═══════════════════════════════════════════════════
        # INTARIAN_PEPPER_ROOT — Adaptive Online Regression
        # ═══════════════════════════════════════════════════
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

                    # ── Compute microprice + OBI ──
                    total_bv = sum(book.buy_orders.values())
                    total_av = sum(-v for v in book.sell_orders.values())
                    if total_bv + total_av > 0:
                        mp = best_bid + (total_bv / (total_bv + total_av)) * (best_ask - best_bid)
                        obi = (total_bv - total_av) / (total_bv + total_av)
                    else:
                        mp = mid
                        obi = 0.0

                    # ── Update rolling history ──
                    self.ipr_mp_hist.append(mp)
                    self.ipr_mid_hist.append(mid)
                    # Keep only what's needed (window + lags)
                    max_keep = IPR_REG_WINDOW + IPR_LAGS + 5
                    if len(self.ipr_mp_hist) > max_keep:
                        self.ipr_mp_hist = self.ipr_mp_hist[-max_keep:]
                        self.ipr_mid_hist = self.ipr_mid_hist[-max_keep:]

                    # ── Refit regression every tick (the "recalculate" loop) ──
                    new_coefs = self._refit_regression()
                    if new_coefs is not None:
                        self.ipr_reg_coefs = new_coefs

                    # ── Compute adaptive FV ──
                    if (self.ipr_reg_coefs is not None
                            and len(self.ipr_mp_hist) >= IPR_LAGS):
                        # Regression prediction from live-fitted coefficients
                        lags = self.ipr_mp_hist[-IPR_LAGS:]
                        fv = self.ipr_reg_coefs[0]  # intercept
                        for i, lag_val in enumerate(lags):
                            fv += self.ipr_reg_coefs[i + 1] * lag_val

                        # Adaptive drift: add estimated drift for 1 tick ahead
                        drift_rate = self._estimate_drift()
                        fv += drift_rate * IPR_DRIFT_HORIZON

                    else:
                        # Warmup fallback: microprice + fixed drift bias
                        fv = mp + IPR_FALLBACK_DRIFT_BIAS

                    # OBI nudge (volume imbalance, small weight)
                    fv += obi * IPR_OBI_SHIFT

                    fv_int = round(fv)

                    # ── Asymmetric takes (always long-biased) ──
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

                    # ── Posting: long-biased, wide ask ──
                    if buy_cap > 0:
                        bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                        orders.append(Order(IPR, bp, buy_cap))
                    if sell_cap > 0:
                        # Extra wide ask: adaptive regression FV already includes drift
                        # so we post at FV+2 minimum to stay long
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
                "mp": self.ipr_mp_hist[-60:],   # Keep last 60 to stay under 50k char
                "md": self.ipr_mid_hist[-60:],
                "rc": self.ipr_reg_coefs,
                "l": self.aco_liq
            },
            separators=(",", ":")
        )
