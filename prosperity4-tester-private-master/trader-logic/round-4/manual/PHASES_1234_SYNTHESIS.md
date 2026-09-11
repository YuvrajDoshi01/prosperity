# R4 Manual — 4-Phase MC Verification Synthesis (10K-seed final)

**Compute spent**: 233,284 candidates * 50M paths (Phase 1) + top 100 * 10B paths * **10,000 seeds** (Phase 2 final, 1T paths total) + top 20 * sigma/KO/jump grids (Phase 3) + top 10 * 100M antithetic paths (Phase 4) = ~25 trillion strategy-paths total. Phase 2 was incrementally tightened from 5 -> 500 -> 10,000 seeds; final SE on mean ~$31-34.

## Phase results

| Phase | Method | Verdict |
|---|---|---|
| Phase 1 | 233,284 strats * 50M paths GPU sweep -> 400 candidates | DROP_60C is max mean. 48 strats on Pareto frontier. |
| Phase 2 | Top 100 * 1B paths * 5 seeds | SE on mean ~$80-120. Confirms Phase 1 ranking. |
| Phase 3 | Top 20 * 12 sigmas, 5 KO frequencies, 5 jump regimes | DROP_60C extremely sigma-fragile. Hedged variants robust. |
| Phase 4 | Top 10 * 100M antithetic | CVaR-5% bootstrap SE ~$700-1000 (3-10x tighter than Phase 2). |

## Phase 2 Pareto frontier (mean / Sharpe / CVaR-5%) — 10K-seed verified

11-point frontier on 10K-seed * 10M-paths verification (SE on mean ~$31, SE on CVaR-5% ~$73):

| # | Mean ± SE | Sharpe | CVaR-5% ± SE | Positions added to base |
|---|---:|---:|---:|---|
| 1 | $163,079 ± $34 | 0.474 | -$551,983 ± $89 | base DROP_60C |
| 2 | $162,249 ± $32 | 0.495 | -$525,793 ± $88 | +25 AC_45_P |
| 3 | $162,048 ± $31 | 0.511 | -$473,185 ± $73 | +15 AC_50_C **★ DOM_NICE_v3** |
| 4 | $161,218 ± $28 | 0.564 | -$410,541 ± $66 | +15 AC_50_C +25 AC_45_P |
| 5 | $160,531 ± $28 | 0.567 | -$395,467 ± $61 | +25 AC_50_C +25 AC_45_P |
| 6 | $160,388 ± $27 | 0.582 | -$395,532 ± $65 | +15 AC_50_C +50 AC_45_P |
| 7 | $159,701 ± $26 | 0.605 | -$357,351 ± $57 | **+25 AC_50_C +50 AC_45_P** ★ Option B |
| 8 | $158,805 ± $26 | 0.603 | -$357,135 ± $57 | +25 AC_50_P +25 AC_50_C +25 AC_45_P |

Frontier identical at 5-seed, 500-seed, and 10K-seed precision. Mean and CVaR-5% values agree across runs to within MC error. **Frontier ordering is stable**.

Base = DROP_60C: { AC_50_P_2=+50, AC_50_C_2=+50, AC_50_CO=-50, AC_40_BP=-50, AC_45_KO=+500 }

## DOM_NICE_v2 (prior recommendation) is DOMINATED at z>23σ

DOM_NICE_v2 = DROP_60C + 50 AC_35_P (10K-seed): mean $161,005 ± $32, Sharpe 0.494, CVaR-5% -$525,457 ± $88. Phase 2 rank #11.

Frontier point #3 (DOM_NICE_v3 = DROP+15 AC_50_C) **strictly dominates** DOM_NICE_v2:

| Paired test (10K seeds) | Delta | SE | z-score |
|---|---:|---:|---:|
| Mean | **+$1,043** | $45 | **+23.4σ** |
| Sharpe | +0.017 | — | — |
| CVaR-5% | **+$52,272** | $114 | **+458σ** |

Better on all 3 dimensions with statistical certainty (p ≪ 10^-50).

## Phase 3 robustness (sigma sensitivity)

Mean E[score] across sigma grid:

| Strategy | s=2.20 | s=2.51 | s=2.55 | s=2.70 | s=2.80 |
|---|---:|---:|---:|---:|---:|
| DROP_60C | $354,001 | $163,672 | $142,076 | $66,176 | $19,691 |
| +25 AC_50_C | $243,597 | $161,796 | $154,116 | $130,206 | $118,207 |
| +25 AC_45_P+25 AC_35_P | $175,911 | $161,708 | $162,983 | $173,022 | $183,930 |
| +50 AC_35_P (DOM_NICE_v2) | $202,110 | $161,496 | $159,613 | $158,238 | $161,881 |

DROP_60C is the most sigma-fragile (loses $144k from sigma=2.51 to sigma=2.80). DOM_NICE_v2 is among the most sigma-robust (only $9k swing across same range). DROP+25 AC_50_C is in between.

KO monitoring: ALL candidates degrade similarly (4/d -> 16/d loses ~$65k per strategy). Brief specifies 4/d, so this is fixed.

Jumps: light jumps (lambda<=5) barely move EV. Heavy jumps benefit long-call hedges (DROP+25 AC_50_C goes to $271k under lambda=20, sigma_J=0.3) and hurt naked DROP_60C ($15k).

## Recommendation matrix

| If you want... | Ship | Mean | Sharpe | CVaR-5% |
|---|---|---:|---:|---:|
| Max EV (no hedge, sigma-fragile) | DROP_60C | $163,215 | 0.474 | -$552k |
| Small mean cost, small CVaR tightening | DROP +25 AC_45_P | $162,358 | 0.496 | -$526k |
| **Best risk-adj near max mean (recommended)** | **DROP +15 AC_50_C** | **$162,119** | **0.511** | **-$473k** |
| Pareto knee (best Sharpe per mean dollar) | DROP +25 AC_50_C +50 AC_45_P | $159,674 | **0.605** | **-$358k** |
| Sigma-robust (insurance against vol misspec) | DOM_NICE_v2 (DROP +50 AC_35_P) | $161,099 | 0.494 | -$526k |

## Final picks (3 options)

### Option A — "Max EV with cheap upside hedge" [TOP RECOMMENDATION]

```
SELL   50    AC_50_CO    @ 22.20
BUY   500    AC_45_KO    @  0.175
SELL   50    AC_40_BP    @  5.00
BUY    50    AC_50_P_2   @  9.75
BUY    50    AC_50_C_2   @  9.75
BUY    15    AC_50_C     @ 12.025   ★ NEW HEDGE
```

6 positions, mean $162,119, Sharpe 0.511, CVaR-5% -$473,625 (1B paths, 5 seeds, SE on mean ~$80).

**Strict Pareto improvement** over DOM_NICE_v2 on all metrics: +$1,020 mean, +0.017 Sharpe, +$52,626 CVaR-5%.

### Option B — "Best Sharpe near max mean"

```
SELL   50    AC_50_CO    @ 22.20
BUY   500    AC_45_KO    @  0.175
SELL   50    AC_40_BP    @  5.00
BUY    50    AC_50_P_2   @  9.75
BUY    50    AC_50_C_2   @  9.75
BUY    25    AC_50_C     @ 12.025   ★ HEDGE 1
BUY    50    AC_45_P     @  9.10    ★ HEDGE 2
```

7 positions, mean $159,674, Sharpe 0.605 (top in Phase 2), CVaR-5% -$357,680.

Costs $3,541 mean vs DROP_60C for 28% better Sharpe and 35% tighter CVaR-5%.

### Option C — "Sigma-robust insurance" (current recommendation)

DOM_NICE_v2 unchanged: mean $161,099, Sharpe 0.494, CVaR-5% -$526,251. Best vol-misspec insurance ($9k swing over sigma=2.51-2.80) but Pareto-dominated by Option A at the nominal sigma=2.51.

## Position-limit checks (all options)

| Symbol | Cap | A | B | C |
|---|---:|---:|---:|---:|
| AC_50_CO | 50 | -50 | -50 | -50 |
| AC_40_BP | 50 | -50 | -50 | -50 |
| AC_45_KO | 500 | +500 | +500 | +500 |
| AC_50_P_2 | 50 | +50 | +50 | +50 |
| AC_50_C_2 | 50 | +50 | +50 | +50 |
| AC_50_C | 50 | +15 | +25 | 0 |
| AC_45_P | 50 | 0 | +50 | 0 |
| AC_35_P | 50 | 0 | 0 | +50 |

All within caps, no duplicate-symbol issues.

## Mechanism: why AC_50_C hedge beats AC_35_P hedge

The DROP_60C structure has two structural risks:

1. **Down-tail (S << 50)**: KO knocks out exactly when S falls below 35, leaving us short the binary put cliff at 40 with no downside protection from KO. AC_35_P plugs THIS hole.
2. **Up-tail (S >> 50)**: Short chooser becomes a short call paying (S-50) on the 3-week leg with no upside hedge from C_2 (which is only 2-week). AC_50_C plugs THIS hole.

Empirically Phase 2 showed the up-tail hedge yields more variance reduction per dollar of EV cost (~$75/contract for AC_50_C vs ~$95/contract for AC_35_P), so AC_50_C dominates AC_35_P at the Pareto knee.

## Files

```
phase1_results.json              # 233K candidates -> 400 finalists
phase2_results.json              # 100 strats x 1B paths x 5 seeds (SE ~$80)
phase2_500seeds_results.json     # 100 strats x 5B paths x 500 seeds (SE ~$45)
phase2_10kseeds_results.json     # 100 strats x 10B paths x 10,000 seeds (SE ~$31) ★ FINAL
phase3_results.json              # sensitivity grids (sigma, KO, jumps)
phase3_10k_results.json          # Phase 3 re-run on 10K-seed candidates
phase4_results.json              # 10 strats x 100M antithetic (CVaR-5% SE ~$700)
phase4_10k_results.json          # Phase 4 re-run on 10K-seed candidates
phase{1,2,3,4}_*_log.txt         # stdout logs
analyze_500seeds.py              # 5 vs 500 comparison
analyze_10kseeds.py              # 5 vs 500 vs 10K progression + paired test
PHASES_1234_SYNTHESIS.md         # this file
```
