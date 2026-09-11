import json
from datamodel import Order, TradingState

"""
Round 1 Combined Trader — INTARIAN_PEPPER_ROOT + ASH_COATED_OSMIUM

INTARIAN_PEPPER_ROOT (limit 80):
  "Steady value" — random walk with +1000/day trend
  Strategy: microprice 4-lag regression + trade flow + carry signal
  Regression: nearly uniform coefs [0.24, 0.27, 0.23, 0.26], intercept ~0
  AC(1) = -0.50 (strong mean reversion)
  Spread: 12-14 tight, 16-17 wide. L1 vol ~11.5

ASH_COATED_OSMIUM (limit 80):
  "Volatile with hidden pattern" — O-U mean reversion to FV ~10000
  Strategy: fixed FV MM + O-U directional bias when deviating from FV
  Mid range: only 27-36 ticks per day around 10000
  AC(1) = -0.49, spread: 16 (62%), 18-19 (26%). L1 vol ~14
  When mid > FV+2: 42% down, 26% up (16% edge)
  When mid < FV-2: 41% up, 28% down (13% edge)

Website: 1000 ticks per product (not 2000). CSV ≠ website (36% book match).
One-sided book ticks: ~9% for both products — must handle gracefully.
"""

# ═══ INTARIAN_PEPPER_ROOT CONFIG ═══
IPR = "INTARIAN_PEPPER_ROOT"
IPR_LIMIT = 80
# Cross-validated 4-lag regression (averaged across 3 days)
IPR_COEFS = [0.2474, 0.2529, 0.2412, 0.2585]
IPR_INTERCEPT = 0.2078
IPR_TRADE_FLOW_COEF = 1.5
IPR_TRADE_FLOW_WINDOW = 5
IPR_TRADE_FLOW_NORM = 15.0
IPR_OBI_SHIFT = 0.5
IPR_CARRY_TRIGGER = 4
IPR_CARRY_DECAY = 0.7
IPR_CARRY_THRESHOLD = 0.5
IPR_CARRY_WIDE = 3
IPR_AGGRESSION_THRESHOLD = 40

# ═══ ASH_COATED_OSMIUM CONFIG ═══
ACO = "ASH_COATED_OSMIUM"
ACO_LIMIT = 80
ACO_FV = 10000
ACO_AGGRESSION_THRESHOLD = 40
ACO_LIQUIDATION_WINDOW = 10


class Trader:
    def __init__(self):
        # IPR state
        self.ipr_mp_cache = []
        self.ipr_tf_history = []
        self.ipr_prev_bid = None
        self.ipr_carry = 0.0
        # ACO state
        self.aco_liq_history = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.ipr_mp_cache = saved.get("mc", [])
            self.ipr_tf_history = saved.get("tf", [])
            self.ipr_prev_bid = saved.get("pb")
            self.ipr_carry = saved.get("cs", 0.0)
            self.aco_liq_history = saved.get("el", [])

        result = {}
        conversions = 0

        # ═══════════════════════════════════════════════════
        # ASH_COATED_OSMIUM — FV=10000, O-U MM + liquidation
        # ═══════════════════════════════════════════════════
        if ACO in state.order_depths:
            book = state.order_depths[ACO]
            if book.buy_orders and book.sell_orders:
                orders = []
                pos = state.position.get(ACO, 0)
                buy_cap = ACO_LIMIT - pos
                sell_cap = ACO_LIMIT + pos
                bids = sorted(book.buy_orders.items(), reverse=True)
                asks = sorted(book.sell_orders.items())

                # Liquidation tracking
                self.aco_liq_history.append(abs(pos) == ACO_LIMIT)
                if len(self.aco_liq_history) > ACO_LIQUIDATION_WINDOW:
                    self.aco_liq_history = self.aco_liq_history[-ACO_LIQUIDATION_WINDOW:]
                soft = (len(self.aco_liq_history) == ACO_LIQUIDATION_WINDOW
                        and sum(self.aco_liq_history) >= 5
                        and self.aco_liq_history[-1])
                hard = (len(self.aco_liq_history) == ACO_LIQUIDATION_WINDOW
                        and all(self.aco_liq_history))

                # Position-dependent aggression
                max_buy = ACO_FV if pos <= ACO_AGGRESSION_THRESHOLD else ACO_FV - 1
                min_sell = ACO_FV if pos >= -ACO_AGGRESSION_THRESHOLD else ACO_FV + 1

                # Take: buy asks at/below FV
                for price, vol in asks:
                    if buy_cap > 0 and price <= max_buy:
                        qty = min(buy_cap, -vol)
                        orders.append(Order(ACO, price, qty))
                        buy_cap -= qty

                # Liquidation bids
                if buy_cap > 0 and hard:
                    q = buy_cap // 2
                    orders.append(Order(ACO, ACO_FV, q))
                    buy_cap -= q
                if buy_cap > 0 and soft:
                    q = buy_cap // 2
                    orders.append(Order(ACO, ACO_FV - 2, q))
                    buy_cap -= q

                # Post bid
                if buy_cap > 0:
                    bid_p = min(ACO_FV - 1, bids[0][0] + 1)
                    orders.append(Order(ACO, bid_p, buy_cap))

                # Take: sell bids at/above FV
                for price, vol in bids:
                    if sell_cap > 0 and price >= min_sell:
                        qty = min(sell_cap, vol)
                        orders.append(Order(ACO, price, -qty))
                        sell_cap -= qty

                # Liquidation asks
                if sell_cap > 0 and hard:
                    q = sell_cap // 2
                    orders.append(Order(ACO, ACO_FV, -q))
                    sell_cap -= q
                if sell_cap > 0 and soft:
                    q = sell_cap // 2
                    orders.append(Order(ACO, ACO_FV + 2, -q))
                    sell_cap -= q

                # Post ask
                if sell_cap > 0:
                    ask_p = max(ACO_FV + 1, asks[0][0] - 1)
                    orders.append(Order(ACO, ask_p, -sell_cap))

                result[ACO] = orders

        # ═══════════════════════════════════════════════════
        # INTARIAN_PEPPER_ROOT — Regression FV + carry signal
        # ═══════════════════════════════════════════════════
        if IPR in state.order_depths:
            book = state.order_depths[IPR]
            if book.buy_orders and book.sell_orders:
                orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get(IPR, 0)
                mid = (best_bid + best_ask) * 0.5

                # Microprice
                total_bv = sum(book.buy_orders.values())
                total_av = sum(-v for v in book.sell_orders.values())
                mp = (best_bid + (total_bv / (total_bv + total_av)) * (best_ask - best_bid)
                      if (total_bv + total_av) > 0 else mid)

                hist = self.ipr_mp_cache
                if len(hist) >= 4:
                    hist = hist[1:]
                hist.append(mp)
                self.ipr_mp_cache = hist

                if len(hist) == 4:
                    fv = IPR_INTERCEPT + sum(c * x for c, x in zip(IPR_COEFS, hist))
                else:
                    fv = mp

                # Trade flow
                market_trades = state.market_trades.get(IPR)
                if market_trades:
                    net_flow = sum(t.quantity if t.price >= mid else -t.quantity
                                  for t in market_trades)
                    self.ipr_tf_history.append(net_flow)
                else:
                    self.ipr_tf_history.append(0.0)
                if len(self.ipr_tf_history) > IPR_TRADE_FLOW_WINDOW:
                    self.ipr_tf_history = self.ipr_tf_history[-IPR_TRADE_FLOW_WINDOW:]

                flow_signal = max(-1.0, min(1.0,
                    sum(self.ipr_tf_history) / IPR_TRADE_FLOW_NORM))
                fv -= flow_signal * IPR_TRADE_FLOW_COEF

                # OBI shift
                obi = ((total_bv - total_av) / (total_bv + total_av)
                       if (total_bv + total_av) > 0 else 0.0)
                fv += obi * IPR_OBI_SHIFT

                fv_int = round(fv)

                # Carry signal
                if self.ipr_prev_bid is not None:
                    bd = best_bid - self.ipr_prev_bid
                    if bd >= IPR_CARRY_TRIGGER:
                        self.ipr_carry = -1.0
                    elif bd <= -IPR_CARRY_TRIGGER:
                        self.ipr_carry = 1.0
                    elif abs(bd) <= 1:
                        self.ipr_carry *= IPR_CARRY_DECAY
                self.ipr_prev_bid = best_bid

                buy_cap = IPR_LIMIT - pos
                sell_cap = IPR_LIMIT + pos

                # Take at FV
                for price, vol in sorted(book.sell_orders.items()):
                    if buy_cap > 0 and price <= fv_int:
                        qty = min(buy_cap, -vol)
                        orders.append(Order(IPR, price, qty))
                        buy_cap -= qty

                for price, vol in sorted(book.buy_orders.items(), reverse=True):
                    if sell_cap > 0 and price >= fv_int:
                        qty = min(sell_cap, vol)
                        orders.append(Order(IPR, price, -qty))
                        sell_cap -= qty

                # Directional posting (carry signal)
                if self.ipr_carry > IPR_CARRY_THRESHOLD:
                    if buy_cap > 0:
                        bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                        orders.append(Order(IPR, bp, buy_cap))
                    if sell_cap > 0:
                        if pos >= IPR_AGGRESSION_THRESHOLD:
                            ap = max(fv_int + 1, best_ask - 1)
                        else:
                            ap = max(fv_int + IPR_CARRY_WIDE, best_ask - 1)
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
                            bp = min(fv_int - IPR_CARRY_WIDE, best_bid + 1)
                        bp = min(bp, best_ask - 1)
                        orders.append(Order(IPR, bp, buy_cap))

                else:
                    if buy_cap > 0:
                        bp = min(fv_int - 1, best_bid + 1, best_ask - 1)
                        orders.append(Order(IPR, bp, buy_cap))
                    if sell_cap > 0:
                        ap = max(fv_int + 1, best_ask - 1, best_bid + 1)
                        orders.append(Order(IPR, ap, -sell_cap))

                result[IPR] = orders

        return result, conversions, json.dumps(
            {"mc": self.ipr_mp_cache,
             "tf": self.ipr_tf_history,
             "pb": self.ipr_prev_bid,
             "cs": round(self.ipr_carry, 3),
             "el": self.aco_liq_history},
            separators=(",", ":")
        )
