"""r4_final_v2 + aggressive VEV_4000 quoting variant.

Hypothesis: stepping bid from intrinsic-1 → intrinsic+5 (and ask from intrinsic+1 →
intrinsic-5) inside the M14/M38 ±10.5 quote pair. Mark 38 sells at intrinsic-10.5
(qty ~10/tick). If we bid intrinsic-5, we sit BELOW Mark 14's intrinsic+10.5 ask
but ABOVE Mark 38's intrinsic-10.5 bid — meaning Mark 38's SELL orders cross OUR
bid at intrinsic-5 → we buy at intrinsic-5, capturing +5 vs intrinsic.

Variants controlled by VEV4000_AGGRO_OFFSET:
  0 = standard (intrinsic±1) [baseline]
  5 = intrinsic±5 (mid-aggressive)
  9 = intrinsic±9 (max-aggressive, just inside M14/M38)
"""
# Copy v2 verbatim then patch VEV_4000-specific block
import importlib.util
import sys

# Load r4_final_v2 module
_spec = importlib.util.spec_from_file_location(
    "r4_final_v2",
    r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/r4_final_v2.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["r4_final_v2"] = _mod
_spec.loader.exec_module(_mod)

# Re-export key symbols
Order = _mod.Order
TradingState = _mod.TradingState
ProsperityEncoder = _mod.ProsperityEncoder

# Configuration knob (override by symbol substitution at module-load time)
VEV4000_AGGRO_OFFSET = 9  # change this to test 0/3/5/7/9

# Override DEEP_ITM_MM logic: replace run_vouchers wrapper that mutates VEV_4000 quoting
_original_run_vouchers = _mod.run_vouchers

def _patched_run_vouchers(state, vstate):
    orders = _original_run_vouchers(state, vstate)
    # Strip existing VEV_4000 deep-ITM MM orders (those are at intrinsic±1)
    # Replace with intrinsic±OFFSET
    sym = "VEV_4000"
    K = 4000
    DEEP_ITM_MM_SIZE = 30
    DEEP_ITM_POS_CAP = 100

    od_v = state.order_depths.get(sym)
    od_ve = state.order_depths.get("VELVETFRUIT_EXTRACT")
    if od_v is None or od_ve is None: return orders
    if not od_ve.buy_orders or not od_ve.sell_orders: return orders
    spot = 0.5 * (max(od_ve.buy_orders) + min(od_ve.sell_orders))
    intrinsic = max(spot - K, 0.0)
    if intrinsic <= 0: return orders

    # Strip prior VEV_4000 deep-ITM MM orders that are within ±2 of intrinsic
    if sym in orders:
        orders[sym] = [
            o for o in orders[sym]
            if abs(o.price - intrinsic) > 2  # keep intrinsic arb (uses INTRINSIC_EDGE=2) and BS-take
        ]

    pos_v = state.position.get(sym, 0)
    existing_buy = sum(o.quantity for o in orders.get(sym, []) if o.quantity > 0)
    existing_sell = sum(-o.quantity for o in orders.get(sym, []) if o.quantity < 0)
    if not od_v.buy_orders or not od_v.sell_orders: return orders
    vbb = max(od_v.buy_orders); vba = min(od_v.sell_orders)

    room_buy = DEEP_ITM_POS_CAP - pos_v - existing_buy
    if room_buy > 0:
        # Step closer to intrinsic — i.e. higher bid
        target_bid = int(round(intrinsic - VEV4000_AGGRO_OFFSET))
        bid_px = max(1, min(target_bid, vba - 1))
        if bid_px > vbb:  # must be strictly above best bid (or join, but go inside)
            qty = min(DEEP_ITM_MM_SIZE, room_buy)
            orders.setdefault(sym, []).append(Order(sym, bid_px, qty))

    room_sell = DEEP_ITM_POS_CAP + pos_v - existing_sell
    if room_sell > 0:
        target_ask = int(round(intrinsic + VEV4000_AGGRO_OFFSET))
        ask_px = min(target_ask, max(target_ask, vbb + 1))
        ask_px = max(ask_px, vbb + 1)
        if ask_px < vba:  # must be inside spread
            qty = min(DEEP_ITM_MM_SIZE, room_sell)
            orders.setdefault(sym, []).append(Order(sym, ask_px, -qty))

    return orders


_mod.run_vouchers = _patched_run_vouchers


# Re-export Trader class so backtester picks it up
class Trader(_mod.Trader):
    pass
