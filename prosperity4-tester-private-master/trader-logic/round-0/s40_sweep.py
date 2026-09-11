"""
Sweep AR2_POST_WEIGHT and SKEW_GAMMA for s40_v2 architecture
"""
import subprocess, sys, re, json, os, tempfile, shutil

BASE = """import json
from datamodel import Order, TradingState

REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4
TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0
L2_OBI_SHIFT = 0.8
SKEW_GAMMA = {skew_gamma}
AR2_COEF_1 = -0.526
AR2_COEF_2 = -0.220
AR2_POST_WEIGHT = {ar2_weight}
CARRY_TRIGGER = 4
CARRY_DECAY = 0.7
CARRY_THRESHOLD = 0.5
CARRY_WIDE_OFFSET = 3
POSITION_LIMIT = 80
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40
TOMATO_POST_SKEW_THRESHOLD = 40
LIQUIDATION_WINDOW = 10
SPREAD_DIRECTION = {{5: +1, 6: -1, 7: +1, 8: -1, 9: -1}}

class Trader:
    def __init__(self):
        self.microprice_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0
        self.mid_history = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        saved = json.loads(state.traderData) if state.traderData else None
        if saved:
            self.microprice_history = saved.get("mp", [])
            self.trade_flow_history = saved.get("tf", [])
            self.emerald_limit_history = saved.get("el", [])
            self.prev_best_bid = saved.get("bb")
            self.carry_signal = saved.get("cs", 0.0)
            self.mid_history = saved.get("mh", [])

        result = {{}}
        conversions = 0

        if "EMERALDS" in state.order_depths:
            book = state.order_depths["EMERALDS"]
            if book.buy_orders and book.sell_orders:
                em_orders = []
                pos = state.position.get("EMERALDS", 0)
                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos
                bids = sorted(book.buy_orders.items(), reverse=True)
                asks = sorted(book.sell_orders.items())
                self.emerald_limit_history.append(abs(pos) == POSITION_LIMIT)
                if len(self.emerald_limit_history) > LIQUIDATION_WINDOW:
                    self.emerald_limit_history = self.emerald_limit_history[-LIQUIDATION_WINDOW:]
                at_limit_soft = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW
                                 and sum(self.emerald_limit_history) >= 5
                                 and self.emerald_limit_history[-1])
                at_limit_hard = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW
                                 and all(self.emerald_limit_history))
                max_buy_price = EMERALD_FV if pos <= EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV - 1
                min_sell_price = EMERALD_FV if pos >= -EMERALD_AGGRESSION_THRESHOLD else EMERALD_FV + 1
                for price, vol in asks:
                    if buy_capacity > 0 and price <= max_buy_price:
                        qty = min(buy_capacity, -vol)
                        em_orders.append(Order("EMERALDS", price, qty))
                        buy_capacity -= qty
                if buy_capacity > 0 and at_limit_hard:
                    qty = buy_capacity // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV, qty))
                    buy_capacity -= qty
                if buy_capacity > 0 and at_limit_soft:
                    qty = buy_capacity // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV - 2, qty))
                    buy_capacity -= qty
                if buy_capacity > 0:
                    em_orders.append(Order("EMERALDS", min(EMERALD_FV - 1, bids[0][0] + 1), buy_capacity))
                for price, vol in bids:
                    if sell_capacity > 0 and price >= min_sell_price:
                        qty = min(sell_capacity, vol)
                        em_orders.append(Order("EMERALDS", price, -qty))
                        sell_capacity -= qty
                if sell_capacity > 0 and at_limit_hard:
                    qty = sell_capacity // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV, -qty))
                    sell_capacity -= qty
                if sell_capacity > 0 and at_limit_soft:
                    qty = sell_capacity // 2
                    em_orders.append(Order("EMERALDS", EMERALD_FV + 2, -qty))
                    sell_capacity -= qty
                if sell_capacity > 0:
                    em_orders.append(Order("EMERALDS", max(EMERALD_FV + 1, asks[0][0] - 1), -sell_capacity))
                result["EMERALDS"] = em_orders

        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5
                spread = best_ask - best_bid
                sorted_bids = sorted(book.buy_orders.items(), reverse=True)
                sorted_asks = sorted(book.sell_orders.items())
                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())
                microprice = (best_bid + (total_bid_vol / (total_bid_vol + total_ask_vol))
                              * (best_ask - best_bid)
                              if (total_bid_vol + total_ask_vol) > 0 else mid)
                hist = self.microprice_history
                if len(hist) >= REGRESSION_LAGS:
                    hist = hist[1:]
                hist.append(microprice)
                self.microprice_history = hist
                if len(hist) == REGRESSION_LAGS:
                    fair_value = REGRESSION_INTERCEPT + sum(
                        c * x for c, x in zip(REGRESSION_COEFS, hist))
                else:
                    fair_value = microprice
                market_trades = state.market_trades.get("TOMATOES")
                if market_trades:
                    net_flow = sum(t.quantity if t.price >= mid else -t.quantity
                                  for t in market_trades)
                    self.trade_flow_history.append(net_flow)
                else:
                    self.trade_flow_history.append(0.0)
                if len(self.trade_flow_history) > TRADE_FLOW_WINDOW:
                    self.trade_flow_history = self.trade_flow_history[-TRADE_FLOW_WINDOW:]
                flow_signal = max(-1.0, min(1.0,
                    sum(self.trade_flow_history) / TRADE_FLOW_NORM))
                fair_value -= flow_signal * TRADE_FLOW_COEF
                bv2 = sorted_bids[1][1] if len(sorted_bids) > 1 else 0
                av2 = -sorted_asks[1][1] if len(sorted_asks) > 1 else 0
                if bv2 + av2 > 0:
                    l2_obi = (bv2 - av2) / (bv2 + av2)
                    fair_value += l2_obi * L2_OBI_SHIFT
                else:
                    obi = ((total_bid_vol - total_ask_vol) /
                           (total_bid_vol + total_ask_vol)
                           if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                    fair_value += obi * 0.5
                fair_value -= pos * SKEW_GAMMA
                take_fv_int = round(fair_value)
                self.mid_history.append(mid)
                if len(self.mid_history) > 3:
                    self.mid_history = self.mid_history[-3:]
                ar2_correction = 0.0
                if len(self.mid_history) >= 3:
                    dmid_1 = self.mid_history[-1] - self.mid_history[-2]
                    dmid_2 = self.mid_history[-2] - self.mid_history[-3]
                    ar2_correction = AR2_COEF_1 * dmid_1 + AR2_COEF_2 * dmid_2
                post_fv = fair_value + ar2_correction * AR2_POST_WEIGHT
                post_fv_int = round(post_fv)
                if self.prev_best_bid is not None:
                    bid_delta = best_bid - self.prev_best_bid
                    if bid_delta >= CARRY_TRIGGER:
                        self.carry_signal = -1.0
                    elif bid_delta <= -CARRY_TRIGGER:
                        self.carry_signal = 1.0
                    elif abs(bid_delta) <= 1:
                        self.carry_signal *= CARRY_DECAY
                self.prev_best_bid = best_bid
                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos
                for price, vol in sorted(book.sell_orders.items()):
                    if buy_capacity > 0 and price <= take_fv_int:
                        qty = min(buy_capacity, -vol)
                        tom_orders.append(Order("TOMATOES", price, qty))
                        buy_capacity -= qty
                for price, vol in sorted(book.buy_orders.items(), reverse=True):
                    if sell_capacity > 0 and price >= take_fv_int:
                        qty = min(sell_capacity, vol)
                        tom_orders.append(Order("TOMATOES", price, -qty))
                        sell_capacity -= qty
                posting_signal = self.carry_signal
                spread_int = int(spread)
                if spread_int in SPREAD_DIRECTION:
                    narrow_dir = SPREAD_DIRECTION[spread_int]
                    posting_signal += narrow_dir * 0.8
                if posting_signal > CARRY_THRESHOLD:
                    if buy_capacity > 0:
                        bid_price = min(post_fv_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))
                    if sell_capacity > 0:
                        if pos >= TOMATO_POST_SKEW_THRESHOLD:
                            ask_price = max(post_fv_int + 1, best_ask - 1)
                        else:
                            ask_price = max(post_fv_int + CARRY_WIDE_OFFSET, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))
                elif posting_signal < -CARRY_THRESHOLD:
                    if sell_capacity > 0:
                        ask_price = max(post_fv_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))
                    if buy_capacity > 0:
                        if pos <= -TOMATO_POST_SKEW_THRESHOLD:
                            bid_price = min(post_fv_int - 1, best_bid + 1)
                        else:
                            bid_price = min(post_fv_int - CARRY_WIDE_OFFSET, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))
                else:
                    if buy_capacity > 0:
                        bid_price = min(post_fv_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))
                    if sell_capacity > 0:
                        ask_price = max(post_fv_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))
                result["TOMATOES"] = tom_orders

        return result, conversions, json.dumps(
            {{"mp": self.microprice_history,
             "tf": self.trade_flow_history,
             "el": self.emerald_limit_history,
             "bb": self.prev_best_bid,
             "cs": round(self.carry_signal, 3),
             "mh": self.mid_history}},
            separators=(",", ":")
        )
"""

CONFIGS = [
    # AR2 weight sweep (skew=0.01)
    {"name": "ar2=0.0_skew=0.01", "ar2_weight": 0.0, "skew_gamma": 0.01},
    {"name": "ar2=0.1_skew=0.01", "ar2_weight": 0.1, "skew_gamma": 0.01},
    {"name": "ar2=0.2_skew=0.01", "ar2_weight": 0.2, "skew_gamma": 0.01},
    {"name": "ar2=0.3_skew=0.01", "ar2_weight": 0.3, "skew_gamma": 0.01},
    {"name": "ar2=0.5_skew=0.01", "ar2_weight": 0.5, "skew_gamma": 0.01},
    {"name": "ar2=0.7_skew=0.01", "ar2_weight": 0.7, "skew_gamma": 0.01},
    {"name": "ar2=1.0_skew=0.01", "ar2_weight": 1.0, "skew_gamma": 0.01},
    # Skew sweep (ar2=0.3)
    {"name": "ar2=0.3_skew=0.0", "ar2_weight": 0.3, "skew_gamma": 0.0},
    {"name": "ar2=0.3_skew=0.005", "ar2_weight": 0.3, "skew_gamma": 0.005},
    {"name": "ar2=0.3_skew=0.015", "ar2_weight": 0.3, "skew_gamma": 0.015},
    {"name": "ar2=0.3_skew=0.02", "ar2_weight": 0.3, "skew_gamma": 0.02},
    # No AR2, no skew (= s38 + narrow spread)
    {"name": "baseline_s38_narrow", "ar2_weight": 0.0, "skew_gamma": 0.0},
]

def run_backtest(script_path, day):
    cmd = [sys.executable, "-m", "prosperity4bt", script_path, f"0-{day}", "--no-out", "--no-progress"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    m = re.search(r"Total profit:\s*([\d,.\-]+)", out)
    if m:
        return int(m.group(1).replace(",", "").replace(".", "").strip())
    # Try matching individual lines
    total = 0
    for line in out.split('\n'):
        pm = re.search(r"(TOMATOES|EMERALDS):\s*([\d,.\-]+)", line)
        if pm:
            val = pm.group(2).replace(",", "")
            total += int(val)
    return total if total != 0 else None

tmpdir = "trader-logic/round-0/sim_tmp"
os.makedirs(tmpdir, exist_ok=True)

print(f"{'Config':<30} {'Day0':>8} {'Day-1':>8} {'Day-2':>8} {'Total':>8}")
print("=" * 70)

for cfg in CONFIGS:
    code = BASE.format(ar2_weight=cfg["ar2_weight"], skew_gamma=cfg["skew_gamma"])
    path = os.path.join(tmpdir, f"s40_{cfg['name']}.py")
    with open(path, 'w') as f:
        f.write(code)

    d0 = run_backtest(path, 0)
    d1 = run_backtest(path, -1)
    d2 = run_backtest(path, -2)
    d0v = d0 if d0 is not None else 0
    d1v = d1 if d1 is not None else 0
    d2v = d2 if d2 is not None else 0
    total = d0v + d1v + d2v
    print(f"{cfg['name']:<30} {d0v:>8,} {d1v:>8,} {d2v:>8,} {total:>8,}")

# Cleanup
shutil.rmtree(tmpdir, ignore_errors=True)
