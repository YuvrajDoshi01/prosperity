"""counterparty_refined.py — REFINED Mark XX counterparty analysis for R4.

Goes beyond intel/counterparty_mining.md:
  - Per-(Mark, product) deep profile w/ horizons {1,2,5,10,50,100}
  - Tick-level microstructure t-stats (h=1,2,5)
  - Time-of-day clustering (open/mid/close)
  - Mark 67/49 inter-arrival distribution
  - Adverse-selection probe: post-Mark-67-trade NEXT-tick mid move

Run:  cd <repo> && PYTHONPATH=prosperity4bt python trader-logic/round-4/intel/counterparty_refined.py
"""
import os, sys, math
from collections import defaultdict
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RES  = os.path.join(ROOT, "prosperity4bt", "resources", "round4")

def load():
    pr, tr = [], []
    for d in (1, 2, 3):
        p = pd.read_csv(os.path.join(RES, f"prices_round_4_day_{d}.csv"), sep=";")
        t = pd.read_csv(os.path.join(RES, f"trades_round_4_day_{d}.csv"), sep=";")
        p["day"] = d; t["day"] = d
        pr.append(p); tr.append(t)
    return pd.concat(pr, ignore_index=True), pd.concat(tr, ignore_index=True)

def mids_by_product(prices):
    """Return {(day, symbol): pd.Series indexed by timestamp -> mid}."""
    out = {}
    for (d, s), g in prices.groupby(["day", "product"]):
        g = g.sort_values("timestamp")
        mid = (g["bid_price_1"] + g["ask_price_1"]) / 2.0
        out[(d, s)] = pd.Series(mid.values, index=g["timestamp"].values)
    return out

def fwd_mid(mids, day, sym, ts, h_ticks):
    """Mid at ts + h_ticks*100 ms; nearest-fwd lookup."""
    s = mids.get((day, sym))
    if s is None: return np.nan
    target = ts + h_ticks * 100
    idx = s.index.searchsorted(target)
    if idx >= len(s): idx = len(s) - 1
    return s.iloc[idx]

def trade_dir(buyer, seller):
    """Sign of trade from Mark's perspective. +1 if Mark is buyer, -1 if Mark is seller."""
    return None  # placeholder; assigned per Mark below

def main():
    print("Loading round 4 data...")
    prices, trades = load()
    mids = mids_by_product(prices)
    print(f"Trades: {len(trades):,}  |  Products: {trades['symbol'].nunique()}  |  Days: {trades['day'].nunique()}")

    MARKS = ["Mark 01","Mark 14","Mark 22","Mark 38","Mark 49","Mark 55","Mark 67"]
    HORIZONS = [1, 2, 5, 10, 50, 100]

    # ---- 1. Per-(Mark, product) horizon profile ----
    print("\n=== 1. Per-(Mark, product) horizon profile (≥10 trades only) ===")
    rows = []
    for mark in MARKS:
        sub = trades[(trades["buyer"] == mark) | (trades["seller"] == mark)]
        for sym, g in sub.groupby("symbol"):
            if len(g) < 10: continue
            sign = np.where(g["buyer"] == mark, 1.0, -1.0)
            entry_mid = []
            for _, t in g.iterrows():
                s = mids.get((t["day"], sym))
                if s is None: entry_mid.append(np.nan); continue
                idx = s.index.searchsorted(t["timestamp"])
                if idx >= len(s): idx = len(s) - 1
                entry_mid.append(s.iloc[idx])
            entry_mid = np.array(entry_mid)
            for h in HORIZONS:
                fwds = np.array([fwd_mid(mids, t["day"], sym, t["timestamp"], h) for _, t in g.iterrows()])
                ret  = sign * (fwds - entry_mid)
                ret = ret[~np.isnan(ret)]
                if len(ret) < 10: continue
                mean = ret.mean()
                std  = ret.std(ddof=1) if len(ret) > 1 else 0.0
                t_stat = mean / (std / math.sqrt(len(ret))) if std > 0 else 0.0
                wr = (ret > 0).mean()
                rows.append({"mark": mark, "symbol": sym, "h": h, "n": len(ret),
                              "mean_ret": mean, "t_stat": t_stat, "win_rate": wr,
                              "avg_qty": g["quantity"].mean()})
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(os.path.dirname(__file__), "refined_per_mark_product_horizon.csv"), index=False)
    # Show survivors of |t|>2.69 (Bonferroni 7-mark)
    survivors = df[(df["t_stat"].abs() > 2.69) & (df["n"] >= 30)].sort_values("t_stat", ascending=False)
    print(f"\nBonferroni survivors (|t|>2.69, n>=30):")
    print(survivors.to_string(index=False))

    # ---- 2. Tick-level (h=1,2,5) microstructure ----
    print("\n=== 2. Microstructure short-horizon t-stats ===")
    micro = df[(df["h"].isin([1,2,5])) & (df["n"] >= 30)].sort_values(["h","t_stat"], ascending=[True, False])
    print(micro.head(20).to_string(index=False))

    # ---- 3. Time-of-day clustering ----
    print("\n=== 3. Time-of-day clustering for Mark 67 / 49 / 38 ===")
    # Bins: open [0,250k), mid [250k,750k), close [750k,1M)
    def bin_t(ts):
        if ts < 250_000: return "open"
        if ts < 750_000: return "mid"
        return "close"
    for mark in ["Mark 67","Mark 49","Mark 38"]:
        sub = trades[(trades["buyer"] == mark) | (trades["seller"] == mark)].copy()
        sub["bucket"] = sub["timestamp"].apply(bin_t)
        cnt = sub.groupby(["bucket","symbol"]).size().unstack(fill_value=0)
        print(f"\n{mark} trades by bucket × symbol:")
        print(cnt)

    # ---- 4. Inter-arrival for Mark 67 / 49 ----
    print("\n=== 4. Mark 67 / 49 inter-arrival distribution (VFE) ===")
    for mark in ["Mark 67", "Mark 49"]:
        sub = trades[((trades["buyer"] == mark) | (trades["seller"] == mark)) &
                     (trades["symbol"] == "VELVETFRUIT_EXTRACT")]
        for d in (1,2,3):
            sd = sub[sub["day"] == d].sort_values("timestamp")
            if len(sd) < 5: continue
            iat = np.diff(sd["timestamp"].values) / 100  # in ticks
            print(f"  {mark} day{d} n={len(sd):3d}  iat ticks: mean={iat.mean():.1f}  med={np.median(iat):.1f}  p25={np.percentile(iat,25):.0f}  p75={np.percentile(iat,75):.0f}")

    # ---- 5. ADVERSE-SELECTION probe: when Mark X trades on product P, what does mid do in next 1-5 ticks? ----
    print("\n=== 5. Adverse-selection: next-1-tick UNSIGNED mid move after Mark trades ===")
    # Diff: do Mark trades pre-shock the mid? Magnitude of next-tick |Δmid|.
    rows = []
    for mark in MARKS:
        for sym in ["HYDROGEL_PACK","VELVETFRUIT_EXTRACT","VEV_4000","VEV_5000","VEV_5100","VEV_5200"]:
            sub = trades[((trades["buyer"] == mark) | (trades["seller"] == mark)) &
                         (trades["symbol"] == sym)]
            if len(sub) < 30: continue
            moves_h1 = []
            for _, t in sub.iterrows():
                m0 = fwd_mid(mids, t["day"], sym, t["timestamp"], 0)
                m1 = fwd_mid(mids, t["day"], sym, t["timestamp"], 1)
                if not (np.isnan(m0) or np.isnan(m1)):
                    moves_h1.append(abs(m1 - m0))
            if not moves_h1: continue
            rows.append({"mark": mark, "symbol": sym, "n": len(moves_h1),
                          "abs_dmid_h1": np.mean(moves_h1)})
    asd = pd.DataFrame(rows).sort_values("abs_dmid_h1", ascending=False)
    print(asd.head(15).to_string(index=False))

    # ---- 6. Mark 67 buy-clustering (defensive: when does he RAID inside spread vs join?) ----
    print("\n=== 6. Mark 67 trade aggression (price - mid_at_trade) by quantity bucket ===")
    sub = trades[(trades["buyer"] == "Mark 67") & (trades["symbol"] == "VELVETFRUIT_EXTRACT")].copy()
    sub["mid"] = [fwd_mid(mids, t["day"], "VELVETFRUIT_EXTRACT", t["timestamp"], 0) for _, t in sub.iterrows()]
    sub["agg"] = sub["price"] - sub["mid"]
    sub["qty_bin"] = pd.cut(sub["quantity"], bins=[0,3,6,9,12,16], labels=["1-3","4-6","7-9","10-12","13-15"])
    print(sub.groupby("qty_bin", observed=False).agg(
        n=("price","size"), mean_agg=("agg","mean"), med_agg=("agg","median"),
        avg_qty=("quantity","mean")
    ))

    # ---- 7. Defensive layer: would CANCELLING our HP/VFE quotes after Mark trades save us? ----
    # For each Mark trade event on HP/VFE, measure UNSIGNED 5-tick |Δmid|.
    print("\n=== 7. 5-tick UNSIGNED |Δmid| post-Mark-trade (cancel-window justification) ===")
    rows = []
    for mark in MARKS:
        for sym in ["HYDROGEL_PACK","VELVETFRUIT_EXTRACT"]:
            sub = trades[((trades["buyer"] == mark) | (trades["seller"] == mark)) &
                         (trades["symbol"] == sym)]
            if len(sub) < 30: continue
            sm5 = []
            for _, t in sub.iterrows():
                m0 = fwd_mid(mids, t["day"], sym, t["timestamp"], 0)
                m5 = fwd_mid(mids, t["day"], sym, t["timestamp"], 5)
                if not (np.isnan(m0) or np.isnan(m5)):
                    sm5.append(abs(m5 - m0))
            if not sm5: continue
            # Compare to baseline: random ts, same sym
            mids_ser = mids.get((sub.iloc[0]["day"], sym))
            base = []
            for d in sub["day"].unique():
                ms = mids.get((d, sym))
                if ms is None: continue
                vals = ms.values
                for i in range(0, len(vals)-5, 5):
                    base.append(abs(vals[i+5] - vals[i]))
            base_mean = np.mean(base) if base else np.nan
            rows.append({"mark": mark, "symbol": sym, "n": len(sm5),
                          "abs_dmid_h5_after_trade": np.mean(sm5),
                          "abs_dmid_h5_baseline": base_mean,
                          "lift": np.mean(sm5) / base_mean if base_mean else np.nan})
    asd2 = pd.DataFrame(rows).sort_values("lift", ascending=False)
    print(asd2.to_string(index=False))

    print("\nSaved CSVs to intel/. Done.")

if __name__ == "__main__":
    main()
