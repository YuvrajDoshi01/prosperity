import sys
from pathlib import Path
from contextlib import contextmanager

sys.path.insert(0, '/home/mmaliar/prosperity4-tester-private/venv/lib/python3.14/site-packages')
from prosperity4bt.data import read_day_data, get_position_limit
from prosperity4bt.runner import prepare_state
from prosperity4bt.datamodel import TradingState, Order, Trade

class MockReader:
    @contextmanager
    def file(self, parts):
        fake_path = "/home/mmaliar/prosperity4-tester-private/fake-round2-data-with-more-volume"
        name = parts[-1] 
        p = Path(fake_path) / name
        if p.exists(): yield p
        else: yield None

data = read_day_data(MockReader(), 2, 6, True)
state = TradingState("", 0, {}, {}, {}, {}, {}, None)
prepare_state(state, data)

orders = [
    Order("INTARIAN_PEPPER_ROOT", 11009, 25),
    Order("INTARIAN_PEPPER_ROOT", 11010, 6),
    Order("INTARIAN_PEPPER_ROOT", 11008, 49)
]

for order in orders:
    print(f"\nMatching order {order.quantity} @ {order.price}")
    order_depth = state.order_depths[order.symbol]
    price_matches = sorted(price for price in order_depth.sell_orders.keys() if price <= order.price)
    print("  price_matches =", price_matches)
    for price in price_matches:
        lim = get_position_limit(order.symbol, None)
        pos = state.position.get(order.symbol, 0)
        max_buy = max(0, lim - pos)
        volume = min(order.quantity, abs(order_depth.sell_orders[price]), max_buy)
        print(f"  Evaluating price {price}: lim={lim}, pos={pos}, max_buy={max_buy}, volume={volume}, sell_order_vol={order_depth.sell_orders[price]}")
        
        if volume <= 0:
            continue
            
        print("  MATCHED!")
        state.position[order.symbol] = state.position.get(order.symbol, 0) + volume
        order_depth.sell_orders[price] += volume
        if order_depth.sell_orders[price] == 0:
            order_depth.sell_orders.pop(price)
        order.quantity -= volume
        
print("\nFinal position:", state.position)
