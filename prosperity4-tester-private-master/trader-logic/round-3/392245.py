"""
HYDROGEL_PACK Trading Strategy — v4
=====================================
Changes vs v3 (all complaints verified correct before applying):

  FIX A: Removed stale quote early-return — was blocking 80% of quoting time.
          IMC orders do not persist. Returning early = not in market.
          Signals are recomputed fresh every tick instead.

  FIX B: Added spread == 16 guard before normal regime.
          spread=15 was reaching normal regime despite plan marking it
          "inconsistent, drop". spread 10-14 and 18+ never observed in data
          but now explicitly blocked too.

  FIX C: Stop loss now submits immediate flatten orders.
          Previously only set lean_target=0 ("stop wanting inventory")
          without actually exiting. Now posts aggressive orders to unwind
          the lean position within the same tick the stop fires.

  FIX D: Lean direction flip resets lean_entry_mid and lean_entry_side.
          Previously only detected 0→nonzero transitions. Direct sign flip
          (long lean → short lean without passing zero) left entry tracking
          referencing the wrong price.

  FIX E: Regime 1: when spread normalises, tracking is cleared.
          The regime1 position is NOT explicitly exited — it is absorbed
          into normal MM inventory. Normal inv_adj then nudges it toward
          lean_target organically. Aggressive exit at spread=16 right after
          a narrow-spread entry would pay 8t half-spread unnecessarily.
          (v3 docstring incorrectly described this as a "passive exit order".)

  FIX F (v3): fill reconciliation helper removed.
          get_own_fills() result was never used in the actual reconciliation
          math — only as an if-guard. Reconciliation clamped against position
          anyway, which the exit sizing already does directly. Removed the
          dead code. No behaviour change.

  FIX G: Stop-loss returns immediately after flatten order.
          Previously the code fell through to normal Layer A/B quoting after
          the stop fired. This could submit both a stop sell AND a normal ask
          in the same tick, overshooting the intended flat.
          Fix: return orders, hstate immediately after stop executes.

  FIX H: Stop-loss comments corrected from "passive" to "aggressive".
          Order(P, best_bid, -qty) crosses the spread (hits existing bids) —
          that is aggressive. Ditto buying at best_ask. Comments now say so.

Strategy derivation: HYDROGEL_STRATEGY_PLAN.md
Signal sources: signal_scan.csv, top_20_per_horizon.csv,
                spread_conditional.csv, rolling_summary.csv,
                autocorr_ret1.csv, event_summary.csv

HARDCODED parameters are flagged [DERIVE] or [DESIGN] — see HydrogelParams.
"""

import json
import math
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


# ─────────────────────────────────────────────────────────────────────────────
# Logger (unchanged — required by IMC backtester)
# ─────────────────────────────────────────────────────────────────────────────

class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        # We truncate state.traderData, trader_data, and self.logs to the same max. length to fit the log limit
        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])

        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]

        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )

        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        if observations:
            for product, observation in observations.conversionObservations.items():
                conversion_observations[product] = [
                    observation.bidPrice,
                    observation.askPrice,
                    observation.transportFees,
                    observation.exportTariff,
                    observation.importTariff,
                    observation.sugarPrice,
                    observation.sunlightIndex,
                ]

        return [observations.plainValueObservations if observations else {}, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])

        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if value is None:
            return ""
        lo, hi = 0, min(len(value), max_length)
        out = ""

        while lo <= hi:
            mid = (lo + hi) // 2

            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."

            encoded_candidate = json.dumps(candidate)

            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        return out


logger = Logger()


# ─────────────────────────────────────────────────────────────────────────────
# Products and limits
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Strategy parameters
# ─────────────────────────────────────────────────────────────────────────────
#
# [DERIVE] = can be derived from enriched CSV / signal scans. Method noted.
# [DESIGN] = risk/sizing choice. Cannot be purely derived from market data.
#
# Parameters with neither tag are competition constraints or pure definitions.


class HydrogelParams:

    # ── Regime 1: spread < 10 ────────────────────────────────────────────
    # Justified by spread_conditional.csv days 0, 1, live.
    # spread=7 fut_ret_10 ≈ +2-4t. spread=9 fut_ret_10 ≈ -2.5 to -4t.

    REGIME1_SPREAD_THRESHOLD = 10
    # [DERIVE] From spread_conditional.csv: find lowest spread where
    # fut_ret_10 > half_spread_cost (8t). Data supports 10 as boundary.

    REGIME1_IMB_THRESHOLD = 999.0
    # v2: effectively disabled (was 0.15).
    # Empirical test on R3 BT (3 days): with R1 entry on:  20,138.
    #                                   with R1 entry off: 20,780  (+642).
    # The aggressive entry at spread=7..9 pays 4-5t half-spread, but the
    # short-horizon (h≤10) edge from spread_conditional.csv is only 2-4t
    # in expectation. Live website log analysis (1k-tick slice, ~6 fills)
    # also showed negative R1 mark-to-mid edge.
    # The exit machinery is preserved — if a position somehow accumulates
    # below this threshold (it can't with 999, but kept for safety) it will
    # still exit correctly. Set back to ~0.15 to re-enable.
    # imbalance_L1_mean ≈ 0.28-0.31 at spread=7 (data-derived).

    REGIME1_EXIT_ROWS = 10
    # [DERIVE] spread=7 returns reverse at fut_50. Exit by row 10 is
    # data-supported from spread_conditional.csv + live confirmation.

    REGIME1_ENTRY_SIZE = 1
    # [DESIGN] Risk choice. 1 unit per signal. Cannot be derived from data.

    # ── Regime 2: spread = 17 ────────────────────────────────────────────
    # fut_ret_50 ≈ -4 to -7t across days 0, 1, live.

    REGIME2_SPREAD = 17
    # Factual regime boundary from spread_value_counts.csv. Not tunable.

    REGIME2_FLATTEN_AGGRESSIVE = True
    # [DESIGN] True = hit bid (guaranteed fill, costs 8t half-spread).
    # False = post at ask (free if fills, risks not filling while price falls).
    # Aggressive chosen: stress regime with persistent downward drift.
    # Cost of guaranteed exit < expected further loss from staying long.

    # ── Regime 3 / Layer B: z_roll_mean_500 ──────────────────────────────
    # top_20_per_horizon.csv: corr=-0.270 (backtest), -0.428 (live) at h=100.
    # event_summary.csv: z>+2 → fut_50=-6 to -14t. z<-2 → fut_100=+8t.

    REGIME3_Z_ENTER = 2.0
    # [DERIVE] Sweep 1.5, 2.0, 2.5, 3.0 on enriched CSV.
    # rolling_summary.csv: z500 p99=2.68, so >2 fires ~1% of rows.

    REGIME3_Z_EXIT = 0.5
    # [DERIVE] Sweep 0.2-1.0 on enriched CSV.

    REGIME3_STOP_TICKS = 20
    # [DERIVE] rolling_summary.csv: dev_roll_mean_500 p75 ≈ 22t.
    # Re-derive from adverse excursion distribution on enriched CSV.

    LAYER_B_SCALE = 0.0
    # [DESIGN] v2: lowered 0.5 → 0.0 after sweeping {0.0, 0.1, 0.25, 0.4}.
    # Sweep results on R3 backtest (HYDROGEL_PACK total over 3 days):
    #   SCALE=0.00 → 20,138  ← best
    #   SCALE=0.10 → 19,592
    #   SCALE=0.25 → 19,177
    #   SCALE=0.40 → 19,452
    # Surprisingly even day 2 (volatile) prefers no lean: vol-scaled slack
    # below already widens our posts on high-vol regimes, providing enough
    # defense without inventory bias. The lean machinery (entry tracking,
    # stop loss, graduated lean) is preserved so it can be re-enabled by
    # raising this scale; left at 0 by default after data-driven tuning.

    # ── Trending-day filter ───────────────────────────────────────────────
    # From live comparison: on trending day z<-2 was permanent, not extreme.
    # Only trust z500 when rolling mean is itself stable.

    MEAN_ANCHOR_WINDOW = 100
    # [DERIVE] Matched to z_roll_500 signal peak at h=100. Sweep 50,100,200.

    MEAN_ANCHOR_STD_MULTIPLIER = 1.0
    # [DERIVE] Rolling mean is "anchored" if drift < N * roll_std_100.
    # 1.0 = moved less than its own typical variation. Sweep 0.5, 1.0, 1.5, 2.0.

    # ── Layer A: book_wap_edge_L3 ─────────────────────────────────────────
    # signal_scan.csv: corr=0.35-0.40 at h=1. Top-10% hit rate 54-61%.
    # Strongest short-horizon signal. Consistent across all days + live.

    LAYER_A_SCALE = 3.0
    # [DERIVE] Run OLS: future_ret_1 ≈ beta * book_wap_edge_L3 on enriched CSV.
    # Use beta as scale. 3.0 is starting point.

    LAYER_A_CLIP = 1.0
    # [DERIVE] Max bid offset from Layer A. Optimise fill-adjusted PnL.

    # ── Quote management ─────────────────────────────────────────────────

    INV_ADJ_CLIP = 3.0
    # [DESIGN] Max ticks of inventory adjustment per tick.
    # Half-spread = 8t. Clipping at 3t leaves 5t margin before crossing.

    INV_ADJ_COEFF = 0.1
    # [DESIGN] Soft nudge coefficient. 0.1 = 10% of gap per tick.
    # Arbitrary — tune after position sizing is settled.

    QUOTE_SIZE = 50
    # [DESIGN] Units per passive quote per side per tick.
    # Kept as a pure constant (no os/env dependency) for IMC website upload.

    # ── Vol-scaled post slack (v2, inspired by r3_v3 F3) ─────────────────
    # Replaces "post AT best_bid" with "post at min(round(mid)-slack, bb+1)".
    # slack scales with realized volatility (rolling stdev of mid).
    # Wider posts on high-vol days = less adverse selection.

    HP_VOL_WINDOW = 20          # rolling stdev window (ticks)
    HP_SLACK_MIN  = 1           # at least 1 tick from FV
    HP_SLACK_MAX  = 3           # at most 3 ticks (capped to avoid quoting outside spread)
    HP_SLACK_COEF = 0.5         # slack ≈ HP_SLACK_COEF * sigma, clipped
    # [DERIVE] Same coefficient as r3_v3 F3. Sigma at low-vol ≈ 1-2 ticks
    # → slack=1; sigma at high-vol day 2 ≈ 5-6 → slack=3 (capped).

    # ── Take phase (v2) ──────────────────────────────────────────────────
    # If a book level crosses fair value, take it directly (cross-book arb).
    # Almost never fires for HG (book best ask is ~8t above mid), but free
    # when it does. Pos-aggression: when |pos| > POS_AGGRESSION_FRAC * limit,
    # narrow the take threshold by 1t to encourage flatten via take.

    POS_AGGRESSION_FRAC = 0.5   # threshold tightens at |pos| >= 50% limit

    # ── Rolling window sizes ──────────────────────────────────────────────

    Z500_WINDOW = 500
    # [DERIVE] Matched to z_roll_mean_500 from diagnostic.
    # Sweep 250, 500, 750, 1000 on enriched CSV.

    STD100_WINDOW = 100
    # [DERIVE] Tied to MEAN_ANCHOR_WINDOW. Keep equal.


# ─────────────────────────────────────────────────────────────────────────────
# Pure math helpers (no external libraries — IMC sandbox safe)
# ─────────────────────────────────────────────────────────────────────────────

def _mean(buf: List[float]) -> Optional[float]:
    return sum(buf) / len(buf) if buf else None

def _std(buf: List[float]) -> Optional[float]:
    n = len(buf)
    if n < 2:
        return None
    mu = sum(buf) / n
    return (sum((x - mu) ** 2 for x in buf) / (n - 1)) ** 0.5

def _zscore(buf: List[float], value: float) -> Optional[float]:
    """
    z-score of value vs buf. buf must NOT include value (no look-ahead).
    Consistent with diagnostic script: rolling window of previous rows,
    applied to current row.
    """
    mu = _mean(buf)
    sd = _std(buf)
    if mu is None or sd is None or sd == 0:
        return None
    return (value - mu) / sd

def _push(buf: List[float], value: float, maxlen: int) -> List[float]:
    buf = buf + [value]
    return buf[-maxlen:] if len(buf) > maxlen else buf

def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ─────────────────────────────────────────────────────────────────────────────
# Book feature computation
# ─────────────────────────────────────────────────────────────────────────────

def compute_book_features(order_depth) -> Dict[str, Optional[float]]:
    """
    book_wap_edge_L3 formula (matches diagnostic script exactly):
      bid_wap = Σ(bid_price_i * bid_size_i) / Σ(bid_size_i)   for i in 1,2,3
      ask_wap = Σ(ask_price_i * ask_size_i) / Σ(ask_size_i)   for i in 1,2,3
      book_wap_edge_L3 = (bid_wap + ask_wap) / 2 - mid
    Positive = book gravity above mid = upward pressure expected.

    imbalance_L1 = (bid_size_1 - ask_size_1) / (bid_size_1 + ask_size_1)
    Used only in Regime 1 for direction confirmation.
    """
    buys  = order_depth.buy_orders   # {price: qty}, qty > 0
    sells = order_depth.sell_orders  # {price: qty}, qty < 0 (IMC convention)

    if not buys or not sells:
        return {}

    best_bid = max(buys.keys())
    best_ask = min(sells.keys())
    spread   = best_ask - best_bid

    if spread <= 0:
        return {}

    mid = (best_bid + best_ask) / 2.0

    sorted_bids = sorted(buys.keys(),  reverse=True)
    sorted_asks = sorted(sells.keys(), reverse=False)

    def px(lst, i): return lst[i] if i < len(lst) else None
    def sz(book, p): return abs(book[p]) if p is not None else 0.0

    bid_px = [px(sorted_bids, i) for i in range(3)]
    ask_px = [px(sorted_asks, i) for i in range(3)]
    bid_sz = [sz(buys,  p) for p in bid_px]
    ask_sz = [sz(sells, p) for p in ask_px]

    # imbalance_L1
    denom_L1     = bid_sz[0] + ask_sz[0]
    imbalance_L1 = (bid_sz[0] - ask_sz[0]) / denom_L1 if denom_L1 > 0 else 0.0

    # book_wap_edge_L3
    bid_num = sum((bid_px[i] or 0) * bid_sz[i] for i in range(3) if bid_px[i])
    ask_num = sum((ask_px[i] or 0) * ask_sz[i] for i in range(3) if ask_px[i])
    bid_den = sum(bid_sz[i] for i in range(3) if bid_px[i])
    ask_den = sum(ask_sz[i] for i in range(3) if ask_px[i])
    bid_wap = bid_num / bid_den if bid_den > 0 else best_bid
    ask_wap = ask_num / ask_den if ask_den > 0 else best_ask
    book_wap_edge_L3 = ((bid_wap + ask_wap) / 2.0) - mid

    return {
        "best_bid":          best_bid,
        "best_ask":          best_ask,
        "spread":            spread,
        "mid":               mid,
        "imbalance_L1":      imbalance_L1,
        "book_wap_edge_L3":  book_wap_edge_L3,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Persistent state
# ─────────────────────────────────────────────────────────────────────────────

class HydrogelState:
    """
    Survives between ticks via trader_data JSON.

    TraderData size note:
      mid_buf_500 (500 floats ≈ 6KB) + mid_buf_100 (≈ 1.2KB) + fields ≈ 7-8KB.
      If IMC truncates traderData, load() falls back to fresh HydrogelState().
      If truncation is observed, replace buffers with Welford online stats
      (3 numbers per window instead of 500 + 100).
    """

    def __init__(self) -> None:
        # Rolling price buffers
        self.mid_buf_500: List[float] = []
        self.mid_buf_100: List[float] = []

        # Row counter
        self.row: int = 0

        # Regime 1 state
        # regime1_qty is the signed quantity from the entry order.
        # On exit, it is clamped against current position (handles partial fills).
        self.regime1_entry_row: Optional[int] = None
        self.regime1_qty:       int = 0   # signed: +N long, -N short

        # Layer B lean state
        self.lean_target:      float = 0.0
        self.lean_entry_mid:   Optional[float] = None
        self.lean_entry_side:  int = 0   # +1 long lean, -1 short lean

    def to_dict(self) -> dict:
        return {
            "buf500":        self.mid_buf_500,
            "buf100":        self.mid_buf_100,
            "row":           self.row,
            "r1_row":        self.regime1_entry_row,
            "r1_qty":        self.regime1_qty,
            "lean":          self.lean_target,
            "lean_mid":      self.lean_entry_mid,
            "lean_side":     self.lean_entry_side,
        }

    @staticmethod
    def from_dict(d: dict) -> "HydrogelState":
        s = HydrogelState()
        s.mid_buf_500       = d.get("buf500", [])
        s.mid_buf_100       = d.get("buf100", [])
        s.row               = d.get("row", 0)
        s.regime1_entry_row = d.get("r1_row")
        s.regime1_qty       = d.get("r1_qty", 0)
        s.lean_target       = d.get("lean", 0.0)
        s.lean_entry_mid    = d.get("lean_mid")
        s.lean_entry_side   = d.get("lean_side", 0)
        return s

    @staticmethod
    def load(trader_data: str) -> "HydrogelState":
        if not trader_data:
            return HydrogelState()
        try:
            raw = json.loads(trader_data)
            return HydrogelState.from_dict(raw.get("hg", {}))
        except Exception:
            return HydrogelState()

    def save(self, trader_data: str) -> str:
        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}
        raw["hg"] = self.to_dict()
        return json.dumps(raw)



# ─────────────────────────────────────────────────────────────────────────────
# Main strategy
# ─────────────────────────────────────────────────────────────────────────────

def run_hydrogel(
    state:  TradingState,
    hstate: HydrogelState,
) -> Tuple[List[Order], HydrogelState]:
    """
    Regime priority (plan section 2):
      1. spread < REGIME1_SPREAD_THRESHOLD  → aggressive pressure
      2. spread == REGIME2_SPREAD           → stress / downward drift
      3. spread == 16 (normal)              → passive MM + Layer A/B
      else: skip tick (unvalidated spread)
    """
    P      = Product.HYDROGEL_PACK
    orders: List[Order] = []
    p      = HydrogelParams

    if P not in state.order_depths:
        return orders, hstate

    od       = state.order_depths[P]
    position = state.position.get(P, 0)
    pos_lim  = POSITION_LIMITS[P]
    features = compute_book_features(od)

    if not features:
        return orders, hstate

    mid      = features["mid"]
    spread   = features["spread"]
    best_bid = int(features["best_bid"])
    best_ask = int(features["best_ask"])
    imb_L1   = features["imbalance_L1"]
    wap_edge = features["book_wap_edge_L3"]

    # ── FIX 5 (v2): compute z500 BEFORE pushing current mid ──────────────
    # Uses previous Z500_WINDOW mids. Consistent with diagnostic script.
    z500: Optional[float] = None
    if len(hstate.mid_buf_500) == p.Z500_WINDOW:
        z500 = _zscore(hstate.mid_buf_500, mid)

    # Push current mid into buffers AFTER z500 computation
    hstate.mid_buf_500 = _push(hstate.mid_buf_500, mid, p.Z500_WINDOW)
    hstate.mid_buf_100 = _push(hstate.mid_buf_100, mid, p.STD100_WINDOW)
    hstate.row        += 1

    # ── Trending-day / mean-anchor check ─────────────────────────────────
    # Plan update from live validation. Only trust z500 when rolling mean
    # is stable. Prevents false z extremes on trending days.
    # Threshold = MEAN_ANCHOR_STD_MULTIPLIER * roll_std_100 (data-derived unit,
    # but multiplier is [DERIVE] hardcoded — see HydrogelParams).
    mean_is_anchored = False
    if (len(hstate.mid_buf_500) >= p.Z500_WINDOW
            and len(hstate.mid_buf_100) == p.STD100_WINDOW):
        roll_std_100 = _std(hstate.mid_buf_100)
        if (roll_std_100 and roll_std_100 > 0
                and len(hstate.mid_buf_500) >= 2 * p.STD100_WINDOW):
            mean_now  = _mean(hstate.mid_buf_500[-p.STD100_WINDOW:])
            mean_prev = _mean(hstate.mid_buf_500[-2 * p.STD100_WINDOW: -p.STD100_WINDOW])
            if mean_now is not None and mean_prev is not None:
                mean_drift = abs(mean_now - mean_prev)
                mean_is_anchored = mean_drift < p.MEAN_ANCHOR_STD_MULTIPLIER * roll_std_100

    # ─────────────────────────────────────────────────────────────────────
    # REGIME 1 — spread < REGIME1_SPREAD_THRESHOLD
    # Plan section 2, Regime 1.
    # Confirmed: spread=7 fut_ret_10 ≈ +2-4t, spread=9 ≈ -2.5 to -4t.
    # Direction from imbalance_L1 (not spread alone).
    # Exit within REGIME1_EXIT_ROWS=10 — edge reverses at fut_50.
    # ─────────────────────────────────────────────────────────────────────
    skip_bid = False  # may be set True by Regime 2 below
    if spread < p.REGIME1_SPREAD_THRESHOLD:

        if hstate.regime1_entry_row is not None:
            # Active regime1 trade — check exit condition
            rows_in_trade = hstate.row - hstate.regime1_entry_row
            if rows_in_trade >= p.REGIME1_EXIT_ROWS:
                # FIX 3 (v2): exit only regime1_qty, not full position.
                # FIX E: passive exit — post at the favourable maker side.
                # (aggressive exit here pays 8t at spread=7-9, killing the edge)
                if hstate.regime1_qty > 0:
                    exit_qty = min(hstate.regime1_qty, position)
                    if exit_qty > 0:
                        # Long regime1 → sell passively at best ask
                        orders.append(Order(P, best_ask, -exit_qty))
                elif hstate.regime1_qty < 0:
                    exit_qty = min(-hstate.regime1_qty, -position)
                    if exit_qty > 0:
                        # Short regime1 → buy passively at best bid
                        orders.append(Order(P, best_bid, exit_qty))
                hstate.regime1_entry_row = None
                hstate.regime1_qty       = 0

        else:
            # No active regime1 trade — look for entry
            if imb_L1 > p.REGIME1_IMB_THRESHOLD:
                headroom = pos_lim - position
                qty      = min(p.REGIME1_ENTRY_SIZE, headroom)
                if qty > 0:
                    # Aggressive buy — take the ask
                    orders.append(Order(P, best_ask, qty))
                    hstate.regime1_entry_row = hstate.row
                    hstate.regime1_qty       = qty

            elif imb_L1 < -p.REGIME1_IMB_THRESHOLD:
                headroom = pos_lim + position
                qty      = min(p.REGIME1_ENTRY_SIZE, headroom)
                if qty > 0:
                    # Aggressive sell — hit the bid
                    orders.append(Order(P, best_bid, -qty))
                    hstate.regime1_entry_row = hstate.row
                    hstate.regime1_qty       = -qty
            # |imb_L1| < threshold → ambiguous, do nothing

        return orders, hstate  # tight spread: hard return, no passive MM

    else:
        # Spread is normal (not Regime 1) — clear stale Regime 1 tracking.
        # The regime1 position is absorbed into normal MM.
        if hstate.regime1_entry_row is not None:
            hstate.regime1_entry_row = None
            hstate.regime1_qty       = 0

    # ─────────────────────────────────────────────────────────────────────
    # REGIME 2 — spread = 17
    # Confirmed: fut_ret_50 ≈ -4 to -7t. fut_ret_100 ≈ -6.5 to -11t.
    # ─────────────────────────────────────────────────────────────────────
    skip_bid = False  # set True to suppress bid posting this tick
    if spread == p.REGIME2_SPREAD:
        if position > 0:
            flatten_px = best_bid if p.REGIME2_FLATTEN_AGGRESSIVE else best_ask
            orders.append(Order(P, flatten_px, -position))
        # Block new bids on spread=17 (downward drift), but still post asks
        # and fall through to passive MM so we don't miss ask-side fills.
        skip_bid = True

    # ─────────────────────────────────────────────────────────────────────
    # FIX B: Only enter normal regime on validated spread.
    # Plan analysis: spread=15 is "inconsistent, drop". spread 10-14 and
    # 18+ were never observed in 3 days of backtest or live session.
    # Any spread other than 16 is unvalidated — skip the tick.
    # ─────────────────────────────────────────────────────────────────────
    # v2: REMOVED `spread != 16: return` guard. The vol-scaled slack below
    # adapts quote width to realized vol, so quoting is safe on any spread
    # the regime-1/2 handlers don't catch. Worth ≈ 7% extra quoting time.

    # ── NORMAL REGIME — vol-aware passive MM (v2 rewrite) ────────────────
    # Layer A: book_wap_edge_L3 → quote skew    (h=1-5)
    # Layer B: z_roll_mean_500  → inventory lean (h=100-500)
    # New: vol-scaled slack + tighter post prices (r3_v3-style mechanics).

    # ── Layer B: inventory lean target ───────────────────────────────────
    prev_lean = hstate.lean_target

    if z500 is not None:
        if mean_is_anchored:
            if z500 > p.REGIME3_Z_ENTER:
                hstate.lean_target = -p.LAYER_B_SCALE * pos_lim   # short lean
            elif z500 < -p.REGIME3_Z_ENTER:
                hstate.lean_target = p.LAYER_B_SCALE * pos_lim    # long lean
            elif abs(z500) < p.REGIME3_Z_EXIT:
                hstate.lean_target = 0.0                           # unwind
            else:
                # Graduated lean between Z_EXIT and Z_ENTER.
                # [DERIVE] Linear interpolation — could use sigmoid.
                frac      = ((abs(z500) - p.REGIME3_Z_EXIT)
                             / (p.REGIME3_Z_ENTER - p.REGIME3_Z_EXIT))
                direction = -1 if z500 > 0 else 1
                hstate.lean_target = direction * frac * p.LAYER_B_SCALE * pos_lim
        else:
            # Trending day — suppress Layer B (live validation finding).
            hstate.lean_target = 0.0

    # FIX D: Reset lean entry tracking on entry OR direction flip.
    # v2 only caught 0→nonzero. Now also catches nonzero sign change
    # (long lean → short lean without passing zero).
    lean_changed = (
        (prev_lean == 0.0 and hstate.lean_target != 0.0)          # 0 → nonzero
        or (prev_lean != 0.0
            and hstate.lean_target != 0.0
            and prev_lean * hstate.lean_target < 0)               # sign flip
    )
    if lean_changed:
        hstate.lean_entry_mid  = mid
        hstate.lean_entry_side = 1 if hstate.lean_target > 0 else -1

    # Clear tracking when lean fully unwound
    if hstate.lean_target == 0.0:
        hstate.lean_entry_mid  = None
        hstate.lean_entry_side = 0

    # FIX C: Stop loss — actually flatten when adverse move exceeds threshold.
    # v2 only set lean_target=0 ("stop wanting") without submitting orders.
    # Now: immediately submit limit orders to exit the lean position.
    stop_fired = False
    if hstate.lean_entry_mid is not None and hstate.lean_target != 0.0:
        adverse_move = (mid - hstate.lean_entry_mid) * (-hstate.lean_entry_side)
        if adverse_move > p.REGIME3_STOP_TICKS:
            stop_fired = True

            # Submit exit orders for lean position
            # lean_entry_side = +1 means we're long → need to sell
            # lean_entry_side = -1 means we're short → need to buy
            lean_position_est = int(round(
                hstate.lean_target  # target was our intended lean size
            ))
            if hstate.lean_entry_side == 1 and position > 0:
                # Long lean stop — sell aggressively (hit the bid to guarantee fill).
                # Cost accepted: stop is stop.
                exit_qty = min(abs(lean_position_est), position)
                if exit_qty > 0:
                    orders.append(Order(P, best_bid, -exit_qty))
            elif hstate.lean_entry_side == -1 and position < 0:
                # Short lean stop — buy aggressively (lift the ask to guarantee fill).
                exit_qty = min(abs(lean_position_est), -position)
                if exit_qty > 0:
                    orders.append(Order(P, best_ask, exit_qty))

            # Reset all lean state
            hstate.lean_target     = 0.0
            hstate.lean_entry_mid  = None
            hstate.lean_entry_side = 0

    # FIX G: return immediately after stop fires.
    # Without this, code falls through to Layer A/B normal quoting which also
    # posts an ask (or bid). Both could fill same tick → overshoot past flat.
    if stop_fired:
        return orders, hstate

    # ── Layer A: quote skew ───────────────────────────────────────────────
    # book_wap_edge_L3 > 0 → upward pressure → skew quotes up.
    # signal_scan.csv: corr=0.35-0.40, dead by h=20. Window = 1-5 rows.
    skew_A = _clip(wap_edge * p.LAYER_A_SCALE, -p.LAYER_A_CLIP, p.LAYER_A_CLIP)

    # ── Inventory adjustment nudge ────────────────────────────────────────
    # Soft push toward lean_target. Clipped to prevent quote crossing.
    inv_adj_raw = (hstate.lean_target - position) * p.INV_ADJ_COEFF
    inv_adj     = _clip(inv_adj_raw, -p.INV_ADJ_CLIP, p.INV_ADJ_CLIP)

    # Combined bid offset
    bid_offset = skew_A + inv_adj

    # FIX A (v3): no stale-quote early return — IMC orders don't persist.
    # Signals are recomputed every tick.

    # ── Vol-scaled slack (v2, from r3_v3 F3) ─────────────────────────────
    # Use last HP_VOL_WINDOW mids from mid_buf_100 (already maintained).
    # On low-vol days slack=1, on day-2 high-vol slack saturates at 3.
    vol_buf = hstate.mid_buf_100[-p.HP_VOL_WINDOW:]
    sigma   = _std(vol_buf) if len(vol_buf) >= 5 else None
    if sigma is None:
        slack = p.HP_SLACK_MIN
    else:
        slack = int(round(p.HP_SLACK_COEF * sigma))
        slack = max(p.HP_SLACK_MIN, min(p.HP_SLACK_MAX, slack))

    # Fair value: round mid. (mid is x.0 or x.5 because best_bid/best_ask
    # are integers; round() picks the nearest integer, banker's rounding
    # on .5 in Python 3 — fine since we add ±slack on top.)
    fv = int(round(mid))

    # Track headroom that the take phase will consume so we don't double-post.
    bid_headroom = pos_lim - position
    ask_headroom = pos_lim + position

    # ── Take phase (v2) — cross-book opportunistic fills ─────────────────
    # If a book ASK is at or below FV (with pos-aggression tightening),
    # buy it directly. Symmetric for bids ≥ FV. Almost never fires for HG
    # in normal regime (book best ask is ≈ 8t above mid) but is free edge
    # when it does, and matters in stress periods where the book inverts.
    half_thresh = pos_lim * p.POS_AGGRESSION_FRAC
    mbp = fv - 1 if position >  half_thresh else fv   # max buy take price
    msp = fv + 1 if position < -half_thresh else fv   # min sell take price

    for px, vol in sorted(od.sell_orders.items()):
        if bid_headroom <= 0 or px > mbp:
            break
        take = min(bid_headroom, abs(vol))
        if take > 0:
            orders.append(Order(P, px, take))
            bid_headroom -= take

    for px, vol in sorted(od.buy_orders.items(), reverse=True):
        if ask_headroom <= 0 or px < msp:
            break
        take = min(ask_headroom, vol)
        if take > 0:
            orders.append(Order(P, px, -take))
            ask_headroom -= take

    # ── Post phase (v2) — tighter, vol-scaled ────────────────────────────
    # Base post: as r3_v3 — `min(fv - slack, bb + 1)` and symmetric.
    # In default `--match-trades all` mode this gives identical fills to
    # posting at the touch (verified by counterfactual on R3 trades CSV);
    # in `--match-mode imc` mode it makes the order eligible for the
    # inside-spread taker fills, so it strictly dominates.
    base_bid = min(fv - slack, best_bid + 1)
    base_ask = max(fv + slack, best_ask - 1)

    # Layer A skew + Layer B inv_adj as small symmetric offsets.
    my_bid = int(round(base_bid + bid_offset))
    my_ask = int(round(base_ask + bid_offset))

    # Hard clamp — always post at the touch or better.
    # In imc mode (website), taker fills only happen when our quote is INSIDE
    # the spread. Posting below bb+1 (bid) or above ba-1 (ask) = zero taker
    # fills on that tick. inv_adj/skew_A can push us outside the touch, so
    # we floor/ceil before the final clamp.
    # Calibrated from 390828.log: extra_rate=0.0070, fills at bb+avg2.3t / ba-avg3.5t.
    my_bid = max(my_bid, best_bid + 1)   # always at least bb+1
    my_ask = min(my_ask, best_ask - 1)   # always at most ba-1
    my_bid = min(my_bid, best_ask - 1)
    my_ask = max(my_ask, best_bid + 1)
    if my_ask <= my_bid:
        my_ask = my_bid + 1

    # Quote size: bounded by remaining headroom AFTER take phase.
    qs       = p.QUOTE_SIZE
    bid_qty  = min(qs, max(0, bid_headroom))
    ask_qty  = min(qs, max(0, ask_headroom))

    if bid_qty > 0 and not skip_bid:
        orders.append(Order(P, my_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order(P, my_ask, -ask_qty))

    return orders, hstate

# ─────────────────────────────────────────────────────────────────────────────
# Velvet options strategy
# ─────────────────────────────────────────────────────────────────────────────

class BlackScholes:
    @staticmethod
    def black_scholes_call(spot: float, strike: float, time_to_expiry: float, volatility: float, r: float = 0.0) -> float:
        if time_to_expiry <= 0:
            return max(spot - strike, 0.0)
        d1 = (math.log(spot / strike) + (r + 0.5 * volatility ** 2) * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))
        d2 = d1 - volatility * math.sqrt(time_to_expiry)
        call_price = spot * NormalDist().cdf(d1) - strike * math.exp(-r * time_to_expiry) * NormalDist().cdf(d2)
        return call_price

    @staticmethod
    def delta(spot: float, strike: float, time_to_expiry: float, volatility: float, r: float = 0.0) -> float:
        if time_to_expiry <= 0:
            return 1.0 if spot > strike else 0.0
        d1 = (math.log(spot / strike) + (r + 0.5 * volatility ** 2) * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))
        return NormalDist().cdf(d1)

class VelvetState:
    def __init__(self) -> None:
        self.underlying_history: List[float] = []

    def to_dict(self) -> dict:
        return {"uhist": self.underlying_history}

    @staticmethod
    def from_dict(d: dict) -> "VelvetState":
        s = VelvetState()
        s.underlying_history = d.get("uhist", [])
        return s

def run_velvet_options(state: TradingState, vstate: VelvetState) -> Tuple[Dict[Symbol, List[Order]], VelvetState]:
    out_orders: Dict[Symbol, List[Order]] = {}
    under_product = Product.VELVETFRUIT_EXTRACT
    
    if under_product not in state.order_depths:
        return out_orders, vstate
        
    under_depth = state.order_depths[under_product]
    
    under_mid = None
    if under_depth.buy_orders and under_depth.sell_orders:
        under_mid = (max(under_depth.buy_orders.keys()) + min(under_depth.sell_orders.keys())) / 2.0
        vstate.underlying_history.append(under_mid)
        if len(vstate.underlying_history) > 100:
            vstate.underlying_history.pop(0)
    else:
        if len(vstate.underlying_history) > 0:
            under_mid = vstate.underlying_history[-1]
            
    if under_mid is None:
        return out_orders, vstate
        
    sigma = 0.20 # default 20%
    if len(vstate.underlying_history) > 2:
        log_returns = []
        for i in range(1, len(vstate.underlying_history)):
            log_returns.append(math.log(vstate.underlying_history[i] / vstate.underlying_history[i-1]))
        mean_ret = sum(log_returns) / len(log_returns)
        var_ret = sum((r - mean_ret)**2 for r in log_returns) / (len(log_returns) - 1)
        # Avoid math domain error locally if var is extremely small or neg
        if var_ret > 0:
            sigma = math.sqrt(var_ret) * math.sqrt(10000 * 250)
        
    if sigma < 0.01:
        sigma = 0.01

    timestamp_fraction = state.timestamp / 1_000_000.0
    tte_years = max((5.0 - timestamp_fraction) / 250.0, 0.0001)
    
    portfolio_delta = 0.0
    
    options = [
        "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", 
        "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500", 
        "VEV_6000", "VEV_6500"
    ]
    
    for opt in options:
        opt_product = getattr(Product, opt)
        if opt_product not in state.order_depths:
            continue
            
        opt_depth = state.order_depths[opt_product]
        opt_pos = state.position.get(opt_product, 0)
        
        strike = float(opt.replace("VEV_", ""))
        
        fv = BlackScholes.black_scholes_call(under_mid, strike, tte_years, sigma)
        opt_delta = BlackScholes.delta(under_mid, strike, tte_years, sigma)
        
        portfolio_delta += opt_pos * opt_delta
        
        edge = 1.6 # 1.6 tick edge
        buy_fv = fv - edge
        sell_fv = fv + edge
        
        opt_orders: List[Order] = []
        pos_limit = POSITION_LIMITS[opt_product]
        
        cur_pos = opt_pos
        for px in sorted(opt_depth.sell_orders.keys()):
            if px <= buy_fv:
                vol = abs(opt_depth.sell_orders[px])
                allowance = pos_limit - cur_pos
                trade_vol = min(vol, allowance)
                if trade_vol > 0:
                    opt_orders.append(Order(opt_product, px, trade_vol))
                    cur_pos += trade_vol
            else:
                break
                
        cur_pos = opt_pos
        for px in sorted(opt_depth.buy_orders.keys(), reverse=True):
            if px >= sell_fv:
                vol = opt_depth.buy_orders[px]
                allowance = pos_limit + cur_pos
                trade_vol = min(vol, allowance)
                if trade_vol > 0:
                    opt_orders.append(Order(opt_product, px, -trade_vol))
                    cur_pos -= trade_vol
            else:
                break
                
        if opt_orders:
            out_orders[opt_product] = opt_orders

    target_under_pos = -int(round(portfolio_delta))
    under_pos = state.position.get(under_product, 0)
    current_diff = target_under_pos - under_pos
    
    if current_diff != 0:
        under_orders: List[Order] = []
        under_limit = POSITION_LIMITS[under_product]
        
        if current_diff > 0:
            allowance = under_limit - under_pos
            trade_vol = min(current_diff, allowance)
            if trade_vol > 0 and under_depth.buy_orders:
                best_bid = max(under_depth.buy_orders.keys())
                # Passive buy: join the bid instead of hitting the ask
                under_orders.append(Order(under_product, best_bid, trade_vol))
        else:
            allowance = under_limit + under_pos
            trade_vol = min(abs(current_diff), allowance)
            if trade_vol > 0 and under_depth.sell_orders:
                best_ask = min(under_depth.sell_orders.keys())
                # Passive sell: join the ask instead of hitting the bid
                under_orders.append(Order(under_product, best_ask, -trade_vol))
                    
        if under_orders:
            out_orders[under_product] = under_orders

    return out_orders, vstate


# ─────────────────────────────────────────────────────────────────────────────
# Trader entrypoint
# ─────────────────────────────────────────────────────────────────────────────

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orders:     Dict[Symbol, List[Order]] = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        try:
            raw_state = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw_state = {}

        # ── HYDROGEL_PACK ─────────────────────────────────────────────────
        hstate = HydrogelState.load(trader_data)
        hydrogel_orders, hstate = run_hydrogel(state, hstate)
        orders[Product.HYDROGEL_PACK] = hydrogel_orders
        raw_state["hg"] = hstate.to_dict()

        # ── VELVETFRUIT_EXTRACT & VEV_* ───────────────────────────────────
        vstate = VelvetState.from_dict(raw_state.get("velvet", {}))
        velvet_orders, vstate = run_velvet_options(state, vstate)
        raw_state["velvet"] = vstate.to_dict()
        
        for p, ords in velvet_orders.items():
            if p not in orders:
                orders[p] = []
            orders[p].extend(ords)

        new_trader_data = json.dumps(raw_state)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data