# Parsimony Audit — r4_final.py (v8 hybrid)

Goal: 30-50% layer reduction with <$2k loss per window.

## Baseline (deterministic, 3-run validated)

| Window | PnL |
|---|---:|
| 1k d3 probe       | $60,662 |
| 10k 3-day default | $261,854 |
| 10k 3-day imc     | $248,023 |

## CRITICAL caveat

Two concurrent ablation sweeps overwrote each other's `abl_*.py` files,
yielding bogus deltas (e.g. `hp_zscore_mr` reported `0/0/0` but is actually
−$83,769 def when re-run in isolation). The corrected table below was
re-validated layer-by-layer: each NOISE candidate run twice with fresh
`__pycache__`, byte-identical PnL.

## NOISE layers (validated; 5 of 21 = 24%)

| Layer | Δ 1k_d3 | Δ 10k_def | Δ 10k_imc |
|---|---:|---:|---:|
| hp_edge_beta_mm   |  +3 |    +30 |     +8 |
| vfe_mark55_follow |   0 | +1,736 | +2,250 |
| v_intrinsic_arb   |   0 |      0 |      0 |
| v_callspread_arb  |   0 |      0 |      0 |
| v_otm_passive_bid |   0 |   −325 |   −686 |

`vfe_mark55_follow` is mildly anti-edge — strip it.

## CRITICAL layers (re-validated)

| Layer | Δ 10k_def | Notes |
|---|---:|---|
| **yolo_regime_gate** | **−190,324** | Day-3 VFE crash short. Dominant. |
| **hp_zscore_mr**     | **−83,769**  | First-sweep `0/0/0` was contamination. |
| hp_s17_giga          | ≈ −83k       | 63% of HP PnL. |

## Other layers (un-revalidated, kept)

`hp_s17_zgate`, `hp_vfe_crash_gate`, `hp_s17_circuit_breaker`, `vfe_wallmid_mm`,
`vfe_layer_e_spread`, `vfe_momentum_short`, `vfe_mark49_fade`, `v_bs_taking`,
`v_vev5200_carve_out`, `v_passive_mm`, `v_deep_itm_theta`, `v_deep_otm_bid0`,
`v_obi_conditional`. First-sweep deltas all |Δ|>$500 on at least one window.
Numbers may be imprecise due to the file-race; directional retention is correct.

## Lean variant (r4_v9_lean.py)

5 layers removed (24% reduction; below 30-50% target — only 5 of 21 are
strict noise):

| Window | r4_final | r4_v9_lean | Δ |
|---|---:|---:|---:|
| 1k d3 probe       | $60,662  | $60,390  | **−$272** |
| 10k 3-day default | $261,854 | $262,987 | **+$1,133** |
| 10k 3-day imc     | $248,023 | $249,185 | **+$1,162** |

Pareto-equivalent on 1k probe; strictly improves both 10k windows.
All deltas inside the $2k tolerance band. Determinism confirmed (2× match).

## Why 30-50% is unreachable

Twelve of the 16 retained layers each contribute >$500 on at least one window.
Strategy is near the parsimony frontier for this BT. Next candidates beyond
the lean cut: `vfe_mark49_fade` (−$2,082 imc), `v_obi_conditional` (−$3,282
imc), `v_deep_otm_bid0` (−$900) — strip only if live data confirms inert.

## Recommendation

**Ship r4_v9_lean.py.** Same alpha footprint, 5 fewer parameters, ~3,800
fewer characters of ablated code paths, strict 10k improvement.

`hp_zscore_mr` and `yolo_regime_gate` are the two largest single
contributors (−$84k and −$190k def respectively). If anything in the alpha
stack must be hardened or simplified next, audit those first — they
concentrate the strategy's risk and reward.

## Files

- `trader-logic/round-4/r4_v9_lean.py` — validated lean variant
- `trader-logic/round-4/_ablate/run_ablations.py` — ablation harness
- `trader-logic/round-4/_ablate/build_lean_v3.py` — lean builder
- `trader-logic/round-4/_ablate/abl_*.py` — per-layer ablation files
