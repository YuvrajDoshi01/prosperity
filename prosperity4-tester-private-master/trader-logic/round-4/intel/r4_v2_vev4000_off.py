"""r4_final_v2 with VEV_4000 deep-ITM MM DISABLED — to measure standalone contribution.

Also tests: WIDER edge (post at intrinsic±2 instead of ±1) — sometimes the MM bots
are queue-priority-sensitive even though they don't react to spread.
"""
import importlib.util
import sys

_spec = importlib.util.spec_from_file_location(
    "r4_final_v2",
    r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/r4_final_v2.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["r4_final_v2"] = _mod
_spec.loader.exec_module(_mod)

Order = _mod.Order

MODE = "size_up"  # "off" | "wider" | "size_up"

_orig = _mod.run_vouchers

def _patched(state, vstate):
    orders = _orig(state, vstate)
    sym = "VEV_4000"
    K = 4000
    od_v = state.order_depths.get(sym)
    od_ve = state.order_depths.get("VELVETFRUIT_EXTRACT")
    if od_v is None or od_ve is None: return orders
    if not od_ve.buy_orders or not od_ve.sell_orders: return orders
    spot = 0.5 * (max(od_ve.buy_orders) + min(od_ve.sell_orders))
    intrinsic = max(spot - K, 0.0)
    if intrinsic <= 0 or not od_v.buy_orders or not od_v.sell_orders: return orders

    # Strip prior VEV_4000 deep-ITM MM orders (within ±2 of intrinsic)
    if sym in orders:
        orders[sym] = [o for o in orders[sym] if abs(o.price - intrinsic) > 2]

    if MODE == "off":
        return orders  # No deep-ITM MM at all

    pos_v = state.position.get(sym, 0)
    existing_buy = sum(o.quantity for o in orders.get(sym, []) if o.quantity > 0)
    existing_sell = sum(-o.quantity for o in orders.get(sym, []) if o.quantity < 0)
    vbb = max(od_v.buy_orders); vba = min(od_v.sell_orders)

    if MODE == "wider":
        # Post at intrinsic±2 instead of ±1 (avoid clamp to vbb+1)
        DEEP_ITM_MM_SIZE = 30
        DEEP_ITM_POS_CAP = 100
        room_buy = DEEP_ITM_POS_CAP - pos_v - existing_buy
        if room_buy > 0:
            target_bid = int(round(intrinsic - 2))
            bid_px = max(1, min(target_bid, vbb + 1))
            if bid_px <= vba - 1:
                qty = min(DEEP_ITM_MM_SIZE, room_buy)
                orders.setdefault(sym, []).append(Order(sym, bid_px, qty))
        room_sell = DEEP_ITM_POS_CAP + pos_v - existing_sell
        if room_sell > 0:
            target_ask = int(round(intrinsic + 2))
            ask_px = max(target_ask, vba - 1)
            if ask_px >= vbb + 1:
                qty = min(DEEP_ITM_MM_SIZE, room_sell)
                orders.setdefault(sym, []).append(Order(sym, ask_px, -qty))
    elif MODE == "size_up":
        # Same intrinsic±1 but quote SIZE 100 instead of 30
        DEEP_ITM_MM_SIZE = 100
        DEEP_ITM_POS_CAP = 200
        room_buy = DEEP_ITM_POS_CAP - pos_v - existing_buy
        if room_buy > 0:
            target_bid = int(round(intrinsic - 1))
            bid_px = max(1, min(target_bid, vbb + 1))
            if bid_px <= vba - 1:
                qty = min(DEEP_ITM_MM_SIZE, room_buy)
                orders.setdefault(sym, []).append(Order(sym, bid_px, qty))
        room_sell = DEEP_ITM_POS_CAP + pos_v - existing_sell
        if room_sell > 0:
            target_ask = int(round(intrinsic + 1))
            ask_px = max(target_ask, vba - 1)
            if ask_px >= vbb + 1:
                qty = min(DEEP_ITM_MM_SIZE, room_sell)
                orders.setdefault(sym, []).append(Order(sym, ask_px, -qty))

    return orders

_mod.run_vouchers = _patched

class Trader(_mod.Trader):
    pass
