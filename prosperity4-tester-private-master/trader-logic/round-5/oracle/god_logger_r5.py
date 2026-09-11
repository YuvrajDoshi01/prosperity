"""R5 GOD LOGGER — places zero orders, captures pristine market state via Logger.flush.

Submit this and download the .log/.json from the run-logs page to inspect:
  - Live order books for all 50 R5 products with no own-footprint
  - Bot quote dynamics (verify MM non-reactivity holds in R5)
  - Market trades distribution (taker arrival rate, side bias)
  - The exact day(s) IMC runs the live engine on (probe vs final eval)

The Logger.flush pattern emits a single compressed JSON line per tick that
IMC's runtime captures into the activities log — same pattern thedarkmarc's
sub 551021 uses, so we know this transport works in R5.

Use cases:
  - Diff against `prosperity4bt/resources/round5/prices_round_5_day_*.csv`
    historical CSVs to confirm live-vs-CSV calibration (R3/R4 had drift).
  - Capture observations / Ignith news payloads if they ship via observations.
  - Establish baseline bot behavior before iterating strategies.

Behavior: returns {} for orders every tick. Position stays at 0 for all 50
products. conversions=0, trader_data="".
"""
import json
from typing import Any

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict, conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )
        max_item_length = (self.max_log_length - base_length) // 3
        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings):
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths):
        return {sym: [od.buy_orders, od.sell_orders] for sym, od in order_depths.items()}

    def compress_trades(self, trades):
        out = []
        for arr in trades.values():
            for t in arr:
                out.append([t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp])
        return out

    def compress_observations(self, observations):
        conv_obs = {}
        if observations:
            for product, o in observations.conversionObservations.items():
                conv_obs[product] = [
                    o.bidPrice, o.askPrice, o.transportFees,
                    o.exportTariff, o.importTariff,
                    o.sugarPrice, o.sunlightIndex,
                ]
        return [observations.plainValueObservations if observations else {}, conv_obs]

    def compress_orders(self, orders):
        out = []
        for arr in orders.values():
            for o in arr:
                out.append([o.symbol, o.price, o.quantity])
        return out

    def to_json(self, value):
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value, max_length):
        if value is None:
            return ""
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            if len(json.dumps(candidate)) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


class Trader:
    def bid(self):
        return 0

    def run(self, state: TradingState):
        result: dict = {}
        conversions = 0
        trader_data = ""
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
