import json
from datamodel import Order, TradingState

"""
s3_aggressive.py — Aggressive Market Making with Tight Posting

HYPOTHESIS: On the website, the taker bot frequency depends on the effective
spread. Posting tighter (inside MM spread) increases taker activity because
the bot sees better prices and trades more often.

DESIGN:
- TOMATOES: Multi-level orders at FV±1, FV±3, FV±5 with size allocation
  that prioritizes the tightest level. If bots react to our presence,
  the tight level captures high-frequency fills and deeper levels catch
  overflow when we're at position limit.
- TOMATOES: Aggressive mean-reversion taking after large moves.
- EMERALDS: Standard arb at 9999/10001 + conversion attempt.

FAIR VALUE: 4-lag microprice regression + trade flow + volume imbalance.
The volume imbalance signal (76% hit rate) adds 0.59 * vol_imb to FV.
"""


class Trader:
    def __init__(self):
        self.mc = []      # microprice cache (4 lags)
        self.tf = []      # trade flow history
        self.ew = []      # EMERALDS liquidation tracking
        self.fills = {"TOMATOES": 0, "EMERALDS": 0}

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.mc = td.get("c", [])
            self.tf = td.get("f", [])
            self.ew = td.get("w", [])

        orders = {}
        conversions = 0

        # Track fills for diagnostics
        for p in state.own_trades:
            self.fills[p] = self.fills.get(p, 0) + len(state.own_trades.get(p, []))

        # ═══════════════════════════════════════════════
        # EMERALDS
        # ═══════════════════════════════════════════════
        if "EMERALDS" in state.order_depths:
            od = state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo = []
                pos = state.position.get("EMERALDS", 0)
                tb, ts_ = 80 - pos, 80 + pos
                buys = sorted(od.buy_orders.items(), reverse=True)
                sells = sorted(od.sell_orders.items())

                # Liquidation tracking
                self.ew.append(abs(pos) == 80)
                if len(self.ew) > 10:
                    self.ew = self.ew[-10:]
                soft = len(self.ew) == 10 and sum(self.ew) >= 5 and self.ew[-1]
                hard = len(self.ew) == 10 and all(self.ew)

                # Take at or below fair (10000)
                for p, v in sells:
                    if tb > 0 and p <= 10000:
                        q = min(tb, -v)
                        eo.append(Order("EMERALDS", p, q))
                        tb -= q

                # Liquidation bids
                if tb > 0 and hard:
                    q = tb // 2
                    eo.append(Order("EMERALDS", 10000, q))
                    tb -= q
                if tb > 0 and soft:
                    q = tb // 2
                    eo.append(Order("EMERALDS", 9998, q))
                    tb -= q

                # Post bid
                if tb > 0:
                    eo.append(Order("EMERALDS", min(9999, buys[0][0] + 1), tb))

                # Take at or above fair
                for p, v in buys:
                    if ts_ > 0 and p >= 10000:
                        q = min(ts_, v)
                        eo.append(Order("EMERALDS", p, -q))
                        ts_ -= q

                # Liquidation asks
                if ts_ > 0 and hard:
                    q = ts_ // 2
                    eo.append(Order("EMERALDS", 10000, -q))
                    ts_ -= q
                if ts_ > 0 and soft:
                    q = ts_ // 2
                    eo.append(Order("EMERALDS", 10002, -q))
                    ts_ -= q

                # Post ask
                if ts_ > 0:
                    eo.append(Order("EMERALDS", max(10001, sells[0][0] - 1), -ts_))

                orders["EMERALDS"] = eo

                # Try conversion: if we have a position, try to flatten via conversion
                if pos > 10:
                    conversions = min(pos, 10)
                elif pos < -10:
                    conversions = max(pos, -10)

        # ═══════════════════════════════════════════════
        # TOMATOES — Full aggressive strategy
        # ═══════════════════════════════════════════════
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb = max(od.buy_orders)
                ba = min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)

                # ─── Fair Value: Microprice Regression ───
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) * 0.5

                c = self.mc
                if len(c) >= 4:
                    c = c[1:]
                c.append(mp)
                self.mc = c

                if len(c) == 4:
                    fv = 2.208667 + 0.059694 * c[0] + 0.117270 * c[1] + 0.244154 * c[2] + 0.578440 * c[3]
                else:
                    fv = mp

                # ─── Trade Flow Signal ───
                trades = state.market_trades.get("TOMATOES")
                mid = (bb + ba) * 0.5
                if trades:
                    sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)
                if len(self.tf) > 5:
                    self.tf = self.tf[-5:]
                fs = max(-1.0, min(1.0, sum(self.tf) / 15.0))
                fv -= fs * 1.5

                # ─── Volume Imbalance Signal (76% hit rate, 0.59 coefficient) ───
                bv1 = od.buy_orders.get(bb, 0)
                av1 = abs(od.sell_orders.get(ba, 0))
                if bv1 != av1 and (bv1 + av1) > 0:
                    vol_imb = (bv1 - av1) / (bv1 + av1)
                    fv += 0.59 * vol_imb

                tv = round(fv)
                spread = ba - bb

                # ─── Capacity ───
                tb = 80 - pos  # max we can buy
                ts_ = 80 + pos  # max we can sell

                # ═══ PHASE 1: AGGRESSIVE TAKING ═══
                # Take anything priced at or below FV (buys) or at/above FV (sells)
                # No position restriction — take at fair regardless of position
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

                # ═══ PHASE 2: MEAN-REVERSION TAKING ═══
                # After large moves (spread < 10 = narrow spread event),
                # aggressively take from the MM in the reversion direction
                if spread < 10:
                    # Narrow spread = just had a large move
                    # The autocorrelation is -0.44, so fade the move
                    # But we need direction — use recent price change
                    if len(c) >= 2:
                        recent_move = c[-1] - c[-2]
                        if recent_move > 2 and ts_ > 0:
                            # Price went up, expect down — sell aggressively
                            best_bid = bb
                            q = min(ts_, 10)
                            to.append(Order("TOMATOES", best_bid, -q))
                            ts_ -= q
                        elif recent_move < -2 and tb > 0:
                            # Price went down, expect up — buy aggressively
                            best_ask = ba
                            q = min(tb, 10)
                            to.append(Order("TOMATOES", best_ask, q))
                            tb -= q

                # ═══ PHASE 3: MULTI-LEVEL POSTING ═══
                # Post at multiple levels to capture fills at different depths
                # Tightest level gets most size (first to be hit)
                # Deeper levels get remaining size (filled if price moves)

                if tb > 0:
                    # Level 1 (tight): FV - 1 or best_bid + 1, whichever is tighter
                    bid_l1 = min(tv - 1, bb + 1)
                    bid_l1 = min(bid_l1, ba - 1)  # don't cross

                    if tb > 20:
                        # Split: 60% at tight level, 40% at deeper level
                        size_l1 = int(tb * 0.6)
                        size_l2 = tb - size_l1
                        bid_l2 = min(tv - 3, bb)  # deeper level
                        bid_l2 = min(bid_l2, ba - 1)

                        to.append(Order("TOMATOES", bid_l1, size_l1))
                        if bid_l2 < bid_l1:  # only post deeper if different price
                            to.append(Order("TOMATOES", bid_l2, size_l2))
                        else:
                            to.append(Order("TOMATOES", bid_l1, size_l2))
                    else:
                        to.append(Order("TOMATOES", bid_l1, tb))

                if ts_ > 0:
                    ask_l1 = max(tv + 1, ba - 1)
                    ask_l1 = max(ask_l1, bb + 1)

                    if ts_ > 20:
                        size_l1 = int(ts_ * 0.6)
                        size_l2 = ts_ - size_l1
                        ask_l2 = max(tv + 3, ba)
                        ask_l2 = max(ask_l2, bb + 1)

                        to.append(Order("TOMATOES", ask_l1, -size_l1))
                        if ask_l2 > ask_l1:
                            to.append(Order("TOMATOES", ask_l2, -size_l2))
                        else:
                            to.append(Order("TOMATOES", ask_l1, -size_l2))
                    else:
                        to.append(Order("TOMATOES", ask_l1, -ts_))

                orders["TOMATOES"] = to

        # Print diagnostics every 100k ticks
        if state.timestamp % 100000 == 0 and state.timestamp > 0:
            print(f"t={state.timestamp} fills={self.fills} pos={state.position}")

        return orders, conversions, json.dumps(
            {"c": self.mc, "f": self.tf, "w": self.ew},
            separators=(",", ":")
        )
