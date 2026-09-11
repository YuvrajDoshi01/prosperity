import json
from datamodel import Order, TradingState

"""
s24_momentum: Pure Momentum — opposite of mean reversion.

Instead of fading moves (like regression does), FOLLOW them.
After price goes up, BUY more (expect continuation).
After price goes down, SELL more.
Uses 3-tick momentum of mid price.
"""

class Trader:
    def __init__(self):
        self.prev_mids = []  # Recent mid prices (max 10)
        self.ew = []         # EMERALDS liquidation window (max 10)

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.prev_mids = td.get("pm", [])
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

        # ═══ TOMATOES (pure momentum — follow the trend) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, ts = 80 - pos, 80 + pos
                mid = (bb + ba) / 2

                # Track recent direction
                self.prev_mids.append(mid)
                if len(self.prev_mids) > 10: self.prev_mids = self.prev_mids[-10:]

                momentum = 0
                if len(self.prev_mids) >= 3:
                    momentum = self.prev_mids[-1] - self.prev_mids[-3]  # 3-tick momentum

                if momentum > 1:
                    # Bullish: only buy, no sell posting — ride the trend up
                    for p, v in sorted(od.sell_orders.items()):
                        if tb > 0 and p <= round(mid + 1):
                            q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                    if tb > 0:
                        to.append(Order("TOMATOES", min(int(mid), bb + 1), tb))
                elif momentum < -1:
                    # Bearish: only sell, no buy posting — ride the trend down
                    for p, v in sorted(od.buy_orders.items(), reverse=True):
                        if ts > 0 and p >= round(mid - 1):
                            q = min(ts, v); to.append(Order("TOMATOES", p, -q)); ts -= q
                    if ts > 0:
                        to.append(Order("TOMATOES", max(int(mid), ba - 1), -ts))
                else:
                    # Neutral: standard MM both sides
                    for p, v in sorted(od.sell_orders.items()):
                        if tb > 0 and p <= round(mid):
                            q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                    if tb > 0:
                        to.append(Order("TOMATOES", min(int(mid), bb + 1), tb))
                    for p, v in sorted(od.buy_orders.items(), reverse=True):
                        if ts > 0 and p >= round(mid):
                            q = min(ts, v); to.append(Order("TOMATOES", p, -q)); ts -= q
                    if ts > 0:
                        to.append(Order("TOMATOES", max(int(mid), ba - 1), -ts))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({"pm": self.prev_mids, "ew": self.ew}, separators=(",", ":"))
