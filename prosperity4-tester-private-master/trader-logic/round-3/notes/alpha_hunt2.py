"""Follow-up: confirm the key signal — out-of-the-money vouchers have one-sided
seller-only flow. This is FREE money for someone willing to lift the bid.
Plus underlying drift / VWAP analysis.
"""
import os
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester"
DATA_DIR = os.path.join(ROOT, "prosperity4bt", "resources", "round3")


def load_day(d):
    p = pd.read_csv(os.path.join(DATA_DIR, f"prices_round_3_day_{d}.csv"), sep=";")
    t = pd.read_csv(os.path.join(DATA_DIR, f"trades_round_3_day_{d}.csv"), sep=";")
    return p, t


def trade_price_vs_mid(prices, trades):
    """For each trade, was it ABOVE or BELOW current mid? -> direction inference."""
    print("\n=== Trade-price vs mid (signed direction) by product ===")
    mid = prices.set_index(["timestamp", "product"])["mid_price"].to_dict()
    bid = prices.set_index(["timestamp", "product"])["bid_price_1"].to_dict()
    ask = prices.set_index(["timestamp", "product"])["ask_price_1"].to_dict()

    rows = []
    for prod in trades["symbol"].unique():
        tdf = trades[trades["symbol"] == prod].copy()
        if tdf.empty:
            continue
        tdf["mid"] = tdf.apply(lambda r: mid.get((r.timestamp, prod), np.nan), axis=1)
        tdf["bid"] = tdf.apply(lambda r: bid.get((r.timestamp, prod), np.nan), axis=1)
        tdf["ask"] = tdf.apply(lambda r: ask.get((r.timestamp, prod), np.nan), axis=1)
        tdf = tdf.dropna(subset=["mid"])
        # CSV trade.price - if > best_ask ==> aggressive buyer (took ask)
        # if < best_bid ==> aggressive seller (took bid)
        # if between ==> hit mid (rare)
        n_above_ask = (tdf["price"] > tdf["ask"]).sum()
        n_at_ask = (tdf["price"] == tdf["ask"]).sum()
        n_below_bid = (tdf["price"] < tdf["bid"]).sum()
        n_at_bid = (tdf["price"] == tdf["bid"]).sum()
        n_inside = ((tdf["price"] > tdf["bid"]) & (tdf["price"] < tdf["ask"])).sum()
        rows.append({
            "product": prod,
            "n_trades": len(tdf),
            "n>ask": n_above_ask,
            "n=ask": n_at_ask,
            "n=bid": n_at_bid,
            "n<bid": n_below_bid,
            "n_inside": n_inside,
            "vol_at_ask": tdf.loc[tdf["price"] >= tdf["ask"], "quantity"].sum(),
            "vol_at_bid": tdf.loc[tdf["price"] <= tdf["bid"], "quantity"].sum(),
        })
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    return df


def underlying_drift(prices):
    """Does VELVETFRUIT_EXTRACT (or VEV_4000 as proxy) drift?"""
    print("\n=== Underlying drift / mid trajectory (open vs close mid) ===")
    rows = []
    for prod in prices["product"].unique():
        df = prices[prices["product"] == prod].sort_values("timestamp")
        if df.empty:
            continue
        m = df["mid_price"].values
        rows.append({
            "product": prod,
            "open_mid": m[0],
            "close_mid": m[-1],
            "drift": m[-1] - m[0],
            "min": m.min(),
            "max": m.max(),
            "stdev": m.std(),
        })
    print(pd.DataFrame(rows).to_string(index=False))


def deep_dive_otm(prices, trades):
    """Deep dive on OTM vouchers — bid is consistently 1 cheaper than ask?"""
    print("\n=== OTM voucher books (VEV_5400, 5500, 6000, 6500) ===")
    for prod in ["VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500"]:
        df = prices[prices["product"] == prod]
        if df.empty:
            continue
        print(f"\n{prod}:")
        print(f"  bid_price_1 stats: min={df.bid_price_1.min()}, max={df.bid_price_1.max()}, mean={df.bid_price_1.mean():.2f}")
        print(f"  ask_price_1 stats: min={df.ask_price_1.min()}, max={df.ask_price_1.max()}, mean={df.ask_price_1.mean():.2f}")
        print(f"  bid_volume_1 mean: {df.bid_volume_1.mean():.1f}, ask_volume_1 mean: {df.ask_volume_1.mean():.1f}")
        # what fraction of ticks have bid==1?
        if (df.bid_price_1 == 1).sum() > 0:
            print(f"  ticks with bid=1: {(df.bid_price_1==1).sum()}/{len(df)}")
        # if I lift bid (post bid=2 say) and seller-only takers slam every tick at 1 -> i fill
        # at avg cost = 1, then sell at... where? If voucher expires 0, I lose 1 each.
        # BUT if voucher has positive expected payoff, I make.
        td = trades[trades["symbol"] == prod]
        if not td.empty:
            print(f"  taker price mean: {td.price.mean():.2f}, qty sum: {td.quantity.sum()}")
            print(f"  taker prices unique: {sorted(td.price.unique())[:10]}")
    # Critical: what is the underlying expiry / final settlement?
    print("\n=== Final mid prices (proxies for settlement) on day 2 ===")
    last_ts = prices.timestamp.max()
    last = prices[prices.timestamp == last_ts][["product", "mid_price"]].sort_values("product")
    print(last.to_string(index=False))


def underlying_settle_check(prices):
    """If VELVETFRUIT_EXTRACT (the underlying) ends at 5247, then VEV_5500 voucher
    is OTM (max(0, 5247-5500)=0) and pays 0. Selling at 1 to flow = +1 each.
    Look at this!"""
    print("\n=== Voucher PAYOFF analysis (assuming underlying = VELVETFRUIT_EXTRACT) ===")
    und = prices[prices["product"] == "VELVETFRUIT_EXTRACT"]
    if und.empty:
        print("No underlying found")
        return
    final_und = und.sort_values("timestamp").iloc[-1]["mid_price"]
    final_und_max = und["mid_price"].max()
    final_und_min = und["mid_price"].min()
    print(f"VELVETFRUIT_EXTRACT day-end mid: {final_und}, range [{final_und_min}, {final_und_max}]")
    rows = []
    for prod in ["VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500"]:
        strike = int(prod.split("_")[1])
        v = prices[prices["product"] == prod]
        if v.empty:
            continue
        intrinsic_now = max(0, final_und - strike)
        v_now = v.sort_values("timestamp").iloc[-1]["mid_price"]
        v_avg = v["mid_price"].mean()
        rows.append({
            "voucher": prod,
            "strike": strike,
            "voucher_mid_avg": v_avg,
            "voucher_mid_final": v_now,
            "underlying_final": final_und,
            "intrinsic_at_close": intrinsic_now,
            "edge_if_short_voucher_at_avg": v_avg - intrinsic_now,
        })
    df = pd.DataFrame(rows)
    print(df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))


def main():
    print("=" * 80)
    print("FOLLOW-UP ANALYSIS")
    print("=" * 80)
    p, t = load_day(2)
    trade_price_vs_mid(p, t)
    underlying_drift(p)
    deep_dive_otm(p, t)
    underlying_settle_check(p)


if __name__ == "__main__":
    main()
