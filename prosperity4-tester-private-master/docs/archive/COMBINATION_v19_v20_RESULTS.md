# r3_v21 — v19 × v20 combination attempt (REJECTED)

## Result: net regression vs v19 baseline

| Window | v17 | v19 | v20 | v21 (v19+v20) | v21 vs v19 |
|---|---:|---:|---:|---:|---:|
| 1k day 2 | $12,340 | $15,760 | $12,367 | $15,717 | **−$43** |
| 10k 3-day | $56,328 | $86,194 | $56,656 | $86,162 | **−$32** |

## Per-day 10k decomposition

| Day | v19 | v21 | Δ | Source |
|---|---:|---:|---:|---|
| Day 0 | 31,964 | 31,392 | **−$572** | v20 BS-ATM hurts |
| Day 1 | 17,952 | 18,054 | +$102 | small noise |
| Day 2 | 36,278 | 36,715 | **+$437** | v20 BS-ATM helps |

Day 2 ATM MM wins, day 0 ATM MM loses, net negative.

## Why no additive gain

1. **v19 already includes v17 Phase 4.1 deep-ITM theta carry** (per memory `project_round3_alpha_hunt_2026-04-25.md` — "VFE/voucher stack incl. v17 Phase 4.1 ... preserved untouched").
2. **The only new thing v20 adds is BS-anchored ATM MM** (replacing v17/v19's spread-anchored MM at vbb+1/vba-1 with `bid = round(BS_fair − 1.5), ask = round(BS_fair + 1.5)`).
3. **v20's BS-anchored MM is regime-dependent**: helps on day 2 (rising VFE, persistent ATM drift), hurts on day 0 (different IV regime). On v17 base it was net +$328 (10k 3-day) because day 2's gain dominated. On v19 base, day 0's loss is bigger (−$572) and the day 2 gain isn't proportionally larger (+$437).

## Diagnosis

The BS-anchored MM uses a fixed sigma per tick (adaptive median across strikes). On day 0, the regime is different enough that the BS-fair-value diverges from market mid in a way that the spread-anchored MM (vbb+1/vba-1) handles more robustly — spread-anchored is regime-agnostic, BS-anchored requires correctly-calibrated sigma.

Delta hedge (v20's portfolio Greeks block) was already dormant on R3 historical (verified) — not the source of regression.

## What would work

To make v21 net-positive, would need:
1. **Day-type-conditional voucher MM**: use BS on trending days, spread on flat days. Requires a regime detector that fires on day 2 but not day 0 (not yet built).
2. **Better sigma calibration**: per-strike rolling IV instead of cross-strike median. v17 already has IV history per strike; could use that directly instead of `v_get_adaptive_sigma`.
3. **Wider edge on day 0**: dynamic edge based on observed dev_std. v20 hardcodes ATM_BS_EDGE=1.5; could be dynamic.

None of these are quick fixes. **Recommend shipping v19, not v21.**

## Files

- Combination strategy: `trader-logic/round-3/archive/r4_prep_iterations/r3_v21_v19xv20_REJECTED.py`
- v19 (production candidate): `trader-logic/round-3/r3_v19.py`
- v20 (R4-prep follow-up alone): `trader-logic/round-3/r3_v20_delta_hedge.py`

## Net assessment of "combine them"

Cleanly tested: yes. Cleanly composed: no. v19 captures the structural HP alpha; v20's voucher additions were tuned against v17's HP behavior and don't generalize to v19's S7+FLIP regime.

This is a useful finding — saves us from blindly stacking PRs that look additive but aren't. The ~$30k 10k 3-day gain from v19 alone vs v17 dwarfs anything v20 was going to add.

For R4 prep: keep v20's deep-ITM theta carry (already in v19 via v17), drop the BS-ATM MM, focus optimization budget elsewhere.
