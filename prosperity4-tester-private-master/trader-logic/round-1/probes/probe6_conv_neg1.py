import json
from datamodel import Order, TradingState

"""
probe6_conv_neg1 — Round 1 Strategy (website: 10,444)

INTARIAN_PEPPER_ROOT (IPR):
  - Full-book microprice lag-4 regression FV (coefs ~0.25 uniform, cross-val 3 days)
  - Full-book OBI shift (+0.5) — NOTE: double-counts with microprice weighting
  - Trade flow signal (coef=1.5, window=5, norm=15)
  - Carry signal: mean-reversion posting after large bid moves (trigger=4, decay=0.7)
  - Drift bias: FV shifted +5 to exploit deterministic +100/1k uptrend
  - Asymmetric takes: buy at FV+2, sell only at FV+3 (long bias)
  - Position aggression at |pos| > 60
  - One-sided book handling (9% of ticks)
  - NO terminal flattening (drift makes selling at end anti-alpha)

ASH_COATED_OSMIUM (ACO):
  - Fixed FV = 10000 (no OBI, no regression — kept simple)
  - Take at FV, post at best+/-1
  - Self-position-limit tracker (10-tick window): detects when stuck at +/-80
    soft = 5+ of last 10 ticks at limit, hard = all 10. Posts liquidation orders.
  - Position-dependent take aggression at |pos| > 40
  - One-sided book handling: sole liquidity on missing side
  - NO terminal flattening (inventory carry is +EV for O-U)
  - O-U directional takes were TESTED and REVERTED (net negative on backtester)

bid() returns 15 for the Round 1 manual auction challenge.
"""

# ═══ INTARIAN_PEPPER_ROOT CONFIG ═══
IPR = "INTARIAN_PEPPER_ROOT"
IPR_LIMIT = 80
IPR_COEFS = [0.2474, 0.2529, 0.2412, 0.2585]  # Cross-validated 3 days
IPR_INTERCEPT = 0.2078
IPR_LAGS = 4
IPR_TRADE_FLOW_COEF = 1.5
IPR_TRADE_FLOW_WINDOW = 5
IPR_TRADE_FLOW_NORM = 15.0
IPR_OBI_SHIFT = 0.5
IPR_CARRY_TRIGGER = 4
IPR_CARRY_DECAY = 0.7
IPR_CARRY_THRESHOLD = 0.5
IPR_CARRY_WIDE = 3
IPR_AGGRESSION_THRESHOLD = 60
IPR_DRIFT_BIAS = 5.0  # FV shift up to exploit deterministic +100/1k drift
IPR_BUY_SLACK = 2     # Take asks up to FV+2
IPR_SELL_SLACK = 3    # Only take bids at FV+3 or above

# ═══ ASH_COATED_OSMIUM CONFIG ═══
ACO = "ASH_COATED_OSMIUM"
ACO_LIMIT = 80
ACO_FV = 10000
ACO_AGGRESSION_THRESHOLD = 40
ACO_LIQUIDATION_WINDOW = 10


class Trader:
    def __init__(self):
        self.ipr_mp = []
        self.ipr_tf = []
        self.ipr_pb = None
        self.ipr_carry = 0.0
        self.aco_liq = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.ipr_mp = saved.get("m", [])
            self.ipr_tf = saved.get("f", [])
            self.ipr_pb = saved.get("b")
            self.ipr_carry = saved.get("c", 0.0)
            self.aco_liq = saved.get("l", [])

        result = {}
        conversions = -1

        # ═══════════════════════════════════════════════════
        # ASH_COATED_OSMIUM — FV=10000, take at FV, post best±1
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

                # Liquidation tracking (self-position-limit detection)
                self.aco_liq.append(abs(pos) == ACO_LIMIT)
                if len(self.aco_liq) > ACO_LIQUIDATION_WINDOW:
                    self.aco_liq = self.aco_liq[-ACO_LIQUIDATION_WINDOW:]
                soft = (len(self.aco_liq) == ACO_LIQUIDATION_WINDOW
                        and sum(self.aco_liq) >= 5 and self.aco_liq[-1])
                hard = (len(self.aco_liq) == ACO_LIQUIDATION_WINDOW
                        and all(self.aco_liq))

                # Position-dependent aggression
                max_buy = fv_int if pos <= ACO_AGGRESSION_THRESHOLD else fv_int - 1
                min_sell = fv_int if pos >= -ACO_AGGRESSION_THRESHOLD else fv_int + 1

                # TAKE: buy asks at/below FV
                if has_asks:
                    for price, vol in sorted(book.sell_orders.items()):
                        if buy_cap > 0 and price <= max_buy:
                            qty = min(buy_cap, -vol)
                            orders.append(Order(ACO, price, qty))
                            buy_cap -= qty

                # TAKE: sell bids at/above FV
                if has_bids:
                    for price, vol in sorted(book.buy_orders.items(), reverse=True):
                        if sell_cap > 0 and price >= min_sell:
                            qty = min(sell_cap, vol)
                            orders.append(Order(ACO, price, -qty))
                            sell_cap -= qty

                # Liquidation orders
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

                # POST: best±1 with one-sided book handling
                if has_bids and has_asks:
                    if buy_cap > 0:
                        bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                        orders.append(Order(ACO, bp, buy_cap))
                    if sell_cap > 0:
                        ap = max(fv_int + 1, best_ask - 1, best_bid + 1)
                        orders.append(Order(ACO, ap, -sell_cap))
                elif has_bids:
                    if buy_cap > 0:
                        bp = min(fv_int - 1, best_bid + 1)
                        orders.append(Order(ACO, bp, buy_cap))
                    if sell_cap > 0:
                        orders.append(Order(ACO, fv_int + 1, -sell_cap))
                elif has_asks:
                    if sell_cap > 0:
                        ap = max(fv_int + 1, best_ask - 1)
                        orders.append(Order(ACO, ap, -sell_cap))
                    if buy_cap > 0:
                        orders.append(Order(ACO, fv_int - 1, buy_cap))

                result[ACO] = orders

        # ═══════════════════════════════════════════════════
        # INTARIAN_PEPPER_ROOT — Regression FV + carry signal
        # ═══════════════════════════════════════════════════
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

                    # Microprice regression
                    total_bv = sum(book.buy_orders.values())
                    total_av = sum(-v for v in book.sell_orders.values())
                    mp = (best_bid + (total_bv / (total_bv + total_av)) * (best_ask - best_bid)
                          if (total_bv + total_av) > 0 else mid)

                    hist = self.ipr_mp
                    if len(hist) >= IPR_LAGS:
                        hist = hist[1:]
                    hist.append(mp)
                    self.ipr_mp = hist

                    if len(hist) == IPR_LAGS:
                        fv = IPR_INTERCEPT + sum(c * x for c, x in zip(IPR_COEFS, hist))
                    else:
                        fv = mp

                    # Trade flow
                    mt = state.market_trades.get(IPR)
                    if mt:
                        nf = sum(t.quantity if t.price >= mid else -t.quantity for t in mt)
                        self.ipr_tf.append(nf)
                    else:
                        self.ipr_tf.append(0.0)
                    if len(self.ipr_tf) > IPR_TRADE_FLOW_WINDOW:
                        self.ipr_tf = self.ipr_tf[-IPR_TRADE_FLOW_WINDOW:]

                    fs = max(-1.0, min(1.0, sum(self.ipr_tf) / IPR_TRADE_FLOW_NORM))
                    fv -= fs * IPR_TRADE_FLOW_COEF

                    # OBI shift
                    obi = ((total_bv - total_av) / (total_bv + total_av)
                           if (total_bv + total_av) > 0 else 0.0)
                    fv += obi * IPR_OBI_SHIFT

                    # Drift bias: IPR drifts +100/1000 ticks deterministically
                    fv += IPR_DRIFT_BIAS

                    fv_int = round(fv)

                    # Carry signal
                    if self.ipr_pb is not None:
                        bd = best_bid - self.ipr_pb
                        if bd >= IPR_CARRY_TRIGGER:
                            self.ipr_carry = -1.0
                        elif bd <= -IPR_CARRY_TRIGGER:
                            self.ipr_carry = 1.0
                        elif abs(bd) <= 1:
                            self.ipr_carry *= IPR_CARRY_DECAY
                    self.ipr_pb = best_bid

                    buy_cap = IPR_LIMIT - pos
                    sell_cap = IPR_LIMIT + pos

                    # Asymmetric takes: buy aggressively, sell defensively (drift is UP)
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

                    # Posting — long-biased
                    if self.ipr_carry > IPR_CARRY_THRESHOLD:
                        if buy_cap > 0:
                            bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                            orders.append(Order(IPR, bp, buy_cap))
                        if sell_cap > 0:
                            if pos >= IPR_AGGRESSION_THRESHOLD:
                                ap = max(fv_int + 1, best_ask - 1)
                            else:
                                ap = max(fv_int + IPR_CARRY_WIDE + 1, best_ask - 1)
                            ap = max(ap, best_bid + 1)
                            orders.append(Order(IPR, ap, -sell_cap))
                    elif self.ipr_carry < -IPR_CARRY_THRESHOLD:
                        if sell_cap > 0:
                            ap = max(fv_int + 1, best_ask - 1, best_bid + 1)
                            orders.append(Order(IPR, ap, -sell_cap))
                        if buy_cap > 0:
                            if pos <= -IPR_AGGRESSION_THRESHOLD:
                                bp = min(fv_int - 1, best_bid + 1)
                            else:
                                bp = min(fv_int - IPR_CARRY_WIDE + 1, best_bid + 1)
                            bp = min(bp, best_ask - 1)
                            orders.append(Order(IPR, bp, buy_cap))
                    else:
                        if buy_cap > 0:
                            bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                            orders.append(Order(IPR, bp, buy_cap))
                        if sell_cap > 0:
                            ap = max(fv_int + 2, best_ask - 1, best_bid + 1)
                            orders.append(Order(IPR, ap, -sell_cap))

                else:
                    # One-sided book: use last known FV or drift-biased mid
                    buy_cap = IPR_LIMIT - pos
                    sell_cap = IPR_LIMIT + pos

                    if has_bids and not has_asks:
                        # Only bids (no asks) — price dropped, buy opportunity
                        # Post aggressive bid + sell at best_bid + spread estimate
                        if buy_cap > 0:
                            bp = best_bid + 1
                            orders.append(Order(IPR, bp, buy_cap))
                        if sell_cap > 0:
                            ap = best_bid + 14  # ~avg spread
                            orders.append(Order(IPR, ap, -sell_cap))
                    elif has_asks and not has_bids:
                        # Only asks (no bids) — price spiked, sell opportunity
                        # Post aggressive buy below ask + sell inside ask
                        if buy_cap > 0:
                            bp = best_ask - 14  # ~avg spread below ask
                            orders.append(Order(IPR, bp, buy_cap))
                        if sell_cap > 0:
                            ap = best_ask - 1
                            orders.append(Order(IPR, ap, -sell_cap))

                result[IPR] = orders

        return result, conversions, json.dumps(
            {"m": self.ipr_mp, "f": self.ipr_tf,
             "b": self.ipr_pb, "c": round(self.ipr_carry, 3),
             "l": self.aco_liq},
            separators=(",", ":")
        )
