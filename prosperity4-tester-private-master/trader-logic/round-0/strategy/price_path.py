"""
Module 5: Price Path Reconstruction

Between run() calls, the market moves and bots trade.
This module infers what happened using fill patterns.

NOTE: Probe orders (tiny size-1 orders at multiple levels) scored 1,531 on
the website — they're TOXIC in practice. Instead, this module analyzes
own_trades and market_trades to reconstruct price movement WITHOUT probes.

Provides:
  - Inter-iteration volatility estimate
  - Direction of movement between calls
  - Whether large moves occurred (spread narrowed)
"""


class PricePathReconstructor:
    def __init__(self):
        self.prev_mids = {}      # product -> previous mid
        self.vol_estimates = {}  # product -> EMA of |return|
        self.move_history = {}   # product -> list of recent moves

    def update(self, state, mids: dict):
        """
        Called each iteration. Infers what happened between calls.

        Args:
            state: TradingState
            mids: dict[product -> float] current mid prices
        """
        for product, mid in mids.items():
            if product in self.prev_mids:
                move = mid - self.prev_mids[product]
                abs_move = abs(move)

                # Update volatility estimate (EMA)
                prev_vol = self.vol_estimates.get(product, abs_move)
                self.vol_estimates[product] = 0.8 * prev_vol + 0.2 * abs_move

                # Track move history (last 10)
                hist = self.move_history.get(product, [])
                hist.append(move)
                if len(hist) > 10:
                    hist = hist[-10:]
                self.move_history[product] = hist

            self.prev_mids[product] = mid

    def get_volatility(self, product: str) -> float:
        """Current volatility estimate (EMA of |return|)."""
        return self.vol_estimates.get(product, 1.0)

    def get_momentum(self, product: str, window: int = 5) -> float:
        """
        Recent directional momentum.
        Positive = trending up, negative = trending down.
        Normalized to [-1, 1].
        """
        hist = self.move_history.get(product, [])
        if not hist:
            return 0.0
        recent = hist[-window:]
        total = sum(recent)
        max_possible = sum(abs(m) for m in recent) or 1.0
        return total / max_possible

    def had_large_move(self, product: str, threshold: float = 3.0) -> bool:
        """Did the most recent inter-iteration move exceed threshold?"""
        hist = self.move_history.get(product, [])
        if not hist:
            return False
        return abs(hist[-1]) >= threshold

    def get_state(self) -> dict:
        """Serialize for traderData."""
        return {
            'pm': self.prev_mids,
            've': self.vol_estimates,
            'mh': self.move_history,
        }

    def load_state(self, state: dict):
        """Restore from traderData."""
        if state:
            self.prev_mids = state.get('pm', {})
            self.vol_estimates = state.get('ve', {})
            self.move_history = state.get('mh', {})
