"""
Quick sweep: modify s40_v2.py in-place, run, restore. No subdirectory.
"""
import subprocess, sys, re, os

TEMPLATE_PATH = "trader-logic/round-0/s40_v2.py"

with open(TEMPLATE_PATH) as f:
    original = f.read()

CONFIGS = [
    ("ar2=0.0_skew=0.0",   0.0, 0.0),
    ("ar2=0.0_skew=0.01",  0.0, 0.01),
    ("ar2=0.1_skew=0.01",  0.1, 0.01),
    ("ar2=0.2_skew=0.01",  0.2, 0.01),
    ("ar2=0.3_skew=0.01",  0.3, 0.01),
    ("ar2=0.5_skew=0.01",  0.5, 0.01),
    ("ar2=0.7_skew=0.01",  0.7, 0.01),
    ("ar2=1.0_skew=0.01",  1.0, 0.01),
    ("ar2=0.3_skew=0.0",   0.3, 0.0),
    ("ar2=0.3_skew=0.005", 0.3, 0.005),
    ("ar2=0.3_skew=0.015", 0.3, 0.015),
    ("ar2=0.3_skew=0.02",  0.3, 0.02),
    ("ar2=0.3_skew=0.03",  0.3, 0.03),
]

TMPFILE = "trader-logic/round-0/s40_tmp_sweep.py"

def make_variant(code, ar2_weight, skew_gamma):
    code = re.sub(r'AR2_POST_WEIGHT = [\d.]+', f'AR2_POST_WEIGHT = {ar2_weight}', code)
    code = re.sub(r'SKEW_GAMMA = [\d.]+', f'SKEW_GAMMA = {skew_gamma}', code)
    return code

def run_bt(path, day):
    cmd = [sys.executable, "-m", "prosperity4bt", path, f"0-{day}", "--no-out", "--no-progress"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    # Parse "Total profit: X,XXX" or "Total profit: -X,XXX"
    m = re.search(r'Total profit:\s*([-\d,]+)', out)
    if m:
        return int(m.group(1).replace(',', ''))
    return None

print(f"{'Config':<25} {'Day0':>8} {'Day-1':>8} {'Day-2':>8} {'Total':>8}")
print("=" * 60)

try:
    for name, ar2, skew in CONFIGS:
        code = make_variant(original, ar2, skew)
        with open(TMPFILE, 'w') as f:
            f.write(code)

        d0 = run_bt(TMPFILE, 0) or 0
        d1 = run_bt(TMPFILE, -1) or 0
        d2 = run_bt(TMPFILE, -2) or 0
        total = d0 + d1 + d2
        print(f"{name:<25} {d0:>8,} {d1:>8,} {d2:>8,} {total:>8,}")
        sys.stdout.flush()
finally:
    if os.path.exists(TMPFILE):
        os.remove(TMPFILE)
