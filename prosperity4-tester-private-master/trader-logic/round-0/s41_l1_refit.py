"""Test L1 microprice with refitted coefficients from each day"""
import subprocess, sys, re, os

BASELINE = "trader-logic/round-0/s40_v2.py"
TMPFILE = "trader-logic/round-0/s41_l1_tmp.py"

with open(BASELINE) as f:
    baseline_code = f.read()

def run_bt(path, day):
    cmd = [sys.executable, "-m", "prosperity4bt", path, f"0-{day}", "--no-out", "--no-progress"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    m = re.search(r'Total profit:\s*([-\d,]+)', out)
    if m:
        return int(m.group(1).replace(',', ''))
    return None

def test_variant(name, code):
    with open(TMPFILE, 'w') as f:
        f.write(code)
    d0 = run_bt(TMPFILE, 0) or 0
    d1 = run_bt(TMPFILE, -1) or 0
    d2 = run_bt(TMPFILE, -2) or 0
    total = d0 + d1 + d2
    print(f"{name:<45} {d0:>8,} {d1:>8,} {d2:>8,} {total:>8,}")
    sys.stdout.flush()

# L1 refitted coefs from regression output:
# Day -1: intercept=7.157887  [0.091681, 0.150321, 0.253105, 0.503454]
# Day -2: intercept=16.634929  [0.105606, 0.145263, 0.258181, 0.487629]
# Day  0: intercept=54.157054  [0.104178, 0.119137, 0.290111, 0.475720]

# Average of day -1 and -2 (training set):
# intercept = (7.157887 + 16.634929) / 2 = 11.896408
# coefs = [(0.091681+0.105606)/2, (0.150321+0.145263)/2, (0.253105+0.258181)/2, (0.503454+0.487629)/2]
#        = [0.098644, 0.147792, 0.255643, 0.495542]

CONFIGS = [
    # Original total-vol regression
    ("baseline_total_vol", {
        "intercept": "2.208667",
        "coefs": "[0.059694, 0.117270, 0.244154, 0.578440]",
        "l1": False
    }),
    # L1 with day -1/-2 averaged coefs (OOS for day 0)
    ("l1_avg_d-1_d-2", {
        "intercept": "11.896408",
        "coefs": "[0.098644, 0.147792, 0.255643, 0.495542]",
        "l1": True
    }),
    # L1 with day 0 coefs (in-sample, for calibration)
    ("l1_day0_insample", {
        "intercept": "54.157054",
        "coefs": "[0.104178, 0.119137, 0.290111, 0.475720]",
        "l1": True
    }),
    # L1 with day -1 coefs only
    ("l1_day-1_only", {
        "intercept": "7.157887",
        "coefs": "[0.091681, 0.150321, 0.253105, 0.503454]",
        "l1": True
    }),
    # Total-vol with refitted coefs (day -1/-2 avg) for comparison
    ("total_vol_avg_d-1_d-2", {
        "intercept": "14.497116",
        "coefs": "[0.135821, 0.174669, 0.253866, 0.432743]",
        "l1": False
    }),
]

print(f"{'Variant':<45} {'Day0':>8} {'Day-1':>8} {'Day-2':>8} {'Total':>8}")
print("=" * 80)

for name, cfg in CONFIGS:
    code = baseline_code
    code = code.replace(
        "REGRESSION_INTERCEPT = 2.208667",
        f"REGRESSION_INTERCEPT = {cfg['intercept']}")
    code = code.replace(
        "REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]",
        f"REGRESSION_COEFS = {cfg['coefs']}")
    if cfg["l1"]:
        code = code.replace(
            """                # ── Microprice regression (from s36) ──
                microprice = (best_bid + (total_bid_vol / (total_bid_vol + total_ask_vol))
                              * (best_ask - best_bid)
                              if (total_bid_vol + total_ask_vol) > 0 else mid)""",
            """                # ── Microprice using L1 volume only ──
                bid1_vol = book.buy_orders.get(best_bid, 0)
                ask1_vol = abs(book.sell_orders.get(best_ask, 0))
                microprice = (best_bid + (bid1_vol / (bid1_vol + ask1_vol))
                              * (best_ask - best_bid)
                              if (bid1_vol + ask1_vol) > 0 else mid)""")
    test_variant(name, code)

if os.path.exists(TMPFILE):
    os.remove(TMPFILE)
