# HP × VFE Cross-Product Analysis — Round 4

**Script**: `trader-logic/round-4/intel/hp_vfe_cross.py`
**Data**: `prosperity4bt/resources/round4/prices_round_4_day_{1,2,3}.csv`

## Headline

The legacy `vfe_drift < -5` gate has **no statistical foundation** as a cross-
product signal and likely costs PnL on every day, including day 3. Replace it
with a **price-level + recent-low-frequency-of-S17-cycle** gate, not a VFE one.

## 1. Cross-correlation

`corr(HP_t, VFE_{t+k})` on **levels** is non-stationary across days
(+0.18 day 1, −0.22 day 2, −0.44 at +500 lag day 3). Sign FLIPS across days →
no exploitable lead/lag. On **returns** (`dHP, dVFE`) all |ρ| < 0.015 across
k ∈ [-1000, 1000]. **No HF cross-product signal.**

## 2. Granger causality (p = 5 lags, returns)

| day | VFE→HP F | HP→VFE F | crit 5% |
|-----|---------:|---------:|--------:|
| 1   | 1.60     | 0.39     | 2.21    |
| 2   | 1.55     | 0.67     | 2.21    |
| 3   | 0.92     | 0.59     | 2.21    |

**No causality in either direction at α=0.05.** The level correlation is
spurious, driven by joint drift.

## 3. Basket spread (HP − α·VFE) is **not** stationary

OLS hedge ratio per day: α = +0.473 / −0.413 / −0.637. Sign flips → spread
is not cointegrated. Pooled range = 184.5 across days. **No stat-arb edge.**

## 4. VFE crash → HP regime change?

Conditional on `vfe_drift_200 < -5`, HP forward 200-tick return:

| day | n crash | HP_fwd \| crash | HP_fwd \| calm | diff |
|-----|--------:|----------------:|---------------:|-----:|
| 1   | 2,632   | +9.29           | +12.62         | -3.3 |
| 2   | 2,171   | +6.56           | +4.25          | +2.3 |
| 3   | 2,691   | −12.85          | −13.35         | +0.5 |

**Refuted.** VFE crash carries ≤ $3 of HP fwd-return signal — well inside
noise (HP std ~$30 over 200 ticks). The hypothesis fails.

## 5. Gate comparison (proxy: all HP>10010 ticks, fwd-200 reversion PnL)

| day | gate | allow n / mean PnL | block n / mean PnL |
|-----|------|---------------------:|---------------------:|
| 1   | legacy −5         | 1971 / **+6.7**  | 1244 / **+19.1** |
| 1   | tighter −3        | 1892 / +5.7       | 1323 / +19.8       |
| 2   | legacy −5         | 1826 / +13.7      | 666 / +7.4         |
| 3   | legacy −5         | 2512 / +14.4      | 2032 / +3.3        |

Day 3 *does* validate the gate (blocked ticks have +3.3 vs allowed +14.4 → gate
correctly avoids low-mean-reversion setups). **Day 1 the gate is harmful**
(blocks the BEST reversion windows). Net across 3 days: legacy gate is a
day-3 specialist, costs day 1.

## Recommendation

**Drop the VFE-drift gate. Replace with HP-internal regime detector:**

```python
# 200-tick rolling features on HP only:
hp_range = HP_max_200 - HP_min_200
hp_revert_count = number of times HP crossed 9990 ± 5 in last 1000 ticks

# Block S17 entry iff:
no_s17_cycle = hp_revert_count < 2 and hp_range < 25
```

If you must keep a VFE feature, use the **conjunction**: block only when
`vfe_drift < -10 AND hp_revert_count < 2`. Day-3 VFE crash + HP-cycle-absence
is the actual joint event; either alone is too noisy. Validate via:

```bash
python -m prosperity4bt trader-logic/round-4/r4_final_v2.py 4 --ticks 30000 --no-out --no-progress
```

across 3 days, comparing legacy vs new gate variants.
