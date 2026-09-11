# Voucher Portfolio Delta Hedging — R4 Analysis

Source: r4_final_v2 BT log `backtests/2026-04-27_02-19-19.log` (10k 3-day, $111,422 total).
Script: `intel/voucher_delta_hedge.py`. Reconstruction: trade history → per-tick voucher position → BS delta @ sigma=0.18 → drift PnL = sum(voucher_delta_t * dVFE_{t+1}).

## 1. Aggregate portfolio delta (existing strategy, no hedging)

| Day | Voucher delta mean | std | abs-max | Gross voucher qty | VFE move | Unhedged drift PnL |
|----:|------:|----:|----:|------:|----:|----:|
| 1 | -257 | 41 | 337 | -412 | +20.5 | **+$2,348** |
| 2 | -116 | 27 | 176 | -148 | +28.0 | **+$2,267** |
| 3 |  +22 | 48 | 120 |   +3 | -63.5 | **+$3,135** |
| **3-day** | | | | | | **+$7,749** |

**Critical finding**: voucher portfolio is structurally **net SHORT delta** (mean -120). The BS-MM layer fires asymmetric BS_EDGE=10 quotes; bot flow buys our calls more than sells, leaving us short. On all 3 days this short-delta book happens to be **profitable** — VFE drifted up days 1-2 modestly, then down hard day 3 (-$63 spot move). Existing posture banks +$7,749 across days from VFE drift alignment.

## 2. Delta hedge via VFE — does NOT pay

| Threshold X | 3-day hedged drift | hedge cost | **Marginal vs unhedged** |
|--:|--:|--:|--:|
|  10 | +$5,568 | $5,196 | **-$7,377** |
|  30 | +$6,016 | $5,154 | **-$6,887** |
|  50 | +$9,599 | $4,524 | **-$2,674** |
|  80 | +$9,781 | $6,293 | **-$4,261** |
| 120 | +$5,695 | $3,085 | **-$5,139** |

Every threshold is negative — neutralizing voucher delta KILLS the +$7,749 alignment AND adds turnover cost. Hedge accuracy is excellent (residual_std < 1) but irrelevant: the unhedged exposure is alpha, not noise.

## 3. Why top teams' delta-hedged book worked, ours can't

R3 postmortem suggested top teams ran delta-hedged voucher MM for $345k. But our voucher MM is ALREADY profitable (PnL $5-15k 3-day) DUE to its directional bias. The competitor edge is **higher voucher fill volume** (broader strike coverage, tighter quotes, two-sided flow), not delta-hedging per se. With balanced two-sided flow, voucher delta would mean-revert to ~0 and hedging would matter; with our current one-sided seller flow, the residual short delta IS the trade.

## 4. Position-limit envelope

VFE-pos is already pegged to ±200 by Wall-Mid MM + momentum-short layers (vfe_max=200 all 3 days). **No headroom for a delta hedge** without dismantling existing VFE alpha. Voucher gross qty caps at -412 (day 1), within 10×300=3000 limit — voucher MM has 7× more capacity if filled.

## 5. Recommendation: **Do NOT add a delta-hedge layer.**

Instead, exploit asymmetry directly. **One concrete layer (`SHORT_DELTA_TILT`)**: when voucher_delta < -150 and VFE is rising (mid_t - mid_t-50 > +5), CUT BS_EDGE 10→6 on the BUY side only for ATM strikes (5100-5400) to refill long calls and reduce short delta organically. Projected impact: rebalances ~50 delta units on directional whipsaws, marginal +$300-800 BT, no VFE turnover cost.

Alternative gating: skip implementation; voucher PnL is near-saturation (intel/voucher_alpha.md), 3-day BT $111,422 is the operating point. Spend effort on HP/VFE alpha (where 10× upside lives) not voucher hedging.

## Files

- Analysis script: `C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/intel/voucher_delta_hedge.py`
- BT log: `C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/backtests/2026-04-27_02-19-19.log`
- Source strategy: `C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/r4_final_v2.py`
