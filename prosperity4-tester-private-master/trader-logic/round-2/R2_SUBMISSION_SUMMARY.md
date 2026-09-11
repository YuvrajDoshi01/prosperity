# Round 2 Submission Package

Consolidated summary of decisions, evidence, and deliverables for Prosperity 4 Round 2.

## Final standing entering R2

- R1 cumulative PnL banked: **177,000 XIRECs**
- 200k threshold locked (needs only 23k from R2 to clear)
- Any reasonable R2 performance plus manual challenge clears the threshold by a wide margin

## Algorithm submission

**Ship file**: [trader-logic/round-2/r2_v5.py](r2_v5.py)

- Base: r1_v17 (bootstrap anchor + cubic skew + crash_mode)
- Byte-identical to r1_v17 except `MAF_BID = 0`
- `bid()` returns 0 (integer)

### Validation

| Test | Result |
|------|--------|
| r2_v5 on R2 CSV (3 days, default mode) | **276,431** (IPR ~238k + ACO ~37k) |
| r2_v5 on R2 day-1 website data (round 98) | **7,680** (IPR 7,354 + ACO 326) |
| r2_v5 with --extra-flow=scale (MAF-win sim) | 277,332 (+901, small uplift) |
| r2_v5 on R1 CSV (4 days) | 310,529 (matches r1_v17 baseline) |
| Actual R2 website submission 275130 | **8,915** (IPR 7,464 + ACO 1,451) |

### Previous submission comparison

- 274128 (r2_v2, r1_v4 base, bid=20000): **8,412** website
- **275130 (r2_v5, r1_v17 base, bid=0): 8,915 website — +503 improvement**

## Why MAF_BID = 0

Three independent arguments converged:

1. **Structural**: MAF injects new quote levels BETWEEN existing ones, which tightens the effective spread our maker orders compete against. For our making-heavy Linear Utility strategy, this hurts fill rate and narrows captured spread.

2. **Community**: Top-player Discord consensus: "past 180k DO NOT BID — it's a trap." Consistent with our structural analysis.

3. **Empirical**: Local backtester --extra-flow=scale shows only +0.3% uplift. Even under optimistic assumptions, real MAF value is uncertain.

4. **Strategic**: R1 cumulative at 177k makes threshold safe. No upside justifies paying XIRECs for uncertain extra flow.

## Manual challenge allocation

**REVISED after v4 empirical solver**

**Primary pick**: `r=14, s=42, sp=44`

Expected PnL depends on rank interpretation (v4 solver showed huge variance across the two plausible readings of the brief):
- If rank across all 22k registered teams (including 73% ghosts): ~260k
- If rank among engaged submitters only: ~204k
- Worst case across modes: **204k** (best of any non-extreme-robust candidate)

### Why we shifted from (15, 44, 41) to (14, 42, 44)

The v4 solver used empirically-calibrated bucket fractions from R1 leaderboard data (73.3% ghost rate, 8% copy-paster, etc.) and ran iterated best response against TWO rank interpretations:

- **MODE A (all players)**: iteration cycles at sp=1-7 because 73% ghosts at sp=0 make low Speed dominant. Optimum (23, 76, 1) or (23, 74, 3) gives 450-490k but craters in MODE B.
- **MODE B (engaged only)**: arms race with no stable pure Nash. First-iteration best response is (14, 42, 44) at 204k; iterating pushes Speed up to 57 but mean drops to 144k because of cost.

The brief's example ("if you have three players investing 95, 20, 10") implies only engaged investors are ranked (MODE B). But "all players" wording is ambiguous. **Playing modally-robust (14, 42, 44) is the rational call under uncertainty.**

### Decision matrix under modal uncertainty

| Candidate | MODE A | MODE B | Worst | EV P(A)=0.5 |
|-----------|-------:|-------:|------:|------------:|
| (23, 74, 3) | 487,370 | ~60,000 | 60,000 | 273,685 |
| (23, 76, 1) | 453,507 | 23,245 | 23,245 | 238,376 |
| (18, 50, 32) | 316,271 | 84,399 | 84,399 | 200,335 |
| **(14, 42, 44)** | **260,000** | **204,270** | **204,270** | **232,135** |
| (15, 44, 41) | 265,140 | 105,088 | 105,088 | 185,114 |
| (11, 29, 60) | 142,709 | 131,443 | 131,443 | 137,076 |

(14, 42, 44) wins on WORST-CASE and has the second-best EV across all prior beliefs. Only (23, 74, 3) beats it on EV if you're very confident the rank includes ghosts.

### Evidence base

Three solver iterations converged on (15, 44, 41):

| Version | Approach | Evaluations | Result |
|---------|----------|-------------|--------|
| v1 | 18 Normal(mu, sigma) scenarios | 3.2M | (15, 44, 41) point-optimum |
| v2 | 101 scenarios (Normal + Uniform + Bimodal + rank sim) | 17.9M | (16, 46, 38) mean-optimum |
| v3 | Behavioral population Monte Carlo + iterated best response | ~21M | (15, 44, 41) Nash fixed point on iteration 1 |

v3's Nash fixed point is self-consistent: even when 9% of the field copies this allocation (the "sophisticated" bucket in our population model), (15, 44, 41) remains the best response.

### Behavioral calibration from R1 leaderboard

Using 22,130-team R1 leaderboard data (scraped from public API):

- 73.3% of teams are **ghosts** (no engagement with R1)
- Only 5,917 teams (26.7%) are real competition
- Of engaged teams on manual, the R1 leak (87,995) was copied by 35% of engaged
- Elite top 100: 90 hit leak exactly, 10 solved independently near optimum

This confirms that Nash-point analysis applies to the ~18.6% fully-engaged population, not to all 22k.

### Contrarian variant

If concerned about crowding at (15, 44, 41) from Discord leaks:
- **(15, 43, 42)** sits one point above the Nash herd
- Matches the Nash Scale and Research values almost exactly
- Slight Speed percentile gain if the (15, 44, 41) answer goes viral

### Dispersion variant

If "rank across all players" means all 22k registered (not just engaged):
- **(18, 50, 32)** dominates because the ghost pool at sp=0 anchors rank
- More Scale-weighted because you don't need sp=41 to reach top-50%

### Final recommendation

**Submit (r=14, s=42, sp=44)** as primary.

Alternatives based on rank-interpretation prior:
- Very confident MODE A (ghosts count): **(23, 74, 3)** gets 487k in MODE A but only 60k in MODE B
- Very confident MODE B (engaged only): **(14, 42, 44)** same choice, just with more conviction
- Extreme risk aversion: **(11, 29, 60)** guarantees 131k in every scenario

## Files delivered

### Trading algorithm
- `trader-logic/round-2/r2_v5.py` — **R2 submission**
- `trader-logic/round-2/r2_v1.py` — alternative with OBI + wall-mid (abandoned)
- `trader-logic/round-2/r2_v2.py` — r1_v4 base (submitted as 274128, scored 8,412)
- `trader-logic/round-2/r2_v3.py` — median-of-50 bootstrap (regressed on CSV)
- `trader-logic/round-2/r2_v4.py` — median-of-10 bootstrap (regressed on website data)

### Manual challenge
- `trader-logic/round-2/invest_expand_solver.py` — v1, 18-scenario Normal grid
- `trader-logic/round-2/invest_expand_solver_v2.py` — v2, 101 scenarios, multiple models
- `trader-logic/round-2/invest_expand_solver_v3.py` — v3, behavioral population + iterated best response
- `trader-logic/round-2/invest_expand_results.json` — v1 output
- `trader-logic/round-2/invest_expand_results_v2.json` — v2 output
- `trader-logic/round-2/invest_expand_results_v3.json` — v3 Nash equilibrium output

### Behavioral analysis
- `trader-logic/round-2/r1_leaderboard_analysis.py` — standalone leaderboard analyzer
- `trader-logic/round-2/r1_leaderboard_analysis.json` — engagement funnel, leak analysis, country signatures, calibrated buckets
- `trader-logic/round-2/BEHAVIORAL_ANALYSIS.md` — top-tier behavioral analyst writeup
- `trader-logic/round-2/MANUAL_CHALLENGE_WRITEUP.md` — full methodology doc

### Infrastructure
- `prosperity4bt/__main__.py` — `--extra-flow` CLI flag added
- `prosperity4bt/models/test_options.py` — `ExtraFlowMode` enum added
- `prosperity4bt/test_runner.py` — `__apply_extra_flow()` mutator added at line 164
- `prosperity4bt/tools/data_reader.py` — round 98 registered for R2 day-1 website data
- `trader-logic/round-2/oracle/god_logger_r2.py` — probe template
- `trader-logic/round-2/data_diff.py` — R1 vs R2 CSV diff script
- `prosperity4bt/resources/round98/prices_round_98_day_0.csv` — R2 day-1 website data extract

## Actions checklist

Before R2 deadline:
- [ ] Submit r2_v5.py as the Round 2 algorithm (currently submitted as 275130)
- [ ] Enter manual allocation r=15, s=44, sp=41 via web form
- [ ] Monitor Discord for R2 leaks. If a specific allocation goes viral, switch to contrarian variant
- [ ] Do not resubmit after choosing final allocation

After R2 scoring:
- [ ] Compare actual R2 score vs projections (local BT undershoots by ~16%, so expect ~10.3k on single-day scoring, ~285k if full 3-day)
- [ ] If we win MAF (bid = 0 so we won't), note what 100% flow feels like in logs
- [ ] Archive learnings for R3 strategy

## Projected cumulative

| Scenario | R1 | R2 base | MAF | Manual | Cumulative |
|----------|---:|--------:|----:|-------:|-----------:|
| Base case | 177,000 | ~285,000 | 0 | ~228,000 | **~690,000** |
| Conservative | 177,000 | ~200,000 | 0 | ~150,000 | ~527,000 |
| If MAF trap hypothesis wrong (bid=0 loses value) | 177,000 | ~255,000 | 0 | ~228,000 | ~660,000 |

In every case, we clear the 200k threshold by 300k+. The main downside risk on manual is if our game theory model is wrong, but even then, the manual is pure upside on top of already-safe threshold.
