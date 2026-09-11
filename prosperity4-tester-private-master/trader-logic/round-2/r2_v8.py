import json
import math
import numpy as np
from datamodel import Order, OrderDepth, TradingState

LIMIT = 80

# --- ACO Parameters (LU-style, kept from v8 — slightly better than r1_final's ACO) ---
ACO = "ASH_COATED_OSMIUM"
ACO_FV = 10000
ACO_TAKE_WIDTH = 1
ACO_DISREGARD_EDGE = 1
ACO_JOIN_EDGE = 2
ACO_DEFAULT_EDGE = 4
ACO_ADVERSE_VOL = 15

# --- IPR Parameters (from 228959 trend-following via r1_final) ---
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

    # ═══ ACO: LU take/make (unchanged from v8) ═══

    def _aco(self, state):
        book = state.order_depths[ACO]
        if not (book.buy_orders or book.sell_orders):
            return []

        pos = state.position.get(ACO, 0)
        fv = ACO_FV
        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos
        orders = []

        # --- Aggressive takes ---
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

        # --- Passive maker ---
        asks_above = [p for p in book.sell_orders if p > fv + ACO_DISREGARD_EDGE]
        bids_below = [p for p in book.buy_orders if p < fv - ACO_DISREGARD_EDGE]

        if asks_above:
            ref = min(asks_above)
            ask_price = ref if (ref - fv) <= ACO_JOIN_EDGE else ref - 1
        else:
            ask_price = round(fv + ACO_DEFAULT_EDGE)

        if bids_below:
            ref = max(bids_below)
            bid_price = ref if (fv - ref) <= ACO_JOIN_EDGE else ref + 1
        else:
            bid_price = round(fv - ACO_DEFAULT_EDGE)

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        if buy_cap > 0:
            orders.append(Order(ACO, bid_price, buy_cap))
        if sell_cap > 0:
            orders.append(Order(ACO, ask_price, -sell_cap))

        return orders

    # ═══ IPR: 228959 trend-following (target=80, wall-mid, aggressive crossing) ═══

    def _ipr(self, book: OrderDepth, pos, prev_mids, slope, directions):
        orders = []

        wall_mid = prev_mids[-1] + slope if prev_mids else 10000
        best_ask = best_bid = None
        ask_quantity = bid_quantity = 0

        if book.buy_orders and book.sell_orders:
            wall_mid = self._wall_mid(book)
            best_ask = min(book.sell_orders)
            ask_quantity = book.sell_orders[best_ask]          # negative
            best_bid = max(book.buy_orders)
            bid_quantity = book.buy_orders[best_bid]
        elif book.sell_orders:
            best_ask = min(book.sell_orders)
            ask_quantity = book.sell_orders[best_ask]
        elif book.buy_orders:
            best_bid = max(book.buy_orders)
            bid_quantity = book.buy_orders[best_bid]

        # Maintain 5-tick wall-mid history
        prev_mids = [wall_mid] if prev_mids is None else prev_mids + [wall_mid]
        if len(prev_mids) > 5:
            prev_mids.pop(0)
            slope = self._regression_slope(prev_mids)
        else:
            slope = 0

        # 20-tick direction history → trend indicator
        trend = 1 if slope >= 0 else -1
        directions = [trend] if directions is None else directions + [trend]
        if len(directions) > 20:
            directions.pop(0)
        indicator = directions.count(1) / len(directions)

        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos

        mid_spread = (PEPPER_SPREAD_GRADIENT * wall_mid + PEPPER_SPREAD_INTERCEPT) / 2

        if indicator >= 0.5:
            # === UPTREND: go max long ===
            target = 80

            if pos <= 0.9 * target and len(prev_mids) == 5:
                # Aggressive lift: cross the spread to build position FAST
                fair_purchase = math.floor(wall_mid + mid_spread)
                best_ask = min(best_ask, fair_purchase) if best_ask else fair_purchase
                orders.append(Order(IPR, best_ask, buy_cap))

            elif pos < target:
                # Careful accumulation: take at/below wall_mid, passive penny
                if best_ask and best_ask <= wall_mid:
                    buy_qty = min(buy_cap, -ask_quantity)
                    orders.append(Order(IPR, best_ask, buy_qty))
                    buy_cap -= buy_qty
                if best_bid and best_bid < wall_mid - mid_spread / 2:
                    orders.append(Order(IPR, best_bid + 1, buy_cap))

            elif best_ask and best_ask > wall_mid + mid_spread / 2:
                # At target: sell only at premium
                orders.append(Order(IPR, best_ask - 1, -sell_cap))

        else:
            # === DOWNTREND: go max short ===
            target = -80

            # Note: len(prev_mids)==10 is never true (capped at 5).
            # This is an intentional long-bias from 228959 — aggressive short never fires.
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

        # ACO
        if ACO in state.order_depths:
            result[ACO] = self._aco(state)

        # IPR
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
