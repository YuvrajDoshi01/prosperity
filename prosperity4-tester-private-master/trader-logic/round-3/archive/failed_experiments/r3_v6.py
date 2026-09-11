"""r3_v6.py — Aggressive HYDROGEL_PACK MM test.

Hypothesis: top traders earn $80/tick via super-aggressive MM that captures
more spread per tick. Test by:
1. Removing position-aggression on take (always take at fv, not fv-1)
2. Larger post size (no cap)
3. Taking at fv+1 for buys (1 above fair) — accept worse entry for fill rate
4. Multi-level posting (post at best+1 AND mid)

If 1k-tick day 2 PnL > v3's $1,013, this hypothesis is on the right track.
"""
from collections import deque
from statistics import stdev

from datamodel import Order, TradingState

HYDROGEL = "HYDROGEL_PACK"
VEVE = "VELVETFRUIT_EXTRACT"
LIMIT_D1 = 200
LIMIT_V = 300

STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
STRIKES_TRADEABLE = [5000, 5100, 5200, 5300, 5400]
SYM = {k: f"VEV_{k}" for k in STRIKES_ALL}

INTRINSIC_EDGE = 2
INTRINSIC_QTY = 50
VOUCHER_MM_SIZE = 20
VOUCHER_MIN_SPREAD = 2

# Aggressive MM parameters
TAKE_OFFSET = 0            # take at fair (v3 default), but no pos-aggression
POST_SLACK_HP = 1
POST_SLACK_VE = 1


def plain_mid(od):
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    return 0.5 * (max(od.buy_orders) + min(od.sell_orders))


class Trader:
    def bid(self): return 800

    def _aggressive_mm(self, state, product, limit, slack):
        """Aggressive MM: take with TAKE_OFFSET tolerance, post full size, no pos-aggression."""
        od = state.order_depths.get(product)
        mp = plain_mid(od)
        if mp is None:
            return []
        bb, ba = max(od.buy_orders), min(od.sell_orders)
        pos = state.position.get(product, 0)
        fv = round(mp)
        tb = limit - pos
        ts = limit + pos
        result = []
        # Aggressive take: buy at any ask <= fv+TAKE_OFFSET, sell at any bid >= fv-TAKE_OFFSET
        for p, v in sorted(od.sell_orders.items()):
            if tb > 0 and p <= fv + TAKE_OFFSET:
                q = min(tb, -v)
                result.append(Order(product, p, q))
                tb -= q
        for p, v in sorted(od.buy_orders.items(), reverse=True):
            if ts > 0 and p >= fv - TAKE_OFFSET:
                q = min(ts, v)
                result.append(Order(product, p, -q))
                ts -= q
        # Post full remaining capacity
        if tb > 0:
            result.append(Order(product, min(fv - slack, bb + 1), tb))
        if ts > 0:
            result.append(Order(product, max(fv + slack, ba - 1), -ts))
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

    def _intrinsic_arb(self, state, strike, spot, deep_itm):
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
                result.append(Order(product, p, q)); tb -= q
        sell_thr = intrinsic + INTRINSIC_EDGE if deep_itm else spot + INTRINSIC_EDGE
        for p, v in sorted(od.buy_orders.items(), reverse=True):
            if ts > 0 and p > sell_thr:
                q = min(ts, v, INTRINSIC_QTY)
                result.append(Order(product, p, -q)); ts -= q
        return result

    def run(self, state: TradingState):
        orders = {}
        ho = self._aggressive_mm(state, HYDROGEL, LIMIT_D1, POST_SLACK_HP)
        if ho: orders[HYDROGEL] = ho
        vo = self._aggressive_mm(state, VEVE, LIMIT_D1, POST_SLACK_VE)
        if vo: orders[VEVE] = vo
        spot = plain_mid(state.order_depths.get(VEVE))
        if spot is not None:
            for K in (4000, 4500):
                r = self._intrinsic_arb(state, K, spot, deep_itm=True)
                if r: orders.setdefault(SYM[K], []).extend(r)
        for K in STRIKES_TRADEABLE:
            r = self._voucher_mm(state, K)
            if r: orders[SYM[K]] = r
        return orders, 0, ""
