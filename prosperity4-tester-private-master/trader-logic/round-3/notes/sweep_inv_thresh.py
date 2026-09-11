"""sweep_inv_thresh.py - Sweep INV_SUPPRESS_THRESH for hp_inv_aware_mm.py.

Tests thresholds {50, 80, 100, 120, 150, 200(=disabled)} across days 0,1,2.
"""
import subprocess
import sys
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRIPT = os.path.join(BASE, "trader-logic", "round-3", "notes", "hp_inv_aware_mm.py")

THRESHOLDS = [50, 80, 100, 120, 150]
DAYS = [0, 1, 2]

def run_bt(script_path, day, thresh):
    """Run BT and extract HP PnL."""
    # Temporarily monkey-patch the threshold
    with open(script_path, "r") as f:
        src = f.read()

    # Replace the threshold
    modified = re.sub(
        r'INV_SUPPRESS_THRESH = \d+',
        f'INV_SUPPRESS_THRESH = {thresh}',
        src, count=1
    )
    with open(script_path, "w") as f:
        f.write(modified)

    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.join(BASE, "prosperity4bt")

    result = subprocess.run(
        [sys.executable, "-m", "prosperity4bt", script_path, f"3-{day}",
         "--ticks", "10000", "--no-progress", "--no-out"],
        capture_output=True, text=True, env=env, cwd=BASE
    )

    output = result.stdout + result.stderr
    hp_pnl = None
    total_pnl = None
    for line in output.split("\n"):
        if "HYDROGEL_PACK:" in line:
            match = re.search(r'HYDROGEL_PACK:\s*([\-\d,]+)', line)
            if match:
                hp_pnl = int(match.group(1).replace(",", ""))
        if "Total profit:" in line:
            match = re.search(r'Total profit:\s*([\-\d,]+)', line)
            if match:
                total_pnl = int(match.group(1).replace(",", ""))

    return hp_pnl, total_pnl


def main():
    print(f"{'Thresh':>8} | ", end="")
    for d in DAYS:
        print(f"{'D'+str(d)+' HP':>10} {'D'+str(d)+' Tot':>10} | ", end="")
    print(f"{'3-Day HP':>10} {'3-Day Tot':>10}")
    print("-" * 100)

    # First show baseline (v22 = no suppression = thresh=200 = disabled)
    results = {}
    for thresh in THRESHOLDS + [200]:  # 200 = effectively disabled
        row_hp = []
        row_tot = []
        for d in DAYS:
            hp, tot = run_bt(SCRIPT, d, thresh)
            row_hp.append(hp or 0)
            row_tot.append(tot or 0)
        results[thresh] = (row_hp, row_tot)

        label = f"{thresh}" if thresh < 200 else "v22(200)"
        print(f"{label:>8} | ", end="")
        for i, d in enumerate(DAYS):
            print(f"{row_hp[i]:10,d} {row_tot[i]:10,d} | ", end="")
        print(f"{sum(row_hp):10,d} {sum(row_tot):10,d}")

    # Restore original threshold
    with open(SCRIPT, "r") as f:
        src = f.read()
    src = re.sub(r'INV_SUPPRESS_THRESH = \d+', 'INV_SUPPRESS_THRESH = 80', src, count=1)
    with open(SCRIPT, "w") as f:
        f.write(src)


if __name__ == "__main__":
    main()
