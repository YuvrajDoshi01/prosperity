"""r3_v10.py — 401389's HP day-type detection + v9's voucher/VFE strategy.

Combines:
  - 401389 HP trend-follow (TREND SHORT day 2 captures 200-unit short, +$2.5k vs v9)
  - v9 BS voucher taking (BS_EDGE=10, adaptive sigma)
  - v9 Wall Mid VELVETFRUIT_EXTRACT MM
  - v9 intrinsic arb on 4000/4500 + call-spread arb scanner

Original 401389 docstring preserved below for reference.
=====================================================================

HYDROGEL_PACK Trading Strategy — v7 (from 401389)
=====================================
Three-mode strategy based on day-type detection at open.

KEY INSIGHT:
  HYDROGEL_PACK has a stable fair value of ~9990 across all days.
  BUT different days have different regimes:

  TRENDING DAY   (price opens far from 9990):
    - Price opened at 10011 on Day 2, rm20 was +31 above mean by ts=2000
    - Price then trended from 10031 all the way to 9915 (116 tick range)
    - Winner made ~19500 by holding 200 short from ~10020 to ~9920
    - Strategy: SHORT aggressively at open, hold, cover near mean

  MEAN-REVERTING DAY (price opens near 9990):
    - Price oscillates around 9990 all day
    - Strategy: buy aggressively when price < 9950, sell when > 10035
    - Exit when price returns to 9990 ± EXIT_BAND

  PASSIVE MM (always running when not in directional trade):
    - v4 passive market making, collects spread on every bot trade

DAY TYPE DETECTION:
  Use rm20 (20-tick rolling mean) which is ready at ts=2000.
  If rm20 > GLOBAL_MEAN + TREND_OPEN_THRESH → SHORT day
  If rm20 < GLOBAL_MEAN - TREND_OPEN_THRESH → LONG day
  Else → mean-revert day

  Once day type is set at ts=2000 (row 20), it is LOCKED for the day.
  We don't re-detect mid-day (avoids flip-flopping).

SIMULATION RESULTS:
  Day 0 (MR day):  v6 MR strategy → ~46k theoretical, ~19k on live website
  Day 2 (trend):   short 200 from open, hold to low → ~17-20k PnL
"""

import itertools
import json
import math
from collections import deque
from statistics import NormalDist, median
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Observation, Order, ProsperityEncoder, Symbol, Trade, TradingState

_ND_VOUCHER = NormalDist()


# ── Logger ────────────────────────────────────────────────────────────────────

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


# ── Products & limits ─────────────────────────────────────────────────────────

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


# ── Parameters ────────────────────────────────────────────────────────────────

class HydrogelParams:

    # ── Global fair value ─────────────────────────────────────────────────
    GLOBAL_MEAN = 9990      # stable across all 3 days (mean=9990.8, std=31.9)

    # ── Day type detection ────────────────────────────────────────────────
    # Detect at row 20 (ts=2000) using rm20.
    # If rm20 is far from GLOBAL_MEAN → trending day.
    # Locked for the rest of the day once set.
    DAY_DETECT_ROW        = 20     # detect at this row
    TREND_OPEN_THRESH     = 20     # rm20 must be 20+ ticks from mean to call trend
                                   # Day 2: rm20=+31.9 → TREND. Day 0: rm20=+12 → MR.

    # ── Trend-follow mode (triggered on trending days) ────────────────────
    # Build full 200-unit position in first few ticks.
    # Cover in chunks as price moves in our favour.
    # Cover everything when price reaches COVER_TARGET from mean.
    TREND_BUILD_TICKS     = 4      # build position over first 4 ticks (50/tick)
    TREND_BUILD_QTY       = 50     # units per build tick
    TREND_COVER_TARGET    = 10     # cover earlier near mean to lock gains
    TREND_COVER_QTY       = 75     # larger cover chunks to avoid round-tripping PnL

    # ── Trend invalidation (one-way safety override — MtM based) ─────────
    # After trend build completes, track mark-to-market each tick.
    # mtm_per_unit = (mid - trend_entry_mid) * direction
    #   positive → trade is working
    #   negative → trade is losing
    # If mtm_per_unit stays below -TREND_INVAL_LOSS_THRESH for
    # TREND_INVAL_ROWS consecutive ticks → bail out to passive MM.
    # This is more direct than rm50 drift: it asks "are we actually losing?"
    TREND_INVAL_ENABLE     = True
    TREND_INVAL_LOSS_THRESH = 5.0  # ticks of adverse move from entry mid
    TREND_INVAL_ROWS        = 40   # must persist for this many rows
    TREND_INVAL_COOLDOWN    = 200  # rows lockout after invalidation

    # ── Wide-spread cluster fade (SHORT-ONLY) ────────────────────────────
    # Empirical (verified via offline analysis with realistic spread cost):
    #   * Clusters of spread>=17 cluster near LOCAL PRICE PEAKS
    #   * Short-fade at peak works; long-fade at trough loses every day.
    #   * Round-trip spread cost ≈ 16 ticks → must use TP/stop-based exit,
    #     NOT mean-reversion exit (mean-reversion eats the entire spread).
    #
    # Tuned params (realistic-fill sweep, qty=50, k=2, win=50, lw=50):
    #   thr=15, tp=30, stop=20  →  +1,287 total, 8 trades, 87.5% win rate
    WSC_ENABLE         = True
    WSC_SPREAD_THRESH  = 17    # tick count for "wide" spread
    WSC_WINDOW         = 50    # rolling window of recent ticks
    WSC_CLUSTER_COUNT  = 2     # # of spread>=17 ticks within window to fire
    WSC_LOCAL_WINDOW   = 50    # rolling mean window for local extreme detection
    WSC_LOCAL_DIST     = 15    # mid - local_mean must exceed this to fire
    WSC_QTY            = 50    # units per fade entry (book depth caps actual fill)
    WSC_MAX_POS        = 100   # cap on total WSC position
    WSC_TP_TICKS       = 30    # cover when entry_mid - mid >= this
    WSC_STOP_TICKS     = 20    # cover when mid - entry_mid >= this (stop-loss)
    WSC_COOLDOWN       = 50    # rows between consecutive cluster fires
    WSC_MAX_HOLD       = 200   # force-cover after this many rows

    # ── Mean-reversion mode (triggered on MR days) ───────────────────────
    BUY_THRESH   = 9950    # aggressively buy when mid <= this
    SELL_THRESH  = 10035   # aggressively sell when mid >= this
    EXIT_BAND    = 8       # flatten MR position when within 8t of mean
    MR_QTY       = 50      # units per aggressive MR order

    # Trend filter for MR entries (from v6)
    TREND_FILTER  = 15     # block MR entry if rm50 drifted > this from mean
    TREND_WINDOW  = 50     # window for trend filter

    # ── Passive MM (v4, always runs when not in directional trade) ────────
    REGIME1_SPREAD_THRESHOLD = 10
    REGIME1_IMB_THRESHOLD    = 999.0
    REGIME1_EXIT_ROWS        = 10
    REGIME1_ENTRY_SIZE       = 1
    REGIME2_SPREAD             = 17
    REGIME2_FLATTEN_AGGRESSIVE = True
    LAYER_A_SCALE = 3.0
    LAYER_A_CLIP  = 1.0
    LAYER_B_SCALE = 0.0
    REGIME3_Z_ENTER        = 2.0
    REGIME3_Z_EXIT         = 0.5
    REGIME3_STOP_TICKS     = 20
    Z500_WINDOW            = 500
    STD100_WINDOW          = 100
    MEAN_ANCHOR_WINDOW     = 100
    MEAN_ANCHOR_STD_MULTIPLIER = 1.0
    INV_ADJ_CLIP  = 3.0
    INV_ADJ_COEFF = 0.1
    QUOTE_SIZE    = 50
    POS_LIMIT     = 200
    HP_VOL_WINDOW = 20
    HP_SLACK_MIN  = 1
    HP_SLACK_MAX  = 3
    HP_SLACK_COEF = 0.5
    POS_AGGRESSION_FRAC = 0.5


# ── Math helpers ──────────────────────────────────────────────────────────────

def _mean(buf):
    return sum(buf) / len(buf) if buf else None

def _std(buf):
    n = len(buf)
    if n < 2: return None
    mu = sum(buf) / n
    return (sum((x - mu) ** 2 for x in buf) / (n - 1)) ** 0.5

def _zscore(buf, value):
    mu = _mean(buf)
    sd = _std(buf)
    if mu is None or sd is None or sd == 0: return None
    return (value - mu) / sd

def _push(buf, value, maxlen):
    buf = buf + [value]
    return buf[-maxlen:] if len(buf) > maxlen else buf

def _clip(value, lo, hi):
    return max(lo, min(hi, value))


# ── Book features ─────────────────────────────────────────────────────────────

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
        "best_bid":         best_bid,
        "best_ask":         best_ask,
        "spread":           spread,
        "mid":              mid,
        "imbalance_L1":     imbalance_L1,
        "book_wap_edge_L3": book_wap_edge_L3,
    }


# ── Persistent state ──────────────────────────────────────────────────────────

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
        # v6 MR tracking
        self.mr_side: int = 0
        self.mr_entry_mid: Optional[float] = None
        # v7 day type (locked once detected)
        # 0 = unknown, 1 = trend short day, -1 = trend long day, 2 = MR day
        self.day_type: int = 0
        self.trend_built: bool = False  # have we built the trend position?
        self.trend_entry_mid: Optional[float] = None  # mid when build completed
        self.trend_inval_count: int = 0
        self.trend_inval_lockout_until: int = 0
        # re-extension detection
        self.trend_original_dir: int = 0
        self.trend_covered: bool = False
        self.wsc_side: int = 0            # 0 flat, -1 short fade (long disabled)
        self.wsc_last_fire_row: int = -10_000
        self.wsc_entry_row: int = -10_000
        self.wsc_entry_mid: Optional[float] = None
        self.spread_buf: List[int] = []

    def to_dict(self):
        return {
            "buf500":      self.mid_buf_500,
            "buf100":      self.mid_buf_100,
            "row":         self.row,
            "r1_row":      self.regime1_entry_row,
            "r1_qty":      self.regime1_qty,
            "lean":        self.lean_target,
            "lean_mid":    self.lean_entry_mid,
            "lean_side":   self.lean_entry_side,
            "mr_side":     self.mr_side,
            "mr_emid":     self.mr_entry_mid,
            "day_type":    self.day_type,
            "trend_built": self.trend_built,
            "trend_emid":  self.trend_entry_mid,
            "tinval_cnt":  self.trend_inval_count,
            "tinval_lock": self.trend_inval_lockout_until,
            "t_orig_dir":  self.trend_original_dir,
            "t_covered":   self.trend_covered,
            "wsc_side":    self.wsc_side,
            "wsc_lf":      self.wsc_last_fire_row,
            "wsc_er":      self.wsc_entry_row,
            "wsc_em":      self.wsc_entry_mid,
            "spread_buf":  self.spread_buf,
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
        s.mr_side           = d.get("mr_side", 0)
        s.mr_entry_mid      = d.get("mr_emid")
        s.day_type          = d.get("day_type", 0)
        s.trend_built       = d.get("trend_built", False)
        s.trend_entry_mid   = d.get("trend_emid")
        s.trend_inval_count = d.get("tinval_cnt", 0)
        s.trend_inval_lockout_until = d.get("tinval_lock", 0)
        s.trend_original_dir = d.get("t_orig_dir", 0)
        s.trend_covered      = d.get("t_covered", False)
        s.wsc_side           = d.get("wsc_side", 0)
        s.wsc_last_fire_row  = d.get("wsc_lf", -10_000)
        s.wsc_entry_row      = d.get("wsc_er", -10_000)
        s.wsc_entry_mid      = d.get("wsc_em", None)
        s.spread_buf         = d.get("spread_buf", [])
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


# ── Main strategy ─────────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────────────────
    # DAY TYPE DETECTION (locked at row 20 = ts=2000)
    # ─────────────────────────────────────────────────────────────────────
    if hstate.day_type == 0 and hstate.row >= p.DAY_DETECT_ROW and hstate.row > hstate.trend_inval_lockout_until:
        rm20 = _mean(hstate.mid_buf_100[-20:])
        if rm20 is not None:
            drift = rm20 - p.GLOBAL_MEAN
            if drift > p.TREND_OPEN_THRESH:
                hstate.day_type = 1    # trend SHORT day (price too high, will fall)
                hstate.trend_original_dir = -1
                logger.print(f"DAY TYPE: TREND SHORT rm20={rm20:.1f} drift={drift:+.1f}")
            elif drift < -p.TREND_OPEN_THRESH:
                hstate.day_type = -1   # trend LONG day (price too low, will rise)
                hstate.trend_original_dir = 1
                logger.print(f"DAY TYPE: TREND LONG rm20={rm20:.1f} drift={drift:+.1f}")
            else:
                hstate.day_type = 2    # mean-revert day
                logger.print(f"DAY TYPE: MEAN REVERT rm20={rm20:.1f} drift={drift:+.1f}")

    # ─────────────────────────────────────────────────────────────────────
    # ONE-WAY SAFETY OVERRIDE  — mark-to-market based
    # If unrealised PnL per unit has been negative for TREND_INVAL_ROWS
    # consecutive ticks after build → the trend bet is wrong, bail out.
    # ─────────────────────────────────────────────────────────────────────
    if (p.TREND_INVAL_ENABLE
            and hstate.trend_built
            and hstate.day_type in (1, -1)
            and hstate.trend_entry_mid is not None):
        direction  = -1 if hstate.day_type == 1 else 1
        mtm        = (mid - hstate.trend_entry_mid) * direction
        if mtm < -p.TREND_INVAL_LOSS_THRESH:
            hstate.trend_inval_count += 1
        else:
            hstate.trend_inval_count = 0

        if hstate.trend_inval_count >= p.TREND_INVAL_ROWS:
            logger.print(f"TREND INVALIDATED at row={hstate.row} "
                         f"day_type={hstate.day_type} mtm={mtm:.1f} "
                         f"entry={hstate.trend_entry_mid:.1f} → passive MM")
            hstate.day_type = 2
            hstate.trend_inval_count = 0
            hstate.trend_inval_lockout_until = hstate.row + p.TREND_INVAL_COOLDOWN

    # ─────────────────────────────────────────────────────────────────────
    # TREND-FOLLOW MODE
    # ─────────────────────────────────────────────────────────────────────
    if hstate.day_type in (1, -1):
        direction = -1 if hstate.day_type == 1 else 1  # -1=short, +1=long
        dist_from_mean = mid - p.GLOBAL_MEAN

        # Phase 1: build full position in first TREND_BUILD_TICKS rows
        if not hstate.trend_built and hstate.row <= p.DAY_DETECT_ROW + p.TREND_BUILD_TICKS:
            if direction == -1 and position > -pos_lim:
                qty = min(p.TREND_BUILD_QTY, pos_lim + position)
                if qty > 0:
                    orders.append(Order(P, best_bid, -qty))  # hit bid aggressively
                    logger.print(f"TREND BUILD short: qty={qty} px={best_bid} pos={position}")
            elif direction == 1 and position < pos_lim:
                qty = min(p.TREND_BUILD_QTY, pos_lim - position)
                if qty > 0:
                    orders.append(Order(P, best_ask, qty))   # lift ask aggressively
                    logger.print(f"TREND BUILD long: qty={qty} px={best_ask} pos={position}")

            if hstate.row == p.DAY_DETECT_ROW + p.TREND_BUILD_TICKS:
                hstate.trend_built = True
                hstate.trend_entry_mid = mid
            return orders, hstate

        hstate.trend_built = True
        if hstate.trend_entry_mid is None:
            hstate.trend_entry_mid = mid
        if direction == -1 and position < 0:
            # Short position — cover (buy back) when price falls to mean
            if dist_from_mean <= p.TREND_COVER_TARGET:
                qty = min(p.TREND_COVER_QTY, -position)
                if qty > 0:
                    orders.append(Order(P, best_ask, qty))   # lift ask to cover
                    logger.print(f"TREND COVER short: qty={qty} px={best_ask} mid={mid:.1f}")
                if position + qty >= 0:
                    hstate.day_type = 2
                    hstate.trend_covered = True
            return orders, hstate

        elif direction == 1 and position > 0:
            # Long position — cover (sell) when price rises to mean
            if dist_from_mean >= -p.TREND_COVER_TARGET:
                qty = min(p.TREND_COVER_QTY, position)
                if qty > 0:
                    orders.append(Order(P, best_bid, -qty))  # hit bid to cover
                    logger.print(f"TREND COVER long: qty={qty} px={best_bid} mid={mid:.1f}")
                if position - qty <= 0:
                    hstate.day_type = 2
                    hstate.trend_covered = True
            return orders, hstate

        # Fully covered — fall through to passive MM
        hstate.day_type = 2
        hstate.trend_covered = True

    # ─────────────────────────────────────────────────────────────────────
    # WIDE-SPREAD CLUSTER FADE (SHORT-ONLY)
    # Empirical: clusters of spread>=17 cluster near local price PEAKS,
    # and price reverts down after. Long-side fade loses every day.
    # Use TP/stop-based exit (NOT mean-reversion exit — round-trip spread
    # is ~16 ticks, mean-reversion eats it all).
    # Active in any regime, gated by cooldown.
    # ─────────────────────────────────────────────────────────────────────
    hstate.spread_buf = _push(hstate.spread_buf, spread, p.WSC_WINDOW)

    if p.WSC_ENABLE and len(hstate.mid_buf_100) >= p.WSC_LOCAL_WINDOW:
        local_rm = _mean(hstate.mid_buf_100[-p.WSC_LOCAL_WINDOW:])
        if local_rm is not None:
            local_d = mid - local_rm
            held_for = hstate.row - hstate.wsc_entry_row

            # ── Exit on TP / stop / max-hold ─────────────────────────────
            if hstate.wsc_side == -1 and position < 0 and hstate.wsc_entry_mid is not None:
                pnl_per_unit = hstate.wsc_entry_mid - mid   # + = winning short
                reason = None
                if pnl_per_unit >= p.WSC_TP_TICKS:
                    reason = "tp"
                elif pnl_per_unit <= -p.WSC_STOP_TICKS:
                    reason = "stop"
                elif held_for >= p.WSC_MAX_HOLD:
                    reason = "timeout"
                if reason:
                    qc = min(abs(position), p.WSC_MAX_POS)
                    orders.append(Order(P, best_ask, qc))
                    logger.print(
                        f"WSC EXIT short ({reason}) pos={position} mid={mid:.1f} "
                        f"entry={hstate.wsc_entry_mid:.1f} pnl={pnl_per_unit:+.1f} held={held_for}"
                    )
                    hstate.wsc_side = 0
                    hstate.wsc_entry_mid = None
                    return orders, hstate

            # ── Detect cluster: count wide spreads in recent window ─────
            wide_count = sum(1 for s in hstate.spread_buf if s >= p.WSC_SPREAD_THRESH)
            cooldown_ok = (hstate.row - hstate.wsc_last_fire_row) >= p.WSC_COOLDOWN

            # Fire SHORT: cluster + mid above local mean (= local peak)
            if (wide_count >= p.WSC_CLUSTER_COUNT
                    and cooldown_ok
                    and local_d >= p.WSC_LOCAL_DIST
                    and hstate.wsc_side == 0):
                headroom = pos_lim + position
                qty = min(p.WSC_QTY, headroom, p.WSC_MAX_POS - max(0, -position))
                if qty > 0:
                    orders.append(Order(P, best_bid, -qty))
                    hstate.wsc_side = -1
                    hstate.wsc_last_fire_row = hstate.row
                    hstate.wsc_entry_row = hstate.row
                    hstate.wsc_entry_mid = mid
                    logger.print(
                        f"WSC FADE short qty={qty} mid={mid:.1f} rm={local_rm:.1f} "
                        f"d={local_d:+.1f} wide={wide_count}"
                    )
                    return orders, hstate

    # ─────────────────────────────────────────────────────────────────────
    # MEAN-REVERSION MODE (day_type == 2 or not yet detected)
    # ─────────────────────────────────────────────────────────────────────

    # Trend filter for MR entries
    trend_buf    = hstate.mid_buf_100[-p.TREND_WINDOW:]
    roll_mean_50 = _mean(trend_buf)
    trend_drift  = (roll_mean_50 - p.GLOBAL_MEAN) if roll_mean_50 is not None else 0.0
    trending_down = trend_drift < -p.TREND_FILTER
    trending_up   = trend_drift >  p.TREND_FILTER

    dist_from_mean = mid - p.GLOBAL_MEAN

    # MR exit
    if hstate.mr_side != 0 and abs(dist_from_mean) <= p.EXIT_BAND:
        if hstate.mr_side == 1 and position > 0:
            orders.append(Order(P, best_bid, -position))
            logger.print(f"MR EXIT long pos={position} mid={mid:.1f}")
        elif hstate.mr_side == -1 and position < 0:
            orders.append(Order(P, best_ask, -position))
            logger.print(f"MR EXIT short pos={position} mid={mid:.1f}")
        hstate.mr_side      = 0
        hstate.mr_entry_mid = None
        return orders, hstate

    # MR entry
    if mid <= p.BUY_THRESH and not trending_down:
        headroom = pos_lim - position
        qty = min(p.MR_QTY, headroom)
        if qty > 0:
            orders.append(Order(P, best_ask, qty))
            if hstate.mr_side != 1:
                hstate.mr_side = 1; hstate.mr_entry_mid = mid
                logger.print(f"MR ENTER long qty={qty} mid={mid:.1f}")
        return orders, hstate

    elif mid <= p.BUY_THRESH and trending_down:
        logger.print(f"MR BLOCKED long mid={mid:.1f} drift={trend_drift:.1f}")

    elif mid >= p.SELL_THRESH and not trending_up:
        headroom = pos_lim + position
        qty = min(p.MR_QTY, headroom)
        if qty > 0:
            orders.append(Order(P, best_bid, -qty))
            if hstate.mr_side != -1:
                hstate.mr_side = -1; hstate.mr_entry_mid = mid
                logger.print(f"MR ENTER short qty={qty} mid={mid:.1f}")
        return orders, hstate

    elif mid >= p.SELL_THRESH and trending_up:
        logger.print(f"MR BLOCKED short mid={mid:.1f} drift={trend_drift:.1f}")

    # ─────────────────────────────────────────────────────────────────────
    # PASSIVE MM (v4 — runs when not in any directional trade)
    # ─────────────────────────────────────────────────────────────────────

    # Regime 1: tight spread
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

    # Regime 2: spread=17
    skip_bid = False
    if spread == p.REGIME2_SPREAD:
        if position > 0:
            px = best_bid if p.REGIME2_FLATTEN_AGGRESSIVE else best_ask
            orders.append(Order(P, px, -position))
        skip_bid = True

    # Normal passive MM
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

    if bid_qty > 0 and not skip_bid:
        orders.append(Order(P, my_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order(P, my_ask, -ask_qty))

    return orders, hstate


# ── v9 Voucher / VFE strategy (ported) ────────────────────────────────────────

VEVE_SYM = "VELVETFRUIT_EXTRACT"
VOUCHER_STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VOUCHER_STRIKES_TRADEABLE = [5000, 5100, 5200, 5300, 5400]
VOUCHER_STRIKES_DEEP_ITM = [4000, 4500]
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

    od_ve = state.order_depths.get(VEVE_SYM)
    if od_ve and od_ve.buy_orders and od_ve.sell_orders:
        wm = v_wall_mid(od_ve)
        if wm is not None:
            bb = max(od_ve.buy_orders); ba = min(od_ve.sell_orders)
            pos = state.position.get(VEVE_SYM, 0)
            fv = round(wm)
            tb, ts = 200 - pos, 200 + pos
            half = 100
            mbp = fv - 1 if pos > half else fv
            msp = fv + 1 if pos < -half else fv
            ve_orders = []
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

    return orders


# ── Entrypoint ────────────────────────────────────────────────────────────────

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orders      = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}

        # 1) HYDROGEL_PACK: 401389 day-type detection + trend follow
        hstate = HydrogelState.from_dict(raw.get("hg", {}))
        hydrogel_orders, hstate = run_hydrogel(state, hstate)
        orders[Product.HYDROGEL_PACK] = hydrogel_orders
        raw["hg"] = hstate.to_dict()

        # 2) VFE + Vouchers: v9 logic (Wall Mid + BS taking + intrinsic arb + MM)
        vstate = VoucherState.from_dict(raw.get("v9", {}))
        voucher_orders = run_vouchers(state, vstate)
        for sym, ord_list in voucher_orders.items():
            if sym not in orders: orders[sym] = []
            orders[sym].extend(ord_list)
        raw["v9"] = vstate.to_dict()

        new_trader_data = json.dumps(raw)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data