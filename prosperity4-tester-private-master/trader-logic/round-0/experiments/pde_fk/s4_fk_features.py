import json
from datamodel import Order, TradingState

"""
s4_fk_features.py — Feature-Engineered FV + ICT Sweeps

FROM FEATURE ENGINEERING (OOS R²=0.40):
  Top features: vol_imb_l2, gap_asymmetry, weighted_mp_dev, vol_imb_total
  These capture L2 volume direction — 76% hit rate, persistent 20+ ticks

FROM FK ANALYSIS:
  FK optimal spread is ~21 ticks (too wide for this market).
  Reservation price shift at max position: ±1.43 ticks — similar to our ±1.
  CONCLUSION: Use proven best±1 posting, NOT FK-optimal.

STRATEGY: microprice regression + trade flow + L2 features for FV,
  ICT sweep detection for aggressive sizing, standard best±1 posting.
"""

LIMITS = {"TOMATOES": 80, "EMERALDS": 80}


class Trader:
    def __init__(self):
        self.mc = []         # microprice cache
        self.tf = []         # trade flow
        self.ew = []         # EMERALDS liquidation window
        self.tw = []         # TOMATOES liquidation window
        self.sweep = 0.0     # ICT sweep signal
        self.prev_bid = None

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.mc = td.get("mc", [])
            self.tf = td.get("tf", [])
            self.ew = td.get("ew", [])
            self.tw = td.get("tw", [])
            self.sweep = td.get("sw", 0.0)
            self.prev_bid = td.get("pb")

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

        # ═══ TOMATOES (feature-enhanced FV + ICT + proven execution) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, ts = 80 - pos, 80 + pos
                mid = (bb + ba) * 0.5
                spread = ba - bb

                # ── LAYER 1: Microprice regression (base, proven 2,644) ──
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else mid

                c = self.mc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.mc = c

                if len(c) == 4:
                    fv = 2.208667 + 0.059694*c[0] + 0.117270*c[1] + 0.244154*c[2] + 0.578440*c[3]
                else:
                    fv = mp

                # ── LAYER 2: Trade flow (proven +207 PnL) ──
                trades = state.market_trades.get("TOMATOES")
                if trades:
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > 5: self.tf = self.tf[-5:]
                fs = max(-1.0, min(1.0, sum(self.tf) / 15.0))
                fv -= fs * 1.5

                # ── LAYER 3: L2 volume imbalance as FV nudge ──
                # Feature engineering: vol_imb_l2 has r=0.60, gap_asymmetry r=0.60
                # But shifting FV by L2 imbalance scored 2,422 (WORSE).
                # Use as CONTEXT for sweep detection only, not direct FV shift.
                bids_sorted = sorted(od.buy_orders.items(), reverse=True)
                asks_sorted = sorted(od.sell_orders.items())
                l2_imb = 0
                if len(bids_sorted) >= 2 and len(asks_sorted) >= 2:
                    l2_imb = bids_sorted[1][1] - abs(asks_sorted[1][1])

                # ── LAYER 4: ICT Sweep Detection ──
                if self.prev_bid is not None:
                    bid_change = bb - self.prev_bid
                    if bid_change >= 4:
                        # Large UP sweep → expect DOWN reversion (-5.72 over 5 ticks)
                        self.sweep = -1.0
                    elif bid_change <= -4:
                        # Large DOWN sweep → expect UP (weaker: +0.07)
                        self.sweep = 0.5  # asymmetric: up sweeps revert harder
                    else:
                        self.sweep *= 0.5  # fast decay
                self.prev_bid = bb

                # Apply sweep to FV (shift toward expected reversion)
                if abs(self.sweep) > 0.3:
                    fv += self.sweep * 1.5

                # When L2 imbalance CONFIRMS sweep direction, strengthen signal
                if abs(l2_imb) > 5 and self.sweep != 0:
                    imb_dir = 1 if l2_imb > 0 else -1
                    sweep_dir = 1 if self.sweep > 0 else -1
                    if imb_dir == sweep_dir:
                        fv += self.sweep * 0.5  # extra boost when L2 confirms

                tv = round(fv)

                # ── Liquidation tracking ──
                self.tw.append(abs(pos) == 80)
                if len(self.tw) > 10: self.tw = self.tw[-10:]
                soft = len(self.tw) == 10 and sum(self.tw) >= 5 and self.tw[-1]
                hard = len(self.tw) == 10 and all(self.tw)

                # Position-dependent aggression (proven +175 PnL)
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
            "sw": round(self.sweep, 3), "pb": self.prev_bid
        }, separators=(",", ":"))
