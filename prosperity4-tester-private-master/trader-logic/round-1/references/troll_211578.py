"""
Prosperity 4 — Round 1  (v4 — Final)
======================================
4 tunable parameters.  4 measured constants.  Nothing else.

Tunable (sensitivity swing from 3-day backtest):
  PEPPER_TAKE_MAX       = 8       swing =    241
  PEPPER_SELL_THRESHOLD = 7       swing =  5,889  (CLIFF at 2–3, safe at 7)
  ASH_TAKE_VOL          = 16      swing =  1,363
  ASH_DEFAULT_EDGE      = 7       swing =     64

Constants (measured / architectural, swing ≈ 0):
  PEPPER_SLOPE  = 0.001    probe-confirmed exact slope
  PEPPER_EMA_A  = 0.14     EMA speed, swing = 31
  ASH_FAIR      = 10000    probe-confirmed, drift = -0.5/day
  POS_LIMIT     = 80       platform rule

ACO uses the v2 penny-the-inner-bot _make() logic (avg spread captured 11.29).
PEPPER uses v3 improvements (SELL_THRESHOLD=7, no passive asks, simpler bids).
"""

from datamodel import OrderDepth, TradingState, Order
from typing import Any, Dict, List, Tuple
import json

# =============================================================================
#  4 TUNABLE PARAMETERS
# =============================================================================

PEPPER_TAKE_MAX       = 8     # buy bot asks up to fair + this
PEPPER_SELL_THRESHOLD = 7     # sell only if bot bid > fair + this (stops churn)
ASH_TAKE_VOL          = 16    # take bot orders with vol below this
ASH_DEFAULT_EDGE      = 7     # fallback spread when no book levels to penny

# =============================================================================
#  4 MEASURED CONSTANTS
# =============================================================================

PEPPER_SLOPE  = 0.001      # exact trend: +1 per 1000 ticks (probe-confirmed)
PEPPER_EMA_A  = 0.14       # base EMA smoothing speed
ASH_FAIR      = 10_000     # mean-reversion anchor (probe-confirmed)
POS_LIMIT     = 80         # platform position limit

# ACO _make() architectural constants (swing = 0, not tunable)
_DISREGARD = 1    # ignore book quotes within 1 tick of fair
_JOIN_EDGE = 2    # join (don't penny) if within 2 ticks of fair


# =============================================================================
#  Helpers
# =============================================================================

def two_sided_mid(od: OrderDepth):
    """Mid-price ONLY when both bid and ask are quoted.
    Returns None on one-sided markets to prevent EMA inflation."""
    if od.buy_orders and od.sell_orders:
        return (max(od.buy_orders) + min(od.sell_orders)) / 2.0
    return None


# =============================================================================
#  Logger
# =============================================================================

class Logger:
    def __init__(self):
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep=" ", end="\n"):
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state, orders, conversions, trader_data):
        from datamodel import ProsperityEncoder
        base = len(self._json([self._state(state, ""), self._orders(orders),
                                conversions, "", ""]))
        lim = (self.max_log_length - base) // 3
        print(self._json([
            self._state(state, self._cut(state.traderData, lim)),
            self._orders(orders), conversions,
            self._cut(trader_data, lim),
            self._cut(self.logs, lim),
        ]))
        self.logs = ""

    def _state(self, state, td):
        return [
            state.timestamp, td,
            [[l.symbol, l.product, l.denomination] for l in state.listings.values()],
            {s: [od.buy_orders, od.sell_orders] for s, od in state.order_depths.items()},
            self._trades(state.own_trades),
            self._trades(state.market_trades),
            state.position,
            self._obs(state.observations),
        ]

    def _trades(self, trades):
        return [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
                for arr in trades.values() for t in arr]

    def _obs(self, obs):
        co = {}
        for p, o in obs.conversionObservations.items():
            co[p] = [o.bidPrice, o.askPrice, o.transportFees,
                     o.exportTariff, o.importTariff, o.sugarPrice, o.sunlightIndex]
        return [obs.plainValueObservations, co]

    def _orders(self, orders):
        return [[o.symbol, o.price, o.quantity] for arr in orders.values() for o in arr]

    def _json(self, v):
        from datamodel import ProsperityEncoder
        return json.dumps(v, cls=ProsperityEncoder, separators=(",", ":"))

    def _cut(self, s, n):
        return s if len(s) <= n else s[:n - 3] + "..."


logger = Logger()


# =============================================================================
#  Trader
# =============================================================================

class Trader:

    # -- ASH: clear inventory toward neutral --------------------------------
    # Exact logic from v2 (189857.py lines 150-174) - proven at 11.29 spread

    def _clear(self, od, pos, bvol, svol):
        """Sell to any bid >= fair (when long) or buy any ask <= fair (when short)."""
        orders = []
        fair = ASH_FAIR
        limit = POS_LIMIT
        net = pos + bvol - svol

        if net > 0:
            for p in sorted(od.buy_orders.keys(), reverse=True):
                if p < fair or net <= 0:
                    break
                vol = od.buy_orders[p]
                qty = min(vol, net, limit + pos - svol)
                if qty > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", p, -qty))
                    svol += qty
                    net -= qty
        elif net < 0:
            for p in sorted(od.sell_orders.keys()):
                if p > fair or net >= 0:
                    break
                vol = -od.sell_orders[p]
                qty = min(vol, -net, limit - pos - bvol)
                if qty > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", p, qty))
                    bvol += qty
                    net += qty

        return orders, bvol, svol

    # -- ASH: penny-the-inner-bot passive quotes ----------------------------
    # Exact logic from v2 (189857.py lines 177-208) - the key to 11.29 spread
    # Uses _DISREGARD, _JOIN_EDGE (architectural constants) and ASH_DEFAULT_EDGE
    # Inventory skew derived from pos // 25 (no SOFT/HARD params needed)

    def _make(self, od, pos, bvol, svol):
        """Post tightest legal quotes around fair, skewed by inventory."""
        orders = []
        fair = ASH_FAIR
        limit = POS_LIMIT

        # Find best book levels outside the disregard zone
        asks_above = [p for p in od.sell_orders if p > fair + _DISREGARD]
        bids_below = [p for p in od.buy_orders if p < fair - _DISREGARD]
        best_ask = min(asks_above) if asks_above else None
        best_bid = max(bids_below) if bids_below else None

        # Default: quote at fair +/- DEFAULT_EDGE
        ask = fair + ASH_DEFAULT_EDGE
        if best_ask is not None:
            # Penny the inner bot, or join if very close to fair
            ask = best_ask if (best_ask - fair) <= _JOIN_EDGE else best_ask - 1

        bid = fair - ASH_DEFAULT_EDGE
        if best_bid is not None:
            bid = best_bid if (fair - best_bid) <= _JOIN_EDGE else best_bid + 1

        # Inventory skew: 1 tick per 25 units of imbalance
        # Inventory skew (v2 exact logic - only skew ONE side)
        skew = 0
        if   abs(pos) > 50: skew = 2
        elif abs(pos) > 45: skew = 1
        if   pos > 0: ask -= skew
        elif pos < 0: bid += skew

        if bid >= ask:
            ask = bid + 1

        buy_qty = limit - (pos + bvol)
        sell_qty = limit + (pos - svol)
        if buy_qty > 0:
            orders.append(Order("ASH_COATED_OSMIUM", bid, buy_qty))
        if sell_qty > 0:
            orders.append(Order("ASH_COATED_OSMIUM", ask, -sell_qty))

        return orders, bvol, svol

    # -- ASH main -----------------------------------------------------------

    def _run_ash(self, state: TradingState) -> List[Order]:
        if "ASH_COATED_OSMIUM" not in state.order_depths:
            return []

        od = state.order_depths["ASH_COATED_OSMIUM"]
        pos = state.position.get("ASH_COATED_OSMIUM", 0)
        fair = ASH_FAIR
        limit = POS_LIMIT
        bvol = svol = 0
        orders: List[Order] = []

        # 1. Glitch sniper: take extreme bot errors (>20 from fair)
        if od.sell_orders:
            for px in sorted(od.sell_orders.keys()):
                if px >= fair - 20:
                    break
                vol = -od.sell_orders[px]
                qty = min(vol, limit - pos - bvol)
                if qty > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", px, qty))
                    bvol += qty

        if od.buy_orders:
            for px in sorted(od.buy_orders.keys(), reverse=True):
                if px <= fair + 20:
                    break
                vol = od.buy_orders[px]
                qty = min(vol, limit + pos - svol)
                if qty > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", px, -qty))
                    svol += qty

        # 2. Take mispriced bot orders (crossing bot, vol < ASH_TAKE_VOL)
        if od.sell_orders:
            best_ask = min(od.sell_orders)
            ask_vol = -od.sell_orders[best_ask]
            if best_ask <= fair - 1 and ask_vol < ASH_TAKE_VOL:
                qty = min(ask_vol, limit - pos - bvol)
                if qty > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", best_ask, qty))
                    bvol += qty

        if od.buy_orders:
            best_bid = max(od.buy_orders)
            bid_vol = od.buy_orders[best_bid]
            if best_bid >= fair + 1 and bid_vol < ASH_TAKE_VOL:
                qty = min(bid_vol, limit + pos - svol)
                if qty > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", best_bid, -qty))
                    svol += qty

        # 3. Clear inventory toward neutral
        clear_o, bvol, svol = self._clear(od, pos, bvol, svol)
        orders += clear_o

        # 4. Post passive penny quotes
        make_o, _, _ = self._make(od, pos, bvol, svol)
        orders += make_o

        return orders

    # -- PEPPER main --------------------------------------------------------

    def _run_pepper(self, state: TradingState, saved: Dict) -> List[Order]:
        od = state.order_depths["INTARIAN_PEPPER_ROOT"]
        pos = state.position.get("INTARIAN_PEPPER_ROOT", 0)
        ts = state.timestamp

        # Fair value: base (EMA) + slope * timestamp
        mid = two_sided_mid(od)
        if mid is not None:
            cur_base = mid - PEPPER_SLOPE * ts
            if "base" not in saved:
                saved["base"] = cur_base
            else:
                saved["base"] = (1 - PEPPER_EMA_A) * saved["base"] + PEPPER_EMA_A * cur_base

        fair = saved.get("base", 12_000.0) + PEPPER_SLOPE * ts
        fair_r = round(fair)

        orders: List[Order] = []
        buy_cap = POS_LIMIT - pos
        sell_cap = POS_LIMIT + pos

        logger.print(f"PEPPER ts={ts} pos={pos} fair={fair:.1f}")

        # 1. Take cheap bot asks (aggressive accumulation to pos 80)
        for px in sorted(od.sell_orders.keys()):
            if px > fair + PEPPER_TAKE_MAX or buy_cap <= 0:
                break
            vol = -od.sell_orders[px]
            qty = min(vol, buy_cap)
            orders.append(Order("INTARIAN_PEPPER_ROOT", px, qty))
            buy_cap -= qty

        # 2. Sell only if bots overpay (SELL_THRESHOLD=7 prevents churn)
        for px in sorted(od.buy_orders.keys(), reverse=True):
            if px <= fair + PEPPER_SELL_THRESHOLD or sell_cap <= 0:
                break
            vol = od.buy_orders[px]
            qty = min(vol, sell_cap)
            orders.append(Order("INTARIAN_PEPPER_ROOT", px, -qty))
            sell_cap -= qty

        # 3. Passive bids to fill remaining capacity
        level = 1
        while buy_cap > 0:
            qty = min(buy_cap, POS_LIMIT)
            orders.append(Order("INTARIAN_PEPPER_ROOT", fair_r - level, qty))
            buy_cap -= qty
            level += 1

        return orders

    # -- Entry point --------------------------------------------------------

    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        conversions = 0

        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self._run_ash(state)

        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            result["INTARIAN_PEPPER_ROOT"] = self._run_pepper(state, saved)

        trader_data = json.dumps(saved)
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
