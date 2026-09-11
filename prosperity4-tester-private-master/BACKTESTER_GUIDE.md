# Backtester Guide

Complete reference for the `prosperity4bt` backtester in this repo. Written for someone new to GitHub, Python, and IMC Prosperity.

**Scope:** 2 fill modes (`--match-mode`), 3 CSV trade modes (`--match-trades`), 11 CLI flags.

## Contents

1. [Setup](#1-setup)
2. [Repository layout](#2-repository-layout)
3. [Running a backtest](#3-running-a-backtest)
4. [Writing a trader](#4-writing-a-trader)
5. [Where to put files](#5-where-to-put-files)
6. [CLI reference](#6-cli-reference)
7. [Match modes](#7-match-modes)
8. [Output & calibration](#8-output--calibration)
9. [Troubleshooting](#9-troubleshooting)
10. [Other backtesters](#10-other-backtesters)

---

## 1. Setup

Install Python 3.11+ and Git, then:

```bash
git clone <this-repo-url> imc-prosperity-4-backtester
cd imc-prosperity-4-backtester
pip install typer tqdm ipython jsonpickle

# PYTHONPATH — required so your trader can do `from datamodel import ...`
export PYTHONPATH="$PWD/prosperity4bt"              # bash / git-bash
# or on PowerShell:
$env:PYTHONPATH="$PWD\prosperity4bt"
```

Optional but recommended: use a virtual environment (`python -m venv .venv && source .venv/Scripts/activate`) before the `pip install`.

---

## 2. Repository layout

```
imc-prosperity-4-backtester/
├── prosperity4bt/               ENGINE — don't edit unless you know why
│   ├── __main__.py              CLI entry (`python -m prosperity4bt`)
│   ├── back_tester.py           Top-level controller
│   ├── test_runner.py           Per-day simulation loop
│   ├── datamodel.py             TradingState / Order / OrderDepth (MUST match website)
│   ├── constants.py             Position limits
│   ├── models/test_options.py   Enums: MatchMode, TradeMatchingMode
│   ├── tools/order_match_maker.py  All 5 fill modes live here
│   ├── tools/data_reader.py     CSV → TradingState
│   └── resources/round<N>/      CSV market data per round
│
├── trader-logic/                YOUR STRATEGY CODE
│   ├── round-0/                 Tutorial strategies (s3_carry, s36_medallion, …)
│   └── round-1/                 Round 1 strategies
│       ├── r1_v4.py             CURRENT BEST (website 10,624.84) — active at top level
│       ├── refit_regression.py  Utility
│       ├── best/                Archival copy + README
│       ├── early_versions/      Superseded: trader.py, r1_medallion.py, r1_v2.py
│       ├── experiments/         Failed runs: r1_v3.py, r1_hybrid.py, r1_adaptive.py, …
│       ├── templates/           Starter templates per product archetype
│       ├── references/          Competitor code for study
│       ├── probes/              Lambda-environment probes
│       └── oracle/              God-logger / zero-order traders
│
├── backtests/                   Output .log files (auto-created)
├── run-logs/                    Website submission ZIPs
├── CLAUDE.md                    Working notes (bot behavior, lessons)
└── BACKTESTER_GUIDE.md          ← you are here
```

Rule: engine = `prosperity4bt/`. Your code = `trader-logic/`.

---

## 3. Running a backtest

```bash
# Current best, all Round 1 days
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1

# Single day (round-day, dashes OK for negatives)
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1-0
python -m prosperity4bt trader-logic/round-0/s36_medallion.py 0--2

# Tutorial conditions (1k ticks, every tick — matches website test submission)
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 1000

# Full scoring (10k ticks per day)
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 10000

# Best calibrated mode for website ranking
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --match-mode imc

# Debug a crash / see trader prints
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1-0 --ticks 20 --print

# Fast sweep (no log, no bar)
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --no-out --no-progress
```

Output: progress bar per day → PnL summary on stdout → `backtests/<timestamp>.log` (upload to [jmerle's visualizer](https://jmerle.github.io/imc-prosperity-3-visualizer/) for charts).

---

## 4. Writing a trader

Minimum viable file — save as `trader-logic/round-1/my_trader.py`:

```python
import json
from datamodel import TradingState, Order

class Trader:
    def run(self, state: TradingState):
        orders = {}          # dict[product_name, list[Order]]
        conversions = 0      # int (used in later rounds)
        trader_data = ""     # str, persisted to next call (50k char cap)

        # Read the book
        book = state.order_depths["INTARIAN_PEPPER_ROOT"]
        best_bid = max(book.buy_orders)               # price
        best_ask = min(book.sell_orders)              # price
        best_ask_vol = -book.sell_orders[best_ask]    # sell volumes are NEGATIVE
        pos = state.position.get("INTARIAN_PEPPER_ROOT", 0)

        # Persist state across ticks via trader_data
        memory = json.loads(state.traderData) if state.traderData else {}
        # ... your logic, mutate memory ...

        # Place orders: positive qty = BUY, negative = SELL
        orders["INTARIAN_PEPPER_ROOT"] = [Order("INTARIAN_PEPPER_ROOT", best_bid + 1, 1)]

        return orders, conversions, json.dumps(memory)
```

Rules:

| Rule | Detail |
|------|--------|
| Import | `from datamodel import TradingState, Order` (matches website) |
| `Order(symbol, price, quantity)` | `+qty` = buy, `-qty` = sell |
| `sell_orders` volumes | stored as **negative** integers |
| Position limits | 80 per product (see `prosperity4bt/constants.py`) |
| Limit enforcement | **all-or-nothing per side per product** — one over-limit order drops ALL orders for that product that tick |
| `state.own_trades` / `market_trades` | contain trades from the previous tick only, cleared at each call |
| `trader_data` | string, 50,000 char max, returned as `state.traderData` next call |
| **Do not edit** | `prosperity4bt/datamodel.py` (must match website runtime) |

Real examples: `trader-logic/round-1/r1_v4.py` (current best) or `trader-logic/round-0/s36_medallion.py`. Evolution archive: `round-1/early_versions/`.

---

## 5. Where to put files

### Trader files

Anywhere you want — the CLI accepts any path. Convention:

| Location | For |
|----------|-----|
| `trader-logic/round-<N>/<name>.py` | active strategy |
| `round-<N>/best/` | archival copy of headline strategy |
| `round-<N>/early_versions/` | superseded strategies |
| `round-<N>/experiments/` | failed / ablation runs |
| `round-<N>/templates/` | per-archetype starter code |
| `round-<N>/references/` | competitor code |
| `round-<N>/probes/` | environment probes |
| `round-<N>/oracle/` | god-mode / zero-order traders |

### Data files

Drop CSVs in `prosperity4bt/resources/round<N>/` with these exact names:

```
prices_round_<N>_day_<D>.csv        (required)
trades_round_<N>_day_<D>.csv        (optional)
observations_round_<N>_day_<D>.csv  (for conversion rounds)
```

`<N>` = round number, `<D>` = day number (negatives OK). **Semicolon-separated.**

Prices columns: `day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;mid_price;profit_and_loss`

Trades columns: `timestamp;buyer;seller;symbol;currency;price;quantity`

To add a new round/day: drop the CSVs in, then register the day number in `prosperity4bt/tools/data_reader.py → available_days()`.

---

## 6. CLI reference

```
python -m prosperity4bt <algorithm> <days> [OPTIONS]
```

| Arg / Flag | Default | Effect |
|------------|---------|--------|
| `algorithm` (positional) | — | Path to your `.py` file with a `Trader` class |
| `days` (positional) | — | `<round>` for all days, `<round>-<day>` for one. Multiple OK: `0 1 2-1` |
| `--out PATH` | `backtests/<timestamp>.log` | Write log to custom path |
| `--no-out` | off | Skip writing the log |
| `--data PATH` | built-in | Load CSVs from custom folder |
| `--print` | off | Stream trader `print()` to stdout |
| `--match-trades {all,worse,none}` | `all` | See below |
| `--match-mode {default,imc}` | `default` | See §7 |
| `--ticks N` | unlimited | Cap ticks per day (use 1000 for R1 tutorial, 10000 for full) |
| `--iterations N` | None | Call `run()` only N times per day (between calls, orders rest). **Leave blank** — website calls every tick. |
| `--no-progress` | off | Hide progress bar |
| `--merge-pnl` / `--no-merge-pnl` | merge | Sum PnL across days |
| `--original-timestamps` | off | Don't shift timestamps across days |
| `--vis` | off | (currently stub; would open visualizer) |

### `--match-trades` (3 options)

Controls how your orders match against the CSV `trades_*.csv` file (only active in `default` mode):

| Value | Behavior |
|-------|----------|
| `all` | Matches CSV trades priced equal-to-or-worse than your quote |
| `worse` | Matches only strictly-worse CSV trades |
| `none` | Ignores CSV trades entirely |

Use `worse`/`none` if your strategy reads `market_trades` as a signal (avoids feedback-loop double-counting).

---

## 7. Match modes

Two fill-simulation modes. Each has a tradeoff.

| Mode | How it fills | When to use | Known limitations |
|------|-------------|-------------|-------------------|
| `default` | `>=` price crossing + replay CSV trades against you | Quick upper-bound check, strategy ranking | Overfills on crosses; overcounts CSV takers you'd have intercepted; no invisible-taker modeling |
| `imc` | `==` exact + calibrated per-product extra-taker (deterministic CRC32 hash) | **Website ranking (recommended)** | Hardcoded `extra_rate` per product in `TAKER_PARAMS`; calibrated on 1k ticks of one day; new products/rounds need refit via `trader-logic/round-2/calibrate_imc.py` |

Universal limits (both modes): CSV is the market **without your orders** — any fill you'd induce on the website is either missing or approximated. Position resets to 0 each day. MM doesn't react to you. One-sided books (~9% of R1 ticks) pass through as-is — your strategy must handle empty-side cases.

**Calibration snapshot (1k ticks, ACO product, deterministic imc):**

| Dataset | Strategy | Mode | ACO local | Website | Error |
|---------|----------|------|----------:|--------:|------:|
| R2 round98 (274128 data) | r2_v2 (r1_v4 base) | `imc` (extra_rate=0.038) | 1,004 | 1,026 | **−2.2%** |
| R2 round98 (274128 data) | r2_v2 | `default` | — | 1,026 | — |
| R1 day 0 (tutorial) | r1_v4 | `imc` (extra_rate=0.038) | 2,582 | 3,091 | −16.5% |
| R1 day 0 (tutorial) | r1_v4 | `default` | 2,282 | 3,091 | −26.2% |

**Current params** (`prosperity4bt/tools/order_match_maker.py`): IPR extra_rate=0.0 (R2 IPR BT 7,403 vs website 7,386, +0.2%), ACO extra_rate=0.038 (R2-calibrated from round98 CSV = submission 274128's book data, 100% match). Each R2 submission gets slightly randomized book data — round98 only matches 274128; other submissions (275130: 21%, 275498: 21%, 286442: 21%) have different books. R1 drifts because R1 day 0 has a different inside-spread taker rate — per-round re-calibration is expected. Run `python trader-logic/round-2/calibrate_imc.py` to sweep.

---

## 8. Output & calibration

### Terminal summary

```
Day summary:
  ASH_COATED_OSMIUM      PnL:   3,179    Pos:  -2     Trades:  101
  INTARIAN_PEPPER_ROOT   PnL:   7,446    Pos:  80     Trades:   37
  TOTAL                  PnL:  10,625
```

### `.log` file

Three sections, upload as-is to [jmerle visualizer](https://jmerle.github.io/imc-prosperity-3-visualizer/):

- **Sandbox logs** — per-tick trader prints
- **Activities log** — order-book snapshot + PnL per tick
- **Trade History** — every fill as JSON

Format is identical to the IMC website submission log, so any parser that handles one handles both.

### Tick sequence

1. MM bot posts fresh quotes (from CSV)
2. Your `run(state)` is called
3. Position limits enforced (**all-or-nothing per side**)
4. Aggressive takes execute against MM levels
5. Unfilled orders rest inside the spread
6. Taker arrives (in `imc` mode only) — hits our inside-spread resting orders if they improve MM's best
7. Next tick

### Website vs backtester

**The backtester is a ranking tool, not a PnL predictor.**

| Strategy | Website | Local (`default`) | Gap | Notes |
|----------|--------:|-----------------:|----:|-------|
| r1_v4 (best) | **10,624.84** | ≈8,970 | +18% | simple-mid IPR + LU-clear ACO |
| r1_medallion | 10,467.80 | ≈8,860 | +18% | microprice regression + drift |
| trader (basic) | 4,933.80 | 6,528 | +32% | no drift bias |
| s3_carry (R0) | 2,857 | 2,626 | −8% | inside-spread MM |

Rules of thumb:

- **Rankings preserved** across same-framework strategies.
- **Inside-spread MM**: apply `website ≈ backtester × 1.07` (`default` mode).
- **ACO-like stable products**: `--match-mode imc` → within ~1% on the calibration day; re-fit per round.
- **IPR is an inverse-indicator for framework changes.** Example: `r1_v3` (LU-on-IPR) ranked best locally but scored 7,975 on website (−2,650 regression vs r1_v4). Never trust an IPR framework win without submitting.
- **Practical ceiling ~10,625**. Competitors also converged there — remaining gap to #1 (11,744) is likely seed variance.

### Accuracy history

Pre-fix (before 2026-03-21) the backtester **lied**:

| Strategy | Website | Pre-fix local | Sign |
|----------|--------:|--------------:|:----:|
| s19_hybrid_fv | 2,676 | +92 over baseline | actually −175 on website |
| s11_replace_microprice | 1,936 | +1,084 over baseline | actually −915 on website |

Three bugs fixed:

1. **Stale `own_trades` / `market_trades`** — dicts weren't cleared between ticks, causing trade-flow signals and PnL trackers to double-count.
2. **Resting-order quantities not updated after partial fills** — the snapshot happened before matching, so post-fill resting orders kept the original qty and tripped position-limit rejection.
3. **Wrong iteration count** — the old `--iterations 1000` recommendation made `run()` fire on only 50% of ticks. Website calls every tick. Omit the flag.

Post-fix gap: **1% for book-only strategies**, 6–9% for inside-spread MM, 1.6% for ACO with `imc`.

---

## 9. Troubleshooting

| Error | Fix |
|-------|-----|
| `No module named 'datamodel'` | Set `PYTHONPATH` (see §1) or use `from prosperity4bt.datamodel import ...` |
| `does not expose a Trader class` | Class must be named exactly `Trader` (capital T) |
| `Warning: no data found for round N day D` | CSV missing at `prosperity4bt/resources/round<N>/` — check naming and `data_reader.available_days()` |
| `Orders for product X exceeded limit of 80` | Your orders breached the limit — ALL orders for that product that tick dropped silently. Compute `buy_cap = LIMIT - pos`, `sell_cap = LIMIT + pos` before sizing |
| Progress bar but no stdout | Buffered output — run with `python -u -m prosperity4bt …` |
| Trader exception mid-run | Not caught by backtester. Reproduce with `--ticks 10 --print` and wrap suspect code in try/except |
| Strategy crashes on one-sided books | ~9% of R1 ticks have empty `buy_orders` or `sell_orders` — guard `max()`/`min()` calls |

---

## 10. Other backtesters

Cross-validated on Round 1 day 0, 1k ticks — all agree on **ranking** despite 20–60% absolute divergence:

| Backtester | Lang | Install | Notes |
|-----------|------|---------|-------|
| **This repo** | Python | `git clone` | 2 match modes, calibrated `imc` |
| [kevin-fu1/imc-prosperity-4-backtester](https://github.com/kevin-fu1/imc-prosperity-4-backtester) | Python | `git clone` | ≈18% higher absolute; matches our ranking |
| [Xeeshan85/prosperity4btx](https://pypi.org/project/prosperity4btx/) | Python | `pip install prosperity4btx` | Same as Kevin, PyPI-published |
| [GeyzsoN/prosperity_rust_backtester](https://github.com/GeyzsoN/prosperity_rust_backtester) | Rust | `cargo build --release` | Byte-identical scores to this repo, faster |
| [jmerle/imc-prosperity-3-backtester](https://github.com/jmerle/imc-prosperity-3-backtester) | Python | `pip install prosperity3bt` | Upstream original (P3 products) |

---

**Workflow:** copy `templates/template_stable.py` → tweak → run → submit the same `.py` file to the IMC website.
