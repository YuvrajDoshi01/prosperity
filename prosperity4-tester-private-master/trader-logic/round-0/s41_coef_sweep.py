"""
Deep dive: sweep regression coefficients. The averaged d-1/d-2 coefs scored 2,896.
Is this overfit to day 0, or a genuinely better regression?
"""
import subprocess, sys, re, os

BASELINE = "trader-logic/round-0/s40_v2.py"
TMPFILE = "trader-logic/round-0/s41_coef_tmp.py"

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
    print(f"{name:<50} {d0:>8,} {d1:>8,} {d2:>8,} {total:>8,}")
    sys.stdout.flush()

print(f"{'Variant':<50} {'Day0':>8} {'Day-1':>8} {'Day-2':>8} {'Total':>8}")
print("=" * 85)

# Original s36 coefs (from refit_regression on... what training data?)
COEF_SETS = [
    ("s36_original", "2.208667", "[0.059694, 0.117270, 0.244154, 0.578440]"),
    # Refitted total-vol from each day:
    ("refit_d-1", "10.530531", "[0.130456, 0.173436, 0.249136, 0.444855]"),
    ("refit_d-2", "18.463700", "[0.141185, 0.175901, 0.258595, 0.420631]"),
    ("refit_d0_insample", "65.931524", "[0.137463, 0.149770, 0.278882, 0.420674]"),
    ("refit_avg_d-1_d-2", "14.497116", "[0.135821, 0.174669, 0.253866, 0.432743]"),
    # Weighted average: 2/3 d-1 + 1/3 d-2
    ("refit_w23_d-1_w13_d-2", "13.174254",
     f"[{(0.130456*2+0.141185)/3:.6f}, {(0.173436*2+0.175901)/3:.6f}, "
     f"{(0.249136*2+0.258595)/3:.6f}, {(0.444855*2+0.420631)/3:.6f}]"),
    # Just d-1 coefs (closest to s36 intercept)
    # Intercept sensitivity: try avg coefs with different intercepts
    ("avg_coefs_int=10", "10.0", "[0.135821, 0.174669, 0.253866, 0.432743]"),
    ("avg_coefs_int=12", "12.0", "[0.135821, 0.174669, 0.253866, 0.432743]"),
    ("avg_coefs_int=15", "15.0", "[0.135821, 0.174669, 0.253866, 0.432743]"),
    ("avg_coefs_int=18", "18.0", "[0.135821, 0.174669, 0.253866, 0.432743]"),
    ("avg_coefs_int=20", "20.0", "[0.135821, 0.174669, 0.253866, 0.432743]"),
]

for name, intercept, coefs in COEF_SETS:
    code = baseline_code
    code = code.replace(
        "REGRESSION_INTERCEPT = 2.208667",
        f"REGRESSION_INTERCEPT = {intercept}")
    code = code.replace(
        "REGRESSION_COEFS = [0.059694, 0.117270, 0.244154, 0.578440]",
        f"REGRESSION_COEFS = {coefs}")
    test_variant(name, code)

if os.path.exists(TMPFILE):
    os.remove(TMPFILE)
