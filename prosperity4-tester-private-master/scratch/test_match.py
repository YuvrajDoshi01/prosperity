from prosperity4bt.datamodel import Order, OrderDepth, TradingState, Symbol, Trade
from prosperity4bt.data import BacktestData, PriceRow, create_backtest_data
from prosperity4bt.runner import prepare_state, enforce_limits, match_orders
from prosperity4bt.models import SandboxLogRow, BacktestResult, TradeMatchingMode
import sys

def main():
    product = "INTARIAN_PEPPER_ROOT"
    
    # Create mock BacktestData
    price_row = PriceRow(
        day=6, timestamp=0, product=product,
        bid_prices=[10994, 10993], bid_volumes=[9, 2],
        ask_prices=[11009, 11010], ask_volumes=[25, 6],
        mid_price=11001.5, profit_loss=0.0
    )
    data = create_backtest_data(6, 0, [price_row], [], [])
    
    state = TradingState(
        traderData="", timestamp=0, listings={}, order_depths={},
        own_trades={}, market_trades={}, position={}, observations=None
    )
    
    prepare_state(state, data)
    
    orders = {
        product: [
            Order(product, 11009, 25),
            Order(product, 11008, 55)
        ]
    }
    
    sandbox_row = SandboxLogRow(timestamp=0, sandbox_log="", lambda_log="")
    result = BacktestResult(round_num=6, day_num=0, sandbox_logs=[], activity_logs=[], trades=[])
    
    # Enforce limits
    enforce_limits(state, data, orders, sandbox_row)
    print("Sandbox Log after limits:", sandbox_row.sandbox_log)
    print("Orders after limits:", orders)
    
    # Match orders
    match_orders(state, data, orders, result, TradeMatchingMode.worse)
    print("Trades matched:", result.trades)
    print("Position after match:", state.position)

if __name__ == "__main__":
    main()
