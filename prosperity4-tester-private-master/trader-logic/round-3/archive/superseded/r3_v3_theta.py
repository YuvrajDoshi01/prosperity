"""r3_v3_theta.py — v3 + terminal theta harvest A/B variant.

Added vs v3:
  F5. In last 10% of day (timestamp > 900,000), sell OTM vouchers aggressively
      to capture time decay if round-end liquidation is at intrinsic/BS-fair.

Ship only if BT shows >= v3 on 2/3 days. Risk: if liquidation is at market
mid, theta is pre-priced and edge is zero.
"""
import itertools
import json
from statistics import stdev

from datamodel import Order, TradingState

# Products
HYDROGEL = "HYDROGEL_PACK"
VEVE = "VELVETFRUIT_EXTRACT"
LIMIT_D1 = 200
LIMIT_V = 300

STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
STRIKES_TRADEABLE = [5000, 5100, 5200, 5300, 5400]
SYM = {k: f"VEV_{k}" for k in STRIKES_ALL}

# Intrinsic arb
INTRINSIC_EDGE = 2
INTRINSIC_QTY = 50

# Call-spread arb (F1)
ARB_SAFETY_MARGIN = 0.95   # require arb edge >= 5% of bound
ARB_SIZE = 10              # small size — rare opportunities
SPOT_STALE_LIMIT = 3       # ticks

# Voucher MM (unchanged from v1)
VOUCHER_MM_SIZE = 20
VOUCHER_MIN_SPREAD = 2

# Delta-1 MM
POST_SLACK_VE = 1          # VELVETFRUIT_EXTRACT unchanged
HP_VOL_WINDOW = 20         # HYDROGEL rolling stdev window (F3)
HP_SLACK_MIN = 1
HP_SLACK_MAX = 3           # cap to avoid posting outside spread


def plain_mid(od):
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    return 0.5 * (max(od.buy_orders) + min(od.sell_orders))


class Trader:
    def __init__(self):
        self.hp_mid_history = []    # for vol-scaled HYDROGEL MM
        self.last_spot = None
        self.spot_age = 0

    def bid(self):
        return 800

    def _get_spot(self, state):
        """Underlying spot with freshness tracking."""
        od = state.order_depths.get(VEVE)
        mp = plain_mid(od)
        if mp is not None:
            self.last_spot = mp
            self.spot_age = 0
            return mp
        self.spot_age += 1
        if self.spot_age < 20 and self.last_spot is not None:
            return self.last_spot
        return None

    def _hp_slack(self, mid):
        """Vol-scaled post width for HYDROGEL_PACK (F3)."""
        self.hp_mid_history.append(mid)
        if len(self.hp_mid_history) > HP_VOL_WINDOW:
            del self.hp_mid_history[:len(self.hp_mid_history) - HP_VOL_WINDOW]
        if len(self.hp_mid_history) < 5:
            return HP_SLACK_MIN
        sigma = stdev(self.hp_mid_history)
        slack = int(round(0.5 * sigma))
        return max(HP_SLACK_MIN, min(HP_SLACK_MAX, slack))

    def _mm_delta1(self, state, product, limit, slack):
        od = state.order_depths.get(product)
        mp = plain_mid(od)
        if mp is None:
            return []
        bb, ba = max(od.buy_orders), min(od.sell_orders)
        pos = state.position.get(product, 0)
        fv = round(mp)
        tb, ts = limit - pos, limit + pos
        half = limit * 0.5
        mbp = fv - 1 if pos > half else fv
        msp = fv + 1 if pos < -half else fv
        result = []
        for p, v in sorted(od.sell_orders.items()):
            if tb > 0 and p <= mbp:
                q = min(tb, -v)
                result.append(Order(product, p, q))
                tb -= q
        for p, v in sorted(od.buy_orders.items(), reverse=True):
            if ts > 0 and p >= msp:
                q = min(ts, v)
                result.append(Order(product, p, -q))
                ts -= q
        if tb > 0:
            result.append(Order(product, min(fv - slack, bb + 1), tb))
        if ts > 0:
            result.append(Order(product, max(fv + slack, ba - 1), -ts))
        return result

    def _voucher_mm(self, state, strike):
        product = SYM[strike]
        od = state.order_depths.get(product)
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        vbb, vba = max(od.buy_orders), min(od.sell_orders)
        if vba - vbb < VOUCHER_MIN_SPREAD:
            return []
        pos = state.position.get(product, 0)
        tb, ts = LIMIT_V - pos, LIMIT_V + pos
        result = []
        if tb > 0:
            result.append(Order(product, vbb + 1, min(tb, VOUCHER_MM_SIZE)))
        if ts > 0:
            result.append(Order(product, vba - 1, -min(ts, VOUCHER_MM_SIZE)))
        return result

    def _intrinsic_arb(self, state, strike, spot, existing_orders):
        """Strict no-arbitrage bounds on European calls.

        Lower bound: C(K) >= max(S-K, 0). Buy if ask < bound.
        Upper bound: C(K) <= S. Sell if bid > S.

        The v1 sell rule `bid > intrinsic + edge` was NOT a strict arb — it
        assumed TV < edge, which is true for deep ITM only (4000/4500).
        Applying it to ATM/OTM strikes (TV ~ 10) caused -$30k losses in v3.
        """
        product = SYM[strike]
        od = state.order_depths.get(product)
        if od is None:
            return []
        pos = state.position.get(product, 0)
        already_buy = sum(o.quantity for o in existing_orders if o.quantity > 0)
        already_sell = sum(-o.quantity for o in existing_orders if o.quantity < 0)
        tb = LIMIT_V - pos - already_buy
        ts = LIMIT_V + pos - already_sell
        lower_bound = max(spot - strike, 0.0)
        result = []
        # BUY side: ask below intrinsic lower bound (strict arb)
        for p, v in sorted(od.sell_orders.items()):
            if tb > 0 and p < lower_bound - INTRINSIC_EDGE:
                q = min(tb, -v, INTRINSIC_QTY)
                result.append(Order(product, p, q))
                tb -= q
        # SELL side: bid above spot (upper bound violation — very rare but safe)
        for p, v in sorted(od.buy_orders.items(), reverse=True):
            if ts > 0 and p > spot + INTRINSIC_EDGE:
                q = min(ts, v, INTRINSIC_QTY)
                result.append(Order(product, p, -q))
                ts -= q
        return result

    def _call_spread_arb(self, state, orders_so_far):
        """F1: Scan all 45 strike pairs for call-spread arbitrage.

        For K_lo < K_hi: a call spread (long low strike, short high strike) has
        payoff in [0, K_hi - K_lo]. So cost must be in [0, K_hi - K_lo].
        If executable cost (ask_lo - bid_hi) exceeds bound: sell the spread
        (sell K_lo at bid, buy K_hi at ask) for profit.
        If executable cost is NEGATIVE: long the spread (buy K_lo at ask, sell K_hi at bid) for risk-free gain.
        """
        fills = []
        # Compute per-product buy/sell already committed
        committed_buy = {sym: 0 for sym in SYM.values()}
        committed_sell = {sym: 0 for sym in SYM.values()}
        for sym, ord_list in orders_so_far.items():
            if sym in committed_buy:
                committed_buy[sym] = sum(o.quantity for o in ord_list if o.quantity > 0)
                committed_sell[sym] = sum(-o.quantity for o in ord_list if o.quantity < 0)

        for K_lo, K_hi in itertools.combinations(STRIKES_ALL, 2):
            sym_lo, sym_hi = SYM[K_lo], SYM[K_hi]
            od_lo = state.order_depths.get(sym_lo)
            od_hi = state.order_depths.get(sym_hi)
            if od_lo is None or od_hi is None:
                continue

            pos_lo = state.position.get(sym_lo, 0)
            pos_hi = state.position.get(sym_hi, 0)

            # CASE A: buy K_lo at ask, sell K_hi at bid — "negative cost" arb
            if od_lo.sell_orders and od_hi.buy_orders:
                ask_lo = min(od_lo.sell_orders)
                bid_hi = max(od_hi.buy_orders)
                cost = ask_lo - bid_hi
                # Arb if cost < 0 (free money): pay < 0 to own a long-low/short-high spread
                if cost < 0:
                    ask_lo_vol = -od_lo.sell_orders[ask_lo]
                    bid_hi_vol = od_hi.buy_orders[bid_hi]
                    room_buy_lo = LIMIT_V - pos_lo - committed_buy[sym_lo]
                    room_sell_hi = LIMIT_V + pos_hi - committed_sell[sym_hi]
                    size = min(ARB_SIZE, ask_lo_vol, bid_hi_vol, room_buy_lo, room_sell_hi)
                    if size > 0:
                        fills.append((sym_lo, ask_lo, +size))
                        fills.append((sym_hi, bid_hi, -size))
                        committed_buy[sym_lo] += size
                        committed_sell[sym_hi] += size

            # CASE B: sell K_lo at bid, buy K_hi at ask — "too wide" spread arb
            # If bid_lo - ask_hi > 0: we get paid more than we pay, payoff capped at 0
            if od_lo.buy_orders and od_hi.sell_orders:
                bid_lo = max(od_lo.buy_orders)
                ask_hi = min(od_hi.sell_orders)
                # Short-spread: receive bid_lo - ask_hi up front, max loss = K_hi - K_lo
                # Profitable if bid_lo - ask_hi >= (K_hi - K_lo): can close the spread at expiry with zero loss
                # (only possible if market is wildly mispriced - very rare)
                edge = bid_lo - ask_hi - (K_hi - K_lo)
                if edge > 2:  # require 2 ticks of edge
                    bid_lo_vol = od_lo.buy_orders[bid_lo]
                    ask_hi_vol = -od_hi.sell_orders[ask_hi]
                    room_sell_lo = LIMIT_V + pos_lo - committed_sell[sym_lo]
                    room_buy_hi = LIMIT_V - pos_hi - committed_buy[sym_hi]
                    size = min(ARB_SIZE, bid_lo_vol, ask_hi_vol, room_sell_lo, room_buy_hi)
                    if size > 0:
                        fills.append((sym_lo, bid_lo, -size))
                        fills.append((sym_hi, ask_hi, +size))
                        committed_sell[sym_lo] += size
                        committed_buy[sym_hi] += size

        return fills

    def run(self, state: TradingState):
        orders = {}

        # Delta-1 MM with vol-scaled HP slack
        hp_mid = plain_mid(state.order_depths.get(HYDROGEL))
        hp_slack = self._hp_slack(hp_mid) if hp_mid is not None else HP_SLACK_MIN
        ho = self._mm_delta1(state, HYDROGEL, LIMIT_D1, hp_slack)
        if ho:
            orders[HYDROGEL] = ho
        vo = self._mm_delta1(state, VEVE, LIMIT_D1, POST_SLACK_VE)
        if vo:
            orders[VEVE] = vo

        # Spot for voucher arbs
        spot = self._get_spot(state)
        if spot is None or self.spot_age > SPOT_STALE_LIMIT:
            # No spot → skip voucher arbs; still run voucher MM (no spot dependence)
            for K in STRIKES_TRADEABLE:
                r = self._voucher_mm(state, K)
                if r:
                    orders[SYM[K]] = r
            return orders, 0, ""

        # F2: Intrinsic arb on ALL strikes (strict arb bounds, safe for all)
        for K in STRIKES_ALL:
            r = self._intrinsic_arb(state, K, spot, orders.get(SYM[K], []))
            if r:
                orders.setdefault(SYM[K], []).extend(r)

        # F1: Call-spread arbitrage scanner
        arb_fills = self._call_spread_arb(state, orders)
        for sym, price, qty in arb_fills:
            orders.setdefault(sym, []).append(Order(sym, price, qty))

        # Voucher MM (fills remaining capacity after arbs)
        for K in STRIKES_TRADEABLE:
            existing = orders.get(SYM[K], [])
            existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
            existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
            pos = state.position.get(SYM[K], 0)
            od = state.order_depths.get(SYM[K])
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            vbb, vba = max(od.buy_orders), min(od.sell_orders)
            if vba - vbb < VOUCHER_MIN_SPREAD:
                continue
            tb = LIMIT_V - pos - existing_buy
            ts = LIMIT_V + pos - existing_sell
            if tb > 0:
                orders.setdefault(SYM[K], []).append(
                    Order(SYM[K], vbb + 1, min(tb, VOUCHER_MM_SIZE))
                )
            if ts > 0:
                orders.setdefault(SYM[K], []).append(
                    Order(SYM[K], vba - 1, -min(ts, VOUCHER_MM_SIZE))
                )

        # F5: Terminal theta harvest (last 10% of day)
        # Sell OTM vouchers aggressively to capture time decay (if liquidation at intrinsic)
        if state.timestamp > 900_000:
            for K in [5300, 5400, 5500]:
                if spot + 5 < K:  # confidently OTM
                    sym = SYM[K]
                    od = state.order_depths.get(sym)
                    if od is None or not od.buy_orders:
                        continue
                    pos = state.position.get(sym, 0)
                    existing = orders.get(sym, [])
                    existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)
                    ts = LIMIT_V + pos - existing_sell
                    if ts > 0:
                        vba = min(od.sell_orders) if od.sell_orders else max(od.buy_orders) + 1
                        target = -min(30, ts)
                        orders.setdefault(sym, []).append(
                            Order(sym, max(vba - 1, max(od.buy_orders) + 1), target)
                        )

        return orders, 0, ""
