from contextlib import closing, redirect_stdout
from io import StringIO
from IPython.utils.io import Tee
from tqdm import tqdm
from prosperity4bt.constants import LIMITS
from prosperity4bt.models.test_options import TradeMatchingMode, MatchMode, ExtraFlowMode
from prosperity4bt.tools.data_reader import BackDataReader
from prosperity4bt.datamodel import TradingState, Observation, Symbol, Order, OrderDepth, Listing, ConversionObservation
from prosperity4bt.tools.log_creator import ActivityLogCreator
from prosperity4bt.models.input import BacktestData
from prosperity4bt.models.output import BacktestResult
from prosperity4bt.models.output import SandboxLogRow
from prosperity4bt.tools.order_match_maker import OrderMatchMaker


class TestRunner:

    def __init__(self, trader, data_reader: BackDataReader, round: int, day: int, show_progress_bar: bool=False, print_output: bool=False, trade_matching_mode=TradeMatchingMode.all, max_ticks: int=None, iterations: int=None, match_mode: MatchMode=MatchMode.default, extra_flow: ExtraFlowMode=ExtraFlowMode.none):
        self.trader = trader
        self.data_reader = data_reader
        self.round = round
        self.day = day
        self.show_progress_bar = show_progress_bar
        self.print_output = print_output
        self.trade_matching_mode = trade_matching_mode
        self.max_ticks = max_ticks
        self.iterations = iterations  # None = call run() every tick
        self.match_mode = match_mode
        self.extra_flow = extra_flow


    def run(self):
        # Expose round/day to the trader via env vars (pattern borrowed from shh1v).
        # Lets traders auto-configure TTE, etc. without manual per-day edits.
        import os
        os.environ["PROSPERITY4BT_ROUND"] = str(self.round)
        os.environ["PROSPERITY4BT_DAY"] = str(self.day)

        data = self.data_reader.read_from_file(self.round, self.day)
        state = TradingState(
            traderData="",
            timestamp=0,
            listings={},
            order_depths={},
            own_trades={},
            market_trades={},
            position={},
            observations=Observation({}, {}),
        )
        result = BacktestResult(data.round_num, data.day_num)

        timestamps = sorted(data.prices.keys())
        if self.max_ticks is not None:
            timestamps = timestamps[:self.max_ticks]

        # Determine which ticks call run() vs just match resting orders
        if self.iterations is not None and self.iterations < len(timestamps):
            call_interval = max(1, len(timestamps) // self.iterations)
            call_ticks = set(timestamps[i] for i in range(0, len(timestamps), call_interval))
        else:
            call_ticks = set(timestamps)  # call every tick (default)

        resting_orders = {}  # orders that persist between run() calls

        timestamps_iterator = tqdm(timestamps, ascii=True) if self.show_progress_bar else timestamps
        for timestamp in timestamps_iterator:
            state = self.__initialize_trade_state(state, data, timestamp)

            if timestamp in call_ticks:
                # CALL TICK: run the trader, get new orders
                orders = self.__run_trader(state, result, timestamp)
            else:
                # RESTING TICK: use previous orders, still create sandbox log
                orders = self.__rebuild_resting_orders(resting_orders, state)
                sandbox_row = SandboxLogRow(timestamp=timestamp, sandbox_log="", lambda_log="")
                result.sandbox_logs.append(sandbox_row)

            self.__create_activity_logs(state, data, result)
            self.__enforce_limits(state, data, orders, result.sandbox_logs[-1])
            self.__match_orders(state, data, orders, result)

            # Update resting orders with remaining quantities after fills
            # (Order.quantity is mutated during matching — partial fills reduce it)
            # Without this, resting orders on the next tick have the ORIGINAL qty,
            # causing position limit violations and order rejection.
            resting_orders = self.__deep_copy_orders(orders)

        return result

    def __deep_copy_orders(self, orders: dict) -> dict:
        """Store a copy of orders for resting between run() calls."""
        copy = {}
        for product, order_list in orders.items():
            copy[product] = [(o.symbol, o.price, o.quantity) for o in order_list]
        return copy

    def __rebuild_resting_orders(self, resting: dict, state: TradingState) -> dict:
        """Rebuild Order objects from stored resting orders for matching."""
        orders = {}
        for product, order_tuples in resting.items():
            orders[product] = [Order(sym, price, qty) for sym, price, qty in order_tuples]
        return orders

    def __run_trader(self, state: TradingState, result: BacktestResult, timestamp: int) -> dict[Symbol, list[Order]]:
        stdout = StringIO()
        # Tee calls stdout.close(), making stdout.getvalue() impossible
        # This override makes getvalue() possible after close()
        stdout.close = lambda: None  # type: ignore[method-assign]

        if self.print_output:
            with closing(Tee(stdout)):
                orders, conversions, trader_data = self.trader.run(state)
        else:
            with redirect_stdout(stdout):
                orders, conversions, trader_data = self.trader.run(state)

        state.traderData = trader_data

        sandbox_row = SandboxLogRow(
            timestamp=timestamp,
            sandbox_log="",
            lambda_log=stdout.getvalue().rstrip(),
        )
        result.sandbox_logs.append(sandbox_row)

        return orders


    def __initialize_trade_state(self, state: TradingState, data: BacktestData, timestamp: int) -> TradingState:

        state.timestamp = timestamp

        # Preserve previous tick's own_trades and market_trades — IMC live engine passes
        # "trades since last iteration", which means trades from the just-completed tick
        # are visible to the next trader.run() call. Previously these were cleared here,
        # breaking counterparty-aware strategies. Trades from this tick will be added
        # by __match_orders after trader.run() executes.
        # (If state has no prior trades dict, initialize empty.)
        if not hasattr(state, "own_trades") or state.own_trades is None:
            state.own_trades = {}
        if not hasattr(state, "market_trades") or state.market_trades is None:
            state.market_trades = {}

        for product in data.products:
            order_depth = OrderDepth()
            row = data.prices[state.timestamp][product]

            for price, volume in zip(row.bid_prices, row.bid_volumes):
                order_depth.buy_orders[price] = volume

            for price, volume in zip(row.ask_prices, row.ask_volumes):
                order_depth.sell_orders[price] = -volume

            state.order_depths[product] = order_depth
            state.listings[product] = Listing(product, product, 1)

        if self.extra_flow != ExtraFlowMode.none:
            self.__apply_extra_flow(state)

        observation_row = data.observations.get(state.timestamp)
        if observation_row is None:
            state.observations = Observation({}, {})
        else:
            conversion_observation = ConversionObservation(
                bidPrice=observation_row.bidPrice,
                askPrice=observation_row.askPrice,
                transportFees=observation_row.transportFees,
                exportTariff=observation_row.exportTariff,
                importTariff=observation_row.importTariff,
                sugarPrice=observation_row.sugarPrice,
                sunlightIndex=observation_row.sunlightIndex,
            )
            state.observations = Observation(
                plainValueObservations={}, conversionObservations={"MAGNIFICENT_MACARONS": conversion_observation}
            )

        return state


    def __apply_extra_flow(self, state: TradingState) -> None:
        """Simulates R2 MAF "extra 25% flow" by mutating state.order_depths in place.

        Per R2 brief: "the volumes and prices of these quotes fit perfectly in the
        distribution of the already available quotes. Example: given ask[9]=10 and
        ask[7]=10, inject ask[8]=5".

        Two modes:
          scale:  multiply all existing volumes by 1.25 (pragmatic; no new levels)
          interp: inject a new level at the midpoint between each pair of consecutive
                  price levels with volume = 0.25 * min(surrounding volumes). Matches
                  the brief's literal semantics when gaps >= 2 ticks.
        """
        for od in state.order_depths.values():
            if self.extra_flow == ExtraFlowMode.scale:
                for price in list(od.buy_orders.keys()):
                    od.buy_orders[price] = int(round(od.buy_orders[price] * 1.25))
                for price in list(od.sell_orders.keys()):
                    # sell_orders store negative volumes; scale absolute value
                    od.sell_orders[price] = -int(round(abs(od.sell_orders[price]) * 1.25))
            elif self.extra_flow == ExtraFlowMode.interp:
                od.buy_orders = self.__interp_levels(od.buy_orders, sign=1)
                od.sell_orders = self.__interp_levels(od.sell_orders, sign=-1)

    def __interp_levels(self, orders: dict, sign: int) -> dict:
        """Inject midpoint levels between consecutive existing levels.
        sign=1 for buy_orders (positive volumes), sign=-1 for sell_orders (negative)."""
        if len(orders) < 2:
            return orders
        prices = sorted(orders.keys())
        new_orders = dict(orders)
        for i in range(len(prices) - 1):
            p_lo, p_hi = prices[i], prices[i + 1]
            if p_hi - p_lo < 2:
                continue
            p_mid = (p_lo + p_hi) // 2
            if p_mid in new_orders:
                continue
            v_lo = abs(orders[p_lo])
            v_hi = abs(orders[p_hi])
            v_mid = int(round(0.25 * min(v_lo, v_hi)))
            if v_mid > 0:
                new_orders[p_mid] = sign * v_mid
        return new_orders


    # def __validate_orders(self, orders: dict[Symbol, list[Order]]) -> None:
    #     for key, value in orders.items():
    #         if not isinstance(key, str):
    #             raise ValueError(f"Orders key '{key}' is of type {type(key)}, expected a str")
    #         for order in value:
    #             if not isinstance(order.symbol, str):
    #                 raise ValueError(f"Order symbol of '{order}' is of type {type(order.symbol)}, expected a str")
    #             if not isinstance(order.price, int):
    #                 raise ValueError(f"Order price of '{order}' is of type {type(order.price)}, expected an int")
    #             if not isinstance(order.quantity, int):
    #                 raise ValueError(f"Order quantity of '{order}' is of type {type(order.quantity)}, expected an int")


    def __create_activity_logs(self, state: TradingState, data: BacktestData, result: BacktestResult,) -> None:
        log_creator = ActivityLogCreator(state, data, result.day_num)
        log = log_creator.create_log()
        result.activity_logs.extend(log)


    def __enforce_limits(self, state: TradingState, data: BacktestData, orders: dict[Symbol, list[Order]], sandbox_row: SandboxLogRow) -> None:
        sandbox_log_lines = []
        for product in data.products:
            product_orders = orders.get(product, [])
            product_position = state.position.get(product, 0)

            total_long = sum(order.quantity for order in product_orders if order.quantity > 0)
            total_short = sum(abs(order.quantity) for order in product_orders if order.quantity < 0)

            limit = LIMITS.get(product, 80)
            if product_position + total_long > limit or product_position - total_short < -limit:
                sandbox_log_lines.append(f"Orders for product {product} exceeded limit of {limit} set")
                orders.pop(product)

        if len(sandbox_log_lines) > 0:
            sandbox_row.sandbox_log += "\n" + "\n".join(sandbox_log_lines)


    def __match_orders(self, state: TradingState, data: BacktestData, orders: dict[Symbol, list[Order]], result: BacktestResult) -> None:
        # Trader has finished consuming previous tick's trades; clear before this
        # tick's matching so state reflects only "since last iteration" trades.
        state.own_trades = {}
        state.market_trades = {}
        match_maker = OrderMatchMaker(state, data, orders, self.trade_matching_mode, self.match_mode)
        matched_trades = match_maker.match()
        result.trades.extend(matched_trades)