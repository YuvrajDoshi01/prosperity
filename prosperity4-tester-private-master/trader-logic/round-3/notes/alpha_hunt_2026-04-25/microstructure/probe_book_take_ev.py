"""For each tick, simulate taking out L1 at fair value (mid) edge.

If next-tick mid > current ask: taking L1 (and maybe L2) is +EV.
Compute per-product expected take EV.
"""
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3")

def load_prices(day):
    rows = defaultdict(dict)
    with open(ROOT / f"prices_round_3_day_{day}.csv") as f:
        rdr = csv.DictReader(f, delimiter=";")
        for r in rdr:
            ts = int(r["timestamp"]); p = r["product"]
            def _f(k):
                v = r.get(k, ""); return float(v) if v != "" else None
            rows[ts][p] = {
                "bp1": _f("bid_price_1"), "bv1": _f("bid_volume_1"),
                "bp2": _f("bid_price_2"), "bv2": _f("bid_volume_2"),
                "ap1": _f("ask_price_1"), "av1": _f("ask_volume_1"),
                "ap2": _f("ask_price_2"), "av2": _f("ask_volume_2"),
                "mid": _f("mid_price"),
            }
    return rows

def main():
    day = 2
    prices = load_prices(day)
    timestamps = sorted(prices.keys())[:1000]

    # For each product and each tick, compute:
    # take L1 ask at price ap1 (vol av1), then mid moves to mid[t+H]. Edge = mid[t+H] - ap1
    # Average edge per unit per take, by horizon H ∈ {1, 5, 10}
    H_LIST = [1, 5, 10, 50, 100]

    ev = defaultdict(lambda: defaultdict(lambda: {"trade_n": 0, "ev_l1_buy": 0.0, "ev_l1_sell": 0.0, "vol_l1_buy": 0, "vol_l1_sell": 0}))

    for i, ts in enumerate(timestamps):
        for p, row in prices[ts].items():
            if row["ap1"] is None or row["bp1"] is None: continue
            for H in H_LIST:
                if i + H >= len(timestamps): continue
                future = prices[timestamps[i+H]].get(p)
                if not future or future["mid"] is None: continue
                fmid = future["mid"]
                # Buy L1 ask: edge = fmid - ap1 per unit
                ev[p][H]["ev_l1_buy"] += (fmid - row["ap1"]) * row["av1"]
                ev[p][H]["vol_l1_buy"] += row["av1"]
                ev[p][H]["ev_l1_sell"] += (row["bp1"] - fmid) * row["bv1"]
                ev[p][H]["vol_l1_sell"] += row["bv1"]
                ev[p][H]["trade_n"] += 1

    print(f"\n{'product':<28} {'H':>3} {'EV_buy_L1/u':>12} {'EV_sell_L1/u':>12} {'totBuyVol':>10} {'totSellVol':>10}")
    for p in sorted(ev.keys()):
        for H in H_LIST:
            d = ev[p][H]
            if d["vol_l1_buy"] == 0: continue
            print(f"{p:<28} {H:>3} {d['ev_l1_buy']/d['vol_l1_buy']:>12.3f} "
                  f"{d['ev_l1_sell']/d['vol_l1_sell']:>12.3f} "
                  f"{d['vol_l1_buy']:>10} {d['vol_l1_sell']:>10}")

if __name__ == "__main__":
    main()
