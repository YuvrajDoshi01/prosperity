import json
from datamodel import Order, TradingState

"""
r1_v2 — Round 1 Strategy (simple mid FV)

Same as r1_medallion, but IPR FV = round(mid + drift_bias) instead of
microprice-regression + drift. Simpler and empirically better.

Why: in ask-heavy books (MM providing supply to bullish takers), microprice
leans LOW toward the bid. Mid is unweighted and sits higher. With +5 drift,
simple mid gives FV_int that catches the MM ask at 12006 at t=0 — medallion
misses it. Over the day this earlier-and-gradual entry beats medallion's
late-and-bursty entry by ~68 PnL on the website.

Reference: run 210525 scored 10,536.81 (baseline medallion: 10,445-10,468).
"""

# ═══ IPR CONFIG ═══
IPR = "INTARIAN_PEPPER_ROOT"
IPR_LIMIT = 80
IPR_DRIFT_BIAS = 5.0
IPR_BUY_SLACK = 2
IPR_SELL_SLACK = 3

# ═══ ACO CONFIG ═══
ACO = "ASH_COATED_OSMIUM"
ACO_LIMIT = 80
ACO_FV = 10000
ACO_AGGRESSION_THRESHOLD = 40
ACO_LIQUIDATION_WINDOW = 10


class Trader:
    def __init__(self):
        self.aco_liq = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.aco_liq = saved.get("l", [])

        result = {}
        conversions = 0

        # ═══ ACO: take at FV, post best±1 ═══
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

        # ═══ IPR: simple mid FV + drift, no regression ═══
        if IPR in state.order_depths:
            book = state.order_depths[IPR]
            has_bids = bool(book.buy_orders)
            has_asks = bool(book.sell_orders)

            if has_bids or has_asks:
                orders = []
                best_bid = max(book.buy_orders) if has_bids else None
                best_ask = min(book.sell_orders) if has_asks else None
                pos = state.position.get(IPR, 0)
                buy_cap = IPR_LIMIT - pos
                sell_cap = IPR_LIMIT + pos

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

                result[IPR] = orders

        return result, conversions, json.dumps({"l": self.aco_liq}, separators=(",", ":"))
