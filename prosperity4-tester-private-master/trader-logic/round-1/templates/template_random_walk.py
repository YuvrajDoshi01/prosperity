import json
from datamodel import Order, TradingState

"""
template_random_walk.py — Market making for a volatile random-walk product.
Proven TOMATOES logic from s25_training_only.

Strategy:
  - Microprice 4-lag regression for fair value estimation
  - Trade flow signal: coef=1.5, window=5, normalized by 15
  - Position aggression at pos > LIMIT * 0.5
  - Directional posting: widen continuation side by +/-3 after +/-4 bid move
  - Post at best +/- 1

UPDATE CHECKLIST when Round 1 data drops:
  1. Change PRODUCT to the actual symbol name
  2. Change LIMIT to the position limit from the spec
  3. Run refit_regression.py on sample data to get new COEFS and INTERCEPT
  4. Verify TRADE_FLOW_COEF and BID_MOVE_THRESHOLD still work
"""

# ═══ CONFIG — UPDATE THESE ═══
PRODUCT = "KELP"        # UPDATE: actual product symbol
LIMIT = 80              # UPDATE: check position limit

# Microprice 4-lag regression — PLACEHOLDERS, refit from data
# Run: python refit_regression.py <prices.csv> <PRODUCT>
COEFS = [0.06, 0.12, 0.24, 0.58]  # UPDATE after running refit_regression.py
INTERCEPT = 2.21                    # UPDATE after running refit_regression.py

# Trade flow parameters (proven +207 on website score)
TRADE_FLOW_COEF = 1.5   # How strongly trade flow shifts fair value
TRADE_FLOW_WINDOW = 5   # Rolling window for trade flow accumulation
TRADE_FLOW_NORM = 15.0  # Normalization denominator (clamps signal to [-1, 1])

# Directional signal parameters (structural, mean reversion -0.44 both days)
BID_MOVE_THRESHOLD = 4  # Minimum bid change to trigger directional signal
SIGNAL_DECAY = 0.7      # Decay factor when bid is flat
DIRECTIONAL_OFFSET = 3  # Extra ticks to widen on continuation side


class Trader:
    def __init__(self):
        self.tc = []        # microprice cache (last 4 values)
        self.tf = []        # trade flow window
        self.prev_bid = None
        self.signal = 0     # directional signal: +1 buy, -1 sell

    def bid(self):
        return 15

    def run(self, state: TradingState):
        # ── Restore state ──
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.tc = td.get("c", [])
            self.tf = td.get("f", [])
            self.prev_bid = td.get("pb")
            self.signal = td.get("sg", 0)

        orders = {}

        if PRODUCT in state.order_depths:
            od = state.order_depths[PRODUCT]
            if od.buy_orders and od.sell_orders:
                result = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get(PRODUCT, 0)
                mid = (bb + ba) * 0.5

                # ── Microprice (model-free, zero params) ──
                bv = sum(od.buy_orders.values())
                av = sum(-v for v in od.sell_orders.values())
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else mid

                # Maintain rolling cache of microprice values
                c = self.tc
                if len(c) >= 4:
                    c = c[1:]
                c.append(mp)
                self.tc = c

                # ── Regression fair value (cross-validated coefficients) ──
                if len(c) == 4:
                    fv = INTERCEPT
                    for i in range(4):
                        fv += COEFS[i] * c[i]
                else:
                    fv = mp

                # ── Trade flow adjustment ──
                trades = state.market_trades.get(PRODUCT)
                if trades:
                    sv = sum(
                        t.quantity if t.price >= mid else -t.quantity
                        for t in trades
                    )
                    self.tf.append(sv)
                else:
                    self.tf.append(0.0)

                if len(self.tf) > TRADE_FLOW_WINDOW:
                    self.tf = self.tf[-TRADE_FLOW_WINDOW:]

                fs = max(-1.0, min(1.0, sum(self.tf) / TRADE_FLOW_NORM))
                fv -= fs * TRADE_FLOW_COEF

                tv = round(fv)

                # ── Directional signal (mean-reverting large moves) ──
                if self.prev_bid is not None:
                    bid_change = bb - self.prev_bid
                    if bid_change >= BID_MOVE_THRESHOLD:
                        self.signal = -1   # price jumped up -> expect reversion down
                    elif bid_change <= -BID_MOVE_THRESHOLD:
                        self.signal = 1    # price dropped -> expect reversion up
                    elif abs(bid_change) <= 1:
                        self.signal *= SIGNAL_DECAY
                self.prev_bid = bb

                tb = LIMIT - pos   # buy capacity
                ts = LIMIT + pos   # sell capacity

                # ── TAKE at fair (with position aggression at 50% limit) ──
                half_limit = LIMIT * 0.5
                mbp = tv - 1 if pos > half_limit else tv   # max buy price
                msp = tv + 1 if pos < -half_limit else tv  # min sell price

                for p, v in sorted(od.sell_orders.items()):
                    if tb > 0 and p <= mbp:
                        q = min(tb, -v)
                        result.append(Order(PRODUCT, p, q))
                        tb -= q

                for p, v in sorted(od.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= msp:
                        q = min(ts, v)
                        result.append(Order(PRODUCT, p, -q))
                        ts -= q

                # ── POST: directional (widen continuation side after large moves) ──
                if self.signal > 0.5:
                    # Bullish signal: tight bid, wide ask
                    if tb > 0:
                        result.append(Order(PRODUCT, min(tv - 1, bb + 1), tb))
                    if ts > 0:
                        ask_price = max(tv + DIRECTIONAL_OFFSET, ba - 1)
                        result.append(Order(PRODUCT, max(ask_price, bb + 1), -ts))
                elif self.signal < -0.5:
                    # Bearish signal: wide bid, tight ask
                    if ts > 0:
                        result.append(Order(PRODUCT, max(tv + 1, ba - 1), -ts))
                    if tb > 0:
                        bid_price = min(tv - DIRECTIONAL_OFFSET, bb + 1)
                        result.append(Order(PRODUCT, min(bid_price, ba - 1), tb))
                else:
                    # Neutral: symmetric posting
                    if tb > 0:
                        result.append(Order(PRODUCT, min(tv - 1, bb + 1), tb))
                    if ts > 0:
                        result.append(Order(PRODUCT, max(tv + 1, ba - 1), -ts))

                orders[PRODUCT] = result

        return orders, 0, json.dumps({
            "c": self.tc, "f": self.tf,
            "pb": self.prev_bid, "sg": round(self.signal, 3)
        }, separators=(",", ":"))
