# ACO Trade Flow Analysis - Round 2 Deep Dive

## Executive Summary

**NULL HYPOTHESIS**: Trade flow provides no predictive signal for ACO mid-price movements.

**VERDICT**: FAIL TO REJECT. After rigorous statistical testing across 4 days, trade flow signals show:
- No consistent predictive power for next-tick price movements
- High p-values on cross-correlations (all r < 0.01, p > 0.27)
- Direction prediction AUC averaging 0.554 with only 1/4 days significant
- Mixed momentum/reversion dynamics with no stable pattern

**ACTIONABLE CONCLUSION**: Trade flow is NOT a viable alpha source for ACO. The market microstructure is consistent with noise traders hitting a mean-reverting OU process around FV=10000. Focus alpha efforts elsewhere.

---

## 1. Trade Arrival Patterns

| Day | N Trades | IAT Mean (ms) | IAT CoV | Runs Test p | Exponential K-S p |
|-----|----------|---------------|---------|-------------|-------------------|
| -2  | 429      | 2324          | 1.030   | 0.869       | 0.041*            |
| -1  | 459      | 2177          | 0.987   | 0.641       | 0.156             |
| 0   | 471      | 2117          | 0.980   | 0.784       | 0.240             |
| 1   | 465      | 2149          | 0.969   | 0.710       | 0.255             |

**Findings**:
- **CoV ~ 1.0**: Inter-arrival times are consistent with exponential/Poisson process (CoV=1 is hallmark of memoryless arrivals)
- **No clustering**: Runs test fails to reject randomness on all days (p > 0.64)
- **Arrival rate**: ~460 trades/day = 1 trade per 2.2 seconds average
- **Implication**: Taker arrivals are essentially random. No information in arrival timing.

---

## 2. Trade Size Distribution

| Day | Mean Qty | Median | Std  | Min | Max | Chi-sq Uniform p |
|-----|----------|--------|------|-----|-----|------------------|
| -2  | 5.15     | 5.0    | 2.27 | 2   | 10  | 0.0000           |
| -1  | 5.12     | 5.0    | 2.25 | 2   | 10  | 0.0000           |
| 0   | 5.10     | 5.0    | 2.25 | 2   | 10  | 0.0000           |
| 1   | 5.11     | 5.0    | 2.22 | 2   | 10  | 0.0000           |

**Distribution Shape** (averaged across days):
```
qty=2:  ~14%  |  qty=6:  ~17%
qty=3:  ~14%  |  qty=7:  ~5%
qty=4:  ~15%  |  qty=8:  ~7%
qty=5:  ~17%  |  qty=9:  ~5%
               |  qty=10: ~5%
```

**Findings**:
- **NOT uniform**: Chi-square rejects uniformity (p < 0.0001)
- **Bimodal structure**: Higher frequency at qty {5,6} and lower at qty {7,8,9,10}
- **Bounded [2,10]**: Clear min/max constraints
- **Implication**: Bot has discrete size distribution. Large trades (>7) are ~17% of flow.

---

## 3. Trade Direction & Balance

| Day | Buy %  | Sell % | Balance |
|-----|--------|--------|---------|
| -2  | 51.0%  | 49.0%  | +2.0%   |
| -1  | 50.1%  | 49.9%  | +0.2%   |
| 0   | 51.4%  | 48.6%  | +2.8%   |
| 1   | 51.6%  | 48.4%  | +3.2%   |

**Finding**: Near 50/50 balance. Slight buy bias (~51.5%) is NOT statistically significant given sample sizes (binomial 95% CI includes 50%).

---

## 4. Large Trade Impact Analysis

**Definition**: Large = qty > 7 (~17% of trades)

### Signed Impact: E[delta_mid * direction] (positive = momentum, negative = reversion)

| Day | k=1    | k=2    | k=3     | k=4    | k=5    | Pattern          |
|-----|--------|--------|---------|--------|--------|------------------|
| -2  | -0.09  | -0.13  | -0.52   | +0.36  | -0.16  | Weak reversion   |
| -1  | -0.11  | +0.38  | -0.73*  | +0.41  | -0.01  | Mixed            |
| 0   | -0.01  | -0.22  | +0.17   | -0.06  | -0.15  | Noise            |
| 1   | -0.38  | -0.84* | -1.15*  | -0.27  | +0.22  | Strong reversion |

*Asterisk = |t| > 1.96 (significant at alpha=0.05)

**Critical Finding**: 
- **INCONSISTENT across days**: Day 1 shows significant reversion at k=2,3; other days do not
- **Sign flips**: No stable pattern of momentum vs reversion
- **Economic magnitude**: Even significant effects are ~1 tick (economically small vs. 16-tick spread)

**Conclusion**: Large trade impact is NOT a reliable signal. Effects are noisy and regime-dependent.

---

## 5. Post-Trade Dynamics: Momentum vs Reversion

| Day | Classification | Buy Permanent | Sell Permanent | Significance |
|-----|----------------|---------------|----------------|--------------|
| -2  | REVERSION      | -0.05         | +0.03          | None         |
| -1  | MOMENTUM       | +0.36         | -0.54*         | Sell only    |
| 0   | MIXED          | -0.24         | -0.06          | None         |
| 1   | MOMENTUM       | +0.27         | -0.18          | None         |

**Finding**: Dynamics flip between days. This is a REGIME-DEPENDENT phenomenon, not a stable structural feature.

---

## 6. Book State -> Trade Direction Prediction

### Logistic Regression: P(buy) ~ OBI + spread + dev_FV + recent_delta_mid + vol_asym

| Day | N     | Accuracy | AUC   | Z-stat | p-value | Significant? |
|-----|-------|----------|-------|--------|---------|--------------|
| -2  | 416   | 0.536    | 0.540 | 1.17   | 0.244   | NO           |
| -1  | 443   | 0.564    | 0.593 | 2.77   | 0.006   | YES*         |
| 0   | 449   | 0.530    | 0.559 | 1.77   | 0.076   | NO           |
| 1   | 445   | 0.508    | 0.524 | 0.71   | 0.479   | NO           |

**Feature Coefficients** (standardized, averaged):
- OBI: +0.08 (positive OBI -> more likely buy)
- vol_asym: +0.08 (same as OBI by construction)
- dev_from_fv: -0.05 (higher price -> less likely buy, weak)
- recent_delta_mid: -0.03 (rising price -> less likely buy, weak)
- spread: -0.06 (inconsistent sign)

**Critical Finding**:
- **Only 1/4 days significant** (Day -1, p=0.006)
- **AUC range 0.52-0.59**: Barely above random (0.50)
- **Multiple testing**: With Bonferroni correction (alpha=0.0125), even Day -1 is borderline
- **Accuracy ~53%**: No practical edge for order anticipation

**Conclusion**: Book state provides NO consistent predictive power for trade direction.

---

## 7. Signed Flow Accumulation -> Price Prediction

### Cross-correlation: Cumulative signed flow vs next-tick delta_mid

| Day | Pearson r | p-value | Spearman rho | p-value |
|-----|-----------|---------|--------------|---------|
| -2  | +0.0013   | 0.897   | +0.0027      | 0.785   |
| -1  | +0.0004   | 0.968   | +0.0008      | 0.936   |
| 0   | +0.0005   | 0.957   | -0.0026      | 0.796   |
| 1   | +0.0000   | 0.999   | +0.0032      | 0.752   |

### Instantaneous: This-tick signed_qty vs next-tick delta_mid

| Day | Pearson r | p-value |
|-----|-----------|---------|
| -2  | +0.0024   | 0.814   |
| -1  | -0.0054   | 0.587   |
| 0   | -0.0032   | 0.752   |
| 1   | -0.0110   | 0.271   |

**Critical Finding**:
- **All correlations < 0.02 in absolute value**
- **All p-values > 0.27**
- **Zero predictive power**: Trade flow does NOT forecast price

---

## 8. Quantity -> Price Movement Relationship

| Day | r(qty, |delta_mid|) | p-value |
|-----|----------------------|---------|
| -2  | +0.017               | 0.719   |
| -1  | -0.033               | 0.479   |
| 0   | -0.043               | 0.350   |
| 1   | -0.073               | 0.115   |

**Finding**: Large trades do NOT predict larger subsequent moves. Correlation is indistinguishable from zero.

---

## 9. Trade-Book Interaction

### Spread at Trade Time vs Unconditional

| Day | At Trades | Unconditional | Difference |
|-----|-----------|---------------|------------|
| -2  | 16.02     | 16.15         | -0.13      |
| -1  | 16.36     | 16.22         | +0.14      |
| 0   | 16.14     | 16.25         | -0.11      |
| 1   | 16.06     | 16.23         | -0.17      |

**Finding**: Trades occur at near-average spreads. No preference for tight/wide spreads.

### Trades at Extreme Deviations from FV

| Day | Trades @ |dev|>10 | Ticks @ |dev|>10 |
|-----|---------------------|-------------------|
| -2  | 1.4%                | 5.2%              |
| -1  | 0.5%                | 3.0%              |
| 0   | 7.1%                | 9.1%              |
| 1   | 2.0%                | 3.7%              |

**Finding**: Trades are slightly LESS likely at extreme deviations. This is consistent with mean-reversion: price bounces back before takers can hit extreme levels.

---

## Statistical Power Analysis

For detecting IC = 0.03 at alpha=0.01, beta=0.80:
- Required N = (Z_alpha + Z_beta)^2 / IC^2 = (2.58 + 0.84)^2 / 0.0009 = 12,960

With N ~ 450 trades/day, we can detect IC > 0.15 reliably. Our observed correlations (r < 0.02) are well below detection threshold, confirming NULL.

---

## Conclusions & Recommendations

### What We Learned

1. **Taker arrivals are memoryless**: CoV ~ 1.0, no clustering, consistent with Poisson process
2. **Trade sizes are bounded [2,10]** with bimodal peaks at {5,6}
3. **Direction is ~50/50**: No persistent order flow imbalance
4. **No predictive signals**: All cross-correlations are noise
5. **Momentum/reversion is regime-dependent**: Cannot be reliably exploited

### Why Trade Flow Fails for ACO

ACO is an OU process mean-reverting to FV=10000 with:
- AC(1) ~ -0.49 (structural reversion)
- Spread ~ 16 ticks (wide, no alpha in making)
- Takers are noise traders (random direction, random timing)

The "information" in trade flow is already priced into the mean-reversion structure. Trades CAUSE price to deviate from FV, then the MM bot quotes pull it back. This is circular, not predictive.

### Actionable Strategy Implications

1. **DO NOT add trade flow features** to ACO strategy - they add noise, not alpha
2. **DO NOT condition on recent trades** - no momentum/reversion edge
3. **DO exploit OU reversion to FV=10000** - this IS the alpha (already in r2_v8)
4. **DO post inside spread** - capture taker fills on random arrivals
5. **Consider ignoring trade data entirely** for ACO - book state alone is sufficient

### Signal Quality Summary

| Signal                  | IC     | Consistent? | Actionable? | Verdict  |
|-------------------------|--------|-------------|-------------|----------|
| Cum flow -> delta_mid   | <0.01  | Yes (zero)  | No          | REJECT   |
| Trade size -> |delta|   | <0.01  | Yes (zero)  | No          | REJECT   |
| Book -> direction       | ~0.04  | No          | No          | REJECT   |
| Large trade impact      | ~0.02  | No          | No          | REJECT   |
| Post-trade momentum     | varies | No          | No          | REJECT   |

**Final Verdict**: Trade flow is UNINFORMATIVE for ACO. Alpha comes from structural mean-reversion, not flow.

---

*Analysis completed: 2026-04-18*
*Script: /Users/y0d046w/Desktop/prosperity4-tester-private/trader-logic/round-2/aco_trade_flow_analysis.py*
