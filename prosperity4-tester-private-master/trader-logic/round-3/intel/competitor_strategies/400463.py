"""r3_v8.py — v7 + competitor's BS voucher MM (FIXED sigma) + delta hedge.

V8.1 — BS voucher trading (from competitor 392245.py — thedarkmarc):
  Price each tradeable strike via BS with FIXED sigma=0.20 (matches our
  EDA mean IV across days). Their version used realized vol which failed
  on days 1-2 (-$9.7k, -$2.3k) but worked day 0 ($8.4k 1k-tick). Fixed
  sigma should generalize across all days.
  Buy at ask if ask <= BS_fair - 1.6 (edge in price units).
  Sell at bid if bid >= BS_fair + 1.6.

V8.2 — Delta hedge into VFE (passive entry):
  Sum delta-weighted voucher positions. Target VFE = -portfolio_delta.
  Hedge passively by posting at touch (not crossing).

Keeps v7's:
  - Wall Mid for VFE MM
  - Plain mid for HYDROGEL_PACK MM
  - Intrinsic arb on 4000/4500 (loose) + others (strict)
  - Call-spread arb scanner
  - IV smile DISABLED (kept code for future)
""""""r3_v7.py — v3 + Wall Mid + vega-weighted IV smile (P3-winners playbook).

Based on past IMC champion strategies (playbook Section 4 + 10):

V7.1 — WALL MID for fair value (every 2nd-place team across P1/P2/P3 used this):
  Wall Mid = midpoint of HIGHEST-VOLUME bid/ask levels (not best±).
  Tracks IMC's hidden fair value (used for liquidation) far more accurately.
  Frankfurt Hedgehogs earned +39k on RAINFOREST_RESIN alone by using it.

V7.2 — IV smile mean-reversion with VEGA-WEIGHTED z-score (Martin Oravec, P3):
  z = (iv_strike - rolling_mean_iv) / (std_iv × vega)
  Entry: |z| > 1.0
  Window: 150 ticks per strike (CMU Physics finding — quadratic broke; per-strike
    rolling mean was better)
  No global smile fit — just per-strike mean (simpler, more robust).

V7.3 — keep v3's intrinsic arb on 4000/4500 + call-spread scanner.

Past v2 IV smile FAILED because:
- Absolute IV thresholds (0.005-0.01) — should be vega-weighted z-scores
- 100-tick window — too short for level signal
- Quadratic smile fit broke (CMU Physics finding) — per-strike rolling mean simpler
"""
import itertools
import math
from collections import deque
from statistics import NormalDist, mean, stdev

from datamodel import Order, TradingState

_ND = NormalDist()

HYDROGEL = "HYDROGEL_PACK"
VEVE = "VELVETFRUIT_EXTRACT"
LIMIT_D1 = 200
LIMIT_V = 300

STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
STRIKES_IV = [5000, 5100, 5200, 5300, 5400]
STRIKES_TRADEABLE = [5000, 5100, 5200, 5300, 5400]
STRIKES_DEEP_ITM = [4000, 4500]
SYM = {k: f"VEV_{k}" for k in STRIKES_ALL}

# TTE
TTE_DAYS_AT_START = 5.0
TTE_YEAR = 250.0

# Intrinsic arb
INTRINSIC_EDGE = 2
INTRINSIC_QTY = 50

# Call-spread arb (insurance)
ARB_SIZE = 10

# Voucher MM
VOUCHER_MM_SIZE = 20
VOUCHER_MIN_SPREAD = 2

# Delta-1 MM
POST_SLACK_HP = 1
POST_SLACK_VE = 1

# IV mean-reversion (V7.2 — disabled in v8)
IV_WINDOW = 150
IV_Z_ENTRY = 1.0
IV_Z_EXIT = 0.3
IV_MIN_HIST = 30
IV_POS_CAP = 100
IV_TRADE_SIZE = 30

# V8.1 — BS voucher MM (FIXED sigma, edge-based)
BS_SIGMA = 0.20               # matches EDA mean IV across all 3 days
BS_EDGE = 1.6                 # ticks of edge required to trade (competitor's value)
BS_TRADE_SIZE = 50            # max size per trigger
BS_STRIKES = [5000, 5100, 5200, 5300, 5400]  # liquid strikes only

# V8.2 — Delta hedge
HEDGE_THRESHOLD = 30          # only hedge if |portfolio_delta| > threshold


def bs_call(spot, K, T, vol):
    if T <= 0 or vol <= 0:
        return max(spot - K, 0.0)
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    return spot * _ND.cdf(d1) - K * _ND.cdf(d2)


def bs_delta(spot, K, T, vol):
    if T <= 0 or vol <= 0:
        return 1.0 if spot > K else 0.0
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    return _ND.cdf(d1)


def bs_vega(spot, K, T, vol):
    if T <= 0 or vol <= 0:
        return 0.0
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    return spot * math.sqrt(T) * _ND.pdf(d1)


def implied_vol(mkt, spot, K, T, lo=1e-4, hi=5.0):
    intr = max(spot - K, 0.0)
    if mkt <= intr + 1e-6 or T <= 0 or mkt >= spot:
        return None
    for _ in range(50):
        m = 0.5 * (lo + hi)
        if bs_call(spot, K, T, m) < mkt:
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


def wall_mid(od):
    """V7.1 — Wall Mid: midpoint of highest-volume bid/ask levels.

    From jmerle's reference impl + Linear Utility (P2 #2):
      popular_buy_price  = max(buy_orders, key=lambda x: x[1])
      popular_sell_price = min(sell_orders, key=lambda x: x[1])  # sell vols are negative
      true_value = round((popular_buy + popular_sell) / 2)
    """
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    pop_bid = max(od.buy_orders.items(), key=lambda kv: kv[1])[0]
    pop_ask = min(od.sell_orders.items(), key=lambda kv: kv[1])[0]  # most negative = largest size
    return 0.5 * (pop_bid + pop_ask)


def best_mid(od):
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    return 0.5 * (max(od.buy_orders) + min(od.sell_orders))


class Trader:
    def __init__(self):
        self.iv_history = {k: deque(maxlen=IV_WINDOW) for k in STRIKES_IV}
        self.last_spot = None
        self.spot_age = 0

    def bid(self):
        return 800

    def _tte(self, ts):
        d = TTE_DAYS_AT_START - ts / 1_000_000.0
        return max(d, 0.01) / TTE_YEAR

    def _get_spot(self, state):
        od = state.order_depths.get(VEVE)
        # Use wall mid for spot — that's the truer fair
        wm = wall_mid(od)
        if wm is not None:
            self.last_spot = wm
            self.spot_age = 0
            return wm
        bm = best_mid(od)
        if bm is not None:
            self.last_spot = bm
            self.spot_age = 0
            return bm
        self.spot_age += 1
        if self.spot_age < 20 and self.last_spot is not None:
            return self.last_spot
        return None

    def _mm_delta1(self, state, product, limit, slack, use_wall_mid=True):
        od = state.order_depths.get(product)
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        # V7.1: Wall Mid as fair value (configurable per product)
        if use_wall_mid:
            wm = wall_mid(od)
            if wm is None:
                return []
        else:
            wm = best_mid(od)
            if wm is None:
                return []
        bb, ba = max(od.buy_orders), min(od.sell_orders)
        pos = state.position.get(product, 0)
        fv = round(wm)
        tb, ts = limit - pos, limit + pos
        half = limit * 0.5
        mbp = fv - 1 if pos > half else fv
        msp = fv + 1 if pos < -half else fv
        result = []
        for p, v in sorted(od.sell_orders.items()):
            if tb > 0 and p <= mbp:
                q = min(tb, -v)
                result.append(Order(product, p, q)); tb -= q
        for p, v in sorted(od.buy_orders.items(), reverse=True):
            if ts > 0 and p >= msp:
                q = min(ts, v)
                result.append(Order(product, p, -q)); ts -= q
        if tb > 0:
            result.append(Order(product, min(fv - slack, bb + 1), tb))
        if ts > 0:
            result.append(Order(product, max(fv + slack, ba - 1), -ts))
        return result

    def _voucher_mm(self, state, strike, existing_orders):
        product = SYM[strike]
        od = state.order_depths.get(product)
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        vbb, vba = max(od.buy_orders), min(od.sell_orders)
        if vba - vbb < VOUCHER_MIN_SPREAD:
            return []
        pos = state.position.get(product, 0)
        existing_buy = sum(o.quantity for o in existing_orders if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing_orders if o.quantity < 0)
        tb = LIMIT_V - pos - existing_buy
        ts = LIMIT_V + pos - existing_sell
        result = []
        if tb > 0:
            result.append(Order(product, vbb + 1, min(tb, VOUCHER_MM_SIZE)))
        if ts > 0:
            result.append(Order(product, vba - 1, -min(ts, VOUCHER_MM_SIZE)))
        return result

    def _intrinsic_arb(self, state, strike, spot, existing_orders, deep_itm):
        product = SYM[strike]
        od = state.order_depths.get(product)
        if od is None:
            return []
        pos = state.position.get(product, 0)
        already_buy = sum(o.quantity for o in existing_orders if o.quantity > 0)
        already_sell = sum(-o.quantity for o in existing_orders if o.quantity < 0)
        tb = LIMIT_V - pos - already_buy
        ts = LIMIT_V + pos - already_sell
        intrinsic = max(spot - strike, 0.0)
        result = []
        for p, v in sorted(od.sell_orders.items()):
            if tb > 0 and p < intrinsic - INTRINSIC_EDGE:
                q = min(tb, -v, INTRINSIC_QTY)
                result.append(Order(product, p, q)); tb -= q
        sell_thr = intrinsic + INTRINSIC_EDGE if deep_itm else spot + INTRINSIC_EDGE
        for p, v in sorted(od.buy_orders.items(), reverse=True):
            if ts > 0 and p > sell_thr:
                q = min(ts, v, INTRINSIC_QTY)
                result.append(Order(product, p, -q)); ts -= q
        return result

    def _iv_signal_trade(self, state, strike, spot, T, orders_so_far):
        """V7.2 — vega-weighted z-score IV mean reversion (Martin Oravec / CMU Physics)."""
        product = SYM[strike]
        od = state.order_depths.get(product)
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        # Use wall mid for IV computation (more accurate fair price)
        wm = wall_mid(od)
        if wm is None:
            return []
        iv = implied_vol(wm, spot, strike, T)
        if iv is None:
            return []
        hist = self.iv_history[strike]
        hist.append(iv)
        if len(hist) < IV_MIN_HIST:
            return []
        rolling_mean = mean(hist)
        rolling_std = stdev(hist) if len(hist) > 1 else 0.0
        if rolling_std < 1e-5:
            return []
        vega = bs_vega(spot, strike, T, rolling_mean)
        if vega < 1e-3:
            return []
        # Vega-weighted z-score: deviation in option-price units, scaled
        deviation = iv - rolling_mean
        z = deviation / (rolling_std * vega)  # Note: rolling_std * vega = price-space std
        # Actually Martin Oravec's formula is `deviation / (std_IV × vega)` — gives z in $price space
        # We want |z| > IV_Z_ENTRY ≈ 1
        pos = state.position.get(product, 0)
        existing = orders_so_far.get(product, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        tb = LIMIT_V - pos - existing_buy
        ts = LIMIT_V + pos - existing_sell
        # Cap by IV-strategy budget
        tb_iv = min(tb, IV_POS_CAP - max(pos, 0))
        ts_iv = min(ts, IV_POS_CAP + min(pos, 0))
        result = []
        if z > IV_Z_ENTRY and ts_iv > 0:
            # IV high → option overpriced → sell
            best_bid = max(od.buy_orders)
            avail = od.buy_orders[best_bid]
            size = min(IV_TRADE_SIZE, avail, ts_iv)
            if size > 0:
                result.append(Order(product, best_bid, -size))
        elif z < -IV_Z_ENTRY and tb_iv > 0:
            # IV low → option underpriced → buy
            best_ask = min(od.sell_orders)
            avail = -od.sell_orders[best_ask]
            size = min(IV_TRADE_SIZE, avail, tb_iv)
            if size > 0:
                result.append(Order(product, best_ask, +size))
        elif abs(z) < IV_Z_EXIT and pos != 0:
            # Reverted to fair — flatten
            if pos > 0 and od.buy_orders:
                best_bid = max(od.buy_orders)
                avail = od.buy_orders[best_bid]
                size = min(pos, avail, ts_iv)
                if size > 0:
                    result.append(Order(product, best_bid, -size))
            elif pos < 0 and od.sell_orders:
                best_ask = min(od.sell_orders)
                avail = -od.sell_orders[best_ask]
                size = min(-pos, avail, tb_iv)
                if size > 0:
                    result.append(Order(product, best_ask, +size))
        return result

    def _call_spread_arb(self, state, orders_so_far):
        fills = []
        committed_buy = {sym: 0 for sym in SYM.values()}
        committed_sell = {sym: 0 for sym in SYM.values()}
        for sym, ord_list in orders_so_far.items():
            if sym in committed_buy:
                committed_buy[sym] = sum(o.quantity for o in ord_list if o.quantity > 0)
                committed_sell[sym] = sum(-o.quantity for o in ord_list if o.quantity < 0)
        for K_lo, K_hi in itertools.combinations(STRIKES_ALL, 2):
            sym_lo, sym_hi = SYM[K_lo], SYM[K_hi]
            od_lo = state.order_depths.get(sym_lo)
            od_hi = state.order_depths.get(sym_hi)
            if od_lo is None or od_hi is None: continue
            pos_lo = state.position.get(sym_lo, 0)
            pos_hi = state.position.get(sym_hi, 0)
            if od_lo.sell_orders and od_hi.buy_orders:
                ask_lo = min(od_lo.sell_orders)
                bid_hi = max(od_hi.buy_orders)
                if ask_lo - bid_hi < 0:
                    ask_lo_vol = -od_lo.sell_orders[ask_lo]
                    bid_hi_vol = od_hi.buy_orders[bid_hi]
                    room_buy_lo = LIMIT_V - pos_lo - committed_buy[sym_lo]
                    room_sell_hi = LIMIT_V + pos_hi - committed_sell[sym_hi]
                    size = min(ARB_SIZE, ask_lo_vol, bid_hi_vol, room_buy_lo, room_sell_hi)
                    if size > 0:
                        fills.append((sym_lo, ask_lo, +size))
                        fills.append((sym_hi, bid_hi, -size))
                        committed_buy[sym_lo] += size
                        committed_sell[sym_hi] += size
        return fills

    def run(self, state: TradingState):
        orders = {}
        # HYDROGEL_PACK: plain mid (Wall Mid hurt on 1k-tick window)
        # VELVETFRUIT_EXTRACT: Wall Mid (helps consistently)
        ho = self._mm_delta1(state, HYDROGEL, LIMIT_D1, POST_SLACK_HP, use_wall_mid=False)
        if ho: orders[HYDROGEL] = ho
        vo = self._mm_delta1(state, VEVE, LIMIT_D1, POST_SLACK_VE, use_wall_mid=True)
        if vo: orders[VEVE] = vo

        # Spot
        spot = self._get_spot(state)
        if spot is None or self.spot_age > 3:
            for K in STRIKES_TRADEABLE:
                r = self._voucher_mm(state, K, orders.get(SYM[K], []))
                if r: orders[SYM[K]] = r
            return orders, 0, ""

        T = self._tte(state.timestamp)

        # Intrinsic arb (4000/4500 loose, others strict)
        for K in STRIKES_ALL:
            deep_itm = K in STRIKES_DEEP_ITM
            r = self._intrinsic_arb(state, K, spot, orders.get(SYM[K], []), deep_itm)
            if r:
                orders.setdefault(SYM[K], []).extend(r)

        # V7.2: IV smile remains DISABLED.
        # V8.1: BS voucher MM with FIXED sigma=0.20 + delta hedge.
        portfolio_delta = 0.0
        for K in BS_STRIKES:
            sym = SYM[K]
            od_v = state.order_depths.get(sym)
            if od_v is None or not od_v.buy_orders or not od_v.sell_orders:
                continue
            pos_v = state.position.get(sym, 0)
            existing = orders.get(sym, [])
            existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
            existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
            cur_pos_buy = pos_v + existing_buy   # post-buy position
            cur_pos_sell = pos_v - existing_sell  # post-sell position
            fv_bs = bs_call(spot, K, T, BS_SIGMA)
            d = bs_delta(spot, K, T, BS_SIGMA)
            portfolio_delta += pos_v * d
            buy_thr = fv_bs - BS_EDGE
            sell_thr = fv_bs + BS_EDGE
            new_orders = []
            # BUY side: take asks at or below threshold
            for px in sorted(od_v.sell_orders.keys()):
                if px > buy_thr: break
                avail = -od_v.sell_orders[px]
                room = LIMIT_V - cur_pos_buy
                size = min(BS_TRADE_SIZE, avail, room)
                if size > 0:
                    new_orders.append(Order(sym, px, +size))
                    cur_pos_buy += size
                    portfolio_delta += size * d
            # SELL side: take bids at or above threshold
            for px in sorted(od_v.buy_orders.keys(), reverse=True):
                if px < sell_thr: break
                avail = od_v.buy_orders[px]
                room = LIMIT_V + cur_pos_sell
                size = min(BS_TRADE_SIZE, avail, room)
                if size > 0:
                    new_orders.append(Order(sym, px, -size))
                    cur_pos_sell -= size
                    portfolio_delta -= size * d
            if new_orders:
                orders.setdefault(sym, []).extend(new_orders)

        # V8.2: delta hedge via VFE (passive entry — post at touch, not cross)
        if abs(portfolio_delta) > HEDGE_THRESHOLD:
            target_vfe = -int(round(portfolio_delta))
            cur_vfe = state.position.get(VEVE, 0)
            existing_vfe = orders.get(VEVE, [])
            existing_vfe_buy = sum(o.quantity for o in existing_vfe if o.quantity > 0)
            existing_vfe_sell = sum(-o.quantity for o in existing_vfe if o.quantity < 0)
            cur_vfe_after = cur_vfe + existing_vfe_buy - existing_vfe_sell
            diff = target_vfe - cur_vfe_after
            od_u = state.order_depths.get(VEVE)
            if od_u and abs(diff) > 0:
                if diff > 0 and od_u.buy_orders:
                    bb = max(od_u.buy_orders)
                    room = LIMIT_D1 - cur_vfe - existing_vfe_buy
                    size = min(diff, room)
                    if size > 0:
                        orders.setdefault(VEVE, []).append(Order(VEVE, bb, +size))
                elif diff < 0 and od_u.sell_orders:
                    ba = min(od_u.sell_orders)
                    room = LIMIT_D1 + cur_vfe - existing_vfe_sell
                    size = min(-diff, room)
                    if size > 0:
                        orders.setdefault(VEVE, []).append(Order(VEVE, ba, -size))

        # Call-spread arb (insurance)
        arb_fills = self._call_spread_arb(state, orders)
        for sym, price, qty in arb_fills:
            orders.setdefault(sym, []).append(Order(sym, price, qty))

        # Voucher MM (fills remaining capacity)
        for K in STRIKES_TRADEABLE:
            r = self._voucher_mm(state, K, orders.get(SYM[K], []))
            if r:
                orders.setdefault(SYM[K], []).extend(r)

        return orders, 0, ""