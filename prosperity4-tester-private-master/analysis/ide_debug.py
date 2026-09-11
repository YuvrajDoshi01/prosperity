import sys
import os
import importlib
from pathlib import Path

# 1. Setup paths to prioritize the installed package in the venv
repo_root = os.path.dirname(os.path.abspath(__file__))
venv_site_packages = os.path.join(repo_root, "venv", "lib", "python3.14", "site-packages")
if os.path.exists(venv_site_packages):
    sys.path.insert(0, venv_site_packages)

# 2. Setup the 'datamodel' shim required by the backtester package
try:
    from prosperity4bt import datamodel
    sys.modules["datamodel"] = datamodel
    
    from prosperity4bt.runner import run_backtest
    from prosperity4bt.file_reader import PackageResourcesReader
    from prosperity4bt.models import TradeMatchingMode
except ImportError:
    print("Error: Could not import prosperity4bt components. Ensure the package is installed in your venv.")
    sys.exit(1)

def main():
    # --- CONFIGURATION ---
    trader_file_path = Path(repo_root) / "trader-logic" / "round-3" / "428528.py"
    round_num = 3
    day_num = 2
    
    # 3. Load the algorithm
    sys.path.append(str(trader_file_path.parent))
    try:
        trader_module = importlib.import_module(trader_file_path.stem)
    except Exception as e:
        print(f"Error loading trader module: {e}")
        return

    # 4. Execute the backtest
    print(f"--- Starting IDE Debug: {trader_file_path.name} (Round {round_num}, Day {day_num}) ---")
    
    # Note: run_backtest in the library version takes specific positional/keyword arguments
    result = run_backtest(
        trader=trader_module.Trader(),
        file_reader=PackageResourcesReader(),
        round_num=round_num,
        day_num=day_num,
        print_output=True,
        trade_matching_mode=TradeMatchingMode.all,
        no_names=True,               # Matches the --no-names behavior in the CLI
        show_progress_bar=False,
        limits_override=None
    )

    print("\n--- Backtest Complete ---")
    # You can inspect 'result' in your IDE debugger here.
    # result.trades, result.activity_logs, etc. are available.

if __name__ == "__main__":
    main()
