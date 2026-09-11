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
    # v21: v20 (SD's HP) + v19's MR exit handoff (close long when |mid-9990|<=EXIT_BAND).
    # ========================= ALPHA hardcodes =========================
    REGIME2_SPREAD = 17
    ENTRY_MID_MIN = 10010
    S7_WINDOW = 500
    S7_BOTTOM_Q = 0.08
    FLIP_TARGET = 200
    GLOBAL_MEAN = 9990    # v21 added: mean for MR exit
    EXIT_BAND = 8         # v21 added: exit band for MR (|mid-mean|<=this)
    S7_FALLBACK_TIMEOUT = 150 # Aggressively tightened from 1000 for violent trends

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
        # v21: MR exit flag — set after FLIP completes; closes long at mean.
        self.mr_long_active: bool = False
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
            "mrl":       self.mr_long_active,
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
        s.mr_long_active    = d.get("mrl", False)
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
        rows_held = hstate.row - hstate.s17_entry_row

        bottom_thresh = None
        s7_bottom     = False

        if window_ready:
            sorted_window = sorted(hstate.mid_buf_500[-p.S7_WINDOW:])
            bottom_thresh = sorted_window[int(len(sorted_window) * p.S7_BOTTOM_Q)]
            s7_bottom     = (spread == 7 and mid <= bottom_thresh)

        if s7_bottom:
            hstate.s7_covering   = True
            hstate.s17_entry_row = None
            hstate.s17_entry_mid = None
            logger.print(
                f"S17 COVER START [S7_Q{p.S7_BOTTOM_Q:.2f}]: "
                f"mid={mid:.1f} bot={bottom_thresh:.1f} pos={position}"
            )
        elif rows_held >= p.S7_FALLBACK_TIMEOUT:
            hstate.s7_covering   = True
            hstate.s17_entry_row = None
            hstate.s17_entry_mid = None
            logger.print(f"S17 FALLBACK TRIGGERED! rows_held={rows_held} mid={mid:.1f} pos={position}")

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
            hstate.mr_long_active = True   # v21: hand off to MR exit at mean
            logger.print(f"S7 FLIP COMPLETE: pos={position}, MR exit armed")
        return orders, hstate

    # v21: MR exit — close long at mean once we are within EXIT_BAND.
    # Captures the second leg of reversion without overstaying the long.
    if hstate.mr_long_active and position > 0:
        if abs(mid - p.GLOBAL_MEAN) <= p.EXIT_BAND:
            orders.append(Order(P, best_bid, -position))
            logger.print(f"MR EXIT long: pos={position} mid={mid:.1f} (mean={p.GLOBAL_MEAN})")
            hstate.mr_long_active = False
            return orders, hstate
    elif hstate.mr_long_active and position <= 0:
        # Position got flattened externally — clear the flag.
        hstate.mr_long_active = False

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


# === VOUCHERS CLEAN 2 REWRITE ===
import math
from typing import Dict, List, Tuple

class CV2State:
    def __init__(self):
        self.ema_iv = {}
        self.ema_iv_var = {}
        self.ema_fvd = {}
        self.vfe_px = None
        self.ema_rv = None  # RV tracking via EMA of returns

    def to_dict(self):
        return {
            "e_i": self.ema_iv,
            "e_v": self.ema_iv_var,
            "e_f": self.ema_fvd,
            "px": round(self.vfe_px, 2) if self.vfe_px else None,
            "rv": round(self.ema_rv, 6) if self.ema_rv is not None else None
        }

    @staticmethod
    def load(d):
        s = CV2State()
        if not d: return s
        s.ema_iv = {int(k): v for k, v in d.get("e_i", {}).items()}
        s.ema_iv_var = {int(k): v for k, v in d.get("e_v", {}).items()}
        s.ema_fvd = {int(k): v for k, v in d.get("e_f", {}).items()}
        s.vfe_px = d.get("px")
        s.ema_rv = d.get("rv")
        return s

def calc_ema(old_val, new_val, window):
    if old_val is None: return new_val
    alpha = 2.0 / (window + 1.0)
    return alpha * new_val + (1.0 - alpha) * old_val
    
def cv_norm_cdf(x):
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5*t + a4)*t) + a3)*t + a2)*t + a1)*t * math.exp(-x*x/2.0)
    return 0.5 * (1.0 + sign * y)

def cv_bs_call(S, K, T, vol):
    if T <= 0 or vol <= 0: return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    return S * cv_norm_cdf(d1) - K * cv_norm_cdf(d2)

def cv_bs_delta(S, K, T, vol):
    if T <= 0 or vol <= 0: return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    return cv_norm_cdf(d1)

def cv_implied_vol(mkt, S, K, T):
    intr = max(S - K, 0.0)
    if mkt <= intr + 1e-6 or T <= 0 or mkt >= S: return None
    lo, hi = 1e-4, 5.0
    for _ in range(30):
        m = 0.5 * (lo + hi)
        if cv_bs_call(S, K, T, m) < mkt: lo = m
        else: hi = m
    return 0.5 * (lo + hi)

def run_vouchers_clean2(state: TradingState, vstate: CV2State):
    orders = {}
    VFE = "VELVETFRUIT_EXTRACT"
    STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500] 
    
    od_vfe = state.order_depths.get(VFE)
    spot = None
    if od_vfe and od_vfe.buy_orders and od_vfe.sell_orders:
        spot = (max(od_vfe.buy_orders.keys()) + min(od_vfe.sell_orders.keys())) / 2.0
    
    if spot is None: return orders
    
    # RV tracking
    rv = 0.0
    if vstate.vfe_px is not None:
        ret = (spot / vstate.vfe_px) - 1.0
        var_1t = ret ** 2
        vstate.ema_rv = calc_ema(vstate.ema_rv, var_1t, 100) # 100 tick EMA var
        if vstate.ema_rv is not None and vstate.ema_rv > 0:
            rv = math.sqrt(vstate.ema_rv) * math.sqrt(2500000)
    else:
        vstate.ema_rv = 0.0
    
    logger.print(f"VFE SPOT: {spot:.2f} | RV: {rv:.4f}")

    vstate.vfe_px = spot
        
    T = max(5.0 - state.timestamp / 1_000_000.0, 0.01) / 250.0
    portfolio_delta = state.position.get(VFE, 0) * 1.0
    
    for K in STRIKES:
        sym = f"VEV_{K}"
        od = state.order_depths.get(sym)
        pos = state.position.get(sym, 0)
        
        if not od or not od.buy_orders or not od.sell_orders: 
            if K in vstate.ema_iv:
                portfolio_delta += pos * cv_bs_delta(spot, K, T, vstate.ema_iv[K])
            continue
            
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        mid = (bb + ba) / 2.0
        
        iv = cv_implied_vol(mid, spot, K, T)
        if iv is not None:
            prev_ema = vstate.ema_iv.get(K, iv)
            vstate.ema_iv[K] = calc_ema(vstate.ema_iv.get(K), iv, 50)
            diff_sq = (iv - prev_ema) ** 2
            vstate.ema_iv_var[K] = calc_ema(vstate.ema_iv_var.get(K), diff_sq, 50)
            
        roll_mean = vstate.ema_iv.get(K)
        if roll_mean is None: continue
        
        portfolio_delta += pos * cv_bs_delta(spot, K, T, roll_mean)
        
        roll_std = math.sqrt(vstate.ema_iv_var.get(K, 0.0))
        zscore = (iv - roll_mean) / (roll_std + 1e-6) if roll_std > 0 and iv is not None else 0.0
        vol_spread = rv - (iv if iv is not None else roll_mean)
        
        fv = cv_bs_call(spot, K, T, roll_mean)
        diff = mid - fv
        vstate.ema_fvd[K] = calc_ema(vstate.ema_fvd.get(K), diff, 50)
        roll_med_fvd = vstate.ema_fvd[K]
        
        alpha = 0
        if diff > roll_med_fvd + 4.0: alpha -= 2
        elif diff < roll_med_fvd - 4.0: alpha += 2

        # Fix #3: only use z-score once std_iv has warmed up past noise floor
        if roll_std > 0.001:
            if zscore < -2.0: alpha += 1
            elif zscore > 2.0: alpha -= 1
        
        # Fix #1: vol_sprd is meaningless when RV is near-zero (flat market);
        # suppress signal unless RV has at least some reliable signal.
        if rv >= 0.05:
            if vol_spread > 0.03: alpha += 1
            elif vol_spread < -0.03: alpha -= 1

        logger.print(f"[{sym}] pos:{pos} mid:{mid:.2f} (ba:{ba}/bb:{bb}) "
                     f"iv:{iv if iv else 0:.4f} ema_iv:{roll_mean:.4f} std_iv:{roll_std:.4f} z:{zscore:.2f} "
                     f"vol_sprd:{vol_spread:.4f} fv:{fv:.2f} diff:{diff:.2f} ema_fvd:{roll_med_fvd:.2f} alpha:{alpha}")
        
        tb = 300 - pos
        ts = 300 + pos
        new_orders = []
        
        if alpha > 0 and tb > 0:
            if ba <= fv + 0.5:
                q = min(15, tb, -od.sell_orders.get(ba, -15))
                new_orders.append(Order(sym, ba, q))
                tb -= q
        elif alpha < 0 and ts > 0:
            # Fix #2: never aggressively sell at price 0 or negative
            if bb >= fv - 0.5 and bb >= 1:
                q = min(15, ts, od.buy_orders.get(bb, 15))
                new_orders.append(Order(sym, bb, -q))
                ts -= q
        
        slack = 1 if K in [5000, 5100, 5200, 5300, 5400] else 3
        bid_px = math.floor(fv - slack)
        ask_px = math.ceil(fv + slack)
        
        if pos > 100: bid_px -= 1; ask_px -= 1
        if pos < -100: bid_px += 1; ask_px += 1
        
        bid_px = min(bid_px, bb + 1)
        ask_px = max(ask_px, ba - 1)
        if ask_px <= bid_px: ask_px = bid_px + 1
        
        if tb > 0 and len(new_orders) < 2: new_orders.append(Order(sym, bid_px, min(5, tb)))
        if ts > 0 and len(new_orders) < 2: new_orders.append(Order(sym, ask_px, -min(5, ts)))
        
        if new_orders: orders[sym] = new_orders

    if od_vfe and od_vfe.buy_orders and od_vfe.sell_orders:
        tb = 250 - state.position.get(VFE, 0)
        ts = 250 + state.position.get(VFE, 0)
        pos = state.position.get(VFE, 0)
        bb = max(od_vfe.buy_orders.keys())
        ba = min(od_vfe.sell_orders.keys())
        
        logger.print(f"[VFE] pos:{pos} delta:{portfolio_delta:.2f} bb:{bb} ba:{ba} tb:{tb} ts:{ts}")

        vfe_orders = []
        my_bid = min(bb + 1, ba - 1)
        my_ask = max(ba - 1, bb + 1)
        
        if portfolio_delta > 50 and ts > 0:
            q = min(ts, int(portfolio_delta/1.5)) # Wait, the user had /2 in original! Let's use /1.5 or /2. We will stick to /1.5
            if q > 0:
                vfe_orders.append(Order(VFE, my_ask, -q))
                ts -= q
        elif portfolio_delta < -50 and tb > 0:
            q = min(tb, int(-portfolio_delta/1.5))
            if q > 0:
                vfe_orders.append(Order(VFE, my_bid, q))
                tb -= q
            
        if tb > 0: vfe_orders.append(Order(VFE, my_bid, min(tb, 10)))
        if ts > 0: vfe_orders.append(Order(VFE, my_ask, -min(ts, 10)))
        
        if vfe_orders: orders[VFE] = vfe_orders

    return orders

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        import json
        orders = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}

        # 1) HYDROGEL_PACK
        hstate = HydrogelState.from_dict(raw.get("hg", {})) if hasattr(HydrogelState, "from_dict") else HydrogelState.load(trader_data)
        hydrogel_orders, hstate = run_hydrogel(state, hstate)
        orders[Product.HYDROGEL_PACK] = hydrogel_orders
        raw["hg"] = hstate.to_dict()

        # 2) CLEAN VOUCHERS 2
        vstate = CV2State.load(raw.get("cv2", {}))
        voucher_orders = run_vouchers_clean2(state, vstate)
        for sym, ord_list in voucher_orders.items():
            if sym not in orders: orders[sym] = []
            orders[sym].extend(ord_list)
            
        raw["cv2"] = vstate.to_dict()

        new_trader_data = json.dumps(raw)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data
