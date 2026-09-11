"""
R4 Counterparty Forensics — "Hello, I'm Mark"
=============================================
Mines per-Mark trading behavior across 3 days of R4 data.

Outputs:
  - Per-Mark universe / aggression / sizing
  - Per-Mark per-product profiles
  - Mark-to-market PnL using next-tick mid as exit
  - Forward-return predictive signals (10/100 tick horizons)
  - Olivia-analog hunt (extreme-day directional precedence)
  - Mark-to-Mark interaction matrix
  - Strategy recommendations (COPY / FADE / IGNORE) with thresholds + N

Run:
    python counterparty_mining.py
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------- I/O ---------------------------------------- #
ROOT = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4")
OUT_DIR = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/intel")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DAYS = [1, 2, 3]
PRODUCTS_LIM = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    **{f"VEV_{k}": 300 for k in range(4000, 6501, 250)},
}

# ----------------------------- Loaders ------------------------------------ #
def load_trades() -> pd.DataFrame:
    frames = []
    for d in DAYS:
        fp = ROOT / f"trades_round_4_day_{d}.csv"
        df = pd.read_csv(fp, sep=";")
        df["day"] = d
        frames.append(df)
    t = pd.concat(frames, ignore_index=True)
    t["price"] = t["price"].astype(float)
    t["quantity"] = t["quantity"].astype(int)
    return t

def load_prices() -> pd.DataFrame:
    frames = []
    for d in DAYS:
        fp = ROOT / f"prices_round_4_day_{d}.csv"
        df = pd.read_csv(fp, sep=";")
        if "day" not in df.columns:
            df["day"] = d
        frames.append(df)
    p = pd.concat(frames, ignore_index=True)
    p["mid_price"] = p["mid_price"].astype(float)
    return p[["day", "timestamp", "product", "mid_price"]].copy()

# --------------------------- Forward returns ------------------------------ #
def add_forward_mids(trades: pd.DataFrame, prices: pd.DataFrame, horizons=(10, 100, 500)) -> pd.DataFrame:
    """For each trade, attach next-tick mid + forward mids @ horizons (in ticks=timestamp/100)."""
    px = prices.set_index(["day", "product", "timestamp"]).sort_index()
    # mid grids per (day, product) for fast lookup via reindex / nearest
    out = trades.copy()
    out["mid_at_trade"] = np.nan
    out["mid_next"] = np.nan
    for h in horizons:
        out[f"mid_fwd_{h}"] = np.nan

    # build per-(day,product) Series of mid by timestamp for fast asof
    grouped_px = {key: g["mid_price"] for key, g in
                  prices.groupby(["day", "product"])}
    grouped_px_sorted = {k: v.reset_index().sort_values("timestamp")
                         for k, v in
                         {key: g.set_index("timestamp")["mid_price"] for key, g in prices.groupby(["day", "product"])}.items()}

    # Faster: dict[(day,product)] = dict[timestamp]=mid
    mid_lookup = {}
    for (d, prod), g in prices.groupby(["day", "product"]):
        s = g.set_index("timestamp")["mid_price"].sort_index()
        mid_lookup[(d, prod)] = s

    out = out.reset_index(drop=True)
    cols = {"mid_at_trade": [], "mid_next": []}
    for h in horizons:
        cols[f"mid_fwd_{h}"] = []

    for _, row in out.iterrows():
        key = (row["day"], row["symbol"])
        s = mid_lookup.get(key)
        if s is None or len(s) == 0:
            cols["mid_at_trade"].append(np.nan)
            cols["mid_next"].append(np.nan)
            for h in horizons:
                cols[f"mid_fwd_{h}"].append(np.nan)
            continue
        ts = row["timestamp"]
        # mid AT trade timestamp (asof <=)
        idx = s.index.searchsorted(ts, side="right") - 1
        cols["mid_at_trade"].append(s.iloc[idx] if idx >= 0 else np.nan)
        # next-tick mid (>= ts+100, picks first available)
        idx_next = s.index.searchsorted(ts + 100, side="left")
        cols["mid_next"].append(s.iloc[idx_next] if idx_next < len(s) else np.nan)
        for h in horizons:
            tgt = ts + h * 100
            idx_h = s.index.searchsorted(tgt, side="left")
            cols[f"mid_fwd_{h}"].append(s.iloc[idx_h] if idx_h < len(s) else np.nan)

    for c, v in cols.items():
        out[c] = v
    return out

# -------------------------- Universe summary ------------------------------ #
def universe_table(trades: pd.DataFrame) -> pd.DataFrame:
    marks = sorted(set(trades["buyer"]).union(trades["seller"]))
    rows = []
    for m in marks:
        b = trades[trades["buyer"] == m]
        s = trades[trades["seller"] == m]
        n_b, n_s = len(b), len(s)
        v_b = int(b["quantity"].sum()) if n_b else 0
        v_s = int(s["quantity"].sum()) if n_s else 0
        prods = sorted(set(b["symbol"]).union(s["symbol"]))
        rows.append(dict(
            mark=m,
            trades_total=n_b + n_s,
            trades_buy=n_b,
            trades_sell=n_s,
            buy_share=(n_b / (n_b + n_s)) if (n_b + n_s) else np.nan,
            volume_buy=v_b,
            volume_sell=v_s,
            volume_total=v_b + v_s,
            avg_size=(v_b + v_s) / max(1, n_b + n_s),
            n_products=len(prods),
            products=",".join(prods),
        ))
    return pd.DataFrame(rows).sort_values("trades_total", ascending=False)

# ------------------------ Per-Mark per-product ---------------------------- #
def per_mark_per_product(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    marks = sorted(set(trades["buyer"]).union(trades["seller"]))
    for m in marks:
        for prod, g_all in trades.groupby("symbol"):
            b = g_all[g_all["buyer"] == m]
            s = g_all[g_all["seller"] == m]
            if len(b) + len(s) == 0:
                continue
            rows.append(dict(
                mark=m,
                product=prod,
                trades=len(b) + len(s),
                trades_buy=len(b),
                trades_sell=len(s),
                buy_share=len(b) / (len(b) + len(s)),
                vol_buy=int(b["quantity"].sum()),
                vol_sell=int(s["quantity"].sum()),
                avg_qty=(b["quantity"].sum() + s["quantity"].sum()) / (len(b) + len(s)),
                ts_min=int(min(b["timestamp"].min() if len(b) else np.inf,
                                s["timestamp"].min() if len(s) else np.inf)),
                ts_max=int(max(b["timestamp"].max() if len(b) else -1,
                                s["timestamp"].max() if len(s) else -1)),
            ))
    return pd.DataFrame(rows)

# ------------------------------- PnL -------------------------------------- #
def pnl_marked_to_market(trades_fwd: pd.DataFrame) -> pd.DataFrame:
    """For each Mark, compute realized PnL using next-tick mid as exit price.
    Buy at price P, exit at mid_next   -> qty * (mid_next - P)
    Sell at price P, exit at mid_next  -> qty * (P - mid_next)

    Also compute fwd-100 / fwd-500 PnL.
    """
    rows = []
    marks = sorted(set(trades_fwd["buyer"]).union(trades_fwd["seller"]))
    for m in marks:
        rec = {"mark": m}
        as_buyer = trades_fwd[trades_fwd["buyer"] == m]
        as_seller = trades_fwd[trades_fwd["seller"] == m]
        for label, h in [("next", "mid_next"), ("h10", "mid_fwd_10"),
                         ("h100", "mid_fwd_100"), ("h500", "mid_fwd_500")]:
            valid_b = as_buyer.dropna(subset=[h])
            valid_s = as_seller.dropna(subset=[h])
            pnl_b = float(((valid_b[h] - valid_b["price"]) * valid_b["quantity"]).sum())
            pnl_s = float(((valid_s["price"] - valid_s[h]) * valid_s["quantity"]).sum())
            rec[f"pnl_{label}"] = pnl_b + pnl_s
            rec[f"n_{label}"] = len(valid_b) + len(valid_s)
        rec["volume"] = int(as_buyer["quantity"].sum() + as_seller["quantity"].sum())
        rec["pnl_per_vol_h100"] = rec["pnl_h100"] / max(1, rec["volume"])
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("pnl_h100", ascending=False)

# ----------------- Predictive: signed forward return ---------------------- #
def predictive_signals(trades_fwd: pd.DataFrame, horizons=(10, 100, 500), min_n=10) -> pd.DataFrame:
    """Per-Mark signed forward-return statistics.
    Sign: +1 if Mark was buyer, -1 if seller.
    Signed return = sign * (mid_fwd - mid_at_trade) — positive => price moved with Mark.
    """
    rows = []
    marks = sorted(set(trades_fwd["buyer"]).union(trades_fwd["seller"]))
    for m in marks:
        b = trades_fwd[trades_fwd["buyer"] == m].copy()
        s = trades_fwd[trades_fwd["seller"] == m].copy()
        b["sign"] = +1
        s["sign"] = -1
        df = pd.concat([b, s], ignore_index=True)
        rec = {"mark": m, "n": len(df), "vol": int(df["quantity"].sum())}
        for h in horizons:
            col = f"mid_fwd_{h}"
            d = df.dropna(subset=[col, "mid_at_trade"]).copy()
            if len(d) < min_n:
                rec[f"mean_ret_h{h}"] = np.nan
                rec[f"t_h{h}"] = np.nan
                rec[f"n_h{h}"] = len(d)
                continue
            ret = d["sign"] * (d[col] - d["mid_at_trade"])
            mu, sd = ret.mean(), ret.std(ddof=1)
            t = mu / (sd / np.sqrt(len(d))) if sd > 0 else np.nan
            rec[f"mean_ret_h{h}"] = mu
            rec[f"t_h{h}"] = t
            rec[f"n_h{h}"] = len(d)
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("mean_ret_h100", ascending=False)

# ------------------- Olivia analog: extreme-day filter -------------------- #
def olivia_hunt(trades_fwd: pd.DataFrame) -> pd.DataFrame:
    """Look for Marks whose trades cluster near extreme directional moves.
    For each (mark, product, day): correlation between trade-sign and total-day drift.
    Day 3 VFE crash is the canonical setup."""
    rows = []
    for (m, prod, day), g in trades_fwd.groupby(["buyer", "symbol", "day"]):
        sign = +1
        ret_h500 = (g["mid_fwd_500"] - g["mid_at_trade"]).dropna()
        if len(ret_h500) < 3:
            continue
        rows.append(dict(mark=m, product=prod, day=day, side="BUY",
                         n=len(g), vol=int(g["quantity"].sum()),
                         mean_ret_500=float((sign * ret_h500).mean())))
    for (m, prod, day), g in trades_fwd.groupby(["seller", "symbol", "day"]):
        sign = -1
        ret_h500 = (g["mid_fwd_500"] - g["mid_at_trade"]).dropna()
        if len(ret_h500) < 3:
            continue
        rows.append(dict(mark=m, product=prod, day=day, side="SELL",
                         n=len(g), vol=int(g["quantity"].sum()),
                         mean_ret_500=float((sign * ret_h500).mean())))
    return pd.DataFrame(rows).sort_values("mean_ret_500", ascending=False)

# ---------------------- Mark-to-Mark interaction -------------------------- #
def interaction_matrix(trades: pd.DataFrame) -> pd.DataFrame:
    pair = trades.groupby(["buyer", "seller"]).agg(
        trades=("quantity", "size"),
        volume=("quantity", "sum")).reset_index()
    return pair.sort_values("volume", ascending=False)

# ----------------------------- Helpers ------------------------------------ #
def fmt_df(df: pd.DataFrame, floats=2) -> str:
    return df.to_string(index=False, float_format=lambda x: f"{x:,.{floats}f}")

# ----------------------------- MAIN --------------------------------------- #
def main():
    print("[1/7] Loading trades...")
    trades = load_trades()
    print(f"      total trades = {len(trades):,}, marks = {len(set(trades['buyer'])|set(trades['seller']))}")

    print("[2/7] Loading prices...")
    prices = load_prices()

    print("[3/7] Computing forward mids per trade...")
    tf = add_forward_mids(trades, prices)
    miss_next = tf["mid_next"].isna().sum()
    print(f"      mid_next missing on {miss_next}/{len(tf)} trades")

    print("[4/7] Universe...")
    uni = universe_table(trades)
    uni.to_csv(OUT_DIR / "universe.csv", index=False)
    print(uni.to_string(index=False))

    print("[5/7] Per-Mark per-product profile...")
    pmpp = per_mark_per_product(trades)
    pmpp.to_csv(OUT_DIR / "per_mark_per_product.csv", index=False)

    print("[6/7] PnL (mark-to-market)...")
    pnl = pnl_marked_to_market(tf)
    pnl.to_csv(OUT_DIR / "pnl.csv", index=False)
    print(fmt_df(pnl))

    print("[7/7] Predictive signals + Olivia hunt + interactions...")
    pred = predictive_signals(tf)
    pred.to_csv(OUT_DIR / "predictive.csv", index=False)
    print(fmt_df(pred))

    olivia = olivia_hunt(tf)
    olivia.to_csv(OUT_DIR / "olivia_hunt.csv", index=False)

    inter = interaction_matrix(trades)
    inter.to_csv(OUT_DIR / "interaction_matrix.csv", index=False)
    print(fmt_df(inter.head(40)))

    # Per-product, per-mark PnL deep dive (for strategy thresholds)
    rows = []
    for m in sorted(set(trades["buyer"]).union(trades["seller"])):
        for prod in trades["symbol"].unique():
            sub = tf[(tf["symbol"] == prod) & ((tf["buyer"] == m) | (tf["seller"] == m))]
            if len(sub) == 0:
                continue
            sub = sub.copy()
            sub["sign"] = np.where(sub["buyer"] == m, 1, -1)
            d = sub.dropna(subset=["mid_fwd_100", "mid_at_trade"])
            if len(d) < 5:
                continue
            ret = d["sign"] * (d["mid_fwd_100"] - d["mid_at_trade"])
            rows.append(dict(
                mark=m, product=prod, n=len(d),
                vol=int(sub["quantity"].sum()),
                mean_ret_h100=float(ret.mean()),
                t_h100=float(ret.mean() / (ret.std(ddof=1) / np.sqrt(len(ret)))) if ret.std(ddof=1) > 0 else np.nan,
                buy_share=float((sub["sign"] == 1).mean()),
                avg_qty=float(sub["quantity"].mean()),
            ))
    per_prod_pred = pd.DataFrame(rows).sort_values(["product", "mean_ret_h100"], ascending=[True, False])
    per_prod_pred.to_csv(OUT_DIR / "per_mark_per_product_predictive.csv", index=False)

    # Day-3 VFE crash deep dive
    print("\n=== Day 3 VFE drift check ===")
    p3vfe = prices[(prices["day"] == 3) & (prices["product"] == "VELVETFRUIT_EXTRACT")]
    if len(p3vfe) > 0:
        print(f"  VFE day3 mid: open={p3vfe['mid_price'].iloc[0]:.1f}, close={p3vfe['mid_price'].iloc[-1]:.1f}, "
              f"min={p3vfe['mid_price'].min():.1f}, max={p3vfe['mid_price'].max():.1f}")

    # Per-mark per-day directional bias on VFE day 3
    d3vfe_rows = []
    for m in sorted(set(trades["buyer"]).union(trades["seller"])):
        sub = tf[(tf["day"] == 3) & (tf["symbol"] == "VELVETFRUIT_EXTRACT") &
                 ((tf["buyer"] == m) | (tf["seller"] == m))]
        if len(sub) == 0:
            continue
        sub = sub.copy()
        sub["sign"] = np.where(sub["buyer"] == m, 1, -1)
        d3vfe_rows.append(dict(
            mark=m, n=len(sub), vol=int(sub["quantity"].sum()),
            mean_sign=float(sub["sign"].mean()),  # +1 = pure buyer, -1 = pure seller
            net_qty=int((sub["sign"] * sub["quantity"]).sum()),
            ts_first=int(sub["timestamp"].min()),
            ts_last=int(sub["timestamp"].max()),
        ))
    d3vfe = pd.DataFrame(d3vfe_rows).sort_values("net_qty")
    d3vfe.to_csv(OUT_DIR / "day3_vfe_directional.csv", index=False)
    print("\n=== Day 3 VFE per-Mark net qty (most negative = sellers into crash) ===")
    print(fmt_df(d3vfe))

    # Save trades-with-fwd for inspection
    tf.to_csv(OUT_DIR / "trades_with_fwd.csv", index=False)

    print("\nAll outputs written to:", OUT_DIR)


if __name__ == "__main__":
    main()
