"""Day-0 EDA for R3 delta-1 products — classify archetype."""
import csv
from pathlib import Path
from collections import defaultdict

CSV = Path(__file__).parents[3] / "prosperity4bt" / "resources" / "round3" / "prices_round_3_day_0.csv"

by_prod = defaultdict(list)  # product -> list of (ts, mid, bid1, ask1, bv1, av1)
with open(CSV) as f:
    r = csv.DictReader(f, delimiter=";")
    for row in r:
        if not row["mid_price"]: continue
        try:
            mid = float(row["mid_price"])
        except ValueError:
            continue
        bid1 = float(row["bid_price_1"] or 0)
        ask1 = float(row["ask_price_1"] or 0)
        bv1 = float(row["bid_volume_1"] or 0)
        av1 = float(row["ask_volume_1"] or 0)
        by_prod[row["product"]].append((int(row["timestamp"]), mid, bid1, ask1, bv1, av1))


def autocorr1(xs):
    n = len(xs)
    if n < 3: return 0.0
    mu = sum(xs) / n
    num = sum((xs[i] - mu) * (xs[i + 1] - mu) for i in range(n - 1))
    den = sum((x - mu) ** 2 for x in xs)
    return num / den if den else 0.0


def summarize(name):
    data = sorted(by_prod[name])
    mids = [d[1] for d in data]
    bids = [d[2] for d in data]
    asks = [d[3] for d in data]
    bvs = [d[4] for d in data]
    avs = [d[5] for d in data]
    n = len(mids)
    mu = sum(mids) / n
    std = (sum((x - mu) ** 2 for x in mids) / n) ** 0.5
    rets = [mids[i + 1] - mids[i] for i in range(n - 1)]
    ar1_rets = autocorr1(rets)
    ar1_mids = autocorr1(mids)
    spreads = [a - b for b, a in zip(bids, asks) if a > b]
    avg_spread = sum(spreads) / len(spreads) if spreads else 0
    avg_bv = sum(bvs) / n
    avg_av = sum(avs) / n
    one_sided = sum(1 for b, a in zip(bids, asks) if b == 0 or a == 0)
    print(f"\n{name}:")
    print(f"  n={n}  mean={mu:.2f}  std={std:.2f}  range=[{min(mids):.2f}, {max(mids):.2f}]")
    print(f"  AR1(returns)={ar1_rets:.3f}  AR1(mids)={ar1_mids:.3f}")
    print(f"  avg_spread={avg_spread:.2f}  avg_bv={avg_bv:.1f}  avg_av={avg_av:.1f}")
    print(f"  one_sided_ticks={one_sided} ({100*one_sided/n:.1f}%)")
    if abs(ar1_rets) > 0.3:
        print(f"  -> CLASSIFY: mean-reverting (OU / stable)")
    elif abs(ar1_rets) < 0.15:
        print(f"  -> CLASSIFY: random walk")
    else:
        print(f"  -> CLASSIFY: mild mean-reversion")


for p in ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"]:
    if p in by_prod:
        summarize(p)

# Also VELVETFRUIT_EXTRACT spread stats across all 3 days
print("\nVELVETFRUIT_EXTRACT daily range (mid) across 3 days:")
for d in range(3):
    csvd = Path(__file__).parents[3] / "prosperity4bt" / "resources" / "round3" / f"prices_round_3_day_{d}.csv"
    mids = []
    with open(csvd) as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            if row["product"] == "VELVETFRUIT_EXTRACT" and row["mid_price"]:
                try: mids.append(float(row["mid_price"]))
                except ValueError: continue
    if mids:
        print(f"  Day {d}: mean={sum(mids)/len(mids):.2f}  range=[{min(mids):.2f}, {max(mids):.2f}]  n={len(mids)}")
