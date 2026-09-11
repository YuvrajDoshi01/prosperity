import sys
from pathlib import Path
from contextlib import contextmanager
sys.path.insert(0, '/home/mmaliar/prosperity4-tester-private/venv/lib/python3.14/site-packages')
sys.path.insert(0, '/home/mmaliar/prosperity4-tester-private/trader-logic/round-2')

import prosperity4bt.datamodel as model
sys.modules['datamodel'] = model
try18 = __import__("try18-debug")

from prosperity4bt.data import read_day_data
from prosperity4bt.runner import prepare_state, match_orders
from prosperity4bt.datamodel import TradingState, Observation
from prosperity4bt.models import BacktestResult, TradeMatchingMode

class MockReader:
    @contextmanager
    def file(self, parts):
        fake_path = "/home/mmaliar/prosperity4-tester-private/fake-round2-data-with-more-volume"
        name = parts[-1] 
        p = Path(fake_path) / name
        if p.exists(): yield p
        else: yield None

reader = MockReader()
data = read_day_data(reader, 2, 6, True)
state = TradingState("", 0, {}, {}, {}, {}, {}, Observation({}, {}))
prepare_state(state, data)

trader = try18.Trader()
orders, _, _ = trader.run(state)
print("Keys in orders:", list(orders.keys()))
print("data.products:", data.products)

for p in data.products:
    print(f"Checking product: {p}")
    prod_orders = orders.get(p, [])
    print(f"Orders for {p}: {prod_orders}")

result = BacktestResult(round_num=2, day_num=6, sandbox_logs=[], activity_logs=[], trades=[])

# Print what market trades we have
mts = data.trades.get(0, {})
print("market_trades:", mts)

# Let's call match_orders and see what it does
match_orders(state, data, orders, result, TradeMatchingMode.worse)
print("Trades after match:", result.trades)

