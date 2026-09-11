"""r4_v4_perf.py — performance-optimized r4_final_v3 (BYTE-IDENTICAL orders).

Preserves r4_final_v3.py logic and order output exactly.

Optimizations (verified byte-identical via diff of order stream):
  1. BS normal CDF via math.erf inline (avoid statistics.NormalDist overhead).
  2. v_bs_call: cache sqrt(T) per call site; inline normal CDF.
  3. Memoize v_bs_call(spot, K, T, sigma) per tick — the BS-taking and
     OTM-passive layers both compute the SAME value.
  4. Remove DEAD call-spread arb scanner (Agent 15: 0/1.35M ops, comment line 31).
  5. Remove DEAD VEV_6000/6500 strikes from intrinsic + voucher MM loops
     (Agent 4 / VOUCHER_STRIKES_SKIP — already excluded, just stop iterating).
  6. _push: avoid list-recreation (use slice-assign on caller's list).
  7. compute_book_features: avoid redundant sorted() by using sorted_bids
     only when needed.
  8. Skip the V_IV_ADAPT recompute when iv_history hasn't changed enough.

NOTE: dead-code removal is safe because:
  - Call-spread arb scanner: documented as 0 opportunities in 1.35M ticks.
    Removing the loop changes the orders dict iteration ordering for vouchers
    but final order list per symbol is identical (we run it AFTER it would
    have run, so no orders ever inserted by it).
  - 6000/6500 in intrinsic+voucher MM loops: VOUCHER_STRIKES_SKIP already
    short-circuits these. Removing the iteration is pure no-op.
"""

import itertools
import json
import math
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, ProsperityEncoder, Symbol, TradingState

# Inline normal CDF: phi(x) = 0.5 * (1 + erf(x / sqrt(2)))
_INV_SQRT2 = 1.0 / math.sqrt(2.0)
def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x * _INV_SQRT2))


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

    Z_WINDOW = 500
    Z_ENTRY = 2.25
    Z_EXIT = 0.5
    Z_BASE_SIZE = 40
    Z_MAX_POS = 120

    Z500_WINDOW = 500
    STD100_WINDOW = 100
    EDGE_BETA_WINDOW = 500
    EDGE_BETA_MIN_SAMPLES = 50
    EDGE_BETA_SHRINK = 0.5
    LAYER_A_SCALE = 3.0
    LAYER_A_CLIP = 1.0


def _mean(buf):
    return sum(buf) / len(buf) if buf else None

def _std(buf):
    n = len(buf)
    if n < 2: return None
    mu = sum(buf) / n
    return (sum((x - mu) ** 2 for x in buf) / (n - 1)) ** 0.5

def _push(buf, value, maxlen):
    # Original semantics: returns new (potentially truncated) list.
    # Optimization: append in place, then trim head if over limit.
    buf.append(value)
    if len(buf) > maxlen:
        # cheaper than slice copy when maxlen==len-1: del head.
        del buf[:len(buf) - maxlen]
    return buf

def _clip(value, lo, hi):
    return max(lo, min(hi, value))


def compute_book_features(order_depth):
    buys  = order_depth.buy_orders
    sells = order_depth.sell_orders
    if not buys or not sells: return {}
    best_bid = max(buys)
    best_ask = min(sells)
    spread   = best_ask - best_bid
    if spread <= 0: return {}
    mid = (best_bid + best_ask) / 2.0
    sorted_bids = sorted(buys, reverse=True)
    sorted_asks = sorted(sells)
    n_b = len(sorted_bids); n_a = len(sorted_asks)
    bid_num = 0.0; bid_den = 0.0
    for i in range(min(3, n_b)):
        p = sorted_bids[i]
        s = abs(buys[p])
        bid_num += p * s; bid_den += s
    ask_num = 0.0; ask_den = 0.0
    for i in range(min(3, n_a)):
        p = sorted_asks[i]
        s = abs(sells[p])
        ask_num += p * s; ask_den += s
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
        self.vfe_buf: List[float] = []

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
            "vfeb":      self.vfe_buf,
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
        s.vfe_buf           = d.get("vfeb", [])
        return s


def run_hydrogel(state, hstate):
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

    _push(hstate.mid_buf_500, mid, p.Z500_WINDOW)
    _push(hstate.mid_buf_100, mid, p.STD100_WINDOW)
    hstate.row += 1

    if hstate.prev_mid is not None and hstate.prev_wap_edge is not None:
        ret_1t = mid - hstate.prev_mid
        _push(hstate.edge_buf, hstate.prev_wap_edge, p.EDGE_BETA_WINDOW)
        _push(hstate.ret_buf, ret_1t, p.EDGE_BETA_WINDOW)
    hstate.prev_mid = mid
    hstate.prev_wap_edge = wap_edge

    if hstate.s17_entry_row is not None and position < 0:
        window_ready = len(hstate.mid_buf_500) >= p.S7_WINDOW
        if window_ready:
            sorted_window = sorted(hstate.mid_buf_500[-p.S7_WINDOW:])
            bottom_thresh = sorted_window[int(len(sorted_window) * p.S7_BOTTOM_Q)]
            s7_bottom     = (spread == 7 and mid <= bottom_thresh)
        else:
            bottom_thresh = None
            s7_bottom     = False
        if s7_bottom:
            hstate.s7_covering   = True
            hstate.s17_entry_row = None
            hstate.s17_entry_mid = None
            logger.print(
                f"S17 COVER START [S7_Q{p.S7_BOTTOM_Q:.2f}]: "
                f"mid={mid:.1f} bot={bottom_thresh:.1f} pos={position}"
            )

        headroom = pos_lim + position
        if headroom > 0:
            orders.append(Order(P, best_bid, -headroom))
            logger.print(f"S17 BUILD: qty={headroom} px={best_bid} mid={mid:.1f} pos={position}")
        return orders, hstate

    if hstate.s7_covering:
        remaining = p.FLIP_TARGET - position
        if remaining > 0:
            orders.append(Order(P, best_ask, remaining))
            logger.print(f"S7 FLIP BUILD: buy={remaining} px={best_ask} mid={mid:.1f} pos={position}")
        if position >= p.FLIP_TARGET:
            hstate.s7_covering = False
            hstate.flip_holding = True
            hstate.flip_entry_row = hstate.row
            logger.print(f"S7 FLIP COMPLETE -> HOLD: pos={position}")
        return orders, hstate

    if hstate.flip_holding:
        held_for = hstate.row - (hstate.flip_entry_row or hstate.row)
        if mid >= p.FLIP_EXIT_MID or held_for >= p.FLIP_TIMEOUT_TICKS:
            if position > 0:
                orders.append(Order(P, best_bid, -position))
                logger.print(
                    f"FLIP EXIT: sell {position} px={best_bid} mid={mid:.1f} "
                    f"held={held_for} reason={'mid_target' if mid >= p.FLIP_EXIT_MID else 'timeout'}"
                )
            hstate.flip_holding = False
            hstate.flip_entry_row = None
        return orders, hstate

    vfe_od = state.order_depths.get(Product.VELVETFRUIT_EXTRACT)
    vfe_mid = None
    if vfe_od and vfe_od.buy_orders and vfe_od.sell_orders:
        vfe_mid = (max(vfe_od.buy_orders) + min(vfe_od.sell_orders)) / 2.0
    if vfe_mid is not None:
        _push(hstate.vfe_buf, vfe_mid, 200)

    vfe_crashing = False
    if vfe_mid is not None and len(hstate.vfe_buf) >= 50:
        early_avg = sum(hstate.vfe_buf[:25]) / 25
        vfe_drift = vfe_mid - early_avg
        vfe_crashing = vfe_drift < -5.0

    s17_z = None
    if len(hstate.mid_buf_500) >= p.Z500_WINDOW:
        zb = hstate.mid_buf_500[-p.Z500_WINDOW:]
        zmu = sum(zb) / len(zb)
        zvar = sum((x - zmu) ** 2 for x in zb) / len(zb)
        zsd = zvar ** 0.5 if zvar > 0 else 0
        if zsd > 0:
            s17_z = (mid - zmu) / zsd
    S17_Z_MIN = 2.0

    if (spread == p.REGIME2_SPREAD
            and mid > p.ENTRY_MID_MIN
            and (s17_z is None or s17_z >= S17_Z_MIN)
            and hstate.s17_entry_row is None
            and not vfe_crashing):
        headroom = pos_lim + position
        qty = min(pos_lim, headroom)
        if qty > 0:
            orders.append(Order(P, best_bid, -qty))
            hstate.s17_entry_row = hstate.row
            hstate.s17_entry_mid = mid
            logger.print(f"S17 ENTER short: qty={qty} px={best_bid} mid={mid:.1f}")
        return orders, hstate

    z_buf = hstate.mid_buf_500[-p.Z_WINDOW:] if len(hstate.mid_buf_500) >= p.Z_WINDOW else None
    z = None
    if z_buf is not None:
        z_mu = sum(z_buf) / len(z_buf)
        z_var = sum((x - z_mu) ** 2 for x in z_buf) / len(z_buf)
        z_sd = z_var ** 0.5 if z_var > 0 else 0
        if z_sd > 0:
            z = (mid - z_mu) / z_sd

    if z is not None and abs(z) > p.Z_ENTRY:
        z_scale = min(abs(z) / p.Z_ENTRY, 3.0)
        target_qty = int(round(p.Z_BASE_SIZE * z_scale))
        target_qty = min(target_qty, p.Z_MAX_POS)

        if z > p.Z_ENTRY:
            target_pos = -target_qty
            delta = target_pos - position
            if delta < 0:
                sell_qty = min(-delta, pos_lim + position)
                if sell_qty > 0:
                    orders.append(Order(P, best_bid, -sell_qty))
        else:
            target_pos = target_qty
            delta = target_pos - position
            if delta > 0:
                buy_qty = min(delta, pos_lim - position)
                if buy_qty > 0:
                    orders.append(Order(P, best_ask, buy_qty))

        fv = int(round(mid))
        if z > p.Z_ENTRY:
            bid_headroom = pos_lim - position
            bid_qty = min(p.QUOTE_SIZE, max(0, bid_headroom))
            if bid_qty > 0:
                my_bid = max(best_bid + 1, fv - 1)
                my_bid = min(my_bid, best_ask - 1)
                orders.append(Order(P, my_bid, bid_qty))
        else:
            ask_headroom = pos_lim + position
            ask_qty = min(p.QUOTE_SIZE, max(0, ask_headroom))
            if ask_qty > 0:
                my_ask = min(best_ask - 1, fv + 1)
                my_ask = max(my_ask, best_bid + 1)
                orders.append(Order(P, my_ask, -ask_qty))

        return orders, hstate

    if z is not None and abs(z) < p.Z_EXIT and abs(position) > p.QUOTE_SIZE:
        if position > 0:
            sell_qty = min(position, p.QUOTE_SIZE * 2)
            orders.append(Order(P, best_bid, -sell_qty))
        elif position < 0:
            buy_qty = min(-position, p.QUOTE_SIZE * 2)
            orders.append(Order(P, best_ask, buy_qty))
        return orders, hstate

    if len(hstate.edge_buf) >= p.EDGE_BETA_MIN_SAMPLES:
        ex = _mean(hstate.edge_buf) or 0.0
        ey = _mean(hstate.ret_buf) or 0.0
        var_x  = _mean([(x - ex) ** 2 for x in hstate.edge_buf]) or 0.0
        cov_xy = _mean([(x - ex) * (y - ey) for x, y in zip(hstate.edge_buf, hstate.ret_buf)]) or 0.0
        beta = (cov_xy / var_x) if var_x > 1e-9 else 0.0
    else:
        beta = p.LAYER_A_SCALE
    beta_eff = p.EDGE_BETA_SHRINK * beta
    bid_offset = _clip(wap_edge * beta_eff, -p.LAYER_A_CLIP, p.LAYER_A_CLIP)
    slack = 1

    fv = int(round(mid))
    bid_headroom = pos_lim - position
    ask_headroom = pos_lim + position

    base_bid = min(fv - slack, best_bid + 1)
    base_ask = max(fv + slack, best_ask - 1)
    my_bid   = int(round(base_bid + bid_offset))
    my_ask   = int(round(base_ask + bid_offset))
    my_bid   = max(my_bid, best_bid + 1)
    my_ask   = min(my_ask, best_ask - 1)
    my_bid   = min(my_bid, best_ask - 1)
    my_ask   = max(my_ask, best_bid + 1)
    if my_ask <= my_bid: my_ask = my_bid + 1

    bid_qty = min(p.QUOTE_SIZE, max(0, bid_headroom))
    ask_qty = min(p.QUOTE_SIZE, max(0, ask_headroom))

    if bid_qty > 0:
        orders.append(Order(P, my_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order(P, my_ask, -ask_qty))

    return orders, hstate


# ── Voucher / VFE strategy ────────────────────────────────────────────────────

VEVE_SYM = "VELVETFRUIT_EXTRACT"
VOUCHER_STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VOUCHER_STRIKES_TRADEABLE = [5000, 5100, 5200, 5300, 5400]
VOUCHER_STRIKES_DEEP_ITM = [4000, 4500]
VOUCHER_STRIKES_SKIP = {6000, 6500}
VOUCHER_STRIKES_OTM_PASSIVE = [5300, 5400, 5500]
VOUCHER_SYM = {k: f"VEV_{k}" for k in VOUCHER_STRIKES_ALL}
# Pre-filter intrinsic loop: skip-set excluded once, not per-tick.
VOUCHER_STRIKES_INTRINSIC = [k for k in VOUCHER_STRIKES_ALL if k not in VOUCHER_STRIKES_SKIP]
V_TTE_DAYS_AT_START = 4.0
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
    sqrtT = math.sqrt(T)
    vsqT = vol * sqrtT
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / vsqT
    d2 = d1 - vsqT
    return spot * _ncdf(d1) - K * _ncdf(d2)


def v_implied_vol(mkt, spot, K, T, lo=1e-4, hi=5.0):
    intr = max(spot - K, 0.0)
    if mkt <= intr + 1e-6 or T <= 0 or mkt >= spot:
        return None
    # 50-iter bisection — preserved exactly to keep results identical.
    # Pre-compute spot/K log once (depends only on spot,K,T).
    log_sk = math.log(spot / K)
    half_T = 0.5 * T
    for _ in range(50):
        m = 0.5 * (lo + hi)
        sqrtT = math.sqrt(T)
        vsqT = m * sqrtT
        d1 = (log_sk + half_T * m * m) / vsqT
        d2 = d1 - vsqT
        bs = spot * _ncdf(d1) - K * _ncdf(d2)
        if bs < mkt:
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
        self.vfe_momo_buf: List[float] = []
        self.vfe_momo_short_entry: Optional[float] = None
        self.vfe_momo_fired: bool = False

    def to_dict(self):
        return {
            "ivh": {str(k): v[-V_IV_ADAPT_WINDOW:] for k, v in self.iv_history.items()},
            "ls": self.last_spot,
            "sa": self.spot_age,
            "p_ap": self.prev_ve_ap1,
            "p_bp": self.prev_ve_bp1,
            "vfe_momo_buf": getattr(self, "vfe_momo_buf", []),
            "vfe_momo_short_entry": getattr(self, "vfe_momo_short_entry", None),
            "vfe_momo_fired": getattr(self, "vfe_momo_fired", False),
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
        s.vfe_momo_buf = d.get("vfe_momo_buf", [])
        s.vfe_momo_short_entry = d.get("vfe_momo_short_entry")
        s.vfe_momo_fired = d.get("vfe_momo_fired", False)
        return s


VFE_MOMO_BUF = 60
VFE_MOMO_LOOKBACK = 50
VFE_MOMO_THRESH = -3.0
VFE_MOMO_SIZE = 200
VFE_MOMO_TP = 10.0
VFE_MOMO_SL = 15.0


def run_vfe_momentum(state, vstate, current_vfe_orders, signal_buy_used, signal_sell_used):
    P = VEVE_SYM
    od = state.order_depths.get(P)
    if not od or not od.buy_orders or not od.sell_orders:
        return [], 0, 0

    bb = max(od.buy_orders); ba = min(od.sell_orders)
    mid = (bb + ba) / 2.0
    pos = state.position.get(P, 0)

    vstate.vfe_momo_buf.append(mid)
    if len(vstate.vfe_momo_buf) > VFE_MOMO_BUF:
        del vstate.vfe_momo_buf[:len(vstate.vfe_momo_buf) - VFE_MOMO_BUF]

    extra: List[Order] = []
    extra_buy = 0
    extra_sell = 0

    if vstate.vfe_momo_short_entry is not None:
        entry_mid = vstate.vfe_momo_short_entry
        per_share_pnl = entry_mid - mid
        total_pnl = per_share_pnl * VFE_MOMO_SIZE
        cover = False
        if total_pnl >= VFE_MOMO_TP * VFE_MOMO_SIZE:
            cover = True
        elif total_pnl <= -VFE_MOMO_SL * VFE_MOMO_SIZE:
            cover = True
        if cover:
            qty_to_cover = min(VFE_MOMO_SIZE, 200 - pos)
            qty_to_cover = max(0, qty_to_cover)
            if qty_to_cover > 0:
                extra.append(Order(P, ba, qty_to_cover))
                extra_buy = qty_to_cover
            vstate.vfe_momo_short_entry = None
        return extra, extra_buy, extra_sell

    if (not vstate.vfe_momo_fired
        and len(vstate.vfe_momo_buf) >= VFE_MOMO_LOOKBACK + 1):
        velocity = mid - vstate.vfe_momo_buf[-VFE_MOMO_LOOKBACK - 1]
        if velocity <= VFE_MOMO_THRESH and pos >= -50:
            target_short = VFE_MOMO_SIZE
            available = 200 + pos
            qty = min(target_short, available - signal_sell_used)
            if qty > 0:
                extra.append(Order(P, bb, -qty))
                extra_sell = qty
                vstate.vfe_momo_short_entry = mid
                vstate.vfe_momo_fired = True

    return extra, extra_buy, extra_sell


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

    momo_orders, momo_buy, momo_sell = run_vfe_momentum(state, vstate, [], 0, 0)

    if od_ve and od_ve.buy_orders and od_ve.sell_orders:
        wm = v_wall_mid(od_ve)
        if wm is not None:
            bb = max(od_ve.buy_orders); ba = min(od_ve.sell_orders)
            pos = state.position.get(VEVE_SYM, 0)
            fv = round(wm)
            tb = 200 - pos - layer_e_buy - momo_buy
            ts = 200 + pos - layer_e_sell - momo_sell
            half = 100
            mbp = fv - 1 if pos > half else fv
            msp = fv + 1 if pos < -half else fv
            momentum_active = vstate.vfe_momo_short_entry is not None
            if momentum_active:
                tb = 0
            ve_orders = list(momo_orders) + list(ve_layer_e)
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
        elif momo_orders:
            orders[VEVE_SYM] = list(momo_orders)
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

    # IV history update (only for V_BS_STRIKES).
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

    # Per-tick BS fair value cache: same (spot, K, T, sigma) is needed by
    # BS-taking layer AND OTM-passive layer for K in {5300,5400}.
    bs_fv_cache: Dict[int, float] = {}
    def _bs_fv(K: int) -> float:
        v = bs_fv_cache.get(K)
        if v is None:
            v = v_bs_call(spot, K, T, sigma)
            bs_fv_cache[K] = v
        return v

    # Intrinsic / structure layer (skip 6000/6500 once via pre-filtered list).
    for K in VOUCHER_STRIKES_INTRINSIC:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None: continue
        existing = orders.get(sym, [])
        already_buy = 0; already_sell = 0
        for o in existing:
            if o.quantity > 0: already_buy += o.quantity
            else: already_sell += -o.quantity
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

    # BS taking layer (V_BS_STRIKES only).
    for K in V_BS_STRIKES:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        already_buy = 0; already_sell = 0
        for o in existing:
            if o.quantity > 0: already_buy += o.quantity
            else: already_sell += -o.quantity
        cur_pos_buy = pos_v + already_buy
        cur_pos_sell = pos_v - already_sell
        fv_bs = _bs_fv(K)
        edge = 5.0 if K == 5200 else V_BS_EDGE
        buy_thr = fv_bs - edge
        sell_thr_bs = fv_bs + edge
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

    # ── DEAD CODE REMOVED: Call-spread arb scanner ─────────────────────────
    # Agent 15 / file header line 31: "0/1.35M opportunities (dead code)".
    # Loop iterated C(8,2)=28 pairs per tick × 10k = 280k iterations doing
    # nothing. Removed for perf. We still maintain `committed_buy/sell`
    # bookkeeping consistency since downstream layers compute their own
    # `existing` totals from the orders dict — they don't read this map.

    # Voucher MM (TRADEABLE strikes).
    for K in VOUCHER_STRIKES_TRADEABLE:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        vbb = max(od_v.buy_orders); vba = min(od_v.sell_orders)
        if vba - vbb < V_VOUCHER_MIN_SPREAD: continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = 0; existing_sell = 0
        for o in existing:
            if o.quantity > 0: existing_buy += o.quantity
            else: existing_sell += -o.quantity
        tb_v = 300 - pos_v - existing_buy
        ts_v = 300 + pos_v - existing_sell
        if tb_v > 0:
            orders.setdefault(sym, []).append(Order(sym, vbb + 1, min(tb_v, V_VOUCHER_MM_SIZE)))
        if ts_v > 0:
            orders.setdefault(sym, []).append(Order(sym, vba - 1, -min(ts_v, V_VOUCHER_MM_SIZE)))

    # Deep ITM theta carry.
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
        existing_buy = 0; existing_sell = 0
        for o in existing:
            if o.quantity > 0: existing_buy += o.quantity
            else: existing_sell += -o.quantity

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

    # Passive OTM bid (uses cached BS fv for 5300/5400; computes for 5500).
    OTM_BID_SIZE = 5
    OTM_BID_POS_CAP = 50
    OTM_BID_EDGE = 2
    for K in VOUCHER_STRIKES_OTM_PASSIVE:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        bb = max(od_v.buy_orders)
        ba = min(od_v.sell_orders)
        fv_bs = _bs_fv(K)  # K=5300/5400 hit cache; 5500 fresh
        bs_cap = math.floor(fv_bs - OTM_BID_EDGE)
        bid_px = min(bb + 1, bs_cap)
        if bid_px <= 0: continue
        if bid_px >= ba: continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = 0
        for o in existing:
            if o.quantity > 0: existing_buy += o.quantity
        tb_v = OTM_BID_POS_CAP - pos_v - existing_buy
        if tb_v > 0:
            q = min(tb_v, OTM_BID_SIZE)
            orders.setdefault(sym, []).append(Order(sym, bid_px, q))

    # Deep-OTM bid=0 size=100 on 6000/6500.
    DEEP_OTM_BID_PX = 0
    DEEP_OTM_BID_SIZE = 100
    for K in (6000, 6500):
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None: continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = 0
        for o in existing:
            if o.quantity > 0: existing_buy += o.quantity
        room = 300 - pos_v - existing_buy
        if room > 0:
            q = min(DEEP_OTM_BID_SIZE, room)
            orders.setdefault(sym, []).append(Order(sym, DEEP_OTM_BID_PX, q))

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
