"""H9a deep dive: SHORT at mid>X. Test independence from spread=17 trigger."""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_hp(day, n=None):
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "HYDROGEL_PACK"].reset_index(drop=True)
    if n: p = p.head(n)
    p["spread"] = p["ask_price_1"] - p["bid_price_1"]
    return p

def realistic_short_pnl(p, entry_idx, hold, lot=200, exit_at_mid=True):
    """Enter SHORT at bid_price_1 (passive sell that hit) OR ask (cross).
    Exit: hold ticks later, BUY at ask (cross) OR mid."""
    valid = entry_idx[entry_idx + hold < len(p)]
    if len(valid) == 0: return 0, 0
    entry = p.loc[valid, "bid_price_1"].values  # passive sell at bid
    exit_px = p.loc[valid + hold, "mid_price"].values if exit_at_mid else p.loc[valid + hold, "ask_price_1"].values
    pnl_per_lot = entry - exit_px  # short: profit if exit_px < entry
    return pnl_per_lot.mean() * len(valid) * lot, len(valid)

# Map of mid threshold * hold for day 2 first 1k
print("=== Day 2 first 1k: SHORT 200 at MID THR, hold N ticks. EV in $. Entry=BID (passive), Exit=ASK (cross)===")
p = load_hp(2, 1000)
print(f"  spread=17 events in 1k: {(p['spread']==17).sum()} | mid>=10025 events: {(p['mid_price']>=10025).sum()} | mid>=10020 events: {(p['mid_price']>=10020).sum()}")
print(f"\n  THR  | hold5     | hold20    | hold50    | hold100   | hold200   | n_events")
for thr in [10015, 10020, 10025, 10030]:
    row = f"  {thr}|"
    n = (p["mid_price"]>=thr).sum()
    for hold in [5, 20, 50, 100, 200]:
        idx = p.index[p["mid_price"]>=thr]
        # Entry: SHORT at bid, exit: BUY at ask after hold
        valid = idx[idx + hold < len(p)]
        if len(valid)==0:
            row += f" n=0       |"; continue
        entry = p.loc[valid, "bid_price_1"].values
        exit_ask = p.loc[valid + hold, "ask_price_1"].values
        pnl = (entry - exit_ask).mean() * 200 * len(valid)
        row += f" ${pnl:+8.0f}|"
    row += f" {n}"
    print(row)

# Same for day 0 + 1 (cross-validation, full 10k)
print("\n=== Cross-day validation (full 10k each day) ===")
print(f"  THR  | day0 EV(hold100) | day1 EV(hold100) | day2 EV(hold100, full 10k) | day2 first 1k")
for thr in [10015, 10020, 10025, 10030]:
    row = f"  {thr}|"
    for d in [0, 1, 2]:
        p_full = load_hp(d)
        idx = p_full.index[p_full["mid_price"]>=thr]
        valid = idx[idx + 100 < len(p_full)]
        if len(valid)==0:
            row += f" n=0              |"; continue
        entry = p_full.loc[valid, "bid_price_1"].values
        exit_ask = p_full.loc[valid + 100, "ask_price_1"].values
        pnl = (entry - exit_ask).mean() * 200 * len(valid)
        row += f" ${pnl:+10.0f} (n={len(valid):4d})|"
    # Also day 2 first 1k
    p_1k = load_hp(2, 1000)
    idx = p_1k.index[p_1k["mid_price"]>=thr]
    valid = idx[idx + 100 < len(p_1k)]
    if len(valid)>0:
        entry = p_1k.loc[valid, "bid_price_1"].values
        exit_ask = p_1k.loc[valid + 100, "ask_price_1"].values
        pnl = (entry - exit_ask).mean() * 200 * len(valid)
        row += f" ${pnl:+8.0f} (n={len(valid):3d})"
    print(row)

# Single-position scenario: enter SHORT once at first mid>=THR, hold until mid<=EXIT_THR
print("\n=== Single-shot SHORT: enter at first mid>=THR, exit at mid<=EXIT_THR (Day 2 1k) ===")
p = load_hp(2, 1000)
for thr_in, thr_out in [(10025, 10005), (10020, 10000), (10015, 10000), (10025, 9998), (10020, 9998)]:
    above = p["mid_price"] >= thr_in
    if not above.any():
        print(f"  enter>={thr_in} exit<={thr_out}: no entries"); continue
    # State machine: in_pos? when first hit, when next hit thr_out
    pnl_total = 0
    pos = 0
    entry_px = 0
    n_trades = 0
    max_drawdown = 0
    cum_pnl_traj = []
    cur_pnl = 0
    for i, row in p.iterrows():
        if pos == 0 and row["mid_price"] >= thr_in:
            entry_px = row["bid_price_1"]  # passive short at bid
            pos = -200
            n_trades += 1
        elif pos < 0 and row["mid_price"] <= thr_out:
            exit_px = row["ask_price_1"]
            cur_pnl += (entry_px - exit_px) * 200
            pos = 0
        cum_pnl_traj.append(cur_pnl)
    # close at EOD
    if pos < 0:
        exit_px = p.iloc[-1]["mid_price"]
        cur_pnl += (entry_px - exit_px) * 200
    print(f"  enter>={thr_in} exit<={thr_out}: trades={n_trades} EV=${cur_pnl:+.0f}")
