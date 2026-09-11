import json
from datamodel import Order, TradingState

"""
r1_strat_v2 — Round 1 Strategy (based on r1_strat, website: 10,445)

Advisor-hint-aligned improvements over r1_strat:

  1. REPLACED: Fixed IPR_DRIFT_BIAS=6.0 with rolling drift estimate
     - "Recalculate" (chess engine) = update the drift as the game unfolds
     - IPR drifts +1000/day but rate varies across the session
     - Rolling estimate adapts; fixed constant doesn't
     - Volume-independent (uses only mid prices), safe for website

  2. ADDED: AC(1) fade signal for IPR posting
     - "Forced sequences" (chess engine): after large cumulative moves,
       AC(1)=-0.50 guarantees partial reversion
     - After rally: tighter asks (sell into strength), wider bids
     - After dip: tighter bids (buy weakness), wider asks
     - Applied to POSTING only (takes unchanged)

  3. KEPT everything else identical to r1_strat:
     - No OBI, no trade flow, no carry (all 0% PnL per ablation)
     - ACO: take at FV=10000, post best+-1, one-sided handling
     - Lean traderData format

  DRIFT_HORIZON = 5: Orin says "easier to reason about... further ahead"
  FADE is structural (AC1=-0.50 is stable across all CSV days)
"""

# ═══ IPR CONFIG ═══
IPR = "INTARIAN_PEPPER_ROOT"
IPR_LIMIT = 80
IPR_COEFS = [0.2474, 0.2529, 0.2412, 0.2585]
IPR_INTERCEPT = 0.2078
IPR_LAGS = 4
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3

# Rolling drift (replaces fixed IPR_DRIFT_BIAS=6.0)
IPR_DRIFT_WINDOW = 50
IPR_DRIFT_HORIZON = 5     # "Further ahead" per Orin
IPR_DRIFT_DEFAULT = 0.1   # ~+1000/10000 ticks fallback

# Forced-sequence fade parameters
IPR_FADE_WINDOW = 10      # Cumulative move measurement window
IPR_FADE_TRIGGER = 6      # |cum_move| > this = forced reversion
IPR_FADE_TIGHT = 1        # Tighter offset on continuation side
IPR_FADE_WIDE = 3         # Wider offset on faded side

# ═══ ACO CONFIG ═══
ACO = "ASH_COATED_OSMIUM"
ACO_LIMIT = 80
ACO_FV = 10000
ACO_AGGRESSION_THRESHOLD = 40
ACO_LIQUIDATION_WINDOW = 10


class Trader:
    def __init__(self):
        self.ipr_mp = []
        self.ipr_mids = []   # Mid history for drift + fade
        self.aco_liq = []

    def bid(self):
        return 15

    def _estimate_drift(self):
        """
        Rolling drift rate from pure mid prices.
        Volume-independent, safe for website.
        """
        mids = self.ipr_mids
        if len(mids) < IPR_DRIFT_WINDOW:
            return IPR_DRIFT_DEFAULT
        recent = mids[-IPR_DRIFT_WINDOW:]
        return (recent[-1] - recent[0]) / len(recent)

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.ipr_mp = saved.get("m", [])
            self.ipr_mids = saved.get("d", [])
            self.aco_liq = saved.get("l", [])

        result = {}
        conversions = 0

        # ═══ ACO: take at FV, post best+-1 (unchanged from r1_strat) ═══
        if ACO in state.order_depths:
            book = state.order_depths[ACO]
            has_bids = bool(book.buy_orders)
            has_asks = bool(book.sell_orders)

            if has_bids or has_asks:
                orders = []
                pos = state.position.get(ACO, 0)
                buy_cap = ACO_LIMIT - pos
                sell_cap = ACO_LIMIT + pos
                fv = ACO_FV
                best_bid = max(book.buy_orders) if has_bids else None
                best_ask = min(book.sell_orders) if has_asks else None

                self.aco_liq.append(abs(pos) == ACO_LIMIT)
                if len(self.aco_liq) > ACO_LIQUIDATION_WINDOW:
                    self.aco_liq = self.aco_liq[-ACO_LIQUIDATION_WINDOW:]
                soft = (len(self.aco_liq) == ACO_LIQUIDATION_WINDOW
                        and sum(self.aco_liq) >= 5 and self.aco_liq[-1])
                hard = (len(self.aco_liq) == ACO_LIQUIDATION_WINDOW
                        and all(self.aco_liq))

                max_buy = fv if pos <= ACO_AGGRESSION_THRESHOLD else fv - 1
                min_sell = fv if pos >= -ACO_AGGRESSION_THRESHOLD else fv + 1

                # Take
                if has_asks:
                    for price, vol in sorted(book.sell_orders.items()):
                        if buy_cap > 0 and price <= max_buy:
                            qty = min(buy_cap, -vol)
                            orders.append(Order(ACO, price, qty))
                            buy_cap -= qty

                if has_bids:
                    for price, vol in sorted(book.buy_orders.items(), reverse=True):
                        if sell_cap > 0 and price >= min_sell:
                            qty = min(sell_cap, vol)
                            orders.append(Order(ACO, price, -qty))
                            sell_cap -= qty

                # Liquidation
                if buy_cap > 0 and hard:
                    orders.append(Order(ACO, fv, buy_cap // 2))
                    buy_cap -= buy_cap // 2
                if buy_cap > 0 and soft:
                    orders.append(Order(ACO, fv - 2, buy_cap // 2))
                    buy_cap -= buy_cap // 2
                if sell_cap > 0 and hard:
                    orders.append(Order(ACO, fv, -(sell_cap // 2)))
                    sell_cap -= sell_cap // 2
                if sell_cap > 0 and soft:
                    orders.append(Order(ACO, fv + 2, -(sell_cap // 2)))
                    sell_cap -= sell_cap // 2

                # Post
                if has_bids and has_asks:
                    if buy_cap > 0:
                        orders.append(Order(ACO, min(fv - 1, best_bid + 1, best_ask - 1), buy_cap))
                    if sell_cap > 0:
                        orders.append(Order(ACO, max(fv + 1, best_ask - 1, best_bid + 1), -sell_cap))
                elif has_bids:
                    if buy_cap > 0:
                        orders.append(Order(ACO, min(fv - 1, best_bid + 1), buy_cap))
                    if sell_cap > 0:
                        orders.append(Order(ACO, fv + 1, -sell_cap))
                elif has_asks:
                    if sell_cap > 0:
                        orders.append(Order(ACO, max(fv + 1, best_ask - 1), -sell_cap))
                    if buy_cap > 0:
                        orders.append(Order(ACO, fv - 1, buy_cap))

                result[ACO] = orders

        # ═══ IPR: regression + rolling drift + fade posting ═══
        if IPR in state.order_depths:
            book = state.order_depths[IPR]
            has_bids = bool(book.buy_orders)
            has_asks = bool(book.sell_orders)

            if has_bids or has_asks:
                orders = []
                best_bid = max(book.buy_orders) if has_bids else None
                best_ask = min(book.sell_orders) if has_asks else None
                pos = state.position.get(IPR, 0)

                if has_bids and has_asks:
                    mid = (best_bid + best_ask) * 0.5
                    total_bv = sum(book.buy_orders.values())
                    total_av = sum(-v for v in book.sell_orders.values())
                    mp = (best_bid + (total_bv / (total_bv + total_av)) * (best_ask - best_bid)
                          if (total_bv + total_av) > 0 else mid)

                    # Update histories
                    hist = self.ipr_mp
                    if len(hist) >= IPR_LAGS:
                        hist = hist[1:]
                    hist.append(mp)
                    self.ipr_mp = hist

                    self.ipr_mids.append(mid)
                    max_keep = IPR_DRIFT_WINDOW + 10
                    if len(self.ipr_mids) > max_keep:
                        self.ipr_mids = self.ipr_mids[-max_keep:]

                    # FV: fixed regression (unchanged)
                    if len(hist) == IPR_LAGS:
                        fv = IPR_INTERCEPT + sum(c * x for c, x in zip(IPR_COEFS, hist))
                    else:
                        fv = mp

                    # Rolling drift (replaces fixed DRIFT_BIAS=6.0)
                    drift_rate = self._estimate_drift()
                    fv += drift_rate * IPR_DRIFT_HORIZON
                    fv_int = round(fv)

                    buy_cap = IPR_LIMIT - pos
                    sell_cap = IPR_LIMIT + pos

                    # Takes (unchanged from r1_strat)
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

                    # Forced-sequence fade detection
                    if len(self.ipr_mids) >= 2:
                        w_start = max(0, len(self.ipr_mids) - IPR_FADE_WINDOW - 1)
                        cum_move = self.ipr_mids[-1] - self.ipr_mids[w_start]
                    else:
                        cum_move = 0.0

                    rally = cum_move > IPR_FADE_TRIGGER
                    dip = cum_move < -IPR_FADE_TRIGGER

                    # Posting: fade-aware
                    if rally:
                        # After rally: tighter asks (sell into strength), wider bids
                        if sell_cap > 0:
                            ap = max(fv_int + IPR_FADE_TIGHT, best_bid + 1)
                            ap = min(ap, best_ask)
                            orders.append(Order(IPR, ap, -sell_cap))
                        if buy_cap > 0:
                            bp = min(fv_int - IPR_FADE_WIDE, best_bid)
                            orders.append(Order(IPR, bp, buy_cap))
                    elif dip:
                        # After dip: tighter bids (buy weakness), wider asks
                        if buy_cap > 0:
                            bp = min(fv_int - IPR_FADE_TIGHT, best_ask - 1)
                            bp = max(bp, best_bid)
                            orders.append(Order(IPR, bp, buy_cap))
                        if sell_cap > 0:
                            ap = max(fv_int + IPR_FADE_WIDE, best_ask)
                            orders.append(Order(IPR, ap, -sell_cap))
                    else:
                        # Standard: aggressive bid, defensive ask
                        if buy_cap > 0:
                            orders.append(Order(IPR, min(fv_int - 1, best_bid + 1, best_ask - 1), buy_cap))
                        if sell_cap > 0:
                            orders.append(Order(IPR, max(fv_int + 2, best_ask - 1, best_bid + 1), -sell_cap))

                else:
                    # One-sided book (unchanged)
                    buy_cap = IPR_LIMIT - pos
                    sell_cap = IPR_LIMIT + pos
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

                result[IPR] = orders

        return result, conversions, json.dumps(
            {"m": self.ipr_mp, "d": self.ipr_mids[-60:],
             "l": self.aco_liq},
            separators=(",", ":")
        )
