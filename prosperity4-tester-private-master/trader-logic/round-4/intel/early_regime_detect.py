"""
Early regime detection for R4 days 1/2/3.

Goal: by tick 50/100/200, distinguish day-3 (catastrophe) from day-1/day-2.

Features per (day, cutoff_tick):
  HP_drift, HP_vol, HP_spread_mode, HP_spread_mean,
  VFE_drift, VFE_vol, VFE_spread_mean,
  voucher_trade_count, mark_trade_count,
  HP_OBI_mean, VFE_OBI_mean, HP_micro_drift, VFE_micro_drift.
"""

import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4")
DAYS = [1, 2, 3]
CUTOFFS = [25, 50, 100, 200]
TS_STEP = 100  # cutoff_tick * TS_STEP = max ts


def load_prices(day):
    rows = []
    with open(ROOT / f"prices_round_4_day_{day}.csv", "r") as f:
        rd = csv.DictReader(f, delimiter=";")
        for r in rd:
            rows.append(r)
    return rows


def load_trades(day):
    rows = []
    with open(ROOT / f"trades_round_4_day_{day}.csv", "r") as f:
        rd = csv.DictReader(f, delimiter=";")
        for r in rd:
            rows.append(r)
    return rows


def feat_for(day, cutoff):
    """Compute features over first `cutoff` ticks (ts < cutoff*TS_STEP)."""
    max_ts = cutoff * TS_STEP
    prices = load_prices(day)
    trades = load_trades(day)

    by_prod = defaultdict(list)
    for r in prices:
        ts = int(r["timestamp"])
        if ts >= max_ts:
            continue
        by_prod[r["product"]].append(r)

    def stats(prod):
        rows = by_prod.get(prod, [])
        mids, spreads, obis, micros = [], [], [], []
        for r in rows:
            try:
                bp1 = float(r["bid_price_1"]) if r["bid_price_1"] else None
                ap1 = float(r["ask_price_1"]) if r["ask_price_1"] else None
                bv1 = float(r["bid_volume_1"]) if r["bid_volume_1"] else 0.0
                av1 = float(r["ask_volume_1"]) if r["ask_volume_1"] else 0.0
                mid = float(r["mid_price"]) if r["mid_price"] else None
            except ValueError:
                continue
            if mid is not None:
                mids.append(mid)
            if bp1 is not None and ap1 is not None:
                spreads.append(ap1 - bp1)
                vt = bv1 + av1
                if vt > 0:
                    obis.append((bv1 - av1) / vt)
                    micro = (bp1 * av1 + ap1 * bv1) / vt
                    micros.append(micro)
        if not mids:
            return None
        drift = mids[-1] - mids[0]
        vol = statistics.pstdev(mids) if len(mids) > 1 else 0.0
        sp_mean = statistics.mean(spreads) if spreads else 0.0
        sp_mode = Counter([int(round(s)) for s in spreads]).most_common(1)[0][0] if spreads else 0
        obi_mean = statistics.mean(obis) if obis else 0.0
        micro_drift = micros[-1] - micros[0] if len(micros) >= 2 else 0.0
        return dict(drift=drift, vol=vol, sp_mean=sp_mean, sp_mode=sp_mode,
                    obi=obi_mean, micro_drift=micro_drift, n=len(mids))

    hp = stats("HYDROGEL_PACK")
    vfe = stats("VELVETFRUIT_EXTRACT")
    voucher_n = sum(1 for p, rs in by_prod.items() if p.startswith("VEV_") for _ in rs)
    mark_n = sum(1 for t in trades if int(t["timestamp"]) < max_ts and t.get("buyer", "").startswith("Mark"))
    voucher_trades = sum(1 for t in trades if int(t["timestamp"]) < max_ts and t["symbol"].startswith("VEV_"))

    return {
        "day": day, "cutoff": cutoff,
        "HP_drift": hp["drift"] if hp else 0.0,
        "HP_vol": hp["vol"] if hp else 0.0,
        "HP_sp_mode": hp["sp_mode"] if hp else 0,
        "HP_sp_mean": round(hp["sp_mean"], 2) if hp else 0.0,
        "HP_OBI": round(hp["obi"], 3) if hp else 0.0,
        "HP_micro_drift": round(hp["micro_drift"], 2) if hp else 0.0,
        "VFE_drift": vfe["drift"] if vfe else 0.0,
        "VFE_vol": round(vfe["vol"], 2) if vfe else 0.0,
        "VFE_sp_mean": round(vfe["sp_mean"], 2) if vfe else 0.0,
        "VFE_OBI": round(vfe["obi"], 3) if vfe else 0.0,
        "VFE_micro_drift": round(vfe["micro_drift"], 2) if vfe else 0.0,
        "voucher_book_rows": voucher_n,
        "voucher_trades": voucher_trades,
        "mark_trades": mark_n,
    }


def main():
    rows = []
    for d in DAYS:
        for c in CUTOFFS:
            rows.append(feat_for(d, c))

    keys = list(rows[0].keys())
    print(",".join(keys))
    for r in rows:
        print(",".join(str(r[k]) for k in keys))

    # Discriminant: VFE_drift threshold by cutoff
    print("\n--- Discriminant analysis: VFE_drift by day ---")
    for c in CUTOFFS:
        d_vals = {r["day"]: r["VFE_drift"] for r in rows if r["cutoff"] == c}
        d3_minus_max12 = d_vals[3] - max(d_vals[1], d_vals[2])
        print(f"cutoff={c:3d}  d1={d_vals[1]:+7.2f}  d2={d_vals[2]:+7.2f}  d3={d_vals[3]:+7.2f}  "
              f"gap(d3-max(d1,d2))={d3_minus_max12:+7.2f}")

    print("\n--- HP_micro_drift by day ---")
    for c in CUTOFFS:
        d_vals = {r["day"]: r["HP_micro_drift"] for r in rows if r["cutoff"] == c}
        print(f"cutoff={c:3d}  d1={d_vals[1]:+7.2f}  d2={d_vals[2]:+7.2f}  d3={d_vals[3]:+7.2f}")

    print("\n--- HP_vol by day ---")
    for c in CUTOFFS:
        d_vals = {r["day"]: r["HP_vol"] for r in rows if r["cutoff"] == c}
        print(f"cutoff={c:3d}  d1={d_vals[1]:.2f}  d2={d_vals[2]:.2f}  d3={d_vals[3]:.2f}")

    # LOO threshold rule on VFE_drift @ cutoff=50
    print("\n--- LOO threshold rule: VFE_drift @ cutoff=50 ---")
    for c in (25, 50, 100):
        rows_c = [r for r in rows if r["cutoff"] == c]
        for held_out in DAYS:
            train = [r for r in rows_c if r["day"] != held_out]
            test = [r for r in rows_c if r["day"] == held_out][0]
            # Day 3 = "catastrophe" (label=1). Threshold = midpoint between
            # min(d3 in train) and max(non-d3 in train) — but only d1,d2 are non-d3.
            # Fallback: use VFE_drift < -2 as catastrophe predictor.
            pred = "catastrophe" if test["VFE_drift"] < -2 else "normal"
            actual = "catastrophe" if held_out == 3 else "normal"
            print(f"cutoff={c:3d} hold_out=d{held_out}  VFE_drift={test['VFE_drift']:+7.2f}  "
                  f"pred={pred:11s} actual={actual:11s}  {'OK' if pred==actual else 'MISS'}")


if __name__ == "__main__":
    main()
