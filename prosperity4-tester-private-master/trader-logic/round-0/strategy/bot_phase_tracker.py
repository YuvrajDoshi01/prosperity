"""
Module 2: Bot Phase Tracker (Real-Time)

Maintains running estimates of each bot's phase (time until next action).
For tutorial round: one random taker bot, phase estimation is probabilistic.
For Round 1+: multiple bots with distinct cadences, Bayesian classification.

Uses bot profiles (hardcoded or from Module 1) as priors.
Updates in real-time from market_trades and own_trades.
"""

import math
from dataclasses import dataclass, field


@dataclass
class BotProfile:
    bot_id: str
    cadence_ms: float           # mean inter-action interval
    cadence_std: float          # jitter in timing
    size_distribution: dict     # {size: probability}
    spread_offset_mean: float   # typical distance from mid
    spread_offset_std: float
    aggression_ratio: float     # 0 = pure MM, 1 = pure taker
    side_bias: float            # -1 = always sell, +1 = always buy, 0 = balanced
    active_products: list = field(default_factory=list)


# Default profiles from Module 1 analysis (tutorial round)
DEFAULT_PROFILES = {
    'TOMATOES_TAKER': BotProfile(
        bot_id='TOMATOES_TAKER',
        cadence_ms=2430, cadence_std=2450,
        size_distribution={2: 0.255, 3: 0.256, 4: 0.246, 5: 0.240},
        spread_offset_mean=6.75, spread_offset_std=0.5,
        aggression_ratio=1.0, side_bias=0.0,
        active_products=['TOMATOES'],
    ),
    'EMERALDS_TAKER': BotProfile(
        bot_id='EMERALDS_TAKER',
        cadence_ms=4910, cadence_std=4800,
        size_distribution={3: 0.15, 4: 0.158, 5: 0.185, 6: 0.213, 7: 0.148, 8: 0.145},
        spread_offset_mean=8.0, spread_offset_std=0.5,
        aggression_ratio=1.0, side_bias=0.0,
        active_products=['EMERALDS'],
    ),
}


class BotPhaseTracker:
    def __init__(self, profiles: dict = None):
        self.profiles = profiles or DEFAULT_PROFILES
        self.last_seen = {}       # bot_id -> last timestamp
        self.phase_estimate = {}  # bot_id -> estimated next action timestamp
        self.trade_count = {}     # bot_id -> count of attributed trades

    def update(self, timestamp: int, market_trades: dict, own_trades: dict, mids: dict):
        """
        Called every iteration with new trades.
        Classifies trades to bot profiles and updates phase estimates.

        Args:
            timestamp: current timestamp
            market_trades: dict[product -> list[Trade]]
            own_trades: dict[product -> list[Trade]]
            mids: dict[product -> float] current mid prices
        """
        all_trades = []
        for product, trades in market_trades.items():
            for trade in trades:
                all_trades.append((product, trade, 'market'))
        for product, trades in own_trades.items():
            for trade in trades:
                all_trades.append((product, trade, 'own'))

        for product, trade, source in all_trades:
            bot_id = self._classify_trade(product, trade, timestamp, mids.get(product, 0))
            if bot_id:
                self.last_seen[bot_id] = timestamp
                profile = self.profiles[bot_id]
                self.phase_estimate[bot_id] = timestamp + profile.cadence_ms
                self.trade_count[bot_id] = self.trade_count.get(bot_id, 0) + 1

    def time_until_next(self, bot_id: str, current_ts: int) -> float:
        """Estimated ms until this bot next acts."""
        if bot_id not in self.phase_estimate:
            return self.profiles[bot_id].cadence_ms  # prior
        return max(0, self.phase_estimate[bot_id] - current_ts)

    def urgency(self, bot_id: str, current_ts: int, horizon_ms: float = 500) -> float:
        """
        How "urgent" is this bot's next action? 0 = far away, 1 = imminent.
        Used by Module 4 to adjust quoting aggressiveness.
        """
        time_to_next = self.time_until_next(bot_id, current_ts)
        return max(0.0, 1.0 - time_to_next / horizon_ms)

    def _classify_trade(self, product: str, trade, timestamp: int, mid: float) -> str:
        """
        Bayesian classification: assign trade to most likely bot.
        Uses timing, size, and price offset as features.
        """
        best_bot = None
        best_score = float('-inf')

        for bot_id, profile in self.profiles.items():
            if product not in profile.active_products:
                continue

            score = 0.0

            # Timing likelihood
            if bot_id in self.last_seen:
                dt = timestamp - self.last_seen[bot_id]
                if profile.cadence_std > 0:
                    z = (dt - profile.cadence_ms) / profile.cadence_std
                    score += -0.5 * z * z  # log-normal approximation
            # else: uninformative prior (score += 0)

            # Size likelihood
            qty = abs(trade.quantity)
            prob = profile.size_distribution.get(qty, 0.01)
            score += math.log(max(prob, 1e-6))

            # Price offset likelihood
            offset = abs(trade.price - mid)
            if profile.spread_offset_std > 0:
                z = (offset - profile.spread_offset_mean) / profile.spread_offset_std
                score += -0.5 * z * z

            if score > best_score:
                best_score = score
                best_bot = bot_id

        return best_bot

    def get_state(self) -> dict:
        """Serialize for traderData persistence."""
        return {
            'ls': {k: v for k, v in self.last_seen.items()},
            'pe': {k: v for k, v in self.phase_estimate.items()},
            'tc': {k: v for k, v in self.trade_count.items()},
        }

    def load_state(self, state: dict):
        """Restore from traderData."""
        if state:
            self.last_seen = state.get('ls', {})
            self.phase_estimate = {k: float(v) for k, v in state.get('pe', {}).items()}
            self.trade_count = state.get('tc', {})
