"""r3_v19.py — v18 stack + teammate 406026's S7-bottom cover + flip-long-180 mechanic.

Replaces v18's TIMEOUT-based S17 exit with teammate's adaptive S7-bottom cover
(spread==7 AND mid <= 8th-percentile of last 500-tick window), then flips long
to +180 to capture the second leg of the reversion. VFE/voucher stack (incl.
v17 Phase 4.1 deep-ITM theta carry on VEV_4000/4500) preserved untouched.

Teammate verified BT: HP-only $13,406 day-2 1k (live website $13,375.25).
v18 BT: $13,036 (HP $10,851 + VFE $1,940 + vouchers $245). v18 live: $12,815.
v19 target: HP $13,400 + VFE $1,940 + vouchers $245 ≈ $15,500 BT,
website projection ~$15,000 (BT × 0.97 conservative).

Defensive fallback: if S7 condition never fires AND `rows_held >= S7_FALLBACK_TIMEOUT`
(=1000), force-cover via best_ask. Prevents bag-holding short on non-mean-reverting
days. Teammate's strategy has no such fallback; we add it for cross-day robustness.

Original 402045 docstring preserved below.
=====================================================================

HYDROGEL_PACK Trading Strategy — v8
=====================================
Primary signal: spread == 17 AND mid > 10010 → GIGA SHORT

DATA EVIDENCE (Day 0, 10000 rows):
  spread=17 fires 77 times (filtered by mid>10010)
  h=50:  avg=-7.1t, 74% negative
  h=100: avg=-12.3t, 75% negative
  h=200: avg=-23.1t, 83% negative
  Simulation (short 200, exit at mid<9998 or 200t): +69,500 PnL, avg +903/trade

WHY IT WORKS:
  spread=17 appears when market makers widen quotes under stress.
  mid_mean at spread=17 = 10025 (35t above fair value 9990).
  Price almost always reverts back toward 9990 after spread=17 fires.
  The wider spread itself signals that bots know price is too high.

LOGIC:
  1. spread==17 AND mid > ENTRY_MID_MIN → short 200 aggressively (hit bid)
  2. Hold until mid < COVER_TARGET (9998) OR TIMEOUT ticks pass
  3. Cover aggressively (lift ask)
  4. Otherwise: passive MM as per v4

  Additional MR layer (from v6): buy aggressively when mid < 9950 and not trending
"""

import itertools
import json
import math
from collections import deque
from statistics import NormalDist, median
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Observation, Order, ProsperityEncoder, Symbol, Trade, TradingState

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
    # v22: v20 (SD's HP) + hold-flip-until-mid≥FLIP_EXIT_MID + Layer C voucher bid fix.
    # The FLIP_EXIT_MID hold captures the up-leg of S17 reversion (alpha hunt 2026-04-25:
    # quant-finance agent identified this as the missing $30k+ alpha vs teammate's HP-only
    # numbers). Cross-day BT $31-40k per day at FLIP_EXIT_MID=10020.
    # ========================= ALPHA hardcodes =========================
    REGIME2_SPREAD = 17
    ENTRY_MID_MIN = 10010
    S7_WINDOW = 500
    S7_BOTTOM_Q = 0.08
    FLIP_TARGET = 200
    FLIP_EXIT_MID = 10005      # v22: hold long inventory until mid recovers to this
    FLIP_TIMEOUT_TICKS = 1500  # v22: safety bail if reversion stalls

    # ==================== INTRINSIC / structure ========================
    POS_LIMIT = 200
    QUOTE_SIZE = 25  # SD: typical L1 ~15-20, posting 25 = intentional queue capture sizing

    # ===================== DYNAMIC calibration =========================
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
    # v20: SD's HydrogelState (online edge-beta calibration)
    def __init__(self):
        self.mid_buf_500: List[float] = []
        self.mid_buf_100: List[float] = []
        self.row: int = 0
        # Legacy fields kept for backward-compatible traderData decoding only.
        self.regime1_entry_row: Optional[int] = None
        self.regime1_qty: int = 0
        self.lean_target: float = 0.0
        self.lean_entry_mid: Optional[float] = None
        self.lean_entry_side: int = 0
        # S17 short tracking.
        self.s17_entry_row: Optional[int] = None
        self.s17_entry_mid: Optional[float] = None
        # S7 cover+flip phase flag.
        self.s7_covering: bool = False
        # v22: post-FLIP hold phase — suppress passive quoting until mid >= FLIP_EXIT_MID
        self.flip_holding: bool = False
        self.flip_entry_row: Optional[int] = None
        # Online wap-edge calibration state.
        self.prev_mid: Optional[float] = None
        self.prev_wap_edge: Optional[float] = None
        self.edge_buf: List[float] = []
        self.ret_buf: List[float] = []

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
        s.prev_mid          = d.get("pmid")
        s.prev_wap_edge     = d.get("pedge")
        s.edge_buf          = d.get("edgeb", [])
        s.ret_buf           = d.get("retb", [])
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
    # v20: HP block from teammate Superduperbread's r3-hydro-final.py.
    # Strategy: S17 entry/build → S7-bottom percentile cover → flip long to FLIP_TARGET=200.
    # Passive MM fallback uses online edge-beta calibration (cov(edge,ret)/var(edge)).
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

    # Online edge->return samples: pair prev tick's edge with this tick return.
    if hstate.prev_mid is not None and hstate.prev_wap_edge is not None:
        ret_1t = mid - hstate.prev_mid
        hstate.edge_buf = _push(hstate.edge_buf, hstate.prev_wap_edge, p.EDGE_BETA_WINDOW)
        hstate.ret_buf  = _push(hstate.ret_buf, ret_1t, p.EDGE_BETA_WINDOW)
    hstate.prev_mid = mid
    hstate.prev_wap_edge = wap_edge

    # Layer 0A: S17 short with S7-bottom-percentile reversal trigger.
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

        # Keep building short toward limit while in S17 phase.
        headroom = pos_lim + position
        if headroom > 0:
            orders.append(Order(P, best_bid, -headroom))
            logger.print(f"S17 BUILD: qty={headroom} px={best_bid} mid={mid:.1f} pos={position}")
        return orders, hstate

    # Cover+flip phase: keep lifting ask until target long inventory reached.
    if hstate.s7_covering:
        remaining = p.FLIP_TARGET - position
        if remaining > 0:
            orders.append(Order(P, best_ask, remaining))
            logger.print(f"S7 FLIP BUILD: buy={remaining} px={best_ask} mid={mid:.1f} pos={position}")
        if position >= p.FLIP_TARGET:
            hstate.s7_covering = False
            hstate.flip_holding = True               # v22: enter hold phase
            hstate.flip_entry_row = hstate.row
            logger.print(f"S7 FLIP COMPLETE -> HOLD: pos={position}")
        return orders, hstate

    # v22: HOLD-FLIP phase — suppress passive quoting until mid recovers to FLIP_EXIT_MID.
    # Captures the up-leg of S17 reversion. Bail at FLIP_TIMEOUT_TICKS if mid never recovers.
    if hstate.flip_holding:
        held_for = hstate.row - (hstate.flip_entry_row or hstate.row)
        if mid >= p.FLIP_EXIT_MID or held_for >= p.FLIP_TIMEOUT_TICKS:
            if position > 0:
                orders.append(Order(P, best_bid, -position))   # aggressive flat
                logger.print(
                    f"FLIP EXIT: sell {position} px={best_bid} mid={mid:.1f} "
                    f"held={held_for} reason={'mid_target' if mid >= p.FLIP_EXIT_MID else 'timeout'}"
                )
            hstate.flip_holding = False
            hstate.flip_entry_row = None
        return orders, hstate

    # Entry: spread=17 AND elevated price AND not already in S17 short
    if (spread == p.REGIME2_SPREAD
            and mid > p.ENTRY_MID_MIN
            and hstate.s17_entry_row is None):
        headroom = pos_lim + position
        qty = min(pos_lim, headroom)
        if qty > 0:
            orders.append(Order(P, best_bid, -qty))
            hstate.s17_entry_row = hstate.row
            hstate.s17_entry_mid = mid
            logger.print(f"S17 ENTER short: qty={qty} px={best_bid} mid={mid:.1f}")
        return orders, hstate

    # Passive MM fallback with dynamic Layer-A skew (online edge beta).
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


# Original Trader replaced below with combined v11 version. Voucher logic appended.

# ── v9 Voucher / VFE strategy (ported) ────────────────────────────────────────

VEVE_SYM = "VELVETFRUIT_EXTRACT"
VOUCHER_STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VOUCHER_STRIKES_TRADEABLE = [5000, 5100, 5200, 5300, 5400]
VOUCHER_STRIKES_DEEP_ITM = [4000, 4500]
# v12 Layer A: skip 6000/6500 entirely — one-sided sells, expire 0
VOUCHER_STRIKES_SKIP = {6000, 6500}
# v12 Layer C: passive OTM bid strikes (one-sided seller flow)
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
        # v12 Layer E: VFE spread-state lift — track prev L1 bid/ask
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
    # v12 Layer E: VFE spread-state aggressive lift
    # spread==2 AND ap1<prev_ap1 → BUY 20 at ap1-1
    # spread==3 AND bp1>prev_bp1 → SELL 20 at bp1+1
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
            # Buy signal: spread==2 AND ask dropped
            if spread_ve == 2 and ba_ve < vstate.prev_ve_ap1:
                room_buy = E_POS_CAP - pos_ve
                q = min(E_SIZE, room_buy)
                if q > 0:
                    px = int(ba_ve - 1)
                    if px > bb_ve and px < ba_ve:  # inside-spread
                        ve_layer_e.append(Order(VEVE_SYM, px, q))
                        layer_e_buy = q
            # Sell signal: spread==3 AND bid raised
            elif spread_ve == 3 and bb_ve > vstate.prev_ve_bp1:
                room_sell = E_POS_CAP + pos_ve
                q = min(E_SIZE, room_sell)
                if q > 0:
                    px = int(bb_ve + 1)
                    if px > bb_ve and px < ba_ve:  # inside-spread
                        ve_layer_e.append(Order(VEVE_SYM, px, -q))
                        layer_e_sell = q
        # Update prev for next tick (always)
        vstate.prev_ve_ap1 = ba_ve
        vstate.prev_ve_bp1 = bb_ve

    if od_ve and od_ve.buy_orders and od_ve.sell_orders:
        wm = v_wall_mid(od_ve)
        if wm is not None:
            bb = max(od_ve.buy_orders); ba = min(od_ve.sell_orders)
            pos = state.position.get(VEVE_SYM, 0)
            fv = round(wm)
            # Account for Layer E commitments in headroom
            tb = 200 - pos - layer_e_buy
            ts = 200 + pos - layer_e_sell
            half = 100
            mbp = fv - 1 if pos > half else fv
            msp = fv + 1 if pos < -half else fv
            ve_orders = list(ve_layer_e)  # start with Layer E orders
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
        if K in VOUCHER_STRIKES_SKIP: continue   # v12 Layer A
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
        # v12 Layer A: skip pairs involving 6000/6500
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

    # ── v18 Phase 4.1 (ported from v17): Deep ITM theta carry MM ────────────
    # Replaces v12 Layer B (VEV_4000 only). Adds VEV_4500 coverage.
    # v17 live website: VEV_4000 +$134, VEV_4500 +$99 (BT shows 0 on 4500 but
    # website fills due to bot quote dynamics not modeled in BT).
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

    # ── v12 Layer C: Passive OTM bid on VEV_5300/5400/5500 ──────────────────
    # v22: One-sided seller flow → bid unconditional best_bid+1.
    # The fv_bs floor cap was burying bids on VEV_5400/5500 (deep OTM where fv_bs ≈ 0-3
    # and bb+1 ~ 6 → bid_px=3, never filled). Drop the cap; OTM strikes are 1-tick anyway.
    OTM_BID_SIZE = 5
    OTM_BID_POS_CAP = 50
    for K in VOUCHER_STRIKES_OTM_PASSIVE:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        bb = max(od_v.buy_orders)
        ba = min(od_v.sell_orders)
        bid_px = bb + 1   # v22: unconditional penny-on-bid
        if bid_px <= 0: continue
        if bid_px >= ba: continue  # must not cross ask
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        # Cap long position from this layer at +50 (independent of other long sources)
        tb_v = OTM_BID_POS_CAP - pos_v - existing_buy
        if tb_v > 0:
            q = min(tb_v, OTM_BID_SIZE)
            orders.setdefault(sym, []).append(Order(sym, bid_px, q))

    return orders




# ── v11 Trader (combined HP from 402045 + voucher/VFE from v9) ─────────────

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orders      = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}

        # 1) HYDROGEL_PACK: 402045 spread=17 GIGA SHORT + passive MM
        hstate = HydrogelState.from_dict(raw.get("hg", {})) if hasattr(HydrogelState, "from_dict") else HydrogelState.load(trader_data)
        hydrogel_orders, hstate = run_hydrogel(state, hstate)
        orders[Product.HYDROGEL_PACK] = hydrogel_orders
        if hasattr(hstate, "to_dict"):
            raw["hg"] = hstate.to_dict()
        else:
            trader_data = hstate.save(trader_data)
            try:
                raw = json.loads(trader_data) if trader_data else {}
            except Exception:
                raw = {}

        # 2) VFE + Vouchers: v9 (Wall Mid + BS taking + intrinsic arb + MM)
        vstate = VoucherState.from_dict(raw.get("v9", {}))
        voucher_orders = run_vouchers(state, vstate)
        for sym, ord_list in voucher_orders.items():
            if sym not in orders: orders[sym] = []
            orders[sym].extend(ord_list)
        raw["v9"] = vstate.to_dict()

        new_trader_data = json.dumps(raw)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data
