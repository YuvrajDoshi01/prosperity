---
name: Round 1 Submission Trajectory and Key Findings
description: Canonical website-score trajectory v1→v17 (plus v18 BT validation), decision framework, and lessons not covered in focused memories (v17 post-mortem, v18 architecture, LU framework, Nancy guardrail, synthetic testing).
type: project
originSessionId: 955e9ff4-5728-4069-8882-3e961751886f
---
Updated 2026-04-18 after CLAUDE.md dedup.

## Website score trajectory (canonical)

| Version | Submission | Score | IPR | ACO | Key |
|---------|-----------|------:|----:|----:|-----|
| basic trader | 105087 | 4,934 | 2,138 | 2,796 | Baseline |
| r1_medallion bias=5 | — | 10,444.8 | 7,354 | 3,091 | Microprice regression + drift |
| r1_medallion bias=6 | 134926 | 10,467.8 | 7,377 | 3,091 | Previous best |
| r1_v2 | 211338 | 10,536.81 | 7,446 | 3,091 | Simple mid + drift_bias=5 (via 210525 probe) |
| r1_hybrid (×3) | 207789/208196/210055 | 10,106-10,107 | 7,016-7,446 | 3,091-3,179 | Seed-detection — byte-identical, NO improvement |
| r1_v3 | 212392 | 7,974.84 | 4,796 | 3,179 | LU framework on IPR — REGRESSION |
| **r1_v4** | 213352 | **10,624.84** | **7,446** | **3,179** | **r1_v2 IPR + LU ACO — CURRENT BEST** |
| r1_v5 (guardrail) | 228366 | 10,612.84 | 7,434 | 3,179 | Nancy trend detector — neutral (-12) |
| r1_v7 (guardrail+wall-mid) | 228024 | 10,465.84 | 7,287 | 3,179 | REGRESSION — Banker's rounding bug (fixed in v9) |
| r1_v9_defensive | 251714 | 10,601.66 | 7,438 | 3,164 | Cubic ACO skew + circuit breaker + Banker fix. −23 insurance vs v4. |
| r1_v10_defensive | 252728 | 10,455.66 | 7,292 | 3,164 | v9 + toxic-maker fix + neutral startup. IPR −146 from neutral. |
| r1_v11_defensive | 253476 | 10,455.66 | 7,292 | 3,164 | v10 + cur_mid trigger + one-sided IPR drop. **Byte-identical to v10**. |
| r1_v12/v13/v14_defensive | 257139/258586/259621 | 10,443.78 | 7,292 | 3,152 | Sweep-optimal + blind-eye fix + (dump/lean-out variants). All byte-identical on website. −12 from false-positive crash_mode on normal ACO noise. |
| r1_v15/v16 | not submitted | — | — | — | Adaptive-anchor experiments. Both FAILED on synthetic gradient crashes (self-disarm). |
| r1_v17 (tutorial) | not submitted | — | — | — | Bootstrap-only anchor. Synthetic +2,748 vs v14. |
| **r1_v17 (FULL R1)** | **272466** | **89,861.44** | **79,327** | **10,534.44** | Full day 1. IPR 99.1% of buy-and-hold max. ACO cost ~1,743 to bootstrap anchor flicker. **See project_round1_final.md** |
| r1_v8 (Nancy bid port) | — | — | — | — | Self-wash bug, BT regression persists. NOT SUBMITTED |
| Nancy's algov4 (benchmark) | 228959 | 10,734.03 | 7,496 | 3,238 | +109 over r1_v4 via aggressive bid + OU ACO |

## Headline lessons (curated — full details in focused memories)

1. **Simple mid + drift_bias=5 beats microprice for IPR** (r1_v2 via 210525 probe, +90 PnL)
2. **Linear Utility's clear step = +3% on stable products** — ACO +88 PnL matched theory. See `project_lu_framework.md`
3. **LU take_width=1 BREAKS drift products** — r1_v3 regressed IPR by -2,650
4. **IPR drawdown is STRUCTURAL, eliminating LOSES money** — r1_hybrid, r1_v7 both regressed. See `feedback_drawdown_misconception.md`
5. **Seed detection adds no value** — 3 hybrids all 10,106-10,107
6. **Nancy's rolling-slope guardrail IS valid** (r1_v5) — see `project_nancy_guardrail.md`
7. **Nancy's OU ACO model is overfit** — 9 tuned params, +59 ACO edge likely seed variance
8. **Synthetic multi-seed (4 × 4 = 16/16) confirms r1_v5 > r1_v4** — see `project_synthetic_testing.md`
9. **Practical website ceiling ~10,625-10,734** — gap to #1 (11,744) likely seed variance
10. **ACO BT gradient overshoots ~60×** — r1_v9 cubic skew BT predicted −924, actual −15. See `feedback_backtester.md`
11. **traderData format matters** — dead-state removal cost 2 IPR fills (-39 PnL). Keep all fields.

## Defensive stack evolution (v9 → v17)

Each step fixed a latent bug or added a tail-risk defense while minimizing cost on observed data.

- **v9**: Cubic ACO skew + circuit breaker + Banker's rounding fix (+151 IPR recovered from v7)
- **v10**: Toxic-maker fix (crash_mode anchors `base_fv = avg_mid` and widens edges) + neutral startup. Synthetic ACO crash: **+41,339 PnL saved vs v9**. But neutral startup costs ~146 IPR on uptrend days (website confirmed)
- **v11**: `cur_mid` trigger (was 5-tick `avg_mid`, 2-3 tick lag on instant crashes) + IPR one-sided penny-improve drop. Byte-identical to v10 on real (both defenses dormant)
- **v12**: Sweep-optimal params (MAX_CONCESSION 8→4, CRASH_THRESHOLD 25→15) + blind-eye reset fix. Synthetic +14,940 vs v10; website −12 (false-positive crash_mode on normal ACO noise range ±18)
- **v13**: Forced-dump (spread-cross when crash_mode + |pos|>60). **ABANDONED**: synthetic −21,715 vs v12 from inventory ping-pong cycle-loss
- **v14**: "Lean out" (zero buy_cap/sell_cap when crash_mode + |pos|≥60). Cleaner architecture than v13; synthetic −4,736 vs v12 but +21,979 vs v13
- **v15**: Adaptive ACO anchor (bootstrap + slow median). **FAILED**: synthetic −58,568 vs v14 from anchor-tracks-gradient-crash self-disarm
- **v16**: v15 + freeze during prelim_crash. Partial fix: recovers +22,546 vs v15 on ACO_CRASH but still −37,983 vs v14 total
- **v17**: Bootstrap-only anchor (snap once at tick 0, freeze forever). 13-regime synthetic +2,748 vs v14 via ALT_FV_HIGH/LOW wins. **SUBMITTED as 272466** — see `project_round1_final.md` for real-data post-mortem
- **v18**: Adaptive threshold (rolling median avg_mid, frozen MAD, median-of-20 bootstrap, hysteresis). **Beats v17 on all 3 real BT days (+4,920) and 15-seed synthetic.** See `project_round1_v18.md`

### Key architectural insights
- **Blind-eye reset bug (v10/v11)**: `else: cur_mid = avg_mid = ACO_FV` when book lost a side silently disarmed crash_mode. v12 fix: fall back to last known `aco_mids` average
- **Adaptive anchor fundamental tension**: lag shorter than crash duration → self-disarm. Bootstrap-only (v17) or frozen-during-crash (v16) are the only stable designs
- **v14's hardcoded FV=10000 accidentally provides FV-shift protection**: when market at e.g. 14k, crash_mode permanently armed → `base_fv = avg_mid` tracks market
- **MID_SHIFT regime (10-tick shift below CRASH_THRESHOLD=15)** is v14/v17's weakest — adaptive anchor wins this regime but loses gradient crashes (net-negative)

## Submission decision framework

- **Max-PnL uptrend confidence**: r1_v4 (no insurance)
- **Regime uncertainty, full defense**: r1_v9_defensive — preserves +5 drift startup (7,438 IPR) AND full ACO defense (3,164 ACO). Break-even vs v4 at P(rug) > 0.1%
- **Round 2+ with stable-product component**: r1_v18 (adaptive threshold, wins synthetic and real BT over v17/v14)

## Key infrastructure (built during R1)

- `trader-logic/round-1/r1_v5.py` — IPR trend guardrail (Nancy-inspired)
- `trader-logic/round-1/references/nancy_algov4.py` — Nancy's full code
- `trader-logic/round-1/experiments/synthetic/` — `generate.py` + `run_all.py` for regime stress tests
- `trader-logic/round-1/BACKTEST_COMMANDS.md` — canonical command reference
- `trader-logic/round-1/analyzer/trading_analyzer.html` — Superduperbread's dev-vs-real HTML comparator
- Added round 99 support to `prosperity4bt/tools/data_reader.py` for synthetic data
- Custom `website` match-mode in the backtester (taker supplement)
- Independent Rust-logic validator at `prosperity4bt/tools/rust_engine.py`

## Explicit rejections (do NOT revisit)

- r1_v8 (Nancy bid placement): doesn't port, self-wash bug
- OU model for ACO: overfit (9 magic numbers)
- Nancy's spread-linear pricing: 2 tuned coefficients (10-decimal precision)
- Superduperbread's core/reserve system: his 10.4k < our 10.625
- Adaptive anchor (v15/v16): fundamental self-disarm on gradient crashes

## Rehabilitated (previously rejected, now validated 2026-04-17)

- **ACO wall-mid**: earlier r1_v6 "BT −10,775 structural regression" was a `_wall_mid` ask-side bug (`min(..., key=lambda p: abs(vol))` picked SHALLOWEST ask, not deepest). Fixed to `max`. Correct implementation gains +10,772 BT ACO across 3 full days
- **IPR wall-mid**: effect is noise-level (< ±500 ACO variance per run from imc-mode stochastic fills). IPR books are structurally symmetric → wall-mid ≈ simple-mid

## Backtester non-determinism (2026-04-17)

`--match-mode imc` with `extra_rate=0.064` adds stochastic fills. Three back-to-back runs of identical code show ~±1,000 ACO PnL variance per run (IPR is deterministic). Any BT delta < ~2,000 ACO may be noise. Run multiple seeds for small-effect comparisons.

## Day-scaling (tutorial 1k vs full 10k)

- r1_v4 BT 10k: 309,686 (default mode), 318,839 (imc mode)
- IPR scales super-linearly (~10.65× from 1k to 10k on strong drift day)
- ACO sub-linear (3.31× — fill-rate limited by taker arrival rate, not tick count). Natural ceiling ~11-13k on a normal day

## Why/How to apply

- Ship r1_v4 for max tutorial PnL in uptrend regime
- Ship r1_v9_defensive for regime-uncertain days (cost −23 vs v4 for full ACO defense)
- Ship r1_v18 for Round 2+ with stable-product components (adaptive threshold wins real BT and synthetic)
- Don't chase Nancy's +109 — her edge requires 11 tuned params
- Run synthetic (`run_all.py`) before submitting new variants; update synthetic generator when new regimes emerge (e.g. asymmetric-open-book from v17 post-mortem)
