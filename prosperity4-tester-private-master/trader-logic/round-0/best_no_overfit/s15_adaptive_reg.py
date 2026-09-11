import json
from datamodel import Order, TradingState

"""s15_adaptive_reg: Online OLS refit for TOMATOES FV. Accumulates microprice
pairs, refits every 200 ticks via normal equations. Fallback to hardcoded."""

class Trader:
    def __init__(self):
        self.tc = []    # TOMATOES microprice cache (max 4)
        self.tf = []    # TOMATOES trade flow history (max 5)
        self.tw = []    # TOMATOES liquidation window (max 10)
        self.ew = []    # EMERALDS liquidation window (max 10)
        self.xy = []    # training pairs: [[mp0,mp1,mp2,mp3,target], ...]
        self.ac = None   # adaptive coefficients: [intercept, c0, c1, c2, c3]
        self.tk = 0      # tick count

    def bid(self):
        return 15

    def _refit_regression(self):
        if len(self.xy) < 5:
            return
        xtx = [[0.0]*5 for _ in range(5)]
        xty = [0.0]*5
        for row in self.xy:
            x = [1.0, row[0], row[1], row[2], row[3]]
            y = row[4]
            for i in range(5):
                xty[i] += x[i] * y
                for j in range(5):
                    xtx[i][j] += x[i] * x[j]
        # Solve via Gaussian elimination with partial pivoting
        A = [xtx[i][:] + [xty[i]] for i in range(5)]
        for col in range(5):
            # Pivot
            mx, mi = abs(A[col][col]), col
            for r in range(col+1, 5):
                if abs(A[r][col]) > mx:
                    mx, mi = abs(A[r][col]), r
            if mx < 1e-12:
                return  # singular
            A[col], A[mi] = A[mi], A[col]
            # Eliminate
            for r in range(col+1, 5):
                f = A[r][col] / A[col][col]
                for k in range(col, 6):
                    A[r][k] -= f * A[col][k]
        # Back substitute
        beta = [0.0]*5
        for i in range(4, -1, -1):
            s = A[i][5]
            for j in range(i+1, 5):
                s -= A[i][j] * beta[j]
            beta[i] = s / A[i][i]
        self.ac = beta

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])
            self.tw = td.get("tw", [])
            self.ew = td.get("ew", [])
            self.xy = td.get("xy", [])
            self.ac = td.get("ac", None)
            self.tk = td.get("tk", 0)

        self.tk += 1
        orders = {}

        # === EMERALDS ===
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

        # === TOMATOES ===
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, ts = 80 - pos, 80 + pos

                # Microprice
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) * 0.5

                c = self.tc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.tc = c

                # Accumulate training data
                if len(c) == 4:
                    self.xy.append([c[0], c[1], c[2], c[3], mp])
                    if len(self.xy) > 500:
                        self.xy = self.xy[-500:]

                # Refit every 200 ticks when enough data
                if len(self.xy) >= 200 and self.tk % 200 == 0:
                    self._refit_regression()

                # Fair value: adaptive or fallback
                if len(c) == 4:
                    if self.ac is not None:
                        fv = self.ac[0] + self.ac[1]*c[0] + self.ac[2]*c[1] + self.ac[3]*c[2] + self.ac[4]*c[3]
                    else:
                        fv = 2.208667 + 0.059694*c[0] + 0.117270*c[1] + 0.244154*c[2] + 0.578440*c[3]
                else:
                    fv = mp

                # Trade flow
                trades = state.market_trades.get("TOMATOES")
                if trades:
                    mid = (bb + ba) * 0.5
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > 5: self.tf = self.tf[-5:]
                fs = max(-1.0, min(1.0, sum(self.tf) / 15.0))
                fv -= fs * 1.5
                tv = round(fv)

                # Liquidation tracking
                self.tw.append(abs(pos) == 80)
                if len(self.tw) > 10: self.tw = self.tw[-10:]
                soft = len(self.tw) == 10 and sum(self.tw) >= 5 and self.tw[-1]
                hard = len(self.tw) == 10 and all(self.tw)

                mbp = tv - 1 if pos > 40 else tv
                msp = tv + 1 if pos < -40 else tv

                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                if tb > 0 and hard:
                    q = tb // 2; to.append(Order("TOMATOES", tv, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; to.append(Order("TOMATOES", tv - 2, q)); tb -= q
                if tb > 0:
                    to.append(Order("TOMATOES", min(mbp, bb + 1), tb))

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= msp:
                        q = min(ts, v); to.append(Order("TOMATOES", p, -q)); ts -= q
                if ts > 0 and hard:
                    q = ts // 2; to.append(Order("TOMATOES", tv, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; to.append(Order("TOMATOES", tv + 2, -q)); ts -= q
                if ts > 0:
                    to.append(Order("TOMATOES", max(msp, ba - 1), -ts))

                orders["TOMATOES"] = to

        # Save state: trim xy to last 200 for compact traderData
        xy_save = self.xy[-200:] if len(self.xy) > 200 else self.xy
        return orders, 0, json.dumps({
            "c":self.tc,"f":self.tf,"tw":self.tw,"ew":self.ew,
            "xy":xy_save,"ac":self.ac,"tk":self.tk
        }, separators=(",",":"))
