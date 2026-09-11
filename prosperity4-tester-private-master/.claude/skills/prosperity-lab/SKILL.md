---
name: prosperity-lab
description: >
  IMC Prosperity 4 competition workflow. Strategy development, backtesting, feature engineering,
  and submission management. Spawns quant-finance for pricing/strategy, competitive-programming
  for algorithm efficiency, and ml-research for feature extraction.
model: claude-opus-4-6
effort: max
context: fork
---

## Strategy Development Workflow

### New Product Analysis (when a new round drops)
1. Spawn `quant-finance` agent with the product specification
   - Classify the product archetype (fixed-price, random-walk, ETF basket, options, cross-exchange)
   - Identify the Wall Mid (deep-liquidity maker's midpoint)
   - Determine the primary inefficiency to exploit
   - Design the simplest strategy that captures the primary edge

2. Spawn `ml-research` agent with order book data
   - Extract candidate features from the order book (volume imbalance, distance-weighted,
     spread dynamics, trade flow, EMA deviations)
   - Compute pairwise correlations between features and future price movement
   - Select the minimum feature set (target: 2-4 features max)
   - Fit a linear model — check if linear combination beats more complex approaches

3. Spawn `competitive-programming` agent for implementation
   - Implement the strategy in Python within competition constraints
   - Optimize for execution speed (no unnecessary computation per tick)
   - Handle edge cases: empty order books, position limit boundaries, round startup

### Backtesting Protocol
1. Run strategy through `prosperity4bt` backtester
2. Analyze: total PnL, per-product PnL, Sharpe, max drawdown, position utilization
3. Compare against previous submission version
4. Check for overfitting: does performance generalize across different data windows?
5. Only submit if the new version improves on ALL key metrics

### Parameter Tuning
Spawn `quant-finance` agent:
- Feature coefficients: grid search or Bayesian optimization on backtest data
- Spread width: balance fill rate vs adverse selection
- Position limits: when to stop quoting one side
- EMA window: optimize for signal-to-noise on this specific product

### Mid-Competition Adaptation
If IMC patches bot behavior or introduces new mechanics:
1. Spawn `quant-finance` to analyze what changed (compare pre/post patch data)
2. Spawn `ml-research` to re-fit features on new data
3. Re-run full backtest pipeline
4. Emergency resubmit if current strategy is degraded

### Options Round Strategy
Spawn `quant-finance` with options-specific focus:
- Black-Scholes pricing with implied volatility estimation
- IV mean-reversion as primary signal (proven across P1-P3)
- Quadratic volatility smile fitting across strikes
- Delta-hedging to manage Greeks exposure
- Do NOT overcomplicate: simple BS with IV mean-reversion > stochastic vol models

### Cross-Exchange Arbitrage Round
Spawn `quant-finance`:
- Map conversion costs, shipping costs, tariffs
- Detect the hidden taker bot (fills sells near best bid at ~60% rate)
- Identify arbitrage windows accounting for all friction costs
- Position management: balance inventory across exchanges

### Submission Management
Track every submission:
```
Version | Product | Strategy | Backtest PnL | Live PnL | Notes
v35     | TOMATOES| 3-feat linear | 48,230  | pending  | dropped microprice, +12% vs v34
```
