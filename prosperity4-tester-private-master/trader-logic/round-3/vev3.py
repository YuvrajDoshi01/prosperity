"""
Round 3 VEV-only strategy (VEV_4000 signal -> VELVETFRUIT_EXTRACT execution).

Readable parameter taxonomy:
- ALPHA hardcodes: entry/exit hypotheses backed by diagnostics.
- INTRINSIC constants: market structure assumptions (limits/targets).
- DYNAMIC knobs: rolling windows and intraday timing guards.
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


LOG_SYMBOLS = {Product.VELVETFRUIT_EXTRACT, Product.VEV_4000}


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
        filtered_listings = [
            l for l in state.listings.values() if l.symbol in LOG_SYMBOLS
        ]
        filtered_depths = {
            s: [od.buy_orders, od.sell_orders]
            for s, od in state.order_depths.items()
            if s in LOG_SYMBOLS
        }
        filtered_positions = {
            s: p for s, p in state.position.items() if s in LOG_SYMBOLS
        }

        return [
            state.timestamp,
            state.traderData,
            [[l.symbol, l.product, l.denomination] for l in filtered_listings],
            filtered_depths,
            self._compress_trades(state.own_trades),
            self._compress_trades(state.market_trades),
            filtered_positions,
            self._compress_observations(state.observations),
        ]

    def _compress_trades(self, trades):
        return [
            [t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
            for arr in trades.values()
            for t in arr
            if t.symbol in LOG_SYMBOLS
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


# ═════════════════════════════════════════════════════════════════════════════
# VEV strategy
# ═════════════════════════════════════════════════════════════════════════════

class VEVParams:
    # ========================= ALPHA hardcodes =========================
    # Entry hypothesis:
    # - spread=22 cluster marks local richness in VEV_4000
    # - require top-quantile price gate to reduce false positives
    S22_CLUSTER_MIN = 3
    PEAK_WINDOW = 300
    PEAK_Q = 0.75
    MIN_SIGNAL_WARMUP = 75

    # Exit hypothesis:
    # - bottom 8% of rolling 500-tick underlying window is a strong reversal
    #   signal; flip from short to long (+200).
    COVER_WINDOW = 500
    COVER_Q = 0.08
    MIN_COVER_WARMUP = 500

    # Profit/stale guards:
    # - TAKE_PROFIT: absolute short profit target in ticks
    # - STALE_*: if held long enough, allow a smaller profit exit to reduce
    #   inventory drag from stale positions.
    TAKE_PROFIT = 35.0
    STALE_TICKS = 500
    STALE_PROFIT = 15

    # ===================== DYNAMIC intraday knobs ======================
    # Timestamp in backtests runs roughly 0..999900 per day.
    # These guards reduce chance of carrying inventory into day-end.
    LATE_AGGRESSIVE_AFTER = 930_000
    LATE_PROFIT = 15
    FORCE_FLAT_AFTER = 970_000
    NO_ENTRY_AFTER = 950_000

    # ==================== INTRINSIC / structure ========================
    # Exchange/position structure assumptions.
    EXTRACT_LIMIT = 200
    SHORT_TARGET = -200
    LONG_TARGET = 200
    FLAT_TARGET = 0


class VEVState:
    def __init__(self):
        # Signal buffers.
        self.s22_consec: int = 0
        self.vev4k_buf: List[float] = []
        self.S_buf: List[float] = []

        # Position lifecycle flags.
        self.in_short: bool = False
        self.covering: bool = False
        self.cover_target: int = 0

        # Entry metadata for profit/age logic.
        self.entry_S_mid: Optional[float] = None
        self.entry_ts: Optional[int] = None

    def to_dict(self):
        return {
            "s22": self.s22_consec,
            "v4b": self.vev4k_buf,
            "sb": self.S_buf,
            "short": self.in_short,
            "cov": self.covering,
            "cov_tgt": self.cover_target,
            "entryS": self.entry_S_mid,
            "entryTs": self.entry_ts,
        }

    @staticmethod
    def from_dict(d):
        vs = VEVState()
        vs.s22_consec = d.get("s22", 0)
        vs.vev4k_buf = d.get("v4b", [])
        vs.S_buf = d.get("sb", [])
        vs.in_short = d.get("short", False)
        vs.covering = d.get("cov", False)
        vs.cover_target = d.get("cov_tgt", 0)
        vs.entry_S_mid = d.get("entryS")
        vs.entry_ts = d.get("entryTs")
        return vs

    @staticmethod
    def load(trader_data):
        if not trader_data:
            return VEVState()
        try:
            raw = json.loads(trader_data)
            return VEVState.from_dict(raw.get("vev", {}))
        except Exception:
            return VEVState()

    def save(self, trader_data):
        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}
        raw["vev"] = self.to_dict()
        return json.dumps(raw, separators=(",", ":"))


def _order_to_target(symbol: str, pos: int, target: int, bid: int, ask: int) -> List[Order]:
    """
    Move position toward target aggressively.
    If target > pos: buy at ask.
    If target < pos: sell at bid.
    """
    if target > pos:
        return [Order(symbol, ask, target - pos)]
    if target < pos:
        return [Order(symbol, bid, -(pos - target))]
    return []


def run_vev(state: TradingState, vstate: VEVState) -> Tuple[Dict[str, List[Order]], VEVState]:
    p = VEVParams
    out: Dict[str, List[Order]] = {}

    # ── Require underlying ────────────────────────────────────────
    if Product.VELVETFRUIT_EXTRACT not in state.order_depths:
        return out, vstate

    S_od = state.order_depths[Product.VELVETFRUIT_EXTRACT]
    S_bid, S_ask = _best_bid_ask(S_od)
    if S_bid is None or S_ask is None:
        return out, vstate

    S_mid = (S_bid + S_ask) / 2.0
    pos_S = state.position.get(Product.VELVETFRUIT_EXTRACT, 0)
    day_time = state.timestamp % 1_000_000

    # ── Require VEV_4000 signal ───────────────────────────────────
    if Product.VEV_4000 not in state.order_depths:
        return out, vstate

    v4_od = state.order_depths[Product.VEV_4000]
    v4_bid, v4_ask = _best_bid_ask(v4_od)
    if v4_bid is None or v4_ask is None:
        return out, vstate

    v4_spread = v4_ask - v4_bid
    v4_mid = (v4_bid + v4_ask) / 2.0

    # ── Update buffers ────────────────────────────────────────────
    vstate.vev4k_buf = _push(vstate.vev4k_buf, v4_mid, p.PEAK_WINDOW)
    vstate.S_buf = _push(vstate.S_buf, S_mid, p.COVER_WINDOW)

    if v4_spread == 22:
        vstate.s22_consec += 1
    else:
        vstate.s22_consec = 0

    peak_ready = len(vstate.vev4k_buf) >= p.MIN_SIGNAL_WARMUP
    cover_ready = len(vstate.S_buf) >= p.MIN_COVER_WARMUP

    peak_thresh = _quantile(vstate.vev4k_buf, p.PEAK_Q) if peak_ready else None
    cover_thresh = _quantile(vstate.S_buf, p.COVER_Q) if cover_ready else None

    # ── Active cover/flip phase ───────────────────────────────────
    # Once an exit target is chosen, keep executing toward that target.
    if vstate.covering:
        target = vstate.cover_target
        out[Product.VELVETFRUIT_EXTRACT] = _order_to_target(
            Product.VELVETFRUIT_EXTRACT,
            pos_S,
            target,
            S_bid,
            S_ask,
        )

        if pos_S == target:
            logger.print(f"VEV COVER COMPLETE: target={target} pos_S={pos_S}")
            vstate.covering = False
            vstate.cover_target = 0

            # If we flipped long from bottom, we are no longer in short.
            vstate.in_short = False
            vstate.entry_S_mid = None
            vstate.entry_ts = None

        return out, vstate

    # ── If currently short, manage exit/flip ──────────────────────
    # Exit priority:
    # 1) strong bottom flip to long
    # 2) take-profit to flat
    # 3) stale-profit to flat
    # 4) late-profit to flat
    # 5) force-flat near day-end
    if vstate.in_short:
        profit_ticks = 0.0
        held_ticks = 0

        if vstate.entry_S_mid is not None:
            profit_ticks = vstate.entry_S_mid - S_mid

        if vstate.entry_ts is not None:
            held_ticks = max(0, int((state.timestamp - vstate.entry_ts) // 100))

        bottom_cover = cover_ready and cover_thresh is not None and S_mid <= cover_thresh
        profit_cover = profit_ticks >= p.TAKE_PROFIT
        stale_cover = held_ticks >= p.STALE_TICKS and profit_ticks >= p.STALE_PROFIT
        late_profit_cover = day_time >= p.LATE_AGGRESSIVE_AFTER and profit_ticks >= p.LATE_PROFIT
        force_flat = day_time >= p.FORCE_FLAT_AFTER
        ct = f"{cover_thresh:.1f}" if cover_thresh is not None else "NA"

        if bottom_cover:
            # Strong bottom signal: flip all the way long.
            target = p.LONG_TARGET
            reason = "BOTTOM_FLIP_TO_LONG"
        elif profit_cover:
            target = p.FLAT_TARGET
            reason = "TAKE_PROFIT_FLAT"
        elif stale_cover:
            target = p.FLAT_TARGET
            reason = "STALE_PROFIT_FLAT"
        elif late_profit_cover:
            target = p.FLAT_TARGET
            reason = "LATE_PROFIT_FLAT"
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

            out[Product.VELVETFRUIT_EXTRACT] = _order_to_target(
                Product.VELVETFRUIT_EXTRACT,
                pos_S,
                target,
                S_bid,
                S_ask,
            )

            logger.print(
                f"VEV COVER START {reason}: "
                f"S={S_mid:.1f} entry={vstate.entry_S_mid} "
                f"profit={profit_ticks:.1f} held={held_ticks} "
                f"day_time={day_time} target={target} pos_S={pos_S} "
                f"cover_thresh={ct}"
            )
            return out, vstate

        # Keep building short toward -200.
        out[Product.VELVETFRUIT_EXTRACT] = _order_to_target(
            Product.VELVETFRUIT_EXTRACT,
            pos_S,
            p.SHORT_TARGET,
            S_bid,
            S_ask,
        )

        logger.print(
            f"VEV SHORT BUILD: "
            f"s22={vstate.s22_consec} pos_S={pos_S} "
            f"S={S_mid:.1f} entry={vstate.entry_S_mid} "
            f"profit={profit_ticks:.1f} held={held_ticks} "
            f"cover_thresh={ct}"
        )
        return out, vstate

    # ── Entry: VEV_4000 spread cluster + top gate ─────────────────
    # VEV_4000 is signal-only: all execution is in VELVETFRUIT_EXTRACT.
    signal = (
        peak_ready
        and vstate.s22_consec >= p.S22_CLUSTER_MIN
        and peak_thresh is not None
        and v4_mid >= peak_thresh
    )

    if signal and day_time < p.NO_ENTRY_AFTER:
        vstate.in_short = True
        vstate.covering = False
        vstate.cover_target = 0
        vstate.entry_S_mid = S_mid
        vstate.entry_ts = state.timestamp

        out[Product.VELVETFRUIT_EXTRACT] = _order_to_target(
            Product.VELVETFRUIT_EXTRACT,
            pos_S,
            p.SHORT_TARGET,
            S_bid,
            S_ask,
        )

        logger.print(
            f"VEV SHORT ENTER: "
            f"S={S_mid:.1f} target={p.SHORT_TARGET} pos_S={pos_S} "
            f"s22={vstate.s22_consec} "
            f"v4_mid={v4_mid:.1f} peak_thresh={peak_thresh:.1f} "
            f"v4_spread={v4_spread} day_time={day_time}"
        )
        return out, vstate

    # If we are long from a bottom flip and the peak signal appears,
    # the entry block above will sell from +200 to -200.
    # That is intentional: max swing capture.

    return out, vstate


# ═════════════════════════════════════════════════════════════════════════════
# Trader
# ═════════════════════════════════════════════════════════════════════════════

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orders = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        vstate = VEVState.load(trader_data)
        vev_orders, vstate = run_vev(state, vstate)

        for sym, sym_orders in vev_orders.items():
            orders[sym] = sym_orders

        trader_data = vstate.save(trader_data)

        logger.flush(state, orders, conversions, trader_data)
        return orders, conversions, trader_data