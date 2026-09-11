"""
R4 Microstructure Alpha Analysis
=================================
1. OBI L1 -> forward 100-tick mid return
2. L3 volume-weighted microprice vs simple mid
3. VPIN trade-flow toxicity
4. HP spread-state HMM transition matrix
5. Output: ONE recommended signal for r4_final_v2

Data: prosperity4bt/resources/round4/{prices,trades}_round_4_day_{1,2,3}.csv
"""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
RES  = ROOT / "prosperity4bt/resources/round4"
DAYS = [1, 2, 3]
FWD  = 100  # ticks forward (= 10s)

def load_prices(day):
    df = pd.read_csv(RES / f"prices_round_4_day_{day}.csv", sep=";")
    df["day"] = day
    return df

def load_trades(day):
    df = pd.read_csv(RES / f"trades_round_4_day_{day}.csv", sep=";")
    df["day"] = day
    return df

def compute_obi(df):
    bv = df["bid_volume_1"].fillna(0)
    av = df["ask_volume_1"].fillna(0)
    tot = bv + av
    return np.where(tot > 0, (bv - av) / tot, 0.0)

def compute_microprice_l3(df):
    cols_b = [(f"bid_price_{i}", f"bid_volume_{i}") for i in [1,2,3]]
    cols_a = [(f"ask_price_{i}", f"ask_volume_{i}") for i in [1,2,3]]
    bid_pv = sum(df[p].fillna(0) * df[v].fillna(0) for p,v in cols_b)
    ask_pv = sum(df[p].fillna(0) * df[v].fillna(0) for p,v in cols_a)
    bid_v  = sum(df[v].fillna(0) for _,v in cols_b)
    ask_v  = sum(df[v].fillna(0) for _,v in cols_a)
    # Microprice: weight each side by OPPOSITE volume
    bid_avg = bid_pv / bid_v.replace(0, np.nan)
    ask_avg = ask_pv / ask_v.replace(0, np.nan)
    tot = bid_v + ask_v
    micro = (bid_avg * ask_v + ask_avg * bid_v) / tot.replace(0, np.nan)
    return micro

def fwd_return(group, fwd=FWD):
    mid = group["mid_price"].values
    out = np.full(len(mid), np.nan)
    if len(mid) > fwd:
        out[:-fwd] = mid[fwd:] - mid[:-fwd]
    return out

# ------------------------------------------------------------ load
prices = pd.concat([load_prices(d) for d in DAYS], ignore_index=True)
trades = pd.concat([load_trades(d) for d in DAYS], ignore_index=True)

prices = prices.sort_values(["product", "day", "timestamp"]).reset_index(drop=True)
prices["obi"]   = compute_obi(prices)
prices["micro"] = compute_microprice_l3(prices)

# forward return per product per day
prices["fwd_ret"] = (
    prices.groupby(["product", "day"], group_keys=False)
    .apply(lambda g: pd.Series(fwd_return(g), index=g.index))
)

# ------------------------------------------------------------ 1) OBI predictiveness
print("=" * 70)
print("[1] OBI L1 -> forward 100-tick mid return correlation")
print("=" * 70)
obi_summary = []
for prod, g in prices.groupby("product"):
    g2 = g.dropna(subset=["fwd_ret"])
    if len(g2) < 100:
        continue
    rho = g2[["obi", "fwd_ret"]].corr().iloc[0, 1]
    # bucket OBI extremes
    g2 = g2.assign(obi_bin=pd.qcut(g2["obi"], 10, duplicates="drop"))
    top  = g2[g2["obi"] >  0.5]["fwd_ret"].mean()
    bot  = g2[g2["obi"] < -0.5]["fwd_ret"].mean()
    obi_summary.append((prod, rho, top, bot, len(g2)))
obi_df = pd.DataFrame(obi_summary, columns=["product","corr","mean_ret_obi>0.5","mean_ret_obi<-0.5","N"])
obi_df = obi_df.sort_values("corr", key=abs, ascending=False)
print(obi_df.to_string(index=False))

# ------------------------------------------------------------ 2) microprice vs mid
print()
print("=" * 70)
print("[2] L3 microprice vs simple mid: forward-return correlation")
print("=" * 70)
prices["micro_dev"] = prices["micro"] - prices["mid_price"]
mp_summary = []
for prod, g in prices.groupby("product"):
    g2 = g.dropna(subset=["fwd_ret","micro_dev"])
    if len(g2) < 100:
        continue
    rho_mid_lag = g2[["mid_price","fwd_ret"]].corr().iloc[0,1]
    rho_micro   = g2[["micro_dev","fwd_ret"]].corr().iloc[0,1]
    mp_summary.append((prod, rho_micro, rho_mid_lag, g2["micro_dev"].std()))
mp_df = pd.DataFrame(mp_summary, columns=["product","corr_microdev_fwdret","corr_mid_fwdret","micro_dev_std"])
mp_df = mp_df.sort_values("corr_microdev_fwdret", key=abs, ascending=False)
print(mp_df.to_string(index=False))

# ------------------------------------------------------------ 3) VPIN
print()
print("=" * 70)
print("[3] VPIN trade flow toxicity (HP, VFE)")
print("=" * 70)
def vpin_for(symbol, n_buckets=50):
    t = trades[trades["symbol"] == symbol].copy()
    if len(t) == 0:
        return None
    # Use price change vs prior trade as buy/sell classifier (Lee-Ready proxy)
    t = t.sort_values(["day","timestamp"])
    t["dp"] = t.groupby("day")["price"].diff().fillna(0)
    t["buy_vol"]  = np.where(t["dp"] > 0, t["quantity"], np.where(t["dp"]==0, t["quantity"]/2, 0))
    t["sell_vol"] = np.where(t["dp"] < 0, t["quantity"], np.where(t["dp"]==0, t["quantity"]/2, 0))
    V = max(1, int(t["quantity"].sum() / n_buckets))
    cum = 0
    bucket = []
    bv = 0
    sv = 0
    for q, b, s in zip(t["quantity"], t["buy_vol"], t["sell_vol"]):
        cum += q
        bv += b
        sv += s
        if cum >= V:
            bucket.append(abs(bv-sv) / (bv+sv) if (bv+sv)>0 else 0)
            cum = 0; bv = 0; sv = 0
    if not bucket:
        return None
    arr = np.array(bucket)
    return {"symbol": symbol, "n_trades": len(t), "n_buckets": len(arr),
            "VPIN_mean": arr.mean(), "VPIN_p90": np.quantile(arr,0.9),
            "tot_volume": int(t["quantity"].sum())}
vpin_rows = []
for s in ["HYDROGEL_PACK","VELVETFRUIT_EXTRACT","VEV_5000","VEV_5200","VEV_5400","VEV_4000","VEV_4500","VEV_6500"]:
    r = vpin_for(s)
    if r: vpin_rows.append(r)
print(pd.DataFrame(vpin_rows).to_string(index=False))

# ------------------------------------------------------------ 4) HP spread state-machine
print()
print("=" * 70)
print("[4] HYDROGEL_PACK spread state transitions (1-step Markov)")
print("=" * 70)
hp = prices[prices["product"]=="HYDROGEL_PACK"].copy()
hp["spread"] = hp["ask_price_1"] - hp["bid_price_1"]
state_keys = sorted(hp["spread"].dropna().value_counts().index.tolist())
print("Spread frequencies:")
print(hp["spread"].value_counts().sort_index().to_string())
print("\nTransition matrix P(s_{t+1} | s_t):")
hp["sp_next"] = hp.groupby("day")["spread"].shift(-1)
trans = pd.crosstab(hp["spread"], hp["sp_next"], normalize="index").round(3)
print(trans.to_string())
# stationary: prob of S=17 followed by what? Look at 100-tick fwd return after S=17
hp["fwd100"] = hp.groupby("day")["mid_price"].shift(-100) - hp["mid_price"]
print("\nAfter spread=17, mean fwd_100 mid return:", hp.loc[hp["spread"]==17,"fwd100"].mean())
print("After spread=16, mean fwd_100 mid return:", hp.loc[hp["spread"]==16,"fwd100"].mean())
print("After spread=8/9, mean fwd_100 mid return:", hp.loc[hp["spread"].isin([8,9]),"fwd100"].mean())

# ------------------------------------------------------------ 5) Recommendation summary
print()
print("=" * 70)
print("[5] RECOMMENDATION shortlist")
print("=" * 70)
top_obi = obi_df.head(3)
print("Top-3 OBI products:")
print(top_obi.to_string(index=False))
top_micro = mp_df.head(3)
print("\nTop-3 microprice products:")
print(top_micro.to_string(index=False))
