---
name: Round 1 v18 (adaptive threshold) — architecture and results
description: r1_v18 fixes the four weaknesses identified in the 272466 post-mortem. Rolling median for avg_mid, per-day frozen MAD-from-anchor threshold, median-of-20-bootstrap, hysteresis exit. Wins both real BT and synthetic bench over v17 and v14.
type: project
originSessionId: b564564b-4b0d-4055-a502-a5537e373617
---
r1_v18 addresses the four root-cause items in `POST_MORTEM_272466.md`:

1. **Rolling median for ACO avg_mid** (was 5-tick mean, window=5 → median, window=21)
2. **Per-day frozen MAD-from-anchor threshold** (was hardcoded 15 forever)
3. **Median-of-20-samples bootstrap** (was first-tick snap)
4. **Hysteresis on crash trigger** (enter at T, exit at 0.7*T)

## Threshold design: frozen, not live

First attempt used live MAD. It catastrophically failed synthetic — MAD widens during a real crash as new mids drift far from anchor, so threshold widens, dev stays below threshold, crash_mode never triggers. Same self-disarm failure mode as v15/v16 adaptive anchor.

Fix: compute MAD over the FIRST 50 mids (warmup), then FREEZE. Per-day calibration (adapts to observed noise level and anchor bias) but can't self-disarm during a crash.

Formula:
```
threshold_eff = max(ACO_CRASH_FLOOR=15, 4 * MAD_frozen)
```

MAD_frozen = median(|mid_i - anchor| for i in first 50 valid ticks).

## Results

### Real BT (3 days, 10k ticks each)

| Day | v17 Total | v18 Total | Delta |
|---|---:|---:|---:|
| 0 | 96,127 | **96,990** | +863 |
| -1 | 88,238 | **92,298** | +4,060 |
| -2 | 97,662 | 97,659 | -3 |
| **Sum** | **282,027** | **286,947** | **+4,920** |

IPR identical in all three days (v18 doesn't touch IPR). Entire delta is ACO.

### Synthetic bench (15 seeds × 13 regimes)

| Strategy | Total mean PnL |
|---|---:|
| **r1_v18** | **2,864,300** |
| r1_v14_def | 2,856,864 |
| r1_v17 | 2,854,963 |

v18 vs v14 per-regime: wins ACO_CRASH +2,966 ***, ALT_FV_HIGH +2,436 ***, ALT_FV_LOW +1,958 ***, smaller wins on PERMANENT/CRASH_DEEP/MID_SHIFT. Ties or essentially-ties elsewhere.

v18 vs v17: wins every non-flat regime. UPTREND +897 ***, FLAT +609 ***, DOWNTREND +736 ***, REVERSAL +1,264 ***, ACO_CRASH +2,939 ***, ALT_FV_HIGH +1,165 ***, ALT_FV_LOW +512 *, ACO_FLASH/PERMANENT/CRASH_DEEP near-zero but positive.

### Replay of 272466 day 1 data (v17 crash-mode reconstruction)

Using the 272466 activity log ACO mid sequence:
- v17 anchor = 10,008 (banker-rounded snap of first tick 10,007)
- v17 crash_mode fired 512 ticks (5.12%), 200 episodes
- v18 anchor = 10,010 (snap half-up of median of first 20 mids — slightly higher but threshold absorbs)
- v18 frozen MAD ≈ 10, threshold_eff = max(15, 4*10) = **40**
- **v18 crash_mode fires 0 ticks on 272466 day 1** (max dev was 24, well below 40)
- Estimated PnL recovery ≈ 1,355 ACO on real day 1 if v18 had been submitted

## Why the wins

- **ACO_CRASH synthetic +2,966**: the median-bootstrap anchor lands closer to true FV on ALT_FV regimes, so when a crash arrives the magnitude is measured correctly. Rolling median on avg_mid also keeps base_fv stable during crash.
- **ALT_FV_HIGH/LOW +2,000**: bootstrap captures the shifted FV on tick 20 (median of first 20) instead of at tick 0 first-mid (v17 would snap to first available, which might be 6-8 ticks off-center).
- **Real day -1 +4,060**: this day must have had a pattern that triggered v17's fixed 15-tick threshold. v18's frozen MAD adapts to day -1's noise level.

## Why v18 doesn't break what worked

- **IPR untouched**: drift-capture logic is 100% unchanged.
- **During crashes, threshold can't widen**: MAD is frozen after tick 50. A real crash gets caught reliably.
- **Hysteresis prevents flicker**: enter at threshold, exit at 0.7*threshold. No 1-tick oscillation.
- **UPTREND/FLAT/DOWNTREND synthetic identical to v14**: v18's baseline behavior on stable non-ALT-FV regimes matches v14 exactly.

## How to apply

- **Submit v18 for any Round 2+ day with an ACO-like stable product**.
- If the product is genuinely a drift/random-walk type, v18's ACO-specific logic won't apply — use an IPR-style template.
- The rolling-median + frozen-MAD-threshold pattern is reusable: any stable product with a circuit breaker should use this architecture instead of fixed thresholds.

## Files

- Strategy: `trader-logic/round-1/r1_v18.py`
- Dev BT logs: `backtests/2026-04-17_23-38-50.log` (day 0), `..._51` (-1), `..._52` (-2)
- Synthetic runner (updated to include v18): `trader-logic/round-1/experiments/synthetic/run_all.py`
- Post-mortem that drove the design: `trader-logic/round-1/POST_MORTEM_272466.md`
