"""r5_v3.py -- IMC Prosperity 4 Round 5: PEBBLES basket arb + cautious MM.

Key insight from v1/v2: 50 products all drift 1000-5000pts/day. Any MM
that takes directional inventory gets destroyed by drift. Only trade
products where we have a structural FV edge.

Strategy:
  PEBBLES: Basket arb (sum=50000 constraint). Take + Make around basket FV.
  SNACKPACK: Pair-implied FV, very cautious (tight inventory, no takes).
  Everything else: NO TRADING. Zero exposure to directional drift.
"""

import json
import math
from datamodel import TradingState, Order, OrderDepth, Symbol

LIMIT = 80

PEBBLES = ['PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL']
PEBBLES_BASKET_SUM = 50000

SNACKPACK = ['SNACKPACK_CHOCOLATE', 'SNACKPACK_PISTACHIO', 'SNACKPACK_RASPBERRY',
             'SNACKPACK_STRAWBERRY', 'SNACKPACK_VANILLA']
SNACK_PAIRS = [
    ('SNACKPACK_CHOCOLATE', 'SNACKPACK_VANILLA'),
    ('SNACKPACK_RASPBERRY', 'SNACKPACK_STRAWBERRY'),
]

SNACK_PAIR_WINDOW = 200

# PEBBLES tuning
PEB_TAKE_EDGE = 1        # Take when ask < fv - 1 (or bid > fv + 1)
PEB_QUOTE_SIZE = 20
PEB_MM_OFFSET = 2

# SNACKPACK tuning
SNACK_QUOTE_SIZE = 5
SNACK_MM_OFFSET = 4      # Wide offset to avoid adverse selection on drifting pairs

SOFT_LIMIT = 50
HARD_LIMIT = 70


def get_mid(od: OrderDepth) -> float:
    if not od.buy_orders or not od.sell_orders:
        return 0
    return (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2


class Trader:

    def __init__(self):
        self.snack_pair_sums = {}

    def run(self, state: TradingState):
        result = {}
        conversions = 0

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except:
                td = {}
        self.snack_pair_sums = td.get('sp', {})

        # ==================== PEBBLES BASKET ARB ====================
        pebbles_mids = {}
        for p in PEBBLES:
            if p in state.order_depths:
                pebbles_mids[p] = get_mid(state.order_depths[p])

        if len(pebbles_mids) == 5:
            total_mid = sum(pebbles_mids.values())

            for p in PEBBLES:
                od = state.order_depths[p]
                if not od.buy_orders or not od.sell_orders:
                    continue

                other_sum = total_mid - pebbles_mids[p]
                basket_fv = PEBBLES_BASKET_SUM - other_sum
                fv_int = int(round(basket_fv))

                pos = state.position.get(p, 0)
                orders = []
                best_bid = max(od.buy_orders.keys())
                best_ask = min(od.sell_orders.keys())

                # TAKE: aggressive crossing when mispriced vs basket FV
                # Buy underpriced asks
                for ask_price in sorted(od.sell_orders.keys()):
                    if ask_price >= fv_int - PEB_TAKE_EDGE:
                        break
                    ask_vol = abs(od.sell_orders[ask_price])
                    buy_qty = min(ask_vol, LIMIT - pos)
                    if buy_qty > 0:
                        orders.append(Order(p, ask_price, buy_qty))
                        pos += buy_qty

                # Sell overpriced bids
                for bid_price in sorted(od.buy_orders.keys(), reverse=True):
                    if bid_price <= fv_int + PEB_TAKE_EDGE:
                        break
                    bid_vol = od.buy_orders[bid_price]
                    sell_qty = min(bid_vol, LIMIT + pos)
                    if sell_qty > 0:
                        orders.append(Order(p, bid_price, -sell_qty))
                        pos -= sell_qty

                # MAKE: passive quotes around basket FV
                bid_offset = PEB_MM_OFFSET
                ask_offset = PEB_MM_OFFSET
                if pos > SOFT_LIMIT:
                    bid_offset += 2
                if pos < -SOFT_LIMIT:
                    ask_offset += 2

                bid_price = fv_int - bid_offset
                bid_qty = min(PEB_QUOTE_SIZE, LIMIT - pos)
                if bid_qty > 0 and pos < HARD_LIMIT:
                    orders.append(Order(p, bid_price, bid_qty))

                ask_price = fv_int + ask_offset
                ask_qty = min(PEB_QUOTE_SIZE, LIMIT + pos)
                if ask_qty > 0 and pos > -HARD_LIMIT:
                    orders.append(Order(p, ask_price, -ask_qty))

                result[p] = orders

        # ==================== SNACKPACK PAIR MM ====================
        snack_mids = {}
        for p in SNACKPACK:
            if p in state.order_depths:
                snack_mids[p] = get_mid(state.order_depths[p])

        for p1, p2 in SNACK_PAIRS:
            key = f"{p1}_{p2}"
            if p1 in snack_mids and p2 in snack_mids:
                pair_sum = snack_mids[p1] + snack_mids[p2]
                if key not in self.snack_pair_sums:
                    self.snack_pair_sums[key] = []
                self.snack_pair_sums[key].append(pair_sum)
                if len(self.snack_pair_sums[key]) > SNACK_PAIR_WINDOW:
                    self.snack_pair_sums[key] = self.snack_pair_sums[key][-SNACK_PAIR_WINDOW:]

        snack_fvs = {}
        for p1, p2 in SNACK_PAIRS:
            key = f"{p1}_{p2}"
            if key in self.snack_pair_sums and len(self.snack_pair_sums[key]) >= 30:
                mean_sum = sum(self.snack_pair_sums[key]) / len(self.snack_pair_sums[key])
                if p2 in snack_mids:
                    snack_fvs.setdefault(p1, []).append(mean_sum - snack_mids[p2])
                if p1 in snack_mids:
                    snack_fvs.setdefault(p2, []).append(mean_sum - snack_mids[p1])

        for p in SNACKPACK:
            if p in state.order_depths and p not in result:
                od = state.order_depths[p]
                if not od.buy_orders or not od.sell_orders:
                    continue

                if p in snack_fvs and snack_fvs[p]:
                    pair_fv = sum(snack_fvs[p]) / len(snack_fvs[p])
                    mid = get_mid(od)
                    fv = 0.3 * pair_fv + 0.7 * mid  # Lean toward market, pair is hint
                else:
                    fv = get_mid(od)

                pos = state.position.get(p, 0)
                fv_int = int(round(fv))
                orders = []

                bid_offset = SNACK_MM_OFFSET
                ask_offset = SNACK_MM_OFFSET
                if pos > 30:
                    bid_offset += 2
                if pos < -30:
                    ask_offset += 2

                bid_qty = min(SNACK_QUOTE_SIZE, LIMIT - pos)
                if bid_qty > 0 and pos < 50:
                    orders.append(Order(p, fv_int - bid_offset, bid_qty))

                ask_qty = min(SNACK_QUOTE_SIZE, LIMIT + pos)
                if ask_qty > 0 and pos > -50:
                    orders.append(Order(p, fv_int + ask_offset, -ask_qty))

                result[p] = orders

        # Save state
        new_td = {'sp': self.snack_pair_sums}
        try:
            trader_data = json.dumps(new_td)
            if len(trader_data) > 49000:
                for key in self.snack_pair_sums:
                    self.snack_pair_sums[key] = self.snack_pair_sums[key][-50:]
                trader_data = json.dumps({'sp': self.snack_pair_sums})
        except:
            trader_data = ""

        return result, conversions, trader_data
