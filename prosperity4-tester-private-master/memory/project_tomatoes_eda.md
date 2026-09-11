---
name: Round 0 Tutorial Summary (EMERALDS + TOMATOES)
description: Tutorial round finished at 2,857 (s3_carry) / 2,855 (s25 cross-validated). All strategy details and bot forensics are in CLAUDE.md; this memory retains ONLY insights that are reusable for later rounds.
type: project
originSessionId: b564564b-4b0d-4055-a502-a5537e373617
---
Round 0 tutorial: best **2,857** (s3_carry) / **2,855** (s25 cross-validated = NOT overfit). Top scorer fabiantum: 4,950 — gap of 2,093 UNEXPLAINED despite 37+ submissions.

Full per-submission table and bot forensics live in `CLAUDE.md`. This memory keeps only cross-round insights.

## Reusable insights for Round 2+

1. **PnL framework for a game with existing MM bot**: `PnL = Fill Rate × Spread Captured − Inventory Risk` — NOT `IC × Position × Volatility − TC`. Fill rate is exogenous (bot-driven), so signal IC does NOT affect fills. Queue priority (best±1) is the dominant lever.

2. **Regression coefficients are stable across days** (sum to ~1.0). s3_carry/s25 coefs `[0.06, 0.12, 0.24, 0.58]` were rock-stable. Use cross-validated fits, not best-of-N.

3. **Trade flow adds PnL through diffuse posting shifts, not take decisions** — we intercept 98% of taker flow, so market_trades is mostly a feedback loop on our own fills.

4. **Taker bots are contrarian on average** — sell into rallies, buy into dips. Gives us positive expected inventory MTM on long positions into rising markets. IPR replayed this pattern at scale in Round 1 (+79k).

5. **AC(1) ≈ -0.44 is a structural game-engine property** — appears in Round 0 (both products), Round 1 (both products), and P3. It's engine noise, not alpha.

6. **Clearing step HURTS on drift/random-walk products** — Round 0 s13 with clear: 2,077 vs 3,394 baseline. Round 1 IPR with LU take_width=1: 4,796 vs 7,446. Clear only works on stable/pegged products.

7. **Local backtester is MISLEADING** — s11 was +1,084 locally but −915 website; s19 was +92 locally but −175 website. Use for ranking only. See feedback_backtester.md.

## Round 0 infrastructure (still in trader-logic/round-0/ if needed)

- 7-module bot exploitation pipeline (`strategy/`)
- Feature engineering (207 features, top-5 stable r=+0.59 to +0.62 both days)
- FK/HJB solver (conclusion: useless when existing MM competes)
- MM bot profiler (8 analyses)
- `mega_sweep.py` + `grid_search.py` — parameter optimizers

Round 3 data is completely different from Round 0 (P3 Kelp price 2,028 vs Round 0 TOMATOES 5,006, 5× spread difference). Do NOT attempt data reuse. Only AC(1) ≈ -0.45 is structural.
