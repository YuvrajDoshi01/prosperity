import sys
from pathlib import Path
from contextlib import contextmanager
sys.path.insert(0, '/home/mmaliar/prosperity4-tester-private/venv/lib/python3.14/site-packages')

from prosperity4bt.file_reader import FileSystemReader
from prosperity4bt.data import read_day_data
from prosperity4bt.runner import prepare_state
from prosperity4bt.datamodel import TradingState

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

pepper_depth = state.order_depths["INTARIAN_PEPPER_ROOT"]
print("PEPPER sell orders:", pepper_depth.sell_orders)
print("PEPPER buy orders:", pepper_depth.buy_orders)
