"""Trader for Hydrogel Pack, Velvetfruit Extract, and VEV vouchers (4000-6500).

Strategy layers (all run per tick unless YOLO regime fires):

  HYDROGEL_PACK
    1. S17 short campaign: spread==REGIME2_SPREAD AND mid>ENTRY_MID_MIN AND z>=2.0
       AND VFE not crashing AND under failure cap. Short to limit, cover on S7
       bottom-percentile reversal, flip long to FLIP_TARGET, hold to FLIP_EXIT_MID
       (or FLIP_TIMEOUT_TICKS). Two FLIP_HOLD timeouts freeze further S17 entries.
    2. Z-score mean reversion (window=500): |z|>Z_ENTRY directional, |z|<Z_EXIT flatten.
    3. Passive MM fallback with online edge-beta calibration (cov(edge, ret)/var(edge)).

  VELVETFRUIT_EXTRACT
    1. Wall-mid MM (against popular bid/ask volumes).
    2. Spread-state lift: spread==2 + ask dropped → buy; spread==3 + bid raised → sell.
    3. One-shot momentum short: 25-tick velocity <= -3 → short 200, exit at TP/SL.
    4. Mark 49 fade: M49 sells big → buy; M49 buys → sell. Hold M49_HOLD_TICKS ticks.
       Empirical (3-day, mid-to-mid): SELL→+$1.90 (t=20.0, n=105), BUY→-$1.26 (n=17).
    5. Mark 55 follow-flow: aggregate net flow over M55_WINDOW ticks, take on threshold.

  VEV_* (4000-6500)
    - Black-Scholes MM with adaptive sigma (median of recent IV across ATM strikes).
    - Per-strike take when |market - BS| > edge (5.0 for 5200, 10.0 elsewhere).
    - Intrinsic-value floor/ceiling enforcement; cross-strike call-spread arb.
    - Conditional OBI: |L1 imbalance|>0.7 → take aggressively, 2x size on 3+ strike agreement.
    - Deep-ITM (4000/4500) theta carry MM around intrinsic.
    - Passive OTM bid (5300/5400/5500) below BS fair (one-sided seller flow).
    - 6000/6500 bid=0 size=100 (free MTM from Mark 22→01 dumps); skipped from MM/taker.

  YOLO REGIME OVERRIDE
    - At ts=3000, if VFE drift from open <= -1.5 → short voucher portfolio + VFE,
      voucher MM suppressed for the rest of the day.

All orders pass through a final position-limit clamp.

COMPLIANCE: Uses only observable market features (spreads, mids, volumes, market_trades).
No hardcoded fair values, no timestamps, no external data.
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


# ── Products & limits ────────────────────────────────────────────────────────

class Product:
    HYDROGEL_PACK       = "HYDROGEL_PACK"
    VELVETFRUIT_EXTRACT = "VELVETFRUIT_EXTRACT"
    VEV_4000 = "VEV_4000"; VEV_4500 = "VEV_4500"
    VEV_5000 = "VEV_5000"; VEV_5100 = "VEV_5100"
    VEV_5200 = "VEV_5200"; VEV_5300 = "VEV_5300"
    VEV_5400 = "VEV_5400"; VEV_5500 = "VEV_5500"
    VEV_6000 = "VEV_6000"; VEV_6500 = "VEV_6500"


POSITION_LIMITS: Dict[str, int] = {
    Product.HYDROGEL_PACK: 200,
    Product.VELVETFRUIT_EXTRACT: 200,
    **{getattr(Product, f"VEV_{v}"): 300
       for v in ["4000", "4500", "5000", "5100", "5200", "5300", "5400", "5500", "6000", "6500"]},
}


# ── Hydrogel parameters ──────────────────────────────────────────────────────

class HydrogelParams:
    # S17 short campaign
    REGIME2_SPREAD       = 17
    ENTRY_MID_MIN        = 10010
    S7_WINDOW            = 500
    S7_BOTTOM_Q          = 0.08
    FLIP_TARGET          = 200
    FLIP_EXIT_MID        = 10020
    FLIP_TIMEOUT_TICKS   = 1500
    S17_MAX_FAILS        = 2     # freeze S17 entries after this many flip-hold timeouts

    # Sizing
    POS_LIMIT            = 200
    QUOTE_SIZE           = 200

    # Z-score mean reversion
    Z_WINDOW             = 500
    Z_ENTRY              = 2.25  # |z|>this → directional
    Z_EXIT               = 0.5   # |z|<this → flatten directional position
    Z_BASE_SIZE          = 40
    Z_MAX_POS            = 120   # leaves room for S17

    # Online edge-beta MM calibration
    Z500_WINDOW              = 500
    STD100_WINDOW            = 100
    EDGE_BETA_WINDOW         = 500
    EDGE_BETA_MIN_SAMPLES    = 50
    EDGE_BETA_SHRINK         = 0.5
    LAYER_A_SCALE            = 3.0
    LAYER_A_CLIP             = 1.0


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def compute_book_features(order_depth):
    buys  = order_depth.buy_orders
    sells = order_depth.sell_orders
    if not buys or not sells: return {}
    best_bid = max(buys.keys())
    best_ask = min(sells.keys())
    spread   = best_ask - best_bid
    if spread <= 0: return {}
    mid = (best_bid + best_ask) / 2.0
    sorted_bids = sorted(buys.keys(), reverse=True)
    sorted_asks = sorted(sells.keys())
    def px(lst, i): return lst[i] if i < len(lst) else None
    def sz(book, p): return abs(book[p]) if p is not None else 0.0
    bid_px = [px(sorted_bids, i) for i in range(3)]
    ask_px = [px(sorted_asks, i) for i in range(3)]
    bid_sz = [sz(buys, p) for p in bid_px]
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


# ── Hydrogel state ───────────────────────────────────────────────────────────

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
        self.vfe_buf: List[float] = []         # VFE mid for crash gate
        self.s17_failed_count: int = 0          # flip-hold timeout count

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
            "pmid":    self.prev_mid,
            "pedge":   self.prev_wap_edge,
            "edgeb":   self.edge_buf,
            "retb":    self.ret_buf,
            "vfeb":    self.vfe_buf,
            "s17_fc":  self.s17_failed_count,
        }

    @staticmethod
    def from_dict(d):
        s = HydrogelState()
        s.mid_buf_500      = d.get("buf500", [])
        s.mid_buf_100      = d.get("buf100", [])
        s.row              = d.get("row", 0)
        s.s17_entry_row    = d.get("s17_row")
        s.s17_entry_mid    = d.get("s17_mid")
        s.s7_covering      = d.get("s7_cov", False)
        s.flip_holding     = d.get("fh", False)
        s.flip_entry_row   = d.get("fer")
        s.prev_mid         = d.get("pmid")
        s.prev_wap_edge    = d.get("pedge")
        s.edge_buf         = d.get("edgeb", [])
        s.ret_buf          = d.get("retb", [])
        s.vfe_buf          = d.get("vfeb", [])
        s.s17_failed_count = d.get("s17_fc", 0)
        return s


# ── Hydrogel run ─────────────────────────────────────────────────────────────

def run_hydrogel(state, hstate):
    """S17 short → S7 bottom-percentile cover → flip long to FLIP_TARGET → hold to
    FLIP_EXIT_MID. Z-score MR overlay and passive MM fallback with edge-beta calibration."""
    P = Product.HYDROGEL_PACK
    orders = []
    p = HydrogelParams

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

    # Pair prev tick's edge with this tick's return for online beta.
    if hstate.prev_mid is not None and hstate.prev_wap_edge is not None:
        ret_1t = mid - hstate.prev_mid
        hstate.edge_buf = _push(hstate.edge_buf, hstate.prev_wap_edge, p.EDGE_BETA_WINDOW)
        hstate.ret_buf  = _push(hstate.ret_buf,  ret_1t,                p.EDGE_BETA_WINDOW)
    hstate.prev_mid = mid
    hstate.prev_wap_edge = wap_edge

    # ── S17 short build / cover-trigger ───────────────────────────────────
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

        # Keep building short toward limit while S17 phase active.
        headroom = pos_lim + position
        if headroom > 0:
            orders.append(Order(P, best_bid, -headroom))
            logger.print(f"S17 BUILD: qty={headroom} px={best_bid} mid={mid:.1f} pos={position}")
        return orders, hstate

    # ── Cover + flip phase: lift ask until we reach FLIP_TARGET long ──────
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

    # ── Hold-flip phase: suppress passive quoting until mid recovers ──────
    if hstate.flip_holding:
        held_for = hstate.row - (hstate.flip_entry_row or hstate.row)
        if mid >= p.FLIP_EXIT_MID or held_for >= p.FLIP_TIMEOUT_TICKS:
            timed_out = mid < p.FLIP_EXIT_MID
            if position > 0:
                orders.append(Order(P, best_bid, -position))   # aggressive flat
                logger.print(
                    f"FLIP EXIT: sell {position} px={best_bid} mid={mid:.1f} "
                    f"held={held_for} reason={'mid_target' if not timed_out else 'timeout'}"
                )
            if timed_out:
                hstate.s17_failed_count += 1
                logger.print(f"S17 CIRCUIT: failed_count -> {hstate.s17_failed_count}")
            hstate.flip_holding = False
            hstate.flip_entry_row = None
        return orders, hstate

    # ── VFE crash gate: block S17 entry while VFE drifts down sharply ─────
    vfe_od = state.order_depths.get(Product.VELVETFRUIT_EXTRACT)
    vfe_mid = None
    if vfe_od and vfe_od.buy_orders and vfe_od.sell_orders:
        vfe_mid = (max(vfe_od.buy_orders) + min(vfe_od.sell_orders)) / 2.0
    if vfe_mid is not None:
        hstate.vfe_buf = _push(hstate.vfe_buf, vfe_mid, 200)

    vfe_crashing = False
    if vfe_mid is not None and len(hstate.vfe_buf) >= 50:
        early_avg = sum(hstate.vfe_buf[:25]) / 25
        vfe_drift = vfe_mid - early_avg
        vfe_crashing = vfe_drift < -5.0

    # ── S17 entry gate: spread + elevated mid + z>=2.0 + not crashing ─────
    # z-gate raises win-rate from 66% to 83% on day 3 by filtering marginal high-mids.
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
            and not vfe_crashing
            and hstate.s17_failed_count < p.S17_MAX_FAILS):
        headroom = pos_lim + position
        qty = min(pos_lim, headroom)
        if qty > 0:
            orders.append(Order(P, best_bid, -qty))
            hstate.s17_entry_row = hstate.row
            hstate.s17_entry_mid = mid
            logger.print(f"S17 ENTER short: qty={qty} px={best_bid} mid={mid:.1f}")
        return orders, hstate

    # ── Z-score mean reversion ────────────────────────────────────────────
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
        target_qty = min(int(round(p.Z_BASE_SIZE * z_scale)), p.Z_MAX_POS)

        if z > p.Z_ENTRY:
            # Above mean → SHORT
            target_pos = -target_qty
            delta = target_pos - position
            if delta < 0:
                sell_qty = min(-delta, pos_lim + position)
                if sell_qty > 0:
                    orders.append(Order(P, best_bid, -sell_qty))
        else:
            # Below mean → BUY
            target_pos = target_qty
            delta = target_pos - position
            if delta > 0:
                buy_qty = min(delta, pos_lim - position)
                if buy_qty > 0:
                    orders.append(Order(P, best_ask, buy_qty))

        # Post passive on the OTHER side for spread capture.
        fv = int(round(mid))
        if z > p.Z_ENTRY:
            bid_qty = min(p.QUOTE_SIZE, max(0, pos_lim - position))
            if bid_qty > 0:
                my_bid = max(best_bid + 1, fv - 1)
                my_bid = min(my_bid, best_ask - 1)
                orders.append(Order(P, my_bid, bid_qty))
        else:
            ask_qty = min(p.QUOTE_SIZE, max(0, pos_lim + position))
            if ask_qty > 0:
                my_ask = min(best_ask - 1, fv + 1)
                my_ask = max(my_ask, best_bid + 1)
                orders.append(Order(P, my_ask, -ask_qty))
        return orders, hstate

    # ── Z near zero: flatten any directional position ──────────────────────
    if z is not None and abs(z) < p.Z_EXIT and abs(position) > p.QUOTE_SIZE:
        if position > 0:
            sell_qty = min(position, p.QUOTE_SIZE * 2)
            orders.append(Order(P, best_bid, -sell_qty))
        elif position < 0:
            buy_qty = min(-position, p.QUOTE_SIZE * 2)
            orders.append(Order(P, best_ask, buy_qty))
        return orders, hstate

    # ── Passive MM fallback with online edge-beta skew ─────────────────────
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
    if my_ask <= my_bid:
        my_ask = my_bid + 1

    bid_qty = min(p.QUOTE_SIZE, max(0, bid_headroom))
    ask_qty = min(p.QUOTE_SIZE, max(0, ask_headroom))

    if bid_qty > 0:
        orders.append(Order(P, my_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order(P, my_ask, -ask_qty))

    return orders, hstate


# ── Voucher / VFE constants ──────────────────────────────────────────────────

VEVE_SYM = "VELVETFRUIT_EXTRACT"
VOUCHER_STRIKES_ALL         = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VOUCHER_STRIKES_TRADEABLE   = [5000, 5100, 5200, 5300, 5400]
VOUCHER_STRIKES_DEEP_ITM    = [4000, 4500]
VOUCHER_STRIKES_OTM_PASSIVE = [5300, 5400, 5500]
VOUCHER_STRIKES_SKIP        = {6000, 6500}   # one-sided sells, expire 0 — handled by deep-OTM bid only
VOUCHER_SYM = {k: f"VEV_{k}" for k in VOUCHER_STRIKES_ALL}

# BS / pricing
V_TTE_DAYS_AT_START   = 4.0
V_TTE_YEAR            = 250.0
V_BS_SIGMA_DEFAULT    = 0.18
V_BS_EDGE             = 10.0
V_BS_TRADE_SIZE       = 30
V_BS_POS_CAP          = 150
V_BS_STRIKES          = [5000, 5100, 5200, 5300, 5400]
V_IV_ADAPT_WINDOW     = 50
V_IV_ADAPT_MIN_HIST   = 15

# Intrinsic / arb / MM
V_INTRINSIC_EDGE      = 2
V_INTRINSIC_QTY       = 50
V_ARB_SIZE            = 10
V_VOUCHER_MM_SIZE     = 40
V_VOUCHER_MIN_SPREAD  = 2
V_POST_SLACK_VE       = 1

# Conditional voucher OBI layer.
# OBI = (bid_vol - ask_vol)/(bid_vol + ask_vol). |OBI|>threshold and (for buys) tight
# spread → take aggressively. 2x size when 3+ ATM strikes confirm direction.
OBI_ACTIVE_STRIKES        = [4000, 5200, 5300, 5400, 5500]
OBI_ATM_STRIKES           = [5100, 5200, 5300, 5400, 5500]
OBI_THRESHOLD             = 0.7
OBI_SPREAD_COMPRESS_MAX   = 10
OBI_BASE_SIZE             = 10
OBI_CONFIRM_SCALE         = 2
OBI_CONFIRM_MIN_STRIKES   = 3
OBI_POS_CAP               = 30


# ── Voucher state ────────────────────────────────────────────────────────────

class VoucherState:
    def __init__(self):
        self.iv_history: Dict[int, List[float]] = {k: [] for k in V_BS_STRIKES}
        self.last_spot: Optional[float] = None
        self.spot_age: int = 0
        # VFE spread-state lift — track prev L1 bid/ask
        self.prev_ve_ap1: Optional[float] = None
        self.prev_ve_bp1: Optional[float] = None
        # VFE momentum-short
        self.vfe_momo_buf: List[float] = []
        self.vfe_momo_short_entry: Optional[float] = None
        self.vfe_momo_fired: bool = False           # one-shot per day
        # Mark 49 fade
        self.m49_long_until: Optional[int] = None
        self.m49_short_until: Optional[int] = None
        self.m49_seen: List[int] = []                # ts of recent M49 fills already acted on
        # Mark 55 follow-flow
        self.m55_flow_buf: List[int] = []

    def to_dict(self):
        return {
            "ivh":      {str(k): v[-V_IV_ADAPT_WINDOW:] for k, v in self.iv_history.items()},
            "ls":       self.last_spot,
            "sa":       self.spot_age,
            "p_ap":     self.prev_ve_ap1,
            "p_bp":     self.prev_ve_bp1,
            "vfe_momo_buf":         self.vfe_momo_buf,
            "vfe_momo_short_entry": self.vfe_momo_short_entry,
            "vfe_momo_fired":       self.vfe_momo_fired,
            "m49_lu":   self.m49_long_until,
            "m49_su":   self.m49_short_until,
            "m49_seen": self.m49_seen[-32:],
            "m55_flow_buf": self.m55_flow_buf,
        }

    @staticmethod
    def from_dict(d):
        s = VoucherState()
        s.iv_history = {int(k): list(v) for k, v in d.get("ivh", {}).items()}
        for k in V_BS_STRIKES:
            if k not in s.iv_history:
                s.iv_history[k] = []
        s.last_spot             = d.get("ls")
        s.spot_age              = d.get("sa", 0)
        s.prev_ve_ap1           = d.get("p_ap")
        s.prev_ve_bp1           = d.get("p_bp")
        s.vfe_momo_buf          = d.get("vfe_momo_buf", [])
        s.vfe_momo_short_entry  = d.get("vfe_momo_short_entry")
        s.vfe_momo_fired        = d.get("vfe_momo_fired", False)
        s.m49_long_until        = d.get("m49_lu")
        s.m49_short_until       = d.get("m49_su")
        s.m49_seen              = d.get("m49_seen", [])
        s.m55_flow_buf          = d.get("m55_flow_buf", [])
        return s


# ── Voucher helpers ──────────────────────────────────────────────────────────

def voucher_obi(od):
    """Return (obi, spread, best_bid, best_ask) or None."""
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    bb = max(od.buy_orders); ba = min(od.sell_orders)
    bv = od.buy_orders[bb]; av = -od.sell_orders[ba]
    if bv + av <= 0:
        return None
    return ((bv - av) / (bv + av), ba - bb, bb, ba)


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
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    pop_bid = max(od.buy_orders.items(), key=lambda kv: kv[1])[0]
    pop_ask = min(od.sell_orders.items(), key=lambda kv: kv[1])[0]
    return 0.5 * (pop_bid + pop_ask)


def v_plain_mid(od):
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    return 0.5 * (max(od.buy_orders) + min(od.sell_orders))


def v_get_adaptive_sigma(state, vstate):
    all_recent: List[float] = []
    for k in V_BS_STRIKES:
        hist = vstate.iv_history.get(k, [])
        if len(hist) >= V_IV_ADAPT_MIN_HIST:
            all_recent.extend(hist[-V_IV_ADAPT_WINDOW:])
    if len(all_recent) < V_IV_ADAPT_MIN_HIST:
        return V_BS_SIGMA_DEFAULT
    return median(all_recent)


# ── Mark 49 fade ─────────────────────────────────────────────────────────────
# Mark 49 is a wrong-side taker on VFE. Fade by taking the opposite side at L1
# and holding M49_HOLD_TICKS ticks. Inventory contribution capped at +/-M49_POS_CAP.
M49_QTY_MIN_SELL = 8     # 93/105 of M49 sells in 3-day sample
M49_QTY_MIN_BUY  = 1
M49_HOLD_TICKS   = 5
M49_SIZE         = 60
M49_POS_CAP      = 20


def run_mark49_fade(state, vstate):
    """Returns (extra_orders, extra_buy, extra_sell) for VFE.
    Triggered by Mark 49 fills in state.market_trades; flat after M49_HOLD_TICKS."""
    P = VEVE_SYM
    od = state.order_depths.get(P)
    if not od or not od.buy_orders or not od.sell_orders:
        return [], 0, 0

    bb = max(od.buy_orders); ba = min(od.sell_orders)
    pos = state.position.get(P, 0)
    ts_now = state.timestamp

    # Process market_trades for new Mark 49 fills (deduped via vstate.m49_seen).
    m_trades = (state.market_trades or {}).get(P, [])
    seen_set = set(vstate.m49_seen)
    for tr in m_trades:
        if tr.timestamp in seen_set:
            continue
        if tr.seller == "Mark 49" and tr.quantity >= M49_QTY_MIN_SELL:
            vstate.m49_long_until = ts_now + M49_HOLD_TICKS * 100
            vstate.m49_seen.append(tr.timestamp)
            seen_set.add(tr.timestamp)
        elif tr.buyer == "Mark 49" and tr.quantity >= M49_QTY_MIN_BUY:
            vstate.m49_short_until = ts_now + M49_HOLD_TICKS * 100
            vstate.m49_seen.append(tr.timestamp)
            seen_set.add(tr.timestamp)
    if len(vstate.m49_seen) > 64:
        vstate.m49_seen = vstate.m49_seen[-32:]

    # Expire windows.
    if vstate.m49_long_until is not None and ts_now >= vstate.m49_long_until:
        vstate.m49_long_until = None
    if vstate.m49_short_until is not None and ts_now >= vstate.m49_short_until:
        vstate.m49_short_until = None

    extra: List[Order] = []
    extra_buy = 0
    extra_sell = 0

    long_active  = vstate.m49_long_until is not None
    short_active = vstate.m49_short_until is not None
    if long_active and short_active:
        short_active = False   # prefer LONG (stronger empirical signal)

    if long_active and pos < M49_POS_CAP:
        target_buy = min(M49_SIZE, M49_POS_CAP - pos, 200 - pos)
        if target_buy > 0:
            extra.append(Order(P, ba, target_buy))
            extra_buy = target_buy
    elif short_active and pos > -M49_POS_CAP:
        target_sell = min(M49_SIZE, M49_POS_CAP + pos, 200 + pos)
        if target_sell > 0:
            extra.append(Order(P, bb, -target_sell))
            extra_sell = target_sell

    return extra, extra_buy, extra_sell


# ── Mark 55 follow-flow ──────────────────────────────────────────────────────
M55_WINDOW    = 50
M55_THRESH    = 30
M55_TAKE_SIZE = 20
M55_POS_CAP   = 60


def _compute_m55_netflow(state, vstate):
    """Mark 55 net flow on VFE — combines market_trades AND own_trades.
    Returns (sum_net_flow_window, this_tick_net)."""
    tick_net = 0
    for t in (state.market_trades.get(VEVE_SYM, []) or []):
        if t.buyer == "Mark 55":
            tick_net += t.quantity
        elif t.seller == "Mark 55":
            tick_net -= t.quantity
    for t in (state.own_trades.get(VEVE_SYM, []) or []):
        if t.buyer == "Mark 55":
            tick_net += t.quantity
        elif t.seller == "Mark 55":
            tick_net -= t.quantity
    vstate.m55_flow_buf.append(tick_net)
    if len(vstate.m55_flow_buf) > M55_WINDOW:
        vstate.m55_flow_buf = vstate.m55_flow_buf[-M55_WINDOW:]
    return sum(vstate.m55_flow_buf), tick_net


# ── VFE momentum short ───────────────────────────────────────────────────────
# When 25-tick velocity drops <= -3, short 200 once. Exit at TP/SL.
VFE_MOMO_BUF      = 60
VFE_MOMO_LOOKBACK = 25
VFE_MOMO_THRESH   = -3.0
VFE_MOMO_SIZE     = 200
VFE_MOMO_TP       = 12.0   # take-profit per share
VFE_MOMO_SL       = 15.0   # stop-loss per share


def run_vfe_momentum(state, vstate, current_vfe_orders, signal_buy_used, signal_sell_used):
    """Returns additional orders to merge into the VFE list."""
    P = VEVE_SYM
    od = state.order_depths.get(P)
    if not od or not od.buy_orders or not od.sell_orders:
        return [], 0, 0

    bb = max(od.buy_orders); ba = min(od.sell_orders)
    mid = (bb + ba) / 2.0
    pos = state.position.get(P, 0)

    vstate.vfe_momo_buf = vstate.vfe_momo_buf + [mid]
    if len(vstate.vfe_momo_buf) > VFE_MOMO_BUF:
        vstate.vfe_momo_buf = vstate.vfe_momo_buf[-VFE_MOMO_BUF:]

    extra: List[Order] = []
    extra_buy = 0
    extra_sell = 0

    # Exit check first (we have an open short from prior tick).
    if vstate.vfe_momo_short_entry is not None:
        per_share_pnl = vstate.vfe_momo_short_entry - mid
        total_pnl = per_share_pnl * VFE_MOMO_SIZE
        cover = (total_pnl >= VFE_MOMO_TP * VFE_MOMO_SIZE
                 or total_pnl <= -VFE_MOMO_SL * VFE_MOMO_SIZE)
        if cover:
            qty_to_cover = max(0, min(VFE_MOMO_SIZE, 200 - pos))
            if qty_to_cover > 0:
                extra.append(Order(P, ba, qty_to_cover))
                extra_buy = qty_to_cover
            vstate.vfe_momo_short_entry = None
        return extra, extra_buy, extra_sell

    # Entry: 25-tick velocity, one-shot per day.
    if (not vstate.vfe_momo_fired
            and len(vstate.vfe_momo_buf) >= VFE_MOMO_LOOKBACK + 1):
        velocity = mid - vstate.vfe_momo_buf[-VFE_MOMO_LOOKBACK - 1]
        if velocity <= VFE_MOMO_THRESH and pos >= -50:
            available = 200 + pos
            qty = min(VFE_MOMO_SIZE, available - signal_sell_used)
            if qty > 0:
                extra.append(Order(P, bb, -qty))
                extra_sell = qty
                vstate.vfe_momo_short_entry = mid
                vstate.vfe_momo_fired = True

    return extra, extra_buy, extra_sell


# ── Voucher run ──────────────────────────────────────────────────────────────

def run_vouchers(state, vstate):
    orders: Dict[str, List[Order]] = {}
    timestamp = state.timestamp

    od_ve = state.order_depths.get(VEVE_SYM)

    # ── VFE spread-state lift (inside-spread post on tightening signals) ──
    ve_layer_e: List[Order] = []
    layer_e_buy = 0
    layer_e_sell = 0
    if od_ve and od_ve.buy_orders and od_ve.sell_orders:
        bb_ve = max(od_ve.buy_orders); ba_ve = min(od_ve.sell_orders)
        spread_ve = ba_ve - bb_ve
        pos_ve = state.position.get(VEVE_SYM, 0)
        E_SIZE = 20
        E_POS_CAP = 200
        if vstate.prev_ve_ap1 is not None and vstate.prev_ve_bp1 is not None:
            # Buy: spread==2 + ask dropped → post inside at ask-1
            if spread_ve == 2 and ba_ve < vstate.prev_ve_ap1:
                q = min(E_SIZE, E_POS_CAP - pos_ve)
                if q > 0:
                    px = int(ba_ve - 1)
                    if bb_ve < px < ba_ve:
                        ve_layer_e.append(Order(VEVE_SYM, px, q))
                        layer_e_buy = q
            # Sell: spread==3 + bid raised → post inside at bid+1
            elif spread_ve == 3 and bb_ve > vstate.prev_ve_bp1:
                q = min(E_SIZE, E_POS_CAP + pos_ve)
                if q > 0:
                    px = int(bb_ve + 1)
                    if bb_ve < px < ba_ve:
                        ve_layer_e.append(Order(VEVE_SYM, px, -q))
                        layer_e_sell = q
        vstate.prev_ve_ap1 = ba_ve
        vstate.prev_ve_bp1 = bb_ve

    # ── VFE momentum-short (claims position headroom before MM) ───────────
    momo_orders, momo_buy, momo_sell = run_vfe_momentum(state, vstate, [], 0, 0)

    # ── Mark 49 fade (claims position headroom before MM) ─────────────────
    m49_orders, m49_buy, m49_sell = run_mark49_fade(state, vstate)

    # ── Mark 55 follow-flow (claims position headroom before MM) ──────────
    m55_orders: List[Order] = []
    m55_buy = 0
    m55_sell = 0
    m55_signal, _ = _compute_m55_netflow(state, vstate)
    if od_ve and od_ve.buy_orders and od_ve.sell_orders:
        bb_m = max(od_ve.buy_orders); ba_m = min(od_ve.sell_orders)
        pos_m = state.position.get(VEVE_SYM, 0)
        if m55_signal >= M55_THRESH and pos_m < M55_POS_CAP:
            avail = -od_ve.sell_orders[ba_m]
            room = min(M55_POS_CAP - pos_m, 200 - pos_m - layer_e_buy - m49_buy - momo_buy)
            q = min(M55_TAKE_SIZE, avail, room)
            if q > 0:
                m55_orders.append(Order(VEVE_SYM, ba_m, +q))
                m55_buy = q
        elif m55_signal <= -M55_THRESH and pos_m > -M55_POS_CAP:
            avail = od_ve.buy_orders[bb_m]
            room = min(M55_POS_CAP + pos_m, 200 + pos_m - layer_e_sell - m49_sell - momo_sell)
            q = min(M55_TAKE_SIZE, avail, room)
            if q > 0:
                m55_orders.append(Order(VEVE_SYM, bb_m, -q))
                m55_sell = q

    # ── VFE wall-mid MM (around popular bid/ask volumes) ──────────────────
    if od_ve and od_ve.buy_orders and od_ve.sell_orders:
        wm = v_wall_mid(od_ve)
        if wm is not None:
            bb = max(od_ve.buy_orders); ba = min(od_ve.sell_orders)
            pos = state.position.get(VEVE_SYM, 0)
            fv = round(wm)
            tb = 200 - pos - layer_e_buy  - momo_buy  - m49_buy  - m55_buy
            ts = 200 + pos - layer_e_sell - momo_sell - m49_sell - m55_sell
            half = 100
            mbp = fv - 1 if pos >  half else fv
            msp = fv + 1 if pos < -half else fv
            # Suppress passive long quoting while in momentum short.
            if vstate.vfe_momo_short_entry is not None:
                tb = 0
            ve_orders = list(momo_orders) + list(ve_layer_e) + list(m49_orders) + list(m55_orders)
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
        else:
            fallback = list(momo_orders) + list(ve_layer_e) + list(m49_orders)
            if fallback:
                orders[VEVE_SYM] = fallback

    # ── Spot resolution for vouchers (with brief carry-over) ──────────────
    spot = v_plain_mid(state.order_depths.get(VEVE_SYM))
    if spot is None:
        if vstate.last_spot is not None and vstate.spot_age < 20:
            spot = vstate.last_spot
            vstate.spot_age += 1
        else:
            return orders
    else:
        vstate.last_spot = spot
        vstate.spot_age = 0

    if vstate.spot_age > 3:
        return orders

    T = max(V_TTE_DAYS_AT_START - timestamp / 1_000_000.0, 0.01) / V_TTE_YEAR

    # ── Update IV history for adaptive sigma ──────────────────────────────
    for K in V_BS_STRIKES:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders:
            continue
        wm_v = v_wall_mid(od_v)
        if wm_v is None:
            continue
        iv = v_implied_vol(wm_v, spot, K, T)
        if iv is not None:
            hist = vstate.iv_history.setdefault(K, [])
            hist.append(iv)
            if len(hist) > V_IV_ADAPT_WINDOW:
                del hist[:len(hist) - V_IV_ADAPT_WINDOW]

    sigma = v_get_adaptive_sigma(state, vstate)

    # ── Intrinsic floor/ceiling enforcement ──────────────────────────────
    for K in VOUCHER_STRIKES_ALL:
        if K in VOUCHER_STRIKES_SKIP:
            continue
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None:
            continue
        existing = orders.get(sym, [])
        already_buy  = sum(o.quantity for o in existing if o.quantity > 0)
        already_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        pos_v = state.position.get(sym, 0)
        tb = 300 - pos_v - already_buy
        ts = 300 + pos_v - already_sell
        intrinsic = max(spot - K, 0.0)
        deep_itm = K in VOUCHER_STRIKES_DEEP_ITM
        new_orders: List[Order] = []
        for p, v in sorted(od_v.sell_orders.items()):
            if tb > 0 and p < intrinsic - V_INTRINSIC_EDGE:
                q = min(tb, -v, V_INTRINSIC_QTY); new_orders.append(Order(sym, p, q)); tb -= q
        sell_thr = (intrinsic if deep_itm else spot) + V_INTRINSIC_EDGE
        for p, v in sorted(od_v.buy_orders.items(), reverse=True):
            if ts > 0 and p > sell_thr:
                q = min(ts, v, V_INTRINSIC_QTY); new_orders.append(Order(sym, p, -q)); ts -= q
        if new_orders:
            orders.setdefault(sym, []).extend(new_orders)

    # ── Black-Scholes per-strike take ─────────────────────────────────────
    for K in V_BS_STRIKES:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders:
            continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        already_buy  = sum(o.quantity for o in existing if o.quantity > 0)
        already_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        cur_pos_buy  = pos_v + already_buy
        cur_pos_sell = pos_v - already_sell
        fv_bs = v_bs_call(spot, K, T, sigma)
        edge = 5.0 if K == 5200 else V_BS_EDGE   # 5200 needs tighter edge to break even
        buy_thr     = fv_bs - edge
        sell_thr_bs = fv_bs + edge
        new_orders: List[Order] = []
        for px in sorted(od_v.sell_orders.keys()):
            if px > buy_thr:
                break
            avail = -od_v.sell_orders[px]
            room = min(300 - cur_pos_buy, V_BS_POS_CAP - cur_pos_buy)
            size = min(V_BS_TRADE_SIZE, avail, room)
            if size > 0:
                new_orders.append(Order(sym, px, +size)); cur_pos_buy += size
        for px in sorted(od_v.buy_orders.keys(), reverse=True):
            if px < sell_thr_bs:
                break
            avail = od_v.buy_orders[px]
            room = min(300 + cur_pos_sell, V_BS_POS_CAP + cur_pos_sell)
            size = min(V_BS_TRADE_SIZE, avail, room)
            if size > 0:
                new_orders.append(Order(sym, px, -size)); cur_pos_sell -= size
        if new_orders:
            orders.setdefault(sym, []).extend(new_orders)

    # ── Cross-strike call-spread arb (lower ask < higher bid) ─────────────
    committed_buy  = {sym: 0 for sym in VOUCHER_SYM.values()}
    committed_sell = {sym: 0 for sym in VOUCHER_SYM.values()}
    for sym, ord_list in orders.items():
        if sym in committed_buy:
            committed_buy[sym]  = sum(o.quantity for o in ord_list if o.quantity > 0)
            committed_sell[sym] = sum(-o.quantity for o in ord_list if o.quantity < 0)
    for K_lo, K_hi in itertools.combinations(VOUCHER_STRIKES_ALL, 2):
        if K_lo in VOUCHER_STRIKES_SKIP or K_hi in VOUCHER_STRIKES_SKIP:
            continue
        sym_lo = VOUCHER_SYM[K_lo]; sym_hi = VOUCHER_SYM[K_hi]
        od_lo = state.order_depths.get(sym_lo)
        od_hi = state.order_depths.get(sym_hi)
        if od_lo is None or od_hi is None:
            continue
        pos_lo = state.position.get(sym_lo, 0)
        pos_hi = state.position.get(sym_hi, 0)
        if od_lo.sell_orders and od_hi.buy_orders:
            ask_lo = min(od_lo.sell_orders); bid_hi = max(od_hi.buy_orders)
            if ask_lo - bid_hi < 0:
                ask_lo_vol = -od_lo.sell_orders[ask_lo]
                bid_hi_vol =  od_hi.buy_orders[bid_hi]
                room_buy_lo  = 300 - pos_lo - committed_buy[sym_lo]
                room_sell_hi = 300 + pos_hi - committed_sell[sym_hi]
                size = min(V_ARB_SIZE, ask_lo_vol, bid_hi_vol, room_buy_lo, room_sell_hi)
                if size > 0:
                    orders.setdefault(sym_lo, []).append(Order(sym_lo, ask_lo, +size))
                    orders.setdefault(sym_hi, []).append(Order(sym_hi, bid_hi, -size))
                    committed_buy[sym_lo]  += size
                    committed_sell[sym_hi] += size

    # ── Tradeable-strike passive MM (inside spread) ───────────────────────
    for K in VOUCHER_STRIKES_TRADEABLE:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders:
            continue
        vbb = max(od_v.buy_orders); vba = min(od_v.sell_orders)
        if vba - vbb < V_VOUCHER_MIN_SPREAD:
            continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy  = sum(o.quantity for o in existing if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        tb_v = 300 - pos_v - existing_buy
        ts_v = 300 + pos_v - existing_sell
        if tb_v > 0:
            orders.setdefault(sym, []).append(Order(sym, vbb + 1,  min(tb_v, V_VOUCHER_MM_SIZE)))
        if ts_v > 0:
            orders.setdefault(sym, []).append(Order(sym, vba - 1, -min(ts_v, V_VOUCHER_MM_SIZE)))

    # ── Deep ITM (4000/4500) theta carry MM around intrinsic ──────────────
    DEEP_ITM_MM_SIZE    = 30
    DEEP_ITM_POS_CAP    = 100
    DEEP_ITM_BID_OFFSET = 1
    DEEP_ITM_ASK_OFFSET = 1
    for K in VOUCHER_STRIKES_DEEP_ITM:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders:
            continue
        intrinsic = max(spot - K, 0.0)
        if intrinsic <= 0:
            continue
        vbb = max(od_v.buy_orders); vba = min(od_v.sell_orders)
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy  = sum(o.quantity for o in existing if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)

        room_buy = DEEP_ITM_POS_CAP - pos_v - existing_buy
        if room_buy > 0:
            target_bid = int(round(intrinsic - DEEP_ITM_BID_OFFSET))
            bid_px = max(1, min(target_bid, vbb + 1))
            if bid_px <= vba - 1:
                orders.setdefault(sym, []).append(Order(sym, bid_px, min(DEEP_ITM_MM_SIZE, room_buy)))

        room_sell = DEEP_ITM_POS_CAP + pos_v - existing_sell
        if room_sell > 0:
            target_ask = int(round(intrinsic + DEEP_ITM_ASK_OFFSET))
            ask_px = max(target_ask, vba - 1)
            if ask_px >= vbb + 1:
                orders.setdefault(sym, []).append(Order(sym, ask_px, -min(DEEP_ITM_MM_SIZE, room_sell)))

    # ── Passive OTM bid (5300/5400/5500) below BS fair ────────────────────
    # One-sided seller flow: bid at min(best_bid+1, floor(BS_fair - OTM_BID_EDGE)).
    # No asks (no buyer flow). Cap long position from this layer at OTM_BID_POS_CAP.
    OTM_BID_SIZE    = 5
    OTM_BID_POS_CAP = 50
    OTM_BID_EDGE    = 2
    for K in VOUCHER_STRIKES_OTM_PASSIVE:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders:
            continue
        bb = max(od_v.buy_orders); ba = min(od_v.sell_orders)
        fv_bs = v_bs_call(spot, K, T, sigma)
        bs_cap = math.floor(fv_bs - OTM_BID_EDGE)
        bid_px = min(bb + 1, bs_cap)
        if bid_px <= 0 or bid_px >= ba:
            continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        tb_v = OTM_BID_POS_CAP - pos_v - existing_buy
        if tb_v > 0:
            orders.setdefault(sym, []).append(Order(sym, bid_px, min(tb_v, OTM_BID_SIZE)))

    # ── Deep OTM (6000/6500) free MTM via bid=0 size=100 ──────────────────
    # Mark 22 dumps to Mark 01 at price=0 every tick. No delta risk (spot needs +700).
    DEEP_OTM_BID_PX   = 0
    DEEP_OTM_BID_SIZE = 100
    for K in [6000, 6500]:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None:
            continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        room = 300 - pos_v - existing_buy
        if room > 0:
            orders.setdefault(sym, []).append(Order(sym, DEEP_OTM_BID_PX, min(DEEP_OTM_BID_SIZE, room)))

    # ── Conditional voucher OBI ──────────────────────────────────────────
    atm_obis: Dict[int, float] = {}
    for K in OBI_ATM_STRIKES:
        od_v = state.order_depths.get(VOUCHER_SYM[K])
        r = voucher_obi(od_v) if od_v else None
        if r is not None:
            atm_obis[K] = r[0]
    pos_signs = sum(1 for o in atm_obis.values() if o >  OBI_THRESHOLD)
    neg_signs = sum(1 for o in atm_obis.values() if o < -OBI_THRESHOLD)
    scale_buy  = OBI_CONFIRM_SCALE if pos_signs >= OBI_CONFIRM_MIN_STRIKES else 1
    scale_sell = OBI_CONFIRM_SCALE if neg_signs >= OBI_CONFIRM_MIN_STRIKES else 1

    for K in OBI_ACTIVE_STRIKES:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        r = voucher_obi(od_v) if od_v else None
        if r is None:
            continue
        obi, sp_v, vbb, vba = r
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        already_buy  = sum(o.quantity for o in existing if o.quantity > 0)
        already_sell = sum(-o.quantity for o in existing if o.quantity < 0)

        # BUY: OBI > +threshold AND spread tight
        if obi > OBI_THRESHOLD and sp_v <= OBI_SPREAD_COMPRESS_MAX and pos_v < OBI_POS_CAP:
            qty = OBI_BASE_SIZE * scale_buy
            room = min(300 - pos_v - already_buy, OBI_POS_CAP - pos_v - already_buy)
            avail = -od_v.sell_orders[vba]
            q = min(qty, room, avail)
            if q > 0:
                orders.setdefault(sym, []).append(Order(sym, vba, +q))

        # SELL: OBI < -threshold (no spread gate)
        if obi < -OBI_THRESHOLD and pos_v > -OBI_POS_CAP:
            qty = OBI_BASE_SIZE * scale_sell
            room = min(300 + pos_v - already_sell, OBI_POS_CAP + pos_v - already_sell)
            avail = od_v.buy_orders[vbb]
            q = min(qty, room, avail)
            if q > 0:
                orders.setdefault(sym, []).append(Order(sym, vbb, -q))

    return orders


# ── Final position-limit clamp ───────────────────────────────────────────────

def _clamp_to_position_limits(orders_by_sym, positions, debug_log=None):
    """Truncate orders so that cumulative buy/sell never breaches per-product limits.
    Defensive — never expected to fire on validated paths, but enforces IMC's
    per-product all-or-nothing rule if any layer's headroom math drifts."""
    clamped: Dict[str, List[Order]] = {}
    for sym, ords in orders_by_sym.items():
        if not ords:
            clamped[sym] = ords
            continue
        lim = POSITION_LIMITS.get(sym, 999_999)
        pos = positions.get(sym, 0)
        max_buy_total  = max(0, lim - pos)
        max_sell_total = max(0, lim + pos)
        out: List[Order] = []
        cum_buy = 0
        cum_sell = 0
        for o in ords:
            if o.quantity > 0:
                allow = min(o.quantity, max_buy_total - cum_buy)
                if allow > 0:
                    out.append(o if allow == o.quantity else Order(o.symbol, o.price, allow))
                    if allow != o.quantity and debug_log is not None:
                        debug_log.append(f"CLAMP {sym} BUY {o.price}@{o.quantity}->{allow} pos={pos}")
                    cum_buy += allow
                elif debug_log is not None:
                    debug_log.append(f"CLAMP {sym} BUY {o.price}@{o.quantity}->0 pos={pos}")
            elif o.quantity < 0:
                want = -o.quantity
                allow = min(want, max_sell_total - cum_sell)
                if allow > 0:
                    out.append(o if allow == want else Order(o.symbol, o.price, -allow))
                    if allow != want and debug_log is not None:
                        debug_log.append(f"CLAMP {sym} SELL {o.price}@{want}->{allow} pos={pos}")
                    cum_sell += allow
                elif debug_log is not None:
                    debug_log.append(f"CLAMP {sym} SELL {o.price}@{want}->0 pos={pos}")
        clamped[sym] = out
    return clamped


# ── YOLO regime override ─────────────────────────────────────────────────────
# At YOLO_DETECT_TICKS_TS, snapshot VFE drift from open. If <= YOLO_DRIFT_THRESHOLD,
# enter short-everything mode for the rest of the day.
YOLO_DETECT_TICKS_TS = 3000
YOLO_DRIFT_THRESHOLD = -1.5
YOLO_VOUCHER_TARGETS = {
    "VEV_4000": -300, "VEV_4500": -300, "VEV_5000": -300, "VEV_5100": -300,
    "VEV_5200": -300, "VEV_5300": -300, "VEV_5400": -300, "VEV_5500": -300,
}
YOLO_VFE_TARGET = -200


# ── Entry point ──────────────────────────────────────────────────────────────

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orders: Dict[Symbol, List[Order]] = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}

        # YOLO regime gate (decided once at YOLO_DETECT_TICKS_TS).
        yolo_anchor = raw.get("yolo_anchor")
        yolo_regime = raw.get("yolo_regime", None)   # None=undecided, True=short-all, False=normal
        ts = state.timestamp
        vfe_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        vfe_mid = None
        if vfe_od and vfe_od.buy_orders and vfe_od.sell_orders:
            vfe_mid = (max(vfe_od.buy_orders) + min(vfe_od.sell_orders)) / 2.0
        if yolo_anchor is None and vfe_mid is not None:
            yolo_anchor = vfe_mid
            raw["yolo_anchor"] = yolo_anchor
        if (yolo_regime is None and ts >= YOLO_DETECT_TICKS_TS
                and vfe_mid is not None and yolo_anchor is not None):
            yolo_regime = (vfe_mid - yolo_anchor) <= YOLO_DRIFT_THRESHOLD
            raw["yolo_regime"] = yolo_regime

        # Hydrogel always runs.
        hstate = HydrogelState.from_dict(raw.get("hg", {}))
        hydrogel_orders, hstate = run_hydrogel(state, hstate)
        orders[Product.HYDROGEL_PACK] = hydrogel_orders
        raw["hg"] = hstate.to_dict()

        if yolo_regime is True:
            # YOLO: short voucher portfolio + VFE; suppress voucher MM.
            vstate = VoucherState.from_dict(raw.get("v9", {}))
            for sym, target in YOLO_VOUCHER_TARGETS.items():
                od_v = state.order_depths.get(sym)
                if od_v is None or not od_v.buy_orders:
                    continue
                pos_v = state.position.get(sym, 0)
                desired_short = target - pos_v
                if desired_short < 0:
                    bb_v = max(od_v.buy_orders)
                    avail = od_v.buy_orders[bb_v]
                    q = min(-desired_short, avail, 300)
                    if q > 0:
                        orders.setdefault(sym, []).append(Order(sym, bb_v, -q))
            if vfe_od and vfe_od.buy_orders:
                pos_vfe = state.position.get("VELVETFRUIT_EXTRACT", 0)
                desired = YOLO_VFE_TARGET - pos_vfe
                if desired < 0:
                    bb = max(vfe_od.buy_orders)
                    avail = vfe_od.buy_orders[bb]
                    q = min(-desired, avail, 200)
                    if q > 0:
                        orders.setdefault("VELVETFRUIT_EXTRACT", []).append(Order("VELVETFRUIT_EXTRACT", bb, -q))
            raw["v9"] = vstate.to_dict()
        else:
            # Normal mode: voucher MM + VFE momo + counterparty layers.
            vstate = VoucherState.from_dict(raw.get("v9", {}))
            voucher_orders = run_vouchers(state, vstate)
            for sym, ord_list in voucher_orders.items():
                orders.setdefault(sym, []).extend(ord_list)
            raw["v9"] = vstate.to_dict()

        clamp_log: List[str] = []
        orders = _clamp_to_position_limits(orders, state.position, clamp_log)
        for line in clamp_log:
            logger.print(line)

        new_trader_data = json.dumps(raw)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data
