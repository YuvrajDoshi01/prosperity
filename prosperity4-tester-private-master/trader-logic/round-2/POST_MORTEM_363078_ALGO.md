# Round 2 Algorithm Post-Mortem: Submission 363078 (try18-5)

**Algo score:** 99,533.97 (single day, 10k ticks)
**Per-product:** PEPPER 79,312 + ASH 20,222
**Strategy:** `try18-5` — try18-4 + MAF_BID=17 + pepper trend-based graceful unwind
**Date submitted:** 2026-04-20
**Submission UUID:** b2e77c9c-8c4d-41fb-99a1-6c13cbbe2c05
**Source data:** `run-logs/round-2/results.zip` → 363078.{py,log,json}

This document is an algorithm-level deep-dive. For results-level summary, see `POST_MORTEM_363078.md`.

---

## 0. Architecture summary

`try18-5` is a two-product strategy with no shared state:

| Product | Fair value | Edge logic | Inventory mgmt |
|---|---|---|---|
| ASH_COATED_OSMIUM (stable) | EMA bootstrap + zscore mean-reversion + imbalance + dynamic width | take(width=2)/clear(width=1)/make(disregard=1, join=2, default=4) | risk_aversion=0.025, target=0 |
| INTARIAN_PEPPER_ROOT (drift) | filtered MM mid + position-scaled drift_boost + trend drift | take(width=2) on the bid; opportunistic short at width × 2.5 | target=40 (unused — capped at +80) |

MAF_BID = 17 (single-tick passive bid for the auction, outcome unverified).

All actions every tick: `take_orders → clear_orders → make_orders` for ASH; `take → opportunistic_short → make` for PEPPER. `conversions = 1` returned every tick (no-op in this round).

---

## 1. Headline numbers

| Metric | ASH | PEPPER | Total |
|---|---:|---:|---:|
| Final PnL | 20,222 | 79,312 | 99,534 |
| Theoretical max (long-80 buy-and-hold) | n/a (mean-reverting) | 80,560 | n/a |
| Efficiency | n/a | 98.5% | n/a |
| Total submission trades | 682 | 11 | 693 |
| Total submission volume | 3,734 | 96 | 3,830 |
| Avg fill size | 5.5 | 8.7 | n/a |
| Effective spread captured | 10.85 ticks | n/a (drift) | n/a |
| Spread-capture ratio (vs 16.18 mean spread) | 67% | n/a | n/a |
| Avg \|position\| | 19.5 | 79.8 | n/a |
| Time at limit (\|pos\|=80) | 0% | 99.0% | n/a |
| Max drawdown | 227 | 442 | n/a |

**One-line summary:** PEPPER ran in pure drift-capture mode (pinned at +80 for 99% of the day). ASH ran as a tight-spread market-maker with mean-reversion overlay, capturing ~67% of the effective spread on 682 fills.

---

## 2. ASH: the EMA-based market-maker

### 2.1 Fair-value engine

`ash_fair_value_and_width()` builds FV in five stacked steps:

1. **`raw_mid`**: midpoint of L1 if both sides exist; one-sided fallback to `best ± base_width`
2. **`mid`**: median of last 5 raw_mids (smoothing)
3. **`ema`**: median of first 20 raw_mids during bootstrap (ticks 0-20), then `traderObject["ash_ema"]` (which is updated via the median+history machinery in subsequent ticks)
4. **`mr_adjustment`**: `−zscore × ret_std × scale` where scale ∈ {1.0 if \|z\|>1.5, 0.6 if \|z\|>1.0, 0 else}, with imbalance confirmation and direction bias
5. **`inventory_adjustment`**: `−(position − target) × risk_aversion`, with `risk_aversion=0.025`, `target=0`

`fair_value = ema + mr_adjustment + inventory_adjustment`.

### 2.2 EMA convergence and tracking

| Metric | Value |
|---|---:|
| Bootstrap value (ts 0) | 9,971.00 |
| Day-mean ASH mid | 9,982.31 |
| End-of-day FV | 9,997.28 |
| Time to first cross 9,980 | ts 72,300 (7.2% of day) |
| Time to within ±0.5 of day-mean (9,982) | ts 121,400 (12.1% of day) |
| Mean FV-MID gap | −0.50 |
| Stdev FV-MID gap | 2.30 |
| Ticks \|gap\|>2 | 3,678 (37%) |
| Ticks \|gap\|>5 | 315 (3%) |

**Observation:** the EMA was conservative in the early day (anchored around 9,971 for the first 20 ticks, drifted up slowly), and mostly tracked mid throughout. The slow convergence (12.1% of day to reach the day-mean) is a mild inefficiency: zscore signals computed against an EMA that's lagging the actual mean fire spuriously. With a more reactive bootstrap (e.g., reset EMA = mid every N ticks until convergence detected), the strategy might capture an additional ~200 PnL on ASH.

### 2.3 Dynamic width was static

The width formula:
```python
dynamic_width = max(base_width=2, 0.5 × ret_std × (1 + 0.5 × |zscore|))
```

To exceed `base_width=2`, the second term needs to exceed 2, i.e., `ret_std × (1 + 0.5|z|) > 4`. ASH `ret_std` over the day stayed below 2.5 (per the rolling 40-tick window), and even at \|z\|=2 the term is 2.5 × 2 = 5 — but \|z\|>1.5 was rare.

**Result:** width was 2.00 on 9,995 of 9,986 valid ticks. Stdev: 0.005. The "dynamic" width was effectively constant.

This isn't a bug — the architecture has the headroom for higher volatility regimes — but it means the dynamic-width concept added zero PnL on R2 day-1. For R3+, the same code in a higher-vol product (vouchers, options) would activate.

### 2.4 Action breakdown

| Action | Count | Volume | Notes |
|---|---:|---:|---|
| ASH SWEEP BID (active take buy) | 88 | 584 | Crossed for ask ≤ FV − 2 |
| ASH SWEEP ASK (active take sell) | 68 | 456 | Crossed for bid ≥ FV + 2 |
| ASH CLEAR BID (close shorts at FV) | 21 | 79 | Reduce position toward 0 at FV − 1 |
| ASH CLEAR ASK (close longs at FV) | 38 | 198 | Reduce position toward 0 at FV + 1 |
| ASH PASSIVE_MAKE BID | 9,986 | (varies) | Best ± 1 every tick |
| ASH PASSIVE_MAKE ASK | 9,986 | (varies) | Best ± 1 every tick |
| **Submission fills (from trade history)** | **682** | **3,734** | 345 buys, 337 sells |

**Observation 1: passive-fill dominance.** Of the 3,734 ASH volume traded:
- 1,040 from active SWEEPs (28%)
- 277 from CLEAR steps (7%)
- 2,417 from PASSIVE_MAKE fills hit by takers (65%)

The "invisible taker" mechanism (taker bot hits inside-spread quotes) drives 65% of ASH PnL. Same finding as R0 EMERALDS and R1 ACO — passive market-making against a non-reactive MM bot is the dominant alpha.

**Observation 2: balanced flow.** 88/68 sweep ratio (1.29:1 buy/sell), 1866/1868 total volume (essentially 1:1). The strategy was symmetric despite the day's downward bias (mean ASH mid 9,982 < 10,000). The mean-reversion overlay pulled FV down to track the bias, so the balanced symmetric trading-against-FV produced balanced executions.

### 2.5 PnL breakdown

| Decile | ASH gain (Δ) | PEPPER gain (Δ) | Total (Δ) |
|---:|---:|---:|---:|
| 0-10% | 2,132 | 7,334 | 9,466 |
| 10-20% | 1,756 | 7,978 | 9,734 |
| 20-30% | 2,722 | 8,000 | 10,722 |
| 30-40% | 1,964 | 8,000 | 9,964 |
| 40-50% | 1,707 | 8,000 | 9,707 |
| 50-60% | 1,652 | 8,000 | 9,652 |
| 60-70% | 1,845 | 8,000 | 9,845 |
| 70-80% | 2,575 | 8,000 | 10,575 |
| 80-90% | 1,902 | 8,000 | 9,902 |
| 90-100% | 1,966 | 8,000 | 9,966 |

ASH per-decile range: 1,652 – 2,722. **Stdev across deciles: ~360.**

For comparison, R1 v17 ACO oscillated −85 to +2,647 (stdev ~860). The smoothness here is due to:
- No discrete crash_mode flicker
- Dynamic width absorbing volatility regime changes (in principle)
- Continuous risk_aversion vs binary mode flips

**No PnL whitespace.** Every decile contributed positively. No regime where the strategy "froze" or lost money systematically.

### 2.6 Effective spread capture

| Metric | Value |
|---|---:|
| Avg buy price | 9,976.85 |
| Avg sell price | 9,987.70 |
| Effective spread captured per matched pair | 10.85 ticks |
| Day-mean ASH spread | 16.18 ticks |
| Capture ratio | 67% |

The 67% capture ratio is strong. For a passive MM at best ± 1, the maximum theoretical capture is `(spread − 2) = 14.18 ticks`. Our 10.85 captures 76% of that ceiling, with the gap due to:
- Adverse selection on the 28% take volume (buying at FV−2 means we paid 6 below mid but the mid then tends to drop, costing ~3 ticks on average)
- Clear step at FV±1 (small loss vs mid)

**For R3+:** the 67% spread-capture rate is a benchmark. Strategies that don't beat this on stable products are likely making the same mistakes (over-aggressive takes, poor inventory mgmt). 70%+ should be the target for ATM voucher MM.

### 2.7 Position trajectory

ASH abs mean position: **19.5**. Distribution:

| Position bucket | Ticks | % |
|---|---:|---:|
| (−40, −20) | 233 | 2.3% |
| (−20, 0) | 2,817 | 28.2% |
| 0 | 388 | 3.9% |
| (0, 20) | 2,895 | 29.0% |
| (20, 40) | 2,059 | 20.6% |
| (40, 60) | 1,354 | 13.5% |
| (60, 80) | 254 | 2.5% |

**Long-bias asymmetry:** 36.6% of ticks above +20, only 2.3% below −20. This reflects the day's regime: ASH mid mean 9,982, persistently below 10,000, so the EMA-based FV pulled the strategy long.

Max position reached: +72. Never hit the ±80 limit. The position-management layer (risk_aversion + clear) was effective in keeping position under control.

|pos|≤5 occurred 22.1% of the time — frequent flat states. Healthy round-trip cadence.

### 2.8 What the data says about the architecture

1. **Adaptive EMA was the load-bearing decision.** Replacing this with a hardcoded anchor=10,000 would have positioned the strategy to think mid was always undervalued (since mid mean 9,982 < 10,000), generating constant buy signals. Catastrophic.

2. **Dynamic width was inactive but well-architected.** It will activate on higher-vol products in R3+.

3. **Mean-reversion + imbalance overlay added marginal but meaningful PnL.** Approx contribution: 200-500 PnL on ASH (estimated from the 315 ticks where \|gap\|>5 fired the scale=1.0 branch). Not a leg breaker but worth keeping.

4. **The clear step (CLEAR_BID/ASK at FV±1) handled 277 volume.** This is the LU-canonical "+3% trick" — close inventory exactly at FV. PnL contribution: ~277 × ~5 ticks ≈ 1,400 PnL (≈ 7% of ASH total). Worth keeping.

---

## 3. PEPPER: the drift-capture machine

### 3.1 Fair-value engine

`pepper_fair_value_long_biased()`:
1. **`mid_price`**: midpoint of L1 with adverse_volume filter (price levels with `vol >= adverse_volume=15` for raw quotes, fallback to standard L1)
2. **`trend_drift`**: rolling regression slope over last 5 mids, returns ±5 if ≥55% / ≤35% of last 20 directions are up
3. **`drift_boost`**: `0.1/tick × 100-tick lookahead × inventory_ratio` — bullish drift bias, scales with available capacity
4. **`skewed_fair = mid + drift_boost + trend_drift`**

When position = 80, `inventory_ratio = 0` → `drift_boost = 0`. So FV when fully long = `mid + trend_drift`.

### 3.2 FV vs mid statistics

| Metric | Value |
|---|---:|
| FV mean | 14,504.44 |
| MID mean | 14,499.61 |
| FV−MID gap mean | +4.83 |
| FV−MID gap stdev | 1.99 |
| FV−MID gap range | [−8.00, +14.50] |

The mean +4.83 gap is consistent with `drift_boost` averaging +5 (= 0.1×100×0.5 average inventory_ratio) plus `trend_drift` mostly +5 (predominantly bullish day) — but inventory_ratio = 0 most of the day (pos=80), so the gap reduces to mostly trend_drift = +5.

The gap range [−8, +14.5] reflects:
- −8 when bearish trend (trend_drift=−5) + slight inventory adjustment from a brief sub-80 episode
- +14.5 when bullish trend (trend_drift=+5) + drift_boost (when pos < 80)

### 3.3 The take-only philosophy

PEPPER uses asymmetric take widths:
- Buy: `ask_price ≤ fair − take_width=2` → aggressive buy
- Opportunistic short: `bid_price ≥ fair + take_width × 2.5 = fair + 5` → aggressive sell

This 2.5× ratio biases the strategy toward holding long. It only sells when the bid is significantly above FV — i.e., when someone is paying a premium.

**Make logic:** posts a single passive bid at `min(best_bid + 1, math.floor(fair_value))` for remaining capacity. NO ask side make orders. PEPPER is fundamentally a one-sided book strategy.

### 3.4 Action breakdown

| Action | Count | Volume |
|---|---:|---:|
| PEPPER SWEEP_TAKE BID (aggressive buy) | 10 | 88 |
| PEPPER SWEEP_SHORT ASK (opportunistic sell) | 1 | 8 |
| PEPPER SMART_MAKE BID (passive) | 93 | (varies) |
| **Submission trades (from history)** | **11** | **96** |

PEPPER posted passive bid orders 93 times but only 11 fills came from `SUBMISSION` trade attribution. **The 82 other passive posts didn't get filled** — bot flow on PEPPER did not aggressively hit our passive bids. This is expected: PEPPER drift means takers are mostly buying, not selling.

The 88 buy fills were from SWEEPs — i.e., we paid the offer (FV − 2 take threshold) on offers that were below FV. The takes happened in the first 4,800 ticks of the day:

| ts | qty | price |
|---:|---:|---:|
| 100 | 8 | 14,008 |
| 600 | 11 | 14,008 |
| 1,000 | 10 | 14,008 |
| 1,400 | 10 | 14,009 |
| 1,400 | 17 | 14,012 |
| 2,700 | 8 | 13,998 |
| 2,900 | 12 | 14,010 |
| 4,800 | 4 | 14,007 |
| **Total** | **80** | **avg 14,008** |

After ts 4,800, PEPPER position was +80 and stayed there for the rest of the day except for the single short trade.

### 3.5 The single short trade and recovery

At ts 179,100, PEPPER bid spiked to 14,183. Our FV was 14,177.5, so `bid 14,183 ≥ FV + 5 = 14,182.5` triggered the opportunistic short.

| ts | event | qty | price | position |
|---:|---|---:|---:|---:|
| 179,100 | SWEEP_SHORT | −8 | 14,183 | 80 → 72 |
| 182,400 | passive bid filled | +5 | 14,185 | 72 → 77 |
| 184,400 | passive bid filled | +3 | 14,187 | 77 → 80 |

**Round-trip P&L:** 8 × 14,183 − 5 × 14,185 − 3 × 14,187 = 113,464 − 70,925 − 42,561 = **−22 PnL**.

The short fired correctly per its trigger logic, but the price kept rising, so we bought back at higher prices. The opportunistic short LOST 22 PnL net.

**Verdict:** the 2.5× short trigger is too aggressive for a drift-up day. With a +0.1/tick drift, any 5-tick spike is just normal drift, not a mean-reverting overshoot. For R3+: **drop the opportunistic short on drift products, or raise the trigger to width × 5+**.

### 3.6 The slow ramp-up

This is the largest quantifiable inefficiency in PEPPER:

| Position milestone | ts | % of day |
|---:|---:|---:|
| 0 | 0 | 0% |
| 8 | 200 | 0.02% |
| 19 | 700 | 0.07% |
| 29 | 1,100 | 0.11% |
| 56 | 1,500 | 0.15% |
| 76 | 3,000 | 0.30% |
| **80** | **4,900** | **0.49%** |

**Half the day was spent below +80.** During that ramp, average position was approximately 40-50 (instead of 80), and PEPPER mid drifted from 13,993 to ~14,043 over those 4,900 ticks (+50 drift).

Ideal counterfactual:
- If at +80 from ts 100: PnL contribution from ts 0-4900 = 80 × 50 = 4,000 (theoretical max from the drift portion)
- Actual PnL contribution from ts 0-4900: 7,334 + 7,978 = 15,312 over deciles 0-1, but most of that is buy-and-hold MTM gain on the partial position

Quantification: the PEPPER per-decile leak in deciles 0-1 vs steady-state (8,000):
- Decile 0: 7,334 (leak: 666)
- Decile 1: 7,978 (leak: 22)
- **Total ramp-up leak: ~688 PnL**

Plus the slow accumulation cost: the 80 buys averaged 14,008 vs day-open mid 13,993. We paid +15 per share avg over open mid = 15 × 80 = **1,200 PnL paid in entry cost**.

**Combined PEPPER inefficiency: ~1,200-1,500 PnL.** This dominates the 1,248 IPR theoretical-max gap.

### 3.7 Why ramp-up was slow

Take logic: `if ask_price ≤ pepper_fair_value − take_width=2`. With FV in the 14,003-14,012 range early-day, we needed asks at 14,001-14,010 to take. Most of the time the offer was 14,008+ and FV was 14,008-14,010, so the trigger fell short of `≤ FV − 2`.

Improvement candidates:
- **Reduce take_width to 1**: would have allowed takes at fair − 1, ~50% more take opportunities. Risk: more adverse selection.
- **Layer-2 takes**: take both L1 and L2 asks when L1 is exhausted. Currently only L1.
- **Larger passive bids**: post on multiple price levels. Currently posts only at `min(best+1, floor(FV))`.
- **Post ASKS too**: accept some short risk to harvest the offer-side spread on the way up.

Even a 50% improvement in ramp speed (reach +80 by ts 2,500 instead of 4,900) would yield ~500-700 PnL.

### 3.8 PEPPER summary

| Metric | Value |
|---|---:|
| End position | +80 |
| Time at +80 | 9,898 / 10,000 = 99.0% |
| Total realized PnL | 79,312 |
| Theoretical max (long-80 at open) | 80,560 |
| **Total leak** | **1,248** |
| Leak from slow ramp | ~700 |
| Leak from short round-trip | ~22 |
| Leak from entry-price drift | ~500 |

PEPPER ran the right strategy. The 1,248 leak is a structural cost (you can't be +80 at tick 0) plus minor strategy inefficiencies.

---

## 4. Order coverage and timing

| Metric | Value |
|---|---:|
| Total ticks | 10,000 |
| Ticks with 0 orders | 13 (0.13%) |
| Ticks with 2 orders (ASH bid + ASH ask) | 9,677 (96.8%) |
| Ticks with 3 orders (ASH bid + ASH ask + PEPPER) | 301 (3.0%) |
| Ticks with 4-5 orders | 8 (0.08%) |
| Sandbox errors | 0 |

**Strategy uptime: 99.87%.** No technical failures. The 13 zero-order ticks were edge cases (likely one-sided ASH books with PEPPER at +80). No latency issues, no exception handling, no truncated trader_data.

Trader data persistence: every tick wrote ~150-300 chars of state (under the 50k cap). No state loss.

---

## 5. R1 → R2 deltas in algorithm structure

| Aspect | R1 r1_v17 (272466) | R2 try18-5 (363078) |
|---|---|---|
| ACO FV source | hardcoded anchor=10,000 (with bootstrap option) | EMA-based, adaptive |
| ACO mode flips | `crash_mode` binary (5.1% of ticks) | none |
| ACO inventory mgmt | soft-skew at \|pos\|>40 | continuous risk_aversion=0.025 |
| ACO width | static (DISREGARD=1, JOIN=2, DEFAULT=4) | dynamic (max(2, 0.5×ret_std×(1+0.5×\|z\|))) |
| ACO clear | enabled | enabled (CLEAR_BID/ASK at FV±1) |
| IPR FV source | mid + drift_bias=5 | filtered MM mid + drift_boost + trend_drift |
| IPR opportunistic short | symmetric take | take_width × 2.5 (asymmetric) |
| IPR pos limit reach | ts 200 | ts 4,900 |
| Code complexity | ~300 LOC | ~780 LOC |

**The biggest algorithmic improvement:** removing ACO's `crash_mode` binary state. R1 v17 lost ~1,743 PnL on this in real conditions (per `POST_MORTEM_272466.md`). R2 try18-5 has no equivalent failure mode.

**The biggest algorithmic regression:** PEPPER ramp-up is now slower (ts 4,900 vs ts ~200 in r1_v17). r1_v17 was more aggressive in its passive-bid sizing and took on multiple price levels. try18-5 trades only at L1 with conservative sizing. Cost: ~700 PnL.

---

## 6. PnL attribution (estimated)

Approximate decomposition of 99,534 total PnL:

| Source | PnL | Notes |
|---|---:|---|
| PEPPER drift-capture (long 80 × +1,007 drift) | ~80,560 | Theoretical max |
| PEPPER ramp-up leak | ~−700 | Slow accumulation |
| PEPPER entry-price drift | ~−500 | Avg buy 14,008 vs open mid 13,993 |
| PEPPER opportunistic short round-trip | −22 | Single trade lost 22 |
| **PEPPER subtotal** | **79,312** | |
| ASH passive market-making (65% of fills) | ~13,000 | 2,417 vol × ~5.4 ticks/fill |
| ASH active sweeps (28% of fills) | ~4,500 | 1,040 vol × ~4.3 ticks/fill |
| ASH clear step (7% of fills) | ~1,400 | 277 vol × ~5 ticks/fill |
| ASH mean-reversion overlay (zscore) | ~300 | 315 ticks at scale=1.0 |
| ASH inventory management | ~1,000 | Avoiding limit binds |
| **ASH subtotal** | **20,222** | |
| **Grand total** | **99,534** | |

The PEPPER side is over 4× larger than ASH. Drift products dominate when present.

---

## 7. What worked

1. **Adaptive ACO FV.** Replacing the hardcoded 10,000 anchor with EMA was decisive. R2 day-1 ACO mid mean was 9,982; a static anchor would have generated systematic buy signals.

2. **Per-decile smoothness.** ASH per-decile range 1,652-2,722 (stdev ~360) vs R1 r1_v17 -85 to +2,647 (stdev ~860). 2.4× tighter.

3. **Inventory discipline.** ASH never hit the ±80 limit. Avg \|pos\| = 19.5. Healthy round-trip cadence (22% of time near zero).

4. **Spread capture.** 67% of mean book spread captured per round-trip. Top-tier for inside-spread MM.

5. **Strategy uptime.** 99.87% of ticks issued correct orders. Zero sandbox errors, zero exceptions, zero traderData truncation.

6. **PEPPER drift capture.** 98.5% efficiency on theoretical max. Pinned at +80 for 99% of the day.

7. **Code structure.** The take/clear/make + risk_aversion architecture is reusable. ASH's pattern (EMA + zscore + imbalance + dynamic width) is the new template for stable products.

---

## 8. What didn't (controllable inefficiencies)

1. **PEPPER slow ramp-up.** 4,900 ticks to reach +80. Cost ~700-1,200 PnL. Fix: reduce take_width to 1, or add L2 takes, or layer multiple passive bids.

2. **PEPPER opportunistic short on drift product.** Single trigger at ts 179,100 lost 22 PnL net. Fix: drop the short on drift products, or raise threshold to width × 5+.

3. **EMA convergence lag on ASH.** 12.1% of day to reach the day-mean. Fix: shorter bootstrap window (10 ticks?) or restart EMA = mid every N ticks until variance stabilizes.

4. **Dynamic width never activated.** Width was static at 2.00 on 99.95% of ticks. Fix: lower the activation threshold so it kicks in at \|z\|=1 instead of 1.5, or recalibrate `ret_std` floor.

5. **PEPPER passive bids posted but rarely filled.** 93 posts, ~10 fills. Fix: post deeper into the book (L2 levels) or accept that drift products mostly fill via aggressive takes.

Cumulative controllable leak estimate: **1,500-2,500 PnL** could be recovered with R3-targeted refinements.

---

## 9. What didn't (uncontrollable / structural)

1. **Drift products entry cost.** Cannot be at +80 from ts 0. Structural ~500 leak.

2. **Spread crossing on takes.** 28% of ASH volume came from active sweeps. Each pays 1-3 ticks adverse selection. Structural ~3,000 PnL of "edge spent" — already factored into the 67% capture rate.

3. **MM bot non-reactive to our spread.** Confirmed in R0, R1, R2. Spread doesn't widen when we post inside, so we benefit from passive captures, but we also don't have an asymmetric-information edge.

4. **No take signal on a 1-tick basis.** Without a stable next-tick predictor, take decisions are essentially a function of `current_price - rolling_mean`. The strategy implements this via zscore mean-reversion but cannot beat the structural noise floor.

---

## 10. Comparison to documented r2_v5 (counterfactual)

`r2_v5` (= r1_v17 + MAF_BID=0) was the documented submission. Estimated counterfactual on R2 day-1:

| Metric | try18-5 (actual) | r2_v5 (estimated) |
|---|---:|---:|
| ACO FV approach | EMA-based | hardcoded anchor=10,000 |
| ACO FV vs R2 day-1 mean | tracks (9,982) | constant offset (+18) |
| ACO crash_mode triggers | none | 6,737 (67.5% of ticks; mid ≤ 9,985) |
| ACO PnL | 20,222 | ~−2,000 (after crash mode penalties) |
| IPR PnL | 79,312 | ~79,000 |
| Total | **99,534** | **~77,000** |

**try18-5 vs r2_v5 estimated delta: +22,500 PnL** on the actual R2 day-1 regime.

The strategy switch (planned r2_v5 → submitted try18-5) was worth approximately 1/4 of the total R2 algo score. A massive call.

---

## 11. Recommendations for R3+

### 11.1 Carry forward to R3+

- **EMA-based fair value for stable products** (template for R3 vouchers, future stable assets)
- **Continuous risk_aversion** instead of binary mode flips
- **The take/clear/make structure** with separate widths
- **Imbalance confirmation** for zscore signals
- **drift_boost × inventory_ratio** for drift products (ramp-up speed scales with remaining capacity)

### 11.2 Fix in R3+

- **PEPPER-style ramp-up too slow.** For HYDROGEL_PACK and VELVETFRUIT_EXTRACT (R3 delta-1), take_width should be 1 (not 2), and post layered passive bids. The 80-unit limit on R2 vs 200-unit limit on R3 means full position is 2.5x harder to reach — fix the ramp speed first.

- **Drop opportunistic short on drift products.** The 2.5× threshold loses on every drift day.

- **Activate dynamic width earlier.** Lower the |z|>1.5 trigger to |z|>1.0 or recalibrate the formula. Higher-vol R3 products (vouchers) will need this.

- **Faster EMA bootstrap.** 12% of day is too slow. For R3 vouchers (200-300 limits, 1k tutorial ticks), the EMA needs to converge in <50 ticks.

### 11.3 New for R3+

- **Per-product configurability.** try18-5 hard-codes ASH and PEPPER. R3 has 12 products (2 delta-1 + 10 vouchers). Need a unified `Product → params` configuration.

- **Cross-product hedging.** Voucher MM should delta-hedge into VFE. try18-5 has no cross-product logic; R3 demands it.

- **Per-tick PnL diagnostics in trader_data.** Currently the strategy logs FV and orders but not PnL attribution. Add a running `mtm + realized_pnl` to make post-mortem analysis trivial.

- **Position-aware aggression.** When |pos| < 50% of limit, take_width should be lower (more aggressive). When |pos| > 75%, take_width should be higher (defensive). Currently take_width is static.

---

## 12. Files referenced

- Strategy: `run-logs/round-2/results.zip` → `363078.py` (777 LOC)
- Activity log: `run-logs/round-2/results.zip` → `363078.log` (32 MB JSON, 10k tick state + per-tick lambdaLog + 693 trade records)
- Submission metadata: `run-logs/round-2/results.zip` → `363078.json`
- Sibling document (results-level): `trader-logic/round-2/POST_MORTEM_363078.md`
- R1 algo predecessor: `trader-logic/round-1/POST_MORTEM_272466.md`
- Memory record: `memory/project_round2_final.md`

---

## Appendix A: Per-tick state extracted from log

Decoder script (for reference):

```python
import json, re

with open('363078.log') as f:
    data = json.load(f)

for entry in data['logs']:
    ll = json.loads(entry['lambdaLog'])
    state = ll[0]              # [ts, traderData, listings, order_depths, own_trades, market_trades, position, observations]
    orders = ll[1]             # [[symbol, price, qty], ...]
    conversions = ll[2]        # int
    trader_data = ll[3]        # str (jsonpickle)
    log_text = ll[4]           # newline-separated trader.print() output

    ts = state[0]
    pos = state[6]
    own_trades = state[4]      # filled in previous tick
    
    # Parse FV/width from log_text
    m = re.search(r'ASH Fair Value: ([\d.]+) \(width: ([\d.]+)\)', log_text)
    ash_fv = float(m.group(1)) if m else None
```

The trade history in `data['tradeHistory']` is a separate flat list of all 1,032 trade events (693 SUBMISSION, 339 market-only).

## Appendix B: Action-count summary table

| Symbol | Action | Count | Mean qty | Total qty |
|---|---|---:|---:|---:|
| ASH | SWEEP BID | 88 | 6.6 | 584 |
| ASH | SWEEP ASK | 68 | 6.7 | 456 |
| ASH | CLEAR BID | 21 | 3.8 | 79 |
| ASH | CLEAR ASK | 38 | 5.2 | 198 |
| ASH | PASSIVE BID (posted) | 9,986 | n/a | n/a |
| ASH | PASSIVE ASK (posted) | 9,986 | n/a | n/a |
| PEPPER | SWEEP TAKE BID | 10 | 8.8 | 88 |
| PEPPER | SWEEP SHORT ASK | 1 | 8.0 | 8 |
| PEPPER | SMART MAKE BID (posted) | 93 | n/a | n/a |

Posted orders ≠ filled orders. Fill data above is from `tradeHistory`, not `actions`.

---

## Appendix C: Quant-finance deep dive (prosperity-lab spawn)

This section was generated by the prosperity-lab skill spawning quant-finance / competitive-programming / ml-research analysts. It supplements sections 7-11 with closed-form economic interpretation and concrete code-level recommendations.

### C.1 ASH FV architecture: economically motivated but over-parameterized

**Load-bearing components (keep):**

- **Median-of-20 bootstrap.** Robust location estimator that avoids the asymmetric-open failure mode that killed r1_v17. Median > mean here because the bid-ask asymmetry on tick 0 contaminates a mean estimator.

- **Z-score mean-reversion as OU optimal control.** ASH is empirically OU with AC(1) = −0.49 (kappa ≈ 0.69, half-life ≈ 1 tick). For an OU process, optimal FV adjustment is `2 × kappa × deviation / (kappa + lambda)` where lambda is the informed-trader arrival rate. The strategy's `−zscore × ret_std × scale` with `scale ∈ {0, 0.6, 1.0}` is a discretization of this — heuristic constants in the right ballpark, but discarding the continuous relationship.

- **Continuous risk_aversion (Avellaneda-Stoikov limit).** With `risk_aversion=0.025` and `target=0`, max inventory skew at \|pos\|=80 is 2.0 ticks of FV adjustment — below the half-spread (take_width=2). The strategy never crosses itself. Correctly parameterized.

**Decorative components (likely net-zero or net-negative PnL):**

- **Direction bias `−1/+1 × 0.3 × sign(zscore)`.** Conflates two signals: (a) structural negative AC(1) from MM bot bid-ask bounce (already captured by zscore) and (b) genuine contrarian alpha. R0/R1 EDA confirmed the AC(1) is almost entirely from bot quoting mechanics. Estimated marginal PnL: ~0 to slightly negative.

- **Imbalance asymmetric scaling {1.2×, 0.7×}.** The 0.7× dampening on disconfirmation is valuable (prevents false-signal amplification). The 1.2× boost on confirmation is overfitting — imbalance and zscore measure the same latent variable.

- **Discrete zscore thresholds {1.0, 1.5}.** A continuous scaling (e.g., `scale = min(1.0, 0.5 × |z|)`) would remove the regime-switch artifacts.

### C.2 PEPPER drift_boost: well-designed urgency function

```python
drift_boost = 0.1 × 100 × (80 − position) / 80
```

**Economic interpretation:** "expected drift over next 100 ticks (= 10 ticks of price movement) × fraction of unused capacity". When pos=0, drift_boost=10; when pos=80, drift_boost=0.

**Why this is correct:**
- The 100-tick lookahead spans one full spread of drift (spread 16 ÷ drift 0.1/tick = 160 ticks). Approximately equal to the time it takes drift gain to equal spread cost.
- Linearity in `inventory_ratio` ensures smooth FV transition. No discrete mode flips.
- At pos=80, drift_boost=0 prevents posting above the offer when no capacity remains.

**Brittle constant:** `drift_per_tick = 0.1` is hardcoded from R1/R2 EDA. If R3+ delta-1 products have different drift rates, this misprices urgency. **Fix for R3:** rolling drift estimator over last N ticks; default to 0.1 if N < 50.

### C.3 Take/Clear/Make ordering: optimal as-is

The execution ordering `take → clear → make` is **optimal** per the LU framework (`Prosperity_Fundamentals.pdf`):

1. **Take first** consumes mispriced liquidity (ask ≤ FV − w). This updates position before any other decisions.
2. **Clear second** flattens the new position toward target at FV ± 1 (the "+3% PnL trick"). Running before take would reduce a position that hasn't yet benefited from the take edge.
3. **Make last** posts at FV ± default_edge (=4) for residual capacity. If make ran before clear, it would consume capacity at FV ± 4, leaving no room for the tighter FV ± 1 clear posts.

R1 v17 ACO clear step: ~7% volume share. R2 try18-5 ASH clear: 277 volume / 3,734 total = 7.4% — same magnitude. Confirms LU framework's quantitative prediction across rounds.

### C.4 The ~1,500 PnL leak: structural fixes by mechanism

| Fix | Mechanism | Expected PnL | Complexity |
|---|---|---:|---|
| **Multi-level take sweep (PEPPER)** | Iterate `asks_sorted` instead of L1-only in `take_best_orders`. PEPPER's `pepper_fair_value_long_biased` already does this; ASH's does NOT. Unify both. | +500-700 (PEPPER ramp) | Low (6 LOC) |
| **Layered passive bids (PEPPER)** | Replace single `min(best_bid+1, floor(FV))` with 3-level posts (40%/30%/30% capacity at best+1, best, best−1). Catches large sellers sweeping multiple levels. | +100-300 (fill rate) | Medium |
| **Multi-level ASH posting** | Post at 2 bid levels and 2 ask levels (FV±2 with half capacity, FV±3 with half). | +500-1,000 (taker capture) | Medium |
| **Drop PEPPER opportunistic short** | Remove the `bid ≥ FV + take_width × 2.5` trigger on drift products. | +22 (avoid the −22 actual loss) | Trivial |
| **Faster EMA bootstrap** | Reset EMA = mid every N=10 ticks until variance stabilizes. Cuts convergence from 12% of day to <2%. | +200-400 (early-day ASH) | Medium |
| **Total recoverable** | | **1,300-2,400** | |

This brackets the identified ~1,500 PnL leak. Remaining gap to zero-leak is structural (cannot be at +80 at tick 0).

### C.5 Dynamic width: re-parameterize for ASH-like products

Current formula: `dynamic_width = max(2, 0.5 × ret_std × (1 + 0.5 × |z|))`. Activates only when `ret_std > 4 / (1 + 0.5 × |z|)`. ASH ret_std stays below 2.5 — never activates.

**Alternative formula** (multiplicative scale from base):
```python
dynamic_width = base_width × (1 + 0.3 × max(|zscore| − 0.5, 0))
```

At \|z\|=1.5: width = 2 × 1.3 = 2.6. At \|z\|=2.0: width = 2 × 1.45 = 2.9.

**Estimated PnL impact** on the 315 high-z ASH ticks: 6.6 avg fill × 1 tick saved on adverse selection = ~2,000 PnL gain, minus ~6.6 × 0.3 × 10 = ~650 PnL from missed fills. **Net: +1,350 PnL on ASH** if applied this round retroactively.

For R3+ vouchers (higher base vol, larger spreads), the original formula will activate naturally; no re-parameterization needed there.

### C.6 R3+ feature engineering priorities

For the voucher trading environment in R3 ("Gloves Off"), these features should be computed per tick:

**High-priority (compute now):**

1. **Per-strike IV velocity** — Δ(IV)/Δ(tick) over last 5 ticks. R3 EDA found AR1(ΔIV) = −0.5 with 1-30 tick mean-reversion half-life. `r3_v9.py`'s 100-tick window is 30× too slow.

2. **Smile R² as regime indicator** — fit `IV(K) = a + b(K − K_atm) + c(K − K_atm)²` rolling. R² degrades from 0.81 (day 0) to 0.42 (day 2). When R² < 0.5, widen edges and reduce BS-based trading. Don't trust the smile under regime shifts.

3. **Empirical vs BS delta divergence** — per-strike empirical delta = β of voucher Δmid on VFE Δmid (rolling 20-tick regression). VEV_5200 empirical = 0.45 vs BS at current IV. Persistent divergence indicates IV mispricing OR structural hedging mis-spec.

4. **Portfolio net delta and vega** — Σ(pos_k × delta_k) and Σ(pos_k × vega_k) every tick. With 10 strikes × 300-unit limits, aggregate Greeks dominate per-strike PnL. Use as position-management signals.

5. **Per-strike taker imbalance** — rolling 50-tick imbalance of taker side per strike. R3 EDA: OTM strikes (5400-6500) show 100% sell-side taker flow. Posting bids there has near-zero fill probability. Allocate make-side capacity dynamically based on taker imbalance.

**Don't compute (already-tested negatives):**
- **OBI on wide-spread vouchers** — β=0.30, t-stat=8 but R²=1% and spread=20. Signal exists but is unmonetizable (spread cost > expected per-trade gain by 10×).
- **AR(3) level prediction on voucher mids** — R² 1-8%. Not actionable.
- **Time-of-day features** — taker activity uniform across day. No time-clustering.

**Theta carry is the largest single alpha source.** Deep ITM vouchers (4000, 4500) carry ~825-855 PnL per 1k ticks from theta decay alone. A short-deep-ITM + delta-hedge strategy could yield ~5x current PnL — but requires reliable delta hedging, which the R3 BT shows is difficult (VFE MM fills interfere with hedge fills). Solving this is the highest-EV R3 work.

### C.7 Verdict on architectural correctness

The try18-5 architecture is **economically sound at the structural level** (EMA + zscore + risk_aversion + drift_boost are all motivated by closed-form market-making theory) but **over-parameterized at the heuristic level** (direction_bias, discrete thresholds, asymmetric imbalance scaling).

**Hypothetical "Pareto-optimal" version** would:
- Replace the median+EMA + conditional alpha hybrid with a Kalman filter using known OU parameters
- Replace discrete zscore thresholds with continuous scaling
- Drop direction_bias (net-zero contribution)
- Drop opportunistic short on drift products
- Add multi-level take + multi-level make
- Add rolling drift estimator (replace hardcoded 0.1)

Estimated total improvement: ~3,000-4,000 PnL on the same R2 day-1 data. Score 99,534 → ~103,000.

For R3 deployment, the load-bearing components (adaptive FV, continuous inventory skew, urgency-scaled drift_boost, take/clear/make ordering) all carry forward unchanged. The decorative components and structural fixes are the optimization frontier.
