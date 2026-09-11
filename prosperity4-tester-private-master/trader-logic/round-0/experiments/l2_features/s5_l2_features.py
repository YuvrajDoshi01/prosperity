import json
from datamodel import Order, TradingState

"""
s5_l2_features.py — L2 Feature-Enhanced Market Making

KEY DISCOVERY from feature_engineering.py:
  vol_imb_l2     = (bv2 - av2) / (bv2 + av2)     -> r = +0.62 with future return
  gap_asymmetry  = (bid1-bid2) - (ask2-ask1)       -> r = -0.61
  weighted_mp_dev = L1+L2 weighted microprice - mid -> r = +0.60
  vol_imb_total  = full book volume imbalance       -> r = +0.59

These are STRONGER than our current microprice regression (r=0.43).
We were completely ignoring L2 information.

OOS-validated regression (R²=0.40, test r=0.63):
  FV_adj = vol_imb_total * 14.0 + gap_asymmetry * -0.55 + weighted_mp_dev * -1.4

From FK analysis:
  A-S spread formula gives absurd 22-tick half-spreads (fill rate too low).
  Use ONLY the reservation price shift: FV - pos * 0.089 * tau
  Keep posting at best+1/best-1 for fills.
"""


class Trader:
    def __init__(self):
        self.mc = []
        self.tf = []
        self.ew = []
        self.prev_bid = None
        self.sweep_signal = 0.0

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.mc = td.get("c", [])
            self.tf = td.get("f", [])
            self.ew = td.get("w", [])
            self.prev_bid = td.get("pb")
            self.sweep_signal = td.get("ss", 0.0)

        orders = {}
        conversions = 0
        ts = state.timestamp
        T_MAX = 999900
        tau = max(0.01, (T_MAX - ts) / T_MAX)

        # ═══ EMERALDS (proven, unchanged) ═══
        if "EMERALDS" in state.order_depths:
            od = state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo = []
                pos = state.position.get("EMERALDS", 0)
                tb, ts_ = 80 - pos, 80 + pos
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
                    if ts_ > 0 and p >= 10000:
                        q = min(ts_, v); eo.append(Order("EMERALDS", p, -q)); ts_ -= q
                if ts_ > 0 and hard:
                    q = ts_ // 2; eo.append(Order("EMERALDS", 10000, -q)); ts_ -= q
                if ts_ > 0 and soft:
                    q = ts_ // 2; eo.append(Order("EMERALDS", 10002, -q)); ts_ -= q
                if ts_ > 0:
                    eo.append(Order("EMERALDS", max(10001, sells[0][0] - 1), -ts_))
                orders["EMERALDS"] = eo

        # ═══ TOMATOES — L2 FEATURES + FK RESERVATION + SWEEP ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb = max(od.buy_orders)
                ba = min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (bb + ba) / 2.0
                spread = ba - bb

                # ── Extract L1 and L2 book data ──
                buys_sorted = sorted(od.buy_orders.items(), reverse=True)
                sells_sorted = sorted(od.sell_orders.items())

                bv1 = buys_sorted[0][1] if len(buys_sorted) > 0 else 5
                av1 = abs(sells_sorted[0][1]) if len(sells_sorted) > 0 else 5
                bid2 = buys_sorted[1][0] if len(buys_sorted) > 1 else bb - 1
                bv2 = buys_sorted[1][1] if len(buys_sorted) > 1 else 15
                ask2 = sells_sorted[1][0] if len(sells_sorted) > 1 else ba + 1
                av2 = abs(sells_sorted[1][1]) if len(sells_sorted) > 1 else 15

                # ── LAYER 1: Microprice regression (baseline) ──
                total_bv = sum(v for v in od.buy_orders.values())
                total_av = sum(-v for v in od.sell_orders.values())
                mp = bb + (total_bv / (total_bv + total_av)) * spread if (total_bv + total_av) > 0 else mid

                c = self.mc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.mc = c

                if len(c) == 4:
                    fv = 2.208667 + 0.059694*c[0] + 0.117270*c[1] + 0.244154*c[2] + 0.578440*c[3]
                else:
                    fv = mp

                # ── LAYER 2: Trade flow ──
                trades = state.market_trades.get("TOMATOES")
                if trades:
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > 5: self.tf = self.tf[-5:]
                flow_sig = max(-1.0, min(1.0, sum(self.tf) / 15.0))
                fv -= flow_sig * 1.5

                # ── LAYER 3: L2 FEATURES (THE NEW ALPHA) ──
                # vol_imb_l2: r = 0.62 (strongest single feature)
                vol_imb_l2 = (bv2 - av2) / max(bv2 + av2, 1)

                # gap_asymmetry: r = -0.61
                bid_gap = bb - bid2
                ask_gap = ask2 - ba
                gap_asym = bid_gap - ask_gap

                # vol_imb_total: r = 0.59
                total_bid = bv1 + bv2
                total_ask = av1 + av2
                vol_imb_total = (total_bid - total_ask) / max(total_bid + total_ask, 1)

                # weighted_mp_dev: r = 0.60
                if total_bid + total_ask > 0:
                    bid_vwap = (bb * bv1 + bid2 * bv2) / max(total_bid, 1)
                    ask_vwap = (ba * av1 + ask2 * av2) / max(total_ask, 1)
                    wmp = bid_vwap + (total_bid / (total_bid + total_ask)) * (ask_vwap - bid_vwap)
                    wmp_dev = wmp - mid
                else:
                    wmp_dev = 0.0

                # OOS regression coefficients (averaged across days):
                # Day -2: vol_imb_total * 12.58 + gap_asymmetry * -0.59 + weighted_mp_dev * -1.06
                # Day -1: vol_imb_total * 14.90 + gap_asymmetry * -0.52 + weighted_mp_dev * -1.69
                # Average:
                fv += vol_imb_total * 13.7
                fv += gap_asym * -0.55
                fv += wmp_dev * -1.4

                # ── LAYER 4: FK Reservation Price Shift ──
                # gamma=0.05 gives ±7 tick shift at extreme positions
                FK_INV_PENALTY = 0.089  # gamma * sigma^2 (gamma=0.05)
                reservation = fv - pos * FK_INV_PENALTY * tau

                # ── LAYER 5: ICT Sweep Detection ──
                if self.prev_bid is not None:
                    bid_change = bb - self.prev_bid
                    if bid_change >= 4:
                        self.sweep_signal = -1.0
                    elif bid_change <= -4:
                        self.sweep_signal = 1.0
                    else:
                        self.sweep_signal *= 0.6
                self.prev_bid = bb

                # Shift reservation toward expected reversion
                if abs(self.sweep_signal) > 0.3:
                    reservation += self.sweep_signal * 1.5

                # ── COMPUTE ORDERS ──
                tv = round(reservation)  # use reservation (not raw FV) for taking
                tb = 80 - pos
                ts_ = 80 + pos

                # TAKE: at reservation price
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= tv:
                        q = min(tb, -v)
                        to.append(Order("TOMATOES", p, q))
                        tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts_ > 0 and p >= tv:
                        q = min(ts_, v)
                        to.append(Order("TOMATOES", p, -q))
                        ts_ -= q

                # POST: at best+1/best-1 (proven fill priority)
                # But shift based on reservation (which incorporates inventory + features)
                bid_price = min(tv - 1, bb + 1)
                bid_price = min(bid_price, ba - 1)

                ask_price = max(tv + 1, ba - 1)
                ask_price = max(ask_price, bb + 1)

                if tb > 0:
                    to.append(Order("TOMATOES", bid_price, tb))
                if ts_ > 0:
                    to.append(Order("TOMATOES", ask_price, -ts_))

                orders["TOMATOES"] = to

        return orders, conversions, json.dumps(
            {"c": self.mc, "f": self.tf, "w": self.ew,
             "pb": self.prev_bid, "ss": round(self.sweep_signal, 3)},
            separators=(",", ":")
        )
