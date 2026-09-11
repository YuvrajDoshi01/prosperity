import json
import numpy as np
import math
import copy
from typing import Any, List, Tuple, Dict

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState

class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 45000 

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, "", ""]))
        max_item_length = (self.max_log_length - base_length) // 3
        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, max_item_length)),
            self.compress_orders(orders),
            conversions,
            self.truncate(trader_data, 1000),
            self.truncate(self.logs, max_item_length),
        ]))
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [state.timestamp, trader_data, self.compress_listings(state.listings), self.compress_order_depths(state.order_depths),
                self.compress_trades(state.own_trades), self.compress_trades(state.market_trades), state.position, self.compress_observations(state.observations)]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        return {s: [od.buy_orders, od.sell_orders] for s, od in order_depths.items()}

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for t in arr: compressed.append([t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp])
        return compressed

    def compress_observations(self, obs: Observation) -> list[Any]:
        conv = {p: [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff, o.importTariff, o.sugarPrice, o.sunlightIndex] 
                for p, o in obs.conversionObservations.items()} if obs else {}
        return [obs.plainValueObservations if obs else {}, conv]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for o in arr: compressed.append([o.symbol, o.price, o.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if not value: return ""
        if len(json.dumps(value)) <= max_length: return value
        return value[:max_length-3] + "..."

logger = Logger()

class Product:
    PEBBLES_XS, PEBBLES_S, PEBBLES_M, PEBBLES_L, PEBBLES_XL = "PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"
    PANEL_1X2, PANEL_2X2, PANEL_1X4, PANEL_2X4, PANEL_4X4 = "PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"
    OXYGEN_SHAKE_MORNING_BREATH, OXYGEN_SHAKE_EVENING_BREATH, OXYGEN_SHAKE_MINT, OXYGEN_SHAKE_CHOCOLATE, OXYGEN_SHAKE_GARLIC = "OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH", "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC"
    SNACKPACK_CHOCOLATE, SNACKPACK_VANILLA, SNACKPACK_PISTACHIO, SNACKPACK_STRAWBERRY, SNACKPACK_RASPBERRY = "SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO", "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"
    GALAXY_SOUNDS_DARK_MATTER, GALAXY_SOUNDS_BLACK_HOLES, GALAXY_SOUNDS_PLANETARY_RINGS, GALAXY_SOUNDS_SOLAR_WINDS, GALAXY_SOUNDS_SOLAR_FLAMES = "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES", "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS", "GALAXY_SOUNDS_SOLAR_FLAMES"
    SLEEP_POD_SUEDE, SLEEP_POD_LAMB_WOOL, SLEEP_POD_POLYESTER, SLEEP_POD_NYLON, SLEEP_POD_COTTON = "SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER", "SLEEP_POD_NYLON", "SLEEP_POD_COTTON"
    MICROCHIP_CIRCLE, MICROCHIP_OVAL, MICROCHIP_SQUARE, MICROCHIP_RECTANGLE, MICROCHIP_TRIANGLE = "MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE", "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"
    ROBOT_VACUUMING, ROBOT_MOPPING, ROBOT_DISHES, ROBOT_LAUNDRY, ROBOT_IRONING = "ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES", "ROBOT_LAUNDRY", "ROBOT_IRONING"
    UV_VISOR_YELLOW, UV_VISOR_AMBER, UV_VISOR_ORANGE, UV_VISOR_RED, UV_VISOR_MAGENTA = "UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE", "UV_VISOR_RED", "UV_VISOR_MAGENTA"
    TRANSLATOR_SPACE_GRAY, TRANSLATOR_ASTRO_BLACK, TRANSLATOR_ECLIPSE_CHARCOAL, TRANSLATOR_GRAPHITE_MIST, TRANSLATOR_VOID_BLUE = "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST", "TRANSLATOR_VOID_BLUE"

class Cfg:
    POS = 10
    STEP = 50
    CV_SPREAD_BUCKET = 5
    CV_LOOKBACK = 3000
    CV_EXTREME_FRAC = 0.2
    CV_MA_WINDOW = 50
    CV_MIN_RANGE_BUCKETS = 4
    CV_MIN_HOLD = 10
    CV_COOLDOWN = 30
    CV_WARMUP_TICKS = 300
    CV_TSTAT_WINDOW = 100
    CV_TSTAT_MAX = 2.0
    SR_DECISION_TICK = 100
    SR_FORCE_TICK = 260
    SR_T_WINDOW = 120
    SR_T_MIN_POINTS = 40
    SR_T_THRESHOLD = 3.0
    SR_TOTAL_TICKS = 10000
    SR_TP_MULT = 1.6
    SR_HARD_SL = 2000 
    SR_PNL_STOP = -1000 
    SR_SL_MULT = 0.50
    SR_SL_MIN = 0.50
    SR_SL_MAX = 3.00

C = Cfg()

class Trader:
    def __init__(self):
        self.LIMIT = {p: 10 for p in [getattr(Product, a) for a in dir(Product) if not a.startswith("__")]}
            
        self.ROBOT_PARAMS = {
            Product.ROBOT_IRONING:  {"edge": 1.0, "obi_lean": 0.0, "pos_lean": 0.2, "take_width": 0.5},
            Product.ROBOT_VACUUMING: {"edge": 1.5, "obi_lean": 0.0, "pos_lean": 0.2, "take_width": 1.0},
            Product.ROBOT_MOPPING:  {"edge": 2.5, "obi_lean": 1.5, "pos_lean": 0.4, "take_width": 2.0},
            Product.ROBOT_LAUNDRY:  {"edge": 3.0, "obi_lean": 0.0, "pos_lean": 0.4, "take_width": 2.5},
            Product.ROBOT_DISHES:   {"edge": 2.5, "obi_lean": 0.0, "pos_lean": 0.4, "take_width": 2.5}
        }

        self.UV_VISOR_MODELS = {
            Product.UV_VISOR_AMBER:   {"f": [Product.GALAXY_SOUNDS_SOLAR_FLAMES, Product.PEBBLES_XS], "c": [-0.5428, 0.1652], "i": 24200.17, "s": 133.5, "t": 0.5},
            Product.UV_VISOR_MAGENTA: {"f": [Product.ROBOT_IRONING, Product.OXYGEN_SHAKE_MINT],      "c": [0.5817, -0.1011], "i": 7952.36,  "s": 231.4, "t": 1.0},
            Product.UV_VISOR_ORANGE:  {"f": [Product.PANEL_2X2, Product.SLEEP_POD_COTTON],           "c": [-1.2243, 0.3904], "i": 16668.49, "s": 258.6, "t": 1.0},
            Product.UV_VISOR_RED:     {"f": [Product.TRANSLATOR_SPACE_GRAY, Product.OXYGEN_SHAKE_CHOCOLATE], "c": [-0.2987, 0.1343], "i": 13116.74, "s": 175.2, "t": 1.0},
            Product.UV_VISOR_YELLOW:  {"f": [Product.OXYGEN_SHAKE_CHOCOLATE, Product.MICROCHIP_OVAL], "c": [-0.6304, 0.5920], "i": 13334.75, "s": 220.6, "t": 0.5}
        }
    
    def get_obi(self, od: OrderDepth):
        bid_vol = sum(od.buy_orders.values()) if od.buy_orders else 0
        ask_vol = sum(abs(v) for v in od.sell_orders.values()) if od.sell_orders else 0
        if bid_vol + ask_vol == 0: return 0
        return (bid_vol - ask_vol) / (bid_vol + ask_vol)
    
    def slope_t_stat(self, vals: List[float]) -> Tuple[float, float]:
        n = len(vals)
        if n < 3: return 0.0, 0.0
        x_mean = 0.5 * (n - 1)
        y_mean = sum(vals) / n
        sxx, sxy = 0.0, 0.0
        for i, y in enumerate(vals):
            dx = i - x_mean
            sxx += dx * dx
            sxy += dx * (y - y_mean)
        if sxx <= 0: return 0.0, 0.0
        slope = sxy / sxx
        rss = sum((y - (y_mean - slope * x_mean + slope * i))**2 for i, y in enumerate(vals))
        sigma2 = rss / max(1, n - 2)
        se = math.sqrt(max(1e-12, sigma2 / sxx))
        return slope, (slope / se if se > 0 else 0.0)

    def get_book(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders: return None
        bb, ba = max(od.buy_orders), min(od.sell_orders)
        bbv = int(max(0, od.buy_orders.get(bb, 0)))
        bav = int(max(0, -od.sell_orders.get(ba, 0)))
        return bb, ba, (bb + ba) / 2.0, bbv, bav

    def take_orders(self, product, od, fair, width, pos):
        orders, buy_v, sell_v = [], 0, 0
        limit = self.LIMIT.get(product, 10)
        if od.sell_orders:
            ba = min(od.sell_orders)
            if ba <= fair - width:
                q = min(-od.sell_orders[ba], limit - pos)
                if q > 0: orders.append(Order(product, ba, q)); buy_v += q; od.sell_orders[ba] += q
        if od.buy_orders:
            bb = max(od.buy_orders)
            if bb >= fair + width:
                q = min(od.buy_orders[bb], limit + pos)
                if q > 0: orders.append(Order(product, bb, -q)); sell_v += q; od.buy_orders[bb] -= q
        return orders, buy_v, sell_v

    def clear_orders(self, product, od, fair, width, pos, b_v, s_v):
        orders = []
        p_after = pos + b_v - s_v
        f_bid, f_ask = round(fair - width), round(fair + width)
        limit = self.LIMIT.get(product, 10)
        if p_after > limit:
            clear_q = p_after - limit
            sent = 0
            for bb in sorted(od.buy_orders.keys(), reverse=True):
                if bb >= f_ask:
                    q = min(od.buy_orders[bb], clear_q - sent)
                    if q > 0: sent += q; od.buy_orders[bb] -= q
                else: break
            if sent > 0: orders.append(Order(product, int(f_ask), -int(sent))); s_v += sent
        elif p_after < -limit:
            clear_q = abs(p_after) - limit
            sent = 0
            for ba in sorted(od.sell_orders.keys()):
                if ba <= f_bid:
                    q = min(-od.sell_orders[ba], clear_q - sent)
                    if q > 0: sent += q; od.sell_orders[ba] += q
                else: break
            if sent > 0: orders.append(Order(product, int(f_bid), int(sent))); b_v += sent
        return orders, b_v, s_v

    def make_orders(self, product, od, mid, fair, pos, b_v, s_v, edge):
        orders = []
        limit = self.LIMIT.get(product, 10)
        
        ask = round(fair + edge)
        min_ask = int(math.ceil(mid + 0.5))
        ask = max(ask, min_ask)
        
        b_ask = min([p for p in od.sell_orders if p >= min_ask] or [ask])
        if b_ask > min_ask:
            ask = min(ask, b_ask - 1)
        
        bid = round(fair - edge)
        max_bid = int(math.floor(mid - 0.5))
        bid = min(bid, max_bid)
        
        b_bid = max([p for p in od.buy_orders if p <= max_bid] or [bid])
        if b_bid < max_bid:
            bid = max(bid, b_bid + 1)
            
        buy_q = limit - (pos + b_v)
        if buy_q > 0: orders.append(Order(product, int(round(bid)), int(buy_q)))
        sell_q = limit + (pos - s_v)
        if sell_q > 0: orders.append(Order(product, int(round(ask)), -int(sell_q)))
        return orders

    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        orig_od = state.order_depths
        state.order_depths = copy.deepcopy(orig_od)
        try: td = json.loads(state.traderData) if state.traderData else {}
        except: td = {}
        
        mem = td.get("m", {})
        result = {p: [] for p in state.order_depths}
        agg_v = {p: 0 for p in state.order_depths}
        agg_orders = {p: [] for p in state.order_depths}

        cv, sr, uvo = td.get("cv", {}), td.get("sr", {}), td.get("uvo", {})
        
        mids = {}
        for symbol, depth in state.order_depths.items():
            bk = self.get_book(depth)
            if bk: mids[symbol] = bk[2]

        # --- CV ---
        if Product.SNACKPACK_CHOCOLATE in mids and Product.SNACKPACK_VANILLA in mids:
            b_c, b_v = self.get_book(state.order_depths[Product.SNACKPACK_CHOCOLATE]), self.get_book(state.order_depths[Product.SNACKPACK_VANILLA])
            pos_c, pos_v = state.position.get(Product.SNACKPACK_CHOCOLATE, 0), state.position.get(Product.SNACKPACK_VANILLA, 0)
            phase, ticks = cv.get("phase", "IDLE"), cv.get("ticks", 0) + 1
            hist = list(cv.get("hist", []))
            entry, active_since, cooldown_until = cv.get("entry_idx", 0), cv.get("active_since", 0), cv.get("cooldown_until", 0)
            tgt_c, tgt_v = pos_c, pos_v
            spread_idx = int(round((mids[Product.SNACKPACK_VANILLA] - mids[Product.SNACKPACK_CHOCOLATE]) / C.CV_SPREAD_BUCKET))
            hist.append(spread_idx)
            hist = hist[-C.CV_LOOKBACK:]
            lo, hi = min(hist), max(hist)
            rng = hi - lo
            low_band, high_band = lo + C.CV_EXTREME_FRAC * rng, hi - C.CV_EXTREME_FRAC * rng
            ma20_delta = 0.0
            if len(hist) >= C.CV_MA_WINDOW:
                ma20 = sum(hist[-C.CV_MA_WINDOW:]) / C.CV_MA_WINDOW
                if len(hist) >= C.CV_MA_WINDOW + 1:
                    ma20_delta = ma20 - (sum(hist[-(C.CV_MA_WINDOW + 1):-1]) / C.CV_MA_WINDOW)
            
            # Trend conviction check for CV
            cv_tstat = 0.0
            if len(hist) >= C.CV_TSTAT_WINDOW:
                _, cv_tstat = self.slope_t_stat(hist[-C.CV_TSTAT_WINDOW:])

            if ticks >= C.CV_WARMUP_TICKS:
                if phase == "COOLDOWN" and ticks >= cooldown_until: phase = "IDLE"
                if phase == "IDLE":
                    tgt_c, tgt_v = 0, 0
                    if rng >= C.CV_MIN_RANGE_BUCKETS and abs(cv_tstat) < C.CV_TSTAT_MAX:
                        if spread_idx >= high_band and ma20_delta < 0: phase, entry, active_since = "SHORT_ACTIVE", spread_idx, ticks
                        elif spread_idx <= low_band and ma20_delta > 0: phase, entry, active_since = "LONG_ACTIVE", spread_idx, ticks
                elif phase == "SHORT_ACTIVE":
                    tgt_c, tgt_v = C.POS, -C.POS
                    if (ticks - active_since) >= C.CV_MIN_HOLD and (spread_idx >= hi or (spread_idx <= low_band and ma20_delta > 0)):
                        if spread_idx >= hi: phase, cooldown_until, tgt_c, tgt_v = "COOLDOWN", ticks + C.CV_COOLDOWN, 0, 0
                        else: phase, entry, active_since, tgt_c, tgt_v = "LONG_ACTIVE", spread_idx, ticks, -C.POS, C.POS
                elif phase == "LONG_ACTIVE":
                    tgt_c, tgt_v = -C.POS, C.POS
                    if (ticks - active_since) >= C.CV_MIN_HOLD and (spread_idx <= lo or (spread_idx >= high_band and ma20_delta < 0)):
                        if spread_idx <= lo: phase, cooldown_until, tgt_c, tgt_v = "COOLDOWN", ticks + C.CV_COOLDOWN, 0, 0
                        else: phase, entry, active_since, tgt_c, tgt_v = "SHORT_ACTIVE", spread_idx, ticks, C.POS, -C.POS
            
            dc, dv = tgt_c - pos_c, tgt_v - pos_v
            if dc > 0: q = min(C.STEP, dc, b_c[4]); agg_orders[Product.SNACKPACK_CHOCOLATE].append(Order(Product.SNACKPACK_CHOCOLATE, b_c[1], int(q)))
            elif dc < 0: q = min(C.STEP, -dc, b_c[3]); agg_orders[Product.SNACKPACK_CHOCOLATE].append(Order(Product.SNACKPACK_CHOCOLATE, b_c[0], -int(q)))
            if dv > 0: q = min(C.STEP, dv, b_v[4]); agg_orders[Product.SNACKPACK_VANILLA].append(Order(Product.SNACKPACK_VANILLA, b_v[1], int(q)))
            elif dv < 0: q = min(C.STEP, -dv, b_v[3]); agg_orders[Product.SNACKPACK_VANILLA].append(Order(Product.SNACKPACK_VANILLA, b_v[0], -int(q)))
            cv = {"phase": phase, "ticks": ticks, "hist": hist, "entry_idx": entry, "active_since": active_since, "cooldown_until": cooldown_until}

        # --- SR ---
        if Product.SNACKPACK_STRAWBERRY in mids and Product.SNACKPACK_RASPBERRY in mids:
            b_s, b_r = self.get_book(state.order_depths[Product.SNACKPACK_STRAWBERRY]), self.get_book(state.order_depths[Product.SNACKPACK_RASPBERRY])
            pos_s, pos_r = state.position.get(Product.SNACKPACK_STRAWBERRY, 0), state.position.get(Product.SNACKPACK_RASPBERRY, 0)
            ticks = int(sr.get("ticks", 0)) + 1
            decided = bool(sr.get("decided", False))
            side = int(sr.get("side", 0))
            start_mid, slope = float(sr.get("start_mid", 0.0)), float(sr.get("slope", 0.0))
            recent = list(sr.get("recent_mids", []))
            ae_s, ae_r = float(sr.get("avg_entry_s", 0.0)), float(sr.get("avg_entry_r", 0.0))
            q_s, q_r = int(sr.get("entry_qty_s", 0)), int(sr.get("entry_qty_r", 0))
            flat = bool(sr.get("flattening", False))
            center = 0.5 * (mids[Product.SNACKPACK_STRAWBERRY] + mids[Product.SNACKPACK_RASPBERRY])
            recent.append(center)
            if len(recent) > C.SR_T_WINDOW: recent = recent[-C.SR_T_WINDOW:]
            if ticks == 1: start_mid = center

            if (not decided) and ticks >= C.SR_DECISION_TICK:
                s_hat, tval = self.slope_t_stat(recent)
                slope = s_hat
                if (len(recent) >= C.SR_T_MIN_POINTS and abs(tval) >= C.SR_T_THRESHOLD) or ticks >= C.SR_FORCE_TICK:
                    side, decided = (1 if slope > 0 else (-1 if slope < 0 else 0)), True

            if decided:
                if not flat and side != 0:
                    if side == 1:
                        q = min(C.STEP, C.POS - pos_s, C.POS - pos_r, b_s[4], b_r[4])
                        if q > 0:
                            agg_orders[Product.SNACKPACK_STRAWBERRY].append(Order(Product.SNACKPACK_STRAWBERRY, b_s[1], int(q)))
                            agg_orders[Product.SNACKPACK_RASPBERRY].append(Order(Product.SNACKPACK_RASPBERRY, b_r[1], int(q)))
                            ae_s = (ae_s * q_s + b_s[1] * q) / (q_s + q); ae_r = (ae_r * q_r + b_r[1] * q) / (q_r + q); q_s += q; q_r += q
                    else:
                        q = min(C.STEP, pos_s + C.POS, pos_r + C.POS, b_s[3], b_r[3])
                        if q > 0:
                            agg_orders[Product.SNACKPACK_STRAWBERRY].append(Order(Product.SNACKPACK_STRAWBERRY, b_s[0], -int(q)))
                            agg_orders[Product.SNACKPACK_RASPBERRY].append(Order(Product.SNACKPACK_RASPBERRY, b_r[0], -int(q)))
                            ae_s = (ae_s * q_s + b_s[0] * q) / (q_s + q); ae_r = (ae_r * q_r + b_r[0] * q) / (q_r + q); q_s += q; q_r += q
                
                if side != 0 and (pos_s != 0 or pos_r != 0):
                    rem = max(1, C.SR_TOTAL_TICKS - ticks)
                    e_move = abs(slope) * rem
                    stop = max(C.SR_SL_MIN, min(C.SR_SL_MAX, C.SR_SL_MULT * e_move))
                    cap = e_move * (abs(pos_s) + abs(pos_r))
                    pnl = ((mids[Product.SNACKPACK_STRAWBERRY] - ae_s) * pos_s + (mids[Product.SNACKPACK_RASPBERRY] - ae_r) * pos_r) if side == 1 else ((ae_s - mids[Product.SNACKPACK_STRAWBERRY]) * -pos_s + (ae_r - mids[Product.SNACKPACK_RASPBERRY]) * -pos_r)
                    if pnl >= C.SR_TP_MULT * cap or pnl <= C.SR_PNL_STOP: flat = True 
                    _, tval_now = self.slope_t_stat(recent)
                    if abs(tval_now) < 1.0 or (side == 1 and slope < 0) or (side == -1 and slope > 0): flat = True
                    if (pos_s == 0 and abs(ae_r - mids[Product.SNACKPACK_RASPBERRY]) > stop) or (pos_r == 0 and abs(ae_s - mids[Product.SNACKPACK_STRAWBERRY]) > stop): flat = True

                if flat:
                    if pos_s > 0: q = min(pos_s, C.STEP, b_s[3]); agg_orders[Product.SNACKPACK_STRAWBERRY].append(Order(Product.SNACKPACK_STRAWBERRY, b_s[0], -int(q)))
                    elif pos_s < 0: q = min(-pos_s, C.STEP, b_s[4]); agg_orders[Product.SNACKPACK_STRAWBERRY].append(Order(Product.SNACKPACK_STRAWBERRY, b_s[1], int(q)))
                    if pos_r > 0: q = min(pos_r, C.STEP, b_r[3]); agg_orders[Product.SNACKPACK_RASPBERRY].append(Order(Product.SNACKPACK_RASPBERRY, b_r[0], -int(q)))
                    elif pos_r < 0: q = min(-pos_r, C.STEP, b_r[4]); agg_orders[Product.SNACKPACK_RASPBERRY].append(Order(Product.SNACKPACK_RASPBERRY, b_r[1], int(q)))
                
                if flat and pos_s == 0 and pos_r == 0: 
                    side, flat = 0, False
                    ae_s, ae_r, q_s, q_r = 0.0, 0.0, 0, 0

            sr = {"ticks": ticks, "decided": decided, "side": side, "start_mid": start_mid, "slope": slope, "recent_mids": recent, "avg_entry_s": ae_s, "avg_entry_r": ae_r, "entry_qty_s": q_s, "entry_qty_r": q_r, "flattening": flat}

        for p in agg_orders: agg_v[p] = sum(o.quantity for o in agg_orders[p])

        # --- MM & UV_VISOR ---
        for p in state.order_depths:
            if p == Product.SNACKPACK_PISTACHIO: continue
            od, pos = state.order_depths[p], state.position.get(p, 0)
            if p not in mids: continue
            mid = mids[p]
            
            if p in [Product.SNACKPACK_CHOCOLATE, Product.SNACKPACK_VANILLA, Product.SNACKPACK_STRAWBERRY, Product.SNACKPACK_RASPBERRY]:
                result[p] = agg_orders[p]
            elif p in self.UV_VISOR_MODELS:
                model = self.UV_VISOR_MODELS[p]
                feat_present = True
                fv = model["i"]
                for i, f in enumerate(model["f"]):
                    if f in mids: fv += model["c"][i] * mids[f]
                    else: feat_present = False; break
                if not feat_present: continue
                
                raw_res = mid - fv
                std, limit = model["s"], self.LIMIT.get(p, 10)
                threshold = model["t"] * std
                product_orders = []
                cur_p = pos
                
                if p in [Product.UV_VISOR_RED, Product.UV_VISOR_MAGENTA]:
                    # Static raw residual for RED and MAGENTA (no momentum filter)
                    if raw_res > threshold:
                        for pr, vo in sorted(od.buy_orders.items(), reverse=True):
                            if pr > fv + 0.1 * threshold and cur_p > -limit:
                                q = min(vo, cur_p + limit)
                                product_orders.append(Order(p, pr, -int(q))); cur_p -= q
                        if cur_p > -limit:
                            ask_p = max(min(od.sell_orders.keys()) - 1 if od.sell_orders else int(fv + threshold + 1), int(fv + 1))
                            product_orders.append(Order(p, int(ask_p), -int(cur_p + limit)))
                    elif raw_res < -threshold:
                        for pr, vo in sorted(od.sell_orders.items()):
                            if pr < fv - 0.1 * threshold and cur_p < limit:
                                q = min(-vo, limit - cur_p)
                                product_orders.append(Order(p, pr, int(q))); cur_p += q
                        if cur_p < limit:
                            bid_p = min(max(od.buy_orders.keys()) + 1 if od.buy_orders else int(fv - threshold - 1), int(fv - 1))
                            product_orders.append(Order(p, int(bid_p), int(limit - cur_p)))
                else:
                    # Adaptive EMA residual + momentum filter for others
                    if p not in uvo: uvo[p] = raw_res
                    else: uvo[p] = (1 - 0.001) * uvo[p] + 0.001 * raw_res
                    residual = raw_res - uvo[p]
                    
                    p_mem = mem.get(p, [mid, mid, mid])
                    mid_delta = mid - p_mem[0]
                    p_mem[0] = mid
                    mem[p] = p_mem
                    
                    # Warm-up period to let residual EMA stabilize (50 ticks)
                    if state.timestamp < 5000:
                        result[p] = []
                        continue
                    
                    if residual > threshold and mid_delta < 2.0:
                        for pr, vo in sorted(od.buy_orders.items(), reverse=True):
                            if pr > fv + uvo[p] + 0.1 * threshold and cur_p > -limit:
                                q = min(vo, cur_p + limit)
                                product_orders.append(Order(p, pr, -int(q))); cur_p -= q
                        if cur_p > -limit:
                            ask_p = max(min(od.sell_orders.keys()) - 1 if od.sell_orders else int(fv + uvo[p] + threshold + 1), int(fv + uvo[p] + 1))
                            product_orders.append(Order(p, int(ask_p), -int(cur_p + limit)))
                    elif residual < -threshold and mid_delta > -2.0:
                        for pr, vo in sorted(od.sell_orders.items()):
                            if pr < fv + uvo[p] - 0.1 * threshold and cur_p < limit:
                                q = min(-vo, limit - cur_p)
                                product_orders.append(Order(p, pr, int(q))); cur_p += q
                        if cur_p < limit:
                            bid_p = min(max(od.buy_orders.keys()) + 1 if od.buy_orders else int(fv + uvo[p] - threshold - 1), int(fv + uvo[p] - 1))
                            product_orders.append(Order(p, int(bid_p), int(limit - cur_p)))
                result[p] = product_orders
            else:
                is_robot = p.startswith("ROBOT")
                if is_robot:
                    params = self.ROBOT_PARAMS.get(p, {"edge": 2.0, "obi_lean": 0.0, "pos_lean": 0.4, "take_width": 1.5})
                    obi = self.get_obi(od)
                    fair = mid + obi * params["obi_lean"] - pos * params["pos_lean"]
                    width, tw = params["edge"], params["take_width"]
                    t_o, b_v, s_v = self.take_orders(p, od, fair, tw, pos + agg_v[p])
                    c_o, b_v, s_v = self.clear_orders(p, od, fair, width + 1.0, pos + agg_v[p], b_v, s_v)
                    m_o = self.make_orders(p, od, mid, fair, pos + agg_v[p], b_v, s_v, width)
                    result[p] = agg_orders[p] + t_o + c_o + m_o
                    continue

                is_hyper_volatile = p in ["MICROCHIP_RECTANGLE", "PEBBLES_M", "PEBBLES_L", "TRANSLATOR_SPACE_GRAY", "GALAXY_SOUNDS_PLANETARY_RINGS", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_SUEDE"]
                is_volatile = p.startswith("TRANSLATOR") or p.startswith("SLEEP_POD")
                is_semi_volatile = p.startswith("GALAXY_SOUNDS") or p.startswith("PEBBLES")
                p_mem = mem.get(p, [mid, mid, mid])
                last_ret, p_mem[0] = mid - p_mem[0], mid
                if p in [Product.OXYGEN_SHAKE_CHOCOLATE, Product.OXYGEN_SHAKE_EVENING_BREATH, Product.OXYGEN_SHAKE_MINT, Product.OXYGEN_SHAKE_MORNING_BREATH]: 
                    p_mem[1], p_mem[2] = min(p_mem[1], mid), max(p_mem[2], mid)
                mem[p] = p_mem
                risk_av, width_bonus, obi_lean = (0.8, 3.0, 0.0) if is_hyper_volatile else (0.6, 1.5, 0.5) if is_volatile else (0.5, 1.0, 0.3) if is_semi_volatile else (0.2, 0.5, 0.0) if p.startswith("OXYGEN") else (0.3, 0.5, 0.0)
                obi = self.get_obi(od)
                fair = mid - pos * risk_av + obi * obi_lean
                if p.startswith("OXYGEN"): fair -= 0.15 * last_ret
                width = max(1.5, ((min(od.sell_orders) - max(od.buy_orders)) / 2.0) + width_bonus)
                t_o, b_v, s_v = self.take_orders(p, od, fair, width + 0.5, pos + agg_v[p])
                c_o, b_v, s_v = self.clear_orders(p, od, fair, width + 1.0, pos + agg_v[p], b_v, s_v)
                m_o = self.make_orders(p, od, mid, fair, pos + agg_v[p], b_v, s_v, width)
                result[p] = agg_orders[p] + t_o + c_o + m_o
        
        td_out = json.dumps({"cv": cv, "sr": sr, "m": mem, "uvo": uvo}, separators=(",", ":"))
        logger.flush(state, result, 0, td_out)
        state.order_depths = orig_od
        return result, 0, td_out