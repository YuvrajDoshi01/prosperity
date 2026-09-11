"""H4: Taker imprint - do recent taker trades predict next move?
H7: Quote skip / mid jumps - persistence?
H9: Mean reversion levels - any anchor non-9990?
"""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_hp(day):
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    t = pd.read_csv(f"{BASE}/trades_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "HYDROGEL_PACK"].reset_index(drop=True)
    t = t[t["symbol"] == "HYDROGEL_PACK"].reset_index(drop=True)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    return p, t

# Tag each tick: does mid <= bid_prev (sell hit) or >= ask_prev (buy hit)?
print("=== H4: Taker imprint - aggregate signed volume in last K ticks vs fwd N ticks ===")
for day in [0,1,2]:
    p, t = load_hp(day)
    # build per-tick signed volume from trades CSV
    # trade.price > prev_mid -> taker bought (+); < prev_mid -> taker sold (-)
    p["mid_lag"] = p["mid_price"].shift(1)
    trade_signed = pd.DataFrame({"timestamp": t["timestamp"], "price": t["price"], "qty": t["quantity"]})
    # match trade.timestamp to prev mid
    mid_at = p.set_index("timestamp")["mid_lag"]
    trade_signed["prev_mid"] = trade_signed["timestamp"].map(mid_at)
    trade_signed["sign"] = np.where(trade_signed["price"] > trade_signed["prev_mid"], 1,
                                     np.where(trade_signed["price"] < trade_signed["prev_mid"], -1, 0))
    trade_signed["sv"] = trade_signed["sign"] * trade_signed["qty"]
    # roll up to per-timestamp signed volume
    sv_per_ts = trade_signed.groupby("timestamp")["sv"].sum()
    p["sv"] = p["timestamp"].map(sv_per_ts).fillna(0)
    # rolling sum
    for w in [5, 10, 20, 50]:
        p[f"sv_{w}"] = p["sv"].rolling(w).sum()
    p["fwd5"] = p["mid_price"].shift(-5) - p["mid_price"]
    p["fwd20"] = p["mid_price"].shift(-20) - p["mid_price"]
    print(f"--- DAY {day} ---")
    for w in [5, 10, 20, 50]:
        col = f"sv_{w}"
        # quintiles
        p[f"q_{w}"] = pd.qcut(p[col], q=5, labels=False, duplicates="drop")
        for q in range(5):
            mask = p[f"q_{w}"] == q
            if mask.sum() < 20: continue
            f5 = p.loc[mask, "fwd5"].mean()
            f20 = p.loc[mask, "fwd20"].mean()
            sv_avg = p.loc[mask, col].mean()
            if q in [0, 4]:
                print(f"  sv_{w} q{q} avg_sv={sv_avg:+6.1f} n={mask.sum():4d} fwd5={f5:+.3f} fwd20={f20:+.3f}")

# H7: mid jumps - persistence
print("\n=== H7: After mid jump > 5 (rare event), what's the next 5/20-tick move? ===")
for day in [0,1,2]:
    p, _ = load_hp(day)
    p["dmid"] = p["mid_price"].diff()
    p["fwd5"] = p["mid_price"].shift(-5) - p["mid_price"]
    p["fwd20"] = p["mid_price"].shift(-20) - p["mid_price"]
    up_jumps = p[p["dmid"] > 5]
    dn_jumps = p[p["dmid"] < -5]
    print(f"  Day {day}: up_jumps={len(up_jumps)} mean_fwd5={up_jumps['fwd5'].mean():+.2f} fwd20={up_jumps['fwd20'].mean():+.2f}")
    print(f"  Day {day}: dn_jumps={len(dn_jumps)} mean_fwd5={dn_jumps['fwd5'].mean():+.2f} fwd20={dn_jumps['fwd20'].mean():+.2f}")

# H9: mean-reversion anchor
print("\n=== H9: Mid quantile distribution + reversion test ===")
for day in [0,1,2]:
    p, _ = load_hp(day)
    print(f"  Day {day}: mid 5%={p['mid_price'].quantile(0.05):.0f} 25%={p['mid_price'].quantile(0.25):.0f} 50%={p['mid_price'].quantile(0.5):.0f} 75%={p['mid_price'].quantile(0.75):.0f} 95%={p['mid_price'].quantile(0.95):.0f}")
    # extremes
    p["fwd50"] = p["mid_price"].shift(-50) - p["mid_price"]
    p["fwd200"] = p["mid_price"].shift(-200) - p["mid_price"]
    for thr_lo, thr_hi, label in [(p["mid_price"].quantile(0.95), 99999, "top5%"),
                                    (-99999, p["mid_price"].quantile(0.05), "bot5%")]:
        m = p[(p["mid_price"] >= thr_lo) & (p["mid_price"] < thr_hi)] if label == "top5%" else p[(p["mid_price"] >= thr_lo) & (p["mid_price"] < thr_hi)]
        print(f"    {label}: n={len(m)} fwd50={m['fwd50'].mean():+.2f} fwd200={m['fwd200'].mean():+.2f}")
