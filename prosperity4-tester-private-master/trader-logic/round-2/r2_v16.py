import json
import jsonpickle
import numpy as np
import math
from typing import Any, List, Tuple, Dict

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
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

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
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

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])
        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        if observations:
            for product, observation in observations.conversionObservations.items():
                conversion_observations[product] = [
                    observation.bidPrice,
                    observation.askPrice,
                    observation.transportFees,
                    observation.exportTariff,
                    observation.importTariff,
                    observation.sugarPrice,
                    observation.sunlightIndex,
                ]
        return [observations.plainValueObservations if observations else {}, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if value is None:
            return ""
        lo, hi = 0, min(len(value), max_length)
        out = ""

        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            encoded_candidate = json.dumps(candidate)
            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


class Product:
    ASH = "ASH_COATED_OSMIUM"
    PEPPER = "INTARIAN_PEPPER_ROOT"


PARAMS = {
    Product.ASH: {
        "take_width": 2,
        "clear_width": 1,
        "disregard_edge": 1,
        "join_edge": 2,
        "default_edge": 4,
        "risk_aversion": 0.025,
        "target_position": 0,
    },
    Product.PEPPER: {
        "take_width": 1.5,
        "prevent_adverse": True,
        "adverse_volume": 15,
        "disregard_edge": 1,
        "join_edge": 0,
        "default_edge": 2,
        "risk_aversion": 0.025,
        "target_position": 40,
    },
}

# t=0 guardrails for ASH
ASH_T0_SMALL_QUOTE = 6
ASH_EARLY_QUOTE = 14
ASH_ONE_SIDED_DELAY_TICKS = 1
ASH_SMALL_QUOTE_TICKS_TWO_SIDED = 10


def _safe_orders(orders_dict, positions, limits):
    safe_dict = {}
    for product, orders in orders_dict.items():
        if not orders:
            safe_dict[product] = []
            continue

        pos = positions.get(product, 0)
        limit = limits[product]

        valid_orders = []
        for order in orders:
            if order is None:
                continue
            if order.symbol is None or order.price is None or order.quantity is None:
                continue
            if order.quantity == 0 or order.price <= 0:
                continue
            valid_orders.append(order)

        total_buy = sum(o.quantity for o in valid_orders if o.quantity > 0)
        total_sell = sum(o.quantity for o in valid_orders if o.quantity < 0)
        if pos + total_buy <= limit and pos + total_sell >= -limit:
            safe_dict[product] = valid_orders
            continue

        out = []
        cum_buy = 0
        cum_sell_abs = 0
        for order in valid_orders:
            qty = order.quantity
            if qty > 0:
                rem = limit - (pos + cum_buy)
                if rem <= 0:
                    continue
                use_qty = min(qty, rem)
                if use_qty > 0:
                    out.append(Order(order.symbol, order.price, use_qty))
                    cum_buy += use_qty
            else:
                rem = limit + pos - cum_sell_abs
                if rem <= 0:
                    continue
                use_qty = min(-qty, rem)
                if use_qty > 0:
                    out.append(Order(order.symbol, order.price, -use_qty))
                    cum_sell_abs += use_qty
        safe_dict[product] = out
    return safe_dict


class Trader:
    def __init__(self, params=None):
        if params is None:
            params = PARAMS
        self.params = params
        self.LIMIT = {Product.ASH: 80, Product.PEPPER: 80}

    def _observe_ash_t0(self, state: TradingState, traderObject: Dict):
        if "ash_t0_mode" in traderObject:
            return
        order_depth = state.order_depths[Product.ASH]
        has_asks = len(order_depth.sell_orders) > 0
        has_bids = len(order_depth.buy_orders) > 0
        if has_asks and has_bids:
            traderObject["ash_t0_mode"] = "two_sided"
        elif has_asks or has_bids:
            traderObject["ash_t0_mode"] = "one_sided"
        else:
            traderObject["ash_t0_mode"] = "empty"
        traderObject["ash_tick_count"] = traderObject.get("ash_tick_count", 0)
        traderObject["ash_two_sided_count"] = traderObject.get("ash_two_sided_count", 0)

    def _ash_quote_cap(self, traderObject: Dict):
        t0_mode = traderObject.get("ash_t0_mode")
        tick_count = traderObject.get("ash_tick_count", 0)
        two_sided_count = traderObject.get("ash_two_sided_count", 0)

        if t0_mode == "one_sided" and two_sided_count == 0:
            return 0
        if t0_mode == "one_sided":
            return ASH_T0_SMALL_QUOTE
        if t0_mode == "two_sided" and tick_count <= ASH_SMALL_QUOTE_TICKS_TWO_SIDED:
            return ASH_EARLY_QUOTE
        return self.LIMIT[Product.ASH]

    def _ash_take_allowed(self, traderObject: Dict) -> bool:
        t0_mode = traderObject.get("ash_t0_mode")
        two_sided_count = traderObject.get("ash_two_sided_count", 0)
        if t0_mode == "one_sided" and two_sided_count < 1:
            return False
        return traderObject.get("ash_prev_mid") is not None or traderObject.get("ash_ema") is not None

    def take_best_orders(
        self,
        product: str,
        fair_value: float,
        take_width: float,
        orders: List[Order],
        order_depth: OrderDepth,
        position: int,
        buy_order_volume: int,
        sell_order_volume: int,
        prevent_adverse: bool = False,
        adverse_volume: int = 0,
    ) -> Tuple[int, int]:
        position_limit = self.LIMIT[product]

        if len(order_depth.sell_orders) != 0:
            best_ask = min(order_depth.sell_orders.keys())
            best_ask_amount = -1 * order_depth.sell_orders[best_ask]

            if not prevent_adverse or abs(best_ask_amount) <= adverse_volume:
                if best_ask <= fair_value - take_width:
                    quantity = min(best_ask_amount, position_limit - position)
                    if quantity > 0:
                        orders.append(Order(product, best_ask, quantity))
                        buy_order_volume += quantity
                        order_depth.sell_orders[best_ask] += quantity
                        if order_depth.sell_orders[best_ask] == 0:
                            del order_depth.sell_orders[best_ask]

        if len(order_depth.buy_orders) != 0:
            best_bid = max(order_depth.buy_orders.keys())
            best_bid_amount = order_depth.buy_orders[best_bid]

            if not prevent_adverse or abs(best_bid_amount) <= adverse_volume:
                if best_bid >= fair_value + take_width:
                    quantity = min(best_bid_amount, position_limit + position)
                    if quantity > 0:
                        orders.append(Order(product, best_bid, -1 * quantity))
                        sell_order_volume += quantity
                        order_depth.buy_orders[best_bid] -= quantity
                        if order_depth.buy_orders[best_bid] == 0:
                            del order_depth.buy_orders[best_bid]

        return buy_order_volume, sell_order_volume

    def market_make(
        self,
        product: str,
        orders: List[Order],
        bid: int,
        ask: int,
        position: int,
        buy_order_volume: int,
        sell_order_volume: int,
        quote_cap: int | None = None,
    ) -> Tuple[int, int]:
        buy_quantity = self.LIMIT[product] - (position + buy_order_volume)
        if quote_cap is not None:
            buy_quantity = min(buy_quantity, quote_cap)
        if buy_quantity > 0:
            orders.append(Order(product, round(bid), buy_quantity))

        sell_quantity = self.LIMIT[product] + (position - sell_order_volume)
        if quote_cap is not None:
            sell_quantity = min(sell_quantity, quote_cap)
        if sell_quantity > 0:
            orders.append(Order(product, round(ask), -sell_quantity))

        return buy_order_volume, sell_order_volume

    def clear_position_order(
        self,
        product: str,
        fair_value: float,
        width: float,
        orders: List[Order],
        order_depth: OrderDepth,
        position: int,
        buy_order_volume: int,
        sell_order_volume: int,
    ) -> Tuple[int, int]:
        position_after_take = position + buy_order_volume - sell_order_volume
        fair_for_bid = round(fair_value - width)
        fair_for_ask = round(fair_value + width)

        buy_quantity = self.LIMIT[product] - (position + buy_order_volume)
        sell_quantity = self.LIMIT[product] + (position - sell_order_volume)

        if position_after_take > 0:
            clear_quantity = min(sell_quantity, position_after_take)
            sent_quantity = 0

            bids_sorted = sorted(list(order_depth.buy_orders.keys()), reverse=True)
            for bid_price in bids_sorted:
                if bid_price >= fair_for_ask:
                    vol = order_depth.buy_orders[bid_price]
                    taken = min(vol, clear_quantity - sent_quantity)
                    if taken > 0:
                        sent_quantity += taken
                        order_depth.buy_orders[bid_price] -= taken
                        if order_depth.buy_orders[bid_price] == 0:
                            del order_depth.buy_orders[bid_price]
                if sent_quantity >= clear_quantity:
                    break

            if sent_quantity > 0:
                orders.append(Order(product, fair_for_ask, -abs(sent_quantity)))
                sell_order_volume += abs(sent_quantity)

        if position_after_take < 0:
            clear_quantity = min(buy_quantity, abs(position_after_take))
            sent_quantity = 0

            asks_sorted = sorted(list(order_depth.sell_orders.keys()))
            for ask_price in asks_sorted:
                if ask_price <= fair_for_bid:
                    vol = abs(order_depth.sell_orders[ask_price])
                    taken = min(vol, clear_quantity - sent_quantity)
                    if taken > 0:
                        sent_quantity += taken
                        order_depth.sell_orders[ask_price] += taken
                        if order_depth.sell_orders[ask_price] == 0:
                            del order_depth.sell_orders[ask_price]
                if sent_quantity >= clear_quantity:
                    break

            if sent_quantity > 0:
                orders.append(Order(product, fair_for_bid, abs(sent_quantity)))
                buy_order_volume += abs(sent_quantity)

        return buy_order_volume, sell_order_volume

    def pepper_fair_value_long_biased(
        self,
        state: TradingState,
        traderObject: Dict,
        position: int
    ) -> float:
        order_depth = state.order_depths[Product.PEPPER]

        if len(order_depth.sell_orders) != 0 and len(order_depth.buy_orders) != 0:
            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())

            filtered_ask = [
                price for price in order_depth.sell_orders.keys()
                if abs(order_depth.sell_orders[price]) >= self.params[Product.PEPPER]["adverse_volume"]
            ]
            filtered_bid = [
                price for price in order_depth.buy_orders.keys()
                if abs(order_depth.buy_orders[price]) >= self.params[Product.PEPPER]["adverse_volume"]
            ]

            mm_ask = min(filtered_ask) if len(filtered_ask) > 0 else None
            mm_bid = max(filtered_bid) if len(filtered_bid) > 0 else None

            eff_ask = mm_ask if mm_ask is not None else best_ask
            eff_bid = mm_bid if mm_bid is not None else best_bid

            mid_price = (eff_ask + eff_bid) / 2

            drift_per_tick = 0.1
            total_ticks = 100000
            ticks_remaining = max(0, total_ticks - state.timestamp)

            position_limit = self.LIMIT[Product.PEPPER]
            inventory_ratio = (position_limit - position) / position_limit
            time_ratio = ticks_remaining / total_ticks

            drift_boost = drift_per_tick * ticks_remaining * inventory_ratio * time_ratio
            skewed_fair = mid_price + drift_boost
            return skewed_fair

        return None

    def ash_fair_value_and_width(
        self,
        state: TradingState,
        traderObject: Dict,
        position: int,
    ) -> Tuple[float, float]:
        order_depth = state.order_depths[Product.ASH]
        base_width = self.params[Product.ASH]["take_width"]

        has_asks = len(order_depth.sell_orders) > 0
        has_bids = len(order_depth.buy_orders) > 0

        best_ask = min(order_depth.sell_orders.keys()) if has_asks else None
        best_bid = max(order_depth.buy_orders.keys()) if has_bids else None

        if best_ask is not None and best_bid is not None:
            traderObject["ash_two_sided_count"] = traderObject.get("ash_two_sided_count", 0) + 1
            mid = (best_ask + best_bid) / 2
        elif best_ask is not None:
            mid = best_ask - base_width
        elif best_bid is not None:
            mid = best_bid + base_width
        else:
            mid = traderObject.get("ash_prev_mid", traderObject.get("ash_ema", 10000))

        ema = traderObject.get("ash_ema", mid)
        last_ret = mid - traderObject.get('ash_prev_mid', mid)

        returns_history = traderObject.get("ash_returns", [])
        returns_history.append(last_ret)
        if len(returns_history) > 40:
            returns_history.pop(0)
        traderObject['ash_returns'] = returns_history

        if len(returns_history) >= 12:
            ret_std = float(np.std(returns_history))
        else:
            ret_std = 2.0

        window = traderObject.get('ash_mid_history', list())
        window.append(mid)
        if len(window) > 40:
            window.pop(0)
        traderObject['ash_mid_history'] = window

        if len(window) >= 20:
            mean_mid = float(np.mean(window))
            std_mid = float(np.std(window))
            zscore = (mid - mean_mid) / max(std_mid, 1e-6)
        else:
            zscore = 0.0

        if has_bids and has_asks:
            bid_vol = sum(order_depth.buy_orders.values())
            ask_vol = sum(abs(v) for v in order_depth.sell_orders.values())
            imbalance = (bid_vol - ask_vol) / max(bid_vol + ask_vol, 1e-6)
        else:
            imbalance = 0.0

        strong_signal = abs(zscore) > 1.5
        medium_signal = abs(zscore) > 1.0

        if strong_signal:
            raw_mr_adjustment = -zscore * ret_std * 1.0
        elif medium_signal:
            raw_mr_adjustment = -zscore * ret_std * 0.6
        else:
            raw_mr_adjustment = 0.0

        if last_ret > 0:
            direction_bias = -1
        elif last_ret < 0:
            direction_bias = 1
        else:
            direction_bias = 0

        raw_mr_adjustment *= (1 + 0.3 * direction_bias * np.sign(zscore))

        if zscore > 1.0 and imbalance < 0:
            raw_mr_adjustment *= 1.2
        elif zscore < -1.0 and imbalance > 0:
            raw_mr_adjustment *= 1.2
        else:
            raw_mr_adjustment *= 0.7

        max_adjustment = 2.5 * ret_std
        mr_adjustment = float(np.clip(raw_mr_adjustment, -max_adjustment, max_adjustment))

        risk_aversion = self.params[Product.ASH]["risk_aversion"]
        target_position = self.params[Product.ASH]["target_position"]
        inventory_adjustment = -(position - target_position) * risk_aversion

        fair_value = ema + mr_adjustment + inventory_adjustment
        dynamic_width = max(base_width, 0.5 * ret_std * (1 + 0.5 * abs(zscore)))

        ema_alpha = 2 / (50 + 1)
        if abs(zscore) < 1.0:
            ema = mid * ema_alpha + ema * (1 - ema_alpha)
        else:
            ema = mid * (ema_alpha * 0.2) + ema * (1 - ema_alpha * 0.2)

        traderObject["ash_ema"] = ema
        traderObject['ash_prev_mid'] = mid

        return fair_value, dynamic_width

    def take_orders(
        self,
        product: str,
        order_depth: OrderDepth,
        fair_value: float,
        take_width: float,
        position: int,
        prevent_adverse: bool = False,
        adverse_volume: int = 0,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        buy_order_volume = 0
        sell_order_volume = 0

        buy_order_volume, sell_order_volume = self.take_best_orders(
            product, fair_value, take_width, orders, order_depth, position, buy_order_volume, sell_order_volume, prevent_adverse, adverse_volume,
        )
        return orders, buy_order_volume, sell_order_volume

    def clear_orders(
        self,
        product: str,
        order_depth: OrderDepth,
        fair_value: float,
        clear_width: float,
        position: int,
        buy_order_volume: int,
        sell_order_volume: int,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        buy_order_volume, sell_order_volume = self.clear_position_order(
            product, fair_value, clear_width, orders, order_depth, position, buy_order_volume, sell_order_volume,
        )
        return orders, buy_order_volume, sell_order_volume

    def make_orders(
        self,
        product: str,
        order_depth: OrderDepth,
        fair_value: float,
        position: int,
        buy_order_volume: int,
        sell_order_volume: int,
        disregard_edge: float,
        join_edge: float,
        default_edge: float,
        quote_cap: int | None = None,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        asks_above_fair = [price for price in order_depth.sell_orders.keys() if price > fair_value + disregard_edge]
        bids_below_fair = [price for price in order_depth.buy_orders.keys() if price < fair_value - disregard_edge]

        best_ask_above_fair = min(asks_above_fair) if len(asks_above_fair) > 0 else None
        best_bid_below_fair = max(bids_below_fair) if len(bids_below_fair) > 0 else None

        ask = round(fair_value + default_edge)
        if best_ask_above_fair is not None:
            if abs(best_ask_above_fair - fair_value) <= join_edge:
                ask = best_ask_above_fair
            else:
                ask = best_ask_above_fair - 1

        bid = round(fair_value - default_edge)
        if best_bid_below_fair is not None:
            if abs(fair_value - best_bid_below_fair) <= join_edge:
                bid = best_bid_below_fair
            else:
                bid = best_bid_below_fair + 1

        buy_order_volume, sell_order_volume = self.market_make(
            product, orders, bid, ask, position, buy_order_volume, sell_order_volume, quote_cap=quote_cap,
        )

        return orders, buy_order_volume, sell_order_volume

    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        traderObject = {}
        if state.traderData is not None and state.traderData != "":
            traderObject = jsonpickle.decode(state.traderData)

        traderObject["ash_tick_count"] = traderObject.get("ash_tick_count", 0) + 1
        traderObject["ash_two_sided_count"] = traderObject.get("ash_two_sided_count", 0)
        self._observe_ash_t0(state, traderObject)

        result = {}

        if Product.ASH in self.params and Product.ASH in state.order_depths:
            ash_position = state.position.get(Product.ASH, 0)

            fair_value, dynamic_width = self.ash_fair_value_and_width(state, traderObject, ash_position)

            ash_take_orders = []
            buy_order_volume = 0
            sell_order_volume = 0

            if self._ash_take_allowed(traderObject):
                ash_take_orders, buy_order_volume, sell_order_volume = self.take_orders(
                    Product.ASH, state.order_depths[Product.ASH], fair_value, dynamic_width, ash_position,
                )

            ash_clear_orders = []
            if self._ash_take_allowed(traderObject):
                ash_clear_orders, buy_order_volume, sell_order_volume = self.clear_orders(
                    Product.ASH, state.order_depths[Product.ASH], fair_value, self.params[Product.ASH]["clear_width"], ash_position, buy_order_volume, sell_order_volume,
                )

            quote_cap = self._ash_quote_cap(traderObject)
            ash_make_orders = []
            if quote_cap > 0:
                ash_make_orders, _, _ = self.make_orders(
                    Product.ASH,
                    state.order_depths[Product.ASH],
                    fair_value,
                    ash_position,
                    buy_order_volume,
                    sell_order_volume,
                    self.params[Product.ASH]["disregard_edge"],
                    self.params[Product.ASH]["join_edge"],
                    self.params[Product.ASH]["default_edge"],
                    quote_cap=quote_cap,
                )

            result[Product.ASH] = ash_take_orders + ash_clear_orders + ash_make_orders

        if Product.PEPPER in self.params and Product.PEPPER in state.order_depths:
            pepper_position = state.position.get(Product.PEPPER, 0)
            order_depth = state.order_depths[Product.PEPPER]
            pepper_orders = []

            pepper_fair_value = self.pepper_fair_value_long_biased(state, traderObject, pepper_position)

            if pepper_fair_value is not None:
                buy_order_volume = 0
                sell_order_volume = 0
                position_limit = self.LIMIT[Product.PEPPER]

                prevent_adverse = self.params[Product.PEPPER]["prevent_adverse"]
                adverse_volume = self.params[Product.PEPPER]["adverse_volume"]
                take_width = self.params[Product.PEPPER]["take_width"]

                if len(order_depth.sell_orders) != 0:
                    best_ask = min(order_depth.sell_orders.keys())
                    best_ask_amount = -1 * order_depth.sell_orders[best_ask]

                    if not prevent_adverse or abs(best_ask_amount) <= adverse_volume:
                        if best_ask <= pepper_fair_value - take_width:
                            quantity = min(best_ask_amount, position_limit - pepper_position)
                            if quantity > 0:
                                pepper_orders.append(Order(Product.PEPPER, best_ask, quantity))
                                buy_order_volume += quantity
                                order_depth.sell_orders[best_ask] += quantity
                                if order_depth.sell_orders[best_ask] == 0:
                                    del order_depth.sell_orders[best_ask]

                sell_take_width = take_width * 2.5

                if len(order_depth.buy_orders) != 0:
                    best_bid = max(order_depth.buy_orders.keys())
                    best_bid_amount = order_depth.buy_orders[best_bid]

                    if not prevent_adverse or abs(best_bid_amount) <= adverse_volume:
                        if best_bid >= pepper_fair_value + sell_take_width:
                            quantity = min(best_bid_amount, position_limit + pepper_position)
                            if quantity > 0:
                                pepper_orders.append(Order(Product.PEPPER, best_bid, -quantity))
                                sell_order_volume += quantity
                                order_depth.buy_orders[best_bid] -= quantity
                                if order_depth.buy_orders[best_bid] == 0:
                                    del order_depth.buy_orders[best_bid]

                buy_quantity = position_limit - (pepper_position + buy_order_volume)

                disregard_edge = self.params[Product.PEPPER]["disregard_edge"]
                join_edge = self.params[Product.PEPPER]["join_edge"]
                default_edge = self.params[Product.PEPPER]["default_edge"]

                if buy_quantity > 0:
                    bids_below_fair = [
                        price for price in order_depth.buy_orders.keys()
                        if price < pepper_fair_value - disregard_edge
                    ]
                    best_bid_below_fair = max(bids_below_fair) if len(bids_below_fair) > 0 else None

                    bid_price = round(pepper_fair_value - default_edge)
                    if best_bid_below_fair is not None:
                        if abs(pepper_fair_value - best_bid_below_fair) <= join_edge:
                            bid_price = best_bid_below_fair
                        else:
                            bid_price = best_bid_below_fair + 1

                    pepper_orders.append(Order(Product.PEPPER, bid_price, buy_quantity))

            result[Product.PEPPER] = pepper_orders

        result = _safe_orders(result, state.position, self.LIMIT)

        conversions = 1
        trader_data = jsonpickle.encode(traderObject)

        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data