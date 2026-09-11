import os

def build():
    try:
        with open("/home/mmaliar/prosperity4-tester-private/trader-logic/round-3/408576.py", "r") as f:
            lines = f.readlines()
    except Exception as e:
        print("Read error:", e)
        return
        
    # Extract just the HP logic, which ends around "Original Trader replaced below with combined v11 version."
    hp_lines = []
    for line in lines:
        if "Original Trader replaced below with combined v11 version" in line:
            break
        hp_lines.append(line)
        
    new_vouchers_code = """
# === VOUCHERS CLEAN REWRITE ===
import math
from typing import Dict, List

class CleanVoucherState:
    def __init__(self):
        self.ivh = {k: [] for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]}
        self.vfe_prices = []

    def to_dict(self):
        return {
            "ivh": {str(k): [round(x, 5) for x in v[-50:]] for k, v in self.ivh.items()},
            "v_px": [round(x, 2) for x in self.vfe_prices[-50:]]
        }

    @staticmethod
    def load(d):
        s = CleanVoucherState()
        if not d: return s
        s.ivh = {int(k): list(v) for k, v in d.get("ivh", {}).items()}
        for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]:
            if k not in s.ivh: s.ivh[k] = []
        s.vfe_prices = d.get("v_px", [])
        return s

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

def run_vouchers_clean(state: TradingState, vstate: CleanVoucherState):
    orders = {}
    VFE = "VELVETFRUIT_EXTRACT"
    STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
    
    od_vfe = state.order_depths.get(VFE)
    spot = None
    if od_vfe and od_vfe.buy_orders and od_vfe.sell_orders:
        spot = (max(od_vfe.buy_orders.keys()) + min(od_vfe.sell_orders.keys())) / 2.0
    
    if spot is not None:
        vstate.vfe_prices.append(spot)
        if len(vstate.vfe_prices) > 50:
            vstate.vfe_prices.pop(0)
    elif vstate.vfe_prices:
        spot = vstate.vfe_prices[-1]
    else:
        return orders
        
    rv = 0.0
    if len(vstate.vfe_prices) > 10:
        rets = [(vstate.vfe_prices[i]/vstate.vfe_prices[i-1] - 1) for i in range(1, len(vstate.vfe_prices))]
        mu = sum(rets) / len(rets)
        var = sum((x - mu)**2 for x in rets) / (len(rets) - 1)
        rv = math.sqrt(var) * math.sqrt(2500000)

    T = max(5.0 - state.timestamp / 1_000_000.0, 0.01) / 250.0
    portfolio_delta = state.position.get(VFE, 0) * 1.0

    signals = {}
    fvs = {}
    
    for K in STRIKES:
        sym = f"VEV_{K}"
        od = state.order_depths.get(sym)
        if not od or not od.buy_orders or not od.sell_orders: continue
        
        mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2.0
        iv = cv_implied_vol(mid, spot, K, T)
        if iv is not None:
            vstate.ivh[K].append(iv)
            if len(vstate.ivh[K]) > 50:
                vstate.ivh[K].pop(0)
                
        hist = vstate.ivh[K]
        if len(hist) < 10: continue
            
        current_iv = hist[-1]
        roll_mean = sum(hist) / len(hist)
        roll_std = math.sqrt(sum((x - roll_mean)**2 for x in hist) / max(1, len(hist)-1)) if len(hist) > 1 else 0
        
        zscore = (current_iv - roll_mean) / (roll_std + 1e-6)
        vol_spread = rv - current_iv
        
        alpha = 0
        if zscore < -1.5: alpha += 1
        elif zscore > 1.5: alpha -= 1
        
        if vol_spread > 0.03: alpha += 1
        elif vol_spread < -0.03: alpha -= 1
            
        signals[K] = alpha
        fvs[K] = cv_bs_call(spot, K, T, roll_mean)
        
        pos = state.position.get(sym, 0)
        portfolio_delta += pos * cv_bs_delta(spot, K, T, current_iv)

    for K in STRIKES:
        sym = f"VEV_{K}"
        if K not in signals: continue
        
        od = state.order_depths.get(sym)
        pos = state.position.get(sym, 0)
        alpha = signals[K]
        fv = fvs[K]
        
        tb = 300 - pos
        ts = 300 + pos
        
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        
        new_orders = []
        
        if alpha > 0 and tb > 0:
            if ba <= fv + 0.5:
                q = min(15, tb, -od.sell_orders.get(ba, -15))
                new_orders.append(Order(sym, ba, q))
                tb -= q
        elif alpha < 0 and ts > 0:
            if bb >= fv - 0.5:
                q = min(15, ts, od.buy_orders.get(bb, 15))
                new_orders.append(Order(sym, bb, -q))
                ts -= q
                
        slack = 1 if K in [5000, 5100, 5200, 5300, 5400] else 3
        bid_px = math.floor(fv - slack)
        ask_px = math.ceil(fv + slack)
        
        if pos > 100: bid_px -= 1; ask_px -= 1
        if pos < -100: bid_px += 1; ask_px += 1
        
        bid_px = min(bid_px, bb + 1)
        ask_px = max(ask_px, ba - 1)
        if ask_px <= bid_px: ask_px = bid_px + 1
        
        if tb > 0: new_orders.append(Order(sym, bid_px, min(10, tb)))
        if ts > 0: new_orders.append(Order(sym, ask_px, -min(10, ts)))
        
        if new_orders: orders[sym] = new_orders

    if od_vfe and od_vfe.buy_orders and od_vfe.sell_orders:
        tb = 200 - state.position.get(VFE, 0)
        ts = 200 + state.position.get(VFE, 0)
        bb = max(od_vfe.buy_orders.keys())
        ba = min(od_vfe.sell_orders.keys())
        
        vfe_orders = []
        
        if portfolio_delta > 50 and ts > 0:
            q = min(ts, int(portfolio_delta/2))
            vfe_orders.append(Order(VFE, bb, -q))
            ts -= q
        elif portfolio_delta < -50 and tb > 0:
            q = min(tb, int(-portfolio_delta/2))
            vfe_orders.append(Order(VFE, ba, q))
            tb -= q
            
        if tb > 0: vfe_orders.append(Order(VFE, bb, min(tb, 10)))
        if ts > 0: vfe_orders.append(Order(VFE, ba, -min(ts, 10)))
        
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

        # 2) CLEAN VOUCHERS + VFE
        vstate = CleanVoucherState.load(raw.get("cv", {}))
        voucher_orders = run_vouchers_clean(state, vstate)
        for sym, ord_list in voucher_orders.items():
            if sym not in orders: orders[sym] = []
            orders[sym].extend(ord_list)
            
        raw["cv"] = vstate.to_dict()

        new_trader_data = json.dumps(raw)
        logger.flush(state, orders, conversions, new_trader_data)
        return orders, conversions, new_trader_data
"""

    with open("/home/mmaliar/prosperity4-tester-private/trader-logic/round-3/vouchers_clean.py", "w") as f:
        f.write("".join(hp_lines) + "\\n" + new_vouchers_code)
        
    print("Clean rewrite constructed to vouchers_clean.py")

build()
