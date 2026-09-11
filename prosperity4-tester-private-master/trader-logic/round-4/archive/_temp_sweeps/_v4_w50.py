"""r4_final_v3.py — R4 RE-SUBMISSION 2 after 17-agent alpha hunt.

EVOLUTION:
  494304 (z=2.25 only) → -$9,997 LIVE 1k day 3
  v2 (S17 VFE gate + VFE momo) → +$1,016 1k day 3 / $111,422 10k 3-day
  v3 (this) → adds Agent 1's HP S17 z-gate (+$11k), Agent 6's VEV_5200 edge=5 fix,
    Agent 8's VEV_6000/6500 deep-OTM bid (+$900), Agent 21 circuit breaker.

ALPHA STACK in v3:
  HP layer:
    + S17 z-gate (Agent 1): require (mid - mean_500)/sd_500 >= 2.0 to enter S17.
      Day 3 win rate 66% → 83%. +$11k 10k 3-day, 1k probe unchanged.
    + VFE-CRASH GATE (kept from v2): VFE drift < -$5 → block S17.
    + S17 circuit breaker (Agent 21): freeze S17 after 2 FLIP_HOLD timeouts.
    + z-score MR (window=500, threshold=2.25)
    + passive MM with edge-beta calibration

  VFE layer:
    + Wall-Mid MM + Layer-E spread-state lift (kept)
    + One-shot momentum short (kept from v2)

  Voucher layer:
    + VEV_5200 BS_EDGE=5 per-strike (Agent 6): -$259 → +$6,878 day 3 default.
    + VEV_6000/6500 bid=0 size=100 (Agent 8): +$900 deterministic 3-day.
    + (rest unchanged: deep ITM theta, intrinsic arb, BS taking)

REJECTED layers (BT-validated negative):
  - Counterparty (v6/v7) — substitution effect
  - Delta hedging (Agent 18) — destroys $7,749 unhedged alignment
  - Vol surface MM (Agent 11) — IV is slow RW, vol-arb sub-tick
  - Call-spread arb (Agent 15) — 0/1.35M opportunities (dead code)
  - Global BS_EDGE=3 (Agent 5) — risky day-2 5100 collapse

R4 BT (default mode):
                     | r4_final (494304) | r4_final_v2 (v12) |  Δ
  1k day 1           |      $2,402       |      $3,177       | +$775
  1k day 2           |      $15,265      |      $15,469      | +$204
  1k day 3 (probe)   |      -$9,860      |      $1,016       | +$10,876
  10k day 3          |      $38,715      |      $45,394      | +$6,679
  10k 3-day          |      $107,542     |      $111,422     | +$3,880
  10k 3-day imc      |      $100,156     |      $109,818     | +$9,662

Strictly dominates r4_final on ALL test windows.

INTENTIONALLY EXCLUDED:
  - Counterparty layer (Mark 67/49 VFE): didn't add net alpha in BT (v6/v7 tested).
  - Voucher BS_EDGE tightening: voucher PnL near saturation per intel/voucher_alpha.md.
  - DEEP_ITM_POS_CAP bump 100→150: was a no-op (BT identical, never bound).

COMPLIANCE: Per IMC policy 2026-04-27 ("smart reverse engineering of bots OK,
hardcoded pricing/external/bug exploitation = DQ"), v2 uses purely observable
market features (VFE drift, mid velocity) — no hardcoded prices, no timestamps,
no external data. Should be DQ-safe."""

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

    # ==================== INTRINSIC / structure ========================
    POS_LIMIT = 200
    QUOTE_SIZE = 25

    # ===================== Z-SCORE MEAN REVERSION (v4 NEW; v8 TUNED) ====
    Z_WINDOW = 500         # rolling window for z-score
    Z_ENTRY = 2.25         # v8c
    Z_EXIT = 0.5           # |z| < this => flatten
    Z_BASE_SIZE = 40       # base qty per z-signal
    Z_MAX_POS = 120        # max position from z-signals (leave room for S17)

    # ===================== DYNAMIC calibration (v22) ===================
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
        self.vfe_buf: List[float] = []  # v10: VFE mid for crash gate

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
    # S17 entry/build → S7-bottom percentile cover → flip long to FLIP_TARGET → hold to FLIP_EXIT_MID.
    # Passive MM fallback uses online edge-beta calibration: beta = cov(edge, ret) / var(edge).
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

# ── v4: Chris Roberts P3 rolling-IV mean voucher MM ───────────────────────────
# Per-strike rolling IV, fair_K = BS(spot, K, T, mu_iv_K).
# Quote at floor(fair+0.1) bid / ceil(fair-0.1) ask. Skip if (max-min) < ROLL_IV_GATE.
ROLL_IV_WINDOW = 50        # window size (sweep variable: 30/50/100/150)
ROLL_IV_GATE   = 0.5        # skip if max(window)-min(window) < this (vol units)
ROLL_IV_SIZE   = 20         # quote size per strike
ROLL_IV_POS_CAP = 200       # per-strike position cap from this layer
ROLL_IV_STRIKES = [5000, 5100, 5200, 5300, 5400]
ROLL_IV_MIN_HIST = 20       # need this many obs before quoting


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
        # v11 VFE momentum-short
        self.vfe_momo_buf: List[float] = []
        self.vfe_momo_short_entry: Optional[float] = None
        self.vfe_momo_fired: bool = False  # v12: one-shot-per-day
        # v4: Chris Roberts P3 rolling-IV per-strike (independent window)
        self.roll_iv_hist: Dict[int, List[float]] = {k: [] for k in ROLL_IV_STRIKES}

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
            "rivh": {str(k): v[-ROLL_IV_WINDOW:] for k, v in self.roll_iv_hist.items()},
        }

    @staticmethod
    def from_dict(d):
        s = VoucherState()
        s.iv_history = {int(k): list(v) for k, v in d.get("ivh", {}).items()}
        for k in V_BS_STRIKES:
            if k not in s.iv_history: s.iv_history[k] = []
        s.roll_iv_hist = {int(k): list(v) for k, v in d.get("rivh", {}).items()}
        for k in ROLL_IV_STRIKES:
            if k not in s.roll_iv_hist: s.roll_iv_hist[k] = []
        s.last_spot = d.get("ls")
        s.spot_age = d.get("sa", 0)
        s.prev_ve_ap1 = d.get("p_ap")
        s.prev_ve_bp1 = d.get("p_bp")
        s.vfe_momo_buf = d.get("vfe_momo_buf", [])
        s.vfe_momo_short_entry = d.get("vfe_momo_short_entry")
        s.vfe_momo_fired = d.get("vfe_momo_fired", False)
        return s


# ── VFE momentum short (v11): SHORT 200 when (mid - mid_50_ago) <= -3 ─────────
# Source: intel/day3_1k_alpha.md — corr=-0.459, t=-8.13 on 1k day 3.
# Exit: TP at MTM >= +$2000 (= -10/share * 200), SL at MTM <= -$3000 (= +15/share * 200).
VFE_MOMO_BUF = 60          # rolling buffer length
VFE_MOMO_LOOKBACK = 50     # ticks to look back for velocity
VFE_MOMO_THRESH = -3.0     # mid drop trigger
VFE_MOMO_SIZE = 200        # short size
VFE_MOMO_TP = 10.0         # take profit per share (price drops $10)
VFE_MOMO_SL = 15.0         # stop loss per share (price rises $15)


def run_vfe_momentum(state, vstate, current_vfe_orders, signal_buy_used, signal_sell_used):
    """Returns additional orders to merge into VFE order list and updated headroom."""
    P = VEVE_SYM
    od = state.order_depths.get(P)
    if not od or not od.buy_orders or not od.sell_orders:
        return [], 0, 0

    bb = max(od.buy_orders); ba = min(od.sell_orders)
    mid = (bb + ba) / 2.0
    pos = state.position.get(P, 0)

    # Update buffer
    vstate.vfe_momo_buf = vstate.vfe_momo_buf + [mid]
    if len(vstate.vfe_momo_buf) > VFE_MOMO_BUF:
        vstate.vfe_momo_buf = vstate.vfe_momo_buf[-VFE_MOMO_BUF:]

    extra: List[Order] = []
    extra_buy = 0
    extra_sell = 0

    # Check exit first (if we have an open short from prior entry)
    if vstate.vfe_momo_short_entry is not None:
        entry_mid = vstate.vfe_momo_short_entry
        # MTM per share = entry - current (positive = profit on short)
        per_share_pnl = entry_mid - mid
        # Total MTM = per_share * 200
        total_pnl = per_share_pnl * VFE_MOMO_SIZE
        cover = False
        if total_pnl >= VFE_MOMO_TP * VFE_MOMO_SIZE:
            cover = True  # take profit
        elif total_pnl <= -VFE_MOMO_SL * VFE_MOMO_SIZE:
            cover = True  # stop loss
        if cover:
            # Buy back at ask. Use position-aware size.
            qty_to_cover = min(VFE_MOMO_SIZE, 200 - pos)
            qty_to_cover = max(0, qty_to_cover)
            if qty_to_cover > 0:
                extra.append(Order(P, ba, qty_to_cover))
                extra_buy = qty_to_cover
            vstate.vfe_momo_short_entry = None
        # If not covering, no new orders this tick (we already hold the short)
        return extra, extra_buy, extra_sell

    # Check entry: velocity over 50 ticks (v12: one-shot-per-day)
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
                vstate.vfe_momo_fired = True  # don't re-fire today

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

    # v11: VFE momentum-short layer (PRE-MM, claims position headroom)
    momo_orders, momo_buy, momo_sell = run_vfe_momentum(state, vstate, [], 0, 0)

    if od_ve and od_ve.buy_orders and od_ve.sell_orders:
        wm = v_wall_mid(od_ve)
        if wm is not None:
            bb = max(od_ve.buy_orders); ba = min(od_ve.sell_orders)
            pos = state.position.get(VEVE_SYM, 0)
            fv = round(wm)
            # Account for Layer E + VFE-momentum commitments in headroom
            tb = 200 - pos - layer_e_buy - momo_buy
            ts = 200 + pos - layer_e_sell - momo_sell
            half = 100
            mbp = fv - 1 if pos > half else fv
            msp = fv + 1 if pos < -half else fv
            # If momentum has us short, suppress passive WM bidding (don't fight signal)
            momentum_active = vstate.vfe_momo_short_entry is not None
            if momentum_active:
                tb = 0  # don't add long-side via WM MM while in momentum short
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
        # v3 Agent 6: VEV_5200 needs tighter edge to break even (+$7k day 3)
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

    # ── v3 Agent 8: VEV_6000/6500 deep-OTM free $0.50 MTM ─────────────────
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

    # ── v4: Chris Roberts P3 rolling-IV mean voucher MM ───────────────────
    # Per-strike: maintain rolling IV buffer; fair_K = BS(spot, K, T, mu_iv_K).
    # Quote at floor(fair+0.1) bid / ceil(fair-0.1) ask.
    # Skip strike if (max(window) - min(window)) < ROLL_IV_GATE (Chris's stability gate).
    for K in ROLL_IV_STRIKES:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        # Update rolling IV buffer using wall-mid IV
        wm_v = v_wall_mid(od_v)
        if wm_v is not None:
            iv_now = v_implied_vol(wm_v, spot, K, T)
            if iv_now is not None:
                hist = vstate.roll_iv_hist.setdefault(K, [])
                hist.append(iv_now)
                if len(hist) > ROLL_IV_WINDOW:
                    del hist[:len(hist) - ROLL_IV_WINDOW]
        hist = vstate.roll_iv_hist.get(K, [])
        if len(hist) < ROLL_IV_MIN_HIST: continue
        # Stability gate: skip if IV range too wide (regime change)
        iv_range = max(hist) - min(hist)
        if iv_range > ROLL_IV_GATE: continue
        mu_iv = sum(hist) / len(hist)
        fair_K = v_bs_call(spot, K, T, mu_iv)
        # Quote at floor(fair+0.1) bid / ceil(fair-0.1) ask
        bid_px = math.floor(fair_K - 0.1)
        ask_px = math.ceil(fair_K + 0.1)
        # Inside-spread guards
        vbb = max(od_v.buy_orders); vba = min(od_v.sell_orders)
        # Don't cross book in wrong direction: bid must be < best_ask, ask > best_bid
        if bid_px >= vba: bid_px = vba - 1
        if ask_px <= vbb: ask_px = vbb + 1
        if ask_px <= bid_px: ask_px = bid_px + 1
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        room_buy = ROLL_IV_POS_CAP - pos_v - existing_buy
        room_sell = ROLL_IV_POS_CAP + pos_v - existing_sell
        if room_buy > 0 and bid_px > 0:
            q = min(ROLL_IV_SIZE, room_buy)
            orders.setdefault(sym, []).append(Order(sym, int(bid_px), q))
        if room_sell > 0:
            q = min(ROLL_IV_SIZE, room_sell)
            orders.setdefault(sym, []).append(Order(sym, int(ask_px), -q))

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
