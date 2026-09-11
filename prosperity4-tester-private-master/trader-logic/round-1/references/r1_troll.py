"""
Prosperity 4 — Round 1 Trading Algorithm  (IMPROVED v2)
=========================================================
Based on 144810.py with targeted bug fixes identified from log 187427.

Changes from 144810.py
-----------------------
FIX 1  PEPPER_SLOPE corrected from 0.00101 -> 0.001 (measured exactly from data).
       Over 999 900 ticks this removes a +10 drift in fair-value that would cause
       us to be too aggressive buying near end-of-day.

FIX 2  Base EMA only updates when BOTH bid AND ask are quoted.
       When only one side exists the mid_price is a stale/biased proxy
       (e.g. ts=800 in the test had only ask=12010, no bid; EMA inflated the
       base estimate and triggered a buy at deviation +9.3 — above TAKE_MAX=8).

FIX 3  Raised PEPPER_SELL_THRESHOLD from 4 -> 7.
       Bot bids at fair+5-6 triggered sells followed by immediate rebuys
       at fair+7 in the very next tick, losing 0.9 XIRECS/unit per cycle.
       Raising the threshold ensures we only sell to bots paying a clear
       premium, making rebuying less likely to erase the gain.

FIX 4  Removed redundant glitch-sniper loop in _run_pepper.
       The main taking loop (px <= fair + TAKE_MAX) already covers all
       orders at fair-20; the pre-loop only duplicated volume accounting
       and could cause double-counting at the boundary.

Kept from 144810.py (these work well)
--------------------------------------
- ASH _clear / _make inventory-aware market-making   -> P&L +31 900/day
- PEPPER aggressive buy-up to pos limit 80 in ~800 ts -> P&L +73 900/day
- ASH glitch sniper for extreme bot errors (+-20)
- Logger for structured output readable in the Prosperity platform
- jsonpickle / json state serialisation
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple, Any
import json

# -- Constants ----------------------------------------------------------------

POS_LIMIT = 80

# -- PEPPER: trend-following --------------------------------------------------
PEPPER_SLOPE          = 0.001   # FIX 1: exact measured slope (was 0.00101)
PEPPER_BASE_ALPHA     = 0.14    # EMA speed for base estimate (kept from optimiser)
PEPPER_TAKE_MAX       = 8       # take bot asks up to fair + this
PEPPER_BID_LEVELS     = 4       # passive buy levels below fair
PEPPER_ASK_LEVELS     = 2       # thin asks above fair when already long
PEPPER_BID_QTY        = 25      # qty per passive bid level
PEPPER_ASK_QTY        = 6       # qty per passive ask level
PEPPER_SELL_THRESHOLD = 7       # FIX 3: only sell if bot bid > fair + this (was 4)
PEPPER_ASK_THRESHOLD  = 50      # min pos before we post passive asks
PEPPER_ASK_START      = 6       # first ask level above fair

# -- ASH: mean-reversion market-making ----------------------------------------
ASH_FAIR           = 10000
ASH_TAKE_VOL       = 16
ASH_SOFT_LIMIT     = 45
ASH_HARD_LIMIT     = 50
ASH_DISREGARD_EDGE = 1
ASH_JOIN_EDGE      = 2
ASH_DEFAULT_EDGE   = 4


# -- Helpers ------------------------------------------------------------------

def best_bid_ask(od: OrderDepth) -> Tuple:
    bb = max(od.buy_orders.keys())  if od.buy_orders  else None
    ba = min(od.sell_orders.keys()) if od.sell_orders else None
    return bb, ba


def mid_price_if_two_sided(od: OrderDepth):
    """Return (bid+ask)/2 ONLY when both sides are quoted.
    Returns None when one-sided — prevents base-EMA inflation.  (FIX 2)"""
    bb, ba = best_bid_ask(od)
    if bb is not None and ba is not None:
        return (bb + ba) / 2.0
    return None


# -- Structured logger (compatible with Prosperity visualiser) ----------------

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
        lim  = (self.max_log_length - base) // 3
        print(self._json([
            self._state(state, self._cut(state.traderData, lim)),
            self._orders(orders), conversions,
            self._cut(trader_data, lim),
            self._cut(self.logs,   lim),
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


# -- Trader -------------------------------------------------------------------

class Trader:

    LIMIT = {"ASH_COATED_OSMIUM": POS_LIMIT, "INTARIAN_PEPPER_ROOT": POS_LIMIT}

    def bid(self):
        return 15

    # -- ASH inventory-clearing pass -----------------------------------------
    def _clear(self, product, od, fair, limit, pos, bvol, svol):
        """Reduce open inventory by crossing fair-value orders."""
        orders = []
        net = pos + bvol - svol
        if net > 0:
            for p in sorted(od.buy_orders.keys(), reverse=True):
                if p < round(fair) or net <= 0:
                    break
                vol = od.buy_orders[p]
                qty = min(vol, net, limit + pos - svol)
                if qty > 0:
                    orders.append(Order(product, p, -qty))
                    svol += qty
                    net  -= qty
        elif net < 0:
            for p in sorted(od.sell_orders.keys()):
                if p > round(fair) or net >= 0:
                    break
                vol = -od.sell_orders[p]
                qty = min(vol, -net, limit - pos - bvol)
                if qty > 0:
                    orders.append(Order(product, p, qty))
                    bvol += qty
                    net  += qty
        return orders, bvol, svol

    # -- ASH passive quoting pass --------------------------------------------
    def _make(self, product, od, fair, limit, pos, bvol, svol,
              soft_lim, hard_lim, disregard_edge, join_edge, default_edge):
        """Post tightest legal quotes around fair value, skewed by inventory."""
        orders = []
        asks_above = [p for p in od.sell_orders if p > fair + disregard_edge]
        bids_below = [p for p in od.buy_orders  if p < fair - disregard_edge]
        best_ask   = min(asks_above) if asks_above else None
        best_bid   = max(bids_below) if bids_below else None

        ask = round(fair + default_edge)
        if best_ask is not None:
            ask = best_ask if (best_ask - fair) <= join_edge else best_ask - 1

        bid = round(fair - default_edge)
        if best_bid is not None:
            bid = best_bid if (fair - best_bid) <= join_edge else best_bid + 1

        # Inventory skew: tighten the side that restores neutrality
        skew = 0
        if   abs(pos) > hard_lim: skew = 2
        elif abs(pos) > soft_lim: skew = 1
        if   pos > 0: ask -= skew
        elif pos < 0: bid += skew

        if bid >= ask:
            ask = bid + 1

        buy_qty  = limit - (pos + bvol)
        sell_qty = limit + (pos - svol)
        if buy_qty  > 0: orders.append(Order(product, round(bid),  buy_qty))
        if sell_qty > 0: orders.append(Order(product, round(ask), -sell_qty))
        return orders, bvol, svol

    # -- ASH main ------------------------------------------------------------
    def _run_ash(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths:
            return []

        od    = state.order_depths[product]
        pos   = state.position.get(product, 0)
        fair  = ASH_FAIR
        limit = self.LIMIT[product]
        bvol = svol = 0
        orders: List[Order] = []

        # Glitch sniper: take extreme bot errors (>+-20 from fair)
        if od.sell_orders:
            for px in sorted(od.sell_orders.keys()):
                if px >= fair - 20:
                    break
                vol = -od.sell_orders[px]
                qty = min(vol, limit - pos - bvol)
                if qty > 0:
                    orders.append(Order(product, px, qty))
                    bvol += qty

        if od.buy_orders:
            for px in sorted(od.buy_orders.keys(), reverse=True):
                if px <= fair + 20:
                    break
                vol = od.buy_orders[px]
                qty = min(vol, limit + pos - svol)
                if qty > 0:
                    orders.append(Order(product, px, -qty))
                    svol += qty

        # Take mispriced bot orders within normal range
        if od.sell_orders:
            best_ask = min(od.sell_orders)
            ask_vol  = -od.sell_orders[best_ask]
            if best_ask <= fair - 1 and ask_vol < ASH_TAKE_VOL:
                qty = min(ask_vol, limit - pos - bvol)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
                    bvol += qty

        if od.buy_orders:
            best_bid = max(od.buy_orders)
            bid_vol  = od.buy_orders[best_bid]
            if best_bid >= fair + 1 and bid_vol < ASH_TAKE_VOL:
                qty = min(bid_vol, limit + pos - svol)
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))
                    svol += qty

        # Clear inventory toward neutral then post passive quotes
        clear_o, bvol, svol = self._clear(product, od, fair, limit, pos, bvol, svol)
        orders += clear_o
        make_o, _, _ = self._make(
            product, od, fair, limit, pos, bvol, svol,
            ASH_SOFT_LIMIT, ASH_HARD_LIMIT,
            ASH_DISREGARD_EDGE, ASH_JOIN_EDGE, ASH_DEFAULT_EDGE,
        )
        orders += make_o
        return orders

    # -- PEPPER main ---------------------------------------------------------
    def _run_pepper(self, state: TradingState, saved: Dict) -> List[Order]:
        orders: List[Order] = []
        od  = state.order_depths["INTARIAN_PEPPER_ROOT"]
        pos = state.position.get("INTARIAN_PEPPER_ROOT", 0)
        ts  = state.timestamp

        # FIX 2: only update base EMA with two-sided mid price
        mid = mid_price_if_two_sided(od)
        if mid is not None:
            cur_base = mid - PEPPER_SLOPE * ts
            if "pepper_base" not in saved:
                saved["pepper_base"] = cur_base
            else:
                saved["pepper_base"] = (
                    (1.0 - PEPPER_BASE_ALPHA) * saved["pepper_base"]
                    + PEPPER_BASE_ALPHA * cur_base
                )

        base   = saved.get("pepper_base", 12000.0)
        fair   = base + PEPPER_SLOPE * ts
        fair_r = round(fair)

        buy_cap  = POS_LIMIT - pos
        sell_cap = POS_LIMIT + pos

        logger.print(f"PEPPER ts={ts} pos={pos} fair={fair:.2f}")

        # -- 1. Take cheap bot asks (aggressive accumulation) -----------------
        # FIX 4: removed redundant glitch-sniper pre-loop;
        #        main loop already covers any ask below fair + TAKE_MAX
        for px in sorted(od.sell_orders.keys()):
            if px > fair + PEPPER_TAKE_MAX or buy_cap <= 0:
                break
            vol = -od.sell_orders[px]
            qty = min(vol, buy_cap)
            orders.append(Order("INTARIAN_PEPPER_ROOT", px, qty))
            buy_cap -= qty

        # -- 2. Sell to bots paying well above fair (lock extra profit) -------
        # FIX 3: threshold raised from 4 -> 7 to avoid sell/rebuy churn
        for px in sorted(od.buy_orders.keys(), reverse=True):
            if px <= fair + PEPPER_SELL_THRESHOLD or sell_cap <= 0:
                break
            vol = od.buy_orders[px]
            qty = min(vol, sell_cap)
            orders.append(Order("INTARIAN_PEPPER_ROOT", px, -qty))
            sell_cap -= qty

        # -- 3. Passive bids just inside the bot spread ----------------------
        # Bots bid at fair-6; we post at fair-1 to fair-4 to get priority fills.
        for level in range(1, PEPPER_BID_LEVELS + 1):
            if buy_cap <= 0:
                break
            qty = min(PEPPER_BID_QTY, buy_cap)
            orders.append(Order("INTARIAN_PEPPER_ROOT", fair_r - level, qty))
            buy_cap -= qty

        # -- 4. Thin asks when deeply long (earn spread without selling trend)
        if pos > PEPPER_ASK_THRESHOLD and sell_cap > 0:
            for level in range(PEPPER_ASK_START,
                               PEPPER_ASK_START + PEPPER_ASK_LEVELS):
                if sell_cap <= 0:
                    break
                qty = min(PEPPER_ASK_QTY, sell_cap)
                orders.append(Order("INTARIAN_PEPPER_ROOT", fair_r + level, -qty))
                sell_cap -= qty

        return orders

    # -- Entry point ---------------------------------------------------------
    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        conversions = 0

        ash_orders = self._run_ash(state)
        if ash_orders:
            result["ASH_COATED_OSMIUM"] = ash_orders

        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            pep_orders = self._run_pepper(state, saved)
            if pep_orders:
                result["INTARIAN_PEPPER_ROOT"] = pep_orders

        trader_data = json.dumps(saved)
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
