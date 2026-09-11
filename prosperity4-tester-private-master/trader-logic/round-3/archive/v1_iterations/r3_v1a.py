"""r3_v1a.py — HYDROGEL + VELVETFRUIT MM only, no voucher IV trading.

Baseline to isolate delta-1 performance. Keep intrinsic arb on 4000/4500 only.
"""
import json
from math import log, sqrt
from statistics import NormalDist

from datamodel import Order, TradingState

HYDROGEL = "HYDROGEL_PACK"
VEVE = "VELVETFRUIT_EXTRACT"
LIMIT_D1 = 200
LIMIT_V = 300
STRIKES_INTR = [4000, 4500]
SYM_INTR = {k: f"VEV_{k}" for k in STRIKES_INTR}

INTRINSIC_EDGE = 2
INTRINSIC_QTY = 50
MM_POST_SLACK = 1


def microprice_or_mid(od):
    if not od.buy_orders or not od.sell_orders:
        return None
    bb, ba = max(od.buy_orders), min(od.sell_orders)
    mid = 0.5 * (bb + ba)
    bv = sum(od.buy_orders.values())
    av = sum(-v for v in od.sell_orders.values())
    if bv + av <= 0:
        return mid
    return bb + (bv / (bv + av)) * (ba - bb)


class Trader:
    def bid(self): return 800

    def _mm(self, state, product, limit):
        if product not in state.order_depths:
            return []
        od = state.order_depths[product]
        if not od.buy_orders or not od.sell_orders:
            return []
        bb, ba = max(od.buy_orders), min(od.sell_orders)
        pos = state.position.get(product, 0)
        mp = microprice_or_mid(od)
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
            result.append(Order(product, min(fv - MM_POST_SLACK, bb + 1), tb))
        if ts > 0:
            result.append(Order(product, max(fv + MM_POST_SLACK, ba - 1), -ts))
        return result

    def _intrinsic_arb(self, state, strike, spot):
        product = SYM_INTR[strike]
        if product not in state.order_depths:
            return []
        od = state.order_depths[product]
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

    def run(self, state: TradingState):
        orders = {}
        ho = self._mm(state, HYDROGEL, LIMIT_D1)
        if ho: orders[HYDROGEL] = ho
        vo = self._mm(state, VEVE, LIMIT_D1)
        if vo: orders[VEVE] = vo
        spot = microprice_or_mid(state.order_depths.get(VEVE)) if VEVE in state.order_depths else None
        if spot is not None:
            for K in STRIKES_INTR:
                r = self._intrinsic_arb(state, K, spot)
                if r: orders[SYM_INTR[K]] = r
        return orders, 0, ""
