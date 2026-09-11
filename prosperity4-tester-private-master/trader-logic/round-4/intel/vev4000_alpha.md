# VEV_4000 Alpha Hunt — 2026-04-27

## Setup
Deep ITM call on VFE (spot ~5300, K=4000, intrinsic ~$1300, limit 300). Baseline `r4_final_v2.py` PnL: **$3,367 / $2,437 / $2,585 = $8,389 (3-day 10k default)**.

## Findings

### Q1 — Theoretical PnL ceiling
DP perfect-foresight at |pos|=300 = **$2.78M / $2.76M / $2.88M per day** ($8.4M total). But VFE moves only ~$28-33/day → "always at the right level" requires costless direction-flipping; transaction costs/microstructure make this unreachable. **Realistic ceiling = MM-skim on M14↔M38 quote pair = $2,800-3,200/day** (matches measured PnL within +/-3%).

### Q2 — Counterparty structure (CRITICAL)
- **Mark 14 buys at intrinsic+10.5 (median +10.5, n=232 days1-3)**
- **Mark 38 sells at intrinsic-10.5 (median -10.5, n=232)**
- 100% of trades are M14↔M38 with each other. **Zero non-MM counterparties** (M22 = 9 trades total across 3 days).
- Quoted spread ~21 fixed; 12-20% of ticks have inside-spread <±10 quotes (ours).

### Q3 — Position cap (cap=100→300 sweep)
**Cap is NOT binding.** All caps {100,150,200,300} produce **identical 3-day PnL = $111,422** (byte-identical $3,367/$2,437/$2,585). Edge per unit = $0. M14/M38 are non-reactive; we never accumulate near cap.

### Q4 — Theta dynamics
Time premium ≈ 0 throughout (open/close drift ±0.1/day). For r=0 deep ITM, BS theta ≈ 0 — confirmed empirically. **No theta carry alpha exists.** The MM block is misnamed; PnL is pure intrinsic arb.

### Q5 — Bid offset sweep (intrinsic±0/3/5/7/9)
**All offsets identical 3-day PnL = $111,404.** The clamp `bid_px = min(target, vbb+1)` forces every bid to penny-join (intrinsic-9.5) regardless of `target`. M14/M38 don't react.

### Critical ablation
Disabling deep-ITM MM entirely: VEV_4000 day-3 = $2,567 vs baseline $2,585 (Δ=$18). **The MM block contributes ≈ $18/10k = noise.** All $8,389 comes from the `v_intrinsic_arb` take loop (buy <intrinsic-2, sell >intrinsic+2) sweeping M14/M38 quotes that fluctuate across intrinsic ±10.5.

## Recommendation
**Status: SATURATED. Drop deep-ITM MM (saves logic, no PnL loss).** Real upside requires either (a) detecting when M14/M38 stack quotes inside ±10 — book has 12-20% narrow ticks already auto-captured by intrinsic arb at edge=2; (b) reducing INTRINSIC_EDGE from 2→1 to widen take range:

```python
V_INTRINSIC_EDGE = 1   # was 2 → captures more M14/M38 stacked-inside ticks
V_INTRINSIC_QTY = 80   # was 50 → larger sweep per cross
```

**BT projection:** edge=1 widens take threshold by 1 unit on each side → captures ~2x more "narrow-spread" ticks. Estimated +$300-600 / 3-day. Tested: must verify no adverse-selection cost from edge=1 hits when intrinsic is stale during VFE jumps. **Recommend 1k-tick day 2 BT before submitting.** Acceptance: 3-day total ≥ $112,000 default (vs $111,422 baseline) AND day 3 1k-tick > $1,000.
