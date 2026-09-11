# Round 1 Competitor References

Code shared by other players for comparison. Do NOT submit these — they're here purely for study.

| File | Source | Score | Notable |
|------|--------|------:|---------|
| r1_troll.py | TROLL (Discord) | ~10,600 | Time-linear drift (slope=0.001), EMA base, multi-level bids, ACO take-clear-make with glitch sniper |

## Comparison vs our r1_v4

| | r1_v4 (ours) | r1_troll |
|---|---|---|
| Score | **10,624.84** | ~10,600 |
| IPR FV | `mid + 5.0` (static drift) | `base_EMA + slope × timestamp` (time-linear) |
| IPR take | `fv + 2` | `fv + 8` |
| IPR sell | `fv + 3` | `fv + 7` |
| IPR posting | single bid best+1 | 4-level ladder fair-1..fair-4, qty 25 each |
| ACO | Linear Utility canonical (take-clear-make + skew) | Similar + glitch sniper for extreme bot errors |
| Params | 10 (LU-derived) | 14+ (backtest-tuned) |

Both converged to ~10,600 on website despite very different approaches. Useful validation that the tutorial has a practical ceiling ~10,625 — further improvements require different alpha, not refinements of the drift-capture framework.
