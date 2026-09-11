import json
from datamodel import Order, TradingState

"""
r1_hybrid — medallion regression + chess_fader posting

Inspired by the mentor's chess engine metaphor:
  "I spent decades calculating forced sequences on a chessboard."
  "Track those steps and you can narrow down what the next move is most likely to be."

CORE INSIGHT:
  IPR has AC(1) = -0.49 (confirmed across all 3 CSV days).
  In chess terms: every large price move is a "forced sequence" — the board
  MUST revert. A strong chess engine sees this immediately and plays the
  counter-move. We do the same.

  But IPR also has a +1000/day deterministic drift (the "opening theory"):
  the forced line that unfolds across the entire game.

STRATEGY:
  - Track cumulative recent moves (rolling sum of last N dmid values)
  - When cumulative move is strongly UP: post ASKS tighter (fade rally, drift bias stays)
  - When cumulative move is strongly DOWN: post BIDS tighter (fade dip, buy opportunity)
  - Always maintain long bias (drift bias = +5) — the endgame is always UP
  - "Brute force" FV = microprice + drift bias (no regression, just current book state)

  ACO: identical to r1_medallion (stable FV=10000, proven architecture)

Why this differs from r1_medallion:
  - r1_medallion uses lag-4 regression (looks back 4 ticks for smoothing)
  - This uses explicit AC(1) mean-reversion signal (looks at cumulative direction)
  - Posting asymmetry driven by detected rally/dip, not carry signal on bid moves only
  - The "forced sequence" window is wider (10 ticks) and triggers on CUMULATIVE move
"""

# ═══ INTARIAN_PEPPER_ROOT CONFIG ═══
IPR = "INTARIAN_PEPPER_ROOT"
IPR_LIMIT = 80
IPR_COEFS = [0.2474, 0.2529, 0.2412, 0.2585]
IPR_INTERCEPT = 0.2078
IPR_LAGS = 4
IPR_DRIFT_BIAS = 5.0
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3

# Forced-sequence (mean-reversion) parameters
IPR_FADE_WINDOW = 10          # Number of recent ticks to measure cumulative move
IPR_FADE_TRIGGER = 6          # Cumulative move > this = "forced reversion" signal
IPR_FADE_TIGHT = 1            # Tighter posting offset when fading (inside best±1)
IPR_FADE_WIDE = 3             # Wider posting offset on the faded side
IPR_AGGRESSION_THRESHOLD = 60 # Position threshold for aggression

# OBI shift (volume imbalance)
IPR_OBI_SHIFT = 0.5

# ═══ ASH_COATED_OSMIUM CONFIG ═══
ACO = "ASH_COATED_OSMIUM"
ACO_LIMIT = 80
ACO_FV = 10000
ACO_AGGRESSION_THRESHOLD = 40
ACO_LIQUIDATION_WINDOW = 10


class Trader:
    def __init__(self):
        self.ipr_mp = []         # Microprice history for regression
        self.ipr_mids = []       # Rolling mid history for fade detection
        self.aco_liq = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.ipr_mp = saved.get("p", [])
            self.ipr_mids = saved.get("m", [])
            self.aco_liq = saved.get("l", [])

        result = {}
        conversions = 0

        # ═══════════════════════════════════════════════════
        # ASH_COATED_OSMIUM — identical to r1_medallion (proven)
        # ═══════════════════════════════════════════════════
        if ACO in state.order_depths:
            book = state.order_depths[ACO]
            has_bids = bool(book.buy_orders)
            has_asks = bool(book.sell_orders)

            if has_bids or has_asks:
                orders = []
                pos = state.position.get(ACO, 0)
                buy_cap = ACO_LIMIT - pos
                sell_cap = ACO_LIMIT + pos
                fv_int = ACO_FV

                best_bid = max(book.buy_orders) if has_bids else None
                best_ask = min(book.sell_orders) if has_asks else None

                self.aco_liq.append(abs(pos) == ACO_LIMIT)
                if len(self.aco_liq) > ACO_LIQUIDATION_WINDOW:
                    self.aco_liq = self.aco_liq[-ACO_LIQUIDATION_WINDOW:]
                soft = (len(self.aco_liq) == ACO_LIQUIDATION_WINDOW
                        and sum(self.aco_liq) >= 5 and self.aco_liq[-1])
                hard = (len(self.aco_liq) == ACO_LIQUIDATION_WINDOW
                        and all(self.aco_liq))

                max_buy = fv_int if pos <= ACO_AGGRESSION_THRESHOLD else fv_int - 1
                min_sell = fv_int if pos >= -ACO_AGGRESSION_THRESHOLD else fv_int + 1

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

                if buy_cap > 0 and hard:
                    orders.append(Order(ACO, fv_int, buy_cap // 2))
                    buy_cap -= buy_cap // 2
                if buy_cap > 0 and soft:
                    orders.append(Order(ACO, fv_int - 2, buy_cap // 2))
                    buy_cap -= buy_cap // 2
                if sell_cap > 0 and hard:
                    orders.append(Order(ACO, fv_int, -(sell_cap // 2)))
                    sell_cap -= sell_cap // 2
                if sell_cap > 0 and soft:
                    orders.append(Order(ACO, fv_int + 2, -(sell_cap // 2)))
                    sell_cap -= sell_cap // 2

                if has_bids and has_asks:
                    if buy_cap > 0:
                        bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                        orders.append(Order(ACO, bp, buy_cap))
                    if sell_cap > 0:
                        ap = max(fv_int + 1, best_ask - 1, best_bid + 1)
                        orders.append(Order(ACO, ap, -sell_cap))
                elif has_bids:
                    if buy_cap > 0:
                        orders.append(Order(ACO, min(fv_int - 1, best_bid + 1), buy_cap))
                    if sell_cap > 0:
                        orders.append(Order(ACO, fv_int + 1, -sell_cap))
                elif has_asks:
                    if sell_cap > 0:
                        orders.append(Order(ACO, max(fv_int + 1, best_ask - 1), -sell_cap))
                    if buy_cap > 0:
                        orders.append(Order(ACO, fv_int - 1, buy_cap))

                result[ACO] = orders

        # ═══════════════════════════════════════════════════
        # INTARIAN_PEPPER_ROOT — "Forced Sequence" Fader
        # ═══════════════════════════════════════════════════
        if IPR in state.order_depths:
            book = state.order_depths[IPR]
            has_bids = bool(book.buy_orders)
            has_asks = bool(book.sell_orders)

            if has_bids or has_asks:
                orders = []
                pos = state.position.get(IPR, 0)
                buy_cap = IPR_LIMIT - pos
                sell_cap = IPR_LIMIT + pos

                best_bid = max(book.buy_orders) if has_bids else None
                best_ask = min(book.sell_orders) if has_asks else None

                if has_bids and has_asks:
                    mid = (best_bid + best_ask) * 0.5

                    # ── Fair Value: microprice + OBI + drift bias ──
                    total_bv = sum(book.buy_orders.values())
                    total_av = sum(-v for v in book.sell_orders.values())
                    if total_bv + total_av > 0:
                        mp = best_bid + (total_bv / (total_bv + total_av)) * (best_ask - best_bid)
                        obi = (total_bv - total_av) / (total_bv + total_av)
                    else:
                        mp = mid
                        obi = 0.0

                    # Regression FV (from r1_medallion)
                    hist = self.ipr_mp
                    if len(hist) >= IPR_LAGS:
                        hist = hist[1:]
                    hist.append(mp)
                    self.ipr_mp = hist

                    if len(hist) == IPR_LAGS:
                        fv = IPR_INTERCEPT + sum(c * x for c, x in zip(IPR_COEFS, hist))
                    else:
                        fv = mp

                    fv += obi * IPR_OBI_SHIFT + IPR_DRIFT_BIAS
                    fv_int = round(fv)

                    # ── Forced Sequence Detection ──
                    # Track rolling mid, compute cumulative move over window
                    self.ipr_mids.append(mid)
                    if len(self.ipr_mids) > IPR_FADE_WINDOW + 1:
                        self.ipr_mids = self.ipr_mids[-(IPR_FADE_WINDOW + 1):]

                    # Cumulative move over the window
                    if len(self.ipr_mids) >= 2:
                        cum_move = self.ipr_mids[-1] - self.ipr_mids[0]
                    else:
                        cum_move = 0.0

                    # Classify the "forced sequence" state
                    # Strongly UP = market overextended = forced reversion DOWN
                    # Strongly DOWN = market oversold = forced reversion UP
                    rally_detected = cum_move > IPR_FADE_TRIGGER
                    dip_detected = cum_move < -IPR_FADE_TRIGGER

                    # ── Asymmetric Takes (always long-biased) ──
                    buy_thresh = fv_int + IPR_BUY_SLACK
                    sell_thresh = fv_int + IPR_SELL_SLACK

                    for price, vol in sorted(book.sell_orders.items()):
                        if buy_cap > 0 and price <= buy_thresh:
                            qty = min(buy_cap, -vol)
                            orders.append(Order(IPR, price, qty))
                            buy_cap -= qty

                    for price, vol in sorted(book.buy_orders.items(), reverse=True):
                        if sell_cap > 0 and price >= sell_thresh:
                            qty = min(sell_cap, vol)
                            orders.append(Order(IPR, price, -qty))
                            sell_cap -= qty

                    # ── Posting: respond to forced sequence ──
                    if rally_detected:
                        # Market moved strongly UP → forced reversion DOWN expected
                        # Chess move: post ASKS tight (sell into the rally)
                        # Keep bids wide (don't buy at top)
                        if sell_cap > 0:
                            # Tight ask: inside best ask, near FV
                            ap = max(fv_int + IPR_FADE_TIGHT, best_bid + 1)
                            ap = min(ap, best_ask)
                            orders.append(Order(IPR, ap, -sell_cap))
                        if buy_cap > 0:
                            # Wide bid: below FV to catch the reversion
                            bp = min(fv_int - IPR_FADE_WIDE, best_bid)
                            bp = max(bp, best_bid - IPR_FADE_WIDE)
                            orders.append(Order(IPR, bp, buy_cap))

                    elif dip_detected:
                        # Market moved strongly DOWN → forced reversion UP expected
                        # Chess move: post BIDS tight (buy the dip aggressively)
                        # Keep asks wide (don't sell at bottom)
                        if buy_cap > 0:
                            # Tight bid: inside best bid, near FV
                            bp = min(fv_int - IPR_FADE_TIGHT, best_ask - 1)
                            bp = max(bp, best_bid)
                            orders.append(Order(IPR, bp, buy_cap))
                        if sell_cap > 0:
                            # Wide ask: above FV, wait for reversion to complete
                            ap = max(fv_int + IPR_FADE_WIDE, best_ask)
                            ap = min(ap, best_ask + IPR_FADE_WIDE)
                            orders.append(Order(IPR, ap, -sell_cap))

                    else:
                        # No forced sequence detected — standard long-biased posting
                        if buy_cap > 0:
                            bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                            orders.append(Order(IPR, bp, buy_cap))
                        if sell_cap > 0:
                            # Extra wide ask (long bias, don't want to sell)
                            ap = max(fv_int + 2, best_ask - 1, best_bid + 1)
                            orders.append(Order(IPR, ap, -sell_cap))

                else:
                    # One-sided book handling
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
            {"p": self.ipr_mp, "m": self.ipr_mids, "l": self.aco_liq},
            separators=(",", ":")
        )