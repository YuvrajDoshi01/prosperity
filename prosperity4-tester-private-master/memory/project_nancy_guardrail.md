---
name: Nancy's trend guardrail — source and adaptation
description: Nancy (teammate) contributed the rolling-slope + direction-history regime detector that became our r1_v5 guardrail. Her full code is at trader-logic/round-1/references/nancy_algov4.py. Her website score 10,734 vs our r1_v4 10,624.84.
type: project
originSessionId: 955e9ff4-5728-4069-8882-3e961751886f
---
## Source

**Nancy's algov4.py** (teammate Discord share 2026-04-17, website score 10,734):
- Rolling regression slope over last 5 wall-mid values
- Direction history (sign of slope) over last 20 ticks
- `indicator = count(+1) / 20`
- Binary flip: `indicator >= 0.5 → target=+80 LONG`, `< 0.5 → target=-80 SHORT`

Stored at: `trader-logic/round-1/references/nancy_algov4.py`

## What we adopted (structural only)

Our r1_v5 uses the SAME mechanism:
- 5-mid slope window (SLOPE_WINDOW=5)
- 20-direction history (DIR_WINDOW=20)
- Same indicator formula

## What we changed (conservative)

- Asymmetric thresholds (0.55/0.35) instead of symmetric 0.5 — defensive against false flips
- Three zones (drift +5/0/-5) instead of binary target (+80/-80) — softer regime action
- Simple mid instead of Nancy's wall-mid — proven better on our website (r1_v2 discovery)

## What we REJECTED from Nancy (overfit risk)

**OU model (9 tuned params):**
- `alpha=0.0294, beta=1.145, gamma=10000`
- `ask_factor=1.0007, bid_factor=0.9993, edge=1`
- `spread=16, skew=0.5, z_threshold=0.6`

**Spread-linear pricing (2 tuned coefficients):**
- `spread_gradient=0.0010586880760` (10 decimal places)
- `spread_intercept=0.8694130152902`

These are backtest-fit magic numbers. Her +59 ACO advantage over our LU framework is within seed variance and relies on these.

## Validation

**Multi-seed synthetic regime test (4 seeds × 4 regimes):**
- r1_v5 beats r1_v4 on 16/16 seed×regime combinations
- Mean advantage: +15k uptrend, +20k flat, +28k downtrend, +23k reversal
- r1_v4 loses -15k PnL when drift reverses (synthetic data, v4 structurally exposed)

**Website confirmation:**
- r1_v4: 10,624.84 (no guardrail)
- r1_v5: 10,612.84 (−12 on uptrend tutorial, guardrail dormant)
- Nancy's algov4: 10,734.03 (+109 over r1_v4, her edge split ~+50 IPR / +59 ACO)

## How to apply

- For uptrend-confident days: r1_v4 max PnL (no insurance needed)
- For regime uncertainty: r1_v5 (gives up ~12 tutorial PnL for downtrend protection)
- **Do NOT port Nancy's OU model for ACO** — our LU framework is externally validated and doesn't assume specific volatility regime
- Synthetic regime tests at `trader-logic/round-1/experiments/synthetic/` (generate.py + run_all.py)
