# Best Non-Overfit Strategies

Ranked by overfitting risk (lowest first), with website scores.

| File | Overfit Risk | Website | Fitted Parameters |
|------|-------------|---------|-------------------|
| s1_wallmid.py | **ZERO** | 2,614 | None — pure Wall Mid |
| s15_adaptive_reg.py | **ZERO** | 2,495 | None — learns from today's data only |
| s2_tradeflow.py | LOW | 2,851 | 4-lag regression (cross-validated both ways) + trade flow |
| s2_speed_flat.py | LOW | 2,851 | Same as above, 26% smaller file |
| s1_resting_optimized.py | LOW | 2,857 | Same + structural EMERALDS tweak |
| s3_carry.py | LOW | 2,857 | Same + structural mean-reversion carry |

## For Round 1
- s1_wallmid: deploy immediately for any product, zero risk
- s15_adaptive_reg: deploy for final scoring (10k ticks), needs warmup
- s2_tradeflow: refit regression coefficients on new sample data
- s3_carry: strongest on tutorial, carry logic is structural
