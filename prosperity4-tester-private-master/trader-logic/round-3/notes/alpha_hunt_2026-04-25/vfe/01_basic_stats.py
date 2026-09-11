"""VFE basic stats + drift detection across days 0/1/2."""
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_vfe(day):
    p = pd.read_csv(f"{ROOT}/prices_round_3_day_{day}.csv", sep=";")
    t = pd.read_csv(f"{ROOT}/trades_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    t = t[t["symbol"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    return p, t

print(f"{'Day':>4} {'Open':>8} {'Close':>8} {'Drift':>8} {'Trades':>7} {'BuyVol':>7} {'SellVol':>8} {'BuySkew':>8}")
for day in [0, 1, 2]:
    p, t = load_vfe(day)
    o, c = p.iloc[0]["mid_price"], p.iloc[-1]["mid_price"]
    # buyer = SUBMISSION → aggressive buy at ask; seller = SUBMISSION → aggressive sell at bid
    # In IMC trades CSV, both sides hidden bots. Use price vs prior mid to classify.
    p_idx = {ts: i for i, ts in enumerate(p["timestamp"].values)}
    mids = p["mid_price"].values
    buy_vol = sell_vol = 0
    for _, row in t.iterrows():
        ts = row["timestamp"]
        # Find price tick at or before ts
        i = p_idx.get(ts, None)
        if i is None or i == 0:
            continue
        prev_mid = mids[i-1] if i > 0 else mids[i]
        if row["price"] >= prev_mid:
            buy_vol += row["quantity"]
        else:
            sell_vol += row["quantity"]
    skew = buy_vol / max(buy_vol + sell_vol, 1)
    print(f"{day:>4} {o:>8.1f} {c:>8.1f} {c-o:>+8.1f} {len(t):>7} {buy_vol:>7} {sell_vol:>8} {skew:>8.3f}")

# Now early-window detection: at t=100, 500, 1000, 2000, what is mid drift vs end-of-day?
print("\n=== Early-window mid drift vs full-day drift ===")
print(f"{'Day':>4} {'D100':>8} {'D500':>8} {'D1k':>8} {'D2k':>8} {'D5k':>8} {'Dfull':>8}")
for day in [0, 1, 2]:
    p, _ = load_vfe(day)
    mid = p["mid_price"].values
    o = mid[0]
    print(f"{day:>4} {mid[100]-o:>+8.1f} {mid[500]-o:>+8.1f} {mid[1000]-o:>+8.1f} {mid[2000]-o:>+8.1f} {mid[5000]-o:>+8.1f} {mid[-1]-o:>+8.1f}")

# Buy skew over rolling windows
print("\n=== Buy skew in first N ticks (cumulative) ===")
print(f"{'Day':>4} {'BS@100':>8} {'BS@500':>8} {'BS@1k':>8} {'BS@2k':>8} {'BS@5k':>8} {'BS@full':>8}")
for day in [0, 1, 2]:
    p, t = load_vfe(day)
    mids = p["mid_price"].values
    p_ts = p["timestamp"].values
    # Build mid-at-or-before-ts index for trades
    t_sorted = t.sort_values("timestamp").reset_index(drop=True)
    bv = sv = 0
    out = {}
    targets = [100, 500, 1000, 2000, 5000, 9999]
    next_target = 0
    for _, row in t_sorted.iterrows():
        ts_idx = int(row["timestamp"] // 100)
        if ts_idx == 0:
            prev_mid = mids[0]
        else:
            prev_mid = mids[max(0, ts_idx-1)]
        if row["price"] >= prev_mid:
            bv += row["quantity"]
        else:
            sv += row["quantity"]
        while next_target < len(targets) and ts_idx >= targets[next_target]:
            tot = bv + sv
            out[targets[next_target]] = bv / max(tot, 1)
            next_target += 1
    while next_target < len(targets):
        out[targets[next_target]] = bv / max(bv + sv, 1)
        next_target += 1
    print(f"{day:>4} {out[100]:>8.3f} {out[500]:>8.3f} {out[1000]:>8.3f} {out[2000]:>8.3f} {out[5000]:>8.3f} {out[9999]:>8.3f}")
