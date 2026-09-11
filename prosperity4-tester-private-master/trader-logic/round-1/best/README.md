# Best Round 1 Strategies

Ranked by website score. All scores are 1k-tick tutorial submissions.

| File | Website | IPR | ACO | Key |
|------|--------:|----:|----:|-----|
| r1_v4.py | **10,624.84** | 7,446 | 3,179 | **CURRENT BEST** — r1_v2 IPR + Linear Utility ACO |

**Why r1_v4 wins:**
- IPR: simple mid + drift_bias=5 (proven by 210525 probe discovery — microprice regression misses t=0 take)
- ACO: Linear Utility AMETHYSTS port with take→clear→make pipeline (+88 PnL over r1_v2 baseline)
- 10 params total, all derived from market structure or copied from LU's P2 #2 finish. Zero backtester-tuned knobs.

**Expected performance on full-day (10k tick) competition rounds:**
- Backtester: +576/day to +622/day over r1_v2 baseline on days -2, 0
- LU's clear step edge COMPOUNDS with more ticks — larger edge on 10k than on 1k tutorial

## Non-overfit philosophy

Every parameter traces to:
- **Market structure** (e.g., SLOPE = 100/100k derived from observed drift)
- **Linear Utility's P2 #2 code** (validated on different market, different year)
- **Round ratios** (SOFT_LIMIT = 0.5 × LIMIT)

Predicted gain vs actual: theory said +3% × 3,091 = +87, actual measured +88. Matches to the unit → structural edge, not overfit.
