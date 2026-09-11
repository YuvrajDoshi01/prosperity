import json
from datamodel import Order, TradingState

"""
s26_sweep_optimal: Built from mega_sweep landscape-stable findings.

Changes from s25 (2,855 website):
  1. INTERCEPT: 5.0 (was 7.39) — S1 winner, avg=3,537, spread=140 (MOST STABLE)
  2. DIR_WIDTH: 5 (was 3) — S4 unanimous winner (10/10 top results)
  3. DIR_TRIGGER: 2 (was 4) — S4 winner, more sensitive to reversals
  4. DIR_DECAY: 0.9 (was 0.7) — S4 winner, hold signal longer

NOT changed (website-proven, local sweep disagrees but website is ground truth):
  - FLOW_COEF: 1.5 (sweep says 2.0 but website says 2.0 = 2,753, WORSE)
  - TOM_AGGR_TICK: 1 (sweep says 0 but website says 0 = 2,676, WORSE)
  - POST_OFFSET: 1 (sweep says 2 but untested on website)
  - EMERALDS: keep current defaults (sweep found no improvement)
"""

class Trader:
    def __init__(self):
        self.tc = []
        self.tf = []
        self.ew = []
        self.tw = []
        self.pb = None
        self.sig = 0

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])
            self.ew = td.get("w", [])
            self.tw = td.get("tw", [])
            self.pb = td.get("pb")
            self.sig = td.get("sg", 0)

        orders = {}

        # ═══ EMERALDS (unchanged from s25) ═══
        if "EMERALDS" in state.order_depths:
            od = state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo = []
                pos = state.position.get("EMERALDS", 0)
                tb, ts = 80 - pos, 80 + pos
                buys = sorted(od.buy_orders.items(), reverse=True)
                sells = sorted(od.sell_orders.items())
                self.ew.append(abs(pos) == 80)
                if len(self.ew) > 10: self.ew = self.ew[-10:]
                soft = len(self.ew) == 10 and sum(self.ew) >= 5 and self.ew[-1]
                hard = len(self.ew) == 10 and all(self.ew)
                for p, v in sells:
                    if tb > 0 and p <= 10000:
                        q = min(tb, -v); eo.append(Order("EMERALDS", p, q)); tb -= q
                if tb > 0 and hard:
                    q = tb // 2; eo.append(Order("EMERALDS", 10000, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; eo.append(Order("EMERALDS", 9998, q)); tb -= q
                if tb > 0:
                    eo.append(Order("EMERALDS", min(9999, buys[0][0] + 1), tb))
                for p, v in buys:
                    if ts > 0 and p >= 10000:
                        q = min(ts, v); eo.append(Order("EMERALDS", p, -q)); ts -= q
                if ts > 0 and hard:
                    q = ts // 2; eo.append(Order("EMERALDS", 10000, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; eo.append(Order("EMERALDS", 10002, -q)); ts -= q
                if ts > 0:
                    eo.append(Order("EMERALDS", max(10001, sells[0][0] - 1), -ts))
                orders["EMERALDS"] = eo

        # ═══ TOMATOES (sweep-optimized) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (bb + ba) * 0.5

                # Microprice regression (same cross-val coefs, NEW intercept=5.0)
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else mid
                c = self.tc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.tc = c
                if len(c) == 4:
                    fv = 5.0 + 0.059509*c[0] + 0.117116*c[1] + 0.243910*c[2] + 0.577988*c[3]
                else:
                    fv = mp

                # Trade flow (keep 1.5 — website-proven)
                trades = state.market_trades.get("TOMATOES")
                if trades:
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > 5: self.tf = self.tf[-5:]
                fs = max(-1.0, min(1.0, sum(self.tf) / 15.0))
                fv -= fs * 1.5

                tv = round(fv)

                # Directional signal (NEW: trigger=2, decay=0.9)
                if self.pb is not None:
                    bc = bb - self.pb
                    if bc >= 2:       # was 4 — more sensitive
                        self.sig = -1
                    elif bc <= -2:    # was -4
                        self.sig = 1
                    elif abs(bc) <= 1:
                        self.sig *= 0.9  # was 0.7 — hold signal longer
                self.pb = bb

                # Liquidation tracking
                self.tw.append(abs(pos) == 80)
                if len(self.tw) > 10: self.tw = self.tw[-10:]
                tsoft = len(self.tw) == 10 and sum(self.tw) >= 5 and self.tw[-1]
                thard = len(self.tw) == 10 and all(self.tw)

                tb = 80 - pos
                ts = 80 + pos

                # Position aggression (keep — website-proven)
                mbp = tv - 1 if pos > 40 else tv
                msp = tv + 1 if pos < -40 else tv

                # TAKE
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                if tb > 0 and thard:
                    q = tb // 2; to.append(Order("TOMATOES", tv, q)); tb -= q
                if tb > 0 and tsoft:
                    q = tb // 2; to.append(Order("TOMATOES", tv - 2, q)); tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= msp:
                        q = min(ts, v); to.append(Order("TOMATOES", p, -q)); ts -= q
                if ts > 0 and thard:
                    q = ts // 2; to.append(Order("TOMATOES", tv, -q)); ts -= q
                if ts > 0 and tsoft:
                    q = ts // 2; to.append(Order("TOMATOES", tv + 2, -q)); ts -= q

                # POST (NEW: dir_width=5)
                if self.sig > 0.5:
                    if tb > 0:
                        to.append(Order("TOMATOES", min(tv - 1, bb + 1), tb))
                    if ts > 0:
                        to.append(Order("TOMATOES", max(tv + 5, ba - 1, bb + 1), -ts))
                elif self.sig < -0.5:
                    if ts > 0:
                        to.append(Order("TOMATOES", max(tv + 1, ba - 1), -ts))
                    if tb > 0:
                        to.append(Order("TOMATOES", min(tv - 5, bb + 1, ba - 1), tb))
                else:
                    if tb > 0:
                        to.append(Order("TOMATOES", min(tv - 1, bb + 1), tb))
                    if ts > 0:
                        to.append(Order("TOMATOES", max(tv + 1, ba - 1), -ts))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({
            "c": self.tc, "f": self.tf, "w": self.ew, "tw": self.tw,
            "pb": self.pb, "sg": round(self.sig, 3)
        }, separators=(",", ":"))
