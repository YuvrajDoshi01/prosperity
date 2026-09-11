# Round 1 Post-Mortem: Submission 272466 (r1_v17_bootstrap_only)

**Final score:** 89,861.44
**Split:** IPR 79,327 + ACO 10,534.44
**Date:** 2026-04-17
**Strategy:** `r1_v17_bootstrap_only` (v14 plus a one-time anchor bootstrap on the first valid two-sided ACO mid)

---

## Summary

IPR was basically perfect (99.1% of buy-and-hold ceiling). ACO leaked about 1,743 PnL because the bootstrap anchor snapped to 10,008, banker-rounded from the asymmetric tick-0 mid of 10,007. That shifted the crash-mode trigger window off-center and caused 512 spurious crash_mode ticks where v14 would have fired zero.

The synthetic regime test that validated v17 (+2,748 over v14 on 13-regime 25-seed bench) missed this entirely, because synthetic ACO always opens symmetrically at 10,000. v17's bootstrap isn't free insurance. On a normal day with an asymmetric open book, it's strictly worse than v14.

A separate dev-vs-real comparison (Section 9) shows the crash_mode flicker is only ~28% of the story. The other ~72% is a structural BT-vs-real fill-rate gap: dev runs over CSV data at 2.5× the real fill rate in normal mode. That's unfixable without a taker-aware simulator.

---

## 1. What happened

Submission 272466 ran `r1_v17_bootstrap_only` on Round 1 day 1 full-scoring (10,000 ticks). Two independent legs:

| Leg | Role | Final PnL |
|---|---|---:|
| IPR (drift product) | Simple mid + drift_bias=5, asymmetric takes, penny-improve posting | 79,327 |
| ACO (stable product) | LU take/clear/make, cubic skew, circuit breaker, v17 bootstrap anchor | 10,534.44 |

End-of-day positions: IPR +80, ACO +80 (both at position limit).

---

## 2. IPR: basically perfect, nothing to fix

IPR drifted from 12,998.5 to 13,999.5 over the day (+1,001).

| Metric | Value |
|---|---:|
| Theoretical max (long 80, buy-and-hold through +1,001 drift) | 80,080 |
| Actual IPR PnL | 79,327 |
| Efficiency | 99.1% |
| Gap to max | 753 |
| Max running drawdown | 501 |

Per-decile PnL gain held steady at ~8,000 per 1k ticks across all 10 deciles. The drift-capture machine ran flat out from open to close. `drift_bias=5` was well calibrated (drift rate 0.1001/tick × 50-tick horizon = 5).

The 753-unit gap to theoretical max is structural entry cost: you can't buy 80 units at t=0 in a single tick. The 501 max drawdown is just the drift-trade entry pattern working as intended (see `memory/feedback_drawdown_misconception.md`).

Verdict: essentially no headroom on this leg. A pure long-80 oracle would have netted ~753 more.

---

## 3. ACO: where we bled

ACO's per-decile PnL was all over the place:

| Tick window | ACO PnL gained |
|---|---:|
| 0-100k | +2,647 |
| 100k-200k | +1,641 |
| 200k-300k | −85 |
| 300k-400k | +2,521 |
| 400k-500k | +267 |
| 500k-600k | +1,372 |
| 600k-700k | +740 |
| 700k-800k | +109 |
| 800k-900k | +1,178 |
| 900k-1M | +145 |

If every decile had matched the first (2,647/100k), ACO total would've been ~26,470. Actual was 10,534. The tapering isn't position saturation (fills kept coming uniformly all day). It's the circuit breaker firing on normal noise.

### 3.1 Root cause: bootstrap anchor landed off-center

v17 bootstraps the ACO anchor from the first valid two-sided mid via:

```python
def _snap_anchor(x):
    return 2 * round(x / 2)     # snap to nearest even tick
```

At tick 0 the ACO book was asymmetric:
- bid_1 = 9,998 (volume 23)
- ask_1 = 10,016 (volume 13)
- mid = (9,998 + 10,016) / 2 = 10,007.0

`_snap_anchor(10007) = 2 * round(5003.5) = 2 * 5004 = 10,008`. Python's `round()` uses banker's rounding; 5004 is even, so it rounds to 5004. Anchor frozen at 10,008 for the rest of the day.

### 3.2 How the off-center anchor triggered crash_mode

`crash_mode = abs(cur_mid - anchor) > ACO_CRASH_THRESHOLD` with threshold 15.

| Anchor | Crash window | Triggers on |
|---|---|---|
| 10,008 (v17 bootstrap) | `mid < 9,993` or `mid > 10,023` | dips to 9,990, 9,991, 9,992 |
| 10,000 (v14 hardcoded) | `mid < 9,985` or `mid > 10,015` | nothing in observed range |

Observed ACO mid range: 9,986 to 10,015. Sits almost perfectly inside v14's window, biased off v17's.

Firing count reconstructed from the activity log:
- v17 crash_mode: 512 ticks (5.12% of day), 200 distinct episodes
- v14 crash_mode (hardcoded anchor=10,000): 0 ticks

### 3.3 What crash_mode does and why it hurt

During crash_mode the v14/v17 architecture:
1. Disables take and clear steps entirely (only passive make runs)
2. Repoints `base_fv` from anchor to `avg_mid` (120-tick moving average)
3. Widens join_edge and default_edge by `ACO_CRASH_JOIN_EDGE_BONUS = 4`
4. Zeroes `buy_cap` or `sell_cap` if `|pos| >= 60` (asymmetric lean-out)

This is the right response to a real crash. But on a 1-tick flicker from normal noise, it means we skip the take opportunity that tick, post passively at widened edges (worse fill probability), and often pay the spread-crossing cost a tick later re-crossing back into normal mode.

Per-tick PnL by mode (measured on the 272466 log):

| Mode | Ticks | Total PnL | Per-tick |
|---|---:|---:|---:|
| Normal | 9,300 | +11,418 | +1.228 |
| Crash | 700 | −884 | −1.263 |

(The 700 vs 512 gap is because `crash_mode` stays active for 1 extra tick via the one-sided-book fallback path, which inherits the last `avg_mid`.)

v14 counterfactual: if those 700 ticks had been in normal mode at +1.228 PnL/tick:
- Counterfactual gain: 700 × 1.228 = +860
- Actual loss: −884
- Total v14 advantage over v17: ~1,743 PnL

v14 probably would have scored ~12,277 ACO and ~91,604 total.

---

## 4. Why the synthetic test missed this

The 13-regime 25-seed synthetic bench had v17 beating v14 by +2,748 total (primary wins on ALT_FV_HIGH +1,460 and ALT_FV_LOW +1,566). We shipped on that.

The synthetic generator in `trader-logic/round-1/experiments/synthetic/generate.py` produces ACO mids by applying Gaussian noise around a target FV (default 10,000). The opening book is always symmetric: both sides get volume drawn from the same distribution centered on the target FV.

In reality, Round 1 day 1 opened with a 7-unit bid-ask asymmetry (bid 9,998 / ask 10,016) and deeper volume on the bid side. That's a microstructure signal that the MM bot sometimes starts biased.

The failure mode (anchor bootstrap lands off-center when the open is asymmetric, causing frequent false crash triggers) is unreachable in synthetic because the open is constructed to be symmetric.

---

## 5. Additional contributing factors

### 5.1 CRASH_THRESHOLD = 15 was calibrated on synthetic

The v12 sweep that set `CRASH_THRESHOLD = 15` ran on synthetic regimes where ACO normal-regime noise has stddev ~2 and crash regimes drop 25-150 ticks. A threshold of 15 cleanly separates those.

Real-world ACO mid range on day 1 was ±15 around the FV. The threshold sits right at the boundary of normal noise. Any anchor bias pushes one side of the noise distribution past it.

### 5.2 Banker's rounding amplified the asymmetry

`round(5003.5)` could plausibly return 5003 or 5004. Python's half-to-even rule returns 5004 because 5004 is even. If it had gone the other way the anchor would have been 10,006, crash window `[9,991, 10,021]`, still hitting the 9,990 dip but with fewer ticks. The bootstrap is sensitive to a 1-unit rounding choice.

### 5.3 No hysteresis on the threshold

Each 1-tick flicker across the threshold fires crash_mode for that single tick. 200 episodes produced 512 flickered ticks. Hysteresis (enter at dev > 15, exit at dev < 10) would cut flicker count but doesn't fix the underlying anchor offset.

---

## 6. Fix candidates (for Round 2+)

Ranked by preference.

### 6.1 Delay the bootstrap until the book is symmetric

```python
if self.aco_anchor is None:
    bid_vol = book.buy_orders[max(book.buy_orders)]
    ask_vol = abs(book.sell_orders[min(book.sell_orders)])
    spread = min(book.sell_orders) - max(book.buy_orders)
    if spread <= 20 and 0.5 <= bid_vol / ask_vol <= 2.0:
        self.aco_anchor = _snap_anchor(cur_mid)
    # else: don't bootstrap yet; try next tick
```

Pros: cleanly rejects biased opens. Cons: may never bootstrap on a persistently asymmetric day, falling back to `ACO_FV=10000`.

### 6.2 Use median of first N symmetric mids

```python
if self.aco_anchor is None:
    self.aco_bootstrap_samples.append(cur_mid)
    if len(self.aco_bootstrap_samples) >= 20:
        self.aco_anchor = _snap_anchor(statistics.median(self.aco_bootstrap_samples))
```

Pros: averages out tick-0 asymmetry. Cons: anchor unavailable for first 20 ticks (negligible, ~20 PnL).

### 6.3 Raise CRASH_THRESHOLD to absorb anchor noise

Raise from 15 to 20 or 22. The synthetic sweep that chose 15 was dominated by gradient-crash detection speed. On real data where flicker cost exceeds gradient-detection speed benefit, a wider threshold is net-positive.

Pros: one-line change. Cons: slower to catch real gradient crashes.

### 6.4 Prefer hardcoded anchor when FV is knowable

For products where we're confident the FV is a specific round number (ACO at 10,000, AMETHYSTS at 10,000, RESIN at 10,000), skip the bootstrap and use the hardcoded anchor. v17's bootstrap only pays off in the (unrealized) scenario where IMC shifts FV to something unexpected like 14,000.

Rule of thumb: use bootstrap only for products whose FV we can't reason about from first principles.

### 6.5 Update synthetic generator to include asymmetric-open regimes

Add regimes that open with:
- Asymmetric bid/ask volumes (2:1, 3:1 ratios)
- Bid or ask side starting 5-10 ticks off from FV
- One-sided opens (only bid or only ask at tick 0)

Would re-rank v17 vs v14 on the bench and surface any future architectural changes fragile to open-book microstructure.

---

## 7. Comparison summary

| Strategy | Day 1 tutorial (1k) | Extrapolated 10k | Actual full R1 |
|---|---:|---:|---:|
| r1_v4 | 10,624.84 | ~106,248 | (not submitted) |
| r1_v14 | 10,443.78 | ~104,437 | (not submitted) |
| r1_v17 submitted |  | ~106,000 expected | 89,861.44 |
| Nancy's algov4 | 10,734.03 | ~107,340 | unknown |

The actual-vs-extrapolated gap for v17 (~16k shortfall) is partly the ~1,743 crash_mode cost above, and partly that ACO PnL doesn't scale linearly with ticks (fills are taker-arrival-rate-limited, not tick-count-limited). ACO went from 3,179 (1k) to 10,534 (10k), a 3.31× scaling. Close to taker-arrival scaling, not the 10× tick scaling.

For IPR, the 10.65× scaling (7,446 to 79,327) beat the 10× linear projection because Round 1 day 1 had unusually strong drift (+1,001 over 10k ticks vs typical +100/1k = +1,000/10k). Drift-efficient day, drift-capture code ran at peak efficiency.

---

## 8. Lessons for Round 2+

1. v17's bootstrap is not free insurance. If the open book has ≥5-tick bid-ask asymmetry, it costs real PnL.
2. Synthetic tests need microstructure variation at open, not just regime-level variation across the day.
3. Hardcoded FV beats bootstrap when we can reason about FV from first principles. Reserve bootstrap for products where the FV is genuinely unknown.
4. Circuit breakers need hysteresis if the threshold sits near the boundary of normal noise. Enter at `dev > T`, exit at `dev < T - margin`.
5. Banker's rounding bit us again. Cost ~150 PnL in v7 (midpoint handling), now ~1,743 in v17 (anchor snap). Be explicit: `int(math.floor(x + 0.5))` for half-up, not `round()`.
6. Per-tick PnL diagnostics are essential. Slicing day PnL by crash_mode state immediately surfaced the failure. Build this into future strategies as standard telemetry.

---

## 9. Dev-vs-Real comparison (via Superduperbread's trading_analyzer.html)

Superduperbread shared an HTML log analyzer (saved to `trader-logic/round-1/analyzer/trading_analyzer.html`) that diffs dev vs real runs side by side. We ran r1_v17 locally on CSV day 0 full-10k to produce a dev log and loaded both against 272466.

### 9.1 Stat-row summary

| Metric | Real (272466, day 1) | Dev (BT day 0) | Gap |
|---|---:|---:|---:|
| Total PnL | 89,861 | 96,127 | −6,266 |
| IPR PnL | 79,327 | 79,460 | −133 (0.2%) |
| ACO PnL | 10,534 | 16,667 | −6,133 (−37%) |
| IPR drift | +1,001 | +1,002 | identical |
| IPR start to end | 12,998 to 14,000 | 11,998 to 13,000 | same magnitude, different level |
| ACO spread (median) | 16 | 16 | identical |
| ACO spread (mean) | 16.18 | 16.18 | identical |
| Ticks | 10,000 | 10,000 | matched |

Superduperbread's claim "higher volatility in real run but same spread" is partially wrong. ACO mean spread is 16.18 in both runs. IPR drift rate is identical. What's actually different is fill efficiency (next section).

### 9.2 ACO PnL deciles (where real lost ground)

| Decile | Real gain | Dev gain | Gap (dev − real) |
|---|---:|---:|---:|
| 0-10% | +2,624 | +2,103 | −521 |
| 10-20% | +1,645 | +1,341 | −304 |
| 20-30% | −56 | +2,234 | +2,290 |
| 30-40% | +2,532 | +1,874 | −658 |
| 40-50% | +260 | +1,543 | +1,283 |
| 50-60% | +1,372 | +2,574 | +1,201 |
| 60-70% | +715 | +514 | −201 |
| 70-80% | +112 | +1,104 | +991 |
| 80-90% | +1,223 | +2,115 | +892 |
| 90-100% | +145 | +1,925 | +1,780 |

Real wins deciles 0-10%, 10-20%, 30-40%, 60-70%. Real loses big in deciles 20-30%, 40-50%, 50-60%, 70-80%, 80-90%, 90-100%. The 20-30% decile is where the first big crash_mode episode cluster fires (mid dipping to 9,990-9,992 at ts 232,700+) and real actually went negative (−56) while dev gained +2,234.

### 9.3 Crash_mode comparison (anchor sensitivity)

| Run | Bootstrap anchor | Crash ticks | % of day | Episodes | Crash per-tick | Normal per-tick |
|---|---:|---:|---:|---:|---:|---:|
| Real (day 1) | 10,008 | 512 | 5.12% | 199 | −1.458 | +1.189 |
| Dev (day 0) | 10,004 | 139 | 1.39% | 46 | −86.93 | +2.916 |

Dev bootstraps anchor 4 ticks closer to FV=10,000 than real, leading to 3.7× fewer crash episodes. Dev's per-tick crash PnL is far more negative (−86.93) because dev concentrates its few crash events at high-inventory moments where MTM swings dominate; real's crash ticks are mostly flickers at low inventory.

### 9.4 The uncomfortable truth: real's normal-mode PnL rate is 2.5× slower than dev's

- Real normal-mode: +1.189 PnL/tick × 9,488 normal ticks = 11,280 PnL
- Dev normal-mode: +2.916 PnL/tick × 9,861 normal ticks = 28,751 PnL
- Even if crash_mode had fired zero times on real, predicted real ACO PnL would be only 11,890, still ~4,800 below dev's 16,667 prediction.

Crash_mode flicker explains at most ~1,743 of the 6,133 gap. The remaining ~4,400 is the structural BT-vs-real gap for ACO we've documented before (the "60× gradient overshoot" pattern in `memory/feedback_backtester.md`). The backtester runs over CSV data where the taker bot's flow was recorded without our orders; the dev run rides free on that recorded flow. In reality the taker bot has a fixed per-time arrival rate and only a fraction of our passive orders get hit per tick. BT fill rates are ~2.5× real in normal conditions.

### 9.5 Dev ACO position behavior (why we thought we'd score more)

Dev held inventory aggressively:
- 17% of time at +80 (pinned long)
- 22% at ±80 limit combined
- Only 1.8% near-flat
- Mean |position|: 58.5

This produces large MTM swings that get captured as realized PnL when the position unwinds. On CSV, unwinds happen reliably at favorable prices because the CSV already knows the future mid path. On real data, position unwinds are less reliable and we miss the favorable exits.

Superduperbread's observation "biggest difference is inventory management" is consistent with this: dev BT accumulates and unwinds aggressively because of CSV bias; real data can't support the same efficiency.

### 9.6 Implications for Round 2+

1. Never trust dev ACO numbers absolutely. BT × 0.63 is a reasonable default for ACO-like products.
2. Dev IPR numbers do transfer. 0.2% gap on IPR is within noise. Drift products are BT-reliable.
3. Crash_mode flicker is the dominant controllable leak. The 2.5× BT-vs-real rate gap is a structural tax we can't easily eliminate; the anchor-offset flicker cost is fixable.
4. The analyzer dashboard lives at `trader-logic/round-1/analyzer/trading_analyzer.html`. Use it for every future submission post-mortem. Run `python -m prosperity4bt <strategy.py> 1-0 --ticks 10000` to generate a dev log matching a 10k competition day.

---

## Appendix: Files referenced

- Strategy: `run-logs/round-1/272466/272466.py` (= `trader-logic/round-1/r1_v17.py`)
- Activity log: `run-logs/round-1/272466/272466.json` (1.5 MB, 20,000 rows)
- v14 reference: `trader-logic/round-1/r1_v14_defensive.py`
- Synthetic bench: `trader-logic/round-1/experiments/synthetic/generate.py`, `run_all.py`
- Analyzer: `trader-logic/round-1/analyzer/trading_analyzer.html` (Superduperbread)
- Dev log (r1_v17, day 0, 10k ticks): `backtests/2026-04-17_22-48-06.log`
- Calibration notes: `memory/project_round1_calibration.md`
- Memory record: `memory/project_round1_final.md`
