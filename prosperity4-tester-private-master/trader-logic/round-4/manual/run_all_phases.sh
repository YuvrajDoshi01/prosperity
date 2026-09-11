#!/bin/bash
# Master orchestrator — runs all 4 phases sequentially.
# Each phase reads the previous phase's output JSON from results/.

set -e
cd "$(dirname "$0")"
mkdir -p results logs

echo "==================================================================="
echo "RUN ALL PHASES — R4 Manual Challenge GPU Pipeline"
echo "==================================================================="

echo ""
echo "===== PHASE 1: HUGE GRID SWEEP ====="
python -u phase1_huge_grid.py \
    --paths 50000000 \
    --chunk 1000000 \
    --strat_batch 500 \
    --out results/phase1_results.json 2>&1 | tee logs/phase1_log.txt

echo ""
echo "===== PHASE 2: DEEP MULTI-SEED VERIFICATION (10K seeds) ====="
python -u phase2_deep_verify.py \
    --phase1_results results/phase1_results.json \
    --paths_per_seed 10000000 \
    --n_seeds 10000 \
    --top_n 100 \
    --chunk 1000000 \
    --strat_batch 100 \
    --out results/phase2_10kseeds_results.json 2>&1 | tee logs/phase2_10kseeds_log.txt

echo ""
echo "===== PHASE 3: SENSITIVITY ANALYSIS ====="
python -u phase3_sensitivity.py \
    --phase2_results results/phase2_10kseeds_results.json \
    --paths_per_test 50000000 \
    --top_n 20 \
    --out results/phase3_results.json 2>&1 | tee logs/phase3_log.txt

echo ""
echo "===== PHASE 4: ANTITHETIC TAIL ESTIMATION ====="
python -u phase4_antithetic.py \
    --phase2_results results/phase2_10kseeds_results.json \
    --pairs_per_strat 50000000 \
    --top_n 10 \
    --out results/phase4_results.json 2>&1 | tee logs/phase4_log.txt

echo ""
echo "===== IMC ACTUAL SCORING (1M-seed bootstrap) ====="
python -u imc_actual_scoring.py \
    --phase2_results results/phase2_10kseeds_results.json \
    --top_n 100 \
    --n_seeds 1000000 \
    --n_bootstrap 100000 \
    --out results/imc_actual_scoring_results.json 2>&1 | tee logs/imc_actual_scoring_log.txt

echo ""
echo "==================================================================="
echo "ALL PHASES COMPLETE"
echo "==================================================================="
echo "Outputs in results/:"
echo "  phase1_results.json              — huge grid (~233K candidates)"
echo "  phase2_10kseeds_results.json     — deep verify top 100 at 10K seeds"
echo "  phase3_results.json              — sensitivity for top 20"
echo "  phase4_results.json              — antithetic CVaR for top 10"
echo "  imc_actual_scoring_results.json  — empirical IMC score distribution"
echo ""
echo "See MANUAL_R4_FINAL.md for the recommendation."
