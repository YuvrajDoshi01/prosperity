---
name: Round 1 Template Library (for Round 2+ reuse)
description: 7 per-archetype strategy templates in trader-logic/round-1/templates/ built before Round 1. Reusable for Round 2+ new products.
type: project
originSessionId: b564564b-4b0d-4055-a502-a5537e373617
---
Per-archetype templates built pre-Round 1 at `trader-logic/round-1/templates/`. Reusable as scaffolding for any new product type:

| Template | Archetype | Key technique |
|---|---|---|
| `template_stable.py` | Pegged (AMETHYSTS/ACO-like, fixed FV) | LU take/clear/make pipeline, FV=constant, adverse_vol=15 |
| `template_random_walk.py` | Mean-reverting (KELP/STARFRUIT-like) | Filtered-MM-mid + small negative reversion beta |
| `template_basket.py` | ETF basket arb | Z-score on spread (threshold=7, window=45), no component hedging |
| `template_options.py` | Options/derivatives | Black-Scholes r=0, rolling IV mean per strike, no delta hedge |
| `template_conversion.py` | Cross-exchange arb | Implied bid/ask from observations + hidden-taker detection |
| `template_olivia.py` | Insider/event bot | qty=15 filter at daily min/max extremes |
| `refit_regression.py` | Utility | Auto-refit microprice regression coefficients |

**Round N deployment workflow:**
1. Download sample CSVs → identify archetype per product name/behavior
2. Run `refit_regression.py <prices.csv> <PRODUCT>` (if regression-based)
3. Update template configs (FAIR_VALUE, COEFS, LIMIT, product names)
4. Assemble final `trader.py` from selected templates
5. Submit and iterate

**Round 1 outcome:** r1_v4 used `template_stable` pattern for ACO (LU framework) + custom IPR drift logic. See project_round1_results.md for full submission trajectory.

**Warning:** CSV data ≠ website data. Volume-fitted features (microprice regression) may not port. Treat fitted coefs as starting points.
