# Superduperbread's Round 1 submission — website score ~10,400
# Source: teammate shared in Discord 2026-04-17
# Note: scored LESS than our r1_v4 (10,625) — retained for comparison only

from __future__ import annotations

import json
from typing import Any

from datamodel import (
    Listing,
    Observation,
    Order,
    OrderDepth,
    ProsperityEncoder,
    Symbol,
    Trade,
    TradingState,
)


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]],
              conversions: int, trader_data: str) -> None:
        base_length = len(self.to_json([self.compress_state(state, ""),
                                         self.compress_orders(orders),
                                         conversions, "", ""]))
        max_item_length = max(0, (self.max_log_length - base_length) // 3)
        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, max_item_length)),
            self.compress_orders(orders), conversions,
            self.truncate(trader_data, max_item_length),
            self.truncate(self.logs, max_item_length),
        ]))
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [state.timestamp, trader_data,
                self.compress_listings(state.listings),
                self.compress_order_depths(state.order_depths),
                self.compress_trades(state.own_trades),
                self.compress_trades(state.market_trades),
                state.position,
                self.compress_observations(state.observations)]

    def compress_listings(self, listings):
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths):
        return {s: [od.buy_orders, od.sell_orders] for s, od in order_depths.items()}

    def compress_orders(self, orders):
        return [[o.symbol, o.price, o.quantity]
                for arr in orders.values() for o in arr]

    def compress_trades(self, trades):
        return [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
                for arr in trades.values() for t in arr]

    def compress_observations(self, observations):
        co = {}
        for p, o in observations.conversionObservations.items():
            co[p] = [o.bidPrice, o.askPrice, o.transportFees,
                     o.exportTariff, o.importTariff, o.sugarPrice, o.sunlightIndex]
        return [observations.plainValueObservations, co]

    def to_json(self, value):
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value, max_length):
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


class PepperTrader:
    PRODUCT = "INTARIAN_PEPPER_ROOT"
    LIMIT = 80
    MA_WINDOW = 10
    DEV_WINDOW = 80
    BAND_K = 0.2
    PASSIVE_SIZE = 10
    CORE_LOW = 65
    CORE_MID = 70
    CORE_HIGH = 75
    CORE_LOOKBACK = 50
    CORE_UPDATE_FREQ = 50
    SCORE_TO_HIGH = 2.0
    SCORE_TO_MID = 1.0
    SCORE_DOWN_HYST = 0.8
    VANISH_BUY_SIZE = 40
    VANISH_SELL_SIZE = 20

    def trade(self, state: TradingState, td: dict) -> tuple:
        orders: list[Order] = []
        depth = state.order_depths.get(self.PRODUCT)
        if depth is None:
            return orders, td

        bids = [(int(p), abs(int(v))) for p, v in
                sorted(depth.buy_orders.items(), key=lambda x: -x[0])]
        asks = [(int(p), abs(int(v))) for p, v in
                sorted(depth.sell_orders.items(), key=lambda x: x[0])]

        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None

        prev_bid = td.get("p_bid")
        prev_ask = td.get("p_ask")
        ask_vanished = prev_ask is not None and best_ask is None and best_bid is not None
        bid_vanished = prev_bid is not None and best_bid is None and best_ask is not None
        td["p_bid"] = best_bid
        td["p_ask"] = best_ask

        last_price = td.get("last_price")
        if best_bid is not None and best_ask is not None and best_bid <= best_ask:
            ref_price = (best_bid + best_ask) / 2.0
        elif best_bid is not None and best_ask is None:
            ref_price = float(best_bid)
        elif best_ask is not None and best_bid is None:
            ref_price = float(best_ask)
        elif last_price is not None:
            ref_price = float(last_price)
        else:
            return orders, td
        td["last_price"] = ref_price

        hist: list[float] = td.get("hist", [])
        dev_hist: list[float] = td.get("dev_hist", [])
        step_count = int(td.get("step_count", 0)) + 1
        td["step_count"] = step_count
        max_hist_len = self.MA_WINDOW + self.CORE_LOOKBACK + 5
        hist.append(ref_price)
        if len(hist) > max_hist_len:
            hist = hist[-max_hist_len:]
        td["hist"] = hist

        core = int(td.get("core", self.CORE_MID))

        if len(hist) < self.MA_WINDOW:
            td["dev_hist"] = dev_hist
            td["core"] = core
            return self._warmup_orders(state, bids, asks, core), td

        ma = sum(hist[-self.MA_WINDOW:]) / self.MA_WINDOW
        dev = ref_price - ma
        dev_hist.append(abs(dev))
        if len(dev_hist) > self.DEV_WINDOW:
            dev_hist = dev_hist[-self.DEV_WINDOW:]
        td["dev_hist"] = dev_hist

        if len(dev_hist) < max(5, self.MA_WINDOW // 2):
            band = 0.0
            mean_abs_dev = 0.0
        else:
            mean_abs_dev = sum(dev_hist) / len(dev_hist)
            band = self.BAND_K * mean_abs_dev

        score = None
        enough_for_core_update = len(hist) >= self.MA_WINDOW + self.CORE_LOOKBACK
        should_update_core = enough_for_core_update and (step_count % self.CORE_UPDATE_FREQ == 0)

        if should_update_core:
            old_window = hist[-self.MA_WINDOW - self.CORE_LOOKBACK: -self.CORE_LOOKBACK]
            old_ma = sum(old_window) / self.MA_WINDOW
            trend_strength = ma - old_ma
            dip_size = max(1e-6, mean_abs_dev)
            score = trend_strength / dip_size
            if score > self.SCORE_TO_HIGH:
                desired_core = self.CORE_HIGH
            elif score > self.SCORE_TO_MID:
                desired_core = self.CORE_MID
            else:
                desired_core = self.CORE_LOW
            if desired_core > core:
                core = desired_core
            elif desired_core < core and score < self.SCORE_DOWN_HYST:
                core = desired_core
            td["core"] = core

        position = state.position.get(self.PRODUCT, 0)
        in_dip = ref_price <= ma - band if band > 0 else ref_price < ma

        if ask_vanished:
            buy_room = self.LIMIT - position
            if buy_room > 0 and best_bid is not None:
                qty = min(self.VANISH_BUY_SIZE, buy_room)
                if qty > 0:
                    orders.append(Order(self.PRODUCT, best_bid + 1, qty))
            return orders, td

        if bid_vanished:
            if position > core and best_ask is not None:
                trim = min(position - core, self.VANISH_SELL_SIZE)
                if trim > 0:
                    orders.append(Order(self.PRODUCT, best_ask - 1, -trim))
            return orders, td

        if in_dip:
            target = self.LIMIT
        elif ref_price >= ma:
            target = core
        else:
            target = max(core, min(position, self.LIMIT))

        if position < target:
            need = target - position
            for ask_price, ask_vol in asks:
                if need <= 0:
                    break
                should_cross = ask_price <= ma if in_dip else ask_price < ref_price
                if should_cross:
                    qty = min(need, ask_vol)
                    if qty > 0:
                        orders.append(Order(self.PRODUCT, ask_price, qty))
                        need -= qty
            if need > 0:
                passive_bid = self._passive_bid_price(best_bid, best_ask, ref_price)
                qty = min(need, self.PASSIVE_SIZE)
                if qty > 0:
                    orders.append(Order(self.PRODUCT, passive_bid, qty))
        elif position > target:
            excess = position - target
            for bid_price, bid_vol in bids:
                if excess <= 0:
                    break
                should_cross = bid_price >= ma if ref_price >= ma else bid_price > ref_price
                if should_cross:
                    qty = min(excess, bid_vol)
                    if qty > 0:
                        orders.append(Order(self.PRODUCT, bid_price, -qty))
                        excess -= qty
            if excess > 0:
                passive_ask = self._passive_ask_price(best_bid, best_ask, ref_price)
                qty = min(excess, self.PASSIVE_SIZE)
                if qty > 0:
                    orders.append(Order(self.PRODUCT, passive_ask, -qty))

        return orders, td

    def _warmup_orders(self, state, bids, asks, warmup_core):
        orders: list[Order] = []
        position = state.position.get(self.PRODUCT, 0)
        if position >= warmup_core:
            return orders
        need = warmup_core - position
        for ask_price, ask_vol in asks:
            if need <= 0:
                break
            qty = min(need, ask_vol)
            if qty > 0:
                orders.append(Order(self.PRODUCT, ask_price, qty))
                need -= qty
        if need > 0:
            best_bid = bids[0][0] if bids else None
            best_ask = asks[0][0] if asks else None
            ref_price = ((best_bid + best_ask) / 2.0
                         if best_bid is not None and best_ask is not None and best_bid <= best_ask
                         else (best_bid if best_bid is not None else best_ask))
            if ref_price is not None:
                passive_bid = self._passive_bid_price(best_bid, best_ask, ref_price)
                qty = min(need, self.PASSIVE_SIZE)
                if qty > 0:
                    orders.append(Order(self.PRODUCT, passive_bid, qty))
        return orders

    def _passive_bid_price(self, best_bid, best_ask, ref_price):
        if best_bid is not None and best_ask is not None and best_bid < best_ask:
            return best_bid + 1
        if best_bid is not None:
            return best_bid
        return int(ref_price)

    def _passive_ask_price(self, best_bid, best_ask, ref_price):
        if best_bid is not None and best_ask is not None and best_bid < best_ask:
            return best_ask - 1
        if best_ask is not None:
            return best_ask
        return int(ref_price)


class OsmiumTrader:
    PRODUCT = "ASH_COATED_OSMIUM"
    LIMIT = 80
    FAIR_WINDOW = 16
    BAND_WINDOW = 54
    MIN_BAND = 2.0
    CORE_MAX_POS = 50
    MM_SIZE = 15
    RESERVE_CONFIRM_POS = 30
    RESERVE_EXTREME_POS = 50
    EXTREME_Z = 0.3
    CONFIRM_Z = 0.1
    IMB_CONFIRM = 0.25
    VANISH_SIZE = 60
    VANISH_POS_CAP = 75
    CROSS_EDGE_CORE = 0.0
    CROSS_EDGE_RESERVE = 0.5
    UNWIND_BUFFER = 0.5

    def trade(self, state: TradingState, td: dict) -> tuple:
        orders: list[Order] = []
        depth = state.order_depths.get(self.PRODUCT)
        if depth is None:
            return orders, td

        bids = [(int(p), abs(int(v))) for p, v in
                sorted(depth.buy_orders.items(), key=lambda x: -x[0])]
        asks = [(int(p), abs(int(v))) for p, v in
                sorted(depth.sell_orders.items(), key=lambda x: x[0])]
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        bb_vol = bids[0][1] if bids else 0
        ba_vol = asks[0][1] if asks else 0

        ref = self._ref(best_bid, best_ask, td.get("last"))
        if ref is None:
            return orders, td
        td["last"] = ref

        hist: list[float] = td.get("h", [])
        hist.append(ref)
        keep = max(self.FAIR_WINDOW, self.BAND_WINDOW) + 5
        if len(hist) > keep:
            hist = hist[-keep:]
        td["h"] = hist

        prev_bid = td.get("pb")
        prev_ask = td.get("pa")
        ask_vanished = prev_ask is not None and best_ask is None and best_bid is not None
        bid_vanished = prev_bid is not None and best_bid is None and best_ask is not None
        td["pb"] = best_bid
        td["pa"] = best_ask

        imb = 0.0
        if bb_vol + ba_vol > 0:
            imb = (bb_vol - ba_vol) / (bb_vol + ba_vol)

        position = state.position.get(self.PRODUCT, 0)
        buy_room = self.LIMIT - position
        sell_room = self.LIMIT + position
        ordered_buy = 0
        ordered_sell = 0

        if len(hist) < self.FAIR_WINDOW:
            if ask_vanished and buy_room > 0 and best_bid is not None:
                qty = min(self.VANISH_SIZE, buy_room, self.VANISH_POS_CAP - position)
                if qty > 0:
                    orders.append(Order(self.PRODUCT, best_bid + 1, qty))
            if bid_vanished and sell_room > 0 and best_ask is not None:
                qty = min(self.VANISH_SIZE, sell_room, position + self.VANISH_POS_CAP)
                if qty > 0:
                    orders.append(Order(self.PRODUCT, best_ask - 1, -qty))
            return orders, td

        fair = sum(hist[-self.FAIR_WINDOW:]) / self.FAIR_WINDOW
        dev = ref - fair
        dev_hist: list[float] = td.get("d", [])
        dev_hist.append(abs(dev))
        if len(dev_hist) > self.BAND_WINDOW:
            dev_hist = dev_hist[-self.BAND_WINDOW:]
        td["d"] = dev_hist

        band = self.MIN_BAND
        if len(dev_hist) >= 20:
            band = max(self.MIN_BAND, 2.0 * sum(dev_hist) / len(dev_hist))

        z = max(-1.0, min(1.0, dev / band))
        target_core = int(round(-z * self.CORE_MAX_POS))
        target_core = max(-self.CORE_MAX_POS, min(self.CORE_MAX_POS, target_core))
        target_total = target_core

        if ask_vanished:
            target_total = max(target_total, self.VANISH_POS_CAP)
        elif bid_vanished:
            target_total = min(target_total, -self.VANISH_POS_CAP)
        else:
            if z <= -self.EXTREME_Z:
                target_total = max(target_total, self.RESERVE_EXTREME_POS)
            elif z <= -self.CONFIRM_Z and imb > self.IMB_CONFIRM:
                target_total = max(target_total, self.RESERVE_CONFIRM_POS)
            if z >= self.EXTREME_Z:
                target_total = min(target_total, -self.RESERVE_EXTREME_POS)
            elif z >= self.CONFIRM_Z and imb < -self.IMB_CONFIRM:
                target_total = min(target_total, -self.RESERVE_CONFIRM_POS)

        if position > target_core and ref >= fair - self.UNWIND_BUFFER:
            target_total = min(target_total, target_core)
        if position < target_core and ref <= fair + self.UNWIND_BUFFER:
            target_total = max(target_total, target_core)

        target_total = max(-self.LIMIT, min(self.LIMIT, target_total))
        reserve_long_active = target_total > target_core
        reserve_short_active = target_total < target_core

        if position < target_total:
            need = min(target_total - position, buy_room)
            for ask_p, ask_v in asks:
                if need <= 0:
                    break
                edge_req = self.CROSS_EDGE_RESERVE if reserve_long_active else self.CROSS_EDGE_CORE
                if ask_p <= fair + edge_req:
                    qty = min(need, ask_v, buy_room - ordered_buy)
                    if qty > 0:
                        orders.append(Order(self.PRODUCT, ask_p, qty))
                        need -= qty
                        ordered_buy += qty

        if position > target_total:
            excess = min(position - target_total, sell_room)
            for bid_p, bid_v in bids:
                if excess <= 0:
                    break
                edge_req = self.CROSS_EDGE_RESERVE if reserve_short_active else self.CROSS_EDGE_CORE
                if bid_p >= fair - edge_req:
                    qty = min(excess, bid_v, sell_room - ordered_sell)
                    if qty > 0:
                        orders.append(Order(self.PRODUCT, bid_p, -qty))
                        excess -= qty
                        ordered_sell += qty

        if ask_vanished and position < self.VANISH_POS_CAP:
            qty = min(self.VANISH_SIZE, self.VANISH_POS_CAP - position, buy_room - ordered_buy)
            if qty > 0 and best_bid is not None:
                orders.append(Order(self.PRODUCT, best_bid + 1, qty))
                ordered_buy += qty

        if bid_vanished and position > -self.VANISH_POS_CAP:
            qty = min(self.VANISH_SIZE, position + self.VANISH_POS_CAP, sell_room - ordered_sell)
            if qty > 0 and best_ask is not None:
                orders.append(Order(self.PRODUCT, best_ask - 1, -qty))
                ordered_sell += qty

        want_buy = max(0, target_total - position)
        want_sell = max(0, position - target_total)
        bid_size = min(self.MM_SIZE + want_buy, buy_room - ordered_buy)
        ask_size = min(self.MM_SIZE + want_sell, sell_room - ordered_sell)

        if bid_size > 0 and best_bid is not None:
            orders.append(Order(self.PRODUCT, best_bid + 1, bid_size))
        if ask_size > 0 and best_ask is not None:
            orders.append(Order(self.PRODUCT, best_ask - 1, -ask_size))

        return orders, td

    def _ref(self, bb, ba, last):
        if bb is not None and ba is not None and bb <= ba:
            return (bb + ba) / 2.0
        if bb is not None:
            return float(bb)
        if ba is not None:
            return float(ba)
        if last is not None:
            return float(last)
        return None


class Trader:
    def __init__(self) -> None:
        self.pepper = PepperTrader()
        self.osmium = OsmiumTrader()

    def run(self, state: TradingState):
        result: dict[Symbol, list[Order]] = {sym: [] for sym in state.order_depths}
        conversions = 0
        td = self._load(state.traderData)

        if self.pepper.PRODUCT in state.order_depths:
            result[self.pepper.PRODUCT], td = self.pepper.trade(state, td)

        if self.osmium.PRODUCT in state.order_depths:
            result[self.osmium.PRODUCT], td = self.osmium.trade(state, td)

        td_str = json.dumps(td, separators=(",", ":"))
        logger.flush(state, result, conversions, td_str)
        return result, conversions, td_str

    def _load(self, raw: str) -> dict:
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
