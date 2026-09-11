"""H8: Bot identity flow - does counterparty trading VFE first then trade vouchers?
Also: which buyer/seller dominates each voucher and does their flow predict VFE moves?"""
import pickle, numpy as np, pandas as pd, os

OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"
with open(os.path.join(OUT, "data.pkl"), "rb") as f:
    D = pickle.load(f)

trades = D["trades"]; mids = D["mids"]

print("=== Counterparties per product (day 2, top 5 by qty) ===")
t2 = trades[2]
for sym in ["HYDROGEL_PACK","VELVETFRUIT_EXTRACT","VEV_4000","VEV_5000","VEV_5300"]:
    sub = t2[t2["symbol"]==sym]
    if len(sub)==0:
        print(f"  {sym}: 0 trades"); continue
    print(f"  {sym}: {len(sub)} trades")
    counts = pd.concat([sub["buyer"], sub["seller"]]).value_counts().head(5)
    print(f"    counterparties: {counts.to_dict()}")

# For each named bot, is their net flow in VFE correlated with future voucher flow / VFE price?
print("\n=== Per-counterparty net VFE flow vs short-term VFE return ===")
t2 = trades[2].copy()
vfe_t = t2[t2["symbol"]=="VELVETFRUIT_EXTRACT"].copy()
if len(vfe_t)>0:
    # signed qty: buyer's perspective +qty
    parties = pd.concat([vfe_t["buyer"], vfe_t["seller"]]).value_counts()
    print(f"  Total parties in VFE day2: {parties.to_dict()}")

# Cross-symbol: do specific buyers in VFE then become buyers in vouchers within next 100 ticks?
print("\n=== Counterparty repeated across symbols within 50 ticks day 2 ===")
t2_sorted = t2.sort_values("timestamp")
cross_count = 0
for _, row in t2_sorted.iterrows():
    if row["symbol"] != "VELVETFRUIT_EXTRACT": continue
    ts = row["timestamp"]; buyer = row["buyer"]
    later = t2_sorted[(t2_sorted["timestamp"]>ts) & (t2_sorted["timestamp"]<=ts+5000)
                      & (t2_sorted["symbol"].str.startswith("VEV_"))
                      & (t2_sorted["buyer"]==buyer)]
    cross_count += len(later)
print(f"  VFE buyer reappears as buyer in voucher within 5000ms: {cross_count} matches")

# Restrict to 1k window (timestamp <= 99900)
print("\n=== Same in 1k-tick window day 2 ===")
t2_1k = t2_sorted[t2_sorted["timestamp"]<=99900]
print(f"  Total trades 1k: {len(t2_1k)} | by symbol: {t2_1k['symbol'].value_counts().to_dict()}")
counterparts_1k = pd.concat([t2_1k["buyer"], t2_1k["seller"]]).value_counts()
print(f"  Top counterparties: {counterparts_1k.head(10).to_dict()}")

# Net flow signal: HP buyer ID is informed?
print("\n=== HP buyer-side net flow as signal for HP next-100-tick return ===")
t2_hp = t2[t2["symbol"]=="HYDROGEL_PACK"].copy()
if len(t2_hp)>0:
    # compute net buy-sell qty per buyer
    buys = t2_hp.groupby("buyer")["quantity"].sum()
    sells = t2_hp.groupby("seller")["quantity"].sum()
    nets = (buys.reindex(buys.index.union(sells.index)).fillna(0)
            - sells.reindex(buys.index.union(sells.index)).fillna(0))
    print(f"  HP net flow per counterparty (day 2 full): {nets.sort_values().to_dict()}")
