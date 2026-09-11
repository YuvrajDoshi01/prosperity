# Round 3 Archive

Iteration history for R3 strategies. Active strategies live one level up at `trader-logic/round-3/`.

## Active strategies (root)
- `r3_v11.py` — original ship: spread=17 GIGA SHORT (sub 402350 → $12,246)
- `r3_v17.py` — + Phase 4.1 deep-ITM theta carry (sub 405628 → $12,432)
- `r3_v19.py` — + S7+FLIP-180 mechanic (sub 406831 → **$15,468 ★ best 1k probe**)
- `r3_v22.py` — + Hold-FLIP-until-mid≥10020 (**$40,056 BT day-2 10k ★ best final**)

## early_versions/
Earlier strategies before HP breakthrough:
- `r3_v1.py` — pure MM baseline ($28k 3-day BT)
- `r3_v3.py` — + structural arb. Sub 383883 → $1,177
- `r3_v7.py` — Wall Mid VFE breakthrough ($47k 3-day)
- `r3_v9.py` — + safe BS voucher taking. Sub 401608 → $2,636

## v1_iterations/
Initial v1 fair-value experiments:
- `r3_v1a-e.py` — OOP refactor / pure MM / inventory-skew / plain mid (winner) / wider slack

## failed_experiments/
Strategies that performed worse than baseline:
- `r3_v2.py`, `v2b.py` — IV smile z-score (wrong timescale)
- `r3_v4.py` — OBI predictor (spread cost dominates)
- `r3_v5.py` — VR(20) directional via VEV_4000 (-$40k/day)
- `r3_v6.py` — TAKE_OFFSET=1 aggressive (adverse selection -$80k)
- `r3_v8.py` — fixed-sigma BS voucher MM (vol regime fragile)

## superseded/
Versions superseded by later iterations:
- `r3_v3_theta.py` — terminal theta harvest A/B (no effect, didn't ship)
- `r3_v10.py` — + 401389 HP day-type detection (subsumed by v11)
- `r3_v12.py` — Tier-1 alpha stack (subsumed by v14j → v19)
- `r3_v13.py` — Tier-2 alpha expansion (engine fill cap blocked all gains, subsumed)
- `r3_v14.py` — = v14j HP exit fix (subsumed by v19's S7+FLIP)
- `r3_v18.py` — v14j + Phase 4.1 (subsumed by v19; sub 406165 → $12,815)
- `r3_v20.py` — SD's clean HP (subsumed by v22; sub 408128 → $15,224)
- `r3_v20_delta_hedge.py` — voucher Δ-hedge experiment (capacity-bound, didn't ship)
- `r3_v21.py` — v20 + MR exit hybrid (subsumed by v22; sub 408576 → $15,437)

## v14_sweep/
HP exit threshold sweep (v14_a..k). v14j (COVER=0, TIMEOUT=500) won.

| Variant | COVER | TIMEOUT | 1k day-2 BT |
|---------|------:|--------:|------------:|
| v14a | 9985 | 200 | $12,592 |
| v14b | 9970 | 200 | $12,714 |
| v14c | 9950 | 200 | $12,928 |
| v14d | 0 | 200 | $12,974 |
| v14e | 9998 | 500 | $12,410 |
| v14f | 9970 | 500 | $12,680 |
| v14g | 9970 | 1000 | $12,680 |
| v14h | 0 | 1000 | $12,826 |
| v14i | 0 | 300 | $12,236 |
| **v14j** | **0** | **500** | **$13,036** ★ |
| v14k | 0 | 700 | $12,394 |

## v22_sweep/
FLIP_EXIT_MID sweep on top of v20. FLIP=10020 won.

| Variant | FLIP_EXIT_MID | 3-day BT | 10k day-2 BT |
|---------|--------------:|---------:|-------------:|
| v22a | 10005 | $103,336 | $39,799 |
| v22b | 10010 | $103,106 | $39,659 |
| v22c | 10015 | $103,576 | $39,922 |
| **v22 (canonical)** | **10020** | $103,776 | **$40,056** ★ |
| v22d | 10025 | $102,968 | $39,717 |
| v22e | 10030 | $103,092 | $39,897 |
| v22_layerc_only | (no hold, just Layer C fix) | $104,434 | $38,940 |

## r4_prep_iterations/
Build chain that produced r3_v17 (Phase 4.1 multi-step build).

## diagnostics/
- `do_nothing.py` — minimal Trader for engine probing
- `latency_analysis.py`, `options_analysis.py`, `options_charts.py`, `real_arb_analysis.py` — analysis utilities
- `chart_*.png` — IV smile, intrinsic arb, option prices/Greeks plots
