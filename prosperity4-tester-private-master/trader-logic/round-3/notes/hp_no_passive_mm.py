"""hp_no_passive_mm.py - v22 with passive MM DISABLED for HP.

Identical to v22 except the passive MM fallback for HP posts NO orders.
Only alpha regimes (S17 entry, S17 build, S7 cover, FLIP) produce orders.
This isolates the passive MM contribution to HP PnL.

Usage:
  PYTHONPATH=prosperity4bt python -m prosperity4bt trader-logic/round-3/notes/hp_no_passive_mm.py 3-2 --ticks 10000 --no-progress --no-out
"""

import itertools
import json
import math
from statistics import NormalDist, median
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, ProsperityEncoder, Symbol, TradingState

_ND_VOUCHER = NormalDist()


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state, orders, conversions, trader_data):
        print(json.dumps([
            self._compress_state(state),
            [[o.symbol, o.price, o.quantity] for arr in orders.values() for o in arr],
            conversions,
            trader_data,
            self.logs,
        ], cls=ProsperityEncoder, separators=(",", ":")))
        self.logs = ""

    def _compress_state(self, state):
        return [
            state.timestamp,
            state.traderData,
            [[l.symbol, l.product, l.denomination] for l in state.listings.values()],
            {s: [od.buy_orders, od.sell_orders] for s, od in state.order_depths.items()},
            self._compress_trades(state.own_trades),
            self._compress_trades(state.market_trades),
            state.position,
            self._compress_observations(state.observations),
        ]

    def _compress_trades(self, trades):
        return [
            [t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
            for arr in trades.values() for t in arr
        ]

    def _compress_observations(self, observations):
        cc = {}
        if observations:
            for product, obs in observations.conversionObservations.items():
                cc[product] = [obs.bidPrice, obs.askPrice, obs.transportFees,
                               obs.exportTariff, obs.importTariff,
                               obs.sugarPrice, obs.sunlightIndex]
        return [observations.plainValueObservations if observations else {}, cc]


logger = Logger()


class Product:
    HYDROGEL_PACK       = "HYDROGEL_PACK"
    VELVETFRUIT_EXTRACT = "VELVETFRUIT_EXTRACT"
    VEV_4000  = "VEV_4000";  VEV_4500  = "VEV_4500"
    VEV_5000  = "VEV_5000";  VEV_5100  = "VEV_5100"
    VEV_5200  = "VEV_5200";  VEV_5300  = "VEV_5300"
    VEV_5400  = "VEV_5400";  VEV_5500  = "VEV_5500"
    VEV_6000  = "VEV_6000";  VEV_6500  = "VEV_6500"


POSITION_LIMITS: Dict[str, int] = {
    Product.HYDROGEL_PACK: 200,
    Product.VELVETFRUIT_EXTRACT: 200,
    **{getattr(Product, f"VEV_{v}"): 300
       for v in ["4000","4500","5000","5100","5200","5300","5400","5500","6000","6500"]},
}


class HydrogelParams:
    REGIME2_SPREAD = 17
    ENTRY_MID_MIN = 10010
    S7_WINDOW = 500
    S7_BOTTOM_Q = 0.08
    FLIP_TARGET = 200
    FLIP_EXIT_MID = 10020
    FLIP_TIMEOUT_TICKS = 1500
    POS_LIMIT = 200
    QUOTE_SIZE = 25
    Z500_WINDOW = 500
    STD100_WINDOW = 100
    EDGE_BETA_WINDOW = 500
    EDGE_BETA_MIN_SAMPLES = 50
    EDGE_BETA_SHRINK = 0.5
    LAYER_A_SCALE = 3.0
    LAYER_A_CLIP = 1.0


def _mean(buf):
    return sum(buf) / len(buf) if buf else None

def _push(buf, value, maxlen):
    buf = buf + [value]
    return buf[-maxlen:] if len(buf) > maxlen else buf

def _clip(value, lo, hi):
    return max(lo, min(hi, value))


def compute_book_features(order_depth):
    buys  = order_depth.buy_orders
    sells = order_depth.sell_orders
    if not buys or not sells: return {}
    best_bid = max(buys.keys())
    best_ask = min(sells.keys())
    spread   = best_ask - best_bid
    if spread <= 0: return {}
    mid = (best_bid + best_ask) / 2.0
    sorted_bids = sorted(buys.keys(),  reverse=True)
    sorted_asks = sorted(sells.keys(), reverse=False)
    def px(lst, i): return lst[i] if i < len(lst) else None
    def sz(book, p): return abs(book[p]) if p is not None else 0.0
    bid_px = [px(sorted_bids, i) for i in range(3)]
    ask_px = [px(sorted_asks, i) for i in range(3)]
    bid_sz = [sz(buys,  p) for p in bid_px]
    ask_sz = [sz(sells, p) for p in ask_px]
    bid_num = sum((bid_px[i] or 0) * bid_sz[i] for i in range(3) if bid_px[i])
    ask_num = sum((ask_px[i] or 0) * ask_sz[i] for i in range(3) if ask_px[i])
    bid_den = sum(bid_sz[i] for i in range(3) if bid_px[i])
    ask_den = sum(ask_sz[i] for i in range(3) if ask_px[i])
    bid_wap = bid_num / bid_den if bid_den > 0 else best_bid
    ask_wap = ask_num / ask_den if ask_den > 0 else best_ask
    book_wap_edge_L3 = ((bid_wap + ask_wap) / 2.0) - mid
    return {
        "best_bid": best_bid, "best_ask": best_ask,
        "spread": spread, "mid": mid,
        "book_wap_edge_L3": book_wap_edge_L3,
    }


class HydrogelState:
    def __init__(self):
        self.mid_buf_500: List[float] = []
        self.mid_buf_100: List[float] = []
        self.row: int = 0
        self.s17_entry_row: Optional[int] = None
        self.s17_entry_mid: Optional[float] = None
        self.s7_covering: bool = False
        self.flip_holding: bool = False
        self.flip_entry_row: Optional[int] = None
        self.prev_mid: Optional[float] = None
        self.prev_wap_edge: Optional[float] = None
        self.edge_buf: List[float] = []
        self.ret_buf: List[float] = []

    def to_dict(self):
        return {
            "buf500":    self.mid_buf_500,
            "buf100":    self.mid_buf_100,
            "row":       self.row,
            "s17_row":   self.s17_entry_row,
            "s17_mid":   self.s17_entry_mid,
            "s7_cov":    self.s7_covering,
            "fh":        self.flip_holding,
            "fer":       self.flip_entry_row,
            "pmid":      self.prev_mid,
            "pedge":     self.prev_wap_edge,
            "edgeb":     self.edge_buf,
            "retb":      self.ret_buf,
        }

    @staticmethod
    def from_dict(d):
        s = HydrogelState()
        s.mid_buf_500       = d.get("buf500", [])
        s.mid_buf_100       = d.get("buf100", [])
        s.row               = d.get("row", 0)
        s.s17_entry_row     = d.get("s17_row")
        s.s17_entry_mid     = d.get("s17_mid")
        s.s7_covering       = d.get("s7_cov", False)
        s.flip_holding      = d.get("fh", False)
        s.flip_entry_row    = d.get("fer")
        s.prev_mid          = d.get("pmid")
        s.prev_wap_edge     = d.get("pedge")
        s.edge_buf          = d.get("edgeb", [])
        s.ret_buf           = d.get("retb", [])
        return s


def run_hydrogel(state, hstate):
    """v22 HP with passive MM DISABLED. Only alpha regimes produce orders."""
    P      = Product.HYDROGEL_PACK
    orders = []
    p      = HydrogelParams

    if P not in state.order_depths:
        return orders, hstate

    od       = state.order_depths[P]
    position = state.position.get(P, 0)
    pos_lim  = p.POS_LIMIT
    features = compute_book_features(od)
    if not features: return orders, hstate

    mid      = features["mid"]
    spread   = features["spread"]
    best_bid = int(features["best_bid"])
    best_ask = int(features["best_ask"])
    wap_edge = features["book_wap_edge_L3"]

    hstate.mid_buf_500 = _push(hstate.mid_buf_500, mid, p.Z500_WINDOW)
    hstate.mid_buf_100 = _push(hstate.mid_buf_100, mid, p.STD100_WINDOW)
    hstate.row += 1

    if hstate.prev_mid is not None and hstate.prev_wap_edge is not None:
        ret_1t = mid - hstate.prev_mid
        hstate.edge_buf = _push(hstate.edge_buf, hstate.prev_wap_edge, p.EDGE_BETA_WINDOW)
        hstate.ret_buf  = _push(hstate.ret_buf, ret_1t, p.EDGE_BETA_WINDOW)
    hstate.prev_mid = mid
    hstate.prev_wap_edge = wap_edge

    # S17 build
    if hstate.s17_entry_row is not None and position < 0:
        window_ready = len(hstate.mid_buf_500) >= p.S7_WINDOW
        if window_ready:
            sorted_window = sorted(hstate.mid_buf_500[-p.S7_WINDOW:])
            bottom_thresh = sorted_window[int(len(sorted_window) * p.S7_BOTTOM_Q)]
            s7_bottom     = (spread == 7 and mid <= bottom_thresh)
        else:
            s7_bottom     = False
        if s7_bottom:
            hstate.s7_covering   = True
            hstate.s17_entry_row = None
            hstate.s17_entry_mid = None

        headroom = pos_lim + position
        if headroom > 0:
            orders.append(Order(P, best_bid, -headroom))
        return orders, hstate

    # S7 cover/flip
    if hstate.s7_covering:
        remaining = p.FLIP_TARGET - position
        if remaining > 0:
            orders.append(Order(P, best_ask, remaining))
        if position >= p.FLIP_TARGET:
            hstate.s7_covering = False
            hstate.flip_holding = True
            hstate.flip_entry_row = hstate.row
        return orders, hstate

    # FLIP hold
    if hstate.flip_holding:
        held_for = hstate.row - (hstate.flip_entry_row or hstate.row)
        if mid >= p.FLIP_EXIT_MID or held_for >= p.FLIP_TIMEOUT_TICKS:
            if position > 0:
                orders.append(Order(P, best_bid, -position))
            hstate.flip_holding = False
            hstate.flip_entry_row = None
        return orders, hstate

    # S17 entry
    if (spread == p.REGIME2_SPREAD
            and mid > p.ENTRY_MID_MIN
            and hstate.s17_entry_row is None):
        headroom = pos_lim + position
        qty = min(pos_lim, headroom)
        if qty > 0:
            orders.append(Order(P, best_bid, -qty))
            hstate.s17_entry_row = hstate.row
            hstate.s17_entry_mid = mid
        return orders, hstate

    # PASSIVE MM DISABLED - return empty orders
    return orders, hstate


# ---- Voucher/VFE (exact copy from v22) ----

VEVE_SYM = "VELVETFRUIT_EXTRACT"
VOUCHER_STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VOUCHER_STRIKES_TRADEABLE = [5000, 5100, 5200, 5300, 5400]
VOUCHER_STRIKES_DEEP_ITM = [4000, 4500]
VOUCHER_STRIKES_SKIP = {6000, 6500}
VOUCHER_STRIKES_OTM_PASSIVE = [5300, 5400, 5500]
VOUCHER_SYM = {k: f"VEV_{k}" for k in VOUCHER_STRIKES_ALL}
V_TTE_DAYS_AT_START = 5.0
V_TTE_YEAR = 250.0
V_INTRINSIC_EDGE = 2
V_INTRINSIC_QTY = 50
V_ARB_SIZE = 10
V_VOUCHER_MM_SIZE = 20
V_VOUCHER_MIN_SPREAD = 2
V_POST_SLACK_VE = 1
V_BS_SIGMA_DEFAULT = 0.18
V_BS_EDGE = 10.0
V_BS_TRADE_SIZE = 30
V_BS_POS_CAP = 150
V_BS_STRIKES = [5000, 5100, 5200, 5300, 5400]
V_IV_ADAPT_WINDOW = 50
V_IV_ADAPT_MIN_HIST = 15


def v_bs_call(spot, K, T, vol):
    if T <= 0 or vol <= 0:
        return max(spot - K, 0.0)
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    return spot * _ND_VOUCHER.cdf(d1) - K * _ND_VOUCHER.cdf(d2)


def v_implied_vol(mkt, spot, K, T, lo=1e-4, hi=5.0):
    intr = max(spot - K, 0.0)
    if mkt <= intr + 1e-6 or T <= 0 or mkt >= spot:
        return None
    for _ in range(50):
        m = 0.5 * (lo + hi)
        if v_bs_call(spot, K, T, m) < mkt:
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


def v_wall_mid(od):
    if not od or not od.buy_orders or not od.sell_orders: return None
    pop_bid = max(od.buy_orders.items(), key=lambda kv: kv[1])[0]
    pop_ask = min(od.sell_orders.items(), key=lambda kv: kv[1])[0]
    return 0.5 * (pop_bid + pop_ask)


def v_plain_mid(od):
    if not od or not od.buy_orders or not od.sell_orders: return None
    return 0.5 * (max(od.buy_orders) + min(od.sell_orders))


class VoucherState:
    def __init__(self):
        self.iv_history = {k: [] for k in V_BS_STRIKES}
        self.last_spot = None
        self.spot_age = 0
        self.prev_ve_ap1: Optional[float] = None
        self.prev_ve_bp1: Optional[float] = None

    def to_dict(self):
        return {
            "ivh": {str(k): v[-V_IV_ADAPT_WINDOW:] for k, v in self.iv_history.items()},
            "ls": self.last_spot,
            "sa": self.spot_age,
            "p_ap": self.prev_ve_ap1,
            "p_bp": self.prev_ve_bp1,
        }

    @staticmethod
    def from_dict(d):
        s = VoucherState()
        s.iv_history = {int(k): list(v) for k, v in d.get("ivh", {}).items()}
        for k in V_BS_STRIKES:
            if k not in s.iv_history: s.iv_history[k] = []
        s.last_spot = d.get("ls")
        s.spot_age = d.get("sa", 0)
        s.prev_ve_ap1 = d.get("p_ap")
        s.prev_ve_bp1 = d.get("p_bp")
        return s


def v_get_adaptive_sigma(state, vstate):
    all_recent = []
    for k in V_BS_STRIKES:
        hist = vstate.iv_history.get(k, [])
        if len(hist) >= V_IV_ADAPT_MIN_HIST:
            all_recent.extend(hist[-V_IV_ADAPT_WINDOW:])
    if len(all_recent) < V_IV_ADAPT_MIN_HIST:
        return V_BS_SIGMA_DEFAULT
    return median(all_recent)


def run_vouchers(state, vstate):
    orders = {}
    timestamp = state.timestamp

    od_ve = state.order_depths.get(VEVE_SYM)
    ve_layer_e: List[Order] = []
    layer_e_buy = 0
    layer_e_sell = 0
    if od_ve and od_ve.buy_orders and od_ve.sell_orders:
        bb_ve = max(od_ve.buy_orders); ba_ve = min(od_ve.sell_orders)
        spread_ve = ba_ve - bb_ve
        pos_ve = state.position.get(VEVE_SYM, 0)
        E_SIZE = 20
        E_POS_CAP = 200
        if (vstate.prev_ve_ap1 is not None and vstate.prev_ve_bp1 is not None):
            if spread_ve == 2 and ba_ve < vstate.prev_ve_ap1:
                room_buy = E_POS_CAP - pos_ve
                q = min(E_SIZE, room_buy)
                if q > 0:
                    px = int(ba_ve - 1)
                    if px > bb_ve and px < ba_ve:
                        ve_layer_e.append(Order(VEVE_SYM, px, q))
                        layer_e_buy = q
            elif spread_ve == 3 and bb_ve > vstate.prev_ve_bp1:
                room_sell = E_POS_CAP + pos_ve
                q = min(E_SIZE, room_sell)
                if q > 0:
                    px = int(bb_ve + 1)
                    if px > bb_ve and px < ba_ve:
                        ve_layer_e.append(Order(VEVE_SYM, px, -q))
                        layer_e_sell = q
        vstate.prev_ve_ap1 = ba_ve
        vstate.prev_ve_bp1 = bb_ve

    if od_ve and od_ve.buy_orders and od_ve.sell_orders:
        wm = v_wall_mid(od_ve)
        if wm is not None:
            bb = max(od_ve.buy_orders); ba = min(od_ve.sell_orders)
            pos = state.position.get(VEVE_SYM, 0)
            fv = round(wm)
            tb = 200 - pos - layer_e_buy
            ts = 200 + pos - layer_e_sell
            half = 100
            mbp = fv - 1 if pos > half else fv
            msp = fv + 1 if pos < -half else fv
            ve_orders = list(ve_layer_e)
            for p, v in sorted(od_ve.sell_orders.items()):
                if tb > 0 and p <= mbp:
                    q = min(tb, -v); ve_orders.append(Order(VEVE_SYM, p, q)); tb -= q
            for p, v in sorted(od_ve.buy_orders.items(), reverse=True):
                if ts > 0 and p >= msp:
                    q = min(ts, v); ve_orders.append(Order(VEVE_SYM, p, -q)); ts -= q
            if tb > 0:
                ve_orders.append(Order(VEVE_SYM, min(fv - V_POST_SLACK_VE, bb + 1), tb))
            if ts > 0:
                ve_orders.append(Order(VEVE_SYM, max(fv + V_POST_SLACK_VE, ba - 1), -ts))
            orders[VEVE_SYM] = ve_orders
        elif ve_layer_e:
            orders[VEVE_SYM] = list(ve_layer_e)

    spot = v_plain_mid(state.order_depths.get(VEVE_SYM))
    if spot is None:
        if vstate.last_spot is not None and vstate.spot_age < 20:
            spot = vstate.last_spot; vstate.spot_age += 1
        else:
            return orders
    else:
        vstate.last_spot = spot; vstate.spot_age = 0

    if vstate.spot_age > 3:
        return orders

    T = max(V_TTE_DAYS_AT_START - timestamp / 1_000_000.0, 0.01) / V_TTE_YEAR

    for K in V_BS_STRIKES:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        wm_v = v_wall_mid(od_v)
        if wm_v is None: continue
        iv = v_implied_vol(wm_v, spot, K, T)
        if iv is not None:
            hist = vstate.iv_history.setdefault(K, [])
            hist.append(iv)
            if len(hist) > V_IV_ADAPT_WINDOW:
                del hist[:len(hist) - V_IV_ADAPT_WINDOW]

    sigma = v_get_adaptive_sigma(state, vstate)

    for K in VOUCHER_STRIKES_ALL:
        if K in VOUCHER_STRIKES_SKIP: continue
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None: continue
        existing = orders.get(sym, [])
        already_buy = sum(o.quantity for o in existing if o.quantity > 0)
        already_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        pos_v = state.position.get(sym, 0)
        tb = 300 - pos_v - already_buy
        ts = 300 + pos_v - already_sell
        intrinsic = max(spot - K, 0.0)
        deep_itm = K in VOUCHER_STRIKES_DEEP_ITM
        new_orders = []
        for p, v in sorted(od_v.sell_orders.items()):
            if tb > 0 and p < intrinsic - V_INTRINSIC_EDGE:
                q = min(tb, -v, V_INTRINSIC_QTY); new_orders.append(Order(sym, p, q)); tb -= q
        sell_thr = intrinsic + V_INTRINSIC_EDGE if deep_itm else spot + V_INTRINSIC_EDGE
        for p, v in sorted(od_v.buy_orders.items(), reverse=True):
            if ts > 0 and p > sell_thr:
                q = min(ts, v, V_INTRINSIC_QTY); new_orders.append(Order(sym, p, -q)); ts -= q
        if new_orders:
            orders.setdefault(sym, []).extend(new_orders)

    for K in V_BS_STRIKES:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        already_buy = sum(o.quantity for o in existing if o.quantity > 0)
        already_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        cur_pos_buy = pos_v + already_buy
        cur_pos_sell = pos_v - already_sell
        fv_bs = v_bs_call(spot, K, T, sigma)
        buy_thr = fv_bs - V_BS_EDGE
        sell_thr_bs = fv_bs + V_BS_EDGE
        new_orders = []
        for px in sorted(od_v.sell_orders.keys()):
            if px > buy_thr: break
            avail = -od_v.sell_orders[px]
            room = min(300 - cur_pos_buy, V_BS_POS_CAP - cur_pos_buy)
            size = min(V_BS_TRADE_SIZE, avail, room)
            if size > 0:
                new_orders.append(Order(sym, px, +size)); cur_pos_buy += size
        for px in sorted(od_v.buy_orders.keys(), reverse=True):
            if px < sell_thr_bs: break
            avail = od_v.buy_orders[px]
            room = min(300 + cur_pos_sell, V_BS_POS_CAP + cur_pos_sell)
            size = min(V_BS_TRADE_SIZE, avail, room)
            if size > 0:
                new_orders.append(Order(sym, px, -size)); cur_pos_sell -= size
        if new_orders:
            orders.setdefault(sym, []).extend(new_orders)

    committed_buy = {sym: 0 for sym in VOUCHER_SYM.values()}
    committed_sell = {sym: 0 for sym in VOUCHER_SYM.values()}
    for sym, ord_list in orders.items():
        if sym in committed_buy:
            committed_buy[sym] = sum(o.quantity for o in ord_list if o.quantity > 0)
            committed_sell[sym] = sum(-o.quantity for o in ord_list if o.quantity < 0)
    for K_lo, K_hi in itertools.combinations(VOUCHER_STRIKES_ALL, 2):
        if K_lo in VOUCHER_STRIKES_SKIP or K_hi in VOUCHER_STRIKES_SKIP: continue
        sym_lo = VOUCHER_SYM[K_lo]; sym_hi = VOUCHER_SYM[K_hi]
        od_lo = state.order_depths.get(sym_lo)
        od_hi = state.order_depths.get(sym_hi)
        if od_lo is None or od_hi is None: continue
        pos_lo = state.position.get(sym_lo, 0); pos_hi = state.position.get(sym_hi, 0)
        if od_lo.sell_orders and od_hi.buy_orders:
            ask_lo = min(od_lo.sell_orders); bid_hi = max(od_hi.buy_orders)
            if ask_lo - bid_hi < 0:
                ask_lo_vol = -od_lo.sell_orders[ask_lo]
                bid_hi_vol = od_hi.buy_orders[bid_hi]
                room_buy_lo = 300 - pos_lo - committed_buy[sym_lo]
                room_sell_hi = 300 + pos_hi - committed_sell[sym_hi]
                size = min(V_ARB_SIZE, ask_lo_vol, bid_hi_vol, room_buy_lo, room_sell_hi)
                if size > 0:
                    orders.setdefault(sym_lo, []).append(Order(sym_lo, ask_lo, +size))
                    orders.setdefault(sym_hi, []).append(Order(sym_hi, bid_hi, -size))
                    committed_buy[sym_lo] += size
                    committed_sell[sym_hi] += size

    for K in VOUCHER_STRIKES_TRADEABLE:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        vbb = max(od_v.buy_orders); vba = min(od_v.sell_orders)
        if vba - vbb < V_VOUCHER_MIN_SPREAD: continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        tb_v = 300 - pos_v - existing_buy
        ts_v = 300 + pos_v - existing_sell
        if tb_v > 0:
            orders.setdefault(sym, []).append(Order(sym, vbb + 1, min(tb_v, V_VOUCHER_MM_SIZE)))
        if ts_v > 0:
            orders.setdefault(sym, []).append(Order(sym, vba - 1, -min(ts_v, V_VOUCHER_MM_SIZE)))

    DEEP_ITM_MM_SIZE    = 30
    DEEP_ITM_POS_CAP    = 100
    DEEP_ITM_BID_OFFSET = 1
    DEEP_ITM_ASK_OFFSET = 1
    for K in VOUCHER_STRIKES_DEEP_ITM:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        intrinsic = max(spot - K, 0.0)
        if intrinsic <= 0: continue
        vbb = max(od_v.buy_orders); vba = min(od_v.sell_orders)
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)

        room_buy = DEEP_ITM_POS_CAP - pos_v - existing_buy
        if room_buy > 0:
            target_bid = int(round(intrinsic - DEEP_ITM_BID_OFFSET))
            bid_px = min(target_bid, vbb + 1)
            bid_px = max(1, bid_px)
            if bid_px <= vba - 1:
                qty = min(DEEP_ITM_MM_SIZE, room_buy)
                orders.setdefault(sym, []).append(Order(sym, bid_px, qty))

        room_sell = DEEP_ITM_POS_CAP + pos_v - existing_sell
        if room_sell > 0:
            target_ask = int(round(intrinsic + DEEP_ITM_ASK_OFFSET))
            ask_px = max(target_ask, vba - 1)
            if ask_px >= vbb + 1:
                qty = min(DEEP_ITM_MM_SIZE, room_sell)
                orders.setdefault(sym, []).append(Order(sym, ask_px, -qty))

    OTM_BID_SIZE = 5
    OTM_BID_POS_CAP = 50
    OTM_BID_EDGE = 2
    for K in VOUCHER_STRIKES_OTM_PASSIVE:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        bb = max(od_v.buy_orders)
        ba = min(od_v.sell_orders)
        fv_bs = v_bs_call(spot, K, T, sigma)
        bs_cap = math.floor(fv_bs - OTM_BID_EDGE)
        bid_px = min(bb + 1, bs_cap)
        if bid_px <= 0: continue
        if bid_px >= ba: continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        tb_v = OTM_BID_POS_CAP - pos_v - existing_buy
        if tb_v > 0:
            q = min(tb_v, OTM_BID_SIZE)
            orders.setdefault(sym, []).append(Order(sym, bid_px, q))

    return orders


class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orders      = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}

        hstate = HydrogelState.from_dict(raw.get("hg", {}))
        hydrogel_orders, hstate = run_hydrogel(state, hstate)
        orders[Product.HYDROGEL_PACK] = hydrogel_orders
        raw["hg"] = hstate.to_dict()

        vstate = VoucherState.from_dict(raw.get("v9", {}))
        voucher_orders = run_vouchers(state, vstate)
        for sym, ord_list in voucher_orders.items():
            if sym not in orders: orders[sym] = []
            orders[sym].extend(ord_list)
        raw["v9"] = vstate.to_dict()

        new_trader_data = json.dumps(raw)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data
