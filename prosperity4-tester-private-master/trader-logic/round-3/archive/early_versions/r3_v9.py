"""r3_v9.py -- v7 base + safe BS voucher taking (wide edge, pos-capped).

1k-tick 3-day: 8,258 (+52.6% over v7's 5,410)
10k-tick 3-day: 47,305 (vs v7's 47,388, -0.18% = noise)

v8 lesson: BS voucher trading earned +$6k on day 0 but LOST -$6.5k on day 1
because fixed sigma=0.20 diverged from realized vol. Two fixes applied:

V9.1 -- BS voucher taking with VERY WIDE edge (10.0 ticks, up from v8's 1.6):
  Only takes when ask <= BS_fair - 10.0 or bid >= BS_fair + 10.0.
  Grid-searched: peak at edge=10.0 across 3 days. At edge=20+ nothing fires.
  This means we only trade when market is grossly mispriced vs BS, which
  survives +-0.05 sigma estimation error.

V9.2 -- Position cap per strike (BS_POS_CAP=150):
  Limits max net exposure from BS takes to 150 contracts per strike (vs 300 limit).
  Grid-searched: cap=150 gives 1k +2.8k over v7, 10k -83 (noise).
  Higher caps give more 1k but bleed more at 10k.

V9.3 -- Adaptive sigma via rolling IV median:
  Track rolling median IV across 5 tradeable strikes (window=50).
  Median is robust to outlier strikes. Fallback to 0.18 if cold.

V9.4 -- No delta hedge (v8's passive hedge barely filled and interfered with
  VFE MM. The VFE MM already provides natural delta hedging).

Keeps v7's proven:
  - Wall Mid for VFE MM
  - Plain mid for HYDROGEL_PACK MM
  - Intrinsic arb on 4000/4500 (loose) + others (strict)
  - Call-spread arb scanner
  - Voucher passive MM on 5000-5400
"""
import itertools
import math
from collections import deque
from statistics import NormalDist, median

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

# V9.1 -- BS voucher taking (wide edge)
BS_SIGMA_DEFAULT = 0.18          # conservative default (below mean 0.20)
BS_EDGE = 10.0                   # very wide: only trade gross mispricing (grid-searched peak)
BS_TRADE_SIZE = 30               # per-trigger cap
BS_POS_CAP = 150                 # max net position from BS takes per strike (grid-searched: 1k+2.8k, 10k-83)
BS_STRIKES = [5000, 5100, 5200, 5300, 5400]

# V9.2 -- Adaptive sigma
IV_ADAPT_WINDOW = 50             # rolling IV history for median estimation
IV_ADAPT_MIN_HIST = 15           # minimum observations before using adaptive


def bs_call(spot, K, T, vol):
    if T <= 0 or vol <= 0:
        return max(spot - K, 0.0)
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    return spot * _ND.cdf(d1) - K * _ND.cdf(d2)


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
    """Wall Mid: midpoint of highest-volume bid/ask levels."""
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    pop_bid = max(od.buy_orders.items(), key=lambda kv: kv[1])[0]
    pop_ask = min(od.sell_orders.items(), key=lambda kv: kv[1])[0]
    return 0.5 * (pop_bid + pop_ask)


def best_mid(od):
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    return 0.5 * (max(od.buy_orders) + min(od.sell_orders))


class Trader:
    def __init__(self):
        self.last_spot = None
        self.spot_age = 0
        self.iv_history = deque(maxlen=IV_ADAPT_WINDOW)  # all-strike IV pool

    def bid(self):
        return 800

    def _tte(self, ts):
        d = TTE_DAYS_AT_START - ts / 1_000_000.0
        return max(d, 0.01) / TTE_YEAR

    def _get_spot(self, state):
        od = state.order_depths.get(VEVE)
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

    def _get_adaptive_sigma(self, state, spot, T):
        """V9.2: estimate sigma from rolling median of per-strike implied vols."""
        tick_ivs = []
        for K in STRIKES_IV:
            od = state.order_depths.get(SYM[K])
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            wm = wall_mid(od)
            if wm is None:
                wm = best_mid(od)
            if wm is None:
                continue
            iv = implied_vol(wm, spot, K, T)
            if iv is not None and 0.01 < iv < 2.0:
                tick_ivs.append(iv)
        if tick_ivs:
            self.iv_history.append(median(tick_ivs))
        if len(self.iv_history) >= IV_ADAPT_MIN_HIST:
            return median(self.iv_history)
        return BS_SIGMA_DEFAULT

    def _mm_delta1(self, state, product, limit, slack, use_wall_mid=True):
        od = state.order_depths.get(product)
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
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

    def _bs_voucher_take(self, state, spot, T, sigma, orders_so_far):
        """V9.1: BS-priced aggressive takes on liquid strikes with wide edge.

        Only fires when market price diverges > BS_EDGE from BS fair.
        Wide edge ensures we survive sigma misestimation of +-0.05.
        """
        fills = []
        for K in BS_STRIKES:
            sym = SYM[K]
            od_v = state.order_depths.get(sym)
            if od_v is None or not od_v.buy_orders or not od_v.sell_orders:
                continue
            pos_v = state.position.get(sym, 0)
            existing = orders_so_far.get(sym, [])
            existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
            existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)

            fv_bs = bs_call(spot, K, T, sigma)
            buy_thr = fv_bs - BS_EDGE
            sell_thr = fv_bs + BS_EDGE

            cur_buy_room = min(LIMIT_V - pos_v - existing_buy,
                              BS_POS_CAP - max(pos_v, 0))
            cur_sell_room = min(LIMIT_V + pos_v - existing_sell,
                               BS_POS_CAP + min(pos_v, 0))

            # BUY: take asks below threshold
            for px in sorted(od_v.sell_orders.keys()):
                if px > buy_thr:
                    break
                avail = -od_v.sell_orders[px]
                size = min(BS_TRADE_SIZE, avail, cur_buy_room)
                if size > 0:
                    fills.append((sym, px, +size))
                    cur_buy_room -= size

            # SELL: take bids above threshold
            for px in sorted(od_v.buy_orders.keys(), reverse=True):
                if px < sell_thr:
                    break
                avail = od_v.buy_orders[px]
                size = min(BS_TRADE_SIZE, avail, cur_sell_room)
                if size > 0:
                    fills.append((sym, px, -size))
                    cur_sell_room -= size

        return fills

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
            if od_lo is None or od_hi is None:
                continue
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

        # Delta-1 MM: plain mid for HP, Wall Mid for VFE
        ho = self._mm_delta1(state, HYDROGEL, LIMIT_D1, POST_SLACK_HP, use_wall_mid=False)
        if ho:
            orders[HYDROGEL] = ho
        vo = self._mm_delta1(state, VEVE, LIMIT_D1, POST_SLACK_VE, use_wall_mid=True)
        if vo:
            orders[VEVE] = vo

        # Spot
        spot = self._get_spot(state)
        if spot is None or self.spot_age > 3:
            for K in STRIKES_TRADEABLE:
                r = self._voucher_mm(state, K, orders.get(SYM[K], []))
                if r:
                    orders[SYM[K]] = r
            return orders, 0, ""

        T = self._tte(state.timestamp)

        # Intrinsic arb (4000/4500 loose, others strict)
        for K in STRIKES_ALL:
            deep_itm = K in STRIKES_DEEP_ITM
            r = self._intrinsic_arb(state, K, spot, orders.get(SYM[K], []), deep_itm)
            if r:
                orders.setdefault(SYM[K], []).extend(r)

        # V9.2: adaptive sigma from rolling IV median
        sigma = self._get_adaptive_sigma(state, spot, T)

        # V9.1: BS voucher taking with wide edge
        bs_fills = self._bs_voucher_take(state, spot, T, sigma, orders)
        for sym, price, qty in bs_fills:
            orders.setdefault(sym, []).append(Order(sym, price, qty))

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
