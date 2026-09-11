# R4 r4_final.py Parameter Stability Sweep (v9)

10k 3-day default-mode BT. Baseline (current) = $261,854.

## Gradient Table

| Param | Sweep | PnL | Δ vs peak | Δ% peak | Class |
|-------|-------|-----|-----------|---------|-------|
| QUOTE_SIZE | 100 | 252,549 | -9,305 | -3.55% | STEEP downside |
| QUOTE_SIZE | 150 | 257,386 | -4,468 | -1.71% | MODERATE |
| QUOTE_SIZE | **200** ★ | **261,854** | 0 | — | peak |
| QUOTE_SIZE | 250 | 261,854 | 0 | 0 | PLATEAU (limit-clamped) |
| OBI_POS_CAP | 20 | 261,518 | -336 | -0.13% | FLAT |
| OBI_POS_CAP | **30** ★ | **261,854** | 0 | — | peak |
| OBI_POS_CAP | 50 | 261,796 | -58 | -0.02% | FLAT |
| OBI_POS_CAP | 75 | 261,282 | -572 | -0.22% | FLAT |
| VFE_MOMO_TP | 8 | 261,992 | -34 | -0.01% | FLAT |
| VFE_MOMO_TP | **10** ★ | **262,026** | 0 | — | new peak |
| VFE_MOMO_TP | 12 (cur) | 261,854 | -172 | -0.07% | FLAT |
| VFE_MOMO_TP | 15 | 261,603 | -423 | -0.16% | FLAT |
| M49_SIZE | 30 | 259,886 | -1,968 | -0.75% | MODERATE |
| M49_SIZE | 50 | 261,732 | -122 | -0.05% | FLAT |
| M49_SIZE | **60** ★ | **261,854** | 0 | — | peak |
| M49_SIZE | 80 | 261,792 | -62 | -0.02% | FLAT |
| YOLO_THRESH | -1.0 | 261,854 | 0 | — | inert (never fires) |
| YOLO_THRESH | -1.5 (cur) | 261,854 | 0 | — | inert |
| YOLO_THRESH | -2.5 | 261,854 | 0 | — | inert |
| YOLO_THRESH | -3.5 | 171,510 | -90,344 | -34.5% | CLIFF — catastrophic late entry |

## Classification & Recommendation

1. **QUOTE_SIZE**: STEEP downside, FLAT upside (250 = plateau, position-limit clamp). Keep **200**. Shifting to 250 buys nothing (no extra fills, just headroom).
2. **OBI_POS_CAP**: FLAT across 20-50 (max swing $0.22%). Keep **30** (current = peak, neighbors all within $600).
3. **VFE_MOMO_TP**: FLAT (max swing $0.16%). New peak at 10 (+$172) but inside noise. **Shift 12 → 10** to harvest tiny gradient and sit on plateau center (8/10/12 all within $200).
4. **M49_SIZE**: FLAT 50-80. Keep **60** (peak). 50 nearly identical (-$122) — robust either way.
5. **YOLO_DRIFT_THRESHOLD**: BIMODAL — inert in [-2.5, -1.0], CLIFF at -3.5 (-$90k). **No drift in BT reaches -1.0**, so the layer never fires here regardless of threshold ≤ -1.0. **Keep -1.5** as safe inert sentinel. Tightening to -3.5 is the false-positive trap (late entry on day-3 reversal). Loosening below -1.0 untested but symmetric risk → don't.

## Plateau-Shifted Params (only 1 of 5 moves)

Only **VFE_MOMO_TP: 12 → 10** improves BT and sits at plateau center. All other params already at peak with monotone decay. Single-param shift below the 2-param threshold for shipping `r4_v9_robust.py`. Recommendation: **skip v9_robust** — current r4_final.py is already on the plateau ridge for QS/OBI/M49/YOLO. The +$172 from MOMO_TP=10 is well within BT noise (compare M49_60→M49_80 = -$62 noise floor).

**Action**: ship r4_final.py unchanged. Document MOMO_TP=10 as alternate (re-test live).
