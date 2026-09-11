import json
from datamodel import Order, TradingState

"""
s34_grid — Multi-level grid posting + terminal flattening.

New ideas from research:
1. GRID POSTING: post at best±1 AND best±2 simultaneously
   - L1 post gets queue priority, fills from taker at best
   - L2 post captures fills when MM bot's L1 is consumed
   - Split capacity between levels (e.g. 60/40)
2. CONDITIONAL SKIP: don't post during narrow-spread ticks (spread ≤ 8)
   - No edge when MM quotes tight, only adverse selection risk
3. TERMINAL FLATTEN: reduce position in last 500 ticks
   - 49% of PnL is MTM variance — flatten to lock in spread capture
4. Cartesian-optimal regression params
"""


class Trader:
    def __init__(self):
        self.mc = []
        self.tf = []
        self.ew = []
        self.prev_bid = None
        self.signal = 0

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.mc = td.get("c", [])
            self.tf = td.get("f", [])
            self.ew = td.get("w", [])
            self.prev_bid = td.get("pb")
            self.signal = td.get("sg", 0)

        orders = {}

        # ═══ EMERALDS (unchanged) ═══
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

        # ═══ TOMATOES (grid + terminal flatten) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb = max(od.buy_orders)
                ba = min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (bb + ba) * 0.5
                spread = ba - bb

                # FV regression (Cartesian-optimal)
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else mid

                c = self.mc
                if len(c) >= 4: c = c[1:]
                c.append(mp)
                self.mc = c

                if len(c) == 4:
                    fv = 2.75 + 0.059694*c[0] + 0.117270*c[1] + 0.244154*c[2] + 0.578440*c[3]
                else:
                    fv = mp

                # Trade flow
                trades = state.market_trades.get("TOMATOES")
                if trades:
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > 10: self.tf = self.tf[-10:]
                fs = max(-1.0, min(1.0, sum(self.tf) / 10.0))
                fv -= fs * 3.0

                tv = round(fv)

                # Directional signal
                if self.prev_bid is not None:
                    bid_change = bb - self.prev_bid
                    if bid_change >= 4:
                        self.signal = -1
                    elif bid_change <= -4:
                        self.signal = 1
                    elif abs(bid_change) <= 1:
                        self.signal = self.signal * 0.9
                self.prev_bid = bb

                tb = 80 - pos
                ts_ = 80 + pos

                # TERMINAL FLATTEN: in last 500 ticks (ts > 149900),
                # bias toward flat position
                ts = state.timestamp
                flatten_mode = ts > 149900

                # CONDITIONAL SKIP: don't post during narrow spread
                narrow = spread <= 8

                # PHASE 1: Take at fair value
                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= tv:
                        q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts_ > 0 and p >= tv:
                        q = min(ts_, v); to.append(Order("TOMATOES", p, -q)); ts_ -= q

                # PHASE 2: Terminal flattening takes
                if flatten_mode and abs(pos) > 10:
                    if pos > 0:
                        # Sell to flatten
                        for p, v in sorted(od.buy_orders.items(), reverse=True):
                            if ts_ > 0 and p >= tv - 2:
                                q = min(ts_, v, pos)
                                to.append(Order("TOMATOES", p, -q))
                                ts_ -= q
                    elif pos < 0:
                        for p, v in sorted(od.sell_orders.items()):
                            if tb > 0 and p <= tv + 2:
                                q = min(tb, -v, abs(pos))
                                to.append(Order("TOMATOES", p, q))
                                tb -= q

                # PHASE 3: Grid posting
                if narrow:
                    # Narrow spread — only post if we need to flatten
                    if flatten_mode:
                        if pos > 0 and ts_ > 0:
                            to.append(Order("TOMATOES", ba - 1, -ts_))
                        elif pos < 0 and tb > 0:
                            to.append(Order("TOMATOES", bb + 1, tb))
                    # else: skip posting entirely — no edge
                else:
                    # Normal/wide spread — grid post at two levels
                    if self.signal > 0.5 and not flatten_mode:
                        # Directional UP: heavy bid, light ask
                        if tb > 0:
                            l1_qty = (tb * 2) // 3
                            l2_qty = tb - l1_qty
                            if l1_qty > 0:
                                to.append(Order("TOMATOES", bb + 1, l1_qty))
                            if l2_qty > 0:
                                to.append(Order("TOMATOES", bb, l2_qty))
                        if ts_ > 0 and pos >= 40:
                            to.append(Order("TOMATOES", ba - 1, -ts_))

                    elif self.signal < -0.5 and not flatten_mode:
                        # Directional DOWN: heavy ask, light bid
                        if ts_ > 0:
                            l1_qty = (ts_ * 2) // 3
                            l2_qty = ts_ - l1_qty
                            if l1_qty > 0:
                                to.append(Order("TOMATOES", ba - 1, -l1_qty))
                            if l2_qty > 0:
                                to.append(Order("TOMATOES", ba, -l2_qty))
                        if tb > 0 and pos <= -40:
                            to.append(Order("TOMATOES", bb + 1, tb))

                    else:
                        # Neutral or flatten: symmetric grid
                        if tb > 0:
                            l1_qty = (tb * 2) // 3
                            l2_qty = tb - l1_qty
                            bp1 = min(tv - 1, bb + 1)
                            bp1 = min(bp1, ba - 1)
                            bp2 = bp1 - 1
                            if l1_qty > 0:
                                to.append(Order("TOMATOES", bp1, l1_qty))
                            if l2_qty > 0:
                                to.append(Order("TOMATOES", bp2, l2_qty))
                        if ts_ > 0:
                            l1_qty = (ts_ * 2) // 3
                            l2_qty = ts_ - l1_qty
                            ap1 = max(tv + 1, ba - 1)
                            ap1 = max(ap1, bb + 1)
                            ap2 = ap1 + 1
                            if l1_qty > 0:
                                to.append(Order("TOMATOES", ap1, -l1_qty))
                            if l2_qty > 0:
                                to.append(Order("TOMATOES", ap2, -l2_qty))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps(
            {"c": self.mc, "f": self.tf, "w": self.ew, "pb": self.prev_bid, "sg": round(self.signal, 3)},
            separators=(",", ":")
        )
