import json
from datamodel import Order, TradingState

"""
s5_features.py — Conservative Feature-Enhanced Strategy

Base: s2_tradeflow (2,851 on website)
Add TINY nudges from the most stable non-L2-volume features:
  - gap_asymmetry (r=0.60): L1-L2 gap structure, new info beyond microprice
  - ema_5_dev (r=0.49): deviation from 5-tick EMA, mean reversion speed

Philosophy: if even tiny nudges hurt, features add nothing beyond microprice.
No FK reservation, no ICT sweeps, no L2 volume shifts — just pure feature FV.
"""


class Trader:
    def __init__(self):
        self.mc = []     # microprice cache
        self.tf = []     # trade flow
        self.ew = []     # EMERALDS liquidation
        self.tw = []     # TOMATOES liquidation
        self.mid_ema5 = None  # 5-tick EMA of mid

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.mc = td.get("mc", [])
            self.tf = td.get("tf", [])
            self.ew = td.get("ew", [])
            self.tw = td.get("tw", [])
            self.mid_ema5 = td.get("e5")

        orders = {}

        # ═══ EMERALDS (proven, unchanged) ═══
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
                mbp = 10000 - 1 if pos > 40 else 10000
                msp = 10000 + 1 if pos < -40 else 10000
                for p, v in sells:
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v); eo.append(Order("EMERALDS", p, q)); tb -= q
                if tb > 0 and hard:
                    q = tb // 2; eo.append(Order("EMERALDS", 10000, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; eo.append(Order("EMERALDS", 9998, q)); tb -= q
                if tb > 0:
                    eo.append(Order("EMERALDS", min(mbp, buys[0][0] + 1), tb))
                for p, v in buys:
                    if ts > 0 and p >= msp:
                        q = min(ts, v); eo.append(Order("EMERALDS", p, -q)); ts -= q
                if ts > 0 and hard:
                    q = ts // 2; eo.append(Order("EMERALDS", 10000, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; eo.append(Order("EMERALDS", 10002, -q)); ts -= q
                if ts > 0:
                    eo.append(Order("EMERALDS", max(msp, sells[0][0] - 1), -ts))
                orders["EMERALDS"] = eo

        # ═══ TOMATOES (microprice reg + trade flow + small feature nudges) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, ts = 80 - pos, 80 + pos
                mid = (bb + ba) * 0.5
                spread = ba - bb

                # ── LAYER 1: Microprice regression (proven base) ──
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * spread if (bv + av) > 0 else mid

                c = self.mc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.mc = c

                if len(c) == 4:
                    fv = 2.208667 + 0.059694*c[0] + 0.117270*c[1] + 0.244154*c[2] + 0.578440*c[3]
                else:
                    fv = mp

                # ── LAYER 2: Trade flow (proven +207) ──
                trades = state.market_trades.get("TOMATOES")
                if trades:
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > 5: self.tf = self.tf[-5:]
                fs = max(-1.0, min(1.0, sum(self.tf) / 15.0))
                fv -= fs * 1.5

                # ── LAYER 3: Feature nudges (SMALL coefficients) ──

                # Feature A: gap_asymmetry = (bid1-bid2) - (ask2-ask1)
                # r=-0.60: negative gap_asym → price going up → increase fv
                bids_s = sorted(od.buy_orders.items(), reverse=True)
                asks_s = sorted(od.sell_orders.items())
                if len(bids_s) >= 2 and len(asks_s) >= 2:
                    gap_asym = (bids_s[0][0] - bids_s[1][0]) - (asks_s[1][0] - asks_s[0][0])
                    fv -= gap_asym * 0.05  # very conservative

                # Feature B: ema_5_dev = mid - ema5(mid)
                # r=-0.49: positive dev (above EMA) → price reverting down
                alpha = 0.4  # ~5 tick half-life
                if self.mid_ema5 is None:
                    self.mid_ema5 = mid
                else:
                    self.mid_ema5 = alpha * mid + (1 - alpha) * self.mid_ema5
                ema5_dev = mid - self.mid_ema5
                fv -= ema5_dev * 0.05  # very conservative

                tv = round(fv)

                # ── Liquidation tracking ──
                self.tw.append(abs(pos) == 80)
                if len(self.tw) > 10: self.tw = self.tw[-10:]
                soft = len(self.tw) == 10 and sum(self.tw) >= 5 and self.tw[-1]
                hard = len(self.tw) == 10 and all(self.tw)

                mbp = tv - 1 if pos > 40 else tv
                msp = tv + 1 if pos < -40 else tv

                # ═══ TAKE ═══
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                if tb > 0 and hard:
                    q = tb // 2; to.append(Order("TOMATOES", tv, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; to.append(Order("TOMATOES", tv - 2, q)); tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= msp:
                        q = min(ts, v); to.append(Order("TOMATOES", p, -q)); ts -= q
                if ts > 0 and hard:
                    q = ts // 2; to.append(Order("TOMATOES", tv, -q)); ts -= q
                if ts > 0 and soft:
                    q = ts // 2; to.append(Order("TOMATOES", tv + 2, -q)); ts -= q

                # ═══ POST at best±1 (proven optimal) ═══
                if tb > 0:
                    to.append(Order("TOMATOES", min(mbp, bb + 1), tb))
                if ts > 0:
                    to.append(Order("TOMATOES", max(msp, ba - 1), -ts))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({
            "mc": self.mc, "tf": self.tf, "ew": self.ew, "tw": self.tw,
            "e5": self.mid_ema5
        }, separators=(",", ":"))
