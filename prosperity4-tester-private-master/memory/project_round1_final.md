---
name: Round 1 Final Submission (272466, r1_v17) — Failure Post-Mortem
description: r1_v17_bootstrap_only full Round 1 score 89,861.44 (IPR 79,327 + ACO 10,534). Primary loss: ACO bootstrap anchor flickered crash_mode 512 ticks costing ~1,743 PnL. IPR 99.1% of buy-and-hold ceiling.
type: project
originSessionId: b564564b-4b0d-4055-a502-a5537e373617
---
## Score: 89,861.44 on day 1 full scoring (10k ticks)

Submission 272466 (r1_v17_bootstrap_only). Final positions IPR +80, ACO +80. XIRECS −1,829,595 (manual challenge).

## Per-product breakdown

| Product | PnL | Theoretical max | Efficiency |
|---|---:|---:|---:|
| IPR | **79,327** | 80,080 (long-80 buy-and-hold through +1,001 drift) | **99.1%** |
| ACO | **10,534.44** | ~12,277 (if crash_mode never fired) | ~86% |

## Primary failure: v17 bootstrap anchor flickered crash_mode on normal noise

**Mechanism:**
- Tick 0 ACO book was ASYMMETRIC: bid=9,998, ask=10,016, mid=10,007
- `_snap_anchor(10007) = 2 * round(5003.5) = 10,008` (banker's rounding)
- Frozen anchor at 10,008 shifted crash-trigger window to `[9,993, 10,023]`
- v14 hardcoded anchor=10,000 had window `[9,985, 10,015]`
- Observed ACO mid range: 9,986 → 10,015

**Quantified cost:**
- v17 crash_mode fired **512 ticks (5.1% of day)**
- v14 would have fired **0 ticks** (the asymmetric-book shift is what did us in)
- Per-tick PnL during crash_mode: **−1.263** (we actively LOST money)
- Per-tick PnL during normal mode: **+1.228**
- **v17 bootstrap cost: ~1,743 PnL** on ACO vs v14

**Episodes:** 200 distinct crash episodes, mostly 1-tick flickers around mids 9,990-9,992.

## Why this reversed the synthetic prediction

- Synthetic: v17 beat v14 by +2,748 across 13 regimes (ALT_FV wins dominate)
- Real Round 1: v17 LOST ~1,743 vs v14 on ACO alone
- Root cause: synthetic ACO always opens symmetrically at 10,000. Real Day 1 opened ASYMMETRICALLY with 7-unit bias toward ask, biasing anchor 8 ticks high
- **Synthetic regime generator missed the asymmetric-open-book failure mode**

## Why/How to apply

- **v17 bootstrap is NOT free insurance** — it costs real PnL when the open book is asymmetric
- For Round 2+: if the FV is expected to be stable/hardcoded-knowable, prefer v14's hardcoded anchor. Use v17's bootstrap only when there's genuine uncertainty about opening FV
- **Fix candidate:** delay bootstrap until book is SYMMETRIC (`|bid - ask - 2*spread_center| < threshold`) or use avg of first N symmetric mids
- **Alternative:** raise CRASH_THRESHOLD from 15 to ≥20 to absorb anchor bootstrap noise (sweep was done on synthetic where bootstrap lands on 10,000, so threshold=15 was optimal there but fragile on real)
- Update synthetic generator to include asymmetric-open regimes before re-validating bootstrap architectures

## Not-failure modes (confirmed OK)

- IPR drift capture: 79,327 = 99.1% of buy-and-hold max — near-perfect
- IPR max drawdown: 501 (negligible, structural entry cost)
- ACO position saturation: did NOT happen (fills continued uniformly through day)
- Drift_bias=5: well-calibrated for the observed drift rate (0.1001/tick × 50-tick horizon = 5)
- One-sided books: IPR 8.1% / ACO 7.3% of ticks — handled gracefully

## Dev-vs-Real via trading_analyzer.html (Superduperbread's tool)

Ran r1_v17 locally on day 0 10k ticks (BT result: 96,127 = IPR 79,460 + ACO 16,667) and compared to real 272466 via the HTML analyzer at `trader-logic/round-1/analyzer/trading_analyzer.html`.

**Key findings from the dev-vs-real comparison:**
- **IPR gap is negligible** (−133 PnL, 0.2%). Drift products are BT-reliable.
- **ACO gap is structural** (−6,133 PnL, −37%). Breakdown:
  - ~1,743 PnL from bootstrap-anchor crash_mode flicker (the failure we already identified)
  - ~4,400 PnL from structural BT-vs-real rate gap — dev normal-mode ACO rate is **2.5× real's** (+2.916 PnL/tick dev vs +1.189 PnL/tick real)
- **ACO spread identical both runs** (mean 16.18 both) — "higher volatility in real" hypothesis from teammates is NOT supported by the data.
- **Dev bootstrap anchor was 10,004 (day 0 open) vs real's 10,008 (day 1 open)** — 4-tick difference yielded 3.7× more crash episodes in real (199 vs 46).

**Implication:** even without any crash_mode flicker, real ACO would have scored ~11,890 (not 16,667). The 2.5× BT fill-rate overshoot is **unfixable without switching to a taker-aware simulator**. Dev logs should be divided by ~0.63 to estimate real ACO PnL for v17-style strategies.

**IPR vs ACO BT reliability rule:**
- IPR BT PnL ≈ real IPR PnL (within 0.2%)
- ACO BT PnL × 0.63 ≈ real ACO PnL (for v17-style inside-spread MM)

## Scaling observations

| Metric | Tutorial (1k) | Full (10k) | Ratio |
|---|---:|---:|---:|
| Total PnL (v4/v17) | 10,624.84 | 89,861.44 | 8.46× |
| IPR | 7,446 | 79,327 | 10.65× (beat 10× linear — strong drift day) |
| ACO | 3,179 | 10,534 | 3.31× (sub-linear — fill-rate limited, not tick-limited) |

ACO doesn't scale linearly with ticks because fills depend on taker arrivals (constant per unit time), not tick count. ACO's natural ceiling on a normal day is ~11-13k.
