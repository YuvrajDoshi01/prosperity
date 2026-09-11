import sys
from pathlib import Path
from contextlib import contextmanager
sys.path.insert(0, '/home/mmaliar/prosperity4-tester-private/venv/lib/python3.14/site-packages')
from prosperity4bt.data import read_day_data

class MockReader:
    @contextmanager
    def file(self, parts):
        fake_path = "/home/mmaliar/prosperity4-tester-private/fake-round2-data-with-more-volume"
        name = parts[-1] 
        p = Path(fake_path) / name
        yield p

reader = MockReader()
data = read_day_data(reader, 2, 6, True)
print("Prices keys:", list(data.prices.keys())[:5])
if 0 in data.prices:
    print("PEPPER row:", data.prices[0]["INTARIAN_PEPPER_ROOT"])
