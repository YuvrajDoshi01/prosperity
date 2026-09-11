"""
HYDROGEL_PACK Trading Strategy — v4
=====================================
Source: shared by Superduperbread + thedarkmarc on Discord (CULT)
Submission ID: 392245

Combines:
- Hydrogel regime-detection MM (Superduperbread)
- Velvet options BS + delta hedge (thedarkmarc, vibecoded from ericcccsliu/imc-prosperity-2)
"""

import json
import math
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Tuple

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
                compressed.append([trade.symbol, trade.price, trade.quantity, trade.buyer, trade.seller, trade.timestamp])
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        if observations:
            for product, observation in observations.conversionObservations.items():
                conversion_observations[product] = [
                    observation.bidPrice, observation.askPrice, observation.transportFees,
                    observation.exportTariff, observation.importTariff,
                    observation.sugarPrice, observation.sunlightIndex,
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
    HYDROGEL_PACK       = "HYDROGEL_PACK"
    VELVETFRUIT_EXTRACT = "VELVETFRUIT_EXTRACT"
    VEV_4000  = "VEV_4000";  VEV_4500  = "VEV_4500"
    VEV_5000  = "VEV_5000";  VEV_5100  = "VEV_5100"
    VEV_5200  = "VEV_5200";  VEV_5300  = "VEV_5300"
    VEV_5400  = "VEV_5400";  VEV_5500  = "VEV_5500"
    VEV_6000  = "VEV_6000";  VEV_6500  = "VEV_6500"


POSITION_LIMITS: Dict[str, int] = {
    Product.HYDROGEL_PACK: 200,
    Product.VELVETFRUIT_EXTRACT: 200,
    **{getattr(Product, f"VEV_{v}"): 300
       for v in ["4000","4500","5000","5100","5200","5300","5400","5500","6000","6500"]},
}


class HydrogelParams:
    REGIME1_SPREAD_THRESHOLD = 10
    REGIME1_IMB_THRESHOLD = 999.0
    REGIME1_EXIT_ROWS = 10
    REGIME1_ENTRY_SIZE = 1
    REGIME2_SPREAD = 17
    REGIME2_FLATTEN_AGGRESSIVE = True
    REGIME3_Z_ENTER = 2.0
    REGIME3_Z_EXIT = 0.5
    REGIME3_STOP_TICKS = 20
    LAYER_B_SCALE = 0.0
    MEAN_ANCHOR_WINDOW = 100
    MEAN_ANCHOR_STD_MULTIPLIER = 1.0
    LAYER_A_SCALE = 3.0
    LAYER_A_CLIP = 1.0
    INV_ADJ_CLIP = 3.0
    INV_ADJ_COEFF = 0.1
    QUOTE_SIZE = 50
    HP_VOL_WINDOW = 20
    HP_SLACK_MIN  = 1
    HP_SLACK_MAX  = 3
    HP_SLACK_COEF = 0.5
    POS_AGGRESSION_FRAC = 0.5
    Z500_WINDOW = 500
    STD100_WINDOW = 100


def _mean(buf: List[float]) -> Optional[float]:
    return sum(buf) / len(buf) if buf else None

def _std(buf: List[float]) -> Optional[float]:
    n = len(buf)
    if n < 2:
        return None
    mu = sum(buf) / n
    return (sum((x - mu) ** 2 for x in buf) / (n - 1)) ** 0.5

def _zscore(buf: List[float], value: float) -> Optional[float]:
    mu = _mean(buf)
    sd = _std(buf)
    if mu is None or sd is None or sd == 0:
        return None
    return (value - mu) / sd

def _push(buf: List[float], value: float, maxlen: int) -> List[float]:
    buf = buf + [value]
    return buf[-maxlen:] if len(buf) > maxlen else buf

def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def compute_book_features(order_depth) -> Dict[str, Optional[float]]:
    buys  = order_depth.buy_orders
    sells = order_depth.sell_orders

    if not buys or not sells:
        return {}

    best_bid = max(buys.keys())
    best_ask = min(sells.keys())
    spread   = best_ask - best_bid

    if spread <= 0:
        return {}

    mid = (best_bid + best_ask) / 2.0
    sorted_bids = sorted(buys.keys(),  reverse=True)
    sorted_asks = sorted(sells.keys(), reverse=False)

    def px(lst, i): return lst[i] if i < len(lst) else None
    def sz(book, p): return abs(book[p]) if p is not None else 0.0

    bid_px = [px(sorted_bids, i) for i in range(3)]
    ask_px = [px(sorted_asks, i) for i in range(3)]
    bid_sz = [sz(buys,  p) for p in bid_px]
    ask_sz = [sz(sells, p) for p in ask_px]

    denom_L1     = bid_sz[0] + ask_sz[0]
    imbalance_L1 = (bid_sz[0] - ask_sz[0]) / denom_L1 if denom_L1 > 0 else 0.0

    bid_num = sum((bid_px[i] or 0) * bid_sz[i] for i in range(3) if bid_px[i])
    ask_num = sum((ask_px[i] or 0) * ask_sz[i] for i in range(3) if ask_px[i])
    bid_den = sum(bid_sz[i] for i in range(3) if bid_px[i])
    ask_den = sum(ask_sz[i] for i in range(3) if ask_px[i])
    bid_wap = bid_num / bid_den if bid_den > 0 else best_bid
    ask_wap = ask_num / ask_den if ask_den > 0 else best_ask
    book_wap_edge_L3 = ((bid_wap + ask_wap) / 2.0) - mid

    return {
        "best_bid":          best_bid,
        "best_ask":          best_ask,
        "spread":            spread,
        "mid":               mid,
        "imbalance_L1":      imbalance_L1,
        "book_wap_edge_L3":  book_wap_edge_L3,
    }


class HydrogelState:
    def __init__(self) -> None:
        self.mid_buf_500: List[float] = []
        self.mid_buf_100: List[float] = []
        self.row: int = 0
        self.regime1_entry_row: Optional[int] = None
        self.regime1_qty:       int = 0
        self.lean_target:      float = 0.0
        self.lean_entry_mid:   Optional[float] = None
        self.lean_entry_side:  int = 0

    def to_dict(self) -> dict:
        return {
            "buf500":        self.mid_buf_500,
            "buf100":        self.mid_buf_100,
            "row":           self.row,
            "r1_row":        self.regime1_entry_row,
            "r1_qty":        self.regime1_qty,
            "lean":          self.lean_target,
            "lean_mid":      self.lean_entry_mid,
            "lean_side":     self.lean_entry_side,
        }

    @staticmethod
    def from_dict(d: dict) -> "HydrogelState":
        s = HydrogelState()
        s.mid_buf_500       = d.get("buf500", [])
        s.mid_buf_100       = d.get("buf100", [])
        s.row               = d.get("row", 0)
        s.regime1_entry_row = d.get("r1_row")
        s.regime1_qty       = d.get("r1_qty", 0)
        s.lean_target       = d.get("lean", 0.0)
        s.lean_entry_mid    = d.get("lean_mid")
        s.lean_entry_side   = d.get("lean_side", 0)
        return s

    @staticmethod
    def load(trader_data: str) -> "HydrogelState":
        if not trader_data:
            return HydrogelState()
        try:
            raw = json.loads(trader_data)
            return HydrogelState.from_dict(raw.get("hg", {}))
        except Exception:
            return HydrogelState()

    def save(self, trader_data: str) -> str:
        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}
        raw["hg"] = self.to_dict()
        return json.dumps(raw)


def run_hydrogel(state: TradingState, hstate: HydrogelState) -> Tuple[List[Order], HydrogelState]:
    P      = Product.HYDROGEL_PACK
    orders: List[Order] = []
    p      = HydrogelParams

    if P not in state.order_depths:
        return orders, hstate

    od       = state.order_depths[P]
    position = state.position.get(P, 0)
    pos_lim  = POSITION_LIMITS[P]
    features = compute_book_features(od)

    if not features:
        return orders, hstate

    mid      = features["mid"]
    spread   = features["spread"]
    best_bid = int(features["best_bid"])
    best_ask = int(features["best_ask"])
    imb_L1   = features["imbalance_L1"]
    wap_edge = features["book_wap_edge_L3"]

    z500: Optional[float] = None
    if len(hstate.mid_buf_500) == p.Z500_WINDOW:
        z500 = _zscore(hstate.mid_buf_500, mid)

    hstate.mid_buf_500 = _push(hstate.mid_buf_500, mid, p.Z500_WINDOW)
    hstate.mid_buf_100 = _push(hstate.mid_buf_100, mid, p.STD100_WINDOW)
    hstate.row        += 1

    mean_is_anchored = False
    if (len(hstate.mid_buf_500) >= p.Z500_WINDOW
            and len(hstate.mid_buf_100) == p.STD100_WINDOW):
        roll_std_100 = _std(hstate.mid_buf_100)
        if (roll_std_100 and roll_std_100 > 0
                and len(hstate.mid_buf_500) >= 2 * p.STD100_WINDOW):
            mean_now  = _mean(hstate.mid_buf_500[-p.STD100_WINDOW:])
            mean_prev = _mean(hstate.mid_buf_500[-2 * p.STD100_WINDOW: -p.STD100_WINDOW])
            if mean_now is not None and mean_prev is not None:
                mean_drift = abs(mean_now - mean_prev)
                mean_is_anchored = mean_drift < p.MEAN_ANCHOR_STD_MULTIPLIER * roll_std_100

    skip_bid = False
    if spread < p.REGIME1_SPREAD_THRESHOLD:
        if hstate.regime1_entry_row is not None:
            rows_in_trade = hstate.row - hstate.regime1_entry_row
            if rows_in_trade >= p.REGIME1_EXIT_ROWS:
                if hstate.regime1_qty > 0:
                    exit_qty = min(hstate.regime1_qty, position)
                    if exit_qty > 0:
                        orders.append(Order(P, best_ask, -exit_qty))
                elif hstate.regime1_qty < 0:
                    exit_qty = min(-hstate.regime1_qty, -position)
                    if exit_qty > 0:
                        orders.append(Order(P, best_bid, exit_qty))
                hstate.regime1_entry_row = None
                hstate.regime1_qty       = 0
        else:
            if imb_L1 > p.REGIME1_IMB_THRESHOLD:
                headroom = pos_lim - position
                qty      = min(p.REGIME1_ENTRY_SIZE, headroom)
                if qty > 0:
                    orders.append(Order(P, best_ask, qty))
                    hstate.regime1_entry_row = hstate.row
                    hstate.regime1_qty       = qty
            elif imb_L1 < -p.REGIME1_IMB_THRESHOLD:
                headroom = pos_lim + position
                qty      = min(p.REGIME1_ENTRY_SIZE, headroom)
                if qty > 0:
                    orders.append(Order(P, best_bid, -qty))
                    hstate.regime1_entry_row = hstate.row
                    hstate.regime1_qty       = -qty
        return orders, hstate
    else:
        if hstate.regime1_entry_row is not None:
            hstate.regime1_entry_row = None
            hstate.regime1_qty       = 0

    skip_bid = False
    if spread == p.REGIME2_SPREAD:
        if position > 0:
            flatten_px = best_bid if p.REGIME2_FLATTEN_AGGRESSIVE else best_ask
            orders.append(Order(P, flatten_px, -position))
        skip_bid = True

    prev_lean = hstate.lean_target

    if z500 is not None:
        if mean_is_anchored:
            if z500 > p.REGIME3_Z_ENTER:
                hstate.lean_target = -p.LAYER_B_SCALE * pos_lim
            elif z500 < -p.REGIME3_Z_ENTER:
                hstate.lean_target = p.LAYER_B_SCALE * pos_lim
            elif abs(z500) < p.REGIME3_Z_EXIT:
                hstate.lean_target = 0.0
            else:
                frac      = ((abs(z500) - p.REGIME3_Z_EXIT)
                             / (p.REGIME3_Z_ENTER - p.REGIME3_Z_EXIT))
                direction = -1 if z500 > 0 else 1
                hstate.lean_target = direction * frac * p.LAYER_B_SCALE * pos_lim
        else:
            hstate.lean_target = 0.0

    lean_changed = (
        (prev_lean == 0.0 and hstate.lean_target != 0.0)
        or (prev_lean != 0.0
            and hstate.lean_target != 0.0
            and prev_lean * hstate.lean_target < 0)
    )
    if lean_changed:
        hstate.lean_entry_mid  = mid
        hstate.lean_entry_side = 1 if hstate.lean_target > 0 else -1

    if hstate.lean_target == 0.0:
        hstate.lean_entry_mid  = None
        hstate.lean_entry_side = 0

    stop_fired = False
    if hstate.lean_entry_mid is not None and hstate.lean_target != 0.0:
        adverse_move = (mid - hstate.lean_entry_mid) * (-hstate.lean_entry_side)
        if adverse_move > p.REGIME3_STOP_TICKS:
            stop_fired = True
            lean_position_est = int(round(hstate.lean_target))
            if hstate.lean_entry_side == 1 and position > 0:
                exit_qty = min(abs(lean_position_est), position)
                if exit_qty > 0:
                    orders.append(Order(P, best_bid, -exit_qty))
            elif hstate.lean_entry_side == -1 and position < 0:
                exit_qty = min(abs(lean_position_est), -position)
                if exit_qty > 0:
                    orders.append(Order(P, best_ask, exit_qty))
            hstate.lean_target     = 0.0
            hstate.lean_entry_mid  = None
            hstate.lean_entry_side = 0

    if stop_fired:
        return orders, hstate

    skew_A = _clip(wap_edge * p.LAYER_A_SCALE, -p.LAYER_A_CLIP, p.LAYER_A_CLIP)
    inv_adj_raw = (hstate.lean_target - position) * p.INV_ADJ_COEFF
    inv_adj     = _clip(inv_adj_raw, -p.INV_ADJ_CLIP, p.INV_ADJ_CLIP)
    bid_offset = skew_A + inv_adj

    vol_buf = hstate.mid_buf_100[-p.HP_VOL_WINDOW:]
    sigma   = _std(vol_buf) if len(vol_buf) >= 5 else None
    if sigma is None:
        slack = p.HP_SLACK_MIN
    else:
        slack = int(round(p.HP_SLACK_COEF * sigma))
        slack = max(p.HP_SLACK_MIN, min(p.HP_SLACK_MAX, slack))

    fv = int(round(mid))
    bid_headroom = pos_lim - position
    ask_headroom = pos_lim + position

    half_thresh = pos_lim * p.POS_AGGRESSION_FRAC
    mbp = fv - 1 if position >  half_thresh else fv
    msp = fv + 1 if position < -half_thresh else fv

    for px, vol in sorted(od.sell_orders.items()):
        if bid_headroom <= 0 or px > mbp:
            break
        take = min(bid_headroom, abs(vol))
        if take > 0:
            orders.append(Order(P, px, take))
            bid_headroom -= take

    for px, vol in sorted(od.buy_orders.items(), reverse=True):
        if ask_headroom <= 0 or px < msp:
            break
        take = min(ask_headroom, vol)
        if take > 0:
            orders.append(Order(P, px, -take))
            ask_headroom -= take

    base_bid = min(fv - slack, best_bid + 1)
    base_ask = max(fv + slack, best_ask - 1)
    my_bid = int(round(base_bid + bid_offset))
    my_ask = int(round(base_ask + bid_offset))
    my_bid = max(my_bid, best_bid + 1)
    my_ask = min(my_ask, best_ask - 1)
    my_bid = min(my_bid, best_ask - 1)
    my_ask = max(my_ask, best_bid + 1)
    if my_ask <= my_bid:
        my_ask = my_bid + 1

    qs       = p.QUOTE_SIZE
    bid_qty  = min(qs, max(0, bid_headroom))
    ask_qty  = min(qs, max(0, ask_headroom))

    if bid_qty > 0 and not skip_bid:
        orders.append(Order(P, my_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order(P, my_ask, -ask_qty))

    return orders, hstate


class BlackScholes:
    @staticmethod
    def black_scholes_call(spot: float, strike: float, time_to_expiry: float, volatility: float, r: float = 0.0) -> float:
        if time_to_expiry <= 0:
            return max(spot - strike, 0.0)
        d1 = (math.log(spot / strike) + (r + 0.5 * volatility ** 2) * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))
        d2 = d1 - volatility * math.sqrt(time_to_expiry)
        call_price = spot * NormalDist().cdf(d1) - strike * math.exp(-r * time_to_expiry) * NormalDist().cdf(d2)
        return call_price

    @staticmethod
    def delta(spot: float, strike: float, time_to_expiry: float, volatility: float, r: float = 0.0) -> float:
        if time_to_expiry <= 0:
            return 1.0 if spot > strike else 0.0
        d1 = (math.log(spot / strike) + (r + 0.5 * volatility ** 2) * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))
        return NormalDist().cdf(d1)


class VelvetState:
    def __init__(self) -> None:
        self.underlying_history: List[float] = []

    def to_dict(self) -> dict:
        return {"uhist": self.underlying_history}

    @staticmethod
    def from_dict(d: dict) -> "VelvetState":
        s = VelvetState()
        s.underlying_history = d.get("uhist", [])
        return s


def run_velvet_options(state: TradingState, vstate: VelvetState) -> Tuple[Dict[Symbol, List[Order]], VelvetState]:
    out_orders: Dict[Symbol, List[Order]] = {}
    under_product = Product.VELVETFRUIT_EXTRACT

    if under_product not in state.order_depths:
        return out_orders, vstate

    under_depth = state.order_depths[under_product]

    under_mid = None
    if under_depth.buy_orders and under_depth.sell_orders:
        under_mid = (max(under_depth.buy_orders.keys()) + min(under_depth.sell_orders.keys())) / 2.0
        vstate.underlying_history.append(under_mid)
        if len(vstate.underlying_history) > 100:
            vstate.underlying_history.pop(0)
    else:
        if len(vstate.underlying_history) > 0:
            under_mid = vstate.underlying_history[-1]

    if under_mid is None:
        return out_orders, vstate

    sigma = 0.20
    if len(vstate.underlying_history) > 2:
        log_returns = []
        for i in range(1, len(vstate.underlying_history)):
            log_returns.append(math.log(vstate.underlying_history[i] / vstate.underlying_history[i-1]))
        mean_ret = sum(log_returns) / len(log_returns)
        var_ret = sum((r - mean_ret)**2 for r in log_returns) / (len(log_returns) - 1)
        if var_ret > 0:
            sigma = math.sqrt(var_ret) * math.sqrt(10000 * 250)

    if sigma < 0.01:
        sigma = 0.01

    timestamp_fraction = state.timestamp / 1_000_000.0
    tte_years = max((5.0 - timestamp_fraction) / 250.0, 0.0001)

    portfolio_delta = 0.0

    options = [
        "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
        "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
        "VEV_6000", "VEV_6500"
    ]

    for opt in options:
        opt_product = getattr(Product, opt)
        if opt_product not in state.order_depths:
            continue

        opt_depth = state.order_depths[opt_product]
        opt_pos = state.position.get(opt_product, 0)

        strike = float(opt.replace("VEV_", ""))

        fv = BlackScholes.black_scholes_call(under_mid, strike, tte_years, sigma)
        opt_delta = BlackScholes.delta(under_mid, strike, tte_years, sigma)

        portfolio_delta += opt_pos * opt_delta

        edge = 1.6
        buy_fv = fv - edge
        sell_fv = fv + edge

        opt_orders: List[Order] = []
        pos_limit = POSITION_LIMITS[opt_product]

        cur_pos = opt_pos
        for px in sorted(opt_depth.sell_orders.keys()):
            if px <= buy_fv:
                vol = abs(opt_depth.sell_orders[px])
                allowance = pos_limit - cur_pos
                trade_vol = min(vol, allowance)
                if trade_vol > 0:
                    opt_orders.append(Order(opt_product, px, trade_vol))
                    cur_pos += trade_vol
            else:
                break

        cur_pos = opt_pos
        for px in sorted(opt_depth.buy_orders.keys(), reverse=True):
            if px >= sell_fv:
                vol = opt_depth.buy_orders[px]
                allowance = pos_limit + cur_pos
                trade_vol = min(vol, allowance)
                if trade_vol > 0:
                    opt_orders.append(Order(opt_product, px, -trade_vol))
                    cur_pos -= trade_vol
            else:
                break

        if opt_orders:
            out_orders[opt_product] = opt_orders

    target_under_pos = -int(round(portfolio_delta))
    under_pos = state.position.get(under_product, 0)
    current_diff = target_under_pos - under_pos

    if current_diff != 0:
        under_orders: List[Order] = []
        under_limit = POSITION_LIMITS[under_product]

        if current_diff > 0:
            allowance = under_limit - under_pos
            trade_vol = min(current_diff, allowance)
            if trade_vol > 0 and under_depth.buy_orders:
                best_bid = max(under_depth.buy_orders.keys())
                under_orders.append(Order(under_product, best_bid, trade_vol))
        else:
            allowance = under_limit + under_pos
            trade_vol = min(abs(current_diff), allowance)
            if trade_vol > 0 and under_depth.sell_orders:
                best_ask = min(under_depth.sell_orders.keys())
                under_orders.append(Order(under_product, best_ask, -trade_vol))

        if under_orders:
            out_orders[under_product] = under_orders

    return out_orders, vstate


class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orders:     Dict[Symbol, List[Order]] = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        try:
            raw_state = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw_state = {}

        hstate = HydrogelState.load(trader_data)
        hydrogel_orders, hstate = run_hydrogel(state, hstate)
        orders[Product.HYDROGEL_PACK] = hydrogel_orders
        raw_state["hg"] = hstate.to_dict()

        vstate = VelvetState.from_dict(raw_state.get("velvet", {}))
        velvet_orders, vstate = run_velvet_options(state, vstate)
        raw_state["velvet"] = vstate.to_dict()

        for p, ords in velvet_orders.items():
            if p not in orders:
                orders[p] = []
            orders[p].extend(ords)

        new_trader_data = json.dumps(raw_state)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data
