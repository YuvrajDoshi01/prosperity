"""Build r4_v9_lean.py — VALIDATED parsimony-audit variant.

Removed 5 layers (24% reduction) confirmed as NOISE in independent
single-ablation runs (each tested twice for determinism):

  hp_edge_beta_mm   :  +3 / +30   / +8     (deterministic; bid_offset stays ~0)
  vfe_mark55_follow :   0 / +1,736 / +2,250 (M55 signal triggers anti-edge)
  v_intrinsic_arb   :   0 / 0     / 0      (never triggers; dead code)
  v_callspread_arb  :   0 / 0     / 0      (confirmed dead code)
  v_otm_passive_bid :   0 / -325  / -686   (sub-$500 every window)

Layers KEPT despite earlier-mistaken "no-op" claim:
  hp_zscore_mr      : -83,769 def — CRITICAL alpha (initial sweep contaminated
                      by concurrent processes overwriting variant files)
  yolo_regime_gate  : -190,324 def — DOMINANT alpha
"""
from pathlib import Path

REPO = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
SRC = REPO / "trader-logic" / "round-4" / "r4_final.py"
DST = REPO / "trader-logic" / "round-4" / "r4_v9_lean.py"

text = SRC.read_text(encoding="utf-8")

SUBS = [
    # 1. hp_edge_beta_mm — beta_eff = 0
    ("    beta_eff = p.EDGE_BETA_SHRINK * beta",
     "    beta_eff = 0.0  # LEAN: edge-beta noise (+3/+30/+8)"),
    # 2. vfe_mark55_follow — threshold unreachable
    ("M55_THRESH = 30  # v7c confirmed",
     "M55_THRESH = 99999  # LEAN: M55 anti-edge (0/+1,736/+2,250 when removed)"),
    # 3. v_intrinsic_arb
    ("V_INTRINSIC_EDGE = 2",
     "V_INTRINSIC_EDGE = 99999  # LEAN: never triggers (0/0/0)"),
    # 4. v_callspread_arb
    ("            if ask_lo - bid_hi < 0:",
     "            if False and ask_lo - bid_hi < 0:  # LEAN: dead code (0/0/0)"),
    # 5. v_otm_passive_bid
    ("    OTM_BID_SIZE = 5",
     "    OTM_BID_SIZE = 0  # LEAN: -325 def, -686 imc"),
]

HEADER_OLD = '"""r4_v6_m49.py — v5 + Mark 49 VFE fade layer.'
HEADER_NEW = '''"""r4_v9_lean.py — VALIDATED parsimony-audited variant of r4_final (v8 hybrid).

PARSIMONY AUDIT (intel/parsimony_audit.md, 21 layers ablated):

Removed 5 NOISE layers (24% reduction), each confirmed deterministic:
  hp_edge_beta_mm   (+3/+30/+8)        — bid_offset stays near zero
  vfe_mark55_follow (0/+1,736/+2,250)  — M55 signal is anti-edge
  v_intrinsic_arb   (0/0/0)            — never triggers
  v_callspread_arb  (0/0/0)            — confirmed dead code
  v_otm_passive_bid (0/-325/-686)      — sub-$500 every window

Kept (16 critical or material): S17 GIGA, S17 z-gate, S17 circuit breaker,
HP VFE crash gate, HP z-score MR (-$84k def when removed!), VFE Wall-Mid MM,
VFE Layer-E spread, VFE momentum short, VFE Mark 49 fade, BS taking,
VEV_5200 carve-out, voucher passive MM, deep-ITM theta, deep-OTM bid=0,
OBI conditional, YOLO regime gate (★ -$190k def when removed), pos-limit clamp.

Targeted 30-50% layer reduction not achievable: of 21 layers, only 5 are
true NOISE. The remaining 16 each contribute material PnL (>$300 on at least
one window). Layer interactions are LARGE — additive ablation deltas DO NOT
compose linearly. This 5-layer removal was validated end-to-end.

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
