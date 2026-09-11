"""
Test L1-only microprice (requires refitting regression) and other untested FV ideas.
"""
import subprocess, sys, re, os
import csv
import numpy as np

# ═══════════════════════════════════════════════════════════════
# Step 1: Refit regression with L1-only microprice
# ═══════════════════════════════════════════════════════════════
print("=" * 75)
print("STEP 1: Refit regression with L1-only microprice")
print("=" * 75)

CSV_FILES = [
    "prosperity4bt/resources/round0/prices_round_0_day_-1.csv",
    "prosperity4bt/resources/round0/prices_round_0_day_-2.csv",
    "prosperity4bt/resources/round0/prices_round_0_day_0.csv",
]

for csv_path in CSV_FILES:
    microprice_total = []
    microprice_l1 = []
    mids = []

    with open(csv_path) as f:
        reader = csv.reader(f, delimiter=';')
        header = next(reader)
        for row in reader:
            product = row[2]
            if product != "TOMATOES":
                continue
            bp1 = float(row[3]) if row[3] else 0
            bv1 = float(row[4]) if row[4] else 0
            bp2 = float(row[5]) if row[5] else 0
            bv2 = float(row[6]) if row[6] else 0
            bp3 = float(row[7]) if row[7] else 0
            bv3 = float(row[8]) if row[8] else 0
            ap1 = float(row[9]) if row[9] else 0
            av1 = float(row[10]) if row[10] else 0
            ap2 = float(row[11]) if row[11] else 0
            av2 = float(row[12]) if row[12] else 0
            ap3 = float(row[13]) if row[13] else 0
            av3 = float(row[14]) if row[14] else 0

            if bp1 == 0 or ap1 == 0:
                continue

            mid = (bp1 + ap1) / 2
            mids.append(mid)

            # Total volume microprice (current method)
            total_bv = bv1 + bv2 + bv3
            total_av = av1 + av2 + av3
            if total_bv + total_av > 0:
                mp_total = bp1 + (total_bv / (total_bv + total_av)) * (ap1 - bp1)
            else:
                mp_total = mid
            microprice_total.append(mp_total)

            # L1-only microprice
            if bv1 + av1 > 0:
                mp_l1 = bp1 + (bv1 / (bv1 + av1)) * (ap1 - bp1)
            else:
                mp_l1 = mid
            microprice_l1.append(mp_l1)

    day = csv_path.split("day_")[1].replace(".csv", "")
    mids = np.array(mids)
    dmid = np.diff(mids)

    for name, mp_arr in [("total_vol", microprice_total), ("l1_only", microprice_l1)]:
        mp = np.array(mp_arr)
        # Fit lag-4 regression: mid[t+1] = intercept + c1*mp[t-3] + c2*mp[t-2] + c3*mp[t-1] + c4*mp[t]
        n = len(mp)
        X = np.column_stack([mp[i:n-4+i] for i in range(4)])
        y = mids[4:]  # target is mid at t+1 (=mids[4], mids[5], ...)
        # Actually target should be mids at next tick after the 4th lag
        y = mids[4:n]
        X = X[:len(y)]

        # OLS
        XtX = X.T @ X
        Xty = X.T @ y
        coefs = np.linalg.solve(XtX, Xty)

        # With intercept
        X_int = np.column_stack([np.ones(len(X)), X])
        XtX_int = X_int.T @ X_int
        Xty_int = X_int.T @ y
        coefs_int = np.linalg.solve(XtX_int, Xty_int)

        y_pred = X_int @ coefs_int
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r2 = 1 - ss_res / ss_tot

        print(f"\n  Day {day:>3} | {name:>12} | R²={r2:.6f}")
        print(f"    intercept={coefs_int[0]:.6f}  coefs={[f'{c:.6f}' for c in coefs_int[1:]]}")

# ═══════════════════════════════════════════════════════════════
# Step 2: Build and test L1-microprice variant
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 75)
print("STEP 2: Backtest L1 microprice vs total microprice")
print("=" * 75)

BASELINE = "trader-logic/round-0/s40_v2.py"
TMPFILE = "trader-logic/round-0/s41_mp_tmp.py"

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
    print(f"{name:<40} {d0:>8,} {d1:>8,} {d2:>8,} {total:>8,}")
    sys.stdout.flush()
    return d0, d1, d2, total

print(f"\n{'Variant':<40} {'Day0':>8} {'Day-1':>8} {'Day-2':>8} {'Total':>8}")
print("-" * 75)

# Baseline
test_variant("baseline_total_vol_mp", baseline_code)

# L1-only microprice (same regression coefs — quick test)
l1_code = baseline_code.replace(
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
test_variant("l1_mp_same_coefs", l1_code)

# L1-only microprice with refitted coefs (use day 0 fit — we'll compute below)
# We already computed the coefs above, let me extract them for day 0 L1
# For now just test with the day -1/-2 averaged coefs, we'll read them from output

if os.path.exists(TMPFILE):
    os.remove(TMPFILE)
