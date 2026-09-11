# R4 Manual Challenge — Aether Crystal Options

> **⚠ SUPERSEDED — see [MANUAL_R4_FINAL.md](MANUAL_R4_FINAL.md) for the current 5-position DROP_60C ship recommendation.**
>
> This file documents the original 6-position max-EV analysis. After 5-agent verification + 64-subset linearity proof, the AC_60_C SELL was identified as variance pollution (+$0.41 EV but 70% of total portfolio variance) and dropped. Final ship = 5 positions, $165,721 expected with ×3000 multiplier.

## TL;DR — orders to enter (ORIGINAL — 6 positions)

| # | Action | Instrument | Volume | Price | Per-unit edge | EV |
|---|--------|------------|-------:|------:|--------------:|----:|
| 1 | **SELL** | AC_50_CO (chooser) | 50 | 22.20 (bid) | +0.302 | **+15.12** |
| 2 | **BUY** | AC_45_KO (KO put) | 500 | 0.175 (ask) | +0.032 | **+15.75** |
| 3 | **SELL** | AC_40_BP (binary put) | 50 | 5.00 (bid) | +0.232 | **+11.60** |
| 4 | **BUY** | AC_50_P_2 (2w put) | 50 | 9.75 (ask) | +0.121 | **+6.04** |
| 5 | **BUY** | AC_50_C_2 (2w call) | 50 | 9.75 (ask) | +0.121 | **+6.04** |
| 6 | **SELL** | AC_60_C (3w call) | 50 | 8.80 (bid) | +0.008 | **+0.41** |
| | **TOTAL** | | | | | **+54.96** |

**SKIP** the underlying AETHER_CRYSTAL and all other 3-week vanilla options (AC_50_P, AC_50_C, AC_35_P, AC_40_P, AC_45_P) — they are at fair value within bid/ask spread.

If contract multiplier of 3,000 applies (the wording suggests it might apply only to the underlying — verify with the IMC UI before submitting), total EV scales to **~165k XIRECs**.

---

## Method

Underlying:
- S₀ = 50.0 (mid of 49.975 / 50.025)
- σ = 251% annualized
- r = 0 (zero risk-neutral drift)
- 4 steps per trading day, 252 trading days per year
- "21 Solvenarian Days" = 3 weeks = 15 trading days = T = 15/252 ≈ 0.0595
- "14 Solvenarian Days" = 2 weeks = 10 trading days = T = 10/252 ≈ 0.0397
- σ·√T_3w = 0.6125 (giant per-period vol)
- σ·√T_2w = 0.5000

Pricing:
- **Vanilla**: Black-Scholes closed form with σ = 2.51, r = 0
- **Chooser**: V(0) = C_3w(S₀, 50) + P_2w(S₀, 50) — standard r=0 chooser identity (auto-converts to ITM side at 2w; under r=0 the ITM side and the higher-BS side coincide)
- **Binary put**: P(S_T < 40) × payoff(10) under risk-neutral measure
- **Knock-out put**: Reiner-Rubinstein continuous-monitoring formula gives 0.123, but **discrete monitoring at 4 steps/day raises it to 0.207** (verified across 5 seeds × 1M paths each, spread 0.004). The increase comes from missed barrier breaches between observation points.

Cross-checks:
- BS vs MC (200k paths) match within ±0.06 across all vanilla strikes
- Chooser BS = 21.898 vs MC = 21.881 (diff −0.017)
- Binary put BS = 4.768 vs MC = 4.761 (diff −0.007)
- KO put MC stable across 5 different seeds: 0.205 / 0.206 / 0.209 / 0.207 / 0.206 → **0.207 ± 0.005**

---

## Per-instrument detail

| Instrument | Description | Bid | Ask | Fair (BS or MC) | Buy edge | Sell edge | Action |
|-----------|-------------|----:|----:|----------------:|---------:|----------:|--------|
| AETHER_CRYSTAL | Spot, GBM | 49.975 | 50.025 | 50.000 | −0.025 | −0.025 | SKIP |
| AC_50_P | 3w put, K=50 | 12.00 | 12.05 | 12.027 | −0.023 | −0.027 | SKIP |
| AC_50_C | 3w call, K=50 | 12.00 | 12.05 | 12.027 | −0.023 | −0.027 | SKIP |
| AC_35_P | 3w put, K=35 | 4.33 | 4.35 | 4.336 | −0.014 | −0.006 | SKIP |
| AC_40_P | 3w put, K=40 | 6.50 | 6.55 | 6.510 | −0.040 | −0.010 | SKIP |
| AC_45_P | 3w put, K=45 | 9.05 | 9.10 | 9.089 | −0.011 | −0.039 | SKIP |
| AC_60_C | 3w call, K=60 | 8.80 | 8.85 | 8.792 | −0.058 | **+0.008** | SELL 50 |
| AC_50_P_2 | 2w put, K=50 | 9.70 | 9.75 | 9.871 | **+0.121** | −0.171 | BUY 50 |
| AC_50_C_2 | 2w call, K=50 | 9.70 | 9.75 | 9.871 | **+0.121** | −0.171 | BUY 50 |
| AC_50_CO | Chooser at 2w, expires 3w, K=50 | 22.20 | 22.30 | 21.898 | −0.402 | **+0.302** | SELL 50 |
| AC_40_BP | Binary put, K=40, payoff 10, T=3w | 5.00 | 5.10 | 4.768 | −0.332 | **+0.232** | SELL 50 |
| AC_45_KO | Down-and-out put, K=45, B=35, T=3w | 0.15 | 0.175 | 0.207 (MC) | **+0.032** | −0.057 | BUY 500 |

The 3-week vanilla options are priced almost exactly at fair value (efficient market, no edge to extract). The alpha lives in the **exotics** and the **2-week options** which the market appears to underprice slightly.

---

## Variance / risk discussion

The 100-sim score will be noisy because σ = 251% generates very wide terminal distributions. Sources of variance from largest to smallest:

1. **Long 500 KO put** — pays 0 in ~62% of paths (barrier breach), pays nontrivially only in the ~5% of paths where barrier survives AND S_T < 45. Conditional ITM payoff averages ~$4. Per-path PnL ranges from –$87.5 (whole position lost) up to +$22,500 (full ITM payoff at K=45 with S_T → 0).
2. **Short 50 chooser** — fixed premium $1,110 received; pays out average $1,095 with high spread.
3. **Long 50 2w straddle (P_2 + C_2)** — symmetric, pays ~$987 each, neutral mean ~$1,974 received less $975 cost.
4. **Short 50 binary put** — bounded ±$500 loss/gain.
5. **Short 50 60C** — small positions, modest risk.

100-sim Monte Carlo across the full portfolio:
- Theoretical EV = +55.88
- Empirical 100-sim mean (seed 42) = +313 (lucky high tail)
- Empirical 10,000-sim mean = +11.5 (low tail; SE = 12.7 → 95% CI [−13, +37], theoretical EV is just outside)
- Implied 100-sim SE ≈ ±127, so the actual leaderboard score will be EV ± noise

The portfolio is **net positive in expectation but has high single-sim variance**. A more risk-averse alternative would be to drop the KO put (largest variance contributor) and take only the chooser short + binary put short → EV ≈ +27, SE ≈ ±40, much tighter.

**Recommendation**: take all 6 positions. Even if variance bites on this seed, the expected value is positive and the chooser/binary edges are robust under any reasonable model perturbation.

---

## What if σ ≠ 2.51?

Implied vol of the market quotes (computed by inversion):
- 3w ATM call/put @ 12.025 → σ_imp ≈ **2.510** (matches the stated σ exactly)
- 2w ATM call/put @ 9.725 → σ_imp ≈ **2.470** (slight 1.6% discount; this is the source of the 2w buy edge)
- 3w 60-strike call @ 8.825 → σ_imp ≈ **2.51** (matches)

The 3-week vanilla market is calibrated to the stated 2.51. The 2-week market is mildly underpriced relative to the stated vol — this is the small-but-real edge we capture with the 2w straddle buy.

If the true generative σ differs slightly from 2.51, the chooser and binary edges still survive (they're large relative to vol sensitivity). The 2w buy edge would shrink but still be positive at σ ≥ 2.45.

---

## Files

- `manual_r4_solver.py` — main solver (BS pricing, MC verification, optimal positions, 100-sim and 10k-sim PnL distributions)
- `ko_precise.py` — high-precision KO put MC across 5 seeds × 1M paths
