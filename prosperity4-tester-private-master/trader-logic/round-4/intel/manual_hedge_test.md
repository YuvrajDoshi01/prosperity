# R4 Manual — Vanilla Hedge Overlay Test (Synthia hint #4)

**Date**: 2026-04-27 | **Engine**: `manual/hedge_overlay_test.py` (mirrors `r4_simulation_FINAL.py`)
**Paths**: 50M × 2 seeds (20260427, 31415927) = 1M trials of 100 sims each, common random numbers

## Hypothesis (per Synthia hint)

DROP_60C carries two unhedged structural cliffs:
- **Binary put SELL** (AC_40_BP) jumps `$0 → $10` at `S_T = 40`
- **Knock-out put BUY** (AC_45_KO B=35) is extinguished at `min_S < 35`, exact zone of tail loss

A long 3-week vanilla put at `K=40` partially neutralizes the BP cliff (pays `max(40-S_T, 0)` exactly where the SELL hurts). A long put at `K=35` provides uncapped down-protection past the KO barrier, where DROP_60C's payoff goes most negative.

## Variants tested (all = DROP_60C base + add-on)

| ID | Add-on | Cost upfront (3000×) |
|---|---|---:|
| H1 | +25 AC_40_P | -$491,250 |
| H2 | +50 AC_40_P | -$982,500 |
| H3 | +25 AC_35_P | -$326,250 |
| H4 | +50 AC_35_P | -$652,500 |
| H5 | +25 AC_40_P + +25 AC_35_P | -$817,500 |
| H6 | +50 AC_40_P + +50 AC_35_P | -$1,635,000 |
| H7 | +25 AC_40_P + +50 AC_35_P | -$1,143,750 |

## Results — paired delta vs DROP_60C (avg of 2 seeds, 50M paths each)

| Variant | dMean | dCVaR-5% | dCVaR-2% | dSharpe | dP(>0) | t-stat | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| H1_40P25 | -$3,074 | +$24,564 | +$26,554 | +0.0147 | +0.71 pp | -32.8σ | accept |
| H2_40P50 | -$6,150 | +$22,372 | +$22,935 | +0.0107 | +0.74 pp | -32.8σ | accept |
| H3_35P25 | -$1,064 | +$21,356 | +$23,188 | +0.0157 | +0.69 pp | -14.5σ | accept |
| **H4_35P50** | **-$2,128** | **+$26,280** | **+$27,750** | **+0.0205** | **+0.99 pp** | -14.5σ | **accept ★** |
| H5_40P25_35P25 | -$4,139 | +$25,300 | +$26,443 | +0.0164 | +0.90 pp | -24.8σ | accept |
| H6_40P50_35P50 | -$8,278 | -$28,268 | -$36,564 | -0.0263 | -0.50 pp | -24.8σ | reject (over-hedged) |
| H7_35P50_40P25 | -$5,204 | +$10,588 | +$8,092 | +0.0057 | +0.45 pp | -21.7σ | reject (CVaR < $15k) |

(All accept-flagged variants meet acceptance criteria: dMean > -$15k, dCVaR-5% > +$15k, dSharpe > 0.)

## Pareto frontier — H4_35P50 strictly dominates

H4 is the **single Pareto-optimal variant** along (mean, CVaR-5%, Sharpe):
- vs H3: same put, double size → 2× CVaR improvement at 2× the (tiny) mean cost
- vs H5: identical risk reduction, lower mean cost (-$2.1k vs -$4.1k)
- vs H1/H2: better Sharpe AND better tail at lower cost
- H6 over-hedges: 50 of each puts all the way through the cliff → loses both EV (BS edge accumulates) AND tail (vega-positive into low-prob deep-OTM where σ=2.51 fattens upside).

## Mechanism check (why K=35 > K=40 here)

The marginal PnL contribution of the BP-SELL cliff is bounded: -$10 × 50 = -$500/path × 3000 = -$1.5M *only* when S_T < 40 (~12% of paths). The KO-BUY tail is *unbounded* below B=35 — the strategy is +$45 × 500 × 3000 = $67.5M long delta in the K=35 zone but the KO extinguishes it. A K=35 put gives uncapped `max(35-S_T, 0)` exactly where the KO failed. Hedging that catastrophic asymmetry buys more CVaR per BS edge dollar.

## Recommended portfolio — DOM_NICE_v2 (DROP_60C + H4)

| # | Action | Instrument | Vol | Price | Rationale |
|---|---|---|--:|---:|---|
| 1 | SELL | AC_50_CO | 50 | 22.20 | chooser BS edge |
| 2 | BUY | AC_45_KO | 500 | 0.175 | KO mispricing alpha |
| 3 | SELL | AC_40_BP | 50 | 5.00 | BP overpriced |
| 4 | BUY | AC_50_P_2 | 50 | 9.75 | 2w put gamma |
| 5 | BUY | AC_50_C_2 | 50 | 9.75 | 2w call gamma |
| 6 | **BUY** | **AC_35_P** | **50** | **4.35** | **★ NEW — KO-tail + BP-cliff hedge** |

**Headline at 50M × 2 seeds:** E[score] ≈ **$163k** (DROP_60C $164k → -$2.1k), CVaR-5% **-$524k** (DROP_60C -$551k → +$26.3k), Sharpe **0.498** (DROP_60C 0.475 → +0.020), P(>0) **69.4%** (vs 68.4%).

Trade-off: give up 1.3% mean ($2.1k) for 4.8% tail tightening ($26.3k CVaR-5%) and +4.3% Sharpe. Synthia's hint **does** materially help — the K=35 put softens the KO-tail asymmetry that BS-fair pricing of the KO ignored.

## Files
- `trader-logic/round-4/manual/hedge_overlay_test.py` — test harness
- `trader-logic/round-4/manual/hedge_overlay_50M.json` — seed 20260427 results
- `trader-logic/round-4/manual/hedge_overlay_50M_seed2.json` — seed 31415927 results
- `trader-logic/round-4/manual/hedge_overlay_50M_stdout.txt` — full console output
