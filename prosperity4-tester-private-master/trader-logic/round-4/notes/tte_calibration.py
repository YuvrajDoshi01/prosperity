"""Calibrate TTE for R4 by checking IV consistency across strikes and days."""
import csv
import math
from pathlib import Path
from statistics import NormalDist

_ND = NormalDist()
BASE = Path(r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round4")

def bs_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(0, S - K)
    d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _ND.cdf(d1) - K * _ND.cdf(d2)

def implied_vol(mkt, S, K, T):
    intr = max(S - K, 0)
    if mkt <= intr + 0.001 or T <= 0 or mkt >= S:
        return None
    lo, hi = 0.001, 5.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if bs_call(S, K, T, mid) < mkt:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2

def load_prices(day):
    rows = []
    with open(BASE / f"prices_round_4_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows.append(r)
    return rows

STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500]

# Test different TTE assumptions
# R3: TTE=5 at start, so at ts=0 on day 0: T=5/250=0.02
# R4 day 1 = R3 day 1, so at R3 day 1 ts=0: T=(5-1)/250 = 4/250 = 0.016
# If R4 uses its own TTE scale: TTE=4 at start means T=4/250 at ts=0 day 1

# The key test: which TTE gives the most CONSISTENT IVs across strikes?
for tte_start in [3.0, 4.0, 5.0]:
    print(f"\n{'='*60}")
    print(f"TTE_AT_START = {tte_start}")
    print(f"{'='*60}")
    for day in [1, 2, 3]:
        rows = load_prices(day)
        # Collect mid-day snapshot
        vfe_rows = [(int(r["timestamp"]), float(r["mid_price"])) for r in rows if r["product"] == "VELVETFRUIT_EXTRACT"]

        # Sample at ts=500000 (midday)
        ts_target = 500000
        vfe_at_target = None
        for ts, mid in vfe_rows:
            if ts >= ts_target:
                vfe_at_target = mid
                break
        if vfe_at_target is None:
            vfe_at_target = vfe_rows[-1][1]

        S = vfe_at_target
        # T at midday: tte_start - (day-1 full days elapsed) - 0.5 (half day)
        days_elapsed = (day - 1) + 0.5  # day 1 = 0.5, day 2 = 1.5, day 3 = 2.5
        T = max(tte_start - days_elapsed, 0.01) / 250.0

        print(f"\n  Day {day} (S={S:.1f}, T_days={tte_start-days_elapsed:.1f}, T_annual={T:.5f}):")

        ivs = {}
        for K in STRIKES:
            vev_rows = [(int(r["timestamp"]), float(r["mid_price"])) for r in rows if r["product"] == f"VEV_{K}"]
            vev_at_target = None
            for ts, mid in vev_rows:
                if ts >= ts_target:
                    vev_at_target = mid
                    break
            if vev_at_target is None or vev_at_target <= 0.5:
                continue

            iv = implied_vol(vev_at_target, S, K, T)
            if iv is not None:
                ivs[K] = iv
                print(f"    K={K}: C={vev_at_target:.1f}, IV={iv:.2%}")

        if len(ivs) >= 3:
            vals = list(ivs.values())
            iv_mean = sum(vals) / len(vals)
            iv_std = (sum((v - iv_mean)**2 for v in vals) / len(vals))**0.5
            print(f"    -> IV mean={iv_mean:.2%}, std={iv_std:.2%}, CoV={iv_std/iv_mean:.2%}")

# Also test using R3's TTE convention (timestamp-based, continuous decay)
print(f"\n{'='*60}")
print("R3 CONVENTION: T = (TTE_START - timestamp/1_000_000) / 250")
print(f"{'='*60}")
for tte_start in [4.0, 5.0]:
    print(f"\n  TTE_START = {tte_start}:")
    for day in [1, 2, 3]:
        rows = load_prices(day)
        vfe_rows = [(int(r["timestamp"]), float(r["mid_price"])) for r in rows if r["product"] == "VELVETFRUIT_EXTRACT"]

        # At ts=0 (start of day)
        S = vfe_rows[0][1]
        T_r3 = max(tte_start - 0 / 1_000_000, 0.01) / 250.0

        print(f"    Day {day} ts=0: S={S:.1f}, T={T_r3:.5f} ({tte_start:.1f} days)")

        # Check IVs at ts=0
        ivs = {}
        for K in STRIKES:
            vev_rows = [(int(r["timestamp"]), float(r["mid_price"])) for r in rows if r["product"] == f"VEV_{K}"]
            if not vev_rows or vev_rows[0][1] <= 0.5:
                continue
            C = vev_rows[0][1]
            iv = implied_vol(C, S, K, T_r3)
            if iv is not None:
                ivs[K] = iv

        if ivs:
            vals = list(ivs.values())
            iv_mean = sum(vals) / len(vals)
            iv_std = (sum((v - iv_mean)**2 for v in vals) / len(vals))**0.5
            print(f"      IVs: {', '.join(f'K{k}={v:.2%}' for k,v in sorted(ivs.items()))}")
            print(f"      mean={iv_mean:.2%}, std={iv_std:.2%}, CoV={iv_std/iv_mean:.2%}")
