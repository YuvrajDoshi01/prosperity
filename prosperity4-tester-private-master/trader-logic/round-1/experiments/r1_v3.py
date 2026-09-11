import json
from datamodel import Order, TradingState

"""
r1_v3 — Round 1 Strategy (Linear Utility framework + drift projection)

Mixes:
- Linear Utility (P2 #2 finish) take→clear→make pipeline with exact AMETHYSTS params
- Filtered-MM-mid FV (volume≥15 adverse filter) from LU's STARFRUIT logic
- Time-linear drift projection (slope=0.001, derived from +100/100k tick drift)
- EMA smoothing of detrended base (alpha=0.1)
- Soft-limit quote skew (shift 1 tick toward neutral at |pos|>SOFT_LIMIT)

Every parameter is either derived from market structure or copied from LU's
validated P2 #2 finish. Zero params came from backtester tuning.

Reference scores:
  r1_v2    10,536.81 (website)
  TROLL    ~10,600  (website, more sophisticated)
  Target   10,600+
"""

# ═══ CONSTANTS (all derived or LU-validated) ═══
LIMIT = 80
ADVERSE_VOL = 15        # LU exact — toxic-size filter
SOFT_LIMIT = 40         # 0.5 × LIMIT, scaled from LU's 10/20 ratio

# Linear Utility posting knobs (same for both products per LU AMETHYSTS)
TAKE_WIDTH = 1          # LU exact
CLEAR_WIDTH = 0         # LU exact — flatten at FV
DISREGARD_EDGE = 1      # LU exact
JOIN_EDGE = 2           # LU exact
DEFAULT_EDGE = 4        # LU exact

# IPR-specific (drift)
IPR = "INTARIAN_PEPPER_ROOT"
IPR_SLOPE = 0.001       # DERIVED: +100 drift / 100,000 ticks
IPR_EMA_ALPHA = 0.1     # round number, mild smoothing
IPR_SELL_EDGE = 6       # DERIVED: TAKE_WIDTH + 5, asymmetric for drift (resist selling long)

# ACO-specific
ACO = "ASH_COATED_OSMIUM"
ACO_FV = 10000          # structural


class Trader:
    def __init__(self):
        self.ipr_base = None  # EMA of detrended filtered-mm-mid

    def bid(self):
        return 15

    # ═══════════════════════════════════════════════════════════
    # Fair-value helpers
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _filtered_mm_mid(book, fallback_mid):
        """Linear Utility STARFRUIT-style: volume-filtered MM mid.
        Returns (filtered_asks[p]>=ADVERSE + filtered_bids[p]>=ADVERSE) / 2
        or fallback raw mid if either side has no large levels."""
        filt_asks = [p for p, v in book.sell_orders.items() if abs(v) >= ADVERSE_VOL]
        filt_bids = [p for p, v in book.buy_orders.items() if v >= ADVERSE_VOL]
        if filt_asks and filt_bids:
            return (min(filt_asks) + max(filt_bids)) / 2.0
        return fallback_mid

    def _ipr_fv(self, book, timestamp):
        """Time-linear drift projection on EMA-smoothed filtered-mm-mid."""
        if not (book.buy_orders and book.sell_orders):
            return None
        raw_mid = (max(book.buy_orders) + min(book.sell_orders)) / 2.0
        mmmid = self._filtered_mm_mid(book, raw_mid)
        detrended = mmmid - IPR_SLOPE * timestamp
        if self.ipr_base is None:
            self.ipr_base = detrended
        else:
            self.ipr_base = (1 - IPR_EMA_ALPHA) * self.ipr_base + IPR_EMA_ALPHA * detrended
        return self.ipr_base + IPR_SLOPE * timestamp

    # ═══════════════════════════════════════════════════════════
    # Take → Clear → Make pipeline
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _take(symbol, book, fv, pos, adverse_gate=True):
        """Take crossing orders. Returns (orders, bought, sold)."""
        orders = []
        bought = sold = 0
        buy_cap = LIMIT - pos
        sell_cap = LIMIT + pos

        take_threshold_ask = fv - TAKE_WIDTH  # buy if ask <= fv - 1
        take_threshold_bid = fv + TAKE_WIDTH  # sell if bid >= fv + 1

        if book.sell_orders:
            for price, vol in sorted(book.sell_orders.items()):
                if buy_cap <= 0 or price > take_threshold_ask:
                    break
                if adverse_gate and abs(vol) >= ADVERSE_VOL:
                    continue
                qty = min(buy_cap, -vol)
                orders.append(Order(symbol, price, qty))
                buy_cap -= qty
                bought += qty

        if book.buy_orders:
            for price, vol in sorted(book.buy_orders.items(), reverse=True):
                if sell_cap <= 0 or price < take_threshold_bid:
                    break
                if adverse_gate and vol >= ADVERSE_VOL:
                    continue
                qty = min(sell_cap, vol)
                orders.append(Order(symbol, price, -qty))
                sell_cap -= qty
                sold += qty

        return orders, bought, sold

    @staticmethod
    def _clear(symbol, book, fv, pos, bought, sold, clear_width=CLEAR_WIDTH):
        """Flatten position by taking opposing book at fv±clear_width.
        Linear Utility canonical: clear_width=0 → flatten exactly at FV."""
        orders = []
        pos_after = pos + bought - sold
        buy_cap = LIMIT - (pos + bought)
        sell_cap = LIMIT + (pos - sold)

        if pos_after > 0 and sell_cap > 0:
            fair_for_ask = round(fv + clear_width)
            clearable = sum(v for p, v in book.buy_orders.items() if p >= fair_for_ask)
            qty = min(pos_after, clearable, sell_cap)
            if qty > 0:
                orders.append(Order(symbol, fair_for_ask, -qty))
                sold += qty

        elif pos_after < 0 and buy_cap > 0:
            fair_for_bid = round(fv - clear_width)
            clearable = sum(-v for p, v in book.sell_orders.items() if p <= fair_for_bid)
            qty = min(-pos_after, clearable, buy_cap)
            if qty > 0:
                orders.append(Order(symbol, fair_for_bid, qty))
                bought += qty

        return orders, bought, sold

    @staticmethod
    def _make(symbol, book, fv, pos, bought, sold):
        """Penny/join/default posting with soft-limit skew."""
        orders = []
        buy_cap = LIMIT - (pos + bought)
        sell_cap = LIMIT + (pos - sold)

        # Find reference inside market (excluding prices within DISREGARD_EDGE of fv)
        asks_above = [p for p in book.sell_orders if p > fv + DISREGARD_EDGE]
        bids_below = [p for p in book.buy_orders if p < fv - DISREGARD_EDGE]

        # Ask price
        if asks_above:
            best_ref_ask = min(asks_above)
            if best_ref_ask - fv <= JOIN_EDGE:
                ask_price = best_ref_ask      # join
            else:
                ask_price = best_ref_ask - 1  # penny
        else:
            ask_price = round(fv + DEFAULT_EDGE)

        # Bid price
        if bids_below:
            best_ref_bid = max(bids_below)
            if fv - best_ref_bid <= JOIN_EDGE:
                bid_price = best_ref_bid      # join
            else:
                bid_price = best_ref_bid + 1  # penny
        else:
            bid_price = round(fv - DEFAULT_EDGE)

        # Soft-limit skew (lean opposite of position toward neutral)
        if pos > SOFT_LIMIT:
            ask_price -= 1
        elif pos < -SOFT_LIMIT:
            bid_price += 1

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        if buy_cap > 0:
            orders.append(Order(symbol, bid_price, buy_cap))
        if sell_cap > 0:
            orders.append(Order(symbol, ask_price, -sell_cap))

        return orders

    # ═══════════════════════════════════════════════════════════
    # Entry point
    # ═══════════════════════════════════════════════════════════

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved and "b" in saved:
            self.ipr_base = saved["b"]

        result = {}

        # ─── ACO: Linear Utility AMETHYSTS port ────────────────────
        if ACO in state.order_depths:
            book = state.order_depths[ACO]
            if book.buy_orders or book.sell_orders:
                pos = state.position.get(ACO, 0)
                fv = ACO_FV
                take_ords, bought, sold = self._take(ACO, book, fv, pos, adverse_gate=True)
                clear_ords, bought, sold = self._clear(ACO, book, fv, pos, bought, sold)
                make_ords = self._make(ACO, book, fv, pos, bought, sold)
                result[ACO] = take_ords + clear_ords + make_ords

        # ─── IPR: LU framework + drift projection ──────────────────
        if IPR in state.order_depths:
            book = state.order_depths[IPR]
            has_bids = bool(book.buy_orders)
            has_asks = bool(book.sell_orders)

            if has_bids and has_asks:
                fv = self._ipr_fv(book, state.timestamp)
                pos = state.position.get(IPR, 0)

                # IPR uses asymmetric take (drift-favored): sell only if bid >> fv
                take_ords = []
                bought = sold = 0
                buy_cap = LIMIT - pos
                sell_cap = LIMIT + pos

                # Buy side: standard LU take
                for price, vol in sorted(book.sell_orders.items()):
                    if buy_cap <= 0 or price > fv - TAKE_WIDTH:
                        break
                    if abs(vol) >= ADVERSE_VOL:
                        continue
                    qty = min(buy_cap, -vol)
                    take_ords.append(Order(IPR, price, qty))
                    buy_cap -= qty
                    bought += qty

                # Sell side: asymmetric — only if bid well above fv
                for price, vol in sorted(book.buy_orders.items(), reverse=True):
                    if sell_cap <= 0 or price < fv + IPR_SELL_EDGE:
                        break
                    if vol >= ADVERSE_VOL:
                        continue
                    qty = min(sell_cap, vol)
                    take_ords.append(Order(IPR, price, -qty))
                    sell_cap -= qty
                    sold += qty

                # Clear IPR only if oversized (don't fight the drift for normal positions)
                clear_ords = []
                pos_after = pos + bought - sold
                if pos_after > SOFT_LIMIT and sell_cap > 0:
                    # Only sell if bids are well above fv (SELL_EDGE) — drift-aware
                    fair_for_ask = round(fv + IPR_SELL_EDGE)
                    clearable = sum(v for p, v in book.buy_orders.items() if p >= fair_for_ask)
                    qty = min(pos_after - SOFT_LIMIT, clearable, sell_cap)
                    if qty > 0:
                        clear_ords.append(Order(IPR, fair_for_ask, -qty))
                        sold += qty
                elif pos_after < -SOFT_LIMIT and buy_cap > 0:
                    fair_for_bid = round(fv - TAKE_WIDTH)
                    clearable = sum(-v for p, v in book.sell_orders.items() if p <= fair_for_bid)
                    qty = min(-pos_after - SOFT_LIMIT, clearable, buy_cap)
                    if qty > 0:
                        clear_ords.append(Order(IPR, fair_for_bid, qty))
                        bought += qty

                make_ords = self._make(IPR, book, fv, pos, bought, sold)
                result[IPR] = take_ords + clear_ords + make_ords

            elif has_bids or has_asks:
                # One-sided book — conservative single-side post
                pos = state.position.get(IPR, 0)
                buy_cap = LIMIT - pos
                sell_cap = LIMIT + pos
                orders = []
                if has_bids:
                    best_bid = max(book.buy_orders)
                    if buy_cap > 0:
                        orders.append(Order(IPR, best_bid + 1, buy_cap))
                    if sell_cap > 0:
                        orders.append(Order(IPR, best_bid + 14, -sell_cap))
                else:
                    best_ask = min(book.sell_orders)
                    if buy_cap > 0:
                        orders.append(Order(IPR, best_ask - 14, buy_cap))
                    if sell_cap > 0:
                        orders.append(Order(IPR, best_ask - 1, -sell_cap))
                result[IPR] = orders

        return result, 0, json.dumps({"b": self.ipr_base}, separators=(",", ":"))
