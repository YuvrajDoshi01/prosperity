"""r3_ve_v22_improved.py — Multi-strike entry signals + vev3 proven exits.

Improvement over vev3.py:
  Entry A (vev3 original): VEV_4000 spread=22 consec>=3, v4_mid >= Q75
  Entry B (NEW): VEV_5200 spread=4 consec>=3, v52_mid >= Q75
     Best single signal: -11.73 mean@200, 87.5% hit at consec>=3
  Entry C (NEW): ensemble 2+ of {4000,4500,5000,5200} widening consec>=3
     + VFE above trailing 100-tick avg (peak gate)

  Exits: IDENTICAL to vev3 (quantile bottom flip, take profit, stale, late, force flat)
  Added: trailing stop (activate at +20 profit, exit if drops 15 below peak)

Trades ONLY VELVETFRUIT_EXTRACT. Voucher books are read-only signals.

Baseline: vev3.py = $67,054 10k 3-day, $5,161 1k day2.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, ProsperityEncoder, Symbol, TradingState


# ─────────────────────────────────────────────────────────────────────────────
# Products
# ─────────────────────────────────────────────────────────────────────────────

class Product:
    VELVETFRUIT_EXTRACT = "VELVETFRUIT_EXTRACT"
    VEV_4000 = "VEV_4000"
    VEV_4500 = "VEV_4500"
    VEV_5000 = "VEV_5000"
    VEV_5200 = "VEV_5200"


# ─────────────────────────────────────────────────────────────────────────────
# Logger
# ─────────────────────────────────────────────────────────────────────────────

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
                cc[product] = [
                    getattr(obs, "bidPrice", None),
                    getattr(obs, "askPrice", None),
                    getattr(obs, "transportFees", None),
                    getattr(obs, "exportTariff", None),
                    getattr(obs, "importTariff", None),
                    getattr(obs, "sugarPrice", None),
                    getattr(obs, "sunlightIndex", None),
                    getattr(obs, "humidity", None),
                ]
        return [
            getattr(observations, "plainValueObservations", {}) if observations else {},
            cc,
        ]


logger = Logger()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _push(buf, value, maxlen):
    buf = buf + [value]
    return buf[-maxlen:] if len(buf) > maxlen else buf


def _quantile(buf, q):
    if not buf:
        return None
    s = sorted(buf)
    idx = int(len(s) * q)
    return s[min(idx, len(s) - 1)]


def _best_bid_ask(order_depth):
    bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
    ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
    return bid, ask


def _get_spread(state, symbol):
    od = state.order_depths.get(symbol)
    if od is None or not od.buy_orders or not od.sell_orders:
        return None
    return min(od.sell_orders) - max(od.buy_orders)


def _get_mid(state, symbol):
    od = state.order_depths.get(symbol)
    if od is None or not od.buy_orders or not od.sell_orders:
        return None
    return (max(od.buy_orders) + min(od.sell_orders)) / 2.0


# ═════════════════════════════════════════════════════════════════════════════
# Strategy
# ═════════════════════════════════════════════════════════════════════════════

# Spread thresholds from analysis
WIDEN_THRESHOLDS = {
    "VEV_4000": 22,   # mode=21, widen at 22
    "VEV_4500": 17,   # mode=16, widen at 17
    "VEV_5000": 7,    # mode=6,  widen at 7
    "VEV_5200": 4,    # mode=3,  widen at 4
}


class VEParams:
    # ========================= ENTRY — Signal A (vev3 original) ============
    # VEV_4000 spread=22 cluster + peak quantile gate
    S22_CLUSTER_MIN = 3
    PEAK_WINDOW = 300
    PEAK_Q = 0.75
    MIN_SIGNAL_WARMUP = 75

    # ========================= ENTRY — Signal B (VEV_4500 — 96% unique vs A)
    V4500_CLUSTER_MIN = 99       # DISABLED — fires at bad times like B2
    V4500_PEAK_WINDOW = 300
    V4500_PEAK_Q = 0.75

    # ========================= ENTRY — Signal B2 (VEV_5200 — DISABLED) ====
    V5200_CLUSTER_MIN = 99       # disabled — fires at bad times
    V5200_PEAK_WINDOW = 300
    V5200_PEAK_Q = 0.75

    # ========================= ENTRY — Signal C (DISABLED) =================
    # Ensemble causes rapid cycling — dropped.
    ENSEMBLE_MIN_WIDE = 99       # effectively disabled
    ENSEMBLE_CONSEC_MIN = 99
    ENSEMBLE_PEAK_WINDOW = 100

    # ========================= EXIT (identical to vev3) ====================
    COVER_WINDOW = 500
    COVER_Q = 0.08
    MIN_COVER_WARMUP = 500
    TAKE_PROFIT = 35.0
    STALE_TICKS = 500
    STALE_PROFIT = 15

    # ========================= EXIT — Trailing stop (NEW) ==================
    TRAIL_ACTIVATE = 999.0       # DISABLED — testing entry-only improvements
    TRAIL_DELTA = 15.0           # exit if profit drops 15 below peak

    # ========================= INTRADAY GUARDS (identical to vev3) =========
    LATE_AGGRESSIVE_AFTER = 930_000
    LATE_PROFIT = 15
    FORCE_FLAT_AFTER = 970_000
    NO_ENTRY_AFTER = 950_000

    # ========================= POSITION ====================================
    EXTRACT_LIMIT = 200
    SHORT_TARGET = -200
    LONG_TARGET = 200
    FLAT_TARGET = 0


class VEState:
    def __init__(self):
        # Signal A: VEV_4000 (from vev3)
        self.s22_consec: int = 0
        self.vev4k_buf: List[float] = []

        # Signal B: VEV_4500
        self.v45_consec: int = 0
        self.vev45_buf: List[float] = []

        # Signal B2: VEV_5200 (disabled)
        self.v5200_consec: int = 0
        self.vev52_buf: List[float] = []

        # Signal C: ensemble (disabled)
        self.ens_consec: int = 0

        # VFE buffer (for cover quantile + ensemble peak gate)
        self.S_buf: List[float] = []

        # Position lifecycle (from vev3)
        self.in_short: bool = False
        self.covering: bool = False
        self.cover_target: int = 0
        self.entry_S_mid: Optional[float] = None
        self.entry_ts: Optional[int] = None

        # Trailing stop
        self.peak_profit: float = 0.0

    def to_dict(self):
        return {
            "s22": self.s22_consec,
            "v4b": self.vev4k_buf,
            "v45c": self.v45_consec,
            "v45b": self.vev45_buf,
            "v52c": self.v5200_consec,
            "v52b": self.vev52_buf,
            "ec": self.ens_consec,
            "sb": self.S_buf,
            "short": self.in_short,
            "cov": self.covering,
            "cov_tgt": self.cover_target,
            "entryS": self.entry_S_mid,
            "entryTs": self.entry_ts,
            "pkp": self.peak_profit,
        }

    @staticmethod
    def from_dict(d):
        vs = VEState()
        vs.s22_consec = d.get("s22", 0)
        vs.vev4k_buf = d.get("v4b", [])
        vs.v45_consec = d.get("v45c", 0)
        vs.vev45_buf = d.get("v45b", [])
        vs.v5200_consec = d.get("v52c", 0)
        vs.vev52_buf = d.get("v52b", [])
        vs.ens_consec = d.get("ec", 0)
        vs.S_buf = d.get("sb", [])
        vs.in_short = d.get("short", False)
        vs.covering = d.get("cov", False)
        vs.cover_target = d.get("cov_tgt", 0)
        vs.entry_S_mid = d.get("entryS")
        vs.entry_ts = d.get("entryTs")
        vs.peak_profit = d.get("pkp", 0.0)
        return vs

    @staticmethod
    def load(trader_data):
        if not trader_data:
            return VEState()
        try:
            raw = json.loads(trader_data)
            return VEState.from_dict(raw.get("ve2", {}))
        except Exception:
            return VEState()

    def save(self, trader_data):
        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}
        raw["ve2"] = self.to_dict()
        return json.dumps(raw, separators=(",", ":"))


def _order_to_target(symbol, pos, target, bid, ask):
    if target > pos:
        return [Order(symbol, ask, target - pos)]
    if target < pos:
        return [Order(symbol, bid, -(pos - target))]
    return []


def run_ve(state: TradingState, vstate: VEState):
    p = VEParams
    out: Dict[str, List[Order]] = {}
    VFE = Product.VELVETFRUIT_EXTRACT

    # ── Require underlying ────────────────────────────────────────────────
    if VFE not in state.order_depths:
        return out, vstate

    S_od = state.order_depths[VFE]
    S_bid, S_ask = _best_bid_ask(S_od)
    if S_bid is None or S_ask is None:
        return out, vstate

    S_mid = (S_bid + S_ask) / 2.0
    pos_S = state.position.get(VFE, 0)
    day_time = state.timestamp % 1_000_000

    # ── Update VFE buffer ─────────────────────────────────────────────────
    vstate.S_buf = _push(vstate.S_buf, S_mid, p.COVER_WINDOW)

    # ── Signal A: VEV_4000 spread=22 (vev3 original) ─────────────────────
    v4_spread = _get_spread(state, "VEV_4000")
    v4_mid = _get_mid(state, "VEV_4000")

    if v4_mid is not None:
        vstate.vev4k_buf = _push(vstate.vev4k_buf, v4_mid, p.PEAK_WINDOW)

    if v4_spread is not None and v4_spread == 22:
        vstate.s22_consec += 1
    else:
        vstate.s22_consec = 0

    v4_peak_ready = len(vstate.vev4k_buf) >= p.MIN_SIGNAL_WARMUP
    v4_peak_thresh = _quantile(vstate.vev4k_buf, p.PEAK_Q) if v4_peak_ready else None

    signal_A = (
        v4_peak_ready
        and vstate.s22_consec >= p.S22_CLUSTER_MIN
        and v4_peak_thresh is not None
        and v4_mid is not None
        and v4_mid >= v4_peak_thresh
    )

    # ── Signal B: VEV_4500 spread=17 (96% unique vs A, same quality) ─────
    v45_spread = _get_spread(state, "VEV_4500")
    v45_mid = _get_mid(state, "VEV_4500")

    if v45_mid is not None:
        vstate.vev45_buf = _push(vstate.vev45_buf, v45_mid, p.V4500_PEAK_WINDOW)

    if v45_spread is not None and v45_spread >= 17:
        vstate.v45_consec += 1
    else:
        vstate.v45_consec = 0

    v45_peak_ready = len(vstate.vev45_buf) >= p.MIN_SIGNAL_WARMUP
    v45_peak_thresh = _quantile(vstate.vev45_buf, p.V4500_PEAK_Q) if v45_peak_ready else None

    signal_B = (
        v45_peak_ready
        and vstate.v45_consec >= p.V4500_CLUSTER_MIN
        and v45_peak_thresh is not None
        and v45_mid is not None
        and v45_mid >= v45_peak_thresh
    )

    # ── Signal B2: VEV_5200 spread=4 (DISABLED) ──────────────────────────
    v52_spread = _get_spread(state, "VEV_5200")
    v52_mid = _get_mid(state, "VEV_5200")

    if v52_mid is not None:
        vstate.vev52_buf = _push(vstate.vev52_buf, v52_mid, p.V5200_PEAK_WINDOW)

    if v52_spread is not None and v52_spread >= 4:
        vstate.v5200_consec += 1
    else:
        vstate.v5200_consec = 0

    v52_peak_ready = len(vstate.vev52_buf) >= p.MIN_SIGNAL_WARMUP
    v52_peak_thresh = _quantile(vstate.vev52_buf, p.V5200_PEAK_Q) if v52_peak_ready else None

    signal_B2 = (
        v52_peak_ready
        and vstate.v5200_consec >= p.V5200_CLUSTER_MIN
        and v52_peak_thresh is not None
        and v52_mid is not None
        and v52_mid >= v52_peak_thresh
    )

    # ── Signal C: ensemble (2+ strikes widening) ──────────────────────────
    widen_count = 0
    for sym, thresh in WIDEN_THRESHOLDS.items():
        spread = _get_spread(state, sym)
        if spread is not None and spread >= thresh:
            widen_count += 1

    if widen_count >= p.ENSEMBLE_MIN_WIDE:
        vstate.ens_consec += 1
    else:
        vstate.ens_consec = 0

    # Ensemble peak gate: VFE above trailing avg
    ens_above_avg = False
    if len(vstate.S_buf) >= p.ENSEMBLE_PEAK_WINDOW:
        trailing_avg = sum(vstate.S_buf[-p.ENSEMBLE_PEAK_WINDOW:]) / p.ENSEMBLE_PEAK_WINDOW
        ens_above_avg = S_mid > trailing_avg

    signal_C = (
        len(vstate.S_buf) >= p.MIN_SIGNAL_WARMUP
        and vstate.ens_consec >= p.ENSEMBLE_CONSEC_MIN
        and ens_above_avg
    )

    # Combined entry
    any_signal = signal_A or signal_B or signal_C

    # Cover quantile (vev3 exit)
    cover_ready = len(vstate.S_buf) >= p.MIN_COVER_WARMUP
    cover_thresh = _quantile(vstate.S_buf, p.COVER_Q) if cover_ready else None

    # ── Active cover/flip phase (from vev3) ───────────────────────────────
    if vstate.covering:
        target = vstate.cover_target
        out[VFE] = _order_to_target(VFE, pos_S, target, S_bid, S_ask)

        if pos_S == target:
            logger.print(f"VE COVER COMPLETE: target={target} pos={pos_S}")
            vstate.covering = False
            vstate.cover_target = 0
            vstate.in_short = False
            vstate.entry_S_mid = None
            vstate.entry_ts = None
            vstate.peak_profit = 0.0

        return out, vstate

    # ── Manage short position (vev3 exit logic + trailing stop) ───────────
    if vstate.in_short:
        profit_ticks = 0.0
        held_ticks = 0

        if vstate.entry_S_mid is not None:
            profit_ticks = vstate.entry_S_mid - S_mid

        if vstate.entry_ts is not None:
            held_ticks = max(0, int((state.timestamp - vstate.entry_ts) // 100))

        # Track peak profit
        if profit_ticks > vstate.peak_profit:
            vstate.peak_profit = profit_ticks

        # Exit conditions (vev3 priority + trailing stop)
        bottom_cover = (cover_ready and cover_thresh is not None
                        and S_mid <= cover_thresh)
        trail_stop = (vstate.peak_profit >= p.TRAIL_ACTIVATE
                      and profit_ticks < vstate.peak_profit - p.TRAIL_DELTA)
        profit_cover = profit_ticks >= p.TAKE_PROFIT
        stale_cover = held_ticks >= p.STALE_TICKS and profit_ticks >= p.STALE_PROFIT
        late_cover = (day_time >= p.LATE_AGGRESSIVE_AFTER
                      and profit_ticks >= p.LATE_PROFIT)
        force_flat = day_time >= p.FORCE_FLAT_AFTER

        ct = f"{cover_thresh:.1f}" if cover_thresh is not None else "NA"

        if bottom_cover:
            target = p.LONG_TARGET
            reason = "BOTTOM_FLIP_TO_LONG"
        elif trail_stop:
            target = p.FLAT_TARGET
            reason = f"TRAIL_STOP(peak={vstate.peak_profit:.1f})"
        elif profit_cover:
            target = p.FLAT_TARGET
            reason = "TAKE_PROFIT"
        elif stale_cover:
            target = p.FLAT_TARGET
            reason = "STALE_PROFIT"
        elif late_cover:
            target = p.FLAT_TARGET
            reason = "LATE_PROFIT"
        elif force_flat:
            target = p.FLAT_TARGET
            reason = "FORCE_FLAT"
        else:
            target = None
            reason = ""

        if target is not None:
            vstate.covering = True
            vstate.cover_target = target
            vstate.in_short = False

            out[VFE] = _order_to_target(VFE, pos_S, target, S_bid, S_ask)

            logger.print(
                f"VE EXIT {reason}: S={S_mid:.1f} entry={vstate.entry_S_mid} "
                f"profit={profit_ticks:.1f} held={held_ticks} "
                f"day={day_time} target={target} pos={pos_S} cover={ct}"
            )
            return out, vstate

        # Keep building short
        out[VFE] = _order_to_target(VFE, pos_S, p.SHORT_TARGET, S_bid, S_ask)

        logger.print(
            f"VE SHORT HOLD: pos={pos_S} S={S_mid:.1f} "
            f"profit={profit_ticks:.1f} peak={vstate.peak_profit:.1f} held={held_ticks}"
        )
        return out, vstate

    # ── Entry ─────────────────────────────────────────────────────────────
    if any_signal and day_time < p.NO_ENTRY_AFTER:
        vstate.in_short = True
        vstate.covering = False
        vstate.cover_target = 0
        vstate.entry_S_mid = S_mid
        vstate.entry_ts = state.timestamp
        vstate.peak_profit = 0.0

        out[VFE] = _order_to_target(VFE, pos_S, p.SHORT_TARGET, S_bid, S_ask)

        entry_type = "A_4000" if signal_A else ("B_4500" if signal_B else "C_ENS")
        logger.print(
            f"VE SHORT ENTER ({entry_type}): S={S_mid:.1f} "
            f"target={p.SHORT_TARGET} pos={pos_S} "
            f"s22c={vstate.s22_consec} v45c={vstate.v45_consec} "
            f"ens={widen_count}/ec={vstate.ens_consec} day={day_time}"
        )
        return out, vstate

    return out, vstate


# ═════════════════════════════════════════════════════════════════════════════
# Trader
# ═════════════════════════════════════════════════════════════════════════════

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orders = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        vstate = VEState.load(trader_data)
        ve_orders, vstate = run_ve(state, vstate)

        for sym, sym_orders in ve_orders.items():
            orders[sym] = sym_orders

        trader_data = vstate.save(trader_data)

        logger.flush(state, orders, conversions, trader_data)
        return orders, conversions, trader_data
