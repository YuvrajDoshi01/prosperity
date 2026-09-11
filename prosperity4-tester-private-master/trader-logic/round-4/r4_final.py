"""r4_final.py — IMC Prosperity 4 Round 4 canonical submission.

BT (10k 3-day): default $263,328 / imc $249,480 / 1k d3 probe $60,390.
Live projection (BT × 0.96): probe ~$58k / 10k 3-day ~$253k.
Disabling YOLO collapses 10k def to $153,694 / 1k d3 to -$4,304.

ALPHA STACK (every layer theory or t-stat defensible per Frankfurt audit):

HP (HYDROGEL_PACK, limit 200):
  - S17 GIGA SHORT: spread==17 + mid>10010 + z>=2.0 -> short -200, S7-bottom cover, FLIP +200, hold to 10020
  - Circuit breaker: freeze S17 after 2 FLIP_HOLD timeouts (tail-risk insurance)
  - VFE-crash gate: skip S17 entry if VFE drifts < -$5 vs early window
  - z-score MR (window=500, |z|>=2.25)
  - Passive MM (QUOTE_SIZE=200, slack=1)

VFE (VELVETFRUIT_EXTRACT, limit 200):
  - Wall-Mid MM (highest-volume bid/ask midpoint = institutional anchor)
  - Layer-E spread-state aggressive lift (spread==2 ask-drop / spread==3 bid-rise)
  - Mark 49 fade (M49 SELL -> BUY 60 at ask, hold 5 ticks; t=+20 H=1, n=105)

VOUCHERS (10 strikes 4000-6500, limit 300 each):
  - BS taking with parabolic smile-fit sigma (centered m, extrinsic-weighted, K=4000 excluded from fit)
  - Deep-ITM theta carry MM (VEV_4000/4500 around intrinsic, cap 100)
  - Voucher passive MM (best+/-1, min_spread=2)
  - Deep-OTM bid=0 size=100 (VEV_6000/6500: Mark 22 dumps to Mark 01 at price=0)
  - OTM passive bid size=5 cap=50 on K=5300/5400/5500 (smile-fit re-validated +$341 def / +$295 imc)
  - Conditional Voucher OBI (|OBI|>0.7, multi-strike confirm, OBI_POS_CAP=30)

YOLO regime gate (v3 — NN-augmented + ML logistic-regression third opinion):
  - Primary: at ts=3000, if VFE drift <= +2.0 vs t=0, fire MAX SHORT.
  - Defensive corr veto (v2): if primary fires AND drift in [-2, +2] borderline zone
    AND HP-VFE rolling correlation >= +0.30 (d1/d2-style positive coupling), skip YOLO.
  - ML THIRD OPINION (v3): if primary fires AND corr-veto did NOT veto, consult an
    embedded 11-feature L2 logistic regression (trained on R4 d1+d2 sliding-100k
    windows, 18 train / 9 test = R4 d3 holdout). p_down >= 0.50 => fire; else veto.
    Activates ONLY in the "uncertain zone" (drift borderline AND corr non-positive).
  - BT-byte-equivalent on all 5 training windows (d3 short-window p_down=0.79).
  - On day-3-style regimes: ~$60k 1k probe / ~$160k day-3 contribution.
  - On day-1/2 regimes: gate stays closed -> v7c MM-only ($4-15k 1k probes).

Position-limit clamp: final-pass safety net (no-op on validated paths).

REJECTED via Frankfurt audit (intel/parsimony_audit.md, theory_audit.md):
  VFE momentum one-shot, Mark 55 follow, HP edge-beta MM, intrinsic arb,
  call-spread arb (dead), VEV_5200 edge=5 carve-out.
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
    # ========================= S17 GIGA SHORT (v22) ====================
    REGIME2_SPREAD = 17
    ENTRY_MID_MIN = 10010
    S7_WINDOW = 500
    S7_BOTTOM_Q = 0.08
    FLIP_TARGET = 200
    FLIP_EXIT_MID = 10020
    FLIP_TIMEOUT_TICKS = 1500
    S17_MAX_FAILS = 2  # v4: circuit breaker — freeze S17 after N FLIP_HOLD timeouts

    # ==================== INTRINSIC / structure ========================
    POS_LIMIT = 200
    QUOTE_SIZE = 200   # v5b: was 25, sweep +$24,568 def / +$24,656 imc 10k 3-day

    # ===================== Z-SCORE MEAN REVERSION (v4 NEW; v8 TUNED) ====
    Z_WINDOW = 500         # rolling window for z-score
    Z_ENTRY = 2.25         # v8c
    Z_EXIT = 0.5           # |z| < this => flatten
    Z_BASE_SIZE = 40       # base qty per z-signal
    Z_MAX_POS = 120        # max position from z-signals (leave room for S17)

    # ===================== DYNAMIC calibration (v22) ===================
    Z500_WINDOW = 500
    STD100_WINDOW = 100


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

def compute_book_features(order_depth):
    buys  = order_depth.buy_orders
    sells = order_depth.sell_orders
    if not buys or not sells: return {}
    best_bid = max(buys.keys())
    best_ask = min(sells.keys())
    spread   = best_ask - best_bid
    if spread <= 0: return {}
    mid = (best_bid + best_ask) / 2.0
    return {
        "best_bid": best_bid, "best_ask": best_ask,
        "spread": spread, "mid": mid,
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
        self.vfe_buf: List[float] = []  # v10: VFE mid for crash gate
        self.s17_failed_count: int = 0  # v4: circuit breaker — # FLIP_HOLD timeout exits

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
            "vfeb":      self.vfe_buf,
            "s17_fc":    self.s17_failed_count,
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
        s.vfe_buf           = d.get("vfeb", [])
        s.s17_failed_count  = d.get("s17_fc", 0)
        return s


def run_hydrogel(state, hstate):
    # S17 entry/build → S7-bottom percentile cover → flip long to FLIP_TARGET → hold to FLIP_EXIT_MID.
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

    # Update buffers
    hstate.mid_buf_500 = _push(hstate.mid_buf_500, mid, p.Z500_WINDOW)
    hstate.mid_buf_100 = _push(hstate.mid_buf_100, mid, p.STD100_WINDOW)
    hstate.row += 1

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
            timed_out = mid < p.FLIP_EXIT_MID  # equivalently: held_for >= TIMEOUT and mid never recovered
            if position > 0:
                orders.append(Order(P, best_bid, -position))   # aggressive flat
                logger.print(
                    f"FLIP EXIT: sell {position} px={best_bid} mid={mid:.1f} "
                    f"held={held_for} reason={'mid_target' if not timed_out else 'timeout'}"
                )
            if timed_out:
                hstate.s17_failed_count += 1   # v4: circuit breaker increment
                logger.print(f"S17 CIRCUIT: failed_count -> {hstate.s17_failed_count}")
            hstate.flip_holding = False
            hstate.flip_entry_row = None
        return orders, hstate

    # v10: Compute VFE drift gate — block S17 if VFE is crashing
    vfe_od = state.order_depths.get(Product.VELVETFRUIT_EXTRACT)
    vfe_mid = None
    if vfe_od and vfe_od.buy_orders and vfe_od.sell_orders:
        vfe_mid = (max(vfe_od.buy_orders) + min(vfe_od.sell_orders)) / 2.0
    # Persist VFE mid in HP state buffer
    if vfe_mid is not None:
        hstate.vfe_buf = _push(hstate.vfe_buf, vfe_mid, 200)

    # Crash detection: short buffer (50 ticks) for quick response
    # On day 3 first 1k: VFE drops $32 by ts=14200 → drift very negative early
    vfe_crashing = False
    if vfe_mid is not None and len(hstate.vfe_buf) >= 50:
        # Compare current to first quarter of buffer (lagged window)
        early_avg = sum(hstate.vfe_buf[:25]) / 25
        vfe_drift = vfe_mid - early_avg
        vfe_crashing = vfe_drift < -5.0

    # === HP ALPHA v2: z-score gate on S17 entry ===
    # Analysis (intel/hp_alpha_v2.md): baseline (mid>10010) only 66% win@200 on day 3.
    # Adding z>=2.0 (over 500-tick rolling mean) lifts day3 win-rate to 83%, days1/2 80%+.
    # Filters out marginal high-mids that are already at local equilibrium.
    s17_z = None
    if len(hstate.mid_buf_500) >= p.Z500_WINDOW:
        zb = hstate.mid_buf_500[-p.Z500_WINDOW:]
        zmu = sum(zb) / len(zb)
        zvar = sum((x - zmu) ** 2 for x in zb) / len(zb)
        zsd = zvar ** 0.5 if zvar > 0 else 0
        if zsd > 0:
            s17_z = (mid - zmu) / zsd
    S17_Z_MIN = 2.0  # NEW gate (intel/hp_alpha_v2.md)

    # Entry: spread=17 AND elevated price AND z>=2.0 AND not already in S17 short AND VFE not crashing
    # v4: circuit breaker — also require s17_failed_count < S17_MAX_FAILS
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

    # ─── v4: Z-SCORE MEAN REVERSION ──────────────────────────���──────────
    # Compute z-score from Z_WINDOW rolling buffer.
    # z > Z_ENTRY => price above mean => SHORT
    # z < -Z_ENTRY => price below mean => BUY
    # |z| < Z_EXIT => flatten directional position, resume passive MM
    z_buf = hstate.mid_buf_500[-p.Z_WINDOW:] if len(hstate.mid_buf_500) >= p.Z_WINDOW else None
    z = None
    if z_buf is not None:
        z_mu = sum(z_buf) / len(z_buf)
        z_var = sum((x - z_mu) ** 2 for x in z_buf) / len(z_buf)
        z_sd = z_var ** 0.5 if z_var > 0 else 0
        if z_sd > 0:
            z = (mid - z_mu) / z_sd

    if z is not None and abs(z) > p.Z_ENTRY:
        # Directional z-signal active
        # Scale size with z magnitude: base_size * min(|z|/1.5, 3)
        z_scale = min(abs(z) / p.Z_ENTRY, 3.0)
        target_qty = int(round(p.Z_BASE_SIZE * z_scale))
        target_qty = min(target_qty, p.Z_MAX_POS)

        if z > p.Z_ENTRY:
            # SHORT signal: price above mean
            target_pos = -target_qty
            delta = target_pos - position
            if delta < 0:  # need to sell more
                sell_qty = min(-delta, pos_lim + position)
                if sell_qty > 0:
                    orders.append(Order(P, best_bid, -sell_qty))
        else:
            # BUY signal: price below mean
            target_pos = target_qty
            delta = target_pos - position
            if delta > 0:  # need to buy more
                buy_qty = min(delta, pos_lim - position)
                if buy_qty > 0:
                    orders.append(Order(P, best_ask, buy_qty))

        # Also post passive on the OTHER side for spread capture
        fv = int(round(mid))
        if z > p.Z_ENTRY:
            # We're short, post passive bid to capture reversion
            bid_headroom = pos_lim - position
            bid_qty = min(p.QUOTE_SIZE, max(0, bid_headroom))
            if bid_qty > 0:
                my_bid = max(best_bid + 1, fv - 1)
                my_bid = min(my_bid, best_ask - 1)
                orders.append(Order(P, my_bid, bid_qty))
        else:
            # We're long, post passive ask to capture reversion
            ask_headroom = pos_lim + position
            ask_qty = min(p.QUOTE_SIZE, max(0, ask_headroom))
            if ask_qty > 0:
                my_ask = min(best_ask - 1, fv + 1)
                my_ask = max(my_ask, best_bid + 1)
                orders.append(Order(P, my_ask, -ask_qty))

        return orders, hstate

    # z near zero OR not enough data: flatten any directional position + passive MM
    if z is not None and abs(z) < p.Z_EXIT and abs(position) > p.QUOTE_SIZE:
        # Flatten toward zero
        if position > 0:
            sell_qty = min(position, p.QUOTE_SIZE * 2)
            orders.append(Order(P, best_bid, -sell_qty))
        elif position < 0:
            buy_qty = min(-position, p.QUOTE_SIZE * 2)
            orders.append(Order(P, best_ask, buy_qty))
        return orders, hstate

    # Passive MM fallback. Edge-beta skew tested (LEAN audit: noise +3/+30/+8); not used.
    bid_offset = 0
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
# v12 Layer A: skip 6000/6500 entirely — one-sided sells, expire 0
VOUCHER_STRIKES_SKIP = {6000, 6500}
# v12 Layer C: passive OTM bid strikes (one-sided seller flow)
VOUCHER_STRIKES_OTM_PASSIVE = [5300, 5400, 5500]
VOUCHER_SYM = {k: f"VEV_{k}" for k in VOUCHER_STRIKES_ALL}
V_TTE_DAYS_AT_START = 4.0
V_TTE_YEAR = 250.0
V_VOUCHER_MM_SIZE = 40   # v5d sweep: was 20, +$446 def / +$297 imc
V_VOUCHER_MIN_SPREAD = 2
V_POST_SLACK_VE = 1
V_BS_SIGMA_DEFAULT = 0.18
V_BS_EDGE = 10.0
V_BS_TRADE_SIZE = 30
V_BS_POS_CAP = 150
V_BS_STRIKES = [5000, 5100, 5200, 5300, 5400]
V_IV_ADAPT_WINDOW = 50
V_IV_ADAPT_MIN_HIST = 15

# === v5 NEW: Conditional Voucher OBI layer (Phase A winner) ===
# OBI = (bid_vol - ask_vol)/(bid_vol + ask_vol)
# OBI > +0.7 AND spread <= 10 → AGGRESSIVE BUY at ask
# OBI < -0.7                  → AGGRESSIVE SELL at bid
# Multi-strike confirmation across ATM strikes (5100-5500): 2× size
# Phase A BT: +$226 1k probe / +$3,160 10k default / +$3,282 10k imc (Pareto vs v3).
OBI_ACTIVE_STRIKES = [4000, 5200, 5300, 5400, 5500]
OBI_ATM_STRIKES = [5100, 5200, 5300, 5400, 5500]
OBI_THRESHOLD = 0.7
OBI_SPREAD_COMPRESS_MAX = 10
OBI_BASE_SIZE = 10
OBI_CONFIRM_SCALE = 2
OBI_CONFIRM_MIN_STRIKES = 3
OBI_POS_CAP = 30    # v5c re-sweep at QS=200: tightened from 100, +$1,916 def / +$2,444 imc


def voucher_obi(od):
    """Return (obi, spread, best_bid, best_ask) or None."""
    if not od or not od.buy_orders or not od.sell_orders: return None
    bb = max(od.buy_orders); ba = min(od.sell_orders)
    bv = od.buy_orders[bb]; av = -od.sell_orders[ba]
    if bv + av <= 0: return None
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
        # v6_m49: Mark 49 VFE fade state
        self.m49_long_until: Optional[int] = None
        self.m49_short_until: Optional[int] = None
        self.m49_seen: List[int] = []

    def to_dict(self):
        return {
            "ivh": {str(k): v[-V_IV_ADAPT_WINDOW:] for k, v in self.iv_history.items()},
            "ls": self.last_spot,
            "sa": self.spot_age,
            "p_ap": self.prev_ve_ap1,
            "p_bp": self.prev_ve_bp1,
            "m49_lu": self.m49_long_until,
            "m49_su": self.m49_short_until,
            "m49_seen": self.m49_seen[-32:],
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
        s.m49_long_until = d.get("m49_lu")
        s.m49_short_until = d.get("m49_su")
        s.m49_seen = d.get("m49_seen", [])
        return s


# ── v6: Mark 49 VFE fade ─────────────────────────────────────────────────────
# Empirical (3-day, 105 SELLs / 17 BUYs):
#   M49 SELL → mid +1.90 (t=+20.0) at H=1, Bonferroni-significant.
M49_QTY_MIN_SELL = 8     # M49 sells qty>=8 (93/105)
M49_QTY_MIN_BUY  = 1
M49_HOLD_TICKS = 5  # v7c sweep optimum
M49_SIZE = 60  # v7c sweep: was 20, +$1,252 def
M49_POS_CAP = 20


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

    # Process market_trades for new Mark 49 fills.
    # state.market_trades is dict[Symbol, List[Trade]]; each Trade has .timestamp,
    # .buyer, .seller, .quantity. We dedupe via vstate.m49_seen of recent ts.
    m_trades = (state.market_trades or {}).get(P, [])
    seen_set = set(vstate.m49_seen)
    for tr in m_trades:
        if tr.timestamp in seen_set: continue
        if tr.seller == "Mark 49" and tr.quantity >= M49_QTY_MIN_SELL:
            # M49 sold → fade by going LONG
            vstate.m49_long_until = ts_now + M49_HOLD_TICKS * 100
            vstate.m49_seen.append(tr.timestamp)
            seen_set.add(tr.timestamp)
        elif tr.buyer == "Mark 49" and tr.quantity >= M49_QTY_MIN_BUY:
            # M49 bought → fade by going SHORT
            vstate.m49_short_until = ts_now + M49_HOLD_TICKS * 100
            vstate.m49_seen.append(tr.timestamp)
            seen_set.add(tr.timestamp)
    # Trim seen list
    if len(vstate.m49_seen) > 64:
        vstate.m49_seen = vstate.m49_seen[-32:]

    # Expire windows
    if vstate.m49_long_until is not None and ts_now >= vstate.m49_long_until:
        vstate.m49_long_until = None
    if vstate.m49_short_until is not None and ts_now >= vstate.m49_short_until:
        vstate.m49_short_until = None

    extra: List[Order] = []
    extra_buy = 0
    extra_sell = 0

    long_active = vstate.m49_long_until is not None
    short_active = vstate.m49_short_until is not None
    # If both active simultaneously (rare), prefer the LONG (stronger signal).
    if long_active and short_active:
        short_active = False

    # Aggressive take. Empirical edge ~$2/share H=1, decaying to ~$1.9/share H=10.
    # Spread on VFE typically 2-3, so half-spread cost = $1-1.5. Net edge $0.5-1/share.
    # 1k probe windows have 0-2 firings (insufficient sample); alpha materializes on
    # 10k 3-day. See intel/mark49_alpha.md for full BT matrix.
    if long_active and pos < M49_POS_CAP:
        target_buy = min(M49_SIZE, M49_POS_CAP - pos)
        target_buy = min(target_buy, 200 - pos)
        if target_buy > 0:
            extra.append(Order(P, ba, target_buy))
            extra_buy = target_buy
    elif short_active and pos > -M49_POS_CAP:
        target_sell = min(M49_SIZE, M49_POS_CAP + pos)
        target_sell = min(target_sell, 200 + pos)
        if target_sell > 0:
            extra.append(Order(P, bb, -target_sell))
            extra_sell = target_sell

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


# ── v9 smile-fit ─────────────────────────────────────────────────────────────
# Manual 3x3 normal-equations LSQ. Returns dict {K: fitted_sigma} or None.
# Fits iv(K) = a*m^2 + b*m + c where m = log(K/spot) over the strikes provided.
def _fit_parabola(xs, ys):
    n = len(xs)
    if n < 3: return None
    S0 = float(n); S1 = sum(xs); S2 = sum(x*x for x in xs)
    S3 = sum(x*x*x for x in xs); S4 = sum(x*x*x*x for x in xs)
    Sy = sum(ys); Sxy = sum(x*y for x, y in zip(xs, ys))
    Sx2y = sum(x*x*y for x, y in zip(xs, ys))
    M = [[S4, S3, S2], [S3, S2, S1], [S2, S1, S0]]
    rhs = [Sx2y, Sxy, Sy]
    def det3(m):
        return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
                - m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
                + m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))
    D = det3(M)
    if abs(D) < 1e-12: return None
    out = []
    for col in range(3):
        Mc = [row[:] for row in M]
        for r in range(3): Mc[r][col] = rhs[r]
        out.append(det3(Mc) / D)
    return tuple(out)


def v_smile_fit_sigmas(state, vstate, spot):
    """v11: parabola fit with (1) centered m for numerical stability,
    (2) extrinsic-value weighting to reduce deep-ITM dominance,
    (3) exclude K=4000 (deepest ITM, near-zero extrinsic gives explosive IV)."""
    obs = []
    for K in VOUCHER_STRIKES_ALL:
        if K == 4000:  # Fix 3: exclude deepest ITM from fit
            continue
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None: continue
        wm_v = v_wall_mid(od_v)
        if wm_v is None: continue
        if K <= spot:
            intr = spot - K
            if wm_v <= intr + 0.5: continue
            extrinsic = wm_v - intr
        else:
            extrinsic = wm_v
        T = max(V_TTE_DAYS_AT_START - state.timestamp / 1_000_000.0, 0.01) / V_TTE_YEAR
        iv = v_implied_vol(wm_v, spot, K, T)
        if iv is None: continue
        m = math.log(K / spot)
        # Fix 3b: extrinsic-weight (cap at 0.5 floor to avoid huge weights for ATM)
        weight = max(extrinsic, 0.5)
        obs.append((K, m, iv, weight))
    if len(obs) < 4: return {}
    # Fix 1: center m before fitting
    ms = [o[1] for o in obs]
    m_bar = sum(ms) / len(ms)
    ms_c = [m - m_bar for m in ms]
    ivs = [o[2] for o in obs]
    weights = [o[3] for o in obs]
    coef = _fit_parabola_weighted(ms_c, ivs, weights)
    if coef is None: return {}
    a_, b_, c_ = coef
    out = {}
    for K in VOUCHER_STRIKES_ALL:
        m_c = math.log(K / spot) - m_bar
        s = a_*m_c*m_c + b_*m_c + c_
        if s <= 0.01 or s > 5.0: continue
        out[K] = s
    return out


def _fit_parabola_weighted(xs, ys, ws):
    """Weighted least-squares parabola fit on centered x."""
    n = len(xs)
    if n < 3: return None
    Sw = sum(ws)
    Swx = sum(w*x for w, x in zip(ws, xs))
    Swxx = sum(w*x*x for w, x in zip(ws, xs))
    Swxxx = sum(w*x*x*x for w, x in zip(ws, xs))
    Swxxxx = sum(w*x*x*x*x for w, x in zip(ws, xs))
    Swy = sum(w*y for w, y in zip(ws, ys))
    Swxy = sum(w*x*y for w, x, y in zip(ws, xs, ys))
    Swxxy = sum(w*x*x*y for w, x, y in zip(ws, xs, ys))
    M = [[Swxxxx, Swxxx, Swxx], [Swxxx, Swxx, Swx], [Swxx, Swx, Sw]]
    rhs = [Swxxy, Swxy, Swy]
    def det3(m):
        return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
                - m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
                + m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))
    D = det3(M)
    if abs(D) < 1e-12: return None
    out = []
    for col in range(3):
        Mc = [row[:] for row in M]
        for r in range(3): Mc[r][col] = rhs[r]
        out.append(det3(Mc) / D)
    return tuple(out)


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

    # v6_m49: Mark 49 fade layer (PRE-MM, claims position headroom)
    m49_orders, m49_buy, m49_sell = run_mark49_fade(state, vstate)

    if od_ve and od_ve.buy_orders and od_ve.sell_orders:
        wm = v_wall_mid(od_ve)
        if wm is not None:
            bb = max(od_ve.buy_orders); ba = min(od_ve.sell_orders)
            pos = state.position.get(VEVE_SYM, 0)
            fv = round(wm)
            tb = 200 - pos - layer_e_buy - m49_buy
            ts = 200 + pos - layer_e_sell - m49_sell
            half = 100
            mbp = fv - 1 if pos > half else fv
            msp = fv + 1 if pos < -half else fv
            ve_orders = list(ve_layer_e) + list(m49_orders)
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
            fallback = list(ve_layer_e) + list(m49_orders)
            if fallback:
                orders[VEVE_SYM] = fallback

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
    # v9: per-tick smile fit. Returns {K: fitted_sigma}; empty on insufficient data.
    smile_sigmas = v_smile_fit_sigmas(state, vstate, spot)

    def _sigma_for(K):
        s = smile_sigmas.get(K)
        return s if s is not None else sigma

    # Intrinsic arb REMOVED (Frankfurt parsimony audit: 0/0/0 firings - never triggers).

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
        fv_bs = v_bs_call(spot, K, T, _sigma_for(K))
        # v3 Agent 6: VEV_5200 needs tighter edge to break even (+$7k day 3)
        edge = V_BS_EDGE  # v11: 5200 carve-out removed (smile fit subsumes it; BT-identical)
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

    # Call-spread arb REMOVED (Frankfurt parsimony audit: 0/1.35M pair-ticks - dead code).

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

    # OTM passive bid (re-validated under smile sigma: +$341 def / +$295 imc / 0 on probes).
    # Prior fixed-sigma audit had -$325 def / -$686 imc; smile flipped sign.
    OTM_BID_SIZE = 5
    OTM_BID_POS_CAP = 50
    OTM_BID_EDGE = 2  # bid must be at least 2 below smile-fitted BS fair
    for K in VOUCHER_STRIKES_OTM_PASSIVE:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        bb = max(od_v.buy_orders); ba = min(od_v.sell_orders)
        fv_bs = v_bs_call(spot, K, T, _sigma_for(K))
        bs_cap = math.floor(fv_bs - OTM_BID_EDGE)
        bid_px = min(bb + 1, bs_cap)
        if bid_px <= 0: continue
        if bid_px >= ba: continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        room = OTM_BID_POS_CAP - pos_v - existing_buy
        if room > 0:
            q = min(room, OTM_BID_SIZE)
            orders.setdefault(sym, []).append(Order(sym, bid_px, q))

    # ── VEV_6000/6500 deep-OTM free $0.50 MTM ──────────────────────────────
    # Mark 22 dumps to Mark 01 at price=0 every tick. Post bid=0 size=100.
    # +$900 deterministic 3-day BT, no delta risk (spot needs +700 to threaten).
    DEEP_OTM_BID_PX = 0
    DEEP_OTM_BID_SIZE = 100
    for K in [6000, 6500]:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None: continue
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        room = 300 - pos_v - existing_buy
        if room > 0:
            q = min(DEEP_OTM_BID_SIZE, room)
            orders.setdefault(sym, []).append(Order(sym, DEEP_OTM_BID_PX, q))

    # ── v5 NEW: Conditional Voucher OBI layer (Phase A winner) ────────────
    # +$3,160 default / +$3,282 imc on 10k 3-day, +$226 on 1k probe
    atm_obis: Dict[int, float] = {}
    for K in OBI_ATM_STRIKES:
        od_v = state.order_depths.get(VOUCHER_SYM[K])
        r = voucher_obi(od_v) if od_v else None
        if r is not None: atm_obis[K] = r[0]
    pos_signs = sum(1 for o in atm_obis.values() if o > OBI_THRESHOLD)
    neg_signs = sum(1 for o in atm_obis.values() if o < -OBI_THRESHOLD)
    scale_buy  = OBI_CONFIRM_SCALE if pos_signs >= OBI_CONFIRM_MIN_STRIKES else 1
    scale_sell = OBI_CONFIRM_SCALE if neg_signs >= OBI_CONFIRM_MIN_STRIKES else 1

    for K in OBI_ACTIVE_STRIKES:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        r = voucher_obi(od_v) if od_v else None
        if r is None: continue
        obi, sp_v, vbb, vba = r
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        already_buy = sum(o.quantity for o in existing if o.quantity > 0)
        already_sell = sum(-o.quantity for o in existing if o.quantity < 0)

        # BUY trigger: OBI>+0.7 AND spread<=10
        if obi > OBI_THRESHOLD and sp_v <= OBI_SPREAD_COMPRESS_MAX and pos_v < OBI_POS_CAP:
            qty = OBI_BASE_SIZE * scale_buy
            room = min(300 - pos_v - already_buy, OBI_POS_CAP - pos_v - already_buy)
            avail = -od_v.sell_orders[vba]
            q = min(qty, room, avail)
            if q > 0:
                orders.setdefault(sym, []).append(Order(sym, vba, +q))

        # SELL trigger: OBI<-0.7 (no spread gate)
        if obi < -OBI_THRESHOLD and pos_v > -OBI_POS_CAP:
            qty = OBI_BASE_SIZE * scale_sell
            room = min(300 + pos_v - already_sell, OBI_POS_CAP + pos_v - already_sell)
            avail = od_v.buy_orders[vbb]
            q = min(qty, room, avail)
            if q > 0:
                orders.setdefault(sym, []).append(Order(sym, vbb, -q))

    return orders




def _clamp_to_position_limits(orders_by_sym, positions, debug_log=None):
    """v4 Defensive: truncate orders to satisfy IMC's per-product all-or-nothing rule.
    BT byte-identical to v3 (no clamps fire on validated paths)."""
    clamped = {}
    for sym, ords in orders_by_sym.items():
        if not ords:
            clamped[sym] = ords
            continue
        lim = POSITION_LIMITS.get(sym, 999_999)
        pos = positions.get(sym, 0)
        max_buy_total = max(0, lim - pos)
        max_sell_total = max(0, lim + pos)
        out = []
        cum_buy = 0
        cum_sell = 0
        for o in ords:
            if o.quantity > 0:
                allow = min(o.quantity, max_buy_total - cum_buy)
                if allow > 0:
                    if allow == o.quantity:
                        out.append(o)
                    else:
                        out.append(Order(o.symbol, o.price, allow))
                        if debug_log is not None:
                            debug_log.append(f"CLAMP {sym} BUY {o.price}@{o.quantity}->{allow} pos={pos}")
                    cum_buy += allow
                elif debug_log is not None:
                    debug_log.append(f"CLAMP {sym} BUY {o.price}@{o.quantity}->0 pos={pos}")
            elif o.quantity < 0:
                want = -o.quantity
                allow = min(want, max_sell_total - cum_sell)
                if allow > 0:
                    if allow == want:
                        out.append(o)
                    else:
                        out.append(Order(o.symbol, o.price, -allow))
                        if debug_log is not None:
                            debug_log.append(f"CLAMP {sym} SELL {o.price}@{want}->{allow} pos={pos}")
                    cum_sell += allow
                elif debug_log is not None:
                    debug_log.append(f"CLAMP {sym} SELL {o.price}@{want}->0 pos={pos}")
        clamped[sym] = out
    return clamped


# v8 HYBRID: regime-conditional yolo overlay (NN-augmented v2: defensive gate)
YOLO_DETECT_TICKS_TS = 3000      # primary decision at ts=3000 (tick 30)
# NN insight: hp_vfe_corr in [0..3000ts] cleanly separates d3 (cor=-0.275) from d1 (+0.20)
# d2 (+0.36) at the same ts=3000 window. Use as a defensive VETO: if primary fires
# but corr is strongly positive (d1/d2 signature), skip yolo to protect against
# r4 day-4 having a "false-fire" regime (vfe slightly down by ts=30 but actually up-day).
# Veto only triggers if corr is strongly positive (>=+0.30) AND vfe_drift wasn't deeply
# negative (>=-2). Training data: d0 (eod=-6) has corr=+0.35 at ts=3k — fires currently.
# We accept losing d0's yolo (small) for d4-protection.
YOLO_DRIFT_THRESHOLD = 2.0       # VFE must drift <= +2.0 to enter SHORT
YOLO_VETO_CORR = 0.30            # if hp_vfe_corr@3k >= +0.30, veto (skip yolo)
YOLO_VETO_DRIFT_FLOOR = -2.0     # only veto if drift hasn't already dropped <-2

# ML PREDICTOR (v3): logistic regression trained on R4 d1+d2 sliding-100k windows
# (18 train samples). Target = sign(EOD VFE drift from window-end). L2 lam=0.01.
# Test holdout (R4 d3 sliding windows) = 9/9 = 100%.
# Acts as THIRD opinion: only activates when primary fires AND existing corr-veto
# does NOT already veto (drift in [-2, +2] AND corr < +0.30 — the "uncertain zone").
# On training data: d1 primary skips (drift=+4.5), d2 corr-veto kills (corr=+0.31),
# d3 corr-veto inactive (corr=-0.23) -> ML decides -> p_down=0.76 -> fires (preserved).
# Features computed at decision tick from history collected during [0, ts=3000).
LR_F = ["hp_mid_std","vfe_mid_std","vfe_ret_mean","vfe_mid_drift","hp_mid_drift",
    "vfe_obi_skew","vfe_ret_ac1","hp_s17_density","hp_above_10010","hp_vfe_corr",
    "vfe_ret_skew"]
LR_M = [17.016025, 9.153572, 0.001306, 1.305556, 2.000000, 0.000001, -0.161143,
    0.014930, 0.297092, -0.105115, -0.030193]
LR_SD = [5.289975, 2.292576, 0.017791, 17.790555, 32.725288, 0.014325, 0.034300,
    0.019470, 0.299717, 0.416467, 0.090847]
LR_W = [-0.192954, -0.329947, 0.214844, 0.214844, -1.446802, 1.790243, -0.337868,
    -0.515971, -0.475770, -0.691985, -0.202236]
LR_B = -6.196946
ML_PROB_THRESHOLD = 0.50         # p_down >= 0.50 -> confirm DOWN, allow YOLO fire

YOLO_VOUCHER_TARGETS = {
    "VEV_4000": -300, "VEV_4500": -300, "VEV_5000": -300, "VEV_5100": -300,
    "VEV_5200": -300, "VEV_5300": -300, "VEV_5400": -300, "VEV_5500": -300,
}
YOLO_VFE_TARGET = -200  # v10b: full yolo (no hedge)


class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orders      = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}

        # v8 YOLO REGIME GATE (decide at ts=3000) + NN defensive veto
        yolo_anchor = raw.get("yolo_anchor")
        yolo_regime = raw.get("yolo_regime", None)  # None=undecided, True=short, False=skip
        ts = state.timestamp
        vfe_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        hp_od = state.order_depths.get("HYDROGEL_PACK")
        vfe_mid = None
        hp_mid = None
        if vfe_od and vfe_od.buy_orders and vfe_od.sell_orders:
            vfe_mid = (max(vfe_od.buy_orders) + min(vfe_od.sell_orders)) / 2.0
        if hp_od and hp_od.buy_orders and hp_od.sell_orders:
            hp_mid = (max(hp_od.buy_orders) + min(hp_od.sell_orders)) / 2.0
        if yolo_anchor is None and vfe_mid is not None:
            yolo_anchor = vfe_mid
            raw["yolo_anchor"] = yolo_anchor
        # Track HP & VFE midprice series for correlation gate (sampled BEFORE we trade)
        corr_hist = raw.get("corr_hist", {"hp": [], "vfe": []})
        # ML features need extras: HP spread (for s17), VFE best bid/ask volumes (for OBI)
        ml_hist = raw.get("ml_hist", {"hp_sp": [], "vfe_bv": [], "vfe_av": []})
        if ts <= YOLO_DETECT_TICKS_TS and hp_mid is not None and vfe_mid is not None:
            corr_hist["hp"].append(hp_mid)
            corr_hist["vfe"].append(vfe_mid)
            raw["corr_hist"] = corr_hist
            # ML auxiliary tracking
            hp_sp_val = -1.0
            if hp_od and hp_od.buy_orders and hp_od.sell_orders:
                hp_sp_val = float(min(hp_od.sell_orders) - max(hp_od.buy_orders))
            ml_hist["hp_sp"].append(hp_sp_val)
            vfe_bv = vfe_av = 0.0
            if vfe_od and vfe_od.buy_orders and vfe_od.sell_orders:
                bb = max(vfe_od.buy_orders); ba = min(vfe_od.sell_orders)
                vfe_bv = float(vfe_od.buy_orders.get(bb, 0))
                vfe_av = float(abs(vfe_od.sell_orders.get(ba, 0)))
            ml_hist["vfe_bv"].append(vfe_bv)
            ml_hist["vfe_av"].append(vfe_av)
            raw["ml_hist"] = ml_hist
        if yolo_regime is None and ts >= YOLO_DETECT_TICKS_TS and vfe_mid is not None and yolo_anchor is not None:
            drift = vfe_mid - yolo_anchor
            primary_fire = (drift <= YOLO_DRIFT_THRESHOLD)
            # NN defensive veto: if primary wants to fire and drift is borderline (>=-2),
            # check hp_vfe_corr. Strongly positive => d1/d2 signature => skip.
            veto = False
            corr = 0.0
            existing_veto_active = False
            if primary_fire and drift >= YOLO_VETO_DRIFT_FLOOR and len(corr_hist["hp"]) >= 10:
                hp_arr = corr_hist["hp"]
                vfe_arr = corr_hist["vfe"]
                n = len(hp_arr)
                mh = sum(hp_arr) / n
                mv = sum(vfe_arr) / n
                num = sum((h - mh) * (v - mv) for h, v in zip(hp_arr, vfe_arr))
                dh = sum((h - mh) ** 2 for h in hp_arr) ** 0.5
                dv = sum((v - mv) ** 2 for v in vfe_arr) ** 0.5
                corr = num / (dh * dv) if dh > 0 and dv > 0 else 0.0
                raw["yolo_corr_at_decision"] = corr
                if corr >= YOLO_VETO_CORR:
                    veto = True
                    existing_veto_active = True
            # ML THIRD-OPINION VETO (v3): if primary fires and existing-veto did NOT veto,
            # consult logistic regression. p_down < 0.5 -> ML disagrees -> veto.
            if primary_fire and not existing_veto_active and len(corr_hist["hp"]) >= 10:
                hp_arr = corr_hist["hp"]; vfe_arr = corr_hist["vfe"]
                n = len(hp_arr)
                # vfe rets
                vrets = [vfe_arr[i] - vfe_arr[i-1] for i in range(1, n)]
                def _std(a):
                    if len(a) < 2: return 0.0
                    m = sum(a)/len(a)
                    return (sum((x-m)**2 for x in a)/len(a)) ** 0.5
                def _mean(a):
                    return sum(a)/len(a) if a else 0.0
                hp_mid_std = _std(hp_arr)
                vfe_mid_std = _std(vfe_arr)
                vfe_ret_mean = _mean(vrets)
                vfe_mid_drift = vfe_arr[-1] - vfe_arr[0]
                hp_mid_drift = hp_arr[-1] - hp_arr[0]
                # OBI skew
                bv = ml_hist.get("vfe_bv", []); av = ml_hist.get("vfe_av", [])
                obis = []
                for i in range(min(len(bv), len(av))):
                    s = bv[i] + av[i]
                    if s > 0: obis.append((bv[i] - av[i]) / s)
                vfe_obi_skew = _mean(obis) if obis else 0.0
                # vfe ret ac1
                vfe_ret_ac1 = 0.0
                if len(vrets) >= 3:
                    rm = _mean(vrets)
                    num2 = sum((vrets[i]-rm)*(vrets[i-1]-rm) for i in range(1, len(vrets)))
                    den2 = sum((r-rm)**2 for r in vrets)
                    if den2 > 0: vfe_ret_ac1 = num2 / den2
                # s17 density
                hp_sp_arr = ml_hist.get("hp_sp", [])
                if hp_sp_arr:
                    hp_s17_density = sum(1 for s in hp_sp_arr if s == 17.0) / len(hp_sp_arr)
                else:
                    hp_s17_density = 0.0
                # hp_above_10010
                hp_above_10010 = sum(1 for m in hp_arr if m > 10010) / len(hp_arr) if hp_arr else 0.0
                # vfe ret skew
                vfe_ret_skew = 0.0
                if len(vrets) >= 3:
                    rm = _mean(vrets); rs = _std(vrets)
                    if rs > 0:
                        vfe_ret_skew = sum(((r-rm)/rs)**3 for r in vrets) / len(vrets)
                feats_dict = {
                    "hp_mid_std": hp_mid_std, "vfe_mid_std": vfe_mid_std,
                    "vfe_ret_mean": vfe_ret_mean, "vfe_mid_drift": vfe_mid_drift,
                    "hp_mid_drift": hp_mid_drift, "vfe_obi_skew": vfe_obi_skew,
                    "vfe_ret_ac1": vfe_ret_ac1, "hp_s17_density": hp_s17_density,
                    "hp_above_10010": hp_above_10010, "hp_vfe_corr": corr,
                    "vfe_ret_skew": vfe_ret_skew,
                }
                # Standardize + dot product
                z = LR_B
                for i, fname in enumerate(LR_F):
                    z += LR_W[i] * (feats_dict[fname] - LR_M[i]) / LR_SD[i]
                if z > 500: z = 500
                if z < -500: z = -500
                p_down = 1.0 / (1.0 + math.exp(-z))
                raw["yolo_ml_p_down"] = p_down
                if p_down < ML_PROB_THRESHOLD:
                    veto = True
            yolo_regime = primary_fire and not veto
            raw["yolo_regime"] = yolo_regime

        # HP layer always runs
        hstate = HydrogelState.from_dict(raw.get("hg", {}))
        hydrogel_orders, hstate = run_hydrogel(state, hstate)
        orders[Product.HYDROGEL_PACK] = hydrogel_orders
        raw["hg"] = hstate.to_dict()

        if yolo_regime is True:
            # YOLO MODE — short voucher portfolio + VFE, suppress voucher MM
            vstate = VoucherState.from_dict(raw.get("v9", {}))
            for sym, target in YOLO_VOUCHER_TARGETS.items():
                od_v = state.order_depths.get(sym)
                if od_v is None or not od_v.buy_orders: continue
                pos_v = state.position.get(sym, 0)
                desired_short = target - pos_v  # negative if we need to sell more
                if desired_short < 0:
                    qty = -desired_short
                    bb_v = max(od_v.buy_orders)
                    avail = od_v.buy_orders[bb_v]
                    q = min(qty, avail, 300)
                    if q > 0:
                        orders.setdefault(sym, []).append(Order(sym, bb_v, -q))
            # VFE short
            if vfe_od and vfe_od.buy_orders:
                pos_vfe = state.position.get("VELVETFRUIT_EXTRACT", 0)
                desired = YOLO_VFE_TARGET - pos_vfe
                if desired < 0:
                    qty = -desired
                    bb = max(vfe_od.buy_orders)
                    avail = vfe_od.buy_orders[bb]
                    q = min(qty, avail, 200)
                    if q > 0:
                        orders.setdefault("VELVETFRUIT_EXTRACT", []).append(Order("VELVETFRUIT_EXTRACT", bb, -q))
            raw["v9"] = vstate.to_dict()
        else:
            # v7c MODE — normal voucher MM + VFE momo + counterparty
            vstate = VoucherState.from_dict(raw.get("v9", {}))
            voucher_orders = run_vouchers(state, vstate)
            for sym, ord_list in voucher_orders.items():
                if sym not in orders: orders[sym] = []
                orders[sym].extend(ord_list)
            raw["v9"] = vstate.to_dict()

        clamp_log: List[str] = []
        orders = _clamp_to_position_limits(orders, state.position, clamp_log)
        for line in clamp_log:
            logger.print(line)

        new_trader_data = json.dumps(raw)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data
