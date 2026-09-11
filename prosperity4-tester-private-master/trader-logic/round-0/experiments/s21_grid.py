import json
from datamodel import Order, TradingState

"""
s21_grid: Grid Trading — NO fair value estimation at all.

Place buy and sell orders at FIXED price levels relative to current mid.
3 buy levels: mid-3, mid-5, mid-7.  3 sell levels: mid+3, mid+5, mid+7.
Each level gets 1/3 of remaining capacity.
NO taking, NO regression, NO trade flow. Pure passive grid.
"""

class Trader:
    def __init__(self):
        self.ew = []    # EMERALDS liquidation window (max 10)

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.ew = td.get("ew", [])

        orders = {}

        # ═══ EMERALDS (standard take at 10000, post at best±1, liquidation tracking) ═══
        if "EMERALDS" in state.order_depths:
            od = state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo = []
                pos = state.position.get("EMERALDS", 0)
                tb, ts = 80 - pos, 80 + pos
                buys = sorted(od.buy_orders.items(), reverse=True)
                sells = sorted(od.sell_orders.items())
                tv = 10000
                self.ew.append(abs(pos) == 80)
                if len(self.ew) > 10: self.ew = self.ew[-10:]
                soft = len(self.ew) == 10 and sum(self.ew) >= 5 and self.ew[-1]
                hard = len(self.ew) == 10 and all(self.ew)
                mbp = tv - 1 if pos > 40 else tv
                msp = tv + 1 if pos < -40 else tv
                for p, v in sells:
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v); eo.append(Order("EMERALDS", p, q)); tb -= q
                if tb > 0 and hard:
                    q = tb // 2; eo.append(Order("EMERALDS", tv, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; eo.append(Order("EMERALDS", tv - 2, q)); tb -= q
                if tb > 0:
                    eo.append(Order("EMERALDS", min(mbp, buys[0][0] + 1), tb))
                for p, v in buys:
                    if ts > 0 and p >= msp:
                        q = min(ts, v); eo.append(Order("EMERALDS", p, -q)); ts -= q
                if ts > 0 and hard:
                    q = ts // 2; eo.append(Order("EMERALDS", tv, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; eo.append(Order("EMERALDS", tv + 2, -q)); ts -= q
                if ts > 0:
                    eo.append(Order("EMERALDS", max(msp, sells[0][0] - 1), -ts))
                orders["EMERALDS"] = eo

        # ═══ TOMATOES (pure grid — NO fair value, NO taking) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, ts = 80 - pos, 80 + pos
                mid = (bb + ba) / 2

                # Place buy at mid-3, mid-5, mid-7 (3 levels, split capacity equally)
                bid_prices = [int(mid - 3), int(mid - 5), int(mid - 7)]
                for i, bp in enumerate(bid_prices):
                    qty = max(1, tb // 3)
                    if tb > 0 and bp < ba:
                        to.append(Order("TOMATOES", bp, min(qty, tb)))
                        tb -= min(qty, tb)

                # Place sell at mid+3, mid+5, mid+7
                ask_prices = [int(mid + 3), int(mid + 5), int(mid + 7)]
                for i, ap in enumerate(ask_prices):
                    qty = max(1, ts // 3)
                    if ts > 0 and ap > bb:
                        to.append(Order("TOMATOES", ap, -min(qty, ts)))
                        ts -= min(qty, ts)

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({"ew": self.ew}, separators=(",", ":"))
