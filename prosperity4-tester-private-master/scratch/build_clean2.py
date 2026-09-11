import re

with open("trader-logic/round-3/vouchers_clean2.py", "r") as f:
    text = f.read()

part1 = text[:text.find("# === VOUCHERS CLEAN 2 REWRITE ===")]

part2 = """# === VOUCHERS CLEAN 2 REWRITE ===
import math
from typing import Dict, List, Tuple

class CV2State:
    def __init__(self):
        self.ema_iv = {}
        self.ema_td = {}
        self.ema_sd = {}
        self.ema_o = {}
        self.ema_u = None

    def to_dict(self):
        return {
            "e_iv": self.ema_iv,
            "e_td": self.ema_td,
            "e_sd": self.ema_sd,
            "e_o": self.ema_o,
            "e_u": self.ema_u
        }

    @staticmethod
    def load(d):
        s = CV2State()
        if not d: return s
        s.ema_iv = {int(k): v for k, v in d.get("e_iv", {}).items()}
        s.ema_td = {int(k): v for k, v in d.get("e_td", {}).items()}
        s.ema_sd = {int(k): v for k, v in d.get("e_sd", {}).items()}
        s.ema_o = {int(k): v for k, v in d.get("e_o", {}).items()}
        s.ema_u = d.get("e_u")
        return s

def calc_ema(old_val, new_val, window):
    if old_val is None: return new_val
    alpha = 2.0 / (window + 1.0)
    return alpha * new_val + (1.0 - alpha) * old_val
    
def cv_norm_cdf(x):
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5*t + a4)*t) + a3)*t + a2)*t + a1)*t * math.exp(-x*x/2.0)
    return 0.5 * (1.0 + sign * y)

def cv_bs_call(S, K, T, vol):
    if T <= 0 or vol <= 0: return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    return S * cv_norm_cdf(d1) - K * cv_norm_cdf(d2)

def cv_bs_delta(S, K, T, vol):
    if T <= 0 or vol <= 0: return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    return cv_norm_cdf(d1)

def cv_implied_vol(mkt, S, K, T):
    intr = max(S - K, 0.0)
    if mkt <= intr + 1e-6 or T <= 0 or mkt >= S: return None
    lo, hi = 1e-4, 5.0
    for _ in range(30):
        m = 0.5 * (lo + hi)
        if cv_bs_call(S, K, T, m) < mkt: lo = m
        else: hi = m
    return 0.5 * (lo + hi)

THR_OPEN = 1.0
THR_CLOSE = 0.0
THEO_NORM_WINDOW = 20
IV_SCALPING_THR = 0.7
IV_SCALPING_WINDOW = 100
MR_WINDOW = 30
MR_THR = 5.0

def run_vouchers_clean2(state: TradingState, vstate: CV2State):
    orders = {}
    VFE = "VELVETFRUIT_EXTRACT"
    STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500] 
    
    od_vfe = state.order_depths.get(VFE)
    spot = None
    if od_vfe and od_vfe.buy_orders and od_vfe.sell_orders:
        spot = (max(od_vfe.buy_orders.keys()) + min(od_vfe.sell_orders.keys())) / 2.0
    
    if spot is None: return orders
    vstate.ema_u = calc_ema(vstate.ema_u, spot, MR_WINDOW)
    ema_u_dev = spot - vstate.ema_u
        
    T = max(5.0 - state.timestamp / 1_000_000.0, 0.01) / 250.0
    portfolio_delta = state.position.get(VFE, 0) * 1.0
    
    for K in STRIKES:
        sym = f"VEV_{K}"
        od = state.order_depths.get(sym)
        pos = state.position.get(sym, 0)
        
        if not od or not od.buy_orders or not od.sell_orders: 
            if K in vstate.ema_iv:
                portfolio_delta += pos * cv_bs_delta(spot, K, T, vstate.ema_iv[K])
            continue
            
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        mid = (bb + ba) / 2.0
        
        vstate.ema_o[K] = calc_ema(vstate.ema_o.get(K), mid, MR_WINDOW)
        
        iv = cv_implied_vol(mid, spot, K, T)
        if iv is not None:
            vstate.ema_iv[K] = calc_ema(vstate.ema_iv.get(K), iv, 20)
            
        current_iv = vstate.ema_iv.get(K)
        if current_iv is None: continue
        
        portfolio_delta += pos * cv_bs_delta(spot, K, T, current_iv)
        
        theo = cv_bs_call(spot, K, T, current_iv)
        theo_diff = mid - theo
        vstate.ema_td[K] = calc_ema(vstate.ema_td.get(K), theo_diff, THEO_NORM_WINDOW)
        
        mean_td = vstate.ema_td[K]
        avg_dev = abs(theo_diff - mean_td)
        vstate.ema_sd[K] = calc_ema(vstate.ema_sd.get(K), avg_dev, IV_SCALPING_WINDOW)
        
        tb = min(300 - pos, 300)
        ts = min(300 + pos, 300)
        new_orders = []
        did_trade = False
        
        if K >= 5000:
            if vstate.ema_sd[K] >= IV_SCALPING_THR:
                if theo_diff - mid + bb - mean_td >= THR_OPEN and ts > 0:
                    q = min(15, ts, od.buy_orders.get(bb, 15))
                    new_orders.append(Order(sym, bb, -q))
                    ts -= q; did_trade = True
                    
                if pos > 0 and theo_diff - mid + bb - mean_td >= THR_CLOSE:
                    q = min(pos, ts, od.buy_orders.get(bb, pos))
                    if q > 0:
                        new_orders.append(Order(sym, bb, -q))
                        ts -= q; did_trade = True
                        
                elif theo_diff - mid + ba - mean_td <= -THR_OPEN and tb > 0:
                    q = min(15, tb, -od.sell_orders.get(ba, -15))
                    new_orders.append(Order(sym, ba, q))
                    tb -= q; did_trade = True
                    
                if pos < 0 and theo_diff - mid + ba - mean_td <= -THR_CLOSE:
                    q = min(-pos, tb, -od.sell_orders.get(ba, -15))
                    if q > 0:
                        new_orders.append(Order(sym, ba, q))
                        tb -= q; did_trade = True
        else:
            ema_o_dev_K = mid - vstate.ema_o[K]
            current_dev = ema_u_dev + (theo_diff - mean_td)
            
            if current_dev > MR_THR and ts > 0:
                q = min(15, ts, od.buy_orders.get(bb, 15))
                if q > 0:
                    new_orders.append(Order(sym, bb, -q))
                    ts -= q; did_trade = True
            elif current_dev < -MR_THR and tb > 0:
                q = min(15, tb, -od.sell_orders.get(ba, -15))
                if q > 0:
                    new_orders.append(Order(sym, ba, q))
                    tb -= q; did_trade = True
        
        slack = 1 if K in [5000, 5100, 5200, 5300, 5400] else 3
        bid_px = math.floor(theo - slack)
        ask_px = math.ceil(theo + slack)
        
        if pos > 200: bid_px -= 1; ask_px -= 1
        if pos < -200: bid_px += 1; ask_px += 1
        
        bid_px = min(bid_px, bb + 1)
        ask_px = max(ask_px, ba - 1)
        if ask_px <= bid_px: ask_px = bid_px + 1
        
        if tb > 0 and len(new_orders) < 2: new_orders.append(Order(sym, bid_px, min(10, tb)))
        if ts > 0 and len(new_orders) < 2: new_orders.append(Order(sym, ask_px, -min(10, ts)))
        
        if new_orders: orders[sym] = new_orders

    if od_vfe and od_vfe.buy_orders and od_vfe.sell_orders:
        tb = 250 - state.position.get(VFE, 0)
        ts = 250 + state.position.get(VFE, 0)
        bb = max(od_vfe.buy_orders.keys())
        ba = min(od_vfe.sell_orders.keys())
        
        vfe_orders = []
        my_bid = min(bb + 1, ba - 1)
        my_ask = max(ba - 1, bb + 1)
        
        if portfolio_delta > 50 and ts > 0:
            q = min(ts, int(portfolio_delta/1.5))
            if q > 0:
                vfe_orders.append(Order(VFE, my_ask, -q))
                ts -= q
        elif portfolio_delta < -50 and tb > 0:
            q = min(tb, int(-portfolio_delta/1.5))
            if q > 0:
                vfe_orders.append(Order(VFE, my_bid, q))
                tb -= q
            
        if tb > 0: vfe_orders.append(Order(VFE, my_bid, min(tb, 10)))
        if ts > 0: vfe_orders.append(Order(VFE, my_ask, -min(ts, 10)))
        
        if vfe_orders: orders[VFE] = vfe_orders

    return orders

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
        import json
        orders = {p: [] for p in state.order_depths}
        conversions = 0
        trader_data = state.traderData or ""

        try:
            raw = json.loads(trader_data) if trader_data else {}
        except Exception:
            raw = {}

        # 1) HYDROGEL_PACK
        hstate = HydrogelState.from_dict(raw.get("hg", {})) if hasattr(HydrogelState, "from_dict") else HydrogelState.load(trader_data)
        hydrogel_orders, hstate = run_hydrogel(state, hstate)
        orders[Product.HYDROGEL_PACK] = hydrogel_orders
        raw["hg"] = hstate.to_dict()

        # 2) CLEAN VOUCHERS 2
        vstate = CV2State.load(raw.get("cv2", {}))
        voucher_orders = run_vouchers_clean2(state, vstate)
        for sym, ord_list in voucher_orders.items():
            if sym not in orders: orders[sym] = []
            orders[sym].extend(ord_list)
            
        raw["cv2"] = vstate.to_dict()

        new_trader_data = json.dumps(raw)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data
"""

with open("trader-logic/round-3/vouchers_clean2.py", "w") as f:
    f.write(part1 + part2)

