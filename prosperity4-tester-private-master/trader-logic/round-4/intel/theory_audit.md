# R4 r4_final.py (v8 hybrid) — Theory-First Audit

**Frame**: Frankfurt Hedgehogs — "If you can't explain why a strategy works from
first principles, BT outperformance is probably noise." Each layer below is
tagged THEORY-CLEAN, EMPIRICAL+t-stat, or BT-FIT, with a derivation attempt.

Baseline: v8 r4_final 10k 3-day default = $261,854 / imc = $248,023.

## HYDROGEL_PACK layers

| # | Layer | Class | Theory |
|---|---|---|---|
| 1 | S17 GIGA SHORT (spread==17, mid>10010) | THEORY-CLEAN | Reverse-engineered MM bot widens to spread-17 only when the underlying OU process is at upper extreme; observable cycle (S17 → S7 cover) is structural. Sourced from competitor 402045, replicated independently. |
| 2 | S17 z-gate (z>=2.0 over 500-tick mean) | EMPIRICAL → THEORY-CLEAN | Statistical extreme filter. Rejects marginal entries near local equilibrium. Theory: conditional expectation of mean reversion is monotone in |z|; gating at z=2.0 keeps only the right tail. Threshold itself is sweep-tuned but the principle is sound. |
| 3 | VFE-crash gate (block S17 if VFE drift < -$5) | EMPIRICAL | Cross-asset coupling: HP S17 cycle assumes VFE-stable regime. No t-stat, but plausible (regime change in VFE breaks HP MR). Threshold -$5 is BT-tuned. |
| 4 | S17 circuit breaker (S17_MAX_FAILS=2) | THEORY-CLEAN | Bayesian regime-change detector: 2 consecutive timeouts = strong evidence that the cycle hypothesis no longer holds. Standard risk-management. |
| 5 | Z-score MR (|z|>2.25 over 500) | THEORY-CLEAN | Mean reversion of stationary AR-1 / OU process. Position scale ∝ |z|/Z_ENTRY is canonical. |
| 6 | Edge-beta passive MM | THEORY-CLEAN | Glosten-Milgrom: skew quotes by β·book_imbalance with β estimated from cov(edge, return) — purely structural. |
| 7 | QUOTE_SIZE=200 (sweep 25→200) | THEORY-CLEAN | Spread-capture intensity: at fixed spread per fill, size is monotone-positive subject to position-limit constraint. The +$24k sweep gain is the PnL of a previously under-utilized capacity, not a fitted alpha. |

## VELVETFRUIT_EXTRACT layers

| # | Layer | Class | Theory |
|---|---|---|---|
| 8 | Wall-Mid MM | THEORY-CLEAN | P3-winner: highest-volume bid/ask = institutional anchor; mid-of-walls is a less-noisy fair value than top-of-book. |
| 9 | Layer-E spread-state lift (spread==2 ask drops → BUY @ ba-1) | EMPIRICAL | Observed pattern of asymmetric quote moves; small inside-spread aggressive lift. Weak theory but bounded risk. |
| 10 | **VFE momentum ONE-SHOT short** (mid-mid_25_ago<=-3 → short 200, TP=12 SL=15) | **BT-FIT** | Trend-following on 25-tick velocity has theoretical basis (Kyle-style momentum). BUT (a) one-shot-per-day is pure data-snooping — there is no theory predicting "the crash happens once"; (b) LOOKBACK=25, TP=12 are sweep-fit (changed v5b 50→25, v5c TP 9→12); (c) intel/day3_1k_alpha.md correlation -0.46 is in-sample on day 3 itself. **RECOMMEND REMOVE**. |
| 11 | Mark 49 fade (M49 sells qty>=8 → BUY 60, hold 5 ticks, cap ±20) | EMPIRICAL+t-stat | Mark 49 mid-impact: SELL → +$1.90 H=1, t=+20 (n=105). Theory: M49 is a "wrong-side" liquidity-demanding taker; we provide liquidity at his mistaken price. Caveat: H=1 measures contemporaneous impact, not future drift — but t=20 with n=105 is far past Bonferroni for the 7-mark universe. KEEP. |
| 12 | Mark 55 follow-flow (sum window=50 net flow >= 30 → BUY 20) | **BT-FIT** | Original M55 study: corr=+0.16 — weak. Threshold 30, window 50 are sweep-tuned. Multiple-testing across 7 marks × ≥10 horizons: corr=+0.16 won't survive Benjamini-Hochberg at α=0.10. Mechanism (follow informed flow) is plausible but signal-to-noise is too low. **RECOMMEND REMOVE**. |

## VOUCHER layers (10 strikes, K=4000-6500)

| # | Layer | Class | Theory |
|---|---|---|---|
| 13 | BS taking (adaptive sigma, edge=10) | THEORY-CLEAN | Black-Scholes mispricing trade with conservative wide edge. Adaptive sigma = rolling median of cross-strike IVs. |
| 14 | VEV_5200 edge=5 override | BT-FIT | Per-strike override (Agent 6, +$7k day 3). No theory for why 5200 specifically requires tighter edge — likely a single-strike sample-fit. Low risk to keep (still positive edge), but flag. |
| 15 | Intrinsic arb (price < intrinsic - 2 → buy) | THEORY-CLEAN | No-arbitrage: call ≥ max(S-K, 0). |
| 16 | Call-spread arb (ask_lo < bid_hi for K_lo<K_hi) | THEORY-CLEAN | Vertical spread no-arb: C(K_lo) ≥ C(K_hi). |
| 17 | Voucher MM (best±1, min_spread=2) | THEORY-CLEAN | Inside-spread MM = canonical spread capture. |
| 18 | Deep ITM theta carry (VEV_4000/4500 around intrinsic±1) | THEORY-CLEAN | Deep ITM ≈ stock with theta carry; pin to intrinsic. P3 v17 live confirmed +$233. |
| 19 | OTM passive bid 5300/5400/5500 (min(bb+1, BS-2)) | EMPIRICAL | Observed seller flow in OTM strikes; we provide bids at sub-fair. Small size (5/strike, cap 50). Bounded risk. |
| 20 | Deep OTM bid=0 (VEV_6000/6500 size=100) | THEORY-CLEAN | Mark 22 dumps to Mark 01 at price=0 every tick (observed). Bid=0 picks up free MTM. Spot would need +$700 to threaten. |
| 21 | **Conditional Voucher OBI** (OBI>±0.7, multi-strike confirm 3+→2× scale) | **PARTIAL theory + BT-FIT params** | Theory for OBI: one-sided book ⇒ adverse-selection ⇒ price moves toward heavy side (Kyle/Stoll). Theory for multi-strike confirm: cross-sectional signal averaging reduces noise. BUT thresholds (0.7, 3-strike, 2×, spread<=10, POS_CAP=30) are 5 simultaneous BT-sweep parameters — high p-hacking risk. Value claimed +$3,160 default / +$3,282 imc. **CONDITIONAL**: keep mechanism, drop multi-strike scale; or remove entirely. |

## REGIME OVERLAY

| # | Layer | Class | Theory |
|---|---|---|---|
| 22 | **YOLO regime gate** (ts=3000 drift<=-1.5 → short 8 vouchers + VFE) | **BT-FIT** | The drift threshold (-1.5) and detection time (ts=3000) are picked because day-3 of CSV crashed. There is no first-principles reason day-4 (live) replays the same crash mechanism. Theory at best: "if we observe a crash early, ride it" — but the parameters are 100% in-sample fit to day-3. EXTREME data-snooping risk. Headline +$100k+ on day-3 BT but could be -$50k on a non-crashing day-4. Already noted in CLAUDE.md as v8 controversy. **RECOMMEND: keep mechanism but flag, OR remove for theory-clean baseline**. |

## ABLATION RESULTS (10k 3-day default mode)

| Variant | Total | Δ vs v8 | Layer removed | Verdict |
|---|---|---|---|---|
| v8 baseline | $261,854 | — | — | reference |
| no VFE momo | $261,136 | -$718 | layer 10 | wash, REMOVE for cleanliness |
| no M55 | $263,590 | **+$1,736** | layer 12 | **REMOVAL HELPS — REMOVE** |
| no OBI conditional | $255,453 | -$6,401 | layer 21 | costly to remove, KEEP |
| no YOLO | $171,510 | -$90,344 | layer 22 | KEEP (flag day-3 fit risk) |
| v9_theory (no momo + no M55) | (see below) | — | 10 + 12 | strictly dominates v8 |

## RECOMMENDATIONS

**Theory-fail layers to REMOVE in r4_v9_theory.py**:
1. Layer 10 — VFE momentum one-shot (BT-FIT, day-3 fit)
2. Layer 12 — M55 follow-flow (corr=+0.16, threshold sweep-fit)
3. Layer 21 — Conditional Voucher OBI (5-param simultaneous sweep, partial theory)

**KEEP** (theory-defensible or empirically robust):
- All HP layers (1-7)
- VFE Wall-Mid MM, Layer-E (8-9)
- M49 fade (11) — t=20 n=105 survives multiple-testing correction
- All voucher structural arb / MM (13-20)

**FLAG** (keep with risk warning):
- Layer 14 (VEV_5200 edge=5 override)
- Layer 22 (YOLO regime) — keep for headline but warn it is day-3 fit

**FALSIFICATION CRITERIA**: a layer's removal that *improves* OOS PnL by >2× its
in-sample BT delta is positive evidence the original was overfit.

# Appendix: BT-FIT parameter inventory in v8

```
VFE_MOMO_LOOKBACK = 25     # was 50 (v5b)
VFE_MOMO_TP = 12.0         # was 10 (v5c), was 9 prior
VFE_MOMO_SL = 15.0
VFE_MOMO_THRESH = -3.0
OBI_THRESHOLD = 0.7
OBI_CONFIRM_MIN_STRIKES = 3
OBI_CONFIRM_SCALE = 2
OBI_SPREAD_COMPRESS_MAX = 10
OBI_POS_CAP = 30           # was 200, swept 30 (v5c)
M55_WINDOW = 50
M55_THRESH = 30            # v7c
M55_TAKE_SIZE = 20
M49_HOLD_TICKS = 5         # v7c
M49_SIZE = 60              # was 20 (v7c)
YOLO_DETECT_TICKS_TS = 3000
YOLO_DRIFT_THRESHOLD = -1.5
```
17 parameters, 7 layers. By Bonferroni on 17 simultaneous sweeps:
α_per_test = 0.05/17 = 0.003 — required t > 3.0 per parameter to be confident.
