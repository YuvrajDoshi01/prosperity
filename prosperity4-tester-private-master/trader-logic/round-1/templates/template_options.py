import json
from math import log, sqrt
from statistics import NormalDist
from datamodel import Order, TradingState

"""
template_options.py — Black-Scholes options pricing and IV mean-reversion.

Strategy:
  - Per-strike rolling IV average (window=IV_WINDOW)
  - Trade when IV deviates from its rolling mean by > IV_THRESHOLD
  - Post bid/ask around BS fair value
  - NO delta hedging (spread cost > hedge value per playbook)

UPDATE CHECKLIST when Round 1 data drops:
  1. Set UNDERLYING to the actual underlying symbol
  2. Set STRIKES dict mapping strike price -> voucher symbol
  3. Compute TTE from the round spec (days_remaining / 365)
  4. Measure MEAN_IV from sample data
  5. Tune IV_THRESHOLD and IV_WINDOW
  6. Set LIMIT for each voucher
"""

# ═══ CONFIG — UPDATE FROM SAMPLE DATA ═══
UNDERLYING = "VOLCANIC_ROCK"  # UPDATE: underlying product symbol
STRIKES = {
    9500:  "VOUCHER_9500",
    9750:  "VOUCHER_9750",
    10000: "VOUCHER_10000",
    10250: "VOUCHER_10250",
    10500: "VOUCHER_10500",
}
TTE = 246 / 365       # UPDATE: time to expiry in years (days_remaining / 365)
MEAN_IV = 0.16        # UPDATE: mean implied volatility from data
IV_WINDOW = 150       # Rolling window for per-strike IV average
IV_THRESHOLD = 0.01   # Min IV deviation from rolling mean to trade
LIMIT = 200           # UPDATE: position limit per voucher
POST_SPREAD = 1       # Ticks away from BS fair to post bid/ask


# ═══ Black-Scholes (European call, no dividends, r=0) ═══

_nd = NormalDist()

def bs_call(spot, strike, tte, vol):
    """Black-Scholes call price. Assumes r=0."""
    if tte <= 0 or vol <= 0:
        return max(0, spot - strike)
    d1 = (log(spot / strike) + 0.5 * vol ** 2 * tte) / (vol * sqrt(tte))
    d2 = d1 - vol * sqrt(tte)
    return spot * _nd.cdf(d1) - strike * _nd.cdf(d2)


def bs_delta(spot, strike, tte, vol):
    """Black-Scholes call delta."""
    if tte <= 0 or vol <= 0:
        return 1.0 if spot > strike else 0.0
    d1 = (log(spot / strike) + 0.5 * vol ** 2 * tte) / (vol * sqrt(tte))
    return _nd.cdf(d1)


def bs_vega(spot, strike, tte, vol):
    """Black-Scholes vega (sensitivity to vol)."""
    if tte <= 0 or vol <= 0:
        return 0.0
    d1 = (log(spot / strike) + 0.5 * vol ** 2 * tte) / (vol * sqrt(tte))
    return spot * sqrt(tte) * _nd.pdf(d1)


def implied_vol(market_price, spot, strike, tte, lo=0.01, hi=1.0):
    """Binary search for implied volatility."""
    for _ in range(50):
        mid_vol = (lo + hi) / 2
        price = bs_call(spot, strike, tte, mid_vol)
        if price < market_price:
            lo = mid_vol
        else:
            hi = mid_vol
    return (lo + hi) / 2


class Trader:
    def __init__(self):
        # Per-strike IV history: {strike: [iv1, iv2, ...]}
        self.iv_history = {}

    def bid(self):
        return 15

    def run(self, state: TradingState):
        # ── Restore state ──
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.iv_history = td.get("ivh", {})
            # JSON keys are strings, convert back to int
            self.iv_history = {int(k): v for k, v in self.iv_history.items()}

        orders = {}

        # ── Get underlying spot price ──
        spot = None
        if UNDERLYING in state.order_depths:
            uod = state.order_depths[UNDERLYING]
            if uod.buy_orders and uod.sell_orders:
                spot = (max(uod.buy_orders) + min(uod.sell_orders)) / 2

        if spot is None:
            return orders, 0, json.dumps({"ivh": self.iv_history}, separators=(",", ":"))

        # ── Decrement TTE each tick (approx) ──
        # In competition: TTE decreases by 1/365 per day (1M ticks per day)
        # For now, use the constant. UPDATE: compute dynamically if needed.
        tte = TTE

        # ── Process each strike ──
        for strike, voucher in STRIKES.items():
            if voucher not in state.order_depths:
                continue

            vod = state.order_depths[voucher]
            if not vod.buy_orders or not vod.sell_orders:
                continue

            vbb = max(vod.buy_orders)
            vba = min(vod.sell_orders)
            vmid = (vbb + vba) / 2

            # ── Compute implied vol from market mid ──
            if vmid <= 0:
                continue

            iv = implied_vol(vmid, spot, strike, tte)

            # ── Update per-strike IV rolling history ──
            if strike not in self.iv_history:
                self.iv_history[strike] = []
            self.iv_history[strike].append(round(iv, 6))
            if len(self.iv_history[strike]) > IV_WINDOW:
                self.iv_history[strike] = self.iv_history[strike][-IV_WINDOW:]

            iv_hist = self.iv_history[strike]
            if len(iv_hist) < 5:
                # Not enough data yet, skip
                continue

            # ── Rolling mean IV for this strike ──
            rolling_iv = sum(iv_hist) / len(iv_hist)

            # ── BS fair value at rolling mean IV ──
            fair = bs_call(spot, strike, tte, rolling_iv)
            fair_rounded = round(fair)

            # ── Trade when IV deviates from rolling mean ──
            iv_dev = iv - rolling_iv
            pos = state.position.get(voucher, 0)
            result = []

            tb = LIMIT - pos   # buy capacity
            ts = LIMIT + pos   # sell capacity

            if iv_dev > IV_THRESHOLD and ts > 0:
                # IV above mean -> option overpriced -> sell
                # Take bids at or above fair
                for p, v in sorted(vod.buy_orders.items(), reverse=True):
                    if ts > 0 and p >= fair_rounded:
                        q = min(ts, v)
                        result.append(Order(voucher, p, -q))
                        ts -= q
                # Post ask
                if ts > 0:
                    result.append(Order(voucher, max(fair_rounded + POST_SPREAD, vba - 1), -ts))

            elif iv_dev < -IV_THRESHOLD and tb > 0:
                # IV below mean -> option underpriced -> buy
                # Take asks at or below fair
                for p, v in sorted(vod.sell_orders.items()):
                    if tb > 0 and p <= fair_rounded:
                        q = min(tb, -v)
                        result.append(Order(voucher, p, q))
                        tb -= q
                # Post bid
                if tb > 0:
                    result.append(Order(voucher, min(fair_rounded - POST_SPREAD, vbb + 1), tb))

            else:
                # Neutral: passive market making around fair
                if tb > 0:
                    result.append(Order(voucher, min(fair_rounded - POST_SPREAD, vbb + 1), min(tb, 10)))
                if ts > 0:
                    result.append(Order(voucher, max(fair_rounded + POST_SPREAD, vba - 1), -min(ts, 10)))

            if result:
                orders[voucher] = result

        return orders, 0, json.dumps({
            "ivh": {str(k): v for k, v in self.iv_history.items()},
        }, separators=(",", ":"))
