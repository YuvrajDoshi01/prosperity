# Day-4 Prediction & Tail-Risk Analysis for r4_final_v2

## 1. Per-day feature distribution (extracted from R4 CSVs)

| Day | Product | range | drift | tick_vol | mean_spr | %s17 | %s7 |
|-----|---------|------:|------:|---------:|---------:|-----:|----:|
| 1 | HP  | 170 | +57 | 2.15 | 15.7 | 0.017 | 0.008 |
| 2 | HP  | 160 |  -1 | 2.17 | 15.7 | 0.013 | 0.008 |
| 3 | HP  | 158 |  -7 | 2.19 | 15.7 | 0.020 | 0.009 |
| 1 | VFE |  85 | +20 | 1.13 |  5.0 | 0.000 | 0.000 |
| 2 | VFE |  93 | +28 | 1.14 |  5.0 | 0.000 | 0.000 |
| 3 | VFE | 108 | -64 | 1.14 |  5.0 | 0.000 | 0.000 |

**HP is structurally identical across days** (range, vol, spread distribution, S17 frequency all within ±3%). **VFE drift is the only meaningful day-axis** (+20, +28, −64).

**S17 timing varies wildly**: day 1 zero S17 in first 1k; day 2 first at ts=4700 (recovers in 100 ticks); day 3 first at ts=14200 (does **not** recover — 7,300-tick hold). Full-day S17 counts: 152 / 118 / 193.

## 2. Day-4 mixture prior

3 i.i.d. samples → no power to forecast 4th draw. Empirical prior:
- 33% day-1-style (HP cycle, S17 sparse, VFE +)
- 33% day-2-style (HP cycle, S17 mid-day, VFE +)
- 25% day-3-style (HP cycle, S17 + slow recovery, VFE crash)
- 9% out-of-sample tail (heavier extreme, e.g. flat HP or extreme VFE crash)

Day-of-week / sigma-persistence: no signal. R3 also had 3-day data with one outlier (day 0). **Treat day 4 as one fresh draw from this 4-component mixture.**

## 3. r4_final_v2 BT 10k results (ground truth)

| Day | HP | VFE | Vouchers | Total |
|-----|---:|----:|---------:|------:|
| 1 | 6,718 | 3,040 | 679 | **10,438** |
| 2 | 41,699 | 11,914 | 1,978 | **55,591** |
| 3 | 43,191 | -3,709 | 5,912 | **45,394** |
| Mean | 30,536 | 3,748 | 2,856 | **37,141** |

Live ≈ BT × 1.014, so expected day-4 PnL ≈ **$37,650** (mean) with substantial spread. Median ≈ $45,000.

## 4. Tail risk identification — what loses >$20k

### TR-1: VFE drift in [-5, -7] gate-borderline regime
Day 2 first-1k rolling-50 drift hits **−11.1 at i=100**, then rebounds. If day 4 has a day-2-like dip that lingers below −5 longer, S17 entries get blocked at exactly the moments they would have been profitable. **Loss vector: opportunity cost ~$10–20k of HP PnL.**

### TR-2: HP S17 fires AND fails to recover (day-3-style without VFE-crash co-signal)
The crash gate uses VFE as a proxy for HP-flat. If HP is flat-with-S17-spikes but VFE happens to be stable (uncorrelated regime never seen in 3 days), v2 enters S17 short, gets stuck in FLIP_HOLD, exits at TIMEOUT after 1500 ticks. **Loss per S17 stuck event: −$11k** (sub 494304 reproduction). With 5+ such events possible in 10k, **worst-case −$55k**.

### TR-3: VFE momentum-short SL trigger
One-shot per day, max loss bounded at **−$3,000** (SL = +$15 × 200 share). Already realized on day-3 BT (−$3,709 VFE includes this). Bounded; not a tail concern.

### TR-4: Voucher BS edge regime shift
If TTE/sigma drift moves spot far above/below all strikes, deep-ITM 4000/4500 MM gets one-sided fills. Day-3 already shows this risk lives but is small (deep-ITM PnL = $2,585). Bounded.

**Aggregate tail (TR-1 + TR-2 simultaneous): −$30k to −$60k.** That's the worst plausible day-4 outcome.

## 5. Recommendation: ONE upgrade — replace VFE-drift gate with HP-self-validating gate

The current gate uses VFE drift as a **proxy** for "is HP in mean-reverting regime today?" That proxy fails when HP and VFE decorrelate. Direct fix:

**Add HP-S17-recovery counter as a self-validating circuit-breaker.**

```python
# After 2 S17 entries that didn't recover within FLIP_TIMEOUT, freeze S17 for the rest of day.
if hstate.s17_failed_count >= 2:
    s17_blocked = True   # only Z-score MR + passive MM run
```

Mechanics:
- Increment `s17_failed_count` whenever FLIP_HOLD exits via timeout (mid never recovered).
- After 2 failures, disable S17 entries for the remainder of the day. Z-score mean-reversion (Z_ENTRY=2.25, capped at Z_MAX_POS=120) stays active and provides ~60% of the alpha without S17 risk.
- Keep current VFE-drift gate as **primary** filter (catches day-3-style at start); HP-self-gate is the **fallback** for unseen decorrelation regimes.

**Why this dominates:** does not sacrifice average alpha (days 1-2 never trigger the failure counter — S17 always recovered fast), bounds worst case to **2 × −$11k = −$22k** instead of unbounded, and is observable purely from own state (no exotic signals). Single-line change to `HydrogelState`, single condition in `run_hydrogel`. Verifiable in BT: should be byte-identical on days 1-2-3, only diverges on synthetic stress.

**Implementation: ~10 lines, zero new params, fully back-compatible.**

Files: `C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/intel/day4_prediction.md`, `C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/intel/day4_prediction.py`.
