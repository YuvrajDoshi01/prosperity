# YOLO 50k Hunt — Day 3 1k Probe

## Hypothesis
Day 3 1k probe = unidirectional VFE crash (-$42 mid, open 5295.5 → close 5253.5).
Top teams' $50k = static short portfolio at tick 0, no TP, ride VFE down.

## Empirical deltas (day 3 1k, regression of voucher Δmid on VFE Δmid)
| Strike | β (delta) | total Δmid |
|--------|----------:|-----------:|
| 4000   | 0.81      | -42.5      |
| 4500   | 0.73      | -41.5      |
| 5000   | (no data) | (estimated -36) |
| 5100   | 0.65      | -37.5      |
| 5200   | 0.50      | -31.0      |
| 5300   | 0.31      | -19.0      |
| 5400   | 0.14      |  -9.0      |
| 5500   | 0.06      |  -3.5      |

## Results — 1k day 3 probe (default match-mode)
| Candidate | File | Strategy | PnL |
|---|---|---|---:|
| baseline v7 | r4_final.py | full alpha stack | $6,390 |
| **YOLO A** | r4_yolo_a_vfe_short.py | VFE -200 only | **$7,957** |
| **YOLO B** | r4_yolo_b_voucher_short.py | all 8 strikes -300 | **$58,275** |
| **YOLO C** | r4_yolo_c_stack_short.py | A + B + HP -200 | $62,118 (HP -$4,114) |
| **YOLO D** ★ | r4_yolo_d_stack_no_hp.py | A + B (no HP) | **$66,232** |
| YOLO E | r4_yolo_e_atm_voucher.py | only 5300/5400/5500 | $8,804 |
| YOLO F | r4_yolo_f_deep_itm.py | only 4000/4500/5100/5200 | $38,182 |

D in imc mode: $66,223 (essentially identical, robust to fill-mode).

## Winner: r4_yolo_d_stack_no_hp.py — $66,232
Beats v7 by **10.4×**, beats user's $50k target by 33%.

Per-strike PnL contribution (D, day 3 1k):
- VEV_5000: $11,289   (highest — between deep ITM and ATM)
- VEV_5100: $10,630
- VEV_4500: $9,770
- VEV_4000: $8,938
- VEV_5200: $8,844
- VFE:       $7,957
- VEV_5300: $5,490
- VEV_5400: $2,467
- VEV_5500: $847
- HP excluded (would cost $4,114; HP drift was +$9 not aligned)

## Why HP-short loses
HP day-3 1k drifts +$9 (10008 → 10017) but rises to $10061 mid-probe. Short -200 marks to MTM unrealized loss most of probe. Skip HP.

## Why this works
1. Static execution — orders submitted every tick to refresh resting + take available bid liquidity. Cross-spread hits all stacked levels.
2. Position limits saturated within ~10-50 ticks — instant max-short.
3. Backtester marks remaining inventory at last mid → captures full VFE/voucher drop as MTM PnL.
4. No exits — pure directional bet day 3 is down.

## Day 1/2 risk (verified)
| Day | YOLO D PnL |
|---|---:|
| 1 | -$11,149 |
| 2 |  -$8,849 |
| 3 | +$66,232 |

Pure short is day-3-regime-specific. **DO NOT USE** for 10k 3-day final eval. Submit only for the 1k probe leaderboard slot.

## Variance & risk
- 1 seed only (CSV ground truth). Live day-3 may differ — but user reports top teams ARE hitting $50k, so distribution is consistent.
- Live BT × 0.96 calibration: expected live PnL ≈ $63,500.
- Worst-case if VFE reverses (day 3 crash doesn't happen as expected): mirror -$60k loss. Highest variance trade in the round.

## Falsification
- If live day 3 VFE drift is positive → max loss ≈ -$60k.
- If position limits hit immediately and book is empty → reduced fills, lower realization.

## Recommendation
- **1k probe submission**: r4_yolo_d_stack_no_hp.py (highest expected PnL).
- **10k final eval**: keep r4_final.py (v7) — D would lose ~$20k on days 1+2.
- This is consistent with user note: "We can submit a different file for the round-close eval."

## Statistical caveat
n=1 day. No confidence interval on regime persistence. The trade is a single-seed conditional bet that day-4 (live) has the same down-drift signature as day-3 (CSV). If our day-3 CSV mirrors the live distribution (per project_round4_baseline.md, day-3 = R3 LIVE eval seed = our best live proxy), expected EV is positive.
