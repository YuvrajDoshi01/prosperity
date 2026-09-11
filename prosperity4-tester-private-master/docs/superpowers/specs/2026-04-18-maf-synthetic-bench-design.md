# MAF Synthetic Bench — Design Spec

Date: 2026-04-18
Scope: Round 2 synthetic validation harness for the Market Access Fee (MAF) decision.

## Problem

R2's algorithm submission 275130 shipped with `MAF_BID = 0` — we declined to pay for enhanced market access. The decision rested on a structural argument ("MAF injects quotes inside our maker posts, tightening the spread we compete against"), a community hint ("past 180k DO NOT BID — it's a trap"), and a single `--extra-flow=scale` BT run that showed a +0.3% uplift. It was not stress-tested against regime changes and did not quantify the break-even bid under uncertainty.

The synthetic regime tester (`trader-logic/round-1/experiments/synthetic/run_all.py`) already validates R1 strategies across 14 regimes × 25 seeds. It was never wired for R2 because the R2 strategies were byte-identical to their R1 counterparts except for `MAF_BID`, and the BT ignores `bid()` so swapping in `r2_v5`/`r2_v6` would change nothing. This leaves the MAF decision untested under the synthetic harness we use for every other R2 question.

## Goal

Produce a defensible, regime-aware answer to "for what bid X and confidence P(win) does bidding beat not bidding?" The output is a decision table, not a point estimate — the user plugs in their own P(win) belief (informed by Discord chatter, game theory, prior-round competitor behavior) and reads the optimal bid off the table.

Non-goals: fixing cosmetic generator tweaks (spread mode 13→14), refactoring the generator for R3+ products, or modeling MAF cost subtraction inside the BT engine.

## Model of MAF (from R2 brief)

Each participant sees a different order book:
- **MAF winners** (top 50% of bids): trade against the enhanced 100% book. Pay their bid.
- **MAF losers** (bottom 50%): trade against the base 80% book. Pay nothing.
- During R2 **testing** (what round98 captures), no MAF is applied — every tester sees 80%.

The BT's `--extra-flow={none,scale,interp}` flag mutates `state.order_depths` before the matching step. `none` = base book = loser-side. `interp` injects midpoint levels exactly as the brief describes ("given ask[9]=10 and ask[7]=10, inject ask[8]=5") = brief-literal winner-side. `scale` multiplies existing volumes by 1.25 = pragmatic winner-side approximation.

Bid value `X` never enters the BT. `bid()` is read only by the IMC website's auction resolver. For any bid X: `net_PnL = PnL_won − X` if we win, `PnL_lost − 0` if we lose. This is post-hoc arithmetic over the two BT outputs.

## Approach

A new standalone script `trader-logic/round-2/maf_synthetic_bench.py`. Separate from `run_all.py` so the canonical R1 bench is preserved. Serial execution.

Parameters (hardcoded, seed count overridable by env):
- `STRATEGIES = {r2_v5, r2_v6}` — bootstrap-anchor (v17 base) and adaptive-threshold (v18 base)
- `FLOW_MODES = [none, scale, interp]`
- `DATASETS = [round99 (14 regimes), round98 (1 real R2 day)]`
- `SEEDS = [42 + 73·i for i in 25]` (canonical pattern from `run_all.py`)
- `TICKS = 10_000`

Total runs: 2 strategies × 3 flow modes × (14 synthetic regimes + 1 round98 day) × 25 seeds = **2,250**. At ~2s/run ≈ **75 min** serial.

Round98 runs don't need regeneration (static CSV), but seed regeneration for round99 happens once per seed before running all 2 × 3 = 6 cells against that seed's synthetic data. Checkpoint written to `maf_synthetic_results.json` after each seed so a crash at seed 18 doesn't lose seeds 1–17.

## Components

### Runner
- `regenerate(seed)` — subprocess call to `generate.py <seed>` (mirrors `run_all.py`)
- `run_bt(strategy_path, dataset_arg, flow_mode)` → `dict[regime_label, pnl]`
  - dataset_arg: `"99"` for round99 (all 14 days) or `"98-0"` for round98 day 0
  - returns per-day PnL via regex on BT stdout
- `main()` — triple-nested loop (seed × strategy × flow_mode), writes incremental checkpoint after each seed

### Aggregator (same file, separate functions)
Produces four tables:

1. **Per-cell stats**: for each (strategy, regime, flow_mode), report `mean, median, stdev, min, max, 95% CI` across 25 seeds. CI via t-distribution with df=24.

2. **Winner-minus-loser deltas**: `PnL[interp] − PnL[none]` and `PnL[scale] − PnL[none]` per (strategy, regime). This is the "value of winning MAF at this regime" number. Negative deltas flag regimes where winning HURTS (e.g. MAF injected levels might break a strategy's anchor logic — relevant for r2_v5's bootstrap-anchor regime sensitivity).

3. **MAF-model cross-check**: `|mean(interp) − mean(scale)|` per (strategy, regime). If consistently large (>1k PnL), flag "MAF model uncertainty" — we don't know which approximation is closer to IMC's real mechanic. If small, methodology is robust to the approximation choice.

4. **Decision curve**: for bid grid `{0, 1k, 5k, 10k, 15k, 20k, 25k, 30k}` × P(win) grid `{0.1, 0.3, 0.5, 0.7, 0.9}`, compute:
   ```
   E[net PnL | bid=X, P_win] = P_win · (mean(PnL[interp]) − X) + (1 − P_win) · mean(PnL[none])
                             = mean(PnL[none]) + P_win · (delta_mean − X)
   ```
   where `delta_mean = mean(PnL[interp]) − mean(PnL[none])` averaged across regimes. Report the bid level that maximizes E[net PnL] under each P_win, and the **break-even bid** (where E[net PnL] = 0 relative to bid=0) = `delta_mean`. Use `interp` as the brief-literal winner-side proxy; `scale` is shown in the cross-check table.

### Markdown writer
Single file `trader-logic/round-2/maf_synthetic_results.md`. Structure:
- 2-sentence top-line conclusion (e.g. "MAF break-even bid is X under synthetic assumptions; our MAF_BID=0 submission was correct iff our P(win) belief at X was < Y")
- Per-cell PnL table (strategy × regime × flow_mode, mean ± 95% CI)
- Winner-minus-loser delta table
- MAF-model cross-check table
- Decision curve (the punchline table)
- Round98 anchor check: `PnL[round98, none] = ?` vs known website 8,915 (expect ~8,407 from R2-calibrated imc mode) — validates methodology against real data

## Data flow

```
generate.py(seed) ──► round99/prices_round_99_day_{0..13}.csv   (regenerated per seed)
round98/prices_round_98_day_0.csv                                (static real R2 day)
         │
         ▼
run_bt(strategy, dataset, flow)  ──► {regime_or_day: pnl}        (×2,250 total)
         │
         ▼
checkpoint_json[seed][strategy][flow][regime] = pnl              (written after each seed)
         │
         ▼
aggregator ──► per-cell stats + 95% CI
           ──► winner-loser deltas
           ──► MAF-model cross-check (|interp - scale|)
           ──► decision curve E[net | bid, P_win]
           ──► round98 anchor validation
         │
         ▼
maf_synthetic_results.json        (raw seed matrix, for re-analysis)
maf_synthetic_results.md          (human-readable summary)
```

No external APIs, no network. Pure subprocess orchestration + in-memory aggregation + file writes.

## Error handling

- BT run returns empty stdout or no PnL match → record 0, log warning, continue. One-off subprocess failures shouldn't kill a 75-minute run.
- `generate.py` crash → halt; synthetic data integrity is non-negotiable.
- Keyboard interrupt → write final checkpoint before re-raising.
- If `maf_synthetic_results.json` already exists at start, prompt to resume-or-overwrite. Resume skips completed seeds.

## What's explicitly NOT in scope

- Cosmetic generator fidelity (IPR spread mode 13→14 to match R2). Noted as a separate optional tweak; not blocking this bench.
- Refactoring generator for unknown R3+ product types. Scope (c) from the initial brainstorm was explicitly deferred.
- Parallelizing the BT subprocess runs. The existing `run_all.py` is serial; keep consistent style. If 75 min is unacceptable, a future change adds `multiprocessing.Pool` as a 5-line patch.
- Modeling MAF cost inside the BT engine. The post-hoc math is cleaner and keeps the BT agnostic to R2-specific mechanics.

## Verification

After running the bench:
1. Round98 anchor check: synthetic `PnL[round98, none]` mean across 25 seeds must be within ±5% of 8,407 (our R2-calibrated imc mode, pre-change) — else methodology bug.
2. Per-regime sanity: `PnL[UPTREND, none]` for r2_v5 must roughly match `r1_v17` on UPTREND from the existing R1 bench (scaled by tick count). Large divergence flags either a code bug or a silent strategy difference.
3. Decision curve sanity: `break_even_bid` must equal `delta_mean` exactly (pure arithmetic). If not, aggregator bug.
4. MAF-model cross-check: if `|mean(interp) − mean(scale)|` consistently > 5,000 PnL, flag in the markdown summary with a warning ("synthetic conclusions sensitive to MAF approximation choice — take with salt").

## Files touched

| File | Change |
|------|--------|
| `trader-logic/round-2/maf_synthetic_bench.py` | **New** — runner + aggregator + markdown writer |
| `trader-logic/round-2/maf_synthetic_results.json` | **New output** — raw seed matrix (generated on first run) |
| `trader-logic/round-2/maf_synthetic_results.md` | **New output** — human-readable summary (generated on first run) |
| `memory/project_maf_synthetic_bench.md` | **New memory** — captures key findings so future sessions can apply them to R3 MAF-like mechanics |

No changes to `generate.py`, `run_all.py`, `__main__.py`, or any strategy file.

## Open questions (resolved)

- ~~How does `MAF_BID` flow to the BT?~~ It doesn't. Bid is post-hoc arithmetic only.
- ~~Which `--extra-flow` mode represents the winner side?~~ `interp` is brief-literal; `scale` is pragmatic. Run both, cross-check.
- ~~Should we include `r2_v2` (bid=20k, submitted as 274128=8,412) as an anchor?~~ Deferred. Round98 + known R2-calibrated PnL is sufficient validation; adding r2_v2 would only catch methodology bugs that round98 already catches.
