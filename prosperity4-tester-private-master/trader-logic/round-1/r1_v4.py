import json
from datamodel import Order, TradingState

"""
r1_v4 — Round 1 Strategy (r1_v2 IPR + Linear Utility ACO)

Keeps what works, ditches what doesn't.

IPR: reverted to r1_v2 logic (simple mid + drift_bias=5).
  r1_v2 scored IPR=7,446 on website.
  r1_v3 tried LU framework with filtered-mm-mid + TAKE_WIDTH=1 → IPR=4,796 (regression).
  Root cause: LU's take_width assumes present-value FV, but drift needs future-value FV.

ACO: Linear Utility AMETHYSTS-style take-clear-make.
  r1_v3 validated this: ACO went from 3,091 → 3,179 (+88).
  Keeping the structure: take_width=1, clear_width=0, disregard=1, join=2,
  default=4, adverse_vol=15, soft_limit=40.
"""

# ═══ SHARED CONSTANTS ═══
LIMIT = 80
SOFT_LIMIT = 40

# ═══ IPR CONFIG (r1_v2 proven) ═══
IPR = "INTARIAN_PEPPER_ROOT"
IPR_DRIFT_BIAS = 5.0
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3

# ═══ ACO CONFIG (Linear Utility AMETHYSTS exact) ═══
ACO = "ASH_COATED_OSMIUM"
ACO_FV = 10000
ACO_TAKE_WIDTH = 1        # LU exact
ACO_CLEAR_WIDTH = 0       # LU exact — flatten at FV
ACO_DISREGARD_EDGE = 1    # LU exact
ACO_JOIN_EDGE = 2         # LU exact
ACO_DEFAULT_EDGE = 4      # LU exact
ACO_ADVERSE_VOL = 15      # LU exact


class Trader:
    def __init__(self):
        pass

    def bid(self):
        return 15

    # ═══════════════════════════════════════════════════════════
    # ACO: Linear Utility framework (take → clear → make + skew)
    # ═══════════════════════════════════════════════════════════

    def _aco(self, state):
        book = state.order_depths[ACO]
        if not (book.buy_orders or book.sell_orders):
            return []

        pos = state.position.get(ACO, 0)
        fv = ACO_FV
        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos
        bought = sold = 0
        orders = []

        # ─── Take ──────────────────────────────────────────────────
        for price, vol in sorted(book.sell_orders.items()):
            if buy_cap <= 0 or price > fv - ACO_TAKE_WIDTH:
                break
            if abs(vol) >= ACO_ADVERSE_VOL:
                continue
            qty = min(buy_cap, -vol)
            orders.append(Order(ACO, price, qty))
            buy_cap -= qty
            bought += qty

        for price, vol in sorted(book.buy_orders.items(), reverse=True):
            if sell_cap <= 0 or price < fv + ACO_TAKE_WIDTH:
                break
            if vol >= ACO_ADVERSE_VOL:
                continue
            qty = min(sell_cap, vol)
            orders.append(Order(ACO, price, -qty))
            sell_cap -= qty
            sold += qty

        # ─── Clear (flatten at FV) ─────────────────────────────────
        pos_after = pos + bought - sold
        if pos_after > 0 and sell_cap > 0:
            fair_for_ask = round(fv + ACO_CLEAR_WIDTH)
            clearable = sum(v for p, v in book.buy_orders.items() if p >= fair_for_ask)
            qty = min(pos_after, clearable, sell_cap)
            if qty > 0:
                orders.append(Order(ACO, fair_for_ask, -qty))
                sell_cap -= qty
                sold += qty
        elif pos_after < 0 and buy_cap > 0:
            fair_for_bid = round(fv - ACO_CLEAR_WIDTH)
            clearable = sum(-v for p, v in book.sell_orders.items() if p <= fair_for_bid)
            qty = min(-pos_after, clearable, buy_cap)
            if qty > 0:
                orders.append(Order(ACO, fair_for_bid, qty))
                buy_cap -= qty
                bought += qty

        # ─── Make (penny/join/default with soft-limit skew) ────────
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

        if pos > SOFT_LIMIT:
            ask_price -= 1
        elif pos < -SOFT_LIMIT:
            bid_price += 1

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        if buy_cap > 0:
            orders.append(Order(ACO, bid_price, buy_cap))
        if sell_cap > 0:
            orders.append(Order(ACO, ask_price, -sell_cap))

        return orders

    # ═══════════════════════════════════════════════════════════
    # IPR: r1_v2 logic (proven 10,536 on website)
    # ═══════════════════════════════════════════════════════════

    def _ipr(self, state):
        book = state.order_depths[IPR]
        has_bids = bool(book.buy_orders)
        has_asks = bool(book.sell_orders)

        if not (has_bids or has_asks):
            return []

        best_bid = max(book.buy_orders) if has_bids else None
        best_ask = min(book.sell_orders) if has_asks else None
        pos = state.position.get(IPR, 0)
        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos
        orders = []

        if has_bids and has_asks:
            mid = (best_bid + best_ask) * 0.5
            fv_int = round(mid + IPR_DRIFT_BIAS)

            # Asymmetric takes
            for price, vol in sorted(book.sell_orders.items()):
                if buy_cap > 0 and price <= fv_int + IPR_BUY_SLACK:
                    qty = min(buy_cap, -vol)
                    orders.append(Order(IPR, price, qty))
                    buy_cap -= qty

            for price, vol in sorted(book.buy_orders.items(), reverse=True):
                if sell_cap > 0 and price >= fv_int + IPR_SELL_SLACK:
                    qty = min(sell_cap, vol)
                    orders.append(Order(IPR, price, -qty))
                    sell_cap -= qty

            # Post: aggressive bid, defensive ask
            if buy_cap > 0:
                orders.append(Order(IPR, min(fv_int - 1, best_bid + 1, best_ask - 1), buy_cap))
            if sell_cap > 0:
                orders.append(Order(IPR, max(fv_int + 2, best_ask - 1, best_bid + 1), -sell_cap))

        else:
            # One-sided book
            if has_bids and not has_asks:
                if buy_cap > 0:
                    orders.append(Order(IPR, best_bid + 1, buy_cap))
                if sell_cap > 0:
                    orders.append(Order(IPR, best_bid + 14, -sell_cap))
            elif has_asks and not has_bids:
                if buy_cap > 0:
                    orders.append(Order(IPR, best_ask - 14, buy_cap))
                if sell_cap > 0:
                    orders.append(Order(IPR, best_ask - 1, -sell_cap))

        return orders

    def run(self, state: TradingState):
        result = {}
        if ACO in state.order_depths:
            result[ACO] = self._aco(state)
        if IPR in state.order_depths:
            result[IPR] = self._ipr(state)
        return result, 0, ""
