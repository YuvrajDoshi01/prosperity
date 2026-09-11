# R4 Manual — Hidden Alpha Hunt v2

**Date**: 2026-04-27
**Author**: Claude Opus 4.7 (1M)
**Goal**: Exhaustive second-opinion arb hunt across all 12 instruments. Verify nothing was missed by `quant_audit.py`.

## TL;DR — No new alpha found

Out of **59 multi-leg combos** spanning every category the user listed (boxes, conversions, reversals, calendars, ratios, choosers, butterflies, strangles, iron condors/flies, BP-via-spread, KO bounds), **zero produce a risk-free positive PnL**. The top +EV combos all decompose linearly into the per-instrument edges already captured by the recommended portfolio (DROP_60C). Recommendation: ship DROP_60C as planned.

## Methodology

Each combo is evaluated by:

1. `cash_flow_today` — using `bid` for sells, `ask` for buys (worst-case execution)
2. `terminal_payoff` over a dense grid of (S_3w, S_2w) ∈ [1, 100] × [1, 100], stepping 0.5, plus barrier hit/no-hit for KO instruments
3. `lower_bound_pnl = cash_flow + min(terminal_payoff)` — if positive, true static arb
4. `ev_at_fair = cash_flow + Σ qty · BS_fair(sym)` — expected PnL under our model

Verified against 1M-path GBM Monte Carlo (`hidden_alpha_v2_mc.py`). MC matches BS within < 1bp on all instruments (chooser, 2w/3w straddles, BP, KO, P45).

## Results

| Category | Combos | Arbs found | Best EV | Verdict |
|----------|--------|------------|---------|---------|
| Conversions / Reversals (K=50, 3w & 2w) | 4 | 0 | -0.075 | clean (PCP holds at half-spread) |
| Cross-expiry synthetic forwards vs spot | 4 | 0 | -0.075 | clean |
| Calendar synthetic forwards (3w vs 2w) | 2 | 0 | -0.100 | clean |
| Calendar diagonals (same K, same right) | 4 | 0 | +0.094 | small mid edge, no arb |
| Put ratio spreads (1x2, 2x1) | 12 | 0 | -0.030 | clean |
| Call ratio spreads (50/60) | 4 | 0 | -0.007 | clean |
| Chooser replicators / bounds | 6 | 0 | +0.544 | sum of known edges |
| Put butterflies (4 triples × 2 dirs) | 8 | 0 | -0.044 | clean (all positive cost) |
| Call vertical / strangles / iron condor / iron fly | 9 | 0 | -0.001 | clean |
| BP digital replication via put-spread | 3 | 0 | +1.143 | non-arb digital approx |
| KO put structural bounds | 2 | 0 | +0.003 | KO ≤ vanilla holds tightly |
| Chooser + BP composite (4-leg) | 1 | 0 | +0.632 | sum of known edges |
| **TOTAL** | **59** | **0** | — | static-arb-free |

## Detailed analysis of top "+EV" combos

### #1: SELL 5×BP(40), BUY P(45), SELL P(35) — EV +1.143

`legs: [('AC_40_BP', -5), ('AC_45_P', +1), ('AC_35_P', -1)]`

This is the digital-via-put-spread approximation. Note: BP(40) is a 10-payoff cash-or-nothing if S_3w ≤ 40; the put-spread P(45)-P(35) divided by 5 approximates a **centered finite-difference** estimate of the digital. Mean error in the BS smile = 0.014 — small but the **gamma of the digital is much spikier than the spread**, so the static lower bound is -24.77 (catastrophic in fat-tail regions S ∈ [38, 42]).

**Decomposition**: this combo packs together SELL 5×BP (5 × +0.232 = +1.16) − the cost of buying P(45) - P(35) at a slightly off-fair price (-0.014). Almost entirely the BP-sell edge already captured at sell size 50 in the recommended portfolio.

### #2: SELL chooser, SELL BP(40), BUY C_3w(50), BUY P_2w(50) — EV +0.632

This is the chooser-replicator (BUY C_3w + BUY P_2w = static identity for chooser) **plus** sell BP. EV = chooser-sell-edge (+0.302) + replication slack via the buy spreads (+0.098) + BP-sell edge (+0.232) = +0.632. Confirmed by linear decomposition.

The BS-MTM = -4.77 reflects the BP intrinsic; the +5.40 cash flow nets to +0.63 under fair valuation. But as a 4-leg position, the convex risk in the tail (PnL bounds [-54.83, +55.40]) makes this far more volatile than just doing the components separately.

### #3: SELL chooser, BUY 2w straddle (BUY C_2w + BUY P_2w) — EV +0.544

This **looks** like an interesting 3-leg but is just chooser-sell (+0.302) + 2w-straddle-buy (2 × +0.121 = +0.242) = +0.544 exactly.

**Pathwise verification (1M MC)**: chooser − 2w_straddle = +2.156 (matches static identity 21.898 − 19.741 = 2.157). The combo's edge is purely the spread on chooser sale and 2w-straddle purchase — already in DROP_60C.

**Important property**: `chooser ≥ 2w_straddle` PATHWISE (Rubinstein r=0 inequality). So this 3-leg combo has a **bounded loss** of ~$4.32/unit if held to expiry — but doesn't dominate the simpler doing-them-individually approach, because we'd need to short chooser AND buy 2w straddle in matched quantities (50 chooser × 2.156 = $107.80 expected loss to balance against $135 received cash, very tight).

### #4: SELL chooser, BUY synthetic chooser (C_3w + P_2w) — EV +0.400

The classic Rubinstein chooser-replicator. Static identity holds: `chooser_T,t1 = C_T(K) + P_t1(K)` (r=0). Replication is exact path-by-path (no model risk). EV = chooser-sell-edge − replicator buy-spread cost = (22.20 − fair 21.898) − (replicator-ask 21.80 − fair 21.898) = +0.302 + 0.098 = +0.400.

**This is the cleanest combo** — but its EV is identical to the linear sum of the per-instrument edges, and SD per unit (~$0.05) makes it negligible at any safe size.

### #5–9 (calendars +0.094 ea, KO/P45 +0.003)

All small bid-ask noise on closely-fair pairs. None offer above-noise edge.

## Convex bound sanity check

| Slope check | Bid lift | Ask lift | Bound |
|---|---|---|---|
| P(40)-P(35) | +2.150 | +2.220 | width 5 → both ∈ [0, 5] ✓ |
| P(45)-P(40) | +2.500 | +2.600 | width 5 ✓ |
| P(50)-P(45) | +2.900 | +3.000 | width 5 ✓ |
| C(60)-C(50) | -3.250 (sell-50/buy-60 net cost) | width 10 ✓ |

All vertical spreads respect 0 ≤ slope ≤ Δstrike. No monotonicity violations.

Put butterflies — all four triples positive at every quote combination:
- Bfly 35/40/45 mid +0.365, worst-case cost +0.450 (positive ✓)
- Bfly 40/45/50 mid +0.400, worst-case cost +0.500 (positive ✓)
- Broken-wing 35/40/50 cost +3.40 (consistent with K-distance asymmetry)
- Broken-wing 35/45/50 cost +1.70 (consistent)

## What about combos NOT tested?

The user's task list mentioned a few categories I confirmed are infeasible:

1. **Box spreads at K1, K2** — require P AND C at both strikes. We only have C+P pair at K=50 → no boxes constructible.
2. **Calendar boxes** — would lock in interest rate; r=0 → would need exact 0 payoff, no edge.
3. **Knock-in put synthesis** — requires BUY vanilla P(45) + SELL KO. Net cost 8.95 vs fair KI 8.88 = -0.07 EV (unfavorable, not arb).
4. **Binary call (BC) at K=40** — not traded. Cannot arbitrage.
5. **Higher-strike calls (e.g. K=70, 80)** — not traded.

## Conclusion

**The market is static-arb-free at the 0.5-cent grid.** All bid-ask spreads are 0.025–0.05, which exceeds any deviation between BS-fair and mid. Every signed multi-leg combination either:
- Has a spread cost ≥ its mid-vs-fair edge, OR
- Is a linear combination of single-leg edges already known.

**Stick with DROP_60C** (5-position recommendation from the prior analysis):
- SELL 50 chooser (+15.12 EV)
- BUY 500 KO (+15.27 EV)
- SELL 50 BP (+11.60 EV)
- BUY 50 P_2 + BUY 50 C_2 (= 2w straddle, +12.08 EV)
- (No 60C position)

Expected PnL at fair: **+54.07/unit-set** = **$162,210 at ×3000 multiplier** before noise.
Pareto-dominates GLOBAL_MAX (with 60C): same EV, 42% lower SD, 70% P(score>0).

## Files

- `hidden_alpha_v2.py` — main combo enumerator (59 combos)
- `hidden_alpha_v2_output.txt` — full run output
- `hidden_alpha_v2_results.json` — top-10 EV summary
- `hidden_alpha_v2_mc.py` — 1M-path MC verifier
- `hidden_alpha_v2_mc_output.txt` — MC output (chooser/straddle/BP/KO match BS within 1bp)
