# R4 Manual Stress Test — Alternative Model Specifications

**Date**: 2026-04-27
**Engine**: `alt_models_v2.py` (chunked streaming MC, Welford running stats)
**Scope**: 24 base alt-specs + 18 extra break-point specs across σ, μ, microstructure ε
**Path budget**: 10M paths (GBM-class, 24 of 24), 2M paths (Heston/GARCH, 12 of 12), 5M paths (break-point sweep)
**Multiplier**: ×3000 PnL scalar (per-Prosperity precedent + team chat)

> **One-line conclusion**: OPTIMAL_7POS stays positive-EV across every realistic perturbation in the stated ranges (drift up to ±100%/yr, jumps up to λ=20/yr, vol-of-vol up to 0.5, microstructure ε up to 0.20, t-distribution down to df=3). It only goes **negative-EV when σ_true ≤ 2.15** (a 14% downward miscalibration of IMC's stated σ=2.51).

---

## 1. Strategies under test

| Name | Positions | Notes |
|---|---|---|
| **DROP_60C** | -50 CO, +500 KO, -50 BP, +50 P_2, +50 C_2 | Current 5-pos recommendation |
| **OPTIMAL_7POS** | DROP_60C + 50 P (3w) + 25 C (3w) | User's "with hedges" 7-pos |
| **USER_SAFE** | -10 CO, +60 KO, -10 BP, +10 P_2, +10 C_2 | Sizes ÷5 |
| **KO_ZERO** | DROP_60C minus the +500 KO | KO out |

> SD/unit columns are **per-path** SD × 3000 (single-simulation dispersion).
> Per-trial SD on score (averaging 100 sims) = SD/unit ÷ 10.
> So baseline OPTIMAL_7POS per-path SD = $2.64M → per-trial SD ≈ $264k, matching MANUAL_R4_FINAL.md.

---

## 2. Headline table — E[score] for each strategy across all 24 base specs (USD ×3000)

| Spec | DROP_60C | **OPTIMAL_7POS** | USER_SAFE | KO_ZERO |
|---|---:|---:|---:|---:|
| **GBM_baseline (σ=2.51, μ=0)** | **+163,376** | **+158,126** | +28,909 | +116,294 |
| GBM drift +5%/yr | +163,543 | +157,522 | +28,976 | +116,887 |
| GBM drift +10%/yr | +164,401 | +155,779 | +29,137 | +117,613 |
| GBM drift -5%/yr | +161,903 | +158,706 | +28,619 | +114,885 |
| GBM drift -10%/yr | +159,323 | +157,931 | +28,153 | +112,930 |
| Heston sv=0.1, ρ=-0.7 | +167,639 | +158,182 | +29,766 | +120,617 |
| Heston sv=0.1, ρ=0.0 | +163,907 | +157,780 | +29,055 | +117,325 |
| Heston sv=0.1, ρ=+0.7 | +162,780 | +160,845 | +28,638 | +113,802 |
| Heston sv=0.3, ρ=-0.7 | +167,782 | **+150,385** | +30,474 | +129,251 |
| Heston sv=0.3, ρ=0.0 | +160,729 | +157,827 | +28,343 | +113,189 |
| Heston sv=0.3, ρ=+0.7 | +159,406 | +163,944 | +27,752 | +107,790 |
| Heston sv=0.5, ρ=-0.7 | +172,719 | **+148,670** | +31,516 | +134,876 |
| Heston sv=0.5, ρ=0.0 | +164,780 | +156,505 | +29,271 | +118,714 |
| Heston sv=0.5, ρ=+0.7 | +157,752 | +168,287 | +27,114 | +102,296 |
| Merton λ=1, σ_J=0.1 | +161,435 | +157,221 | +28,599 | +115,340 |
| Merton λ=1, σ_J=0.3 | +165,739 | +158,202 | +29,288 | +117,488 |
| Merton λ=5, σ_J=0.1 | +164,683 | +157,548 | +29,211 | +118,111 |
| Merton λ=5, σ_J=0.3 | +174,794 | +161,201 | +30,546 | +119,632 |
| Merton λ=20, σ_J=0.1 | +166,688 | +157,076 | +29,594 | +119,895 |
| Merton λ=20, σ_J=0.3 | +212,186 | **+179,456** | +35,295 | +122,904 |
| Student-t df=3 (capped) | +315,027 | +133,645 | +49,872 | +150,854 |
| Student-t df=5 | +187,726 | +179,361 | +31,719 | +114,897 |
| Student-t df=10 | +171,078 | +165,079 | +29,870 | +116,755 |
| GARCH α=0.10, β=0.85 | +224,228 | +170,822 | +37,244 | +129,209 |
| GARCH α=0.05, β=0.90 | +188,365 | +164,336 | +32,320 | +121,452 |
| GARCH α=0.20, β=0.70 | +246,957 | +176,841 | +40,252 | +132,711 |
| MicroNoise ε=0.01 | +162,276 | +156,323 | +28,915 | +118,028 |
| MicroNoise ε=0.05 | +146,721 | +141,720 | +26,832 | +115,319 |
| MicroNoise ε=0.10 | +130,809 | +125,798 | +24,864 | +114,586 |
| MicroNoise ε=0.20 | +102,621 | +96,686 | +21,736 | +117,767 |
| **σ_true=2.30 (writeup-cited risk)** | +287,981 | **+61,966** | +48,807 | +178,116 |
| σ_true=2.40 | +223,684 | +103,877 | +38,561 | +146,485 |
| σ_true=2.45 | +197,920 | +129,789 | +34,471 | +134,004 |
| σ_true=2.55 | +141,102 | +178,441 | +25,322 | +104,868 |
| σ_true=2.60 | +115,718 | +205,044 | +21,242 | +91,942 |
| σ_true=2.70 | +66,075 | +259,481 | +13,082 | +64,408 |

---

## 3. Robustness ranking (E[score] across all 36 specs)

| Strategy | min(E) | max(E) | mean(E) | range | %neg |
|---|---:|---:|---:|---:|---:|
| DROP_60C | +6,243 (ε=0.5) | +505,308 (σ=2.0) | ~$197k | $499k | 0% |
| **OPTIMAL_7POS** | **−$38,512 (σ=2.0)** | +259,481 (σ=2.7) | ~$153k | $298k | small |
| USER_SAFE | +13,082 (σ=2.7) | +82,383 (σ=2.0) | ~$32k | $69k | 0% |
| KO_ZERO | +64,408 (σ=2.7) | +271,826 (σ=2.0) | ~$120k | $207k | 0% |

**Interpretation**:

- **USER_SAFE is the most robust** by range (smallest min-max swing). At ÷5 sizes, it's structurally insulated from σ-misspecification. But mean EV is also ÷5.
- **KO_ZERO** is the most σ-symmetric: KO is a pure long-vol bet on barrier survival; removing it gets you payoff symmetry around σ=2.51. But you forfeit ~$40k of expected score in the baseline.
- **DROP_60C beats OPTIMAL_7POS in mean(E)** by ~$44k across alt specs — the +50P+25C "hedges" are negative-edge under the σ=2.51 baseline (−$5,475 expected) but turn into a long-vol position that helps when realized vol > pricing vol.
- **OPTIMAL_7POS is the only strategy that ever goes negative** in the tested range (at σ=2.0 and ε≥0.75).

---

## 4. Where does OPTIMAL_7POS go negative-EV?

**Required deviation from σ=2.51 baseline**:

| Perturbation type | Break point | Margin from baseline | Realism |
|---|---|---|---|
| **σ_true low** | **σ ≤ 2.13** | **−0.38 (−15%)** | Plausible if IMC's stated σ is wrong |
| Microstructure ε (false barrier triggers) | ε ≥ 0.51 | 51% false-trigger rate | Not realistic — UI shows discrete reported S |
| Drift | No break in [−100%, +100%] | — | — |
| Heston (sv ≤ 0.5) | No break | — | Long-vol exposure of +50P+25C cancels chooser short-vol |
| Merton (λ ≤ 20, σ_J ≤ 0.3) | No break | — | Jumps actually HELP (long-vol bias from straddle dominates) |
| Student-t df | No break (capped at df=3) | — | — |
| GARCH | No break | — | Clustering preserves unconditional vol; OPTIMAL gains from realised-vol uplift |

**Linear extrapolation from σ-sweep**: at σ=2.10 OPTIMAL=−$11k; at σ=2.15 OPTIMAL=+$3k. Zero-crossing ≈ **σ_true ≈ 2.13**.

**What does that mean operationally?** IMC's stated σ=2.51 is calibrated to fit the 3w ATM 50C @ 12.025 quote. If IMC is gaming us and is internally using σ ≤ 2.13 to settle (a 15% downward miscalibration), OPTIMAL_7POS bleeds money — but the rest of the option market also reprices. There is **no mechanism** for IMC to publish σ=2.51 quotes and settle at σ=2.13: the binary BP @ 5.00 implies σ ≈ 2.51 by inversion, the 2w straddle @ 19.45 implies σ ≈ 2.47, etc. The cross-instrument IV consistency (writeup §1) is incompatible with σ_true ≤ 2.13.

**Microstructure ε=0.51 break point** is similarly far from any plausible UI behavior. At ε=0.20, score is still +$97k (61% of baseline).

---

## 5. Theoretical sign analysis vs. empirical findings

| Perturbation | Theoretical prediction | Empirical |
|---|---|---|
| **+drift** | Hurts KO (S drifts away from put strike) but helps chooser SELL | Mixed; small. OPTIMAL: $158k → $156k at +10%. Drift bias is symmetric in 3w. |
| **−drift** | Helps KO (more put ITM) AND chooser SELL (paths trapped near 50) | Slight help: $158k → $158k at −10%. KO breach risk offsets put-payoff gain. |
| **Heston ρ<0 (leverage)** | Hurts KO (down-moves with high vol breach barrier) | Confirmed: Heston sv=0.5 ρ=−0.7 drops OPTIMAL to $149k (worst Heston cell). |
| **Heston ρ>0** | Helps KO survival; hurts chooser short-vol | Confirmed: Heston sv=0.5 ρ=+0.7 lifts OPTIMAL to $168k (best Heston cell). |
| **Jumps** | If ↑ jumps, KO survives, BP rare; if ↓ jumps, KO breaches | OPTIMAL stays >$157k for all (λ, σ_J) — long straddle dominates. λ=20 σ_J=0.3 → +$179k. |
| **Fat tails (t)** | Should hurt KO (more frequent barrier touches) and chooser SELL | OPTIMAL: df=10 +$165k, df=5 +$179k, df=3 +$134k. Net positive — long straddle wins. |
| **GARCH** | Clustering preserves unconditional vol; option payoffs nearly unchanged | OPTIMAL: +$165 to +$177k. Slight uplift from clustering boosting tail mass. |
| **Microstructure on barrier** | Catastrophic for KO buyer | Confirmed monotone bleed: ε=0.01 −$2k, ε=0.05 −$16k, ε=0.10 −$32k, ε=0.20 −$61k. |
| **σ misspec low** | KO collapses to ≈0; CO put leg becomes ITM | Confirmed dominant risk. σ=2.0 → OPTIMAL −$38k. |
| **σ misspec high** | All long options gain; CO short and BP short hurt | OPTIMAL +$259k at σ=2.7 (long straddle + KO win). |

The big surprise — and the answer the user wanted — is that **the +50P+25C "hedges" in OPTIMAL_7POS aren't really hedges, they're a long-vol overlay**. They turn the strategy from σ-neutral into σ-positive. This is **good** (more realised vol = more PnL) up to the σ=2.51 baseline; it's **bad** when σ_true < quoted (you're paying time-decay on options you can't exercise productively).

---

## 6. Strategy-by-strategy robustness ranking (most → least robust)

| Rank | Strategy | Robustness profile |
|---|---|---|
| 1 | **USER_SAFE** | Tiniest range ($69k); never negative. But mean only $32k. The "tortoise" — survives anything, scores least. |
| 2 | **KO_ZERO** | Range $207k, never negative, mean $120k. Best Sharpe across alt specs (least sensitive to vol misspec). |
| 3 | **DROP_60C** | Range $499k, never negative in tested specs (tiny +$6k at ε=0.50, would go negative at ε≥0.55). Highest mean ($197k) but volatile. |
| 4 | **OPTIMAL_7POS** | Range $298k, **goes negative at σ ≤ 2.13** ($−39k worst). Mean $153k. The "hare" — wins on high-vol regimes, loses on low-vol. |

---

## 7. Recommendation by suspected model feature

| If you suspect... | Optimal vector |
|---|---|
| **Pure GBM σ=2.51 (baseline)** | **DROP_60C** (5 positions). +$163k, lowest variance Pareto-optimum. |
| **Realised vol > 2.51** (positive σ skew) | **OPTIMAL_7POS** strictly dominates DROP_60C: at σ=2.55 it's +$178k vs +$141k. The +50P+25C is a long-vol bet. |
| **Realised vol < 2.51** (negative σ skew) | **KO_ZERO**. KO collapses if σ low; KO_ZERO climbs to +$272k at σ=2.0. Don't bet on barriers. |
| **Heavy jumps (Merton-like)** | **DROP_60C**. Captures jump uplift without paying for the +50P+25C decay in calm jumps. |
| **Negative leverage (ρ<0 Heston)** | **DROP_60C** beats OPTIMAL_7POS by $24k under sv=0.5 ρ=−0.7. |
| **Microstructure barrier noise** | **KO_ZERO**. KO_ZERO is invariant to ε; OPTIMAL drops $61k at ε=0.20. |
| **High kurtosis (fat tails)** | **DROP_60C** (df=5: +$188k) or **OPTIMAL_7POS** (df=5: +$179k). Both score >baseline. |
| **Vol clustering (GARCH)** | **DROP_60C** (best in alt specs at +$224k for α=0.1). |
| **You distrust IMC's stated σ** | Hedge with **KO_ZERO**: insensitive to σ direction. |

**Operational meta-recommendation**: stick with **DROP_60C** (current MANUAL_R4_FINAL) unless you have a specific reason to believe σ_true > 2.51. The +50P+25C in OPTIMAL_7POS is **not a hedge**; it's a directional vol bet that costs ~$5k in baseline EV and amplifies σ-sensitivity. If you want a vol bet, do it consciously — but the cross-IV consistency in the quote sheet says σ_true is very close to 2.51.

---

## 8. Implementation notes

- 10M paths gives ±$830 SE on E[score] for OPTIMAL_7POS — sub-1% relative noise; differences ≥ $5k are statistically significant.
- GBM, Merton, Student-t cumsum-and-exp; Heston/GARCH require step-by-step path generation.
- Student-t df=3 needs Z-cap at ±6σ to avoid 1-in-10M lognormal overflow (df=3 is on the edge of pathological); reported number uses capped innovations so it's a slight UNDERestimate of fat-tail damage. Note that even with the cap, OPTIMAL_7POS stays positive ($+134k).
- Microstructure model: P(observed S < B | true S > B) = ε on each path, applied to KO survivors at terminal. This is harsher than per-step noise (a more realistic "noise on each observation" model would have higher break-point ε since not every false flip survives).
- Heston full-truncation Euler with ρ-correlated Z₁,Z₂.
- GARCH(1,1) with ω = (1−α−β)·σ²·dt to anchor unconditional variance to σ=2.51².
- BP, KO, chooser payoffs hardcoded matching `global_max.py` and `quant_audit.md`.

---

## 9. Files

- `alt_models_v2.py` — main 24-spec MC engine
- `_alt_models_breakpoint.py` — 18-spec break-point sweep (deeper σ, ε, μ)
- `alt_models_v2_output.txt` — text summary tables (24 specs)
- `alt_models_v2.md` — this report

---

## 10. Bottom line for the user

**OPTIMAL_7POS goes negative-EV under realistic perturbations only when σ_true ≤ ~2.13** (a 15% downward miscalibration of the stated σ=2.51). Every other tested perturbation — drift up to ±100%/yr, jumps λ ≤ 20/yr, Heston vol-of-vol up to 0.5, Student-t down to df=3, GARCH, and microstructure noise up to ε=0.50 — leaves OPTIMAL_7POS positive.

**The +50P+25C in OPTIMAL_7POS is NOT a hedge** — it's a long-vol overlay that costs $5k in baseline and turns the strategy σ-positive. **DROP_60C remains the better pick** for the σ=2.51 stated baseline because:
1. Higher baseline E[score] (+$5k).
2. Lower per-trial SD ($344k vs $264k... wait — this is wrong; OPTIMAL has *lower* path-level SD because long straddle dampens chooser SELL variance. Let me state correctly).
3. Wait — OPTIMAL_7POS per-path SD ($2.64M) is actually LOWER than DROP_60C ($3.45M). So OPTIMAL is mean-lower, SD-lower (worse Sharpe? Let me check: 158/264 = 0.60 vs 163/345 = 0.47. OPTIMAL has BETTER Sharpe).

> **Corrected recommendation**: OPTIMAL_7POS has **lower mean ($158k vs $163k)** but **lower SD ($264k vs $345k per trial)**, giving it **higher Sharpe (0.60 vs 0.47)**. Under the IMC scoring rule (mean of 100 sims), the per-trial SD shrinks by √100=10× either way, so the $5k EV gap matters more than the SD reduction. **DROP_60C is still the recommendation IF you trust IMC's σ=2.51.** OPTIMAL_7POS is better only if you believe σ_true > ~2.55 (then the +50P+25C wins enough to overcome the $5k decay cost).
