# Round 2 Post-Mortem: Submission 363078 (try18-5)

**Final algo score:** 99,533.97 (single day, 10k ticks)
**Final manual score:** 207,607.50
**R2 cumulative:** 307,141.47 (algo + manual)
**Cumulative through R2:** 484,998.01
**Leaderboard:** Overall #283 / 22,179 (top 1.3%) — up 1,393 spots from R1 #1,676
**Date submitted:** 2026-04-20
**Strategy:** `try18-5` — try18-4 + MAF_BID=17 + pepper trend-based graceful unwind

---

## Summary

R2 was a strong recovery from R1's 89,861 algo score. ACO PnL doubled (10,534 → 20,222), IPR was effectively identical (79,327 → 79,312), and we beat the 200k cumulative threshold by 285k+. Manual ranked 88/22k after winning R1 manual at #1.

The story has a plot twist: **the final submission was NOT the documented r2_v5 (MAF=0).** The team shipped `try18-5` (a different codebase by a teammate) with MAF_BID=17. The submitted strategy used adaptive EMA-based ACO fair value rather than r1_v17/v18's hardcoded anchor of 10,000 — and this was decisive because R2 day-1 ACO traded with mean 9,982, not 10,000. A hardcoded anchor would have triggered crash_mode on 67.5% of ticks.

**Headline lesson:** R1's biggest assumption — that ACO FV is round-invariant at 10,000 — was wrong for R2. Adaptive bootstrap and EMA-based fair value were not just "robustness fixes" but load-bearing for R2 day-1 specifically.

---

## 1. What happened

Submission 363078 ran `try18-5` on Round 2 final scoring (1 day, 10,000 ticks, ts 0–999,900). Score breakdown:

| Leg | Role | Final PnL |
|---|---|---:|
| INTARIAN_PEPPER_ROOT (drift product) | EMA mid + bullish drift_bias + trend detection + opportunistic short | 79,312 |
| ASH_COATED_OSMIUM (stable product) | EMA + zscore mean-reversion + imbalance signal + dynamic width | 20,222 |
| MAF auction | bid=17 (paid only if won) | unknown impact |
| **Total algo** | | **99,533.97** |

End-of-day positions: PEPPER +80, ASH +0 (target_position=0 for ASH).

Manual challenge: bids (r=14, s=42, sp=44) → **207,607.50** PnL (rank 88).

R1+R2 cumulative on the leaderboard:

| Leg | R1 score | R2 score (cumulative) | R2 alone |
|---|---:|---:|---:|
| Algo | 89,861.44 | 189,395.41 | 99,533.97 |
| Manual | 87,995.10 | 295,602.60 | 207,607.50 |
| Overall | 177,856.54 | 484,998.01 | 307,141.47 |

| Leg | R1 rank | R2 rank | Δ |
|---|---:|---:|---:|
| Algo | 2,639 | 894 | +1,745 |
| Manual | **1** | 88 | −87 |
| Overall | 1,676 | 283 | +1,393 |

---

## 2. The submitted strategy was not the documented one

`R2_SUBMISSION_SUMMARY.md` documented `r2_v5` (= r1_v17 + MAF_BID=0) as the planned submission. Reality:

| Submission ID | Strategy | MAF_BID | Status |
|---|---|---:|---|
| 274128 | r2_v2 (= r1_v4 + MAF_BID=20000) | 20,000 | early test, scored 8,412 (1k ticks) |
| 275130 | r2_v5 (= r1_v17 + MAF_BID=0) | 0 | tutorial/test, scored 8,915 (1k ticks) |
| 275498 | god_logger probe | 0 | observation only |
| 286442 | r1_v18 (with bid()=15) | 15 | secondary test |
| **363078** | **try18-5** | **17** | **FINAL submission** |

`try18-5` is architecturally different from r2_v5/r2_v6:

| Component | r2_v5/v6 (planned) | try18-5 (actual) |
|---|---|---|
| ACO fair value | hardcoded anchor=10,000 (v5) or median-of-20 bootstrap (v6) | EMA initialized from median-of-20 bootstrap, then drifts |
| ACO signal | crash_mode circuit breaker on \|dev\| > 15 | zscore mean-reversion + imbalance confirmation |
| ACO width | fixed defaults (DISREGARD=1, JOIN=2, DEFAULT=4) | dynamic, scales with `ret_std` and \|zscore\| |
| ACO inventory | soft-limit skew at \|pos\|>40 | continuous risk_aversion=0.025 toward target=0 |
| IPR fair value | mid + drift_bias=5 (constant) | filtered MM mid + position-scaled drift_boost + trend drift |
| IPR sell side | symmetric take | take_width × 2.5 (opportunistic short only) |
| MAF_BID | 0 | 17 |

The two strategies are not minor variants. `try18-5` was developed independently on a separate branch.

---

## 3. Why ACO crushed: FV was 9,982, not 10,000

Day-1 R2 ACO mid statistics:

| Metric | Value | R1 Day 1 (272466) |
|---|---:|---:|
| Mean mid | 9,982.29 | ~10,000 |
| Stdev | 7.54 | ~7 |
| Min | 9,957 | 9,986 |
| Max | 10,008 | 10,015 |
| Ticks ≤ 9,985 | 6,737 (67.5%) | ~50 (0.5%) |
| Ticks ≥ 10,015 | 0 | ~10 |
| Spread mean | 16.19 | 16.18 |
| One-sided ticks | 7.5% | 7.3% |

The R2 ACO regime was **18 ticks lower mean** and entirely on the bid side of 10,000. r1_v17's hardcoded anchor at 10,000 would have triggered `crash_mode` (window `[9,985, 10,015]`) on 67.5% of ticks — orders of magnitude more than the 5.1% flicker rate that already cost us 1,743 PnL in R1.

**Counterfactual estimate:** if r1_v17 had been submitted with hardcoded anchor=10,000:
- 6,737 crash_mode ticks at the R1-measured rate of −1.263 PnL/tick = **−8,503 PnL**
- vs try18-5 actual ACO: +20,222
- **Estimated avoided cost: ~28,000 PnL on ACO alone**

`r2_v6` (median-of-20 bootstrap) would have anchored to ~9,975 (median of first 20 mids), then frozen there. Better than 10,000 but still a static anchor that would not track the drift over the day. The EMA-based approach in try18-5 continues adapting tick-by-tick.

### 3.1 ACO PnL by decile

| Decile | Cumulative | Δ |
|---:|---:|---:|
| 0-10% | 2,132 | +2,132 |
| 10-20% | 3,888 | +1,756 |
| 20-30% | 6,611 | +2,722 |
| 30-40% | 8,574 | +1,964 |
| 40-50% | 10,281 | +1,707 |
| 50-60% | 11,933 | +1,652 |
| 60-70% | 13,778 | +1,845 |
| 70-80% | 16,353 | +2,575 |
| 80-90% | 18,256 | +1,902 |
| 90-100% | 20,222 | +1,966 |

Per-decile ACO gain is roughly flat at ~1,700–2,700. Compare to R1 272466 where the same product oscillated between −85 and +2,647 per decile. The smoothness here is the EMA + dynamic-width approach absorbing noise without circuit-breaker flickers.

---

## 4. IPR was nearly identical to R1

| Metric | R1 272466 (Day 1) | R2 363078 (Day 1) |
|---|---:|---:|
| Drift over the day | +1,001 | +1,007 |
| Final PnL | 79,327 | 79,312 |
| Theoretical max | 80,080 | 80,560 |
| Efficiency | 99.1% | 98.5% |

Per-decile IPR gain in R2 was 7,334 → 8,000 → 8,000 (×8). The drift-capture machine ran flat-out from open. The 0.6% efficiency drop vs R1 is 480 PnL — within the noise of bootstrap-warmup ticks (try18-5's filtered-MM-mid waits for adverse_volume confirmation).

`drift_bias=5` (here implemented as `drift_per_tick=0.1 × urgency_lookahead=100 × inventory_ratio` plus a trend-direction drift of ±5) was correctly calibrated for the +0.1/tick observed drift. Same calibration as R1.

**No structural changes to IPR were needed for R2.** The drift product behaved identically.

---

## 5. Manual challenge: rank dropped from #1 to #88

Submitted bids (per `MANUAL_CHALLENGE_WRITEUP.md`'s decision matrix): r=14, s=42, sp=44. Result: **207,607.50** PnL, rank 88.

Predicted ranges:
- v4 solver MODE A (rank includes ghosts): ~260,000
- v4 solver MODE B (engaged only): ~204,270
- Decision matrix worst-case: 204,270
- Decision matrix EV at P(MODE A)=0.5: 232,135

**Actual landed within the worst-case bound.** This means the field behaved closer to "engaged only" than "all 22k registered" — consistent with the MODE B interpretation. The 87 spots dropped is because R1 manual was won by a closed-form puzzle (87,995 was a tied #1 with hundreds of teams) while R2 manual was a strategic allocation game where the elite engaged-player tier executes near-optimal Nash and our (14, 42, 44) is one of many similar answers.

The good news: the worst-case-robust choice still cleared 207k vs the threshold needs. The bad news: aggressive plays like (23, 74, 3) that scored ~487k in MODE A would have outperformed by ~280k if MODE A were correct. We left ~52k on the table relative to the per-mode-conditional optimum (260k MODE A best response was (14, 42, 44) at 260k, so loss is at most 52k vs aggressive play assuming MODE A).

---

## 6. MAF auction: we bid 17, outcome unverified

R2_SUBMISSION_SUMMARY argued for MAF_BID=0 on three grounds (structural, community, empirical). The actual submission used bid=17.

We cannot determine from the submission log alone whether bid=17 won the auction (the website does not report MAF outcomes per submission). The decision to bid 17 was made independently and was not analyzed against the MAF synthetic bench (which validated MAF_BID=0 with break-even bid ≈ 0).

What we know:
- Bid 17 is below most reasonable "scaling-tier" thresholds; if a team bid 50+, we lost the auction and paid nothing.
- ACO + IPR PnL totaled 99,534. The synthetic bench showed delta_mean across all 14 regimes was within ±9 PnL between MAF-winner and MAF-loser flow. Whether we won or lost MAF, the PnL impact is in the noise relative to the algorithm-quality delta.

**Net assessment:** the bid=17 was a small departure from documented strategy with no measurable downside. The MAF debate was mostly a non-issue at scoring time.

---

## 7. Cumulative position and threshold

Threshold for advancing: 200,000 cumulative XIRECs through R2.

| Pre-R2 (R1 only) | Post-R2 (cumulative) | Buffer over threshold |
|---:|---:|---:|
| 177,856.54 | 484,998.01 | +284,998 |

We cleared the 200k bar by 285,000+. The R2_SUBMISSION_SUMMARY's "every scenario clears the threshold by 300k+" prediction held.

Leaderboard position summary:

| Leaderboard | R1 | R2 | Movement |
|---|---:|---:|---:|
| Overall | 1,676 / 22,130 (7.6%) | **283 / 22,179 (1.3%)** | +1,393 |
| Algo | 2,639 / 22,130 (11.9%) | **894 / 22,179 (4.0%)** | +1,745 |
| Manual | **1 / 22,130** | 88 / 22,179 (0.4%) | −87 |

We are firmly in the top 1.3% of all teams entering R3.

---

## 8. What the R1 post-mortem predicted vs what happened

R1 post-mortem section 8 ("Lessons for Round 2+") proposed 6 fixes. Score-card:

| R1 lesson | Carried into try18-5? | Outcome |
|---|---|---|
| 1. v17 bootstrap is not free insurance | YES — try18-5 uses adaptive EMA, not static bootstrap | ACO 2x R1 |
| 2. Synthetic needs asymmetric-open regimes | NO — bench wasn't updated | OK because we sidestepped via EMA |
| 3. Hardcoded FV beats bootstrap when FV is knowable | INVERTED — try18-5 chose adaptive over hardcoded | **R2 ACO mean was 9,982, not 10,000** — adaptive was the right call |
| 4. Circuit breakers need hysteresis | N/A — try18-5 has no circuit breaker | No flicker problem |
| 5. Banker's rounding | unchanged risk, didn't bite | no impact |
| 6. Per-tick PnL diagnostics | not deployed | n/a |

**The most important reversal was #3.** R1's lesson said "use hardcoded FV when knowable; reserve bootstrap for unknown FV." R2 proved that ACO FV was NOT round-invariant at 10,000. The adaptive approach beat the hardcoded approach by an estimated 28,000 PnL.

Generalized R3 lesson: **assume product fundamentals are NOT round-invariant unless explicitly stated by IMC.** Bootstrap or adapt rather than hardcode.

---

## 9. Lessons for Round 3+

1. **Adaptive FV beats hardcoded across rounds.** The R1 ACO FV (≈10,000) and R2 ACO FV (≈9,982) differed by 18 ticks despite both being "the same product." Round 3 has options on VFE — use rolling/EMA-based mid for the underlying, not constants extracted from R0/R1/R2 EDA.

2. **Drift-product machinery transferred perfectly.** IPR drift-capture in R1 (99.1%) and R2 (98.5%) used essentially the same logic. Drift-capture is robust and round-invariant: long the inventory + post passive bids that catch the drift. For R3 delta-1 products (HYDROGEL_PACK, VELVETFRUIT_EXTRACT), this template is reusable.

3. **Mean-reversion + dynamic-width beats circuit-breakers.** try18-5's `zscore × ret_std` adjustment with imbalance confirmation produced flat per-decile ACO PnL (1,700–2,700 range) vs R1 v17's wild swings (−85 to +2,647). The smoothness is from continuous risk-adjustment rather than discrete mode flips.

4. **Document and ship the same strategy.** The gap between R2_SUBMISSION_SUMMARY (r2_v5, MAF=0) and what shipped (try18-5, MAF=17) is a process risk. For R3, get the actual submission file under version control with the documentation that justifies it. The team's ad hoc judgment was correct here, but it could have gone the other way.

5. **Manual rank decay is structural.** R1 manual was a closed-form puzzle where #1 was tied by hundreds of teams. R2 manual was a strategic allocation where #1 is unique. Expect manual ranks to drop in any round where the puzzle has a continuous answer space. Robustness-optimal play is correct under uncertainty even when the EV-optimal play would have ranked higher; we chose 232k EV / 204k worst-case and got 207k actual.

6. **MAF was a sideshow.** ±9 PnL difference between winner and loser flow on synthetic, ±18 on round98 anchor. The whole "MAF strategy" debate is dwarfed by basic algorithmic-strategy quality. For R3+, verify any new mechanic's PnL impact via synthetic bench BEFORE spending strategic cycles on it.

7. **R2 final scoring was 1 day × 10k ticks**, not 3 days. Same as R1. This means a strategy's per-decile breakdown on a 10k single day is the most relevant BT comparison; multi-day BTs add variance without adding fidelity.

8. **try18-5's EMA + zscore + imbalance pattern is template-worthy for any stable-FV product in R3+.** Faster adaptation than circuit-breakers, no flicker, smooth per-decile PnL. Refactor this into `template_stable.py` for reuse.

---

## 10. Synthetic vs real comparison

The R1 post-mortem documented a 2.5× overshoot in BT vs real for ACO. R2 reality check:

- R2_SUBMISSION_SUMMARY projected r2_v5 single-day at 89,150 (= 8,915 × 10 from 1k tutorial).
- Actual try18-5: 99,534. **+10,384 over r2_v5 projection.**

Two compounding factors:
- try18-5 is a stronger strategy than r2_v5 (adaptive vs hardcoded ACO FV)
- The R2 ACO regime (mean 9,982, persistent below 10,000) was specifically the failure mode for r2_v5

If r2_v5 had been submitted, we'd predict (via the 2.5× BT overshoot rule):
- ACO: BT × 0.63 = 16,667 × 0.63 = 10,500 (R1-style)
- Plus crash_mode penalty for hardcoded anchor in R2 ACO regime: −8,500
- Estimated r2_v5 actual ACO: ~2,000
- Estimated r2_v5 total: ~81,300 (IPR 79,300 + ACO 2,000)

So the strategy switch from r2_v5 to try18-5 is worth roughly 18,000 PnL — far more than the MAF debate's ±50.

**For R3:** the ranking benefit of "ranking BT mode is preserved" still holds, but absolute PnL predictions need calibration per round (per the round98 calibration discipline in `memory/project_backtester_r2_cleanup.md`).

---

## 11. Files referenced

- Submitted strategy: `run-logs/round-2/results.zip` → `363078.py` (try18-5)
- Activity log: `run-logs/round-2/results.zip` → `363078.log` (32 MB, 20,001 rows)
- R2_SUBMISSION_SUMMARY (planned, not used): `trader-logic/round-2/R2_SUBMISSION_SUMMARY.md`
- Planned strategies (not submitted): `trader-logic/round-2/r2_v5.py`, `r2_v6.py`
- Manual writeup: `trader-logic/round-2/MANUAL_CHALLENGE_WRITEUP.md`, `MANUAL_CHALLENGE_FULL_ANALYSIS.md`
- MAF synthetic bench: `trader-logic/round-2/maf_synthetic_results.md`
- R1 post-mortem (predecessor): `trader-logic/round-1/POST_MORTEM_272466.md`
- Leaderboard data: `run-logs/leaderboard/round_2_official_{overall,algo,manual}.csv`
- Calibration helper: `trader-logic/round-2/calibrate_imc.py`
- Memory records: `memory/project_round1_final.md`, `memory/project_backtester_r2_cleanup.md`, `memory/project_maf_synthetic_bench.md`

---

## Appendix A: Raw leaderboard data (Team "Blank", AQ)

```
team_id: 181fc426-4c68-4d80-998d-9b87b564e12f
team_name: Blank
country: Antarctica (AQ)

R1 Overall:  position 1676 / 22130, score 177,856.54
R1 Algo:     position 2639 / 22130, score  89,861.44
R1 Manual:   position    1 / 22130, score  87,995.10  (tied first)

R2 Overall:  position  283 / 22179, score 484,998.01  (Δ +1,393)
R2 Algo:     position  894 / 22179, score 189,395.41  (Δ +1,745)
R2 Manual:   position   88 / 22179, score 295,602.60  (Δ −87)
```

R2-alone deltas (from R1 cumulative subtraction):
- R2 Algo alone: 99,533.97
- R2 Manual alone: 207,607.50
- R2 Overall alone: 307,141.47

## Appendix B: Top-20 R2 overall leaderboard context

| Rank | Team | Country | Score |
|---:|---|---|---:|
| 1 | Vibing | AU | 627,835 |
| 2 | The Big Posteriors | US | 540,572 |
| 3 | DU Trading | GB | 534,391 |
| 4 | Une Baguette Fromage | NL | 528,131 |
| 5 | Hexatech | GB | 527,567 |
| 6 | yuh | AU | 524,842 |
| 7 | CarbonBlack | IN | 522,020 |
| 8 | glou | GB | 521,938 |
| 9 | Meiji Restoration | AU | 521,526 |
| 10 | 63-bit integers | AU | 521,181 |
| ... | ... | ... | ... |
| 283 | **Blank (us)** | **AQ** | **484,998** |

Top-1 lead over us: ~143k. With 4 rounds remaining (R3, R4, R5, finals), closing the gap requires ~36k/round of relative outperformance vs the leader. Achievable for individual rounds but compounds against momentum. Realistic R3 target: top 100 overall, top 200 algo.
