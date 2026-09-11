"""
HYDROGEL_PACK strategy (r3-hydro17-6-nohardcode).

Readable parameter taxonomy:
- ALPHA hardcodes: signal hypotheses for S17 entry / S7 bottom cover.
- INTRINSIC constants: market/exchange structure assumptions (limits, queue size).
- DYNAMIC knobs: rolling windows and online calibration controls.
"""

import json
import math
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, ProsperityEncoder, Symbol, TradingState


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
    # ========================= ALPHA hardcodes =========================
    # Hypothesis: spread=17 marks local peaks worth shorting.
    REGIME2_SPREAD = 17
    # Hypothesis: require elevated absolute price to avoid weak spread=17 events.
    ENTRY_MID_MIN = 10010
    # Hypothesis: spread=7 + rolling low-quantile marks bottoming regime.
    S7_WINDOW = 500
    S7_BOTTOM_Q = 0.08
    # Hypothesis: after S7 bottom, target long inventory for rebound capture.
    FLIP_TARGET = 200
    # Improved flip-hold exits (same as 461583):
    # - fixed mid target
    # - fixed trailing activation level
    # - fixed trailing delta
    FLIP_EXIT_OFFSET = 10
    FLIP_TIMEOUT_TICKS = 1500
    FLIP_TRAIL_ENABLE = 10010
    FLIP_TRAIL_DELTA = 10
    # Keep 10010 as anchor; if stale, switch entry gate to ma500 + offset.
    STALE_GATE_TICKS = 500
    STALE_GATE_OFFSET = 25
    # Hypothesis: price > ma200 + 25 marks a rare extension (~p97) worth fading.
    # 25 is structural -- approx 5x normal spread width, not a vol-derived number.
    # Tested: std-based derivation fails because it under-fires by 3-5x vs fixed.
    TR_ENTRY_OFFSET = 25
    # Hypothesis: price back within ma200 + 8 means extension has normalized.
    TR_EXIT_OFFSET = 8
    # Hypothesis: price < ma200 - 25 marks rare downside extension worth buying.
    MR_ENTRY_OFFSET = 25
    # Hypothesis: price back within ma200 - 8 means downside extension normalized.
    MR_EXIT_OFFSET = 8

    # ==================== INTRINSIC / structure ========================
    # Exchange position limit for HYDROGEL_PACK.
    POS_LIMIT = 200
    # Typical L1 size is almost always ~15-20 (by data); posting 25 is intentional queue capture sizing.
    QUOTE_SIZE = 25
    # Layer 1 trend-reversion short cap.
    TR_MAX_POS = 50
    # Layer 2 mean-reversion long cap.
    MR_MAX_POS = 50
    # Layer 4 passive MM: suppress quoting when spread is too tight.
    MIN_MM_SPREAD = 8

    # ===================== DYNAMIC calibration =========================
    # Rolling state buffers.
    Z500_WINDOW = 500
    STD100_WINDOW = 100
    # Online Layer-A beta = cov(edge, ret) / var(edge).
    EDGE_BETA_WINDOW = 500
    EDGE_BETA_MIN_SAMPLES = 50
    EDGE_BETA_SHRINK = 0.5
    # Fallback/cap for Layer-A offset before enough samples.
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
    buf = buf + [value]
    return buf[-maxlen:] if len(buf) > maxlen else buf

def _clip(value, lo, hi):
    return max(lo, min(hi, value))


def _ma_tail(buf, window):
    if len(buf) < window:
        return None
    tail = buf[-window:]
    return sum(tail) / window


def _quantile(buf, q):
    if not buf:
        return None
    s = sorted(buf)
    idx = int((len(s) - 1) * q)
    idx = max(0, min(len(s) - 1, idx))
    return s[idx]


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
    denom_L1     = bid_sz[0] + ask_sz[0]
    imbalance_L1 = (bid_sz[0] - ask_sz[0]) / denom_L1 if denom_L1 > 0 else 0.0
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
        "imbalance_L1": imbalance_L1,
        "book_wap_edge_L3": book_wap_edge_L3,
    }


class HydrogelState:
    def __init__(self):
        self.mid_buf_500: List[float] = []
        self.mid_buf_100: List[float] = []
        self.row: int = 0
        # Legacy fields kept only for backward-compatible traderData decoding.
        self.regime1_entry_row: Optional[int] = None
        self.regime1_qty: int = 0
        self.lean_target: float = 0.0
        self.lean_entry_mid: Optional[float] = None
        self.lean_entry_side: int = 0
        # S17 short tracking.
        self.s17_entry_row: Optional[int] = None   # row we entered the short
        self.s17_entry_mid: Optional[float] = None
        # S7 cover+flip phase flag.
        self.s7_covering: bool = False
        # Improved flip-hold state (after reaching +FLIP_TARGET).
        self.flip_holding: bool = False
        self.flip_entry_row: Optional[int] = None
        self.flip_peak_mid: float = 0.0
        # Layer 1 state.
        self.tr_short_active: bool = False
        # Layer 2 state.
        self.mr_long_active: bool = False
        # Online wap-edge calibration state.
        self.prev_mid: Optional[float] = None
        self.prev_wap_edge: Optional[float] = None
        self.edge_buf: List[float] = []
        self.ret_buf: List[float] = []
        self.last_10010_hit_row: Optional[int] = None

    def to_dict(self):
        return {
            "buf500":    self.mid_buf_500,
            "buf100":    self.mid_buf_100,
            "row":       self.row,
            "r1_row":    self.regime1_entry_row,
            "r1_qty":    self.regime1_qty,
            "lean":      self.lean_target,
            "lean_mid":  self.lean_entry_mid,
            "lean_side": self.lean_entry_side,
            "s17_row":   self.s17_entry_row,
            "s17_mid":   self.s17_entry_mid,
            "s7_cov":    self.s7_covering,
            "fh":        self.flip_holding,
            "fer":       self.flip_entry_row,
            "fpk":       self.flip_peak_mid,
            "trs":       self.tr_short_active,
            "mrl":       self.mr_long_active,
            "pmid":      self.prev_mid,
            "pedge":     self.prev_wap_edge,
            "edgeb":     self.edge_buf,
            "retb":      self.ret_buf,
            "h10010":    self.last_10010_hit_row,
        }

    @staticmethod
    def from_dict(d):
        s = HydrogelState()
        s.mid_buf_500       = d.get("buf500", [])
        s.mid_buf_100       = d.get("buf100", [])
        s.row               = d.get("row", 0)
        s.regime1_entry_row = d.get("r1_row")
        s.regime1_qty       = d.get("r1_qty", 0)
        s.lean_target       = d.get("lean", 0.0)
        s.lean_entry_mid    = d.get("lean_mid")
        s.lean_entry_side   = d.get("lean_side", 0)
        s.s17_entry_row     = d.get("s17_row")
        s.s17_entry_mid     = d.get("s17_mid")
        s.s7_covering       = d.get("s7_cov", False)
        s.flip_holding      = d.get("fh", False)
        s.flip_entry_row    = d.get("fer")
        s.flip_peak_mid     = d.get("fpk", 0.0)
        s.tr_short_active   = d.get("trs", False)
        s.mr_long_active    = d.get("mrl", False)
        s.prev_mid          = d.get("pmid")
        s.prev_wap_edge     = d.get("pedge")
        s.edge_buf          = d.get("edgeb", [])
        s.ret_buf           = d.get("retb", [])
        s.last_10010_hit_row = d.get("h10010")
        return s

    @staticmethod
    def load(trader_data):
        if not trader_data: return HydrogelState()
        try:
            raw = json.loads(trader_data)
            return HydrogelState.from_dict(raw.get("hg", {}))
        except Exception:
            return HydrogelState()

    def save(self, trader_data):
        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}
        raw["hg"] = self.to_dict()
        return json.dumps(raw)


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

    # Update buffers
    hstate.mid_buf_500 = _push(hstate.mid_buf_500, mid, p.Z500_WINDOW)
    hstate.mid_buf_100 = _push(hstate.mid_buf_100, mid, p.STD100_WINDOW)
    hstate.row += 1

    # Update online edge->return samples: pair prev tick's edge with this tick return.
    if hstate.prev_mid is not None and hstate.prev_wap_edge is not None:
        ret_1t = mid - hstate.prev_mid
        hstate.edge_buf = _push(hstate.edge_buf, hstate.prev_wap_edge, p.EDGE_BETA_WINDOW)
        hstate.ret_buf = _push(hstate.ret_buf, ret_1t, p.EDGE_BETA_WINDOW)
    hstate.prev_mid = mid
    hstate.prev_wap_edge = wap_edge
    # "Hit 10010" means 10010 is in the top 75% of recent prices,
    # i.e. above the rolling 25th percentile.
    q25 = _quantile(hstate.mid_buf_500, 0.25)
    if q25 is not None and p.ENTRY_MID_MIN >= q25:
        hstate.last_10010_hit_row = hstate.row

    effective_entry_mid_min = p.ENTRY_MID_MIN
    ma500 = _ma_tail(hstate.mid_buf_500, p.Z500_WINDOW)
    if ma500 is not None:
        last_hit = hstate.last_10010_hit_row
        ticks_since_hit = hstate.row if last_hit is None else (hstate.row - last_hit)
        if ticks_since_hit > p.STALE_GATE_TICKS:
            effective_entry_mid_min = ma500 + p.STALE_GATE_OFFSET
    effective_flip_trail_enable = effective_entry_mid_min
    effective_flip_exit_mid = effective_entry_mid_min + p.FLIP_EXIT_OFFSET

    # Layer 0A: S17 short with S7 bottom-based reversal trigger.
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
        should_cover = s7_bottom
        if should_cover:
            # S7 bottom fired: switch from short build to cover+flip phase.
            hstate.s7_covering  = True
            hstate.s17_entry_row = None
            hstate.s17_entry_mid = None
            logger.print(
                f"S17 COVER START [S7_Q{p.S7_BOTTOM_Q:.2f}]: "
                f"mid={mid:.1f} bot={bottom_thresh:.1f} pos={position}"
            )

        # Keep building short toward limit while still in S17 phase.
        headroom = pos_lim + position  # how much more we can short
        if headroom > 0:
            orders.append(Order(P, best_bid, -headroom))
            logger.print(f"S17 BUILD: qty={headroom} px={best_bid} mid={mid:.1f} pos={position}")
        return orders, hstate

    # Cover+flip phase: keep lifting ask until target long inventory reached.
    if hstate.s7_covering:
        hstate.tr_short_active = False
        hstate.mr_long_active = False
        remaining = p.FLIP_TARGET - position
        if remaining > 0:
            orders.append(Order(P, best_ask, remaining))
            logger.print(f"S7 FLIP BUILD: buy={remaining} px={best_ask} mid={mid:.1f} pos={position}")
        if position >= p.FLIP_TARGET:
            hstate.s7_covering = False
            hstate.flip_holding = True
            hstate.flip_entry_row = hstate.row
            hstate.flip_peak_mid = mid
            logger.print(f"S7 FLIP COMPLETE -> HOLD: pos={position}")
        return orders, hstate

    # Improved flip-hold exits: target / trailing stop / timeout.
    if hstate.flip_holding:
        hstate.tr_short_active = False
        hstate.mr_long_active = False
        held_for = hstate.row - (hstate.flip_entry_row or hstate.row)
        if mid > hstate.flip_peak_mid:
            hstate.flip_peak_mid = mid

        trail_triggered = (
            hstate.flip_peak_mid >= effective_flip_trail_enable
            and mid < hstate.flip_peak_mid - p.FLIP_TRAIL_DELTA
        )
        should_exit = (
            mid >= effective_flip_exit_mid
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
                    f"held={held_for} reason={reason} "
                    f"trail_en={effective_flip_trail_enable:.1f} exit_mid={effective_flip_exit_mid:.1f}"
                )
            hstate.flip_holding = False
            hstate.flip_entry_row = None
            hstate.flip_peak_mid = 0.0
        return orders, hstate

    # Entry: spread=17 AND elevated price AND not already in S17 short
    if (spread == p.REGIME2_SPREAD
            and mid > effective_entry_mid_min
            and hstate.s17_entry_row is None):
        hstate.tr_short_active = False
        hstate.mr_long_active = False
        headroom = pos_lim + position
        qty = min(pos_lim, headroom)   # FULL position — giga short
        if qty > 0:
            orders.append(Order(P, best_bid, -qty))  # hit bid aggressively
            hstate.s17_entry_row = hstate.row
            hstate.s17_entry_mid = mid
            logger.print(
                f"S17 ENTER short: qty={qty} px={best_bid} mid={mid:.1f} "
                f"entry_min={effective_entry_mid_min:.1f}"
            )
        return orders, hstate

    # Layer 1/2 overlays: trend-reversion short + mean-reversion long
    # (non-blocking, capped sizes, mutually exclusive).
    dir_buy_committed = 0
    dir_sell_committed = 0
    ma200 = _ma_tail(hstate.mid_buf_500, 200)
    if ma200 is not None:
        if hstate.tr_short_active:
            # Exit overlay when price normalizes toward ma200.
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

        if hstate.mr_long_active:
            # Exit long overlay when price normalizes toward ma200.
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

    # Layer 4 passive MM: suppress tight-spread quoting.
    if spread < p.MIN_MM_SPREAD:
        return orders, hstate

    # Passive MM fallback with dynamic Layer-A skew.
    if len(hstate.edge_buf) >= p.EDGE_BETA_MIN_SAMPLES:
        ex = _mean(hstate.edge_buf) or 0.0
        ey = _mean(hstate.ret_buf) or 0.0
        var_x = _mean([(x - ex) ** 2 for x in hstate.edge_buf]) or 0.0
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
    if my_ask <= my_bid: my_ask = my_bid + 1

    bid_qty = min(p.QUOTE_SIZE, max(0, bid_headroom))
    ask_qty = min(p.QUOTE_SIZE, max(0, ask_headroom))

    if bid_qty > 0:
        orders.append(Order(P, my_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order(P, my_ask, -ask_qty))

    return orders, hstate


# ============================== VEV3 module ==============================
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

    @staticmethod
    def load(trader_data):
        if not trader_data:
            return VEVState()
        try:
            raw = json.loads(trader_data)
            return VEVState.from_dict(raw.get("vev", {}))
        except Exception:
            return VEVState()


def _best_bid_ask(order_depth):
    bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
    ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
    return bid, ask


def _order_to_target(symbol: str, pos: int, target: int, bid: int, ask: int) -> List[Order]:
    if target > pos:
        return [Order(symbol, ask, target - pos)]
    if target < pos:
        return [Order(symbol, bid, -(pos - target))]
    return []


def run_vev(state: TradingState, vstate: VEVState) -> Tuple[Dict[str, List[Order]], VEVState]:
    p = VEVParams
    out: Dict[str, List[Order]] = {}

    if Product.VELVETFRUIT_EXTRACT not in state.order_depths:
        return out, vstate
    S_od = state.order_depths[Product.VELVETFRUIT_EXTRACT]
    S_bid, S_ask = _best_bid_ask(S_od)
    if S_bid is None or S_ask is None:
        return out, vstate
    S_mid = (S_bid + S_ask) / 2.0
    pos_S = state.position.get(Product.VELVETFRUIT_EXTRACT, 0)
    day_time = state.timestamp % 1_000_000

    if Product.VEV_4000 not in state.order_depths:
        return out, vstate
    v4_od = state.order_depths[Product.VEV_4000]
    v4_bid, v4_ask = _best_bid_ask(v4_od)
    if v4_bid is None or v4_ask is None:
        return out, vstate
    v4_spread = v4_ask - v4_bid
    v4_mid = (v4_bid + v4_ask) / 2.0

    vstate.vev4k_buf = _push(vstate.vev4k_buf, v4_mid, p.PEAK_WINDOW)
    vstate.S_buf = _push(vstate.S_buf, S_mid, p.COVER_WINDOW)
    vstate.s22_consec = vstate.s22_consec + 1 if v4_spread == 22 else 0

    peak_ready = len(vstate.vev4k_buf) >= p.MIN_SIGNAL_WARMUP
    cover_ready = len(vstate.S_buf) >= p.MIN_COVER_WARMUP
    peak_thresh = _quantile(vstate.vev4k_buf, p.PEAK_Q) if peak_ready else None
    cover_thresh = _quantile(vstate.S_buf, p.COVER_Q) if cover_ready else None

    if vstate.covering:
        target = vstate.cover_target
        out[Product.VELVETFRUIT_EXTRACT] = _order_to_target(Product.VELVETFRUIT_EXTRACT, pos_S, target, S_bid, S_ask)
        if pos_S == target:
            vstate.covering = False
            vstate.cover_target = 0
            vstate.in_short = False
            vstate.entry_S_mid = None
            vstate.entry_ts = None
        return out, vstate

    if vstate.in_short:
        profit_ticks = (vstate.entry_S_mid - S_mid) if vstate.entry_S_mid is not None else 0.0
        held_ticks = max(0, int((state.timestamp - vstate.entry_ts) // 100)) if vstate.entry_ts is not None else 0
        bottom_cover = cover_ready and cover_thresh is not None and S_mid <= cover_thresh
        profit_cover = profit_ticks >= p.TAKE_PROFIT
        stale_cover = held_ticks >= p.STALE_TICKS and profit_ticks >= p.STALE_PROFIT
        late_profit_cover = day_time >= p.LATE_AGGRESSIVE_AFTER and profit_ticks >= p.LATE_PROFIT
        force_flat = day_time >= p.FORCE_FLAT_AFTER
        if bottom_cover:
            target = p.LONG_TARGET
        elif profit_cover or stale_cover or late_profit_cover or force_flat:
            target = p.FLAT_TARGET
        else:
            target = None
        if target is not None:
            vstate.covering = True
            vstate.cover_target = target
            vstate.in_short = False
            out[Product.VELVETFRUIT_EXTRACT] = _order_to_target(Product.VELVETFRUIT_EXTRACT, pos_S, target, S_bid, S_ask)
            return out, vstate
        out[Product.VELVETFRUIT_EXTRACT] = _order_to_target(Product.VELVETFRUIT_EXTRACT, pos_S, p.SHORT_TARGET, S_bid, S_ask)
        return out, vstate

    signal = (
        peak_ready
        and vstate.s22_consec >= p.S22_CLUSTER_MIN
        and peak_thresh is not None
        and v4_mid >= peak_thresh
    )
    if signal and day_time < p.NO_ENTRY_AFTER:
        vstate.in_short = True
        vstate.covering = False
        vstate.cover_target = 0
        vstate.entry_S_mid = S_mid
        vstate.entry_ts = state.timestamp
        out[Product.VELVETFRUIT_EXTRACT] = _order_to_target(Product.VELVETFRUIT_EXTRACT, pos_S, p.SHORT_TARGET, S_bid, S_ask)
    return out, vstate


# ============================ Voucher5 module ============================
VOUCHER_STRIKES = {
    "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000, "VEV_5100": 5100,
    "VEV_5200": 5200, "VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500,
    "VEV_6000": 6000, "VEV_6500": 6500,
}
DEEP_ITM_STRIKES = [4000, 4500]
DEEP_ITM_MM_SIZE = 30
DEEP_ITM_POS_CAP = 200
PASSIVE_MM_STRIKES = [5100]
PASSIVE_MM_SIZE = 15
PASSIVE_MM_POS_CAP = 150
PASSIVE_MM_MIN_SPREAD = 3
LAG_FAIR_STRIKES = ["VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]
LAG_FAIR_EDGE: Dict[str, float] = {"VEV_5200": 0.0, "VEV_5300": 0.0, "VEV_5400": 0.0, "VEV_5500": 0.0}
LAG_FAIR_SIZE = 300
LAG_FAIR_LIMIT = 300
T = 5.0 / 365.0
FALLBACK_IV: Dict[str, float] = {"VEV_5200": 0.232, "VEV_5300": 0.232, "VEV_5400": 0.222, "VEV_5500": 0.238}


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_delta(S: float, K: float, sigma: float) -> float:
    if S <= 0 or K <= 0:
        return 0.0
    if sigma <= 1e-9 or T <= 0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1)


def run_voucher5(state: TradingState, memory: Dict[str, Any]) -> Tuple[Dict[str, List[Order]], Dict[str, Any]]:
    out: Dict[str, List[Order]] = {}
    s_bid, s_ask = _best_bid_ask(state.order_depths[Product.VELVETFRUIT_EXTRACT]) if Product.VELVETFRUIT_EXTRACT in state.order_depths else (None, None)
    S_now: Optional[float] = (s_bid + s_ask) / 2.0 if s_bid is not None and s_ask is not None else None

    if S_now is not None:
        for K in DEEP_ITM_STRIKES:
            sym = f"VEV_{K}"
            if sym not in state.order_depths:
                continue
            bid, ask = _best_bid_ask(state.order_depths[sym])
            if bid is None or ask is None or ask - bid < 3:
                continue
            intrinsic = max(S_now - K, 0.0)
            if intrinsic <= 0:
                continue
            pos = state.position.get(sym, 0)
            bid_px = int(max(1, min(bid + 1, intrinsic - 1)))
            if bid_px >= ask:
                bid_px = bid
            ask_px = int(max(ask - 1, intrinsic + 1))
            if ask_px <= bid:
                ask_px = ask
            room_buy = DEEP_ITM_POS_CAP - pos
            room_sell = DEEP_ITM_POS_CAP + pos
            if room_buy > 0 and bid_px < ask_px:
                out.setdefault(sym, []).append(Order(sym, bid_px, min(DEEP_ITM_MM_SIZE, room_buy)))
            if room_sell > 0 and ask_px > bid_px:
                out.setdefault(sym, []).append(Order(sym, ask_px, -min(DEEP_ITM_MM_SIZE, room_sell)))

    for K in PASSIVE_MM_STRIKES:
        sym = f"VEV_{K}"
        if sym not in state.order_depths:
            continue
        bid, ask = _best_bid_ask(state.order_depths[sym])
        if bid is None or ask is None or ask - bid < PASSIVE_MM_MIN_SPREAD:
            continue
        pos = state.position.get(sym, 0)
        existing = out.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        room_buy = min(PASSIVE_MM_POS_CAP - pos - existing_buy, 300 - pos - existing_buy)
        room_sell = min(PASSIVE_MM_POS_CAP + pos - existing_sell, 300 + pos - existing_sell)
        if room_buy > 0:
            out.setdefault(sym, []).append(Order(sym, bid + 1, min(PASSIVE_MM_SIZE, room_buy)))
        if room_sell > 0:
            out.setdefault(sym, []).append(Order(sym, ask - 1, -min(PASSIVE_MM_SIZE, room_sell)))

    if S_now is None:
        return out, memory

    for sym in LAG_FAIR_STRIKES:
        if sym not in state.order_depths:
            continue
        bid, ask = _best_bid_ask(state.order_depths[sym])
        if bid is None or ask is None:
            continue
        mid = (bid + ask) / 2.0
        K = VOUCHER_STRIKES[sym]
        sigma = FALLBACK_IV.get(sym, 0.25)
        delta = bs_delta(S_now, K, sigma)
        edge = LAG_FAIR_EDGE.get(sym, 1.0)
        key_mid = f"{sym}_mid"; key_S = f"{sym}_S"; key_delta = f"{sym}_delta"
        if key_mid not in memory:
            memory[key_mid] = mid; memory[key_S] = S_now; memory[key_delta] = delta
            continue
        prev_mid = float(memory[key_mid]); prev_S = float(memory[key_S]); prev_delta = float(memory[key_delta])
        lag_fair = prev_mid + prev_delta * (S_now - prev_S)
        pos = state.position.get(sym, 0)
        if pos < LAG_FAIR_LIMIT and lag_fair - bid >= edge:
            qty = min(LAG_FAIR_SIZE, LAG_FAIR_LIMIT - pos)
            if qty > 0:
                out.setdefault(sym, []).append(Order(sym, bid, qty))
        if pos > 0:
            out.setdefault(sym, []).append(Order(sym, ask, -pos))
        memory[key_mid] = mid; memory[key_S] = S_now; memory[key_delta] = delta
    return out, memory


def merge_orders_with_limits(state: TradingState, base_orders: Dict[Symbol, List[Order]], new_orders: Dict[Symbol, List[Order]]) -> Dict[Symbol, List[Order]]:
    for sym, arr in new_orders.items():
        for o in arr:
            base_orders.setdefault(sym, []).append(o)
    clipped: Dict[Symbol, List[Order]] = {s: [] for s in base_orders}
    for sym, arr in base_orders.items():
        lim = POSITION_LIMITS.get(sym, 10**9)
        pos = state.position.get(sym, 0)
        buy_used = 0
        sell_used = 0
        for o in arr:
            if o.quantity > 0:
                cap = lim - pos - buy_used
                qty = min(o.quantity, max(0, cap))
                if qty > 0:
                    clipped[sym].append(Order(sym, o.price, qty))
                    buy_used += qty
            elif o.quantity < 0:
                cap = lim + pos - sell_used
                qty = min(-o.quantity, max(0, cap))
                if qty > 0:
                    clipped[sym].append(Order(sym, o.price, -qty))
                    sell_used += qty
    return clipped


class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orders      = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        hstate = HydrogelState.load(trader_data)
        vstate = VEVState.load(trader_data)
        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}
        voucher_mem = raw.get("v5", {})
        if not isinstance(voucher_mem, dict):
            voucher_mem = {}

        hydrogel_orders, hstate = run_hydrogel(state, hstate)
        vev_orders, vstate = run_vev(state, vstate)
        voucher_orders, voucher_mem = run_voucher5(state, voucher_mem)

        combined: Dict[Symbol, List[Order]] = {}
        combined[Product.HYDROGEL_PACK] = hydrogel_orders
        combined = merge_orders_with_limits(state, combined, vev_orders)
        combined = merge_orders_with_limits(state, combined, voucher_orders)

        for sym, arr in combined.items():
            orders[sym] = arr

        raw["hg"] = hstate.to_dict()
        raw["vev"] = vstate.to_dict()
        raw["v5"] = voucher_mem
        trader_data = json.dumps(raw, separators=(",", ":"))

        logger.flush(state, orders, conversions, trader_data)
        return orders, conversions, trader_data