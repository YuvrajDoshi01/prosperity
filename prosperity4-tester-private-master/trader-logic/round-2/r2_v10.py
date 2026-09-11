import json
import math
import numpy as np
from datamodel import Order, OrderDepth, TradingState

LIMIT = 80

# --- ACO Parameters (LU canonical: Take → Clear → Make + inventory skew) ---
# Analysis confirms R2 ACO == R1 ACO: FV=10000, symmetric spreads (100%),
# modal spread=16 (64%), AC(1)=-0.49, L1 vol mean=14, 50/50 taker flow.
# Spread-signal overlay REMOVED: symmetric spreads can't leak direction;
# prior map was overfitting to specific CSV replay days.
ACO = "ASH_COATED_OSMIUM"
ACO_FV = 10000
ACO_TAKE_WIDTH = 1       # take at FV±1 (inside the 16-wide spread)
ACO_ADVERSE_VOL = 15     # skip fills where L1 vol ≥ 15 (organic maker size)
ACO_DISREGARD_EDGE = 1   # ignore ask/bid within 1 of FV for maker ref
ACO_JOIN_EDGE = 2        # join if ref ask/bid within 2 of FV
ACO_DEFAULT_EDGE = 4     # default maker width when no ref level
ACO_SOFT_POS = 40        # begin inventory skew at |pos| > 40

# --- IPR Parameters (228959 trend-following, no warmup gate) ---
IPR = "INTARIAN_PEPPER_ROOT"
PEPPER_SPREAD_GRADIENT = 0.0010586880760
PEPPER_SPREAD_INTERCEPT = 0.8694130152902


class Trader:
    def bid(self):
        return 2000

    # ═══ Helpers ═══

    @staticmethod
    def _regression_slope(prices):
        x = np.arange(len(prices))
        y = np.array(prices)
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        denom = np.sum((x - x_mean) ** 2)
        if denom == 0:
            return 0.0
        return float(np.sum((x - x_mean) * (y - y_mean)) / denom)

    @staticmethod
    def _wall_mid(book: OrderDepth):
        """Mid of the largest-volume bid and ask levels."""
        best_vol, deep_bid = 0, 0
        for price, vol in book.buy_orders.items():
            if vol > best_vol:
                best_vol = vol
                deep_bid = price

        best_vol, deep_ask = 0, 0
        for price, vol in book.sell_orders.items():
            if vol < best_vol:
                best_vol = vol
                deep_ask = price

        return (deep_bid + deep_ask) / 2

    # ═══ ACO: LU Take → Clear → Make (canonical, with inventory skew) ═══
    #
    # Analysis of R2 bid-mid / ask-mid confirms:
    #   • Spreads are ALWAYS symmetric (bid_to_mid == ask_to_mid, 0% asymmetry)
    #   • Modal spread = 16 (64%), secondary 18-19 (25%), tight 5-10 (6%)
    #   • FV = 10000 ± 1.8 across all 4 days
    #   • Taker flow balanced 50/50, avg qty ~5, ~456 trades/day
    #   • No intraday regime changes (Q1 vs Q4 identical)
    #
    # Changes from prior v10:
    #   REMOVED: spread-signal overlay (overfitting — symmetric spreads
    #            can't directionally predict next-tick mid moves)
    #   ADDED:   clear step at FV (validated +3% PnL on stable products, R1)
    #   ADDED:   soft-limit inventory skew at |pos| > 40 (r1_v4 validated)

    def _aco(self, state):
        book = state.order_depths[ACO]
        if not (book.buy_orders or book.sell_orders):
            return []

        pos = state.position.get(ACO, 0)
        fv = ACO_FV
        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos
        orders = []

        best_bid = max(book.buy_orders) if book.buy_orders else None
        best_ask = min(book.sell_orders) if book.sell_orders else None

        # --- 1. TAKE: aggressive fills at FV±1, adverse_vol filtered ---
        for price, vol in sorted(book.sell_orders.items()):
            if buy_cap <= 0 or price > fv - ACO_TAKE_WIDTH:
                break
            if abs(vol) >= ACO_ADVERSE_VOL:
                continue
            qty = min(buy_cap, -vol)
            orders.append(Order(ACO, price, qty))
            buy_cap -= qty

        for price, vol in sorted(book.buy_orders.items(), reverse=True):
            if sell_cap <= 0 or price < fv + ACO_TAKE_WIDTH:
                break
            if vol >= ACO_ADVERSE_VOL:
                continue
            qty = min(sell_cap, vol)
            orders.append(Order(ACO, price, -qty))
            sell_cap -= qty

        # --- 2. CLEAR: flatten inventory exactly at FV ---
        # Sell at FV when long, buy at FV when short.
        # This is the +3% trick from LU: extract the last tick of edge
        # that the take step leaves on the table.
        if pos > 0 and sell_cap > 0:
            clear_qty = min(pos, sell_cap)
            orders.append(Order(ACO, fv, -clear_qty))
            sell_cap -= clear_qty
        elif pos < 0 and buy_cap > 0:
            clear_qty = min(-pos, buy_cap)
            orders.append(Order(ACO, fv, clear_qty))
            buy_cap -= clear_qty

        # --- 3. MAKE: passive quotes with penny/join/default + inventory skew ---
        asks_above = [p for p in book.sell_orders if p > fv + ACO_DISREGARD_EDGE]
        bids_below = [p for p in book.buy_orders if p < fv - ACO_DISREGARD_EDGE]

        # Base maker prices (penny/join/default logic)
        if asks_above:
            ref = min(asks_above)
            ask_price = ref if (ref - fv) <= ACO_JOIN_EDGE else ref - 1
        else:
            ask_price = fv + ACO_DEFAULT_EDGE

        if bids_below:
            ref = max(bids_below)
            bid_price = ref if (fv - ref) <= ACO_JOIN_EDGE else ref + 1
        else:
            bid_price = fv - ACO_DEFAULT_EDGE

        # Inventory skew: when |pos| > SOFT_POS, tighten the reducing side
        # and widen the extending side to accelerate mean-reversion.
        if abs(pos) > ACO_SOFT_POS:
            skew = 1  # 1-tick skew at soft limit
            if pos > 0:
                # Long: tighten ask (more eager to sell), widen bid
                ask_price = max(fv + 1, ask_price - skew)
                bid_price = bid_price - skew
            else:
                # Short: tighten bid (more eager to buy), widen ask
                bid_price = min(fv - 1, bid_price + skew)
                ask_price = ask_price + skew

        # Safety: never cross our own spread
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        if buy_cap > 0:
            orders.append(Order(ACO, bid_price, buy_cap))
        if sell_cap > 0:
            orders.append(Order(ACO, ask_price, -sell_cap))

        return orders

    # ═══ IPR: 228959 trend-following (no warmup gate) ═══

    def _ipr(self, book: OrderDepth, pos, prev_mids, slope, directions):
        orders = []

        wall_mid = prev_mids[-1] + slope if prev_mids else 10000
        best_ask = best_bid = None
        ask_quantity = bid_quantity = 0

        if book.buy_orders and book.sell_orders:
            wall_mid = self._wall_mid(book)
            best_ask = min(book.sell_orders)
            ask_quantity = book.sell_orders[best_ask]
            best_bid = max(book.buy_orders)
            bid_quantity = book.buy_orders[best_bid]
        elif book.sell_orders:
            best_ask = min(book.sell_orders)
            ask_quantity = book.sell_orders[best_ask]
        elif book.buy_orders:
            best_bid = max(book.buy_orders)
            bid_quantity = book.buy_orders[best_bid]

        prev_mids = [wall_mid] if prev_mids is None else prev_mids + [wall_mid]
        if len(prev_mids) > 5:
            prev_mids.pop(0)
            slope = self._regression_slope(prev_mids)
        else:
            slope = 0

        trend = 1 if slope >= 0 else -1
        directions = [trend] if directions is None else directions + [trend]
        if len(directions) > 20:
            directions.pop(0)
        indicator = directions.count(1) / len(directions)

        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos

        mid_spread = (PEPPER_SPREAD_GRADIENT * wall_mid + PEPPER_SPREAD_INTERCEPT) / 2

        if indicator >= 0.5:
            target = 80

            if pos <= 0.9 * target:
                fair_purchase = math.floor(wall_mid + mid_spread)
                best_ask = min(best_ask, fair_purchase) if best_ask else fair_purchase
                orders.append(Order(IPR, best_ask, buy_cap))

            elif pos < target:
                if best_ask and best_ask <= wall_mid:
                    buy_qty = min(buy_cap, -ask_quantity)
                    orders.append(Order(IPR, best_ask, buy_qty))
                    buy_cap -= buy_qty
                if best_bid and best_bid < wall_mid - mid_spread / 2:
                    orders.append(Order(IPR, best_bid + 1, buy_cap))

            elif best_ask and best_ask > wall_mid + mid_spread / 2:
                orders.append(Order(IPR, best_ask - 1, -sell_cap))

        else:
            target = -80

            if pos >= 0.9 * target and len(prev_mids) == 10:
                if best_bid:
                    orders.append(Order(IPR, best_bid, -sell_cap))
                else:
                    orders.append(Order(IPR, math.floor(wall_mid - mid_spread), -sell_cap))

            elif pos > target:
                if best_bid and best_bid >= wall_mid:
                    sell_qty = min(sell_cap, bid_quantity)
                    orders.append(Order(IPR, best_bid, -sell_qty))
                    sell_cap -= sell_qty
                if best_ask and best_ask > wall_mid + mid_spread / 2:
                    orders.append(Order(IPR, best_ask - 1, -sell_cap))

            elif best_bid and best_bid < wall_mid - mid_spread / 2:
                orders.append(Order(IPR, best_bid + 1, buy_cap))

        return orders, prev_mids, slope, directions

    # ═══ Main ═══

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else {}
        if not isinstance(saved, dict):
            saved = {}

        result = {}

        if ACO in state.order_depths:
            result[ACO] = self._aco(state)

        if IPR in state.order_depths:
            orders, mids, slope, dirs = self._ipr(
                state.order_depths[IPR],
                state.position.get(IPR, 0),
                saved.get("mids"),
                saved.get("slope", 0),
                saved.get("dirs"),
            )
            result[IPR] = orders
            saved["mids"] = mids
            saved["slope"] = slope
            saved["dirs"] = dirs

        return result, 0, json.dumps(saved, separators=(",", ":"))
