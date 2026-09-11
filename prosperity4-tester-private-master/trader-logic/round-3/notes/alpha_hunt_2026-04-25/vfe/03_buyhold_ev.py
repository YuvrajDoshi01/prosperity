"""Quantify: if we hit +200 long at the open and hold until tick 1000, what is EV?
Then test: rolling buy_skew threshold to flip to long, vs buy-and-hold."""
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load_vfe(day):
    p = pd.read_csv(f"{ROOT}/prices_round_3_day_{day}.csv", sep=";")
    t = pd.read_csv(f"{ROOT}/trades_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    t = t[t["symbol"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    return p, t

print("=== Buy-and-hold +200 long EV (entry @ ask, exit @ mid at end) ===")
print("(realistic: buy from ask side over first ~100 ticks, then hold)")
print(f"{'Day':>4} {'Entry_ask':>10} {'Mid@1k':>10} {'Mid@end':>10} {'PnL_1k':>10} {'PnL_full':>10}")
for day in [0, 1, 2]:
    p, _ = load_vfe(day)
    ap1 = p["ask_price_1"].values
    mid = p["mid_price"].values
    # Estimate avg entry price = avg ask price over first ~30 ticks (if we sweep 200 in 30 ticks @ ~7vol/tick)
    entry = np.mean(ap1[:30])
    pnl_1k = (mid[1000] - entry) * 200
    pnl_full = (mid[-1] - entry) * 200
    print(f"{day:>4} {entry:>10.2f} {mid[1000]:>10.2f} {mid[-1]:>10.2f} {pnl_1k:>+10.1f} {pnl_full:>+10.1f}")

print("\n=== Greedy: continuous buy-skew rolling-window strategy ===")
# Strategy: maintain rolling 100-tick buy-vol/(buy+sell). If > 0.55, target pos=+200; if <0.45, target pos=-200; else target=0.
def simulate(day, window=100, long_thresh=0.55, short_thresh=0.45, edge=2):
    p, t = load_vfe(day)
    mid = p["mid_price"].values
    bp1 = p["bid_price_1"].values; ap1 = p["ask_price_1"].values
    timestamps = p["timestamp"].values
    # Bin trades by tick index
    buy_per_tick = np.zeros(len(mid))
    sell_per_tick = np.zeros(len(mid))
    for _, row in t.iterrows():
        ti = int(row["timestamp"] // 100)
        if ti >= len(mid): continue
        prev_mid = mid[max(0, ti-1)]
        if row["price"] >= prev_mid:
            buy_per_tick[ti] += row["quantity"]
        else:
            sell_per_tick[ti] += row["quantity"]
    cum_buy = pd.Series(buy_per_tick).rolling(window, min_periods=1).sum().values
    cum_sell = pd.Series(sell_per_tick).rolling(window, min_periods=1).sum().values
    skew = cum_buy / np.maximum(cum_buy + cum_sell, 1)

    pos = 0; cash = 0; LIMIT = 200
    for i in range(len(mid)-1):
        s = skew[i]
        if s > long_thresh: target = LIMIT
        elif s < short_thresh: target = -LIMIT
        else: target = 0
        diff = target - pos
        # Trade up to 20 per tick assuming MM bot supplies; pay edge
        trade_qty = max(-20, min(20, diff))
        if trade_qty > 0:
            cash -= trade_qty * (ap1[i])  # take ask
            pos += trade_qty
        elif trade_qty < 0:
            cash -= trade_qty * (bp1[i])  # +cash for sell at bid
            pos += trade_qty
    # Mark to mid at horizon=1k or full
    return cash, pos, mid

for day in [0, 1, 2]:
    cash, pos, mid = simulate(day)
    pnl_1k = cash + pos * mid[1000] if 1000 < len(mid) else cash + pos*mid[-1]
    pnl_full = cash + pos * mid[-1]
    print(f"Day {day}: pos@end={pos:>+5}, PnL@1k={pnl_1k:>+8.1f}, PnL@full={pnl_full:>+8.1f}")

# Per first 1k ticks only
print("\n=== Restricted to first 1k ticks (website BT window) ===")
def simulate_1k(day, window=50, long_thresh=0.55, short_thresh=0.45):
    p, t = load_vfe(day)
    mid = p["mid_price"].values[:1001]
    bp1 = p["bid_price_1"].values[:1001]; ap1 = p["ask_price_1"].values[:1001]
    buy_per_tick = np.zeros(len(mid))
    sell_per_tick = np.zeros(len(mid))
    for _, row in t.iterrows():
        ti = int(row["timestamp"] // 100)
        if ti >= len(mid): continue
        prev_mid = mid[max(0, ti-1)]
        if row["price"] >= prev_mid:
            buy_per_tick[ti] += row["quantity"]
        else:
            sell_per_tick[ti] += row["quantity"]
    cum_buy = pd.Series(buy_per_tick).rolling(window, min_periods=1).sum().values
    cum_sell = pd.Series(sell_per_tick).rolling(window, min_periods=1).sum().values
    skew = cum_buy / np.maximum(cum_buy + cum_sell, 1)

    pos = 0; cash = 0; LIMIT = 200
    fills = 0
    for i in range(len(mid)-1):
        s = skew[i]
        if s > long_thresh: target = LIMIT
        elif s < short_thresh: target = -LIMIT
        else: target = 0
        diff = target - pos
        trade_qty = max(-20, min(20, diff))
        if trade_qty > 0:
            cash -= trade_qty * ap1[i]; pos += trade_qty; fills += abs(trade_qty)
        elif trade_qty < 0:
            cash -= trade_qty * bp1[i]; pos += trade_qty; fills += abs(trade_qty)
    pnl = cash + pos * mid[-1]
    return pnl, pos, fills

for win in [30, 50, 100, 200]:
    print(f"--- window={win} ---")
    for day in [0, 1, 2]:
        pnl, pos, fills = simulate_1k(day, window=win)
        print(f"Day {day}: pnl={pnl:>+8.1f} pos={pos:>+5} fills={fills}")
