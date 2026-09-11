"""
Quick sweep: test s40_v2 with different AR2 and skew values by modifying the file in-place.
"""
import subprocess, sys, re, os, shutil

TEMPLATE_PATH = "trader-logic/round-0/s40_v2.py"

# Read the template
with open(TEMPLATE_PATH) as f:
    template = f.read()

CONFIGS = [
    ("ar2=0.0_skew=0.0",   0.0, 0.0),
    ("ar2=0.0_skew=0.01",  0.0, 0.01),
    ("ar2=0.1_skew=0.01",  0.1, 0.01),
    ("ar2=0.2_skew=0.01",  0.2, 0.01),
    ("ar2=0.3_skew=0.01",  0.3, 0.01),   # Current s40_v2
    ("ar2=0.5_skew=0.01",  0.5, 0.01),
    ("ar2=0.7_skew=0.01",  0.7, 0.01),
    ("ar2=1.0_skew=0.01",  1.0, 0.01),
    ("ar2=0.3_skew=0.0",   0.3, 0.0),
    ("ar2=0.3_skew=0.005", 0.3, 0.005),
    ("ar2=0.3_skew=0.015", 0.3, 0.015),
    ("ar2=0.3_skew=0.02",  0.3, 0.02),
    ("ar2=0.3_skew=0.03",  0.3, 0.03),
]

def make_variant(code, ar2_weight, skew_gamma):
    code = re.sub(r'AR2_POST_WEIGHT = [\d.]+', f'AR2_POST_WEIGHT = {ar2_weight}', code)
    code = re.sub(r'SKEW_GAMMA = [\d.]+', f'SKEW_GAMMA = {skew_gamma}', code)
    return code

def run_bt(path, day):
    cmd = [sys.executable, "-m", "prosperity4bt", path, f"0-{day}", "--no-out", "--no-progress"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    total = 0
    for line in out.split('\n'):
        m = re.search(r':\s+([\d,-]+)$', line.strip())
        if m and ('TOMATOES' in line or 'EMERALDS' in line or 'Total' in line):
            val = m.group(1).replace(',', '')
            if 'Total' in line:
                return int(val)
    return None

tmpdir = "trader-logic/round-0/sim_tmp"
os.makedirs(tmpdir, exist_ok=True)

print(f"{'Config':<25} {'Day0':>8} {'Day-1':>8} {'Day-2':>8} {'Total':>8}")
print("=" * 60)

for name, ar2, skew in CONFIGS:
    code = make_variant(template, ar2, skew)
    path = os.path.join(tmpdir, f"s40_{name}.py")
    with open(path, 'w') as f:
        f.write(code)

    d0 = run_bt(path, 0)
    d1 = run_bt(path, -1)
    d2 = run_bt(path, -2)
    d0v = d0 or 0
    d1v = d1 or 0
    d2v = d2 or 0
    total = d0v + d1v + d2v
    print(f"{name:<25} {d0v:>8,} {d1v:>8,} {d2v:>8,} {total:>8,}")
    sys.stdout.flush()

shutil.rmtree(tmpdir, ignore_errors=True)
