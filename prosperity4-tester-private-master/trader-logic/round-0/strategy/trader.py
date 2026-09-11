"""
Module 7: Full A-S Integrated Trader

Unified quoting framework combining all modules:
  - Module 2: Bot Phase Tracker (real-time bot timing)
  - Module 3: Adverse Selection (toxicity-aware spread)
  - Module 4: Quote Timing Optimizer (A-S reservation price + danger-adjusted spread)
  - Module 5: Price Path Reconstruction (volatility + momentum)
  - Module 6: Position Limit Manager (hard constraint enforcement)

For tutorial round: uses proven microprice regression + trade flow as fair value.
For Round 1+: swap in new fair value estimators per product, add new bot profiles.

Single-file deployment: everything is inlined for Lambda submission.
"""

import json
import math
from datamodel import Order, TradingState


# ============================================================
# INLINE BOT PROFILES (from Module 1 offline analysis)
# ============================================================
BOT_PROFILES = {
    'TOMATOES_TAKER': {
        'cadence_ms': 2430, 'cadence_std': 2450,
        'sizes': {2: 0.255, 3: 0.256, 4: 0.246, 5: 0.240},
        'offset_mean': 6.75, 'offset_std': 0.5,
        'products': ['TOMATOES'],
    },
    'EMERALDS_TAKER': {
        'cadence_ms': 4910, 'cadence_std': 4800,
        'sizes': {3: 0.15, 4: 0.158, 5: 0.185, 6: 0.213, 7: 0.148, 8: 0.145},
        'offset_mean': 8.0, 'offset_std': 0.5,
        'products': ['EMERALDS'],
    },
}

# Toxicity rates (from Module 3 — CONFIRMED very low)
# Only 1.2-1.8% of TOMATOES fills are toxic, 0% for EMERALDS
# This means the taker is uninformed noise — quote aggressively
TOXICITY = {'TOMATOES_TAKER': 0.015, 'EMERALDS_TAKER': 0.00}

# A-S parameters per product
AS_PARAMS = {
    'TOMATOES': {'gamma': 0.05, 'sigma_sq': 1.80, 'k': 0.04},
    'EMERALDS': {'gamma': 0.01, 'sigma_sq': 0.50, 'k': 0.02},
}

# Position limits
LIMITS = {'TOMATOES': 80, 'EMERALDS': 80}

T_MAX = 999900  # last timestamp of full day


class Trader:
    def __init__(self):
        # Fair value state
        self.microprice_cache = []
        self.flow_history = []

        # Module 2: Phase tracking
        self.last_seen = {}
        self.phase_estimate = {}

        # Module 5: Price path
        self.prev_mids = {}
        self.vol_estimates = {}

    def bid(self):
        return 15

    def run(self, state: TradingState):
        # Restore state
        td = json.loads(state.traderData) if state.traderData else {}
        self.microprice_cache = td.get('mc', [])
        self.flow_history = td.get('fh', [])
        self.last_seen = td.get('ls', {})
        self.phase_estimate = {k: float(v) for k, v in td.get('pe', {}).items()}
        self.prev_mids = td.get('pm', {})
        self.vol_estimates = td.get('ve', {})

        ts = state.timestamp
        time_remaining = max(0.01, (T_MAX - ts) / T_MAX)

        # Update bot phase tracker (Module 2)
        self._update_phases(state)

        # Compute fair values
        fair_values = {}
        mids = {}

        for product in state.order_depths:
            od = state.order_depths[product]
            if not od.buy_orders or not od.sell_orders:
                continue
            bb = max(od.buy_orders.keys())
            ba = min(od.sell_orders.keys())
            mids[product] = (bb + ba) / 2.0

            if product == 'EMERALDS':
                fair_values[product] = 10000
            elif product == 'TOMATOES':
                fair_values[product] = self._tomatoes_fair_value(od, state)
            else:
                # Round 1+: add new product fair value estimators here
                fair_values[product] = round((bb + ba) / 2.0)

        # Update price path (Module 5)
        self._update_price_path(mids)

        # Build orders per product
        all_orders = {}
        for product in state.order_depths:
            od = state.order_depths[product]
            if not od.buy_orders or not od.sell_orders:
                continue

            fv = fair_values.get(product)
            if fv is None:
                continue

            position = state.position.get(product, 0)
            limit = LIMITS.get(product, 80)
            to_buy = limit - position
            to_sell = limit + position

            buys = sorted(od.buy_orders.items(), reverse=True)
            sells = sorted(od.sell_orders.items())

            orders = []

            if product == 'EMERALDS':
                # EMERALDS: proven strategy (with liquidation tracking for extra PnL)
                orders = self._emeralds_orders(od, position, fv, limit, buys, sells)
            else:
                # TOMATOES (and future products): A-S framework
                p = AS_PARAMS.get(product, AS_PARAMS['TOMATOES'])

                # Module 4: Danger level from bot phases
                danger = self._compute_danger(product, ts)

                # A-S reservation price (Module 7 core)
                reservation = fv - position * p['gamma'] * p['sigma_sq'] * time_remaining

                # Volatility-adjusted spread
                vol = self.vol_estimates.get(product, 1.0)
                vol_factor = max(0.5, min(2.0, vol / 1.34))  # normalize to baseline

                # Position-dependent aggression (proven +175 PnL on website)
                pos_aggression = 1 if abs(position) > limit * 0.5 else 0

                # TAKE phase: use fair value (not reservation) for taking decisions
                tv = round(fv)
                max_buy_price = tv - pos_aggression if position > limit * 0.5 else tv
                min_sell_price = tv + pos_aggression if position < -limit * 0.5 else tv

                for price, volume in sells:
                    if to_buy > 0 and price <= max_buy_price:
                        q = min(to_buy, -volume)
                        orders.append(Order(product, price, q))
                        to_buy -= q

                for price, volume in buys:
                    if to_sell > 0 and price >= min_sell_price:
                        q = min(to_sell, volume)
                        orders.append(Order(product, price, -q))
                        to_sell -= q

                # MAKE phase: use reservation price + danger-adjusted spread
                half_spread = max(1, round(1.0 * vol_factor * (1 + danger * 0.5)))

                if to_buy > 0:
                    bid_price = min(round(reservation) - half_spread, buys[0][0] + 1)
                    bid_price = min(bid_price, sells[0][0] - 1)
                    orders.append(Order(product, int(bid_price), to_buy))

                if to_sell > 0:
                    ask_price = max(round(reservation) + half_spread, sells[0][0] - 1)
                    ask_price = max(ask_price, buys[0][0] + 1)
                    orders.append(Order(product, int(ask_price), -to_sell))

            # Module 6: Final position limit validation
            total_buy = sum(o.quantity for o in orders if o.quantity > 0)
            total_sell = sum(abs(o.quantity) for o in orders if o.quantity < 0)
            if position + total_buy > limit or position - total_sell < -limit:
                # Trim to fit (shouldn't happen with correct logic, but safety net)
                orders = self._trim_orders(orders, product, position, limit)

            all_orders[product] = orders

        # Save state
        trader_data = json.dumps({
            'mc': self.microprice_cache,
            'fh': self.flow_history,
            'ls': self.last_seen,
            'pe': {k: v for k, v in self.phase_estimate.items()},
            'pm': self.prev_mids,
            've': self.vol_estimates,
        }, separators=(',', ':'))

        return all_orders, 0, trader_data

    # ============================================================
    # FAIR VALUE ESTIMATORS
    # ============================================================

    def _tomatoes_fair_value(self, od, state) -> float:
        """Microprice regression + trade flow (proven 2,851 on website)."""
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        bv = sum(od.buy_orders.values())
        av = sum(-v for v in od.sell_orders.values())
        mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) * 0.5

        c = self.microprice_cache
        if len(c) >= 4:
            c = c[1:]
        c.append(mp)
        self.microprice_cache = c

        if len(c) == 4:
            fv = 2.208667 + 0.059694*c[0] + 0.117270*c[1] + 0.244154*c[2] + 0.578440*c[3]
        else:
            fv = mp

        # Trade flow signal
        trades = state.market_trades.get("TOMATOES")
        if trades:
            mid = (bb + ba) * 0.5
            sv = sum(t.quantity if t.price >= mid else -t.quantity for t in trades)
            self.flow_history.append(sv)
        else:
            self.flow_history.append(0.0)
        if len(self.flow_history) > 5:
            self.flow_history = self.flow_history[-5:]

        fs = max(-1.0, min(1.0, sum(self.flow_history) / 15.0))
        fv -= fs * 1.5

        return fv

    # ============================================================
    # EMERALDS (proven strategy, don't change)
    # ============================================================

    def _emeralds_orders(self, od, position, fv, limit, buys, sells):
        """EMERALDS: proven approach with position-dependent aggression."""
        orders = []
        to_buy = limit - position
        to_sell = limit + position
        tv = int(fv)

        mbp = tv - 1 if position > limit * 0.5 else tv
        msp = tv + 1 if position < -limit * 0.5 else tv

        for p, v in sells:
            if to_buy > 0 and p <= mbp:
                q = min(to_buy, -v)
                orders.append(Order("EMERALDS", p, q))
                to_buy -= q

        if to_buy > 0:
            orders.append(Order("EMERALDS", min(mbp, buys[0][0] + 1), to_buy))

        for p, v in buys:
            if to_sell > 0 and p >= msp:
                q = min(to_sell, v)
                orders.append(Order("EMERALDS", p, -q))
                to_sell -= q

        if to_sell > 0:
            orders.append(Order("EMERALDS", max(msp, sells[0][0] - 1), -to_sell))

        return orders

    # ============================================================
    # MODULE 2: Bot Phase Tracking
    # ============================================================

    def _update_phases(self, state):
        """Update bot phase estimates from observed trades."""
        ts = state.timestamp
        for product in state.order_depths:
            mid = None
            od = state.order_depths[product]
            if od.buy_orders and od.sell_orders:
                mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2.0

            for trade in state.market_trades.get(product, []):
                bot_id = self._classify_trade(product, trade, ts, mid or 0)
                if bot_id:
                    self.last_seen[bot_id] = ts
                    cadence = BOT_PROFILES[bot_id]['cadence_ms']
                    self.phase_estimate[bot_id] = ts + cadence

    def _classify_trade(self, product, trade, timestamp, mid):
        """Simple classification: match to product's known taker bot."""
        for bot_id, profile in BOT_PROFILES.items():
            if product in profile['products']:
                return bot_id
        return None

    def _compute_danger(self, product, current_ts, horizon_ms=500):
        """Aggregate danger from bots trading this product."""
        danger = 0.0
        for bot_id, tox in TOXICITY.items():
            prof = BOT_PROFILES.get(bot_id, {})
            if product not in prof.get('products', []):
                continue
            if bot_id in self.phase_estimate:
                time_to = max(0, self.phase_estimate[bot_id] - current_ts)
                urgency = max(0, 1.0 - time_to / horizon_ms)
            else:
                urgency = 0.0
            danger += tox * urgency
        return min(1.0, danger)

    # ============================================================
    # MODULE 5: Price Path
    # ============================================================

    def _update_price_path(self, mids):
        """Update volatility estimates from mid price changes."""
        for product, mid in mids.items():
            if product in self.prev_mids:
                move = abs(mid - self.prev_mids[product])
                prev_vol = self.vol_estimates.get(product, move)
                self.vol_estimates[product] = 0.8 * prev_vol + 0.2 * move
            self.prev_mids[product] = mid

    # ============================================================
    # MODULE 6: Position Limit Safety
    # ============================================================

    def _trim_orders(self, orders, product, position, limit):
        """Emergency trim if orders somehow exceed limits."""
        bids = [o for o in orders if o.quantity > 0]
        asks = [o for o in orders if o.quantity < 0]

        max_buy = limit - position
        max_sell = limit + position

        trimmed = []
        remaining_buy = max_buy
        for o in sorted(bids, key=lambda x: x.price, reverse=True):
            if remaining_buy <= 0:
                break
            q = min(o.quantity, remaining_buy)
            trimmed.append(Order(product, o.price, q))
            remaining_buy -= q

        remaining_sell = max_sell
        for o in sorted(asks, key=lambda x: x.price):
            if remaining_sell <= 0:
                break
            q = min(abs(o.quantity), remaining_sell)
            trimmed.append(Order(product, o.price, -q))
            remaining_sell -= q

        return trimmed
