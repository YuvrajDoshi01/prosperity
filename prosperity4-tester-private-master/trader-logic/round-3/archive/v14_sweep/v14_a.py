"""r3_v11.py — 402045's spread=17 GIGA SHORT HP + v9's voucher/VFE strategy.

Combines:
  - 402045 HP strategy: spread==17 AND mid>10010 → short 200, exit at mid<9998
    Day 2 1k-tick: $10,224 (vs v9 $606, +$9,618)
  - v9 BS voucher taking + Wall Mid VFE MM + intrinsic arb + call-spread arb

Expected 1k-tick day 2: ~$12,300 (HP $10,224 + VFE $1,940 + vouchers $156)
Expected website score: ~$12,200 (BT × 0.99 verified ratio)

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

    # ── Global fair value ─────────────────────────────────────────────────
    GLOBAL_MEAN = 9990

    # ── Spread=17 SHORT signal ────────────────────────────────────────────
    # Entry: spread==17 AND mid > ENTRY_MID_MIN
    # Size: full 200 units (GIGA short)
    # Exit: mid < COVER_TARGET OR row > entry_row + TIMEOUT
    ENTRY_MID_MIN  = 10010   # only short if price is elevated (not just random spread=17)
    COVER_TARGET   = 9985    # v14a: lower lock-in
    TIMEOUT        = 200     # max ticks to hold the short

    # ── MR long signal (from v6) ──────────────────────────────────────────
    # Buy aggressively when price is very low AND not trending down
    BUY_THRESH     = 9950
    EXIT_BAND      = 8
    MR_QTY         = 50
    TREND_FILTER   = 15
    TREND_WINDOW   = 50

    # ── Passive MM (v4 unchanged) ─────────────────────────────────────────
    REGIME1_SPREAD_THRESHOLD = 10
    REGIME1_IMB_THRESHOLD    = 999.0
    REGIME1_EXIT_ROWS        = 10
    REGIME1_ENTRY_SIZE       = 1
    REGIME2_SPREAD             = 17   # NOTE: regime2 flatten is DISABLED — we WANT spread=17
    REGIME2_FLATTEN_AGGRESSIVE = False
    LAYER_A_SCALE  = 3.0
    LAYER_A_CLIP   = 1.0
    INV_ADJ_CLIP   = 3.0
    INV_ADJ_COEFF  = 0.1
    QUOTE_SIZE     = 50
    POS_LIMIT      = 200
    HP_VOL_WINDOW  = 20
    HP_SLACK_MIN   = 1
    HP_SLACK_MAX   = 3
    HP_SLACK_COEF  = 0.5
    POS_AGGRESSION_FRAC = 0.5
    Z500_WINDOW    = 500
    STD100_WINDOW  = 100


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
    def __init__(self):
        self.mid_buf_500: List[float] = []
        self.mid_buf_100: List[float] = []
        self.row: int = 0
        # v4 regime tracking
        self.regime1_entry_row: Optional[int] = None
        self.regime1_qty: int = 0
        self.lean_target: float = 0.0
        self.lean_entry_mid: Optional[float] = None
        self.lean_entry_side: int = 0
        # v8 spread=17 short tracking
        self.s17_entry_row: Optional[int] = None   # row we entered the short
        self.s17_entry_mid: Optional[float] = None
        # v6 MR long tracking
        self.mr_side: int = 0
        self.mr_entry_mid: Optional[float] = None
        # v12 Layer D: open-dump SHORT tracking
        self.day_open: Optional[float] = None     # first observed mid
        self.od_entry_row: Optional[int] = None
        self.od_entry_mid: Optional[float] = None

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
            "mr_side":   self.mr_side,
            "mr_emid":   self.mr_entry_mid,
            "do":        self.day_open,
            "od_row":    self.od_entry_row,
            "od_mid":    self.od_entry_mid,
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
        s.mr_side           = d.get("mr_side", 0)
        s.mr_entry_mid      = d.get("mr_emid")
        s.day_open          = d.get("do")
        s.od_entry_row      = d.get("od_row")
        s.od_entry_mid      = d.get("od_mid")
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
    imb_L1   = features["imbalance_L1"]
    wap_edge = features["book_wap_edge_L3"]

    # Update buffers
    z500 = None
    if len(hstate.mid_buf_500) == p.Z500_WINDOW:
        z500 = _zscore(hstate.mid_buf_500, mid)
    hstate.mid_buf_500 = _push(hstate.mid_buf_500, mid, p.Z500_WINDOW)
    hstate.mid_buf_100 = _push(hstate.mid_buf_100, mid, p.STD100_WINDOW)
    hstate.row += 1

    # v12 Layer D: capture day_open on first observation
    if hstate.day_open is None:
        hstate.day_open = mid

    # Trend filter for MR entries
    trend_buf    = hstate.mid_buf_100[-p.TREND_WINDOW:]
    roll_mean_50 = _mean(trend_buf)
    trend_drift  = (roll_mean_50 - p.GLOBAL_MEAN) if roll_mean_50 is not None else 0.0
    trending_down = trend_drift < -p.TREND_FILTER

    # ─────────────────────────────────────────────────────────────────────
    # v12 Layer D: HP open-dump SHORT at tick=100
    # Persistent open-dump pattern across all 3 days. At tick=100
    # (timestamp=10000), if mid > day_open + 5, SHORT 200 aggressively.
    # Exit when mid < day_open OR tick > 600.
    # ─────────────────────────────────────────────────────────────────────
    OD_ENTRY_TS = 10_000   # tick 100
    OD_EXIT_TS  = 60_000   # tick 600
    OD_TRIGGER_OFFSET = 5  # mid > day_open + 5
    ts = state.timestamp

    # Open-dump exit check
    if hstate.od_entry_row is not None and position < 0:
        should_exit = (mid < hstate.day_open) or (ts > OD_EXIT_TS)
        if should_exit:
            cover_qty = -position
            orders.append(Order(P, best_ask, cover_qty))
            logger.print(
                f"OD COVER: qty={cover_qty} px={best_ask} mid={mid:.1f} "
                f"day_open={hstate.day_open:.1f} ts={ts}"
            )
            hstate.od_entry_row = None
            hstate.od_entry_mid = None
            return orders, hstate
        # Keep building short
        headroom = pos_lim + position
        if headroom > 0:
            orders.append(Order(P, best_bid, -headroom))
            logger.print(f"OD BUILD: qty={headroom} px={best_bid} mid={mid:.1f} pos={position}")
        return orders, hstate

    # Open-dump entry: at tick=100 (timestamp 10000), if mid > day_open + 5
    if (ts == OD_ENTRY_TS
            and hstate.day_open is not None
            and mid > hstate.day_open + OD_TRIGGER_OFFSET
            and hstate.s17_entry_row is None
            and hstate.od_entry_row is None):
        headroom = pos_lim + position
        qty = min(pos_lim, headroom)
        if qty > 0:
            orders.append(Order(P, best_bid, -qty))
            hstate.od_entry_row = hstate.row
            hstate.od_entry_mid = mid
            logger.print(
                f"OD ENTER short: qty={qty} px={best_bid} mid={mid:.1f} "
                f"day_open={hstate.day_open:.1f}"
            )
        return orders, hstate

    # ─────────────────────────────────────────────────────────────────────
    # LAYER 0A: SPREAD=17 GIGA SHORT
    # When spread widens to 17 AND price is elevated → short everything
    # ─────────────────────────────────────────────────────────────────────

    # Check exit first: cover if price returned to mean or timeout
    if hstate.s17_entry_row is not None and position < 0:
        rows_held = hstate.row - hstate.s17_entry_row
        should_cover = (
            mid <= p.COVER_TARGET          # price returned to near mean
            or rows_held >= p.TIMEOUT      # held long enough
        )
        if should_cover:
            cover_qty = -position          # cover full short
            orders.append(Order(P, best_ask, cover_qty))  # lift ask to cover
            logger.print(
                f"S17 COVER: qty={cover_qty} px={best_ask} mid={mid:.1f} "
                f"rows_held={rows_held} entry={hstate.s17_entry_mid:.1f} "
                f"pnl_est={(hstate.s17_entry_mid - mid) * cover_qty:.0f}"
            )
            hstate.s17_entry_row = None
            hstate.s17_entry_mid = None
            return orders, hstate

        # Keep building to -200: hit bid with full remaining headroom every tick
        headroom = pos_lim + position  # how much more we can short
        if headroom > 0:
            orders.append(Order(P, best_bid, -headroom))
            logger.print(f"S17 BUILD: qty={headroom} px={best_bid} mid={mid:.1f} pos={position}")
        return orders, hstate

    # Entry: spread=17 AND elevated price AND not already in S17 short
    if (spread == p.REGIME2_SPREAD
            and mid > p.ENTRY_MID_MIN
            and hstate.s17_entry_row is None):
        headroom = pos_lim + position
        qty = min(pos_lim, headroom)   # FULL position — giga short
        if qty > 0:
            orders.append(Order(P, best_bid, -qty))  # hit bid aggressively
            hstate.s17_entry_row = hstate.row
            hstate.s17_entry_mid = mid
            logger.print(f"S17 ENTER short: qty={qty} px={best_bid} mid={mid:.1f}")
        return orders, hstate

    # ─────────────────────────────────────────────────────────────────────
    # LAYER 0B: MR LONG (price too low → buy aggressively)
    # ─────────────────────────────────────────────────────────────────────

    dist_from_mean = mid - p.GLOBAL_MEAN

    # MR exit
    if hstate.mr_side == 1 and position > 0 and abs(dist_from_mean) <= p.EXIT_BAND:
        orders.append(Order(P, best_bid, -position))
        logger.print(f"MR EXIT long pos={position} mid={mid:.1f}")
        hstate.mr_side = 0; hstate.mr_entry_mid = None
        return orders, hstate

    # MR entry
    if mid <= p.BUY_THRESH and not trending_down and hstate.s17_entry_row is None:
        headroom = pos_lim - position
        qty = min(p.MR_QTY, headroom)
        if qty > 0:
            orders.append(Order(P, best_ask, qty))
            if hstate.mr_side != 1:
                hstate.mr_side = 1; hstate.mr_entry_mid = mid
                logger.print(f"MR ENTER long qty={qty} mid={mid:.1f}")
        return orders, hstate

    # ─────────────────────────────────────────────────────────────────────
    # REGIME 1: tight spread (unchanged from v4)
    # ─────────────────────────────────────────────────────────────────────
    if spread < p.REGIME1_SPREAD_THRESHOLD:
        if hstate.regime1_entry_row is not None:
            if hstate.row - hstate.regime1_entry_row >= p.REGIME1_EXIT_ROWS:
                if hstate.regime1_qty > 0:
                    eq = min(hstate.regime1_qty, position)
                    if eq > 0: orders.append(Order(P, best_ask, -eq))
                elif hstate.regime1_qty < 0:
                    eq = min(-hstate.regime1_qty, -position)
                    if eq > 0: orders.append(Order(P, best_bid, eq))
                hstate.regime1_entry_row = None; hstate.regime1_qty = 0
        else:
            if imb_L1 > p.REGIME1_IMB_THRESHOLD:
                qty = min(p.REGIME1_ENTRY_SIZE, pos_lim - position)
                if qty > 0:
                    orders.append(Order(P, best_ask, qty))
                    hstate.regime1_entry_row = hstate.row; hstate.regime1_qty = qty
            elif imb_L1 < -p.REGIME1_IMB_THRESHOLD:
                qty = min(p.REGIME1_ENTRY_SIZE, pos_lim + position)
                if qty > 0:
                    orders.append(Order(P, best_bid, -qty))
                    hstate.regime1_entry_row = hstate.row; hstate.regime1_qty = -qty
        return orders, hstate
    else:
        if hstate.regime1_entry_row is not None:
            hstate.regime1_entry_row = None; hstate.regime1_qty = 0

    # ─────────────────────────────────────────────────────────────────────
    # PASSIVE MM (v4 — runs when no directional trade active)
    # ─────────────────────────────────────────────────────────────────────
    skew_A  = _clip(wap_edge * p.LAYER_A_SCALE, -p.LAYER_A_CLIP, p.LAYER_A_CLIP)
    inv_adj = _clip((hstate.lean_target - position) * p.INV_ADJ_COEFF,
                    -p.INV_ADJ_CLIP, p.INV_ADJ_CLIP)
    bid_offset = skew_A + inv_adj

    vol_buf = hstate.mid_buf_100[-p.HP_VOL_WINDOW:]
    sigma   = _std(vol_buf) if len(vol_buf) >= 5 else None
    slack   = p.HP_SLACK_MIN if sigma is None else max(
        p.HP_SLACK_MIN, min(p.HP_SLACK_MAX, int(round(p.HP_SLACK_COEF * sigma))))

    fv = int(round(mid))
    bid_headroom = pos_lim - position
    ask_headroom = pos_lim + position

    half_thresh = pos_lim * p.POS_AGGRESSION_FRAC
    mbp = fv - 1 if position >  half_thresh else fv
    msp = fv + 1 if position < -half_thresh else fv

    for px, vol in sorted(od.sell_orders.items()):
        if bid_headroom <= 0 or px > mbp: break
        take = min(bid_headroom, abs(vol))
        if take > 0:
            orders.append(Order(P, px, take)); bid_headroom -= take

    for px, vol in sorted(od.buy_orders.items(), reverse=True):
        if ask_headroom <= 0 or px < msp: break
        take = min(ask_headroom, vol)
        if take > 0:
            orders.append(Order(P, px, -take)); ask_headroom -= take

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

    # ── v12 Layer B: VEV_4000 best±1 SIZE=5 MM ──────────────────────────────
    # VEV_4000 is currently $0 in v11 day-2 1k. Add passive both-sided MM.
    # qty 5, position cap ±50 to leave headroom for intrinsic arb.
    K4000 = 4000
    sym_4000 = VOUCHER_SYM[K4000]
    od_4000 = state.order_depths.get(sym_4000)
    if od_4000 is not None and od_4000.buy_orders and od_4000.sell_orders:
        vbb = max(od_4000.buy_orders); vba = min(od_4000.sell_orders)
        if vba - vbb >= 2:  # need at least 2 spread for inside-spread room
            pos_v = state.position.get(sym_4000, 0)
            existing = orders.get(sym_4000, [])
            existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
            existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
            MM_4000_SIZE = 5
            MM_4000_POS_CAP = 50
            tb_v = MM_4000_POS_CAP - pos_v - existing_buy
            ts_v = MM_4000_POS_CAP + pos_v - existing_sell
            if tb_v > 0:
                q = min(tb_v, MM_4000_SIZE)
                orders.setdefault(sym_4000, []).append(Order(sym_4000, vbb + 1, q))
            if ts_v > 0:
                q = min(ts_v, MM_4000_SIZE)
                orders.setdefault(sym_4000, []).append(Order(sym_4000, vba - 1, -q))

    # ── v12 Layer C: Passive OTM bid on VEV_5300/5400/5500 ──────────────────
    # One-sided seller flow → bid at min(best_bid+1, floor(BS_fair-2)).
    # Posting BELOW best_bid is fine — taker hits all levels; we just queue.
    # qty 5 per strike, cap +50 long. No asks (no buyer flow).
    OTM_BID_SIZE = 5
    OTM_BID_POS_CAP = 50
    OTM_BID_EDGE = 2  # bid must be at least 2 below BS fair
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
