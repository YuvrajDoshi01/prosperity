"""Passive MM with spread-state aware skew.

Engine reality (from R0 lessons):
- We post inside bp1+1, ap1-1. Bot's MM doesn't move.
- External takers hit ALL price-priority levels — so they hit OUR inside post first if they cross.
- 'Invisible takers' are also bot quote moves; when bot moves bp1 up, prior bp1 level is gone.

Strategy:
- Default: post 50@bp1+1 buy, 50@ap1-1 sell, with cap at LIMIT=200.
- If spread=2 with ap1 dropped (predictive +1.4 next tick): SKIP sell side, post 50 BUY at bp1+1 only,
  and ALSO place +1@ap1+0 cross to grab inventory cheaply (since ap1 is about to move up).
- If spread=3 with ap1 raised (predictive -1.2): SKIP buy, post 50 SELL at ap1-1.
- Signal-based take: at spread=2/ap_dn fire 1 unit cross.

Key: in this CSV simulator, we approximate fills via taker volumes.
"""
import pandas as pd
import numpy as np

ROOT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

def load(day):
    p = pd.read_csv(f"{ROOT}/prices_round_3_day_{day}.csv", sep=";")
    t = pd.read_csv(f"{ROOT}/trades_round_3_day_{day}.csv", sep=";")
    p = p[p["product"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    t = t[t["symbol"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    return p, t

def simulate(day, ticks=1000, qty_skew=20, edge=1, take_qty=20):
    p, t = load(day)
    mid = p["mid_price"].values
    bp1 = p["bid_price_1"].values; ap1 = p["ask_price_1"].values
    bv1 = p["bid_volume_1"].fillna(0).values; av1 = p["ask_volume_1"].fillna(0).values
    spread = ap1 - bp1
    bp_diff = np.diff(bp1, prepend=bp1[0])
    ap_diff = np.diff(ap1, prepend=ap1[0])

    # Bin trades
    n = len(mid)
    buy_at_ask = np.zeros(n); sell_at_bid = np.zeros(n)
    for _, row in t.iterrows():
        ti = int(row["timestamp"] // 100)
        if ti >= n: continue
        if row["price"] >= ap1[ti]: buy_at_ask[ti] += row["quantity"]
        elif row["price"] <= bp1[ti]: sell_at_bid[ti] += row["quantity"]

    pos, cash = 0, 0.0; LIMIT = 200
    nticks = min(ticks, n-1)
    for i in range(nticks):
        # Detect spread regime
        bull = (spread[i] == 2 and ap_diff[i] < 0)
        bear = (spread[i] == 3 and ap_diff[i] > 0)
        # Aggressive take on signal
        if bull and pos < LIMIT - take_qty:
            cash -= take_qty * ap1[i]; pos += take_qty
        elif bear and pos > -LIMIT + take_qty:
            cash += take_qty * bp1[i]; pos -= take_qty
        # Passive MM
        if spread[i] >= 2:
            post_bid = not bear
            post_ask = not bull
            my_bp = bp1[i] + edge; my_ap = ap1[i] - edge
            if my_bp >= my_ap:
                continue
            if post_ask and pos > -LIMIT:
                q = min(int(buy_at_ask[i]), qty_skew, LIMIT + pos)
                if q > 0:
                    cash += q * my_ap; pos -= q
            if post_bid and pos < LIMIT:
                q = min(int(sell_at_bid[i]), qty_skew, LIMIT - pos)
                if q > 0:
                    cash -= q * my_bp; pos += q
    pnl = cash + pos * mid[nticks]
    return pnl, pos

print("=== Spread-state-aware PASSIVE MM (signal-skewed) ===")
print(f"{'edge':>5} {'qty':>5} {'take':>5} {'PnL_d0':>10} {'PnL_d1':>10} {'PnL_d2':>10} {'Sum':>10}")
for edge in [1]:
    for qty in [20, 50]:
        for take in [0, 5, 10, 20]:
            results = []
            for day in [0, 1, 2]:
                pnl, _ = simulate(day, ticks=1000, qty_skew=qty, edge=edge, take_qty=take)
                results.append(pnl)
            print(f"{edge:>5} {qty:>5} {take:>5} {results[0]:>+10.1f} {results[1]:>+10.1f} {results[2]:>+10.1f} {sum(results):>+10.1f}")

# Same simulator but base = current v11-equivalent: penny-MM both sides default
print("\n=== Baseline (no skew) for comparison ===")
def baseline(day, ticks=1000, qty=20, edge=1):
    p, t = load(day)
    mid = p["mid_price"].values
    bp1 = p["bid_price_1"].values; ap1 = p["ask_price_1"].values
    spread = ap1 - bp1
    n = len(mid)
    buy_at_ask = np.zeros(n); sell_at_bid = np.zeros(n)
    for _, row in t.iterrows():
        ti = int(row["timestamp"] // 100)
        if ti >= n: continue
        if row["price"] >= ap1[ti]: buy_at_ask[ti] += row["quantity"]
        elif row["price"] <= bp1[ti]: sell_at_bid[ti] += row["quantity"]
    pos, cash = 0, 0.0; LIMIT = 200
    for i in range(min(ticks, n-1)):
        if spread[i] < 2: continue
        my_bp = bp1[i] + edge; my_ap = ap1[i] - edge
        if pos > -LIMIT:
            q = min(int(buy_at_ask[i]), qty, LIMIT + pos)
            if q: cash += q * my_ap; pos -= q
        if pos < LIMIT:
            q = min(int(sell_at_bid[i]), qty, LIMIT - pos)
            if q: cash -= q * my_bp; pos += q
    return cash + pos * mid[min(ticks, n-1)], pos

for day in [0, 1, 2]:
    pnl, pos = baseline(day, qty=20, edge=1)
    print(f"Day {day}: pnl={pnl:>+8.1f} pos={pos:>+5}")

# Try also: when bull, lift ap1 (cross spread). Does cost structure work out?
print("\n=== Attribution: spread-state take alone (no MM) ===")
def take_only(day, ticks=1000, take_qty=20):
    p, _ = load(day)
    mid = p["mid_price"].values
    bp1 = p["bid_price_1"].values; ap1 = p["ask_price_1"].values
    spread = ap1 - bp1
    bp_diff = np.diff(bp1, prepend=bp1[0])
    ap_diff = np.diff(ap1, prepend=ap1[0])
    pos, cash = 0, 0.0; LIMIT = 200
    n = min(ticks, len(mid)-1)
    for i in range(n):
        bull = (spread[i] == 2 and ap_diff[i] < 0)
        bear = (spread[i] == 3 and ap_diff[i] > 0)
        if bull:
            q = min(take_qty, LIMIT - pos)
            if q > 0: cash -= q*ap1[i]; pos += q
        elif bear:
            q = min(take_qty, LIMIT + pos)
            if q > 0: cash += q*bp1[i]; pos -= q
        # Decay positions toward 0 (close at next mid)
        # Naive: hold for k=1 tick then unwind at mid (NOT realistic — must cross)
    return cash + pos * mid[n], pos

for take in [10, 20, 50]:
    results = []
    for day in [0, 1, 2]:
        pnl, pos = take_only(day, take_qty=take)
        results.append((pnl, pos))
    print(f"take={take}: " + " ".join(f"d{d}=pnl{r[0]:+.1f}/pos{r[1]:+}" for d, r in enumerate(results)))
