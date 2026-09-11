"""r3_v20_delta_hedge.py — v17 + delta-hedged BS-anchored ATM voucher MM.

Replaces v17's spread-anchored voucher MM with BS-anchored MM for ATM
strikes (5100-5400), then hedges aggregate delta in VFE.

Empirical basis from EDA_FINDINGS.md (bimodal autocorr):
  - Deep ITM 4000/4500: ac(1) ~ 0 — keep v17 Phase 4.1 (intrinsic-anchored)
  - ATM 5100-5400: ac(1) 0.81-0.98 — drift, MM around BS fair, delta-hedge
  - Deep OTM 6000+: frozen, skip
Calibration: ATM IV ~27% (T=days/250), single sigma works for ATM region.

Inherits r3_v17 documentation below.
=====================================================================

r3_v17.py — Consolidated R4-prep strategy (Phases 1-4 stack on r3_v11).

This is the consolidated final from the R4-prep roadmap (worktree
.worktrees/r4-prep, branch r3-prep-roadmap). Combines:

  + r3_v11 (shipped baseline) — spread=17 GIGA SHORT for HP, Wall Mid for VFE,
    BS voucher taking, intrinsic arb, call-spread arb scanner
  + Phase 1.1 multi-level VFE/voucher passive posting (40/30/30 capacity split)
  + Phase 2 day-type detector infrastructure (lib/regime.py inlined; doesn't
    fire on R3 historical but ready for HP-style products in R4)
  + Phase 4.1 deep-ITM theta carry MM on VEV_4000/VEV_4500 — the BIG win
  + Phase 4.2 smile R² regime gate (defensive widening only when R²<0.5)
  + Phase 4.3 empirical-vs-BS delta β divergence gate

PnL trajectory (vs r3_v11 baseline 1k-day-2 $12,262 / 10k-3-day $46,976):

  v11 (shipped)           1k=12,262  10k=46,976
  v12 (multi-level post)  1k=12,262  10k=47,036  Δ=+60       Phase 1.1
  v13 (day-type detect)   1k=12,262  10k=47,036  Δ=+0        Phase 2 (no fire)
  v14 (theta carry)       1k=12,396  10k=55,880  Δ=+8,904    Phase 4.1 ★
  v15 (smile R² gate)     1k=12,340  10k=56,328  Δ=+9,352    Phase 4.2
  v16 (empirical δ gate)  1k=12,340  10k=56,328  Δ=+9,352    Phase 4.3 (no fire)
  v17 (this file)         1k=12,340  10k=56,328  consolidated

Per-day 10k breakdown (v17 vs v11):
  Day 0: 27,939 vs 24,989 (+$2,950)
  Day 1:  9,484 vs  5,996 (+$3,488)
  Day 2: 18,905 vs 15,990 (+$2,915)

Most of the win comes from Phase 4.1 deep-ITM theta carry. Phase 4.2 adds
defensive value on day 2 stress. Phase 4.3 is dormant infrastructure.

Decision points kept (from earlier iterations):
  - direction_bias DROPPED (net-zero per R2 post-mortem Appendix C.1)
  - aggressive smile R² tightening DROPPED (regressed -$1.7k in v15 first iter)
  - imbalance 1.2× boost DROPPED (overfit-prone)
  - Day-type detector kept as no-op infra for R4 (HP-style products may fire)

Calibration notes:
  - VFE_GLOBAL_MEAN = 5260 — empirical at row 20 shows ~5248 drift -12 (below
    threshold). For R4 with stronger drift products, recalibrate.
  - DEEP_ITM_POS_CAP = 100 limits cumulative theta exposure
  - DELTA_DIVERGENCE_THRESH = 0.05 — kept tight; gate rarely fires

Inherits r3_v15 documentation below.
=====================================================================

r3_v15.py — v14 + smile R² regime gate (Phase 4.2, alpha A10).

Adds a quadratic-fit smile R² indicator that scales BS voucher edges:
  - R² > 0.85 (tight smile, healthy regime): edge × 0.7 (more aggressive MM)
  - R² < 0.50 (smile breakdown, regime stress): edge × 1.5 (defensive)
  - Else: edge × 1.0 (default)

Computed each tick across STRIKES_IV = [5000, 5100, 5200, 5300, 5400] using
the IVs already calculated by v11's adaptive sigma logic. Fit:
    IV(K) = a + b*(K - K_atm) + c*(K - K_atm)²
where K_atm = strike closest to current spot.

R² < 0.5 was empirically observed on R3 day 2 (alpha_hunt EDA: smile R²
degrades 0.81 → 0.42 across days). Defensive edge widens BS taking thresholds.

Baseline (v14): 1k-tick day 2 = $12,396, 10k 3-day = $55,880.
Expected v15: defensive scaling reduces adverse-selection on stress days,
estimated +$200-1500 on 10k 3-day.

Inherits r3_v14 documentation below.
=====================================================================

r3_v14.py — v13 + theta carry MM on deep ITM vouchers (Phase 4.1, alpha A5).

Phase 4.1 from R4-prep roadmap (alpha_hunt3 EV: $825-855 per 1k ticks per strike):
  - Add active MM on VEV_4000 and VEV_4500 (currently only intrinsic arb, no MM)
  - Post bids at min(best_bid+1, intrinsic-1) for size DEEP_ITM_MM_SIZE
  - Post asks at max(best_ask-1, intrinsic+1) for size DEEP_ITM_MM_SIZE
  - Accumulating short positions harvest time premium decay (theta)
  - Position cap to manage delta exposure (DEEP_ITM_POS_CAP = 100)

Why this isn't hedged: deep ITM voucher delta ≈ 1.0, but the position cap and
the short MM bias mean net delta exposure stays bounded. A separate cross-product
delta hedge is Phase 4.3 work; this is the pure theta harvester.

Baseline (v11/v13): VEV_4000 = $0, VEV_4500 = $0 on day 2 1k-tick (no fills).
Expected v14: $200-1000 from spread capture + theta on deep ITM.

Inherits r3_v13 documentation below.
=====================================================================

r3_v13.py — v12 + VFE day-type detection (Phase 2 — alpha A1, EV +$20-40k/round).

Adds 401389-style day-type detector to VFE:
  - At row 20 (ts=2000): compute drift = rm20 - VFE_GLOBAL_MEAN
  - If drift > +20 ticks: TREND_LONG day -> accumulate VFE long up to limit
  - If drift < -20 ticks: TREND_SHORT day -> accumulate VFE short up to limit
  - Else: MEAN_REVERT day -> existing v11/v12 Wall Mid MM
  - Trend invalidation: if MTM negative for 40 consecutive rows, bail to MR

Empirical R3 calibration (alpha_hunt3.py):
  Day 0: VFE drift -6   -> MEAN_REVERT (no extra exposure, MM only)
  Day 1: VFE drift +20.5 -> borderline TREND_LONG
  Day 2: VFE drift +28  -> TREND_LONG (buy-and-hold of all delta-1 = $41,600)

VFE_GLOBAL_MEAN: chosen as 5260 (mid of 3-day mean range, see alpha_hunt3 EDA).

VFE_TREND_BUILD_QTY=50/tick over 4 rows = 200-unit position by row 24.
VFE_TREND_COVER_TARGET=10: cover when within 10 ticks of mean (lock gains).
VFE_TREND_INVAL_LOSS_THRESH=5, ROWS=40, COOLDOWN=200 (ported from 401389).

Baseline (v11): 1k-tick day 2 = $12,262 ($1,940 VFE + $10,224 HP + $98 vouchers).
Expected v13 day 2: $12,262 -> $20-50k if TREND_LONG fires correctly.
Expected v13 day 0: should NOT fire (drift -6 < threshold) -> $12,262 baseline.

PRESERVES from v12:
  - HP spread=17 GIGA SHORT (untouched)
  - Voucher MM 3-layer posting
  - VFE Wall Mid 3-layer posting (still runs on MR days)

Inherits all v11/v12 documentation below.
=====================================================================

r3_v11.py — 402045's spread=17 GIGA SHORT HP + v9's voucher/VFE strategy.

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
    COVER_TARGET   = 9998    # cover when price returns near mean (9990 + 8t buffer)
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

    # Trend filter for MR entries
    trend_buf    = hstate.mid_buf_100[-p.TREND_WINDOW:]
    roll_mean_50 = _mean(trend_buf)
    trend_drift  = (roll_mean_50 - p.GLOBAL_MEAN) if roll_mean_50 is not None else 0.0
    trending_down = trend_drift < -p.TREND_FILTER

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

# ── Empirical delta β tracking (Phase 4.3 alpha A9) ─────────────────────────
EMPIRICAL_DELTA_WINDOW    = 20    # rolling window of price changes
EMPIRICAL_DELTA_MIN_HIST  = 10    # min samples before β is reliable
DELTA_DIVERGENCE_THRESH   = 0.05  # |β - bs_delta| > this => skip BS take


def empirical_delta_beta(spot_changes, voucher_changes):
    """Compute β = cov(spot_changes, voucher_changes) / var(spot_changes).

    Args:
        spot_changes: list of recent VFE Δmid values (most recent last)
        voucher_changes: list of recent voucher Δmid values (paired)

    Returns:
        β as float, or None if insufficient data or zero spot variance.
    """
    n = len(spot_changes)
    if n < EMPIRICAL_DELTA_MIN_HIST or n != len(voucher_changes):
        return None
    sum_sv = sum(s * v for s, v in zip(spot_changes, voucher_changes))
    sum_ss = sum(s * s for s in spot_changes)
    if sum_ss < 1e-9:
        return None
    return sum_sv / sum_ss


def bs_delta(spot, K, T, vol):
    """Black-Scholes delta for a call option."""
    if T <= 0 or vol <= 0:
        return 1.0 if spot > K else 0.0
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    return _ND_VOUCHER.cdf(d1)


# ── Smile R² regime gate (Phase 4.2 alpha A10) ──────────────────────────────
SMILE_R2_HIGH    = 0.85   # R² above this -> tight smile, aggressive MM (edge × 0.7)
SMILE_R2_LOW     = 0.50   # R² below this -> smile breakdown, defensive (edge × 1.5)
SMILE_EDGE_TIGHT = 0.7    # multiplier applied to V_BS_EDGE when R² > HIGH
SMILE_EDGE_WIDE  = 1.5    # multiplier when R² < LOW
SMILE_FIT_STRIKES = [5000, 5100, 5200, 5300, 5400]   # 5 strikes for OLS fit


def smile_r2_quadratic(ivs_by_strike, k_atm):
    """Fit IV(K) = a + b(K-K_atm) + c(K-K_atm)² across the strikes that have IVs.

    Args:
        ivs_by_strike: dict of {strike: latest_IV}
        k_atm: at-the-money strike (closest to spot)

    Returns:
        R² of the OLS fit (in [0, 1]) or None if insufficient data (<3 strikes).
    """
    pairs = [(K - k_atm, iv) for K, iv in ivs_by_strike.items() if iv is not None]
    if len(pairs) < 3:
        return None

    n = len(pairs)
    sum_x = sum_y = sum_x2 = sum_x3 = sum_x4 = sum_xy = sum_x2y = 0.0
    for x, y in pairs:
        x2 = x * x
        sum_x += x; sum_y += y
        sum_x2 += x2; sum_x3 += x2 * x; sum_x4 += x2 * x2
        sum_xy += x * y; sum_x2y += x2 * y

    # Solve 3x3 normal equations: [n, sx, sx2; sx, sx2, sx3; sx2, sx3, sx4] [a; b; c] = [sy; sxy; sx2y]
    M = [[n, sum_x, sum_x2], [sum_x, sum_x2, sum_x3], [sum_x2, sum_x3, sum_x4]]
    rhs = [sum_y, sum_xy, sum_x2y]
    det = (
        M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1])
        - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0])
        + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0])
    )
    if abs(det) < 1e-9:
        return None

    def cof(i, j):
        m2 = [[M[r][c] for c in range(3) if c != j] for r in range(3) if r != i]
        return ((-1) ** (i + j)) * (m2[0][0] * m2[1][1] - m2[0][1] * m2[1][0])

    inv_det = 1.0 / det
    a = (cof(0, 0) * rhs[0] + cof(1, 0) * rhs[1] + cof(2, 0) * rhs[2]) * inv_det
    b = (cof(0, 1) * rhs[0] + cof(1, 1) * rhs[1] + cof(2, 1) * rhs[2]) * inv_det
    c = (cof(0, 2) * rhs[0] + cof(1, 2) * rhs[1] + cof(2, 2) * rhs[2]) * inv_det

    y_mean = sum_y / n
    ss_res = ss_tot = 0.0
    for x, y in pairs:
        yhat = a + b * x + c * x * x
        ss_res += (y - yhat) ** 2
        ss_tot += (y - y_mean) ** 2
    if ss_tot < 1e-12:
        return None
    r2 = 1.0 - ss_res / ss_tot
    return max(0.0, min(1.0, r2))   # clamp to [0, 1]


def smile_edge_multiplier(r2):
    """Map smile R² to BS edge multiplier.

    DEFENSIVE-ONLY: tightening edges on healthy regimes regressed -$1.7k 10k 3-day
    in v15 testing. Keep edge default and only WIDEN on stress days (R² < 0.5).
    """
    if r2 is None:
        return 1.0
    if r2 < SMILE_R2_LOW:
        return SMILE_EDGE_WIDE
    return 1.0


# ── ATM BS-anchored MM + delta hedge (v20) ──────────────────────────────────
# For ATM strikes only. Post around BS fair value with small edge; delta-hedge
# aggregate exposure in VFE. EDA: ac(1) on these strikes is 0.81-0.98 (persistent
# drift), so spread capture without directional pickup requires delta hedge.
ATM_BS_STRIKES   = [5100, 5200, 5300, 5400]   # subset of V_BS_STRIKES
ATM_BS_EDGE      = 1.5     # quote at BS_fair ± edge (Nancy's recommendation)
ATM_MM_SIZE      = 30      # per-leg post size
ATM_POS_CAP      = 100     # max abs position per ATM strike
HEDGE_THRESHOLD  = 30      # |net_delta| > this triggers VFE hedge order
HEDGE_RESERVE    = 50      # max VFE units used for hedging (don't starve VFE MM)
HEDGE_ENABLE     = True    # toggle. Verified dormant on R3 historical (net δ stays
                           # below 30 because BS-anchored MM is symmetric). Kept on
                           # for safety on R4+ data with potentially asymmetric flow.


def bs_delta(spot, K, T, sigma):
    """Black-Scholes call delta = N(d1)."""
    if T <= 0 or sigma <= 0:
        return 1.0 if spot > K else 0.0
    d1 = (math.log(spot / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return _ND_VOUCHER.cdf(d1)


# ── Deep ITM theta carry MM (Phase 4.1 alpha A5) ─────────────────────────────
# alpha_hunt3 finding: $825-855 per 1k ticks per strike from theta decay.
# v11 only does intrinsic arb on 4000/4500 (rare fires). Add active MM that
# posts bids and asks around intrinsic value to capture spread + theta.
DEEP_ITM_MM_SIZE     = 30   # per-leg post size
DEEP_ITM_POS_CAP     = 100  # max abs position per deep-ITM strike (vs 300 limit)
DEEP_ITM_BID_OFFSET  = 1    # post bid at intrinsic - this (we want to BUY low)
DEEP_ITM_ASK_OFFSET  = 1    # post ask at intrinsic + this (we want to SELL high)
DEEP_ITM_INSIDE_BOOK = True # if True, take min(best_ask-1, intrinsic+OFFSET) for ask

# ── VFE day-type detection (Phase 2 alpha A1) ────────────────────────────────
# Inlined from trader-logic/lib/regime.py for single-file submission compliance.
# Calibrated from competitor 401389 (HP DAY_DETECT_ROW=20, TREND_OPEN_THRESH=20)
# and alpha_hunt3.py R3 empirics.

VFE_GLOBAL_MEAN          = 5260   # 3-day mean anchor (alpha_hunt3 day means: ~5230/5260/5281)
VFE_DAY_DETECT_ROW       = 20     # detect at row 20 (ts=2000)
VFE_TREND_DRIFT_THRESH   = 20     # |rm20 - mean| > this => trending
VFE_TREND_BUILD_QTY      = 50     # units per build tick
VFE_TREND_BUILD_TICKS    = 4      # build full position over 4 ticks
VFE_TREND_COVER_TARGET   = 10     # cover when within this many ticks of mean
VFE_TREND_COVER_QTY      = 75     # cover qty per chunk
VFE_POS_LIMIT            = 200
VFE_TREND_INVAL_LOSS     = 5.0    # ticks adverse from entry triggers count
VFE_TREND_INVAL_ROWS     = 40     # consecutive bad rows -> bail out
VFE_TREND_INVAL_COOLDOWN = 200    # rows lockout after invalidation

# Day-type sentinel values
DT_UNKNOWN     = 0
DT_TREND_SHORT = 1   # price too high, expected to fall (short bias)
DT_TREND_LONG  = -1  # price too low, expected to rise (long bias)
DT_MEAN_REVERT = 2


def vfe_detect_day_type(mid_history, global_mean, drift_thresh):
    """Classify VFE day from rm20 drift (inline regime.py:detect_day_type).

    Returns DT_TREND_SHORT (1), DT_TREND_LONG (-1), or DT_MEAN_REVERT (2).
    """
    n = len(mid_history)
    if n < 20:
        return DT_UNKNOWN
    rm20 = sum(mid_history[-20:]) / 20.0
    drift = rm20 - global_mean
    if drift > drift_thresh:
        return DT_TREND_SHORT
    if drift < -drift_thresh:
        return DT_TREND_LONG
    return DT_MEAN_REVERT


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
        # VFE day-type tracking (Phase 2)
        self.vfe_mid_history = []
        self.vfe_row = 0
        self.vfe_day_type = DT_UNKNOWN
        self.vfe_trend_built = False
        self.vfe_trend_entry_mid = None
        self.vfe_trend_inval_count = 0
        self.vfe_trend_lockout_until = 0
        # Phase 4.3: empirical delta tracking (per-strike)
        self.last_voucher_mid = {k: None for k in V_BS_STRIKES}
        self.spot_changes = []          # rolling deque of last spot_chg
        self.voucher_changes = {k: [] for k in V_BS_STRIKES}

    def to_dict(self):
        return {
            "ivh": {str(k): v[-V_IV_ADAPT_WINDOW:] for k, v in self.iv_history.items()},
            "ls": self.last_spot,
            "sa": self.spot_age,
            "vmh": self.vfe_mid_history[-50:],   # cap history for traderData size
            "vrow": self.vfe_row,
            "vdt": self.vfe_day_type,
            "vtb": self.vfe_trend_built,
            "vtem": self.vfe_trend_entry_mid,
            "vtic": self.vfe_trend_inval_count,
            "vtlu": self.vfe_trend_lockout_until,
            # Phase 4.3 empirical delta state
            "lvm": {str(k): v for k, v in self.last_voucher_mid.items() if v is not None},
            "sc": self.spot_changes[-EMPIRICAL_DELTA_WINDOW:],
            "vc": {str(k): v[-EMPIRICAL_DELTA_WINDOW:] for k, v in self.voucher_changes.items()},
        }

    @staticmethod
    def from_dict(d):
        s = VoucherState()
        s.iv_history = {int(k): list(v) for k, v in d.get("ivh", {}).items()}
        for k in V_BS_STRIKES:
            if k not in s.iv_history: s.iv_history[k] = []
        s.last_spot = d.get("ls")
        s.spot_age = d.get("sa", 0)
        s.vfe_mid_history = list(d.get("vmh", []))
        s.vfe_row = int(d.get("vrow", 0))
        s.vfe_day_type = int(d.get("vdt", DT_UNKNOWN))
        s.vfe_trend_built = bool(d.get("vtb", False))
        s.vfe_trend_entry_mid = d.get("vtem")
        s.vfe_trend_inval_count = int(d.get("vtic", 0))
        s.vfe_trend_lockout_until = int(d.get("vtlu", 0))
        # Phase 4.3 empirical delta state
        s.last_voucher_mid = {int(k): v for k, v in d.get("lvm", {}).items()}
        for k in V_BS_STRIKES:
            if k not in s.last_voucher_mid: s.last_voucher_mid[k] = None
        s.spot_changes = list(d.get("sc", []))
        s.voucher_changes = {int(k): list(v) for k, v in d.get("vc", {}).items()}
        for k in V_BS_STRIKES:
            if k not in s.voucher_changes: s.voucher_changes[k] = []
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
        plain_mid_ve = v_plain_mid(od_ve)
        if wm is not None:
            bb = max(od_ve.buy_orders); ba = min(od_ve.sell_orders)
            pos = state.position.get(VEVE_SYM, 0)
            fv = round(wm)

            # ── VFE day-type detection (Phase 2) ──────────────────────────
            if plain_mid_ve is not None:
                vstate.vfe_mid_history.append(plain_mid_ve)
                if len(vstate.vfe_mid_history) > 50:
                    del vstate.vfe_mid_history[: len(vstate.vfe_mid_history) - 50]
                vstate.vfe_row += 1

            # Detect day type at row 20 (locked once set)
            if (vstate.vfe_day_type == DT_UNKNOWN
                    and vstate.vfe_row >= VFE_DAY_DETECT_ROW
                    and vstate.vfe_row > vstate.vfe_trend_lockout_until):
                vstate.vfe_day_type = vfe_detect_day_type(
                    vstate.vfe_mid_history, VFE_GLOBAL_MEAN, VFE_TREND_DRIFT_THRESH
                )

            # Trend invalidation safety (from 401389:432-449)
            if (vstate.vfe_trend_built
                    and vstate.vfe_day_type in (DT_TREND_SHORT, DT_TREND_LONG)
                    and vstate.vfe_trend_entry_mid is not None
                    and plain_mid_ve is not None):
                direction = -1 if vstate.vfe_day_type == DT_TREND_SHORT else 1
                mtm = (plain_mid_ve - vstate.vfe_trend_entry_mid) * direction
                if mtm < -VFE_TREND_INVAL_LOSS:
                    vstate.vfe_trend_inval_count += 1
                else:
                    vstate.vfe_trend_inval_count = 0
                if vstate.vfe_trend_inval_count >= VFE_TREND_INVAL_ROWS:
                    vstate.vfe_day_type = DT_MEAN_REVERT
                    vstate.vfe_trend_inval_count = 0
                    vstate.vfe_trend_lockout_until = vstate.vfe_row + VFE_TREND_INVAL_COOLDOWN

            # ── TREND mode: build then cover (Phase 2 alpha A1) ───────────
            # When VFE day_type is TREND_LONG/SHORT, skip Wall Mid MM entirely
            # and run the build/cover/hold logic. Falls through to MM only on
            # MR days or after a forced invalidation.
            vfe_handled_by_trend = False
            if vstate.vfe_day_type in (DT_TREND_SHORT, DT_TREND_LONG):
                vfe_handled_by_trend = True
                direction = -1 if vstate.vfe_day_type == DT_TREND_SHORT else 1
                pos_lim = VFE_POS_LIMIT
                ve_orders_trend = []

                # Build phase: row 20-24, accumulate 50/tick
                if (not vstate.vfe_trend_built
                        and vstate.vfe_row <= VFE_DAY_DETECT_ROW + VFE_TREND_BUILD_TICKS):
                    if direction == -1 and pos > -pos_lim:
                        qty = min(VFE_TREND_BUILD_QTY, pos_lim + pos)
                        if qty > 0:
                            ve_orders_trend.append(Order(VEVE_SYM, bb, -qty))
                    elif direction == 1 and pos < pos_lim:
                        qty = min(VFE_TREND_BUILD_QTY, pos_lim - pos)
                        if qty > 0:
                            ve_orders_trend.append(Order(VEVE_SYM, ba, qty))
                    if vstate.vfe_row == VFE_DAY_DETECT_ROW + VFE_TREND_BUILD_TICKS:
                        vstate.vfe_trend_built = True
                        vstate.vfe_trend_entry_mid = plain_mid_ve

                # Cover phase: dist from mean in our favour
                elif vstate.vfe_trend_built:
                    dist_from_mean = (plain_mid_ve or fv) - VFE_GLOBAL_MEAN
                    if direction == -1 and pos < 0 and dist_from_mean <= VFE_TREND_COVER_TARGET:
                        qty = min(VFE_TREND_COVER_QTY, -pos)
                        if qty > 0:
                            ve_orders_trend.append(Order(VEVE_SYM, ba, qty))
                            if pos + qty >= 0:
                                vstate.vfe_day_type = DT_MEAN_REVERT
                                vfe_handled_by_trend = False  # next tick: MR -> MM
                    elif direction == 1 and pos > 0 and dist_from_mean >= -VFE_TREND_COVER_TARGET:
                        qty = min(VFE_TREND_COVER_QTY, pos)
                        if qty > 0:
                            ve_orders_trend.append(Order(VEVE_SYM, bb, -qty))
                            if pos - qty <= 0:
                                vstate.vfe_day_type = DT_MEAN_REVERT
                                vfe_handled_by_trend = False
                    # If no cover trigger, hold (no orders this tick)

                if vfe_handled_by_trend:
                    orders[VEVE_SYM] = ve_orders_trend

            # Wall Mid MM only runs on MR days (or before day-type detected)
            if not vfe_handled_by_trend:
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
                # Phase 1.1: 3-layer VFE posting (40/30/30 split)
                if tb > 0:
                    bp = min(fv - V_POST_SLACK_VE, bb + 1)
                    q1 = int(tb * 0.4); q2 = int(tb * 0.3); q3 = tb - q1 - q2
                    if q1 > 0: ve_orders.append(Order(VEVE_SYM, bp, q1))
                    if q2 > 0 and bp - 1 < bp: ve_orders.append(Order(VEVE_SYM, bp - 1, q2))
                    if q3 > 0 and bp - 2 < bp: ve_orders.append(Order(VEVE_SYM, bp - 2, q3))
                if ts > 0:
                    ap = max(fv + V_POST_SLACK_VE, ba - 1)
                    q1 = int(ts * 0.4); q2 = int(ts * 0.3); q3 = ts - q1 - q2
                    if q1 > 0: ve_orders.append(Order(VEVE_SYM, ap, -q1))
                    if q2 > 0 and ap + 1 > ap: ve_orders.append(Order(VEVE_SYM, ap + 1, -q2))
                    if q3 > 0 and ap + 2 > ap: ve_orders.append(Order(VEVE_SYM, ap + 2, -q3))
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

    # Phase 4.2: Smile R² regime gate. Compute R² across STRIKES_IV using
    # the latest IV from each strike's history. Use it to scale BS edge.
    latest_ivs = {}
    for K in SMILE_FIT_STRIKES:
        hist = vstate.iv_history.get(K, [])
        if hist:
            latest_ivs[K] = hist[-1]
    k_atm_smile = min(SMILE_FIT_STRIKES, key=lambda k: abs(k - spot))
    smile_r2 = smile_r2_quadratic(latest_ivs, k_atm_smile)
    bs_edge_eff = V_BS_EDGE * smile_edge_multiplier(smile_r2)

    # Phase 4.3: Track per-strike empirical delta β. Update history first,
    # then compute β for each strike to gate BS taking.
    spot_chg = (spot - vstate.last_spot) if vstate.last_spot is not None else 0.0
    if abs(spot_chg) > 1e-9:
        vstate.spot_changes.append(spot_chg)
        if len(vstate.spot_changes) > EMPIRICAL_DELTA_WINDOW:
            del vstate.spot_changes[: len(vstate.spot_changes) - EMPIRICAL_DELTA_WINDOW]

    empirical_betas = {}
    for K in V_BS_STRIKES:
        sym = VOUCHER_SYM[K]
        od_v_chk = state.order_depths.get(sym)
        if od_v_chk is None or not od_v_chk.buy_orders or not od_v_chk.sell_orders:
            continue
        cur_v_mid = 0.5 * (max(od_v_chk.buy_orders) + min(od_v_chk.sell_orders))
        last_v_mid = vstate.last_voucher_mid.get(K)
        if last_v_mid is not None and abs(spot_chg) > 1e-9:
            v_chg = cur_v_mid - last_v_mid
            vstate.voucher_changes[K].append(v_chg)
            if len(vstate.voucher_changes[K]) > EMPIRICAL_DELTA_WINDOW:
                del vstate.voucher_changes[K][: len(vstate.voucher_changes[K]) - EMPIRICAL_DELTA_WINDOW]
        vstate.last_voucher_mid[K] = cur_v_mid

        beta = empirical_delta_beta(vstate.spot_changes, vstate.voucher_changes[K])
        empirical_betas[K] = beta

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
        # Phase 4.2: bs_edge_eff is V_BS_EDGE × smile R² multiplier
        buy_thr = fv_bs - bs_edge_eff
        sell_thr_bs = fv_bs + bs_edge_eff
        # Phase 4.3: gate BS taking when empirical delta diverges from BS delta
        beta_emp = empirical_betas.get(K)
        if beta_emp is not None:
            bs_d = bs_delta(spot, K, T, sigma)
            if abs(beta_emp - bs_d) > DELTA_DIVERGENCE_THRESH:
                # BS price is unreliable for this strike — skip BS taking this tick
                continue
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
        # Phase 1.1: 3-layer voucher MM (40/30/30 split). MM_SIZE caps total per side.
        if tb_v > 0:
            tb_total = min(tb_v, V_VOUCHER_MM_SIZE)
            q1 = int(tb_total * 0.4); q2 = int(tb_total * 0.3); q3 = tb_total - q1 - q2
            bp = vbb + 1
            if q1 > 0: orders.setdefault(sym, []).append(Order(sym, bp, q1))
            if q2 > 0 and bp - 1 >= 1: orders.setdefault(sym, []).append(Order(sym, bp - 1, q2))
            if q3 > 0 and bp - 2 >= 1: orders.setdefault(sym, []).append(Order(sym, bp - 2, q3))
        if ts_v > 0:
            ts_total = min(ts_v, V_VOUCHER_MM_SIZE)
            q1 = int(ts_total * 0.4); q2 = int(ts_total * 0.3); q3 = ts_total - q1 - q2
            ap = vba - 1
            if q1 > 0: orders.setdefault(sym, []).append(Order(sym, ap, -q1))
            if q2 > 0: orders.setdefault(sym, []).append(Order(sym, ap + 1, -q2))
            if q3 > 0: orders.setdefault(sym, []).append(Order(sym, ap + 2, -q3))

    # ── Phase 4.1: Deep ITM theta carry MM ───────────────────────────────────
    # Active MM on VEV_4000 / VEV_4500 around intrinsic value. Captures
    # spread + theta decay. Position-capped to manage delta exposure.
    for K in VOUCHER_STRIKES_DEEP_ITM:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        intrinsic = max(spot - K, 0.0)
        if intrinsic <= 0: continue   # not actually ITM, skip
        vbb = max(od_v.buy_orders); vba = min(od_v.sell_orders)
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)

        # Bid side: post BELOW intrinsic to buy cheap. Cap at DEEP_ITM_POS_CAP long.
        room_buy = DEEP_ITM_POS_CAP - pos_v - existing_buy
        if room_buy > 0:
            target_bid = int(round(intrinsic - DEEP_ITM_BID_OFFSET))
            # Stay inside book: at most best_bid + 1 (don't cross the spread)
            bid_px = min(target_bid, vbb + 1) if DEEP_ITM_INSIDE_BOOK else target_bid
            bid_px = max(1, bid_px)  # never zero or negative
            if bid_px <= vba - 1:    # don't cross the ask
                qty = min(DEEP_ITM_MM_SIZE, room_buy)
                orders.setdefault(sym, []).append(Order(sym, bid_px, qty))

        # Ask side: post ABOVE intrinsic to sell expensive. Cap at -DEEP_ITM_POS_CAP short.
        room_sell = DEEP_ITM_POS_CAP + pos_v - existing_sell
        if room_sell > 0:
            target_ask = int(round(intrinsic + DEEP_ITM_ASK_OFFSET))
            ask_px = max(target_ask, vba - 1) if DEEP_ITM_INSIDE_BOOK else target_ask
            if ask_px >= vbb + 1:    # don't cross the bid
                qty = min(DEEP_ITM_MM_SIZE, room_sell)
                orders.setdefault(sym, []).append(Order(sym, ask_px, -qty))

    # ── v20 Phase 4.3: BS-anchored ATM voucher MM + portfolio delta hedge ───
    # ATM strikes have ac(1) 0.81-0.98 (drift). MM at BS_fair±EDGE captures
    # the bid-ask spread; delta hedge in VFE offloads the directional risk.
    net_voucher_delta = 0.0
    for K in V_BS_STRIKES:
        sym = VOUCHER_SYM[K]
        pos_v = state.position.get(sym, 0)
        if pos_v == 0:
            continue
        delta_K = bs_delta(spot, K, T, sigma)
        net_voucher_delta += pos_v * delta_K

    for K in ATM_BS_STRIKES:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        vbb = max(od_v.buy_orders); vba = min(od_v.sell_orders)
        pos_v = state.position.get(sym, 0)
        if abs(pos_v) >= ATM_POS_CAP:
            continue   # at cap, don't post more on the side that would extend
        fv_bs = v_bs_call(spot, K, T, sigma)
        bid_px = int(round(fv_bs - ATM_BS_EDGE))
        ask_px = int(round(fv_bs + ATM_BS_EDGE))
        # Keep inside book; clamp to existing best ± 1
        bid_px = max(1, min(bid_px, vba - 1))
        ask_px = max(bid_px + 1, ask_px, vbb + 1)
        if ask_px <= bid_px:
            ask_px = bid_px + 1

        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        room_buy = ATM_POS_CAP - pos_v - existing_buy
        room_sell = ATM_POS_CAP + pos_v - existing_sell
        if room_buy > 0:
            qty = min(ATM_MM_SIZE, room_buy)
            orders.setdefault(sym, []).append(Order(sym, bid_px, qty))
        if room_sell > 0:
            qty = min(ATM_MM_SIZE, room_sell)
            orders.setdefault(sym, []).append(Order(sym, ask_px, -qty))

    # Delta hedge: if aggregate voucher delta exceeds threshold, offset in VFE
    if HEDGE_ENABLE and abs(net_voucher_delta) > HEDGE_THRESHOLD:
        od_ve = state.order_depths.get(VEVE_SYM)
        if od_ve and od_ve.buy_orders and od_ve.sell_orders:
            ve_pos = state.position.get(VEVE_SYM, 0)
            existing_ve = orders.get(VEVE_SYM, [])
            existing_ve_buy = sum(o.quantity for o in existing_ve if o.quantity > 0)
            existing_ve_sell = sum(-o.quantity for o in existing_ve if o.quantity < 0)
            hedge_qty = int(round(abs(net_voucher_delta)))
            hedge_qty = min(hedge_qty, HEDGE_RESERVE)
            if net_voucher_delta > 0:
                # Long delta (long calls) -> sell VFE
                room = 200 + ve_pos - existing_ve_sell
                qty = min(hedge_qty, max(0, room))
                if qty > 0:
                    orders.setdefault(VEVE_SYM, []).append(
                        Order(VEVE_SYM, max(od_ve.buy_orders), -qty))
            else:
                # Short delta (short calls) -> buy VFE
                room = 200 - ve_pos - existing_ve_buy
                qty = min(hedge_qty, max(0, room))
                if qty > 0:
                    orders.setdefault(VEVE_SYM, []).append(
                        Order(VEVE_SYM, min(od_ve.sell_orders), qty))

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
