"""r3_v4.py — v3 + OBI-driven position bias on VEV_4000/4500 + size scaling on high-flow strikes.

Based on exhaustive EDA findings (notes/voucher_analysis_output.txt):

  V4.1 — OBI predictor (new alpha source):
    Underlying OBI significantly predicts VEV_4000/4500 next-tick returns:
      - VEV_4000: β = +0.29 to +0.38, t-stat 8.2 to 10.5, R² 0.7-1.2%
      - VEV_4500: β = -0.35 to -0.25, t-stat -11.1 to -7.8, R² 0.6-1.2%
    Use OBI as position-bias in MM (skew fair value) rather than aggressive takes
    (spread=20 on 4000/4500 exceeds signal magnitude).

  V4.2 — Size scale-up on tradeable-taker-flow strikes:
    VEV_5300/5400 had 37-81 taker trades/day (vs VEV_5000-5200 with <10).
    Increase MM size from 20 → 40 on these strikes to capture more flow.

  V4.3 — Enable VEV_5500 with small size:
    81-94 taker trades/day but spread=1 (no inside-spread room). Post AT best
    with size=5 to catch occasional price improvement fills.

  V4.4 — Keep v3's structural arbs (insurance; never fire in BT).

EDA confirmed v2's IV-surface failure was TIMESCALE mismatch (half-life 1-30
ticks vs v2's 100-200 tick window). Correct-timescale IV trading is too noisy
given vouching spread costs — do not re-enable.
"""
import itertools
from statistics import stdev

from datamodel import Order, TradingState


# Products
HYDROGEL = "HYDROGEL_PACK"
VEVE = "VELVETFRUIT_EXTRACT"
LIMIT_D1 = 200
LIMIT_V = 300

STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
STRIKES_TRADEABLE = [5000, 5100, 5200, 5300, 5400]
STRIKES_HIGH_FLOW = [5300]  # only 5300 has spread >= 2 reliably (5400 spread=1.4)
SYM = {k: f"VEV_{k}" for k in STRIKES_ALL}

# Intrinsic arb
INTRINSIC_EDGE = 2
INTRINSIC_QTY = 50

# Call-spread arb (insurance)
ARB_SIZE = 10
SPOT_STALE_LIMIT = 3

# Voucher MM (differentiated by flow class)
VOUCHER_MM_SIZE_BASE = 20
VOUCHER_MM_SIZE_HIGH = 40          # V4.2: 5300/5400
VOUCHER_MM_SIZE_TIGHT = 5          # V4.3: 5500 tight-spread token size
VOUCHER_MIN_SPREAD = 2             # strikes with spread<2 skip MM (5500 exception)

# Delta-1 MM
POST_SLACK_VE = 1
HP_VOL_WINDOW = 20
HP_SLACK_MIN = 1
HP_SLACK_MAX = 3

# V4.1 — OBI predictor
OBI_WINDOW = 3                     # smooth OBI over last N ticks to reduce noise
OBI_THRESHOLD = 0.4                # trigger magnitude
OBI_BIAS_4000 = +30                # when OBI > thresh: target +30 pos in VEV_4000
OBI_BIAS_4500 = -30                # when OBI > thresh: target -30 pos in VEV_4500 (opposite sign)
OBI_QTY_PER_TICK = 10              # max inventory adjustment per tick


def plain_mid(od):
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    return 0.5 * (max(od.buy_orders) + min(od.sell_orders))


def obi_from(od):
    """Order book imbalance of best levels: (bv1 - av1) / (bv1 + av1)."""
    if not od or not od.buy_orders or not od.sell_orders:
        return 0.0
    bb = max(od.buy_orders)
    ba = min(od.sell_orders)
    bv = od.buy_orders[bb]
    av = -od.sell_orders[ba]
    if bv + av <= 0:
        return 0.0
    return (bv - av) / (bv + av)


class Trader:
    def __init__(self):
        self.hp_mid_history = []
        self.obi_history = []
        self.last_spot = None
        self.spot_age = 0

    def bid(self):
        return 800

    def _get_spot(self, state):
        od = state.order_depths.get(VEVE)
        mp = plain_mid(od)
        if mp is not None:
            self.last_spot = mp
            self.spot_age = 0
            return mp
        self.spot_age += 1
        if self.spot_age < 20 and self.last_spot is not None:
            return self.last_spot
        return None

    def _hp_slack(self, mid):
        self.hp_mid_history.append(mid)
        if len(self.hp_mid_history) > HP_VOL_WINDOW:
            del self.hp_mid_history[:len(self.hp_mid_history) - HP_VOL_WINDOW]
        if len(self.hp_mid_history) < 5:
            return HP_SLACK_MIN
        sigma = stdev(self.hp_mid_history)
        slack = int(round(0.5 * sigma))
        return max(HP_SLACK_MIN, min(HP_SLACK_MAX, slack))

    def _mm_delta1(self, state, product, limit, slack):
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

    def _obi_bias(self, state, smoothed_obi, orders_so_far):
        """V4.1: translate OBI signal into position targets on VEV_4000/4500.

        Strong positive OBI → target long VEV_4000, short VEV_4500.
        Strong negative OBI → opposite.
        Move toward target by up to OBI_QTY_PER_TICK per tick.
        """
        if abs(smoothed_obi) < OBI_THRESHOLD:
            return []
        sign = 1 if smoothed_obi > 0 else -1
        fills = []
        for K, bias_sign in [(4000, OBI_BIAS_4000), (4500, OBI_BIAS_4500)]:
            sym = SYM[K]
            target = sign * bias_sign * abs(smoothed_obi)  # scale by |OBI|
            pos = state.position.get(sym, 0)
            existing = orders_so_far.get(sym, [])
            already_buy = sum(o.quantity for o in existing if o.quantity > 0)
            already_sell = sum(-o.quantity for o in existing if o.quantity < 0)
            delta = int(round(target - pos))
            delta = max(-OBI_QTY_PER_TICK, min(OBI_QTY_PER_TICK, delta))
            if delta == 0:
                continue
            od = state.order_depths.get(sym)
            if od is None:
                continue
            if delta > 0 and od.sell_orders:
                # Buy at best ask
                best_ask = min(od.sell_orders)
                avail = -od.sell_orders[best_ask]
                room = LIMIT_V - pos - already_buy
                size = min(delta, avail, room)
                if size > 0:
                    fills.append((sym, best_ask, +size))
            elif delta < 0 and od.buy_orders:
                best_bid = max(od.buy_orders)
                avail = od.buy_orders[best_bid]
                room = LIMIT_V + pos - already_sell
                size = min(-delta, avail, room)
                if size > 0:
                    fills.append((sym, best_bid, -size))
        return fills

    def _voucher_mm(self, state, strike, size_override=None):
        product = SYM[strike]
        od = state.order_depths.get(product)
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        vbb, vba = max(od.buy_orders), min(od.sell_orders)
        spread = vba - vbb
        if strike in STRIKES_TIGHT_SPREAD:
            # V4.3: 5500 has spread=1, post AT best prices with tiny size
            mm_size = VOUCHER_MM_SIZE_TIGHT
            if spread < 1:
                return []
            post_bid_price = vbb
            post_ask_price = vba
        else:
            if spread < VOUCHER_MIN_SPREAD:
                return []
            mm_size = size_override if size_override else VOUCHER_MM_SIZE_BASE
            post_bid_price = vbb + 1
            post_ask_price = vba - 1
        pos = state.position.get(product, 0)
        tb, ts = LIMIT_V - pos, LIMIT_V + pos
        result = []
        if tb > 0:
            result.append(Order(product, post_bid_price, min(tb, mm_size)))
        if ts > 0:
            result.append(Order(product, post_ask_price, -min(ts, mm_size)))
        return result

    def _call_spread_arb(self, state, orders_so_far):
        """Insurance — no BT fires but catches real arbs on live."""
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
            # Negative-cost spread: buy lo, sell hi
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

        # Delta-1 MM
        hp_mid = plain_mid(state.order_depths.get(HYDROGEL))
        hp_slack = self._hp_slack(hp_mid) if hp_mid is not None else HP_SLACK_MIN
        ho = self._mm_delta1(state, HYDROGEL, LIMIT_D1, hp_slack)
        if ho:
            orders[HYDROGEL] = ho
        vo = self._mm_delta1(state, VEVE, LIMIT_D1, POST_SLACK_VE)
        if vo:
            orders[VEVE] = vo

        # Track underlying OBI (smoothed)
        und_od = state.order_depths.get(VEVE)
        obi_now = obi_from(und_od)
        self.obi_history.append(obi_now)
        if len(self.obi_history) > OBI_WINDOW:
            del self.obi_history[:len(self.obi_history) - OBI_WINDOW]
        smoothed_obi = sum(self.obi_history) / len(self.obi_history) if self.obi_history else 0.0

        # Spot
        spot = self._get_spot(state)
        if spot is None or self.spot_age > SPOT_STALE_LIMIT:
            for K in STRIKES_TRADEABLE:
                r = self._voucher_mm(state, K)
                if r:
                    orders[SYM[K]] = r
            return orders, 0, ""

        # Intrinsic arb on all strikes (deep ITM uses loose, others strict)
        for K in STRIKES_ALL:
            deep_itm = K in (4000, 4500)
            r = self._intrinsic_arb(state, K, spot, orders.get(SYM[K], []), deep_itm)
            if r:
                orders.setdefault(SYM[K], []).extend(r)

        # V4.1: OBI predictor DISABLED — spread > signal magnitude.
        # 1-tick predictive R²=1% with β=0.3 yields ~0.15 expected move per OBI unit,
        # vs spread=20 on VEV_4000/4500. Aggressive entry+exit loses every round-trip.
        # Re-enable only with passive posting + extreme |OBI| threshold.
        # obi_fills = self._obi_bias(state, smoothed_obi, orders)
        # for sym, price, qty in obi_fills:
        #     orders.setdefault(sym, []).append(Order(sym, price, qty))

        # Call-spread arb (insurance)
        arb_fills = self._call_spread_arb(state, orders)
        for sym, price, qty in arb_fills:
            orders.setdefault(sym, []).append(Order(sym, price, qty))

        # Voucher MM with differentiated sizing AND spread-dependent posting.
        # Only post inside-spread (vbb+1, vba-1) when spread >= 2, else skip.
        # No "post-at-best" mode (causes crossing on tight spreads).
        for K in STRIKES_TRADEABLE:
            existing = orders.get(SYM[K], [])
            existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
            existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
            pos = state.position.get(SYM[K], 0)
            od = state.order_depths.get(SYM[K])
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            vbb, vba = max(od.buy_orders), min(od.sell_orders)
            spread = vba - vbb
            if spread < VOUCHER_MIN_SPREAD:
                continue  # no room to post inside
            # Size class (only meaningful when spread >= 2)
            if K in STRIKES_HIGH_FLOW:
                size = VOUCHER_MM_SIZE_HIGH
            else:
                size = VOUCHER_MM_SIZE_BASE
            tb = LIMIT_V - pos - existing_buy
            ts = LIMIT_V + pos - existing_sell
            if tb > 0:
                orders.setdefault(SYM[K], []).append(Order(SYM[K], vbb + 1, min(tb, size)))
            if ts > 0:
                orders.setdefault(SYM[K], []).append(Order(SYM[K], vba - 1, -min(ts, size)))

        return orders, 0, ""
