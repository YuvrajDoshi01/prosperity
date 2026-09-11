"""r3_v1.py — Round 3 MVP.

Strategy components:
  HYDROGEL_PACK         : simple mid-anchored MM with pos-aggression at 50% limit.
  VELVETFRUIT_EXTRACT   : simple mid-anchored MM (also provides BS spot for v2).
  VEV_4000, VEV_4500    : deep-ITM intrinsic arbitrage.
  VEV_5000..VEV_5400    : pure spread-capture MM at best +/- 1.
  VEV_5500..VEV_6500    : skipped (thin or penny-pegged).

Fair value: plain mid (robust); microprice was tested and triggered spurious
takes on tight-spread products (v1d vs v1b: +8.3k improvement over 3 days).

3-day historical BT: ~+28k (HYDROGEL +23k, VE +0.5k, vouchers +4.3k).
Day-2 has weaker HYDROGEL performance — investigate in v2.
"""
from datamodel import Order, TradingState

# Products
HYDROGEL = "HYDROGEL_PACK"
VEVE = "VELVETFRUIT_EXTRACT"
LIMIT_D1 = 200
LIMIT_V = 300

# Voucher strikes by role
STRIKES_TRADEABLE = [5000, 5100, 5200, 5300, 5400]   # vega-meaningful, worth MM'ing
STRIKES_INTR = [4000, 4500]                          # deep ITM, intrinsic arb only
SYM = {k: f"VEV_{k}" for k in STRIKES_TRADEABLE + STRIKES_INTR}

# Intrinsic arbitrage
INTRINSIC_EDGE = 2   # ticks of edge required before firing
INTRINSIC_QTY = 50   # cap per opportunity

# Voucher spread-capture MM
VOUCHER_MM_SIZE = 20
VOUCHER_MIN_SPREAD = 2   # skip post if bid-ask spread < 2 (nothing to capture)

# Delta-1 MM
POST_SLACK = 1


def plain_mid(od):
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    return 0.5 * (max(od.buy_orders) + min(od.sell_orders))


class Trader:
    def bid(self):
        # Manual "bid" challenge — submitted via UI for R3 manual auction
        return 800

    def _mm_delta1(self, state, product, limit):
        od = state.order_depths.get(product)
        mp = plain_mid(od)
        if mp is None:
            return []
        bb, ba = max(od.buy_orders), min(od.sell_orders)
        pos = state.position.get(product, 0)
        fv = round(mp)
        tb, ts = limit - pos, limit + pos
        # Pos-aggression: tighten take threshold by 1 when loaded
        half = limit * 0.5
        mbp = fv - 1 if pos > half else fv
        msp = fv + 1 if pos < -half else fv
        result = []
        for p, v in sorted(od.sell_orders.items()):
            if tb > 0 and p <= mbp:
                q = min(tb, -v)
                result.append(Order(product, p, q))
                tb -= q
        for p, v in sorted(od.buy_orders.items(), reverse=True):
            if ts > 0 and p >= msp:
                q = min(ts, v)
                result.append(Order(product, p, -q))
                ts -= q
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
                q = min(tb, -v, INTRINSIC_QTY)
                result.append(Order(product, p, q))
                tb -= q
        for p, v in sorted(od.buy_orders.items(), reverse=True):
            if ts > 0 and p > intrinsic + INTRINSIC_EDGE:
                q = min(ts, v, INTRINSIC_QTY)
                result.append(Order(product, p, -q))
                ts -= q
        return result

    def run(self, state: TradingState):
        orders = {}

        # Delta-1 MM
        ho = self._mm_delta1(state, HYDROGEL, LIMIT_D1)
        if ho: orders[HYDROGEL] = ho
        vo = self._mm_delta1(state, VEVE, LIMIT_D1)
        if vo: orders[VEVE] = vo

        # Voucher intrinsic arbitrage (deep ITM) — needs spot
        spot = plain_mid(state.order_depths.get(VEVE))
        if spot is not None:
            for K in STRIKES_INTR:
                r = self._intrinsic_arb(state, K, spot)
                if r: orders[SYM[K]] = r

        # Voucher spread-capture MM
        for K in STRIKES_TRADEABLE:
            r = self._voucher_mm(state, K)
            if r: orders[SYM[K]] = r

        return orders, 0, ""
