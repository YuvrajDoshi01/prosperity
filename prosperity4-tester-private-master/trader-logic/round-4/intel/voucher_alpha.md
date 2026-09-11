# R4 Voucher Alpha Hunt — Findings

Script: `intel/voucher_alpha.py` (run: `cd repo && python trader-logic/round-4/intel/voucher_alpha.py`)

## 1. Per-strike "perfect MM" PnL ceiling — Day 3, 10k ticks

Posting `[fv-edge, fv+edge]` against market trades (aggressor inferred from
trade-vs-fv sign; ambient prints split half-credit).

| K     | edge=2 | edge=4 | edge=6 | edge=8 | edge=10 |
|-------|-------:|-------:|-------:|-------:|--------:|
| 4000  |    479 |  1,043 |  1,607 |  2,230 |   2,191 |
| 5200+ |     0  |     0  |     0  |     0  |       0 |

Critical: VEV_4500/5000/5100 had only 1–2 trades on day 3 (DEAD strikes).
For 5200/5300/5400/5500, ALL trades print at `p ≈ wall_mid` (Mark 01 buys
from Mark 22 at fair market BBO). Trade-direction inference fails → ceiling
shows $0, but **r4_final actually makes $3,730 on VEV_5300** in the BT
because passive quotes get crossed by ambient flow modeled differently in
the matching engine.

**Real per-strike ceilings (from r4_final BT default day-3 10k):**
- VEV_4000: $2,585 (vs perfect-MM $2,230 → ALREADY ABOVE CEILING via
  intrinsic arb + theta carry, saturated)
- VEV_5300: $3,730 (winner)
- VEV_5400: −$192, VEV_5200: −$259 (adverse selection > spread capture)
- VEV_5100/5000/4500/5500/6000/6500: ≤ $50 each

## 2. Delta-hedged portfolio — Day 3 stats

Toy portfolio = +50 each of K∈[5000..5400] (n=250 long, +1.4M notional):

- Aggregate Δ range [122, 173], mean 144, std 8.5 (over 10k ticks)
- Spot range [5191, 5300] (drift −104 net negative)
- Unhedged Δ-PnL: **−$12,799** cumulative (drift loss if always long Δ≈144)
- Intraday std of unhedged path: $2,849
- |ΔΔ| > 10 rebalance triggers: only **15 events** over 10k ticks
  → very low hedge frequency required

**Implication.** A delta-hedged voucher MM ON A NEUTRAL portfolio (no
directional Δ) would protect ~$13k/day against spot drift and add a
**theoretical ceiling of $13k×3 = $39k** above current voucher PnL on
the 3-day BT — IF the smile stays flat AND we hedge via VFE (which has
its own VFE Wall-Mid MM that already runs).

## 3. Vol surface — Day 3

ATM IV ≈ **0.34** (NOT 0.18 as `V_BS_SIGMA_DEFAULT` assumes — adaptive
sigma rescues this within 15 ticks). Cross-strike IV mean per K:

| K    | IV mean | IV std | |z|>2 frequency |
|------|--------:|-------:|----------------:|
| 4500 | 0.815   | 0.119  | 2.6% |
| 5000 | 0.352   | 0.027  | 4.5% |
| 5100 | 0.343   | 0.021  | 2.2% |
| 5200 | 0.349   | 0.024  | 1.2% |
| 5300 | 0.354   | 0.024  | 1.8% |
| 5400 | 0.337   | 0.020  | 0.5% |

Smile is approximately flat in 5000-5400 (∆IV ≤ 0.02 = 6% relative).
**Vol-arb edge per option:** vega(K=5300) ≈ 1.0 × Δσ=0.02 → $0.02 per
voucher. **Below the 1-tick spread** ($1). Vol-arb is NOT a profitable
alpha at this surface flatness.

## 4. Why "delta-hedged voucher MM" likely got Seven Deuce $345k

Hypothesis: their alpha was NOT mispricing detection but **fill-rate × edge** at
volume scale across 5–6 strikes simultaneously, with VFE delta-hedge
recycling capital. Per-strike spread capture estimate:

- VEV_5300: 80 trades × 5 qty avg = 400 round-trip size × $1 edge = $400
- VEV_5400: 115 × 5 × $1 = $575
- VEV_5200: 32 × 5 × $1 = $160
- Sum across 5 strikes: ~$2,000/day → $6,000/3-day at 100% fill
- Multiply by 10k:1k ratio (ours BT 10k vs leaderboard 1k): irrelevant for
  final eval; final = 10k 3-day

The $345k cannot come from single-day capture. It MUST come from S17 GIGA
SHORT on HP scaled larger PLUS VFE Wall-Mid PLUS perfect voucher MM. Our
HP PnL is $38,693 day 3 alone — Seven Deuce probably has $250k+ on HP
combined, not vouchers.

**Re-classification:** voucher PnL ceiling is honestly ~$10–20k 3-day.
Closing the gap to top algo means improving HP/VFE primarily, with
voucher tightening as a $5–10k secondary lift.

## 5. Concrete recommendation: TWO LOW-RISK VOUCHER MICRO-OPTIMIZATIONS

Both tested in `trader-logic/round-4/r4_voucher_alpha.py`:

### A. Strike-specific MM size (5300=30, others=20)
- **Day-3 10k default mode:** $38,715 — IDENTICAL to r4_final
- Reason no improvement: 5300 had 80 trades over 10k ticks; current size 20
  already exceeds avg trade qty of ~3. Fill rate is exogenous.
- **Verdict: NEUTRAL.** Keep at 20.

### B. `V_BS_SIGMA_DEFAULT = 0.32` (replace hardcoded 0.18)
- **Day-3 10k:** −$29,200 vs r4_final ($9,512 vs $38,715)
- Catastrophic: in first 15 ticks before adaptive sigma kicks in,
  sigma=0.32 makes BS overprice → BS-take BUY threshold rises → buys
  4500/5100/5200 at top, holds through −104 spot move
- **Verdict: REJECT.** The 0.18 default is PROTECTIVE.

### C. Recommended actual upgrade — none from voucher portfolio.
Voucher alpha is exhausted at the r4_final architecture. The honest
$5–10k lift is from:
1. Bumping `DEEP_ITM_POS_CAP` from 100 to 150 on VEV_4000 (+25% theta carry capacity).
2. Adding tighter take-edge `V_BS_EDGE = 5` on VEV_5300 specifically.

But neither has been BT-tested in this session — propose for next iteration.

**Conclusion:** voucher portfolio is near its ceiling at r4_final. Pursue HP
expansion (e.g. wider z-score grid) or VFE alpha (counterparty mining beyond
r4_v6/v7) for the next material PnL bump.
