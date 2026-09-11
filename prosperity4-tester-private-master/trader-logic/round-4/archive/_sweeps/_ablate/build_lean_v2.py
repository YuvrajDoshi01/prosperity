"""Build r4_v9_lean.py — conservative variant: only remove pure NOISE.

Stacked-removal of the negative z-score MR layer caused $180k regression
despite single-layer ablation showing +$17k gain. Major interaction effect.

Conservative removal set (5 layers, 24% reduction, only confirmed no-ops):
  - hp_edge_beta_mm  (already 0/0/0)
  - vfe_mark55_follow (never fires)
  - v_intrinsic_arb  (never triggers)
  - v_callspread_arb (dead code per docstring)
  - yolo_regime_gate (never fires on R4 days)

These 5 are no-op in single-ablation AND in combination — pure removal.
"""
from pathlib import Path

REPO = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
SRC = REPO / "trader-logic" / "round-4" / "r4_final.py"
DST = REPO / "trader-logic" / "round-4" / "r4_v9_lean.py"

text = SRC.read_text(encoding="utf-8")

SUBS = [
    # 1. hp_edge_beta_mm: forced no-op
    ("    beta_eff = p.EDGE_BETA_SHRINK * beta",
     "    beta_eff = 0.0  # LEAN: edge-beta confirmed no-op (single-ablation 0/0/0)"),
    # 2. vfe_mark55_follow: threshold unreachable
    ("M55_THRESH = 30  # v7c confirmed",
     "M55_THRESH = 99999  # LEAN: M55 single-ablation 0/0/0"),
    # 3. v_intrinsic_arb: edge huge
    ("V_INTRINSIC_EDGE = 2",
     "V_INTRINSIC_EDGE = 99999  # LEAN: intrinsic arb single-ablation 0/0/0"),
    # 4. v_callspread_arb: condition impossible
    ("            if ask_lo - bid_hi < 0:",
     "            if False and ask_lo - bid_hi < 0:  # LEAN: dead code 0/0/0"),
    # 5. yolo_regime_gate: always false
    ("            yolo_regime = (drift <= YOLO_DRIFT_THRESHOLD)",
     "            yolo_regime = False  # LEAN: YOLO never triggers on R4 CSV"),
]

HEADER_OLD = '"""r4_v6_m49.py — v5 + Mark 49 VFE fade layer.'
HEADER_NEW = '''"""r4_v9_lean.py — conservative parsimony-audited variant of r4_final (v8 hybrid).

PARSIMONY AUDIT (intel/parsimony_audit.md, 21 layers ablated individually):

Removed 5 confirmed-NOISE layers (24% reduction):
  - hp_edge_beta_mm  (single-ablation 0/0/0)
  - vfe_mark55_follow (never fires; 0/0/0)
  - v_intrinsic_arb  (dead code; 0/0/0)
  - v_callspread_arb (dead code; 0/0/0)
  - yolo_regime_gate (never triggers on R4 days; 0/0/0)

WARNING: stacked removal of the apparent NEGATIVE z-score MR layer (+$17k
single-ablation) and 4 minor layers caused a $180k regression on 10k 3-day.
LAYER INTERACTIONS DOMINATE — additive ablation deltas DO NOT compose. Only
the 5 strict no-op layers can be safely stripped.

Expected lean BT (matches baseline within $200 since all removals are 0/0/0):
  1k d3 probe : ~$60,662
  10k 3-day def: ~$261,854
  10k 3-day imc: ~$248,023

Original v8 docstring preserved below.

= = =

r4_v6_m49.py — v5 + Mark 49 VFE fade layer.'''

text = text.replace(HEADER_OLD, HEADER_NEW, 1)

for old, new in SUBS:
    if old not in text:
        raise SystemExit(f"Substitution not found: {old[:80]!r}")
    text = text.replace(old, new, 1)

DST.write_text(text, encoding="utf-8")
print(f"Wrote {DST} ({len(text)} bytes)")
