"""Probe: how much PnL is achievable from market_trade replay alone?

In default mode, market_trades CSV is replayed against our resting orders.
Buy market_trade at price P matches our SELL orders at price >= P (we get hit at OUR price).
The fill credits at OUR order price (line 92), not market trade price.

This means: posting a sell at best+1 (= ask−1, inside spread) when the CSV market_trade
was a buy at the OLD ask: we sell to that taker at our better price (best+1 instead of ask).
We capture (best+1 - bid) - (ask - best+1) = ... wait. Just compute exit edge per fill.

Strategy: for every market trade in CSV, simulate posting at best±1 and compute edge.
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
                v = r.get(k, ""); return float(v) if v != "" else None
            rows[ts][p] = {
                "bp1": _f("bid_price_1"), "ap1": _f("ask_price_1"),
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
    timestamps = sorted(prices.keys())[:1000]

    # For each market trade, determine direction (taker-buy vs taker-sell):
    # If trade price >= ask, it's a taker buy (someone lifted ask)
    # If trade price <= bid, it's a taker sell (someone hit bid)
    # In between → indeterminate (could be either)
    by_prod = defaultdict(lambda: {"buy_q": 0, "sell_q": 0, "buy_avg_p": [], "sell_avg_p": []})

    for ts in timestamps:
        for tr in trades.get(ts, []):
            p = tr["product"]
            if p not in prices.get(ts, {}): continue
            row = prices[ts][p]
            tp = tr["price"]; q = tr["qty"]
            bp = row["bp1"]; ap = row["ap1"]
            if ap is not None and tp >= ap:
                by_prod[p]["buy_q"] += q
                by_prod[p]["buy_avg_p"].append(tp)
            elif bp is not None and tp <= bp:
                by_prod[p]["sell_q"] += q
                by_prod[p]["sell_avg_p"].append(tp)

    print(f"\n{'product':<28} {'taker_buy_q':>12} {'taker_sell_q':>12} {'imbalance':>10}")
    for p in sorted(by_prod.keys()):
        d = by_prod[p]
        print(f"{p:<28} {d['buy_q']:>12} {d['sell_q']:>12} {d['buy_q']-d['sell_q']:>10}")

if __name__ == "__main__":
    main()
