import sys
import os
sys.path.insert(0, '/home/mmaliar/prosperity4-tester-private/venv/lib/python3.14/site-packages')

from prosperity4bt.data import BacktestData, get_position_limit
from prosperity4bt.runner import run_backtest, TradeMatchingMode
from prosperity4bt.file_reader import FileSystemReader
from prosperity4bt.datamodel import Order, TradingState

class MockTrader:
    def __init__(self):
        self.tick = 0
    def run(self, state: TradingState):
        print(f"--- TICK {self.tick} ---")
        print("Inventory:", state.position)
        orders = {}
        if self.tick == 0:
            orders["INTARIAN_PEPPER_ROOT"] = [
                Order("INTARIAN_PEPPER_ROOT", 11009, 25),
                Order("INTARIAN_PEPPER_ROOT", 11008, 55)
            ]
        self.tick += 1
        return orders, 1, ""

def main():
    reader = FileSystemReader("/home/mmaliar/prosperity4-tester-private/fake-round2-data-with-more-volume")
    trader = MockTrader()
    result = run_backtest(
        trader=trader,
        file_reader=reader,
        round_num=2,
        day_num=6,
        print_output=True,
        trade_matching_mode=TradeMatchingMode.worse,
        no_names=True,
        show_progress_bar=False,
    )

if __name__ == "__main__":
    main()
