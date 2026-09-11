"""Ablation runner for r4_final.py parsimony audit.

For each layer, generate a modified strategy file that DISABLES that layer
(typically by setting a sentinel param to be unreachable), then run the 3 BT
windows: 1k d3 probe, 10k 3-day default, 10k 3-day imc.

Outputs CSV with delta vs baseline.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
SRC = REPO / "trader-logic" / "round-4" / "r4_final.py"
ABLATE_DIR = REPO / "trader-logic" / "round-4" / "_ablate"
ABLATE_DIR.mkdir(exist_ok=True)

BASE_TEXT = SRC.read_text(encoding="utf-8")

# Each ablation: (name, list_of_(old, new) substitutions to disable layer)
# Designed to be PRECISE — only kill that layer, leave everything else.
ABLATIONS = {
    # --- HP layer ablations ---
    "hp_s17_giga": [
        # Disable S17 entry by making spread requirement impossible.
        ("    REGIME2_SPREAD = 17", "    REGIME2_SPREAD = 99999  # ABL"),
    ],
    "hp_s17_zgate": [
        # Remove z-gate by setting threshold to -inf so always passes (i.e. layer becomes inert as filter)
        ("    S17_Z_MIN = 2.0  # NEW gate (intel/hp_alpha_v2.md)",
         "    S17_Z_MIN = -99.0  # ABL: gate disabled"),
    ],
    "hp_vfe_crash_gate": [
        # Disable VFE crash gate by always making vfe_crashing False
        ("        vfe_crashing = vfe_drift < -5.0",
         "        vfe_crashing = False  # ABL"),
    ],
    "hp_s17_circuit_breaker": [
        ("    S17_MAX_FAILS = 2  # v4: circuit breaker — freeze S17 after N FLIP_HOLD timeouts",
         "    S17_MAX_FAILS = 99999  # ABL: circuit breaker disabled"),
    ],
    "hp_zscore_mr": [
        # Set Z_ENTRY high so directional z-signal never fires
        ("    Z_ENTRY = 2.25         # v8c", "    Z_ENTRY = 99.0  # ABL"),
    ],
    "hp_edge_beta_mm": [
        # Force beta to 0 -> bid_offset = 0 (still posts but no skew)
        ("    beta_eff = p.EDGE_BETA_SHRINK * beta",
         "    beta_eff = 0.0  # ABL: edge-beta off"),
    ],
    # --- VFE layer ablations ---
    "vfe_wallmid_mm": [
        # Disable Wall-Mid MM — short-circuit the WM block
        ("        wm = v_wall_mid(od_ve)",
         "        wm = None  # ABL: WM MM off"),
    ],
    "vfe_layer_e_spread": [
        # Disable Layer-E by making both branches impossible
        ("            if spread_ve == 2 and ba_ve < vstate.prev_ve_ap1:",
         "            if False and spread_ve == 2 and ba_ve < vstate.prev_ve_ap1:  # ABL"),
        ("            elif spread_ve == 3 and bb_ve > vstate.prev_ve_bp1:",
         "            elif False and spread_ve == 3 and bb_ve > vstate.prev_ve_bp1:  # ABL"),
    ],
    "vfe_momentum_short": [
        # Disable VFE momo by setting threshold unreachable
        ("VFE_MOMO_THRESH = -3.0     # mid drop trigger",
         "VFE_MOMO_THRESH = -99999.0  # ABL"),
    ],
    "vfe_mark49_fade": [
        # Make M49 thresholds unreachable
        ("M49_QTY_MIN_SELL = 8     # M49 sells qty>=8 (93/105)",
         "M49_QTY_MIN_SELL = 99999  # ABL"),
        ("M49_QTY_MIN_BUY  = 1",
         "M49_QTY_MIN_BUY  = 99999  # ABL"),
    ],
    "vfe_mark55_follow": [
        # M55 threshold unreachable
        ("M55_THRESH = 30  # v7c confirmed",
         "M55_THRESH = 99999  # ABL"),
    ],
    # --- Voucher layer ablations ---
    "v_bs_taking": [
        # Set BS edge huge so no take fires
        ("V_BS_EDGE = 10.0",
         "V_BS_EDGE = 99999.0  # ABL"),
        ("        edge = 5.0 if K == 5200 else V_BS_EDGE",
         "        edge = 99999.0  # ABL"),
    ],
    "v_vev5200_carve_out": [
        # Use global V_BS_EDGE for 5200 too (no carve-out)
        ("        edge = 5.0 if K == 5200 else V_BS_EDGE",
         "        edge = V_BS_EDGE  # ABL: no carve-out"),
    ],
    "v_intrinsic_arb": [
        # Both buy and sell intrinsic legs gated by V_INTRINSIC_EDGE; raise it absurd
        ("V_INTRINSIC_EDGE = 2",
         "V_INTRINSIC_EDGE = 99999  # ABL"),
    ],
    "v_callspread_arb": [
        # Make the arb condition impossible (ask_lo - bid_hi < -inf is never true)
        ("            if ask_lo - bid_hi < 0:",
         "            if False and ask_lo - bid_hi < 0:  # ABL: call-spread arb off"),
    ],
    "v_passive_mm": [
        # voucher MM size = 0
        ("V_VOUCHER_MM_SIZE = 40   # v5d sweep: was 20, +$446 def / +$297 imc",
         "V_VOUCHER_MM_SIZE = 0  # ABL"),
    ],
    "v_deep_itm_theta": [
        # Set DEEP_ITM_POS_CAP to 0
        ("    DEEP_ITM_POS_CAP    = 100",
         "    DEEP_ITM_POS_CAP    = 0  # ABL"),
    ],
    "v_otm_passive_bid": [
        # OTM_BID_SIZE = 0
        ("    OTM_BID_SIZE = 5",
         "    OTM_BID_SIZE = 0  # ABL"),
    ],
    "v_deep_otm_bid0": [
        # Skip 6000/6500 bid=0 by zeroing size
        ("    DEEP_OTM_BID_SIZE = 100",
         "    DEEP_OTM_BID_SIZE = 0  # ABL"),
    ],
    "v_obi_conditional": [
        # OBI threshold unreachable
        ("OBI_THRESHOLD = 0.7",
         "OBI_THRESHOLD = 99.0  # ABL"),
    ],
    "yolo_regime_gate": [
        # Force yolo_regime False always
        ("            yolo_regime = (drift <= YOLO_DRIFT_THRESHOLD)",
         "            yolo_regime = False  # ABL"),
    ],
}


def make_variant(name: str, subs):
    text = BASE_TEXT
    for old, new in subs:
        if old not in text:
            print(f"  WARN: substitution not found in {name}: {old[:60]!r}", file=sys.stderr)
            return None
        text = text.replace(old, new, 1)
    out = ABLATE_DIR / f"abl_{name}.py"
    out.write_text(text, encoding="utf-8")
    return out


def run_bt(path: Path, day_arg: str, ticks: int, imc: bool):
    cmd = [
        sys.executable, "-m", "prosperity4bt",
        str(path), day_arg,
        "--ticks", str(ticks),
        "--no-out", "--no-progress",
    ]
    if imc:
        cmd += ["--match-mode", "imc"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "prosperity4bt")
    # Keep workdir = repo root
    p = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, env=env, timeout=900)
    out = p.stdout + p.stderr
    return out


def parse_total(out: str):
    # The script prints multiple "Total profit: ..." lines (one per day, then aggregate).
    # We want the LAST one for multi-day, or the only one for single-day.
    matches = re.findall(r"Total profit:\s*([\-,\d]+)", out)
    if not matches:
        return None
    last = matches[-1].replace(",", "")
    try:
        return int(last)
    except Exception:
        return None


def main():
    out_csv = ABLATE_DIR / "ablation_results.csv"
    # Open immediately, write header + flush per row.
    f = open(out_csv, "w", encoding="utf-8", buffering=1)
    f.write("layer,1k_d3,d_1k,10k_def,d_def,10k_imc,d_imc\n")
    f.flush()

    print("Running baseline r4_final.py ...", flush=True)
    base_results = {}
    base_results["1k_d3"] = parse_total(run_bt(SRC, "4-3", 1000, False))
    base_results["10k_def"] = parse_total(run_bt(SRC, "4", 10000, False))
    base_results["10k_imc"] = parse_total(run_bt(SRC, "4", 10000, True))
    bl_msg = f"BASELINE: 1k_d3={base_results['1k_d3']} | 10k_def={base_results['10k_def']} | 10k_imc={base_results['10k_imc']}"
    print(bl_msg, flush=True)
    f.write(f"BASELINE,{base_results['1k_d3']},0,{base_results['10k_def']},0,{base_results['10k_imc']},0\n")
    f.flush()

    for name, subs in ABLATIONS.items():
        path = make_variant(name, subs)
        if path is None:
            print(f"SKIP {name} (sub not found)", flush=True)
            f.write(f"{name},,,,,,\n"); f.flush()
            continue
        v_1k = parse_total(run_bt(path, "4-3", 1000, False))
        v_def = parse_total(run_bt(path, "4", 10000, False))
        v_imc = parse_total(run_bt(path, "4", 10000, True))
        d1 = (v_1k - base_results['1k_d3']) if v_1k is not None else None
        dd = (v_def - base_results['10k_def']) if v_def is not None else None
        di = (v_imc - base_results['10k_imc']) if v_imc is not None else None
        d1s = f"{d1:+}" if d1 is not None else "?"
        dds = f"{dd:+}" if dd is not None else "?"
        dis = f"{di:+}" if di is not None else "?"
        print(f"ABL {name:30s} | 1k {v_1k} ({d1s}) | def {v_def} ({dds}) | imc {v_imc} ({dis})", flush=True)
        f.write(f"{name},{v_1k},{d1},{v_def},{dd},{v_imc},{di}\n")
        f.flush()
    f.close()
    print(f"\nWrote {out_csv}", flush=True)


if __name__ == "__main__":
    main()
