"""Analyze day 3 to understand the HP and VFE losses."""
import csv
from pathlib import Path
from collections import defaultdict

BASE = Path(r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round4")

def load_prices(day):
    rows = []
    with open(BASE / f"prices_round_4_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows.append(r)
    return rows

# Day 3 HP analysis: when does spread=17 fire? When does spread=7 fire?
print("=" * 60)
print("DAY 3 HP SPREAD ANALYSIS")
print("=" * 60)
rows = load_prices(3)
hp_rows = [(int(r["timestamp"]), float(r["mid_price"]),
            int(r["ask_price_1"]) - int(r["bid_price_1"]) if r["bid_price_1"] and r["ask_price_1"] else None)
           for r in rows if r["product"] == "HYDROGEL_PACK"]

# Spread distribution over time
s17_times = []
s7_times = []
for ts, mid, spread in hp_rows:
    if spread == 17:
        s17_times.append((ts, mid))
    if spread == 7:
        s7_times.append((ts, mid))

print(f"Spread=17 events: {len(s17_times)}")
for ts, mid in s17_times[:20]:
    print(f"  ts={ts:>6}: mid={mid:.1f}")
print(f"Spread=7 events: {len(s7_times)}")
for ts, mid in s7_times[:20]:
    print(f"  ts={ts:>6}: mid={mid:.1f}")

# HP mid over time (first/last 1000 ticks)
print("\nHP mid trajectory (every 100 ticks):")
for i in range(0, min(len(hp_rows), 10000), 100):
    ts, mid, spread = hp_rows[i]
    print(f"  ts={ts:>6}: mid={mid:.1f}, spread={spread}")

# Day 3 VFE analysis
print("\n" + "=" * 60)
print("DAY 3 VFE ANALYSIS")
print("=" * 60)
vfe_rows = [(int(r["timestamp"]), float(r["mid_price"]))
            for r in rows if r["product"] == "VELVETFRUIT_EXTRACT"]

print("VFE mid trajectory (every 200 ticks):")
for i in range(0, min(len(vfe_rows), 10000), 200):
    ts, mid = vfe_rows[i]
    print(f"  ts={ts:>6}: mid={mid:.1f}")

# Find the crash: when does VFE start dropping fast?
print("\nVFE returns (5-tick rolling sum, > 5 std):")
mids = [m for _, m in vfe_rows]
returns_5 = [sum(mids[i] - mids[i-1] for i in range(j, j+5)) for j in range(1, len(mids)-5)]
mean_r5 = sum(returns_5) / len(returns_5)
std_r5 = (sum((r - mean_r5)**2 for r in returns_5) / len(returns_5))**0.5
print(f"  5-tick return: mean={mean_r5:.3f}, std={std_r5:.3f}")
for j, r5 in enumerate(returns_5):
    if abs(r5 - mean_r5) > 3 * std_r5:
        ts = vfe_rows[j+1][0]
        mid = vfe_rows[j+1][1]
        print(f"  ts={ts:>6}: 5-tick return={r5:+.1f}, mid={mid:.1f}")

# Day 2 HP analysis for comparison
print("\n" + "=" * 60)
print("DAY 2 HP SPREAD=17 TIMING (for comparison)")
print("=" * 60)
rows2 = load_prices(2)
hp_rows2 = [(int(r["timestamp"]), float(r["mid_price"]),
             int(r["ask_price_1"]) - int(r["bid_price_1"]) if r["bid_price_1"] and r["ask_price_1"] else None)
            for r in rows2 if r["product"] == "HYDROGEL_PACK"]

s17_times2 = [(ts, mid) for ts, mid, spread in hp_rows2 if spread == 17]
s7_times2 = [(ts, mid) for ts, mid, spread in hp_rows2 if spread == 7]
print(f"Day 2 Spread=17 events: {len(s17_times2)}")
if s17_times2:
    print(f"  First: ts={s17_times2[0][0]}, mid={s17_times2[0][1]:.1f}")
    print(f"  Last:  ts={s17_times2[-1][0]}, mid={s17_times2[-1][1]:.1f}")
print(f"Day 2 Spread=7 events: {len(s7_times2)}")
if s7_times2:
    print(f"  First: ts={s7_times2[0][0]}, mid={s7_times2[0][1]:.1f}")
    print(f"  Last:  ts={s7_times2[-1][0]}, mid={s7_times2[-1][1]:.1f}")

# What happens around spread=17 on day 2
print("\nDay 2 S17 sequence (first event):")
for i, (ts, mid, spread) in enumerate(hp_rows2):
    if spread == 17 and mid > 10010:
        # Show context
        start = max(0, i - 5)
        end = min(len(hp_rows2), i + 50)
        for j in range(start, end):
            ts2, mid2, sp2 = hp_rows2[j]
            marker = " <<< S17" if j == i else ""
            marker2 = " <<< S7" if sp2 == 7 else ""
            print(f"  ts={ts2:>6}: mid={mid2:.1f}, spread={sp2}{marker}{marker2}")
        break
