"""
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

import json
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Observation, Order, ProsperityEncoder, Symbol, Trade, TradingState


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


class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orders      = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        hstate = HydrogelState.load(trader_data)
        hydrogel_orders, hstate = run_hydrogel(state, hstate)
        orders[Product.HYDROGEL_PACK] = hydrogel_orders
        trader_data = hstate.save(trader_data)

        logger.flush(state, orders, conversions, trader_data)
        return orders, conversions, trader_data