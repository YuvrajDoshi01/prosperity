"""r3_voucher_v22_improvement.py — Voucher-only improvements over v22.

HP: NO-OP (stub). HP logic lives in r3_hp_v22_improved.py — will be combined later.

Voucher improvements over v22 baseline:
  1. VEV_5000: Dedicated wide-spread MM (size 30, cap +-200, inventory skew)
  2. OTM passive bids scaled up: 5300 size=20/cap=200, 5400 size=20/cap=250, 5500 size=20/cap=300
  3. Spread=1 fix: post at best_bid (not best_bid+1) when spread==1 on OTM strikes
  4. Per-strike BS edges: 5300=4, 5400=3, 5500=2 (was uniform 10)
  5. Add VEV_5500 to BS taking strikes
  6. VEV_6000/6500: "Free options" — passive bid at 0 to accumulate (mark-to-mid +0.5/contract)
  7. VEV_4000/4500: Deep ITM cap increased 100→200

Unchanged from v22:
  - VFE Wall-Mid MM + Layer E
  - Intrinsic arb on all strikes
  - Deep ITM theta carry MM (4000/4500) — strategy near-optimal, only cap raised
  - Call-spread arb scanner
  - Generic passive MM on [5100, 5200, 5300, 5400] (5000 removed — dedicated layer)
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


def _clip(value, lo, hi):
    return max(lo, min(hi, value))


# ══════════════════════════════════════════════════════════════════════════════
# VFE / Voucher strategy — IMPROVED from v22
# ══════════════════════════════════════════════════════════════════════════════

VEVE_SYM = "VELVETFRUIT_EXTRACT"
VOUCHER_STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
# CHANGE 1: Removed 5000 from TRADEABLE — dedicated wide-spread MM layer handles it
VOUCHER_STRIKES_TRADEABLE = [5100, 5200, 5300, 5400]
VOUCHER_STRIKES_DEEP_ITM = [4000, 4500]
VOUCHER_STRIKES_SKIP = set()  # v22 skipped 6000/6500; now traded via free OTM layer
VOUCHER_STRIKES_FREE_OTM = [6000, 6500]  # bid=0, ask=1, 100% taker sells at 0
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
V_BS_TRADE_SIZE = 30
V_BS_POS_CAP = 200  # 300 over-accumulates on OTM; 200 is the sweet spot
# CHANGE 4: Per-strike BS edges (was uniform V_BS_EDGE=10)
V_BS_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]  # CHANGE 5: added 5500
V_BS_EDGE_MAP = {
    5000: 10, 5100: 10, 5200: 10,
    5300: 4,   # was 10 — mid~47, edge=10 never fires; edge=4 → buy below 43
    5400: 3,   # was 10 — mid~16, edge=10 never fires; edge=3 → buy below 13
    5500: 2,   # NEW — mid~6, edge=2 → buy below 4 (fires on dips)
}
V_IV_ADAPT_WINDOW = 50
V_IV_ADAPT_MIN_HIST = 15

# CHANGE 1: VEV_5000 dedicated wide-spread MM params
V_5000_MM_SIZE = 30
V_5000_POS_CAP = 300
V_5000_SKEW_THRESH = 120  # start inventory skew when |pos| > this

# CHANGE 2+3: OTM passive bid params (was: size=5, cap=50, edge=2 for all)
OTM_BID_PARAMS = {
    5300: {"size": 20, "cap": 200, "edge": 1},  # 300 collapsed day2; 200 tested best
    5400: {"size": 20, "cap": 250, "edge": 1},  # 300 hurt; 250 gave +1553 vs +1103
    5500: {"size": 20, "cap": 300, "edge": 1},  # marginal, keep 300
}


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

    # ── VFE: Wall-Mid MM + Layer E (UNCHANGED from v22) ──────────────────────
    od_ve = state.order_depths.get(VEVE_SYM)
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
            if spread_ve == 2 and ba_ve < vstate.prev_ve_ap1:
                room_buy = E_POS_CAP - pos_ve
                q = min(E_SIZE, room_buy)
                if q > 0:
                    px = int(ba_ve - 1)
                    if px > bb_ve and px < ba_ve:
                        ve_layer_e.append(Order(VEVE_SYM, px, q))
                        layer_e_buy = q
            elif spread_ve == 3 and bb_ve > vstate.prev_ve_bp1:
                room_sell = E_POS_CAP + pos_ve
                q = min(E_SIZE, room_sell)
                if q > 0:
                    px = int(bb_ve + 1)
                    if px > bb_ve and px < ba_ve:
                        ve_layer_e.append(Order(VEVE_SYM, px, -q))
                        layer_e_sell = q
        vstate.prev_ve_ap1 = ba_ve
        vstate.prev_ve_bp1 = bb_ve

    if od_ve and od_ve.buy_orders and od_ve.sell_orders:
        wm = v_wall_mid(od_ve)
        if wm is not None:
            bb = max(od_ve.buy_orders); ba = min(od_ve.sell_orders)
            pos = state.position.get(VEVE_SYM, 0)
            fv = round(wm)
            tb = 200 - pos - layer_e_buy
            ts = 200 + pos - layer_e_sell
            half = 100
            mbp = fv - 1 if pos > half else fv
            msp = fv + 1 if pos < -half else fv
            ve_orders = list(ve_layer_e)
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

    # ── Spot for BS pricing ──────────────────────────────────────────────────
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

    # ── IV history update ────────────────────────────────────────────────────
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

    # ── Intrinsic arb (UNCHANGED) ───────────────────────────────────────────
    for K in VOUCHER_STRIKES_ALL:
        if K in VOUCHER_STRIKES_SKIP: continue
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

    # ── BS taking — CHANGE 4: per-strike edges ──────────────────────────────
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
        bs_edge = V_BS_EDGE_MAP.get(K, 10.0)  # CHANGE: per-strike edge
        buy_thr = fv_bs - bs_edge
        sell_thr_bs = fv_bs + bs_edge
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

    # ── Call-spread arb (UNCHANGED) ──────────────────────────────────────────
    committed_buy = {sym: 0 for sym in VOUCHER_SYM.values()}
    committed_sell = {sym: 0 for sym in VOUCHER_SYM.values()}
    for sym, ord_list in orders.items():
        if sym in committed_buy:
            committed_buy[sym] = sum(o.quantity for o in ord_list if o.quantity > 0)
            committed_sell[sym] = sum(-o.quantity for o in ord_list if o.quantity < 0)
    for K_lo, K_hi in itertools.combinations(VOUCHER_STRIKES_ALL, 2):
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

    # ── Generic passive MM on ATM strikes (5000 REMOVED — dedicated layer) ──
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

    # ── CHANGE 1: VEV_5000 dedicated wide-spread MM ─────────────────────────
    # spread=6 (99%), zero taker flow, perfect for aggressive inside-spread MM.
    # Size 30 (was 20 in generic), cap +-150, inventory skew at |pos|>80.
    sym_5k = VOUCHER_SYM[5000]
    od_5k = state.order_depths.get(sym_5k)
    if od_5k and od_5k.buy_orders and od_5k.sell_orders:
        vbb = max(od_5k.buy_orders); vba = min(od_5k.sell_orders)
        v_spread = vba - vbb
        if v_spread >= 3:  # only MM when spread is wide enough (5000 always has 6)
            pos_v = state.position.get(sym_5k, 0)
            existing = orders.get(sym_5k, [])
            existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
            existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)

            # Inventory skew: widen the side we're overweight on
            bid_widen = 1 if pos_v > V_5000_SKEW_THRESH else 0
            ask_widen = 1 if pos_v < -V_5000_SKEW_THRESH else 0

            bid_px = vbb + 1 + bid_widen   # at spread=6: bb+1 or bb+2 if long-heavy
            ask_px = vba - 1 - ask_widen    # at spread=6: ba-1 or ba-2 if short-heavy

            # Safety: ensure bid < ask and both inside spread
            if bid_px >= ask_px:
                bid_px = vbb + 1
                ask_px = vba - 1
            if bid_px <= vbb: bid_px = vbb + 1
            if ask_px >= vba: ask_px = vba - 1

            room_buy = V_5000_POS_CAP - pos_v - existing_buy
            room_sell = V_5000_POS_CAP + pos_v - existing_sell
            # Also respect hard limit of 300
            room_buy = min(room_buy, 300 - pos_v - existing_buy)
            room_sell = min(room_sell, 300 + pos_v - existing_sell)

            if room_buy > 0 and bid_px < ask_px:
                qty = min(V_5000_MM_SIZE, room_buy)
                orders.setdefault(sym_5k, []).append(Order(sym_5k, bid_px, qty))
            if room_sell > 0 and ask_px > bid_px:
                qty = min(V_5000_MM_SIZE, room_sell)
                orders.setdefault(sym_5k, []).append(Order(sym_5k, ask_px, -qty))

    # ── Deep ITM theta carry MM (UNCHANGED) ─────────────────────────────────
    DEEP_ITM_MM_SIZE    = 30
    DEEP_ITM_POS_CAP    = 300
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

    # ── CHANGE 2+3: Scaled OTM passive bids with spread=1 fix ───────────────
    # v22: size=5, cap=50, edge=2, skips spread=1 (57-67% of ticks on 5400).
    # Now: per-strike size/cap, edge=1, and post at bb (not bb+1) when spread=1.
    for K in VOUCHER_STRIKES_OTM_PASSIVE:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        bb = max(od_v.buy_orders)
        ba = min(od_v.sell_orders)
        v_spread = ba - bb

        params = OTM_BID_PARAMS.get(K, {"size": 5, "cap": 50, "edge": 2})
        fv_bs = v_bs_call(spot, K, T, sigma)
        bs_cap = math.floor(fv_bs - params["edge"])

        # CHANGE 3: spread=1 fix — post at bb instead of bb+1
        if v_spread == 1:
            # At spread=1, bb+1 == ba (crosses). Post at bb to compete with MM bot.
            # Taker sells AT the bid, so we get filled at our price.
            bid_px = min(bb, bs_cap)
        else:
            # spread >= 2: post at bb+1 for queue priority (inside spread)
            bid_px = min(bb + 1, bs_cap)

        if bid_px <= 0: continue
        if bid_px >= ba: continue  # must not cross ask

        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        tb_v = params["cap"] - pos_v - existing_buy
        # Also respect hard limit
        tb_v = min(tb_v, 300 - pos_v - existing_buy)
        if tb_v > 0:
            q = min(tb_v, params["size"])
            orders.setdefault(sym, []).append(Order(sym, bid_px, q))

    # ── CHANGE 6: Free OTM passive bids on VEV_6000/6500 ───────────────────
    # Book: constant bid=0, ask=1, mid=0.5. Taker sells ~320 vol/day at 0.
    # Buy at 0, mark-to-mid = +0.5/contract. Zero risk (cost=0).
    FREE_OTM_BID_SIZE = 50
    FREE_OTM_POS_CAP = 300
    for K in VOUCHER_STRIKES_FREE_OTM:
        sym = VOUCHER_SYM[K]
        od_v = state.order_depths.get(sym)
        if od_v is None or not od_v.buy_orders or not od_v.sell_orders: continue
        bb = max(od_v.buy_orders)
        ba = min(od_v.sell_orders)
        # Only act when book is the expected constant pattern (bid=0, ask=1)
        if bb > 1 or ba > 2: continue  # safety: skip if book is unusual
        pos_v = state.position.get(sym, 0)
        existing = orders.get(sym, [])
        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        room = min(FREE_OTM_POS_CAP - pos_v - existing_buy,
                    300 - pos_v - existing_buy)
        if room > 0:
            q = min(FREE_OTM_BID_SIZE, room)
            # Post at bb (0) — taker sells at bid, we get filled pro-rata with bot
            orders.setdefault(sym, []).append(Order(sym, bb, q))

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

        # HP: NO-OP stub — HP logic will come from r3_hp_v22_improved.py
        # (orders[HYDROGEL_PACK] stays empty)

        vstate = VoucherState.from_dict(raw.get("v9", {}))
        voucher_orders = run_vouchers(state, vstate)
        for sym, ord_list in voucher_orders.items():
            if sym not in orders: orders[sym] = []
            orders[sym].extend(ord_list)
        raw["v9"] = vstate.to_dict()

        new_trader_data = json.dumps(raw)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data
