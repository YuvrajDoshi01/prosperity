"""Sweep deeper to find exact break-points for OPTIMAL_7POS."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from alt_models_v2 import (
    STRATEGIES, gbm_chunk, run_spec, CONTRACT_MULTIPLIER
)
import numpy as np

print("Finding break-points where OPTIMAL_7POS goes <=0 EV")
print("=" * 80)

# Sigma sweep down
print("\nSigma sweep (low):")
for true_sigma in [2.00, 2.10, 2.15, 2.20, 2.25]:
    nm = f"sigma_{true_sigma}"
    s = run_spec(nm, 5_000_000, gbm_chunk, 500_000, seed=1000+int(true_sigma*100),
                 sigma=true_sigma, mu=0.0)

print("\nMicrostructure sweep (high):")
for eps in [0.30, 0.50, 0.75, 0.90]:
    nm = f"micro_{eps}"
    s = run_spec(nm, 5_000_000, gbm_chunk, 500_000, seed=2000+int(eps*100),
                 micro_eps=eps, sigma=2.51, mu=0.0)

print("\nLarge negative drift sweep:")
for mu in [-0.20, -0.50, -1.0]:
    nm = f"drift_{mu}"
    s = run_spec(nm, 5_000_000, gbm_chunk, 500_000, seed=3000+int(abs(mu)*100),
                 sigma=2.51, mu=mu)

print("\nLarge positive drift sweep:")
for mu in [+0.30, +0.50, +1.0]:
    nm = f"drift_+{mu}"
    s = run_spec(nm, 5_000_000, gbm_chunk, 500_000, seed=4000+int(mu*100),
                 sigma=2.51, mu=mu)
