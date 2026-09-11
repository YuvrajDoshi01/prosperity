# Memory Index

- [project_round1_v18.md](project_round1_v18.md) — **r1_v18 adaptive threshold** — fixes 4 root causes from 272466. Beats v17 on all 3 real days (+4,920 BT total) and wins 15-seed synthetic bench (2,864,300 vs v14's 2,856,864)
- [project_round1_final.md](project_round1_final.md) — Full R1 submission 272466 (r1_v17): 89,861.44. IPR 99.1% of buy-and-hold max. ACO bootstrap anchor cost ~1,743 PnL via 512-tick crash_mode flicker
- [project_round1_results.md](project_round1_results.md) — R1 submission trajectory v1→v17, all lessons, synthetic-vs-real divergence
- [project_round1_calibration.md](project_round1_calibration.md) — R1 BT calibration (imc mode extra_rate=0.064), IPR ablation, ACO 60× BT overshoot
- [project_round1_prep.md](project_round1_prep.md) — Round 2+ reusable template library (7 archetypes) + deployment workflow
- [project_round1_probe.md](project_round1_probe.md) — R1 Lambda probe (210525): env, unpatched vulns, MACARONS conversion formula
- [project_manual_challenge_r1.md](project_manual_challenge_r1.md) — R1 manual: clearing auction solver, 87,995 XIRECs optimal
- [project_lu_framework.md](project_lu_framework.md) — LU 7 patterns, exact params, stable ✓ / drift ✗
- [project_nancy_guardrail.md](project_nancy_guardrail.md) — Nancy's rolling-slope regime detector → r1_v5
- [project_synthetic_testing.md](project_synthetic_testing.md) — round99/ regime generator + multi-seed comparator (NOTE: missing asymmetric-open regime — see project_round1_final.md)
- [project_tomatoes_eda.md](project_tomatoes_eda.md) — Round 0 cross-round insights (7 reusable lessons); details in CLAUDE.md
- [feedback_backtester.md](feedback_backtester.md) — Local BT ≠ website. Use for ranking only. Trust IPR gradient, not ACO (60× overshoot)
- [feedback_drawdown_misconception.md](feedback_drawdown_misconception.md) — Drift-product drawdowns are entry-cost, not a bug. Eliminating costs PnL
