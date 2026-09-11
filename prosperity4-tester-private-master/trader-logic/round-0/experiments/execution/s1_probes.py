import json
from datamodel import Order, TradingState

"""
s1_probes: s2_tradeflow (2,851) + Probe Orders for Price Path Reconstruction

Between our run() calls, the market moves and bots trade. We can't see what
happened, but we CAN infer it from which of our small probe orders got filled.

Place size-1 orders at ±2, ±3, ±4 from fair value. Which ones fill tells us:
- How far the price traveled between iterations
- Which direction the market moved
- Real-time volatility estimation

Use this information to:
1. Detect if we're in a high-vol regime (widen spread next iteration)
2. Detect directional momentum (lean quotes)
3. Better fair value from filled probe prices

IMPORTANT: Probes use minimal capacity (3 lots per side = 6 total out of 80 limit).
The remaining 74+ lots are used for the main MM strategy.
"""

PROBE_SIZES = [1, 1, 1]  # 3 probes per side, 1 lot each
PROBE_OFFSETS = [2, 3, 4]  # distance from fair value


class Trader:
    def __init__(self):
        self.tc = []    # microprice cache
        self.tf = []    # trade flow history
        self.ew = []    # EMERALDS liquidation window
        self.tw = []    # TOMATOES liquidation window
        self.last_probes = {}  # product -> list of (price, side) probes outstanding
        self.vol_estimate = 1.0  # running volatility estimate

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])
            self.ew = td.get("ew", [])
            self.tw = td.get("tw", [])
            self.last_probes = td.get("lp", {})
            self.vol_estimate = td.get("v", 1.0)

        # Reconstruct price path from filled probes
        probe_info = self._analyze_filled_probes(state)

        orders = {}

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

        # ═══ TOMATOES ═══
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

                if len(c) == 4:
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

                # Reserve capacity for probes (3 per side)
                probe_capacity = sum(PROBE_SIZES)  # 3 lots per side
                main_tb = max(0, tb - probe_capacity)
                main_ts = max(0, ts - probe_capacity)

                # TAKE
                for p, v in sorted(od.sell_orders.items()):
                    if main_tb > 0 and p <= mbp:
                        q = min(main_tb, -v); to.append(Order("TOMATOES", p, q)); main_tb -= q
                if main_tb > 0 and hard:
                    q = main_tb // 2; to.append(Order("TOMATOES", tv, q)); main_tb -= q
                if main_tb > 0 and soft:
                    q = main_tb // 2; to.append(Order("TOMATOES", tv - 2, q)); main_tb -= q

                # MAIN POST
                if main_tb > 0:
                    to.append(Order("TOMATOES", min(mbp, bb + 1), main_tb))

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if main_ts > 0 and p >= msp:
                        q = min(main_ts, v); to.append(Order("TOMATOES", p, -q)); main_ts -= q
                if main_ts > 0 and hard:
                    q = main_ts // 2; to.append(Order("TOMATOES", tv, -q)); main_ts -= q
                if main_ts > 0 and soft:
                    q = main_ts // 2; to.append(Order("TOMATOES", tv + 2, -q)); main_ts -= q

                if main_ts > 0:
                    to.append(Order("TOMATOES", max(msp, ba - 1), -main_ts))

                # PROBE ORDERS (size 1 each, at offsets from fair)
                # These detect inter-iteration price movement
                new_probes = []
                remaining_buy = tb - (tb - max(0, tb - probe_capacity)) - main_tb
                remaining_sell = ts - (ts - max(0, ts - probe_capacity)) - main_ts

                # Recalculate remaining capacity correctly
                used_buy = sum(o.quantity for o in to if o.quantity > 0)
                used_sell = sum(abs(o.quantity) for o in to if o.quantity < 0)
                remaining_buy = tb - used_buy
                remaining_sell = ts - used_sell

                for i, offset in enumerate(PROBE_OFFSETS):
                    if remaining_buy >= PROBE_SIZES[i]:
                        probe_price = tv - offset
                        if probe_price > 0:
                            to.append(Order("TOMATOES", probe_price, PROBE_SIZES[i]))
                            remaining_buy -= PROBE_SIZES[i]
                            new_probes.append((probe_price, "buy"))

                    if remaining_sell >= PROBE_SIZES[i]:
                        probe_price = tv + offset
                        to.append(Order("TOMATOES", probe_price, -PROBE_SIZES[i]))
                        remaining_sell -= PROBE_SIZES[i]
                        new_probes.append((probe_price, "sell"))

                self.last_probes["TOMATOES"] = new_probes
                orders["TOMATOES"] = to

        return orders, 0, json.dumps({
            "c": self.tc, "f": self.tf, "ew": self.ew, "tw": self.tw,
            "lp": self.last_probes, "v": self.vol_estimate
        }, separators=(",", ":"))

    def _analyze_filled_probes(self, state: TradingState):
        """Check which probe orders from last iteration got filled."""
        info = {"filled_buy": [], "filled_sell": [], "range": 0}

        tom_probes = self.last_probes.get("TOMATOES", [])
        if not tom_probes:
            return info

        own_trades = state.own_trades.get("TOMATOES", [])
        for trade in own_trades:
            for probe_price, probe_side in tom_probes:
                if trade.price == probe_price and abs(trade.quantity) == 1:
                    if probe_side == "buy":
                        info["filled_buy"].append(probe_price)
                    else:
                        info["filled_sell"].append(probe_price)

        if info["filled_buy"] or info["filled_sell"]:
            all_prices = info["filled_buy"] + info["filled_sell"]
            info["range"] = max(all_prices) - min(all_prices) if len(all_prices) > 1 else 0

            # Update volatility estimate (EMA)
            self.vol_estimate = 0.7 * self.vol_estimate + 0.3 * max(1, info["range"])

        return info
