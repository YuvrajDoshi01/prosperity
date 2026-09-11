---
name: Round 1 Backtester Calibration & Alpha Analysis
description: Calibrated imc matching mode (extra_rate=0.064 for ACO), probe results showing ACO fills are strategy-independent, IPR ablation proving only drift bias matters, Rust-logic engine validation, 16 website submissions analyzed
type: project
originSessionId: f18e0d1e-9b40-461c-bde1-3161e1b8bc44
---
## Final Score: 10,467.8 (bias=6.0, run 134926)

Best website result from 16 submissions. IPR=7,377, ACO=3,091.

## Backtester Calibration (2026-04-15)

**imc mode with `extra_rate=0.064` for ACO** matches website within 1.6%.
Use `--match-mode imc` flag.

**Independent Rust-logic engine** (`prosperity4bt/tools/rust_engine.py`) built from chrispyroberts/imc-prosperity-4 source. Validates IPR=7,351-7,565 on CSV days (matches website 7,354). ACO undershoots by ~900 (invisible takers not in CSV).

## Game Engine Tick Sequence (from Rust source)
1. Fresh books generated (MM bot)
2. Strategy called → returns orders
3. Aggressive takes execute (== price matching)
4. Unfilled → passive levels in book
5. Taker arrives → hits ALL levels by price priority (bot AND strategy)
6. Passive orders DISCARDED at tick end. Position limits: ALL-OR-NOTHING.

## Website Probe Results (16 submissions)

| Probe | Total | ACO | ACO Fills | Key |
|-------|-------|-----|-----------|-----|
| bias=6 (BEST) | **10,468** | 3,091 | 101 | Optimal drift bias |
| bias=5 baseline | 10,445 | 3,091 | 101 | Previous best |
| Cleaned (no dead state) | 10,429 | 3,091 | 101 | 2 fewer IPR fills from traderData format change |
| No-take ACO | 9,987 | 2,633 | 66 | Takes worth 458 |
| Wide ACO (FV±3) | 10,445 | 3,091 | 101 | IDENTICAL — posting width irrelevant |
| State logger | 10,445 | 3,091 | 101 | observations=EMPTY, conversions=DISABLED |
| Conv +1 / -1 | 10,445 | 3,091 | 101 | Conversions have ZERO effect |
| Multi-level | 10,445 | 3,091 | 101 | Multi-level = zero effect |
| TROLL ACO | 10,435 | 3,081 | 94 | Take/clear/make framework = marginal loss |
| Swept ACO | 10,313 | 2,959 | 93 | BT gradient is WRONG for ACO |

## IPR Ablation: Only Drift Bias Matters

| Removed | Delta | % of PnL |
|---------|-------|----------|
| Drift bias | -10,508 | 35% |
| Asymmetric takes | -389 | 1.3% |
| Regression | -151 | 0.5% |
| Trade flow | 0 | 0% |
| OBI | 0 | 0% |
| Carry signal | 0 | 0% |

## Critical Lessons
- **traderData format matters**: removing dead state variables cost 2 IPR fills (-39 PnL). Keep all fields.
- **ACO fills are strategy-independent**: 101 fills across 12 of 16 runs (constant).
- **Gap to #1 (1,277)**: theoretical max ~10,651. #1 at 11,744 likely has different seed or unknown mechanism. Exhaustively probed — no hidden alpha found.
