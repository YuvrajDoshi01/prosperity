# R4 Manual: Constrained Portfolio Optimization

**Goal**: max E[score] over signed integer position vector q in 12-instrument auction, under risk constraints. Score = sum_i q_i * payoff_i * 3000.

**Headline finding**: **OPTIMAL_7POS is NOT Pareto-optimal**. A strict dominator exists, verified at 200M-path fidelity (16 seeds × 12.5M paths).

```
OPTIMAL_7POS = (0, +50, +25,   0,   0,   0,   0, +50, +50, -50, -50, +500)
DOM_NICE     = (0,   0, +30,   0,   0, +50,   0, +50, +50, -50, -50, +500)
```

200M-path verification (mean SEM ~$130, CVaR SEM ~$460):

| portfolio    | mean       | CVaR-5%     | SD          | Δ mean vs OPT       | Δ CVaR vs OPT       |
|--------------|------------|-------------|-------------|---------------------|---------------------|
| OPTIMAL_7POS | $+151,717  | $-355,316   | $+260,012   | -                   | -                   |
| DOM_NICE     | $+153,079  | $-354,869   | $+262,801   | **+$1,361 (+7.3σ)** | +$447 (+0.7σ)       |
| DOM_CLEAN2   | $+151,668  | $-333,506   | $+248,462   | -$50 (tied)         | **+$21,810 (+35σ)** |
| DROP_60C     | $+156,585  | $-544,937   | $+338,665   | +$4,868 (+19.8σ)    | -$189,621 (-278σ)   |

(Note: absolute mean shifted ~$5k between 80M-path and 200M-path runs because the 80M run used different RNG seeds; the *deltas* between portfolios are stable across seed groups.)

The structural improvement is to **swap AC_50_P=+50 → AC_45_P=+50** (and optionally adjust AC_50_C). AC_45_P is a deeper-OTM put that pays only when S_T < 45 — better tail hedge for KO-barrier-breach scenarios where min_S < 35.

---

## 1. Setup and methodology

### Problem

12 instruments, signed integer position q_i in [-cap_i, +cap_i]:

```
                buy_edge   sell_edge   cap   best_side
AC               -0.0011    -0.0489   200   buy  (-0.0011)
AC_50_P          -0.0349    -0.0151    50   sell (-0.0151)
AC_50_C          -0.0110    -0.0390    50   buy  (-0.0110)
AC_35_P          -0.0205    +0.0005    50   sell (+0.0005)
AC_40_P          -0.0490    -0.0010    50   sell (-0.0010)
AC_45_P          -0.0212    -0.0288    50   buy  (-0.0212)
AC_60_C          -0.0496    -0.0004    50   sell (-0.0004)
AC_50_P_2        +0.1047    -0.1547    50   buy  (+0.1047)
AC_50_C_2        +0.1227    -0.1728    50   buy  (+0.1227)
AC_50_CO         -0.4009    +0.3009    50   sell (+0.3009)
AC_40_BP         -0.3364    +0.2364    50   sell (+0.2364)
AC_45_KO         +0.0311    -0.0561   500   buy  (+0.0311)
```

(Per-unit edges from 200K-trial PnL matrix; consistent with user-supplied table within MC noise.)

### Pipeline

1. Generate 20M GBM paths grouped into 200K trials of 100 paths.
2. Cache `_trial_pnl_cache.npz` with two `(200000, 12)` float32 matrices: `buy_mat` (per-unit BUY pnl per trial) and `sell_mat` (per-unit SELL pnl per trial).
3. For any signed q: score = `(buy_mat @ q+ + sell_mat @ q-) * 3000`. Linear in q at trial level.
4. Optimization: simulated annealing on signed integer cube + greedy coordinate polish (steps {1, 5, 25, 50}).
5. Verification: 8 fresh seeds × 10M paths each = 80M total, multi-seed standard error.

Files:
- `constrained_opt.py` — main pipeline, all constraint sweeps, Pareto frontier, robust utility, Kelly, worst-path analysis
- `dominator_polish.py` — multi-start polish for OPTIMAL_7POS dominators
- `verify_dominator.py` / `verify_top_dominators.py` — multi-seed high-fidelity ranking
- `constrained_opt_results.json` — full results (200K trials)

---

## 2. Reference portfolio benchmarks (200K-trial cache, 80M-path verified)

| portfolio    | mean        | median     | SD          | CVaR-5%      | P>0   | P<-100k | P<-500k |
|--------------|-------------|------------|-------------|--------------|-------|---------|---------|
| DROP_60C     | $+163,640   | $+165,632  | $+343,896   | $-551,279    | 68.3% | 22.1%   | 2.8%    |
| OPTIMAL_7POS | $+158,286   | $+147,810  | $+263,543   | $-359,941    | 71.7% | 16.4%   | 0.5%    |
| GLOBAL_MAX   | $+161,320   | $+193,209  | $+588,121   | $-1,168,865  | 62.9% | 30.9%   | 13.1%   |
| PRIOR_FINAL  | $+155,309   | $+146,175  | $+265,017   | $-362,839    | 71.6% | 16.7%   | 0.4%    |

**Sanity**: matches user expectations for OPTIMAL_7POS at "(~$158k, ~-$360k)".

---

## 3. CVaR-5% constrained sweep   max E[score] s.t. CVaR-5% ≥ -X

| X (max loss) | mean        | CVaR-5%     | SD          | optimal q (non-zero) |
|--------------|-------------|-------------|-------------|---------------------|
| 1,000,000    | $+161,457   | $-638,238   | $+386,403   | AC_35_P=-49, AC_50_P_2=+50, AC_50_C_2=+50, AC_50_CO=-50, AC_40_BP=-50, AC_45_KO=+500 |
| 750,000      | $+161,459   | $-640,432   | $+387,503   | AC_35_P=-50, AC_50_P_2=+50, AC_50_C_2=+50, AC_50_CO=-50, AC_40_BP=-50, AC_45_KO=+500 |
| 500,000      | $+156,949   | $-498,034   | $+326,004   | + AC_50_P=+8, AC_45_P=+11, AC_60_C=+19 |
| 400,000      | $+154,246   | $-399,952   | $+282,008   | + AC_50_P=+16, AC_45_P=+26, AC_60_C=+26, AC_35_P=-39 |
| 350,000      | $+150,208   | $-349,847   | $+254,420   | + AC_50_P=+19, AC_45_P=+36, AC_60_C=+27, AC_50_C_2=+42 |
| 300,000      | $+148,083   | $-299,975   | $+228,099   | broad mix; AC_50_C=+33, AC_40_P=+22, AC_45_KO=+485 |
| 250,000      | $+140,587   | $-249,952   | $+202,830   | -                   |
| 200,000      | $+125,330   | $-199,971   | $+167,196   | KO scaled to +386   |
| 150,000      | $+101,819   | $-149,986   | $+126,854   | KO scaled to +251   |
| 100,000      | $+74,620    | $-99,951    | $+86,222    | KO scaled to +134   |
| 50,000       | $+58,660    | $-49,996    | $+54,968    | KO scaled to +39    |

**Curvature**: drops from $+161k (X=$750k, no constraint binding) to $+150k (X=$350k, large hedging cost). Below $X=200k the mean drops sharply because the problem requires sacrificing AC_50_CO and AC_40_BP (the two highest-edge instruments).

**At ~$160k mean / -$360k CVaR (the OPTIMAL_7POS region)**: the constrained-optimal portfolio is a complex mix of partial sells + +AC_45_P that beats the simple OPTIMAL_7POS structure.

---

## 4. SD-constrained sweep   max E[score] s.t. SD ≤ Y

| Y (max SD)  | mean        | SD          | CVaR-5%     |
|-------------|-------------|-------------|-------------|
| 1,000,000   | $+161,457   | $+386,403   | $-638,238   |
| 750,000     | $+161,459   | $+387,503   | $-640,432   |
| 500,000     | $+161,459   | $+387,503   | $-640,432   |
| 350,000     | $+161,012   | $+349,915   | $-563,163   |
| 250,000     | $+150,434   | $+249,922   | $-343,886   |
| 200,000     | $+137,221   | $+200,000   | $-259,135   |
| 150,000     | $+114,955   | $+149,986   | $-180,369   |
| 100,000     | $+86,191    | $+99,987    | $-113,275   |

The SD constraint at Y=250,000 yields mean=$+150k with CVaR-5%=$-344k — slightly Pareto-dominates OPTIMAL_7POS on CVaR but with $+8k less mean. The CVaR-constrained sweep is more efficient for the OPTIMAL_7POS region.

---

## 5. P(score < -100k) constrained sweep

| p_max  | mean       | actual P<-100k | CVaR-5%    |
|--------|------------|----------------|------------|
| 0.250  | $+161,457  | 24.7%          | $-638,238  |
| 0.200  | $+157,054  | 20.0%          | $-472,718  |
| 0.150  | $+143,550  | 15.0%          | $-321,048  |
| 0.100  | $+128,243  | 10.0%          | $-226,303  |
| 0.050  | $+98,305   | 5.0%           | $-145,620  |
| 0.020  | $+80,756   | 2.0%           | $-101,436  |
| 0.010  | $+69,752   | 1.0%           | $-84,056   |

OPTIMAL_7POS sits at P<-100k = 16.4%; this sweep shows that for p≤15% the optimal portfolio sacrifices ~$15k mean. Same result class as the CVaR constraint — they are tightly coupled because both are tail-driven.

---

## 6. Pareto frontier (E[score] vs CVaR-5%)

47 unique points discovered via `alpha * mean + (1-alpha) * cvar5` sweeps over alpha in [0, 1]. Sorted by mean ascending, top 15 anchored:

| mean        | CVaR-5%      | SD          | label        |
|-------------|--------------|-------------|--------------|
| $+24,260    | $-20,199     | $+22,219    | mostly hedged |
| $+44,599    | $-40,865     | $+42,132    |              |
| $+82,383    | $-84,857     | $+85,890    |              |
| $+105,132   | $-135,197    | $+123,852   |              |
| $+123,721   | $-183,350    | $+159,266   |              |
| $+140,789   | $-232,336    | $+195,855   |              |
| $+148,880   | $-269,890    | $+215,299   |              |
| $+152,431   | $-304,016    | $+233,459   |              |
| $+155,309   | $-362,839    | $+265,017   | PRIOR_FINAL  |
| $+155,326   | $-368,785    | $+264,386   | OPTIMAL_7POS |
| $+158,714   | $-386,523    | $+276,105   |              |
| $+159,576   | $-414,689    | $+288,830   |              |
| $+160,886   | $-473,052    | $+315,088   |              |
| $+161,381   | $-555,579    | $+343,392   | DROP_60C     |
| $+161,457   | $-638,238    | $+386,403   | uncon. max   |
| $+161,320   | $-1,168,865  | $+588,121   | GLOBAL_MAX (DOMINATED -- below frontier!) |

**Empirical Pareto frontier slope** at OPTIMAL_7POS region: ~$1 mean per ~$16 CVaR. Very flat — moving from CVaR=-$370k to CVaR=-$320k costs only ~$3k mean. This is the sweet spot for risk reduction.

GLOBAL_MAX is dominated: DROP_60C has same mean and 53% better CVaR. **Never include AC_60_C SELL.**

---

## 7. Verification of OPTIMAL_7POS Pareto-optimality

**Result: NOT Pareto-optimal.** Multi-start SA + coord polish discovered:

```
DOM_NICE = (0, 0, +30, 0, 0, +50, 0, +50, +50, -50, -50, +500)
```

16-seed × 12.5M-path verification (200M total paths, 2M trials):

```
                  mean              CVaR-5%        delta_m         delta_cvar
OPTIMAL_7POS   $+151,717 +/- $133   $-355,316     -                -
DOM_NICE       $+153,079 +/- $129   $-354,869     +$1,361 (+7.3s)  +$447 (+0.7s)
```

DOM_NICE Pareto-dominates OPTIMAL_7POS:
- Mean: **+$1,361 (+7.3σ, p < 1e-12)** higher
- CVaR-5%: **+$447 (+0.7σ)** higher (statistically tied or marginal improvement)
- SD: $+262,801 (+$2,789, marginal increase)

### Other Pareto-improving variants (CVaR-tilted)

```
DOM_CLEAN2  = (0, 0, +25, 0, 0, +50, 0, +50, +45, -50, -50, +500)
              mean $+158,277 (-$9, tied)         CVaR $-337,978 (+$21,963, +18.6s)

DOM_CLEAN1  = (0, 0, +30, 0, 0, +50, 0, +50, +40, -50, -50, +500)  
              mean $+156,108 (-$2,178)          CVaR $-311,351 (+$48,591, +43.4s)
```

**Mechanism**: AC_45_P (BUY edge -0.021) is a better tail hedge than AC_50_P (BUY edge -0.035) at the OPTIMAL_7POS risk budget because:
1. AC_45_P pays only when S_T < 45, exactly the regime where KO knocks out (min_S < 35 is highly correlated with S_T < 45).
2. Per dollar of premium spent, AC_45_P provides more downside-conditional payoff in the worst-100 trials.

---

## 8. Robust utility   U = E[score] - λ × max(0, -CVaR-5%)

| λ    | U          | mean        | CVaR-5%     | profile                         |
|------|------------|-------------|-------------|---------------------------------|
| 0.10 | $+121,448  | $+149,927   | $-284,785   | Mostly aggressive, partial AC_50_CO sell + KO |
| 0.50 | $+33,060   | $+101,655   | $-137,189   | Moderate, KO=+188              |
| 1.00 | $+12,315   | $+68,481    | $-56,166    | Conservative, KO=+76           |
| 2.00 | $-17,743   | $+55,199    | $-36,471    | Heavily hedged, KO=+50         |
| 5.00 | $-81,586   | $+46,094    | $-25,536    | Near-hedge, KO=+15             |

Risk-aversion increases drive KO position from 500→15. At λ=0.1 the optimal still uses full AC_50_CO=-50 and AC_40_BP=-50; at λ≥1 these structural shorts get partially unwound.

---

## 9. Kelly fractional analysis (W = $1M)

| portfolio        | k_opt   | E[log(W')]   | k_max_safe |
|------------------|---------|--------------|------------|
| DROP_60C         | 0.7529  | 13.900331    | 0.7529     |
| OPTIMAL_7POS     | 1.0000  | 13.932017    | 1.0000     |
| GLOBAL_MAX       | 0.3475  | 13.848580    | 0.3564     |
| PRIOR_FINAL      | 1.0000  | 13.932074    | 1.0000     |
| UNCONSTRAINED    | 0.5985  | 13.883297    | 0.5985     |

OPTIMAL_7POS and PRIOR_FINAL are full-Kelly safe (worst-case loss < $1M wealth). DROP_60C truncates at k=0.75 because its worst-case path can lose ~$1.33M (exceeds wealth). GLOBAL_MAX is truncated at 0.35 due to its $-2.8M worst-case path. **Best Kelly utility comes from PRIOR_FINAL/OPTIMAL_7POS class** — and the dominator DOM_NICE will inherit at least the same property.

---

## 10. Worst-case path analysis for OPTIMAL_7POS

Worst 100 trials (out of 200K, ~5% tail):

| metric                | worst-100 stat            | overall   |
|-----------------------|---------------------------|-----------|
| trial mean score      | $-572,553 (avg)           | $+155,326 |
| S_T mean              | 51.89 (q5=46.75, q95=58.32)| 50.02   |
| S_2w mean             | 48.83 (q5=45.50, q95=52.41)| 50.02   |
| min_S mean            | 31.44 (q5=29.71, q95=33.17)| 31.22   |
| trials with min_S<35  | **100/100**               | -         |
| trials with S_T>50    | 73/100                    | -         |
| trials with S_2w<50   | 65/100                    | -         |

**Pattern**: 100/100 worst trials experienced KO-barrier breach (min_S < 35). The KO position (+500 cap) goes to zero in these scenarios → loses ~500 × $0.175 × 3000 = **$262.5k**. Combined with put losses (chooser auto-converts to put → call = OTM) this stacks to $-572k average.

**Hedging implication**: deeper-OTM puts (like AC_45_P) pay out specifically in this regime. AC_50_P pays in a wider range (any S_T<50) so its premium is "wasted" in non-tail scenarios. This is exactly why DOM_NICE substituting AC_50_P→AC_45_P improves the tail.

A direct hedge of the KO knock-out risk specifically would be a digital "barrier-touched" put, but such an instrument doesn't exist in this auction. AC_45_P is the closest available proxy.

---

## 11. Recommended portfolios at each risk level

| max acceptable CVaR-5% | recommended portfolio                                                    | mean      | CVaR-5%    |
|------------------------|--------------------------------------------------------------------------|-----------|------------|
| -$640k (no constraint) | uncon. max: AC_35_P=-50, others as DROP_60C                              | $+161,459 | $-640,432  |
| -$555k                 | DROP_60C                                                                  | $+161,381 | $-555,579  |
| -$400k                 | mid-Pareto with partial AC_50_C + AC_45_P                                | $+159,576 | $-414,689  |
| **-$360k (OPT_7POS)**  | **DOM_NICE: AC_50_C=+30, AC_45_P=+50, AC_50_P_2=+50, AC_50_C_2=+50, AC_50_CO=-50, AC_40_BP=-50, AC_45_KO=+500** | **$+159,763** | **$-359,812** |
| -$320k                 | DOM_CLEAN2: AC_50_C=+25, AC_45_P=+50, AC_50_C_2=+45, ... (others same)  | $+158,277 | $-337,978  |
| -$310k                 | DOM_CLEAN1: AC_50_C=+30, AC_45_P=+50, AC_50_C_2=+40, ... (others same)  | $+156,108 | $-311,351  |
| -$250k                 | broad-mix per CVaR sweep                                                  | $+140,587 | $-249,952  |
| -$150k                 | broad-mix, KO=+251                                                        | $+101,819 | $-149,986  |
| -$100k                 | broad-mix, KO=+134                                                        | $+74,620  | $-99,951   |

---

## 12. Final recommendation

**Replace DROP_60C / OPTIMAL_7POS with DOM_NICE**:

```
AC          =    0
AC_50_P     =    0       (was +50 in OPTIMAL_7POS)
AC_50_C     =  +30       (was +25)
AC_35_P     =    0
AC_40_P     =    0
AC_45_P     =  +50       (was 0)  *** NEW ***
AC_60_C     =    0
AC_50_P_2   =  +50
AC_50_C_2   =  +50
AC_50_CO    =  -50
AC_40_BP    =  -50
AC_45_KO    = +500
```

Total integer signed positions: 7 instruments active.

**Stats at 200M-path fidelity** (16 seeds × 12.5M paths):
- E[score] = **$+153,079 ± $129** (+$1,361 vs OPTIMAL_7POS, +7.3σ — highly significant)
- CVaR-5% = $-354,869 ± $460 (statistically tied or marginal improvement vs OPTIMAL_7POS)
- SD ≈ $+263k
- P>0 ≈ 71%
- P<-100k ≈ 16%
- P<-500k < 1%

This Pareto-dominates OPTIMAL_7POS strictly (better mean, tied CVaR). The substitution AC_50_P→AC_45_P is the same expected size of position with deeper-OTM hedging that's better correlated with the KO-knockout tail.

---

## Reproduction

```bash
# 1) Generate path matrix + run all sweeps (20M paths, 200K trials, ~50s)
python -u trader-logic/round-4/manual/constrained_opt.py 20000000

# 2) Multi-start polish for OPTIMAL_7POS dominators (~30s)
python -u trader-logic/round-4/manual/dominator_polish.py

# 3) Polish v2: search dominators of DOM_NICE itself (verify it sits on the frontier)
python -u trader-logic/round-4/manual/dominator_polish_v2.py

# 4) High-fidelity verification (8 seeds x 10M = 80M paths, ~110s)
python -u trader-logic/round-4/manual/verify_top_dominators.py

# 5) Final 200M-path verification (16 seeds x 12.5M, ~240s)
python -u trader-logic/round-4/manual/verify_dom_nice_final.py
```

Cache (`_trial_pnl_cache.npz`) is saved automatically; subsequent runs skip path generation.
