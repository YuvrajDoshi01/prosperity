---
name: Synthetic regime testing framework
description: round99/ CSV generator + multi-seed strategy comparator for stress-testing regime changes. Validates tail-risk behavior that real CSVs don't cover.
type: project
originSessionId: 955e9ff4-5728-4069-8882-3e961751886f
---
## Purpose

Real CSV days all have uptrend drift. We can't verify regime-change robustness without synthetic data.

## Files

- `trader-logic/round-1/experiments/synthetic/generate.py` — generates round99 CSVs with 4 regimes
  - Day 0: UPTREND (+100/1k drift, tutorial baseline)
  - Day 1: FLAT (zero drift)
  - Day 2: DOWNTREND (-100/1k drift)
  - Day 3: REVERSAL (uptrend then downtrend mid-day)
- `trader-logic/round-1/experiments/synthetic/run_all.py` — multi-seed comparator

## Generator

Takes seed as CLI arg (default 42). Noise is Gaussian(0, 1), bots emulate MM behavior. Limitations: CSV is too-clean liquidity, absolute PnL is ~2-3× real website.

**Only relative ranking is actionable.**

## Backtester integration

Added round 99 to `prosperity4bt/tools/data_reader.py` `available_days()`:
```python
if round == 99:
    return [0, 1, 2, 3]
```

## Usage

```bash
# Generate synthetic data (optional seed arg)
python trader-logic/round-1/experiments/synthetic/generate.py 42

# Run one strategy
python -m prosperity4bt trader-logic/round-1/r1_v5.py 99 --ticks 10000 --no-out

# Single regime
python -m prosperity4bt trader-logic/round-1/r1_v5.py 99-2 --ticks 10000 --no-out

# Multi-seed comparator (generates seeds 42/123/456/789, runs 6 strategies)
python trader-logic/round-1/experiments/synthetic/run_all.py
```

## Validated findings

Multi-seed run (2026-04-17):
- r1_v5 beats r1_v4 on 16/16 seed×regime combos
- r1_v4 loses 15k+ per seed when drift reverses (DOWNTREND regime)
- r1_v7 scores highest on synthetic but regressed on real website (-159) — synthetic ACO dominance masks IPR regression
- r1_v8 confirmed worse than v4 across all regimes

## Why/How to apply

- Use synthetic tests to validate regime robustness before submitting
- NEVER use synthetic PnL for absolute predictions — only rankings
- If a variant regresses on any synthetic regime, it's risky for Round 2+
- Real-website regression cannot be caught by synthetic (v7 false-positive) — synthetic is necessary but not sufficient
