# MAF Synthetic Bench — R2 Market Access Fee Decision

Seeds: **25** (canonical 42 + 73·i pattern). Ticks/day: 10,000. Strategies: r2_v5, r2_v6.

Assumes MAF winners trade against `interp`-book (brief-literal inject-midpoint mechanic); losers trade against `none`-book (base 80% flow). `scale` (×1.25 all volumes) shown as pragmatic cross-check.

## Top-line conclusion

- **r2_v5**: break-even bid ≈ -8 (all 14 regimes) / 1 (4 core regimes only). Baseline (no-MAF) mean PnL per regime = 22,262. `E[net delta | bid=X, P_win] = P_win · (delta_mean − X)`.

- **r2_v6**: break-even bid ≈ -9 (all 14 regimes) / -2 (4 core regimes only). Baseline (no-MAF) mean PnL per regime = 22,465. `E[net delta | bid=X, P_win] = P_win · (delta_mean − X)`.


If break-even is negative or zero, no positive bid is +EV — MAF_BID=0 wins under any P_win belief. If positive, bid up to break-even yields positive expected return scaled by P_win.



## Per-cell PnL (mean ± 95% CI across seeds, round99 synthetic)

### r2_v5

| Regime | none | scale | interp |
|--------|-----:|------:|-------:|
| UPTREND |    24,325 ±    271 |    24,370 ±    266 |    24,331 ±    274 |
| FLAT |    16,226 ±    300 |    16,246 ±    299 |    16,236 ±    301 |
| DOWNTREND |     8,252 ±    326 |     8,270 ±    331 |     8,246 ±    326 |
| REVERSAL |    16,207 ±    329 |    16,253 ±    338 |    16,202 ±    326 |
| ACO_CRASH |    20,481 ±    241 |    20,555 ±    233 |    20,427 ±    242 |
| ACO_FLASH |    25,859 ±    337 |    25,787 ±    360 |    25,861 ±    338 |
| PERMANENT |    27,139 ±    328 |    27,114 ±    350 |    27,132 ±    329 |
| CRASH_DEEP |    34,675 ±    780 |    34,562 ±    845 |    34,651 ±    783 |
| ALT_FV_HIGH |    24,273 ±    349 |    24,287 ±    350 |    24,277 ±    348 |
| ALT_FV_LOW |    24,175 ±    296 |    24,216 ±    298 |    24,184 ±    298 |
| MID_SHIFT |    18,611 ±    987 |    18,880 ±    963 |    18,579 ±    982 |
| DEFENSE_BOT |    24,534 ±    269 |    24,569 ±    268 |    24,528 ±    270 |
| VOLUME_BURST |    24,544 ±    284 |    24,587 ±    290 |    24,561 ±    288 |
| ASYM_OPEN |    22,366 ±    690 |    22,454 ±    635 |    22,334 ±    705 |

### r2_v6

| Regime | none | scale | interp |
|--------|-----:|------:|-------:|
| UPTREND |    24,597 ±    101 |    24,641 ±     94 |    24,601 ±    107 |
| FLAT |    16,729 ±    146 |    16,740 ±    134 |    16,733 ±    145 |
| DOWNTREND |     8,674 ±    143 |     8,680 ±    141 |     8,660 ±    139 |
| REVERSAL |    16,593 ±    138 |    16,640 ±    141 |    16,593 ±    140 |
| ACO_CRASH |    20,949 ±    241 |    20,960 ±    236 |    20,940 ±    238 |
| ACO_FLASH |    26,167 ±    275 |    26,046 ±    320 |    26,166 ±    272 |
| PERMANENT |    27,406 ±    227 |    27,394 ±    256 |    27,394 ±    231 |
| CRASH_DEEP |    35,028 ±    440 |    34,877 ±    559 |    34,994 ±    442 |
| ALT_FV_HIGH |    24,546 ±    213 |    24,561 ±    209 |    24,544 ±    210 |
| ALT_FV_LOW |    24,553 ±    114 |    24,612 ±    110 |    24,572 ±    119 |
| MID_SHIFT |    17,886 ±    396 |    18,218 ±    384 |    17,850 ±    386 |
| DEFENSE_BOT |    24,785 ±    169 |    24,824 ±    166 |    24,767 ±    171 |
| VOLUME_BURST |    24,883 ±    165 |    24,866 ±    187 |    24,875 ±    166 |
| ASYM_OPEN |    21,708 ±    587 |    21,867 ±    494 |    21,692 ±    601 |

## Value of winning MAF per regime (PnL[winner] − PnL[loser])

### r2_v5

| Regime | delta (interp) | delta (scale) |
|--------|---------------:|--------------:|
| UPTREND |          +6 |         +45 |
| FLAT |         +11 |         +20 |
| DOWNTREND |          -6 |         +18 |
| REVERSAL |          -4 |         +46 |
| ACO_CRASH |         -54 |         +74 |
| ACO_FLASH |          +1 |         -72 |
| PERMANENT |          -7 |         -25 |
| CRASH_DEEP |         -24 |        -113 |
| ALT_FV_HIGH |          +4 |         +15 |
| ALT_FV_LOW |          +9 |         +41 |
| MID_SHIFT |         -31 |        +270 |
| DEFENSE_BOT |          -6 |         +35 |
| VOLUME_BURST |         +17 |         +43 |
| ASYM_OPEN |         -32 |         +88 |

### r2_v6

| Regime | delta (interp) | delta (scale) |
|--------|---------------:|--------------:|
| UPTREND |          +4 |         +44 |
| FLAT |          +4 |         +11 |
| DOWNTREND |         -14 |          +6 |
| REVERSAL |          -0 |         +48 |
| ACO_CRASH |         -10 |         +11 |
| ACO_FLASH |          -1 |        -122 |
| PERMANENT |         -12 |         -12 |
| CRASH_DEEP |         -34 |        -151 |
| ALT_FV_HIGH |          -2 |         +15 |
| ALT_FV_LOW |         +19 |         +59 |
| MID_SHIFT |         -36 |        +332 |
| DEFENSE_BOT |         -17 |         +40 |
| VOLUME_BURST |          -8 |         -17 |
| ASYM_OPEN |         -17 |        +158 |

## MAF model cross-check (|mean(interp) − mean(scale)| per regime)

Large values indicate synthetic conclusions are sensitive to the MAF approximation choice. Flag threshold: 5,000 PnL.

### r2_v5

| Regime | |interp − scale| | Flag |
|--------|------------------:|:-----|
| UPTREND |            39 | ok |
| FLAT |            10 | ok |
| DOWNTREND |            24 | ok |
| REVERSAL |            50 | ok |
| ACO_CRASH |           128 | ok |
| ACO_FLASH |            73 | ok |
| PERMANENT |            18 | ok |
| CRASH_DEEP |            89 | ok |
| ALT_FV_HIGH |            10 | ok |
| ALT_FV_LOW |            32 | ok |
| MID_SHIFT |           301 | ok |
| DEFENSE_BOT |            41 | ok |
| VOLUME_BURST |            27 | ok |
| ASYM_OPEN |           119 | ok |

### r2_v6

| Regime | |interp − scale| | Flag |
|--------|------------------:|:-----|
| UPTREND |            40 | ok |
| FLAT |             7 | ok |
| DOWNTREND |            20 | ok |
| REVERSAL |            48 | ok |
| ACO_CRASH |            20 | ok |
| ACO_FLASH |           120 | ok |
| PERMANENT |             0 | ok |
| CRASH_DEEP |           117 | ok |
| ALT_FV_HIGH |            17 | ok |
| ALT_FV_LOW |            40 | ok |
| MID_SHIFT |           369 | ok |
| DEFENSE_BOT |            57 | ok |
| VOLUME_BURST |             9 | ok |
| ASYM_OPEN |           175 | ok |

## Decision curve — E[net PnL delta vs not bidding], ALL 14 regimes

Formula: `E[net delta | bid=X, P_win] = P_win · (delta_mean − X)` where `delta_mean = mean(PnL[interp] − PnL[none])` across all 14 regimes (includes stress regimes like CRASH_DEEP).

Positive values → bidding beats not bidding. Break-even bid = `delta_mean`.

### r2_v5 (delta_mean_all = -8)

| bid | P=0.1 | P=0.3 | P=0.5 | P=0.7 | P=0.9 |
|---:|---:|---:|---:|---:|---:|
| 0 |        -1 |        -3 |        -4 |        -6 |        -8 |
| 1,000 |      -101 |      -303 |      -504 |      -706 |      -908 |
| 5,000 |      -501 |    -1,503 |    -2,504 |    -3,506 |    -4,508 |
| 10,000 |    -1,001 |    -3,003 |    -5,004 |    -7,006 |    -9,008 |
| 15,000 |    -1,501 |    -4,503 |    -7,504 |   -10,506 |   -13,508 |
| 20,000 |    -2,001 |    -6,003 |   -10,004 |   -14,006 |   -18,008 |
| 25,000 |    -2,501 |    -7,503 |   -12,504 |   -17,506 |   -22,508 |
| 30,000 |    -3,001 |    -9,003 |   -15,004 |   -21,006 |   -27,008 |

### r2_v6 (delta_mean_all = -9)

| bid | P=0.1 | P=0.3 | P=0.5 | P=0.7 | P=0.9 |
|---:|---:|---:|---:|---:|---:|
| 0 |        -1 |        -3 |        -4 |        -6 |        -8 |
| 1,000 |      -101 |      -303 |      -504 |      -706 |      -908 |
| 5,000 |      -501 |    -1,503 |    -2,504 |    -3,506 |    -4,508 |
| 10,000 |    -1,001 |    -3,003 |    -5,004 |    -7,006 |    -9,008 |
| 15,000 |    -1,501 |    -4,503 |    -7,504 |   -10,506 |   -13,508 |
| 20,000 |    -2,001 |    -6,003 |   -10,004 |   -14,006 |   -18,008 |
| 25,000 |    -2,501 |    -7,503 |   -12,504 |   -17,506 |   -22,508 |
| 30,000 |    -3,001 |    -9,003 |   -15,004 |   -21,006 |   -27,008 |

## Decision curve — E[net PnL delta vs not bidding], CORE 4 regimes

Core regimes = ['UPTREND', 'FLAT', 'DOWNTREND', 'REVERSAL']. Closer to R2 live (one normal day, no crash/flash/asym-open).

### r2_v5 (delta_mean_core = 1)

| bid | P=0.1 | P=0.3 | P=0.5 | P=0.7 | P=0.9 |
|---:|---:|---:|---:|---:|---:|
| 0 |        +0 |        +0 |        +1 |        +1 |        +1 |
| 1,000 |      -100 |      -300 |      -499 |      -699 |      -899 |
| 5,000 |      -500 |    -1,500 |    -2,499 |    -3,499 |    -4,499 |
| 10,000 |    -1,000 |    -3,000 |    -4,999 |    -6,999 |    -8,999 |
| 15,000 |    -1,500 |    -4,500 |    -7,499 |   -10,499 |   -13,499 |
| 20,000 |    -2,000 |    -6,000 |    -9,999 |   -13,999 |   -17,999 |
| 25,000 |    -2,500 |    -7,500 |   -12,499 |   -17,499 |   -22,499 |
| 30,000 |    -3,000 |    -9,000 |   -14,999 |   -20,999 |   -26,999 |

### r2_v6 (delta_mean_core = -2)

| bid | P=0.1 | P=0.3 | P=0.5 | P=0.7 | P=0.9 |
|---:|---:|---:|---:|---:|---:|
| 0 |        -0 |        -0 |        -1 |        -1 |        -1 |
| 1,000 |      -100 |      -300 |      -501 |      -701 |      -901 |
| 5,000 |      -500 |    -1,500 |    -2,501 |    -3,501 |    -4,501 |
| 10,000 |    -1,000 |    -3,000 |    -5,001 |    -7,001 |    -9,001 |
| 15,000 |    -1,500 |    -4,500 |    -7,501 |   -10,501 |   -13,501 |
| 20,000 |    -2,000 |    -6,000 |   -10,001 |   -14,001 |   -18,001 |
| 25,000 |    -2,500 |    -7,500 |   -12,501 |   -17,501 |   -22,501 |
| 30,000 |    -3,000 |    -9,000 |   -15,001 |   -21,001 |   -27,001 |

## Round98 anchor check (real R2 day 1 data, submission 274128)

Methodology validator. round98 CSV = r2_v2 submission 274128's book data (100% match). That submission WAS in the bottom 50% of bids, so its real book was the 80% flow. Reported numbers are for r2_v5/v6 (not r2_v2) — so absolute numbers differ from 8,407 (r2_v2's imc-calibrated PnL). Use the `interp - none` delta to gauge whether MAF would have flipped the sign vs r2_v2's actual 8,412 website score.

| Strategy | none | scale | interp |
|----------|-----:|------:|-------:|
| r2_v5 |    9,119 ±     0 |    9,106 ±     0 |    9,115 ±     0 |
| r2_v6 |    9,215 ±     0 |    9,191 ±     0 |    9,197 ±     0 |


---

Generated by `trader-logic/round-2/maf_synthetic_bench.py`. Design: `docs/superpowers/specs/2026-04-18-maf-synthetic-bench-design.md`.
