"""r3_combined_v22.py — HP improved + VEV directional + Voucher improved.

HP (from r3_hp_v22_improved.py):
  Layer 0  S17 GIGA SHORT         (v22 baseline)
  Layer 1  TREND-REVERSION SHORT  mid > ma200 + 25 -> short to -50, exit ma200+8
  Layer 2  MEAN-REVERSION LONG    mid < ma200 - 25 -> buy to +50, exit ma200-8
  Layer 3  IMPROVED FLIP EXIT     target 10020, trailing stop, timeout 1500
  Layer 4  FILTERED PASSIVE MM    suppress quotes when spread <= 8

VFE directional (from vev3.py — replaces Wall-Mid MM):
  VEV_4000 spread=22 consec>=3 + v4_mid >= Q75 → short VFE to -200
  Exit: quantile bottom flip to +200, take profit, stale, late, force flat
  $67,054 10k 3-day, $5,161 1k day2 (vs $2,328 old Wall-Mid MM)

Vouchers (from r3_voucher_v22_improvement.py, VFE MM removed):
  1. VEV_5000: Dedicated wide-spread MM (size 30, cap 300, inventory skew)
  2. OTM passive bids scaled: 5300 size=20/cap=200, 5400 size=20/cap=250, 5500 size=20/cap=300
  3. Spread=1 fix: post at bb (not bb+1) when spread==1 on OTM strikes
  4. Per-strike BS edges: 5300=4, 5400=3, 5500=2 (was uniform 10)
  5. VEV_5500 added to BS taking strikes
  6. VEV_6000/6500: Free OTM passive bids at 0
  7. Deep ITM cap 300
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


# ══════════════════════════════════════════════════════════════════════════════
# HYDROGEL_PACK — 5-layer improved strategy
# ══════════════════════════════════════════════════════════════════════════════

class HydrogelParams:
    # S17 GIGA SHORT (Layer 0)
    REGIME2_SPREAD = 17
    ENTRY_MID_MIN = 10010
    S7_WINDOW = 500
    S7_BOTTOM_Q = 0.08
    FLIP_TARGET = 200

    # FLIP EXIT (Layer 3)
    FLIP_EXIT_MID = 10020
    FLIP_TIMEOUT_TICKS = 1500
    FLIP_TRAIL_ENABLE = 10010
    FLIP_TRAIL_DELTA = 10

    # TREND-REVERSION SHORT (Layer 1)
    TR_MA_WINDOW = 200
    TR_ENTRY_OFFSET = 25
    TR_EXIT_OFFSET = 8
    TR_MAX_POS = 50

    # MEAN-REVERSION LONG (Layer 2)
    MR_ENTRY_OFFSET = 25
    MR_EXIT_OFFSET = 8
    MR_MAX_POS = 50

    # PASSIVE MM (Layer 4)
    POS_LIMIT = 200
    QUOTE_SIZE = 25
    MIN_MM_SPREAD = 8

    # Dynamic calibration
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

def _zscore(buf, value):
    mu = _mean(buf); sd = _std(buf)
    if mu is None or sd is None or sd == 0: return None
    return (value - mu) / sd

def _push(buf, value, maxlen):
    buf = buf + [value]
    return buf[-maxlen:] if len(buf) > maxlen else buf

def _clip(value, lo, hi):
    return max(lo, min(hi, value))

def _quantile(buf, q):
    if not buf:
        return None
    s = sorted(buf)
    idx = int(len(s) * q)
    return s[min(idx, len(s) - 1)]


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
        self.flip_peak_mid: float = 0.0
        self.tr_short_active: bool = False
        self.mr_long_active: bool = False
        self.prev_mid: Optional[float] = None
        self.prev_wap_edge: Optional[float] = None
        self.edge_buf: List[float] = []
        self.ret_buf: List[float] = []

    def to_dict(self):
        return {
            "buf500":  self.mid_buf_500,
            "buf100":  self.mid_buf_100,
            "row":     self.row,
            "s17_row": self.s17_entry_row,
            "s17_mid": self.s17_entry_mid,
            "s7_cov":  self.s7_covering,
            "fh":      self.flip_holding,
            "fer":     self.flip_entry_row,
            "fpk":     self.flip_peak_mid,
            "tr_s":    self.tr_short_active,
            "mr_l":    self.mr_long_active,
            "pmid":    self.prev_mid,
            "pedge":   self.prev_wap_edge,
            "edgeb":   self.edge_buf,
            "retb":    self.ret_buf,
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
        s.flip_peak_mid     = d.get("fpk", 0.0)
        s.tr_short_active   = d.get("tr_s", False)
        s.mr_long_active    = d.get("mr_l", False)
        s.prev_mid          = d.get("pmid")
        s.prev_wap_edge     = d.get("pedge")
        s.edge_buf          = d.get("edgeb", [])
        s.ret_buf           = d.get("retb", [])
        return s


def _get_ma200(hstate):
    buf = hstate.mid_buf_500
    if len(buf) < 200:
        return None
    return sum(buf[-200:]) / 200


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
    if not features:
        return orders, hstate

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

    ma200 = _get_ma200(hstate)

    # LAYER 0: S17 GIGA SHORT
    if hstate.s17_entry_row is not None and position < 0:
        hstate.tr_short_active = False
        hstate.mr_long_active = False

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

    # S7 cover + flip
    if hstate.s7_covering:
        remaining = p.FLIP_TARGET - position
        if remaining > 0:
            orders.append(Order(P, best_ask, remaining))
            logger.print(f"S7 FLIP BUILD: buy={remaining} px={best_ask} mid={mid:.1f} pos={position}")
        if position >= p.FLIP_TARGET:
            hstate.s7_covering    = False
            hstate.flip_holding   = True
            hstate.flip_entry_row = hstate.row
            hstate.flip_peak_mid  = mid
            logger.print(f"S7 FLIP COMPLETE -> HOLD: pos={position}")
        return orders, hstate

    # LAYER 3: IMPROVED FLIP HOLD
    if hstate.flip_holding:
        held_for = hstate.row - (hstate.flip_entry_row or hstate.row)

        if mid > hstate.flip_peak_mid:
            hstate.flip_peak_mid = mid

        trail_triggered = (
            hstate.flip_peak_mid >= p.FLIP_TRAIL_ENABLE
            and mid < hstate.flip_peak_mid - p.FLIP_TRAIL_DELTA
        )
        should_exit = (
            mid >= p.FLIP_EXIT_MID
            or trail_triggered
            or held_for >= p.FLIP_TIMEOUT_TICKS
        )

        if should_exit:
            if position > 0:
                reason = "mid_target"
                if trail_triggered:
                    reason = f"trail(peak={hstate.flip_peak_mid:.0f})"
                elif held_for >= p.FLIP_TIMEOUT_TICKS:
                    reason = "timeout"
                orders.append(Order(P, best_bid, -position))
                logger.print(
                    f"FLIP EXIT: sell {position} px={best_bid} mid={mid:.1f} "
                    f"held={held_for} reason={reason}"
                )
            hstate.flip_holding   = False
            hstate.flip_entry_row = None
            hstate.flip_peak_mid  = 0.0
        return orders, hstate

    # S17 ENTRY
    if (spread == p.REGIME2_SPREAD
            and mid > p.ENTRY_MID_MIN
            and hstate.s17_entry_row is None):
        hstate.tr_short_active = False
        hstate.mr_long_active = False

        headroom = pos_lim + position
        qty = min(pos_lim, headroom)
        if qty > 0:
            orders.append(Order(P, best_bid, -qty))
            hstate.s17_entry_row = hstate.row
            hstate.s17_entry_mid = mid
            logger.print(f"S17 ENTER short: qty={qty} px={best_bid} mid={mid:.1f}")
        return orders, hstate

    # LAYERS 1/2: DIRECTIONAL OVERLAYS (non-blocking)
    dir_buy_committed = 0
    dir_sell_committed = 0

    if ma200 is not None:
        # LAYER 1: TREND-REVERSION SHORT
        if hstate.tr_short_active:
            if mid <= ma200 + p.TR_EXIT_OFFSET:
                hstate.tr_short_active = False
                logger.print(f"TR SHORT EXIT: mid={mid:.1f} ma200={ma200:.1f}")
            else:
                target_short = -p.TR_MAX_POS
                if position > target_short:
                    sell_qty = min(position - target_short, pos_lim + position)
                    if sell_qty > 0:
                        orders.append(Order(P, best_bid, -sell_qty))
                        dir_sell_committed += sell_qty
                        logger.print(
                            f"TR SHORT BUILD: qty={sell_qty} px={best_bid} "
                            f"mid={mid:.1f} ma200={ma200:.1f} pos={position}"
                        )
        elif (mid > ma200 + p.TR_ENTRY_OFFSET
                and not hstate.mr_long_active
                and position > -p.TR_MAX_POS):
            hstate.tr_short_active = True
            sell_qty = min(p.TR_MAX_POS + position, pos_lim + position)
            if sell_qty > 0:
                orders.append(Order(P, best_bid, -sell_qty))
                dir_sell_committed += sell_qty
                logger.print(
                    f"TR SHORT ENTER: qty={sell_qty} px={best_bid} "
                    f"mid={mid:.1f} ma200={ma200:.1f} dev={mid - ma200:.1f}"
                )

        # LAYER 2: MEAN-REVERSION LONG
        if hstate.mr_long_active:
            if mid >= ma200 - p.MR_EXIT_OFFSET:
                hstate.mr_long_active = False
                logger.print(f"MR LONG EXIT: mid={mid:.1f} ma200={ma200:.1f}")
            else:
                target_long = p.MR_MAX_POS
                if position < target_long:
                    buy_qty = min(target_long - position, pos_lim - position)
                    if buy_qty > 0:
                        orders.append(Order(P, best_ask, buy_qty))
                        dir_buy_committed += buy_qty
                        logger.print(
                            f"MR LONG BUILD: qty={buy_qty} px={best_ask} "
                            f"mid={mid:.1f} ma200={ma200:.1f} pos={position}"
                        )
        elif (mid < ma200 - p.MR_ENTRY_OFFSET
                and not hstate.tr_short_active
                and position < p.MR_MAX_POS):
            hstate.mr_long_active = True
            buy_qty = min(p.MR_MAX_POS - position, pos_lim - position)
            if buy_qty > 0:
                orders.append(Order(P, best_ask, buy_qty))
                dir_buy_committed += buy_qty
                logger.print(
                    f"MR LONG ENTER: qty={buy_qty} px={best_ask} "
                    f"mid={mid:.1f} ma200={ma200:.1f} dev={ma200 - mid:.1f}"
                )

    # LAYER 4: PASSIVE MM
    if spread < p.MIN_MM_SPREAD:
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
    bid_headroom = pos_lim - position - dir_buy_committed
    ask_headroom = pos_lim + position - dir_sell_committed

    base_bid = min(fv - slack, best_bid + 1)
    base_ask = max(fv + slack, best_ask - 1)
    my_bid   = int(round(base_bid + bid_offset))
    my_ask   = int(round(base_ask + bid_offset))
    my_bid   = max(my_bid, best_bid + 1)
    my_ask   = min(my_ask, best_ask - 1)
    my_bid   = min(my_bid, best_ask - 1)
    my_ask   = max(my_ask, best_bid + 1)
    if my_ask <= my_bid:
        my_ask = my_bid + 1

    bid_qty = min(p.QUOTE_SIZE, max(0, bid_headroom))
    ask_qty = min(p.QUOTE_SIZE, max(0, ask_headroom))

    if bid_qty > 0:
        orders.append(Order(P, my_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order(P, my_ask, -ask_qty))

    return orders, hstate


# ══════════════════════════════════════════════════════════════════════════════
# VEV_4000 signal → VELVETFRUIT_EXTRACT directional (from vev3.py)
# ══════════════════════════════════════════════════════════════════════════════

class VEVParams:
    S22_CLUSTER_MIN = 3
    PEAK_WINDOW = 300
    PEAK_Q = 0.75
    MIN_SIGNAL_WARMUP = 75
    COVER_WINDOW = 500
    COVER_Q = 0.08
    MIN_COVER_WARMUP = 500
    TAKE_PROFIT = 35.0
    STALE_TICKS = 500
    STALE_PROFIT = 15
    LATE_AGGRESSIVE_AFTER = 930_000
    LATE_PROFIT = 15
    FORCE_FLAT_AFTER = 970_000
    NO_ENTRY_AFTER = 950_000
    EXTRACT_LIMIT = 200
    SHORT_TARGET = -200
    LONG_TARGET = 200
    FLAT_TARGET = 0


class VEVState:
    def __init__(self):
        self.s22_consec: int = 0
        self.vev4k_buf: List[float] = []
        self.S_buf: List[float] = []
        self.in_short: bool = False
        self.covering: bool = False
        self.cover_target: int = 0
        self.entry_S_mid: Optional[float] = None
        self.entry_ts: Optional[int] = None

    def to_dict(self):
        return {
            "s22": self.s22_consec,
            "v4b": self.vev4k_buf,
            "sb": self.S_buf,
            "short": self.in_short,
            "cov": self.covering,
            "cov_tgt": self.cover_target,
            "entryS": self.entry_S_mid,
            "entryTs": self.entry_ts,
        }

    @staticmethod
    def from_dict(d):
        vs = VEVState()
        vs.s22_consec = d.get("s22", 0)
        vs.vev4k_buf = d.get("v4b", [])
        vs.S_buf = d.get("sb", [])
        vs.in_short = d.get("short", False)
        vs.covering = d.get("cov", False)
        vs.cover_target = d.get("cov_tgt", 0)
        vs.entry_S_mid = d.get("entryS")
        vs.entry_ts = d.get("entryTs")
        return vs


def _vev_order_to_target(symbol, pos, target, bid, ask):
    if target > pos:
        return [Order(symbol, ask, target - pos)]
    if target < pos:
        return [Order(symbol, bid, -(pos - target))]
    return []


def run_vev(state: TradingState, vevstate: VEVState):
    p = VEVParams
    out: Dict[str, List[Order]] = {}
    VFE = Product.VELVETFRUIT_EXTRACT

    if VFE not in state.order_depths:
        return out, vevstate

    S_od = state.order_depths[VFE]
    if not S_od.buy_orders or not S_od.sell_orders:
        return out, vevstate

    S_bid = max(S_od.buy_orders)
    S_ask = min(S_od.sell_orders)
    S_mid = (S_bid + S_ask) / 2.0
    pos_S = state.position.get(VFE, 0)
    day_time = state.timestamp % 1_000_000

    # Require VEV_4000
    v4_sym = Product.VEV_4000
    if v4_sym not in state.order_depths:
        return out, vevstate
    v4_od = state.order_depths[v4_sym]
    if not v4_od.buy_orders or not v4_od.sell_orders:
        return out, vevstate

    v4_bid = max(v4_od.buy_orders)
    v4_ask = min(v4_od.sell_orders)
    v4_spread = v4_ask - v4_bid
    v4_mid = (v4_bid + v4_ask) / 2.0

    # Update buffers
    vevstate.vev4k_buf = _push(vevstate.vev4k_buf, v4_mid, p.PEAK_WINDOW)
    vevstate.S_buf = _push(vevstate.S_buf, S_mid, p.COVER_WINDOW)

    if v4_spread == 22:
        vevstate.s22_consec += 1
    else:
        vevstate.s22_consec = 0

    peak_ready = len(vevstate.vev4k_buf) >= p.MIN_SIGNAL_WARMUP
    cover_ready = len(vevstate.S_buf) >= p.MIN_COVER_WARMUP
    peak_thresh = _quantile(vevstate.vev4k_buf, p.PEAK_Q) if peak_ready else None
    cover_thresh = _quantile(vevstate.S_buf, p.COVER_Q) if cover_ready else None

    # Active cover/flip
    if vevstate.covering:
        target = vevstate.cover_target
        out[VFE] = _vev_order_to_target(VFE, pos_S, target, S_bid, S_ask)
        if pos_S == target:
            vevstate.covering = False
            vevstate.cover_target = 0
            vevstate.in_short = False
            vevstate.entry_S_mid = None
            vevstate.entry_ts = None
        return out, vevstate

    # Manage short position
    if vevstate.in_short:
        profit_ticks = 0.0
        held_ticks = 0
        if vevstate.entry_S_mid is not None:
            profit_ticks = vevstate.entry_S_mid - S_mid
        if vevstate.entry_ts is not None:
            held_ticks = max(0, int((state.timestamp - vevstate.entry_ts) // 100))

        bottom_cover = cover_ready and cover_thresh is not None and S_mid <= cover_thresh
        profit_cover = profit_ticks >= p.TAKE_PROFIT
        stale_cover = held_ticks >= p.STALE_TICKS and profit_ticks >= p.STALE_PROFIT
        late_cover = day_time >= p.LATE_AGGRESSIVE_AFTER and profit_ticks >= p.LATE_PROFIT
        force_flat = day_time >= p.FORCE_FLAT_AFTER

        if bottom_cover:
            target = p.LONG_TARGET
        elif profit_cover:
            target = p.FLAT_TARGET
        elif stale_cover:
            target = p.FLAT_TARGET
        elif late_cover:
            target = p.FLAT_TARGET
        elif force_flat:
            target = p.FLAT_TARGET
        else:
            target = None

        if target is not None:
            vevstate.covering = True
            vevstate.cover_target = target
            vevstate.in_short = False
            out[VFE] = _vev_order_to_target(VFE, pos_S, target, S_bid, S_ask)
            return out, vevstate

        out[VFE] = _vev_order_to_target(VFE, pos_S, p.SHORT_TARGET, S_bid, S_ask)
        return out, vevstate

    # Entry: VEV_4000 spread=22 cluster + peak gate
    signal = (
        peak_ready
        and vevstate.s22_consec >= p.S22_CLUSTER_MIN
        and peak_thresh is not None
        and v4_mid >= peak_thresh
    )

    if signal and day_time < p.NO_ENTRY_AFTER:
        vevstate.in_short = True
        vevstate.covering = False
        vevstate.cover_target = 0
        vevstate.entry_S_mid = S_mid
        vevstate.entry_ts = state.timestamp
        out[VFE] = _vev_order_to_target(VFE, pos_S, p.SHORT_TARGET, S_bid, S_ask)
        return out, vevstate

    return out, vevstate


# ══════════════════════════════════════════════════════════════════════════════
# VFE / Voucher strategy — IMPROVED from v22 (VFE MM removed → handled by run_vev)
# ══════════════════════════════════════════════════════════════════════════════

VEVE_SYM = "VELVETFRUIT_EXTRACT"
VOUCHER_STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VOUCHER_STRIKES_TRADEABLE = [5100, 5200, 5300, 5400]  # 5000 removed — dedicated MM
VOUCHER_STRIKES_DEEP_ITM = [4000, 4500]
VOUCHER_STRIKES_SKIP = set()  # v22 skipped 6000/6500; now traded via free OTM layer
VOUCHER_STRIKES_FREE_OTM = [6000, 6500]
VOUCHER_STRIKES_OTM_PASSIVE = [5300, 5400, 5500]
VOUCHER_SYM = {k: f"VEV_{k}" for k in VOUCHER_STRIKES_ALL}
V_TTE_DAYS_AT_START = 5.0
V_TTE_YEAR = 250.0
V_INTRINSIC_EDGE = 2
V_INTRINSIC_QTY = 50
V_ARB_SIZE = 10
V_VOUCHER_MM_SIZE = 20
V_VOUCHER_MIN_SPREAD = 2
V_BS_SIGMA_DEFAULT = 0.18
V_BS_TRADE_SIZE = 30
V_BS_POS_CAP = 200  # 300 over-accumulates on OTM; 200 is the sweet spot
V_BS_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
V_BS_EDGE_MAP = {
    5000: 10, 5100: 10, 5200: 10,
    5300: 4, 5400: 3, 5500: 2,
}
V_IV_ADAPT_WINDOW = 50
V_IV_ADAPT_MIN_HIST = 15

V_5000_MM_SIZE = 30
V_5000_POS_CAP = 300
V_5000_SKEW_THRESH = 120

OTM_BID_PARAMS = {
    5300: {"size": 20, "cap": 200, "edge": 1},
    5400: {"size": 20, "cap": 250, "edge": 1},
    5500: {"size": 20, "cap": 300, "edge": 1},
}


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

    def to_dict(self):
        return {
            "ivh": {str(k): v[-V_IV_ADAPT_WINDOW:] for k, v in self.iv_history.items()},
            "ls": self.last_spot,
            "sa": self.spot_age,
        }

    @staticmethod
    def from_dict(d):
        s = VoucherState()
        s.iv_history = {int(k): list(v) for k, v in d.get("ivh", {}).items()}
        for k in V_BS_STRIKES:
            if k not in s.iv_history: s.iv_history[k] = []
        s.last_spot = d.get("ls")
        s.spot_age = d.get("sa", 0)
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

    # VFE is now handled by run_vev (directional strategy)

    # Spot for BS pricing
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

    # IV history update
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

    # Intrinsic arb
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

    # BS taking — per-strike edges
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
        bs_edge = V_BS_EDGE_MAP.get(K, 10.0)
        buy_thr = fv_bs - bs_edge
        sell_thr_bs = fv_bs + bs_edge
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

    # Call-spread arb
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

    # Generic passive MM on ATM strikes (5000 removed — dedicated layer)
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

    # VEV_5000 dedicated wide-spread MM
    sym_5k = VOUCHER_SYM[5000]
    od_5k = state.order_depths.get(sym_5k)
    if od_5k and od_5k.buy_orders and od_5k.sell_orders:
        vbb = max(od_5k.buy_orders); vba = min(od_5k.sell_orders)
        v_spread = vba - vbb
        if v_spread >= 3:
            pos_v = state.position.get(sym_5k, 0)
            existing = orders.get(sym_5k, [])
            existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
            existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)

            bid_widen = 1 if pos_v > V_5000_SKEW_THRESH else 0
            ask_widen = 1 if pos_v < -V_5000_SKEW_THRESH else 0

            bid_px = vbb + 1 + bid_widen
            ask_px = vba - 1 - ask_widen

            if bid_px >= ask_px:
                bid_px = vbb + 1
                ask_px = vba - 1
            if bid_px <= vbb: bid_px = vbb + 1
            if ask_px >= vba: ask_px = vba - 1

            room_buy = V_5000_POS_CAP - pos_v - existing_buy
            room_sell = V_5000_POS_CAP + pos_v - existing_sell
            room_buy = min(room_buy, 300 - pos_v - existing_buy)
            room_sell = min(room_sell, 300 + pos_v - existing_sell)

            if room_buy > 0 and bid_px < ask_px:
                qty = min(V_5000_MM_SIZE, room_buy)
                orders.setdefault(sym_5k, []).append(Order(sym_5k, bid_px, qty))
            if room_sell > 0 and ask_px > bid_px:
                qty = min(V_5000_MM_SIZE, room_sell)
                orders.setdefault(sym_5k, []).append(Order(sym_5k, ask_px, -qty))

    # Deep ITM theta carry MM
    DEEP_ITM_MM_SIZE    = 30
    DEEP_ITM_POS_CAP    = 300
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

    # Scaled OTM passive bids with spread=1 fix
    for K in VOUCHER_STRIKES_OTM_PASSIVE:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        bb = max(od_v.buy_orders)
        ba = min(od_v.sell_orders)
        v_spread = ba - bb

        params = OTM_BID_PARAMS.get(K, {"size": 5, "cap": 50, "edge": 2})
        fv_bs = v_bs_call(spot, K, T, sigma)
        bs_cap = math.floor(fv_bs - params["edge"])

        if v_spread == 1:
            bid_px = min(bb, bs_cap)
        else:
            bid_px = min(bb + 1, bs_cap)

        if bid_px <= 0: continue
        if bid_px >= ba: continue

        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        tb_v = params["cap"] - pos_v - existing_buy
        tb_v = min(tb_v, 300 - pos_v - existing_buy)
        if tb_v > 0:
            q = min(tb_v, params["size"])
            orders.setdefault(sym, []).append(Order(sym, bid_px, q))

    # Free OTM passive bids on VEV_6000/6500
    FREE_OTM_BID_SIZE = 50
    FREE_OTM_POS_CAP = 300
    for K in VOUCHER_STRIKES_FREE_OTM:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        bb = max(od_v.buy_orders)
        ba = min(od_v.sell_orders)
        if bb > 1 or ba > 2: continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        room = min(FREE_OTM_POS_CAP - pos_v - existing_buy,
                    300 - pos_v - existing_buy)
        if room > 0:
            q = min(FREE_OTM_BID_SIZE, room)
            orders.setdefault(sym, []).append(Order(sym, bb, q))

    return orders


# ══════════════════════════════════════════════════════════════════════════════
# Trader
# ══════════════════════════════════════════════════════════════════════════════

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

        vevstate = VEVState.from_dict(raw.get("vev", {}))
        vev_orders, vevstate = run_vev(state, vevstate)
        for sym, ord_list in vev_orders.items():
            orders[sym] = ord_list
        raw["vev"] = vevstate.to_dict()

        vstate = VoucherState.from_dict(raw.get("v9", {}))
        voucher_orders = run_vouchers(state, vstate)
        for sym, ord_list in voucher_orders.items():
            if sym not in orders: orders[sym] = []
            orders[sym].extend(ord_list)
        raw["v9"] = vstate.to_dict()

        new_trader_data = json.dumps(raw)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data
