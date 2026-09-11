import json
import math
from datamodel import Order, TradingState

"""
s5_l2_features.py — L2 Feature-Enhanced Market Making (FINAL)

REPLACES 4-lag microprice regression entirely.
The 3-feature L2 model is strictly superior:
  - r = 0.63 vs 0.52 (21% improvement in correlation)
  - RMSE = 1.04 vs 1.15 (10% reduction in prediction error)
  - Hit rate = 61.5% vs 55.5% (6 percentage points)
  - Cross-day: train -2 test -1 r=0.624, train -1 test -2 r=0.634
  - Pooled R² = 0.396

FEATURES (pooled coefficients, stable across both days):
  predicted_return = +0.396 * vol_imb_dist_weighted
                     -2.306 * ema_5_dev_pct
                     -0.158 * gap_asymmetry
                     -0.021

  FV = mid + predicted_return

WHERE:
  vol_imb_dist_weighted = sum(vol/dist) for bids minus asks across L1+L2
  ema_5_dev_pct = (mid - EMA5) / spread  (mean-reversion, normalized)
  gap_asymmetry = (bid1-bid2) - (ask2-ask1)

CROSS-DAY COEFFICIENT STABILITY:
  Day -2 fit: VIDW=+0.441, EMA=-2.548, GAP=-0.124
  Day -1 fit: VIDW=+0.356, EMA=-2.075, GAP=-0.189
  Pooled:     VIDW=+0.396, EMA=-2.306, GAP=-0.158
  Max variation: ~20% — acceptable for 3 features
"""

# Pooled regression coefficients
COEFF_VIDW = +0.396082
COEFF_EMA  = -2.306071
COEFF_GAP  = -0.157866
INTERCEPT  = -0.021384

# FK inventory management (gamma=0.05)
FK_INV_PENALTY = 0.089

T_MAX = 999900


class Trader:
    def __init__(self):
        self.ema5 = None
        self.tf = []
        self.ew = []
        self.prev_bid = None
        self.sweep = 0.0

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.ema5 = td.get("e5")
            self.tf = td.get("tf", [])
            self.ew = td.get("ew", [])
            self.prev_bid = td.get("pb")
            self.sweep = td.get("sw", 0.0)

        orders = {}
        conversions = 0
        tau = max(0.01, (T_MAX - state.timestamp) / T_MAX)

        # ═══ EMERALDS ═══
        if "EMERALDS" in state.order_depths:
            od = state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo = []
                pos = state.position.get("EMERALDS", 0)
                tb, ts = 80 - pos, 80 + pos
                buys = sorted(od.buy_orders.items(), reverse=True)
                sells = sorted(od.sell_orders.items())

                self.ew.append(abs(pos) == 80)
                if len(self.ew) > 10:
                    self.ew = self.ew[-10:]
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

        # ═══ TOMATOES ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb = max(od.buy_orders)
                ba = min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (bb + ba) / 2.0
                spread = ba - bb

                # Extract L1 + L2
                buys_s = sorted(od.buy_orders.items(), reverse=True)
                sells_s = sorted(od.sell_orders.items())
                bv1 = buys_s[0][1] if len(buys_s) > 0 else 5
                av1 = abs(sells_s[0][1]) if len(sells_s) > 0 else 5
                b2 = buys_s[1][0] if len(buys_s) > 1 else bb - 1
                bv2 = buys_s[1][1] if len(buys_s) > 1 else 15
                a2 = sells_s[1][0] if len(sells_s) > 1 else ba + 1
                av2 = abs(sells_s[1][1]) if len(sells_s) > 1 else 15

                # ── FEATURE 1: vol_imb_dist_weighted ──
                vidw = (bv1 / (mid - bb + 0.5) - av1 / (ba - mid + 0.5) +
                        bv2 / (mid - b2 + 0.5) - av2 / (a2 - mid + 0.5))

                # ── FEATURE 2: ema_5_dev_pct ──
                a5 = 2.0 / 6.0
                if self.ema5 is None:
                    self.ema5 = mid
                else:
                    self.ema5 = a5 * mid + (1 - a5) * self.ema5
                ema_dev_pct = (mid - self.ema5) / max(spread, 1)

                # ── FEATURE 3: gap_asymmetry ──
                gap_asym = (bb - b2) - (a2 - ba)

                # ── PREDICTED RETURN (r=0.63, cross-day validated) ──
                pred_ret = (INTERCEPT +
                            COEFF_VIDW * vidw +
                            COEFF_EMA * ema_dev_pct +
                            COEFF_GAP * gap_asym)

                # ── FAIR VALUE ──
                fv = mid + pred_ret

                # ── TRADE FLOW (additive, supplementary) ──
                trades = state.market_trades.get("TOMATOES")
                if trades:
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > 5:
                    self.tf = self.tf[-5:]
                flow = max(-1.0, min(1.0, sum(self.tf) / 15.0))
                fv -= flow * 1.0

                # ── ICT SWEEP ──
                if self.prev_bid is not None:
                    bc = bb - self.prev_bid
                    if bc >= 4:
                        self.sweep = -1.0
                    elif bc <= -4:
                        self.sweep = 1.0
                    else:
                        self.sweep *= 0.6
                self.prev_bid = bb

                if abs(self.sweep) > 0.3:
                    fv += self.sweep * 1.0

                # ── FK RESERVATION ──
                reservation = fv - pos * FK_INV_PENALTY * tau

                tv = round(reservation)
                tb = 80 - pos
                ts = 80 + pos

                # TAKE
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= tv:
                        q = min(tb, -v)
                        to.append(Order("TOMATOES", p, q))
                        tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= tv:
                        q = min(ts, v)
                        to.append(Order("TOMATOES", p, -q))
                        ts -= q

                # POST
                bid_price = min(tv - 1, bb + 1)
                bid_price = min(bid_price, ba - 1)

                ask_price = max(tv + 1, ba - 1)
                ask_price = max(ask_price, bb + 1)

                if tb > 0:
                    to.append(Order("TOMATOES", bid_price, tb))
                if ts > 0:
                    to.append(Order("TOMATOES", ask_price, -ts))

                orders["TOMATOES"] = to

        return orders, conversions, json.dumps({
            "e5": self.ema5, "tf": self.tf, "ew": self.ew,
            "pb": self.prev_bid, "sw": round(self.sweep, 3),
        }, separators=(",", ":"))
