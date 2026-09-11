"""Round 4 EDA: comprehensive analysis of all 12 products across 3 days."""
import csv
import math
from collections import defaultdict
from pathlib import Path

BASE = Path(r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round4\ROUND_4")

def load_prices(day):
    rows = []
    with open(BASE / f"prices_round_4_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows.append(r)
    return rows

def load_trades(day):
    rows = []
    with open(BASE / f"trades_round_4_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows.append(r)
    return rows

# ---- Collect per-product time series ----
products_data = defaultdict(lambda: defaultdict(list))  # product -> day -> list of dicts

for day in [1, 2, 3]:
    for row in load_prices(day):
        p = row["product"]
        ts = int(row["timestamp"])
        mid = float(row["mid_price"])
        bp1 = int(row["bid_price_1"]) if row["bid_price_1"] else None
        bv1 = int(row["bid_volume_1"]) if row["bid_volume_1"] else None
        ap1 = int(row["ask_price_1"]) if row["ask_price_1"] else None
        av1 = int(row["ask_volume_1"]) if row["ask_volume_1"] else None
        bp2 = int(row["bid_price_2"]) if row["bid_price_2"] else None
        bv2 = int(row["bid_volume_2"]) if row["bid_volume_2"] else None
        ap2 = int(row["ask_price_2"]) if row["ask_price_2"] else None
        av2 = int(row["ask_volume_2"]) if row["ask_volume_2"] else None
        spread = (ap1 - bp1) if (ap1 is not None and bp1 is not None) else None
        products_data[p][day].append({
            "ts": ts, "mid": mid, "spread": spread,
            "bp1": bp1, "bv1": bv1, "ap1": ap1, "av1": av1,
            "bp2": bp2, "bv2": bv2, "ap2": ap2, "av2": av2,
        })

# ---- Trades analysis ----
trades_data = defaultdict(lambda: defaultdict(list))  # product -> day -> list
for day in [1, 2, 3]:
    for row in load_trades(day):
        sym = row["symbol"]
        trades_data[sym][day].append({
            "ts": int(row["timestamp"]),
            "buyer": row["buyer"],
            "seller": row["seller"],
            "price": float(row["price"]),
            "qty": int(row["quantity"]),
        })

print("=" * 80)
print("ROUND 4 EDA — PRODUCT SUMMARY")
print("=" * 80)

PRODUCTS = sorted(products_data.keys())
for p in PRODUCTS:
    print(f"\n{'='*60}")
    print(f"  {p}")
    print(f"{'='*60}")
    for day in [1, 2, 3]:
        ticks = products_data[p][day]
        if not ticks:
            print(f"  Day {day}: NO DATA")
            continue
        mids = [t["mid"] for t in ticks]
        spreads = [t["spread"] for t in ticks if t["spread"] is not None]

        n = len(mids)
        first_mid = mids[0]
        last_mid = mids[-1]
        min_mid = min(mids)
        max_mid = max(mids)
        drift = last_mid - first_mid

        # Returns
        returns = [mids[i] - mids[i-1] for i in range(1, len(mids))]
        mean_ret = sum(returns) / len(returns) if returns else 0
        std_ret = (sum((r - mean_ret)**2 for r in returns) / len(returns))**0.5 if returns else 0

        # AC(1)
        if len(returns) > 1:
            mean_r = sum(returns) / len(returns)
            var_r = sum((r - mean_r)**2 for r in returns) / len(returns)
            cov_r = sum((returns[i] - mean_r) * (returns[i-1] - mean_r) for i in range(1, len(returns))) / (len(returns) - 1)
            ac1 = cov_r / var_r if var_r > 0 else 0
        else:
            ac1 = 0

        # Spread distribution
        if spreads:
            spread_counts = defaultdict(int)
            for s in spreads:
                spread_counts[s] += 1
            top_spreads = sorted(spread_counts.items(), key=lambda x: -x[1])[:5]
            avg_spread = sum(spreads) / len(spreads)
            min_spread = min(spreads)
            max_spread = max(spreads)

        # L1 volume
        bv1s = [t["bv1"] for t in ticks if t["bv1"] is not None]
        av1s = [t["av1"] for t in ticks if t["av1"] is not None]
        avg_bv1 = sum(bv1s) / len(bv1s) if bv1s else 0
        avg_av1 = sum(av1s) / len(av1s) if av1s else 0

        # One-sided ticks
        one_sided = sum(1 for t in ticks if t["bp1"] is None or t["ap1"] is None)

        print(f"\n  Day {day} ({n} ticks):")
        print(f"    Mid:    {first_mid:.1f} -> {last_mid:.1f}  (range {min_mid:.1f}-{max_mid:.1f}, drift={drift:+.1f})")
        print(f"    Return: mean={mean_ret:.4f}, std={std_ret:.4f}, AC(1)={ac1:.3f}")
        if spreads:
            print(f"    Spread: avg={avg_spread:.1f}, min={min_spread}, max={max_spread}")
            print(f"    Spread dist: {dict(top_spreads)}")
        print(f"    L1 vol: bid={avg_bv1:.1f}, ask={avg_av1:.1f}")
        print(f"    One-sided: {one_sided}/{n} ({100*one_sided/n:.1f}%)")

    # Trade stats
    print(f"\n  TRADES:")
    for day in [1, 2, 3]:
        tr = trades_data[p][day]
        if not tr:
            print(f"    Day {day}: 0 trades")
            continue
        total_qty = sum(t["qty"] for t in tr)
        avg_qty = total_qty / len(tr)
        # Unique bots
        buyers = set(t["buyer"] for t in tr)
        sellers = set(t["seller"] for t in tr)
        all_bots = buyers | sellers
        print(f"    Day {day}: {len(tr)} trades, total_qty={total_qty}, avg_qty={avg_qty:.1f}, bots={all_bots}")

# ---- Cross-day comparison ----
print("\n" + "=" * 80)
print("CROSS-DAY COMPARISON")
print("=" * 80)

print(f"\n{'Product':>25} | {'D1 open':>8} {'D1 close':>8} {'D1 drift':>8} | {'D2 open':>8} {'D2 close':>8} {'D2 drift':>8} | {'D3 open':>8} {'D3 close':>8} {'D3 drift':>8}")
for p in PRODUCTS:
    row = f"{p:>25} |"
    for day in [1, 2, 3]:
        ticks = products_data[p][day]
        if ticks:
            mids = [t["mid"] for t in ticks]
            row += f" {mids[0]:>8.1f} {mids[-1]:>8.1f} {mids[-1]-mids[0]:>+8.1f} |"
        else:
            row += f" {'N/A':>8} {'N/A':>8} {'N/A':>8} |"
    print(row)

# ---- HP special analysis (spread=17 signal from R3) ----
print("\n" + "=" * 80)
print("HP SPREAD=17 ANALYSIS (R3 GIGA SHORT signal)")
print("=" * 80)
for day in [1, 2, 3]:
    ticks = products_data["HYDROGEL_PACK"][day]
    if not ticks:
        continue
    spread_17_count = sum(1 for t in ticks if t["spread"] == 17)
    total = len(ticks)
    mids_at_17 = [t["mid"] for t in ticks if t["spread"] == 17]
    mids_after_17 = []
    for i, t in enumerate(ticks):
        if t["spread"] == 17 and i + 50 < len(ticks):
            mids_after_17.append(ticks[i+50]["mid"] - t["mid"])
    print(f"  Day {day}: spread=17 in {spread_17_count}/{total} ticks ({100*spread_17_count/total:.1f}%)")
    if mids_at_17:
        print(f"    Mid when spread=17: mean={sum(mids_at_17)/len(mids_at_17):.1f}, range={min(mids_at_17):.1f}-{max(mids_at_17):.1f}")
    if mids_after_17:
        avg_future = sum(mids_after_17) / len(mids_after_17)
        print(f"    Mid change 50 ticks after spread=17: mean={avg_future:.1f}")

# ---- VFE Wall Mid analysis ----
print("\n" + "=" * 80)
print("VFE WALL MID ANALYSIS")
print("=" * 80)
for day in [1, 2, 3]:
    ticks = products_data["VELVETFRUIT_EXTRACT"][day]
    if not ticks:
        continue
    wall_mids = []
    for t in ticks:
        # Wall mid = midpoint of highest-volume bid and ask
        levels_bid = []
        if t["bp1"] is not None and t["bv1"] is not None:
            levels_bid.append((t["bp1"], t["bv1"]))
        if t["bp2"] is not None and t["bv2"] is not None:
            levels_bid.append((t["bp2"], t["bv2"]))
        levels_ask = []
        if t["ap1"] is not None and t["av1"] is not None:
            levels_ask.append((t["ap1"], t["av1"]))
        if t["ap2"] is not None and t["av2"] is not None:
            levels_ask.append((t["ap2"], t["av2"]))

        if levels_bid and levels_ask:
            best_bid = max(levels_bid, key=lambda x: x[1])
            best_ask = max(levels_ask, key=lambda x: x[1])
            wm = (best_bid[0] + best_ask[0]) / 2
            wall_mids.append(wm)

    if wall_mids:
        diffs = [wall_mids[i] - wall_mids[i-1] for i in range(1, len(wall_mids))]
        print(f"  Day {day}: Wall Mid range {min(wall_mids):.1f}-{max(wall_mids):.1f}, mean={sum(wall_mids)/len(wall_mids):.1f}")

# ---- Voucher BS analysis ----
print("\n" + "=" * 80)
print("VOUCHER BS ANALYSIS — IMPLIED VOL")
print("=" * 80)

STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]

def bs_call_price(S, K, T, sigma, r=0):
    """Black-Scholes call price."""
    if T <= 0 or sigma <= 0:
        return max(0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    # Approximate N(x) using erf
    def norm_cdf(x):
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)

def implied_vol(S, K, T, market_price, r=0):
    """Bisection IV solver."""
    if market_price <= max(0, S - K):
        return None
    lo, hi = 0.001, 5.0
    for _ in range(100):
        mid = (lo + hi) / 2
        p = bs_call_price(S, K, T, mid, r)
        if p > market_price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2

# TTE: R4 starts with some TTE — need to figure out from R3 context
# R3 said TTE 5d at R3 start. R4 is next round so TTE = 4d at R4 start?
# Day 1 = 4/5, Day 2 = 3/5, Day 3 = 2/5
# Actually need to check — each day is 1/5 of total = 0.2
# R3 was 5 days total. Let's assume R4 has similar structure.
# R4 day 1 might be day 4 of the 5-day option lifecycle = TTE 2/5 = 0.4?
# Or R4 is its own thing. Let's compute IV for different TTE assumptions.

print("\n  Testing TTE assumptions...")
for tte_days_remaining in [4, 3, 2, 1]:
    T = tte_days_remaining / 252  # annualized
    print(f"\n  --- TTE = {tte_days_remaining} days (T={T:.4f}) ---")
    for day in [1, 2, 3]:
        vfe_ticks = products_data["VELVETFRUIT_EXTRACT"][day]
        if not vfe_ticks:
            continue
        # Use mid-day VFE price
        mid_idx = len(vfe_ticks) // 2
        S = vfe_ticks[mid_idx]["mid"]

        ivs = {}
        for K in STRIKES:
            vev_name = f"VEV_{K}"
            vev_ticks = products_data[vev_name][day]
            if not vev_ticks:
                continue
            vev_mid_idx = len(vev_ticks) // 2
            c_price = vev_ticks[vev_mid_idx]["mid"]
            intrinsic = max(0, S - K)
            if c_price <= intrinsic or c_price <= 0.5:
                ivs[K] = None
                continue
            iv = implied_vol(S, K, T, c_price)
            ivs[K] = iv

        print(f"    Day {day} (S={S:.1f}): ", end="")
        for K in STRIKES:
            iv = ivs.get(K)
            if iv is not None:
                print(f"K{K}={iv:.2%} ", end="")
            else:
                print(f"K{K}=N/A ", end="")
        print()

# ---- R3 vs R4 comparison for HP and VFE ----
print("\n" + "=" * 80)
print("R4 vs R3 DATA DIFFERENCES")
print("=" * 80)
print("""
R3 Day 2 (website test): HP mid ~10,010, VFE mid ~5,260
R4 Day 1: HP mid ~9958, VFE mid ~5245
R4 Day 2: HP mid ~10011, VFE mid ~5268  (SIMILAR to R3 day 2!)
R4 Day 3: HP mid ~10008, VFE mid ~5296
""")

# Check if R4 data is just R3 data shifted or genuinely new
print("Checking first 5 timestamps per product for R4 vs R3 patterns:")
for p in ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"]:
    print(f"\n  {p}:")
    for day in [1, 2, 3]:
        ticks = products_data[p][day][:5]
        print(f"    Day {day}: {[(t['ts'], t['mid'], t['spread']) for t in ticks]}")

# ---- Tick count ----
print("\n" + "=" * 80)
print("TICK COUNTS")
print("=" * 80)
for day in [1, 2, 3]:
    for p in PRODUCTS:
        ticks = products_data[p][day]
        if ticks:
            max_ts = max(t["ts"] for t in ticks)
            print(f"  Day {day} {p}: {len(ticks)} ticks, max_ts={max_ts}")
            break  # all products same tick count per day

print("\n\nDONE.")
