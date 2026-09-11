import sys
sys.path.insert(0, '/home/mmaliar/prosperity4-tester-private/venv/lib/python3.14/site-packages')
import inspect
from prosperity4bt.runner import match_orders, match_order, match_buy_order

print(inspect.getsource(match_buy_order))
