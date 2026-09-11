"""day4_prediction.py — Feature distribution + day-4 prediction for r4_final_v2.

Extracts per-day features for HP, VFE, vouchers; clusters days 1/2/3; estimates
day-4 mixture distribution; simulates worst-case scenarios.
"""
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

DATA = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4")
P3   = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/previous-prosperity/p3_r3")


def load_prices(path):
    rows = defaultdict(list)  # product -> list of (timestamp, mid, bb, ba, bv1, av1)
    with open(path, newline="") as f:
        rdr = csv.DictReader(f, delimiter=";")
        for r in rdr:
            try:
                ts = int(r["timestamp"]); mid = float(r["mid_price"])
                bb = r.get("bid_price_1") or ""; ba = r.get("ask_price_1") or ""
                bb = float(bb) if bb else None; ba = float(ba) if ba else None
                bv = float(r.get("bid_volume_1") or 0); av = float(r.get("ask_volume_1") or 0)
                rows[r["product"]].append((ts, mid, bb, ba, bv, av))
            except Exception:
                continue
    for k in rows: rows[k].sort()
    return rows


def feats(rows, product):
    arr = rows.get(product, [])
    if len(arr) < 50: return None
    mids = [r[1] for r in arr]
    spreads = [(r[3] - r[2]) for r in arr if r[2] and r[3]]
    rng = max(mids) - min(mids)
    drift = mids[-1] - mids[0]
    diffs = [mids[i] - mids[i-1] for i in range(1, len(mids))]
    vol = statistics.stdev(diffs) if len(diffs) > 1 else 0
    mean_spread = statistics.mean(spreads) if spreads else 0
    spread_dist = {}
    for s in spreads:
        spread_dist[int(s)] = spread_dist.get(int(s), 0) + 1
    n = len(spreads)
    pct_s17 = spread_dist.get(17, 0) / n if n else 0
    pct_s7  = spread_dist.get(7, 0) / n if n else 0
    return {
        "n": len(arr),
        "mid_first": mids[0],
        "mid_last": mids[-1],
        "mid_min": min(mids),
        "mid_max": max(mids),
        "range": rng,
        "drift": drift,
        "tick_vol": vol,
        "mean_spread": mean_spread,
        "pct_s17": pct_s17,
        "pct_s7": pct_s7,
    }


def cluster(per_day_features, key):
    # Simple z-score distance between days
    days = sorted(per_day_features.keys())
    vec = {d: per_day_features[d][key] for d in days if per_day_features[d]}
    return vec


def main():
    out = []
    out.append("# Day-4 Prediction\n")
    out.append("Days 1/2/3 are samples from a distribution; day 4 is unseen but 'same characteristics'.\n\n")

    per_day = {}
    for d in [1, 2, 3]:
        rows = load_prices(DATA / f"prices_round_4_day_{d}.csv")
        per_day[d] = {
            "HP":  feats(rows, "HYDROGEL_PACK"),
            "VFE": feats(rows, "VELVETFRUIT_EXTRACT"),
        }

    out.append("## 1. Per-day feature table (HP / VFE)\n\n")
    out.append("| Day | Product | range | drift | tick_vol | mean_spr | %s17 | %s7 |\n")
    out.append("|-----|---------|------:|------:|---------:|---------:|-----:|----:|\n")
    for d in [1, 2, 3]:
        for prod in ["HP", "VFE"]:
            f = per_day[d][prod]
            if f is None: continue
            out.append(f"| {d} | {prod} | {f['range']:.0f} | {f['drift']:+.0f} | "
                       f"{f['tick_vol']:.2f} | {f['mean_spread']:.1f} | "
                       f"{f['pct_s17']:.3f} | {f['pct_s7']:.3f} |\n")
    out.append("\n")

    # Quick characterization
    out.append("## 2. Day archetype\n\n")
    archetypes = {}
    for d in [1, 2, 3]:
        hp = per_day[d]["HP"]; vfe = per_day[d]["VFE"]
        if not hp or not vfe: continue
        is_hp_cycle = hp["pct_s17"] > 0.005 and hp["range"] > 30
        is_vfe_crash = vfe["drift"] < -10 or (vfe["mid_last"] / vfe["mid_first"] - 1) < -0.005
        archetypes[d] = ("HP_CYCLE" if is_hp_cycle else "HP_FLAT",
                         "VFE_CRASH" if is_vfe_crash else "VFE_STABLE")
        out.append(f"- Day {d}: HP={archetypes[d][0]}, VFE={archetypes[d][1]}, "
                   f"VFE_drift={vfe['drift']:+.0f}, VFE_chg={(vfe['mid_last']/vfe['mid_first']-1)*100:+.2f}%\n")

    # Day-4 prediction (mixture)
    out.append("\n## 3. Day-4 prediction (mixture of empirical samples)\n\n")
    out.append("With 3 i.i.d. samples we have NO power to forecast a 4th draw. "
               "Empirical Bayesian: each archetype gets prior 1/3, plus uniform tail mass for "
               "out-of-sample regimes (R3 had 3 days too; day-3 was noticeably different).\n\n")
    out.append("**Prior (recommended):**\n")
    out.append("- 33% day-1-style (HP cycle, VFE stable, S17 fires cleanly)\n")
    out.append("- 33% day-2-style (HP cycle stronger, VFE stable)\n")
    out.append("- 25% day-3-style (HP flat or weak cycle, VFE crash)\n")
    out.append("- 9% MORE EXTREME than any seen day (heavier tail)\n\n")

    # Compare R3 vs R4 to test the 'same distribution' assumption
    out.append("## 4. R3 vs R4 distribution check\n\n")
    out.append("Checking whether IMC reuses similar dynamics across rounds.\n\n")
    p3_per_day = {}
    for d in [0, 1, 2]:
        try:
            rows = load_prices(P3 / f"prices_round_3_day_{d}.csv")
            p3_per_day[d] = feats(rows, "VOLCANIC_ROCK") or feats(rows, "VOLCANIC_ROCK_VOUCHER_10000")
        except Exception:
            p3_per_day[d] = None

    return "".join(out)


if __name__ == "__main__":
    md = main()
    out_path = Path(__file__).parent / "day4_prediction.md"
    print(md)
