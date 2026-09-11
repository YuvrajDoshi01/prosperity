# Round 1 Strategies

**Current best: [r1_v4.py](r1_v4.py)** — website score **10,624.84** (213352).

## Directory structure

```
round-1/
├── r1_v4.py                    # Current best strategy (active)
├── refit_regression.py         # Utility: auto-refit microprice regression from CSV
├── best/                       # Archival copy of best strategy + documentation
│   ├── r1_v4.py
│   └── README.md               # Score rankings and philosophy
├── experiments/                # Failed or abandoned experiments (for lessons-learned)
│   ├── r1_adaptive.py          # Drift-adaptive variant
│   ├── r1_hybrid.py            # Seed-detection hybrid — scored 10,107 (no improvement)
│   ├── r1_v3.py                # LU framework applied to IPR — scored 7,975 (regression)
│   └── r1_medallion_dp.py      # DP experiment
├── early_versions/             # Older strategies superseded by v4
│   ├── trader.py               # Original basic trader (website 4,934)
│   ├── r1_medallion.py         # Microprice regression + drift (website 10,468)
│   └── r1_v2.py                # Simple mid + drift (website 10,536.81)
├── templates/                  # Per-archetype starter templates for future products
│   ├── template_stable.py      # Pegged product (AMETHYSTS-like)
│   ├── template_random_walk.py # Mean-reverting random walk (STARFRUIT-like)
│   ├── template_basket.py      # ETF basket arbitrage
│   ├── template_options.py     # Black-Scholes options pricer
│   ├── template_conversion.py  # Cross-exchange arb (MAGNIFICENT_MACARONS-like)
│   └── template_olivia.py      # Insider-bot copy-trading (SQUID_INK-like)
├── references/                 # Competitor code for study
│   └── r1_troll.py             # Another player's strategy (~10.6k website)
├── probes/                     # Lambda environment probes (separate workflow)
└── oracle/                     # God-logger & zero-order traders for pristine data extraction
```

## Strategy evolution

| Stage | File | Website | Discovery |
|-------|------|--------:|-----------|
| 1 | early_versions/trader.py | 4,934 | Baseline combined trader |
| 2 | early_versions/r1_medallion.py | 10,468 | +drift bias of 5 = 35% of total PnL |
| 3 | early_versions/r1_v2.py | 10,536.81 | Simple mid > microprice regression (210525 probe) |
| 4 | experiments/r1_hybrid.py | 10,107 | Seed-detection hybrid failed — drawdown IS the drift entry cost |
| 5 | experiments/r1_v3.py | 7,975 | Full LU framework on IPR broke drift capture |
| **6** | **r1_v4.py** | **10,624.84** | r1_v2 IPR + LU ACO clear step = +88 PnL |
| 7 | r1_v9_defensive.py | 10,601.66 | Cubic ACO inventory skew + circuit breaker + Banker's-rounding/tie-breaker fixes. Insurance: −23 vs v4 on real, +10k mean across 16 synthetic regime stress combos. |
| 8 | r1_v10_defensive.py | 10,455.66 | v9 + toxic-maker anchor fix + blind-bull startup fix. IPR cost −146 vs v9 (neutral startup on uptrend). ACO identical to v9 on real data (dormant, no crash). |
| 9 | r1_v11_defensive.py | **10,455.66** | v10 + `cur_mid` crash trigger (no MA lag) + IPR one-sided penny-improve drop. **Byte-identical to v10 on website** — zero cost, two dormant defenses (crash never fired, one-sided ticks had no taker flow). |
| 10 | r1_v12_defensive.py | **10,443.78** | v11 + blind-eye reset fix + sweep-optimal params (MAX_CONCESSION 8→4, CRASH_THRESHOLD 25→15). Synthetic +14,940 over v10; **website −12 (crash regimes never materialized; lower threshold triggers false positives on real ACO noise ±18)**. |
| 11 | r1_v13_defensive.py | 10,443.78 | v12 + forced-dump spread-cross when crash_mode + \|pos\|>60. Synthetic −21,715 vs v12 (cycle-loss); byte-identical to v12 on website. Textbook "inventory ping-pong" failure. |
| 12 | r1_v14_defensive.py | 10,443.78 | v12 + asymmetric quoting: `buy_cap=0` when crash_mode + pos≥60 (symmetric on short side). Byte-identical to v12/v13 on website (shutoff never fires). Synthetic −4,736 vs v12 but +21,979 vs v13. Architecturally correct for true one-way crashes. |
| 13 | r1_v15.py | not submitted | v14 + adaptive ACO anchor (bootstrap from first tick, slow median update). **FAILED: synthetic −58,568 vs v14.** On gradient crashes, anchor follows price down, crash_mode self-disarms, bot accumulates toxic inventory at crashed prices. Addresses FV-shift concern but breaks gradient-crash protection. Don't ship. |
| 14 | r1_v16.py | not submitted | v15 + freeze anchor updates while `prelim_crash` armed. Partial fix: +22,546 vs v15 on ACO_CRASH, still −37,983 vs v14 total synthetic. Gradient slow-start evades the freeze threshold — the fix engages too late. |
| **15** | **r1_v17.py** | **not submitted** | **v14 + bootstrap-only anchor (one-time snap at tick 0, frozen forever). 13-regime × 25-seed synthetic: +2,748 vs v14 total. Matches v14 on crash regimes, wins +3,026 on ALT_FV_HIGH/LOW. NEW EV-optimal default — pareto-dominates v14 for FV-shift scenarios at ~3k total cost on synthetic baselines.** |

## Submission recommendation (as of 2026-04-17)

After 8 website probes and 13-regime × 25-seed synthetic validation, the EV-optimal choice depends on threat model:

**Ship r1_v17** if you want full defensive stack with bootstrap FV-shift insurance:
- Matches v14's crash-regime performance (ACO_CRASH/FLASH/PERMANENT/CRASH_DEEP all within noise)
- Wins ALT_FV_HIGH +1,460 and ALT_FV_LOW +1,566 via bootstrap
- Small cost on baseline regimes (~2.9k) from 2-tick snap offset
- Website projected ≈ 10,440 (close to v14's 10,443.78)

**Ship r1_v9_def** for EV-optimal play if you prioritize website points:
- Website 10,601.66 (proven)
- Only −23 cost for defensive stack, preserves +5 IPR drift startup
- Break-even vs v4 at P(rug pull) > 0.1%

**Ship r1_v4** if you're confident IMC stays boring:
- Best website result 10,624.84
- Zero defensive stack — fully exposed to regime surprises

v10/v11/v12/v13/v14 are all pareto-dominated: either by v9 (if you keep +5 IPR drift) or by v17 (if you want the full defensive + FV-shift stack). Three submissions (257139/258586/259621) confirmed v12/v13/v14 are byte-identical on real data (10,443.78), meaning their additional refinements beyond v9 never fire on observed Round 1 data.

## Key learnings (see [CLAUDE.md](../../CLAUDE.md) Round 1 section for the full list)

1. **Simple mid beats microprice for drift products** — in ask-heavy books, microprice leans low and misses the t=0 entry
2. **Linear Utility's clear step = +3% PnL on stable products** (matches theory to within 1 PnL unit)
3. **LU's take_width=1 BREAKS drift products** — assumes present-value FV; drift needs future-value FV
4. **Drawdowns on drift trades are entry-cost, not bugs** — eliminating them costs PnL
5. **Seed detection works, but hardcoded orders don't fill** — no counterparty exists at the desired prices during drawdown
6. **Backtester for ranking only** — IPR backtester is inverse-indicator for framework changes

## Running

```bash
$env:PYTHONPATH="<repo-root>\prosperity4bt"

# Current best, all 4 days, tutorial-length
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 1000

# Full-day scoring
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 10000

# Specific day
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1--1 --ticks 1000
```
