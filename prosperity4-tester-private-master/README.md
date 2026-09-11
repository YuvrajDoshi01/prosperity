# IMC Prosperity 4 Backtester

Python-based backtester for the [IMC Prosperity 4 challenge](https://prosperity.imc.com/), forked from [jmerle/imc-prosperity-3-backtester](https://github.com/jmerle/imc-prosperity-3-backtester) and restructured in an OOP style.

**Current state:** Round 1 (tutorial round complete, competition round ongoing).
**Best website score:** **10,624.84** (r1_v4 — see [trader-logic/round-1/](trader-logic/round-1/)).

## Usage

```bash
# Set PYTHONPATH (Windows PowerShell)
$env:PYTHONPATH="<path>\imc-prosperity-4-backtester\prosperity4bt"

# Run on all days in a round
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1

# Run specific round-day
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1--1

# Full 10k-tick day
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 10000

# Tutorial scoring simulation (1k ticks, run() every tick like website)
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 1000

# Common flags
#   --ticks N                          max ticks to simulate
#   --match-trades {all|worse|none}    order match mode (default: all)
#   --no-out                           skip saving .log file
#   --no-progress                      hide progress bars
#   --print                            show trader stdout
```

Output logs go to `backtests/<timestamp>.log`. Website submission replay ZIPs live in `run-logs/round-N/<id>/`.

## Architecture

```
BackTester              main controller, iterates rounds/days
  └── TestRunner        single-day simulation
        ├── DataReader          loads CSVs (prosperity4bt/resources/round{N}/)
        ├── Trader.run()        user strategy (trader-logic/round-N/*.py)
        ├── ActivityLogger      records tick state
        └── OrderMatchMaker     fills orders against market book
  └── ResultMerger       combines per-day results
  └── OutputFileWriter   writes consolidated .log
```

Per-tick sequence:
1. Build `TradingState` from the loaded order-book snapshot
2. Call `Trader.run(state)` — returns `(orders, conversions, trader_data)`
3. Enforce position limits (all-or-nothing per product per side)
4. Match orders against the book, then against market-trades
5. Log activity + fills

## Trader Contract

```python
from datamodel import TradingState, Order

class Trader:
    def bid(self):        # Round 1+ manual auction (any int)
        return 15

    def run(self, state: TradingState):
        orders = {}       # dict[Symbol, list[Order]]
        conversions = 0   # int (Round 2+ conversions)
        trader_data = ""  # str, persisted to next call (≤50k chars)
        return orders, conversions, trader_data
```

- `Order(symbol, price, quantity)` — positive qty = buy, negative = sell
- `OrderDepth.sell_orders` volumes are **negative** integers by convention
- Position limits: 80 per product (Round 1: INTARIAN_PEPPER_ROOT, ASH_COATED_OSMIUM)
- Do not edit `prosperity4bt/datamodel.py` — must match the Prosperity runtime

## Backtester Calibration

The backtester matches the website exactly on book state for Round 0 Day 0 and Round 1 Day 1 (the days whose CSVs align with website replay). It diverges on taker fills where our orders change the book.

**Rule of thumb:**
- **Use for ranking**, not absolute PnL prediction
- ACO/stable products: backtester ≈ website within 2%
- IPR/drift products: backtester can be inverse-indicator (see the r1_v3 regression investigation in git log)

## Key Files

| Path | Purpose |
|------|---------|
| `prosperity4bt/back_tester.py` | Main controller |
| `prosperity4bt/test_runner.py` | Per-day simulator |
| `prosperity4bt/datamodel.py` | TradingState/Order/OrderDepth/Trade — do not edit |
| `prosperity4bt/constants.py` | Position limits |
| `prosperity4bt/tools/order_match_maker.py` | Exchange matching simulation |
| `prosperity4bt/tools/data_reader.py` | CSV → BacktestData |
| `trader-logic/round-0/` | Tutorial round strategies (s1 through s36) |
| `trader-logic/round-1/` | Round 1 strategies (r1_v2, r1_v4 current best) |
| `trader-logic/auction_solver.py` | Manual-challenge clearing auction optimizer |
| `CLAUDE.md` | Working notes: bot behavior, strategy forensics, submission record |

## License

MIT — see [LICENSE](LICENSE).
