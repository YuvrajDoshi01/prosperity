# Early Regime Detection — R4 Day 1/2/3

## Setup
First-N-tick feature scan on `prices_round_4_day_{1,2,3}.csv`. Day 3 = catastrophe label (S17 fired at ts=14200, VFE drops -$32 by ts=14200, HP didn't revert). Goal: detect by tick 50/100 to gate S17 entry.

Script: `intel/early_regime_detect.py`.

## Feature scan (cutoff=50, ts<5000)

| day | VFE_0 | HP_0 | VFE_rng | VFE_vol | HP_vol | vol_ratio | VFE_OBI |
|-----|-------|------|---------|---------|--------|-----------|---------|
| 1   | 5245.0 | 9958.0 | 9.5  | 2.69 | 2.40 | **1.12** | -0.004 |
| 2   | 5267.5 | 10011.0 | 13.5 | 4.27 | 6.10 | **0.70** | +0.047 |
| 3   | 5295.5 | 10008.0 | 7.5  | 1.87 | 5.00 | **0.37** | +0.038 |

## Discriminants that work by tick 50

1. **VFE_init level** — day 3 starts ~$28 above day 1, ~$28 above day 2. >5285 ⇒ catastrophe regime.
2. **vol_ratio = pstdev(VFE_mid) / pstdev(HP_mid)** — day 3 = 0.37, days 1-2 ∈ [0.70, 1.12]. Day 3 VFE is *abnormally still while HP is volatile* (suppressed VFE flow → no fundamental support for HP rally).

## Discriminants that DON'T work

- **Raw VFE_drift** at ts<5000/10000: day 3 drift is +0.5/+1.0 (looks fine). Crash hasn't started yet — only fires after tick 100. **Cannot use raw drift as early signal.**
- HP_micro_drift, HP_OBI, voucher activity, mark trade count — no day-3 separation by tick 50/100.

## Composite score (LOO-stable, both cutoffs)

```
score = (VFE_init - 5280)/15  +  (0.55 - vol_ratio)/0.30
```

| day | cutoff=50 | cutoff=100 |
|-----|-----------|-----------|
| 1 | -4.23 | -1.64 |
| 2 | -1.33 | -1.84 |
| **3** | **+1.62** | **+1.82** |

`score > 0` → DEFENSE flag. Margin >+2.95 between d3 and d2 at cutoff=50 (3-day LOO holds: each held-out day classifies correctly under threshold=0).

## Risk gate design

```python
# In Trader.run, after first 50 ticks (timestamp >= 5000):
if not self.regime_locked and timestamp >= 5000:
    vfe_init = self.first_vfe_mid           # captured at first tick
    vfe_mids_50 = self.vfe_buf[:50]
    hp_mids_50  = self.hp_buf[:50]
    vol_ratio = pstdev(vfe_mids_50) / max(pstdev(hp_mids_50), 1e-3)
    score = (vfe_init - 5280)/15 + (0.55 - vol_ratio)/0.30
    self.DEFENSE = (score > 0.0)
    self.regime_locked = True

# Effects when DEFENSE flag set:
#  1. Block S17 GIGA SHORT (already done via VFE-drift gate; this tightens it earlier).
#  2. Reduce HP Z_MAX_POS 120 → 60 (less inventory in unstable HP).
#  3. Tighten voucher BS_EDGE 10 → 14 (wider quotes when VFE flow is suppressed).
#  4. Skip aggressive momentum / FLIP target reduction 200 → 100.
```

## BT validation of current r4_final_v2 (already has VFE-drift gate)

- 1k 3-day total: **$19,662** (d1=3,177 / d2=15,469 / **d3=1,016 — positive after gate**)
- 10k 3-day total: **$111,422** (d1=10,438 / d2=55,591 / d3=45,394)

The current VFE-drift gate (d3 catastrophe @ ts=14200 averted) already works. The proposed early-regime gate fires *before* ts=5000, allowing pre-emptive position-size reduction.

## ONE concrete recommendation for r4_final_v2

Add a `DEFENSE` flag computed once at `timestamp == 5000` from `(VFE_init, vol_ratio)` composite score with threshold 0. When DEFENSE is on:
- Already gated: S17 entry (existing VFE-drift gate is reactive; this is preemptive backup).
- New: cap HP `Z_MAX_POS` at 60 (was 120) and reduce `FLIP_TARGET` to 100 (was 200).
- New: voucher `BS_EDGE` += 4.

Risk: 3 days = 3 samples — score threshold is fitted on n=3 with margin 2.95. Robust to ±50% feature noise but fragile if day-4 starts at VFE in [5275, 5295] with vol_ratio in [0.5, 0.7]. The composite score captures *initial regime calmness in VFE*; if R4 day-4 has a different microstructure, the rule may misfire. Recommend logging `score` to `traderData` for post-hoc validation regardless of gate action.
