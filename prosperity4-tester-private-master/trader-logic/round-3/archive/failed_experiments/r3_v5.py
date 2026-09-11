"""r3_v5.py — v3 + DIRECTIONAL ALPHA via VR(20) mean-reversion on VEV_4000/4500.

Background: R3 leaderboard shows top traders earning $100k+ on 1k ticks vs our
median $1,177 (59th percentile). The alpha IS directional, not MM-spread.

EDA (notes/voucher_analysis.py):
- VELVETFRUIT_EXTRACT VR(20) = 0.7 (strong 20-tick mean-reversion)
- VEV_4000/4500 are delta-1 proxies (TV ≈ 0, mean = intrinsic)
- 300-contract limit × $1247 = $374k notional → $10/tick move = $3k PnL

Strategy:
  Track VE rolling mean (window=20). When |spot - mean| > Z_THRESHOLD * sigma:
    - spot ABOVE: short VEV_4000 (expect reversion down → 4000 falls in lockstep)
    - spot BELOW: long VEV_4000 (expect reversion up)
  Exit when spot crosses rolling mean (target hit).
  Size: scale with deviation magnitude, cap at LIMIT=300.

Keeps:
  - All v3 MM (HYDROGEL, VE, vouchers 5000-5400)
  - Intrinsic arb on 4000/4500 (loose rule for deep ITM)
  - Call-spread arb scanner (insurance)

Target: Move from $1k median to top 10% ($10k+) PnL on 1k-tick BT day 2.
"""
import itertools
from collections import deque
from statistics import stdev, mean

from datamodel import Order, TradingState

HYDROGEL = "HYDROGEL_PACK"
VEVE = "VELVETFRUIT_EXTRACT"
LIMIT_D1 = 200
LIMIT_V = 300

STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
STRIKES_TRADEABLE = [5000, 5100, 5200, 5300, 5400]
SYM = {k: f"VEV_{k}" for k in STRIKES_ALL}

# Intrinsic arb
INTRINSIC_EDGE = 2
INTRINSIC_QTY = 50

# Call-spread arb (insurance)
ARB_SIZE = 10
SPOT_STALE_LIMIT = 3

# Voucher MM
VOUCHER_MM_SIZE = 20
VOUCHER_MIN_SPREAD = 2

# Delta-1 MM
POST_SLACK_VE = 1
HP_VOL_WINDOW = 20
HP_SLACK_MIN = 1
HP_SLACK_MAX = 3

# V5 — Directional mean-reversion on VEV_4000/4500
DIR_WINDOW = 20             # rolling window for VE mean (matches VR(20) finding)
DIR_Z_ENTRY = 1.5           # |spot - mean| / sigma threshold to enter
DIR_Z_EXIT = 0.3            # exit when |spot - mean| / sigma below this
DIR_MAX_POS = 200           # max position taken via directional (leaves room for arb)
DIR_QTY_PER_TICK = 50       # max position adjustment per tick (controlled entry)


def plain_mid(od):
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    return 0.5 * (max(od.buy_orders) + min(od.sell_orders))


class Trader:
    def __init__(self):
        self.hp_mid_history = []
        self.ve_mid_history = deque(maxlen=DIR_WINDOW)
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
            self.ve_mid_history.append(mp)
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
                q = min(tb, -v); result.append(Order(product, p, q)); tb -= q
        for p, v in sorted(od.buy_orders.items(), reverse=True):
            if ts > 0 and p >= msp:
                q = min(ts, v); result.append(Order(product, p, -q)); ts -= q
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

    def _directional(self, state, spot, orders_so_far):
        """V5 — VR(20) mean-reversion on VEV_4000 (highest delta) using VE deviation.

        spot above 20-tick mean → expect reversion DOWN → SHORT VEV_4000.
        spot below 20-tick mean → expect reversion UP → LONG VEV_4000.
        Size proportional to z-score, capped at DIR_MAX_POS.
        """
        if len(self.ve_mid_history) < DIR_WINDOW:
            return []
        history = list(self.ve_mid_history)
        rolling_mean = mean(history)
        rolling_sigma = stdev(history)
        if rolling_sigma < 0.5:  # near-flat market, skip
            return []
        z = (spot - rolling_mean) / rolling_sigma

        # Target VEV_4000 position scales with -z (negative correlation: spot up → short voucher)
        if abs(z) < DIR_Z_EXIT:
            target = 0  # close out
        elif abs(z) < DIR_Z_ENTRY:
            return []  # neutral zone; no change
        else:
            scale = max(-1.0, min(1.0, z / 3.0))  # cap at ±3 sigma
            target = +int(round(scale * DIR_MAX_POS))  # POSITIVE: trend-follow VE direction

        sym = SYM[4000]
        pos = state.position.get(sym, 0)
        existing = orders_so_far.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        delta = target - pos
        delta = max(-DIR_QTY_PER_TICK, min(DIR_QTY_PER_TICK, delta))
        if delta == 0:
            return []
        od = state.order_depths.get(sym)
        if od is None:
            return []
        fills = []
        if delta > 0 and od.sell_orders:
            best_ask = min(od.sell_orders)
            avail = -od.sell_orders[best_ask]
            room = LIMIT_V - pos - existing_buy
            size = min(delta, avail, room)
            if size > 0:
                fills.append((sym, best_ask, +size))
        elif delta < 0 and od.buy_orders:
            best_bid = max(od.buy_orders)
            avail = od.buy_orders[best_bid]
            room = LIMIT_V + pos - existing_sell
            size = min(-delta, avail, room)
            if size > 0:
                fills.append((sym, best_bid, -size))
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

        # Delta-1 MM
        hp_mid = plain_mid(state.order_depths.get(HYDROGEL))
        hp_slack = self._hp_slack(hp_mid) if hp_mid is not None else HP_SLACK_MIN
        ho = self._mm_delta1(state, HYDROGEL, LIMIT_D1, hp_slack)
        if ho: orders[HYDROGEL] = ho
        vo = self._mm_delta1(state, VEVE, LIMIT_D1, POST_SLACK_VE)
        if vo: orders[VEVE] = vo

        # Spot
        spot = self._get_spot(state)
        if spot is None or self.spot_age > SPOT_STALE_LIMIT:
            for K in STRIKES_TRADEABLE:
                r = self._voucher_mm(state, K, orders.get(SYM[K], []))
                if r: orders[SYM[K]] = r
            return orders, 0, ""

        # Intrinsic arb (all strikes, hybrid rule)
        for K in STRIKES_ALL:
            deep_itm = K in (4000, 4500)
            r = self._intrinsic_arb(state, K, spot, orders.get(SYM[K], []), deep_itm)
            if r:
                orders.setdefault(SYM[K], []).extend(r)

        # V5: directional disabled — spread cost ($20 on VEV_4000) ≫ signal value.
        # Tested both MR (-$40k/day) and trend-follow (-$44k/day) at 1k ticks.
        # Top-trader $100k+ alpha is NOT from naive direction bets via vouchers.
        # dir_fills = self._directional(state, spot, orders)
        # for sym, price, qty in dir_fills:
        #     orders.setdefault(sym, []).append(Order(sym, price, qty))

        # Call-spread arb (insurance)
        arb_fills = self._call_spread_arb(state, orders)
        for sym, price, qty in arb_fills:
            orders.setdefault(sym, []).append(Order(sym, price, qty))

        # Voucher MM (after arbs claim capacity)
        for K in STRIKES_TRADEABLE:
            r = self._voucher_mm(state, K, orders.get(SYM[K], []))
            if r:
                orders.setdefault(SYM[K], []).extend(r)

        return orders, 0, ""
