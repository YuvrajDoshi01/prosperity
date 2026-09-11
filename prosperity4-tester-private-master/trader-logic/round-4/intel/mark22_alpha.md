# Mark 22 Alpha — Dedicated Reverse-Engineering for R4 v6

**Mandate**: Find Mark 22 alpha that beats v5 strictly on 10k 3-day def $163,376
/ imc $156,182 / 1k probe $6,390. Result: **NO IMPLEMENTABLE EDGE FOUND**.

## Sign Convention Correction
The mandate cited "Mark 22 sells HP → mid drops -3.66 in 2 ticks (n=19, t=-7.27)".
Re-running the analysis: **the sign is INVERTED**. Mark 22 SELL VFE → mid POPS
UP +1.50 in 1 tick (n=101, t=+10.18). Mark 22 SELL HP → mid POPS UP +3.94 in 2
ticks (n=8, t=+4.38). Mark 22 sells mark **local bottoms**: he is the passive
maker absorbing temporary down-pressure that immediately reverts.

The "n=19" cell came from `M22S → M55S within 1000ms, h=100t fwd`, which is
**NEGATIVE** (-$2.92, t=-1.21) and not the strongest cell. The strongest cell
in the data is M22 SELL VFE alone at h=1, t=+10.18.

## Five Axes Probed

### 1. HP fade: NOT IMPLEMENTABLE
- n=8 over 3 days. mean Δmid h=1 = +3.19, t=+5.64. Real signal but micro-N.
- HP spread when M22 prints: median 7, mean 7.12. Half-spread cost = 3.5.
- Best implementable variant (passive sell at best_ask−1): -$0.625/share, t=-1.02. Net: NEGATIVE EV after spread cost.
- 8 trades × 4 avg qty × $3.19 = $102 / 3-day GROSS. After spread cost: ~$0.

### 2. VFE fade: ALREADY ABSORBED BY v5
- n=101, mean Δmid h=1 = **+1.50**, t=+10.18. Strong, robust signal.
- Passive bid at best_bid+1, hold 10t: +1.60/share, t=+4.85. Total +$158 / 3-day.
- Per-day: D1 +$614, D2 +$370, D3 +$94 (using actual M22 trade qtys).
- **CRITICAL**: v5's Wall-Mid MM already posts a bid at best_bid+1 with size up
  to 200 every tick. The Mark 22 alpha is structurally captured by passive WM MM.
  v5 VFE PnL already shows D1=$3,060, D2=$11,998, D3=-$1,567 → $13,491 / 3-day.
- I tested two boost variants:
  1. Shift WM MM bid level to best_bid+2 when M22 prints → 10k def $163,366 (-$10), imc $156,158 (-$24).
  2. ADD an inside-spread bid at best_bid+2 size 20 alongside WM MM bid+1 → byte-identical, same -$10/-$24.
- The boost pays +1/share extra to displace the same fills. Net: no incremental alpha.

### 3. Mark 22 → Mark 55 sequence: WEAKER than M22 alone
- M22S → M55S within 100t, n=89. Forward at M22 entry: +1.49 t=+4.36 (h=10).
  But same passive bid at M22 entry on UNCONDITIONAL set (n=101, no M55 filter)
  scores +1.60 t=+4.85. M55 confirmation REMOVES samples without improving edge.
- At M55 trigger time, signal has DECAYED — passive bid camp NEGATIVE (-$0.35 to -$3.12).
- Original v6_mark_seq (cross-spread at M55 trigger) imc -$23k confirms the sequence is unimplementable.

### 4. VEV_6000/6500 free 0.5/share: FULLY EXTRACTED
- 317 sells per strike, all at price=0.0 (Mark 22 dumps to Mark 01).
- Mid is 0.5 in 100% of ticks (0/30000 elevated). No further extraction possible.
- v5 already runs deep-OTM bid=0 size=100 → +$300/3-day captured.

### 5. Time-of-day clustering: UNIFORM
- VFE: deciles 14/9/13/7/5/16/10/6/8/13 — no concentration.
- HP: scattered (1,1,2,1,_,_,_,1,_,2). N too small for pattern.
- VEV_6000: uniform (39/27/24/39/26/38/35/34/30/25).
- No tradable time gating.

## Implementability Summary

| Axis | Edge real? | Edge implementable? | Reason |
|------|-----------|---------------------|--------|
| HP fade | Yes (t=+5.64) | NO | n=8 too thin, half-spread = 3.5 ≈ alpha |
| VFE fade | Yes (t=+10.18) | NO | v5 WM MM already captures it |
| M22→M55 seq | Weaker than M22 alone | NO | Cross-spread cost > alpha (v6_mark_seq -$23k confirmed) |
| VEV deep-OTM | Yes | YES (already in v5) | bid=0 size=100 already deployed |
| Time clustering | No | — | Uniform distribution |

## Final Recommendation
**Do NOT ship r4_v6_m22.py.** Mark 22 alpha is structurally absorbed by v5's
Wall-Mid MM. v5 remains the strict baseline ($163,376 def / $156,182 imc / $6,390 1k).
The R4 voucher/HP alpha space is exhausted at this complexity.
