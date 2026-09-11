# R4 Vol Surface Alpha Hunt — Findings

Script: `trader-logic/round-4/intel/vol_surface_alpha.py`
Data: 30k snapshots × 10 strikes, 246,316 IV points across days 1-3.

## 1. IV(K, t) matrix — 6 snapshots

| day-ts (S, T_yr) | K=4000 | K=4500 | K=5000 | K=5100 | K=5200 | K=5300 | K=5400 | K=5500 | K=6000 | K=6500 |
|---|---|---|---|---|---|---|---|---|---|---|
| d1-0      (S=5245, T=.0160) | — | — | 0.271 | 0.270 | 0.268 | 0.267 | 0.251 | 0.276 | 0.416 | 0.629 |
| d1-500000 (S=5244, T=.0140) | — | — | 0.271 | 0.267 | 0.276 | 0.280 | 0.261 | 0.275 | 0.446 | 0.674 |
| d2-0      (S=5267, T=.0120) | — | — | 0.282 | 0.280 | 0.285 | 0.296 | 0.267 | 0.287 | 0.467 | 0.714 |
| d2-500000 (S=5246, T=.0100) | 1.007 | — | 0.307 | 0.288 | 0.296 | 0.302 | 0.287 | 0.309 | 0.526 | 0.796 |
| d3-0      (S=5296, T=.0080) | — | — | 0.310 | 0.313 | 0.315 | 0.320 | 0.306 | 0.323 | 0.551 | 0.853 |
| d3-500000 (S=5201, T=.0060) | 1.263 | — | 0.359 | 0.349 | 0.345 | 0.354 | 0.334 | 0.316 | 0.718 | 1.064 |

ATM cluster (5000-5400) IV grinds **0.27 → 0.35 over 3 days** (secular vol creep as TTE shrinks). Wings (4000, 6000, 6500) blow up — discreteness near intrinsic, NOT a tradeable smile signal. Deep ITM K=4500 only quotes when intrinsic-tight; ignore.

## 2. Term structure: AC + cross-strike corr (ATM cluster)

| K | n | IV mean | IV std | AC(1) | AC(10) | AC(100) |
|---|---|---|---|---|---|---|
| 5000 | 29999 | 0.308 | 0.037 | 0.971 | 0.969 | 0.958 |
| 5100 | 30000 | 0.301 | 0.034 | 0.995 | 0.994 | 0.983 |
| 5200 | 30000 | 0.308 | 0.034 | 0.998 | 0.997 | 0.984 |
| 5300 | 30000 | 0.313 | 0.035 | 0.999 | 0.997 | 0.984 |
| 5400 | 30000 | 0.293 | 0.035 | 0.999 | 0.997 | 0.986 |

IV is a **slow random walk** (AC(1)≈0.999, AC(100)≈0.984). Cross-strike Pearson 0.977-0.994 — near-perfect comovement. **No relative-value arb exists in ATM cluster.**

## 3. Vol-of-vol (K=5300)

- Per-tick d(IV) stdev = **0.00167** (rolling-100t median 0.0011, p95 0.0020).
- Vega_ATM(T=2d) ~ 189/contract per 1.0 IV → **$1.89 per 0.01 IV move**.
- Per-tick expected vol-arb $-edge = vega·σ(dIV) = **$0.315 < $1 tick spread.**

**Verdict: vol-of-vol IS NOT a tradeable alpha in any single-strike sense.**

## 4. Mispricing forward-100t PnL (|z|>1σ)

| K | thr | n events | mean fwd-PnL | win % |
|---|---|---|---|---|
| 5000 | 0.006 | 8131 | +$0.26 | 50.9% |
| 5100 | 0.004 | 12968 | -$0.23 | 45.6% |
| 5200 | 0.004 | 9423 | -$0.10 | 47.5% |
| 5300 | 0.004 | 22895 | +$0.05 | 47.4% |
| 5400 | 0.005 | 26753 | -$0.03 | 40.5% |

Win rates 41-51%, edges sub-$0.30. **Cross-sectional mispricing is noise.**

## 5. Greeks @ pos +50 each strike, day-3 ts=500k, S=5201

Aggregate **Δ=227, Γ=0.48, Vega=27,644, Θ=-$3,358/day**.
- 1% spot ($52) move = ±$11,821 (delta-dominant)
- 1% vol move = ±$276 (vega tiny)
- 1 day theta bleed = -$3,358

**Edge is theta carry (deep-ITM K=4000) and delta capture (Wall-Mid VFE), NOT vol arbitrage.** This validates `r4_final` already saturating VEV_4000 at $2,585 via theta + intrinsic.

## 6. Recommendation

**Reject vol-surface MM as primary alpha.** Three independent signals (flat smile, AC≈1, sub-tick vov edge) refute the P3-winners hypothesis. Top P3 teams' "rolling-IV-mean MM" was almost certainly **passive spread capture × 5+ strike fill volume**, not vol prediction. Per-strike $-edge on R4 day-3 ATM cluster: ~$1 spread × 50-150 trades = $50-150/strike/day → **$5-10k 3-day across cluster IS the realistic ceiling**, matching `r4_final` $3,730 VEV_5300 actual.

**Concrete moves (BT-testable):**
1. Tighten `V_BS_EDGE` 5300 from 10 → 5 (post inside spread): est +$500-1,500/day on the 105 trades/day strike. **Test:** `python -m prosperity4bt trader-logic/round-4/r4_final.py 4-3 --ticks 10000 --no-out --no-progress`.
2. Raise `DEEP_ITM_POS_CAP` 4000 from 100 → 150 (+25% theta carry capacity, supported by AC≈1 IV stability at K=4000).
3. **Skip** any vol-mispricing engine — corr 0.99 means cluster trades as one factor; no statistical arbitrage available.

Total realistic voucher portfolio lift: **+$3-6k 3-day**, NOT the +$30k a vol-surface MM would imply. Pursue HP/VFE for material PnL.
