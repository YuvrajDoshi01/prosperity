"""r3_v2.py — v1 + IV surface z-score trading layer.

Additions over v1:
  - Compute Black-Scholes IV per tradeable strike each tick.
  - Fit quadratic smile IV(m) across strikes where m = log(K/spot)/sqrt(TTE).
  - Compute residuals = IV_K - IV_fit(m_K) and track rolling stdev per strike.
  - On |z_K| > Z_THRESHOLD, override v1 MM with directional take-and-post:
      * z > +thresh: IV too high -> voucher overpriced -> sell at fair.
      * z < -thresh: IV too low  -> voucher underpriced -> buy at fair.

TTE config: TTE_DAYS_AT_START is the TTE (in days) at tick 0 of the current day.
  Submission day = 5. Historical BT: day 0 -> 8, day 1 -> 7, day 2 -> 6.
"""
import json
import os
from math import log, sqrt
from statistics import NormalDist

from datamodel import Order, TradingState

_nd = NormalDist()

# Products
HYDROGEL = "HYDROGEL_PACK"
VEVE = "VELVETFRUIT_EXTRACT"
LIMIT_D1 = 200
LIMIT_V = 300

STRIKES_TRADEABLE = [5000, 5100, 5200, 5300, 5400]
STRIKES_INTR = [4000, 4500]
SYM = {k: f"VEV_{k}" for k in STRIKES_TRADEABLE + STRIKES_INTR}

# TTE: auto-detected from backtester env vars (PROSPERITY4BT_{ROUND,DAY}), falling
# back to TTE_DAYS_AT_START for submission. R3 historical: day 0=8, day 1=7, day 2=6.
# Submission day = 5.
TTE_DAYS_AT_START = 5.0  # submission default
TTE_YEAR_LEN = 250.0


def _tte_days_at_start():
    try:
        r = int(os.environ.get("PROSPERITY4BT_ROUND", "-1"))
        d = int(os.environ.get("PROSPERITY4BT_DAY", "-1"))
        if r == 3 and 0 <= d <= 2:
            return 8.0 - d
    except (ValueError, TypeError):
        pass
    return TTE_DAYS_AT_START

# IV surface z-score trading
IV_WINDOW = 200             # rolling window per strike for residual stdev
IV_Z_THRESHOLD = 3.0        # |z| > threshold to trigger trade (raised to reduce noise-trading)
IV_MIN_HIST = 30            # min ticks before trusting z-score
IV_POS_CAP = 60             # max position per strike from IV trades
IV_TAKE_ORDER_SIZE = 20     # size for aggressive takes on outliers
IV_PASSIVE_SIZE = 10        # size for passive posts on outliers

# Intrinsic arbitrage (unchanged)
INTRINSIC_EDGE = 2
INTRINSIC_QTY = 50

# Voucher MM (fallback when no IV signal)
VOUCHER_MM_SIZE = 20
VOUCHER_MIN_SPREAD = 2

# Delta-1 MM
POST_SLACK = 1


def bs_call(spot, strike, tte, vol):
    if tte <= 0 or vol <= 0:
        return max(spot - strike, 0.0)
    d1 = (log(spot / strike) + 0.5 * vol * vol * tte) / (vol * sqrt(tte))
    d2 = d1 - vol * sqrt(tte)
    return spot * _nd.cdf(d1) - strike * _nd.cdf(d2)


def implied_vol(market_price, spot, strike, tte, lo=0.001, hi=3.0):
    intrinsic = max(spot - strike, 0.0)
    if market_price <= intrinsic:
        return lo
    if market_price >= spot:
        return hi
    for _ in range(50):
        m = 0.5 * (lo + hi)
        if bs_call(spot, strike, tte, m) < market_price:
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


def plain_mid(od):
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    return 0.5 * (max(od.buy_orders) + min(od.sell_orders))


def fit_quadratic(xs, ys):
    """Least-squares quadratic y = a*x^2 + b*x + c. Returns (a, b, c) or None if singular."""
    n = len(xs)
    if n < 3:
        return None
    s1 = n
    sx = sum(xs)
    sxx = sum(x * x for x in xs)
    sxxx = sum(x ** 3 for x in xs)
    sxxxx = sum(x ** 4 for x in xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxxy = sum(x * x * y for x, y in zip(xs, ys))
    # Normal equations:
    # [sxxxx sxxx sxx][a]   [sxxy]
    # [sxxx  sxx  sx ][b] = [sxy ]
    # [sxx   sx   s1 ][c]   [sy  ]
    m = [[sxxxx, sxxx, sxx], [sxxx, sxx, sx], [sxx, sx, s1]]
    b = [sxxy, sxy, sy]
    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
           - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    if abs(det) < 1e-15:
        return None
    coefs = []
    for col in range(3):
        mi = [row[:] for row in m]
        for r in range(3):
            mi[r][col] = b[r]
        d_i = (mi[0][0] * (mi[1][1] * mi[2][2] - mi[1][2] * mi[2][1])
               - mi[0][1] * (mi[1][0] * mi[2][2] - mi[1][2] * mi[2][0])
               + mi[0][2] * (mi[1][0] * mi[2][1] - mi[1][1] * mi[2][0]))
        coefs.append(d_i / det)
    return tuple(coefs)


class Trader:
    def __init__(self):
        self.resid_hist = {}  # {strike: [residuals over last IV_WINDOW ticks]}

    def bid(self):
        return 800

    def _tte(self, timestamp):
        d = _tte_days_at_start() - timestamp / 1_000_000.0
        return max(d, 0.01) / TTE_YEAR_LEN

    def _mm_delta1(self, state, product, limit):
        od = state.order_depths.get(product)
        mp = plain_mid(od)
        if mp is None:
            return []
        bb, ba = max(od.buy_orders), min(od.sell_orders)
        pos = state.position.get(product, 0)
        fv = round(mp)
        tb, ts = limit - pos, limit + pos
        half = limit * 0.5
        mbp = fv - 1 if pos > half else fv
        msp = fv + 1 if pos < -half else fv
        result = []
        for p, v in sorted(od.sell_orders.items()):
            if tb > 0 and p <= mbp:
                q = min(tb, -v); result.append(Order(product, p, q)); tb -= q
        for p, v in sorted(od.buy_orders.items(), reverse=True):
            if ts > 0 and p >= msp:
                q = min(ts, v); result.append(Order(product, p, -q)); ts -= q
        if tb > 0:
            result.append(Order(product, min(fv - POST_SLACK, bb + 1), tb))
        if ts > 0:
            result.append(Order(product, max(fv + POST_SLACK, ba - 1), -ts))
        return result

    def _voucher_mm(self, state, strike):
        product = SYM[strike]
        od = state.order_depths.get(product)
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        vbb, vba = max(od.buy_orders), min(od.sell_orders)
        if vba - vbb < VOUCHER_MIN_SPREAD:
            return []
        pos = state.position.get(product, 0)
        tb, ts = LIMIT_V - pos, LIMIT_V + pos
        result = []
        if tb > 0:
            result.append(Order(product, vbb + 1, min(tb, VOUCHER_MM_SIZE)))
        if ts > 0:
            result.append(Order(product, vba - 1, -min(ts, VOUCHER_MM_SIZE)))
        return result

    def _intrinsic_arb(self, state, strike, spot):
        product = SYM[strike]
        od = state.order_depths.get(product)
        if od is None:
            return []
        pos = state.position.get(product, 0)
        tb, ts = LIMIT_V - pos, LIMIT_V + pos
        intrinsic = max(spot - strike, 0.0)
        result = []
        for p, v in sorted(od.sell_orders.items()):
            if tb > 0 and p < intrinsic - INTRINSIC_EDGE:
                q = min(tb, -v, INTRINSIC_QTY); result.append(Order(product, p, q)); tb -= q
        for p, v in sorted(od.buy_orders.items(), reverse=True):
            if ts > 0 and p > intrinsic + INTRINSIC_EDGE:
                q = min(ts, v, INTRINSIC_QTY); result.append(Order(product, p, -q)); ts -= q
        return result

    def _iv_signal(self, state, spot, tte):
        """Return dict{strike: (iv, z_score, smile_iv, market_mid)} or empty if not enough data."""
        ivs = {}
        moneyness = {}
        for K in STRIKES_TRADEABLE:
            od = state.order_depths.get(SYM[K])
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            vmid = 0.5 * (max(od.buy_orders) + min(od.sell_orders))
            if vmid <= max(spot - K, 0) + 1e-3 or vmid >= spot:
                continue
            iv = implied_vol(vmid, spot, K, tte)
            ivs[K] = (iv, vmid)
            moneyness[K] = log(K / spot) / sqrt(tte)
        if len(ivs) < 3:
            return {}
        # Fit quadratic smile
        xs = [moneyness[K] for K in ivs]
        ys = [ivs[K][0] for K in ivs]
        coefs = fit_quadratic(xs, ys)
        if coefs is None:
            return {}
        a, b, c = coefs
        out = {}
        for K, (iv, vmid) in ivs.items():
            m = moneyness[K]
            smile_iv = a * m * m + b * m + c
            resid = iv - smile_iv
            hist = self.resid_hist.setdefault(K, [])
            hist.append(round(resid, 6))
            if len(hist) > IV_WINDOW:
                del hist[:len(hist) - IV_WINDOW]
            if len(hist) < IV_MIN_HIST:
                out[K] = (iv, 0.0, smile_iv, vmid)
                continue
            # Rolling stdev
            mu = sum(hist) / len(hist)
            var = sum((r - mu) ** 2 for r in hist) / len(hist)
            stdev = sqrt(max(var, 1e-12))
            z = (resid - mu) / stdev
            out[K] = (iv, z, smile_iv, vmid)
        return out

    def _iv_trade(self, state, strike, spot, tte, smile_iv, z, vmid):
        """Emit aggressive orders when |z| > threshold. Falls back to MM otherwise."""
        product = SYM[strike]
        od = state.order_depths.get(product)
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        vbb, vba = max(od.buy_orders), min(od.sell_orders)
        pos = state.position.get(product, 0)
        fair = bs_call(spot, strike, tte, smile_iv)
        fair_r = round(fair)
        tb, ts = LIMIT_V - pos, LIMIT_V + pos
        # Apply position cap specifically for IV-driven positions
        tb = min(tb, IV_POS_CAP - max(pos, 0))
        ts = min(ts, IV_POS_CAP + min(pos, 0))
        result = []
        if z > IV_Z_THRESHOLD and ts > 0:
            # overpriced: take any bid >= fair, then post ask slightly above fair
            for p, v in sorted(od.buy_orders.items(), reverse=True):
                if ts > 0 and p >= fair_r:
                    q = min(ts, v, IV_TAKE_ORDER_SIZE)
                    result.append(Order(product, p, -q)); ts -= q
            if ts > 0:
                result.append(Order(product, max(fair_r + 1, vbb + 1), -min(ts, IV_PASSIVE_SIZE)))
        elif z < -IV_Z_THRESHOLD and tb > 0:
            # underpriced: take any ask <= fair, then post bid slightly below
            for p, v in sorted(od.sell_orders.items()):
                if tb > 0 and p <= fair_r:
                    q = min(tb, -v, IV_TAKE_ORDER_SIZE)
                    result.append(Order(product, p, q)); tb -= q
            if tb > 0:
                result.append(Order(product, min(fair_r - 1, vba - 1), min(tb, IV_PASSIVE_SIZE)))
        else:
            # no signal: fall back to v1 voucher MM
            return self._voucher_mm(state, strike)
        return result

    def _serialize(self):
        return json.dumps({
            "rh": {str(k): v for k, v in self.resid_hist.items()},
        }, separators=(",", ":"))

    def run(self, state: TradingState):
        if state.traderData:
            try:
                td = json.loads(state.traderData)
                self.resid_hist = {int(k): v for k, v in td.get("rh", {}).items()}
            except (json.JSONDecodeError, ValueError):
                self.resid_hist = {}

        orders = {}

        ho = self._mm_delta1(state, HYDROGEL, LIMIT_D1)
        if ho: orders[HYDROGEL] = ho
        vo = self._mm_delta1(state, VEVE, LIMIT_D1)
        if vo: orders[VEVE] = vo

        spot = plain_mid(state.order_depths.get(VEVE))
        if spot is None:
            return orders, 0, self._serialize()

        tte = self._tte(state.timestamp)

        for K in STRIKES_INTR:
            r = self._intrinsic_arb(state, K, spot)
            if r: orders[SYM[K]] = r

        signal = self._iv_signal(state, spot, tte)
        for K in STRIKES_TRADEABLE:
            if K in signal:
                iv, z, smile_iv, vmid = signal[K]
                r = self._iv_trade(state, K, spot, tte, smile_iv, z, vmid)
            else:
                r = self._voucher_mm(state, K)
            if r:
                orders[SYM[K]] = r

        return orders, 0, self._serialize()
