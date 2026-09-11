# Mark 14 Reverse-Engineering for R4 v6

Mandate: Mark 14 alpha that strictly Pareto-dominates v5 ($163,376 def /
$156,182 imc / $6,390 1k probe).

**Verdict: do NOT ship.** Mark 14 alpha is real in raw CSV but already
structurally captured by v5's inside-the-book MM. BT cannot detect counterparty
signals. v6_m14 ships dormant (byte-identical to v5).

## Findings

**1. Quote pattern hardcoded.** HP: M14 buys mid-8 (494/496 exact, std=0.29),
sells mid+8 (500/507). VEV_4000: M14 +/-10 (~95%). Stationary day-to-day to
+/-0.07. Deterministic spread-MM bot.

**2. M14<->M38 pair.** HP: 1003 trades, 95% at spread=16. VEV_4000: 439 trades,
79% at spread=21. M38 always crosses; M14 always passive. Spread>=15 on 96.7%
of HP ticks.

**3+5. Directional drift, cross-product.** No alpha. Rolling net qty -> fwd mid
|corr| < 0.11. HP/VEV_4000/VFE 10k-bucket flows orthogonal (|corr| < 0.08).

**4. VFE Mark 14 fade.** 647 trades, h=50 fade edge +0.85/share (t=-2.70),
$2,636 theoretical 3-day. h=100: $4,492, t=-3.38.

## Why no v6 ships

**A. v5 already front-runs M14.** HP MM posts `best_bid+1`/`best_ask-1` =
mid+/-7 vs M14 at mid+/-8. The QUOTE_SIZE 25->200 sweep gain (+$24,568 def)
IS the M14 alpha. VEV_4000 deep_itm: vbb+1/vba-1 = mid+/-9 vs M14 at +/-10.
HP step-2 inside (best_bid+2) BT $160,948, **-$2,428**. Tighter quotes drop
fill rate faster than they raise per-fill edge.

**B. VFE fade is captured by Wall-Mid MM.** Wall-Mid posts tighter than M14;
when M14 trades VFE we ARE the counterparty. M14's -$0.85/share loss = our MM
markout. Already in v5's $11,998/$14,000/$2,575 daily VFE PnL. v5 docstring:
"Counterparty layer didn't add net alpha in BT".

**C. BT cannot detect counterparty.** `state.market_trades` shows CSV-trade
LEFTOVERS after our orders consume them. We are the counterparty -> qty=0
(dropped). `own_trades` sets counterparty="" (matches against order_depths,
not named market_trades). 2000-tick trace: zero M14 in either path. Fade
module never fires in BT.

**D. BT sweep vs v5 (10k 3-day default)**
| Variant | PnL | Delta |
|---|---:|---:|
| v5 baseline | 163,376 | --- |
| v6_m14 (M14 module dormant) | 163,376 | 0 |
| DEEP_ITM_MM_SIZE 30->80 | 163,036 | -340 |
| V_VOUCHER_MM_SIZE 40->60 | 163,252 | -124 |
| HP best_bid+2 inside | 160,948 | -2,428 |

v6_m14 ties all 3 metrics. No variant dominates.

## Recommendation

Keep v5 for round-close. Use `r4_v6_m14.py` only as conditional fallback iff
IMC live engine attaches counterparty names (R3 logs show "" -> unlikely).
For v7+: focus on HP S17 z-gate, VFE momo re-sweep, VEV OBI conditional. Mark
14 alpha is DOA for this matching infrastructure.

## Files
- `mark14_alpha.py`, `mark14_alpha_v2.py` -- forensics + per-trade economics.
- `../r4_v6_m14.py` -- v5 + dormant M14 fade module (BT identical to v5).
