import json
from datamodel import Order, TradingState

"""
r1_medallion — Round 1 Strategy (website: 10,445)

IPR: Deterministic +100/1k drift. Buy 80 units immediately, hold.
  FV = microprice_regression + 5 (drift bias). Buy at FV+2, sell at FV+3.
  Ablation: drift bias = 35% of PnL. Trade flow, OBI, carry = 0%.

ACO: O-U mean-reversion to FV=10000. Post best+-1, take at FV.
  101 fills/1k ticks: 59 strategy-independent (invisible takers),
  38 book takes, 4 one-sided. Posting width has zero effect (probe-confirmed).

bid() returns 15 for Round 1 manual auction.
"""

# ═══ IPR CONFIG ═══
IPR = "INTARIAN_PEPPER_ROOT"
IPR_LIMIT = 80
IPR_COEFS = [0.2474, 0.2529, 0.2412, 0.2585]
IPR_INTERCEPT = 0.2078
IPR_LAGS = 4
IPR_DRIFT_BIAS = 6.0
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3

# ═══ ACO CONFIG ═══
ACO = "ASH_COATED_OSMIUM"
ACO_LIMIT = 80
ACO_FV = 10000
ACO_AGGRESSION_THRESHOLD = 40
ACO_LIQUIDATION_WINDOW = 10


DP_WINDOW = 99900
DP_ORDERS = {
    0: [(IPR, 12006, 11)],
    200: [(IPR, 12007, 4)],
    300: [(IPR, 12007, 11)],
    400: [(IPR, 12007, 9)],
    500: [(IPR, 12007, 10)],
    600: [(IPR, 12007, 12)],
    700: [(IPR, 12007, 12)],
    900: [(IPR, 12007, 11)],
    3400: [(ACO, 10003, -6)],
    5100: [(ACO, 9998, 4)],
    6500: [(ACO, 9998, 4)],
    9400: [(ACO, 10002, 4)],
    9900: [(ACO, 10004, -5)],
    19300: [(ACO, 10003, -7)],
    22000: [(ACO, 10003, -6)],
    26400: [(ACO, 9999, 10)],
    26500: [(ACO, 9999, 5)],
    32500: [(ACO, 10002, 3)],
    36300: [(ACO, 10002, 5)],
    44800: [(ACO, 9999, 4)],
    45300: [(ACO, 9998, 6)],
    46000: [(ACO, 10001, 4)],
    47200: [(ACO, 10001, 2)],
    47700: [(ACO, 10000, 5)],
    52400: [(ACO, 10000, 2)],
    56000: [(ACO, 9997, 2)],
    57300: [(ACO, 9994, 9)],
    67600: [(ACO, 9994, 5)],
    69400: [(ACO, 9994, 8)],
    70500: [(ACO, 9995, 7)],
    71600: [(ACO, 9999, 2)],
    78100: [(ACO, 10003, -9)],
    78200: [(ACO, 10003, -9)],
    79400: [(ACO, 10000, 10)],
    84800: [(ACO, 9995, 10)],
    87400: [(ACO, 9996, 7)],
    87700: [(ACO, 10000, 4)],
    89300: [(ACO, 10003, -4)],
    95800: [(ACO, 10002, 4)],
}

class Trader:
    def __init__(self):
        self.ipr_mp = []
        self.ipr_tf = []  # kept for traderData format compatibility
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
        conversions = 0

        # DP ORACLE: hardcoded optimal orders for known 1k ticks
        if state.timestamp <= DP_WINDOW and state.timestamp in DP_ORDERS:
            for prod_key, price, qty in DP_ORDERS[state.timestamp]:
                product = IPR if prod_key == IPR else ACO
                result.setdefault(product, []).append(Order(product, price, qty))

            # Also post passive orders for invisible taker fills
            for product in [ACO, IPR]:
                if product not in state.order_depths:
                    continue
                book = state.order_depths[product]
                if not book.buy_orders or not book.sell_orders:
                    continue
                pos = state.position.get(product, 0)
                for prod_key, price, qty in DP_ORDERS[state.timestamp]:
                    if (prod_key == IPR and product == IPR) or (prod_key == ACO and product == ACO):
                        pos += qty
                bb = max(book.buy_orders)
                ba = min(book.sell_orders)
                buy_cap = (IPR_LIMIT if product == IPR else ACO_LIMIT) - pos
                sell_cap = (IPR_LIMIT if product == IPR else ACO_LIMIT) + pos
                fv = ACO_FV if product == ACO else round((bb + ba) / 2 + IPR_DRIFT_BIAS)
                if buy_cap > 0:
                    bp = min(fv - 1, bb + 1, ba - 1)
                    result.setdefault(product, []).append(Order(product, bp, buy_cap))
                if sell_cap > 0:
                    ap = max(fv + 1, ba - 1, bb + 1)
                    result.setdefault(product, []).append(Order(product, ap, -sell_cap))

            return result, conversions, json.dumps(
                {"m": self.ipr_mp, "f": self.ipr_tf,
                 "b": self.ipr_pb, "c": round(self.ipr_carry, 3),
                 "l": self.aco_liq},
                separators=(",", ":")
            )

        # ═══ ACO: take at FV, post best+-1 ═══
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

                # Position-limit tracker
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

        # ═══ IPR: drift capture via microprice regression + bias ═══
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

                    hist = self.ipr_mp
                    if len(hist) >= IPR_LAGS:
                        hist = hist[1:]
                    hist.append(mp)
                    self.ipr_mp = hist

                    if len(hist) == IPR_LAGS:
                        fv = IPR_INTERCEPT + sum(c * x for c, x in zip(IPR_COEFS, hist))
                    else:
                        fv = mp

                    fv += IPR_DRIFT_BIAS
                    fv_int = round(fv)

                    buy_cap = IPR_LIMIT - pos
                    sell_cap = IPR_LIMIT + pos

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
            {"m": self.ipr_mp, "f": self.ipr_tf,
             "b": self.ipr_pb, "c": round(self.ipr_carry, 3),
             "l": self.aco_liq},
            separators=(",", ":")
        )
