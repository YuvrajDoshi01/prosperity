# R4-prep follow-up: 3-task experiment results

Three follow-up experiments after the P3 2025 EDA, in response to the question
"so did the EDA help?".

## Task (1) — 3-day autocorr stability ✅ confirmed

`scripts/autocorr_stability.py` extends the day-2 EDA across days 0-2.

**Verdict: bimodal autocorr is stable across all 3 days.**

| Strike region | Day 0 ac(1) | Day 1 ac(1) | Day 2 ac(1) | Verdict |
|---|---:|---:|---:|---|
| K=4000 | -0.003 | +0.020 | +0.003 | Scalpable every day |
| K=4500 | +0.009 | +0.019 | +0.017 | Scalpable every day |
| K=5100-5500 | 0.71-0.99 | 0.89-0.98 | 0.81-0.98 | Drift every day |
| K=6000-6500 | 0.997 | 0.997 | 0.997 | Frozen every day |

ATM IV drifts upward across days (24% → 25% → 27%) — gamma/theta effects
intensify as expiry approaches. Pattern stable; v17 Phase 4.1 architecture
holds across all 3 days.

## Task (2) — Squid Ink OU lean on HP ❌ rejected

`r3_v19_squid_ou.py` (renamed; team has separate v19) tested adding continuous
OU positioning lean to HP between v17's discrete spread=17 / MR LONG triggers.

| Config | 1k day 2 | 10k 3-day | Δ vs v17 |
|---|---:|---:|---:|
| v17 baseline | $12,340 | $56,328 | (baseline) |
| v19_squid SCALE=50 | $12,340 | $56,032 | **−$296** |
| v19_squid SCALE=25 | $12,340 | $56,264 | **−$64** |

**Verdict: rejected.** HP's discrete-trigger architecture (spread=17 GIGA SHORT)
is more efficient than continuous OU lean. The OU lean partially deploys
position before the trigger fires, reducing GIGA SHORT effectiveness.

**Lesson:** P3 Squid Ink strategy doesn't transfer to HP — HP has additional
exploitable structure (spread-state stress signal) beyond pure OU. File moved
to `archive/r4_prep_iterations/r3_squid_ou_REJECTED.py`.

## Task (3) — BS-anchored ATM voucher MM with delta hedge ✅ marginal positive

`r3_v20_delta_hedge.py` replaces v17's spread-anchored voucher MM (post at
vbb+1/vba-1) with BS-anchored MM for ATM strikes (5100-5400). Adds delta
hedge in VFE for safety.

| Config | 1k day 2 | 10k 3-day | Δ vs v17 |
|---|---:|---:|---:|
| v17 baseline | $12,340 | $56,328 | (baseline) |
| v20 (hedge enabled) | $12,367 | $56,656 | **+$27 / +$328** |

**Per-product day 2 (10k) gains:**
- VEV_5400: $433 → $729 (+$296)
- VEV_5300: $762 → $1,189 (+$427)
- VEV_5200: $709 → $804 (+$95)

**Verdict: net +$328 on 10k 3-day** from BS-anchored ATM MM. Delta hedge
fires near-zero times in BT (net δ stays below 30 because symmetric MM
keeps position near-zero) — kept enabled for R4 safety on potentially
asymmetric flow.

The +$27 1k-day-2 gain is small. ATM voucher fills accumulate over many
ticks (similar to Phase 4.1 theta carry). Multi-day rounds will scale this.

## Cumulative comparison (R4-prep stack)

| Strategy | 1k day 2 | 10k 3-day | Δ vs r3_v11 baseline |
|---|---:|---:|---:|
| r3_v11 (shipped) | $12,262 | $46,976 | — |
| r3_v17 (R4-prep stack) | $12,340 | $56,328 | +$78 / +$9,352 |
| **r3_v20 (BS ATM MM + Phase 4.1)** | **$12,367** | **$56,656** | **+$105 / +$9,680** |

v20 is +$27 over v17 on the website-parity 1k window — small but positive.

## Files added/modified

- `scripts/autocorr_stability.py` — 3-day stability EDA
- `previous-prosperity/p3_r3/EDA_FINDINGS.md` — already existed; results integrated
- `trader-logic/round-3/r3_v20_delta_hedge.py` — BS-anchored ATM MM + portfolio delta hedge
- `trader-logic/round-3/archive/r4_prep_iterations/r3_squid_ou_REJECTED.py` — negative result, archived

## Honest summary

- Task (1) was a quick stability check — confirmed bimodal autocorr is real (not a day-2 artifact)
- Task (2) was a negative result — Squid Ink → HP transfer doesn't work
- Task (3) was a marginal positive — +$27 on 1k window; +$328 on 10k 3-day

The EDA's most actionable insight remains: **deep ITM scalpability** (already
captured by Phase 4.1 in v17). The ATM BS-MM addition (v20) is a smaller
incremental win. Expected website score for v20: ~$12,243 (BT × 0.99) — likely
within noise of v17's $12,432 actual.

**For the team's v19 ($15,760 BT):** the BS-anchored ATM MM in v20 is
independent of the team's HP improvements (S7+FLIP). Both can be combined
into a v21 if desired, with expected BT around $86,194 + $328 = $86,522 on
10k 3-day if effects are additive.
