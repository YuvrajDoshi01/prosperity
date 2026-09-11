# R4-Prep Strategy Iterations (archived)

These are the intermediate strategies produced during the R4-readiness roadmap
(`.worktrees/r4-prep` branch `r4-prep-roadmap`). The consolidated final is
`trader-logic/round-3/r3_v17.py`. Each iteration here represents one Phase
of the roadmap and is preserved for audit / regression isolation.

## Iteration table (vs r3_v11 baseline 1k=$12,262 / 10k=$46,976)

| File | Phase | Change | 1k day 2 | 10k 3-day | Δ vs v11 (10k) |
|---|---|---|---:|---:|---:|
| `r3_v12_multilevel.py` | 1.1 | 3-layer passive posting on VFE + vouchers | 12,262 | 47,036 | +60 |
| `r3_v13_daytype.py` | 2.1-2.4 | VFE day-type detector + invalidation | 12,262 | 47,036 | +0 (didn't fire) |
| `r3_v14_theta_carry.py` | 4.1 | Active MM on VEV_4000/4500 (theta harvest) | 12,396 | 55,880 | **+8,904** ★ |
| `r3_v15_smile_r2.py` | 4.2 | Smile R² defensive widening on R²<0.5 | 12,340 | 56,328 | +9,352 |
| `r3_v16_empirical_delta.py` | 4.3 | Empirical δ vs BS δ divergence gate | 12,340 | 56,328 | +9,352 (no fire) |

Final consolidated → `trader-logic/round-3/r3_v17.py`

## Why archived rather than deleted

Each iteration tested a specific hypothesis. The deltas above are computable
only with these intermediate files; merging directly to v17 from v11 loses
the per-Phase attribution. If a future Phase regresses, isolating to a
single intermediate gives the cleanest debug surface.

## Lessons learned (per file)

- **v12 (multi-level)** — alpha_hunt Q2 projection ($11k 3-day) didn't
  materialise in v11's already-saturated MM architecture. Multi-level adds
  marginal value when the underlying flow is sweeping multiple levels (rare).
- **v13 (day-type)** — VFE drift is too gentle (~0.5 ticks at row 20) for
  detection. Memory entry confirms first-1k VFE drift = -3.5, not +28.
  Detector kept as no-op infrastructure for R4 HP-style products.
- **v14 (theta carry)** — biggest win. v11 only had intrinsic arb on
  VEV_4000/4500 (rare fires). Active MM around intrinsic captures spread +
  theta decay continuously. Day 2 alone: VEV_4000 went $0 → $2,437.
- **v15 (smile R²)** — first attempt with both tightening AND widening
  regressed -$1.7k 10k 3-day. Tightening invites adverse selection on healthy
  days. Defensive-only (widen on R²<0.5) added small +$448.
- **v16 (empirical delta gate)** — gate rarely fires because v11's BS taking
  is itself rare (edge=10 too wide). Infrastructure ready for R4 stress.

See `R4_PREP_RESULTS.md` (worktree root) for full results writeup.
