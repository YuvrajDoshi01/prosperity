"""Probe per-product trade flow on R3 day 2 (1k ticks = ts 0..99900).

Key questions:
1. How much volume goes through each product per tick?
2. Distribution of trade prices vs mid (where do takers hit?)
3. Spread distribution per product (multi-level posting room)
4. L2 vs L1 volume ratio (estimate L2 attractiveness)
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
            ts = int(r["timestamp"])
            p = r["product"]
            def _f(k):
                v = r.get(k, "")
                return float(v) if v != "" else None
            rows[ts][p] = {
                "bp1": _f("bid_price_1"), "bv1": _f("bid_volume_1"),
                "bp2": _f("bid_price_2"), "bv2": _f("bid_volume_2"),
                "bp3": _f("bid_price_3"), "bv3": _f("bid_volume_3"),
                "ap1": _f("ask_price_1"), "av1": _f("ask_volume_1"),
                "ap2": _f("ask_price_2"), "av2": _f("ask_volume_2"),
                "ap3": _f("ask_price_3"), "av3": _f("ask_volume_3"),
                "mid": _f("mid_price"),
            }
    return rows

def load_trades(day):
    out = defaultdict(list)
    with open(ROOT / f"trades_round_3_day_{day}.csv") as f:
        rdr = csv.DictReader(f, delimiter=";")
        for r in rdr:
            ts = int(r["timestamp"])
            out[ts].append({
                "product": r["symbol"], "price": float(r["price"]),
                "qty": int(r["quantity"]),
            })
    return out

def main():
    day = 2
    prices = load_prices(day)
    trades = load_trades(day)
    timestamps = sorted(prices.keys())[:1000]  # 1k ticks = website parity

    # Per-product summary
    flow = defaultdict(lambda: {
        "trade_count": 0, "trade_qty": 0,
        "spread_sum": 0.0, "spread_count": 0,
        "L1_bid_v_sum": 0, "L2_bid_v_sum": 0, "L3_bid_v_sum": 0,
        "L1_ask_v_sum": 0, "L2_ask_v_sum": 0, "L3_ask_v_sum": 0,
        "L2_present": 0, "L3_present": 0,
        "trade_at_mid": 0, "trade_at_bid": 0, "trade_at_ask": 0, "trade_inside": 0, "trade_outside": 0,
        "spread_eq_2": 0, "spread_gt_2": 0, "spread_ge_4": 0, "ticks": 0,
    })

    for ts in timestamps:
        for p, row in prices[ts].items():
            f = flow[p]
            f["ticks"] += 1
            if row["bp1"] is not None and row["ap1"] is not None:
                spread = row["ap1"] - row["bp1"]
                f["spread_sum"] += spread
                f["spread_count"] += 1
                if spread == 2:
                    f["spread_eq_2"] += 1
                elif spread > 2:
                    f["spread_gt_2"] += 1
                if spread >= 4:
                    f["spread_ge_4"] += 1
                f["L1_bid_v_sum"] += int(row["bv1"] or 0)
                f["L1_ask_v_sum"] += int(row["av1"] or 0)
            if row["bp2"] is not None:
                f["L2_present"] += 1
                f["L2_bid_v_sum"] += int(row["bv2"] or 0)
            if row["ap2"] is not None:
                f["L2_ask_v_sum"] += int(row["av2"] or 0)
            if row["bp3"] is not None:
                f["L3_present"] += 1
                f["L3_bid_v_sum"] += int(row["bv3"] or 0)
            if row["ap3"] is not None:
                f["L3_ask_v_sum"] += int(row["av3"] or 0)

        for tr in trades.get(ts, []):
            p = tr["product"]
            if p not in prices[ts]:
                continue
            row = prices[ts][p]
            f = flow[p]
            f["trade_count"] += 1
            f["trade_qty"] += tr["qty"]
            tp = tr["price"]
            mid = row["mid"]
            bp = row["bp1"]; ap = row["ap1"]
            if mid is not None and tp == mid: f["trade_at_mid"] += 1
            elif bp is not None and tp == bp: f["trade_at_bid"] += 1
            elif ap is not None and tp == ap: f["trade_at_ask"] += 1
            elif bp is not None and ap is not None and bp < tp < ap: f["trade_inside"] += 1
            else: f["trade_outside"] += 1

    print(f"\n{'product':<28} {'ticks':>6} {'trades':>6} {'qty':>6} {'q/tk':>5} {'avSpr':>6} {'sp=2%':>6} {'sp>=4%':>6} {'L2%':>5} {'L3%':>5} {'avBV1':>6} {'avBV2':>6} {'avAV1':>6} {'avAV2':>6} {'@bid':>5} {'@ask':>5} {'@mid':>5} {'inside':>6}")
    for p in sorted(flow.keys()):
        f = flow[p]
        t = f["ticks"]; sc = f["spread_count"]
        print(f"{p:<28} {t:>6} {f['trade_count']:>6} {f['trade_qty']:>6} "
              f"{f['trade_qty']/t:>5.2f} "
              f"{(f['spread_sum']/sc if sc else 0):>6.2f} "
              f"{(100*f['spread_eq_2']/sc if sc else 0):>5.1f}% "
              f"{(100*f['spread_ge_4']/sc if sc else 0):>5.1f}% "
              f"{(100*f['L2_present']/t):>4.0f}% "
              f"{(100*f['L3_present']/t):>4.0f}% "
              f"{f['L1_bid_v_sum']/t:>6.1f} "
              f"{f['L2_bid_v_sum']/t:>6.1f} "
              f"{f['L1_ask_v_sum']/t:>6.1f} "
              f"{f['L2_ask_v_sum']/t:>6.1f} "
              f"{f['trade_at_bid']:>5} {f['trade_at_ask']:>5} {f['trade_at_mid']:>5} {f['trade_inside']:>5}")

if __name__ == "__main__":
    main()
