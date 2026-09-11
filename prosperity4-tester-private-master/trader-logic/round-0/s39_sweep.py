"""Sweep VWAP-based FV variants vs microprice regression on day 0."""
import subprocess, sys, re, os

BASE = '/Users/y0d046w/Desktop/prosperity4-tester-private'

# Template: s36 with FV replaced
TEMPLATE = '''import json
from datamodel import Order, TradingState

TRADE_FLOW_COEF = 1.5
TRADE_FLOW_WINDOW = 5
TRADE_FLOW_NORM = 15.0
OBI_SHIFT = {obi_shift}
L2_OBI_SHIFT = {l2_obi_shift}
CARRY_TRIGGER = 4
CARRY_DECAY = 0.7
CARRY_THRESHOLD = 0.5
CARRY_WIDE_OFFSET = 3
POSITION_LIMIT = 80
EMERALD_FV = 10000
EMERALD_AGGRESSION_THRESHOLD = 40
TOMATO_POST_SKEW_THRESHOLD = 40
TERMINAL_TIMESTAMP = 900000
TERMINAL_POSITION_THRESHOLD = 28
LIQUIDATION_WINDOW = 10
REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]
REGRESSION_INTERCEPT = 2.208667
REGRESSION_LAGS = 4
FV_MODE = "{fv_mode}"
VWAP_WEIGHT = {vwap_weight}
SKEW_GAMMA = {skew_gamma}

class Trader:
    def __init__(self):
        self.microprice_history = []
        self.trade_flow_history = []
        self.emerald_limit_history = []
        self.prev_best_bid = None
        self.carry_signal = 0.0
        self.prev_mid = None
        self.dmid_history = []

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
            self.prev_mid = saved.get("pm")
            self.dmid_history = saved.get("dh", [])

        result = {{}}
        conversions = 0

        # EMERALDS (identical to s36)
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
                at_limit_soft = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW and sum(self.emerald_limit_history) >= 5 and self.emerald_limit_history[-1])
                at_limit_hard = (len(self.emerald_limit_history) == LIQUIDATION_WINDOW and all(self.emerald_limit_history))
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

        # TOMATOES
        if "TOMATOES" in state.order_depths:
            book = state.order_depths["TOMATOES"]
            if book.buy_orders and book.sell_orders:
                tom_orders = []
                best_bid = max(book.buy_orders)
                best_ask = min(book.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                mid = (best_bid + best_ask) * 0.5
                sorted_bids = sorted(book.buy_orders.items(), reverse=True)
                sorted_asks = sorted(book.sell_orders.items())
                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())

                # --- FV computation based on mode ---
                if FV_MODE == "vwap":
                    num = 0.0
                    den = 0.0
                    for p, v in sorted_bids:
                        num += p * v
                        den += v
                    for p, v in sorted_asks:
                        num += p * (-v)
                        den += (-v)
                    vwap = num / den if den > 0 else mid
                    fair_value = VWAP_WEIGHT * vwap + (1 - VWAP_WEIGHT) * mid
                elif FV_MODE == "vwap_ar2":
                    num = 0.0
                    den = 0.0
                    for p, v in sorted_bids:
                        num += p * v
                        den += v
                    for p, v in sorted_asks:
                        num += p * (-v)
                        den += (-v)
                    vwap = num / den if den > 0 else mid
                    dmid = mid - self.prev_mid if self.prev_mid is not None else 0.0
                    self.dmid_history.append(dmid)
                    if len(self.dmid_history) > 2:
                        self.dmid_history = self.dmid_history[-2:]
                    self.prev_mid = mid
                    ar2_pred = 0.0
                    if len(self.dmid_history) >= 2:
                        ar2_pred = -0.526 * self.dmid_history[-1] - 0.220 * self.dmid_history[-2]
                    fair_value = VWAP_WEIGHT * vwap + (1 - VWAP_WEIGHT) * mid + ar2_pred * 0.15
                elif FV_MODE == "microprice_reg":
                    microprice = (best_bid + (total_bid_vol / (total_bid_vol + total_ask_vol)) * (best_ask - best_bid) if (total_bid_vol + total_ask_vol) > 0 else mid)
                    hist = self.microprice_history
                    if len(hist) >= REGRESSION_LAGS:
                        hist = hist[1:]
                    hist.append(microprice)
                    self.microprice_history = hist
                    if len(hist) == REGRESSION_LAGS:
                        fair_value = REGRESSION_INTERCEPT + sum(c * x for c, x in zip(REGRESSION_COEFS, hist))
                    else:
                        fair_value = microprice
                else:
                    fair_value = mid

                # Trade flow
                market_trades = state.market_trades.get("TOMATOES")
                if market_trades:
                    net_flow = sum(t.quantity if t.price >= mid else -t.quantity for t in market_trades)
                    self.trade_flow_history.append(net_flow)
                else:
                    self.trade_flow_history.append(0.0)
                if len(self.trade_flow_history) > TRADE_FLOW_WINDOW:
                    self.trade_flow_history = self.trade_flow_history[-TRADE_FLOW_WINDOW:]
                flow_signal = max(-1.0, min(1.0, sum(self.trade_flow_history) / TRADE_FLOW_NORM))
                fair_value -= flow_signal * TRADE_FLOW_COEF

                # OBI/L2 OBI
                if L2_OBI_SHIFT > 0:
                    bv2 = sorted_bids[1][1] if len(sorted_bids) > 1 else 0
                    av2 = -sorted_asks[1][1] if len(sorted_asks) > 1 else 0
                    if bv2 + av2 > 0:
                        l2_obi = (bv2 - av2) / (bv2 + av2)
                        fair_value += l2_obi * L2_OBI_SHIFT
                    else:
                        obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol) if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                        fair_value += obi * 0.5
                elif OBI_SHIFT > 0:
                    obi = ((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol) if (total_bid_vol + total_ask_vol) > 0 else 0.0)
                    fair_value += obi * OBI_SHIFT

                # Position skew (trailing stop ramp)
                if SKEW_GAMMA > 0:
                    fair_value -= pos * SKEW_GAMMA

                fair_value_int = round(fair_value)

                # Carry
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
                    if buy_capacity > 0 and price <= fair_value_int:
                        qty = min(buy_capacity, -vol)
                        tom_orders.append(Order("TOMATOES", price, qty))
                        buy_capacity -= qty
                for price, vol in sorted(book.buy_orders.items(), reverse=True):
                    if sell_capacity > 0 and price >= fair_value_int:
                        qty = min(sell_capacity, vol)
                        tom_orders.append(Order("TOMATOES", price, -qty))
                        sell_capacity -= qty

                if state.timestamp > TERMINAL_TIMESTAMP and abs(pos) > TERMINAL_POSITION_THRESHOLD:
                    if pos > 0 and sell_capacity > 0:
                        for price, vol in sorted(book.buy_orders.items(), reverse=True):
                            if sell_capacity > 0 and pos > 0:
                                qty = min(sell_capacity, vol, pos)
                                tom_orders.append(Order("TOMATOES", price, -qty))
                                sell_capacity -= qty
                                pos -= qty
                    elif pos < 0 and buy_capacity > 0:
                        for price, vol in sorted(book.sell_orders.items()):
                            if buy_capacity > 0 and pos < 0:
                                qty = min(buy_capacity, -vol, -pos)
                                tom_orders.append(Order("TOMATOES", price, qty))
                                buy_capacity -= qty
                                pos += qty

                if self.carry_signal > CARRY_THRESHOLD:
                    if buy_capacity > 0:
                        bp = min(fair_value_int - 1, best_bid + 1)
                        bp = min(bp, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bp, buy_capacity))
                    if sell_capacity > 0:
                        if pos >= TOMATO_POST_SKEW_THRESHOLD:
                            ap = max(fair_value_int + 1, best_ask - 1)
                        else:
                            ap = max(fair_value_int + CARRY_WIDE_OFFSET, best_ask - 1)
                        ap = max(ap, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ap, -sell_capacity))
                elif self.carry_signal < -CARRY_THRESHOLD:
                    if sell_capacity > 0:
                        ap = max(fair_value_int + 1, best_ask - 1)
                        ap = max(ap, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ap, -sell_capacity))
                    if buy_capacity > 0:
                        if pos <= -TOMATO_POST_SKEW_THRESHOLD:
                            bp = min(fair_value_int - 1, best_bid + 1)
                        else:
                            bp = min(fair_value_int - CARRY_WIDE_OFFSET, best_bid + 1)
                        bp = min(bp, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bp, buy_capacity))
                else:
                    if buy_capacity > 0:
                        bp = min(fair_value_int - 1, best_bid + 1)
                        bp = min(bp, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bp, buy_capacity))
                    if sell_capacity > 0:
                        ap = max(fair_value_int + 1, best_ask - 1)
                        ap = max(ap, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ap, -sell_capacity))

                result["TOMATOES"] = tom_orders

        return result, conversions, json.dumps(
            {{"mp": self.microprice_history, "tf": self.trade_flow_history, "el": self.emerald_limit_history,
              "bb": self.prev_best_bid, "cs": round(self.carry_signal, 3),
              "pm": self.prev_mid, "dh": [round(x,4) for x in self.dmid_history]}},
            separators=(",",":")
        )
'''

configs = [
    # Baselines
    ("s36_microprice_reg", "microprice_reg", 0.0, 0.5, 0.0, 0.0),
    ("s38_microprice_l2obi", "microprice_reg", 0.0, 0.0, 0.8, 0.0),

    # VWAP variants
    ("vwap_pure", "vwap", 1.0, 0.0, 0.0, 0.0),
    ("vwap_0.85", "vwap", 0.85, 0.0, 0.0, 0.0),
    ("vwap_0.85_l2obi", "vwap", 0.85, 0.0, 0.8, 0.0),
    ("vwap_0.85_obi0.5", "vwap", 0.85, 0.5, 0.0, 0.0),
    ("vwap_ar2_l2obi", "vwap_ar2", 0.85, 0.0, 0.8, 0.0),

    # Skew variants (with best FV)
    ("s38_l2obi_skew0.01", "microprice_reg", 0.0, 0.0, 0.8, 0.01),
    ("s38_l2obi_skew0.02", "microprice_reg", 0.0, 0.0, 0.8, 0.02),
    ("s38_l2obi_skew0.05", "microprice_reg", 0.0, 0.0, 0.8, 0.05),
    ("vwap_l2obi_skew0.01", "vwap", 0.85, 0.0, 0.8, 0.01),
    ("vwap_l2obi_skew0.02", "vwap", 0.85, 0.0, 0.8, 0.02),

    # No terminal flatten
    # (handled by TERMINAL_TIMESTAMP > 900000, effectively always)
]

results = []
for name, fv_mode, vwap_w, obi_s, l2_s, gamma in configs:
    code = TEMPLATE.format(fv_mode=fv_mode, vwap_weight=vwap_w,
                           obi_shift=obi_s, l2_obi_shift=l2_s, skew_gamma=gamma)
    tmp = os.path.join(BASE, 'trader-logic/round-0/s39_tmp.py')
    with open(tmp, 'w') as f:
        f.write(code)

    cmd = f"python3 -m prosperity4bt {tmp} 0--0 --no-out --no-progress"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=BASE)
    out = r.stdout + r.stderr

    m = re.search(r'Total profit:\s*([\d,.-]+)', out)
    if m:
        profit = int(m.group(1).replace(',', ''))
        results.append((name, profit))
        print(f"{name:30s} → day 0: {profit:,}")
    else:
        print(f"{name:30s} → FAILED: {out[:200]}")

os.remove(os.path.join(BASE, 'trader-logic/round-0/s39_tmp.py'))

print(f"\n{'='*60}")
print(f"{'RANKING':^60}")
print(f"{'='*60}")
for name, profit in sorted(results, key=lambda x: -x[1]):
    delta = profit - 2626  # vs s36
    print(f"  {name:30s} {profit:>6,}  ({delta:>+5})")
