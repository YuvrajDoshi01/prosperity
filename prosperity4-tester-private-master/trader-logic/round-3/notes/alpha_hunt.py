"""Alpha hunt: reverse-engineer ~$80/tick mechanism for Round 3 top traders.

Answers Q1-Q8 with code+data. Uses day 2 as test window (1k ticks, 0..99,900 step 100).
"""
import os
import sys
import pandas as pd
import numpy as np
from collections import defaultdict

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester"
DATA_DIR = os.path.join(ROOT, "prosperity4bt", "resources", "round3")

LIMITS = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300, "VEV_5100": 300,
    "VEV_5200": 300, "VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300,
    "VEV_6000": 300, "VEV_6500": 300,
}

PRODUCTS = list(LIMITS.keys())


def load_day(day):
    p = pd.read_csv(os.path.join(DATA_DIR, f"prices_round_3_day_{day}.csv"), sep=";")
    t = pd.read_csv(os.path.join(DATA_DIR, f"trades_round_3_day_{day}.csv"), sep=";")
    return p, t


def best_bid_ask(row):
    return row.bid_price_1, row.ask_price_1, row.bid_volume_1, row.ask_volume_1


def q1_theoretical_max(prices_df, day):
    """Q1: 100% inside-spread MM capture, per product, full 1k ticks."""
    print("\n=== Q1: Theoretical maximum if we capture 100% inside-spread MM each tick ===")
    print(f"(Day {day}, 1000 ticks)")
    rows = []
    total = 0.0
    for prod in PRODUCTS:
        df = prices_df[prices_df["product"] == prod].copy()
        if df.empty:
            continue
        # spread captured per round trip if posting at best+1 (penny)
        # = (ask - bid) - 2  (we lose 1 tick on each side because we penny inside)
        spreads = df["ask_price_1"] - df["bid_price_1"]
        edge = (spreads - 2).clip(lower=0)
        # max fillable per tick limited by smaller of (bid_volume_1, ask_volume_1) and pos room
        bv = df["bid_volume_1"].fillna(0)
        av = df["ask_volume_1"].fillna(0)
        # round-trip = min(bv, av), but capped by limit (we cycle 0->+L->0 if needed)
        rt_vol = pd.concat([bv, av], axis=1).min(axis=1)
        # also capped by limit: per tick we can flip from -L to +L = 2L size, but realistic 1 round trip = L
        rt_vol = rt_vol.clip(upper=LIMITS[prod])
        # avg edge per tick
        per_tick = edge * rt_vol
        prod_pnl = per_tick.sum()
        rows.append({
            "product": prod,
            "ticks": len(df),
            "mean_spread": float(spreads.mean()),
            "mean_edge": float(edge.mean()),
            "mean_rt_vol": float(rt_vol.mean()),
            "max_pnl": float(prod_pnl),
        })
        total += prod_pnl
    df = pd.DataFrame(rows).sort_values("max_pnl", ascending=False)
    print(df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\nTOTAL THEORETICAL MAX (day {day}): {total:,.0f}")
    return total, df


def q2_multilevel(prices_df, trades_df):
    """Q2: Multi-level posting vs single-level. Estimate gain from 30%->50% taker capture."""
    print("\n=== Q2: Multi-level posting impact estimate ===")
    rows = []
    for prod in PRODUCTS:
        pdf = prices_df[prices_df["product"] == prod]
        tdf = trades_df[trades_df["symbol"] == prod]
        if pdf.empty or tdf.empty:
            continue
        n_takers = len(tdf)
        avg_qty = float(tdf["quantity"].mean()) if n_takers else 0
        spread = float((pdf["ask_price_1"] - pdf["bid_price_1"]).mean())
        edge_single = max(spread - 2, 0)
        # single: capture 30% of taker flow at edge_single
        single = 0.30 * n_takers * avg_qty * edge_single
        # multi: capture 50% but at average edge ~spread/2 (deeper levels = wider edge but
        # only filled when taker walks book; assume blended edge = (spread-2 + spread + spread+2)/3 = spread)
        multi_edge = spread
        multi = 0.50 * n_takers * avg_qty * multi_edge
        rows.append({
            "product": prod,
            "n_takers": n_takers,
            "avg_qty": avg_qty,
            "single_pnl": single,
            "multi_pnl": multi,
            "gain": multi - single,
        })
    df = pd.DataFrame(rows).sort_values("gain", ascending=False)
    print(df.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
    print(f"\nTotal projected gain from multi-level: {df['gain'].sum():,.0f}")
    return df


def q3_flow_imbalance(prices_df, trades_df):
    """Q3: order flow imbalance: buyer vs seller initiated, time clustering."""
    print("\n=== Q3: Order flow imbalance / clustering ===")
    # We don't have buyer/seller labels reliably (often blank). Infer from price vs mid.
    # buyer-initiated if trade.price >= mid; seller-init if < mid.
    mid_lookup = prices_df.set_index(["timestamp", "product"])["mid_price"].to_dict()
    rows = []
    for prod in PRODUCTS:
        tdf = trades_df[trades_df["symbol"] == prod].copy()
        if tdf.empty:
            continue
        tdf["mid"] = tdf.apply(lambda r: mid_lookup.get((r["timestamp"], prod), np.nan), axis=1)
        tdf = tdf.dropna(subset=["mid"])
        tdf["signed"] = np.where(tdf["price"] >= tdf["mid"], tdf["quantity"], -tdf["quantity"])
        buy_vol = tdf.loc[tdf["signed"] > 0, "quantity"].sum()
        sell_vol = tdf.loc[tdf["signed"] < 0, "quantity"].sum()
        # time clustering: variance of inter-arrival times
        if len(tdf) > 1:
            ia = np.diff(np.sort(tdf["timestamp"].values))
            cov = ia.std() / max(ia.mean(), 1e-9)  # CoV; >1 = bursty, <1 = regular
        else:
            cov = np.nan
        # autocorrelation of signed flow per tick
        per_tick = tdf.groupby("timestamp")["signed"].sum()
        if len(per_tick) > 5:
            ac1 = per_tick.autocorr(lag=1)
        else:
            ac1 = np.nan
        rows.append({
            "product": prod,
            "n_trades": len(tdf),
            "buy_vol": int(buy_vol),
            "sell_vol": int(sell_vol),
            "imbalance": (buy_vol - sell_vol) / max(buy_vol + sell_vol, 1),
            "interarrival_cov": cov,
            "signed_ac1": ac1,
        })
    df = pd.DataFrame(rows)
    print(df.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    return df


def q4_quote_prediction(prices_df):
    """Q4: predict mid_{t+1} from past mids. Test for HYDROGEL, VELVETFRUIT."""
    print("\n=== Q4: Quote prediction R^2 (mid_{t+1} ~ mid_t, mid_{t-1}, mid_{t-2}) ===")
    rows = []
    for prod in PRODUCTS:
        df = prices_df[prices_df["product"] == prod].sort_values("timestamp")
        if len(df) < 100:
            continue
        m = df["mid_price"].values
        if len(m) < 10:
            continue
        # build matrix
        n = len(m) - 3
        X = np.column_stack([m[2:-1], m[1:-2], m[:-3]])  # mid_t, t-1, t-2
        y = m[3:]
        # OLS
        Xc = np.column_stack([np.ones(n), X])
        try:
            beta, *_ = np.linalg.lstsq(Xc, y, rcond=None)
            yhat = Xc @ beta
            ss_res = ((y - yhat) ** 2).sum()
            ss_tot = ((y - y.mean()) ** 2).sum()
            r2 = 1 - ss_res / max(ss_tot, 1e-9)
            # also: predict next-tick CHANGE
            dy = np.diff(m)
            ddx = np.column_stack([dy[1:-1], dy[:-2]])
            ddy = dy[2:]
            Xc2 = np.column_stack([np.ones(len(ddy)), ddx])
            b2, *_ = np.linalg.lstsq(Xc2, ddy, rcond=None)
            yh2 = Xc2 @ b2
            r2_chg = 1 - ((ddy - yh2) ** 2).sum() / max(((ddy - ddy.mean()) ** 2).sum(), 1e-9)
        except Exception:
            r2 = r2_chg = np.nan
        rows.append({
            "product": prod,
            "r2_level": r2,
            "r2_change": r2_chg,
            "ar1_coef": float(np.corrcoef(m[:-1], m[1:])[0, 1]) if len(m) > 2 else np.nan,
        })
    df = pd.DataFrame(rows).sort_values("r2_change", ascending=False)
    print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    return df


def q5_cross_product_hedge(prices_df):
    """Q5: deep-ITM voucher + short underlying = delta-neutral; estimate carry."""
    print("\n=== Q5: Cross-product hedge / theta carry analysis ===")
    # Underlying = VEV (the pure VEV, no strike)? Likely encoded as VELVETFRUIT_EXTRACT (price ~5247).
    # Vouchers VEV_4000 (deep ITM, price ~1247 = 5247-4000) confirms underlying = VELVETFRUIT_EXTRACT.
    und = prices_df[prices_df["product"] == "VELVETFRUIT_EXTRACT"].set_index("timestamp")["mid_price"]
    rows = []
    for v in ["VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]:
        vd = prices_df[prices_df["product"] == v].set_index("timestamp")["mid_price"]
        joined = pd.concat([und.rename("u"), vd.rename("v")], axis=1).dropna()
        if len(joined) < 50:
            continue
        # empirical delta: regress dV on dU
        du = joined["u"].diff().dropna()
        dv = joined["v"].diff().dropna()
        if len(du) < 10 or du.std() < 1e-9:
            continue
        delta = float(np.cov(du, dv)[0, 1] / np.var(du))
        # theta = mean change in voucher price (drift toward expiry)
        theta_per_tick = float(dv.mean())
        # delta-neutral: hold +N voucher, -delta*N underlying
        # PnL/tick from theta (ignoring vol gamma): N * theta
        # but also pays gamma * 0.5 * du^2; let's just report theta and delta
        N = LIMITS[v]
        carry_per_tick = N * theta_per_tick  # if long voucher, theta>0=gain
        rows.append({
            "voucher": v,
            "mean_voucher_mid": float(joined["v"].mean()),
            "mean_underlying_mid": float(joined["u"].mean()),
            "intrinsic_check": float(joined["v"].mean()) - max(float(joined["u"].mean()) - int(v.split("_")[1]), 0),
            "empirical_delta": delta,
            "theta_per_tick": theta_per_tick,
            "carry_per_tick_full_size": carry_per_tick,
            "carry_per_1k_ticks": carry_per_tick * 1000,
        })
    df = pd.DataFrame(rows)
    print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    return df


def q6_timing(prices_df, trades_df):
    """Q6: timestamp ranges where opportunity is concentrated."""
    print("\n=== Q6: Timing analysis -- when is alpha concentrated? ===")
    # bucket by 100-tick windows = 10k ts
    trades_df = trades_df.copy()
    trades_df["bucket"] = (trades_df["timestamp"] // 10000) * 10000
    bucket_taker = trades_df.groupby("bucket")["quantity"].agg(["count", "sum"])
    print("Taker activity by 10k-ts bucket (top 10):")
    print(bucket_taker.sort_values("count", ascending=False).head(10).to_string())
    # one-sided book ticks
    one_sided = []
    for prod in PRODUCTS:
        df = prices_df[prices_df["product"] == prod]
        oss = df[(df["bid_price_1"].isna()) | (df["ask_price_1"].isna())]
        if len(oss) > 0:
            one_sided.append({"product": prod, "n_one_sided": len(oss), "frac": len(oss) / max(len(df), 1)})
    if one_sided:
        print("\nOne-sided book ticks per product:")
        print(pd.DataFrame(one_sided).to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    # spread widening events
    print("\nSpread widening (HYDROGEL_PACK, top 10 wide ticks):")
    h = prices_df[prices_df["product"] == "HYDROGEL_PACK"].copy()
    h["spread"] = h["ask_price_1"] - h["bid_price_1"]
    print(h.nlargest(10, "spread")[["timestamp", "bid_price_1", "ask_price_1", "spread", "mid_price"]].to_string(index=False))
    return bucket_taker


def q7_hydrogel_ceiling(prices_df, trades_df):
    """Q7: HYDROGEL_PACK alone -- max MM ceiling."""
    print("\n=== Q7: HYDROGEL_PACK theoretical MM ceiling ===")
    h = prices_df[prices_df["product"] == "HYDROGEL_PACK"].copy()
    th = trades_df[trades_df["symbol"] == "HYDROGEL_PACK"]
    h["spread"] = h["ask_price_1"] - h["bid_price_1"]
    h["best_vol"] = h[["bid_volume_1", "ask_volume_1"]].min(axis=1)
    print(f"Mean spread: {h['spread'].mean():.2f}")
    print(f"Mean best vol (min(bid,ask)): {h['best_vol'].mean():.2f}")
    print(f"Number of takers: {len(th)}")
    print(f"Mean taker qty: {th['quantity'].mean() if len(th) else 0:.2f}")
    print(f"Total taker volume: {th['quantity'].sum() if len(th) else 0}")
    # Theoretical MM PnL = takers_per_tick × edge × avg_qty
    # If we capture every taker at edge=(spread-2)/2 (we get half the spread minus 1):
    edge_per_capture = (h["spread"].mean() - 2)
    half_edge = edge_per_capture / 2
    total_taker_vol = th["quantity"].sum()
    upper = total_taker_vol * edge_per_capture
    realistic = total_taker_vol * half_edge * 0.5  # capture 50% of taker flow at half-spread
    print(f"\nUpper bound (100% capture, full edge): {upper:,.0f}")
    print(f"Realistic (50% capture, half-edge): {realistic:,.0f}")
    # Also: spread × pos_limit per round-trip × 1000 ticks
    print(f"\nPer-tick MM upper if we round-trip 200 contracts: {200 * (h['spread'].mean()-2):,.0f}")
    print(f"× 1000 ticks: {200 * (h['spread'].mean()-2) * 1000:,.0f}")


def q8_fill_rate(prices_df, trades_df):
    """Q8: empirical fill-rate analysis. Per product: (taker_volume) / (best_bid_vol + best_ask_vol)."""
    print("\n=== Q8: Empirical fill-rate analysis ===")
    rows = []
    for prod in PRODUCTS:
        pdf = prices_df[prices_df["product"] == prod]
        tdf = trades_df[trades_df["symbol"] == prod]
        if pdf.empty:
            continue
        avail = (pdf["bid_volume_1"].fillna(0).sum() + pdf["ask_volume_1"].fillna(0).sum())
        taker_vol = tdf["quantity"].sum() if len(tdf) else 0
        rows.append({
            "product": prod,
            "avail_book_vol": int(avail),
            "taker_vol": int(taker_vol),
            "fill_pressure": taker_vol / max(avail, 1),  # what fraction of book is consumed by takers
            "n_takers": len(tdf),
            "ticks": len(pdf),
            "takers_per_tick": len(tdf) / max(len(pdf), 1),
        })
    df = pd.DataFrame(rows).sort_values("fill_pressure", ascending=False)
    print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    return df


def main():
    print("=" * 80)
    print("ALPHA HUNT — Round 3 80x gap reverse-engineering")
    print("=" * 80)
    prices2, trades2 = load_day(2)
    print(f"\nDay 2 prices rows: {len(prices2)}, trades rows: {len(trades2)}")
    print(f"Day 2 timestamp range: {prices2['timestamp'].min()} .. {prices2['timestamp'].max()}")
    print(f"Day 2 unique timestamps: {prices2['timestamp'].nunique()}")
    print(f"Day 2 products: {prices2['product'].unique().tolist()}")

    total, q1_df = q1_theoretical_max(prices2, 2)
    q2_df = q2_multilevel(prices2, trades2)
    q3_df = q3_flow_imbalance(prices2, trades2)
    q4_df = q4_quote_prediction(prices2)
    q5_df = q5_cross_product_hedge(prices2)
    q6_timing(prices2, trades2)
    q7_hydrogel_ceiling(prices2, trades2)
    q8_df = q8_fill_rate(prices2, trades2)

    print("\n" + "=" * 80)
    print("SUMMARY: top alpha candidates")
    print("=" * 80)


if __name__ == "__main__":
    main()
