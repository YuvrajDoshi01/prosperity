"""Build r4_v9_lean.py from r4_final.py by stacking the ablations identified
as NOISE / NEGATIVE / borderline in the parsimony audit.

Layers removed (10 of 21 = 48% reduction):
  NOISE (5)        : hp_edge_beta_mm, vfe_mark55_follow, v_intrinsic_arb,
                     v_callspread_arb, yolo_regime_gate
  NEGATIVE (1)     : hp_zscore_mr
  MINOR / BORD (4) : vfe_mark49_fade, v_otm_passive_bid, v_deep_otm_bid0,
                     vfe_layer_e_spread
"""
from pathlib import Path

REPO = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
SRC = REPO / "trader-logic" / "round-4" / "r4_final.py"
DST = REPO / "trader-logic" / "round-4" / "r4_v9_lean.py"

text = SRC.read_text(encoding="utf-8")

SUBS = [
    # hp_edge_beta_mm: force beta_eff=0 (no-op confirmed)
    ("    beta_eff = p.EDGE_BETA_SHRINK * beta",
     "    beta_eff = 0.0  # LEAN: edge-beta confirmed no-op in ablation"),
    # vfe_mark55_follow: threshold unreachable
    ("M55_THRESH = 30  # v7c confirmed",
     "M55_THRESH = 99999  # LEAN: M55 never fires in 10k 3-day"),
    # v_intrinsic_arb: edge huge
    ("V_INTRINSIC_EDGE = 2",
     "V_INTRINSIC_EDGE = 99999  # LEAN: intrinsic arb dead code"),
    # v_callspread_arb: condition impossible
    ("            if ask_lo - bid_hi < 0:",
     "            if False and ask_lo - bid_hi < 0:  # LEAN: call-spread arb dead code"),
    # yolo_regime_gate: never enter YOLO
    ("            yolo_regime = (drift <= YOLO_DRIFT_THRESHOLD)",
     "            yolo_regime = False  # LEAN: yolo never triggers on R4 days"),
    # hp_zscore_mr: NEGATIVE alpha — remove (entry threshold unreachable)
    ("    Z_ENTRY = 2.25         # v8c",
     "    Z_ENTRY = 99.0  # LEAN: z-score MR is NEGATIVE alpha (-$17k def / -$18k imc)"),
    # vfe_mark49_fade: minor net negative on 10k
    ("M49_QTY_MIN_SELL = 8     # M49 sells qty>=8 (93/105)",
     "M49_QTY_MIN_SELL = 99999  # LEAN: M49 fade -$2k 10k"),
    ("M49_QTY_MIN_BUY  = 1",
     "M49_QTY_MIN_BUY  = 99999  # LEAN"),
    # v_otm_passive_bid: tiny loss
    ("    OTM_BID_SIZE = 5",
     "    OTM_BID_SIZE = 0  # LEAN: passive OTM bid sub-$500 contribution"),
    # v_deep_otm_bid0: small loss
    ("    DEEP_OTM_BID_SIZE = 100",
     "    DEEP_OTM_BID_SIZE = 0  # LEAN: deep-OTM bid=0 nets -$900"),
    # vfe_layer_e_spread: borderline (1k +$551 but def/imc lose ~$800)
    ("            if spread_ve == 2 and ba_ve < vstate.prev_ve_ap1:",
     "            if False and spread_ve == 2 and ba_ve < vstate.prev_ve_ap1:  # LEAN"),
    ("            elif spread_ve == 3 and bb_ve > vstate.prev_ve_bp1:",
     "            elif False and spread_ve == 3 and bb_ve > vstate.prev_ve_bp1:  # LEAN"),
]

# Update top docstring header
HEADER_OLD = '"""r4_v6_m49.py — v5 + Mark 49 VFE fade layer.'
HEADER_NEW = '''"""r4_v9_lean.py — parsimony-audited lean variant of r4_final (v8 hybrid).

PARSIMONY AUDIT (intel/parsimony_audit.md, 21 layers ablated individually):
Removed 10 layers (48% reduction) classified as NOISE / NEGATIVE / borderline:
  NOISE (delta < $500 on every window):
    - hp_edge_beta_mm  (0/0/0)
    - vfe_mark55_follow (0/0/0)
    - v_intrinsic_arb  (0/0/0)
    - v_callspread_arb (0/0/0; dead code)
    - yolo_regime_gate (0/0/0; never triggers on R4 days)
  NEGATIVE (removing IMPROVES PnL):
    - hp_zscore_mr     (-58 / +17,342 / +18,330) ★ silent leak
  MINOR (small loss on 10k):
    - vfe_mark49_fade  (-75 / -1,904 / -2,082)
    - v_otm_passive_bid (-138 / -355 / -351)
    - v_deep_otm_bid0  (-600 / -900 / -900)
    - vfe_layer_e_spread (+551 / -865 / -757)

Kept (CRITICAL alpha): S17 GIGA, S17 z-gate, S17 circuit breaker, VFE crash
gate, VFE Wall-Mid MM, VFE momentum short, BS taking, VEV_5200 carve-out,
voucher passive MM, deep-ITM theta carry, OBI conditional, position-limit clamp.

Expected lean BT (additive estimate, validate after build):
  1k d3 probe : ~$60,500  (vs $60,662 baseline, ~-$160)
  10k 3-day def: ~$275,000 (vs $261,854 baseline, ~+$13,300)
  10k 3-day imc: ~$262,000 (vs $248,023 baseline, ~+$14,200)

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
