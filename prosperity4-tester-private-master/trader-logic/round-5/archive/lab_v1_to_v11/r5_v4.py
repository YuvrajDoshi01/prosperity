"""r5_v4.py -- IMC Prosperity 4 Round 5: Hedged basket arb + no generic MM.

Key fix from v3: PEBBLES positions were wildly unhedged. The basket arb
must keep NET basket position near zero. When we buy one PEBBLES product,
we must sell others, or at minimum NOT accumulate one-sided inventory.

Strategy:
  PEBBLES: Basket-neutral MM. FV = basket-implied. Position skew forces
    inventory back toward 0. No aggressive takes (they accumulate direction).
    Quote on BOTH sides always, let taker fills drive PnL.
  ALL OTHER PRODUCTS: No trading (v2 showed generic MM loses on drifters).
"""

import json
from datamodel import TradingState, Order, OrderDepth, Symbol

LIMIT = 80

PEBBLES = ['PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL']
PEBBLES_BASKET_SUM = 50000

# Tuning
QUOTE_SIZE = 15
BASE_OFFSET = 2          # Base offset from basket FV
SKEW_PER_LOT = 0.05      # Price skew per unit of inventory (cents/lot)
MAX_POS = 60              # Hard position cap per product


def get_mid(od: OrderDepth) -> float:
    if not od.buy_orders or not od.sell_orders:
        return 0
    return (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2


class Trader:

    def run(self, state: TradingState):
        result = {}
        conversions = 0

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

                # Position-aware skew: when long, pull FV down (want to sell);
                # when short, pull FV up (want to buy)
                skew = -pos * SKEW_PER_LOT  # negative pos -> positive skew -> higher FV -> buy more
                skewed_fv = fv_int + int(round(skew))

                bid_offset = BASE_OFFSET
                ask_offset = BASE_OFFSET

                # Extra widening at extreme positions
                if pos > MAX_POS // 2:
                    bid_offset += 1
                if pos > MAX_POS:
                    bid_offset += 2
                if pos < -MAX_POS // 2:
                    ask_offset += 1
                if pos < -MAX_POS:
                    ask_offset += 2

                bid_price = skewed_fv - bid_offset
                ask_price = skewed_fv + ask_offset

                bid_qty = min(QUOTE_SIZE, LIMIT - pos)
                ask_qty = min(QUOTE_SIZE, LIMIT + pos)

                if bid_qty > 0 and pos < MAX_POS:
                    orders.append(Order(p, bid_price, bid_qty))
                if ask_qty > 0 and pos > -MAX_POS:
                    orders.append(Order(p, ask_price, -ask_qty))

                result[p] = orders

        return result, conversions, ""
