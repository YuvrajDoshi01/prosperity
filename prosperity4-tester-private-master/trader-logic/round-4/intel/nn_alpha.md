# NN Forward-Return Forecaster — Negative Result

## Task
Train tiny linear / MLP forecaster for HP and VFE 10-tick forward mid return.
Deploy as numpy-only inference inside `r4_v5_nn.py`. Acceptance: 10k 3-day BT
sum (default + imc) > $318,815 (v5 baseline).

## Data & features
R4 days 1-3, per-product per-tick. 10 features: `obi1, micro_dev (WAP_L3-mid),
ret_5/20/100, vol50, spread, spread17 (HP only), vfe_drift_50, flow100`
(rolling Mark 22/49/55/67 net imbalance).

## Models
- **Ridge linear** (lambda=1) — 11 weights/product (incl bias)
- **MLP 1-hidden 8 neurons, tanh** — pure-numpy backprop, 200-400 epochs

## Out-of-sample (leave-one-day-out)

### HYDROGEL_PACK
| Hold | lin R^2 | lin sgn | mlp R^2 | mlp sgn |
|------|---------|---------|---------|---------|
| d1   |  0.0145 | 0.491   | -0.0063 | 0.481   |
| d2   |  0.0089 | 0.486   | -0.0186 | 0.472   |
| d3   |  0.0141 | 0.496   | -0.0013 | 0.492   |

### VELVETFRUIT_EXTRACT
| Hold | lin R^2 | lin sgn | mlp R^2 | mlp sgn |
|------|---------|---------|---------|---------|
| d1   |  0.0217 | 0.488   | 0.0046  | 0.493   |
| d2   |  0.0189 | 0.492   | 0.0059  | 0.495   |
| d3   |  0.0210 | 0.494   | 0.0023  | 0.490   |

MLP overfits (negative OOS R^2). Linear wins. Deployed linear weights only.

## Feature importance (full-fit linear)
HP: `micro_dev` +0.99, `obi1` +0.80, **`spread17` -0.72** (confirms S17 short alpha
mechanically), `vol50` -0.04. Other features <|0.01|.

VFE: `micro_dev` +1.34 (dominant), `obi1` -0.38 (contrarian to HP), `ret_20`
+0.03, `vfe_drift_50` -0.012 (mean-reversion). All others ~0.

## Deployment hooks tried
1. **HP S17 gate** (`nn_pred_hp <= 0`): all S17-eligible ticks already satisfy this
   (spread17 coef -0.72 forces pred negative). Gate never bites → byte-identical
   to v5 ($162,930 / $155,885).
2. **HP S17 gate stricter** (`<= -1.2`): prunes 65-85% of S17 entries → catastrophic
   ($87,406 default, -$75,524 vs v5). NN cannot rank winners vs losers within
   spread=17 universe (R^2 too small).
3. **VFE momo confirmation** (require `nn_pred_vfe <= 0` in addition to velocity
   <=-3): blocks one productive day-1 momo entry, -$188 default / -$38 imc.
4. **VFE momo weak veto** (require `nn_pred_vfe < +1.0`): NN never strongly
   disagrees with momo trigger; byte-identical to v5.

## Final BT (best NN config: weak veto)
| Mode    | v5 baseline | v5_nn   | delta |
|---------|------------:|--------:|------:|
| 10k def | 162,930     | 162,930 | 0     |
| 10k imc | 155,885     | 155,885 | 0     |
| **Sum** | **318,815** | **318,815** | **0** |

## Conclusion: REJECT
- OOS R^2 = 0.009-0.022 is below the threshold needed to override v5's
  structural signals (S17 trigger, z-score gate, OBI multi-strike confirm).
- Sign accuracy ~49-50% = coin-flip in event-aligned subsets.
- The NN's `spread17` coef merely re-encodes the S17 rule already hard-coded.
- v5 is alpha-saturated for the linear-feature universe. To beat v5 requires
  either (a) much richer features (level-2/3 imbalance dynamics, cross-voucher
  IV slope, regime classification) or (b) state-dependent policies (RL),
  neither feasible in IMC's 1s/50KB sandbox without weeks of engineering.

## Files
- `intel/nn_alpha.py` — training script (numpy + pandas + sklearn-free)
- `intel/nn_alpha_weights.json` — fitted weights (linear + MLP)
- `intel/nn_alpha_diag.py` — eligibility-aware NN diagnostic
- `r4_v5_nn.py` — v5 + NN hooks (deployable but byte-identical to v5)

Recommend: **continue submitting v5**; do not ship v5_nn. Time better spent on
non-NN ideas (cross-voucher IV slope arb, manual challenge, R5 prep).
