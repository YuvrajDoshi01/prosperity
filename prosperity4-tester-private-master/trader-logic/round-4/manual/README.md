# R4 Manual Challenge — Codebase Index

## TL;DR

**Recommendation**: see [`MANUAL_R4_FINAL.md`](MANUAL_R4_FINAL.md) — DOM_NICE_v3 (DROP_60C + 15 AC_50_C), strict Pareto improvement over DOM_NICE_v2 verified at 10K-seed precision (z=23σ on mean, z=458σ on CVaR-5%).

To re-run everything: `./run_all_phases.sh` (~12 min on RTX 4070 Ti).

## Documentation

| File | Purpose |
|---|---|
| [`MANUAL_R4_FINAL.md`](MANUAL_R4_FINAL.md) | **Final orders to submit** + decision matrix + risk model |
| [`PHASES_1234_SYNTHESIS.md`](PHASES_1234_SYNTHESIS.md) | 4-phase MC verification synthesis (compute summary, Pareto frontier, mechanism) |
| [`IMC_SCORING_SIMULATION.md`](IMC_SCORING_SIMULATION.md) | Empirical IMC score distribution (1M-seed universe, 100K bootstrap) |
| [`intel_recon.md`](intel_recon.md) | Multiplier verification + Discord/team-chat intel |

## Pipeline (4 phases + IMC-style scoring)

| Script | Compute | Output | What it does |
|---|---|---|---|
| `phase1_huge_grid.py` | 233K candidates × 50M paths | `results/phase1_results.json` | GPU sweep over full strategy grid → top 400 finalists + 48 Pareto-optimal |
| `phase2_deep_verify.py` | 100 strats × 10B paths × 10K seeds | `results/phase2_10kseeds_results.json` | Deep verification (SE on mean ~$31) |
| `phase3_sensitivity.py` | Top 20 × 12 σ × 5 KO × 5 jump | `results/phase3_results.json` | σ/KO/jump robustness |
| `phase4_antithetic.py` | Top 10 × 100M antithetic | `results/phase4_results.json` | Tight CVaR-5% bootstrap |
| `imc_actual_scoring.py` | 100 strats × 1M paths × 100K bootstrap | `results/imc_actual_scoring_results.json` | Literal IMC scoring distribution |

## Reference + analysis utilities

| File | Purpose |
|---|---|
| `r4_simulation_FINAL.py` | Canonical numpy reference simulator (CPU, single-threaded) |
| `test_r4_simulation.py` | 12-test correctness suite (position limits, divisibility, payoffs) |
| `analyze_500seeds.py` | Compares 5-seed vs 500-seed Phase 2 results |
| `analyze_10kseeds.py` | Compares 5-seed → 500-seed → 10K-seed progression |
| `imc_one_realization.py` | Walk through ONE literal IMC scoring step-by-step |
| `imc_user_safe.py` | IMC scoring distribution including USER_SAFE strategy |
| `imc_seed_invariance.py` | Demonstrates master-seed choice is irrelevant |

## Directory layout

```
manual/
├── README.md                      ★ this file
├── MANUAL_R4_FINAL.md             ★ recommendation
├── PHASES_1234_SYNTHESIS.md       ★ synthesis
├── IMC_SCORING_SIMULATION.md      ★ IMC report
├── intel_recon.md
│
├── phase{1,2,3,4}_*.py            # pipeline
├── imc_*.py                       # IMC scoring scripts
├── analyze_*seeds.py              # progression analysis
├── r4_simulation_FINAL.py         # canonical reference
├── test_r4_simulation.py          # correctness tests
├── run_all_phases.sh              # orchestrator
│
├── results/                       # all .json outputs
├── logs/                          # all stdout logs
└── archive/                       # superseded experiments (~50 files)
    ├── early_per_agent/           # cp_optimal, ml_research, quant_audit, global_search_v2
    ├── early_verification/        # verify_*, final_verification, corrected_metrics
    ├── early_optimization/        # constrained_opt, pareto_*, global_max
    ├── early_robustness/          # multiseed_v2, sigma_sensitivity_v2, ko_*, alt_models_v2, billion_path, cdf_100m, hedge_overlay
    ├── early_gpu/                 # gpu_sweep, hidden_alpha_v2
    └── early_misc/                # dominator_*, MANUAL_R4_WRITEUP.md, manual_r4_solver.py
```

## Verification chain

1. **Phase 1** → 233K-candidate sweep finds 48 Pareto-optimal configurations and top 400 by mean/Sharpe
2. **Phase 2** → top 100 verified at 10K seeds × 10M paths each (SE on mean ~$31, paired test z=23σ)
3. **Phase 3** → top 20 stress-tested across 12 σ values, 5 KO frequencies, 5 jump regimes
4. **Phase 4** → top 10 get tight CVaR-5% via 100M antithetic-paired paths (SE ~$700)
5. **IMC scoring** → 1M-seed universe + 100K bootstrap empirical IMC score distribution

All five layers agree: **DOM_NICE_v3 is Pareto-optimal at the recommended risk/return knee.**

## Reproducibility

GBM seed: configurable via `--seed` (default 42 for IMC scoring, 20260428 for phases)
- Master seed choice is statistically irrelevant — see `imc_seed_invariance.py` for empirical demonstration.

GPU: requires CUDA (RTX 4070 Ti 12GB tested). For CPU fallback, use `r4_simulation_FINAL.py` (slower, single-threaded).
